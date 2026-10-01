# -*- coding: utf-8 -*-
"""推送层精修批钉（推送审校 P2×2）。

P2-1 明细总表「中转」列主行城市名限宽：二段衔接行走 _fit_text
（限宽自适应降号+截断）而主行 d.text 直绘无限宽——同列两种语言，
超长城市名会叠字出列。统一走 _fit_text 同列同语言。
P2-2 _rest_seg 单条超长装不下时整段静默丢（shown 空 return title，
无「等N条」留痕）——「另监控」辅信息归零且读者不知有未列入项；
预算内挂计数留痕，title 本身近满时维持裸 title（整行预算地板）。
"""


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
