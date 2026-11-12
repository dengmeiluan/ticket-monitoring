// maps_cloak：让目标 App 读自己 /proc/self/maps 时看不到模拟器痕迹。
//
// 注入方式：`setprop wrap.<pkg> "LD_PRELOAD=/data/local/tmp/libmaps_cloak.so"`
// （本机 Android 15 镜像自带 native-bridge 是 v2、系统要 v3，Zygisk 全灭，
//  所以不走 Zygisk；wrap+LD_PRELOAD 已实测主/子进程全部命中。）
//
// 原理：LD_PRELOAD 的同名符号优先于 libc —— 我们直接**符号插桩** open/openat/
// fopen/syscall，命中 maps 路径时把"过滤后的内容"写成 memfd 再交回调用者。
// App 的执行完全不受影响（libhoudini 照旧在跑，只是它不出现在 maps 文本里）。
//
// 与设计文档的偏差（已记录）：入口从 Zygisk 换成 constructor；配置编译进 .so
// （App 读不到 /data/adb）。
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <android/log.h>
#include <dlfcn.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/system_properties.h>
#include <sys/syscall.h>
#include <pthread.h>
#include <unistd.h>

#include <string>
#include <vector>

#define TAG "maps_cloak"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, TAG, __VA_ARGS__)
#define LOGV(...) __android_log_print(ANDROID_LOG_VERBOSE, TAG, __VA_ARGS__)

// ── 编译期配置（运行期用属性微调，见 config_prop）────────────────────────────
static const char *kMarkers[] = {"houdini", "nemu", "mumu", "netease"};
static const char *kConfProp = "tm.maps_cloak";   // "on" / "off"



// ── 对 App 撒谎的属性表（真机取值为准）──────────────────────────────────────
struct SpoofProp { const char *key; const char *value; };
static const SpoofProp kSpoofProps[] = {
    {"ro.dalvik.vm.native.bridge", ""},
    {"ro.product.cpu.abilist", "arm64-v8a,armeabi-v7a,armeabi"},
    {"ro.product.cpu.abilist64", "arm64-v8a"},
    {"ro.product.cpu.abilist32", "armeabi-v7a,armeabi"},
    {"ro.kernel.qemu", ""},
    {"ro.boot.qemu", ""},
    {"ro.hardware.egl", ""},
};

// ── 只在 access/stat/readlink 上隐藏（open 必须放行，否则 ARM 库加载会坏）──
static const char *kEmuStatPaths[] = {
    "/system/lib64/libhoudini.so", "/system/lib/libhoudini.so",
    "/system/bin/houdini", "/system/bin/houdini64",
    "/system/lib/arm", "/system/lib64/arm64", "/system/lib/arm64",
    "/system/lib/libnemu", "/system/lib64/libnemu",
    "/system/etc/cpuinfo.arm64.txt", "/system/etc/cpuinfo.x86_64.txt",
};

// ── root 痕迹隐藏表（App 里常见的 su/magisk 探测点）────────────────────────
static const char *kRootPaths[] = {
    "/system/bin/su", "/system/xbin/su", "/system_ext/bin/su", "/sbin/su",
    "/su/bin/su", "/system/bin/magisk", "/system/xbin/magisk",
    "/system/bin/ksud", "/system_ext/bin/ksud", "/system/bin/busybox",
    "/system/xbin/busybox", "/data/adb", "/data/adb/magisk", "/data/adb/ksu",
    "/debug_ramdisk", "/sbin/.magisk",
};

// ── 真实函数（RTLD_NEXT 拿到调用者之后的实现）────────────────────────────────
typedef int (*open_fn)(const char *, int, ...);
typedef int (*openat_fn)(int, const char *, int, ...);
typedef FILE *(*fopen_fn)(const char *, const char *);
typedef long (*syscall_fn)(long, ...);


// 内联汇编直接发系统调用：热路径兜底用，绝不经过 libc（否则会递归）
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
    return -1;
#endif
}

static open_fn real_open;
static open_fn real_open64;
static openat_fn real_openat;
static openat_fn real_openat64;
static fopen_fn real_fopen;
static fopen_fn real_fopen64;
static syscall_fn real_syscall;
typedef int (*access_fn)(const char *, int);
typedef int (*stat_fn)(const char *, struct stat *);
typedef ssize_t (*readlink_fn)(const char *, char *, size_t);
static access_fn real_access;
static stat_fn real_stat;
static stat_fn real_lstat;
static stat_fn real_stat64;
static stat_fn real_lstat64;
static readlink_fn real_readlink;
typedef int (*prop_get_fn)(const char *, char *);
static prop_get_fn real_prop_get;


