# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r236_push.py
- tests/test_r244_push.py
- tests/test_r249_push.py
- tests/test_r254_push.py
- tests/test_r257_push.py
- tests/test_r285_push.py
- tests/test_r293_push.py
- tests/test_r304_push_rc_lure.py
- tests/test_r315_push.py
- tests/test_r323_push_pins.py
- tests/test_r329_push.py
- tests/test_v15117_push.py
- tests/test_v15121_push.py
- tests/test_v1589_push.py
- tests/test_v167_push.py
- tests/test_v178_push.py
- tests/test_v199_push.py
- tests/test_v200_push.py
- tests/test_v201_push.py
- tests/test_v225_push.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import core.notifier as nm
import inspect
import json
import logging
import logging as _lg
import os
import pytest
import re
import report
import report as _rep
import report as rep
import sys
import urllib.parse

from core import notifier
from core.alerter import Alerter, _TREND_MISSING_NOTE, _storm_title
from core.models import FlightPrice, Route
from datetime import date, datetime, timedelta
from report import _TBL_TIER_LEGEND, _transfer_layover_line
from types import SimpleNamespace


# ---- merged from tests/test_r236_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _route(ad=1900, at=1700):
    from core.models import Route as _R
    return _R(from_code="SHA", to_code="URC", from_name="上海",
              to_name="乌鲁木齐", dates=["2026-09-25"],
              alert_direct=ad, alert_transfer=at)


def _sect(direct_price, transfer_price=None, name="MU8369"):
    s = {"date": "2026-09-25", "best_direct": None, "best_transfer": None,
         "seen_plats": ["qunar"]}
    if direct_price:
        bd = {"price": direct_price, "name": name,
              "depTime": "19:55", "arrTime": "01:25", "_platform": "qunar"}
        s["best_direct"] = bd
        # top3 池同填（生产 _build_sections 恒填；图挂兜底 _top3_blocks
        # 明细行嵌 name——污染向量真实可达的载体）
        s["top_direct"] = [bd]
        s["top_transfer"] = []
        s["platform_mins"] = {"qunar": direct_price}
        s["plat_top3"] = {"qunar": [bd]}
    if transfer_price:
        s["best_transfer"] = {"price": transfer_price, "name": "CZ6976转",
                              "depTime": "12:05", "arrTime": "23:50",
                              "transCity": "郑州", "_platform": "ctrip"}
    return [s]


def _alerter(sent):
    class FakeN:
        def send(self, t, d="", **kw):
            sent.append((t, d))
            return True

    import logging as _lg
    return Alerter(_lg.getLogger("t236"), notifier=FakeN(), storage=None,
                   digest=True, user="t")


def _img_down(a, monkeypatch):
    """图挂兜底形态（与 test_push_digest_table_fail_fallback 同款）：
    表格图渲染失败走 _top3_blocks 文本兜底，确定性不渲染 PNG。"""
    import report as _rep

    def _boom(*_a, **_k):
        raise RuntimeError("img down")

    monkeypatch.setattr(_rep, "render_flights_table", _boom)
    monkeypatch.setattr(_rep, "upload_freeimage", lambda p, lg=None: "")


BAD = "MU<8369"


def test_digest_hit_branch_desp_sanitized(monkeypatch):
    """达标报告出口：desp 存档前单点消毒——主推与 _send_urgent
    （短信/电话下游）三消费端收到的都是消毒后文本。"""
    sent = []
    urgent = []
    a = _alerter(sent)
    _img_down(a, monkeypatch)
    monkeypatch.setattr(a, "_archive_notify", lambda t, d, **kw: "")
    monkeypatch.setattr(a, "_send_urgent",
                        lambda t, d, hits, launch="": urgent.append((t, d))
                        or True)
    a._push_digest(_route(), _sect(1750, None, name=BAD))
    assert sent, "达标轮主推丢失"
    for _t, _d in sent:
        assert "<" not in _d and "＜" not in _d and "…" not in _d, _d[:300]
    for _t, _d in urgent:
        assert "<" not in _d and "＜" not in _d and "…" not in _d, _d[:300]
    assert any("MU8369" in _d for _t, _d in sent), "消毒不得误伤正常词面"


def test_digest_heartbeat_tail_desp_sanitized(monkeypatch):
    """未达标心跳尾出口：send 点包裹消毒（简报 desp 同嵌 name）。"""
    sent = []
    a = _alerter(sent)
    _img_down(a, monkeypatch)
    monkeypatch.setattr(a, "_heartbeat_gate", lambda: True)
    a._push_digest(_route(), _sect(1950, None, name=BAD))
    assert sent, "心跳简报未发出"
    for _t, _d in sent:
        assert "<" not in _d and "＜" not in _d and "…" not in _d, _d[:300]


# ---- merged from tests/test_r244_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _m(t):
    return len(t)


# ---- _summary_lines：消费契约钉 ----

def test_lines_all_fit_no_tail():
    """全容：单行装下全部 bits，无尾注。"""
    out = _rep._summary_lines(_m, ["aaaa"] * 8, 100000)
    assert len(out) == 1 and "等" not in out[0], out


def test_lines_overflow_tail_merged():
    """超容并入形：4 宽位 25 条预算 45 → 3 行×6 条（39）余 7，
    尾注「 ｜ 等7条」恰 45 并回尾行；渲染段=前 18 条原序。"""
    bits = ["b%02dx" % i for i in range(25)]
    out = _rep._summary_lines(_m, bits, 45)
    assert len(out) == 3, out
    assert out[-1].endswith("等7条"), out
    got = out[0].split(" ｜ ") + out[1].split(" ｜ ") \
        + out[2].split(" ｜ ")[:-1]
    assert got == bits[:18], (got, bits[:18])


def test_lines_overflow_tail_own_line():
    """超容独立形：尾注并回超预算（5 宽位行恰满 45，+尾注 51>45）
    → 尾注独立成行，尾注行被调用端渲染不参与切片。"""
    out = _rep._summary_lines(_m, ["aaaaa"] * 25, 45)
    assert out[-1] == "等7条", out
    assert len(out) == 4, out
    got = [s for ln in out[:3] for s in ln.split(" ｜ ")]
    assert got == ["aaaaa"] * 18, got


def test_lines_empty_items():
    """空 items → 无行（调用端 elif 分支语义不变）。"""
    assert _rep._summary_lines(_m, [], 880) == []


def test_lines_max_three_lines_cap():
    """数据行上限 3（尾注行是额外落点不计入）：溢出位全部进尾注
    计数——接受丢弃但留痕，渲染+尾注计数守恒。"""
    bits = ["b%02dx" % i for i in range(40)]
    out = _rep._summary_lines(_m, bits, 45)
    assert out[-1] == "等22条", out                 # 尾注独立成行
    assert len(out) == 4 and len(out[:-1]) <= 3, out  # 数据行 ≤3
    n_rendered = sum(len(ln.split(" ｜ ")) for ln in out[:-1])
    assert n_rendered + 22 == len(bits), (n_rendered, out)


# ---- 结构钉：join 恒纯 + 两路单源 ----

def test_summary_join_stays_pure():
    """join 函数体（docstring 剔除）禁出现「等」标记逻辑（r244 P0
    判例锁面：标记混入 join 即污染按分隔符切片的调用端）。"""
    import ast
    tree = ast.parse(inspect.getsource(_rep._summary_join))
    fn = tree.body[0]
    body = fn.body
    if body and isinstance(body[0], ast.Expr) \
            and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    code = ast.unparse(ast.Module(body=body, type_ignores=[]))
    assert "等" not in code, "标记混入 _summary_join"


def test_summary_lines_single_source_wiring():
    """summary/ops 两路必须同走 _summary_lines 单源（定义+2 调用点）。"""
    src = open(_rep.__file__, encoding="utf-8").read()
    assert src.count("_summary_lines(") >= 3, \
        "summary/ops 未同走单源 helper"


# ---- merged from tests/test_r249_push.py ----

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
    # 走势图发射点（r297 R1 起为 _tseg 单点：url 在场=图、缺席=留痕行，
    # 两态同点发射）——钉语义不变：趋势行落位在走势发射之前
    assert 'sec.append(_tseg)' in body, "走势发射点未收 _tseg 单点"
    assert body.index("_trend_block(") < body.index("sec.append(_tseg)"), (
        "趋势行应落走势图之前（与告警 KPI→趋势→图 同序）")


# ---- merged from tests/test_r254_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_upload_ghimg_display_url_quoted(monkeypatch, tmp_path):
    """显示 URL path 段百分号编码：CJK 租户段不再裸拼；PUT 路径保留
    原文（Contents API 未编码路径）。"""
    captured = {}

    class _R:
        status_code = 201
        text = ""

    def fake_put(url, **kw):
        captured["put_url"] = url
        return _R()

    monkeypatch.setattr(report.httpx, "put", fake_put)
    png = tmp_path / "trend_邓美銮_URC_SHA_2026-10-15.png"
    png.write_bytes(b"\x89PNG fake")
    url = report.upload_ghimg(str(png), {"repo": "o/r", "token": "t"},
                              logging.getLogger("t"))
    assert url, "上传应成功返回显示 URL"
    assert not any("\u4e00" <= ch <= "\u9fff" for ch in url), \
        f"显示 URL 仍含裸 CJK: {url}"
    assert "%E9" in url, f"CJK 段未百分号编码: {url}"
    assert "/charts/" in captured["put_url"]
    # PUT 路径保留原文（不 quote）
    assert "trend_邓美銮_URC_SHA_2026-10-15_" in captured["put_url"]


def test_dingtalk_send_prod_gate_blocks_side_scripts(monkeypatch):
    """非生产形态进程未设重定向变量时，真实域名发送被资格门拒绝
    （返回 False 不发请求）；显式重定向变量放行（压测打桩路径）。"""
    from core import notifier
    from core.notifier import DingTalkNotifier
    sent = {}

    def fake_post(url, **kw):
        sent["url"] = url

        class _R:
            status_code = 200
            text = '{"errcode":0,"errmsg":"ok"}'

            def json(self):
                return {"errcode": 0}

        return _R()

    monkeypatch.setattr(notifier.httpx, "post", fake_post)
    monkeypatch.setattr(notifier, "_prod_ledger_allowed", lambda: False)
    # 旁路形态：无重定向变量 → 拒发（conftest autouse 放行的会话态
    # 由 delenv 显式摘除，monkeypatch LIFO 测试结束自恢复）
    monkeypatch.delenv("DING_WEBHOOK_ALLOW", raising=False)
    dt = DingTalkNotifier(
        "https://oapi.dingtalk.com/robot/send?access_token=real",
        logging.getLogger("t"))
    ok = dt.send("t", "d")
    assert ok is False
    assert "url" not in sent, "资格门应拦住真实发送"
    # 显式重定向（测试 webhook 声明）→ 放行
    monkeypatch.setenv("DING_WEBHOOK_ALLOW", "1")
    ok2 = dt.send("t", "d")
    assert ok2 is True
    assert "oapi.dingtalk.com" in sent["url"]


def test_dingtalk_send_prod_gate_allows_prod_process(monkeypatch):
    """生产形态进程（exe/main.py/webui.py 入口）不受门影响。"""
    from core import notifier
    from core.notifier import DingTalkNotifier
    sent = {}

    def fake_post(url, **kw):
        sent["url"] = url

        class _R:
            status_code = 200
            text = '{"errcode":0}'

            def json(self):
                return {"errcode": 0}

        return _R()

    monkeypatch.setattr(notifier.httpx, "post", fake_post)
    monkeypatch.setattr(notifier, "_prod_ledger_allowed", lambda: True)
    monkeypatch.delenv("DING_WEBHOOK_ALLOW", raising=False)
    dt = DingTalkNotifier(
        "https://oapi.dingtalk.com/robot/send?access_token=real",
        logging.getLogger("t"))
    assert dt.send("t", "d") is True
    assert "oapi.dingtalk.com" in sent["url"]


def test_dingtalk_send_gate_spares_stub_endpoints(monkeypatch):
    """非真实域名（本地打桩/假端点）不受门限制——单测 fake 与压测
    打桩路径零感知。"""
    from core import notifier
    from core.notifier import DingTalkNotifier
    sent = {}

    def fake_post(url, **kw):
        sent["url"] = url

        class _R:
            status_code = 200
            text = '{"errcode":0}'

            def json(self):
                return {"errcode": 0}

        return _R()

    monkeypatch.setattr(notifier.httpx, "post", fake_post)
    monkeypatch.setattr(notifier, "_prod_ledger_allowed", lambda: False)
    monkeypatch.delenv("DING_WEBHOOK_ALLOW", raising=False)
    dt = DingTalkNotifier("http://127.0.0.1:9/mock/robot",
                          logging.getLogger("t"))
    assert dt.send("t", "d") is True
    assert "127.0.0.1:9" in sent["url"]


def test_dingtalk_send_gate_rejects_zero_flag(monkeypatch):
    """严格判钉（Soldier Minor-1）：DING_WEBHOOK_ALLOW 取值「0」必须
    与「未设」同拒——门写松成 truthy 判断（设了就放行）时本钉变红。
    delenv 形态的既有钉抓不住该变异（无变量两态同假）。"""
    from core import notifier
    from core.notifier import DingTalkNotifier
    sent = {}

    def fake_post(url, **kw):
        sent["url"] = url

        class _R:
            status_code = 200
            text = '{"errcode":0}'

            def json(self):
                return {"errcode": 0}

        return _R()

    monkeypatch.setattr(notifier.httpx, "post", fake_post)
    monkeypatch.setattr(notifier, "_prod_ledger_allowed", lambda: False)
    monkeypatch.setenv("DING_WEBHOOK_ALLOW", "0")
    dt = DingTalkNotifier(
        "https://oapi.dingtalk.com/robot/send?access_token=real",
        logging.getLogger("t"))
    assert dt.send("t", "d") is False
    assert "url" not in sent, "ALLOW=0 应与未设同拒，不得放行真实域名"


