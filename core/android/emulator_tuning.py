# -*- coding: utf-8 -*-
"""MuMu 实例调优：把「点不动 / 白屏 / 半帧」这类整轮报废从根上掐掉。

为什么这件事比继续调指纹更影响爬取率
------------------------------------
App 渠道是**坐标驱动**的：脚本按 900×1600 竖屏写死坐标，靠 `uiautomator
dump` 找控件。两个现场条件会直接让整轮归零，而它们都与风控无关：

1. **动画未关**：页面切换/列表回弹期间，控件的**位置在变**。dump 拿到的是
   某一帧的坐标，点下去时控件已经移走——账本记成「设城市失败 / 页面认不
   出」，人看着像「这条通路时好时坏」。仓库里已经因为同类原因吃过两次亏
   （横屏 1600×900 让硬编码坐标全偏；复用残留界面导致后续航线卡在设城市）。
   关掉三档动画后，控件在 dump 与 tap 之间**不再移动**，这是最便宜且收益
   最直接的一刀。
2. **息屏/屏保/自动锁屏**：MuMu 前台窗口被系统息屏后，`screencap` 拿到黑图、
   `dump` 拿到空层级，表现是 `no-ui` / `blocked`。这些都是「设备就绪」之后
   才发生的，前面的健康检查看不到。

能改与不改
----------
* 改：`window_animation_scale` / `transition_animation_scale` /
  `animator_duration_scale` = 0、`svc power stayon true`、屏幕超时置最大、
  关屏保、预确认沉浸模式弹层。全部是 `settings`/`svc`，可逆、不影响身份。
* **不改**：分辨率与 DPI（这里不管）。要改屏幕用 ``display.spoof()``，
  并且**必须**同时 ``dev.set_design()`` 开坐标换算，否则 App 渠道按现有
  竖屏写死的坐标会按比例偏（这条是本模块与 ``display`` 的分工边界）。
* 改：**自动旋转也在这里固化**（`accelerometer_rotation=0` +
  `user_rotation=0`）。原先把这件事只交给 `device.lock_portrait()`，
  但它是按需调用、且实例重启后 MuMu（`window_auto_rotate`）会把
  `accelerometer_rotation` 重新置 1 —— 现场表现就是飞猪/携程 App 隔几轮
  又变回横屏，硬编码坐标整片失效。放进调优层后每 boot 至少校一次，
  与动画开关同一张标记文件、同一次 adb 往返，成本为零。
* **不改**：CPU/内存分配（要重启实例，且属于宿主机资源决策，交给操作员）。

失败一律 fail-soft：读不到就跳过，绝不阻断采集。
"""
from __future__ import annotations

from .fingerprint import _call, _text, boot_id

# 设备内标记：`<boot_id>`。这些设置持久化在 settings.db 里，按 boot 只做一次
# 检查即可；同周期重复调用只花一条 adb（读标记）。
_MARK = "/data/local/tmp/tm_tuned_%d.ok"

# 关掉即可，值就是 0/1/秒
_SETTINGS = (
    ("global", "window_animation_scale", "0"),
    ("global", "transition_animation_scale", "0"),
    ("global", "animator_duration_scale", "0"),
    ("system", "screen_off_timeout", "2147483647"),
    ("secure", "screensaver_enabled", "0"),
    ("secure", "immersive_mode_confirmations", "confirmed"),
    # 竖屏锁：MuMu 的 window_auto_rotate=true 会在实例重启后把这两项置回
    # （accelerometer_rotation=1），App 随后转成横屏、写死坐标全偏。放在
    # 调优层是为了"每 boot 至少校一次"，而不是等某个调用方记得去锁。
    ("system", "accelerometer_rotation", "0"),
    ("system", "user_rotation", "0"),
)

# 期望值（验收用）：只核对三档动画、常亮与竖屏锁
_EXPECT = {
    "window_animation_scale": "0",
    "transition_animation_scale": "0",
    "animator_duration_scale": "0",
    "accelerometer_rotation": "0",
    "user_rotation": "0",
}


def _mark_path(vm: int) -> str:
    return _MARK % int(vm)


def verify(dev) -> dict:
    """读回关键项。返回 ``{"ok": bool, "values": {...}}``。"""
    values = {}
    for scope, key, _want in _SETTINGS:
        if key not in _EXPECT:
            continue
        values[key] = _text(
            _call(dev, "shell", "settings", "get", scope, key)).strip()
    ok = all(values.get(k) == v for k, v in _EXPECT.items())
    return {"ok": ok, "values": values}


def apply(dev, config: dict = None, logger=None, *, vm: int = 0,
          force: bool = False) -> dict:
    """关动画 + 常亮 + 关屏保。返回 ``{"ok", "actions", "verify", "skipped"}``。

    挂在 `AndroidRuntime.ensure_ready()` 里、身份硬化之后：那时 adb 已通，
    且还没启动任何 App（设置对**之后**启动的进程生效，动画开关本身是全局的，
    不需要重启 App）。
    """
    sec = ((config or {}).get("android") or {}).get("tuning") \
        if isinstance(config, dict) else None
    sec = sec if isinstance(sec, dict) else {}
    if sec.get("enabled") is False:
        return {"ok": True, "skipped": "tuning disabled", "actions": []}

    rep = {"ok": False, "actions": [], "verify": {}, "skipped": ""}
    boot = boot_id(dev)
    cur = _text(_call(dev, "shell", "cat", _mark_path(vm))).strip()
    if not force and boot and cur == boot:
        rep["ok"] = True
        rep["skipped"] = "tuned this boot"
        return rep

    for scope, key, want in _SETTINGS:
        _call(dev, "shell", "settings", "put", scope, key, want)
        rep["actions"].append("settings %s %s=%s" % (scope, key, want))
    # 充电时保持唤醒（MuMu 永远处于"充电"状态，这条最稳）
    _call(dev, "shell", "svc", "power", "stayon", "true")
    rep["actions"].append("svc power stayon true")

    rep["verify"] = verify(dev)
    # 统一走 write_remote：`sh -c "echo X > path"` 在 Windows 上静默失败
    from .fingerprint import write_remote
    write_remote(dev, _mark_path(vm), boot or "1")
    rep["ok"] = bool(rep["verify"].get("ok"))
    if logger:
        v = rep["verify"].get("values") or {}
        logger.info("[android] 实例调优：动画关 %s，常亮生效 %s",
                    "ok" if all(v.get(k) == g for k, g in _EXPECT.items())
                    else "未确认",
                    "ok" if rep["ok"] else "待复核")
    return rep


def _quote(v) -> str:
    return "'" + str(v).replace("'", "'\\''") + "'"
