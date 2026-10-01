# -*- coding: utf-8 -*-
"""fliggy 舱位标签（价格行行尾舱位词）落地钉。

冻结快照实证新形态：span.discount 文本为舱位词（CA8564「¥9900
商务舱」，该行唯一报价=商务舱价），裸落库后明细受众无从辨识舱位、
易误读为经济舱天价。提取=价格行分支行尾四舱位词匹配；「全价」
满值形态天然不匹配（discount「N折」值域协议与 cabin 双零误配）。
"""

from crawlers.fliggy import FliggyCrawler


def _row(txt):
    rows = FliggyCrawler._parse_pc_text(txt, "2026-10-05")
    assert rows, txt
    return rows[0]


def test_fliggy_cabin_price_row_trailing_word():
    """价格行「¥9900 商务舱」行尾舱位词 → extra.cabin 落键。"""
    r = _row("海航HU7145\n中型机 788\n15:15\n21:30\n"
             "乌鲁木齐天山国际机场\n虹桥国际机场T2\n¥9900 商务舱")
    assert r["cabin"] == "商务舱"
    assert r["price"] == 9900.0
    # 舱位词不含「N折」→ discount 不被误配
    assert "discount" not in r


def test_fliggy_cabin_fullprice_form_no_cabin():
    """「全价」满值形态：不落 cabin（宁缺勿错）；discount 落「全价」
    （无折扣可售真值，qunar/tuniu/tongcheng 同域同词面，消费端
    discount_txt 单源守卫放行）。"""
    r = _row("国航CA8564\n中型机 320\n15:15\n21:30\n"
             "乌鲁木齐天山国际机场\n虹桥国际机场T2\n¥2400 全价")
    assert "cabin" not in r
    assert r["discount"] == "全价"


def test_fliggy_cabin_whole_line_branch_kept():
    """既有整行舱位词分支保持兼容；价格行舱位词不覆盖已有值。"""
    r = _row("海航HU7145\n中型机 788\n15:15\n21:30\n"
             "乌鲁木齐天山国际机场\n虹桥国际机场T2\n"
             "商务舱\n¥9900 5.0折")
    assert r["cabin"] == "商务舱"
    assert r["discount"] == "5.0折"


def test_fliggy_cabin_dual_price_row_dropped():
    """双价行（跨舱位并列，CA8564「¥9900 商务舱/¥3960」谱系）：取低者
    为主价时必须撤 cabin——首价格行的舱位词不得标注来自第二行的低价，
    否则落库即成「商务舱 ¥3960」持久化误导。"""
    r = _row("国航CA8564\n中型机 320\n15:15\n21:30\n"
             "乌鲁木齐天山国际机场\n虹桥国际机场T2\n¥9900 商务舱\n¥3960")
    assert r["price"] == 3960.0
    assert "cabin" not in r
