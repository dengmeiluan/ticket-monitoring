// maps_cloak：让指定 App 读自己 /proc/self/maps 时看不到 houdini/nemu 痕迹。
//
// 设计见 docs/superpowers/specs/2026-11-08-maps-cloak-design.md
// 步骤见 docs/superpowers/plans/2026-11-08-maps-cloak.md
//
// 本文件（Task 3 阶段）只做"注入 + 读配置 + 打日志"，用来先证明：
//   1. 模块能被 Zygisk 注入目标 App；
//   2. 作用域名单（packages）判定正确。
// seccomp 过滤器在 Task 4 接入（vendor/nerium 的 proc_broker）。
#include <android/log.h>
#include <jni.h>

#include <unistd.h>

#include <cstring>
#include <string>
#include <vector>

#include "zygisk.hpp"

#define LOG_TAG "maps_cloak"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, LOG_TAG, __VA_ARGS__)
#define LOGW(...) __android_log_print(ANDROID_LOG_WARN, LOG_TAG, __VA_ARGS__)

using zygisk::Api;
using zygisk::AppSpecializeArgs;
using zygisk::Option;

// 与 config/global.json 的 packages 保持一致（Task 4 改成从文件读）。
static const char *kPackages[] = {
    "com.taobao.trip",
};

static bool in_scope(const std::string &pkg) {
    for (const char *p : kPackages) {
        if (pkg == p) return true;
    }
    return false;
}

class MapsCloak : public zygisk::ModuleBase {
public:
    void onLoad(Api *api, JNIEnv *env) override {
        api_ = api;
        env_ = env;
    }

    void preAppSpecialize(AppSpecializeArgs *args) override {
        // 注意：**不要**在这里调 setOption(DLCLOSE_MODULE_LIBRARY) ——
        // 它会让 Zygisk 立刻 dlclose 本模块的 .so，之后继续执行模块代码必然 SIGSEGV
        // （实测：留下 zygisk/unloaded 标记、日志一行都打不出来）。
        // Task 4 需要模块常驻做 seccomp 代理，本来也不该卸载。
        std::string pkg;
        if (args != nullptr && args->nice_name != nullptr) {
            const char *c = env_->GetStringUTFChars(args->nice_name, nullptr);
            if (c != nullptr) {
                pkg = c;
                env_->ReleaseStringUTFChars(args->nice_name, c);
            }
        }
        LOGI("injected pkg=%s pid=%d in_scope=%d", pkg.c_str(), getpid(),
             in_scope(pkg) ? 1 : 0);
    }

private:
    Api *api_ = nullptr;
    JNIEnv *env_ = nullptr;
};

REGISTER_ZYGISK_MODULE(MapsCloak)
