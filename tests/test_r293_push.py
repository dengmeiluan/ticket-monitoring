# -*- coding: utf-8 -*-
"""r293 推送审校 P3-1（TDD 先行，审校报告 _scratch/worker_r293_push.md）：

达标行价格绿 C_QUAL 在达标行浅绿底 (238,249,242) 上 4.47:1——差
0.03 未达 AA 正文档（16px 常规字重不构成大字豁免）。修法=行底提亮
(242,250,246)（单点改善该带全部色对；勿动 C_QUAL 全局值——与 webui
--green 同值同注释，牵一发双端，LESSONS 十六§3）。

钉面：WCAG 公式复算总表图全部「文字/图形 × 实际衬底」候选色对
≥4.5（图形档描边族按 ≥3 线单列）。达标行底是内联字面量，钉从源码
正则提取真值（调色日钉跟着新值复算，防回归）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r293_push.py -q
"""
import inspect
import re

import report


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
