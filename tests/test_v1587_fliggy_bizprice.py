# -*- coding: utf-8 -*-
"""fliggy 双价行高档舱价 → bizPrice 落地钉（渠道调研 F1 转正）。

dump 实证：CA8564「¥9900 商务舱 / ¥3960」跨舱位并列双价行，9900 与
tongcheng bizPrice「商务舱 9900」同值跨渠道互证（CZ6975 2880 同）。
双价行取低者为主价时，高价带行尾高档舱词（公务/商务/头等）即落
bizPrice（与 qunar/tuniu/tongcheng 同键同协议 int）；无词高价（同舱
双价/「全价」满值）与经济舱词宁缺勿错不落；单报价行主价即高档舱价，
bizPrice 不重复记账。
"""

from crawlers.fliggy import FliggyCrawler


def _row(txt):
    rows = FliggyCrawler._parse_pc_text(txt, "2026-10-06")
    assert rows, txt
    return rows[0]


_HEAD = "国航CA8564\n中型机 320\n15:15\n21:30\n乌鲁木齐天山国际机场\n虹桥国际机场T2\n"


def test_bizprice_high_first_with_word():
    """高价在前带舱位词：主价取低、高价落 bizPrice、cabin 撤键不变。"""
    r = _row(_HEAD + "¥9900 商务舱\n¥3960\n订票")
    assert r["price"] == 3960.0
    assert r["bizPrice"] == 9900 and isinstance(r["bizPrice"], int)
    assert "cabin" not in r


def test_bizprice_low_first_high_with_word():
    """低价在前、高价行带词：词跟随本行报价，同样落 bizPrice。"""
    r = _row(_HEAD + "¥3960 4.5折\n¥9900 商务舱\n订票")
    assert r["price"] == 3960.0
    assert r["bizPrice"] == 9900
    assert "cabin" not in r


def test_bizprice_no_word_high_not_booked():
    """无词/「全价」满值高价：高档舱归属无佐证，宁缺勿错不落。"""
    r = _row(_HEAD + "¥9900 全价\n¥3960 4.5折\n订票")
    assert r["price"] == 3960.0
    assert "bizPrice" not in r


def test_bizprice_economy_word_not_booked():
    """经济舱词高价：不属高档舱域，不落 bizPrice。"""
    r = _row(_HEAD + "¥9900 经济舱\n¥3960\n订票")
    assert r["price"] == 3960.0
    assert "bizPrice" not in r


def test_bizprice_three_price_rows_converge():
    """第三个价格行：bizPrice 恒为带词高档价中最低（协议=高档舱最低
    参考价，qunar businessClassMinPrice/tuniu ADT 最低 baseFare 同
    语义），不随后续无词行回撤。"""
    r = _row(_HEAD + "¥9900 商务舱\n¥5000\n¥3960\n订票")
    assert r["price"] == 3960.0
    assert r["bizPrice"] == 9900


def test_bizprice_two_worded_rows_take_lowest():
    """两档带词高档行（假想 ¥9900 商务舱＋¥12000 头等舱）：取最低档
    ——取 max 会成「公务￥头等价」舱名数值双误（Soldier M4）。"""
    r = _row(_HEAD + "¥9900 商务舱\n¥12000 头等舱\n¥3960\n订票")
    assert r["price"] == 3960.0
    assert r["bizPrice"] == 9900


def test_bizprice_single_price_row_untouched():
    """单报价行（主价即高档舱价）：bizPrice 不重复记账，cabin 照旧。"""
    r = _row(_HEAD + "¥9900 商务舱\n订票")
    assert r["price"] == 9900.0
    assert r["cabin"] == "商务舱"
    assert "bizPrice" not in r


def test_bizprice_alt_price_still_not_leaked():
    """_alt_price 内部留痕键继续不进 extra（既有卫生语义不回退）。"""
    r = _row(_HEAD + "¥9900 商务舱\n¥3960\n订票")
    assert "_alt_price" not in r
