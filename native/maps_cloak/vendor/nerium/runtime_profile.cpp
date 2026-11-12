#include <jni.h>
#include <android/log.h>
#include <dlfcn.h>
#include <elf.h>
#include <EGL/egl.h>
#include <GLES2/gl2.h>
#include <sys/auxv.h>
#include <unistd.h>
#include "vendor/zygisk.hpp"

#include <array>
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <map>
#include <mutex>
#include <string>

namespace {
using GlString = const GLubyte* (*)(GLenum);
GlString original_string = nullptr;
std::array<Elf64_auxv_t, 130> auxiliary{};
constexpr char platform[] = "aarch64";
using SensorAtIndex = jboolean (*)(JNIEnv*, jclass, jlong, jobject, jint);
SensorAtIndex original_sensor = nullptr;
std::string module_apk;
bool guest_ready = false;
thread_local bool guest_initializing = false;
std::mutex guest_mutex;

bool configure_guest(JNIEnv* env) {
    const char* arm = std::getenv("DEVICE_LAB_ARM_GUEST");
    if (!arm || std::strcmp(arm, "1") != 0) return true;
    if (guest_initializing || module_apk.empty()) return false;
    std::lock_guard<std::mutex> lock(guest_mutex);
    if (guest_ready) return true;
    guest_initializing = true;
    struct Reset { ~Reset() { guest_initializing = false; } } reset;
    jclass loader_class = env->FindClass("dalvik/system/PathClassLoader");
    jclass class_loader = env->FindClass("java/lang/ClassLoader");
    jclass runtime = env->FindClass("java/lang/Runtime");
    if (!loader_class || !class_loader || !runtime) return false;
    jmethodID constructor = env->GetMethodID(loader_class, "<init>",
            "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/ClassLoader;)V");
    jmethodID system_loader = env->GetStaticMethodID(class_loader, "getSystemClassLoader", "()Ljava/lang/ClassLoader;");
    jmethodID load_class = env->GetMethodID(class_loader, "loadClass", "(Ljava/lang/String;)Ljava/lang/Class;");
    if (!constructor || !system_loader || !load_class) return false;
    jobject parent = env->CallStaticObjectMethod(class_loader, system_loader);
    jstring apk = env->NewStringUTF(module_apk.c_str());
    jstring search = env->NewStringUTF((module_apk + "!/lib/arm64-v8a").c_str());
    jobject loader = env->NewObject(loader_class, constructor, apk, search, parent);
    if (!loader || env->ExceptionCheck()) return false;
    jstring class_name = env->NewStringUTF("dev.androidlab.module.GuestProfile");
    auto guest = static_cast<jclass>(env->CallObjectMethod(loader, load_class, class_name));
    if (!guest || env->ExceptionCheck()) return false;
    jstring library = env->NewStringUTF((module_apk + "!/lib/arm64-v8a/libguestprofile.so").c_str());
    jmethodID native_load = env->GetStaticMethodID(runtime, "nativeLoad", "(Ljava/lang/String;Ljava/lang/ClassLoader;Ljava/lang/Class;)Ljava/lang/String;");
    auto error = native_load ? static_cast<jstring>(env->CallStaticObjectMethod(runtime, native_load, library, loader, guest)) : nullptr;
    if (error || env->ExceptionCheck()) {
        if (error) {
            const char* text = env->GetStringUTFChars(error, nullptr);
            if (text) { __android_log_print(ANDROID_LOG_WARN, "DeviceLabRuntime", "guest load: %s", text); env->ReleaseStringUTFChars(error, text); }
        }
        return false;
    }
    jmethodID configure = env->GetStaticMethodID(guest, "configurePlatform", "()Ljava/lang/String;");
    auto result = configure ? static_cast<jstring>(env->CallStaticObjectMethod(guest, configure)) : nullptr;
    if (!result || env->ExceptionCheck()) return false;
    const char* text = env->GetStringUTFChars(result, nullptr);
    if (text) {
        guest_ready = std::strcmp(text, "configured") == 0 || std::strcmp(text, "already_configured") == 0;
        __android_log_print(guest_ready ? ANDROID_LOG_INFO : ANDROID_LOG_WARN, "DeviceLabRuntime", "guest auxv: %s", text);
        env->ReleaseStringUTFChars(result, text);
    }
    if (guest_ready) env->NewGlobalRef(loader);
    return guest_ready;
}

void try_guest(JNIEnv* env) {
    configure_guest(env);
    if (env->ExceptionCheck()) { env->ExceptionDescribe(); env->ExceptionClear(); }
}

jboolean sensor_profile(JNIEnv* env, jclass type, jlong manager, jobject sensor, jint index) {
    if (!original_sensor || original_sensor == sensor_profile) {
        env->ThrowNew(env->FindClass("java/lang/IllegalStateException"), "Original sensor JNI entry unavailable");
        return false;
    }
    const jboolean result = original_sensor(env, type, manager, sensor, index);
    if (!result || env->ExceptionCheck()) return result;
    jclass sensor_class = env->GetObjectClass(sensor);
    for (const char* field_name : {"mName", "mVendor"}) {
        jfieldID field = env->GetFieldID(sensor_class, field_name, "Ljava/lang/String;");
        if (!field) break;
        auto value = static_cast<jstring>(env->GetObjectField(sensor, field));
        if (!value) continue;
        const char* text = env->GetStringUTFChars(value, nullptr);
        if (!text) break;
        const char* replacement = nullptr;
        if (std::strcmp(field_name, "mName") == 0 && std::strncmp(text, "Goldfish ", 9) == 0) replacement = text + 9;
        if (std::strcmp(field_name, "mVendor") == 0 && (std::strcmp(text, "AOSP") == 0
                || std::strcmp(text, "The Android Open Source Project") == 0)) replacement = "Google";
        if (replacement) {
            jstring label = env->NewStringUTF(replacement);
            env->SetObjectField(sensor, field, label);
            env->DeleteLocalRef(label);
        }
        env->ReleaseStringUTFChars(value, text);
        env->DeleteLocalRef(value);
    }
    env->DeleteLocalRef(sensor_class);
    return result;
}

const GLubyte* graphics_string(GLenum name) {
    const GLubyte* value = original_string(name);
    if (!value) return nullptr;
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
        return reinterpret_cast<const GLubyte*>(version.c_str());
    }
    return value;
}

