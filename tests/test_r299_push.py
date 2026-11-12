# -*- coding: utf-8 -*-
"""r299 推送层四案（TDD 先行；立案=P3-A/B/C/D 备案族翻身，用户指令
「P3 备案族维持全做」）：

P3-A #### 标题加粗字模入模型：msyh 加粗对 ASCII advance 膨胀（实测
纯数字串 1.111，CJK 方块字两权重恒 1.0）——两路 #### 标题族
（日报 _route_section_title / 告警 _section_title）的判定从「模型
38=40 减 2 缓冲」代理升级为「加粗投影宽直接对 40 预算判」（_dw_bold：
ASCII 因子 Pillow 实测校准，字体缺席回退保守常量）。纯 CJK 标题
38-40 段不再被一刀切降档（加粗不膨胀=真放得下），数字密集 38 段
投影可 >40 的如实降档（实测 1.111 下模型 38 纯数字标题加粗 42.2，
旧代理放行=窄屏折行实险）。

P3-B 日报构建端字节预算（地板档总额预留制，二十五§2）：钉钉发送端
硬顶 18000B（含截断尾注），构建端预算 16000B——全量档超预算时按序
降级为地板档（标题+KPI 摘要行+查现价链接核心判据恒落位），留痕行
防「推送数据缺失」观感；全量档预算内逐字节不变（门判据=产物变短，
三十§10 生效域门控）。

P3-C 日报池混合池第二层守卫（三十§9b 能力对称）：日报池构建器此前
只有分类池（直飞/中转分组）孤低价标记——双渠道同轮毒价互抬锚可穿透
（锚供给薄时两毒价互相进 others 压住中位）；补混合池第二遍（与告警
链同序同函数：分类标后、收集剔除前，对 _xphan 互抬对双拦）。

P3-D 日报「各渠道最低」同价合并判据同构（三十§3）：合并条件从「纯
价格相等」升级为「_fmt_brief 逐字相等」（与告警链 _channel_market_lines
同律）——纯价格相等曾把不同班并成一行丢航班身份；身份随 brief 在行，
价格相等而班次不同维持逐渠道行如实分列。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r299_push.py -q
"""
import sys
import os

sys.path.insert(0, os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))

import core.alerter as alerter
import report
from core.alerter import Alerter, dep_win_txt, _dw as _dw_line


# ---------------- P3-A 加粗字模入模型 ----------------

def test_bold_factor_fallback_in_range():
    """校准因子在保守带内：Pillow 实测（Windows msyh）或回退常量，
    两态都须落在 [1.05, 1.15]（实测 1.111；回退档须 ≥ 实测才保守）。"""
    f = alerter._TITLE_BOLD_ASCII
    assert 1.05 <= f <= 1.15, f


def test_dw_bold_ascii_inflates_cjk_not():
    """投影模型形态：ASCII 字符乘因子、CJK 方块字与全角标点不乘
    （CJK 加粗 advance 恒等是实测结论，不是近似）。"""
    import core.alerter as _a
    mono_cjk = _a._dw_bold("上海→海口")
    assert mono_cjk == _dw_line("上海→海口"), (mono_cjk, _dw_line("上海→海口"))
    assert _a._dw_bold("01/29") > _dw_line("01/29")


def test_daily_title_known_inline_nonregression():
    """生产词面非回归：r296 案1 样本（模型 37、ASCII 10 单位）在真实
    因子下加粗投影 ≈38.1 ≤40——内联档维持。"""
    out = report._route_section_title(
        ("上海", "海口"), "2027-01-29", dep_win=dep_win_txt("19:00", ""))
    assert out.split("\n\n")[0] == "#### 上海→海口 01/29（19:00后出发）", out


def test_daily_title_digit_heavy_demoted(monkeypatch):
    """行为牙齿：因子放大后数字密集标题投影破 40 必须降档（窗下沉
    引用行）——旧模型 38 代理对此恒放行（模型积分不带字模）。"""
    monkeypatch.setattr(alerter, "_TITLE_BOLD_ASCII", 1.6)
    out = report._route_section_title(
        ("机场", "机场东"), "2027-01-29", dep_win=dep_win_txt("07:00", "09:00"))
    first = out.split("\n\n")[0]
    assert "（07:00–09:00）" not in first, out  # 窗不再内联
    assert "> " in out and "07:00" in out, out  # 窗在引用行完整保留


