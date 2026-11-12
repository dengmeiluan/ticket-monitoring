# maps 洗白模块（seccomp）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 5 个目标 App 读自己 `/proc/self/maps` 时看不到 `houdini`/`nemu` 痕迹，从而拿掉携程 50003 与阿里滑块的"环境是模拟器"判据。

**Architecture:** Zygisk 模块在目标 App 进程安装 seccomp 过滤器（`user_notif`）；命中 `open/openat/openat2/newfstatat` 且路径为自身 maps 时，由模块线程读真实内容、滤掉标记行、写入 `memfd`，再用 `SECCOMP_IOCTL_NOTIF_ADDFD` 把该 fd 交回调用者。

**Tech Stack:** C++17 · Zygisk（`zygisk.hpp`，仓内已有）· Android NDK r27 · CMake + Ninja · Python（打包与验收脚本）

**Spec:** `docs/superpowers/specs/2026-11-08-maps-cloak-design.md`

**落地状态：进行中**（代码与脚本部分已存在；下列 Step 未勾选，表示真机回滚/A-B 尚未完成，不代表未开工）。

## Global Constraints

- 只对 `config/global.json` 里 `packages` 列出的包生效；默认第一批只有 `com.taobao.trip`。
- 过滤词表固定取自配置 `markers`，默认 `["houdini","nemu","mumu","netease"]`。
- **不改 ABI、不碰 KeyMint/Play Integrity、不隐藏跨进程读取**。
- 任何时刻可通过 `touch /data/adb/modules/tm_maps_cloak/disable` + 重启完全退出。
- 模块目录：`/data/adb/modules/tm_maps_cloak/{module.prop,zygisk/<abi>.so,config/global.json}`。
- 测试命令必须带 `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"`；读文件用 UTF-8。
- 工具链装到 `_tools/`（已在 `.gitignore`），**不进 git**；nerium 源码进 `native/maps_cloak/vendor/`（MIT，保留 LICENSE）。

## Review Focus

- **App 多进程**：`com.taobao.trip:remote` 之类子进程若不安装过滤器，SDK 在子进程读 maps 仍会看到痕迹 → 验收须覆盖子进程。
- **`read` 而非 `open` 的读取路径**：若 SDK 打开 maps 后 `pread` 偏移读，memfd 内容必须完整且可随机访问（不能是管道）。
- **过滤器装太晚**：Zygisk 在 `preAppSpecialize` 安装才算赶在首帧前；装晚了风控已取样。
- **ANR 风险**：通知循环若有阻塞（例如在监听线程里做重 IO），App 会卡死 → 循环内只做内存过滤 + memfd 写。
- **回滚可验证性**：disable 后必须能量到泄漏回到 5/1（否则无法区分"没生效"与"本来就没有"）。

---

### Task 1: 工具链与源码就位

**Files:**
- Create: `_tools/ndk/`（NDK r27c 解压目录，gitignore）
- Create: `native/maps_cloak/vendor/nerium/{proc_broker.cpp,proc_broker.hpp,proc_view.cpp,proc_view.hpp,syscall_dispatch.S,policy_gate.cpp,policy_gate.hpp,policy_gate.S,LICENSE}`

**Interfaces:**
- Produces: 编译环境变量 `NDK`（指向 `_tools/ndk/android-ndk-r27c`），供 Task 3/4 的 build 脚本使用。

- [ ] **Step 1:** 下载并解压 NDK r27c 到 `_tools/ndk/`
  验证：`_tools/ndk/android-ndk-r27c/toolchains/llvm/prebuilt/windows-x86_64/bin/clang.exe --version` 打印版本。
- [ ] **Step 2:** 从 nerium 取上列 8 个文件 + LICENSE 到 `native/maps_cloak/vendor/nerium/`（raw.githubusercontent.com 直取）
  验证：`ls native/maps_cloak/vendor/nerium` 含 9 个文件，`wc -l proc_broker.cpp` > 500。
- [ ] **Step 3:** 提交
  ```bash
  git add native/maps_cloak/vendor/nerium
  git commit -m "chore(maps-cloak): vendor nerium seccomp broker (MIT)"
  ```

---

### Task 2: 配置与打包（纯 Python，可单测）

**Files:**
- Create: `scripts/build_maps_cloak.py`
- Create: `tests/test_r1063_maps_cloak_pack.py`

**Interfaces:**
- Produces:
  - `load_config(path) -> dict`：校验 `enabled/packages/markers`，缺字段抛 `ValueError`
  - `build_module(out_zip: str, so_by_abi: dict, cfg: dict) -> str`：产出模块 zip，内部路径固定为 `module.prop`、`zygisk/arm64-v8a.so`、`zygisk/x86_64.so`、`config/global.json`