bool configure_graphics() {
    // The pinned API 34 wrappers call a shared data slot, not an inline trampoline.
    void* gles = dlopen("libGLESv2.so", RTLD_NOW | RTLD_LOCAL);
    void* egl = dlopen("libEGL.so", RTLD_NOW | RTLD_LOCAL);
    if (!gles || !egl) return false;
    const auto* getter = static_cast<const unsigned char*>(dlsym(gles, "glGetString"));
    constexpr unsigned char prefix[] = {0x53, 0x89, 0xfb, 0xe8};
    constexpr unsigned char suffix[] = {0x89, 0xdf, 0x5b, 0xff, 0xa0, 0x10, 0x05, 0, 0};
    if (!getter || std::memcmp(getter, prefix, sizeof(prefix)) != 0
            || std::memcmp(getter + 8, suffix, sizeof(suffix)) != 0) return false;
    using Connection = unsigned char* (*)();
    auto connection = reinterpret_cast<Connection>(dlsym(egl, "_ZN7android18egl_get_connectionEv"));
    if (!connection || eglGetDisplay(EGL_DEFAULT_DISPLAY) == EGL_NO_DISPLAY) return false;
    auto** slot = reinterpret_cast<GlString*>(connection() + 0x510);
    Dl_info target{};
    if (!*slot || !dladdr(reinterpret_cast<void*>(*slot), &target) || !target.dli_fname
            || std::strstr(target.dli_fname, "/libEGL.so") == nullptr) return false;
    original_string = *slot;
    __atomic_store_n(slot, graphics_string, __ATOMIC_RELEASE);
    return true;
}

