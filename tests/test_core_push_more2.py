# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r267_push.py
- tests/test_r339_push.py
- tests/test_v1556_push.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import core.notifier as N
import datetime as dt
import json
import logging
import os
import re
import sys

from core.alerter import Alerter, _dw, _fit_line, kpi_tier_txt
from core.models import FlightPrice, Route
from core.specials import SpecialDeal, SpecialWatch, build_special_push
from unittest import mock


# ---- merged from tests/test_r267_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _src():
    return open("core/alerter.py", encoding="utf-8").read()


def test_refline_prefix_in_budget():
    src = _src()
    # 降级档：引用行前缀并入量纲（消费点总预算扣减，LESSONS 十九§2）
    assert re.search(r'_fit_line\(\s*names,\s*limit=40 - _dw\("> "\)', src), \
        "引用行前缀未并入量纲（> +40 半角本体=42 超宽渲染行）"
    # 地板档随限收紧：names[:16]+"(截)"=36 本体，渲染行=2+36=38 恰满
    assert 'fallbacks=[names[:16] + "(截)"]' in src, \
        "地板档未随限收紧（末档超预算=恒达标律破口）"


def test_budget_math():
    # 数学锚：前缀宽 2；收紧后地板档本体 36（"(截)" 半角括号 _dw 实值 4：
    # 16×2+4=36），整行 38=limit 恰满
    assert _dw("> ") == 2
    fb = "去哪儿、携程、飞猪、同程"[:16] + "(截)"
    assert _dw(fb) <= 38, "地板档本体超 38（整行将破 limit）"
    # 守卫行为：40 半角本体在 limit=38 下降级、38 地板达标
    wide = "站" * 20  # 40 半角
    got = _fit_line(wide, limit=38, fallbacks=[fb])
    assert _dw(got) <= 38, got


# ---- merged from tests/test_r339_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("t339p")

_W = SpecialWatch(from_code="URC", from_name="乌鲁木齐",
                  max_price=2000.0, round_trip=False)

_D = SpecialDeal(src="tuniu", from_code="URC", to_code="ALK",
                 date="2026-11-16", src_price=1800.0,
                 airline="东方航空", discount="3.2折",
                 to_name="阿拉善左旗（阿拉善左旗机场）")


# ---- P1-1：特价标题不复用档位语义点 ----

def test_special_title_avoids_tier_emoji():
    title, desp = build_special_push(_W, [(_D, 1600.0)])
    assert title, "标题空"
    for e in ("🎯", "🚨", "🔔", "🔥"):
        assert e not in title, f"标题复用档位语义点 {e}：{title}"


def test_special_title_banner_not_mislabeled():
    """决策级断言：特价标题进邮件壳横幅不产「达标」绿底。"""
    title, _ = build_special_push(_W, [(_D, 1600.0)])
    html = N._banner_html(title)
    assert "达标" not in html, "特价邮件横幅误标达标"


# ---- P2-2：特价正文段落律 + 首行行宽 ----

def test_special_desp_paragraph_law():
    """段内无单 \n（PC 贴字根治：日期与价格行间必须 \n\n）。"""
    _, desp = build_special_push(_W, [(_D, 1600.0)])
    assert "\n" not in desp.replace("\n\n", ""), \
        f"段内单 \\n 违段落律：{desp!r}"


def test_special_first_line_fitted():
    """首行（长名域）≤40 半角（_dw 真函数），且价格判据保留（地板
    档语义：✅ 短名+价格恒落位）。"""
    from core.alerter import _dw
    _, desp = build_special_push(_W, [(_D, 1600.0)])
    first = desp.split("\n")[0]
    assert _dw(first) <= 40, f"首行 {len(first)} 超 40 半角：{first!r}"
    assert "￥1600" in desp, "价格判据丢失"


# ---- P2-1：Bark 强提醒文本纪律 ----

def _mk_bark(monkeypatch):
    bk = N.BarkNotifier(key="k1", logger=_LOG)
    calls = []
    monkeypatch.setattr(
        N.httpx, "post",
        lambda u, **kw: calls.append((u, kw))
        or mock.Mock(status_code=200, json=lambda: {"code": 200}))
    return bk, calls


def test_bark_body_filters_legend_at_gauge(monkeypatch):
    """图例行/仪表条/@行滤除 + 档位 emoji 转写为词（_alert_body 同族）。"""
    bk, calls = _mk_bark(monkeypatch)
    desp = ("> ⏱ 17:53 🎯真达标 🟩破线 🟨擦边 超线\n\n"
            "#### 上海 → 海口\n\n直飞 **￥900** 低￥200\n\n"
            "🟩🟩🟩🟩🟩\n\n@13800138000 \n\n⏰ 17:53")
    bk.send("达标", desp)
    body = calls[0][1]["json"]["body"]
    assert "⏱" not in body and "🟩" not in body, body
    assert "@138" not in body, body
    assert "￥900" in body, "价格判据丢失"


