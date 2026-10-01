# -*- coding: utf-8 -*-
"""r249 推送四案（TDD 先行，审计报告 _scratch/r249_push_audit.md）：

P1-1 _fmt_flight_line 兜底链对联程双码行缺「剥「/」后段」档——
    双码行（UQ2509/Y87520 形，09-24 真实发行）在 bare 地板档逐字截
    下先截码：仅停形态悬垂「UQ2509/」、停+跨天形态码截空再舍停让
    航班号整体消失。图挂兜底轮（图床上传失败轮）文本是明细唯一
    载体，航班号是取票/值机的辨识信息。修法：链中增「剥「/」后段
    保首段」档（零损耗先于逐字截）；单码行不生成该档（与 bare
    恒同串=数学死档，十九§16 判据），同构先例 r235 P1（_l2_fallbacks
    联程剥首段档）。
P2-1 逐字截地板不感知括号对：三处 _trim（alerter._section_title /
    report._route_section_title / report._miss_chart_line）截断可停在
    括号对中间产出「乌鲁木齐（地窝」半截括号——截后剥孤立「（」。
P2-2 截断轮 debug/last_push.md 写截断前原文（desp 参数）与实收
    （text）/推送落账三者不一致，按 mtime 对账取证时对不上——
    改写实收 text（与落账同源）。
P2-3 能力对称（三十§3）：告警路径常驻「> 📉 近7天 …」趋势行而日报
    无同构消费点——日报是每日唯一综合视图，信息容量反低于告警。
    词面组装提单源 _trend_bits_str/_trend_block（模块级），告警
    _trend_line 与日报 build_and_push 同消费。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r249_push.py
"""
import logging
import os
import re

import core.notifier as nm

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------- P1-1: 联程双码行剥「/」后段档 ----------

def _fbase():
    return {"_platform": "qunar", "price": 2218,
            "name": "UQ2509/Y87520", "code": "UQ2509/Y87520",
            "depTime": "08:30", "arrTime": "00:40",
            "transCity": "郑州", "layoverT": "1:30"}


def test_flight_line_codeshare_stop_keeps_first_seg():
    from core.alerter import Alerter, _disp_dw
    line = Alerter._fmt_flight_line(dict(_fbase()), idx=2)
    assert "UQ2509/" not in line, "悬垂「UQ2509/」在场（逐字截截码）：%r" % line
    assert "UQ2509" in line, "首段码丢失：%r" % line
    assert _disp_dw(line) <= 40, "行宽 %d 超 40：%r" % (_disp_dw(line), line)


def test_flight_line_codeshare_stop_crossday_keeps_first_seg():
    """停+跨天形态航班号曾整体消失（码截空再舍停）——取票辨识信息。"""
    from core.alerter import Alerter, _disp_dw
    line = Alerter._fmt_flight_line(dict(_fbase(), crossDayDesc="+1天"), idx=2)
    assert "UQ2509" in line, "停+跨天形态航班号整体消失：%r" % line
    assert _disp_dw(line) <= 40, "行宽超 40：%r" % line


def test_flight_line_single_code_no_regress():
    """单码/无「/」行不生成剥段档（与 bare 恒同串=死档）——全码照旧。"""
    from core.alerter import Alerter
    line = Alerter._fmt_flight_line(
        dict(_fbase(), name="UQ2509", code="UQ2509"), idx=2)
    assert "UQ2509" in line and "/" not in line.replace("→", "")


def test_flight_line_codeshare_full_code_survives_when_fits():
    """Soldier P1-1：剥段判据必须折入 bare 地板（全码→首段→逐字截）
    而非独立档置 bare 前——独立档曾吞「bare 全码可放下」档，144 组
    经停/直飞双码行第二段码无谓丢失（修复动机自相矛盾）。"""
    from core.alerter import Alerter
    line = Alerter._fmt_flight_line(
        dict(_fbase(), price=599, transCity="", layoverT=""), idx=1)
    assert "UQ2509/Y87520" in line, (
        "bare 全码可放下时被剥段档吞掉第二段码：%r" % line)
    # 全码放不下时才降首段（双码+停形态既有钉覆盖）


def test_trim_nested_paren_all_levels():
    """Soldier P2-2：剥括号须 while 化——嵌套括号名单轮剥除后仍残留
    孤立「（」（「北京（首都（T3）机场」截断形态）。"""
    from core.alerter import Alerter
    import report
    out = Alerter._section_title("北京（首都（T3）机场）", "上海（虹桥+浦东）",
                                 "10/03~10/09", "08:00-10:00 出发")
    assert out.count("（") == out.count("）"), "嵌套括号残留：%r" % out[:60]
    out2 = report._miss_chart_line(
        "北京（首都（T3）机场）→上海（虹桥+浦东）", "2026-10-06")
    assert out2.count("（") == out2.count("）"), "嵌套括号残留：%r" % out2[:60]


