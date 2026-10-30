# App 渠道 P1 实施计划：Android 运行时 + 设备原语 + 智行日历族采集

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不影响现有 5 个浏览器渠道的前提下，建立可脚本控制的 Android 运行时层，用智行 App 采集到真实的每日最低价并落库。

**Architecture:** `core/android/` 是唯一接触 MuMu/ADB 的边界（runtime + device + loginstate），`crawlers/app_base.py` 提供不依赖 Playwright 的 `AppCrawler` 基类（复用 `path_note` 账本契约），`crawlers/app_zhixing.py` 实现渠道。设备是单例资源，用模块级 `threading.Lock` 串行。整条链路受 `android.enabled` 总开关控制，关闭时零外部进程、零 import 副作用。

**Tech Stack:** Python 3.11、`subprocess`（调用 MuMuManager.exe / adb.exe）、`uiautomator dump` XML 解析、现有 `core.models.FlightPrice`。

**Spec:** `docs/superpowers/specs/2026-10-29-app-channels-design.md`

## 落地状态（2026-10-30 实测核对）

勾选框尚未回填，但下列产物**已存在并有用例**；以此段为准判断进度，不要用未勾数当未开工：

- 已落地：`core/android/runtime.py`、`core/android/device.py`、`core/android/login_api.py`、
  `core/android/login_session.py`、`crawlers/app_base.py`、`crawlers/app_zhixing.py`；
  用例 `tests/test_app_crawler_base.py`、`test_app_login_api.py`、`test_app_login_session.py`、
  `test_app_zhixing_parse.py`、`test_app_zhixing_calendar.py`、`test_app_zhixing_crawler.py`、
  `test_app_snapshot.py`、`test_app_blocker_flow.py`、`test_app_channel_optional.py`。
- 未落地（未创建）：`core/android/loginstate.py` —— 快照/状态实现并入了 `login_session.py`；
- 未落地（未创建）：`tests/test_app_meituan_parse.py` —— 美团 App 解析未接入。
- 勾选框保持原样不改：它们是按任务粒度记的，产物存在不等于该任务的全部子项都验收过。

## Global Constraints

- 现有 5 渠道行为**不得改变**；`android.enabled` 缺省 `false` 时任何 App 相关代码不得执行。
- 状态诚实：App 的「查无航班 / 网络异常 / 请登录」不得记为 `empty`，只有明确无结果文案才记 `empty`。
- 未登录只能产出**日历族**结果（每日最低价、无航班号），必须标 `calendar` 路径；`¥3??` 遮罩价必须识别为 masked 而非 0。
- 新文件纯 LF；不新增第三方依赖到 `requirements.txt` 之外（`uiautomator2`/`adbutils` 不引入，直接 subprocess 调 adb）。
- 每个任务结束时测试必须全绿才能进入下一任务。
- 设备操作全部有超时；任何一步失败都要落 `path_note` 而不是抛栈。

---

### Task 1: Android 配置加载与总开关

**Files:**
- Create: `core/android/__init__.py`
- Create: `core/android/config.py`
- Test: `tests/test_android_config.py`

**Interfaces:**
- Produces: `core.android.config.normalize(raw: dict) -> dict`；`core.android.config.is_enabled(cfg: dict) -> bool`；`AndroidConfig` dataclass 字段：`enabled, provider, install_dir, vm_index, boot_timeout_s, action_timeout_s, snapshot`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_android_config.py
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.android.config import normalize, is_enabled

def test_missing_block_disables_everything():
    c = normalize(None)
    assert c.enabled is False
    assert is_enabled(None) is False
    assert is_enabled({"crawler": {}}) is False

def test_enabled_true_is_respected():
    c = normalize({"enabled": True})
    assert c.enabled is True
    assert is_enabled({"android": {"enabled": True}}) is True

def test_defaults_are_clamped():
    c = normalize({"enabled": True, "boot_timeout_s": 1, "action_timeout_s": 99999})
    assert c.boot_timeout_s >= 10
    assert c.action_timeout_s <= 600