// 从 libc.so 句柄取真函数：避免 RTLD_NEXT 解析到自己的同名符号（会导致无限递归）
static void *load_from_libc(const char *name) {
    void *h = dlopen("libc.so", RTLD_NOW | RTLD_NOLOAD);
    if (h == nullptr) h = dlopen("libc.so", RTLD_NOW);
    if (h == nullptr) return nullptr;
    return dlsym(h, name);
}

static void resolve_real() {
    if (real_open) return;
    real_open = (open_fn) load_from_libc("open");
    real_open64 = (open_fn) load_from_libc("open64");
    real_openat = (openat_fn) load_from_libc("openat");
    real_openat64 = (openat_fn) load_from_libc("openat64");
    real_fopen = (fopen_fn) load_from_libc("fopen");
    real_fopen64 = (fopen_fn) load_from_libc("fopen64");
    real_syscall = (syscall_fn) load_from_libc("syscall");
    if (!real_open) real_open = open;
    if (!real_open64) real_open64 = real_open;
    if (!real_openat) real_openat = openat;
    if (!real_openat64) real_openat64 = real_openat;
    if (!real_fopen) real_fopen = fopen;
    if (!real_fopen64) real_fopen64 = real_fopen;
    if (!real_syscall) real_syscall = syscall;
    real_access = (access_fn) load_from_libc("access");
    real_stat = (stat_fn) load_from_libc("stat");
    real_lstat = (stat_fn) load_from_libc("lstat");
    real_stat64 = (stat_fn) load_from_libc("stat64");
    real_lstat64 = (stat_fn) load_from_libc("lstat64");
    real_readlink = (readlink_fn) load_from_libc("readlink");
    if (!real_access) real_access = access;
    if (!real_stat) real_stat = stat;
    if (!real_lstat) real_lstat = lstat;
    if (!real_stat64) real_stat64 = real_stat;
    if (!real_lstat64) real_lstat64 = real_lstat;
    if (!real_readlink) real_readlink = readlink;
    real_prop_get = (prop_get_fn) load_from_libc("__system_property_get");
    if (!real_prop_get) real_prop_get = (prop_get_fn) dlsym(
        RTLD_NEXT, "__system_property_get");
}

static bool enabled() {
    // 运行期开关：`setprop tm.maps_cloak off` 可一键关掉（不用卸载）
    char v[PROP_VALUE_MAX] = {0};
    int n = __system_property_get(kConfProp, v);
    if (n > 0 && (strcmp(v, "off") == 0 || strcmp(v, "0") == 0)) return false;
    return true;
}

// ── 路径判定：是不是"本进程自己的 maps"──────────────────────────────────────


static bool is_emu_stat_path(const char *path) {
    if (path == nullptr) return false;
    for (const char *p : kEmuStatPaths) {
        const size_t n = strlen(p);
        if (strncmp(path, p, n) == 0 && (path[n] == '\0' || path[n] == '/'))
            return true;
    }
    return false;
}

// 属性查询：命中欺骗表就返回假值
static bool spoof_prop(const char *name, std::string *out) {
    if (name == nullptr) return false;
    for (const SpoofProp &p : kSpoofProps) {
        if (strcmp(name, p.key) == 0) {
            *out = p.value;
            return true;
        }
    }
    return false;
}

static bool is_root_path(const char *path) {
    if (path == nullptr) return false;
    for (const char *p : kRootPaths) {
        const size_t n = strlen(p);
        if (strncmp(path, p, n) == 0) {
            // 精确匹配，或是其子路径
            if (path[n] == '\0' || path[n] == '/') return true;
        }
    }
    return false;
}

static bool is_own_maps(const char *path) {
    if (path == nullptr) return false;
    if (strcmp(path, "/proc/self/maps") == 0) return true;
    if (strncmp(path, "/proc/", 6) == 0) {
        const char *p = path + 6;
        char *end = nullptr;
        long pid = strtol(p, &end, 10);
        if (end && strcmp(end, "/maps") == 0 && pid == (long) getpid()) return true;
    }
    return false;
}

static bool has_marker(const std::string &line) {
    for (const char *m : kMarkers) {
        if (line.find(m) != std::string::npos) return true;
    }
    return false;
}

