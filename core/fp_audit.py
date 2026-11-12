"""指纹一致性核账（离线）：找出「自己和自己矛盾」的地方。

为什么不靠"看起来像"：风控判的不是单个字段像不像人，而是**字段之间互相印证**。
同一个会话里 UA 说 Safari、引擎却是 Chromium，比 UA 写得更花哨危险得多——
这类矛盾是高熵特征，一次就够判定。

本模块只做**只读核账**：
  * 输入是「一份指纹档案 + 相关配置」（不碰浏览器、不碰设备），所以能进单测、
    能在 CI 跑、能给面板当读数；
  * 输出是 `[{id, level, title, detail, fix}]`：`level` 取 `high/mid/low`，
    `fix` 是能直接照做的一句中文；
  * 没有命中就返回空列表——「已知矛盾全清」这句话才成立。

核的六条（都是**可复现的字段对照**，不是猜测）
---------------------------------------------
1. `ua_vs_runtime`   UA 声明的引擎族必须与运行时一致（本仓运行时是 Chromium）
2. `ua_ch_vs_ua`     `sec-ch-ua*` 必须与 UA 的 Chrome 大版本一致；移动档必须 `?1`+Android
3. `mobile_vs_viewport` 移动 UA 必须配窄视口 + 触摸；桌面 UA 配宽视口
4. `locale_vs_accept_language` `Accept-Language` 的第一语言必须等于 `locale`
5. `tls_vs_ua`       TLS 指纹（curl_cffi impersonate）族必须与 UA 同族
6. `timezone_vs_geo` 配置了出口地理时，时区必须与该地区自洽（国内 + 境外时区是最便宜的矛盾）
"""
from __future__ import annotations

import re

LEVELS = ("high", "mid", "low")

# 运行时是 Chromium：UA 必须声称 Chromium 系（Chrome / Chromium / Edg / OPR）。
_CHROMIUM_UA = re.compile(r"(Chrome|Chromium|Edg|OPR)/\d+", re.I)
_SAFARI_ONLY = re.compile(r"Version/\d+(\.\d+)*.*Safari/", re.I)
_FIREFOX = re.compile(r"Firefox/\d+", re.I)

# 时区 → 可接受的国家/地区（粗粒度：只用来抓"明显跨区"）
_TZ_REGION = {
    "Asia/Shanghai": ("CN",),
    "Asia/Chongqing": ("CN",),
    "Asia/Urumqi": ("CN",),
    "Asia/Hong_Kong": ("HK", "CN"),
    "Asia/Macau": ("MO", "CN"),
    "Asia/Taipei": ("TW",),
    "Asia/Tokyo": ("JP",),
    "Asia/Seoul": ("KR",),
    "Asia/Singapore": ("SG",),
    "Asia/Bangkok": ("TH",),
    "Asia/Kuala_Lumpur": ("MY",),
    "America/New_York": ("US",),
    "America/Los_Angeles": ("US",),
    "Europe/London": ("GB",),
    "Europe/Berlin": ("DE",),
}


def _bad(fid, level, title, detail, fix):
    return {"id": fid, "level": level, "title": title,
            "detail": str(detail), "fix": fix}


def check_ua_vs_runtime(fp):
    """UA 声明的引擎族必须与运行时一致。

    本仓所有浏览器通路都跑在 Playwright Chromium 上，所以：
      * `Firefox/…`、`Version/… Safari/…`（Safari 专属形态）都是**直接矛盾**；
      * 真正安全的写法是 Android Chrome / Windows Chrome。
    """
    ua = str((fp or {}).get("ua") or "")
    if not ua:
        return [_bad("ua_vs_runtime", "high", "UA 为空",
                     "没有 UA：请求头会退回库默认值",
                     "在指纹档案里显式写 UA")]
    if _FIREFOX.search(ua):
        return [_bad("ua_vs_runtime", "high", "UA 声称 Firefox，引擎是 Chromium",
                     "navigator.userAgent 与 JS 引擎能力对不上",
                     "改用 Chrome 系 UA（桌面 Windows Chrome / 移动 Android Chrome）")]
    if _SAFARI_ONLY.search(ua) and not _CHROMIUM_UA.search(ua):
        return [_bad("ua_vs_runtime", "high", "UA 声称 Safari，引擎是 Chromium",
                     "Safari 专属 UA 会与 navigator.userAgentData、"
                     "window.chrome、UA-CH 头三处同时矛盾",
                     "改用 Android Chrome UA（移动档）或 Windows Chrome UA（桌面档）")]
    if not _CHROMIUM_UA.search(ua):
        return [_bad("ua_vs_runtime", "mid", "UA 里没有可核对的 Chrome 版本",
                     "无法与 UA-CH / 内核版本对齐",
                     "UA 里带上 Chrome/<主版本>")]
    return []


