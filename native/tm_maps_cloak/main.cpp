// tm_maps_cloak（Zygisk 版）：让目标 App 读自己 /proc/self/maps 时看不到模拟器痕迹。
//
// 为什么是 Zygisk 版：Android 12 这台镜像的 zygote **不读 `wrap.` 属性**
// （实测 App 环境变量里没有 LD_PRELOAD），所以 LD_PRELOAD 那条路走不通；
// 而这里的 Magisk Kitsune + Zygisk 是**可用**的（zygote 已注入）。
//
// 做法（最小面）：在 App 进程里装一个 **seccomp 过滤器**，只拦 `openat`，
// 用 `SECCOMP_RET_USER_NOTIF` 把请求交给本进程的监督线程；命中
// /proc/self/maps 时用"过滤后的内容"（memfd）应答，其它一律
// `SECCOMP_USER_NOTIF_FLAG_CONTINUE` 放行。
// 好处：连直读 syscall 的 SDK 也拦得住，且不需要 hook 任何函数。
#define _GNU_SOURCE
#include <android/log.h>
#include <errno.h>
#include <fcntl.h>
#include <jni.h>
#include <linux/audit.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <pthread.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/uio.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <unistd.h>

#include <string>

#include "proc_broker.hpp"
#include "zygisk.hpp"

#define TAG "tm_maps_cloak"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, TAG, __VA_ARGS__)
#define LOGW(...) __android_log_print(ANDROID_LOG_WARN, TAG, __VA_ARGS__)

// 作用域（编译期；只对这几个包生效）
static const char *kScope[] = {
    "com.taobao.trip",
};

static int g_listener = -1;
static volatile int g_listener_ready = 0;
static pthread_mutex_t g_mx = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t g_cv = PTHREAD_COND_INITIALIZER;
static volatile bool g_installed = false;

static bool in_scope(const std::string &pkg) {
    for (const char *p : kScope) {
        if (pkg == p) return true;
    }
    return false;
}

// ── 安装 seccomp 过滤器（只拦 openat）──────────────────────────────────────
static int install_filter(void) {
    struct sock_filter filter[] = {
        // [0] 载入 syscall 号
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS,
                 (uint32_t) offsetof(struct seccomp_data, nr)),
        // [1] 命中 openat → USER_NOTIF
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, (uint32_t) __NR_openat, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_USER_NOTIF),
        // 其它一律放行
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
    };
    struct sock_fprog prog = {
        .len = (unsigned short) (sizeof(filter) / sizeof(filter[0])),
        .filter = filter,
    };
    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0) {
        LOGW("PR_SET_NO_NEW_PRIVS 失败: %s", strerror(errno));
        return -1;
    }
    int fd = (int) syscall(SYS_seccomp, SECCOMP_SET_MODE_FILTER,
                           SECCOMP_FILTER_FLAG_NEW_LISTENER, &prog);
    if (fd < 0) {
        LOGW("seccomp(NEW_LISTENER) 失败: %s", strerror(errno));
        return -1;
    }
    return fd;
}


// 安全读对端（本进程）内存里的字符串
static bool read_remote_string(pid_t pid, uint64_t addr, char *buf, size_t size) {
    if (addr == 0 || buf == nullptr || size < 2) return false;
    struct iovec local { buf, size - 1 };
    struct iovec remote { (void *) (uintptr_t) addr, size - 1 };
    const ssize_t n = process_vm_readv(pid, &local, 1, &remote, 1, 0);
    if (n <= 0) return false;
    buf[n] = '\0';
    return true;
}

// 判断这次 openat 是不是在读"自己的 maps"
static bool is_maps_openat(const struct seccomp_notif &req) {
    if (req.data.nr != (int) __NR_openat) return false;
    const int dirfd = (int) req.data.args[0];
    if (dirfd != AT_FDCWD) return false;
    char path[256];
    if (!read_remote_string((pid_t) req.pid, (uint64_t) req.data.args[1],
                            path, sizeof(path))) {
        return false;
    }
    if (strcmp(path, "/proc/self/maps") == 0) return true;
    char self[64];
    snprintf(self, sizeof(self), "/proc/%d/maps", (int) req.pid);
    return strcmp(path, self) == 0;
}

