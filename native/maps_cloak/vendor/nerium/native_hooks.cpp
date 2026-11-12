#include <android/log.h>
#include <dlfcn.h>
#include <fcntl.h>
#include <jni.h>
#include <sys/syscall.h>
#include <sys/system_properties.h>
#include <sys/auxv.h>
#include <sys/utsname.h>
#include <sys/stat.h>
#include <sys/vfs.h>
#include <sys/mman.h>
#include <GLES2/gl2.h>
#include <unistd.h>
#include "profile.hpp"
#include "proc_view.hpp"

#include <array>
#include <atomic>
#include <cerrno>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <string>
#include <string_view>
#include <map>
#include <mutex>

extern "C" {
__attribute__((visibility("hidden"))) long (*device_lab_original_syscall)(long, ...) = nullptr;
__attribute__((visibility("hidden"))) long device_lab_syscall_entry(long, ...);
}

namespace {
using HookFunction = int (*)(void*, void*, void**);
using LibraryLoaded = void (*)(const char*, void*);

// Public LSPosed/Vector native ABI. The framework owns this structure.
struct NativeApi {
    uint32_t version;
    HookFunction hook;
    int (*unhook)(void*);
};

using device_lab::replacement_property;

using PropertyGet = int (*)(const char*, char*);
using PropertyCallback = void (*)(void*, const char*, const char*, uint32_t);
using PropertyReadCallback = void (*)(const prop_info*, PropertyCallback, void*);
using Fopen = FILE* (*)(const char*, const char*);
using Open = int (*)(const char*, int, ...);
using OpenAt = int (*)(int, const char*, int, ...);
using OpenChecked = int (*)(const char*, int);
using OpenAtChecked = int (*)(int, const char*, int);
using Uname = int (*)(struct utsname*);
using Auxval = unsigned long (*)(unsigned long);
using GlString = const GLubyte* (*)(GLenum);
using Readlink = ssize_t (*)(const char*, char*, size_t);
using ReadlinkAt = ssize_t (*)(int, const char*, char*, size_t);

PropertyGet original_property_get = nullptr;
PropertyReadCallback original_property_callback = nullptr;
Fopen original_fopen = nullptr;
Open original_open = nullptr;
OpenAt original_openat = nullptr;
OpenChecked original_open_checked = nullptr;
OpenAtChecked original_openat_checked = nullptr;
Uname original_uname = nullptr;
Auxval original_auxval = nullptr;
GlString original_gl_string = nullptr;
GlString original_gl3_string = nullptr;
HookFunction hook_function = nullptr;
Readlink original_readlink = nullptr;
ReadlinkAt original_readlinkat = nullptr;
std::string cpu_snapshot;
std::string cpu_shadow_path;
std::atomic<bool> cpu_shadow_ready{false};
std::array<bool, 14> installed{};

void profile_machine(struct utsname* value) {
    std::strcpy(value->machine, "aarch64");
}

long raw_uname(struct utsname* value) {
    long result;
    __asm__ volatile("syscall" : "=a"(result) : "a"(SYS_uname), "D"(value) : "rcx", "r11", "memory");
    return result;
}

bool uname_controls(struct utsname& observed) {
    const bool null_fault = raw_uname(nullptr) == -EFAULT;
    const long page_size = sysconf(_SC_PAGESIZE);
    void* page = mmap(nullptr, static_cast<size_t>(page_size), PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (page == MAP_FAILED) return false;
    std::memset(page, 0xa5, sizeof(struct utsname));
    bool readonly_fault = false;
    if (mprotect(page, static_cast<size_t>(page_size), PROT_READ) == 0) {
        readonly_fault = raw_uname(static_cast<struct utsname*>(page)) == -EFAULT;
        const auto* bytes = static_cast<const unsigned char*>(page);
        for (size_t i = 0; i < sizeof(struct utsname); ++i) readonly_fault &= bytes[i] == 0xa5;
    }
    munmap(page, static_cast<size_t>(page_size));
    return raw_uname(&observed) == 0 && observed.machine[0] != '\0' && null_fault && readonly_fault;
}

int uname_profile(struct utsname* value) {
    const int result = original_uname(value);
    if (result == 0) profile_machine(value);
    return result;
}

unsigned long auxval_profile(unsigned long type) {
    static constexpr char platform[] = "aarch64";
    if (type == AT_PLATFORM) return reinterpret_cast<unsigned long>(platform);
    return original_auxval(type);
}

const GLubyte* graphics_profile(GlString original, GLenum name) {
    const GLubyte* value = original(name);
    if (value == nullptr) return nullptr;
    if (name == GL_VENDOR) return reinterpret_cast<const GLubyte*>("ARM");
    if (name == GL_RENDERER) return reinterpret_cast<const GLubyte*>("Mali-G715");
    if (name == GL_VERSION) {
        static std::mutex mutex;
        static std::map<std::string, std::string> versions;
        std::lock_guard<std::mutex> lock(mutex);
        const std::string actual(reinterpret_cast<const char*>(value));
        auto entry = versions.try_emplace(actual, actual).first;
        std::string& version = entry->second;
        const size_t suffix = version.find(" (");
        if (suffix != std::string::npos) version.resize(suffix);
        // Keep the actual API version; omit the host driver's optional description.
        return reinterpret_cast<const GLubyte*>(version.c_str());
    }
    return value;
}

const GLubyte* gl_string_profile(GLenum name) { return graphics_profile(original_gl_string, name); }
const GLubyte* gl3_string_profile(GLenum name) { return graphics_profile(original_gl3_string, name); }

bool cpu_descriptor(int fd) {
    struct stat descriptor{}, reference{};
    if (fstat(fd, &descriptor) != 0) return false;
    const auto matches = [&](const char* path) {
        return stat(path, &reference) == 0 && descriptor.st_dev == reference.st_dev && descriptor.st_ino == reference.st_ino;
    };
    return matches("/proc/cpuinfo") || (cpu_shadow_ready.load(std::memory_order_acquire) && matches(cpu_shadow_path.c_str()));
}

ssize_t descriptor_link(const char* path, char* value, size_t size, ssize_t result) {
    if (result < 0) return result;
    const int saved_errno = errno;
    int fd = -1, consumed = 0;
    if (std::sscanf(path, "/proc/self/fd/%d%n", &fd, &consumed) == 1 && consumed > 0
            && path[consumed] == '\0') {
        const char* replacement = cpu_descriptor(fd) ? "/proc/cpuinfo" : proc_descriptor_path(fd);
        if (replacement != nullptr) {
            const size_t length = std::strlen(replacement);
            const size_t count = size < length ? size : length;
            std::memcpy(value, replacement, count);
            result = static_cast<ssize_t>(count);
        }
    }
    errno = saved_errno;
    return result;
}

ssize_t readlink_profile(const char* path, char* value, size_t size) {
    return descriptor_link(path, value, size, original_readlink(path, value, size));
}

ssize_t readlinkat_profile(int directory, const char* path, char* value, size_t size) {
    return descriptor_link(path, value, size, original_readlinkat(directory, path, value, size));
}

int property_get(const char* name, char* value) {
    if (const char* replacement = replacement_property(name)) {
        const size_t length = std::strlen(replacement);
        std::memcpy(value, replacement, length + 1);
        return static_cast<int>(length);
    }
    return original_property_get(name, value);
}

struct CallbackContext {
    PropertyCallback callback;
    void* cookie;
};

void property_read_callback(const prop_info* info, PropertyCallback callback, void* cookie) {
    CallbackContext context{callback, cookie};
    original_property_callback(info, [](void* data, const char* name, const char* value, uint32_t serial) {
        const auto& state = *static_cast<CallbackContext*>(data);
        const char* replacement = replacement_property(name);
        state.callback(state.cookie, name, replacement == nullptr ? value : replacement, serial);
    }, &context);
}

std::string read_original_cpuinfo() {
    const int fd = static_cast<int>(syscall(SYS_openat, AT_FDCWD, "/proc/cpuinfo", O_RDONLY | O_CLOEXEC, 0));
    if (fd < 0) return {};
    std::string result;
    char buffer[4096];
    ssize_t count;
    while ((count = read(fd, buffer, sizeof(buffer))) > 0) result.append(buffer, count);
    const int read_error = errno;
    close(fd);
    if (count < 0) {
        errno = read_error;
        return {};
    }
    return result;
}

void remove_hypervisor_flag(std::string& text) {
    constexpr std::string_view token = "hypervisor";
    size_t position = 0;
    while ((position = text.find(token, position)) != std::string::npos) {
        const auto whitespace = [](char value) { return value == ' ' || value == '\t' || value == '\n'; };
        const bool start = position == 0 || whitespace(text[position - 1]);
        const size_t end = position + token.size();
        const bool finish = end == text.size() || whitespace(text[end]);
        if (start && finish) text.erase(position, token.size());
        else position = end;
    }
}

bool cpuinfo_path(const char* path) {
    return path != nullptr && std::strcmp(path, "/proc/cpuinfo") == 0;
}

bool simple_read(int flags) {
    return (flags & O_ACCMODE) == O_RDONLY
            && (flags & (O_CREAT | O_TRUNC | O_EXCL | O_DIRECTORY | O_PATH)) == 0;
}

int cpuinfo_fd(int flags) {
    if (!cpu_shadow_ready.load(std::memory_order_acquire)) return -1;
    const int result = static_cast<int>(syscall(SYS_openat, AT_FDCWD, cpu_shadow_path.c_str(), flags, 0));
    if (result < 0) __android_log_print(ANDROID_LOG_WARN, "DeviceLabNative", "cpuinfo snapshot open failed: errno=%d", errno);
    return result;
}

FILE* fopen_cpuinfo(const char* path, const char* mode) {
    if (mode != nullptr && mode[0] == 'r' && std::strchr(mode, '+') == nullptr) {
        const int fd = proc_view_fd(AT_FDCWD, path, O_RDONLY | (std::strchr(mode, 'e') != nullptr ? O_CLOEXEC : 0));
        if (fd >= 0) {
            FILE* stream = fdopen(fd, mode);
            if (stream != nullptr) return stream;
            close(fd);
        }
    }
    if (cpuinfo_path(path) && mode != nullptr && mode[0] == 'r' && std::strchr(mode, '+') == nullptr) {
        int flags = O_RDONLY;
        if (std::strchr(mode, 'e') != nullptr) flags |= O_CLOEXEC;
        const int fd = cpuinfo_fd(flags);
        if (fd >= 0) {
            FILE* result = fdopen(fd, mode);
            if (result != nullptr) return result;
            close(fd);
        }
    }
    return original_fopen(path, mode);
}

bool needs_mode(int flags) {
    return (flags & O_CREAT) != 0 || (flags & O_TMPFILE) == O_TMPFILE;
}

int open_cpuinfo(const char* path, int flags, ...) {
    mode_t mode = 0;
    if (needs_mode(flags)) {
        va_list args;
        va_start(args, flags);
        mode = va_arg(args, mode_t);
        va_end(args);
    }
    const int view = proc_view_fd(AT_FDCWD, path, flags);
    if (view >= 0) return view;
    if (cpuinfo_path(path) && simple_read(flags)) {
        const int fd = cpuinfo_fd(flags);
        if (fd >= 0) return fd;
    }
    return original_open(path, flags, mode);
}

int openat_cpuinfo(int directory, const char* path, int flags, ...) {
    mode_t mode = 0;
    if (needs_mode(flags)) {
        va_list args;
        va_start(args, flags);
        mode = va_arg(args, mode_t);
        va_end(args);
    }
    const int view = proc_view_fd(directory, path, flags);
    if (view >= 0) return view;
    if (cpuinfo_path(path) && simple_read(flags)) {
        const int fd = cpuinfo_fd(flags);
        if (fd >= 0) return fd;
    }
    return original_openat(directory, path, flags, mode);
}

int open_checked_cpuinfo(const char* path, int flags) {
    const int view = proc_view_fd(AT_FDCWD, path, flags);
    if (view >= 0) return view;
    if (cpuinfo_path(path) && simple_read(flags)) {
        const int fd = cpuinfo_fd(flags);
        if (fd >= 0) return fd;
    }
    return original_open_checked(path, flags);
}

int openat_checked_cpuinfo(int directory, const char* path, int flags) {
    const int view = proc_view_fd(directory, path, flags);
    if (view >= 0) return view;
    if (cpuinfo_path(path) && simple_read(flags)) {
        const int fd = cpuinfo_fd(flags);
        if (fd >= 0) return fd;
    }
    return original_openat_checked(directory, path, flags);
}

template<typename Function>
bool install_hook(HookFunction hook, void* library, const char* symbol, void* replacement, Function& original) {
    void* target = dlsym(library, symbol);
    const int status = target == nullptr ? -1 : hook(target, replacement, reinterpret_cast<void**>(&original));
    __android_log_print(status == 0 ? ANDROID_LOG_INFO : ANDROID_LOG_ERROR,
                        "DeviceLabNative", "%s hook status: %d", symbol, status);
    return status == 0 && original != nullptr;
}

void library_loaded(const char*, void* handle) {
    if (hook_function == nullptr) return;
    void* target = dlsym(handle, "glGetString");
    Dl_info info{};
    if (target == nullptr || dladdr(target, &info) == 0 || info.dli_fname == nullptr) return;
    const std::string_view path(info.dli_fname);
    if (!installed[10] && path.find("/libGLESv2.so") != std::string_view::npos)
        installed[10] = install_hook(hook_function, handle, "glGetString", reinterpret_cast<void*>(gl_string_profile), original_gl_string);
    if (!installed[11] && path.find("/libGLESv3.so") != std::string_view::npos)
        installed[11] = install_hook(hook_function, handle, "glGetString", reinterpret_cast<void*>(gl3_string_profile), original_gl3_string);
}
}

extern "C" __attribute__((visibility("hidden")))
long device_lab_sys_uname(struct utsname* value) {
    const long result = device_lab_original_syscall(SYS_uname, value);
    if (result == 0) profile_machine(value);
    return result;
}

extern "C" __attribute__((visibility("hidden")))
long device_lab_sys_fstatfs(int fd, struct statfs* value) {
    const long result = device_lab_original_syscall(SYS_fstatfs, fd, value);
    const int saved_errno = errno;
    if (result == 0 && (cpu_descriptor(fd) || proc_descriptor_path(fd) != nullptr)) {
        struct statfs proc{};
        if (statfs("/proc", &proc) == 0) *value = proc;
    }
    errno = saved_errno;
    return result;
}

extern "C" __attribute__((visibility("hidden")))
long device_lab_sys_readlinkat(int directory, const char* path, char* value, size_t size) {
    const long result = device_lab_original_syscall(SYS_readlinkat, directory, path, value, size);
    return descriptor_link(path, value, size, result);
}

extern "C" __attribute__((visibility("hidden")))
long device_lab_sys_openat(int directory, const char* path, int flags, mode_t mode) {
    const int view = proc_view_fd(directory, path, flags);
    return view >= 0 ? view : device_lab_original_syscall(SYS_openat, directory, path, flags, mode);
}

extern "C" __attribute__((visibility("default"), used))
LibraryLoaded native_init(const NativeApi* api) {
    if (api == nullptr || api->version < 2 || api->hook == nullptr) return nullptr;
    // native_init runs under the framework's loader lock. A nested dlopen would deadlock it.
    void* libc = RTLD_DEFAULT;
    hook_function = api->hook;
    cpu_snapshot = read_original_cpuinfo();
    remove_hypervisor_flag(cpu_snapshot);
    installed[0] = install_hook(api->hook, libc, "__system_property_get", reinterpret_cast<void*>(property_get), original_property_get);
    installed[1] = install_hook(api->hook, libc, "__system_property_read_callback", reinterpret_cast<void*>(property_read_callback), original_property_callback);
    installed[2] = install_hook(api->hook, libc, "fopen", reinterpret_cast<void*>(fopen_cpuinfo), original_fopen);
    installed[3] = install_hook(api->hook, libc, "open", reinterpret_cast<void*>(open_cpuinfo), original_open);
    installed[4] = install_hook(api->hook, libc, "openat", reinterpret_cast<void*>(openat_cpuinfo), original_openat);
    installed[5] = install_hook(api->hook, libc, "__open_2", reinterpret_cast<void*>(open_checked_cpuinfo), original_open_checked);
    installed[6] = install_hook(api->hook, libc, "__openat_2", reinterpret_cast<void*>(openat_checked_cpuinfo), original_openat_checked);
    installed[7] = install_hook(api->hook, libc, "uname", reinterpret_cast<void*>(uname_profile), original_uname);
    installed[8] = install_hook(api->hook, libc, "syscall", reinterpret_cast<void*>(device_lab_syscall_entry), device_lab_original_syscall);
    installed[9] = install_hook(api->hook, libc, "getauxval", reinterpret_cast<void*>(auxval_profile), original_auxval);
    installed[12] = install_hook(api->hook, libc, "readlink", reinterpret_cast<void*>(readlink_profile), original_readlink);
    installed[13] = install_hook(api->hook, libc, "readlinkat", reinterpret_cast<void*>(readlinkat_profile), original_readlinkat);
    library_loaded(nullptr, RTLD_DEFAULT);
    return library_loaded;
}

extern "C" JNIEXPORT jboolean JNICALL
Java_dev_androidlab_module_DeviceHooks_configureCpuSnapshot(JNIEnv* env, jclass, jstring input, jstring module) {
    if (!installed[10] || !installed[11]) {
        // Called after native_init returns, outside the framework's loader lock.
        void* graphics = dlopen("libGLESv2.so", RTLD_NOW | RTLD_LOCAL);
        if (graphics != nullptr) library_loaded(nullptr, graphics);
        void* graphics3 = dlopen("libGLESv3.so", RTLD_NOW | RTLD_LOCAL);
        if (graphics3 != nullptr) library_loaded(nullptr, graphics3);
    }
    if (cpu_shadow_ready.load(std::memory_order_acquire)) return true;
    // The native bridge can mount its ARM CPU view after native_init has run.
    std::string snapshot = read_original_cpuinfo();
    if (snapshot.empty()) snapshot = cpu_snapshot;
    remove_hypervisor_flag(snapshot);
    if (snapshot.empty()) return false;
    const char* value = env->GetStringUTFChars(input, nullptr);
    if (value == nullptr) return false;
    const std::string path(value);
    env->ReleaseStringUTFChars(input, value);
    const char* module_value = env->GetStringUTFChars(module, nullptr);
    if (module_value == nullptr) return false;
    configure_proc_views(path, module_value, device_lab_original_syscall);
    env->ReleaseStringUTFChars(module, module_value);
    // SELinux denies reopening memfds read-only on this image. Use the scoped app's own cache.
    const int fd = static_cast<int>(syscall(SYS_openat, AT_FDCWD, path.c_str(),
                                           O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC | O_NOFOLLOW, 0600));
    if (fd < 0) return false;
    size_t written = 0;
    while (written < snapshot.size()) {
        const ssize_t count = write(fd, snapshot.data() + written, snapshot.size() - written);
        if (count <= 0) {
            close(fd);
            return false;
        }
        written += static_cast<size_t>(count);
    }
    close(fd);
    cpu_shadow_path = path;
    cpu_shadow_ready.store(true, std::memory_order_release);
    return true;
}

extern "C" JNIEXPORT jstring JNICALL
Java_dev_androidlab_module_DeviceHooks_nativeStatus(JNIEnv* env, jclass) {
    struct utsname observed{};
    const bool controls = uname_controls(observed);
    const std::string views = proc_view_controls();
    char status[448];
    std::snprintf(status, sizeof(status), "get=%d callback=%d fopen=%d open=%d openat=%d open_checked=%d openat_checked=%d uname=%d syscall=%d auxval=%d gl2=%d gl3=%d readlink=%d readlinkat=%d cpu_cache=%d uname_controls=%d raw_uname=%s %s",
                  installed[0], installed[1], installed[2], installed[3], installed[4], installed[5], installed[6], installed[7], installed[8], installed[9], installed[10], installed[11], installed[12], installed[13], cpu_shadow_ready.load(), controls, observed.machine, views.c_str());
    return env->NewStringUTF(status);
}

extern "C" JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM* vm, void*) {
    JNIEnv* env = nullptr;
    if (vm->GetEnv(reinterpret_cast<void**>(&env), JNI_VERSION_1_6) != JNI_OK) return JNI_ERR;
    jclass thread_class = env->FindClass("java/lang/Thread");
    jmethodID current = env->GetStaticMethodID(thread_class, "currentThread", "()Ljava/lang/Thread;");
    jobject thread = env->CallStaticObjectMethod(thread_class, current);
    jmethodID get_loader = env->GetMethodID(thread_class, "getContextClassLoader", "()Ljava/lang/ClassLoader;");
    jobject loader = env->CallObjectMethod(thread, get_loader);
    jclass loader_class = env->FindClass("java/lang/ClassLoader");
    jmethodID load_class = env->GetMethodID(loader_class, "loadClass", "(Ljava/lang/String;)Ljava/lang/Class;");
    jstring name = env->NewStringUTF("dev.androidlab.module.DeviceHooks");
    auto module = static_cast<jclass>(env->CallObjectMethod(loader, load_class, name));
    if (env->ExceptionCheck() || module == nullptr) return JNI_ERR;
    JNINativeMethod methods[] = {
        {const_cast<char*>("nativeStatus"), const_cast<char*>("()Ljava/lang/String;"),
         reinterpret_cast<void*>(Java_dev_androidlab_module_DeviceHooks_nativeStatus)},
        {const_cast<char*>("configureCpuSnapshot"), const_cast<char*>("(Ljava/lang/String;Ljava/lang/String;)Z"),
         reinterpret_cast<void*>(Java_dev_androidlab_module_DeviceHooks_configureCpuSnapshot)}
    };
    return env->RegisterNatives(module, methods, 2) == JNI_OK ? JNI_VERSION_1_6 : JNI_ERR;
}
