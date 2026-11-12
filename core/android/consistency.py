"""设备环境**自洽性审计**（r1063 T83）：找出风控 SDK 一眼能看穿的矛盾。

背景（用户实测，长期存在）：
* 携程 App 登录**固定 50003**；
* 飞猪点「机票」弹阿里 NC 滑块，一滑就 `请点我重试(error:xxxx)`；
* 同一台机的智行/去哪儿 App 却正常出数（19s）。

用户问：是否 MuMu 底层 ID 被封？要不要换 ID？

真机取到的证据表明问题**不是"某个 ID 被封"**，而是这台机器的"设备脸"**自相矛盾**：

| 项 | 实测值 | 真机应该是 |
|---|---|---|
| `ro.product.brand/model` | vivo / V2405A | vivo X200 Pro = 天玑 9400 |
| `/proc/cpuinfo Hardware` | **MT6991**（天玑 9400）| 与上面一致 ✓ |
| `ro.board.platform` | **mt6897**（天玑 9300）| 应为 mt6991 ✗ |
| `ro.hardware` | **mt6897** | 应为 mt6991 ✗ |
| `ro.soc.manufacturer/model` | 空 / MT6991 | MediaTek / MT6991 ✗ |
| GPU `GL_RENDERER` | **Adreno (TM) 750**（高通）| Immortalis-G925（ARM Mali）✗ |
| `ro.product.cpu.abilist` | 含 **x86_64,x86** | 只有 ARM ✗ |
| `ro.product.marketname` | 空 | vivo X200 Pro ✗ |

风控 SDK 不需要"知道你是模拟器"，只要发现**GPU 与 SoC 冲突**、**同机型两颗芯片**，
就足以判定"环境异常"——这正是 50003 / 强制滑块的常见触发路径。

ABI 那条**不能直接改**：`abi_canary` 已实测把 ABI 改成 arm64 会让携程
`SIGSEGV`（加固 so 与 ABI 绑定），所以那条只能按包实测、且目前判定为"不允许"。

本模块只做**只读审计**：把矛盾列出来并给出建议，不改任何状态。
"""

from __future__ import annotations

import re

# 高通 SoC → 平台代号（`ro.board.platform`）。高通机型 `ro.hardware` 恒为
# `qcom`，`ro.board.platform` 是代号——**它本来就不等于 SoC 串**，
# 拿 SoC 串去比会误报（r1063 T84 真机踩到）。
QCOM_PLATFORM = {
    "SM8650": ("pineapple",),
    "SM8550": ("kalama",),
    "SM8475": ("cape",),
    "SM8450": ("taro",),
    "SM8350": ("lahaina",),
    "SM8250": ("kona",),
    "SM7325": ("yupik",),
}

# SoC → 该机型的 GPU 家族（用于判断 GL_RENDERER 是否自洽）
SOC_GPU = {
    "MT6991": ("ARM Mali", ("Immortalis", "Mali")),
    "MT6989": ("ARM Mali", ("Immortalis", "Mali")),
    "MT6897": ("ARM Mali", ("Immortalis", "Mali")),
    "SM8650": ("Qualcomm", ("Adreno",)),
    "SM8550": ("Qualcomm", ("Adreno",)),
    "SM8475": ("Qualcomm", ("Adreno",)),
    "Tensor": ("ARM Mali", ("Mali",)),
}

# 市场名（model 码 → 对外名称）。真机上这个 prop 是有值的，
# 空的会与"品牌+型号"对不上。
MARKETNAME = {
    "V2405A": "vivo X200 Pro",
    "23127PN0CC": "Xiaomi 14",
    "2201123C": "Xiaomi 12",
    "SM-S9280": "Galaxy S24 Ultra",
}


def _soc_family(soc_model: str):
    """`MT6991` → ("ARM Mali", ("Immortalis","Mali"))；认不出返回 (None, ())。"""
    s = str(soc_model or "").upper()
    for k, v in SOC_GPU.items():
        if s.startswith(k.upper()):
            return v
    return (None, ())


