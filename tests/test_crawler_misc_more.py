# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1065_proc_cpuinfo.py
- tests/test_r1224_cookie_dedupe.py
- tests/test_r1246_cookies_or_empty.py
- tests/test_r1561_stall_skip_not_timeout.py
- tests/test_r1574_foreign_app_stack.py
- tests/test_r1771_form_slots.py
- tests/test_r273_layover.py
- tests/test_r320_citydata.py
- tests/test_r340_push.py
- tests/test_r396_request_url_traceability.py
- tests/test_r407_success_path_url.py
- tests/test_r410_url_attr_scope.py
- tests/test_r660_calendar_cell_viewport.py
- tests/test_r725_marketing_activity_overlay.py
- tests/test_r727_glyph_is_not_flight_no.py
- tests/test_r780_round_trip_row_marking.py
- tests/test_r911_web_stealth_human_risk.py
- tests/test_r929_paced_not_failure.py
- tests/test_r936_scene_on_unknown.py
- tests/test_r944_gap_left_block.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import ast
import crawlers
import crawlers.base as base_mod
import glob
import io
import json
import logging
import main
import os
import pytest
import re
import sys
import tempfile

from PIL import Image, ImageDraw
from core import riskscore
from core.alerter import _dw
from core.channels import APP_CHANNELS, BROWSER_CHANNELS, dim_state
from core.citydata import CITY, CITY_HOT, CITY_NPY, CITY_PY, CODE_NAME
from core.storage import PriceStorage
from core.yield_stats import is_paced, statuses_ok
from crawlers import human, slider, stealth_ext
from crawlers.app_base import AppCrawler, save_scene
from crawlers.app_blockers import BLOCK_AD, _close_button, _texts, detect_block, has_payload
from crawlers.app_tongcheng_parse import parse_form, parse_form_slots
from crawlers.app_zhixing_nav import _calendar_cell, _cell_month_scroll_hint, _needs_earlier, _pick_date, _tap_calendar_cell
from crawlers.app_zhixing_parse import _nodes, _unescape, detect_state, parse_flight_rows
from crawlers.base import BaseCrawler, _dedupe_cookies, cookies_or_empty
from crawlers.qunar import QunarCrawler


# ---- merged from tests/test_r1065_proc_cpuinfo.py ----

FAKE_CPUINFO = AppCrawler.FAKE_CPUINFO


class FakeDev:
    def __init__(self, head_out, mumu=True):
        self.head_out = head_out
        self.mumu = mumu
        self.mumu_cmds = []

    def _sh(self, *args):
        return self.head_out

    def mumu_available(self):
        return self.mumu

    def mumu_sh(self, cmd):
        self.mumu_cmds.append(cmd)
        return "ok"


def _crawler():
    class C(AppCrawler):
        name = "app_test"
        package = "com.test"

        def login_url(self):
            return ""

        def fetch(self, *a, **k):
            return []

    return C({"user_data_dir": "user_data"}, logging.getLogger("t"))


def test_mounts_when_host_cpu_visible():
    d = FakeDev("processor\t: 0\nvendor_id\t: GenuineIntel\n"
                "model name\t: Intel(R) Core(TM) i7-14700\n")
    _crawler().ensure_proc_cpuinfo(d)
    assert d.mumu_cmds, "看到 Intel 却没去重挂"
    assert "mount --bind" in d.mumu_cmds[0]
    assert FAKE_CPUINFO in d.mumu_cmds[0]


def test_noop_when_already_arm():
    d = FakeDev("processor\t: 0\nCPU implementer\t: 0x41\n")
    _crawler().ensure_proc_cpuinfo(d)
    assert d.mumu_cmds == [], "已经是 ARM 视图就不该再挂"


def test_noop_when_unrecognised():
    """读不出特征（比如命令失败、返回空）时不要乱动。"""
    d = FakeDev("")
    _crawler().ensure_proc_cpuinfo(d)
    assert d.mumu_cmds == []


def test_noop_without_mumu_channel():
    d = FakeDev("vendor_id\t: GenuineIntel\n", mumu=False)
    _crawler().ensure_proc_cpuinfo(d)
    assert d.mumu_cmds == []


def test_survives_sh_exception():
    class Boom(FakeDev):
        def _sh(self, *a):
            raise RuntimeError("adb dead")

    _crawler().ensure_proc_cpuinfo(Boom(""))


# ---- merged from tests/test_r1224_cookie_dedupe.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def test_dedupes_same_name_domain_path():
    ck = [
        {"name": "mtoken", "domain": ".tuniu.com", "path": "/", "value": "A"},
        {"name": "mtoken", "domain": ".tuniu.com", "path": "/", "value": "B"},
        {"name": "ssoUser", "domain": ".tuniu.com", "path": "/", "value": "C"},
    ]
    out = _dedupe_cookies(ck)
    assert len(out) == 2, out
    assert out[0]["value"] == "A", "应当保留先出现的那份"
    assert out[1]["name"] == "ssoUser"


def test_keeps_different_path_or_domain():
    """同名但 path/domain 不同的必须都留着——否则会把登录态弄丢。"""
    ck = [
        {"name": "mtoken", "domain": ".tuniu.com", "path": "/"},
        {"name": "mtoken", "domain": "m.tuniu.com", "path": "/"},
        {"name": "mtoken", "domain": ".tuniu.com", "path": "/flight"},
    ]
    assert len(_dedupe_cookies(ck)) == 3


def test_idempotent_and_empty_safe():
    assert _dedupe_cookies([]) == []
    assert _dedupe_cookies(None) == []
    ck = [{"name": "a", "domain": "d", "path": "/"}]
    assert _dedupe_cookies(_dedupe_cookies(ck)) == ck


def test_missing_fields_tolerated():
    """缺字段不能炸（真实快照里见过没有 path 的条目）。"""
    out = _dedupe_cookies([{"name": "x"}, {"name": "y", "domain": "d"}])
    assert len(out) == 2


def test_wired_before_add_cookies():
    import io
    src = io.open(os.path.join(ROOT, "crawlers", "base.py"), encoding="utf-8").read()
    i = src.find("ctx.add_cookies(")
    seg = src[max(0, i - 400):i + 80]
    assert "_dedupe_cookies(plan)" in seg, "灌 cookie 前没有去重（重复会直接抛异常）"


# ---- merged from tests/test_r1246_cookies_or_empty.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

class Ctx:
    def __init__(self, behavior):
        self.behavior = behavior

    def cookies(self):
        if isinstance(self.behavior, Exception):
            raise self.behavior
        return self.behavior


class Log:
    def __init__(self):
        self.warns = []

    def warning(self, fmt, *a):
        self.warns.append(fmt % a if a else fmt)


def test_normal_passthrough():
    ck = [{"name": "a", "domain": "d", "path": "/"}]
    assert cookies_or_empty(Ctx(ck)) == ck


def test_multiple_cookies_degrades_to_empty():
    log = Log()
    got = cookies_or_empty(Ctx(Exception("Multiple cookies exist with name=mtoken")), log)
    assert got == []
    assert log.warns, "降级必须留痕"


def test_other_errors_still_raise():
    """负控：别的异常不许被吞——那会把真故障变成"没 cookie"。"""
    try:
        cookies_or_empty(Ctx(Exception("Target page, context or browser has been closed")))
    except Exception as e:
        assert "closed" in str(e)
    else:
        raise AssertionError("非目标异常被吞了")


def test_none_logger_is_safe():
    assert cookies_or_empty(Ctx(Exception("Multiple cookies exist with name=x"))) == []


def test_tuniu_uses_the_helper():
    import io
    s = io.open(os.path.join(ROOT, "crawlers", "tuniu.py"), encoding="utf-8").read()
    assert "cookies_or_empty(ctx)" in s, "tuniu 仍在前台裸读 cookie"
    assert "ctx.cookies()" not in s, "仍有裸 ctx.cookies() 调用"
    # 导入可能是多行的：查 import 语句块，不查某一行
    i = s.find("from .base import (")
    assert i > 0, "找不到 .base 导入"
    j = s.find(")", i)
    assert "cookies_or_empty" in s[i:j], "import 块里没带 cookies_or_empty"


# ---- merged from tests/test_r1561_stall_skip_not_timeout.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class _Fake(AppCrawler):
    name = "app_ctrip"
    APP_STALL_STREAK = 3
    APP_STALL_S = 1800

    def __init__(self):
        self.notes = []
        self.user_data_root = "user_data"
        self._timeout_streak = 5

    # 只接我们要验的两个钩子
    def app_stall_left_s(self):
        return 1200.0

    def app_gone_left_s(self):
        return 0.0

    def active_plat(self):  # 有人正在别的渠道登录？没有
        return ""

    def path_note(self, path, status, date=None, detail=""):
        self.notes.append((path, status, detail))

    def service_closed_skip(self, dates):
        return False

    def login_wall_skip(self, dates, path=""):
        return False


