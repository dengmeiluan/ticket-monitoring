#include "proc_view.hpp"

#include <android/log.h>
#include <fcntl.h>
#include <linux/memfd.h>
#include <limits.h>
#include <sys/syscall.h>
#include <unistd.h>

#include <atomic>
#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <string_view>

namespace {
DeviceLabSyscall original = nullptr;
std::string module_apk;
std::string cache_prefix;
std::atomic<bool> ready{false};
bool kernel_broker = false;

enum class View { none, maps, mounts };
const char* view_path(View view) { return view == View::maps ? "/proc/self/maps" : "/proc/self/mountinfo"; }
const char* view_name(View view) { return view == View::maps ? "maps" : "mountinfo"; }

std::string descriptor_target(int fd) {
    char path[64], value[PATH_MAX];
    std::snprintf(path, sizeof(path), "/proc/self/fd/%d", fd);
    const long size = original(SYS_readlinkat, AT_FDCWD, path, value, sizeof(value) - 1);
    return size < 0 ? std::string{} : std::string(value, static_cast<size_t>(size));
}

View select_view(int directory, const char* path) {
    if (path == nullptr) return View::none;
    std::string full(path);
    if (!full.empty() && full[0] != '/' && directory != AT_FDCWD) full = descriptor_target(directory) + "/" + full;
    char numeric[64], thread[64];
    std::snprintf(numeric, sizeof(numeric), "/proc/%d/", getpid());
    std::snprintf(thread, sizeof(thread), "/proc/%d/", gettid());
    for (const std::string_view prefix : {std::string_view("/proc/self/"), std::string_view("/proc/thread-self/"),
                                         std::string_view(numeric), std::string_view(thread)}) {
        if (full.compare(0, prefix.size(), prefix) == 0) {
            const std::string suffix = full.substr(prefix.size());
            if (suffix == "maps") return View::maps;
            if (suffix == "mountinfo") return View::mounts;
        }
    }
    return View::none;
}

bool write_all(int fd, const std::string& text) {
    size_t position = 0;
    while (position < text.size()) {
        const long count = original(SYS_write, fd, text.data() + position, text.size() - position);
        if (count < 0 && errno == EINTR) continue;
        if (count <= 0) return false;
        position += static_cast<size_t>(count);
    }
    return true;
}

int snapshot_fd(View view, int flags, const std::string& text) {
    const std::string name = std::string("guest.proc.") + view_name(view);
    int writable = static_cast<int>(original(SYS_memfd_create, name.c_str(), MFD_CLOEXEC | MFD_ALLOW_SEALING));
    if (writable >= 0) {
        int result = -1;
        if (write_all(writable, text) && fcntl(writable, F_ADD_SEALS, F_SEAL_WRITE | F_SEAL_GROW | F_SEAL_SHRINK | F_SEAL_SEAL) == 0) {
            char path[64];
            std::snprintf(path, sizeof(path), "/proc/self/fd/%d", writable);
            result = static_cast<int>(original(SYS_openat, AT_FDCWD, path, flags, 0));
        }
        close(writable);
        if (result >= 0) return result;
    }
    std::string temporary = cache_prefix + view_name(view) + ".XXXXXX";
    writable = mkostemp(temporary.data(), O_CLOEXEC);
    if (writable < 0) return -1;
    const bool written = write_all(writable, text);
    close(writable);
    const int result = written ? static_cast<int>(original(SYS_openat, AT_FDCWD, temporary.c_str(), flags, 0)) : -1;
    const int error = errno;
    unlink(temporary.c_str());
    errno = error;
    return result;
}
}

void configure_proc_views(const std::string& cpu_path, const std::string& module_path, DeviceLabSyscall syscall) {
    if (ready.load(std::memory_order_acquire)) return;
    std::string directory = cpu_path.substr(0, cpu_path.find_last_of('/'));
    char canonical[PATH_MAX];
    if (realpath(directory.c_str(), canonical) != nullptr) directory = canonical;
    cache_prefix = directory + "/device-lab-proc-";
    module_apk = module_path;
    kernel_broker = getenv("DEVICE_LAB_PROC_BROKER") != nullptr;
    original = syscall;
    ready.store(original != nullptr && !module_apk.empty(), std::memory_order_release);
}

