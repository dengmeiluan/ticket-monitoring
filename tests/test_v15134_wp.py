# -*- coding: utf-8 -*-
"""r234 波次2 审计落地钉（_scratch/worker_r234_webui_push.md +
worker_r234_observe.md 消化）：

- WP-P2-1 遗留单航线标题差额词走 gap_txt 单源：「≤」白名单外字符
          出正文 + 价格未 :.0f 曾出「￥1850.0」，两个衍生问题一并消除
- WP-P2-2 _fmt_flight_line 骨架档辨识信息跟入：跨天（+1天）/停X
          保到地板档、渠道名先让位（档序律：辨识信息最后丢；
          双名 36 半角行曾触发跨天班读不出 +1天）
- WP-P2-3 弹层正文链接 .pvbody a 触控热区 36px 补齐（NOTIFY 轻页
          .md a 先例，主站弹层家族最后漏点）
- WP-E1   qunar lay2dep 空串落键收口（H5/PC 两写点无值不落；
          ctrip/tongcheng 同键早是无值不落口径，qunar 是唯一例外，
          直飞行 ×276 曾带空串落库）
- WP-E2   合成推送隔离（conftest 自律）：send 触达测试全量
          PUSH_HISTORY_FILE 重定向——20 条合成记录曾混入生产账本

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v15134_wp.py -q
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.alerter import Alerter, _disp_dw  # noqa: E402
from core.models import FlightPrice, Route  # noqa: E402
from core.storage import PriceStorage  # noqa: E402
from crawlers.qunar import QunarCrawler  # noqa: E402

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
    """双名 36 半角行（生产在案形态）落入骨架档时：跨天（+1天）保留、
    渠道名先让位——曾骨架档整体丢辨识信息，跨天班按到达时刻误判
    当日达（档序律：辨识信息最后丢）。"""
    f = {"price": 1850, "name": "新海航｜天津航空GS7495", "code": "GS7495",
         "depTime": "21:10", "arrTime": "02:35", "crossDayDesc": "+1天",
         "transCity": "郑州", "layoverT": "1时55分", "totalDuration": "",
         "_platform": "qunar"}
    out = Alerter._fmt_flight_line(f, idx=3, mark="🔥 ")
    assert "+1天" in out, "骨架档丢跨天辨识信息（误判当日达风险）"
    assert "去哪儿" not in out and "同价" not in out, \
        "渠道名未先于辨识信息让位"
    assert _disp_dw(out) <= 40, f"骨架档超宽: {out!r}"


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
    src = _src("webui.py")
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