def test_local_push_image_roundtrip_quoted_url(monkeypatch, tmp_path):
    """推-1 往返钉（Soldier P1-1）：quote 后的图 URL 尾段必须仍能
    反推本地渲染图——邮件通道 _local_push_image 按尾段**原文**拼
    data/{stem}.png，编码后反推恒 miss、回落高失败率网络下载；
    unquote 对存量裸 CJK 与 ASCII 茎双态 no-op。"""
    import urllib.parse as _up
    from core import notifier
    monkeypatch.chdir(tmp_path)
    stem = "trend_邓美銮_URC_SHA_2026-10-15"
    img = tmp_path / "data" / (stem + ".png")
    img.parent.mkdir()
    img.write_bytes(b"\x89PNG fake")
    path = f"charts/20261007/{stem}_030938.png"
    url = "https://cdn.jsdelivr.net/gh/o/r@main/" + _up.quote(path, safe=":/@")
    assert "%E9" in url
    assert notifier._local_push_image(url) == b"\x89PNG fake"


# ---- merged from tests/test_r257_push.py ----

sys.path.insert(0, __import__("os").path.dirname(
    __import__("os").path.dirname(__import__("os").path.abspath(__file__))))

_DATE = "2026-09-25"
_ROUTES = [
    {"from": "SHA", "to": "URC", "from_name": "上海",
     "to_name": "乌鲁木齐", "dates": [_DATE],
     "alert_direct": 2000, "alert_transfer": 1800,
     "transfer_arrival_max": "02:00"},
]
_ZD_ROUTES = _ROUTES + [
    {"from": "SHA", "to": "SYN", "from_name": "上海",
     "to_name": "三亚", "dates": [_DATE],
     "alert_direct": 1600, "alert_transfer": 0,
     "transfer_arrival_max": "02:00"},
]


def _cfg(routes):
    return {"notifier": {"image_host": {"provider": "freeimage"}},
            "users": [{"name": "u", "routes": routes,
                       "platforms": ["qunar", "ctrip"],
                       "notifier": {"image_host": {"provider": "freeimage"}}}]}


class FakeN:
    def __init__(self):
        self.sent = {}

    def send(self, title, desp="", **kw):
        self.sent["title"], self.sent["desp"] = title, desp
        return True


def _strip_images(desp):
    return re.sub(r"!\[[^\]]*\]\([^)]*\)", "", desp)


@pytest.fixture()
def env(monkeypatch):
    """build_and_push 离线夹具：图床/渲染/明细查询全部桩化，
    _rounds 按 (from,to) 分派（三亚=零数据，上海→乌鲁木齐=旧代
    3 位低价样本供 p7 参照回算）。"""
    import report as rep
    seen = {"rounds": []}

    def _rounds(db, fc, tc, d, am, **kw):
        seen["rounds"].append((fc, tc, d))
        if (fc, tc) == ("SHA", "SYN"):
            return []
        return [(datetime(2026, 9, 20, 8, 0), 576.0, None)]

    monkeypatch.setattr(rep, "_rounds", _rounds)
    monkeypatch.setattr(rep, "prepare_round_charts",
                        lambda c, lg, *a, **k: {("SHA", "URC", _DATE):
                                                "http://x/t.png"})
    monkeypatch.setattr(rep, "render_flights_table", lambda *a, **k: None)
    monkeypatch.setattr(rep, "upload_freeimage",
                        lambda p, lg: "http://x/f.png")
    return {"rep": rep, "seen": seen}


def test_daily_no_data_route_reconciled(env, monkeypatch):
    """P-1：全窗零数据航线补对账行（能力对称）——航线名与
    「近48时无数据」词面在 desp 留痕，不再无声消失。"""
    rep = env["rep"]
    monkeypatch.setattr(
        rep, "_route_latest_flights",
        lambda db, fc, tc, d, **kw: (
            [{"price": 2690, "transCity": "", "_platform": "qunar"}]
            if (fc, tc) == ("SHA", "URC") else []))
    n = FakeN()
    ok = rep.build_and_push(_cfg(_ZD_ROUTES), _lg.getLogger("t"), n, user="u")
    assert ok and n.sent["desp"]
    d = n.sent["desp"]
    assert "近48时无数据" in d, d
    assert "上海→三亚" in d, "零数据航线名应在对账行留痕：" + d


def test_daily_empty_pool_jump_link_fallback(env, monkeypatch):
    """P-2：空池轮 desp 剥图后仍有一个可点查价入口（单源
    _ensure_jump_link 消费；告警链同款兜底）。"""
    rep = env["rep"]
    monkeypatch.setattr(rep, "_route_latest_flights",
                        lambda db, fc, tc, d, **kw: [])
    n = FakeN()
    ok = rep.build_and_push(_cfg(_ROUTES), _lg.getLogger("t"), n, user="u")
    assert ok and n.sent["desp"]
    stripped = _strip_images(n.sent["desp"])
    assert "](http" in stripped, "剥图后零可点链接：" + stripped
    assert "[→ 打开" in stripped, stripped


def test_empty_pool_p7_compact_tier_lands(env, monkeypatch):
    """（r258-P2-1 改写）空池补偿的近 7 天参照真实落行：独立引用行长形
    「> 近7天直飞最低 ￥N（MM/DD HH:MM）」全价位带恒落位——旧「同行
    拼接+紧凑档」形态产「无渠道明细7天最低￥N」连读病句、参照时刻被裁，
    已由独立引用行形态退役（钉面随行为演进改写，参照落行语义担保不变）。"""
    rep = env["rep"]
    monkeypatch.setattr(rep, "_route_latest_flights",
                        lambda db, fc, tc, d, **kw: [])
    n = FakeN()
    ok = rep.build_and_push(_cfg(_ROUTES), _lg.getLogger("t"), n, user="u")
    assert ok and n.sent["desp"]
    d = n.sent["desp"]
    line = [ln for ln in d.splitlines() if "无渠道明细" in ln]
    assert line, d
    assert "7天最低" not in line[0] and "近7天" not in line[0], line[0]
    ref = [ln for ln in d.splitlines() if "近7天直飞最低" in ln]
    assert ref and "￥576" in ref[0], d
    assert rep._dw_line(ref[0]) <= 40, ref[0]
    # 5 位价位带（主价位带上沿）：独立长形恒可落，不塌地板
    monkeypatch.setattr(
        rep, "_rounds",
        lambda db, fc, tc, dd, am, **kw: (
            [] if (fc, tc) == ("SHA", "SYN")
            else [(datetime(2026, 9, 20, 8, 0), 12650.0, None)]))
    n2 = FakeN()
    ok2 = rep.build_and_push(_cfg(_ROUTES), _lg.getLogger("t"), n2, user="u")
    assert ok2
    d2 = n2.sent["desp"]
    ref2 = [ln for ln in d2.splitlines() if "近7天直飞最低" in ln]
    assert ref2 and "￥12650" in ref2[0], "5 位价补偿参照塌地板：" + d2
    assert rep._dw_line(ref2[0]) <= 40, ref2[0]


def test_daily_jump_link_skips_empty_dates_route(env, monkeypatch):
    """兜底锚选取谓词必须滤空 dates 航线：首条启用航线 dates=[] 时
    选取即命中、dates 检查在其后——整篇日报零兜底链接（后随航线
    的 dates 在场也救不回）。谓词内联滤空 dates 后取首条可锚航线。"""
    rep = env["rep"]
    monkeypatch.setattr(rep, "_route_latest_flights",
                        lambda db, fc, tc, d, **kw: [])
    no_dates = {"from": "SHA", "to": "SYN", "from_name": "上海",
                "to_name": "三亚", "dates": [],
                "alert_direct": 1600, "alert_transfer": 0,
                "transfer_arrival_max": "02:00"}
    n = FakeN()
    ok = rep.build_and_push(_cfg([no_dates] + _ROUTES),
                            _lg.getLogger("t"), n, user="u")
    assert ok and n.sent["desp"]
    stripped = _strip_images(n.sent["desp"])
    assert "](http" in stripped, "首航线 dates=[] 曾让整篇零兜底链接：" + stripped


# ---- 备案② bare 档半截码（token 边界律投影） ----

def test_flight_line_bare_cut_at_code_token_boundary():
    """bare 地板档逐字截截进字母数字段=半截码（「川航3U8」形，真函数
    网格实证三形态；三十一§2 token 边界律投影）——截点落码段中时整
    token 回退（丢整段码优于半截噪音，价格+时刻+跨天地板恒落位）。"""
    from core.alerter import Alerter, _disp_dw
    f = {"price": 9876, "name": "川航3U8863", "code": "川航3U8863",
         "depTime": "17:55", "arrTime": "18:50", "crossDayDesc": "+1天",
         "_platform": "qunar", "transCity": "郑州", "layoverT": "2:05"}
    line = Alerter._fmt_flight_line(f, 1)
    assert "川航3U8" not in line, "半截码在场：" + line
    assert "川航" in line, "CJK 名前缀随整 token 回退丢失：" + line
    assert "￥9876" in line and "17:55→18:50" in line and "+1天" in line, line
    assert _disp_dw(line) <= 40, line
    # 全字母数字码（裸航班号行）：码要么完整在、要么整 absent——
    # 无半截第三形态（放得下时全码照常在，子串断言不成立）
    f2 = dict(f, name="3U8863", code="3U8863")
    line2 = Alerter._fmt_flight_line(f2, 1)
    assert "3U8863 17:55" in line2 or "￥9876 17:55" in line2, \
        "半截码形态：" + line2
    assert _disp_dw(line2) <= 40, line2


# ---- 备案③ 日报图挂兜底容量对齐（[:3]→[:5]，与告警 _top3_blocks 同量） ----

def test_daily_fallback_top5_capacity_aligned():
    """日报图挂文本兜底两池各取 5 行——v15133 立项语义=TOP5（与告警
    路径 _top3_blocks[:5] 能力对称），实现曾 [:3] 漂移。"""
    from report import _daily_top_fallback
    pool = [{"price": 1000 + k, "name": "南航CZ697%d" % k,
             "code": "CZ697%d" % k, "depTime": "10:00", "arrTime": "15:00",
             "_platform": "qunar", "transCity": ""} for k in range(6)]
    out = _daily_top_fallback(pool, [])
    assert out.count("CZ697") == 5, "兜底容量应=5（告警侧同量）：" + out


# ---- merged from tests/test_r285_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _al():
    from core.alerter import Alerter
    return Alerter(logging.getLogger("r285"), storage=None)


def _disp_dw(s):
    from core import alerter as _a
    return _a._disp_dw(s)


# ---- T1 P2-1 bare_mk 收域到 ∈hits ----

def _fire_base(**kw):
    f = {"name": "海航｜海南航空HU7815", "code": "HU7815", "price": 1595,
         "depTime": "19:55", "arrTime": "01:25", "crossDayDesc": "+1天",
         "_platform": "qunar"}
    f.update(kw)
    return f


class TestBareMkScopedToHits:
    """bare_mk 保码剥跨天档的启用域=「该行 ∈ hits」（hits 区 seg 行
    承载时刻+跨天）；非命中 🔥 行跨天恒保到地板。"""

    def test_non_hit_fire_row_keeps_cross(self):
        """TOP5 次优达标 🔥 行（非 hits）：跨天恒保（消息内无第二承载
        位——旧形态剥掉=误判当日达破口）。码在病理宽度下整码丢弃是
        既定地板语义（三十一§2，r257 钉面），本钉锁跨天恒保与无半截。"""
        ln = _al()._fmt_flight_line(_fire_base(), 2, "🔥 ")
        assert "+1天" in ln, ln
        assert _disp_dw(ln) <= 40, ln

    def test_hit_fire_row_keeps_code_drops_cross(self):
        """∈hits 的 🔥 行：hits 区 seg 行承载时刻+跨天，保码剥跨天
        语义保持（r283 P2-1 立项语义收域后不变）。"""
        ln = _al()._fmt_flight_line(_fire_base(), 1, "🔥 ", in_hits=True)
        assert "HU7815" in ln, ln
        assert "+1天" not in ln, ln
        assert _disp_dw(ln) <= 40, ln

    def test_non_hit_wide_name_cross_floor_and_no_half_code(self):
        """病理宽名非命中 🔥 行：跨天恒保到地板 + 无半截码（三十一§2）
        + 预算恒达标——跨天保全不得靠超宽实现。"""
        ln = _al()._fmt_flight_line(
            _fire_base(name="川航3U8863", code="川航3U8863", price=9876),
            2, "🔥 ")
        assert "+1天" in ln, ln
        assert _disp_dw(ln) <= 40, ln

    def test_top3_blocks_scopes_bare_mk_to_best_only(self):
        """接线行为钉：_top3_blocks 对 best（∈hits）传 in_hits=True、
        次优 🔥 行不传——同消息内两行分工：best 行码保跨天让位
        （hits 区 seg 承载）、次优行跨天恒保。"""
        a = _al()
        route = SimpleNamespace(
            from_code="SHA", to_code="URC", from_name="上海",
            to_name="乌鲁木齐", alert_direct=1700, alert_transfer=0,
            transfer_baggage="", transfer_arrival_max="02:00",
            dep_time_min="", dep_time_max="")
        best = _fire_base(price=1600, name="海航HU7815",
                          depTime="21:10", arrTime="02:35")
        second = _fire_base(price=1650, name="国航CA1295", code="CA1295",
                            depTime="19:55", arrTime="01:25")
        s = {"date": "2026-10-27", "best_direct": best,
             "top_direct": [best, second], "best_transfer": None,
             "top_transfer": [], "seen_plats": ["qunar"],
             "all_flights": [best, second]}
        desp = a._top3_blocks(route, [s])
        b_line = [l for l in desp.split("\n\n") if "HU7815" in l]
        s_line = [l for l in desp.split("\n\n") if "19:55" in l]
        assert b_line and s_line, desp
        # best ∈ hits：hits 区 seg 行承载跨天，TOP3 行保码剥跨天
        assert "+1天" not in b_line[0], b_line[0]
        # 次优 🔥 行不在 hits：跨天恒保（修复断言）
        assert "+1天" in s_line[0], s_line[0]


# ---- T2 P2-2 档序对齐（经X 不先于停X 丢） ----