def test_daily_title_pure_cjk_gains_margin(monkeypatch):
    """模型变准的方向二：因子=1.0（CJK 加粗零膨胀的实测外推）时投影
    =模型宽——40 预算内模型 39 标题内联（旧 38 代理降档为标题+引用行
    两段）。"""
    monkeypatch.setattr(alerter, "_TITLE_BOLD_ASCII", 1.0)
    nm_a, nm_b = "春" * 7, "秋" * 6   # 本体 5+26+箭头 2=33，加日期 6=39
    out = report._route_section_title((nm_a, nm_b), "2027-01-29")
    assert out.split("\n\n")[0] == f"#### {nm_a}→{nm_b} 01/29", out


def test_alert_title_same_law_real_and_model(monkeypatch):
    """告警侧同律（两路 #### 标题族同源）：现行实态=带数字窗的标题
    投影 40.3>40 → 窗下沉引用行（38 代理时代同形，非回归）；因子=1.0
    （模型准确侧）投影=模型 39 ≤40 → 窗内联——降档边界随真实字模
    走而非一刀切常量。"""
    out = Alerter._section_title("上海", "海口", "01/29", "（19:00后出发）")
    assert out == "#### ✈️ 上海→海口 01/29\n\n> （19:00后出发）\n\n", out
    monkeypatch.setattr(alerter, "_TITLE_BOLD_ASCII", 1.0)
    out1 = Alerter._section_title("上海", "海口", "01/29", "（19:00后出发）")
    assert out1 == "#### ✈️ 上海→海口 01/29（19:00后出发）\n\n", out1


def test_title_floor_bold_fits():
    """地板档恒达标：病理长名双侧逐字截后，加粗投影 ≤40（裁剪房按
    投影模型扣预算——投影超预算的标题族不出地板越线形态）。"""
    long_nm = "测" * 30
    out = report._route_section_title((long_nm, long_nm), "2027-01-29")
    first = out.split("\n\n")[0]
    assert alerter._dw_bold(first) <= 40, (first, alerter._dw_bold(first))


# ---------------- P3-B 构建端字节预算 ----------------

def test_budget_all_fit_byte_identical():
    """全量档预算内：逐字节原样（生效域门控——门判据=产物变短，
    非截断轮零变形）。"""
    blocks = [("A块\n\n", "A地\n\n"), ("B块\n\n", "B地\n\n")]
    out = report._daily_byte_budget("H\n\n", blocks, "T\n\n")
    assert out == "H\n\nA块\n\nB块\n\nT\n\n"


def test_budget_degrades_to_floors_with_note():
    """超预算：装不下的全量档降级为地板档（标题+价格判据恒在场），
    留痕行说明精简面；总字节 ≤ 预算。"""
    full = "明" * 4000 + "\n\n"          # ~8001B
    floor = "#### 上海→海口 01/29\n\n> 直飞 ￥1700 差￥250\n\n[🔍 查现价](u)\n\n"
    blocks = [(full, floor), (full, floor), (full, floor)]
    out = report._daily_byte_budget("H\n\n", blocks, "T\n\n", budget=12000)
    assert out.encode("utf-8").__len__() <= 12000
    assert out.count("#### 上海→海口 01/29") == 3      # 三节标题恒在场
    assert "已精简" in out                              # 留痕行
    assert "[🔍 查现价](u)" in out                      # 链接判据恒在场


def test_budget_floor_reserve_never_swallowed():
    """预留制不变量：地板档总额先扣，全量档在剩余空间竞争——首块
    全量装得下装、末块全量必让位地板，任何一节的价格行不随载体陪葬。"""
    full = "明" * 4000 + "\n\n"
    floor = "F\n\n"
    blocks = [(full, floor), (full, floor), (full, floor)]
    out = report._daily_byte_budget("H\n\n", blocks, "T\n\n", budget=11000)
    assert out.count("F\n\n") >= 1                      # 至少一节落地板
    assert out.startswith("H\n\n") and out.endswith("T\n\n")


# ---------------- P3-C 混合池第二层 ----------------