- [ ] **Step 1: 写失败测试** `tests/test_r1063_maps_cloak_pack.py`
```python
def test_load_config_rejects_missing_markers(tmp_path):
    p = tmp_path / "global.json"; p.write_text('{"enabled":true,"packages":["a"]}')
    with pytest.raises(ValueError): load_config(str(p))

def test_build_module_layout(tmp_path):
    so = tmp_path / "a.so"; so.write_bytes(b"\x7fELF")
    z = build_module(str(tmp_path / "o.zip"), {"arm64-v8a": str(so),
                     "x86_64": str(so)},
                     {"enabled": True, "packages": ["com.taobao.trip"],
                      "markers": ["houdini"]})
    names = set(zipfile.ZipFile(z).namelist())
    assert {"module.prop", "zygisk/arm64-v8a.so", "zygisk/x86_64.so",
            "config/global.json"} <= names
```
- [ ] **Step 2:** 跑测试确认失败（`ImportError`）
- [ ] **Step 3:** 实现 `scripts/build_maps_cloak.py`（`zipfile` 写出；`module.prop` 用固定模板，id=`tm_maps_cloak`）
- [ ] **Step 4:** 跑测试确认通过
- [ ] **Step 5:** 提交

---

### Task 3: 最小 Zygisk 骨架 + 注入验证

**Files:**
- Create: `native/maps_cloak/CMakeLists.txt`
- Create: `native/maps_cloak/main.cpp`

**Interfaces:**
- Produces: `libmaps_cloak.so`（arm64-v8a / x86_64 各一份），注入后向 logcat 打 `maps_cloak: injected pkg=<pkg> pid=<pid>`。

- [ ] **Step 1:** 写 `CMakeLists.txt`（两 ABI、`-std=c++17`、链接 `log`）
- [ ] **Step 2:** 实现 `main.cpp`：Zygisk 模块，`preAppSpecialize` 里读包名，命中 `packages` 时打日志（此步不装过滤器）
- [ ] **Step 3:** 编译：`cmake --build` 产出两个 `.so`
  验证：`llvm-readelf -h` 显示 `Machine: AArch64` / `X86-64`
- [ ] **Step 4:** 部署+重启+启动飞猪，`logcat -d | grep maps_cloak` 看到注入行
- [ ] **Step 5:** 提交

---

### Task 4: 移植 seccomp 代理并启用过滤

**Files:**
- Modify: `native/maps_cloak/main.cpp`（`preAppSpecialize` 里调 `proc_broker_install(...)`）
- Modify: `native/maps_cloak/CMakeLists.txt`（加入 vendor 的 4 个 .cpp/.S）
- Create: `native/maps_cloak/config.cpp`（读 `config/global.json` 的极简 JSON 解析）

**Interfaces:**
- Consumes: Task 1 的 vendor 源码、Task 3 的注入点
- Produces: `bool proc_broker_install(const std::vector<std::string>& markers)`；命中 maps 时返回过滤后的 memfd

- [ ] **Step 1:** 接 `config.cpp`，把 `markers`/`packages` 读进内存
- [ ] **Step 2:** 在 `preAppSpecialize` 末尾安装过滤器（只对命中包）
- [ ] **Step 3:** 改 `proc_view.cpp` 的过滤函数：按 `markers` 删行（先删行，不替换）
- [ ] **Step 4:** 编译并部署
- [ ] **Step 5:** 验收（**设备侧**）：
  ```
  python -m core.android.hide tells --pkg com.taobao.trip
  ```
  期望：`houdini`/`nemu` 均为 0；再启飞猪跑一次真实查询能出数。
- [ ] **Step 6:** 提交

---

### Task 5: 面板与命令行可观测（沿用现有隐藏层命令）

**Files:**
- Modify: `core/android/hide.py`（`status()` 增加 `tm_maps_cloak` 模块位；`fix()` 支持启用它）
- Modify: `tests/test_r1063_device_hide.py`

**Interfaces:**
- Consumes: Task 4 的模块目录名 `tm_maps_cloak`
- Produces: `python -m core.android.hide status` 输出含 `tm_maps_cloak=on|disabled|缺失`

- [ ] **Step 1:** 写失败测试（断言 `HIDE_MODULES` 含 `tm_maps_cloak`，且 `status()` 会读它）
- [ ] **Step 2:** 改 `hide.py` 让测试通过
- [ ] **Step 3:** 跑测试
- [ ] **Step 4:** 提交

---

### Task 6: 回滚验证与结论落档

**Files:**
- Modify: `docs/CAPABILITY_AND_UNBLOCK.md`（追加"maps 洗白"一节：做法、验收数字、回滚方式）
- Modify: `.superpowers/sdd/2026-11-06-crawl-strategy-control-plane/progress.md`（轮次台账）

- [ ] **Step 1:** 回滚实测：`touch /data/adb/modules/tm_maps_cloak/disable` + 重启 + `hide tells` → 期望 `houdini×5, nemu×1`
- [ ] **Step 2:** 重新启用 + 重启 + `hide tells` → 期望 0/0（证明效果与回滚都成立）
- [ ] **Step 3:** 把两组数字写进文档与台账
- [ ] **Step 4:** 提交
