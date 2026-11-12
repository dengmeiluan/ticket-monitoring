#include <sys/types.h>
#include "vendor/zygisk.hpp"
#include "policy_gate.hpp"
#include <android/log.h>
#include <linux/audit.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <fcntl.h>
#include <unistd.h>
#include <array>
#include <cerrno>
#include <cstddef>
#include <cstring>

extern "C" {
void* device_lab_policy_prctl = nullptr;
void device_lab_policy_entry();
}
namespace {
constexpr size_t capacity = 4096;
std::array<sock_filter, capacity> before{}, after{};
size_t source_size = 0;
struct stat runtime{};
bool hooked = false;

void save(const std::string& path, const sock_filter* data, size_t size) {
    const int fd = open(path.c_str(), O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0600);
    if (fd < 0) return;
    const auto* bytes = reinterpret_cast<const char*>(data);
    size_t offset = 0;
    while (offset < size) {
        const ssize_t count = write(fd, bytes + offset, size - offset);
        if (count < 0 && errno == EINTR) continue;
        if (count <= 0) break;
        offset += static_cast<size_t>(count);
    }
    close(fd);
}
}

extern "C" int device_lab_install_policy(int option, unsigned long mode, const sock_fprog* program) {
    const auto original = reinterpret_cast<int (*)(int, ...)>(device_lab_policy_prctl);
    if (!original) { errno = ENOSYS; return -1; }
    // Retain the entire original program, including architecture and UID checks.
    if (!program || !program->filter || program->len == 0 || program->len > capacity - 5
            || program->filter[0].code != (BPF_LD | BPF_W | BPF_ABS)
            || program->filter[0].k != offsetof(seccomp_data, arch)) return original(option, mode, program);
    bool trap = false;
    for (size_t i = 0; i < program->len; ++i)
        trap |= program->filter[i].code == (BPF_RET | BPF_K) && program->filter[i].k == SECCOMP_RET_TRAP;
    if (!trap) return original(option, mode, program);
    const sock_filter prefix[] = {
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(seccomp_data, arch)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, AUDIT_ARCH_X86_64, 0, 3),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(seccomp_data, nr)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_openat2, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
    };
    std::memcpy(before.data(), program->filter, program->len * sizeof(sock_filter));
    std::memcpy(after.data(), prefix, sizeof(prefix));
    std::memcpy(after.data() + 5, program->filter, program->len * sizeof(sock_filter));
    sock_fprog patched{static_cast<unsigned short>(program->len + 5), after.data()};
    const int result = original(option, mode, &patched);
    const int error = errno;
    if (result == 0) source_size = program->len;
    __android_log_print(result == 0 ? ANDROID_LOG_INFO : ANDROID_LOG_ERROR, "DeviceLabPolicy",
                        "openat2 policy status=%d source_length=%u original_suffix_preserved=1", result == 0 ? 0 : error, program->len);
    errno = error;
    return result;
}

bool install_openat2_policy(zygisk::Api* api) {
    if (stat("/system/lib64/libandroid_runtime.so", &runtime) != 0) return false;
    api->pltHookRegister(runtime.st_dev, runtime.st_ino, "prctl", reinterpret_cast<void*>(device_lab_policy_entry), &device_lab_policy_prctl);
    hooked = api->pltHookCommit() && device_lab_policy_prctl != nullptr;
    return hooked;
}
bool restore_openat2_policy(zygisk::Api* api) {
    if (!hooked) return true;
    api->pltHookRegister(runtime.st_dev, runtime.st_ino, "prctl", device_lab_policy_prctl, nullptr);
    const bool restored = api->pltHookCommit();
    if (restored) hooked = false;
    __android_log_print(restored ? ANDROID_LOG_INFO : ANDROID_LOG_ERROR, "DeviceLabPolicy", "policy PLT restored=%d", restored);
    return restored;
}
void save_openat2_policy(const std::string& directory) {
    if (!source_size) return;
    const std::string cache = directory + "/cache";
    if (mkdir(cache.c_str(), 0700) != 0 && errno != EEXIST) return;
    save(cache + "/device-lab-seccomp-before.bin", before.data(), source_size * sizeof(sock_filter));
    save(cache + "/device-lab-seccomp-after.bin", after.data(), (source_size + 5) * sizeof(sock_filter));
}
