// maps_cloak（精简版）：只做两件事，面越窄越稳。
//
//   1) App 读自己的 /proc/self/maps 时，返回**过滤后**的内容（去掉 houdini/nemu 等痕迹）；
//   2) App 探测 root 常见路径（su/magisk/ksud/busybox//data/adb）时，返回"不存在"。
//
// 教训（本轮真实踩坑，写下来免得重犯）：
//   * 在插桩函数里调 `dlsym`/`dlopen` 会经由 malloc/属性读取再回到自己 → **无限递归**；
//   * `thread_local` 会走 `__emutls_get_address`（它自己 malloc）→ 同样递归；
//   * 插桩 `syscall` 和 `stat` 家族收益小、风险大（`app_process64` 直接
//     "trying to execute non-executable memory"）。
//   ⇒ 所以：**只在构造函数里解析一次真函数**，热路径零分配、零 dlopen；
//     只插 open/openat/fopen 三个符号。
#define _GNU_SOURCE
#include <dlfcn.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/system_properties.h>
#include <pthread.h>
#include <unistd.h>

#include <android/log.h>

#define TAG "maps_cloak"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, TAG, __VA_ARGS__)

typedef int (*open_fn)(const char *, int, ...);
typedef int (*openat_fn)(int, const char *, int, ...);
typedef FILE *(*fopen_fn)(const char *, const char *);

static open_fn g_open;
static open_fn g_open64;
static openat_fn g_openat;
static openat_fn g_openat64;
static fopen_fn g_fopen;
static fopen_fn g_fopen64;

// 编译期配置（App 读不到 /data/adb，所以内置；可用属性 tm.maps_cloak=off 一键关）
static const char *kMarkers[] = {"houdini", "nemu", "mumu", "netease"};
static const char *kRootPaths[] = {
    "/system/bin/su", "/system/xbin/su", "/system_ext/bin/su", "/sbin/su",
    "/su/bin/su", "/system/bin/magisk", "/system/xbin/magisk",
    "/system/bin/ksud", "/system_ext/bin/ksud",
    "/system/bin/busybox", "/system/xbin/busybox",
    "/data/adb", "/debug_ramdisk", "/sbin/.magisk",
};

// 内联系统调用：热路径兜底，不经过 libc
static inline long raw_syscall6(long n, long a1, long a2, long a3, long a4,
                                long a5, long a6) {
#if defined(__x86_64__)
    long ret;
    register long r10 __asm__("r10") = a4;
    register long r8 __asm__("r8") = a5;
    register long r9 __asm__("r9") = a6;
    __asm__ volatile("syscall"
                     : "=a"(ret)
                     : "a"(n), "D"(a1), "S"(a2), "d"(a3), "r"(r10), "r"(r8),
                       "r"(r9)
                     : "rcx", "r11", "memory");
    return ret;
#elif defined(__aarch64__)
    register long x8 __asm__("x8") = n;
    register long x0 __asm__("x0") = a1;
    register long x1 __asm__("x1") = a2;
    register long x2 __asm__("x2") = a3;
    register long x3 __asm__("x3") = a4;
    register long x4 __asm__("x4") = a5;
    register long x5 __asm__("x5") = a6;
    __asm__ volatile("svc #0"
                     : "+r"(x0)
                     : "r"(x8), "r"(x1), "r"(x2), "r"(x3), "r"(x4), "r"(x5)
                     : "memory");
    return x0;
#else
    (void) n; (void) a1; (void) a2; (void) a3; (void) a4; (void) a5; (void) a6;
    return -1;
#endif
}

static void resolve_once(void) {
    if (g_open != nullptr) return;
    void *h = dlopen("libc.so", RTLD_NOW);
    if (h == nullptr) return;
    g_open = (open_fn) dlsym(h, "open");
    g_open64 = (open_fn) dlsym(h, "open64");
    g_openat = (openat_fn) dlsym(h, "openat");
    g_openat64 = (openat_fn) dlsym(h, "openat64");
    g_fopen = (fopen_fn) dlsym(h, "fopen");
    g_fopen64 = (fopen_fn) dlsym(h, "fopen64");
}