int proc_view_fd(int directory, const char* path, int flags) {
    if (!ready.load(std::memory_order_acquire) || (flags & O_ACCMODE) != O_RDONLY
            || (flags & (O_CREAT | O_TRUNC | O_EXCL | O_DIRECTORY | O_PATH)) != 0) return -1;
    const View view = select_view(directory, path);
    if (view == View::none) return -1;
    if (kernel_broker) return static_cast<int>(original(SYS_openat, directory, path, flags, 0));
    const int fd = static_cast<int>(original(SYS_openat, AT_FDCWD, view_path(view), O_RDONLY | O_CLOEXEC, 0));
    if (fd < 0) return -1;
    std::string text;
    char buffer[4096];
    long count;
    while ((count = original(SYS_read, fd, buffer, sizeof(buffer))) > 0) {
        text.append(buffer, static_cast<size_t>(count));
        if (text.size() > 8 * 1024 * 1024) { count = -1; errno = EFBIG; break; }
    }
    const int error = errno;
    close(fd);
    if (count < 0) { errno = error; return -1; }
    std::string filtered;
    size_t position = 0, omitted = 0;
    while (position < text.size()) {
        size_t end = text.find('\n', position);
        if (end == std::string::npos) end = text.size(); else ++end;
        const std::string_view line(text.data() + position, end - position);
        const bool hidden = view == View::maps
                ? line.find("/libndk_translation") != std::string_view::npos
                    || line.find("/libhoudini") != std::string_view::npos || line.find(module_apk) != std::string_view::npos
                : line.find(" /proc/cpuinfo ") != std::string_view::npos
                    || line.find("/adb/modules/device_lab_cpu/") != std::string_view::npos
                    || line.find("/misc/device-lab/") != std::string_view::npos;
        if (hidden) ++omitted; else filtered.append(line);
        position = end;
    }
    if (filtered.empty()) { errno = EIO; return -1; }
    const int result = snapshot_fd(view, flags, filtered);
    __android_log_print(result >= 0 ? ANDROID_LOG_INFO : ANDROID_LOG_WARN, "DeviceLabProc",
                        "%s view bytes=%zu/%zu omitted=%zu fd=%d errno=%d", view_name(view), filtered.size(), text.size(), omitted, result, errno);
    return result;
}

const char* proc_descriptor_path(int fd) {
    if (!ready.load(std::memory_order_acquire)) return nullptr;
    const std::string path = descriptor_target(fd);
    if (kernel_broker) {
        const std::string prefix = "/proc/" + std::to_string(getpid()) + "/";
        if (path == prefix + "maps") return "/proc/self/maps";
        if (path == prefix + "mountinfo") return "/proc/self/mountinfo";
    }
    if (path == "/memfd:guest.proc.maps (deleted)" || path.compare(0, cache_prefix.size() + 5, cache_prefix + "maps.") == 0)
        return "/proc/self/maps";
    if (path == "/memfd:guest.proc.mountinfo (deleted)" || path.compare(0, cache_prefix.size() + 10, cache_prefix + "mountinfo.") == 0)
        return "/proc/self/mountinfo";
    return nullptr;
}

std::string proc_view_controls() {
    std::string summary;
    for (View view : {View::maps, View::mounts}) {
        const int fd = proc_view_fd(AT_FDCWD, view_path(view), O_RDONLY | O_CLOEXEC);
        bool valid = fd >= 0;
        std::string backend = "unavailable";
        if (fd >= 0) {
            const std::string actual = descriptor_target(fd);
            backend = kernel_broker ? "kernel-broker" : actual.find("/memfd:") == 0 ? "sealed-memfd" : "unlinked-cache";
            const char* alias = proc_descriptor_path(fd);
            valid &= alias != nullptr && std::strcmp(alias, view_path(view)) == 0;
            valid &= (fcntl(fd, F_GETFL) & O_ACCMODE) == O_RDONLY && (fcntl(fd, F_GETFD) & FD_CLOEXEC) != 0;
            char first[128]{}, second[128]{};
            const ssize_t count = read(fd, first, sizeof(first) - 1);
            valid &= count > 0 && lseek(fd, 0, SEEK_SET) == 0;
            const ssize_t repeated = read(fd, second, sizeof(second) - 1);
            valid &= count == repeated && count > 0 && std::memcmp(first, second, static_cast<size_t>(count > 0 ? count : 0)) == 0;
            unsigned long long start = 0, stop = 0;
            unsigned id = 0, parent = 0, major = 0, minor = 0;
            char permissions[5]{};
            valid &= view == View::maps ? std::sscanf(first, "%llx-%llx %4s", &start, &stop, permissions) == 3 && start < stop
                    : std::sscanf(first, "%u %u %u:%u", &id, &parent, &major, &minor) == 4;
            errno = 0;
            valid &= write(fd, "x", 1) == -1 && errno == EBADF;
            close(fd);
        }
        if (!summary.empty()) summary += " ";
        summary += std::string(view_name(view)) + "=" + (valid ? "1/" : "0/") + backend;
    }
    return summary;
}
