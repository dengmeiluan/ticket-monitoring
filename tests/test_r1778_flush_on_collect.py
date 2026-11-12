# -*- coding: utf-8 -*-
"""r1778：采到即落库——整条查询的池子若等轮尾才写，中途重启就全丢。

实测：08:02:30 同程 App「得到 1 条记录」、08:02:51 同程浏览器「得到 1 条记录」，
而 `flight_prices` 最大 fetched_at 停在 08:00:36——我在 08:05 重启进程，
正在飞的那条查询里已采到的行全没落库（TerminateProcess 不跑信号处理）。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    return io.open(os.path.join(ROOT, "main.py"), encoding="utf-8",
                   newline="").read()


def test_flush_helper_exists_and_is_called_per_channel():
    s = _src()
    assert "def _flush_now(" in s, "没有即时落库助手"
    i = s.index("all_prices.extend(prices)")
    assert "_flush_now(prices)" in s[i:i + 200], "渠道完成时没有即时写"


def test_failover_rows_also_flushed():
    s = _src()
    i = s.index("all_prices.extend(_pr2 or [])")
    assert "_flush_now(_pr2 or [])" in s[i:i + 200], "换道回采的行没有即时写"


def test_tail_write_only_writes_unwritten():
    s = _src()
    assert "_wrote_ids" in s, "没有已写集合"
    i = s.index("all_prices = _stable_pool(all_prices)")
    seg = s[i:i + 400]
    assert "_wrote_ids" in seg, "轮尾仍整批重写（会重复入库）"
    assert "save_many(_rest)" in seg, "轮尾没有改成只补未写的"
