# -*- coding: utf-8 -*-
"""r245 运维哨：磁盘水位预警（数据观测 P2 立案——10-04 磁盘满事件
×33 静默降级，走势/明细补位被跳过而无运维可感知信号）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r245_disk.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_disk_low_threshold_boundary():
    """disk_low 纯函数：剩余 < 地板=低水位；地板=0 恒不误报。
    以阈值参数为注入点（真实磁盘真实调用，无 mock——floor 取
    天文大值必低、取 0 恒安全，两端边界真实可达）。"""
    from main import disk_low
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert disk_low(root, floor_gb=10 ** 9) is True    # 剩余必小于天文大值
    assert disk_low(root, floor_gb=0) is False         # free<0 恒假


def test_disk_low_bad_root_no_crash():
    """不存在的路径不抛异常、返回 False（检查自身故障不误报不炸轮）。"""
    from main import disk_low
    assert disk_low(os.path.join(os.path.abspath(os.sep), "no", "such",
                                 "dir"), floor_gb=10 ** 9) is False


def test_disk_low_wired_into_sweep():
    """接线钉：扫描轮开头挂水位检查（每轮一次，WARNING 词面在位）。"""
    src = open("main.py", encoding="utf-8").read()
    assert "disk_low(_REPO_ROOT" in src
    assert "磁盘] 剩余" in src
