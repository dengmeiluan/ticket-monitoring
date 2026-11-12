# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r314_login_finish_watch.py
- tests/test_r513_login_button_names_the_surface.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import json
import os
import pytest
import socket
import subprocess
import sys
import threading
import time
import urllib.request

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


# ---- merged from tests/test_r513_login_button_names_the_surface.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _slot(plat, name, surface, surface_label, need):
    return {"plat": plat, "name": name, "surface": surface,
            "surface_label": surface_label, "account": "a***@b.c",
            "requirement": "必须登录", "login_url": "https://x.invalid/",
            "active": False, "saving": False, "pending": False, "error": "",
            "saved": True,
            "status": "login_required" if need else "available",
            "needs_login": need, "health_need_login": need,
            "profile": "p", "saved_at": 0, "detail": "", "verified_at": "",
            "page_ok": False, "session_verified": False,
            "detail_ok": not need}


_CASES = {
    "single_h5": {"fliggy": dict(_slot("fliggy", "飞猪 PC", "pc", "PC", False),
                                 slot="fliggy"),
                  "fliggy_h5": dict(_slot("fliggy", "飞猪 H5", "h5", "H5", True),
                                    slot="fliggy_h5")},
    "both_fliggy": {"fliggy": dict(_slot("fliggy", "飞猪 PC", "pc", "PC", True),
                                   slot="fliggy"),
                    "fliggy_h5": dict(_slot("fliggy", "飞猪 H5", "h5", "H5", True),
                                      slot="fliggy_h5")},
    "cross_plat": {"fliggy": dict(_slot("fliggy", "飞猪 PC", "pc", "PC", True),
                                  slot="fliggy"),
                   "qunar": dict(_slot("qunar", "去哪儿", "", "全端", True),
                                 slot="qunar")},
    "single_plat": {"ctrip": dict(_slot("ctrip", "携程", "", "全端", True),
                                  slot="ctrip")},
}

















# ---- merged from tests/test_r314_login_finish_watch.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PORT = None      # fixture 期取空闲端口（r251 同款动态口）
BASE = ""
_proc = None


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_up(timeout=20.0):
    # 本机探活显式空代理（LESSONS 廿四§9：默认 opener 吃环境代理假失败）
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    end = time.time() + timeout
    while time.time() < end:
        try:
            with opener.open(BASE + "/api/state", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.4)
    return False






def _plats(qunar):
    d = {"saved": False, "active": False, "stale": False, "pending": False}
    d.update(qunar)
    return {"ok": True, "plats": {
        "qunar": d, "ctrip": dict(d), "tongcheng": dict(d),
        "tuniu": dict(d), "fliggy": dict(d)}}


# finish 前态：qunar 登录窗开着（active）→ 卡片渲染「我已登录完成」钮
PLATS_A = _plats({"saved": False, "active": True})
# 翻落态：会话已保存、验证窗内（stale+pending）→「已保存，等待采集验证…」
PLATS_B = _plats({"saved": True, "active": False, "stale": True, "pending": True})


def test_login_finish_watch_source_pin():
    """源码钉：有界短周跟Watch 在场 + finish 成功分支接线。"""
    import webui
    import pathlib
    src = webui_full_src()
    assert "function lgFinishWatch(p,left)" in src, (
        "缺 finish 后短周跟Watch：会话保存是登录线程异步尾部，"
        "finish 返回时 active 尚未翻落，立即刷读旧态、30s 轮询太晚")
    i = src.index("function lgFinishWatch")
    seg = src[i:i + 420]
    assert "if(left<=0)return" in seg, "Watch 缺有界停点（登录线程悬挂时不得无限轮询）"
    assert "lgFinishWatch(p,10)" in src, "finish 成功分支未接线 Watch"
    # 接线必须在 j.ok 分支内（失败路径不轮询：「没有进行中的登录」错误态重拉无益）
    j = src.index("lgFinishWatch(p,10)")
    head = src[max(0, j - 300):j]
    assert "toast(j.ok?" in head, "Watch 接线未落在成功 toast 分支内"