// ── 生成过滤后的 memfd ──────────────────────────────────────────────────────
static int build_filtered_maps() {
    int fd = -1;
#ifdef SYS_memfd_create
    fd = (int) raw_syscall6(SYS_memfd_create, (long) "maps_cloak", 0, 0, 0, 0, 0);
#endif
    if (fd < 0) return -1;

    // 注意：读真实 maps 必须用 RTLD_NEXT 的 open，否则自己套自己
    int in = real_open("/proc/self/maps", O_RDONLY | O_CLOEXEC);
    if (in < 0) {
        raw_syscall6(SYS_close, fd, 0, 0, 0, 0, 0);
        return -1;
    }
    char buf[8192];
    std::string chunk;
    std::string out;
    out.reserve(256 * 1024);
    ssize_t n;
    int dropped = 0;
    while ((n = read(in, buf, sizeof(buf))) > 0) {
        chunk.append(buf, (size_t) n);
        size_t pos;
        while ((pos = chunk.find('\n')) != std::string::npos) {
            std::string line = chunk.substr(0, pos + 1);
            chunk.erase(0, pos + 1);
            if (has_marker(line)) {
                dropped++;
                continue;
            }
            out.append(line);
        }
    }
    if (!chunk.empty() && !has_marker(chunk)) out.append(chunk);
    close(in);

    const char *p = out.data();
    size_t left = out.size();
    while (left > 0) {
        ssize_t w = write(fd, p, left);
        if (w <= 0) break;
        p += w;
        left -= (size_t) w;
    }
    lseek(fd, 0, SEEK_SET);
    LOGV("maps served: dropped=%d kept=%zu bytes", dropped, out.size());
    return fd;
}

static int serve_maps(int flags) {
    int fd = build_filtered_maps();
    if (fd < 0) return -1;
    // 只读语义对 maps 足够；调用者若要求 O_WRONLY 之类，退回真实文件
    if ((flags & O_ACCMODE) != O_RDONLY) {
        raw_syscall6(SYS_close, fd, 0, 0, 0, 0, 0);
        return -1;
    }
    return fd;
}

// ── 插桩：open / openat / fopen / syscall ──────────────────────────────────
extern "C" int open(const char *path, int flags, ...) {
    mode_t mode = 0;
    if (flags & (O_CREAT | O_TMPFILE)) {
        va_list ap;
        va_start(ap, flags);
        mode = (mode_t) va_arg(ap, int);
        va_end(ap);
    }
    if (enabled() && is_own_maps(path)) {
        int fd = serve_maps(flags);
        if (fd >= 0) return fd;
    }
    if (enabled() && is_root_path(path)) {
        errno = ENOENT;          // 对 App 来说这些文件"不存在"
        return -1;
    }
    return real_open(path, flags, mode);
}

extern "C" int open64(const char *path, int flags, ...) {
    mode_t mode = 0;
    if (flags & (O_CREAT | O_TMPFILE)) {
        va_list ap;
        va_start(ap, flags);
        mode = (mode_t) va_arg(ap, int);
        va_end(ap);
    }
    if (enabled() && is_own_maps(path)) {
        int fd = serve_maps(flags);
        if (fd >= 0) return fd;
    }
    return real_open64(path, flags, mode);
}

extern "C" int openat(int dirfd, const char *path, int flags, ...) {
    mode_t mode = 0;
    if (flags & (O_CREAT | O_TMPFILE)) {
        va_list ap;
        va_start(ap, flags);
        mode = (mode_t) va_arg(ap, int);
        va_end(ap);
    }
    // AT_FDCWD 时才可能是绝对路径；其它 dirfd 交给真实实现
    if (enabled() && (dirfd == AT_FDCWD) && is_own_maps(path)) {
        int fd = serve_maps(flags);
        if (fd >= 0) return fd;
    }
    if (enabled() && (dirfd == AT_FDCWD) && is_root_path(path)) {
        errno = ENOENT;
        return -1;
    }
    return real_openat(dirfd, path, flags, mode);
}

extern "C" int openat64(int dirfd, const char *path, int flags, ...) {
    mode_t mode = 0;
    if (flags & (O_CREAT | O_TMPFILE)) {
        va_list ap;
        va_start(ap, flags);
        mode = (mode_t) va_arg(ap, int);
        va_end(ap);
    }
    if (enabled() && (dirfd == AT_FDCWD) && is_own_maps(path)) {
        int fd = serve_maps(flags);
        if (fd >= 0) return fd;
    }
    return real_openat64(dirfd, path, flags, mode);
}