def test_mixed_pool_second_layer_catches_cross_lift():
    """互抬对机制（与告警链同序列同函数）：分类池（直飞/中转分组）
    两毒价互相压锚双逃；混合池补层后锚供给变宽双拦。"""
    def _row(pl, price, trans):
        return {"_platform": pl, "price": price,
                "transCity": "" if not trans else "郑州"}

    directs = [_row("qunar", 700, False), _row("ctrip", 700, False)]
    trans = [_row("fliggy", 2100, True), _row("tuniu", 2200, True)]
    # 分类池两遍（日报构建器既有序列）：直飞组/中转组各自标记
    for _g in (directs, trans):
        Alerter._mark_xchan(_g)
    assert not any(f.get("_xphan") for f in directs + trans), "分类池应双逃"
    out = directs + trans
    Alerter._mark_xchan(out)                            # 混合池补层
    assert [f["_platform"] for f in out if f.get("_xphan")] == \
        ["qunar", "ctrip"], "混合池应双拦互抬对"


def test_daily_builder_wires_mixed_layer():
    """接线钉：日报池构建器的标记序列=分类循环+混合池单遍（源码钉
    ——行为面由上测与告警链同函数保证）。"""
    src = open(report.__file__, encoding="utf-8").read()
    assert src.count("Alerter._mark_xchan(out)") == 1, "混合池补层未接线"


# ---------------- P3-D 同价合并判据同构 ----------------

def _mkt_row(code, dep="15:30", arr="18:55"):
    return {"code": code, "name": "国航" + code, "price": 1700,
            "depTime": dep, "arrTime": arr, "transCity": ""}


def test_market_merge_carries_identity():
    """同价且同班（brief 逐字相等）：合并单行、身份随 brief 在行
    （「- 两渠道 最低 国航CA8573 15:30-18:55 ￥1700」族）。"""
    pmins = {"qunar": (1700, True), "ctrip": (1700, True)}
    row = _mkt_row("CA8573")
    out = report._daily_market_fallback(
        pmins, {"qunar": row, "ctrip": dict(row)})
    assert "渠道 最低" in out, out
    assert "CA8573" in out, out                          # 航班身份在行
    first = out.rstrip("\n").splitlines()[0]
    assert _dw_line(first) <= 40, (first, _dw_line(first))


def test_market_same_price_diff_flights_keeps_rows():
    """价格相等而班次不同：不合并（纯价格判据曾把不同班并成一行丢
    身份）——逐渠道行如实分列。"""
    pmins = {"qunar": (1700, True), "ctrip": (1700, True)}
    out = report._daily_market_fallback(
        pmins, {"qunar": _mkt_row("CA8573"),
                "ctrip": _mkt_row("MU5137", dep="09:00", arr="12:20")})
    assert "渠道 最低" not in out, out
    assert "CA8573" in out and "MU5137" in out, out


def test_market_merge_without_rows_falls_back_price_lines():
    """行缺席防御（best_rows=None 旧调用形态）：维持逐渠道价格行，
    不产出无身份合并行。"""
    pmins = {"qunar": (1700, True), "ctrip": (1700, True)}
    out = report._daily_market_fallback(pmins)
    assert "渠道 最低" not in out, out
    assert "￥1700" in out, out


# ---------------- W1/W2 配置页语义配色（用户实报） ----------------

def test_cfg_platform_pills_channel_colors():
    """W1：配置页渠道胶囊按渠道识别色着装——五颗同蓝不可辨（语义
    配色审计维度）。模板带 pch+p-{plat} 类与渠道点；五渠道「浅底+色
    边+原色点」三件套规则在场；--c-* 令牌全渠道齐。"""
    import webui
    src = webui.PAGE
    assert 'class="chip pch p-${p}' in src, "胶囊模板未挂渠道类"
    assert '${srxPlatIcon(p)}${PLATS[p]}' in src, "渠道官方图标缺席"
    for p in ("qunar", "fliggy", "ctrip", "tongcheng", "tuniu"):
        assert (".chip.pch.p-" + p + ".on{background:color-mix" in src), p
        assert (".chip.pch.p-" + p + ".on .pdot{background:var(--c-"
                + p + ")}") in src, p


def test_route_head_color_semantics():
    """W2：航线头颜色跟读者视线走——中文名上蓝主色、三字码弱化灰
    （旧态：rtcode 蓝占色、城市名单色黑白）。"""
    import webui
    src = webui.PAGE
    rt = [ln for ln in src.splitlines() if ln.strip().startswith(".rtcode{")]
    assert rt and "var(--mut)" in rt[0] and "var(--blue)" not in rt[0], rt
    assert ".rhead>b{color:var(--blue)}" in src, "城市名未上主色"
