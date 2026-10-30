# -*- coding: utf-8 -*-
"""r296 推送层：日报小节标题接时段窗（能力对称收编）+ #### 标题
38 缓冲对称。

背景：告警侧 _section_title 已有 dep_win 三档（内联 ≤38 / head-only
+引用行下沉 / 裁剪房 38 逐字截+日期窗合并下沉）；日报侧
_route_section_title 同为 #### 标题（钉钉渲染加粗字模宽于计量模型，
r295 P3-E 判例）却停在 40 阈值且无时段窗——日报读者对「为何只见
晚间班」无解释（日报/告警双端真实产物实证：同航线同日期告警侧
「#### ✈️ …（19:00后出发）」在案、日报侧裸标题在案）。本轮：
dep_win 词面抽单源 dep_win_txt 两端共用；_route_section_title 三档
对齐告警侧（38 阈值）。_miss_chart_line 是 "> ⚠️" 引用行形态
（常规字模）不适用 #### 加粗字模判例，维持 40 不收编。"""
from core.alerter import _dw, dep_win_txt
from report import _route_section_title


# ---------- dep_win_txt 词面单源 ----------

def test_dep_win_txt_forms():
    """三形态与告警侧原内联构造逐字等价（抽函数零词面漂移）。"""
    assert dep_win_txt("19:00", "") == "（19:00后出发）"
    assert dep_win_txt("08:00", "22:00") == "（08:00–22:00）"
    assert dep_win_txt("", "22:00") == "（00:00–22:00）"
    assert dep_win_txt("", "") == ""
    # 配置带秒形态 [:5] 截断（告警侧原行为）
    assert dep_win_txt("19:00:00", "") == "（19:00后出发）"
    assert dep_win_txt(None, None) == ""


# ---------- 窗词面手抄残留收口（Soldier M-1） ----------

def test_push_title_depwin_no_handbuilt_residual():
    """推送标题链（_push_digest 未达标/已达标标题）的窗词面裸构造
    已收编 dep_win_txt 单源——残留计数钉（十六§3b 裸表达式残留
    收口）：`f"（{lo[:5]}` 形态（无下划线局部名的手抄构造）全文
    零残留；dep_win_txt 定义处用 _lo 命名不在锁面。"""
    src = open("core/alerter.py", encoding="utf-8").read()
    assert src.count('f"（{lo[:5]}') == 0
    assert src.count('f"（{lo}') == 0


# ---------- _route_section_title 接时段窗 ----------

def test_route_title_short_inline_with_win():
    """档1：标题+窗总宽 ≤38 内联（「#### 上海→海口 01/29（19:00
    后出发）」实宽 37）。"""
    out = _route_section_title(("上海", "海口"), "2027-01-29",
                               dep_win="（19:00后出发）")
    assert out == "#### 上海→海口 01/29（19:00后出发）\n\n"
    assert _dw(out.rstrip()) <= 38


def test_route_title_sinks_win_when_over():
    """档2：head ≤38 而 head+win >38（5 字名+窗实宽 43>38，head-only
    28）→ 窗下沉引用行（告警侧同构：日期在标题、窗独立引用行）。"""
    out = _route_section_title(("乌鲁木齐南", "海口"), "2027-01-29",
                               dep_win="（19:00后出发）")
    assert out == "#### 乌鲁木齐南→海口 01/29\n\n> （19:00后出发）\n\n"
    assert _dw(out.split("\n\n")[0]) <= 38


def test_route_title_long_name_floor_merges_win():
    """档3：本体超宽（双侧长自定义名）→ 逐字截 + 日期与窗合并
    同一条引用行（告警侧 sub=d_span+dep_win 同律：日期是跨天辨识
    信息不可丢，窗是过滤解释，两段都只在引用行承载）。"""
    out = _route_section_title(
        ("乌鲁木齐（地窝堡）", "上海（虹桥+浦东）"), "2027-01-29",
        dep_win="（19:00后出发）")
    lines = [ln for ln in out.split("\n\n") if ln]
    assert lines[0].startswith("#### ")
    assert _dw(lines[0]) <= 38
    assert "01/29" in lines[1]
    assert "19:00后出发" in lines[1]


def test_route_title_no_win_zero_regression():
    """无窗（默认参）：短名单行——与旧版逐字一致。"""
    assert _route_section_title(("上海", "海口"), "2027-01-29") == \
        "#### 上海→海口 01/29\n\n"


def test_route_title_sink_threshold_38():
    """38 缓冲对称：39-40 带（#### 加粗字模判例投影日报侧）——
    head 实宽 40（5+28+1+ceil(5.5)）→ 标题保名、日期下沉（旧档
    行为）；窗并入同一条引用行。"""
    out = _route_section_title(("七字城市名甲乙丙", "四字城市名"),
                               "2027-01-29", dep_win="（19:00后出发）")
    assert _dw("#### 七字城市名甲乙丙→四字城市名 01/29") == 40
    assert out == ("#### 七字城市名甲乙丙→四字城市名\n\n"
                   "> 01/29（19:00后出发）\n\n")


def test_route_title_win_sink_head38():
    """档2 实证：head ≤38（恰卡 38=5+26+1+6）而 head+窗 >38 →
    日期在标题、窗独立引用行下沉。"""
    out = _route_section_title(("七字城市名甲乙丙", "三字城市"),
                               "2027-01-29", dep_win="（19:00后出发）")
    assert _dw("#### 七字城市名甲乙丙→三字城市 01/29") == 38
    assert out == ("#### 七字城市名甲乙丙→三字城市 01/29\n\n"
                   "> （19:00后出发）\n\n")


def test_route_title_inline_37_zero_regression():
    """≤38 仍内联（首档活档非恒下沉）：实宽 37（ceil(37.0)）的
    短名+窗形态内联单行。"""
    out = _route_section_title(("上海", "海口"), "2027-01-29",
                               dep_win="（19:00后出发）")
    assert _dw("#### 上海→海口 01/29（19:00后出发）") == 37
    assert out == "#### 上海→海口 01/29（19:00后出发）\n\n"