def check_ua_ch_vs_ua(fp, headers=None):
    """`sec-ch-ua*` 必须与 UA 自洽（版本、移动位、平台）。"""
    fp = fp or {}
    ua = str(fp.get("ua") or "")
    mobile = bool(fp.get("is_mobile"))
    h = {str(k).lower(): v for k, v in (headers or {}).items()}
    out = []
    m = re.search(r"Chrome/(\d+)", ua)
    major = m.group(1) if m else ""
    if mobile:
        # 移动 Chromium 也会发 UA-CH：缺了或说"?0" 都是矛盾
        mo = str(h.get("sec-ch-ua-mobile") or "")
        if "sec-ch-ua" not in h:
            out.append(_bad("ua_ch_vs_ua", "mid", "移动档没有 UA-CH",
                            "Android Chrome 会发 sec-ch-ua*；缺了等于自曝被改写",
                            "移动档补 sec-ch-ua / ?1 / \"Android\""))
        elif mo.strip() not in ("?1", '"1"', "1"):
            out.append(_bad("ua_ch_vs_ua", "mid", "移动档的 sec-ch-ua-mobile 不是 ?1",
                            "UA 说移动端，头里说非移动",
                            "移动档统一 sec-ch-ua-mobile: ?1"))
        plat = str(h.get("sec-ch-ua-platform") or "")
        if plat and "android" not in plat.lower():
            out.append(_bad("ua_ch_vs_ua", "mid", "移动档平台不是 Android",
                            "收到 %r" % plat, "移动档 sec-ch-ua-platform 写 \"Android\""))
    elif "sec-ch-ua" in h and major:
        got = str(h.get("sec-ch-ua") or "")
        if major not in got:
            out.append(_bad("ua_ch_vs_ua", "high", "UA-CH 版本与 UA 不一致",
                            "UA 说 Chrome/%s，头里是 %s" % (major, got[:60]),
                            "UA-CH 的 v= 与 UA 的 Chrome 主版本对齐"))
        if str(h.get("sec-ch-ua-platform") or "").strip('"') not in (
                "Windows", "macOS", "Linux", ""):
            out.append(_bad("ua_ch_vs_ua", "mid", "桌面档平台可疑",
                            str(h.get("sec-ch-ua-platform")),
                            "桌面档写 \"Windows\"（与 UA 的 Windows NT 一致）"))
    return out


def check_mobile_vs_viewport(fp, viewport=None):
    """移动 UA 必须配窄视口 + 触摸；桌面 UA 不能配手机视口。"""
    fp = fp or {}
    mobile = bool(fp.get("is_mobile"))
    vp = viewport or {}
    w = int(vp.get("width") or 0)
    touch = vp.get("has_touch")
    out = []
    if mobile:
        if w and w > 600:
            out.append(_bad("mobile_vs_viewport", "high", "移动 UA 配桌面视口",
                            "UA 说手机，视口宽 %d" % w, "移动档视口 ≤ 500（常用 390×844）"))
        if touch is False:
            out.append(_bad("mobile_vs_viewport", "high", "移动 UA 但触摸关闭",
                            "has_touch=false 与手机 UA 矛盾", "移动档打开 has_touch"))
    else:
        if w and w < 500:
            out.append(_bad("mobile_vs_viewport", "mid", "桌面 UA 配手机视口",
                            "视口宽 %d" % w, "桌面档视口 ≥ 1200（常用 1366×900）"))
    return out


def check_locale_vs_accept_language(fp, headers=None):
    fp = fp or {}
    loc = str(fp.get("locale") or "").strip()
    h = {str(k).lower(): v for k, v in (headers or {}).items()}
    al = str(h.get("accept-language") or "")
    if not loc or not al:
        return []
    first = al.split(",")[0].strip().lower()
    if first != loc.replace("_", "-").lower():
        return [_bad("locale_vs_accept_language", "mid",
                     "Accept-Language 与 locale 不一致",
                     "locale=%s，头首语言=%s" % (loc, first),
                     "Accept-Language 首语言跟随 locale")]
    return []