# ---------- P2-1: 逐字截剥孤立「（」（三处同轮） ----------

def test_section_title_no_lone_paren():
    from core.alerter import Alerter
    out = Alerter._section_title("乌鲁木齐（地窝堡）", "上海（虹桥+浦东）",
                                 "10/03~10/09", "08:00-10:00 出发")
    assert out.count("（") == out.count("）"), "未配对全角括号：%r" % out[:60]


def test_route_section_title_no_lone_paren():
    import report
    out = report._route_section_title(
        ["乌鲁木齐（地窝堡）", "上海（虹桥+浦东）"], "2026-10-06")
    assert out.count("（") == out.count("）"), "未配对全角括号：%r" % out[:60]


def test_miss_chart_line_no_lone_paren():
    import report
    out = report._miss_chart_line(
        "乌鲁木齐（地窝堡）→上海（虹桥+浦东）", "2026-10-06")
    assert out.count("（") == out.count("）"), "未配对全角括号：%r" % out[:60]


# ---------- P2-2: last_push.md 写实收 text（与落账同源） ----------

class _FakeResp:
    def __init__(self):
        self.text = '{"errcode":0,"errmsg":"ok"}'

    def json(self):
        return {"errcode": 0, "errmsg": "ok"}


class _CapturePost:
    def __call__(self, url, **kw):
        self.payload = kw.get("json")
        return _FakeResp()


def _mk_notifier():
    n = nm.DingTalkNotifier.__new__(nm.DingTalkNotifier)
    n.logger = logging.getLogger("t249")
    n.last_errcode = None
    n._fail_streak = 0
    n._signed_url = lambda: "http://127.0.0.1/fake-webhook"
    return n


def test_last_push_writes_sent_text(monkeypatch, tmp_path):
    """截断轮 last_push.md（取证锚）与实收/push_history 逐字一致。"""
    monkeypatch.chdir(tmp_path)   # send() 向 CWD 落 debug/last_push.md
    cap = _CapturePost()
    monkeypatch.setattr(nm.httpx, "post", cap)
    n = _mk_notifier()
    desp = "a" * 19000   # 触发 18000B 截断
    n.send("t", desp)
    txt = cap.payload["markdown"]["text"]
    with open("debug/last_push.md", encoding="utf-8") as f:
        body = re.sub(r"\A(<!--[^>]*-->\n)+", "", f.read())   # 剥全部头注释行
    assert body == txt, (
        "last_push.md 与实收不一致（截断轮写截断前原文，取证对账失锚）")


# ---------- P2-3: 日报补 7 天趋势行（能力对称三十§3） ----------

def test_trend_bits_str_wording():
    from core.alerter import _trend_bits_str
    hist = [("t0", 1000, 1000, False, False), ("t1", 840, 900, False, False)]
    assert _trend_bits_str(hist) == "直飞 ↓16%｜中转 ↓10%"
    assert _trend_bits_str(
        [("t0", 1000, 1000, 0, 0), ("t1", 999, 1000, 0, 0)]) == "", (
        "<1% 横盘「→0%」是噪音（线上实锤），整段省略")
    assert _trend_bits_str([]) == ""


def test_trend_block_wording():
    from core.alerter import _trend_block
    assert _trend_block("直飞 ↓16%｜中转 ↓3%") == (
        "> 📉 近7天 直飞 ↓16%｜中转 ↓3%\n\n")
    assert _trend_block("直飞 ↑8%") == "> 📈 近7天 直飞 ↑8%\n\n"
    assert _trend_block("") == ""
    assert _trend_block(None) == ""


def test_alerter_trend_line_consumes_single_source():
    """告警 _trend_line 词面组装走单源（函数体内不再手抄 bits 循环）。"""
    with open(ROOT + "/core/alerter.py", encoding="utf-8") as f:
        src = f.read()
    m = src.index("def _trend_line(self, route, date")
    body = src[m:src.index("\n    def ", m + 10)]
    assert "_trend_line_str(" in body, "_trend_line 未消费词面单源"
    assert "bits = []" not in body, "bits 构造仍手抄在 _trend_line（未单源）"


def test_daily_trend_symmetry_pin():
    """日报 build_and_push 消费同款趋势行（词面同源）且落点在走势图前
    （与告警路径 KPI→趋势→图 同序）。"""
    with open(ROOT + "/report.py", encoding="utf-8") as f:
        src = f.read()
    m = src.index("def build_and_push")
    body = src[m:]
    assert "_trend_block(" in body, (
        "日报缺近7天趋势行消费点（能力对称三十§3：告警常驻而日报无同构）")
    assert "_trend_line_str(" in body, "日报趋势词面未走单源"
    assert body.index("_trend_block(") < body.index('desp += f"![走势]('), (
        "趋势行应落走势图之前（与告警 KPI→趋势→图 同序）")