def test_bark_truncation_has_note(monkeypatch):
    """600 截断带留痕（「（已截断」尾注，钉钉/ntfy/短信/WinToast 同族）。"""
    bk, calls = _mk_bark(monkeypatch)
    bk.send("t", "字" * 900)
    body = calls[0][1]["json"]["body"]
    assert len(body) <= 640, f"截断失效：{len(body)}"
    assert "已截断" in body, f"截断无留痕：{body[-40:]!r}"


def test_bark_dangling_colon_stripped(monkeypatch):
    """URL 避让让位后悬垂冒号剥（ntfy 同构守卫）。"""
    bk, calls = _mk_bark(monkeypatch)
    bk.send("t", "中转 ￥2650:\n\n[购买](https://example.invalid/x)")
    body = calls[0][1]["json"]["body"]
    assert not body.rstrip().endswith((":", "：")), f"悬垂冒号：{body[-30:]!r}"


# ---- P3-1：走势图小注 mkt 词条购买性限定 ----

def test_trend_ring_note_mkt_buy_limit():
    mod = open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "report.py"), encoding="utf-8").read()
    assert "未必可购" in mod, "走势图小注缺 mkt 购买性限定"


# ---- merged from tests/test_v1556_push.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _fp(price, name, dpt, art, plat="qunar", dep="2026-09-25"):
    return {"price": price, "name": name, "code": name, "depTime": dpt,
            "arrTime": art, "depDate": dep, "arrDate": dep,
            "transCity": "", "crossDayDesc": "",
            "totalDuration": "6时", "_platform": plat}


def _ps(plist, fc, tc, d):
    return [FlightPrice(platform=f["_platform"], from_city=fc, to_city=tc,
                        depart_date=d, price=f["price"],
                        extra=json.dumps([f], ensure_ascii=False))
            for f in plist]


def _mk_alerter():
    log = logging.getLogger("t1556push")
    return Alerter(log, notifier=None, storage=None, digest=True,
                   at_mobile="", storm_repeat=1, user="演练")


# ----：kpi_tier_txt 行情消歧（单源单测） ----

def test_kpi_tier_txt_market_disambiguation():
    """破线未达标：词面带「·行情」短注（「低￥N」词面属真达标档，
    图内 summary 脱离上下文曾读成可出手）；真达标对称显名「·真达标」
    （正向档裸「低￥N」同源不显名）；恰达线/超线/擦边口径不变。"""
    assert kpi_tier_txt("中转", 1500, 1700, False).endswith("低￥200·行情")
    assert kpi_tier_txt("直飞", 1500, 1700, True).endswith("低￥200·真达标")
    assert "·行情" not in kpi_tier_txt("直飞", 1500, 1700, True)
    assert "行情破线" in kpi_tier_txt("直飞", 1700, 1700, False)
    assert "真达标" in kpi_tier_txt("直飞", 1700, 1700, True)
    assert "差￥300" in kpi_tier_txt("直飞", 2000, 1700, False)
    assert "擦边" in kpi_tier_txt("直飞", 1780, 1700, False)


# ----：multi 主路径真达标行无仪表条（真实链路） ----

def test_multi_digest_qual_row_no_gauge():
    """真达标行已有 🎯+低￥N+hits 🔥 三重同义（撤达标行），
    multi 主路径 `_g` 无条件吃 _gauge 曾让 🎯 行下挂 🟩 满格——与图例
    「🟩=破线」同色两义、主次拉平。纯真达标场景（无破线蹲守行）desp
    不得出现 🟩 满格条。"""
    a = _mk_alerter()
    d = "2026-09-25"
    r1 = Route(from_code="SHA", to_code="URC", from_name="上海",
               to_name="乌鲁木齐", dates=[d], alert_direct=1900,
               alert_transfer=1700)
    r2 = Route(from_code="URC", to_code="SHA", from_name="乌鲁木齐",
               to_name="上海", dates=[d], alert_direct=1900,
               alert_transfer=1700)
    p1 = _ps([_fp(1468, "南航CZ6981", "18:30", "23:40")], "SHA", "URC", d)
    p2 = _ps([_fp(1520, "东航MU8369", "08:00", "13:00")], "URC", "SHA", d)
    pv = a._digest_payload([(r1, a._build_sections(r1, p1)),
                            (r2, a._build_sections(r2, p2))],
                           fresh=True, with_tables=False, with_charts=False)
    desp = pv["desp"]
    assert "🎯" in desp
    assert "🟩🟩🟩🟩🟩" not in desp, desp


