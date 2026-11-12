# -*- coding: utf-8 -*-
"""分辨率 / DPI：让「机型声明的屏幕」和「设备真实屏幕」不再打架。

两种做法，风险和收益完全不同
--------------------------
**A. 身份对齐（``align_identity``，默认推荐，零风险）**

设备是 900×1600、密度 320，而身份池里那台 Redmi K50 声明 1080×2400/440。
风控只要读一次 ``DisplayMetrics`` 就能看出「机型与屏幕不符」——这比不伪装
更可疑。做法：把**身份档案里的 display/density 改成设备的真实值**，其余字段
（品牌/型号/build 指纹）不变。不改任何设备设置，坐标一个字都不用动。

**B. 真改屏幕（``spoof``，需要坐标换算，默认关闭）**

``wm size 1080x2400`` + ``wm density 440`` 之后，物理像素变了，而 App 渠道
的坐标**是按现有竖屏写死的**（`device.py` 里记过横屏 1600×900 让坐标全偏的
现场）。所以这一条必须配 ``AdbDevice.design`` 做**设计坐标系 → 设备坐标系**
的换算：

* 写死的常量按设计坐标系（900×1600）给；
* 从 UI 树 ``bounds`` 读出来的坐标已经是设备坐标系，用 ``dev.to_design()``
  换回设计坐标再参与比较/计算。

``design`` 默认 None = 完全不做换算（现状逐字不变）。这条设计上的取舍是
刻意的：**宁可默认不伪装，也不默认把一个会把坐标改坏的开关打开。**

DPI 的小知识（决定 B 方案会不会把界面搞变形）
-------------------------------------------
``wm density`` 与 ``wm size`` 同比例变化时，**dp 尺寸不变**，界面布局看起来
一样、只是更细；不同比例才叫"把界面放大/缩小"。所以 spoof 默认按
``density_new = density_old * (h_new / h_old)`` 同比缩放，避免布局错位。
"""
from __future__ import annotations

import re

from .fingerprint import _call, _text

DESIGN_DEFAULT = (900, 1600)


def actual(dev) -> dict:
    """读设备真实屏幕：``{"width","height","density","override"}``。"""
    out = {"width": 0, "height": 0, "density": 0, "override": False}
    size = _text(_call(dev, "shell", "wm", "size"))
    m = re.search(r"Override size:\s*(\d+)x(\d+)", size)
    if m:
        out["width"], out["height"] = int(m.group(1)), int(m.group(2))
        out["override"] = True
    else:
        m = re.search(r"Physical size:\s*(\d+)x(\d+)", size)
        if m:
            out["width"], out["height"] = int(m.group(1)), int(m.group(2))
    den = _text(_call(dev, "shell", "wm", "density"))
    m = re.search(r"Override density:\s*(\d+)", den)
    if m:
        out["density"] = int(m.group(1))
        out["override"] = True
    else:
        m = re.search(r"Physical density:\s*(\d+)", den)
        if m:
            out["density"] = int(m.group(1))
    return out


def audit(dev, ident) -> dict:
    """身份声明 vs 设备真实的差异报告（不改任何东西）。"""
    prof = getattr(ident, "profile", {}) or {}
    want = prof.get("display") or (0, 0)
    want_d = int(prof.get("density") or 0)
    got = actual(dev)
    issues = []
    if want and got["width"] and tuple(want) != (got["width"], got["height"]):
        issues.append("声明 %sx%s，设备 %dx%d"
                      % (want[0], want[1], got["width"], got["height"]))
    # 密度容差 15%：不同 ROM 的 density 会略有出入，不值得当问题
    if want_d and got["density"]:
        delta = abs(want_d - got["density"]) / float(want_d)
        if delta > 0.15:
            issues.append("声明 density %d，设备 %d" % (want_d, got["density"]))
    return {"ok": not issues, "issues": issues, "want": list(want) if want else [],
            "want_density": want_d, "got": got}


def align_identity(ident, dev) -> dict:
    """把身份档案的 display/density 对齐到设备真实值（零风险路线）。

    返回 ``{"changed": bool, "from": ..., "to": ...}``；拿不到真实屏幕就不动。
    """
    got = actual(dev)
    if not got["width"] or not got["height"]:
        return {"changed": False, "reason": "读不到 wm size"}
    data = getattr(ident, "data", None)
    if not isinstance(data, dict):
        return {"changed": False, "reason": "identity 不可写"}
    prof = data.get("profile")
    if not isinstance(prof, dict):
        return {"changed": False, "reason": "profile 缺失"}
    before = (list(prof.get("display") or []), int(prof.get("density") or 0))
    prof["display"] = [got["width"], got["height"]]
    if got["density"]:
        prof["density"] = got["density"]
    after = (list(prof["display"]), int(prof.get("density") or 0))
    if tuple(before[0]) == tuple(after[0]) and before[1] == after[1]:
        return {"changed": False, "from": before, "to": after}
    return {"changed": True, "from": before, "to": after}


def plan_spoof(dev, *, width: int = 0, height: int = 0,
               density: int = 0) -> dict:
    """算 target：只给宽高时，density 按同比缩放（保持 dp 尺寸不变）。"""
    got = actual(dev)
    w = int(width or 0) or got["width"]
    h = int(height or 0) or got["height"]
    d = int(density or 0)
    if not d and got["density"] and got["height"]:
        d = int(round(got["density"] * (h / float(got["height"]))))
    return {"width": w, "height": h, "density": d, "current": got}


def spoof(dev, *, width: int = 0, height: int = 0, density: int = 0) -> dict:
    """真改屏幕（``wm size``/``wm density``）。返回执行结果，不抛异常。

    调用方必须自己负责坐标换算（``AdbDevice.design``），否则 App 渠道的
    写死坐标会全偏。
    """
    p = plan_spoof(dev, width=width, height=height, density=density)
    rep = {"ok": False, "target": p, "applied": [], "error": ""}
    if not p["width"] or not p["height"]:
        rep["error"] = "没有可用的目标分辨率"
        return rep
    _call(dev, "shell", "wm", "size", "%dx%d" % (p["width"], p["height"]))
    rep["applied"].append("wm size %dx%d" % (p["width"], p["height"]))
    if p["density"]:
        _call(dev, "shell", "wm", "density", str(p["density"]))
        rep["applied"].append("wm density %d" % p["density"])
    got = actual(dev)
    rep["after"] = got
    rep["ok"] = (got["width"] == p["width"] and got["height"] == p["height"])
    return rep


def reset(dev) -> dict:
    """恢复出厂屏幕设置（``wm size reset`` / ``wm density reset``）。"""
    _call(dev, "shell", "wm", "size", "reset")
    _call(dev, "shell", "wm", "density", "reset")
    return {"ok": True, "after": actual(dev)}


def scale_for(design, actual_wh) -> tuple:
    """设计坐标系 → 设备坐标系的缩放比。任一为空返回 ``(1.0, 1.0)``。"""
    try:
        dw, dh = int(design[0]), int(design[1])
        aw, ah = int(actual_wh[0]), int(actual_wh[1])
    except (TypeError, ValueError, IndexError):
        return (1.0, 1.0)
    if min(dw, dh, aw, ah) <= 0:
        return (1.0, 1.0)
    return (aw / float(dw), ah / float(dh))