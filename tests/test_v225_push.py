# -*- coding: utf-8 -*-
"""r225 推送层六案回归（审校 P2 清单落地）：
P1 总表单元格文本统一过 _no_emoji（潜伏 tofu 防线）；
P2 心跳/主链 KPI 行1 百分比降级链收单源 helper（「·pct」中间档补齐，
调用点内联 fallback 列表是档序悄悄回退的温床——源码钉锁调用点）；
P3 总表档位色词条前移 summary 盒尾（首屏琥珀价有解码）+ 底部图例
首行退役四档词条（词面单源四方同语言不破）；
P4 report.py 点环小注注释正名（「真达标」现役词）；
P5 _p7_note 空小节 3 连 DB 回算收单算。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v225_push.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import report  # noqa: E402


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
    一致零漂移）。"""
    assert report._TBL_TIER_LEGEND == (
        "深绿=真达标 · 描绿=行情破线 · 琥珀=擦边 · 深蓝=超线")


def test_bottom_legend_tier_entries_retired():
    """底部图例首行退役四档词条只留衔接警示色（词条前移不复制——
    同词面两处消费点违十六§3b 单源律）。"""
    src = open("report.py", encoding="utf-8").read()
    assert "橙红=衔接不足 · 绿停时=衔接达标" in src
    assert "深蓝={TIER_FULL['over']} · 橙红" not in src


# ---- P2: KPI 行1 百分比降级链单源 helper ----

def test_pct_fallback_forms_three_tiers():
    """三档形态：全角括号态 → 间隔号态 → 地板态；pct 空（<1% 省略）
    三档同形（首档恒达标）。主链 _kpi_block 与心跳两分支同源。"""
    from core.alerter import _pct_fallback_forms
    b = "🟨直飞 ￥1760　线￥1900　低￥140"
    assert _pct_fallback_forms(b, "7%") == [b + "（7%）", b + "·7%", b]
    assert _pct_fallback_forms(b, "") == [b, b, b]


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
    """空小节补偿行 _p7_note() 由 3 连调收单算：每个空分支头局部变量
    化（源码钉：2 处赋值形态 + 1 处既有 _p7_note(False) 调用）。"""
    src = open("report.py", encoding="utf-8").read()
    assert src.count("p7 = _p7_note()") == 2, src.count("p7 = _p7_note()")
    # 4 = def 行 1 + 两分支赋值 2 + 未设线档 _p7_note(False) 1
    assert src.count("_p7_note(") == 4, src.count("_p7_note(")