def test_multi_digest_market_row_keeps_gauge():
    """行情破线（未达标）行仪表条保留（设计原意：只给破线行
    留 🟩 满格强化）—— 修复不得矫枉过正撤掉蹲守档强化。
    r318 心跳轻量化随迁：蹲守档（qual_hit=False、price≤th）不在
    hits/fell 豁免面，未达标轮 desp 压缩为单行（档位色自含于总表
    PNG）；仪表条载体在全量小节——补一条真达标航线让 hits 非空、
    蹲守行随全量小节出仪表，钉面语义不变。"""
    a = _mk_alerter()
    d = "2026-09-25"
    # 中转行情班：到达约束内（00:55 ≤ 02:00）但直挂约束不满足
    # （transfer_baggage=direct 行未标注）→ 进 top_transfers 成
    # best_transfer_mkt（KPI 展示班），qual_hit=False、price≤th →
    # 行情破线档成立
    r1 = Route(from_code="SHA", to_code="URC", from_name="上海",
               to_name="乌鲁木齐", dates=[d], alert_direct=1900,
               alert_transfer=1900, transfer_baggage="direct")
    r2 = Route(from_code="URC", to_code="SHA", from_name="乌鲁木齐",
               to_name="上海", dates=[d], alert_direct=1900,
               alert_transfer=1900, transfer_baggage="direct")
    p1 = _ps([{"price": 1800, "name": "春秋9C7006", "code": "9C7006/9C7310",
               "depTime": "15:15", "arrTime": "00:55", "depDate": d,
               "arrDate": "2026-09-26", "transCity": "石家庄",
               "crossDayDesc": "+1天", "totalDuration": "9时40分",
               "layover": 180, "layoverSrc": "transInfo",
               "_platform": "fliggy"}], "SHA", "URC", d)
    p2 = _ps([{"price": 1500, "name": "春秋9C8846", "code": "9C8846",
               "depTime": "09:00", "arrTime": "23:00", "depDate": d,
               "arrDate": d, "transCity": "西安",
               "crossDayDesc": "", "totalDuration": "5时",
               "layover": 120, "layoverSrc": "transInfo",
               "_platform": "tongcheng"}], "URC", "SHA", d)
    r3 = Route(from_code="CAN", to_code="PEK", from_name="广州",
               to_name="北京", dates=[d], alert_direct=1900,
               alert_transfer=1700)
    p3 = _ps([_fp(1468, "南航CZ6981", "18:30", "23:40")], "CAN", "PEK", d)
    pv = a._digest_payload([(r1, a._build_sections(r1, p1)),
                            (r2, a._build_sections(r2, p2)),
                            (r3, a._build_sections(r3, p3))],
                           fresh=True, with_tables=False, with_charts=False)
    desp = pv["desp"]
    assert "🟩🟩🟩🟩🟩" in desp, desp


# ----：ops 回退截尾不用 U+2026 ----

def test_ops_truncate_no_ellipsis_char():
    """「…」钉钉渲染成。。（钉钉渲染定律）——总表上传失败回退的 ops 注截尾
    尾注为截断标记（生产链统一半角形态），全链 desp 不再出现
    U+2026 字符；本钉自建 fallback，守 U+2026 禁现语义。"""
    a = _mk_alerter()
    d = "2026-09-25"
    r1 = Route(from_code="SHA", to_code="URC", from_name="上海",
               to_name="乌鲁木齐", dates=[d], alert_direct=1900,
               alert_transfer=1700)
    p1 = _ps([_fp(1468, "南航CZ6981", "18:30", "23:40")], "SHA", "URC", d)
    secs = a._build_sections(r1, p1)
    # 模拟超宽 ops 注走截尾 fallback（_fit_line 空尾档）
    from core.alerter import _fit_line
    _n = "孤低价拦截×3：飞猪￥9900、去哪儿￥9500、同程￥9300、途牛￥9100"
    out = _fit_line(_n, fallbacks=[
        _n[:_n.find("：") + 1] + "（截）" if "：" in _n else _n[:18] + "（截）"])
    assert "…" not in out
    assert "（截）" in out
    # 全链组装路径也不产 …（图 URL 假链触发 ops 回退）
    a.round_charts = {}
    pv = a._digest_payload([(r1, secs)], fresh=True, with_tables=False,
                           with_charts=False)
    assert "…" not in pv["desp"], pv["desp"]
