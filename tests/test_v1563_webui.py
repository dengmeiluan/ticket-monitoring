"""webui 回归钉： P2 三项落地。

①P2-1 配置搜索登录卡（.lgcard）并入字段级过滤——复位清单与搜索首循环
两处同步（搜索态非命中登录卡整版滞留，把真命中顶出首屏）；
②P2-2 亮色 AA 残尾三处（.okTxt/.upill.warn/.hbadge.mid 换深令牌，
暗色 --warn≡--warn-deep 同值故暗色覆写删）；
③P2-3 通知详情页 NOTIFY_PAGE esc 补 > 转义（与主页 esc 同律，
 既有备案收口）。
"""

from webui import NOTIFY_PAGE, PAGE


def test_cfgfilter_lgcard_in_both_lists():
    """：#cfgview .lgcard 必须同时出现在复位清单与搜索首循环。
    （r275 起复位清单新增孤儿头显隐成员并重组——按「lgcard 在两处
    清单」的意图断言，不再锁整串字面）"""
    clear_i = PAGE.find("function cfgSearchClear")
    filter_i = PAGE.find("function cfgFilter(")   # 带括号防前缀误中 cfgFilterD
    assert clear_i > 0 and filter_i > clear_i, "cfgSearchClear/cfgFilter 缺"
    assert PAGE[clear_i:filter_i].count("#cfgview .lgcard") == 1, \
        "复位清单未含 .lgcard"
    loop_i = PAGE.find("#cfgview .glgrid>div,#cfgview .srow,#cfgview .lgcard")
    assert loop_i > 0, "搜索首循环未并入 .lgcard"
    # 命中判定沿用 textContent+inputs 现成逻辑（lgcard 无 input 亦可）


def test_aa_light_tail_deep_tokens():
    """：三处亮色小字换 --ok-txt/--warn-deep；暗色覆写删除
    （--warn 与 --warn-deep 暗色同值 #d9b34a，覆写纯冗余）。"""
    assert ".okTxt{color:var(--ok-txt)" in PAGE
    assert ".upill.warn{color:var(--warn-deep)" in PAGE
    assert ".hbadge.mid{color:var(--warn-deep)" in PAGE
    assert 'html[data-theme="dark"] .upill.warn' not in PAGE


def test_notify_esc_gt():
    """/：NOTIFY_PAGE esc 与主页 esc 同序补 &gt;（& < > " '）。"""
    assert '.replace(/>/g,"&gt;")' in NOTIFY_PAGE
    # 主页 esc 本就齐全，防两处漂移
    assert ".replace(/>/g,'&gt;')" in PAGE