extern "C" FILE *fopen(const char *path, const char *mode) {
    if (enabled() && mode && mode[0] == 'r' && is_own_maps(path)) {
        int fd = serve_maps(O_RDONLY);
        if (fd >= 0) {
            FILE *f = fdopen(fd, "r");
            if (f) return f;
            raw_syscall6(SYS_close, fd, 0, 0, 0, 0, 0);
        }
    }
    return real_fopen(path, mode);
}

extern "C" FILE *fopen64(const char *path, const char *mode) {
    if (enabled() && mode && mode[0] == 'r' && is_own_maps(path)) {
        int fd = serve_maps(O_RDONLY);
        if (fd >= 0) {
            FILE *f = fdopen(fd, "r");
            if (f) return f;
            raw_syscall6(SYS_close, fd, 0, 0, 0, 0, 0);
        }
    }
    return real_fopen64(path, mode);
}

// 有些 SDK 直接走 syscall(SYS_openat, ...) 读 maps，这里也兜住
extern "C" long syscall(long number, ...) {
    va_list ap;
    va_start(ap, number);
    long a1 = va_arg(ap, long);
    long a2 = va_arg(ap, long);
    long a3 = va_arg(ap, long);
    long a4 = va_arg(ap, long);
    long a5 = va_arg(ap, long);
    long a6 = va_arg(ap, long);
    va_end(ap);

#ifdef SYS_openat
    if (enabled() && number == SYS_openat) {
        const char *path = (const char *) a2;
        if (is_own_maps(path)) {
            int fd = serve_maps((int) a3);
            if (fd >= 0) return fd;
        }
    }
#endif
#ifdef SYS_open
    if (enabled() && number == SYS_open) {
        const char *path = (const char *) a1;
        if (is_own_maps(path)) {
            int fd = serve_maps((int) a2);
            if (fd >= 0) return fd;
        }
    }
#endif
    if (real_syscall != nullptr) {
        return real_syscall(number, a1, a2, a3, a4, a5, a6);
    }
    return raw_syscall6(number, a1, a2, a3, a4, a5, a6);
}

// 自检：由本进程读自己的 maps，统计标记词次数。
// root 在外部读 /proc/<pid>/maps 不经过插桩，所以验收必须由 App 自己读。
static void log_self_view() {
    FILE *f = fopen("/proc/self/maps", "r");
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
    char summary[512] = {0};
    size_t off = 0;
    for (size_t i = 0; i < n && i < 8; i++) {
        int w = snprintf(summary + off, sizeof(summary) - off, "%s=%d ",
                         kMarkers[i], counts[i]);
        if (w > 0) off += (size_t) w;
    }
    LOGI("self-view: lines=%d %s", total, summary);
}

static void log_self_view();
static void root_probe();
static void prop_probe();
static bool diag_on();
static bool prop_spoof_on();

// 延迟自检：在 App 完全加载后（15s / 30s）再读一次，代表风控 SDK 真正取样时的视角。
static void *delayed_self_view(void *) {
    sleep(15);
    log_self_view();
    root_probe();
    prop_probe();
    sleep(15);
    log_self_view();
    return nullptr;
}


// 自检：从 App 进程视角探测 root 痕迹（这些就是 NC SDK 会查的点）

// 自检：App 视角看到的属性（应已被我们改成真机取值）
static void prop_probe() {
    if (!prop_spoof_on()) {
        LOGI("prop-probe: 属性撒谎=关（默认），跳过");
        return;
    }
    char v1[PROP_VALUE_MAX] = {0};
    char v2[PROP_VALUE_MAX] = {0};
    __system_property_get("ro.dalvik.vm.native.bridge", v1);
    __system_property_get("ro.product.cpu.abilist", v2);
    LOGI("prop-probe: native.bridge='%s' abilist='%s'", v1, v2);
}


// 诊断开关：默认关。诊断函数内部会调用我们自己的插桩（易递归），只在排查时打开。
static bool diag_on() {
    char v[PROP_VALUE_MAX] = {0};
    int n = real_prop_get ? real_prop_get("tm.maps_cloak.diag", v) : 0;
    return n > 0 && (v[0] == '1' || strcmp(v, "on") == 0);
}

