// 测试用：极小的 LD_PRELOAD 载体（用来验证 wrap.<pkg> 注入是否可行）。
//
// 为什么值得先测这个：本机 Android 15 镜像自带的 native-bridge 是 v2、而系统要 v3，
// 于是 Zygisk 在所有 App 进程都起不来（任何 Zygisk 模块都白装）。
// Android 本身支持 `setprop wrap.<pkg> "LD_PRELOAD=/path/lib.so"`（调试用途），
// 这条路不经过 Zygisk —— 如果它通，我们的 seccomp 代理可以直接挂在 App 进程里。
#include <android/log.h>
#include <stdio.h>
#include <unistd.h>

#define TAG "maps_cloak"

__attribute__((constructor)) static void on_load(void) {
    __android_log_print(ANDROID_LOG_INFO, TAG, "PRELOAD OK pid=%d", getpid());
    FILE *f = fopen("/data/local/tmp/maps_cloak_preload.txt", "a");
    if (f) {
        fprintf(f, "loaded pid=%d\n", getpid());
        fclose(f);
    }
}
