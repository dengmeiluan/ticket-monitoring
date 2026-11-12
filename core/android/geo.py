"""App 定位固定（r1063 T45）：把模拟器的 GPS 钉在指定坐标。

为什么要做
----------
风控最便宜的一条矛盾是「**IP 在 A 地、时区在 B 地、GPS 在 C 地**」。
本仓已有 `crawler.geo`（时区/语言）与出口 IP 的对齐，但 **App 通路的 GPS 从没设过**：
Android 模拟器出厂定位是「加州山景城」（Google 总部），一家上海出发的机票 App
读到设备在加州 —— 这是比 UA 写得更花哨危险得多的硬矛盾。

做法
----
Android 模拟器（含 MuMu）都支持 adb 的 emulator console 命令：

    adb -s <serial> emu geo fix <经度> <纬度> [海拔]

配合 `settings put secure location_mode 3`（GPS+网络定位都开）。
两步都是**幂等**的，可以每次开查前重打一遍（模拟器重启/被回收后会回到默认点）。

默认坐标：**上海浦东世博片区**（中华艺术宫/世博大道一带）。
口径与 `geolocation` 一致：经度在前、纬度在后（`geo fix` 的历史顺序）。
"""
from __future__ import annotations

import logging

_LOG = logging.getLogger(__name__)

# 上海浦东世博片区（中华艺术宫 / 世博大道一带）
SHANGHAI_EXPO = {
    "name": "上海浦东世博片区",
    "lat": 31.1874,
    "lon": 121.4921,
    "alt": 10,
}

# Android 的定位模式：0=全关 1=仅设备(GPS) 2=仅网络 3=GPS+网络（真机默认）
LOCATION_MODE_ALL = 3


def coords_from(config: dict = None) -> dict:
    """从 `android.geo` 段读坐标；缺省 = 上海世博片区。

    支持 `android.geo: {enabled: true, lat: .., lon: .., alt: .., name: ..}`。
    `enabled` 显式为假时返回 `{}`（不动设备）。
    """
    sec = {}
    if isinstance(config, dict):
        sec = config.get("geo") if isinstance(config.get("geo"), dict) else {}
        # 也允许整段 config 传进来（调用方有时传顶层配置）
        if not sec and isinstance(config.get("android"), dict):
            a = config["android"]
            sec = a.get("geo") if isinstance(a.get("geo"), dict) else {}
    if sec.get("enabled") is False:
        return {}
    out = dict(SHANGHAI_EXPO)
    for k in ("lat", "lon", "alt"):
        v = sec.get(k)
        if v is None or v == "":
            continue
        try:
            out[k] = float(v)
        except (TypeError, ValueError):
            pass
    if sec.get("name"):
        out["name"] = str(sec["name"])
    return out


def _adb(dev, *args, timeout: float = 20):
    """跑一条 adb 命令（r1063 T59 修：之前调 `dev.sh()`，真实设备上是 `_sh`）。

    依次尝试三种入口，任一成功即返回其输出：

    * `AdbDevice._sh(*args)` —— 仓库里真实的执行入口（`adb -s <serial> <args…>`）；
    * `AdbDevice.run_script("shell <cmd>")` —— 只支持 shell 形式的命令；
    * `dev.sh(*args)` —— 测试替身/旧封装，保留兼容。

    三样都没有就抛 `AttributeError`——**不要静默返回空**：那会让"定位没设上"
    看起来像"设上了"，正是这次事故难看的地方。
    """
    sh = getattr(dev, "_sh", None)
    if callable(sh):
        return sh(*args, timeout=timeout)
    if args and str(args[0]) == "shell":
        run = getattr(dev, "run_script", None)
        if callable(run):
            return run(" ".join(str(a) for a in args[1:]), timeout=timeout)
    sh2 = getattr(dev, "sh", None)
    if callable(sh2):
        return sh2(*args, timeout=timeout)
    raise AttributeError("设备对象没有可用的 adb 执行入口（_sh/run_script/sh 都没有）")


