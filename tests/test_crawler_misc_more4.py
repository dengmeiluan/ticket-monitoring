# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1777_ms_sentinel.py
- tests/test_r934_dismiss_retry.py
- tests/test_v15134_wp.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import io
import json
import logging
import os
import sys

from core.alerter import Alerter, _disp_dw
from core.models import FlightPrice, Route
from core.storage import PriceStorage
from crawlers.app_base import dismiss_until_gone
from crawlers.app_zhixing import AppZhixingCrawler
from crawlers.qunar import QunarCrawler


# ---- merged from tests/test_r1777_ms_sentinel.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class _Log:
    def info(self, fmt, *a):
        pass

    warning = info


def _crawler():
    c = AppZhixingCrawler({}, _Log())
    c.paths = []
    c.user_data_root = os.path.join(os.getcwd(), "_scratch", "_u")
    return c


def test_known_zero_ms_is_not_filled_from_delta():
    c = _crawler()
    c.path_note("app-login", "ok", detail="登录正常")          # 假定这步很慢
    c.path_note("app-date", "unsupported", ms=-1, detail="日期超视野")
    rows = {r["path"]: r for r in c.paths}
    assert rows["app-date"]["ms"] == 0, rows["app-date"]


def test_missing_ms_still_backfills():
    """没传 ms 的（真实的抓取步骤）仍要兜底补，不然速度口径又空了。"""
    c = _crawler()
    c.path_note("app-login", "ok", detail="登录正常")
    c.path_note("app-city", "timeout", detail="点城市位失败")
    rows = {r["path"]: r for r in c.paths}
    assert rows["app-city"]["ms"] >= 0


def test_horizon_note_uses_sentinel():
    import io
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "crawlers", "app_base.py"),
        encoding="utf-8").read()
    i = src.index("def reject_far_dates")
    seg = src[i:i + 1200]
    assert "ms=-1" in seg, "日期视野检查没用哨兵"
    assert "_ms_known_zero" in src, "没有哨兵处理"


# ---- merged from tests/test_r934_dismiss_retry.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

class FakeDev:
    """``frames`` 逐帧返回 dump；记录 BACK 次数。"""

    def __init__(self, frames):
        self.frames = list(frames)
        self.i = 0
        self.backs = 0
        self.dumps = 0

    def dump(self):
        self.dumps += 1
        f = self.frames[min(self.i, len(self.frames) - 1)]
        self.i += 1
        return f

    def keyevent(self, code):
        self.backs += 1
        return True


DIALOG = '<node text="Search_Calendar_Dialog" />'
HOME = '<node text="机票查询" />'


# ---------------------------------------------------------------------------
# 1. 已经关掉：不该按 BACK
# ---------------------------------------------------------------------------
def test_already_gone_does_not_press_back():
    d = FakeDev([HOME])
    gone, xml = dismiss_until_gone(d, "Search_Calendar_Dialog")
    assert gone is True
    assert d.backs == 0
    assert "机票查询" in xml


# ---------------------------------------------------------------------------
# 2. 一次 BACK 就关掉（最常见）
# ---------------------------------------------------------------------------
def test_one_back_closes_dialog():
    d = FakeDev([DIALOG, HOME])
    gone, xml = dismiss_until_gone(d, "Search_Calendar_Dialog", tries=2)
    assert gone is True
    assert d.backs == 1


# ---------------------------------------------------------------------------
# 3. 按了几次都关不掉：如实返回 False（不假装成功）
# ---------------------------------------------------------------------------
def test_still_open_returns_false():
    d = FakeDev([DIALOG])
    gone, _ = dismiss_until_gone(d, "Search_Calendar_Dialog", tries=2)
    assert gone is False
    assert d.backs == 2


# ---------------------------------------------------------------------------
# 4. 设备异常也不能抛
# ---------------------------------------------------------------------------
def test_keyevent_failure_is_fail_soft():
    class Bad(FakeDev):
        def keyevent(self, code):
            raise RuntimeError("device gone")
    d = Bad([DIALOG])
    gone, _ = dismiss_until_gone(d, "Search_Calendar_Dialog")
    assert gone is False


def test_dump_failure_is_fail_soft():
    class Bad(FakeDev):
        def dump(self):
            raise RuntimeError("uiautomator dead")
    d = Bad([DIALOG])
    try:
        gone, _ = dismiss_until_gone(d, "Search_Calendar_Dialog")
    except Exception as e:                    # noqa: BLE001
        raise AssertionError("不该抛：%s" % e)
    assert gone is False


# ---------------------------------------------------------------------------
# 5. 两处调用点都在（源码钉）
# ---------------------------------------------------------------------------
def test_zhixing_retries_instead_of_giving_up():
    src = io.open(os.path.join(ROOT, "crawlers", "app_zhixing_nav.py"),
                  encoding="utf-8").read()
    # 只钉**不变量**：弹层没关不许直接放弃，必须 BACK + 重试。
    # r938 之后重试的正确形态是「重新打开弹层再点」（BACK 已把弹层关掉，
    # 就地找格子注定失败）；具体形态由 test_r938_date_retry_reopen.py 钉住。
    assert "dismiss_until_gone" in src, "智行仍直接放弃，没有 BACK 重试"
    assert ("open_date_dialog(dev)" in src
            or "重试一次点击" in src), "没有可用的重试路径"
    assert ("重开弹层失败" in src or "重试后仍开" in src), \
        "重试后仍失败没有独立证据"