static void root_probe() {
    char buf[512] = {0};
    size_t off = 0;
    for (const char *p : kRootPaths) {
        int r = real_open(p, O_RDONLY | O_CLOEXEC);
        int seen = (r >= 0);
        if (seen) real_syscall(SYS_close, r);
        int w = snprintf(buf + off, sizeof(buf) - off, "%s=%s ",
                         strrchr(p, '/') ? strrchr(p, '/') + 1 : p,
                         seen ? "1" : "0");
        if (w > 0) off += (size_t) w;
        if (off > sizeof(buf) - 64) break;
    }
    LOGI("root-probe(view=%s): %s", "app-raw", buf);

    // 再走一遍**经过插桩**的路径，确认 App 真正看到的是"不存在"
    char buf2[512] = {0};
    size_t off2 = 0;
    for (const char *p : kRootPaths) {
        int seen = (access(p, F_OK) == 0);
        int w = snprintf(buf2 + off2, sizeof(buf2) - off2, "%s=%s ",
                         strrchr(p, '/') ? strrchr(p, '/') + 1 : p,
                         seen ? "1" : "0");
        if (w > 0) off2 += (size_t) w;
        if (off2 > sizeof(buf2) - 64) break;
    }
    LOGI("root-probe(hidden): %s", buf2);
}


// ── root 痕迹：access / stat 家族 / readlink 一律"不存在" ────────────────────
extern "C" int access(const char *path, int mode) {
    if (enabled() && (is_root_path(path) || is_emu_stat_path(path))) {
        errno = ENOENT;
        return -1;
    }
    return real_access(path, mode);
}

extern "C" int stat(const char *path, struct stat *buf) {
    if (enabled() && (is_root_path(path) || is_emu_stat_path(path))) {
        errno = ENOENT;
        return -1;
    }
    return real_stat(path, buf);
}

extern "C" int lstat(const char *path, struct stat *buf) {
    if (enabled() && (is_root_path(path) || is_emu_stat_path(path))) {
        errno = ENOENT;
        return -1;
    }
    return real_lstat(path, buf);
}

extern "C" int stat64(const char *path, struct stat64 *buf) {
    if (enabled() && is_root_path(path)) {
        errno = ENOENT;
        return -1;
    }
    return real_stat64(path, reinterpret_cast<struct stat *>(buf));
}

extern "C" int lstat64(const char *path, struct stat64 *buf) {
    if (enabled() && is_root_path(path)) {
        errno = ENOENT;
        return -1;
    }
    return real_lstat64(path, reinterpret_cast<struct stat *>(buf));
}

extern "C" ssize_t readlink(const char *path, char *buf, size_t sz) {
    if (enabled() &&
        (is_root_path(path) || is_emu_stat_path(path))) {
        errno = ENOENT;
        return -1;
    }
    return real_readlink(path, buf, sz);
}


// ── 属性撒谎：__system_property_get ─────────────────────────────────────────

// 属性撒谎的独立开关：默认关（`setprop tm.maps_cloak.prop_spoof 1` 打开）。
// 实测默认开启会让 App 进程直接消失（原因待查），所以不默认带上。
static bool prop_spoof_on() {
    char v[PROP_VALUE_MAX] = {0};
    int n = real_prop_get ? real_prop_get("tm.maps_cloak.prop_spoof", v) : 0;
    return n > 0 && (strcmp(v, "1") == 0 || strcmp(v, "on") == 0);
}

extern "C" int __system_property_get(const char *name, char *value) {
    static bool in_hook = false;       // 普通 static（避免 TLS 初始化 malloc）
    if (in_hook) {
        if (value != nullptr) value[0] = '\0';
        return 0;
    }
    in_hook = true;
    std::string fake;
    if (enabled() && prop_spoof_on() && spoof_prop(name, &fake)) {
        const size_t n = fake.size();
        if (value != nullptr) {
            memcpy(value, fake.c_str(), n + 1);
        }
        return (int) n;
    }
    int ret = real_prop_get ? real_prop_get(name, value) : 0;
    in_hook = false;
    return ret;
}

__attribute__((constructor)) static void on_load(void) {
    LOGI("maps_cloak 就绪 pid=%d enabled=%d uid=%d", getpid(),
         enabled() ? 1 : 0, getuid());
    // 诊断默认关：诊断函数内部会调用我们自己的插桩（易递归），只在排查时打开。
    if (diag_on()) {
        log_self_view();
        root_probe();
        prop_probe();
        pthread_t th;
        if (pthread_create(&th, nullptr, delayed_self_view, nullptr) == 0) {
            pthread_detach(th);
        }
    }
}