def audit(facts: dict) -> dict:
    """传入实测事实，返回 {ok, items:[{key,got,want,level,hint}], summary}。

    `facts` 键（缺的项跳过，不猜）：
      brand/model/board/hardware/soc_model/soc_manufacturer/marketname/
      abilist/gl_renderer/cpuinfo_hardware
    """
    items = []

    def add(key, got, want, level, hint):
        items.append({"key": key, "got": str(got or ""), "want": str(want or ""),
                      "level": level, "hint": hint})

    soc = facts.get("soc_model") or facts.get("cpuinfo_hardware") or ""
    board = facts.get("board") or ""
    hw = facts.get("hardware") or ""
    cpu_hw = facts.get("cpuinfo_hardware") or ""

    # ① 平台代号要与 SoC **同族**（不是"字面相等"——高通机型的 board 是代号）
    soc_up = str(soc).upper()
    if soc_up.startswith("MT"):
        for name, val in (("ro.board.platform", board), ("ro.hardware", hw)):
            if val and val.upper() != soc_up:
                add(name, val, soc, "high",
                    "联发科机型的 board/hardware 应等于小写 SoC（mtXXXX）")
    elif soc_up.startswith("SM"):
        if hw and hw.lower() != "qcom":
            add("ro.hardware", hw, "qcom", "high",
                "高通机型 ro.hardware 恒为 qcom")
        want = QCOM_PLATFORM.get(soc_up, ())
        if want and board and board.lower() not in want:
            add("ro.board.platform", board, "/".join(want), "mid",
                "高通机型的 board 是平台代号（与 SoC 串不同名是正常的）")
    # 判据用**包含**：真机 Hardware 行可能写 `Qualcomm Technologies, Inc SM8650`
    # 也可能是 `MT6991`，与 ro.soc.model 字面不等但语义一致。
    if soc and cpu_hw:
        _a, _b = str(soc).upper(), str(cpu_hw).upper()
        if not (_a in _b or _b in _a):
            add("ro.soc.model vs cpuinfo", soc, cpu_hw, "high",
                "SoC 两处不一致（型号与 Hardware 行对不上）")

    # ② GPU 与 SoC 必须同一家
    fam, marks = _soc_family(soc)
    gl = str(facts.get("gl_renderer") or "")
    if fam and gl:
        if not any(m.lower() in gl.lower() for m in marks):
            add("GL_RENDERER", gl, "%s（%s 的 GPU）" % ("/".join(marks), soc),
                "high", "GPU 与 SoC 不同家：这是模拟器最常被查的破绽之一")

    # ③ abilist 里有 x86 = 转译层铁证
    abi = str(facts.get("abilist") or "")
    if abi and ("x86" in abi.lower()):
        add("ro.product.cpu.abilist", abi, "只有 ARM（arm64-v8a,armeabi-v7a,armeabi）",
            "high",
            "真机不会有 x86；但**不能随便改**——abi_canary 实测会让携程 SIGSEGV，"
            "只能按包实测后决定")

    # ④ 市场名缺失
    model = str(facts.get("model") or "")
    mk = str(facts.get("marketname") or "")
    if model and not mk and model in MARKETNAME:
        add("ro.product.marketname", "（空）", MARKETNAME[model], "mid",
            "真机这个 prop 有值；空的与品牌+型号对不上")

    # ⑤ soc.manufacturer 缺失
    sm = str(facts.get("soc_manufacturer") or "")
    if soc.upper().startswith("MT") and not sm:
        add("ro.soc.manufacturer", "（空）", "MediaTek", "mid",
            "联发科机型这个 prop 有值")

    # 电池电压：真机常 3700–4400 mV。异常低/为 0 是模拟器软特征（改不掉，
    # `dumpsys battery set` 不支持 voltage，sysfs 也只读）。
    try:
        _raw = str(facts.get("battery_voltage") or "").strip()
        # 缺这项就跳过（docstring 的「缺的项跳过，不猜」）：把缺失当 0
        # 会把每台未采集电池的机器都误报成模拟器。
        if not _raw:
            raise ValueError("battery_voltage absent")
        _v = int(_raw)
        # 采到了但为 0 也要报：真机从不会报 0 mV（本机 dumpsys 0/3，sysfs 3300）
        if _v < 3500:
            add("battery.voltage_now", "%d mV" % _v, "3700–4400 mV", "mid",
                "模拟器电池电压异常低；`dumpsys battery set voltage` 不支持、"
                "sysfs 只读 —— 属改不掉的一类（与 ABI 并列）")
    except (TypeError, ValueError):
        pass

    high = [i for i in items if i["level"] == "high"]
    return {"ok": not high, "items": items, "high": len(high),
            "total": len(items),
            "summary": ("发现 %d 处矛盾（其中 %d 处高风险）" % (len(items), len(high)))
                       if items else "设备脸自洽"}


