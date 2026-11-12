// MuMu Cloak v0.3 —— 改用 JNI 层替换（不再做 GOT 打补丁）
//
// 为什么换方案：
//   * GOT 打补丁只能改「App 自己的 .so」才安全（改系统库会把进程搞崩），
//     但 Android 的属性读取实际发生在系统库（SystemProperties → libandroid_runtime），
//     所以扫 App 自己的库必然 patched=0。
//   * 正确层次是 JNI：`android.os.SystemProperties` 的 native 方法可以用
//     RegisterNatives 在**本进程内**替换，干净、只影响当前 App 进程。
#include <android/log.h>
#include <jni.h>
#include <sys/system_properties.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>

#include "zygisk.hpp"

#define LOG_TAG "mumucloak"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, LOG_TAG, __VA_ARGS__)

namespace {

// 内置默认词表（markers.txt 读不到时用）
const char *kDefaultMarkers[] = {"nemu", "mumu", "netease", "houdini"};

// 运行期词表：可在 /data/adb/modules/mumu_cloak/markers.txt 覆盖
// （一行一个词，`#` 开头为注释）。**必须在 preAppSpecialize 里加载**——
// 那时进程仍是 root，能读 0700 的 /data/adb/modules；
// specialize 之后 app uid 就读不到了。
char g_markers[32][64];
int g_marker_count = 0;
bool g_markers_loaded = false;
int g_hits = 0;

void load_markers() {
  if (g_markers_loaded) return;
  g_markers_loaded = true;
  FILE *f = fopen("/data/adb/modules/mumu_cloak/markers.txt", "re");
  if (f) {
    char line[128];
    while (fgets(line, sizeof(line), f) && g_marker_count < 32) {
      char *p = line;
      while (*p == ' ' || *p == '\t') ++p;
      if (*p == '#' || *p == '\n' || *p == '\r' || *p == 0) continue;
      size_t n = strlen(p);
      while (n && (p[n - 1] == '\n' || p[n - 1] == '\r' ||
                   p[n - 1] == ' ' || p[n - 1] == '\t')) {
        p[--n] = 0;
      }
      if (n == 0 || n >= sizeof(g_markers[0])) continue;
      memcpy(g_markers[g_marker_count], p, n + 1);
      ++g_marker_count;
    }
    fclose(f);
  }
  if (g_marker_count == 0) {
    for (const char *m : kDefaultMarkers) {
      size_t n = strlen(m);
      if (n >= sizeof(g_markers[0])) continue;
      memcpy(g_markers[g_marker_count], m, n + 1);
      ++g_marker_count;
    }
    LOGI("markers: builtin (%d)", g_marker_count);
  } else {
    LOGI("markers: file (%d)", g_marker_count);
  }
}

bool has_marker(const char *s) {
  if (!s || !*s) return false;
  for (int i = 0; i < g_marker_count; ++i) {
    if (strstr(s, g_markers[i])) return true;
  }
  return false;
}

void note(const char *what, const char *key) {
  if (g_hits < 15) {
    ++g_hits;
    LOGI("CLOAK %s %s", what, key ? key : "");
  }
}

// ---- 替换 android.os.SystemProperties 的 native 实现 ----
jstring j_get(JNIEnv *env, jclass, jstring jkey, jstring jdef) {
  if (!jkey) return jdef;
  const char *key = env->GetStringUTFChars(jkey, nullptr);
  if (!key) return jdef;
  bool hide = has_marker(key);
  char value[PROP_VALUE_MAX] = {0};
  int len = hide ? 0 : __system_property_get(key, value);
  if (hide) note("hide-prop", key);
  env->ReleaseStringUTFChars(jkey, key);
  if (len <= 0) return jdef;
  return env->NewStringUTF(value);
}

jint j_get_int(JNIEnv *env, jclass, jstring jkey, jint def) {
  if (!jkey) return def;
  const char *key = env->GetStringUTFChars(jkey, nullptr);
  if (!key) return def;
  bool hide = has_marker(key);
  char value[PROP_VALUE_MAX] = {0};
  int len = hide ? 0 : __system_property_get(key, value);
  if (hide) note("hide-prop-int", key);
  env->ReleaseStringUTFChars(jkey, key);
  if (len <= 0) return def;
  return (jint)atoi(value);
}

jlong j_get_long(JNIEnv *env, jclass, jstring jkey, jlong def) {
  if (!jkey) return def;
  const char *key = env->GetStringUTFChars(jkey, nullptr);
  if (!key) return def;
  bool hide = has_marker(key);
  char value[PROP_VALUE_MAX] = {0};
  int len = hide ? 0 : __system_property_get(key, value);
  env->ReleaseStringUTFChars(jkey, key);
  if (len <= 0) return def;
  return (jlong)atoll(value);
}

jboolean j_get_bool(JNIEnv *env, jclass, jstring jkey, jboolean def) {
  if (!jkey) return def;
  const char *key = env->GetStringUTFChars(jkey, nullptr);
  if (!key) return def;
  bool hide = has_marker(key);
  char value[PROP_VALUE_MAX] = {0};
  int len = hide ? 0 : __system_property_get(key, value);
  env->ReleaseStringUTFChars(jkey, key);
  if (len <= 0) return def;
  return (jboolean)(strcmp(value, "1") == 0 || strcmp(value, "true") == 0);
}

// ---- binder 服务名隐藏 ----
jobjectArray g_services = nullptr;   // 过滤后的快照（全局引用）
int g_svc_hits = 0;

jobjectArray j_get_service_names(JNIEnv *env, jclass) {
  if (g_svc_hits < 5) {
    ++g_svc_hits;
    LOGI("CLOAK listServices -> filtered snapshot");
  }
  return g_services;
}

void install_service_hooks(JNIEnv *env) {
  jclass cls = env->FindClass("android/os/ServiceManager");
  if (!cls) {
    env->ExceptionClear();
    LOGI("FindClass ServiceManager failed");
    return;
  }
  // 先调原始实现拿全量列表
  jmethodID mid = env->GetStaticMethodID(
      cls, "listServices", "()[Ljava/lang/String;");
  if (!mid) {
    env->ExceptionClear();
    LOGI("no listServices");
    return;
  }
  auto full = (jobjectArray)env->CallStaticObjectMethod(cls, mid);
  if (env->ExceptionCheck()) {
    env->ExceptionClear();
    LOGI("listServices threw");
    return;
  }
  int n = full ? env->GetArrayLength(full) : 0;
  int kept = 0;
  int hidden_n = 0;
  jobjectArray filtered = env->NewObjectArray(n, env->FindClass("java/lang/String"), nullptr);
  for (int i = 0; i < n; ++i) {
    auto s = (jstring)env->GetObjectArrayElement(full, i);
    if (!s) continue;
    const char *c = env->GetStringUTFChars(s, nullptr);
    bool hide = has_marker(c);
    if (hide) ++hidden_n;
    env->ReleaseStringUTFChars(s, c);
    if (!hide) {
      env->SetObjectArrayElement(filtered, kept++, s);
    }
    env->DeleteLocalRef(s);
  }
  g_services = (jobjectArray)env->NewGlobalRef(filtered);
  LOGI("services: total=%d kept=%d", n, kept);

  JNINativeMethod m[] = {
      {(char *)"listServices", (char *)"()[Ljava/lang/String;",
       (void *)j_get_service_names},
  };
  jint rc = env->RegisterNatives(cls, m, 1);
  if (env->ExceptionCheck()) env->ExceptionClear();
  LOGI("RegisterNatives(ServiceManager) rc=%d", (int)rc);
}

// ---- 诊断：列出目标类的方法 + native 标志 ----
// ---- 文件层：让 /system/bin/nemu* 对 App 表现为「不存在」----
#include <sys/stat.h>

bool is_hidden_path(const char *path) {
  if (!path) return false;
  if (strncmp(path, "/system/bin/", 12) == 0) return has_marker(path + 12);
  if (strncmp(path, "/system/xbin/", 13) == 0) return has_marker(path + 13);
  return false;
}

// 1=BA_EXISTS 2=BA_REGULAR 4=BA_DIRECTORY 8=BA_HIDDEN
jint attrs_of(const char *path) {
  struct stat st;
  if (!path || stat(path, &st) != 0) return 0;
  jint a = 1;                       // exists
  if (S_ISREG(st.st_mode)) a |= 2;
  if (S_ISDIR(st.st_mode)) a |= 4;
  if (path[0] && strrchr(path, '/') && strrchr(path, '/')[1] == '.') a |= 8;
  return a;
}

// (Ljava/io/File;)I
jint j_attrs_file(JNIEnv *env, jobject, jobject jfile) {
  if (!jfile) return 0;
  jclass fc = env->FindClass("java/io/File");
  jmethodID toStr = env->GetMethodID(fc, "getPath", "()Ljava/lang/String;");
  if (!toStr) { env->ExceptionClear(); return 0; }
  auto js = (jstring)env->CallObjectMethod(jfile, toStr);
  if (!js || env->ExceptionCheck()) { env->ExceptionClear(); return 0; }
  const char *c = env->GetStringUTFChars(js, nullptr);
  jint r = 0;
  if (c) {
    bool hide = is_hidden_path(c);
    if (hide) note("hide-file", c);
    r = hide ? 0 : attrs_of(c);
    env->ReleaseStringUTFChars(js, c);
  }
  return r;
}

// (Ljava/lang/String;)I
jint j_attrs_str(JNIEnv *env, jobject, jstring jpath) {
  if (!jpath) return 0;
  const char *c = env->GetStringUTFChars(jpath, nullptr);
  jint r = 0;
  if (c) {
    bool hide = is_hidden_path(c);
    if (hide) note("hide-file", c);
    r = hide ? 0 : attrs_of(c);
    env->ReleaseStringUTFChars(jpath, c);
  }
  return r;
}

void install_fs_hooks(JNIEnv *env) {
  jclass cls = env->FindClass("java/io/UnixFileSystem");
  if (!cls) {
    env->ExceptionClear();
    LOGI("no UnixFileSystem");
    return;
  }
  JNINativeMethod a[] = {
      {(char *)"getBooleanAttributes0",
       (char *)"(Ljava/io/File;)I", (void *)j_attrs_file},
  };
  jint rc = env->RegisterNatives(cls, a, 1);
  if (env->ExceptionCheck()) env->ExceptionClear();
  LOGI("RegisterNatives(UnixFileSystem File) rc=%d", (int)rc);

  JNINativeMethod b[] = {
      {(char *)"getBooleanAttributes0",
       (char *)"(Ljava/lang/String;)I", (void *)j_attrs_str},
  };
  jint rc2 = env->RegisterNatives(cls, b, 1);
  if (env->ExceptionCheck()) env->ExceptionClear();
  LOGI("RegisterNatives(UnixFileSystem String) rc=%d", (int)rc2);
}

void install_prop_hooks(JNIEnv *env) {
  jclass cls = env->FindClass("android/os/SystemProperties");
  if (!cls) {
    env->ExceptionClear();
    LOGI("FindClass SystemProperties failed");
    return;
  }
  JNINativeMethod methods[] = {
      {(char *)"native_get", (char *)"(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;",
       (void *)j_get},
      {(char *)"native_get_int", (char *)"(Ljava/lang/String;I)I",
       (void *)j_get_int},
      {(char *)"native_get_long", (char *)"(Ljava/lang/String;J)J",
       (void *)j_get_long},
      {(char *)"native_get_boolean", (char *)"(Ljava/lang/String;Z)Z",
       (void *)j_get_bool},
  };
  jint rc = env->RegisterNatives(cls, methods, 4);
  if (env->ExceptionCheck()) env->ExceptionClear();
  LOGI("RegisterNatives rc=%d", (int)rc);
}

}  // namespace

class MuMuCloak : public zygisk::ModuleBase {
 public:
  void onLoad(zygisk::Api *, JNIEnv *env) override { env_ = env; }

  void preAppSpecialize(zygisk::AppSpecializeArgs *args) override {
    (void)args;
    // 此时仍是 root：赶紧把词表读进来（specialize 之后就读不到了）
    load_markers();
  }

  void postAppSpecialize(const zygisk::AppSpecializeArgs *args) override {
    if (!args || args->uid < 10000) return;
    if (!env_) {
      LOGI("no JNIEnv");
      return;
    }
    install_prop_hooks(env_);
    install_service_hooks(env_);
    install_fs_hooks(env_);
  }

 private:
  JNIEnv *env_ = nullptr;
};

REGISTER_ZYGISK_MODULE(MuMuCloak)