def test_qunar_retries_instead_of_giving_up():
    src = io.open(os.path.join(ROOT, "crawlers", "app_qunar.py"),
                  encoding="utf-8").read()
    assert "dismiss_until_gone" in src, "qunar 日期弹层仍直接放弃"


# ---- merged from tests/test_v15134_wp.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("t15134wp")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(*rel):
    with open(os.path.join(_ROOT, *rel), encoding="utf-8") as f:
        return f.read()


def _fp(plat, price=1600, tbg="direct", code="MU5700", trans="兰州"):
    return {"price": price, "name": "东航" + code, "code": code,
            "depTime": "10:00", "arrTime": "15:00",
            "depDate": "2026-10-06", "arrDate": "2026-10-06",
            "transCity": trans, "crossDayDesc": "",
            "totalDuration": "9时30分", "_platform": plat,
            "transferBaggage": tbg, "layoverM": 120}


def _ps(fs, fc="URC", tc="SHA", d="2026-10-06"):
    return [FlightPrice(platform=f["_platform"], from_city=fc, to_city=tc,
                        depart_date=d, price=f["price"],
                        extra=json.dumps([f], ensure_ascii=False))
            for f in fs]


def _route(**kw):
    d = dict(from_code="URC", to_code="SHA", from_name="乌鲁木齐",
             to_name="上海", dates=["2026-10-06"],
             alert_direct=0, alert_transfer=1700,
             transfer_arrival_max="23:59", transfer_baggage="direct")
    d.update(kw)
    return Route(**d)


class FakeN:
    def __init__(self):
        self.sent = []

    def send(self, title, desp, **kw):
        self.sent.append({"title": title, "desp": desp})
        return True


# ---- WP-P2-1 遗留标题差额词单源 -------------------------------

def test_legacy_title_gap_txt(tmp_path):
    """遗留单航线标题「直飞￥1850≤1900」三重病：「≤」不在确定安全
    字符集（钉钉渲染器行为不可实测，白名单外字符不入正文）、差额词
    第三词源（聚合路径走 gap_txt）、价格未 :.0f（浮点价曾出
    「￥1850.0」）。修后与聚合标题同语言。"""
    a = Alerter(_LOG, notifier=FakeN(),
                storage=PriceStorage(str(tmp_path / "p.db")),
                digest=True, user="t")
    a._send_urgent = lambda *args, **kwargs: True
    a.check_and_alert(_route(), _ps([_fp("fliggy", price=1600.0)]))
    title = a.notifier.sent[-1]["title"]
    assert "≤" not in title, "「≤」白名单外字符入正文"
    assert "低￥100" in title, "差额词未走 gap_txt 单源（与聚合标题同语言）"
    assert ".0" not in title and "￥1600" in title, "价格未 :.0f"


# ---- WP-P2-2 骨架档辨识信息跟入 -------------------------------

def test_skeleton_keeps_identity():
    """🔥 行新档序（r283 P2-1，命中域）：保完整码、剥跨天括注——
    同一告警 desp 的 hits 区 seg 行恒承载该班时刻+跨天，读者不再知价
    不知班。r285 审校 P2-1 收域：保码剥跨天启用域=「该行 ∈ hits」
    （in_hits=True，TOP5 次优 🔥 行无第二承载位必须保跨天，钉在
    test_r285_push）——本钉样本随域加参（语义=命中行语义）；
    report 日报兜底语境（keep_cross=True，无 hits 段）跨天恒保
    （test_r283_push 对照钉）。渠道名先让位（档序律：辨识信息最后
    丢）维持。"""
    f = {"price": 1850, "name": "新海航｜天津航空GS7495", "code": "GS7495",
         "depTime": "21:10", "arrTime": "02:35", "crossDayDesc": "+1天",
         "transCity": "郑州", "layoverT": "1时55分", "totalDuration": "",
         "_platform": "qunar"}
    out = Alerter._fmt_flight_line(f, idx=3, mark="🔥 ", in_hits=True)
    assert "GS7495" in out, "🔥 行整码丢弃（读者知价不知班）"
    assert "￥1850" in out and "21:10→02:35" in out, out
    assert "去哪儿" not in out and "同价" not in out, \
        "渠道名未先于辨识信息让位"
    assert _disp_dw(out) <= 40, f"🔥 行超宽: {out!r}"


# 停X 跟入降级档的语义由 test_v166_push 骨架钉锁定（同一改动的姊妹
# 断言不重复落钉）；本文件锁定跨天辨识信息保到地板档这一核心档序，
# 并给 skeleton/skeleton_nb 两档直落钉（r234 Soldier P2-1：样本实测
# 两颗既有新钉均落 bare，前三档行为零钉面；「剥渠道保完整码」独立
# 档与 bare 数学等价已撤档，直落钉锁真实分档的可辨形态）。


