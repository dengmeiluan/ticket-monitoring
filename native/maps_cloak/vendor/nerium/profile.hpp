#pragma once

#include <cstring>

namespace device_lab {
inline constexpr char profile_directory[] = "/data/misc/device-lab";
// Captured from the stock API 34 image's ARM native-bridge view, not physical hardware.
inline constexpr char arm64_cpuinfo[] =
    "processor\t: 1\nBogoMIPS\t: 1.00\n"
    "Features\t: fp asimd evtstrm aes pmull sha1 sha2 crc32 atomics fphp asimdhp\n"
    "CPU implementer\t: 0x41\nCPU architecture: 8\nCPU variant\t: 0x6\n"
    "CPU part\t: 0x802\nCPU revision\t: 13\n";

struct Property { const char* name; const char* value; };

inline constexpr Property properties[] = {
    {"ro.product.manufacturer", "Google"}, {"ro.product.brand", "google"},
    {"ro.product.model", "Pixel 8"}, {"ro.product.device", "shiba"},
    {"ro.product.name", "shiba"}, {"ro.hardware", "shiba"},
    {"ro.product.board", "zuma"}, {"ro.kernel.qemu", "0"}, {"ro.boot.qemu", "0"},
    {"ro.boot.hardware", "shiba"}, {"ro.boot.qemu.avd_name", ""},
    {"ro.build.fingerprint", "google/shiba/shiba:14/AP1A.240505.005/11677807:user/release-keys"},
    {"ro.build.id", "AP1A.240505.005"}, {"ro.build.type", "user"},
    {"ro.build.tags", "release-keys"}, {"ro.build.version.incremental", "11677807"},
    {"ro.product.cpu.abilist", "arm64-v8a"}, {"ro.product.cpu.abilist64", "arm64-v8a"},
    {"ro.product.cpu.abilist32", ""}, {"ro.dalvik.vm.native.bridge", "0"},
    {"ro.dalvik.vm.isa.arm", ""}, {"ro.dalvik.vm.isa.arm64", ""}
};

inline const char* replacement_property(const char* name) {
    if (name == nullptr) return nullptr;
    for (const auto& property : properties) {
        if (std::strcmp(name, property.name) == 0) return property.value;
    }
    return nullptr;
}
}
