# maps 洗白模块（seccomp 方案）设计

日期：2026-11-08 · 状态：待批准 · 关联：T106/T107

## 意图（为什么做）

携程 App 登录恒返 **50003「当前登录环境存在风险」**，飞猪 App **滑块点完就直接堵住**。
T106 量到，这两个 App 自己的 `/proc/<pid>/maps` 里有两条**真机绝不会有**的痕迹：

```
/system/lib64/libhoudini.so                                   ← ARM→x86 翻译层，r-xp 正在执行
/dev/__properties__/u:object_r:vendor_nemu_default_prop:s0    ← MuMu 的 SELinux 属性上下文
/dev/__properties__/u:object_r:vendor_houdini_default_prop:s0
```

风控只要读一次 maps 就能判"模拟器"。设备脸（机型/SoC/GPU）、root 痕迹（magisk）、
传感器、出口 IP 都已处理干净——**只剩这两条**。

## 目标 / 非目标

**目标**：让指定 App 读自己 maps 时，看到的是一份**滤掉 houdini/nemu 相关行**的版本；
App 其余行为（执行、启动、查询、登录）完全不受影响。

**非目标**：不改 ABI 声明；不碰 Play Integrity / KeyMint；不隐藏跨进程读取
（别人读 `/proc/<我方pid>/maps` 不管）；不改变真实内存布局。

## 方案对比（已选定第 2 条）

1. **PLT/JNI hook**：便宜（只要 NDK），但阿里/携程若直读 syscall 就绕过。
2. **seccomp user-notification 代理**（nerium 的做法，**选定**）：内核层拦截
   `open/openat/openat2/stat` 家族，命中 maps 时用净化内容应答（memfd + `ADDFD`），
   **直读 syscall 也拦得住**。前提已验证：本机内核 6.1.90，`user_notif` 可用。
3. **Frida 脚本**：零编译，但 Frida 自身是风控头号检测目标，等于用更大的暴露换小的。不做。

## 实现（复用而非重写）

从 `5forzin/nerium`（MIT）取这四块，落到本仓 `native/maps_cloak/`：

| 源文件（nerium） | 用途 |
|---|---|
| `proc_broker.cpp` (26KB) | seccomp 过滤器安装 + 用户态通知循环 + `ADDFD` 应答 |
| `proc_view.cpp` (8.7KB) | 生成"净化后的 /proc 内容" |
| `syscall_dispatch.S` | 系统调用入口跳板 |
| `policy_gate.cpp/.S` | 注入时机与作用域闸门 |

**不复用**：`cpu_namespace`/`property_namespace`（身份已由 `tm_identity` 管）、
`guestkeymint`/`relay`/各种 probe（与本目标无关）。

我们自己写：
* Zygisk 入口（复用仓里已有的 `native/mumu_cloak/zygisk.hpp`）；
* 作用域名单 + 过滤词表：`/data/adb/modules/tm_maps_cloak/config/global.json`
  ```json
  {"enabled": true,
   "packages": ["ctrip.android.view", "com.taobao.trip", "com.Qunar",
                "com.tongcheng.android", "cn.suanya.zhixing"],
   "markers": ["houdini", "nemu", "mumu", "netease"]}
  ```
* 打包脚本 `scripts/build_maps_cloak.py`（产出 Magisk/KernelSU 模块 zip，
  与现有 `scripts/identity_boot_module.py` 的目录约定一致）。

**工具链**：Android NDK r27 + CMake + Ninja（不需要 JDK/Gradle——我们直接编 `.so` 并自己打 zip）。

## 验收（三条，全部要满足）

1. `python -m core.android.hide tells --pkg com.taobao.trip` → `houdini` 与 `nemu` **均为 0**；
2. 五个目标 App **都能正常启动并出数**（用现有 `python -m core.channel_engine.probe` 跑一轮）；
3. `touch /data/adb/modules/tm_maps_cloak/disable` + 重启后，泄漏**回到 5/1**
   （证明可秒级回滚，且效果确实来自本模块）。

## 失败即回滚

模块被 disable 后完全退出链路；不影响 `tm_identity` 与其它模块。
若出现 App 崩溃/ANR/查询明显变慢（>5%），视为失败，直接 disable。

## 已知风险

* **supervisor 线程模型**：seccomp user-notif 需要一个进程监听；Zygisk 注入后由
  我们自己的线程做监听，需处理 App 多进程（`:remote` 等）各自安装；
* **Android 15 的 SELinux**：App 读自己 maps 是允许的，但我们的应答要保证 fd
  可被 App 正常 `read`（用 memfd，无路径权限问题）；
* **nerium 面向 AVD Android 14**：它的 `proc_view` 里可能写死了某些镜像布局假设，
  移植时要逐条核对（已计划只取与会话无关的"过滤"部分，不取它的"重造布局"部分）；
* 若 15 上出现内核级不兼容（例如 MuMu 的 seccomp 已被自身策略占用），
  **降级 MuMu 实例到 Android 14 再试**（用户已授权）。

## 留给实现者的判断

* 过滤是"删行"还是"替换为无害路径"——删行更简单，但某些 SDK 会数条目；
  默认删行，若验收 2 失败再改替换；
* 是否对 5 个包全开还是先只开 `com.taobao.trip`（分两批更稳）；
* `stat` 家族只拦 `stat`/`newfstatat`，还是连 `access`/`readlink` 一起（先窄后宽）。