def test_vm_index_coerced_to_int():
    assert normalize({"enabled": True, "vm_index": "2"}).vm_index == 2
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_android_config.py -v`
Expected: FAIL `ModuleNotFoundError: core.android`

- [ ] **Step 3: 实现**

`core/android/__init__.py` 只做导出，不 import 重量级模块（保证关闭时零开销）。
`core/android/config.py` 用 `dataclasses.dataclass`，`normalize` 里做范围钳制（boot 10–600、action 5–900）。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_android_config.py -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

---

### Task 2: MuMuManager 封装（发现/查询/控制）

**Files:**
- Create: `core/android/mumu.py`
- Test: `tests/test_android_mumu.py`

**Interfaces:**
- Produces: `MuMuManager(install_dir=None)`；`.manager_path`、`.adb_path`、`.available() -> bool`、`.info(vm=0) -> dict|None`、`.launch(vm)`、`.shutdown(vm)`、`.engine_state() -> dict`、`.setting(vm, key, value=None)`
- 所有方法内部 `subprocess.run(..., timeout=...)`，失败返回 `None`/`False`，**不抛异常**

- [ ] **Step 1: 写失败测试**（用 monkeypatch 打桩 subprocess，断言命令拼装与失败兜底）

关键用例：
- `available()` 在 manager 不存在时返回 False 且不调 subprocess
- `info()` 解析 JSON，`is_android_started` 键存在
- `info()` 遇到非 JSON 输出返回 None（不抛）
- `launch()` 超时返回 False

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_android_mumu.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**（`install_dir` 为空时按 `D:\Program Files\Netease\MuMu` → `C:\...` 探测，找不到则 `available()=False`）

- [ ] **Step 4: 跑测试确认通过**

- [ ] **Step 5: 提交**

---

### Task 3: AdbDevice 原语（screencap / tap / input / dump / app_start）

**Files:**
- Create: `core/android/device.py`
- Test: `tests/test_android_device.py`

**Interfaces:**
- Produces: `AdbDevice(adb_path: str, serial: str)`；`.connect() -> bool`、`.online() -> bool`、`.screencap() -> bytes`、`.tap(x, y) -> bool`、`.swipe(x1,y1,x2,y2,ms) -> bool`、`.input_text(s) -> bool`、`.dump() -> str`（XML）、`.app_start(pkg) -> bool`、`.app_stop(pkg)`、`.current_activity() -> str`、`.prop(key) -> str`

- [ ] **Step 1: 写失败测试**（打桩 subprocess）

关键用例：
- `dump()` 返回含 `<hierarchy` 的字符串；adb 报 "device offline" 时返回空串
- `screencap()` 返回以 `\x89PNG` 开头的 bytes；失败返回 b""
- `tap()` 坐标越界（负值）直接返回 False 不调 adb

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现**（串行执行，每条命令都有 timeout；`dump()` 内部先 dump 到 /sdcard 再 cat）
- [ ] **Step 4: 跑测试确认通过**
- [ ] **Step 5: 提交**

---

### Task 4: AndroidRuntime（单例 + 设备锁 + ensure_ready）

**Files:**
- Create: `core/android/runtime.py`
- Test: `tests/test_android_runtime.py`

**Interfaces:**
- Produces: `get_runtime(cfg) -> AndroidRuntime`（模块级缓存）、`.status() -> dict`（`{"state": "disabled|not_installed|stopped|starting|ready|error", "detail": str, "adb_ok": bool, "device": AdbDevice|None}`）、`.ensure_ready() -> (bool, str)`、`.device_lock()` 上下文管理器、`.last_error: str`

- `ensure_ready()`：未启用→`(False, "disabled")` 且**不碰 subprocess**；MuMu 不存在→`(False,"not_installed")`；实例未启动→launch 并轮询 `boot_timeout_s`；adb 连不上→`(False,"adb")`；成功→`(True,"ready")`

- [ ] **Step 1: 写失败测试**

关键用例：
- 关闭时空转：mock 掉 subprocess，断言调用次数为 0
- 未安装时 `ensure_ready()` 返回 `(False, "not_installed")`
- 已启动 + adb 通 → `(True, "ready")`
- 启动超时 → `(False, "timeout")` 且 `status()["state"]=="starting"`
- `device_lock()` 串行：两个线程同时进入，第二个必须等待（用 sleep 打桩计时）

- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现**
- [ ] **Step 4: 跑测试确认通过**
- [ ] **Step 5: 提交**

---

### Task 5: AppCrawler 基类

**Files:**
- Create: `crawlers/app_base.py`
- Test: `tests/test_app_crawler_base.py`

**Interfaces:**
- Produces: `AppCrawler`（**不继承** BaseCrawler）：`__init__(config, logger)`、`name`、`package`、`PATH_STATUS`（含 `calendar`）、`path_reset/path_note`（与 BaseCrawler 同签名同字段）、`safe_fetch(from_city,to_city,dates,ret_date="")`、`fetch()` 抽象、`login_url() -> str`（返回 App 登录入口描述）

- [ ] **Step 1: 写失败测试**：`safe_fetch` 在 `fetch` 抛异常时返回 `[]` 且记 `error` 路径；`path_note` 非法 status 归 `error`；日志行格式为 `[app_zhixing] ...`（健康正则要求）
- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现**（`path_note` 字段顺序与 BaseCrawler 一致，便于账本复用）
- [ ] **Step 4: 跑测试确认通过**
- [ ] **Step 5: 提交**

---

### Task 6: 智行日历族解析器（纯函数，可离线测）

**Files:**
- Create: `crawlers/app_zhixing_parse.py`
- Create: `tests/fixtures/zhixing_calendar_dump.xml`（真实 dump 脱敏）
- Test: `tests/test_app_zhixing_parse.py`

**Interfaces:**
- Produces: `parse_calendar(xml: str) -> list[dict]`（每项 `{"date","price"}`，price 为 int 或 None）、`parse_flight_rows(xml: str) -> list[dict]`、`detect_state(xml: str) -> str`（`"login"|"empty"|"ok"|"unknown"`）、`MASK_RE`

- `parse_calendar` 必须：
  - 从 `text="10-28"` + 相邻 `text="¥342"` 配对出日期与价
  - `¥3??` 识别为 `price=None` 且 `masked=True`，**不得**当成 0 或 3
  - 返回按日期升序

- [ ] **Step 1: 写失败测试**（含 masked 价、缺价日、乱序）
- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现**
- [ ] **Step 4: 跑测试确认通过**
- [ ] **Step 5: 提交**

---

### Task 7: 智行 App 渠道（接入 REGISTRY，但默认不启用）

**Files:**
- Create: `crawlers/app_zhixing.py`
- Modify: `crawlers/__init__.py:9-15`（REGISTRY 追加 `"app_zhixing"`）
- Test: `tests/test_app_zhixing_crawler.py`

**Interfaces:**
- Produces: `AppZhixingCrawler(AppCrawler)`，`name="app_zhixing"`，`package="cn.suanya.zhixing"`；`fetch()` 返回 `[FlightPrice]`（`price`=日历最低价，`flight_no=""`，`extra` 标注 `{"calendar": True, "masked": bool}`）

- fetch 流程：`runtime.ensure_ready()` → 失败即 `path_note(..., status)` 并返回 `[]` → `app_start` → `dump` → `detect_state` → 解析日历 → 产出 FlightPrice
- **不得**在未登录时伪造航班号或明细价

- [ ] **Step 1: 写失败测试**（打桩 runtime + device，验证：disabled 时返回 [] 且无 subprocess；ready 时用 fixture dump 产出正确价格；login 状态记 `login` 不记 empty）
- [ ] **Step 2: 跑测试确认失败**
- [ ] **Step 3: 实现**
- [ ] **Step 4: 跑测试确认通过**
- [ ] **Step 5: 提交**

---

### Task 8: 真机验证（真实 MuMu，非 mock）

**Files:**
- Create: `_scratch/spike_mobile/p1_live_check.py`

- [ ] **Step 1: 用真实运行时跑一次 SHA→北京 的日历采集**，打印耗时与结果条数
- [ ] **Step 2: 核对价格与 App 界面截图一致**（截图落 `_scratch/spike_mobile/evidence/`）
- [ ] **Step 3: 记录单次耗时基线**到 `docs/APP_CHANNELS.md`
- [ ] **Step 4: 提交**

**验收：** 至少产出 1 条真实日历价，且与界面显示一致；未登录时不出现任何航班明细价。

---

## 后续阶段（本计划不含，另行编写）

- P2：健康/账本/配置 UI 接入
- P3：网页内嵌登录画面 + 快照
- P4：美团
- P5：首次引导 + 发布
