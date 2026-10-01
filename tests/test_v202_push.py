# -*- coding: utf-8 -*-
"""推送审校落地四案：图挂兜底入字节预算+@段地板预留（P1-1/P1-2）、
title 锚点缺席分支逐条让位（P2-1）、小节标题末档城市名截尾（P2-2）、
legacy 价格行行宽守卫（P2-3）。附带 M-3 走势单点居中两端同语言。

审校实证：兜底分支在预算组装后直拼，
prod40 形态 28296B 被发送端截到 17799B、@段随之蒸发——「图挂兜底」
退化为部分兜底，违「构建端降级优于发送端截断」；修法=总额预留制
（@段恒落位 + 兜底块预算竞争 + 让位说明行）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v202_push.py -q
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.alerter import Alerter, _dw  # noqa: E402
from core.models import FlightPrice, Route  # noqa: E402

logging.basicConfig(level=logging.CRITICAL)
LOG = logging.getLogger("t202p")

_PLATS = ["qunar", "ctrip", "fliggy", "tongcheng", "tuniu"]
_AIRLINES = ["春秋9C", "国航CA", "东航MU", "南航CZ", "海航HU"]
combo12 = [("URC", "SHA", "乌鲁木齐", "上海"),
           ("SHA", "URC", "上海", "乌鲁木齐"),
           ("CTU", "PEK", "成都", "北京"),
           ("PEK", "CTU", "北京", "成都"),
           ("CAN", "SZX", "广州", "深圳"),
           ("SZX", "CAN", "深圳", "广州"),
           ("HGH", "CKG", "杭州", "重庆"),
           ("CKG", "XIY", "重庆", "西安"),
           ("XIY", "KMG", "西安", "昆明"),
           ("KMG", "HAK", "昆明", "海口"),
           ("HAK", "HRB", "海口", "哈尔滨"),
           ("HRB", "HGH", "哈尔滨", "杭州")]


def _flight(price, plat, i, trans=None):
    code = f"{8800 + i}"
    f = {"price": price, "name": _AIRLINES[i % 5] + code,
         "code": _AIRLINES[i % 5][-2:] + code,
         "depTime": f"{6 + i // 3 % 12:02d}:{(i * 15) % 60:02d}",
         "arrTime": f"{9 + i // 3 % 12:02d}:{(i * 15 + 30) % 60:02d}",
         "_platform": plat}
    if trans:
        f["transCity"] = trans
        f["layover"] = 180
        f["totalDuration"] = "18时52分"
        f["arrTime"] = f"01:{(i * 7) % 60:02d}"
        f["transferBaggage"] = "direct"
    else:
        f.update({"cabin": "Y", "meal": "有小食", "prate": 86.4,
                  "plane": "738", "baggage": "20kg", "discount": "5.5折",
                  "labels": "含免费托运", "fewTicket": "余3张"})
    return f


def _route(fc, tc, fn, tn, ad=1900, at=1700):
    return Route(from_code=fc, from_name=fn, to_code=tc, to_name=tn,
                 dates=["2026-10-05"], alert_direct=ad, alert_transfer=at,
                 transfer_arrival_max="02:00", transfer_layover_min=90)


def _prices(route):
    out = []
    for d in route.dates:
        for pi in range(5):
            plat = _PLATS[pi % 5]
            fs = []
            for i in range(12):
                base = 1500 + (i * 37) % 900
                if i == 0:
                    fs.append(_flight(base, plat, i))
                elif i % 4 == 1:
                    fs.append(_flight(base + 200, plat, i, trans="西安"))
                else:
                    fs.append(_flight(base + 400, plat, i))
            out.append(FlightPrice(
                platform=plat, from_city=route.from_code,
                to_city=route.to_code, depart_date=d, price=fs[0]["price"],
                extra=json.dumps(fs, ensure_ascii=False),
                fetched_at="2026-09-29 14:00:00"))
    return out


def _digest(routes_prices, at="13800138000", monkeypatch=None):
    import report as _report
    if monkeypatch:
        monkeypatch.setattr(_report, "render_flights_table",
                            lambda *a, **k: None)
    a = Alerter(LOG, notifier=None, digest=True, at_mobile=at,
                platforms=list(_PLATS))
    return a._digest_payload(routes_prices, fresh=True)


def _prod12(monkeypatch=None, ad=1900, at=1700):
    rs = []
    for fc, tc, fn, tn in combo12:
        r = _route(fc, tc, fn, tn, ad=ad, at=at)
        secs = Alerter(LOG, notifier=None,
                       digest=True)._build_sections(r, _prices(r))
        rs.append((r, secs))
    return rs


def test_fallback_budget_and_at_floor(monkeypatch):
    """P1-1/P1-2：图挂兜底路径总量受构建端预算约束——兜底块超预算
    竞争让位（说明行在场），@手机号段地板预留恒落位（发送端 18000B
    截断不再触发、@ 触达不再随兜底路径蒸发）。"""
    p = _digest(_prod12(monkeypatch), monkeypatch=monkeypatch)
    desp = p["desp"]
    raw = len(desp.encode("utf-8"))
    # 构建端预算：15000B 头部 + 兜底头行/说明行/表头图行容差，
    # 发送端 18000B 截断点前留足安全带（修前实测 28296B）
    assert raw <= 16200, f"兜底路径 desp {raw}B 超构建端预算"
    assert "@13800138000" in desp, "@段被兜底块顶飞（地板预留失效）"
    assert "明细总表上传失败" in desp


def test_fallback_demote_note_when_over(monkeypatch):
    """兜底块竞争让位时出说明行（防「推送数据缺失」观感）：
    超预算形态必有「因超长让位」说明；预算内小数据形态不出。"""
    big = _digest(_prod12(monkeypatch), monkeypatch=monkeypatch)["desp"]
    assert "因超长让位" in big
    rs2 = _prod12(monkeypatch)[:2]
    small = _digest(rs2, monkeypatch=monkeypatch)["desp"]
    assert "因超长让位" not in small
    assert "TOP" in small or "直飞最优" in small   # 兜底明细本体在场


def test_title_no_anchor_tail_drop(monkeypatch):
    """P2-1：锚点缺席（全部未设阈值）title 超限时逐条丢清单尾条——
    钉钉 [:60] 字符静默截的切点不再落在条目中间。"""
    rs = _prod12(monkeypatch, ad=0, at=0)
    p = _digest(rs, monkeypatch=monkeypatch)
    t = p["title"]
    assert len(t) <= 60, f"title {len(t)} 字符超钉钉硬截断上限"
    # 丢尾条后末条目完整（非「上→乌 10/05」半条形态）：
    # 尾部要么是完整条目（末段含日期短语），要么是状态前缀
    assert t.endswith(("05", "06")) or "｜" not in t


def test_section_title_long_city_trim():
    """P2-2：小节标题末档（城市名本体超宽）逐侧截尾——长自定义名
    极端形态标题行 60/40 曾不受控；截后标题行与引用行均 ≤40 半角。"""
    t = Alerter._section_title(
        "十二字超长自定义城市名甲乙丙", "另一个十二字超长城市名丁戊己",
        "10/05~10/06", " 06:00-09:00 出发")
    for ln in t.split("\n\n"):
        assert _dw(ln.rstrip()) <= 40, f"超宽行: {ln!r}"


def test_legacy_price_line_fit():
    """P2-3：legacy 价格行走 _fit_line——去抖涨跌注在场曾 47/40
    （全链唯一没走守卫的动态行）。真执行：涨跌注让位、价格判据
    地板档恒落；源码钉辅助锁降级链在位。"""
    from core.alerter import _fit_line
    base = "**价格**：￥1737（线￥1700）"
    out = _fit_line(f"- {base}（较上次推送降 ￥63）",
                    fallbacks=[f"- {base}", "- ￥1737"])
    assert _dw(out) <= 40
    assert out == f"- {base}"   # 涨跌注让位、判据保全
    assert _fit_line("- ￥1737", fallbacks=["- ￥1737"]) == "- ￥1737"
    src = open("core/alerter.py", encoding="utf-8").read()
    assert "_fit_line(f\"- {_pbase}{diff_txt}\"" in src
    assert 'f"- ￥{f[\'price\']:.0f}"' in src   # 地板档在案


def test_webui_test_push_copy():
    """P2-4：webui 测试推送词面——H1 级弃用（#### 纪律）、正文行
    ≤40 半角。"""
    import webui as _w
    src = open(_w.__file__, encoding="utf-8").read()
    assert '"# ✅ 测试推送成功' not in src   # 旧 H1 词面（引号锚防 #### 子串误伤）
    assert "#### ✅ 测试推送成功" in src


def test_trend_single_point_centered():
    """M-3：单轮窗数据点居中（webui JS 同场景 0.5 同语言）——
    i/(N-1) 在 N==1 退化 0 曾把单点画在左轴上。"""
    src = open("report.py", encoding="utf-8").read()
    assert "if len(series) > 1 else 0.5" in src
