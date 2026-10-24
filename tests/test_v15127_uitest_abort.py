# -*- coding: utf-8 -*-
"""uitest 中断假绿修复：脚本中途抛异常时「中断于异常」只写结果文件、
不参与退出码判定——bad/errors 均空时 os._exit(0) 把中断吞成 CI 全绿
（实锤：单跑 Element not attached 中断，exit code 仍 0）。

中断=非全绿，必须非零退出。源码钉锁三件：中断标志置位、标志参与
exit 判定、标志初值 False。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v15127_uitest_abort.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    return open(os.path.join(_ROOT, "docs", "uitest.py"),
                encoding="utf-8").read()


def test_abort_flag_set_in_except():
    src = _src()
    assert "_aborted = False" in src, "中断标志未初始化"
    # except 分支必须置位（缩进锚定：8 空格体=main 内 except）
    assert "        _aborted = True" in src, "except 未置中断标志"


def test_abort_participates_in_exit_code():
    src = _src()
    assert "1 if (_aborted or bad or errors) else 0" in src, \
        "中断标志不参与退出码=中断假绿"
