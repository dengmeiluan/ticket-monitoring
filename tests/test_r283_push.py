# -*- coding: utf-8 -*-
"""r283 推送层：ntfy 强提醒命中行前置（P1-1）+ 图挂兜底保码档（P2-1）+
ops 注悬垂分隔符（P3-1）+ 预览注粘连（P3-2）+ 邮件横幅词面（P3-3）+
@段末行（P3-4）。

P1-1 实证：31/31 真实 urgent 轮 desp 全超 600 截断线，hits 行在线性
序尾部恒被截——kept body「命中」行数为 0，唯一可操作载体（打开XX
直达链接）全灭，留痕仅剩计数。修法=命中块（🔥 head+seg/tail 引用
段）前置到 body 头部，锚点 KPI 与其余小节原序随后按预算截。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r283_push.py -q
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import core.notifier as _not  # noqa: E402


def _mk_desp(fill_len=1100):
    """真实 digest 形态：KPI 头（含建议出手）+ 填充节 + 尾部 hits。"""
    fill = ("#### 10/28 周二\n\n> 10/28 最低 ￥1980（线￥1900）"
            "超线 4.2%\n\n") * (fill_len // 60 + 1)
    return (
        "#### 🎯 上海→乌鲁木齐 真达标 ￥1760（线￥1900）距线-7.4%，"
        "建议出手\n\n"
        "> 10/27 周一 最低 ￥1760 ｜ 🟩行情破线\n\n"
        + fill
        + "> 🔥 **真达标 ￥1701** 海航HU7815\n\n"
        + "> 21:10→02:35(+1天)\n\n"
        + "> 乌→上 10/27 · 去哪儿 · 低价￥63 · "
          "[打开去哪儿](https://flight.qunar.com/view/xyz)\n\n"
        + "@138****1234\n")


def _send_capture(monkeypatch, desp, budget_note=True):
    captured = {}

    class _R:
        status_code = 200
        text = ""

    def _fake_post(url, json=None, **kw):
        captured.update(json or {})
        return _R()

    monkeypatch.setattr(_not.httpx, "post", _fake_post)
    n = _not.NtfyNotifier("topic-r283", logging.getLogger("r283"))
    n.send("达标警报", desp)
    return captured.get("message") or ""


# ---- P1-1 ntfy 命中行前置 ----

def test_ntfy_hits_frontloaded_in_budget(monkeypatch):
    """长 desp（超 600 截断线）的 kept body 必含「命中」行与「打开」
    直达链接词面——命中块前置后 600 预算内必达，线性尾序恒截翻案。"""
    body = _send_capture(monkeypatch, _mk_desp())
    assert "￥1701" in body, body
    assert "打开去哪儿" in body, body
    assert "已截断" in body, "长 desp 应保留截断留痕"


def test_ntfy_no_hits_desp_unchanged(monkeypatch):
    """无命中块的 desp 零变形：重排只动命中块，其余小节原序保留。"""
    short = ("#### 🎯 上海→乌鲁木齐 真达标 ￥1760（线￥1900）"
             "距线-7.4%，建议出手\n\n> 10/27 最低 ￥1760\n")
    body = _send_capture(monkeypatch, short)
    assert "建议出手" in body, body
    assert "已截断" not in body, body
    assert body.index("真达标") < body.index("10/27"), body


# ---- P2-1 图挂兜底 🔥 行保码剥跨天括注终档 ----

class TestFmtFlightLineMarkKeepCode:
    """带 mark 行（🔥 可出手行）「保码剥 cross」终档：告警 desp
    的 hits 区 seg 行已单独承载时刻+跨天（hit_rows 源自 hits 全集），
    head 地板档在 40 预算下按行结构分工——跨天班五行中两行无航班号
    （读者知价不知班）翻案；keep_cross=True（report 日报兜底语境，
    无 hits 段承载）维持旧档序防「当日达误判」回潮。
    r285 审校 P2-1：启用域收口到「该行 ∈ hits」（in_hits 形参，
    TOP5 次优 🔥 行无第二承载位必须保跨天）——本类钉面随域加参
    in_hits=True（原语义=命中行语义）；非命中域的钉在 r285。"""

    def _line(self, alerter, mark, name, dep, arr, cross, **kw):
        f = {"name": name, "code": "HU7815", "price": 1701,
             "depTime": dep, "arrTime": arr,
             "crossDayDesc": cross, "_platform": "qunar"}
        return alerter._fmt_flight_line(f, mark=mark, **kw)

    @pytest.fixture
    def alerter(self):
        from core.alerter import Alerter
        return Alerter(logging.getLogger("r283"), storage=None)

    def test_mark_row_keeps_code_drops_cross(self, alerter):
        """🔥 行（∈hits）：航班号完整在场、跨天括注让位（seg 行承载）。"""
        ln = self._line(alerter, "🔥", "海航｜海南航空HU7815",
                        "21:10", "02:35", "+1天", in_hits=True)
        assert "HU7815" in ln, ln
        assert "￥1701" in ln, ln
        assert "21:10" in ln, ln
        assert "+1天" not in ln, ln

    def test_plain_top_row_keeps_cross_semantics(self, alerter):
        """无 mark 行档序不变：跨天括注优先于码（无 seg 行承载跨天，
        防当日达误判）。"""
        ln = self._line(alerter, "", "海航｜海南航空HU7815",
                        "21:10", "02:35", "+1天")
        assert "+1天" in ln, ln

    def test_keep_cross_daily_digest_semantics(self, alerter):
        """keep_cross=True（report 日报兜底语境）：跨天恒保到地板
        （该消息无 hits 段，剥掉=误判当日达回潮——Soldier M-1）。"""
        ln = self._line(alerter, "🔥", "海航｜海南航空HU7815",
                        "21:10", "02:35", "+1天", keep_cross=True)
        assert "+1天" in ln, ln


# ---- P3-1 ops 注地板档悬垂分隔符 ----

def test_ops_fallbacks_floor_no_dangling_separator():
    """无冒号长注地板档截点落在「·」上时剥尾分隔符：产出
    「…标注缺失·(截)」读作未完列举——「·」是并列连接件不是信息。"""
    from core.alerter import _ops_fallbacks
    n = "上→乌 10/27 中转直挂标注缺失·按未标注判不达标"
    floor = _ops_fallbacks(n)[-1]
    assert floor.endswith("(截)"), floor
    body = floor[:-len("(截)")]
    assert not body.rstrip().endswith(("·", "、", "：", ":")), floor


# ---- P3-2 webui 预览注与 @ 段粘连 ----
# （钉面随 r285 审校 P3-4 迁址：预览注改走 _append_before_at @ 前插
#  单源，前导段落分隔由该单源承担——锁定新形态的钉在
#  tests/test_r285_push.py::test_preview_note_before_at_segment，
#  旧「直拼+前导 \n\n」形态随改写一并禁复活。）


# ---- P3-3 邮件横幅口径词（消「真达标/已达标」一邮两词面）----

def test_email_banner_uses_scale_word_not_tier_word():
    """🚨/🎯 横幅主字=口径词「达标 · 可出手」：desp 正文头档位词
    「已达标——可出手」同屏并存时「真达标/已达标」两词一信。"""
    from core.notifier import _banner_html
    html = _banner_html("🚨 上海→乌鲁木齐 真达标 ￥1760")
    assert "达标 · 可出手" in html, html
    assert "真达标" not in html, html


# ---- P3-4 @ 段恒为消息末行 ----

def test_append_before_at_keeps_at_last():
    """详情链接/失败注插入尾部 @ 段之前：@ 是「谁被点名」的触达
    载体（atMobiles 高亮恒在最后一条消息段）。"""
    from core.alerter import _append_before_at
    desp = "正文\n\n@138****1234 "
    out = _append_before_at(desp, "[📲 完整详情](https://x.y)")
    assert out.index("完整详情") < out.index("@138"), out
    assert out.rstrip().endswith("@138****1234") or \
        "@138****1234" in out[out.index("@138"):], out


def test_append_before_at_without_at_tail():
    """无 @ 段尾部直拼（非达标轮 at_mobiles=None 路径零变形）。"""
    from core.alerter import _append_before_at
    desp = "正文段落"
    out = _append_before_at(desp, "注")
    assert out == "正文段落\n\n注", repr(out)
