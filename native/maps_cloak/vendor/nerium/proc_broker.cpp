
// tm: aarch64 没有 SYS_open / SYS_stat（x86 专属），补兼容定义
#ifndef SYS_open
#define SYS_open (-1)
#endif
#ifndef SYS_stat
#define SYS_stat (-1)
#endif
#ifndef SYS_readlink
#define SYS_readlink (-1)
#endif
#ifndef SYS_lstat
#define SYS_lstat (-1)
#endif

#include "proc_broker.hpp"
#include <android/log.h>
#include <fcntl.h>
#include <limits.h>
#include <linux/stat.h>
#include <linux/openat2.h>
#include <linux/kcmp.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/statfs.h>
#include <sys/syscall.h>
#include <sys/xattr.h>
#include <sys/mman.h>
#include <unistd.h>
#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <limits>
#include <string>
#include <string_view>
#include <vector>
#include <unordered_set>

bool notification_valid(int listener, uint64_t id) {
    int result;
    do { result = ioctl(listener, SECCOMP_IOCTL_NOTIF_ID_VALID, &id); } while (result < 0 && errno == EINTR);
    return result == 0;
}

int write_notification_memory(const seccomp_notif& request, int listener, uint64_t address, const void* data, size_t size) {
    const std::string base = "/proc/" + std::to_string(request.pid);
    const int memory = open((base + "/mem").c_str(), O_RDWR | O_CLOEXEC);
    if (memory < 0) return EAGAIN;
    FILE* maps = fopen((base + "/maps").c_str(), "re");
    if (maps == nullptr) { close(memory); return EAGAIN; }
    // Pin mm before validating the notification, including on PID reuse.
    if (!notification_valid(listener, request.id)) { fclose(maps); close(memory); return ENOENT; }
    const bool fits = size <= static_cast<uint64_t>(std::numeric_limits<off_t>::max())
            && address <= static_cast<uint64_t>(std::numeric_limits<off_t>::max()) - size;
    const uint64_t end = fits ? address + size : 0;
    uint64_t cursor = address;
    char line[4096];
    while (fits && cursor < end && fgets(line, sizeof(line), maps)) {
        unsigned long long first = 0, last = 0;
        char permissions[5]{};
        if (std::sscanf(line, "%llx-%llx %4s", &first, &last, permissions) == 3 && cursor >= first && cursor < last) {
            if (permissions[1] != 'w') break;
            cursor = last < end ? last : end;
        }
    }
    fclose(maps);
    int error = EFAULT;
    if (fits && cursor == end) {
        const ssize_t written = pwrite(memory, data, size, static_cast<off_t>(address));
        if (written == static_cast<ssize_t>(size)) error = 0;
        else if (written < 0 && (errno == EACCES || errno == EPERM)) error = EAGAIN;
    }
    close(memory);
    return error;
}