def check_tls_vs_ua(fp, tls_impersonate=""):
    """TLS 指纹族必须与 UA 同族（curl_cffi impersonate）。"""
    fp = fp or {}
    ua = str(fp.get("ua") or "").lower()
    imp = str(tls_impersonate or "").lower()
    if not imp or imp in ("off", "none"):
        return []
    if "firefox" in ua and "firefox" not in imp:
        return [_bad("tls_vs_ua", "high", "TLS 指纹与 UA 不同族",
                     "UA=Firefox，impersonate=%s" % imp, "两者用同一浏览器族")]
    if "safari" in ua and "safari" not in imp and not _CHROMIUM_UA.search(ua):
        return [_bad("tls_vs_ua", "high", "TLS 指纹与 UA 不同族",
                     "UA=Safari，impersonate=%s" % imp, "两者用同一浏览器族")]
    return []


def check_timezone_vs_geo(fp):
    """配了出口地理时，时区必须自洽（国内站 + 境外时区是最便宜的矛盾）。"""
    fp = fp or {}
    tz = str(fp.get("timezone") or "")
    geo = str(fp.get("geo") or fp.get("country") or "").upper()
    if not tz or not geo:
        return []
    ok = _TZ_REGION.get(tz)
    if ok and geo not in ok:
        return [_bad("timezone_vs_geo", "mid", "时区与出口地理不一致",
                     "时区 %s 常见于 %s，而出口地理写 %s" % (tz, "/".join(ok), geo),
                     "让时区跟随出口 IP 所在地区")]
    return []


def check_android_identity(entry, props=None, soc_map=None):
    """App 侧身份自洽（**离线**，只看厂商池条目与派生 props）。

    PC 侧核的是"UA/UA-CH/TLS 之间"，App 侧要核的是"机型/指纹/SoC/构建之间"。
    一台宣称天玑 9400、`ro.hardware` 却写着 mt6897 的机器，比 UA 写得花哨危险
    得多——这类矛盾一次就够判定。

    查五条（都能离线复现）：
      1. `fingerprint` 五段与 brand/product/device/release 一致；
      2. `fingerprint` 里没有模拟器内部代号（`missi_`/`mumu_`/`sdk`/`vbox`…）；
      3. `soc` 在映射表里（不在 → `ro.soc.model` 会缺，而真机必报）；
      4. `soc` 厂商与 `hardware` 族一致（mt*↔MediaTek、qcom/sm*↔Qualcomm…）；
      5. 构建标记必须是 release（`user`/`release-keys`），不是 `test-keys`。
    """
    e = entry if isinstance(entry, dict) else {}
    p = props if isinstance(props, dict) else {}
    out = []
    fp = str(e.get("fingerprint") or p.get("ro.build.fingerprint") or "")
    brand = str(e.get("brand") or p.get("ro.product.brand") or "")
    device = str(e.get("device") or p.get("ro.product.device") or "")
    release = str(e.get("release") or "")
    if not fp:
        out.append(_bad("android_fp_shape", "high", "App 身份缺少指纹",
                        "没有 ro.build.fingerprint", "补齐机型指纹"))
        return out
    seg = fp.split("/")
    if len(seg) < 3 or ":" not in fp:
        out.append(_bad("android_fp_shape", "high", "指纹不是五段式",
                        fp[:60], "写成 brand/product/device:release/id/inc:type/tags"))
    else:
        if brand and seg[0].lower() != brand.lower():
            out.append(_bad("android_fp_shape", "mid", "指纹品牌段与 brand 不一致",
                            "指纹 %r vs brand %r" % (seg[0], brand),
                            "让指纹第一段 = ro.product.brand"))
        if device and seg[2].split(":")[0].lower() != device.lower():
            out.append(_bad("android_fp_shape", "mid", "指纹 device 段与 device 不一致",
                            "指纹 %r vs device %r" % (seg[2].split(":")[0], device),
                            "让指纹第三段 = ro.product.device"))
        if release and ":" in seg[2]:
            got = seg[2].split(":", 1)[1]
            if got and got != release:
                out.append(_bad("android_fp_shape", "mid", "指纹 release 段与 release 不一致",
                                "指纹 %r vs release %r" % (got, release),
                                "两处用同一个版本号"))
    low = fp.lower()
    for mark in ("missi_", "mumu_", "google_sdk", "sdk_gphone", "vbox",
                 "genymotion", "emulator", "andy"):
        if mark in low:
            out.append(_bad("android_emulator", "high", "指纹里有模拟器代号",
                            "命中 %r" % mark, "换真实机型指纹"))
            break
    soc = str(e.get("soc") or "")
    if soc:
        if soc_map is not None:
            _M = soc_map
        else:
            try:
                from core.android.fingerprint import SOC_MODEL_BY_SOC as _M
            except Exception:
                # 拿不到映射表 → **不做判定**：核账不许因为自己读不到东西就报
                # 「未知 SoC」的假警报（那会让用户去改一个没问题的机型）。
                _M = {}
        if _M and soc not in _M:
            out.append(_bad("android_soc", "mid", "SoC 不在映射表里",
                            "%r（未知 → ro.soc.model 会缺，真机必报）" % soc,
                            "在 SOC_MODEL_BY_SOC 登记该 SoC 的编号"))
        hw = str(e.get("hardware") or "").lower()
        if hw:
            if soc.lower().startswith("mediatek") and not hw.startswith("mt"):
                out.append(_bad("android_soc", "high", "SoC 厂商与 hardware 不一致",
                                "soc=%r，hardware=%r" % (soc, hw),
                                "MediaTek 机型 hardware 应是 mtXXXX"))
            if soc.lower().startswith("qualcomm") and not (
                    hw.startswith("qcom") or hw.startswith("sm")
                    or hw.startswith("kona") or hw.startswith("taro")):
                out.append(_bad("android_soc", "high", "SoC 厂商与 hardware 不一致",
                                "soc=%r，hardware=%r" % (soc, hw),
                                "Qualcomm 机型 hardware 应是 qcom / smXXXX"))
    tags = str(p.get("ro.build.tags") or "")
    btype = str(p.get("ro.build.type") or "")
    if "test-keys" in tags:
        out.append(_bad("android_build", "high", "构建标记是 test-keys",
                        tags, "用 release-keys"))
    if btype and btype != "user":
        out.append(_bad("android_build", "mid", "构建类型不是 user",
                        btype, "ro.build.type 写 user"))
    return out