def _transfer_base(**kw):
    f = {"price": 870, "name": "南航CZ6949/HO1108",
         "code": "CZ6949/HO1108", "depTime": "08:30", "arrTime": "20:00",
         "crossDayDesc": "", "transCity": "郑州", "layoverT": "2:05",
         "totalDuration": "11时30分", "_platform": "ctrip"}
    f.update(kw)
    return f


class TestViaOrderAlignedWithSegChain:
    """停多久必配经哪（配对不变量）：任何降级档输出行含「 停」⟹
    含经郑州——seg 链档序（丢停留时长→丢经停城市→保时刻跨天）投影
    到 TOP3 行降级链。"""

    @pytest.mark.parametrize("name", [
        "MU6716",
        "南航CZ6949",
        "南航CZ6949/HO1108",
        "海南航空｜金鹏航空Y87519",
        "中国联合航空KN5977｜中联航KN5977超长双名形态",
    ])
    @pytest.mark.parametrize("cross,lay", [("", "2:05"),
                                           ("+1天", "2:05"),
                                           ("+1天", "22:55")])
    def test_stop_always_paired_with_via(self, name, cross, lay):
        ln = _al()._fmt_flight_line(
            _transfer_base(name=name, code=name, crossDayDesc=cross,
                           layoverT=lay), 1)
        assert _disp_dw(ln) <= 40, ln
        if " 停" in ln:
            assert "经郑州" in ln, f"裸停无城市（不知停哪）：{ln!r}"
        if cross:
            assert cross in ln, f"跨天恒保到地板：{ln!r}"

    def test_stop_never_naked_in_deep_band(self):
        """深降级带不产「裸停」（停X 无经X 配对）——旧 slim3 带
        「…20:00 停2:05（携程）」形态（城市先于时长被丢，兜底区只见
        停多久不知停哪）翻案；40 半角下经X+停X+渠道同框本属稀有，
        实效锁语义：停X 或与经X 同框、或整段让位。"""
        a = _al()
        f = _transfer_base(name="南航CZ6949", code="CZ6949")
        ln = a._fmt_flight_line(f, 1)
        assert _disp_dw(ln) <= 40, ln
        assert " 停" not in ln or "经郑州" in ln, ln

    def test_long_name_band_keeps_via_after_stop_dropped(self):
        """骨架/地板带（名字段让位后）：经X 仍在（舍停先于舍经，
        城市辨识不先于时长量化被丢）。"""
        a = _al()
        f = _transfer_base(name="海南航空｜金鹏航空Y87519双名长形态",
                           code="Y87519")
        ln = a._fmt_flight_line(f, 1)
        assert "Y87519" in ln and "经郑州" in ln, ln
        assert _disp_dw(ln) <= 40, ln

    def test_bare_drops_stop_before_via(self):
        """bare 档超宽：先舍停X（时长量化）保经X（城市辨识）——
        seg 链同律；经X 只在码放不下时最后让位，跨天恒保。"""
        a = _al()
        f = _transfer_base(name="中国联合航空KN5977｜中联航KN5977长双名",
                           code="KN5977/KN1234", crossDayDesc="+1天",
                           layoverT="2:05")
        ln = a._fmt_flight_line(f, 1)
        assert _disp_dw(ln) <= 40, ln
        assert "+1天" in ln, f"跨天恒保：{ln!r}"


# ---- T3 P3-1 降级 mini 行挂航线短名 ----

class TestMiniRouteTag:
    """整节降级替身语境（minis 顶替全节文本）：mini 行头部带航线短名
    「📍 广→乌 10/27」——离链辨识归属；节内第 2+ 日期语境（默认）
    不带（上方 #### 标题托底，常态不加状态标识律）。"""

    def _payload_many_routes(self):
        """多航线把节预算吃爆，触发整节降级替身（minis 顶替全节）。"""
        a = _al()
        from core.models import Route as _R
        cities = [("广州", "乌海", "CAN", "WUA"),
                  ("上海", "乌鲁木齐", "SHA", "URC"),
                  ("北京", "西安", "BJS", "SIA"),
                  ("成都", "杭州", "CTU", "HGH"),
                  ("深圳", "昆明", "SZX", "KMG"),
                  ("重庆", "南京", "CKG", "NKG"),
                  ("武汉", "青岛", "WUH", "TAO"),
                  ("长沙", "厦门", "CSX", "XMN"),
                  ("南京", "兰州", "NKG", "LHW"),
                  ("天津", "贵阳", "TSN", "KWE"),
                  ("合肥", "宁波", "HFE", "NGB"),
                  ("郑州", "海口", "CGO", "HAK"),
                  ("济南", "大连", "TNA", "DLC"),
                  ("太原", "南宁", "TYN", "NNG"),
                  ("南昌", "石家庄", "KHN", "SJW"),
                  ("长春", "银川", "CGQ", "INC"),
                  ("哈尔滨", "西宁", "HRB", "XNN"),
                  ("沈阳", "拉萨", "SHE", "LXA"),
                  ("呼和浩特", "桂林", "HET", "KWL"),
                  ("无锡", "丽江", "WUX", "LJG"),
                  ("烟台", "佛山", "YNT", "FUO"),
                  ("温州", "包头", "WNZ", "BAV"),
                  ("珠海", "洛阳", "ZUH", "LYA"),
                  ("泉州", "榆林", "JJN", "UYN")]
        rs = []
        # r318 心跳轻量化随迁：整节降级替身的载体在达标/回落轮（未达标
        # 轮 desp 压缩为单行 KPI 摘要恒低于预算，无降级面）——夹具改
        # 达标价（1650+k ≤ 1700+k 线）触发全量小节的预算竞争，钉面
        # 语义不变
        for k, (fn, tn, fc, tc) in enumerate(cities):
            r = _R(from_code=fc, to_code=tc, from_name=fn, to_name=tn,
                   dates=["2026-10-27", "2026-10-28"],
                   alert_direct=1700 + k, alert_transfer=1500 + k)

            def _sec(date, dp):
                return {"date": date,
                        "best_direct": {"price": dp, "name": "CZ3341",
                                        "depTime": "08:00",
                                        "arrTime": "11:20",
                                        "_platform": "qunar"},
                        "best_transfer": None, "seen_plats": ["qunar"]}

            rs.append((r, [_sec("2026-10-27", 1650 + k),
                           _sec("2026-10-28", 1655 + k)]))
        return a._digest_payload(rs, fresh=True,
                                 with_tables=False, with_charts=False)

    def test_demoted_mini_rows_carry_route_tag(self):
        import re as _re
        p = self._payload_many_routes()
        d = p["desp"]
        # r318 心跳轻量化随迁：达标多航线轮的预算让位由 hits 行区
        # 主导（sec 节超共享池转 mini 替身）——降级说明行走
        # hit_demoted 态 mid 档「命中行仅价格」；「仅列关键价」full
        # 档的可达面（未达标全量小节降级）已随轻量化退役
        assert "航线较多" in d, "夹具未触发降级，先修夹具"
        # 降级替身与命中行带航线短名——离链可辨识；前段完整节走全名
        # 标题不降级。断言按「📍 短名 日期」模式计数，不锚具体航线
        # （预算边界上最末节可能整体让位静默消失）
        tagged = _re.findall(r"📍 .→. \d{2}/\d{2}", d)
        assert len(tagged) >= 4, f"带航线短名的降级 mini 行不足: {tagged!r}"

    def test_in_section_mini_rows_untagged(self):
        """节内第 2+ 日期语境：mini 行不带航线短名（标题托底）——
        旧行为零变化。
        r318 随迁：📍 日期标签载体在全量小节，夹具改达标轮。"""
        a = _al()
        from core.models import Route as _R
        r = _R(from_code="CAN", to_code="WUA", from_name="广州",
               to_name="乌海", dates=["2026-10-27", "2026-10-28"],
               alert_direct=1900, alert_transfer=1700)

        def _sec(date, dp):
            return {"date": date,
                    "best_direct": {"price": dp, "name": "CZ3341",
                                    "depTime": "08:00", "arrTime": "11:20",
                                    "_platform": "qunar"},
                    "best_transfer": None, "seen_plats": ["qunar"]}

        p = a._digest_payload(
            [(r, [_sec("2026-10-27", 1800), _sec("2026-10-28", 1820)])],
            fresh=True, with_tables=False, with_charts=False)
        d = p["desp"]
        assert "📍 10/28" in d, d
        assert "📍 广→乌" not in d, d


# ---- T4 P3-2 日报兜底补渠道最低段 ----

class TestDailyMarketFallback:
    def test_lines_shape_and_budget(self):
        from report import _daily_market_fallback
        out = _daily_market_fallback(
            {"qunar": (1660.0, True), "ctrip": (1700.0, True),
             "fliggy": (1710.0, True)})
        assert "- 去哪儿 最低 ￥1660" in out, out
        assert "- 携程 最低 ￥1700" in out, out
        assert "- 飞猪 最低 ￥1710" in out, out
        for ln in out.strip().split("\n\n"):
            assert _disp_dw(ln) <= 40, ln

    def test_empty_pmins_silent(self):
        from report import _daily_market_fallback
        assert _daily_market_fallback({}) == ""

    def test_wired_into_both_daily_fallback_branches(self):
        """两个图挂兜底分支（上传失败/渲染异常）同接 _daily_market_
        fallback——能力对称收编不许只落一条路径（三十§3）。"""
        src = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "report.py"),
            encoding="utf-8").read()
        assert src.count("_daily_market_fallback(") >= 3, \
            "定义+两个兜底分支接线不足"


# ---- T5 P3-4 预览注插入 @ 段之前 ----

def test_preview_note_before_at_segment():
    """预览注改走 _append_before_at 同律：@ 恒为消息末行不变量在
    预览器不破例（r283 P3-4 源码钉随形态改写：前导 \n\n 改由
    _append_before_at 单源承担）。"""
    src = webui_full_src()
    assert 'p["desp"], "> （预览态无明细总表图' in src, \
        "预览注未走 @ 前插单源"
    assert "_append_before_at(" in src, "单源调用缺席"


# ---- merged from tests/test_r293_push.py ----

