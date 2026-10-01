# -*- coding: utf-8 -*-
"""WebUI 审计修复五件（_scratch/r263_webui_audit.md 立案，TDD 先行）：

F1 启动恢复对 jpmontab 脏值无白名单——localStorage 回退段直通
   showMonTab，非法 tab 名（版本升级改名残留）令四 pane 全隐=空白
   死区，且脏值写进 hash 二次刷新仍死循环永不自愈（hash 段白名单
   已在，localStorage 段对齐同款）。
F2 筛选抽屉 .flab 开关行 label 文字区触控热区 20px<36px 基准——
   三触控块（≤900coarse/901+coarse/≤760）只补了开关本体
   （.switch::before），label 本体漏收（coarse 390/820/1366 实测）。
F3 390 档 #montabs 3px 隐藏溢出低于 xhint 判定阈值(+4)——末位 tab
   微裁无横滚暗示；布局级修复（mtab 横向 padding 收 1px 消溢出），
   不动判定阈值（阈值复核 6 处防 1px 抗锯齿误挂的面更大）。
F4 走势图跨天分隔竖线+日期标签取警示色 --stl——时间参考线混入
   警示色族与中转达标琥珀虚线语义竞争；竖线中性化 --line2、标签
   文字 --mut（线条档/文字档各归其位）。
F5 走势图网格线专用 --grid 令牌——--line(1.29:1) 偏隐接近有等于
   无，亮/暗谱各提半档至 1.8:1 档（装饰豁免线，骨架感立现不与
   数据线竞争）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_webui_fixes.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _page_src():
    import webui
    return webui.PAGE


# ---------- F1: 启动恢复 localStorage 白名单 ----------

def test_restore_whitelists_localstorage_tab():
    """hash 段白名单已在（防任意 hash 注入）；localStorage 回退段
    同律：脏 tab 名经白名单过滤，不合法一律落空（overview 缺省）。"""
    src = _page_src()
    i = src.index("启动恢复")
    seg = src[i:src.index("hashchange 消费", i)]
    # localStorage 值消费点必须过白名单（脏值全隐 pane=空白死区死循环）
    assert "localStorage.getItem('jpmontab')" in seg
    assert (".indexOf(localStorage.getItem('jpmontab'))>=0"
            "?localStorage.getItem('jpmontab')") in seg, (
        "localStorage 回退段未过白名单：非法 jpmontab 直通 showMonTab "
        "令四 pane 全隐，且脏值写 hash 后二次刷新仍死循环")


# ---------- F2: .flab label 触控热区（三触控块家族） ----------

def test_flab_label_hotzone_three_blocks():
    """三触控块同值补档：.flab{position:relative}+.flab::after 外扩
    （纵向 -8px 吃满 frow 行距、横向 -4px 同 .md a 先例防吃邻件）。
    计数钉锁「受控枚举」：新增触控档时随族 +1 并改钉。"""
    src = _page_src()
    assert src.count(".flab{position:relative}") == 3, (
        "flab 热区补档家族计数=%d（应 3：≤900coarse/901+coarse/≤760）"
        % src.count(".flab{position:relative}"))
    assert src.count(
        ".flab::after{content:'';position:absolute;inset:-8px -4px}") == 3


# ---------- F3: 390 档 #montabs 消除 3px 隐藏溢出 ----------

def test_montabs_390_padding_tightened():
    """390 块 #montabs .mtab 横向 padding 收 2px（10→8，五件省 16-20px
    消 3px 溢出）；必须 ID 特异性——基础块 #montabs .mtab (1,1,0) 恒压
    类选择器 (0,2,0)（LESSONS 触控家族同款判例），声明序在后同特异性
    胜出。"""
    src = _page_src()
    i = src.index("@media(max-width:390px){#montabs")
    seg = src[i:src.index("@media", i + 40)]
    assert "#montabs .mtab{padding:9px 8px}" in seg, (
        "390 块缺 ID 特异性 mtab padding 收窄：#montabs 3px 隐藏溢出"
        "低于 xhint 阈值(+4)，末位 tab 微裁且无横滚暗示")


# ---------- F4: 跨天分隔竖线/日期标签中性化 ----------

def test_trend_dayline_neutral_color():
    """竖线 --stl(警示)→--line2(线条)、日期标签 →--mut(文字档)；
    --stl 回归「衔接警示」语义独占。"""
    src = _page_src()
    i = src.index("ctx.globalAlpha=.45")
    seg = src[i:i + 700]
    assert "--stl" not in seg, "跨天分隔竖线/日期标签仍取警示色 --stl"
    assert "cssv('--line2')" in seg
    assert "cssv('--mut')" in seg


# ---------- F5: 网格线专用 --grid 令牌 ----------

def test_grid_token_defined_both_schemes():
    src = _page_src()
    # 亮谱 + 暗谱各一份定义
    assert src.count("--grid:") >= 2, (
        "--grid 令牌须亮/暗谱各一份定义（消费带×定义带分离纪律）")


def test_grid_consumed_not_line():
    src = _page_src()
    i = src.index("const GRID=")
    seg = src[i:i + 120]
    assert "cssv('--grid')" in seg, (
        "网格线仍取 --line(1.29:1) 偏隐：应走 --grid 提半档令牌")