static int is_off(void) {
    char v[PROP_VALUE_MAX] = {0};
    // 用 raw syscall 读属性不安全，这里只在构造函数里读一次（见 on_load）
    return v[0] == 'X';
}

static int g_enabled = 1;

static bool is_own_maps(const char *p) {
    if (p == nullptr) return false;
    if (strcmp(p, "/proc/self/maps") == 0) return true;
    if (strncmp(p, "/proc/", 6) == 0) {
        const char *q = p + 6;
        long pid = 0;
        while (*q >= '0' && *q <= '9') pid = pid * 10 + (*q++ - '0');
        return strcmp(q, "/maps") == 0 && pid == (long) getpid();
    }
    return false;
}

static bool is_root_path(const char *p) {
    if (p == nullptr) return false;
    for (const char *r : kRootPaths) {
        size_t n = strlen(r);
        if (strncmp(p, r, n) == 0 && (p[n] == '\0' || p[n] == '/')) return true;
    }
    return false;
}

static bool has_marker(const char *line, size_t len) {
    for (const char *m : kMarkers) {
        const size_t ml = strlen(m);
        if (len < ml) continue;
        for (size_t i = 0; i + ml <= len; i++) {
            if (memcmp(line + i, m, ml) == 0) return true;
        }
    }
    return false;
}

// 生成"过滤后的 maps"到 memfd（全程只用 raw_syscall / 已有 fd，零 malloc）
static int build_filtered_maps(void) {
    long fd = raw_syscall6(SYS_memfd_create, (long) "maps_cloak", 0, 0, 0, 0, 0);
    if (fd < 0) return -1;
    long in = raw_syscall6(SYS_openat, AT_FDCWD, (long) "/proc/self/maps",
                           O_RDONLY | O_CLOEXEC, 0, 0, 0);
    if (in < 0) {
        raw_syscall6(SYS_close, fd, 0, 0, 0, 0, 0);
        return -1;
    }
    char buf[8192];
    char line[2048];
    size_t ll = 0;
    long n;
    while ((n = raw_syscall6(SYS_read, in, (long) buf, sizeof(buf), 0, 0, 0))
           > 0) {
        for (long i = 0; i < n; i++) {
            if (ll < sizeof(line) - 1) line[ll++] = buf[i];
            if (buf[i] == '\n') {
                if (!has_marker(line, ll)) {
                    raw_syscall6(SYS_write, fd, (long) line, ll, 0, 0, 0);
                }
                ll = 0;
            }
        }
    }
    if (ll > 0 && !has_marker(line, ll)) {
        raw_syscall6(SYS_write, fd, (long) line, ll, 0, 0, 0);
    }
    raw_syscall6(SYS_close, in, 0, 0, 0, 0, 0);
    raw_syscall6(SYS_lseek, fd, 0, SEEK_SET, 0, 0, 0);
    return (int) fd;
}

static int open_common(const char *path, int flags, mode_t mode, int is_at,
                       int dirfd, open_fn real, int is64) {
    if (g_enabled) {
        if (is_own_maps(path)) {
            int fd = build_filtered_maps();
            if (fd >= 0) return fd;
        }
        if (!is_at && is_root_path(path)) {
            return (int) raw_syscall6(SYS_openat, AT_FDCWD, (long) path,
                                      flags, mode, 0, 0);
        }
        if (is_at && dirfd == AT_FDCWD && is_root_path(path)) {
            return (int) raw_syscall6(SYS_openat, AT_FDCWD, (long) path,
                                      flags, mode, 0, 0);
        }
    }
    (void) is64;
    return is_at ? ((openat_fn) real)(dirfd, path, flags, mode)
                 : real(path, flags, mode);
}

extern "C" int open(const char *path, int flags, ...) {
    mode_t mode = 0;
    if (flags & (O_CREAT | O_TMPFILE)) {
        va_list ap;
        va_start(ap, flags);
        mode = (mode_t) va_arg(ap, int);
        va_end(ap);
    }
    return open_common(path, flags, mode, 0, AT_FDCWD, g_open, 0);
}

