# -*- coding: utf-8 -*-
"""r921：按 App 伪装 ABI——MuMu 官方 abi-select 表的读写与幂等。

2026-11-03 实测（这台 MuMu / Android 15）：

    /system/etc/mumu-configs/abi-select-android12.config
        ctrip\\.android\\.view      arm64-v8a      # 携程
    重启实例后：
        dumpsys package ctrip.android.view → primaryCpuAbi=arm64-v8a
        全局 ro.product.cpu.abi            → x86_64（不变，系统仍稳）
        携程正常启动（CtripHomeActivity 在前台），无 UnsatisfiedLinkError

这比「全局改 ro.product.cpu.abi」好得多：App 视角是 arm64，系统仍跑 x86，
而且只影响我们关心的几个包。本文件钉住读写/幂等/回滚三类行为。

注意：表里**第一列本身就是一条正则**（带 `\\.` 转义），不是裸包名——
用裸包名去匹配转义文本必然匹配不到（踩过）。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r921_app_abi_select.py -q
"""
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.android import vendor  # noqa: E402

_LOG = logging.getLogger("test_r921")

_TABLE = """\
com\\.tencent\\.tmgp\\.dnf    arm64-v8a   # 地下城与勇士
com\\.netease\\.onmyoji      x86_64      # yys
ctrip\\.android\\.view       arm64-v8a   # 携程
com\\.Qunar                  arm64-v8a   # 去哪儿
############################################
.*\\.tmgp\\..*               arm         # 应用宝默认ARM
"""


class FakeDev:
    """假设备：``cat`` 返回表内容，``cp``/``printf`` 记录调用。"""

    def __init__(self, table=_TABLE, has_backup=False):
        self.table = table
        self.has_backup = has_backup
        self.calls = []
        self.appended = ""

    def _sh(self, *a, timeout=None):
        cmd = " ".join(str(x) for x in a)
        self.calls.append(cmd)
        if cmd == "shell cat %s" % vendor.ABI_SELECT:
            return self.table
        if "ls /data/local/tmp/abi-select.orig" in cmd:
            return "/data/local/tmp/abi-select.orig" if self.has_backup else ""
        if cmd.startswith("shell cp -f %s /data" % vendor.ABI_SELECT):
            self.has_backup = True
            return ""
        if "printf" in cmd and ">>" in cmd:
            # 取出单引号里的 payload
            i = cmd.find("'")
            j = cmd.rfind("'")
            self.appended = cmd[i + 1:j].replace("'\\''", "'")
            self.table = self.table + self.appended
            return "TM_OK"
        if "cp -f /data/local/tmp/abi-select.orig" in cmd:
            self.table = _TABLE
            return "TM_OK"
        return ""


# ---------------------------------------------------------------------------
# 1. 读：第一列是正则，不是裸包名
# ---------------------------------------------------------------------------
def test_read_parses_escaped_patterns():
    cur = vendor.read_abi_select(FakeDev())
    assert cur["exists"] is True
    assert cur["apps"]["ctrip.android.view"] == "arm64-v8a"
    assert cur["apps"]["com.Qunar"] == "arm64-v8a"
    # 不在票务表里的包不该被收进来
    assert "com.tencent.tmgp.dnf" not in cur["apps"]


def test_read_missing_table_is_soft():
    cur = vendor.read_abi_select(FakeDev(table=""))
    assert cur["exists"] is False and cur["apps"] == {}


def test_read_ignores_comment_and_wildcard_lines():
    cur = vendor.read_abi_select(FakeDev())
    # 通配行 .*\.tmgp\..* 不是我们的包
    assert all("tmgp" not in p for p in cur["apps"])


# ---------------------------------------------------------------------------
# 2. 写：幂等 + 备份 + 只加缺的
# ---------------------------------------------------------------------------
def test_set_app_abi_adds_missing_and_backs_up():
    dev = FakeDev()
    rep = vendor.set_app_abi(dev)
    assert rep["ok"] is True
    assert set(rep["added"]) == {"com.taobao.trip", "com.tongcheng.android",
                                 "cn.suanya.zhixing"}
    assert rep["present"] == ["ctrip.android.view", "com.Qunar"]
    assert rep["restart_required"] is True
    assert "arm64-v8a" in dev.appended
    assert "com\\.taobao\\.trip" in dev.appended
    # 备份动作发生过
    assert any("cp -f %s" % vendor.ABI_SELECT in c for c in dev.calls)


def test_set_app_abi_is_idempotent():
    dev = FakeDev()
    vendor.set_app_abi(dev)
    before = dev.table
    rep2 = vendor.set_app_abi(dev)
    assert rep2["ok"] is True and rep2["added"] == []
    assert rep2["restart_required"] is False      # 没变就不用重启
    assert dev.table == before                    # 没重复追加


def test_set_app_abi_custom_abi():
    dev = FakeDev()
    rep = vendor.set_app_abi(dev, apps={"com.Qunar": r"com\.Qunar"},
                             abi="armeabi-v7a")
    assert rep["added"] == []                     # 已在表里
    # 自定义包：能写进去（read_abi_select 只回读票务包，所以按 payload 断言）
    rep2 = vendor.set_app_abi(dev, apps={"com.new.app": r"com\.new\.app"},
                              abi="armeabi-v7a")
    assert "com\\.new\\.app" in dev.appended
    assert "armeabi-v7a" in dev.appended
    # read_abi_select 的职责是"票务包现状"，不含自定义包 —— 这是刻意的窄口径
    assert "com.new.app" not in vendor.read_abi_select(dev)["apps"]


def test_set_app_abi_reports_missing_table():
    dev = FakeDev(table="")
    rep = vendor.set_app_abi(dev)
    assert rep["ok"] is False and "abi-select" in rep["error"]


# ---------------------------------------------------------------------------
# 3. 回滚
# ---------------------------------------------------------------------------
def test_revert_restores_backup():
    dev = FakeDev()
    vendor.set_app_abi(dev)                       # 追加并产生备份
    assert "com\\.taobao\\.trip" in dev.table
    rep = vendor.revert_app_abi(dev)
    assert rep["ok"] is True
    assert "com\\.taobao\\.trip" not in dev.table  # 回到原表
    assert dev.table == _TABLE


def test_revert_without_backup_is_reported():
    rep = vendor.revert_app_abi(FakeDev(has_backup=False))
    assert rep["ok"] is False and "没有备份" in rep["error"]


# ---------------------------------------------------------------------------
# 4. 票务包清单
# ---------------------------------------------------------------------------
def test_ticket_apps_cover_five_channels():
    assert set(vendor.TICKET_APPS) == {
        "ctrip.android.view", "com.taobao.trip", "com.Qunar",
        "com.tongcheng.android", "cn.suanya.zhixing"}
    for pat in vendor.TICKET_APPS.values():
        assert r"\." in pat, pat                  # 必须是转义形式