namespace {
std::string proc_base(uint32_t tid) { return "/proc/" + std::to_string(tid); }
bool cpu_descriptor(uint32_t pid, int fd) {
    const std::string base = proc_base(pid);
    struct stat descriptor{}, reference{};
    return stat((base + "/fd/" + std::to_string(fd)).c_str(), &descriptor) == 0
            && stat((base + "/root/proc/cpuinfo").c_str(), &reference) == 0
            && descriptor.st_dev == reference.st_dev && descriptor.st_ino == reference.st_ino;
}
std::string read_link(const std::string& path) {
    char value[PATH_MAX];
    const ssize_t count = readlink(path.c_str(), value, sizeof(value));
    return count > 0 ? std::string(value, static_cast<size_t>(count)) : std::string{};
}
int tgid(uint32_t tid) {
    FILE* file = fopen((proc_base(tid) + "/status").c_str(), "re");
    if (!file) return -1;
    int result = -1;
    char line[512];
    while (fgets(line, sizeof(line), file)) if (std::sscanf(line, "Tgid: %d", &result) == 1) break;
    fclose(file);
    return result;
}
std::string request_string(const seccomp_notif& request, int listener, uint64_t address, bool* valid = nullptr) {
    if (valid) *valid = false;
    if (address > static_cast<uint64_t>(std::numeric_limits<off_t>::max())) return {};
    const int fd = open((proc_base(request.pid) + "/mem").c_str(), O_RDONLY | O_CLOEXEC);
    if (fd < 0) return {};
    char text[PATH_MAX + 1];
    ssize_t count = -1;
    if (notification_valid(listener, request.id)) count = pread(fd, text, sizeof(text), static_cast<off_t>(address));
    close(fd);
    if (count <= 0) return {};
    const void* end = std::memchr(text, 0, static_cast<size_t>(count));
    if (end && valid) *valid = true;
    return end ? std::string(text, static_cast<const char*>(end) - text) : std::string{};
}
std::string full_path(const seccomp_notif& request, int directory, std::string path) {
    if (path.empty()) return {};
    if (path[0] != '/') {
        const std::string base = directory == AT_FDCWD ? proc_base(request.pid) + "/cwd"
                : proc_base(request.pid) + "/fd/" + std::to_string(directory);
        struct stat stats{};
        if (stat(base.c_str(), &stats) != 0 || !S_ISDIR(stats.st_mode)) return {};
        path = read_link(base) + "/" + path;
    }
    // Ordinary paths must reach the caller's VFS checks without a privileged
    // realpath traversal, which can itself generate observable directory opens.
    if (path.find("/proc") == std::string::npos && path.find("/../") == std::string::npos) return {};
    // Walk components so /proc/self/root/proc/self resolves in the caller's context.
    size_t position = 0;
    std::string expanded = "/";
    while (position < path.size()) {
        if (path[position] == '/') { while (position < path.size() && path[position] == '/') ++position; }
        else {
            const size_t end = path.find('/', position);
            const std::string part = path.substr(position, end == std::string::npos ? end : end - position);
            if (part != ".") {
                std::string component = part;
                if (expanded == "/proc" && part == "self") component = std::to_string(tgid(request.pid));
                else if (expanded == "/proc" && part == "thread-self") component = std::to_string(tgid(request.pid)) + "/task/" + std::to_string(request.pid);
                else if (expanded == "/proc" && part == "mounts") component = std::to_string(tgid(request.pid)) + "/mounts";
                char canonical[PATH_MAX];
                if (!realpath((expanded + (expanded == "/" ? "" : "/") + component).c_str(), canonical)) return {};
                expanded = canonical;
            }
            position = end == std::string::npos ? path.size() : end;
        }
    }
    return expanded;
}
std::string own_view(const seccomp_notif& request, const std::string& path) {
    unsigned pid = 0, task = 0;
    char name[32]{};
    int end = 0;
    if (std::sscanf(path.c_str(), "/proc/%u/task/%u/%31[^/]%n", &pid, &task, name, &end) != 3) {
        end = 0;
        if (std::sscanf(path.c_str(), "/proc/%u/%31[^/]%n", &pid, name, &end) != 2) return {};
        task = pid;
    }
    if (path[static_cast<size_t>(end)] != '\0' || tgid(pid) != tgid(request.pid) || tgid(task) != tgid(request.pid)) return {};
    const std::string view(name);
    return view == "maps" || view == "smaps" || view == "numa_maps" || view == "mountinfo" || view == "mounts" ? view : std::string{};
}
std::string snapshot_source(uint32_t pid, int fd) {
    const std::string actual = read_link(proc_base(pid) + "/fd/" + std::to_string(fd));
    constexpr const char* prefix = "/data/misc/device-lab/proc-broker-";
    if (actual.compare(0, std::strlen(prefix), prefix) != 0) return {};
    const std::string tail = actual.substr(std::strlen(prefix));
    char name[32]{}; unsigned owner = 0, task = 0;
    if (std::sscanf(tail.c_str(), "%31[^.].%u.%u.", name, &owner, &task) != 3) return {};
    const std::string view(name);
    if (view == "fdinfo") {
        unsigned descriptor = 0;
        if (std::sscanf(tail.c_str(), "%31[^.].%u.%u.%u.", name, &owner, &task, &descriptor) != 4) return {};
        return proc_base(owner) + (task ? "/task/" + std::to_string(task) : "") + "/fdinfo/" + std::to_string(descriptor);
    }
    if (view == "maps" || view == "smaps" || view == "numa_maps" || view == "mountinfo" || view == "mounts")
        return proc_base(owner) + (task ? "/task/" + std::to_string(task) : "") + "/" + view;
    return {};
}
std::string link_path(const seccomp_notif& request, int directory, const std::string& input) {
    if (input.empty()) return {};
    const size_t slash = input.find_last_of('/');
    const std::string parent = slash == std::string::npos ? "." : input.substr(0, slash);
    const std::string resolved = full_path(request, directory, parent);
    return resolved.empty() ? std::string{} : resolved + "/" + input.substr(slash == std::string::npos ? 0 : slash + 1);
}
std::string descriptor_source(const seccomp_notif& request, int directory, const std::string& input, bool device_alias = false) {
    const std::string path = link_path(request, directory, input);
    unsigned owner = 0, task = 0; int fd = -1, end = 0;
    if (std::sscanf(path.c_str(), "/proc/%u/task/%u/fd/%d%n", &owner, &task, &fd, &end) != 3) {
        end = 0;
        if (std::sscanf(path.c_str(), "/proc/%u/fd/%d%n", &owner, &fd, &end) != 2) return {};
        task = owner;
    }
    if (path[static_cast<size_t>(end)] != '\0' || tgid(owner) != tgid(request.pid) || tgid(task) != tgid(request.pid)) return {};
    const std::string source = snapshot_source(task, fd);
    if (!source.empty() || !device_alias) return source;
    if (cpu_descriptor(task, fd)) return "/proc/cpuinfo";
    // Keep the original descriptor and its I/O; only the scoped diagnostic link label changes.
    const std::string target = read_link(proc_base(task) + "/fd/" + std::to_string(fd));
    if (target == "/dev/goldfish_pipe_dprctd") return "/dev/graphics/channel";
    if (target == "/dev/goldfish_sync") return "/dev/graphics/sync";
    return {};
}
std::string fdinfo_source(const seccomp_notif& request, const std::string& path) {
    unsigned owner = 0, task = 0; int fd = -1, end = 0;
    if (std::sscanf(path.c_str(), "/proc/%u/task/%u/fdinfo/%d%n", &owner, &task, &fd, &end) != 3) {
        end = 0;
        if (std::sscanf(path.c_str(), "/proc/%u/fdinfo/%d%n", &owner, &fd, &end) != 2) return {};
        task = owner;
    }
    if (path[static_cast<size_t>(end)] != '\0' || tgid(owner) != tgid(request.pid) || tgid(task) != tgid(request.pid)) return {};
    return snapshot_source(task, fd);
}
uint64_t proc_mount_id(uint32_t pid) {
    FILE* file = fopen((proc_base(pid) + "/mountinfo").c_str(), "re");
    if (!file) return 0;
    char* line = nullptr; size_t capacity = 0; uint64_t result = 0;
    while (getline(&line, &capacity, file) >= 0) {
        unsigned long long id = 0; char point[PATH_MAX]{};
        if (std::sscanf(line, "%llu %*u %*s %*s %4095s", &id, point) == 2 && std::strcmp(point, "/proc") == 0) { result = id; break; }
    }
    free(line); fclose(file);
    return result;
}
bool artifact(std::string_view line) {
    // tm: 追加 MuMu/网易系与它自家的 native bridge 名（真机都没有）
    if (line.find("nemu") != std::string_view::npos ||
        line.find("mumu") != std::string_view::npos ||
        line.find("netease") != std::string_view::npos ||
        line.find("libnb.so") != std::string_view::npos) {
        return true;
    }
    return line.find("libndk_translation") != std::string_view::npos || line.find("libhoudini") != std::string_view::npos
            || line.find("/dev.androidlab.module-") != std::string_view::npos
            || line.find("/android.hardware.graphics.mapper@3.0-impl-ranchu.so") != std::string_view::npos;
}
std::string filter(const std::string& text, const std::string& view) {
    std::string result;
    bool omit = false;
    size_t position = 0;
    while (position < text.size()) {
        size_t end = text.find('\n', position);
        if (end == std::string::npos) end = text.size(); else ++end;
        const std::string_view line(text.data() + position, end - position);
        if (view == "smaps") {
            unsigned long long first = 0, last = 0;
            char permissions[5]{};
            if (std::sscanf(std::string(line).c_str(), "%llx-%llx %4s", &first, &last, permissions) == 3) omit = artifact(line);
        } else omit = artifact(line) || ((view == "mountinfo" || view == "mounts")
                && (line.find(" /proc/cpuinfo ") != std::string_view::npos || line.find("/adb/modules/device_lab_cpu/") != std::string_view::npos
                    || line.find("/misc/device-lab/") != std::string_view::npos));
        if (!omit) result.append(line);
        position = end;
    }
    return result;
}
int make_snapshot(const seccomp_notif& request, const std::string& source_path, const std::string& view, int flags, int listener) {
    // Only the requester's own proc records are opened with supervisor credentials.
    const int source = open(source_path.c_str(), O_RDONLY | O_CLOEXEC);
    if (source < 0) return -1;
    if (!notification_valid(listener, request.id)) { close(source); return -1; }
    std::string text;
    char buffer[16384];
    ssize_t count;
    while ((count = read(source, buffer, sizeof(buffer))) > 0) {
        text.append(buffer, static_cast<size_t>(count));
        if (text.size() > 8 * 1024 * 1024) { count = -1; break; }
    }
    close(source);
    if (count < 0 || text.empty()) return -1;
    int info_fd = -1;
    if (view == "fdinfo") {
        const std::string original = fdinfo_source(request, source_path);
        struct stat stats{};
        const uint64_t mount_id = proc_mount_id(request.pid);
        if (original.empty() || stat(original.c_str(), &stats) != 0 || mount_id == 0) return -1;
        std::string normalized;
        size_t position = 0;
        while (position < text.size()) {
            size_t end = text.find('\n', position); if (end == std::string::npos) end = text.size(); else ++end;
            const std::string line = text.substr(position, end - position);
            if (line.compare(0, 7, "mnt_id:") == 0) normalized += "mnt_id:\t" + std::to_string(mount_id) + "\n";
            else if (line.compare(0, 4, "ino:") == 0) normalized += "ino:\t" + std::to_string(stats.st_ino) + "\n";
            else normalized += line;
            position = end;
        }
        text = normalized;
        info_fd = std::atoi(source_path.c_str() + source_path.find_last_of('/') + 1);
    } else text = filter(text, view);
    if (text.empty()) return -1;
    unsigned owner = 0, task = 0;
    if (std::sscanf(source_path.c_str(), "/proc/%u/task/%u/", &owner, &task) != 2) {
        if (std::sscanf(source_path.c_str(), "/proc/%u/", &owner) != 1) return -1;
        task = 0;
    }
    std::string path = "/data/misc/device-lab/proc-broker-" + view + "." + std::to_string(owner) + "." + std::to_string(task)
            + (info_fd >= 0 ? "." + std::to_string(info_fd) : "") + ".XXXXXX";
    const int writable = mkostemp(path.data(), O_CLOEXEC);
    if (writable < 0) return -1;
    constexpr char context[] = "u:object_r:system_file:s0";
    bool ok = fchmod(writable, 0444) == 0 && fsetxattr(writable, "security.selinux", context, sizeof(context), 0) == 0;
    size_t position = 0;
    while (ok && position < text.size()) {
        const ssize_t written = write(writable, text.data() + position, text.size() - position);
        if (written < 0 && errno == EINTR) continue;
        if (written <= 0) ok = false; else position += static_cast<size_t>(written);
    }
    close(writable);
    const int result = ok ? open(path.c_str(), (flags & ~O_CLOEXEC) | O_CLOEXEC) : -1;
    unlink(path.c_str());
    return result;
}
int copied(const seccomp_notif& request, seccomp_notif_resp& response, int listener,
           uint64_t address, const void* data, size_t size, long value = 0) {
    const int error = write_notification_memory(request, listener, address, data, size);
    if (error == EAGAIN) return 0;
    response.error = -error;
    response.val = error == 0 ? value : 0;
    return 1;
}

bool map_directory(const seccomp_notif& request, const std::string& path) {
    unsigned owner = 0, task = 0; int end = 0;
    if (std::sscanf(path.c_str(), "/proc/%u/task/%u/map_files%n", &owner, &task, &end) != 2 || end == 0) {
        end = 0;
        if (std::sscanf(path.c_str(), "/proc/%u/map_files%n", &owner, &end) != 1 || end == 0) return false;
        task = owner;
    }
    return path[static_cast<size_t>(end)] == '\0' && tgid(owner) == tgid(request.pid) && tgid(task) == tgid(request.pid);
}
std::unordered_set<std::string> hidden_map_ranges(uint32_t pid) {
    std::unordered_set<std::string> result;
    FILE* file = fopen((proc_base(pid) + "/maps").c_str(), "re");
    if (!file) return result;
    char* line = nullptr; size_t size = 0;
    while (getline(&line, &size, file) >= 0) {
        const std::string_view record(line);
        if (artifact(record)) result.emplace(record.substr(0, record.find(' ')));
    }
    free(line); fclose(file);
    return result;
}
int map_entries(const seccomp_notif& request, seccomp_notif_resp& response, int listener) {
    const int fd = static_cast<int>(request.data.args[0]);
    const std::string path = read_link(proc_base(request.pid) + "/fd/" + std::to_string(fd));
    if (!map_directory(request, path)) return 0;
    const uint64_t size = request.data.args[2];
    if (size == 0 || size > 1024 * 1024) return 0;
    const int group = tgid(request.pid);
    // pidfd_getfd selects the group leader's table. Verify that it is shared.
    if (syscall(SYS_kcmp, request.pid, group, KCMP_FILES, 0, 0) != 0) return 0;
    const int process = static_cast<int>(syscall(SYS_pidfd_open, group, 0));
    if (process < 0) return 0;
    const int duplicate = static_cast<int>(syscall(SYS_pidfd_getfd, process, fd, 0));
    close(process);
    if (duplicate < 0) return 0;
    if (!notification_valid(listener, request.id)) { close(duplicate); return 1; }
    const off_t initial = lseek(duplicate, 0, SEEK_CUR);
    if (initial < 0) { close(duplicate); return 0; }
    const auto hidden = hidden_map_ranges(request.pid);
    struct Entry { uint64_t inode; int64_t offset; unsigned short length; unsigned char type; char name[1]; };
    std::vector<char> buffer(static_cast<size_t>(size));
    long count = 0; size_t kept = 0;
    do {
        count = syscall(SYS_getdents64, duplicate, buffer.data(), buffer.size());
        if (count <= 0) break;
        kept = 0;
        size_t offset = 0;
        while (offset < static_cast<size_t>(count)) {
            const auto* entry = reinterpret_cast<const Entry*>(buffer.data() + offset);
            if (entry->length < 20 || offset + entry->length > static_cast<size_t>(count)) { count = -1; errno = EIO; break; }
            const size_t length = entry->length;
            if (hidden.find(entry->name) == hidden.end()) { std::memmove(buffer.data() + kept, entry, length); kept += length; }
            offset += length;
        }
    } while (count > 0 && kept == 0);
    const int error = errno;
    if (count < 0) { close(duplicate); response.error = -error; return 1; }
    if (kept > 0) {
        size_t offset = 0;
        Entry* last = nullptr;
        while (offset < kept) { last = reinterpret_cast<Entry*>(buffer.data() + offset); offset += last->length; }
        // The last visible cookie must include any omitted trailing entries.
        if (last) last->offset = lseek(duplicate, 0, SEEK_CUR);
    }
    const int handled = copied(request, response, listener, request.data.args[1], buffer.data(), kept, static_cast<long>(kept));
    // A rejected output buffer must not consume the caller's directory stream.
    if (handled == 0 || response.error != 0) lseek(duplicate, initial, SEEK_SET);
    close(duplicate);
    return handled;
}
}

