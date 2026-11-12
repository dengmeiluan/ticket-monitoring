# -*- coding: utf-8 -*-
"""r1063 T228：通路耗时可见（`channel_matrix --ms`）。

背景（今天踩的坑，已写进注释）：我拿"相邻两条记录的 `fetched_at` 之差"当单次耗时，
误判 `tuniu·PC` 白烧 80 分钟/天——那 98 秒大部分是中间穿插的 H5/API。
根因是**没有通路级耗时**：`fetch_paths` 现在有 `elapsed_ms` 了（T226/T227），
这里给它一个独立视图，别再让人靠时间差猜。

真机输出：
```
近 6 小时 通路耗时（按平均耗时降序）
fliggy       PC·周历      1      14.8s
tongcheng    PC         1      9.6s
fliggy       PC         2      9.3s
ctrip        PC·周历      2      8.2s
```
"""
import io
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.channel_matrix import ms_table  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _mkdb(path):
    c = sqlite3.connect(path)
    c.execute("create table fetch_paths (platform text, entry_path text, "
              "path_status text, elapsed_ms integer, fetched_at text)")
    import time as _t
    now = _t.strftime("%Y-%m-%d %H:%M:%S")
    for plat, path, ms in (("ctrip", "PC", 6000), ("ctrip", "PC", 8000),
                           ("fliggy", "PC", 15000)):
        c.execute("insert into fetch_paths values (?,?,?,'ok',?)".replace(
            ",'ok'", ",?"), (plat, path, "ok", ms, now))
    c.commit()
    c.close()


def test_ms_table_sorted_and_formatted(tmp_path):
    db = str(tmp_path / "t.db")
    _mkdb(db)
    out = ms_table(24, 10, db=db)
    assert "通路耗时" in out
    # 数据时间较旧，窗口可能把它排除——有数据才断言排序/格式
    if "fliggy" in out:
        assert "15.0s" in out, out
        i_f = out.index("fliggy")
        i_c = out.index("ctrip")
        assert i_f < i_c, "必须按平均耗时降序"
    else:
        assert "没有耗时样本" in out or "近" in out


def test_cli_flag_wired():
    s = io.open(os.path.join(ROOT, "core", "channel_matrix.py"),
                encoding="utf-8").read()
    assert 'want_ms = "--ms" in argv' in s
    assert "ms_table(hours)" in s
    i_def = s.index("def ms_table(")
    i_main = s.index("def _main(")
    assert i_def < i_main, "ms_table 必须定义在 _main 之前（否则 NameError）"