// ── 监督线程：接通知 → 交给 broker → 应答 ─────────────────────────────────
static void *supervisor(void *arg) {
    (void) arg;
    // 等主线程装好过滤器并把 listener 交过来
    pthread_mutex_lock(&g_mx);
    while (!g_listener_ready) pthread_cond_wait(&g_cv, &g_mx);
    const int listener = g_listener;
    pthread_mutex_unlock(&g_mx);
    LOGI("supervisor 启动（listener=%d，本线程无过滤器）", listener);

    // 通知结构大小（内核 >=5.0 才有这个命令；失败就退回默认结构）
    size_t notif_size = sizeof(struct seccomp_notif);
    size_t resp_size = sizeof(struct seccomp_notif_resp);
    struct seccomp_notif_sizes sizes {};
    if (syscall(SYS_seccomp, SECCOMP_GET_NOTIF_SIZES, 0, &sizes) == 0) {
        notif_size = sizes.seccomp_notif;
        resp_size = sizes.seccomp_notif_resp;
    }
    struct seccomp_notif *req =
        (struct seccomp_notif *) calloc(1, notif_size);
    struct seccomp_notif_resp *resp =
        (struct seccomp_notif_resp *) calloc(1, resp_size);
    if (req == nullptr || resp == nullptr) {
        LOGW("分配通知缓冲失败");
        return nullptr;
    }

    for (;;) {
        memset(req, 0, notif_size);
        if (ioctl(listener, SECCOMP_IOCTL_NOTIF_RECV, req) != 0) {
            if (errno == EINTR) continue;
            LOGW("NOTIF_RECV 失败（errno=%d），监督线程退出", errno);
            break;
        }
        memset(resp, 0, resp_size);
        if (!is_maps_openat(*req)) {
            // 只洗 maps；其它 openat 一律放行，绝不干预 App 正常启动
            resp->flags = SECCOMP_USER_NOTIF_FLAG_CONTINUE;
            resp->val = 0;
            resp->error = 0;
            ioctl(listener, SECCOMP_IOCTL_NOTIF_SEND, resp);
            continue;
        }
        const int handled = handle_proc_notification(*req, *resp, listener);
        if (handled == 2) {
            continue;                       // 已用 ADDFD 原子应答
        }
        if (handled == 1) {
            ioctl(listener, SECCOMP_IOCTL_NOTIF_SEND, resp);
            continue;
        }
        // 兜底：放行
        resp->flags = SECCOMP_USER_NOTIF_FLAG_CONTINUE;
        resp->val = 0;
        resp->error = 0;
        ioctl(listener, SECCOMP_IOCTL_NOTIF_SEND, resp);
    }
    free(req);
    free(resp);
    return nullptr;
}

class MapsCloak : public zygisk::ModuleBase {
public:
    void onLoad(zygisk::Api *api, JNIEnv *env) override {
        api_ = api;
        env_ = env;
    }

    void preAppSpecialize(zygisk::AppSpecializeArgs *args) override {
        std::string pkg;
        if (args != nullptr && args->nice_name != nullptr) {
            const char *c = env_->GetStringUTFChars(args->nice_name, nullptr);
            if (c != nullptr) {
                pkg = c;
                env_->ReleaseStringUTFChars(args->nice_name, c);
            }
        }
        if (!in_scope(pkg)) return;
        if (g_installed) return;

        // 关键顺序：**先**起监督线程（它不继承过滤器），**再**装过滤器
        pthread_t th;
        if (pthread_create(&th, nullptr, supervisor, nullptr) != 0) {
            LOGW("监督线程创建失败，跳过 maps 洗白（pkg=%s）", pkg.c_str());
            return;
        }
        pthread_detach(th);

        const int fd = install_filter();
        if (fd < 0) {
            LOGW("过滤器安装失败，本进程不做 maps 洗白（pkg=%s）", pkg.c_str());
            return;
        }
        g_installed = true;
        LOGI("已安装 maps 洗白过滤器 pkg=%s pid=%d", pkg.c_str(), getpid());
        pthread_mutex_lock(&g_mx);
        g_listener = fd;
        g_listener_ready = 1;
        pthread_cond_signal(&g_cv);
        pthread_mutex_unlock(&g_mx);
    }

private:
    zygisk::Api *api_ = nullptr;
    JNIEnv *env_ = nullptr;
};

REGISTER_ZYGISK_MODULE(MapsCloak)
