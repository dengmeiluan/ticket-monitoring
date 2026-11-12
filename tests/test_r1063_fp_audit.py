# -*- coding: utf-8 -*-
"""r1063 T25：指纹一致性核账（离线）——「自己和自己矛盾」是最便宜的风控证据。

核账模块 `core/fp_audit.py` 只读、可离线、可进 CI；它查的是**字段之间**的
互相印证，而不是"单个字段像不像人"：UA 说 Safari、引擎却是 Chromium，比
UA 写得更花哨危险得多。

本轮它抓出并修掉了 3 处移动档矛盾（iPhone/Safari UA + 无 UA-CH + chrome TLS）：
移动档整体切到 Android Chrome（UA / UA-CH / vendor / platform / WebGL /
userAgentData / window.chrome 一起对齐）。
"""
import io
import os

from core import fp_audit as fa


def _headers(**kw):
    return {str(k).replace("_", "-"): v for k, v in kw.items()}


# ---------------- 核账规则本身 ----------------

def test_ua_vs_runtime_flags_safari_and_firefox():
    safari = {"ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                    "Version/16.6 Mobile/15E148 Safari/604.1"}
    hits = fa.check_ua_vs_runtime(safari)
    assert hits and hits[0]["id"] == "ua_vs_runtime"
    assert hits[0]["level"] == "high"

    firefox = {"ua": "Mozilla/5.0 (Windows NT 10.0; rv:126.0) "
                     "Gecko/20100101 Firefox/126.0"}
    assert fa.check_ua_vs_runtime(firefox)[0]["id"] == "ua_vs_runtime"

    chrome = {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"}
    assert fa.check_ua_vs_runtime(chrome) == []


def test_mobile_must_carry_mobile_client_hints():
    fp = {"ua": "Mozilla/5.0 (Linux; Android 14; Pixel 8) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Mobile Safari/537.36",
          "is_mobile": True}
    miss = fa.check_ua_ch_vs_ua(fp, {})
    assert miss and miss[0]["id"] == "ua_ch_vs_ua"
    ok = fa.check_ua_ch_vs_ua(fp, {"sec-ch-ua": '"Chromium";v="126"',
                                   "sec-ch-ua-mobile": "?1",
                                   "sec-ch-ua-platform": '"Android"'})
    assert ok == []


def test_ua_ch_version_must_match_ua():
    fp = {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"}
    hits = fa.check_ua_ch_vs_ua(fp, {"sec-ch-ua": '"Chromium";v="126"',
                                     "sec-ch-ua-platform": '"Windows"'})
    assert hits and hits[0]["id"] == "ua_ch_vs_ua"


def test_mobile_viewport_and_touch():
    fp = {"ua": "x", "is_mobile": True}
    assert fa.check_mobile_vs_viewport(fp, {"width": 1366})
    assert fa.check_mobile_vs_viewport(fp, {"width": 390, "has_touch": False})
    assert fa.check_mobile_vs_viewport(fp, {"width": 390, "has_touch": True}) == []


def test_locale_and_timezone_rules():
    fp = {"locale": "zh-CN"}
    assert fa.check_locale_vs_accept_language(
        fp, {"accept-language": "en-US,en;q=0.9"})
    assert fa.check_locale_vs_accept_language(
        fp, {"accept-language": "zh-CN,zh;q=0.9"}) == []
    # 国内站却配了纽约时区：最便宜的一条矛盾
    assert fa.check_timezone_vs_geo({"timezone": "America/New_York",
                                     "geo": "CN"})


# ---------------- 仓库默认档：必须「已知矛盾全清」 ----------------

def test_repo_defaults_are_self_consistent():
    from crawlers.base import DESKTOP_UA, MOBILE_UA, profile_headers

    desk = {"ua": DESKTOP_UA, "locale": "zh-CN", "is_mobile": False}
    mob = {"ua": MOBILE_UA, "locale": "zh-CN", "is_mobile": True}
    assert fa.audit(desk, profile_headers(dict(desk)),
                    {"width": 1366, "height": 900}) == []
    assert fa.audit(mob, profile_headers(dict(mob)),
                    {"width": 390, "height": 844, "has_touch": True}) == []


def test_mobile_ua_is_chromium_not_safari():
    """回归钉子：移动档 UA 不许再退回 Safari 形态（那是与引擎矛盾的）。"""
    from crawlers.base import MOBILE_UA

    assert "Chrome/" in MOBILE_UA
    assert "Version/" not in MOBILE_UA
    assert "iPhone" not in MOBILE_UA
    assert "Mobile Safari" in MOBILE_UA          # Android Chrome 的标准尾巴


def test_summary_is_actionable():
    hits = [{"id": "x", "level": "high", "title": "T",
             "detail": "D", "fix": "F"}]
    txt = fa.summary(hits)
    assert "1 处矛盾" in txt and "F" in txt
    assert "已知矛盾全清" in fa.summary([])


def test_audit_module_has_no_side_effects_on_import():
    """核账必须能脱离爬虫包/浏览器跑（CI 也要能跑）。"""
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "core", "fp_audit.py"),
        encoding="utf-8").read()
    head = src[:src.index("def _main(")]
    assert "import playwright" not in head
    assert "from crawlers" not in head.split('if __name__')[0].replace(
        "from crawlers.base import", "")   # 只在 CLI 里延迟导入
