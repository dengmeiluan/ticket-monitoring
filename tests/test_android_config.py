# -*- coding: utf-8 -*-
"""Android 运行时配置：缺省关闭，全字段钳制。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.android.config import is_enabled, normalize


def test_missing_block_disables_everything():
    c = normalize(None)
    assert c.enabled is False
    assert is_enabled(None) is False
    assert is_enabled({"crawler": {}}) is False


def test_enabled_true_is_respected():
    assert normalize({"enabled": True}).enabled is True
    assert is_enabled({"android": {"enabled": True}}) is True
    assert is_enabled({"android": {"enabled": False}}) is False


def test_defaults_are_clamped():
    c = normalize({"enabled": True, "boot_timeout_s": 1,
                   "action_timeout_s": 99999})
    assert c.boot_timeout_s >= 10
    assert c.action_timeout_s <= 900


def test_vm_index_coerced_to_int():
    assert normalize({"enabled": True, "vm_index": "2"}).vm_index == 2


def test_bad_types_do_not_raise():
    c = normalize({"enabled": True, "vm_index": "abc",
                   "boot_timeout_s": "x", "install_dir": 123})
    assert c.vm_index == 0
    assert isinstance(c.boot_timeout_s, int)
    assert isinstance(c.install_dir, str)
