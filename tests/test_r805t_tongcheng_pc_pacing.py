# -*- coding: utf-8 -*-
"""r805t：新增的 PC 通路不许绕开节流。

r805 给同程加国内 PC 通路时，第一版**完全没有 `_sleep()`**——H5 主循环
每日期后都 sleep，新写的 PC 循环却连打。这不是"少睡一会"，而是绕开了
全项目的请求节流纪律：多日期一次连打是该渠道最容易被风控盯上的形态，
而账本上会记成"PC 通路失败"，把自找的风控读成渠道不行。

判据：
  1. `_fetch_pc_dom` 的循环体内必须调用 `self._sleep()`；
  2. 调用必须**在日期循环里**（在循环外调一次等于没节流多日期）；
  3. 与 H5 主循环同律——两边都不能缺。
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _fn(src, name, end_marker):
    i = src.index("    def %s(" % name)
    j = src.index(end_marker, i)
    return src[i:j]


def test_pc_path_sleeps_between_dates():
    src = io.open(os.path.join(ROOT, "crawlers", "tongcheng.py"),
                  encoding="utf-8").read()
    body = _fn(src, "_fetch_pc_dom", "\n    def _pick_lowest(")
    assert "self._sleep()" in body, (
        "PC 通路没有 _sleep()：多日期连打会自招风控，"
        "而账本会把风控记成「PC 不行」")
    # 必须在 for date 循环内——用缩进判断它处在循环体里
    loop = re.search(r"\n(\s+)for date in dates:", body)
    assert loop, "找不到日期循环，判据失效需重写"
    indent = loop.group(1)
    sleep_indents = [len(m.group(1)) for m in
                     re.finditer(r"\n(\s+)self\._sleep\(\)", body)]
    assert sleep_indents, "没有找到循环内的 _sleep()"
    assert min(sleep_indents) > len(indent), (
        "self._sleep() 在 for-date 循环**外**（缩进 %s vs 循环 %s）："
        "只睡一次等于多日期连打"
        % (min(sleep_indents), len(indent)))


def test_h5_path_still_sleeps():
    """H5 主循环的节流不能因为加了 PC 通路而被顺手删掉。"""
    src = io.open(os.path.join(ROOT, "crawlers", "tongcheng.py"),
                  encoding="utf-8").read()
    i = src.index("    def fetch(self, from_city: str, to_city: str,")
    j = src.index("\n    def ", i + 10)
    body = src[i:j]
    assert "self._sleep()" in body, "H5 主循环的 _sleep() 没了"