int handle_proc_notification(const seccomp_notif& request, seccomp_notif_resp& response, int listener) {
    const auto& args = request.data.args;
    const int number = request.data.nr;
    if (number == SYS_openat || number == SYS_open || number == SYS_openat2) {
        const bool at = number != SYS_open;
        int flags = static_cast<int>(args[at ? 2 : 1]);
        if (number == SYS_openat2) {
            if (args[3] != sizeof(open_how) || args[2] > static_cast<uint64_t>(std::numeric_limits<off_t>::max())) return 0;
            const int memory = open((proc_base(request.pid) + "/mem").c_str(), O_RDONLY | O_CLOEXEC);
            if (memory < 0) return 0;
            open_how how{};
            const ssize_t size = notification_valid(listener, request.id) ? pread(memory, &how, sizeof(how), static_cast<off_t>(args[2])) : -1;
            close(memory);
            if (size != sizeof(how) || how.mode != 0 || how.resolve != 0 || how.flags > static_cast<uint64_t>(std::numeric_limits<int>::max())) return 0;
            flags = static_cast<int>(how.flags);
        }
        constexpr int allowed = O_CLOEXEC | O_NONBLOCK | O_LARGEFILE | O_NOFOLLOW | O_NOCTTY | O_NOATIME;
        if ((flags & ~allowed) != 0) return 0;
        const std::string input = request_string(request, listener, args[at ? 1 : 0]);
        if ((flags & O_NOFOLLOW) != 0) {
            const std::string final = link_path(request, at ? static_cast<int>(args[0]) : AT_FDCWD, input);
            struct stat entry{};
            if (final.empty() || lstat(final.c_str(), &entry) != 0 || S_ISLNK(entry.st_mode)) return 0;
        }
        const std::string source = full_path(request, at ? static_cast<int>(args[0]) : AT_FDCWD, input);
        const std::string view = fdinfo_source(request, source).empty() ? own_view(request, source) : "fdinfo";
        if (view.empty()) return 0;
        const int snapshot = make_snapshot(request, source, view, flags, listener);
        if (snapshot < 0) return 0;
        seccomp_notif_addfd injection{};
        injection.id = request.id;
        injection.flags = SECCOMP_ADDFD_FLAG_SEND;
        injection.srcfd = snapshot;
        injection.newfd_flags = flags & O_CLOEXEC;
        int fd;
        do { fd = ioctl(listener, SECCOMP_IOCTL_NOTIF_ADDFD, &injection); } while (fd < 0 && errno == EINTR && notification_valid(listener, request.id));
        const int error = errno;
        close(snapshot);
        if (fd < 0) __android_log_print(ANDROID_LOG_WARN, "DeviceLabProcBroker", "ADDFD %s failed: %d", view.c_str(), error);
        return fd >= 0 ? 2 : 0;
    }
    if (number == SYS_getdents64) return map_entries(request, response, listener);
    if (number == SYS_mmap) {
        const std::string source = snapshot_source(request.pid, static_cast<int>(args[4]));
        if (source.empty() || args[2] != PROT_READ || (args[3] != MAP_PRIVATE && args[3] != MAP_SHARED)) return 0;
        const int fd = open(source.c_str(), O_RDONLY | O_CLOEXEC);
        if (fd < 0) return 0;
        void* mapped = mmap(nullptr, args[1], PROT_READ, static_cast<int>(args[3]), fd, static_cast<off_t>(args[5]));
        const int error = errno;
        close(fd);
        if (mapped != MAP_FAILED) { munmap(mapped, args[1]); return 0; }
        response.error = -error;
        return 1;
    }
    if (number == SYS_statx) {
        bool valid = false;
        const std::string path = request_string(request, listener, args[1], &valid);
        if (!valid) return 0;
        const int flags = static_cast<int>(args[2]);
        constexpr int allowed = AT_EMPTY_PATH | AT_SYMLINK_NOFOLLOW | AT_NO_AUTOMOUNT | AT_STATX_SYNC_TYPE;
        if ((flags & ~allowed) != 0) return 0;
        const std::string source = (flags & AT_EMPTY_PATH) != 0 && path.empty() ? snapshot_source(request.pid, static_cast<int>(args[0]))
                : (flags & AT_SYMLINK_NOFOLLOW) == 0 ? descriptor_source(request, static_cast<int>(args[0]), path) : std::string{};
        if (source.empty()) return 0;
        struct statx stats{};
        if (syscall(SYS_statx, AT_FDCWD, source.c_str(), flags & ~AT_EMPTY_PATH, args[3], &stats) != 0) { response.error = -errno; return 1; }
        if ((stats.stx_mask & STATX_MNT_ID) != 0) {
            const uint64_t id = proc_mount_id(request.pid);
            if (id == 0) return 0;
            stats.stx_mnt_id = id;
        }
        return copied(request, response, listener, args[4], &stats, sizeof(stats));
    }
    if (number == SYS_stat || number == SYS_statfs) {
        const std::string path = request_string(request, listener, args[0]);
        const std::string source = descriptor_source(request, AT_FDCWD, path);
        if (source.empty()) return 0;
        if (number == SYS_statfs) {
            struct statfs stats{};
            if (statfs(source.c_str(), &stats) != 0) return 0;
            return copied(request, response, listener, args[1], &stats, sizeof(stats));
        }
        struct stat stats{};
        if (stat(source.c_str(), &stats) != 0) return 0;
        return copied(request, response, listener, args[1], &stats, sizeof(stats));
    }
    if (number == SYS_fstatfs || number == SYS_fstat || number == SYS_newfstatat) {
        const int fd = static_cast<int>(args[0]);
        if (number == SYS_fstatfs && cpu_descriptor(request.pid, fd)) {
            struct statfs stats{};
            if (statfs("/proc", &stats) != 0) return 0;
            return copied(request, response, listener, args[1], &stats, sizeof(stats));
        }
        std::string source;
        if (number == SYS_newfstatat) {
            bool valid = false;
            const std::string path = request_string(request, listener, args[1], &valid);
            if (!valid) return 0;
            if (args[3] == AT_EMPTY_PATH && path.empty()) source = snapshot_source(request.pid, fd);
            else if (args[3] == 0 && !path.empty()) source = descriptor_source(request, fd, path);
            else return 0;
        } else source = snapshot_source(request.pid, fd);
        if (source.empty()) return 0;
        if (number == SYS_fstatfs) {
            struct statfs stats{};
            if (statfs(source.c_str(), &stats) != 0) return 0;
            return copied(request, response, listener, args[1], &stats, sizeof(stats));
        }
        struct stat stats{};
        if (stat(source.c_str(), &stats) != 0) return 0;
        return copied(request, response, listener, args[number == SYS_fstat ? 1 : 2], &stats, sizeof(stats));
    }
    if (number == SYS_readlinkat || number == SYS_readlink) {
        const bool at = number == SYS_readlinkat;
        const std::string input = request_string(request, listener, args[at ? 1 : 0]);
        const std::string link = link_path(request, at ? static_cast<int>(args[0]) : AT_FDCWD, input);
        const size_t slash = link.find_last_of('/');
        if (slash != std::string::npos && map_directory(request, link.substr(0, slash))) {
            if (artifact(read_link(link))) {
                response.error = static_cast<int>(args[at ? 3 : 2]) <= 0 ? -EINVAL : -ENOENT;
                return 1;
            }
        }
        const std::string target = descriptor_source(request, at ? static_cast<int>(args[0]) : AT_FDCWD, input, true);
        if (target.empty()) return 0;
        const int size = static_cast<int>(args[at ? 3 : 2]);
        if (size <= 0) { response.error = -EINVAL; return 1; }
        const size_t count = static_cast<size_t>(size) < target.size() ? static_cast<size_t>(size) : target.size();
        return copied(request, response, listener, args[at ? 2 : 1], target.data(), count, static_cast<long>(count));
    }
    return 0;
}