def collect(dev, cfg: dict = None) -> dict:
    """从设备读事实（只读）。读不到的键就不放进去，交给 `audit` 跳过。"""
    out = {}

    def prop(k):
        try:
            fn = getattr(dev, "getprop", None)
            if callable(fn):
                return str(fn(k) or "").strip()
            return str(dev._sh("shell", "getprop", k) or "").strip()
        except Exception:
            return ""

    out["brand"] = prop("ro.product.brand")
    out["model"] = prop("ro.product.model")
    out["board"] = prop("ro.board.platform")
    out["hardware"] = prop("ro.hardware")
    out["soc_model"] = prop("ro.soc.model")
    out["soc_manufacturer"] = prop("ro.soc.manufacturer")
    out["marketname"] = prop("ro.product.marketname")
    out["abilist"] = prop("ro.product.cpu.abilist")
    # 电池软特征（r1063 T104）：风控 SDK 常查"是否永远插电/电压是否合理"
    try:
        _b = str(dev._sh("shell", "dumpsys battery") or "")
        import re as _re
        for _k, _key in (("voltage", "battery_voltage"),
                         ("temperature", "battery_temp"),
                         ("level", "battery_level")):
            m = _re.search(_k + r":\s*(-?\d+)", _b)
            if m:
                out[_key] = m.group(1)
        if "AC powered: true" in _b:
            out["battery_ac"] = "true"
    except Exception:
        pass
    try:
        from .fingerprint import _text, as_root
        cpu = _text(as_root(dev, "cat /proc/cpuinfo | grep -m1 Hardware")) or ""
        # 取**整行**：真机 Hardware 常是 `Qualcomm Technologies, Inc SM8650`
        # 这种多词形态，只取第一个词会把它读成 `Qualcomm`（假矛盾）
        m = re.search(r"Hardware\s*:\s*(.+)", cpu)
        if m:
            out["cpuinfo_hardware"] = m.group(1).strip()[:64]
        gl = _text(as_root(dev, "dumpsys SurfaceFlinger | grep -m1 -i 'GLES:'")) or ""
        m2 = re.search(r"GLES:\s*([^,]+),\s*([^,]+)", gl)
        if m2:
            out["gl_renderer"] = "%s %s" % (m2.group(1).strip(), m2.group(2).strip())
    except Exception:
        pass
    return out

def note_if_issues(dev, cfg: dict = None) -> dict:
    """审计一次并把结果记进降级账本（面板「降级」那行会显示）。

    为什么值得占一条降级位：设备脸矛盾是**最常见、也最容易被忽略**的
    "0 条"根因（携程 50003 / 阿里强制滑块都可能是它），而它不在任何
    采集日志里——不单独记账，用户永远看不到。
    """
    try:
        facts = collect(dev, cfg)
        rep = audit(facts)
    except Exception as e:
        return {"ok": False, "why": "%s: %s" % (type(e).__name__, str(e)[:60])}
    if rep.get("high"):
        try:
            from core import degraded as _dg
            first = next((i for i in rep["items"] if i["level"] == "high"), {})
            _dg.note("device_env", "",
                     "%d 处矛盾（%s：现 %s / 应 %s）"
                     % (rep["high"], first.get("key", ""),
                        str(first.get("got", ""))[:24],
                        str(first.get("want", ""))[:24]))
        except Exception:
            pass
    return rep


def _main(argv=None):                              # pragma: no cover - CLI
    """CLI：读真机 → 审计 → 打印。0=自洽，1=有高风险矛盾。"""
    import json as _json
    import logging
    import sys

    argv = list(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    cfg = {"android": {}}
    try:
        import yaml
        with open("config.yaml", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception:
        pass
    from . import emulator
    dev = emulator.device(cfg)
    if dev is None:
        print("拿不到设备（模拟器没开/没连上）")
        return 1
    facts = collect(dev, cfg)
    rep = audit(facts)
    if "--json" in argv:
        print(_json.dumps({"facts": facts, "audit": rep}, ensure_ascii=False,
                          indent=1, default=str))
        return 0 if rep["ok"] else 1
    print("设备脸事实：")
    for k, v in facts.items():
        if v:
            print("  %-22s %s" % (k, str(v)[:60]))
    print("\n审计：%s" % rep["summary"])
    for it in rep["items"]:
        print("  [%-4s] %-30s 现=%-30s 应=%s"
              % (it["level"], it["key"], it["got"][:30], it["want"][:40]))
        if it.get("hint"):
            print("         → %s" % it["hint"][:100])
    if not rep["items"]:
        print("  （无矛盾，设备脸自洽）")
    return 0 if rep["ok"] else 1


if __name__ == "__main__":                         # pragma: no cover
    raise SystemExit(_main())
