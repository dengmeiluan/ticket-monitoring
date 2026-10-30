# -*- coding: utf-8 -*-
"""r498：演示库不能无限堆积。

实测：系统临时目录里堆了 **37 个** `ticket_demo_prices_*.db`、合计 **182MB**
——每个测试/演示进程按端口建一个，从不回收，长跑会占满临时盘。

修法边界（每条都要钉，删错会打断正在运行的实例）：
  1) 本次端口自己的库**绝不删**（哪怕它很旧）；
  2) 1 小时内被写过的**不删**（活跃实例会持续写，mtime 很新）；
  3) 正在被占用的删不掉也不报错（Windows 抛 OSError，静默跳过）；
  4) 只碰 `ticket_demo_prices_*.db` 这一种名字，别的文件一律不动。
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import webui  # noqa: E402


def _mk(dirpath, name, age_s):
    import time as _t
    p = os.path.join(dirpath, name)
    with open(p, "wb") as f:
        f.write(b"x" * 32)
    ts = _t.time() - age_s
    os.utime(p, (ts, ts))
    return p


def test_sweep_removes_only_stale_non_current(monkeypatch):
    d = tempfile.mkdtemp()
    monkeypatch.setattr(tempfile, "gettempdir", lambda: d)
    cur = _mk(d, "ticket_demo_prices_8765.db", 7200)   # 本次端口但很旧
    old = _mk(d, "ticket_demo_prices_1111.db", 7200)   # 旧且非本次
    fresh = _mk(d, "ticket_demo_prices_2222.db", 60)   # 新
    other = _mk(d, "prices.db", 7200)                  # 不像 demo 库
    keep_me = _mk(d, "monitor.log", 7200)

    n = webui._demo_db_sweep(8765, max_age_s=3600)

    assert n == 1, "应只清理 1 个历史库，实际 %d" % n
    assert os.path.exists(cur), "删掉了本次端口的库（会打断当前实例）"
    assert not os.path.exists(old), "历史库未清理"
    assert os.path.exists(fresh), "删掉了 1 小时内活跃的库（正在运行的实例会被打断）"
    assert os.path.exists(other), "删了不相关的数据库文件"
    assert os.path.exists(keep_me), "删了不相关的日志文件"


def test_sweep_is_noop_on_empty_dir(monkeypatch):
    d = tempfile.mkdtemp()
    monkeypatch.setattr(tempfile, "gettempdir", lambda: d)
    assert webui._demo_db_sweep(8765) == 0


def test_sweep_never_raises(monkeypatch):
    """目录不可读时也不得抛（启动路径不能因为清理失败而崩）。"""
    def boom():
        raise OSError("nope")
    monkeypatch.setattr(tempfile, "gettempdir", boom)
    assert webui._demo_db_sweep(8765) == 0


def test_entry_calls_the_sweep_before_building():
    """入口必须先清理再建库，否则新库会被自己刚建的逻辑影响。"""
    import io
    w = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                newline="").read()
    i = w.index("_swept = _demo_db_sweep(args.port)")
    j = w.index("db = _demo_db_path(args.port)", i)
    assert i < j, "清理必须发生在建库之前"