extern "C" int open64(const char *path, int flags, ...) {
    mode_t mode = 0;
    if (flags & (O_CREAT | O_TMPFILE)) {
        va_list ap;
        va_start(ap, flags);
        mode = (mode_t) va_arg(ap, int);
        va_end(ap);
    }
    return open_common(path, flags, mode, 0, AT_FDCWD, g_open64, 1);
}

extern "C" int openat(int dirfd, const char *path, int flags, ...) {
    mode_t mode = 0;
    if (flags & (O_CREAT | O_TMPFILE)) {
        va_list ap;
        va_start(ap, flags);
        mode = (mode_t) va_arg(ap, int);
        va_end(ap);
    }
    return open_common(path, flags, mode, 1, dirfd, (open_fn) g_openat, 0);
}

extern "C" int openat64(int dirfd, const char *path, int flags, ...) {
    mode_t mode = 0;
    if (flags & (O_CREAT | O_TMPFILE)) {
        va_list ap;
        va_start(ap, flags);
        mode = (mode_t) va_arg(ap, int);
        va_end(ap);
    }
    return open_common(path, flags, mode, 1, dirfd, (open_fn) g_openat64, 1);
}

extern "C" FILE *fopen(const char *path, const char *mode) {
    if (g_enabled && mode != nullptr && mode[0] == 'r' && is_own_maps(path)) {
        int fd = build_filtered_maps();
        if (fd >= 0) {
            FILE *f = fdopen(fd, "r");
            if (f != nullptr) return f;
            raw_syscall6(SYS_close, fd, 0, 0, 0, 0, 0);
        }
    }
    return g_fopen(path, mode);
}

extern "C" FILE *fopen64(const char *path, const char *mode) {
    if (g_enabled && mode != nullptr && mode[0] == 'r' && is_own_maps(path)) {
        int fd = build_filtered_maps();
        if (fd >= 0) {
            FILE *f = fdopen(fd, "r");
            if (f != nullptr) return f;
            raw_syscall6(SYS_close, fd, 0, 0, 0, 0, 0);
        }
    }
    return g_fopen64(path, mode);
}


// ── 诊断自检（默认关；setprop tm.maps_cloak.diag 1 打开）───────────────────
static void diag_self_view(void) {
    FILE *f = fopen("/proc/self/maps", "r");     // 故意走**我们自己的** fopen
    if (f == nullptr) {
        LOGI("self-view: open failed");
        return;
    }
    const size_t n = sizeof(kMarkers) / sizeof(kMarkers[0]);
    int counts[8] = {0};
    char line[1024];
    int total = 0;
    while (fgets(line, sizeof(line), f) != nullptr) {
        total++;
        for (size_t i = 0; i < n && i < 8; i++) {
            if (strstr(line, kMarkers[i]) != nullptr) counts[i]++;
        }
    }
    fclose(f);
    char sum[384] = {0};
    size_t off = 0;
    for (size_t i = 0; i < n && i < 8; i++) {
        int w = snprintf(sum + off, sizeof(sum) - off, "%s=%d ",
                         kMarkers[i], counts[i]);
        if (w > 0) off += (size_t) w;
    }
    LOGI("self-view: lines=%d %s", total, sum);
}

static void *diag_thread(void *) {
    sleep(8);
    diag_self_view();
    sleep(8);
    diag_self_view();
    return nullptr;
}

__attribute__((constructor)) static void on_load(void) {
    resolve_once();
    char v[PROP_VALUE_MAX] = {0};
    if (__system_property_get("tm.maps_cloak", v) > 0 &&
        (strcmp(v, "off") == 0 || strcmp(v, "0") == 0)) {
        g_enabled = 0;
    }
    LOGI("maps_cloak 就绪 pid=%d enabled=%d open=%p", getpid(), g_enabled,
         (void *) g_open);
    char d[PROP_VALUE_MAX] = {0};
    if (__system_property_get("tm.maps_cloak.diag", d) > 0 &&
        (strcmp(d, "1") == 0 || strcmp(d, "on") == 0)) {
        pthread_t th;
        if (pthread_create(&th, nullptr, diag_thread, nullptr) == 0) {
            pthread_detach(th);
        }
    }
}