bool configure_auxiliary() {
    const auto* getter = static_cast<const unsigned char*>(dlsym(RTLD_DEFAULT, "getauxval"));
    constexpr unsigned char prefix[] = {0x53, 0x48, 0x89, 0xfb, 0xe8};
    constexpr unsigned char load[] = {0x48, 0x8b, 0x80, 0x18, 0x04, 0, 0};
    if (!getter || std::memcmp(getter, prefix, sizeof(prefix)) != 0
            || std::memcmp(getter + 9, load, sizeof(load)) != 0) return false;
    int32_t displacement = 0;
    std::memcpy(&displacement, getter + 5, sizeof(displacement));
    using Globals = unsigned char* (*)();
    auto globals = reinterpret_cast<Globals>(const_cast<unsigned char*>(getter + 9) + displacement);
    auto** slot = reinterpret_cast<Elf64_auxv_t**>(globals() + 0x418);
    if (!*slot) return false;
    size_t count = 0;
    bool page_size_matches = false, replaced = false;
    for (; count < auxiliary.size() - 2 && (*slot)[count].a_type != AT_NULL; ++count) {
        auxiliary[count] = (*slot)[count];
        if (auxiliary[count].a_type == AT_PAGESZ)
            page_size_matches = auxiliary[count].a_un.a_val == static_cast<unsigned long>(sysconf(_SC_PAGESIZE));
        if (auxiliary[count].a_type == AT_PLATFORM) {
            auxiliary[count].a_un.a_val = reinterpret_cast<uintptr_t>(platform);
            replaced = true;
        }
    }
    if (count == auxiliary.size() - 2 || !page_size_matches) return false;
    if (!replaced) auxiliary[count++] = {AT_PLATFORM, {reinterpret_cast<uintptr_t>(platform)}};
    auxiliary[count] = {};
    __atomic_store_n(slot, auxiliary.data(), __ATOMIC_RELEASE);
    return true;
}

bool set_string(JNIEnv* env, jclass type, const char* name, const char* value) {
    jfieldID field = env->GetStaticFieldID(type, name, "Ljava/lang/String;");
    if (!field) return false;
    jstring text = env->NewStringUTF(value);
    env->SetStaticObjectField(type, field, text);
    env->DeleteLocalRef(text);
    return !env->ExceptionCheck();
}

bool configure_build(JNIEnv* env) {
    jclass build = env->FindClass("android/os/Build");
    jclass version = env->FindClass("android/os/Build$VERSION");
    if (!build || !version) return false;
    const jfieldID sdk = env->GetStaticFieldID(version, "SDK_INT", "I");
    if (!sdk || env->GetStaticIntField(version, sdk) != 34) return false;
    const std::pair<const char*, const char*> fields[] = {
        {"MANUFACTURER", "Google"}, {"BRAND", "google"}, {"MODEL", "Pixel 8"},
        {"DEVICE", "shiba"}, {"PRODUCT", "shiba"}, {"HARDWARE", "shiba"}, {"BOARD", "zuma"},
        {"FINGERPRINT", "google/shiba/shiba:14/AP1A.240505.005/11677807:user/release-keys"},
        {"ID", "AP1A.240505.005"}, {"TYPE", "user"}, {"TAGS", "release-keys"}
    };
    for (const auto& field : fields) if (!set_string(env, build, field.first, field.second)) return false;
    if (!set_string(env, version, "INCREMENTAL", "11677807")) return false;
    jclass string = env->FindClass("java/lang/String");
    jstring abi = env->NewStringUTF("arm64-v8a");
    for (const char* name : {"SUPPORTED_ABIS", "SUPPORTED_64_BIT_ABIS", "SUPPORTED_32_BIT_ABIS"}) {
        jfieldID field = env->GetStaticFieldID(build, name, "[Ljava/lang/String;");
        if (!field) return false;
        jobjectArray values = env->NewObjectArray(std::strcmp(name, "SUPPORTED_32_BIT_ABIS") == 0 ? 0 : 1, string, abi);
        env->SetStaticObjectField(build, field, values);
        env->DeleteLocalRef(values);
    }
    env->DeleteLocalRef(abi);
    return !env->ExceptionCheck();
}
}