def _emu_geo_fix(dev, lat: float, lon: float, alt: float) -> tuple:
    """`adb emu geo fix <lon> <lat> <alt>`。返回 (ok, detail)。"""
    try:
        out = _adb(dev, "emu", "geo", "fix", str(lon), str(lat), str(alt),
                   timeout=20)
    except Exception as e:
        return False, "emu geo fix 失败：%s" % str(e)[:80]
    text = str(out or "")
    if "KO" in text or "error" in text.lower():
        return False, "emu geo fix 被拒：%s" % text.strip()[:60]
    return True, text.strip()[:60] or "ok"


def _enable_providers(dev) -> bool:
    """打开定位开关（否则坐标设了也没人读）。"""
    ok = False
    for cmd in (
            "settings put secure location_mode %d" % LOCATION_MODE_ALL,
            "settings put secure location_providers_allowed +gps,+network"):
        try:
            _adb(dev, "shell", cmd, timeout=15)
            ok = True
        except Exception:
            continue
    return ok


def last_location(dev) -> str:
    """读回最近一次定位（用于验证），读不到返回空串。"""
    for cmd in ("dumpsys location", "cmd location providers"):
        try:
            out = str(_adb(dev, "shell", cmd, timeout=20) or "")
        except Exception:
            continue
        if not out:
            continue
        for line in out.splitlines():
            low = line.lower()
            if "last location" in low or "last known" in low or "gps:" in low:
                return line.strip()[:160]
        return out.strip().splitlines()[0][:160] if out.strip() else ""
    return ""


def fix(dev, config: dict = None, *, logger=None) -> dict:
    """把设备定位钉到配置坐标（幂等，可每次开查前调用）。**失败绝不阻断采集。**"""
    log = logger or _LOG
    pos = coords_from(config)
    if not pos:
        return {"ok": False, "skipped": True, "detail": "定位固定已关闭"}
    lat, lon, alt = pos["lat"], pos["lon"], pos.get("alt", 0)
    ok, detail = _emu_geo_fix(dev, lat, lon, alt)
    providers = _enable_providers(dev)
    rep = {"ok": bool(ok), "lat": lat, "lon": lon, "name": pos.get("name", ""),
           "detail": detail, "providers": providers}
    if ok:
        try:
            log.info("[定位] 已钉到 %s（%.4f, %.4f）", pos.get("name", ""),
                     lat, lon)
        except Exception:
            pass
    else:
        try:
            log.warning("[定位] 钉坐标失败（不阻断采集）：%s", detail)
        except Exception:
            pass
        # 记账（r1063 T60）：只写日志等于没写——上轮"定位从没设上"就藏在这里
        try:
            from core import degraded as _dg
            _dg.note("app_geo", "", detail)
        except Exception:
            pass
    return rep


def status(dev, config: dict = None) -> dict:
    """核对定位状态（r1063 T64 改）：**三段如实报告**，不猜。

    * `mode`：`settings get secure location_mode`（3 = GPS+网络都开）；
    * `providers`：`location_providers_allowed`；
    * `last`：最近一次定位。**只有应用请求过才会有值**——`null` 说明"还没人问过"，
      不代表坐标没设上（这一条以前被我误读成失败）。

    `verdict` 只有三种：`已设置` / `未请求过（正常）` / `无法确认`。
    """
    pos = coords_from(config)
    mode = str(_adb(dev, "shell", "settings get secure location_mode",
                    timeout=15) or "").strip()
    prov = str(_adb(dev, "shell", "settings get secure "
                                          "location_providers_allowed",
                    timeout=15) or "").strip()
    last = last_location(dev)
    if mode == "3" and "gps" in prov.lower():
        verdict = "已设置" if last and "null" not in last.lower() \
            else "未请求过（正常）"
    elif last and "null" not in last.lower():
        verdict = "已设置"
    else:
        verdict = "无法确认"
    out = {"want": pos, "mode": mode, "providers": prov, "last": last,
           "verdict": verdict,
           # 「未请求过」也算设好了：坐标在、开关在，只是还没有应用来查
           "ok": verdict in ("已设置", "未请求过（正常）")}
    if verdict == "无法确认":
        try:
            from core import degraded as _dg
            _dg.note("app_geo", "", "定位状态无法确认（mode=%s）" % mode)
        except Exception:
            pass
    return out