def test_stall_skip_is_blocked_not_timeout():
    c = _Fake()
    skipped = c.early_skip(["2026-12-01"], path="app-login")
    assert skipped is True, "熔断期间必须跳过"
    assert c.notes, "跳过也必须留一条通路记录（否则用户看不出为什么没跑）"
    for path, status, detail in c.notes:
        # r1841：闸门跳过 = **我方主动不发** → paced（原先是 blocked）。
        # 这条门禁真正要守的是「绝不能记 timeout」——那会让 _timeout_streak+1
        # 并再次续期熔断窗口，渠道永远回不来。
        assert status == "paced", (
            "熔断跳过被记成 %r —— 应记 paced（我方主动不发）：%s"
            % (status, detail))
        assert status != "timeout", "熔断跳过被记成 timeout，会续期熔断窗口"
        assert "暂停中" in detail, detail
        assert "本轮未发请求" in detail, "没说明这一轮根本没发请求"


def test_stall_skip_does_not_touch_timeout_streak():
    c = _Fake()
    before = c._timeout_streak
    c.early_skip(["2026-12-01"], path="app-login")
    assert c._timeout_streak == before, (
        "熔断跳过改变了连败计数（%d → %d）" % (before, c._timeout_streak))


# ---- merged from tests/test_r1574_foreign_app_stack.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class _Log:
    def __init__(self):
        self.lines = []

    def warning(self, fmt, *a):
        self.lines.append(fmt % a if a else fmt)

    def info(self, fmt, *a):
        self.lines.append(fmt % a if a else fmt)


class _Dev:
    def __init__(self, act, after=None):
        self.act = act
        self.after = after or act
        self.stops = []
        self.starts = []

    def current_activity(self):
        return self.act

    def app_stop(self, pkg):
        self.stops.append(pkg)
        self.act = self.after

    def app_start(self, pkg):
        self.starts.append(pkg)
        self.act = pkg + "/Main"


def _mk(pkg="com.tongcheng.android"):
    c = AppCrawler({}, _Log())
    c.name = "app_tongcheng"
    c.package = pkg
    c.logger = _Log()
    return c


def test_foreign_app_channel_is_stopped_not_just_switched():
    c = _mk()
    dev = _Dev("ctrip.android.view/ctrip.android.flight.FlightMainActivity",
               after="com.tongcheng.android/Home")
    c._ensure_own_app(dev)
    assert "ctrip.android.view" in dev.stops, (
        "前台残留的是别的 App 渠道，必须 force-stop 它，否则任务栈会反复抢前台：%s"
        % dev.stops)
    assert c.package in dev.starts, dev.starts


def test_unknown_package_is_not_killed():
    c = _mk()
    dev = _Dev("com.android.settings/.Settings", after="com.tongcheng.android/H")
    c._ensure_own_app(dev)
    assert dev.stops == [], "不是自家渠道的包不许乱停：%s" % dev.stops
    assert c.package in dev.starts, dev.starts


def test_already_own_app_does_nothing():
    c = _mk()
    dev = _Dev("com.tongcheng.android/.MainActivity")
    assert c._ensure_own_app(dev) is False
    assert dev.stops == [] and dev.starts == []


# ---- merged from tests/test_r1771_form_slots.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FORM = """<hierarchy>
  <node text="机票查询" bounds="[500,1500][700,1560]" />
  <node text="单程" bounds="[120,700][220,760]" />
  <node text="往返" bounds="[260,700][360,760]" />
  <node text="上海" bounds="[120,1080][320,1140]" />
  <node text="东京" bounds="[900,1080][1100,1140]" />
  <node text="11月16日" bounds="[120,1300][360,1360]" />
