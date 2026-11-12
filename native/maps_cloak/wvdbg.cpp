// wvdbg：强制打开宿主 App 的 WebView 远程调试（用于**测量**它内部的真实指纹）。
//
// 背景：飞猪机票页一加载就被阿里 NC 下发「通过验证以确保正常访问」拦截页，人手拖也失败；
// 而同 IP、未登录的**浏览器**通路能正常出数 → 被针对的是 App 内的 WebView 环境。
// 要看它到底露出什么，就得能在这个 WebView 上执行 JS。
//
// 做法：LD_PRELOAD 进 App 进程后，起一个线程等 Application 就绪，再用 JNI 调
// `android.webkit.WebView.setWebContentsDebuggingEnabled(true)`（公开 API）。
// 之后 `chrome://inspect` 那套 devtools socket 就会出现，Playwright 可直连。
//
// 注意：本文件只用于**取证**，不改变页面行为；用完把 wrap 撤掉即可。
#define _GNU_SOURCE
#include <android/log.h>
#include <dlfcn.h>
#include <jni.h>
#include <pthread.h>
#include <unistd.h>

#define TAG "maps_cloak"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, TAG, __VA_ARGS__)

typedef jint (*get_vms_fn)(JavaVM **, jsize, jsize *);

static void *enable_debug(void *arg) {
    (void) arg;
    // 等 App 把 Application / ActivityThread 初始化好
    sleep(4);
    auto get_vms = (get_vms_fn) dlsym(RTLD_DEFAULT, "JNI_GetCreatedJavaVMs");
    if (get_vms == nullptr) {
        LOGI("wvdbg: JNI_GetCreatedJavaVMs 找不到");
        return nullptr;
    }
    JavaVM *vm = nullptr;
    jsize n = 0;
    if (get_vms(&vm, 1, &n) != JNI_OK || vm == nullptr || n == 0) {
        LOGI("wvdbg: 拿不到 JavaVM");
        return nullptr;
    }
    JNIEnv *env = nullptr;
    if (vm->AttachCurrentThread(&env, nullptr) != JNI_OK || env == nullptr) {
        LOGI("wvdbg: AttachCurrentThread 失败");
        return nullptr;
    }
    jclass wv = env->FindClass("android/webkit/WebView");
    if (wv == nullptr) {
        env->ExceptionClear();
        LOGI("wvdbg: 找不到 WebView 类");
        vm->DetachCurrentThread();
        return nullptr;
    }
    jmethodID m = env->GetStaticMethodID(
        wv, "setWebContentsDebuggingEnabled", "(Z)V");
    if (m == nullptr) {
        env->ExceptionClear();
        LOGI("wvdbg: 找不到 setWebContentsDebuggingEnabled");
        vm->DetachCurrentThread();
        return nullptr;
    }
    env->CallStaticVoidMethod(wv, m, JNI_TRUE);
    if (env->ExceptionCheck()) {
        env->ExceptionDescribe();
        env->ExceptionClear();
        LOGI("wvdbg: 调用抛异常");
    } else {
        LOGI("wvdbg: 已开启 WebView 远程调试 pid=%d", getpid());
    }
    vm->DetachCurrentThread();
    return nullptr;
}

__attribute__((constructor)) static void on_load(void) {
    pthread_t th;
    if (pthread_create(&th, nullptr, enable_debug, nullptr) == 0) {
        pthread_detach(th);
    }
    LOGI("wvdbg: preloaded pid=%d", getpid());
}