extern "C" JNIEXPORT jboolean JNICALL
Java_dev_androidlab_module_RuntimeProfile_prepare(JNIEnv* env, jclass, jlong address, jstring apk) {
    auto* api = reinterpret_cast<zygisk::Api*>(address);
    const char* path = env->GetStringUTFChars(apk, nullptr);
    if (!path || !api) return false;
    module_apk = path;
    env->ReleaseStringUTFChars(apk, path);
    // Magisk 27's native-bridge callback can omit boot-native originals on this image.
    // Validate the pinned ART method's native data pointer before registering a replacement.
    jclass owner = env->FindClass("android/hardware/SystemSensorManager");
    jclass executable = env->FindClass("java/lang/reflect/Executable");
    jmethodID method = owner ? env->GetStaticMethodID(owner, "nativeGetSensorAtIndex", "(JLandroid/hardware/Sensor;I)Z") : nullptr;
    jfieldID art_field = executable ? env->GetFieldID(executable, "artMethod", "J") : nullptr;
    jobject reflected = method ? env->ToReflectedMethod(owner, method, true) : nullptr;
    const jlong art = reflected && art_field ? env->GetLongField(reflected, art_field) : 0;
    SensorAtIndex verified = nullptr;
    if (art && !env->ExceptionCheck()) {
        const auto* bytes = reinterpret_cast<const unsigned char*>(art);
        uint32_t flags = 0;
        std::memcpy(&flags, bytes + 4, sizeof(flags));
        if ((flags & 0x108) == 0x108) {
            void* pointer = nullptr;
            std::memcpy(&pointer, bytes + 16, sizeof(pointer));
            Dl_info info{};
            if (pointer && dladdr(pointer, &info) && info.dli_fname && std::strstr(info.dli_fname, "/libandroid_runtime.so"))
                verified = reinterpret_cast<SensorAtIndex>(pointer);
        }
    }
    if (!verified) {
        __android_log_print(ANDROID_LOG_ERROR, "DeviceLabRuntime", "sensor ART layout validation failed");
        return false;
    }
    JNINativeMethod sensor[] = {{const_cast<char*>("nativeGetSensorAtIndex"),
            const_cast<char*>("(JLandroid/hardware/Sensor;I)Z"), reinterpret_cast<void*>(sensor_profile)}};
    api->hookJniNativeMethods(env, "android/hardware/SystemSensorManager", sensor, 1);
    original_sensor = verified;
    const bool ready = original_sensor && original_sensor != sensor_profile;
    __android_log_print(ready ? ANDROID_LOG_INFO : ANDROID_LOG_ERROR,
                        "DeviceLabRuntime", "JNI preparation sensors=%d original_is_replacement=%d", ready, original_sensor == sensor_profile);
    return ready;
}

extern "C" JNIEXPORT void JNICALL
Java_dev_androidlab_module_RuntimeProfile_configure(JNIEnv* env, jclass) {
    const bool build = configure_build(env);
    if (env->ExceptionCheck()) { env->ExceptionDescribe(); env->ExceptionClear(); }
    const bool auxiliary = configure_auxiliary();
    const bool graphics = configure_graphics();
    try_guest(env);
    __android_log_print(build && auxiliary && graphics ? ANDROID_LOG_INFO : ANDROID_LOG_ERROR,
                        "DeviceLabRuntime", "profile build=%d auxv=%d graphics_dispatch=%d", build, auxiliary, graphics);
}

extern "C" JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM* vm, void*) {
    JNIEnv* env = nullptr;
    if (vm->GetEnv(reinterpret_cast<void**>(&env), JNI_VERSION_1_6) != JNI_OK) return JNI_ERR;
    if (!std::getenv("DEVICE_LAB_PREPARE_RUNTIME")) Java_dev_androidlab_module_RuntimeProfile_configure(env, nullptr);
    // The published auxv and EGL pointers require this library to remain loaded even on a partial setup.
    return JNI_VERSION_1_6;
}