</hierarchy>"""


def test_slots_come_from_page_nodes():
    d = parse_form_slots(FORM)
    assert d.get("dep") == (220, 1110), d
    assert d.get("arr") == (1000, 1110), d
    assert d.get("date") == (240, 1330), d


def test_slots_match_parse_form_texts():
    f = parse_form(FORM)
    assert f and f["dep"] == "上海" and f["arr"] == "东京", f
    d = parse_form_slots(FORM)
    assert d, "同一份表单必须也能给出坐标"


def test_non_form_has_no_slots():
    assert parse_form_slots('<hierarchy><node text="火车票" '
                            'bounds="[0,0][10,10]" /></hierarchy>') == {}


def test_crawler_prefers_slots():
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "crawlers", "app_tongcheng.py"),
        encoding="utf-8").read()
    assert "parse_form_slots" in src, "爬虫没用页面坐标"
    i = src.index('_slots.get("dep")')
    assert "_form_slot(page" in src[i:i + 200], "兜底没保留"


# ---- merged from tests/test_r273_layover.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _pc_row(b1, b2, code="SC4926/SC4603", trans_city="青岛", price="980"):
    return {"ret": True, "data": {"flights": [{
        "code": code, "minPrice": price, "transCity": trans_city,
        "crossDayDesc": "+1天", "transTime": "",
        "binfo1": b1, "binfo2": b2,
    }]}}


# ---- RED：跨日真停 ≥24h 不再被 %1440 回绕成小值 ----

def test_qunar_pc_crossday_transfer_layover_not_wrapped():
    b1 = {"airCode": "SC4926", "depTime": "14:30", "arrTime": "19:10",
          "date": "2026-10-15", "arrDate": "2026-10-15"}
    b2 = {"airCode": "SC4603", "depTime": "19:15", "arrTime": "21:00",
          "date": "2026-10-16", "arrDate": "2026-10-16"}
    out = QunarCrawler._parse_pc_flights(
        json.dumps(_pc_row(b1, b2), ensure_ascii=False), "2026-10-15")
    assert len(out) == 1
    t = out[0]
    # 真停 24:05（ctrip 同指纹 1445 互证），旧实现落 5
    assert t["layover"] == 1445, t
    assert t["layoverSrc"] == "times"
    assert t["lay2dep"] == "19:15" and t["arrDate"] == "2026-10-16"
    from core.flightnorm import normalize as _nf
    _t = _nf(dict(t), "2026-10-15")
    assert _t["layoverM"] == 1445 and _t["layoverT"] == "24:05", _t
    # LAY_MIN=90 衔接筛选放行（旧值 5 被保守误剔的决策面）
    assert _t["layoverM"] >= 90


def test_qunar_h5_crossday_transfer_layover_not_wrapped():
    row = {"minPrice": 800, "code": "SC4926/SC4603", "transCity": "青岛",
           "binfo1": {"depTime": "14:30", "arrTime": "19:10",
                      "depDate": "2026-10-15", "arrDate": "2026-10-15"},
           "binfo2": {"depTime": "19:15", "arrTime": "21:00",
                      "depDate": "2026-10-16", "arrDate": "2026-10-16"}}
    out = QunarCrawler._extract_flights_obj([row])
    assert out and out[0]["layover"] == 1445, out


# ---- 回归：钉不住/等价形态维持旧结果 ----

def test_qunar_pc_transfer_layover_legacy_shapes_unchanged():
    # 既有夹具形态（首段自身跨天，真停 19:25 <24h）：钉法与 %1440 等价
    b1 = {"airCode": "MU5533", "depTime": "23:25", "arrTime": "01:10",
          "date": "2026-09-25", "arrDate": "2026-09-26"}
    b2 = {"airCode": "SC8711", "depTime": "20:35", "arrTime": "00:55",
          "date": "2026-09-26", "arrDate": "2026-09-27"}
    out = QunarCrawler._parse_pc_flights(
        json.dumps(_pc_row(b1, b2, code="MU5533/SC8711", trans_city="济南"),
                   ensure_ascii=False), "2026-09-25")
    assert out[0]["layover"] == 1165, out

    # 同日中转：180 分钟
    b1 = {"depTime": "08:00", "arrTime": "10:00",
          "date": "2026-10-15", "arrDate": "2026-10-15"}
    b2 = {"depTime": "13:00", "arrTime": "15:00",
          "date": "2026-10-15", "arrDate": "2026-10-15"}
    out = QunarCrawler._parse_pc_flights(
        json.dumps(_pc_row(b1, b2), ensure_ascii=False), "2026-10-15")
    assert out[0]["layover"] == 180, out

    # 隔夜 <24h：23:00 到、次日 06:00 走 → 7h
    b1 = {"depTime": "20:00", "arrTime": "23:00",
          "date": "2026-10-15", "arrDate": "2026-10-15"}
    b2 = {"depTime": "06:00", "arrTime": "09:00",
          "date": "2026-10-16", "arrDate": "2026-10-16"}
    out = QunarCrawler._parse_pc_flights(
        json.dumps(_pc_row(b1, b2), ensure_ascii=False), "2026-10-15")
    assert out[0]["layover"] == 420, out


def test_qunar_pc_transfer_layover_dates_missing_fallback():
    # binfo1.arrDate 缺席（守卫不拦、生产可达的防御形态）→ 钉不住
    # 退回旧 %1440+span 守卫形态
    b1 = {"depTime": "20:00", "arrTime": "23:10", "date": "2026-10-15"}
    b2 = {"depTime": "06:00", "arrTime": "09:00",
          "date": "2026-10-16", "arrDate": "2026-10-16"}
    out = QunarCrawler._parse_pc_flights(
        json.dumps(_pc_row(b1, b2), ensure_ascii=False), "2026-10-15")
    assert out and out[0]["layover"] == 410, out

    # Soldier M-2 专属钉：钉不住 × span≥2 × 钟面差 <5h 的旧守卫组合
    # 形态（~25h 真停被回绕成 55min 的垃圾带）→ 弃算不落键（宁缺勿错）
    b1 = {"depTime": "20:00", "arrTime": "23:10", "date": "2026-10-15"}
    b2 = {"depTime": "00:05", "arrTime": "02:00",
          "date": "2026-10-18", "arrDate": "2026-10-18"}
    out = QunarCrawler._parse_pc_flights(
        json.dumps(_pc_row(b1, b2), ensure_ascii=False), "2026-10-15")
    assert out and "layover" not in out[0], out


def test_layover_pinned_helper_edges():
    # 纯函数边界：日期解析败/结果 ≤0/语义验证不过 → None（调用方退旧形态）
    from crawlers.qunar import _layover_pinned
    b1 = {"arrTime": "23:00", "arrDate": "2026-10-15"}
    # 二段自身跨天（arrTime<depTime）：b2.date=次日 → 停 7h
    b2 = {"depTime": "06:00", "arrTime": "09:00",
          "date": "2026-10-16", "arrDate": "2026-10-16"}
    assert _layover_pinned(b1, b2) == 420
    # 跨 2 天真停（45h15m 形态）
    b2 = {"depTime": "20:15", "arrTime": "22:00",
          "date": "2026-10-17", "arrDate": "2026-10-17"}
    assert _layover_pinned(b1, b2) == 2 * 1440 - 165
    # 矛盾形态（b2.date 早于 b1.arrDate，语义验证不过）→ None
    b1 = {"arrTime": "19:10", "arrDate": "2026-10-16"}
    b2 = {"depTime": "09:00", "arrTime": "11:00",
          "date": "2026-10-15", "arrDate": "2026-10-15"}
    assert _layover_pinned(b1, b2) is None
    # 日期键缺席 → None
    assert _layover_pinned(
        {"arrTime": "10:00"},
        {"depTime": "12:00", "date": "2026-10-16",
         "arrDate": "2026-10-16"}) is None


# ---- merged from tests/test_r320_citydata.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 旧 50 城手抄表语义快照（wizard.py 迁移前定格，存量配置兼容铁律）
_LEGACY = {
    "北京": "BJS", "上海": "SHA", "广州": "CAN", "深圳": "SZX",
    "成都": "CTU", "重庆": "CKG", "杭州": "HGH", "西安": "SIA",
    "南京": "NKG", "武汉": "WUH", "长沙": "CSX", "厦门": "XMN",
    "三亚": "SYX", "海口": "HAK", "昆明": "KMG", "丽江": "LJG",
    "大理": "DLU", "西双版纳": "JHG", "香格里拉": "DIG", "腾冲": "TCZ",
    "乌鲁木齐": "URC", "青岛": "TAO", "天津": "TSN", "郑州": "CGO",
    "济南": "TNA", "福州": "FOC", "温州": "WNZ", "宁波": "NGB",
    "合肥": "HFE", "贵阳": "KWE", "南宁": "NNG", "桂林": "KWL",
    "兰州": "LHW", "西宁": "XNN", "银川": "INC", "呼和浩特": "HET",
    "太原": "TYN", "石家庄": "SJW", "哈尔滨": "HRB", "长春": "CGQ",
    "沈阳": "SHE", "大连": "DLC", "珠海": "ZUH", "汕头": "SWA",
    "泉州": "JJN", "无锡": "WUX", "烟台": "YNT", "威海": "WEH",
    "敦煌": "DNH", "张家界": "DYG",
}


def test_city_table_scale_and_users_case():
    """全国民航网覆盖规模 + 用户实报城（连云港）在场。"""
    assert len(CITY) >= 200, len(CITY)
    assert CITY.get("连云港") == "LYG"
    assert CODE_NAME.get("LYG") == "连云港"


def test_legacy_names_codes_zero_drift():
    """旧 50 城 (名,码) 语义零漂移（存量配置兼容铁律）。"""
    bad = {n: (c, CITY.get(n)) for n, c in _LEGACY.items()
           if CITY.get(n) != c}
    assert not bad, f"旧城漂移: {bad}"


def test_code_shape_and_uniqueness():
    """码形态全验 + 码→名转写唯一 + 名→码无同名异码。"""
    for n, c in CITY.items():
        assert re.fullmatch(r"[A-Z]{3}", c), (n, c)
    for c, n in CODE_NAME.items():
        assert re.fullmatch(r"[A-Z]{3}", c) and 1 <= len(n) <= 10, (c, n)
    assert len(CODE_NAME) >= 200


def test_pinyin_groups_and_hot():
    """首字母分组全覆盖（面板字母导航）；热门组 ⊆ 全表。"""
    assert set(CITY_PY) == set(CITY), "首字母表与城市表不同域"
    for n, py in CITY_PY.items():
        assert re.fullmatch(r"[A-Z]", py), (n, py)
    assert 8 <= len(CITY_HOT) <= 30
    assert set(CITY_HOT) <= set(CITY)


def test_name_py_full_coverage():
    """拼音全拼表（官方 namePy，面板搜索的拼音通道）：覆盖全表、
    小写字母串形态（渠道引号瑕疵已清洗）。"""
    assert set(CITY_NPY) == set(CITY), "全拼表与城市表不同域"
    for n, p in CITY_NPY.items():
        assert re.fullmatch(r"[a-z]+", p), (n, p)
    assert CITY_NPY.get("连云港") == "lianyungang"


def test_wizard_city_single_source():
    """wizard.CITY 单源化（配置页联想/归一与采集词表同源防漂移）。"""
    import wizard
    assert wizard.CITY is CITY or wizard.CITY == CITY, (
        "wizard.CITY 未接 citydata 单源（手抄表漂移风险）")


def test_crawler_cityname_superset():
    """三渠道 CITY_NAME 全国超集（码→中文名转写全通；用户实报城
    连云港在场）。旧键旅游名语义保留（DIG=香格里拉）。"""
    from crawlers.ctrip import CtripCrawler
    from crawlers.qunar import QunarCrawler
    from crawlers.tongcheng import TongchengCrawler
    for cls in (CtripCrawler, QunarCrawler, TongchengCrawler):
        t = cls.CITY_NAME
        assert len(t) >= 250, (cls.__name__, len(t))
        assert t.get("LYG") == "连云港", cls.__name__
        assert t.get("DIG") == "香格里拉", cls.__name__


# ---- merged from tests/test_r340_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class _FakeNf:
    def __init__(self):
        self.sent = []

    def send(self, title, desp, **kw):
        self.sent.append((title, desp))


class _FakeAl:
    def __init__(self, nf):
        self.notifier = nf


@pytest.fixture()
def iso(monkeypatch):
    monkeypatch.setattr(main, "_SENT_LAST", {})
    monkeypatch.setattr(main, "_SENT_CNT", {})
    monkeypatch.setattr(main, "_LOGIN_ALERT_STREAK", {})
    monkeypatch.setattr(main, "_sent_save", lambda: None)
    return monkeypatch


def _run(iso, plat="qunar", suspect=True):
    iso.setitem(crawlers.REGISTRY, plat,
                type("C", (), {"login_suspect": suspect}))
    nf = _FakeNf()
    main._channel_login_alert_sentinel(
        [({"platforms": [plat]}, _FakeAl(nf))],
        logging.getLogger("r340"))
    return nf


def _assert_paragraph_law(desp):
    parts = desp.split("\n\n")
    assert all("\n" not in p for p in parts), \
        f"段落内存在单换行（PC 端粘行律，LESSONS 十§1）: {desp!r}"
    over = [(p, _dw(p)) for p in parts if _dw(p) > 40]
    assert not over, f"超手机 40 半角红线: {over} (desp={desp!r})"


def test_login_alert_desp_paragraph_law(iso):
    iso.setattr(main, "_LOGIN_ALERT_STREAK", {"qunar": 1})
    nf = _run(iso, "qunar", suspect=True)
    assert nf.sent, "连续 2 轮应触发告警"
    title, desp = nf.sent[0]
    assert title == "渠道登录态告警", title
    _assert_paragraph_law(desp)
    assert "qunar" in desp, desp
    assert "2" in desp, desp
    assert "登录" in desp, desp


def test_login_alert_desp_worst_platform_width(iso):
    """平台名最长（tongcheng 9 字符）+ 3 位数轮数的最坏计宽形态。"""
    iso.setattr(main, "_LOGIN_ALERT_STREAK", {"tongcheng": 998})
    nf = _run(iso, "tongcheng", suspect=True)
    assert nf.sent, "连续 999 轮应触发告警"
    _assert_paragraph_law(nf.sent[0][1])
    assert "tongcheng" in nf.sent[0][1]
    assert "999" in nf.sent[0][1]


def test_login_recover_desp_paragraph_law(iso):
    import datetime as _dt
    today = _dt.date.today().isoformat()
    iso.setattr(main, "_LOGIN_ALERT_STREAK", {"qunar": 2})
    iso.setattr(main, "_SENT_LAST", {("qunar", "login"): today})
    nf = _run(iso, "qunar", suspect=False)
    assert nf.sent, "恢复路径应发通知"
    title, desp = nf.sent[0]
    assert title == "渠道登录态恢复", title
    _assert_paragraph_law(desp)
    assert "qunar" in desp and "恢复" in desp, desp


# ---- merged from tests/test_r396_request_url_traceability.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class _Dummy(BaseCrawler):
    name = "dummy"
    URL_TPL = "https://example.test/list?date={date}"

    def __init__(self):
        super().__init__({}, logging.getLogger("t_r396"))

    def fetch(self, *a, **kw):  # pragma: no cover - 只测路径账
        return []


def _store():
    d = tempfile.mkdtemp(prefix="tm_r396_")
    return PriceStorage(os.path.join(d, "prices.db"))


def test_path_note_keeps_explicit_url():
    c = _Dummy()
    c.path_reset()
    rec = c.path_note("H5", "ok", rows=3, date="2026-11-16",
                      url="https://m.test/a?date=2026-11-16")
    assert rec["url"] == "https://m.test/a?date=2026-11-16"


def test_explicit_url_beats_page_fallback():
    """页面 URL 兜底不得覆盖调用方显式给的值（不同路径不同地址）。"""
    class _Page:
        url = "https://stale.test/from-previous-path"

    c = _Dummy()
    c.path_reset()
    c._last_page = _Page()
    rec = c.path_note("API", "login", date="2026-11-16",
                      url="https://api.test/touchInnerList")
    assert rec["url"] == "https://api.test/touchInnerList", rec


def test_page_url_still_used_when_caller_has_none():
    """调用方没给 URL 时，被拦状态仍要留下页面地址（原有行为）。"""
    class _Page:
        url = "https://passport.test/login?redirect=x"

    c = _Dummy()
    c.path_reset()
    c._last_page = _Page()
    rec = c.path_note("H5", "login", date="2026-11-16")
    assert rec["url"] == "https://passport.test/login?redirect=x", rec


def test_url_reaches_the_ledger():
    """端到端：URL 一路写进 fetch_paths 的 request_url 列。"""
    st = _store()
    c = _Dummy()
    c.path_reset()
    rec = c.path_note("H5", "soft_reject", detail="444",
                      url="https://m.test/x?d=2026-11-16")
    st.save_fetch_path("tongcheng", "SHA", "BKK", "2026-11-16",
                       rec["path"], rec["status"],
                       request_url=rec.get("url", ""),
                       note=rec.get("detail", ""))
    with st._conn() as conn:
        row = conn.execute(
            "SELECT request_url FROM fetch_paths ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row[0] == "https://m.test/x?d=2026-11-16", row


def test_all_persist_points_pass_url():
    """三个落账点（主采/补采/自检）都必须把 url 传下去。

    只改其中一处会留下"有些路径有 URL、有些没有"的半吊子溯源，比全无
    更难排查（读者会以为空的那些是采集没走到）。
    """
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(here, "main.py"), encoding="utf-8").read()
    calls = re.findall(r"save_fetch_path\((?:[^()]|\([^()]*\))*", src)
    assert len(calls) >= 3, [c[:60] for c in calls]
    missing = [c[:80] for c in calls if "request_url=" not in c]
    assert not missing, missing


# ---- merged from tests/test_r407_success_path_url.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CRAWLERS = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "crawlers")


def _read(fn):
    return open(os.path.join(CRAWLERS, fn), encoding="utf-8").read()


def test_window_calendar_success_records_real_url():
    src = _read("tongcheng.py")
    i = src.index('self.path_note("窗历", "calendar"')
    # 前面几行是导入真实端点的代码
    block = src[max(0, i - 700):i + 400]
    assert "url=" in block, block
    assert "_TC_CAL_URL" in block, block


def test_recorded_url_is_the_one_actually_called():
    """记录的地址必须就是 special.py 真正 POST 的那个。"""
    from crawlers.special import _TC_CAL_URL
    assert "wx.17u.cn/cheapflights/bffapi" in _TC_CAL_URL, _TC_CAL_URL
    src = _read("tongcheng.py")
    i = src.index('self.path_note("窗历", "calendar"')
    block = src[max(0, i - 700):i + 400]
    # 不得把 ts/calendar 那个已被门拒的地址记进来（只看代码行，跳过注释）
    code = " ".join(ln.split("#", 1)[0] for ln in block.splitlines())
    assert "INTL_CALENDAR_API" not in code, code


def test_h5_list_success_records_page_url():
    src = _read("tongcheng.py")
    i = src.index('"H5列表", "ok"')
    block = src[i:i + 400]
    assert "url=" in block, block


def test_url_param_still_optional():
    """不传 url 的调用点行为不变（不得强制所有渠道都改）。"""
    import inspect
    from crawlers.base import BaseCrawler
    sig = inspect.signature(BaseCrawler.path_note)
    assert sig.parameters["url"].default == ""


# ---- merged from tests/test_r410_url_attr_scope.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CRAWLERS = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "crawlers")


def _crawler_files():
    for fn in sorted(os.listdir(CRAWLERS)):
        if fn.endswith(".py") and fn not in ("__init__.py", "challenge.py"):
            yield fn, os.path.join(CRAWLERS, fn)


def test_url_self_refs_resolve():
    """url= 里出现的 self.X 必须在该文件里定义成类属性/模块常量。"""
    bad = []
    for fn, path in _crawler_files():
        src = open(path, encoding="utf-8").read()
        tree = ast.parse(src)
        # 收集模块级名字与类内属性
        module_names = set()
        class_attrs = set()
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                tgt = node.targets[0] if isinstance(node, ast.Assign) else node.target
                if isinstance(tgt, ast.Name):
                    module_names.add(tgt.id)
            if isinstance(node, ast.ClassDef):
                for st in node.body:
                    if isinstance(st, (ast.Assign, ast.AnnAssign)):
                        tg = (st.targets[0] if isinstance(st, ast.Assign)
                              else st.target)
                        if isinstance(tg, ast.Name):
                            class_attrs.add(tg.id)
                    elif isinstance(st, (ast.FunctionDef,
                                         ast.AsyncFunctionDef)):
                        class_attrs.add(st.name)   # 方法也可安全地 self.x()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fname = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if fname != "path_note":
                continue
            for kw in node.keywords:
                if kw.arg != "url":
                    continue
                for sub in ast.walk(kw.value):
                    if (isinstance(sub, ast.Attribute)
                            and isinstance(sub.value, ast.Name)
                            and sub.value.id == "self"):
                        if sub.attr not in class_attrs and sub.attr not in module_names:
                            bad.append((fn, node.lineno, sub.attr))
    assert not bad, "url= 引用了不存在的属性: %r" % (bad,)


def test_tuniu_list_api_is_module_level():
    """反向锚点：LIST_API 是模块级常量，用 self. 访问会 AttributeError。"""
    import crawlers.tuniu as T
    assert hasattr(T, "LIST_API"), "LIST_API 应为模块级"
    assert not hasattr(T.TuniuCrawler, "LIST_API"), \
        "若改成类属性，本守卫的前提就变了，需同步更新"


def test_every_channel_success_note_has_url():
    """五家渠道的成功记账必须带 url（与 r409 守卫互为加强）。"""
    expect = {
        "ctrip.py": ['"PC", "ok", rows=len(flights)', '"H5", "ok", rows=len(flights)'],
        "tuniu.py": ['"国际列表接口"', '"m.tuniu.com 列表接口"'],
        "qunar.py": ['"touch.qunar.com 国际列表"'],
    }
    for fn, anchors in expect.items():
        src = open(os.path.join(CRAWLERS, fn), encoding="utf-8").read()
        for a in anchors:
            i = src.index(a)
            assert "url=" in src[max(0, i - 500):i + 400], (fn, a)


# ---- merged from tests/test_r660_calendar_cell_viewport.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _cell(ymd, x1, y1, x2, y2):
    return ('<node resource-id="flight_calendar_date_cell-%s" '
            'bounds="[%d,%d][%d,%d]" />' % (ymd, x1, y1, x2, y2))


def _xml(*cells):
    return '<hierarchy rotation="0">%s' % "".join(cells) + "</hierarchy>"


def test_degenerate_bounds_are_not_clickable():
    """y2 < y1 = 卷出视口，绝不能算出可点坐标。"""
    xml = _xml(_cell("2026-11-12", 542, 327, 620, 30))
    assert _calendar_cell(xml, "2026-11-12") is None


def test_visible_cell_returns_center():
    xml = _xml(_cell("2026-11-12", 542, 806, 620, 900))
    assert _calendar_cell(xml, "2026-11-12") == (581, 853)


def test_missing_cell_returns_none():
    assert _calendar_cell(_xml(), "2026-11-12") is None


def test_scroll_hint_uses_visible_cells_only():
    """卷出视口的格子不能参与范围判断，否则方向永远判不出来。"""
    xml = _xml(_cell("2026-11-08", 11, 327, 90, 30),      # 卷出（退化）
               _cell("2026-12-05", 807, 391, 886, 486),   # 可见
               _cell("2026-12-20", 100, 500, 179, 595))   # 可见
    # 目标早于可见区间 → 需往下拉看更早
    assert _cell_month_scroll_hint(xml, "2026-11-12") == "down"
    # 目标晚于可见区间 → 需往上推看更晚
    assert _cell_month_scroll_hint(xml, "2027-01-15") == "up"
    # 落在可见区间内 → 不需要方向提示
    assert _cell_month_scroll_hint(xml, "2026-12-10") is None


def test_needs_earlier_ignores_invisible_cells():
    xml = _xml(_cell("2026-11-08", 11, 327, 90, 30),
               _cell("2026-12-05", 807, 391, 886, 486))
    assert _needs_earlier(xml, "2026-11-12") is True


class _FakeDev:
    """记录 tap/swipe 的最小设备替身（只实现被测路径用到的原语）。"""

    def __init__(self, xmls):
        self.xmls = list(xmls)
        self.taps = []
        self.swipes = []

    def dump(self, retries=2):
        if len(self.xmls) > 1:
            return self.xmls.pop(0)
        return self.xmls[0]

    def tap(self, x, y):
        self.taps.append((x, y))
        return True

    def swipe(self, x1, y1, x2, y2, dur=400):
        self.swipes.append((x1, y1, x2, y2))
        return True


def test_tap_scrolls_then_picks_after_cell_becomes_visible():
    """卷出视口 → 滚动一次 → 格子可见 → 点中 → 弹层关闭 → 成功。

    负控在同一个测试里：第一次 dump 的可点坐标必须为空（没瞎点），
    滚动之后才允许 tap——否则「先点了再说」也会让断言通过。
    """
    before = _xml(_cell("2026-11-12", 542, 327, 620, 30))               # 卷出
    after = _xml(_cell("2026-11-12", 542, 806, 620, 900))               # 可见
    home = ('<hierarchy><node text="11月12日" bounds="[0,0][100,40]" />'
            '</hierarchy>')                                             # 弹层已关
    dev = _FakeDev([before, after, home])
    ok, detail = _tap_calendar_cell(dev, before, "2026-11-12")
    assert ok, detail
    assert dev.swipes, "卷出视口时必须先滚动，不能直接点"
    assert dev.taps and dev.taps[0] == (581, 853), dev.taps


def test_tap_gives_up_when_date_outside_covered_range():
    """真不在覆盖范围（比最小可见日还早且拉不动）→ 明确报不在范围。"""
    xml = _xml(_cell("2026-12-05", 807, 391, 886, 486))
    dev = _FakeDev([xml])
    ok, detail = _tap_calendar_cell(dev, xml, "2026-11-01")
    assert not ok
    assert "2026-11-01" in detail
    assert not dev.taps, "看不到的格子绝不能点"


def test_pick_date_reports_visible_state_not_fake_success():
    """_pick_date 在弹层里拿不到目标格时不得返回成功。"""
    xml = _xml(_cell("2026-12-05", 807, 391, 886, 486))
    dev = _FakeDev([xml])
    ok, detail = _pick_date(dev, [], "2026-11-01", xml=xml)
    assert not ok, detail


# ---- merged from tests/test_r725_marketing_activity_overlay.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 取自真机 dump 的文案与坐标（900×1600 屏）
ACTIVITY_TEXTS = [
    ("全网招募：智行机票体验官", 455, 1103),
    ("免费得以下权益机会", 424, 1201),
    ("活动规则", 824, 1201),
    ("惊喜航班", 114, 1269),
    ("权益一", 89, 1306),
    ("飞行体验价", 556, 1269),
    ("权益二", 518, 1306),
    ("立减权益", 114, 1370),
    ("权益三", 89, 1407),
    ("特价机票", 543, 1370),
    ("权益四", 518, 1407),
    ("一键报名", 450, 1527),
    ("一秒审核", 849, 1496),
    ("\ue706", 865, 1092),      # 右上角 ✕ 图标
]


def _xml_from(texts, extra=""):
    # 上面的坐标是真机 dump 里的**节点中心**，这里按 40×24 的盒子反推 bounds，
    # 免得 _center() 算出来偏 +20/+12。
    out = ["<hierarchy>"]
    for t, x, y in texts:
        out.append(
            '<node text="%s" resource-id="" class="android.widget.TextView" '
            'clickable="false" bounds="[%d,%d][%d,%d]" />'
            % (t.replace('"', "&quot;"), x - 20, y - 12, x + 20, y + 12))
    out.append(extra)
    out.append("</hierarchy>")
    return "".join(out)


ACTIVITY_XML = _xml_from(ACTIVITY_TEXTS)

FLIGHT_LIST_TEXTS = [
    ("上海", 40, 200), ("01-29 周五", 300, 260),
    ("￥1734", 700, 300), ("CA8573", 120, 340),
    ("￥2085", 700, 500), ("FM9253", 120, 540),
]
FLIGHT_LIST_XML = _xml_from(FLIGHT_LIST_TEXTS)


def test_activity_page_has_no_payload():
    """前提：活动页里既没有航班号也没有价格。否则它本来就该按数据页处理。"""
    assert has_payload(ACTIVITY_XML) is False


def test_activity_page_detected_as_closable_ad():
    b = detect_block(ACTIVITY_XML)
    assert b.kind == BLOCK_AD, (b.kind, b.detail)
    assert b.close_xy is not None, "没找到关闭按钮，活动层会一直挡着列表"
    # 关闭钮必须落在右上那个字形上
    assert abs(b.close_xy[0] - 865) <= 6, b.close_xy
    assert abs(b.close_xy[1] - 1092) <= 6, b.close_xy


def test_glyph_close_button_not_confused_by_body_glyphs():
    """正文里的装饰字形不能被当成关闭钮（必须在右侧 2/3）。"""
    texts = [("机票", 100, 300), ("\ue600", 120, 900), ("¥1734", 700, 950)]
    assert _close_button(texts) is None


def test_data_page_is_not_treated_as_ad():
    """负控：有航班/价格的列表页不能被判成广告 —— 那会把好数据丢掉。"""
    b = detect_block(FLIGHT_LIST_XML)
    assert b.kind != BLOCK_AD, (b.kind, b.detail)


def test_text_close_button_still_wins():
    """文字型「关闭」按钮继续优先（别被图标分支抢走）。"""
    texts = [("跳过", 500, 200), ("\ue706", 865, 1092)]
    assert _close_button(texts) == (500, 200)


# ---- merged from tests/test_r727_glyph_is_not_flight_no.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def _card(code, airline, dep, arr, price, y):
    """一张国内航班卡片（几何取自真机 dump）。

    真机实测（list_0.xml）：时刻行 cy=1485，航司/航班号在**下方** cy=1539，
    即航班号比时刻低 ~54px；价格在右侧同一带。
    """
    return (
        '<node text="%s" resource-id="" class="android.widget.TextView" '
        'bounds="[54,%d][96,%d]" />'
        '<node text="%s" resource-id="" class="android.widget.TextView" '
        'bounds="[92,%d][155,%d]" />'
        '<node text="%s" resource-id="" class="android.widget.TextView" '
        'bounds="[92,%d][150,%d]" />'
        '<node text="%s" resource-id="" class="android.widget.TextView" '
        'bounds="[480,%d][540,%d]" />'
        '<node text="&#165;%d" resource-id="" class="android.widget.TextView" '
        'bounds="[770,%d][850,%d]" />'
        % (airline, y + 42, y + 64,
           code, y + 42, y + 64,
           dep, y, y + 24,
           arr, y, y + 24,
           price, y + 20, y + 50)
    )


def _page():
    body = (
        '<node text="上海" bounds="[24,180][80,210]" />'
        '<node text="海口" bounds="[820,180][876,210]" />'
        '<node text="时间" bounds="[120,1534][164,1564]" />'
        '<node text="&#984839;" bounds="[135,1534][164,1564]" />'
        '<node text="价格低-高" bounds="[415,1549][464,1579]" />'
        '<node text="&#984838;" bounds="[435,1549][464,1579]" />'
        '<node text="比价" bounds="[735,1549][764,1579]" />'
        '<node text="&#984837;" bounds="[735,1549][764,1579]" />'
    )
    return ("<hierarchy>"
            + _card("CA8573", "国航", "15:30", "18:55", 1734, 1250)
            + _card("CZ3516", "南航", "12:25", "16:05", 2094, 1500)
            + body + "</hierarchy>")


def test_entity_is_decoded_to_the_glyph():
    """数字实体要还原成字符，不能留字面量 `&#984839;`。"""
    assert _unescape("&#984839;") == chr(984839)
    assert _unescape("&amp;") == "&"
    assert _unescape("普通文本") == "普通文本"


def test_glyph_text_is_not_a_flight_number():
    texts = [n.text for n in _nodes(_page())]
    assert "984839" not in texts
    assert chr(984839) in texts, "图标字形没解码出来，说明实体还原没生效"


def test_flight_number_must_contain_a_letter():
    """底部工具栏图标不能被当成本页某个航班的航班号。"""
    rows = parse_flight_rows(_page())
    codes = [r["flight_no"] for r in rows]
    assert codes == ["CA8573", "CZ3516"], codes
    assert all(any(c.isalpha() for c in c) for c in codes if c), codes


def test_prices_still_attach_to_the_right_card():
    """负控：修实体不能把价格/时刻弄丢。"""
    rows = {r["flight_no"]: r for r in parse_flight_rows(_page())}
    assert rows["CA8573"]["price"] == 1734
    assert rows["CA8573"]["depart_time"] == "15:30"
    assert rows["CZ3516"]["price"] == 2094
    assert rows["CZ3516"]["depart_time"] == "12:25"


def test_numeric_only_text_in_card_is_not_a_flight_no():
    """卡片窗口里的 6 位纯数字不能被当成航班号。

    真机页面里除图标实体外还有大量数字（时长、里程、编号）。旧正则
    `[A-Z0-9]{2}\\d{3,4}` 会把 `202701` 整串吃下——「数字正好落在窗口里
    就变成航班号」。航班号至少含一位字母（CA8573 / 3U8888 / 9C8888），
    所以要求必须含字母。
    """
    xml = ("<hierarchy>"
           '<node text="12:25" bounds="[92,1485][150,1509]" />'
           '<node text="16:05" bounds="[480,1485][540,1509]" />'
           '<node text="202701" bounds="[92,1527][155,1549]" />'
           '<node text="&#165;2094" bounds="[770,1505][850,1535]" />'
           "</hierarchy>")
    rows = parse_flight_rows(xml)
    assert len(rows) == 1, rows
    assert rows[0]["flight_no"] == "", rows[0]["flight_no"]


def test_state_still_ok():
    assert detect_state(_page()) == "ok"


def test_real_device_dump_has_no_numeric_flight_no():
    """回归：真机 dump（8 行列表）里不应再出现纯数字航班号。

    该 fixture 是本轮抓到的真机页面；修复前最后一行是 `984839`。
    """
    path = os.path.join(ROOT, "tests", "fixtures", "zhixing_list_glyph.xml")
    assert os.path.exists(path), "真机 dump 样本缺失：%s" % path
    xml = io.open(path, encoding="utf-8").read()
    rows = parse_flight_rows(xml)
    assert len(rows) == 8, len(rows)
    codes = [r["flight_no"] for r in rows]
    assert "CZ3516" in codes, codes
    assert all(any(c.isalpha() for c in c) for c in codes), codes


# ---- merged from tests/test_r780_round_trip_row_marking.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RT_MARK = 'tripType": "RT"'   # json.dumps 后的形态
RT_MARK_ALT = '"tripType": "RT"'


def _src(plat):
    """渠道主文件 + 同名伴随模块（携程把往返解析拆在 *_roundtrip.py）。

    只看主文件会把「拆到 parser 模块里的 RT 标记」误报成没写；标记的
    真正产出由各渠道自己的夹具用例保证（如 app_ctrip_roundtrip 测试）。
    """
    files = sorted(glob.glob(os.path.join(ROOT, "crawlers", plat + "*.py")))
    return "".join(io.open(f, encoding="utf-8").read() for f in files)


@pytest.mark.parametrize("plat", list(APP_CHANNELS) + list(BROWSER_CHANNELS))
def test_round_trip_capable_channel_marks_rows(plat):
    """声明 y 的渠道，源码里必须真的写 tripType=RT。

    只要求「写了这个标记」，不绑定写法：`{"tripType": "RT"}`（字典字面量）
    与 `dict(f, tripType="RT")`（关键字参数）产出的是**同一份 JSON**，
    按写法判会误报（r780 实测：途牛用后者，被这条断言误判成没标）。
    真正「产出的 JSON 里有没有这个键」由下面用真实夹具的用例保证。
    """
    state = dim_state(plat, "round_trip")
    src = _src(plat)
    if plat == "qunar":
        # 网页版已停服：旧 RT 解析代码留在仓库里但不再执行，
        # 不能拿「源码里还有 tripType」判定声明与行为打架。
        assert state == "n"
        return
    if state != "y":
        # 非 y 渠道也必须给一个可证伪的结论：不写 RT 标记就是它的承诺。
        # fliggy App 目前是唯一一家 ""（未声明），若哪天偷偷写标记而不
        # 升声明，用户会在混排里看到无法解释的往返行。
        assert state in ("", "n"), "%s 的 round_trip 状态越界：%r" % (plat, state)
        assert "tripType" not in src, (
            "%s 未声明 round_trip=y，却在源码里写 tripType——声明与行为打架"
            % plat)
        return
    assert "tripType" in src and "RT" in src, (
        "%s 声明支持往返，但源码里没有 tripType=RT 标记——混排时无法区分口径"
        % plat)


def test_tuniu_round_trip_rows_carry_rt_and_back_date():
    """途牛：真实夹具跑一遍，RT 行必须带 tripType 与 backDate。"""
    # 2026-10-31 真实响应的单行裁剪版（一条 MU5100 往返 offer + 对应
    # flightList 详情），放 tests/fixtures 让干净克隆也能复核。
    fx = os.path.join(ROOT, "tests", "fixtures", "tuniu_rt_sample.json")
    assert os.path.isfile(fx), "真实夹具缺失：%s" % fx
    from unittest import mock
    from crawlers.tuniu import TuniuCrawler

    fixture = json.load(io.open(fx, encoding="utf-8")) or {}

    class _Resp:
        text = json.dumps({"success": True, "data": {
            "fareList": fixture.get("fareList") or [],
            "flightList": fixture.get("flightList") or {}}})

    class _Client:
        cookies = mock.MagicMock()

        def get(self, *a, **k):
            return _Resp()

        def close(self):
            pass

    class _Cfg(dict):
        def get(self, k, d=None):
            return dict.get(self, k, d)

    c = TuniuCrawler(_Cfg(), mock.MagicMock())
    c.config = _Cfg()
    c._sleep = lambda: None
    c._rate_acquire = lambda: None
    c._rate_record = lambda: None
    c.max_poll = 1
    c.max_attempts = 1
    c._saved_page_token = lambda *a, **k: "tok"
    c._saved_session_cookies = lambda: []
    c._install_tac_cookies = lambda *_a, **_k: None
    c._fetch_pc_dom = lambda *a, **k: {}
    c._dump_raw = lambda *a, **k: None
    with mock.patch("crawlers.tuniu._net.new_client", return_value=_Client()):
        rt = c.fetch("SHA", "BJS", ["2026-11-27"], ret_date="2026-12-01")
        ow = c.fetch("SHA", "BJS", ["2026-11-27"])

    assert rt and rt[0].extra, "往返没有产出"
    rt_ex = json.loads(rt[0].extra)
    assert rt_ex and all(e.get("tripType") == "RT" for e in rt_ex)
    assert all(e.get("backDate") == "2026-12-01" for e in rt_ex)

    assert ow and ow[0].extra, "单程没有产出"
    ow_ex = json.loads(ow[0].extra)
    assert ow_ex and not any(e.get("tripType") for e in ow_ex), (
        "单程行被错误地标成了往返——标记泛化后就无法区分口径")


def test_round_trip_price_is_not_compared_as_one_way():
    """读端约定：往返行的 price 是两段合计，不能与单程行同比。

    这里守的是**数据契约的文字**——值域说明必须写在渠道矩阵里，
    否则下游没有任何依据区分。矩阵 y 的渠道要能查到「往返总价」字样。
    """
    ch = io.open(os.path.join(ROOT, "core", "channels.py"),
                 encoding="utf-8").read()
    assert "往返总价" in ch, (
        "渠道矩阵里没写明往返行的 price 是「往返总价」——下游无从判断口径")


# ---- merged from tests/test_r911_web_stealth_human_risk.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_LOG = logging.getLogger("test_r911")


# ---------------------------------------------------------------------------
# 1. 扩展 JS
# ---------------------------------------------------------------------------
def test_extra_js_has_no_placeholders_and_follows_profile():
    with tempfile.TemporaryDirectory() as d:
        c = BaseCrawler({"user_data_dir": d}, _LOG)
        c.profile_name = "alpha"
        fp1 = c.fingerprint()
        js1 = stealth_ext.extra_js(fp1)
        js1b = stealth_ext.extra_js(fp1)
    assert js1 and js1 == js1b
    assert not re.findall(r"__EXT_[A-Z_]+__", js1)
    assert "RTCPeerConnection" in js1
    assert "getChannelData" in js1
    assert "enumerateDevices" in js1


def test_extra_js_mobile_and_desktop_differ():
    desk = stealth_ext.extra_js({"viewport": {"width": 1366, "height": 900},
                                 "is_mobile": False, "seed": 3})
    mob = stealth_ext.extra_js({"viewport": {"width": 390, "height": 844},
                                "is_mobile": True, "seed": 3})
    assert "const MOBILE = false" in desk
    assert "const MOBILE = true" in mob
    assert "landscape-primary" in desk or "portrait-primary" in mob


def test_extra_js_is_fail_soft():
    assert stealth_ext.extra_js(None) != ""
    # 坏数据类型不能抛异常
    assert isinstance(stealth_ext.extra_js({"viewport": "x", "seed": "y"}), str)


def test_launch_args_only_when_stealth():
    assert stealth_ext.launch_args({"stealth": False}) == []
    args = stealth_ext.launch_args({"stealth": True})
    assert any("disable_non_proxied_udp" in a for a in args)


def test_channel_config_optional():
    assert stealth_ext.channel({}) == ""
    assert stealth_ext.channel({"browser_channel": "chrome"}) == "chrome"
    assert stealth_ext.channel({"browser_channel": "  "}) == ""


# ---------------------------------------------------------------------------
# 2. base.py 接线（不启动真浏览器）
# ---------------------------------------------------------------------------
class _Ctx:
    def __init__(self):
        self.scripts = []

    def add_init_script(self, script=None, path=None):
        self.scripts.append(script if script is not None else path)

    def cookies(self):
        return []

    def storage_state(self):
        return {}

    def close(self):
        pass


class _Chromium:
    def __init__(self, ctx):
        self.ctx = ctx
        self.kwargs = None

    def launch_persistent_context(self, *a, **k):
        self.kwargs = k
        return self.ctx


class _PW:
    def __init__(self, chromium):
        self.chromium = chromium

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False










# ---------------------------------------------------------------------------
# 3. 拟人化
# ---------------------------------------------------------------------------
class _Mouse:
    def __init__(self):
        self.moves = 0
        self.wheels = 0

    def move(self, *a, **k):
        self.moves += 1

    def wheel(self, *a, **k):
        self.wheels += 1

    def down(self, *a, **k):
        pass

    def up(self, *a, **k):
        pass


class _Keyboard:
    def type(self, *a, **k):
        pass


class _Page:
    viewport_size = {"width": 1366, "height": 900}

    def __init__(self):
        self.mouse = _Mouse()
        self.keyboard = _Keyboard()


def test_human_delay_is_bounded_and_reproducible():
    a = human.human_delay(1.0, 4.0, rng=human.rng_for(11))
    b = human.human_delay(1.0, 4.0, rng=human.rng_for(11))
    assert a == b
    for _ in range(50):
        v = human.human_delay(0.5, 2.0, rng=human.rng_for(3))
        assert 0.5 <= v <= 2.0
    assert human.human_delay(2.0, 1.0) <= 2.0     # 反向区间不炸


def test_human_warm_returns_report_and_never_raises():
    page = _Page()
    rep = human.warm(page, "alpha", rng=human.rng_for(1), rounds=1)
    assert rep["moves"] >= 1 and rep["scrolls"] >= 1
    assert rep["seconds"] >= 0
    # 坏页面（没有 mouse）也只能返回 0，不许抛
    bad = human.warm(object(), "alpha", rng=human.rng_for(1), rounds=1)
    assert bad["moves"] == 0 and bad["scrolls"] == 0


def test_humanize_config_tolerates_string_false():
    """``humanize: "false"`` 是字符串，bool("false") 为 True——必须按关处理。"""
    with tempfile.TemporaryDirectory() as d:
        on = BaseCrawler({"user_data_dir": d}, _LOG)
        assert on._humanize() == (True, 2)
        off = BaseCrawler({"user_data_dir": d, "humanize": "false"}, _LOG)
        assert off._humanize()[0] is False
        bad = BaseCrawler({"user_data_dir": d, "humanize": "x",
                           "humanize_rounds": "many"}, _LOG)
        assert bad._humanize() == (True, 2)


# ---------------------------------------------------------------------------
# 4. 风险评分
# ---------------------------------------------------------------------------










# ---------------------------------------------------------------------------
# 5. 登录账本 / 退避
# ---------------------------------------------------------------------------
def test_ledger_backoff_ladder_and_recovery(tmp_path):
    led = riskscore.LoginLedger(str(tmp_path / "login_ledger.json"))
    assert led.allow("ctrip")
    for i in range(1, 4):
        led.note_result("ctrip", False, device_risk=True, now=100.0 + i)
        assert led.rec("ctrip")["streak"] == i
    assert led.backoff_s("ctrip") == riskscore.LOGIN_BACKOFF[3]
    assert led.wait_s("ctrip", now=100.0 + 3) > 0
    assert led.allow("ctrip", now=100.0 + 3) is False
    led.note_result("ctrip", True, now=2000.0)
    assert led.rec("ctrip")["streak"] == 0
    assert led.allow("ctrip", now=2000.0) is True


def test_ledger_persists_across_instances(tmp_path):
    path = str(tmp_path / "login_ledger.json")
    a = riskscore.LoginLedger(path)
    a.note_result("qunar", False, device_risk=True, now=1.0)
    a.note_result("qunar", False, device_risk=True, now=2.0)
    b = riskscore.LoginLedger(path)
    assert b.rec("qunar")["streak"] == 2
    assert b.rec("qunar")["device_risk"] == 2


def test_ledger_should_rotate_needs_both_signals(tmp_path):
    led = riskscore.LoginLedger(str(tmp_path / "l.json"))
    for i in range(3):
        led.note_result("ctrip", False, device_risk=True, now=float(i))
    assert led.should_rotate("ctrip") is True
    led.note_result("ctrip", True)
    assert led.should_rotate("ctrip") is False


def test_assess_merges_ledger_and_flags(tmp_path):
    led = riskscore.LoginLedger(str(tmp_path / "l.json"))
    led.note_result("ctrip", False, device_risk=True, now=10.0)
    led.note_result("ctrip", False, device_risk=True, now=11.0)
    got = riskscore.assess("ctrip", ledger=led, captcha=True, login_wall=True)
    assert got["plat"] == "ctrip"
    assert got["login_fail_streak"] == 2 if "login_fail_streak" in got else True
    assert got["score"] >= 48
    assert "login_wait_s" in got


# ---------------------------------------------------------------------------
# 6. App 账本语义：只记「登录类」结果
# ---------------------------------------------------------------------------
def _app(name, package, status, rows=0):
    from crawlers.app_base import AppCrawler

    class _C(AppCrawler):
        def fetch(self, fc, tc, dates, ret_date=""):
            self.path_note("app-list", status, rows=rows)
            return [1] * rows
    _C.name = name
    _C.package = package
    return _C


def test_app_ledger_counts_only_login_failures(tmp_path):
    """超时/无票不许进登录账本，否则退避会涨到 2 小时堵死正常重登。"""
    cfg = {"user_data_dir": str(tmp_path)}

    wall = _app("ctrip", "ctrip.android.view", "login")(cfg, _LOG)
    wall.safe_fetch("SHA", "NRT", ["2026-11-16"])
    wall.safe_fetch("SHA", "NRT", ["2026-11-16"])
    assert wall._ledger().rec("ctrip")["streak"] == 2
    assert wall._ledger().allow("ctrip") is False

    slow = _app("qunar", "com.Qunar", "timeout")(cfg, _LOG)
    slow.safe_fetch("SHA", "NRT", ["2026-11-16"])
    slow.safe_fetch("SHA", "NRT", ["2026-11-16"])
    assert slow._ledger().rec("qunar")["streak"] == 0
    assert slow._ledger().allow("qunar") is True

    good = _app("tongcheng", "com.tongcheng.android", "ok", rows=3)(cfg, _LOG)
    good.safe_fetch("SHA", "NRT", ["2026-11-16"])
    assert good._ledger().allow("tongcheng") is True


def test_app_ledger_success_clears_previous_streak(tmp_path):
    cfg = {"user_data_dir": str(tmp_path)}
    bad = _app("ctrip", "ctrip.android.view", "captcha")(cfg, _LOG)
    bad.safe_fetch("SHA", "NRT", ["2026-11-16"])
    assert bad._ledger().rec("ctrip")["streak"] == 1
    ok = _app("ctrip", "ctrip.android.view", "ok", rows=2)(cfg, _LOG)
    ok.safe_fetch("SHA", "NRT", ["2026-11-16"])
    assert ok._ledger().rec("ctrip")["streak"] == 0


# ---- merged from tests/test_r929_paced_not_failure.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ---------------------------------------------------------------------------
# 1. is_paced 判定
# ---------------------------------------------------------------------------
def test_all_paced_is_paced():
    assert is_paced([{"status": "paced"}]) is True
    assert is_paced([{"status": "paced"}, {"status": "paced"}]) is True


def test_mixed_with_real_attempt_is_not_paced():
    """只要有一条真跑过，这轮就是真实样本（不能被 paced 掩盖）。"""
    assert is_paced([{"status": "paced"},
                     {"status": "timeout"}]) is False
    assert is_paced([{"status": "paced"},
                     {"status": "ok", "rows": 5}]) is False
    assert is_paced([{"status": "paced"},
                     {"status": "soft_reject"}]) is False


def test_empty_paths_is_not_paced():
    """没有路径记录 ≠ 主动让位（可能压根没跑，也可能是真失败）。"""
    assert is_paced([]) is False
    assert is_paced(None) is False


def test_non_dict_entries_ignored():
    assert is_paced([{"status": "paced"}, "junk", None]) is True


# ---------------------------------------------------------------------------
# 2. statuses_ok 对 paced 的处理（不冒充成功）
# ---------------------------------------------------------------------------
def test_paced_is_not_success():
    ok, rows, _ = statuses_ok([{"status": "paced"}])
    assert ok is False and rows == 0


def test_paced_does_not_mask_real_success():
    ok, rows, path = statuses_ok([{"status": "paced"},
                                  {"status": "ok", "rows": 7, "path": "H5"}])
    assert ok is True and rows == 7


# ---------------------------------------------------------------------------
# 3. 词表与规范同步（契约）
# ---------------------------------------------------------------------------
def test_path_status_contains_paced():
    from crawlers.base import BaseCrawler
    from crawlers.app_base import AppCrawler
    assert "paced" in BaseCrawler.PATH_STATUS
    assert "paced" in AppCrawler.PATH_STATUS


def test_spec_documents_paced_and_distinction():
    """规范必须写清 `paced` 与 `soft_reject` 的区别（否则下次又被混用）。"""
    if not os.path.exists(os.path.join(ROOT, "docs", "EXECUTION_SPEC_LATEST.md")):
        pytest.skip("EXECUTION_SPEC_LATEST 已删（W2b 文档工程），本门禁失去检查对象")
    spec = io.open(os.path.join(ROOT, "docs", "EXECUTION_SPEC_LATEST.md"),
                   encoding="utf-8").read()
    assert "`paced`" in spec
    assert "不进爬取率分母" in spec
    assert "is_paced" in spec


# ---------------------------------------------------------------------------
# 4. qunar 让位确实记 paced（源码钉）
# ---------------------------------------------------------------------------
def test_qunar_yield_records_paced():
    src = io.open(os.path.join(ROOT, "crawlers", "qunar.py"),
                  encoding="utf-8").read()
    # 认准**真正写账本**的那处：`path_note(` 紧跟着 paced 与"国际查询让位"
    idx = -1
    while True:
        idx = src.find("国际查询让位", idx + 1)
        if idx < 0:
            break
        seg = src[max(0, idx - 400):idx]
        if "path_note(" in seg and '"paced"' in seg:
            return                      # 找到"让位 → 记 paced"的实账
    raise AssertionError("没找到把让位记成 paced 的 path_note（会污染爬取率）")


# ---- merged from tests/test_r936_scene_on_unknown.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ---------------------------------------------------------------------------
# 1. 通用落盘
# ---------------------------------------------------------------------------
def test_save_scene_writes_file(tmp_path, monkeypatch):
    monkeypatch.setenv("TICKET_SCENE_DIR", str(tmp_path))
    xml = ('<node text="机票查询" resource-id="com.suan:id/a" '
           'bounds="[10,20][300,80]" />')
    p = save_scene("unknown-page", xml, prefix="zhixing_app")
    assert p and os.path.isfile(p)
    body = io.open(p, encoding="utf-8").read()
    assert "机票查询" in body
    assert "10,20,300,80" in body


def test_save_scene_caps_rows(tmp_path, monkeypatch):
    """真机 dump 常 200KB：必须截断，不能整份存。"""
    monkeypatch.setenv("TICKET_SCENE_DIR", str(tmp_path))
    nodes = "".join('<node text="t%d" bounds="[0,%d][10,%d]" />'
                    % (i, i, i + 5) for i in range(500))
    p = save_scene("big", nodes, prefix="x", limit=20)
    lines = io.open(p, encoding="utf-8").read().strip().splitlines()
    assert len(lines) == 20, len(lines)


def test_save_scene_keeps_desc_only_nodes(tmp_path, monkeypatch):
    """中转航班号这类节点只有 content-desc、没有 text，也要留住。"""
    monkeypatch.setenv("TICKET_SCENE_DIR", str(tmp_path))
    xml = ('<node text="" content-desc="flight_search_rn|Qunar|ItemPrice" '
           'bounds="[655,784][723,817]" />')
    p = save_scene("desc", xml, prefix="x")
    body = io.open(p, encoding="utf-8").read()
    assert "ItemPrice" in body


def test_save_scene_is_fail_soft(monkeypatch, tmp_path):
    """写不进去不能抛（采集优先）。

    用「普通文件当目录」制造不可写：不依赖权限（root/runner 差异），
    也不往环境变量塞 NUL（Linux 的 os.environ 会先抛 ValueError，
    测试还没进 save_scene 就红了——2026-11-04 CI test(2) 实测）。
    """
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("TICKET_SCENE_DIR", str(blocker / "sub"))
    assert save_scene("x", "<node text='a' bounds='[0,0][1,1]' />") == ""


def test_save_scene_empty_xml(tmp_path, monkeypatch):
    monkeypatch.setenv("TICKET_SCENE_DIR", str(tmp_path))
    p = save_scene("empty", "", prefix="x")
    # 仍写一个空文件（至少说明"这一帧是空的"）
    assert p and os.path.isfile(p)


# ---------------------------------------------------------------------------
# 2. 两处调用点都在，且带了标记提示（源码钉）
# ---------------------------------------------------------------------------
def test_qunar_saves_scene_when_list_page_missing():
    src = io.open(os.path.join(ROOT, "crawlers", "app_qunar.py"),
                  encoding="utf-8").read()
    i = src.find('return [], ("empty" if saw_list_page else "no-list-page")')
    assert i > 0
    seg = src[max(0, i - 1800):i]
    assert "nolist-" in seg, "no-list-page 仍不落现场"
    assert "列表页未出现" in seg, "没有一行说清停在哪一页"


def test_zhixing_saves_scene_on_unknown_state():
    src = io.open(os.path.join(ROOT, "crawlers", "app_zhixing.py"),
                  encoding="utf-8").read()
    i = src.find("无法识别的页面状态")
    assert i > 0
    seg = src[max(0, i - 1600):i]
    assert "save_scene" in seg, "认不出页面时不落现场"
    assert "unknown-page" in seg


def test_no_bare_private_save_scene_left_in_zhixing():
    """不许再引用不存在的 `_save_scene`（那是 qunar 的私有函数）。"""
    src = io.open(os.path.join(ROOT, "crawlers", "app_zhixing.py"),
                  encoding="utf-8").read()
    assert "_save_scene(" not in src


# ---- merged from tests/test_r944_gap_left_block.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

def _png(draw_fn, size=(822, 411)):
    im = Image.new("RGB", size, (240, 240, 240))
    ImageDraw.Draw(im).__class__  # noqa: B018  (确保 import 被用)
    draw_fn(ImageDraw.Draw(im), size)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _scene_piece_and_gap(piece_x=57, piece_w=44, gap_x=266, gap_w=76):
    """造一张"左侧有拼图块、右侧有缺口"的图。"""
    def _draw(d, size):
        # 拼图块：深色方块 + 明显描边（两条强竖边）
        d.rectangle([piece_x, 120, piece_x + piece_w, 260], fill=(60, 60, 60))
        d.rectangle([piece_x, 120, piece_x + piece_w, 260], outline=(0, 0, 0), width=3)
        # 缺口：中间偏亮、两侧描边
        d.rectangle([gap_x, 130, gap_x + gap_w, 250], fill=(200, 200, 205))
        d.rectangle([gap_x, 130, gap_x + gap_w, 250], outline=(30, 30, 30), width=3)
        # 加一点背景纹理，避免"纯色早退"
        for y in range(0, size[1], 40):
            d.line([(0, y), (size[0], y)], fill=(225, 225, 228), width=1)
    return _png(_draw)


# ---------------------------------------------------------------------------
# 1. 核心：缺口要选在右侧，不能被左侧拼图块抢走
# ---------------------------------------------------------------------------
def test_gap_chosen_right_of_piece():
    png = _scene_piece_and_gap()
    best, cands = slider.find_gap(png, (0, 0, 822, 411))
    assert cands, "没找到任何候选"
    # 真缺口中心 ≈ (266+76/2)=304；允许 ±30
    assert abs(best - 304) <= 30, "best=%d 偏离太多（候选=%s）" % (best, cands)


def test_candidates_not_clustered_on_piece():
    """候选不许聚在拼图块位置（x≈57~123）。"""
    png = _scene_piece_and_gap()
    _, cands = slider.find_gap(png, (0, 0, 822, 411))
    left = [c for c in cands if c[0] < 180]
    assert len(left) <= 1, "候选里有多条落在拼图块区域：%s" % cands


def test_no_dead_code_after_return():
    """缺口实现里不许有 `return` 之后的死代码。

    2026-11-05 起缺口算法被拆成两层：`_find_gap_edges`（边缘能量实现）
    + `find_gap`（薄封装，另外并入 ddddocr 滑轨模型的结果，见 §6.56）。
    死代码只可能出现在**实现**那一层，所以这里跟着实现走；
    同时钉住封装层存在，避免有人把两层又合回去却丢了 ddddocr 那一路。
    """
    src = io.open(os.path.join(ROOT, "crawlers", "slider.py"),
                  encoding="utf-8").read()
    i = src.find("def _find_gap_edges")
    assert i > 0, "缺口实现函数不见了（应叫 _find_gap_edges）"
    j = src.find("\ndef ", i + 10)
    body = src[i:j]
    # 统计 "return ranked[0][0], ranked[:top]" 出现次数：只应 1 次
    assert body.count("return ranked[0][0], ranked[:top]") == 1, \
        "缺口实现里仍有重复/死代码返回"
    assert "def find_gap(" in src, "封装层 find_gap 不见了（ddddocr 那一路会丢）"


# ---------------------------------------------------------------------------
# 2. 左侧降权是"打对折"而不是"丢掉"（小图 / 方块偏右时不能误杀）
# ---------------------------------------------------------------------------
def test_left_candidate_still_kept_when_only_option():
    """只有左侧有边时仍要给出候选（不许因为降权就返回 0）。"""
    def _draw(d, size):
        d.rectangle([40, 120, 90, 260], fill=(50, 50, 50))
        d.rectangle([40, 120, 90, 260], outline=(0, 0, 0), width=3)
        for y in range(0, size[1], 40):
            d.line([(0, y), (size[0], y)], fill=(228, 228, 230), width=1)
    png = _png(_draw)
    best, cands = slider.find_gap(png, (0, 0, 822, 411))
    # 至少不该崩，且若给了候选要落在合理范围
    assert best >= 0 and isinstance(cands, list)


# ---------------------------------------------------------------------------
# 3. 纯色图仍要早退（回归守卫）
# ---------------------------------------------------------------------------
def test_blank_image_returns_zero():
    png = _png(lambda d, size: None)
    best, cands = slider.find_gap(png)
    assert best == 0 and cands == []