def _lum(rgb):
    def _c(c):
        c /= 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (_c(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _ratio(fg, bg):
    lf, lb = _lum(fg), _lum(bg)
    hi, lo = max(lf, lb), min(lf, lb)
    return (hi + 0.05) / (lo + 0.05)


def _qual_row_bg():
    """达标行底色真值：从 report.py 源码正则提取（qual 分支整行
    rectangle 的 fill 字面量），不硬编码——调色日钉随新值复算。"""
    src = inspect.getsourcefile(report)
    with open(src, "rb") as fh:
        text = fh.read().decode("utf-8", errors="ignore")
    # 行尾归一：Windows autocrlf 工作树是 CRLF，钉锁字面量形态不锁
    # 换行表示（否则新鲜 clone 恒红而 CI 恒绿=环境脆弱钉）
    text = text.replace("\r\n", "\n")
    m = re.search(
        r"fill=\((\d+),\s*(\d+),\s*(\d+)\)\)\n\s*elif alt % 2:", text)
    assert m, "达标行底字面量形态迁移（qual rectangle 正则失配，钉需随形态改写）"
    return tuple(int(x) for x in m.groups())


def test_qual_row_price_contrast_aa():
    """P3-1 主钉：达标价绿 × 达标行底 ≥4.5（红态=4.47 贴线）。"""
    bg = _qual_row_bg()
    r = _ratio(report.C_QUAL, bg)
    assert r >= 4.5, "达标价绿 × 达标行底 %s = %.2f:1 <4.5（AA 正文档）" \
        % (bg, r)


def test_table_color_pairs_aa():
    """总表图「文字色 × 实际衬底」真实可达集合 ≥4.5（防调色日回归：
    任何一色一底改动，本钉按公式当场复算）。价格/正文/次级/警示四族
    覆盖白卡/斑马/达标行底/表头/摘要条五个真实衬底；类别胶囊四对
    （达标行绿字走 C_OK_TXT 专档——C_QUAL 对胶囊浅底 4.28/4.43 欠
    AA 的同族病 webui --ok-txt 已修，PNG 侧同值对齐；非达标行蓝字/
    深橙字两对现状过线在守）。不含生产不可达组合（达标行价格恒
    C_QUAL——_tier_of 对 qual 短路，PRICE_PLAIN×达标行底是死对）。"""
    D = report.DESIGN
    qual_bg = _qual_row_bg()
    # 达标行类别胶囊文字专档：与 webui --ok-txt 同值同注释（双端律）
    assert getattr(report, "C_OK_TXT", None) == (11, 110, 57), \
        "C_OK_TXT 缺席或漂移（webui --ok-txt #0b6e39 双端同值）"
    src = open(inspect.getsourcefile(report), encoding="utf-8").read()
    assert "cap_tx = (C_OK_TXT if qual" in src, \
        "达标行类别胶囊文字未走 C_OK_TXT 专档（欠 AA 复活）"
    pairs = [
        # (前景, 衬底, 语义)
        (report.C_QUAL, D.CARD, "达标绿×白卡"),
        (report.C_QUAL, D.ROW_ALT, "达标绿×斑马"),
        (report.C_OK_TXT, D.CAP_DIRECT_BG, "胶囊绿字×直飞胶囊底"),
        (report.C_OK_TXT, D.CAP_TRANSFER_BG, "胶囊绿字×中转胶囊底"),
        (report.C_DIRECT, D.CAP_DIRECT_BG, "胶囊蓝字×直飞胶囊底"),
        (report.C_TRANSFER_TX, D.CAP_TRANSFER_BG, "胶囊橙字×中转胶囊底"),
        (report.C_NEAR, D.CARD, "擦边琥珀×白卡"),
        (report.C_NEAR, D.ROW_ALT, "擦边琥珀×斑马"),
        (report.C_CMP, D.CARD, "比价红×白卡"),
        (D.PRICE_PLAIN, D.CARD, "非达标蓝×白卡"),
        (D.PRICE_PLAIN, D.ROW_ALT, "非达标蓝×斑马"),
        (D.MUTED, D.CARD, "弱化灰×白卡"),
        (D.MUTED, D.ROW_ALT, "弱化灰×斑马"),
        (D.MUTED, qual_bg, "弱化灰×达标行底"),
        (D.SUMMARY_TX, D.SUMMARY_BG, "摘要正文×摘要底"),
        (D.HEAD_TX, D.HEAD_BG, "表头字×表头底"),
        (D.CHAIN_TX, D.CARD, "渠道链×白卡"),
        (D.LAY_SHORT, D.CARD, "衔接警示×白卡"),
        (report.C_TEXT, D.CARD, "正文×白卡"),
        (report.C_TEXT, qual_bg, "正文×达标行底"),
    ]
    bad = ["%s %.2f" % (name, _ratio(fg, bg))
           for fg, bg, name in pairs if _ratio(fg, bg) < 4.5]
    assert not bad, "对比度 <4.5 色对：%s" % "; ".join(bad)


# ---- merged from tests/test_r304_push_rc_lure.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _rsrc(name="report.py"):
    return open(os.path.join(_BASE, name), encoding="utf-8").read()


def _flight(**kw):
    f = {"price": 2150, "name": "东航MU8352", "code": "MU8352",
         "depTime": "08:20", "arrTime": "11:35", "_platform": "ctrip"}
    f.update(kw)
    return f


# ---------------------------------------------------------------- _rc_word

def test_rc_word_none_none_empty():
    """双侧缺席（键缺/None）不出词——「无值不落词」，与 webui
    _rc_txt 首门同语义。"""
    from report import _rc_word
    assert _rc_word({}) == ""
    assert _rc_word({"returnFee": None, "changeFee": None}) == ""


def test_rc_word_free_and_priced_forms():
    """0/0→「免费退改」；双侧数值→「退￥N·改￥M」（·连接，与 webui
    join('·') 同字）。"""
    from report import _rc_word
    assert _rc_word({"returnFee": 0, "changeFee": 0}) == "免费退改"
    assert _rc_word({"returnFee": 464, "changeFee": 232}) == "退￥464·改￥232"


def test_rc_word_minus_one_both_and_single_side():
    """-1「不可办理」：双侧同 -1 与 webui one() 逐字同——
    「不可退·不可改」（join 形态，非并读缩写）；单侧 -1 缺另一侧
    →「不可退」（filter(Boolean) 同构：缺席侧不出段）。"""
    from report import _rc_word
    assert _rc_word({"returnFee": -1, "changeFee": -1}) == "不可退·不可改"
    assert _rc_word({"returnFee": -1, "changeFee": None}) == "不可退"
    assert _rc_word({"returnFee": None, "changeFee": -1}) == "不可改"
    assert _rc_word({"returnFee": -1, "changeFee": 100}) == "不可退·改￥100"


# ---------------------------------------------------------------- 槽位注册

def test_rc_slot_registered_in_parts():
    """次行字段清单注册 rc 槽（三端渲染门收口：爬虫键 ↔ webui
    白名单/价格格徽标 ↔ PNG 槽——age/risk 同律先例）。"""
    src = _rsrc()
    assert '("rc", _rc_word(f))' in src, "rc 槽未入次行字段清单"


def test_lure_word_carried_by_labels_never_dedicated_slot():
    """lure 词面（页面价￥N不可购）的正文载体是 labels 槽：爬虫端
    组装链把词面 append 进 labels（ctrip.py `_lure_price_tag`），PNG
    labels 槽/lurePrice 数值键驱动 webui 价格格徽标/CSV 三通道已闭合。
    report.py 端不得再造专用槽或第二词源——同词面双渲染零信息增量
    且重复词面反引「图内价错了」困惑（Soldier F1 实锤：两槽同吃
    绘制 2 次）。禁复活 + labels 承载实效双段断言。"""
    src = _rsrc()
    assert '("lure",' not in src, "lure 专用槽禁复活（labels 已承载同词面）"
    assert "页面价" not in src, "report.py 端不得再造该词面第二源"
    assert '("labels", str(f.get("labels") or "").strip())' in src, \
        "labels 槽承载实效丢失（词面进图的真实载体）"


# ---------------------------------------------------------------- 丢档链

def test_lure_not_in_chain_rc_never_dropped():
    """丢档链语义：rc 恒保组不进任何丢档档位（比价隐性成本语义，
    与 transferTax 同族恒保）；lure 不设专用槽故不入链（若将来以
    任何形式回流须与本钉对账，labels 槽既有丢档语义已覆盖同词面）。"""
    src = _rsrc()
    m = re.search(r"_chain = \(.*?\n\s+for _drop, _ss in _chain:", src, re.S)
    assert m, "_chain 丢档链未找到"
    chain = m.group(0)
    assert (chain.count("True)") + chain.count("False)")) == 6, \
        f"丢档链档位数漂移：{chain.count('True)') + chain.count('False)')}"
    assert re.search(r'"tkrisk",\s*"carryon"', chain), \
        "末档形态漂移（tkrisk 后应直连 carryon）"
    assert '"rc"' not in chain, "rc（恒保组）出现在丢档链"
    assert '"lure"' not in chain, "lure 专用槽残留丢档链"


# ---------------------------------------------------------------- 行为钉

def test_rc_word_rendered_into_png(tmp_path, monkeypatch):
    """真实渲染链行为钉：含 rc 的行渲染 tmp PNG，词条以 12px 次行
    小字真实落画布（捕获 ImageDraw.text 全部绘制串）；lure 词面不经
    report 端（labels 槽承载，fixture 无 labels 词面故不得出现）。"""
    import PIL.ImageDraw as _ID
    from report import render_flights_table as _render

    drawn = []
    _orig = _ID.ImageDraw.text

    def _spy(self, xy, text, **k):
        drawn.append(str(text))
        return _orig(self, xy, text, **k)

    monkeypatch.setattr(_ID.ImageDraw, "text", _spy)
    rows = [("direct", [_flight(returnFee=464, changeFee=232)])]
    out = tmp_path / "t.png"
    _render(rows, "测试", str(out), top_n=5)
    assert out.exists() and out.stat().st_size > 0, "渲染未产出"
    joined = "\n".join(drawn)
    assert "退￥464·改￥232" in joined, "rc 词条未进图"
    assert "页面价" not in joined, "report 端 lure 词面残留"


def test_rc_absent_row_renders_without_word(tmp_path, monkeypatch):
    """无 rc/lure 值的行零词条（空值剔除门）——防「无值也占位」
    反向回归。"""
    import PIL.ImageDraw as _ID
    from report import render_flights_table as _render

    drawn = []
    _orig = _ID.ImageDraw.text

    def _spy(self, xy, text, **k):
        drawn.append(str(text))
        return _orig(self, xy, text, **k)

    monkeypatch.setattr(_ID.ImageDraw, "text", _spy)
    rows = [("direct", [_flight()])]
    out = tmp_path / "t.png"
    _render(rows, "测试", str(out), top_n=5)
    joined = "\n".join(drawn)
    assert "退￥" not in joined and "不可退" not in joined
    assert "页面价" not in joined


# ---- merged from tests/test_r315_push.py ----

_C_QUAL = _rep.C_QUAL          # (14, 131, 69) 达标绿
_BODY_Y0, _BODY_Y1 = 64, 400   # 图体区（顶部小注 <64、底部小注 >400 排除）


def _count_qual(path):
    """图体区达标绿像素计数（RGB 距离 ≤30 容差，抗 LANCZOS 扩散）。"""
    from PIL import Image
    img = Image.open(path).convert("RGB")
    w, h = img.size
    px = img.load()
    n = 0
    for y in range(_BODY_Y0, min(_BODY_Y1, h)):
        for x in range(w):
            r, g, b = px[x, y]
            if abs(r - _C_QUAL[0]) <= 30 and abs(g - _C_QUAL[1]) <= 30 \
                    and abs(b - _C_QUAL[2]) <= 30:
                n += 1
    return n


def _render(vals, qd, name, tmp_path):
    from datetime import datetime, timedelta
    t0 = datetime(2026, 10, 10, 8, 0, 0)
    ser = [(t0 + timedelta(minutes=30 * i), vals[i], None, qd[i], False)
           for i in range(len(vals))]
    out = str(tmp_path / name)
    _rep.render_chart(ser, "吞环对照", thresholds=(1800.0, 0.0), out_path=out)
    assert os.path.isfile(out)
    return out


def test_tier_ring_survives_minpoint_overlay(tmp_path):
    """恒档达标轮首点=最低点=环点形态：首环不得被最低点让位白描边
    吞没。对照法自校准——病灶图 A（最低点=首点=环点，首环被吞）与
    健康图 B（最低点在中间非环点，首末两环完整）同阈值同渲染管线，
    两图唯一差异=首环存亡；缺陷态 A 显著小于 B，修复后 A≈B。"""
    # A：递增恒达标（全部 <1800），首点 1749=最低价 → 首点=唯一入场
    # 环点+最低点（达标价通常即最低价的必现形态）
    vals_a = [1749, 1755, 1761, 1767, 1773, 1779, 1785, 1791, 1797]
    qa = [True] * 9
    # B：恒达标，最低点 1700 落中间 idx3（非环点，走常规大点分支，
    # 距首末环远不波及）
    vals_b = [1790, 1793, 1796, 1700, 1775, 1778, 1781, 1784, 1787]
    qb = [True] * 9
    green_a = _count_qual(_render(vals_a, qa, "ring_min_first.png", tmp_path))
    green_b = _count_qual(_render(vals_b, qb, "ring_min_mid.png", tmp_path))
    assert green_b >= 12, f"健康对照环基线不成立：B={green_b}"
    assert green_a >= green_b * 0.8, (
        f"达标轮首环被最低点让位白描边吞没：A={green_a} < B={green_b}×0.8")


# ---- P2-1 direct 组空态词面 ----------

def test_direct_group_empty_note_not_transfer_wording():
    """空态词面按 kind 分派单源：direct 组空态说「未回直飞班次」，
    不复用中转归因词面——「直飞最优」组头下印「未回中转班次」是词面
    与组语义颠倒（日报 directs 空+mkt 非空形态生产可达）。"""
    note = _rep._group_empty_note("direct", 0, None)
    assert "中转" not in note
    assert "直飞" in note


def test_direct_group_empty_note_skips_transfer_constraints():
    """direct 组即使带 meta（衔接下限/到达约束）也不拼中转判据段——
    「衔接≥N 分钟·02:00 前到达」对直飞组是错位约束词面。"""
    note = _rep._group_empty_note("direct", 90, "02:00")
    assert "衔接" not in note and "到达" not in note
    assert "直飞" in note


def test_transfer_group_empty_note_unchanged():
    """transfer 组空态三档词面原样（r271 单源钉语义不丢）：双约束
    缺省归因渠道未回中转班次、带约束拼约束段。"""
    assert "中转" in _rep._group_empty_note("transfer", 0, None)
    note = _rep._group_empty_note("transfer", 90, "02:00")
    assert "衔接≥90 分钟" in note and "02:00 前到达" in note


def test_empty_note_dispatch_wired_in_table_render():
    """源码钉：明细总表空态分支经 kind 分派单源取词——共用
    _transfer_empty_note 直调（无 kind 门）的旧形态不得复活。"""
    with open(_rep.__file__, encoding="utf-8") as f:
        src = f.read()
    assert "_group_empty_note(kind, lay_min, meta.get(\"arrival_max\"))" in src


# ---- P2-2 日报兜底分支图例（RED 先行）----------

def test_daily_fallback_keeps_tier_legend():
    """日报图挂失败兜底分支的 emoji 档位 KPI 必须带图例解释位（复用
    digest 侧 _legend_line 单源，勿另写第二份图例词面）——图例已撤入
    图的常态下，兜底轮 🎯/🟩 整条消息零解释是「可出手/未必可出手」
    决策级失语（能力对称三十§3：digest 常驻托底、日报缺位）。"""
    with open(_rep.__file__, encoding="utf-8") as f:
        src = f.read()
    # 锚=调用点字面（图例行紧贴 _kpi_fallback 的段落拼接形态），
    # 两路兜底（上传失败/生成失败）各一；不锁「def 到调用点」的字符
    # 窗口——两定义点间合法增厚（嵌套兜底函数族）会把窗口撑爆假红
    # （窗口钉判例：窗口是实现细节，锚结构才是钉面）；锚不含行首缩进
    # （两分支嵌套深度不同，带缩进锚必假红）
    assert src.count('Alerter._legend_line() + "\\n\\n"') == 2


# ---- merged from tests/test_r323_push_pins.py ----

sys.path.insert(0, __import__("os").path.dirname(
    __import__("os").path.dirname(__import__("os").path.abspath(__file__))))

_DATE = "2026-09-25"
_ROUTES = [
    {"from": "SHA", "to": "URC", "from_name": "上海",
     "to_name": "乌鲁木齐", "dates": [_DATE],
     "alert_direct": 2000, "alert_transfer": 1800,
     "transfer_arrival_max": "02:00"},
]


def _cfg(routes):
    return {"notifier": {"image_host": {"provider": "freeimage"}},
            "users": [{"name": "u", "routes": routes,
                       "platforms": ["qunar", "ctrip"],
                       "notifier": {"image_host": {"provider": "freeimage"}}}]}


class FakeN:
    def __init__(self):
        self.sent = {}

    def send(self, title, desp="", **kw):
        self.sent["title"], self.sent["desp"] = title, desp
        return True


def test_transfer_layover_line_tokens():
    """token 链（单源）：停[·二段]。跨楼 token 不在此链（挂到达列，
    挤进本链会随中转列宽截断面常态被吃——目检实录）。"""
    f = {"layoverT": "2:05", "lay2dep": "14:30",
         "transGoDate": "2027-01-30",
         "transTerminal": "T1", "transDepTerminal": "T2"}
    assert _transfer_layover_line(f) == "停2:05·二段01-30 14:30"
    assert _transfer_layover_line({"layoverT": "2:05"}) == "停2:05"
    assert _transfer_layover_line(
        {"layoverT": "1:10", "lay2dep": "16:30"}) == "停1:10·二段16:30"
    assert _transfer_layover_line({"transTerminal": "T1"}) == ""
    assert _transfer_layover_line({}) == ""


def test_terminal_key_consumed_in_table_render():
    """transTerminal 落图消费点在案（已采键零消费回归面）。"""
    with open("report.py", encoding="utf-8") as f:
        src = f.read()
    assert "transTerminal" in src and "transDepTerminal" in src
    assert "_tt}→{_tdt}" in src


def test_daily_trend_exception_reconciled(monkeypatch):
    """日报趋势查询异常补对账注（告警路径同场景同词面，能力对称）。"""
    monkeypatch.setattr(rep, "_rounds",
                        lambda db, fc, tc, d, am, **kw:
                        [(datetime(2026, 9, 20, 8, 0), 576.0, None)])
    monkeypatch.setattr(rep, "prepare_round_charts",
                        lambda c, lg, *a, **k: {})
    monkeypatch.setattr(rep, "render_flights_table", lambda *a, **k: None)
    monkeypatch.setattr(rep, "upload_freeimage",
                        lambda p, lg: "http://x/f.png")
    monkeypatch.setattr(rep, "_route_latest_flights",
                        lambda db, fc, tc, d, **kw:
                        [{"price": 2690, "transCity": "",
                          "_platform": "qunar"}])
    def _boom(*a, **k):
        raise RuntimeError("db 满窗异常")
    monkeypatch.setattr(rep, "_trend_line_str", _boom)
    n = FakeN()
    ok = rep.build_and_push(_cfg(_ROUTES), _lg.getLogger("t"), n, user="u")
    assert ok and n.sent["desp"]
    assert "近7天趋势暂缺" in n.sent["desp"], n.sent["desp"]


def test_trend_missing_note_single_source():
    """对账注词面单源在 alerter（日报 import 消费，零手抄第二份）。"""
    assert _TREND_MISSING_NOTE == "> ⚠️ 近7天趋势暂缺"
    with open("core/alerter.py", encoding="utf-8") as f:
        assert f.read().count("近7天趋势暂缺") == 1
    with open("report.py", encoding="utf-8") as f:
        assert "近7天趋势暂缺" not in f.read()


def test_tbl_tier_legend_purchasability_note():
    """图例带「未必可出手」购买性语义（行情破线档动作语义入图）。"""
    assert "未必可出手" in _TBL_TIER_LEGEND


# ---- merged from tests/test_r329_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("t_r329_push")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _fp(price, name, dpt, art, trans="", cross="", plat="qunar",
        dep="2026-11-16", **over):
    d0 = date.fromisoformat(dep)
    days = 1 if cross == "+1天" else (2 if cross == "+2天" else 0)
    f = {"price": price, "name": name, "code": name, "depTime": dpt,
         "arrTime": art, "depDate": dep,
         "arrDate": str(d0 + timedelta(days=days)),
         "transCity": trans, "crossDayDesc": cross,
         "totalDuration": "6时", "_platform": plat}
    f.update(over)
    return f


def _ps(plist, fc, tc, d):
    return [FlightPrice(platform=f["_platform"], from_city=fc, to_city=tc,
                        depart_date=d, price=f["price"],
                        extra=json.dumps([f], ensure_ascii=False))
            for f in plist]


class _FakeN:
    def __init__(self):
        self.calls = []

    def send(self, t, d, at_mobiles=None, is_at_all=False, launch=""):
        self.calls.append((t, d, at_mobiles))
        return True


# ---- P1-1：shareAirline 单独在场「承运·」档（webui 同语言三档）----

def test_p11_share_txt_three_tiers():
    _share = _rep._share_txt
    # 组合档：共享·名+号（存量行为不变）
    assert _share({"shareCarrier": "CZ8404", "shareAirline": "南航"}) \
        == "共享·南航CZ8404"
    # 号-only 档（存量行为不变）
    assert _share({"shareCarrier": "CZ8404"}) == "共享·CZ8404"
    # 名-only 档（r329 P1-1：非共享中转行二段承运，webui「承运·」同词面）
    assert _share({"shareAirline": "东方航空|四川航空"}) \
        == "承运·东方航空|四川航空"
    # 双空零词
    assert _share({}) == ""
    # 模块源钉：_parts 的 share 键消费单源函数（调用点内联是档序
    # 回退温床，LESSONS 十九§9）
    src = open(os.path.join(_ROOT, "report.py"), encoding="utf-8").read()
    assert '("share", _share_txt(f))' in src


# ---- P2-3：舱码括注门扩国际段级值域（webui 任意非空即显对齐）----

def test_p23_cabin_bracket_intl_gate():
    _cb = _rep._cabin_bracket
    # 存量行为：单字母/字母+数字括注
    assert _cb("经济舱", "Y") == "经济舱(Y)"
    assert _cb("经济舱", "B0") == "经济舱(B0)"
    # r329 国际段级连串过门（webui/PNG 同语言）
    assert _cb("经济舱", "W-W") == "经济舱(W-W)"
    assert _cb("经济舱", "Q-Y-B") == "经济舱(Q-Y-B)"
    # 非经济舱不括注（存量行为）
    assert _cb("公务舱", "Y") == "公务舱"
    # 空码不括注
    assert _cb("经济舱", "") == "经济舱"


# ---- P2-1：日历价行空时刻跳过 seg 段（生产 13 条推送裸「> →」根治）----

def test_calendar_row_never_enters_push_hits():
    a = Alerter(_LOG, notifier=_FakeN(), storage=None, digest=True,
                storm_repeat=1, user="演练")
    r = Route(from_code="PVG", to_code="NRT", from_name="上海",
              to_name="东京", dates=["2026-11-16"],
              alert_direct=3000, alert_transfer=0)
    # 日历最低价行：name=「日历最低价」、时刻双空。它不是可出手机票，
    # 不得进入推送分类池/命中，也不得产出「日历最低价 →」空段。
    p = _ps([_fp(2580, "日历最低价", "", "", plat="ctrip")],
            "PVG", "NRT", "2026-11-16")
    assert a._build_sections(r, p) == []
    # 同一轮里的正常航班仍必须命中（守卫不误杀真实低价）
    r2 = Route(from_code="NRT", to_code="PVG", from_name="东京",
               to_name="上海", dates=["2026-11-16"],
               alert_direct=3000, alert_transfer=0)
    p2 = _ps([_fp(2620, "东航MU524", "15:10", "18:25", plat="qunar")],
             "NRT", "PVG", "2026-11-16")
    built = [(r, a._build_sections(r, p)), (r2, a._build_sections(r2, p2))]
    pv = a._digest_payload(built, fresh=True, with_tables=False)
    desp = pv["desp"]
    # 裸「> →」零信息段绝迹（含「> →(+1天)」变体）
    assert "> →" not in desp, desp
    assert "日历最低价 →" not in desp, desp
    # 正常航班命中且 seg 完整；日历航线不冒充命中
    assert "🔥" in desp and "东→上" in desp, desp[-400:]
    assert "15:10→18:25" in desp


# ---- P2-4：机场码辨识槽（国际 city 级查询 PVG/SHA 分辨）----

def test_p24_airport_token_slot():
    src = open(os.path.join(_ROOT, "report.py"), encoding="utf-8").read()
    # parts 机场槽本体（Soldier m-3 半死钉补全：丢档链 3 个 "airport"
    # 字符串满足不了此断言，主修复点被摘即红）
    assert '("airport", _apt)' in src
    # 丢档链末三档才丢（辨识信息在 cabin/lcc 档级保留）：_chain 区域
    # 内 "airport" 计数==3（4/5/6 档 drop 元组各一）
    chain_zone = src.split("_chain = (")[1].split("for _drop")[0]
    assert chain_zone.count('"airport"') == 3, chain_zone


# ---- P3-1：风暴标题保尾「等N条」计数 ----

def test_p31_storm_title_keeps_count_tail():
    # 主推标题（≤51 字符主体+「等21条」尾）：风暴前缀拼入后
    # 「等N条」规模感知不再被切点吃掉
    body = "上海→洛阳 11/16 · 北京→上海 11/17 · 成都→拉萨 11/18" \
           " · 西安→昆明 11/19 · 广州→厦门 11/20"
    full = body + "等21条"
    t = _storm_title(2, 3, full)
    assert t.startswith("📞 达标提醒 2/3 ")
    assert len(t) <= 60, (len(t), t)
    assert t.endswith("等21条"), t
    # 短标题（不触发截断）原样保留
    t2 = _storm_title(1, 3, "上海→洛阳 11/16")
    assert t2 == "📞 达标提醒 1/3 上海→洛阳 11/16"
    # 无计数尾的长标题：旧切法行为不变
    t3 = _storm_title(2, 3, body)
    assert len(t3) <= 60 and t3.startswith("📞 达标提醒 2/3 ")


# ---- merged from tests/test_v15117_push.py ----

def test_plat_tag_tie_precedes_stale():
    from report import _plat_tag
    cn = {"tongcheng": "同程", "qunar": "去哪儿"}
    # tie+stale 同现：tie 前置（被截的恒是 stale 尾段）
    assert _plat_tag({"_platform": "tongcheng", "_tie_n": 2,
                      "_stale_h": 99.0}, cn) == "同程·同价×2·99h前"
    # 无 stale / 无 tie 行形态不变
    assert _plat_tag({"_platform": "tongcheng", "_tie_n": 3}, cn) == \
        "同程·同价×3"
    assert _plat_tag({"_platform": "tongcheng", "_stale_h": 1.0}, cn) == \
        "同程·1h前"
    assert _plat_tag({"_platform": "qunar"}, cn) == "去哪儿"


def test_plat_full_tie_precedes_stale():
    # 文本版同序：两段同现时 tie 必在 stale 前；全形态超 40 半角走
    # 骨架档（渠道·同价×N）时 stale 可丢、tie 必保
    from core.alerter import Alerter
    f = {"_platform": "tongcheng", "_tie_n": 2, "_stale_h": 99.0,
         "price": 900, "name": "9C6928", "depTime": "08:30",
         "arrTime": "11:20"}
    line = Alerter._fmt_flight_line(f, idx=1)
    i_tie, i_stale = line.find("同价×2"), line.find("99h前")
    if i_stale >= 0:
        assert 0 <= i_tie < i_stale
    else:
        assert i_tie >= 0


# ---- merged from tests/test_v15121_push.py ----

# ==================== P1-1 / P2-5 / P2-2: 日报图注与词面 ====================

_ROUTE = {"from": "SHA", "to": "URC", "from_name": "上海",
          "to_name": "乌鲁木齐", "dates": ["2026-09-25"],
          "alert_direct": 2000, "alert_transfer": 1800,
          "transfer_arrival_max": "02:00"}
_FLIGHTS = [
    {"price": 2690, "transCity": "", "_platform": "qunar"},
    {"price": 2150, "transCity": "郑州", "depTime": "12:05",
     "arrTime": "00:35", "arrDate": "2026-09-26", "_platform": "ctrip"},
]


def _daily_cfg():
    return {"notifier": {"image_host": {"provider": "ghimg"}},
            "users": [{"name": "u", "routes": [_ROUTE],
                       "notifier": {"image_host": {"provider": "ghimg"}}}]}


def _build_daily(monkeypatch):
    import report as rep
    monkeypatch.setattr(rep, "prepare_round_charts",
                        lambda c, lg, *a, **k: {("SHA", "URC", "2026-09-25"):
                                       "http://x/t.png"})
    monkeypatch.setattr(rep, "_route_latest_flights",
                        lambda db, fc, tc, d, **kw: _FLIGHTS)
    monkeypatch.setattr(rep, "render_flights_table", lambda *a, **k: None)
    monkeypatch.setattr(rep, "upload_chart", lambda p, c, lg: "http://x/t.png")
    sent = {}

    class FakeN:
        def send(self, title, desp="", **kw):
            sent["desp"] = desp
            return True

    ok = rep.build_and_push(_daily_cfg(), logging.getLogger("t"),
                            FakeN(), user="u")
    assert ok and sent.get("desp")
    return sent["desp"]


class TestDailyTableHeading:
    """P1-1：日报明细表图行前必须有档位图注（图例就近律）；
    P2-5：alt 词面与主推送同词「明细总表」。"""

    def test_heading_before_table_image(self, monkeypatch):
        d = _build_daily(monkeypatch)
        m = re.search(r"#### 📋 明细总表 \S+\n\n!\[明细总表\]\(",
                      d)
        assert m, d[-400:]

    def test_alt_word_unified(self, monkeypatch):
        d = _build_daily(monkeypatch)
        assert "![明细表](" not in d, "alt 词面与主推送分叉"
        assert "![明细总表](http://x/t.png)" in d

    def test_tier_word_from_single_source(self, monkeypatch):
        """图注档位词必须出自 _TBL_HEAD_TIER 单源（勿手抄词面）。"""
        from core.alerter import _TBL_HEAD_TIER
        d = _build_daily(monkeypatch)
        assert f"#### 📋 明细总表 {_TBL_HEAD_TIER}" in d

    def test_timestamp_line_no_space(self, monkeypatch):
        """P2-2：日报 ⏱ 行并主推送口径（⏱ 后不空格）。"""
        d = _build_daily(monkeypatch)
        assert "> ⏱" in d
        assert "> ⏱ " not in d, d[:120]


# ==================== P1-2: 达标日期小节置顶 ====================

class TestHitSectionFirst:
    """同航线多日期：达标日期 section 排前（组内稳定排序）。"""

    def _two_date_payload(self):
        import logging as _lg
        from core.alerter import Alerter
        from core.models import Route as _R
        a = Alerter(_lg.getLogger("t"), storage=None, digest=True)
        r = _R(from_code="SHA", to_code="URC", from_name="上海",
               to_name="乌鲁木齐", dates=["2026-10-05", "2026-10-06"],
               alert_direct=1900, alert_transfer=1700)

        def _sec(date, direct_price):
            return {"date": date, "best_direct": None,
                    "best_transfer": None, "seen_plats": ["qunar"],
                    "best_direct": {"price": direct_price,
                                    "name": "MU8369",
                                    "depTime": "19:55",
                                    "arrTime": "01:25",
                                    "_platform": "qunar"}
                    if direct_price else None}

        # 列表序：10/05（1950 未达标）在前、10/06（1800 达标）在后
        return a._digest_payload(
            [(r, [_sec("2026-10-05", 1950), _sec("2026-10-06", 1800)])],
            fresh=True, with_tables=False)

    def test_hit_date_section_before_non_hit(self):
        p = self._two_date_payload()
        d = p["desp"]
        # 达标日期 10/06 得完整 KPI（￥1800 带 🎯），未达标 10/05
        # 降 mini 行（￥1950）——达标信息须在前
        i_hit = d.find("￥1800")
        i_plain = d.find("￥1950")
        assert i_hit != -1 and i_plain != -1
        assert i_hit < i_plain, "达标日期小节应排在未达标日期之前"
        assert "📍 10/05" in d, "未达标日期保留 mini 行不丢覆盖"

    def test_date_span_keeps_calendar_order(self):
        """小节标题日期跨度按日历序（重排后不得出现 10/06-10/05）。"""
        p = self._two_date_payload()
        assert "10/06-10/05" not in p["desp"]
        assert "10/05-10/06" in p["desp"]

    def test_stable_when_no_hits(self):
        """无达标轮：日期序原样（稳定排序零扰动）。"""
        import logging as _lg
        from core.alerter import Alerter
        from core.models import Route as _R
        a = Alerter(_lg.getLogger("t"), storage=None, digest=True)
        r = _R(from_code="SHA", to_code="URC", from_name="上海",
               to_name="乌鲁木齐", dates=["2026-10-05", "2026-10-06"],
               alert_direct=1000, alert_transfer=900)

        def _sec(date):
            return {"date": date, "best_direct": {"price": 1950,
                    "name": "MU8369", "depTime": "19:55",
                    "arrTime": "01:25", "_platform": "qunar"},
                    "best_transfer": None, "seen_plats": ["qunar"]}

        p = a._digest_payload(
            [(r, [_sec("2026-10-05"), _sec("2026-10-06")])],
            fresh=False, with_tables=False)
        d = p["desp"]
        assert d.find("10/05") < d.find("10/06")


# ==================== P2-4: 强提醒通道死链词 ====================

_DESP_TAIL = ("> 🎯直飞 ￥1540　线￥1700　已达标\n\n"
              "> 乌→上 10/06 · 携程 · 低￥160 · "
              "[打开携程](https://flights.ctrip.com/x)")

class TestDeadJumpWord:
    """[打开XX](url) 进纯文本通道剥壳后是死文字，按动词前缀整段剥。"""

    def test_plaintoast_strips_jump_word(self):
        from core.notifier import WindowsToastNotifier as W
        out = W._plain(_DESP_TAIL, 500)
        assert "打开" not in out, out
        assert "低￥160" in out, "有效信息不得陪剥"

    def test_alert_body_strips_jump_word(self, monkeypatch):
        """短信路径：剥点在 AliyunAlertNotifier.send 内联层（ntfy 同吃
        _alert_body 但还原 URL 可点，剥离不得上移到共享层）。"""
        from unittest import mock
        import json as _json
        import core.notifier as N
        calls = []

        def _fake_post(url, **kw):
            calls.append(kw)
            return mock.Mock(status_code=200)

        monkeypatch.setattr(N.httpx, "post", _fake_post)
        ay = N.AliyunAlertNotifier(url="http://mock", user="u",
                                   password="p",
                                   logger=logging.getLogger("t"))
        assert ay.send("达标提醒", _DESP_TAIL) is True
        body = _json.loads(calls[0]["content"])["message"]
        assert "打开" not in body, body
        assert "低￥160" in body, body

    def test_link_without_open_verb_untouched(self):
        """非「打开」前缀链接（🔍 打开渠道查现价 以 emoji 打头、
        → 打开XX查价）不受整段剥影响（逐字面回归）。"""
        from core.notifier import WindowsToastNotifier as W
        out = W._plain("[🔍 打开渠道查现价](https://x)\n\n"
                       "[→ 打开同程查价](https://y)", 500)
        # 两者有既有 skip/查询语义兜底，但不得被新剥除改形成半截
        assert "https://" not in out
        assert "](http" not in out

    def test_only_jump_link_line_dropped(self):
        """整行只剩打开链接 → 行消失不留残段。"""
        from core.notifier import WindowsToastNotifier as W
        out = W._plain("正文行\n\n[打开携程](https://x)\n\n尾行", 500)
        assert "打开" not in out and "正文行" in out and "尾行" in out


# ---- merged from tests/test_v1589_push.py ----

def _dw(s):
    from core.alerter import _disp_dw
    return _disp_dw(s)


# ---- ServerChan：发送端截断留痕 ----

class _FakeUrlResp:
    def read(self):
        return b'{"code":0}'

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _sc_send(monkeypatch, tmp_path, desp):
    """捕获 ServerChan 实际发出的 desp（零网络）。"""
    cap = {}

    def fake_urlopen(req, timeout=None):
        cap["req"] = req
        return _FakeUrlResp()

    monkeypatch.chdir(tmp_path)   # push_history 落 CWD logs/
    monkeypatch.setattr(nm.urllib.request, "urlopen", fake_urlopen)
    n = nm.ServerChanNotifier("SCT_test", logging.getLogger("t"))
    n.send("t", desp)
    qs = urllib.parse.parse_qs(cap["req"].data.decode("utf-8"))
    return qs["desp"][0]


def test_serverchan_truncation_leaves_trace(monkeypatch, tmp_path):
    """>31800B 纯文本：产物 ≤31800B 且尾注在案（丢失面点明）——
    静默截断曾让尾部明细总表/对账段无声丢失。"""
    desp = "长" * 20000   # 60000B，纯 CJK 无 ![ 无 \n\n
    out = _sc_send(monkeypatch, tmp_path, desp)
    assert len(out.encode("utf-8")) <= 31800, \
        f"截断产物 {len(out.encode('utf-8'))}B 超 ServerChan 31800B 上限"
    assert "已截断" in out, "尾注丢失面说明未落位"
    assert "明细总表" in out, "丢失面语义（尾部明细总表）未点明"


def test_serverchan_truncation_keeps_intact_link(monkeypatch, tmp_path):
    """双图链长文：尾部图链被切点整体让位（不横切 URL 成死链），
    在位图链原样保留。"""
    link_a = "![走势](https://a.example.com/x.png)"
    link_b = "![总表](https://b.example.com/t.png)"
    desp = ("x" * 14000 + "\n\n" + link_a + "\n\n"
            + "y" * 14000 + "\n\n" + link_b + "\n\n" + "z" * 4000)
    out = _sc_send(monkeypatch, tmp_path, desp)
    assert len(out.encode("utf-8")) <= 31800
    assert link_a in out, "在位图链被误切"
    # 死链形态：](http 后被拦腰截断（无闭合括号）=横切实锤
    assert "](https://b" not in out, "尾部图链被横切成死链"


def test_serverchan_truncation_note_no_dup(monkeypatch, tmp_path):
    """无链分支尾注不与本体同义两现（钉钉病句同口关闭）：
    「见控制台」只出现一次。"""
    desp = "a" * 40000
    out = _sc_send(monkeypatch, tmp_path, desp)
    assert out.count("见控制台") == 1, out[-200:]


# ---- 钉钉：无链分支尾注词面去重 ----

class _FakeResp:
    def json(self):
        return {"errcode": 0, "errmsg": "ok"}


class _CapturePost:
    def __call__(self, url, **kw):
        self.payload = kw.get("json")
        return _FakeResp()


def test_dingtalk_note_no_link_branch_distinct(monkeypatch, tmp_path):
    """19000B 无链文本（push_history 实录形态）：尾注不再产出
    「完整明细见控制台），完整详情见控制台」同义两现；无链提示改
    独立语义。"""
    monkeypatch.chdir(tmp_path)
    cap = _CapturePost()
    monkeypatch.setattr(nm.httpx, "post", cap)
    n = nm.DingTalkNotifier.__new__(nm.DingTalkNotifier)
    n.logger = logging.getLogger("t")
    n.last_errcode = None
    n._fail_streak = 0
    n._signed_url = lambda: "http://127.0.0.1/fake-webhook"
    n.send("t", "a" * 19000)
    txt = cap.payload["markdown"]["text"]
    assert len(txt.encode("utf-8")) <= 18000
    assert txt.count("见控制台") == 1, txt[-200:]
    assert "本条已无跳转链接" in txt, "无链分支应给独立指引"


def test_dingtalk_note_with_link_branch_unchanged(monkeypatch, tmp_path):
    """有链分支：尾注维持本体词面（不误加无链提示）。"""
    monkeypatch.chdir(tmp_path)
    cap = _CapturePost()
    monkeypatch.setattr(nm.httpx, "post", cap)
    n = nm.DingTalkNotifier.__new__(nm.DingTalkNotifier)
    n.logger = logging.getLogger("t")
    n.last_errcode = None
    n._fail_streak = 0
    n._signed_url = lambda: "http://127.0.0.1/fake-webhook"
    desp = ("x" * 8000 + "\n\n![走势](https://a.com/x.png)\n\n"
            + "y" * 8000 + "\n\n![总表](https://b.com/t.png)\n\n"
            + "z" * 2500)
    n.send("t", desp)
    txt = cap.payload["markdown"]["text"]
    assert len(txt.encode("utf-8")) <= 18000
    assert "本条已无跳转链接" not in txt, "有链分支误挂无链提示"
    assert txt.count("见控制台") == 1, txt[-200:]


# ---- _cross_compare：头行终档守卫 ----

def test_cross_compare_head_long_name_fits_40():
    """双航司长名+日期+结论（45 半角实发形态）：头行逐行 ≤40 半角，
    航班号与结论保留（地板档=航班号+价格结论，核心判据最小集）。"""
    from core.alerter import Alerter as _A
    base = {"code": "HU7849", "depTime": "08:15", "arrTime": "12:40",
            "depDate": "2026-10-05", "arrDate": "2026-10-05",
            "transCity": "", "crossDayDesc": ""}
    secs = [{"date": "2026-10-05", "pool": [
        dict(base, name="新海航｜海南航空HU7849", price=2546,
             _platform="qunar"),
        dict(base, name="新海航｜海南航空HU7849", price=2746,
             _platform="ctrip")]}]
    secs.append({"date": "2026-10-06", "pool": [
        dict(base, depDate="2026-10-06", name="新海航｜海南航空HU7849",
             price=2688, _platform="qunar"),
        dict(base, depDate="2026-10-06", name="新海航｜海南航空HU7849",
             price=2888, _platform="ctrip")]})
    txt = _A._cross_compare(secs)
    assert txt
    for ln in txt.splitlines():
        assert _dw(ln) <= 40, f"头行超宽 {ln!r} ({_dw(ln)} 半角)"
    head_ln = next(ln for ln in txt.splitlines() if "💰" in ln)
    assert "HU7849" in head_ln, "地板档丢航班号"


# ---- _ops_fallbacks：地板档全角感知截 ----

def test_ops_fallbacks_floor_cjk_width_safe():
    """全 CJK 长注（无冒号形态）：末档地板按 _disp_dw 预算截，
    恒 ≤40 半角（字符数截曾 47 半角超宽）。"""
    from core.alerter import _ops_fallbacks
    tiers = _ops_fallbacks("航变免费退改与直挂标注缺失" * 4)
    assert tiers
    assert _dw(tiers[-1]) <= 40, \
        f"地板档超宽 {tiers[-1]!r} ({_dw(tiers[-1])} 半角)"


def test_ops_fallbacks_floor_colon_head_width_safe():
    """冒号形态：地板保前缀——前缀本身超长时按宽截，恒 ≤40。"""
    from core.alerter import _ops_fallbacks
    n = "超长事由前缀不需要这么长但是为了测试宽度守卫必须写满：" + "内容" * 30
    tiers = _ops_fallbacks(n)
    assert tiers
    assert _dw(tiers[-1]) <= 40, \
        f"地板档超宽 {tiers[-1]!r} ({_dw(tiers[-1])} 半角)"


def test_ops_fallbacks_normal_forms_unchanged():
    """现行四类 ops 注模板（34-40 半角恰安全）：降级链首档语义不回退。"""
    from core.alerter import _ops_fallbacks
    tiers = _ops_fallbacks("直挂标注缺失：qunar、ctrip、tongcheng")
    assert tiers, "正常形态应产出降级链"
    assert tiers[0].startswith("> ⚠️ 直挂标注缺失：qunar、ctrip")


# ---- GitHub 图库上传（ghimg） ----

class _CapturePut:
    """httpx.put 替身：按脚本逐次返回，捕获全部调用参数。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def __call__(self, url, **kw):
        self.calls.append({"url": url, **kw})
        return self.script.pop(0)


class _GhResp:
    def __init__(self, status, text=""):
        self.status_code = status
        self.text = text


def _ghimg(tmp_path):
    import os
    import report as rp
    p = os.path.join(tmp_path, "trend_urc_sha_2026-10-05.png")
    open(p, "wb").write(b"\x89PNG fake")
    return rp, p


def test_ghimg_upload_success_jsdelivr_url(monkeypatch, tmp_path):
    """上传成功：Contents API PUT → 显示 URL=jsDelivr（gh 库@main 路径），
    文件名带时分戳防 CDN 陈旧缓存。"""
    import os
    rp, p = _ghimg(tmp_path)
    cap = _CapturePut([_GhResp(201, '{"content":{"path":"charts/x.png"}}')])
    monkeypatch.setattr(rp.httpx, "put", cap)
    url = rp.upload_ghimg(
        p, {"repo": "dengmeiluan/ticket-img", "token": "t0k"},
        logging.getLogger("t"))
    assert url and url.startswith(
        "https://cdn.jsdelivr.net/gh/dengmeiluan/ticket-img@main/charts/"), url
    assert url.endswith(".png"), url
    body = cap.calls[0]
    assert body["url"].startswith(
        "https://api.github.com/repos/dengmeiluan/ticket-img/contents/charts/")
    assert body["headers"]["Authorization"] == "Bearer t0k"
    assert body["json"]["content"], "base64 内容缺失"


def test_ghimg_upload_retries_via_proxy(monkeypatch, tmp_path):
    """首连异常（api.github.com 直连不通形态）：按配置代理重试一次。"""
    rp, p = _ghimg(tmp_path)

    class _FailThenOk:
        def __init__(self):
            self.calls = []

        def __call__(self, url, **kw):
            self.calls.append(kw)
            if len(self.calls) == 1:
                raise rp.httpx.ConnectError("direct blocked")
            return _GhResp(201)

    fl = _FailThenOk()
    monkeypatch.setattr(rp.httpx, "put", fl)
    url = rp.upload_ghimg(
        p, {"repo": "dengmeiluan/ticket-img", "token": "t0k",
            "proxy": "http://127.0.0.1:7897"},
        logging.getLogger("t"))
    assert url, "代理重试后应成功"
    assert len(fl.calls) == 2
    assert fl.calls[0].get("proxy") is None, "首连应直连"
    assert fl.calls[1].get("proxy") == "http://127.0.0.1:7897"


def test_ghimg_upload_fail_returns_none(monkeypatch, tmp_path):
    """双连皆败：返回 None（r199 后交调用方图挂文本兜底）。"""
    rp, p = _ghimg(tmp_path)

    class _AlwaysFail:
        def __call__(self, url, **kw):
            return _GhResp(401, '{"message":"Bad credentials"}')

    monkeypatch.setattr(rp.httpx, "put", _AlwaysFail())
    url = rp.upload_ghimg(
        p, {"repo": "dengmeiluan/ticket-img", "token": "bad"},
        logging.getLogger("t"))
    assert url is None


def test_upload_chart_ghimg_branch_wired():
    """upload_chart 装配 ghimg 分支（provider=ghimg 且 repo/token 齐
    才走，失败交文本兜底的词面在案）。"""
    import os
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(base, "report.py"), encoding="utf-8").read()
    assert 'provider == "ghimg"' in src, "upload_chart 缺 ghimg 分支"
    assert "GitHub 图库失败，放弃图链路交文本兜底" in src


# ---- merged from tests/test_v167_push.py ----

# ---- 中转文字面 AA ----------

def test_ct_transfer_tx_token():
    """中转文字面深橙令牌与图形本体分离（对浅橙底 4.95:1 过 AA）。"""
    assert _rep.C_TRANSFER_TX == (166, 84, 8)
    assert _rep.C_TRANSFER_TX != _rep.C_TRANSFER


def test_transfer_text_faces_use_tx_token():
    """源码钉：组头/胶囊文字面走 TX 令牌，左色条/描边保 C_TRANSFER 本体。"""
    with open(_rep.__file__, encoding="utf-8") as f:
        src = f.read()
    assert "C_TRANSFER_TX = (166, 84, 8)" in src
    assert 'fill=tx_c, anchor="lm")' in src          # 组头 19px 文字
    assert "fill=cap_tx, anchor=\"mm\")" in src      # 胶囊 12px 文字
    assert "outline=cap_c," in src                   # 胶囊描边=本体
    assert "fill=color)   # 左色条" in src           # 左色条=本体


# ---- 破线空心绿描边 ----------

def test_hollow_price_stroke_width_2():
    """源码钉：破线空心绿价描边 2px（1px 在 2x 缩回+手机缩放下断档最弱）。"""
    with open(_rep.__file__, encoding="utf-8") as f:
        src = f.read()
    assert "stroke_width=2, stroke_fill=C_QUAL)" in src


# ---- 标注避让对档位环加罚 ----------

def test_chart_ring_penalty_smoke(tmp_path):
    """带档位环+▼回落+双最低点标注的合成序列真渲染出图（ring_pts 罚分
    路径整链走通）。"""
    from datetime import datetime, timedelta
    t0 = datetime(2026, 9, 20, 8, 0, 0)
    d_vals = [2450, 2380, 2100, 1998, 1930, 1880, 1860, 1895, 1930]
    t_vals = [2600, 2520, 2350, 2260, 2140, 2050, 1720, 1690, 1688]
    qd = [False, False, False, False, False, True, True, True, False]
    ser = [(t0 + timedelta(minutes=30 * i), d_vals[i], t_vals[i],
            qd[i], i >= 6) for i in range(9)]
    out = str(tmp_path / "trend.png")
    _rep.render_chart(ser, "环标/回落合成", thresholds=(1900.0, 1700.0),
                      out_path=out)
    assert os.path.isfile(out)


# ---- merged from tests/test_v178_push.py ----

class TestPushV178BlackCard:
    @staticmethod
    def _src():
        with open(report.__file__, encoding="utf-8") as f:
            return f.read()

    def test_black_slot_in_parts(self):
        """决策字段次行有 black 槽位（黑卡价词面挂 blackCard 条件）。"""
        src = self._src()
        assert '("black", ("黑卡价" if f.get("blackCard") else ""))' in src, \
            "PNG 次行缺 black 槽位"

    def test_black_in_drop_tiers(self):
        """black 入丢档链（与 discount 同档可丢，恒保组不动）。"""
        src = self._src()
        # r224 起丢档链变量化为 _chain（plan=None 兜底取 _chain[-1]
        # 重建串），钉锚随形态翻转
        i0 = src.index("_chain = (")
        seg = src[i0:i0 + 700]
        assert '"black"' in seg, "black 未入丢档链（超宽行背着它重试）"


# ---- merged from tests/test_v199_push.py ----

# ==================== P0: 日报明细表走 provider 感知上传 ====================

_ROUTE = {"from": "SHA", "to": "URC", "from_name": "上海",
          "to_name": "乌鲁木齐", "dates": ["2026-09-25"],
          "alert_direct": 2000, "alert_transfer": 1800,
          "transfer_arrival_max": "02:00"}
_FLIGHTS = [
    {"price": 2690, "transCity": "", "_platform": "qunar"},
    {"price": 2150, "transCity": "郑州", "depTime": "12:05",
     "arrTime": "00:35", "arrDate": "2026-09-26", "_platform": "ctrip"},
]


def _daily_cfg():
    return {"notifier": {"image_host": {"provider": "ghimg"}},
            "users": [{"name": "u", "routes": [_ROUTE],
                       "notifier": {"image_host": {"provider": "ghimg"}}}]}


def _patch_daily_commons(monkeypatch, rep):
    monkeypatch.setattr(rep, "prepare_round_charts",
                        lambda c, lg, *a, **k: {("SHA", "URC", "2026-09-25"):
                                       "http://x/t.png"})
    monkeypatch.setattr(rep, "_route_latest_flights",
                        lambda db, fc, tc, d, **kw: _FLIGHTS)
    monkeypatch.setattr(rep, "render_flights_table", lambda *a, **k: None)


class TestDailyTableProviderUpload:
    """P0：日报明细表上传必须走 upload_chart（cfg 感知 provider），
    硬编码 upload_freeimage 曾让明细表独走 freeimage→pixhost 死链。"""

    def test_upload_chart_called_with_cfg(self, monkeypatch):
        import report as rep
        _patch_daily_commons(monkeypatch, rep)
        calls = {}

        def _cap_upload(p, c, lg):
            calls["png"], calls["cfg"] = p, c
            return "http://x/table.png"

        monkeypatch.setattr(rep, "upload_chart", _cap_upload)

        def _forbidden(p, lg):
            raise AssertionError(
                "upload_freeimage 不应再被日报明细表路径调用")

        monkeypatch.setattr(rep, "upload_freeimage", _forbidden)
        sent = {}

        class FakeN:
            def send(self, title, desp="", **kw):
                sent["desp"] = desp
                return True

        ok = rep.build_and_push(_daily_cfg(), logging.getLogger("t"),
                                FakeN(), user="u")
        assert ok and sent.get("desp")
        assert calls.get("cfg") == _daily_cfg(), \
            "upload_chart 必须拿到 cfg（provider 感知）"
        assert "![明细总表](http://x/table.png)" in sent["desp"]

    def test_upload_fail_degrades_to_text_kpi(self, monkeypatch):
        """turl=None（P1 后 ghimg 失败形态）→ 明细表留痕 + KPI 文本
        兜底（图挂信息守恒在日报侧闭合）。"""
        import report as rep
        _patch_daily_commons(monkeypatch, rep)
        monkeypatch.setattr(rep, "upload_chart", lambda p, c, lg: None)
        sent = {}

        class FakeN:
            def send(self, title, desp="", **kw):
                sent["desp"] = desp
                return True

        ok = rep.build_and_push(_daily_cfg(), logging.getLogger("t"),
                                FakeN(), user="u")
        assert ok
        d = sent["desp"]
        assert "明细总表缺失" in d and "![明细总表](" not in d
        assert "直飞 ￥2690" in d, "KPI 文本兜底应接管"


# ==================== P1: pixhost 出局，失败交文本兜底 ====================

class TestPixhostOutOfChain:
    """pixhost 显示端直连不可达（v1.5.89 用户热修先例）：上传链
    失败必须返回 None 交图挂文本兜底，不得产出显示端死链 URL。"""

    def test_upload_chart_terminal_not_pixhost(self, monkeypatch):
        import report as rep
        assert not hasattr(rep, "_upload_pixhost"), \
            "pixhost 上传函数应已随链路撤除"
        monkeypatch.setattr(rep, "upload_ghimg", lambda p, ih, lg: None)
        ih = {"provider": "ghimg", "repo": "o/r", "token": "t"}
        url = rep.upload_chart("/tmp/x.png", {}, logging.getLogger("t"),
                               ih=ih)
        assert url is None, "ghimg 失败后不得落 pixhost 死链"

    def test_freeimage_fail_not_pixhost(self, monkeypatch, tmp_path):
        import report as rep
        png = tmp_path / "x.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n")
        monkeypatch.setattr(rep, "_FREEIMG_STATE", {"n": 0, "probe": 0})

        def _dead(*a, **k):
            raise Exception("freeimage endpoint banned")

        monkeypatch.setattr(rep.httpx, "post", _dead)
        url = rep.upload_freeimage(str(png), logging.getLogger("t"))
        assert url is None, "freeimage 失败后不得落 pixhost 死链"

    def test_unconfigured_host_no_pixhost(self, monkeypatch):
        """ih 空 dict=未配置语义：曾「直走 pixhost」，出局后为 None
        （文本兜底接管）。"""
        import report as rep
        url = rep.upload_chart("/tmp/x.png", {}, logging.getLogger("t"),
                               ih={})
        assert url is None


# ==================== P2-1: ops 降级链截断标记半角化 ====================

class TestOpsFallbacksBudget:
    """5 渠道缺失+飞猪(维护中)打头：k=1 档须入 40 预算（首渠道名
    保全，docstring 声称的语义落地），_fit_line 不塌裸地板。"""

    N = "乌上 10/05 无数据：飞猪(维护中)、去哪儿、携程、同程、途牛"

    def test_first_channel_tier_fits(self):
        from core.alerter import _disp_dw, _fit_line, _ops_fallbacks
        out = _fit_line("> ⚠️ " + self.N,
                        fallbacks=_ops_fallbacks(self.N))
        assert _disp_dw(out) <= 40, f"超宽：{_disp_dw(out)}"
        assert "飞猪(维护中)" in out, f"首渠道名未入预算：{out!r}"
        # r220 校准补让位档:(截) 标记与首渠道名争预算时渠道名优先,
        # 诚实性由「渠道全量对账循控制台」备案兜底
        assert ("(截)" in out) or (_disp_dw("> ⚠️ " + self.N) > 40), \
            f"截标记与渠道名双失:{out!r}"

    def test_floor_nonempty_after_prefix(self):
        from core.alerter import _ops_fallbacks
        floor = _ops_fallbacks(self.N)[-1]
        body = floor.replace("> ⚠️ ", "").removesuffix("(截)")
        assert body.strip(), f"地板档前缀后空（病句形态）：{floor!r}"

    def test_normal_form_unchanged(self):
        from core.alerter import _disp_dw, _fit_line, _ops_fallbacks
        n = "孤低价拦截×3：MU1234、MU5678、MU9012"
        out = _fit_line("> ⚠️ " + n, fallbacks=_ops_fallbacks(n))
        assert "孤低价拦截×3：" in out and _disp_dw(out) <= 40


# ==================== P2-2: 直飞组头线价下沉 ====================

def _mk_alerter():
    from core.alerter import Alerter
    return Alerter(logging.getLogger("t"), notifier=None,
                   base_url="http://127.0.0.1:8765")


class TestTop3DirectHeaderBudget:
    """5 位数阈值+多日期组头 41 半角：线价下沉引用行，渲染行恒 ≤40，
    线价信息不丢（信息守恒）。4 位数形态 r220 校准后同降（带日期组头
    「（线￥N）· MM/DD」数字计宽上浮破 40），与中转组头「> 线￥N」
    引用行形态两端统一。"""

    def _desp(self, alert_direct):
        from core.models import Route
        r = Route(from_code="SHA", from_name="上海", to_code="URC",
                  to_name="乌鲁木齐", dates=["2026-10-05", "2026-10-06"],
                  alert_direct=alert_direct, alert_transfer=1800)
        sections = [{"date": "2026-10-05", "top_direct": [],
                     "top_transfer": []},
                    {"date": "2026-10-06", "top_direct": [],
                     "top_transfer": []}]
        return _mk_alerter()._top3_blocks(r, sections)

    def test_wide_header_degrades_with_quote(self):
        from core.alerter import _disp_dw
        desp = self._desp(12345)
        assert "线￥12345" in desp, "线价信息丢失"
        for ln in desp.split("\n"):
            if ln.strip():
                assert _disp_dw(ln) <= 40, f"超宽行：{ln!r}"
        assert "#### ✈️ 直飞最优TOP5（线￥12345）" not in desp

    def test_narrow_header_unchanged(self):
        desp = self._desp(1234)
        # r220 校准:带日期组头「（线￥N） · MM/DD」超 40,线值降档到
        # 紧跟引用行(与 5 位数同形态,信息守恒)
        assert "#### ✈️ 直飞最优TOP5 · 10/05\n\n> 线￥1234" in desp
        assert "#### ✈️ 直飞最优TOP5 · 10/06\n\n> 线￥1234" in desp


# ==================== P2-3: 携程指引行词面收常量 ====================

class TestCtripLoginNoteWidth:
    """「（持续无数据请运行 --login ctrip 重新登录）」43 半角超宽
    ——词面缩短并收模块常量（内联字面是守卫失效温床）。"""

    def test_constant_within_budget(self):
        from core.alerter import _CTIP_LOGIN_NOTE, _disp_dw
        assert _disp_dw(_CTIP_LOGIN_NOTE) <= 40, \
            f"{_CTIP_LOGIN_NOTE!r} = {_disp_dw(_CTIP_LOGIN_NOTE)}"

    def test_old_long_form_absent(self):
        with open("core/alerter.py", encoding="utf-8") as f:
            src = f.read()
        assert "重新登录）" not in src, "43 半角长词面残留"


# ==================== P2-4: 风暴标题前缀计入预算 ====================

class TestStormTitleBudget:
    """前缀「📞 达标提醒 N/M 」计入 60 字符预算（notifier title[:60]
    同口径）——满额主推 title 直拼曾静默截尾丢「｜另监控」段。"""

    def test_full_title_truncated_to_60(self):
        from core.alerter import _storm_title
        t = _storm_title(2, 3, "达标！乌→上 10/05 直飞￥1500 " + "x" * 60)
        assert len(t) <= 60
        assert t.startswith("📞 达标提醒 2/3 达标！乌→上"), t
        assert "达标！乌→上 10/05 直飞￥1500" in t, "锚点段被截"

    def test_short_title_untouched(self):
        from core.alerter import _storm_title
        t = _storm_title(3, 3, "达标！乌→上 10/05 直飞￥1500")
        assert t == "📞 达标提醒 3/3 达标！乌→上 10/05 直飞￥1500"

    def test_storm_path_uses_helper(self):
        with open("core/alerter.py", encoding="utf-8") as f:
            src = f.read()
        assert "_storm_title(" in src
        i = src.index("def _storm(")
        assert "_storm_title(" in src[i:], "风暴路径未走 helper"
        assert 'f"📞 达标提醒' not in src[i:], "内联直拼残留"


# ---- merged from tests/test_v200_push.py ----

def _src():
    import report
    with open(report.__file__, encoding="utf-8") as f:
        return f.read()


def test_rest_seg_single_oversize_item_keeps_marker():
    from core.alerter import _rest_seg
    base = "❌ 全部未达标｜最近 上→乌 10/05 直飞差￥400"
    # 单条超长（装不下）：出「等1条」计数留痕，不再静默全丢
    out = _rest_seg(base, ["乌鲁木齐→上海 10/06 经北京中转 CZ8888/CZ3210 联程" * 3])
    assert out.startswith(base)
    assert "等1条" in out, "单条超长装不下应留「等1条」计数"
    assert len(out) <= 60


def test_rest_seg_marker_respects_budget():
    from core.alerter import _rest_seg
    # title 本身近满（len(title)+len(marker)>60）：维持裸 title，
    # 整行 60 字符预算是地板约束（marker「｜另监控 等1条」8 字符，
    # title>52 时挂不下）
    long_base = "题" * 53
    out = _rest_seg(long_base, ["超长条目" * 20])
    assert out == long_base


def test_trans_col_main_row_width_guarded():
    """中转列主行城市名走 _fit_text 限宽（w-6 与二段行同款），不再
    裸 d.text 直绘无限宽（超长城市名叠字出列）。"""
    src = _src()
    assert 'trans_cx, trans_cw = x, w' in src
    m = None
    for line in src.splitlines():
        if 'trans_cx, trans_cw = x, w' in line:
            m = line
            break
    assert m is not None
    # 主行分支不再有对 txt 的裸 d.text（fill=fill 直绘形态）
    seg_start = src.index('trans_cx, trans_cw = x, w')
    seg = src[seg_start:seg_start + 700]
    assert 'd.text((x + w / 2' not in seg, "中转主行仍裸 d.text 直绘（无限宽）"
    assert '_fit_text(d, txt or' in seg, "主行未走 _fit_text 限宽"


# ---- merged from tests/test_v201_push.py ----

def test_upload_ghimg_path_has_seconds(monkeypatch, tmp_path):
    captured = {}

    class _R:
        status_code = 201
        text = ""

    def fake_put(url, **kw):
        captured["url"] = url
        return _R()

    monkeypatch.setattr(report.httpx, "put", fake_put)
    png = tmp_path / "trend_URC_SHA_2026-10-06.png"
    png.write_bytes(b"\x89PNG fake")
    url = report.upload_ghimg(str(png), {"repo": "o/r", "token": "t"},
                              logging.getLogger("t"))
    m = re.search(r"/charts/\d{8}/trend_URC_SHA_2026-10-06_(\d{6})\.png$",
                  url or "")
    assert m, f"路径未含 6 位时分秒戳: {url}"


def test_upload_ghimg_same_minute_distinct_paths(monkeypatch, tmp_path):
    # 同分钟两次上传（心跳+日报同轮竞态的构造形态）路径必须不同
    seq = [datetime(2026, 9, 29, 9, 8, 0), datetime(2026, 9, 29, 9, 8, 25)]

    class _FakeDT:
        @staticmethod
        def now():
            return seq[len(captured) % len(seq)]

    captured = []

    class _R:
        status_code = 201
        text = ""

    def fake_put(url, **kw):
        captured.append(url)
        return _R()

    monkeypatch.setattr(report.httpx, "put", fake_put)
    monkeypatch.setattr(report, "datetime", _FakeDT)
    png = tmp_path / "trend_URC_SHA_2026-10-06.png"
    png.write_bytes(b"\x89PNG fake")
    ih = {"repo": "o/r", "token": "t"}
    log = logging.getLogger("t")
    u1 = report.upload_ghimg(str(png), ih, log)
    u2 = report.upload_ghimg(str(png), ih, log)
    assert u1 and u2 and u1 != u2, \
        f"同分钟两次上传路径撞车: {u1} vs {u2}"


def test_local_push_image_matches_both_timestamps(tmp_path, monkeypatch):
    # 邮件 cid 直嵌反推正则兼容旧 4 位/新 6 位时分戳双态
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "trend_X.png").write_bytes(b"png-bytes")
    monkeypatch.chdir(tmp_path)
    base = "https://cdn.jsdelivr.net/gh/o/r@main/charts/20260929/trend_X"
    assert notifier._local_push_image(base + "_0930.png") == b"png-bytes"
    assert notifier._local_push_image(base + "_093015.png") == b"png-bytes"
    assert notifier._local_push_image(base + ".png") == b""


# ---- merged from tests/test_v225_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---- P1: 总表单元格文本统一过 _no_emoji ----

def test_tbl_cells_strip_emoji(monkeypatch):
    """含 emoji 的渠道串（航班名/中转城市/次行字段）入图不渲染 tofu：
    cells 组装与次行 plan/sub 文本统一过 _no_emoji（箭头区在 _EMJI
    正则豁免，零误伤）。探针双门：_fit_text（组名/次行路径）+
    _ScaledDraw.text（表体 cells 直绘路径——出发/到达/全程三格不经
    _fit_text，单门探不到该三格的回退，十九§14 空分支假绿家族）。"""
    seen = []
    real_fit = report._fit_text

    def spy_fit(d, text, *a, **kw):
        seen.append(str(text))
        return real_fit(d, text, *a, **kw)

    monkeypatch.setattr(report, "_fit_text", spy_fit)
    real_text = report._ScaledDraw.text

    def spy_text(self, xy, t, **k):
        seen.append(str(t))
        return real_text(self, xy, t, **k)

    monkeypatch.setattr(report._ScaledDraw, "text", spy_text)
    f = {"name": "春秋9C8846✈营销", "depTime": "08:00",
         "arrTime": "11:30", "price": 1200.0, "_platform": "qunar",
         "_qual": False, "transCity": "西安✈转",
         "totalDuration": "5时30分✈", "crossDayDesc": "次日✈达",
         "plane": "空客321✈", "planeSize": "中型机",
         "meal": "有餐食✈盒", "labels": "大机型✈",
         "stopCity": "", "stopTimeT": ""}
    rows = [("direct", [f])]
    out = os.path.join("_scratch", "r225_t225_tbl_emoji.png")
    report.render_flights_table(rows, "测试标题", out, summary="")
    assert seen, "渲染未经过探针（探针失灵）"
    # 直绘三格确在探针视野：totalDuration/crossDayDesc 的 ✈ 只能经
    # _no_emoji 剥除后入 d.text，未剥即被 spy_text 抓住
    bad = [t for t in seen if "✈" in t]
    assert not bad, bad[:3]


# ---- P3: 档位色词条前移 summary 盒尾 + 底部图例退役四档词条 ----

def _one_row(qual):
    f = {"name": "MU5137", "depTime": "08:00", "arrTime": "11:30",
         "price": 1200.0, "_platform": "qunar", "_qual": qual}
    return [("direct", [f])]


def _tbl_h(rows, summary):
    out = os.path.join("_scratch", "r225_t225_tbl_h.png")
    report.render_flights_table(rows, "测试", out, summary=summary)
    from PIL import Image
    return Image.open(out).size[1]


def test_tier_legend_moves_into_summary_box():
    """legend_worthy 时档位色词条行并入 summary 盒尾：盒高 +16（一行
    14px 档）；与底部图例退役四档词条联动后总高差 = 48(图例)+16(词条行)。"""
    sm = ["直飞最低 ￥1200 低￥100·行情"]
    h_plain = _tbl_h(_one_row(False), sm)
    h_qual = _tbl_h(_one_row(True), sm)
    assert h_qual - h_plain == 48 + 16, (h_plain, h_qual)


def test_tbl_tier_legend_constant():
    """前移词条行常量（TIER_FULL 投影单源，词面与旧底部图例首行逐字
    一致零漂移；r323 起描绿档带「未必可出手」购买性语义——r318 slim
    撤 💡 建议行后该动作语义在图内的唯一承载）。"""
    assert report._TBL_TIER_LEGEND == (
        "深绿=真达标 · 描绿=行情破线（未必可出手） · 琥珀=擦边 · 深蓝=超线")


def test_bottom_legend_tier_entries_retired():
    """底部图例首行退役四档词条只留衔接警示色（词条前移不复制——
    同词面两处消费点违十六§3b 单源律）。"""
    src = open("report.py", encoding="utf-8").read()
    assert "橙红=衔接不足 · 绿停时=衔接达标" in src
    assert "深蓝={TIER_FULL['over']} · 橙红" not in src


# ---- P2: KPI 行1 百分比降级链单源 helper ----

def test_pct_fallback_forms_three_tiers():
    """降级链形态：全角括号态 → 间隔号态 → 裸态 → 剥线地板档
    （r309 E1 第四档：剥「　线￥N」参照段，保价格+差额恒达标）；
    pct 空（<1% 省略）前三档同形、地板档仍兜极限带超宽。主链
    _kpi_block 与心跳两分支同源。"""
    from core.alerter import _pct_fallback_forms
    b = "🟨直飞 ￥1760　线￥1900　低￥140"
    assert _pct_fallback_forms(b, "7%") == [
        b + "（7%）", b + "·7%", b, "🟨直飞 ￥1760　低￥140"]
    assert _pct_fallback_forms(b, "") == [
        b, b, b, "🟨直飞 ￥1760　低￥140"]


def test_pct_fallback_forms_call_sites():
    """源码钉锁调用点：helper 定义 1 处 + 消费 3 处（主链 else 分支、
    心跳直飞/中转两分支）——内联 fallback 列表残留即钉红。"""
    src = open("core/alerter.py", encoding="utf-8").read()
    assert src.count("_pct_fallback_forms(") == 4, src.count(
        "_pct_fallback_forms(")


def test_heartbeat_line1_reaches_middle_tier():
    """心跳行1 降级链真达中间档：全角括号态超宽、间隔号态恰达线时，
    实际落位必须是「·N%」形态而非直接跳地板档（40 半角守卫
    _fit_line 统一降级语义）。"""
    from core.alerter import _disp_dw, _fit_line, _pct_fallback_forms
    base = "🟨中转 ￥1750　线￥1700　高￥550"
    pct = "3%"
    full = base + f"（{pct}）"
    assert _disp_dw(full) > 40, "样本未触发降级，用例失真"
    mid = base + "·" + pct
    assert _disp_dw(mid) <= 40, "中间档样本须预算内恒达标"
    forms = _pct_fallback_forms(base, pct)
    assert _fit_line(forms[0], fallbacks=forms[1:]) == mid


# ---- P4 + P5: 注释正名 / _p7_note 单算 ----

def test_ring_note_comment_current_wording():
    """report.py 点环小注注释「🎯达标」为旧词——现役「真达标」
    （_TIER_TABLE 已正名，错认知随注释传递）。alerter 图例注释
    同律（🎯 与「真达标」词面分离定义，无连续字面，只断言旧词零残留）。"""
    src = open("report.py", encoding="utf-8").read()
    assert "🎯达标" not in src
    assert "🎯真达标" in src
    asrc = open(os.path.join("core", "alerter.py"),
                encoding="utf-8").read()
    assert "🎯达标" not in asrc, "alerter 注释旧词残留"


def test_p7_note_evaluated_once_per_branch():
    """空小节补偿参照 _p7_note 回算收单算：独立引用行形态
    （r258-P2-1）下由 _p7_quote_line 单点封装，两空分支各调一次
    _p7_quote_line（每次内含 1 次 _p7_note()）；未设线档
    _p7_note(False) 既有调用维持（源码钉锁写点受控枚举）。"""
    src = open("report.py", encoding="utf-8").read()
    assert src.count("p7 = _p7_note()") == 1, src.count("p7 = _p7_note()")
    # 3 = def 行 1 + 两空分支调用 2（def _p7_quote_line(): 行含同串）
    assert src.count("_p7_quote_line()") == 3, src.count("_p7_quote_line()")
    # 3 = def 行 1 + _p7_quote_line 内赋值 1 + 未设线档 _p7_note(False) 1
    #     （r257-P3-3 紧凑档随同行拼接链一并退役）
    assert src.count("_p7_note(") == 3, src.count("_p7_note(")