def audit_pool(pool=None, limit=0):
    """对 App 厂商池逐个跑 `check_android_identity`，返回 `(n, hits)`。

    `limit>0` 时只查前 N 个（面板/接口用，避免每次打开面板都全量算）。
    """
    try:
        from core.android.fingerprint import PHONE_POOL as _P
        from core.android.fingerprint import build_from_vendor as _b
    except Exception:
        return 0, []
    p = list(pool if pool is not None else _P)
    if limit and limit > 0:
        p = p[:limit]
    hits = []
    for i, e in enumerate(p):
        try:
            props = _b(e, seed=i).props()
        except Exception:
            props = {}
        hits += check_android_identity(e, props)
    return len(p), hits


def audit(fp, headers=None, viewport=None, tls_impersonate="", config=None):
    """跑全部检查，返回命中列表（空 = 已知矛盾全清）。"""
    cfg = config or {}
    if not tls_impersonate:
        tls_impersonate = str(cfg.get("tls_impersonate") or "chrome")
    fp = dict(fp or {})
    if config:
        for k_src, k_dst in (("locale", "locale"), ("timezone", "timezone")):
            if cfg.get(k_src) and not fp.get(k_dst):
                fp[k_dst] = cfg[k_src]
    hits = []
    hits += check_ua_vs_runtime(fp)
    hits += check_ua_ch_vs_ua(fp, headers)
    hits += check_mobile_vs_viewport(fp, viewport)
    hits += check_locale_vs_accept_language(fp, headers)
    hits += check_tls_vs_ua(fp, tls_impersonate)
    hits += check_timezone_vs_geo(fp)
    return hits


def summary(hits) -> str:
    """人话汇总（给 CLI 与日志用）。"""
    hits = list(hits or ())
    if not hits:
        return "指纹核账：已知矛盾全清"
    lines = ["指纹核账：%d 处矛盾" % len(hits)]
    for h in hits:
        lines.append("  [%s] %s：%s（%s）→ %s"
                     % (h["level"], h["title"], h["detail"],
                        h["id"], h["fix"]))
    return "\n".join(lines)


def _main(argv=None):                        # pragma: no cover - CLI 入口
    """`python -m core.fp_audit`：对当前仓库的默认指纹跑一次核账。"""
    import sys

    # 延迟导入：本模块要能脱离爬虫包单测
    from crawlers.base import (DESKTOP_UA, MOBILE_UA, profile_headers)

    cases = [
        ("桌面档", {"ua": DESKTOP_UA, "locale": "zh-CN", "is_mobile": False},
         {"width": 1366, "height": 900}),
        ("移动档", {"ua": MOBILE_UA, "locale": "zh-CN", "is_mobile": True},
         {"width": 390, "height": 844, "has_touch": True}),
    ]
    bad = 0
    for name, fp, vp in cases:
        hdrs = profile_headers(dict(fp, timezone="Asia/Shanghai"))
        hits = audit(fp, hdrs, vp)
        print("== %s ==" % name)
        print(summary(hits))
        bad += len(hits)
    return 0 if not bad else 1


if __name__ == "__main__":                   # pragma: no cover
    raise SystemExit(_main())