def test_skeleton_tier_direct_landing():
    """skeleton 档直落钉：渠道段全角括号形态在场、码完整、≤40
    （样本恰可达该档：nb/bare 均不放行）。"""
    f = {"price": 580, "name": "长龙航GS7495", "code": "GS7495",
         "depTime": "21:10", "arrTime": "02:35", "crossDayDesc": "",
         "transCity": "", "layoverT": "", "totalDuration": "",
         "_platform": "tongcheng"}
    out = Alerter._fmt_flight_line(f, idx=None, mark="")
    assert "（同程）" in out, "skeleton 档渠道段全角括号形态缺失"
    assert "GS7495" in out and _disp_dw(out) <= 40, f"码段/宽度异常: {out!r}"


def test_skeleton_nb_tier_direct_landing():
    """skeleton_nb 档直落钉：全角括号对剥除后渠道裸词保词界（「（」
    换空格而非双删——双删曾让时刻与渠道名粘成「02:35同程」）、
    码完整、同价计数在场、≤40（skeleton 41-43 恰超、nb 收回带）。"""
    f = {"price": 580, "name": "长龙航GS7495AB", "code": "GS7495AB",
         "depTime": "21:10", "arrTime": "02:35", "crossDayDesc": "",
         "transCity": "", "layoverT": "", "totalDuration": "",
         "_platform": "tongcheng", "_tie_n": 3}
    out = Alerter._fmt_flight_line(f, idx=None, mark="")
    assert " 同价×3" in out and "（同价" not in out, \
        "skeleton_nb 档应剥括号保裸词形态"
    assert "GS7495AB" in out and _disp_dw(out) <= 40, f"码段/宽度异常: {out!r}"


# ---- WP-P2-3 弹层正文链接触控热区 ------------------------------

def test_pvbody_link_touch_area():
    """弹层正文链接（推送预览/记录/通知详情三入口共用 .pvbody）的
    跳转链接触控热区补齐：inline 锚盒高随环境字体浮动（Win 17px/
    CI Linux 15px），inset:-11px 按最差环境补到 37px 触控基准
    （r234「23px 行盒」估算落 -7px 实得 31px；r243 首修 -10px 在
    CI 差 1px，几何地板钉按最差环境取值）。position:relative +
    ::after 外扩声明双在案。"""
    src = webui_full_src()
    assert "#pvMask .pvbody a{position:relative}" in src, \
        "弹层链接缺定位锚（::after 外扩前提）"
    assert "#pvMask .pvbody a::after" in src and "inset:-11px -4px" in src, \
        "弹层链接触控外扩块缺失（CI 15px 锚盒需纵向 ±11px 达 37px）"


# ---- WP-E1 qunar lay2dep 空串落键收口 -------------------------

_PC_DATE = "2026-10-06"


def _pc(**kw):
    b2 = {"depTime": "06:50", "arrTime": "12:30",
          "date": _PC_DATE, "arrDate": _PC_DATE,
          "depTerminal": "T5", "depAirport": "咸阳机场"}
    b2.update(kw.pop("b2", {}))
    flight = {"minPrice": 2000, "code": kw.pop("code", "GS7495/9C6178"),
              "transCity": kw.pop("transCity", "西安"),
              "binfo1": {"depTime": "19:25", "arrTime": "21:40",
                         "date": _PC_DATE, "arrTerminal": "T3",
                         "arrAirport": "咸阳机场"},
              "binfo2": b2}
    flight.update(kw)
    return json.dumps({"data": {"flights": [flight]}}, ensure_ascii=False)


def test_qunar_direct_row_no_empty_lay2dep():
    """无值不落键：qunar 直飞行曾恒带 lay2dep:\"\" 落库（×276 实测；
    消费端 falsy 门兜住属「无值不落」门欠账，写入面根治）——
    ctrip/tongcheng 同键早是缺席口径，qunar 是四渠道唯一例外。
    中转行真值照落零漂移。"""
    direct = json.dumps({"data": {"flights": [{
        "minPrice": 2000, "code": "9C8866",
        "binfo": {"depTime": "08:00", "arrTime": "11:30",
                  "date": _PC_DATE, "arrDate": _PC_DATE}}]}})
    d = QunarCrawler._parse_pc_flights(direct, _PC_DATE)[0]
    assert "lay2dep" not in d, "直飞行空串 lay2dep 落键"
    t = QunarCrawler._parse_pc_flights(_pc(), _PC_DATE)[0]
    assert t["lay2dep"] == "06:50", "中转行真值出口被误伤"


# ---- WP-E2 合成推送隔离自律 -----------------------------------

def test_push_history_env_isolated_in_tests():
    """conftest autouse 自律生效：整个测试会话内 PUSH_HISTORY_FILE
    必被重定向——send 触达测试漏隔离曾把 20 条合成记录混入生产
    push_history（控制台推送记录可见假推送）。"""
    assert os.environ.get("PUSH_HISTORY_FILE"), (
        "tests/conftest.py 缺 autouse PUSH_HISTORY_FILE 隔离")
