# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1028_login_compact_status.py
- tests/test_r624_login_wait_is_visible.py
- tests/test_r805aj_login_wait_progress.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import io
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request


# ---- merged from tests/test_r1028_login_compact_status.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_static_tight_status_map_and_full_title():
    with io.StringIO(webui_full_src()) as f:
        src = f.read()
    i = src.index("r1028：双端半格只有 113px")
    block = src[i:i + 900]
    # r-登录体验：page_ok 的完整句改为「已保存 · 页面可访问（该端未跑过明细）」，
    # 半格短句必须同步（只改长句会让半格与 title 各说各话）。
    assert "页面可达·未跑明细" in block, "半格短句没跟上新口径"
    assert "页面可访问（该端未跑过明细）" in block, "完整句没跟上新口径"
    assert "明细待验" not in block, "旧短句还留着（两套说法会让用户读成两种状态）"
    assert "会话有效·明细可用" in block
    assert "const _subTxt=tight?" in block
    j = src.index('class="lgsub" title=')
    assert "_stText" in src[j:j + 260], "短句替换后完整状态没有进 title"


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _payload():
    def slot(key, plat, status):
        return {"slot": key, "plat": plat, "status": status, "saved": True,
                "needs_login": False, "active": False, "saving": False,
                "pending": False, "account": "淘宝账号" if plat == "fliggy" else "",
                "requirement": "必须登录"}
    plats = {k: slot(k, k, "saved") for k in
             ("ctrip", "qunar", "tongcheng", "tuniu")}
    plats["fliggy"] = slot("fliggy", "fliggy", "page_ok")
    return {"ok": True, "plats": plats, "slots": {
        "ctrip": slot("ctrip", "ctrip", "saved"),
        "qunar": slot("qunar", "qunar", "saved"),
        "fliggy": slot("fliggy", "fliggy", "page_ok"),
        "fliggy_h5": slot("fliggy_h5", "fliggy", "page_ok"),
        "tongcheng": slot("tongcheng", "tongcheng", "saved"),
        "tuniu": slot("tuniu", "tuniu", "saved"),
    }}




# ---- merged from tests/test_r624_login_wait_is_visible.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_login_start_shows_in_progress_copy():
    """静态旁证：文案与 aria-busy 的存在（渲染判据在主测试）。

    r-登录体验：进行中文案不再用「正在打开窗口…」冒充进度，而是先写
    「正在提交登录请求」，随后由服务端阶段（排队/起窗/等用户/保存）
    逐段替换；两者都算合格的「进行中」文案。
    """
    w = webui_full_src()
    i = w.index("async function loginStart(")
    seg = w[i:i + 1400]
    # 收紧：新文案已随本条合入，必须出现；旧词面「正在打开窗口…」不许再当进度用
    # （自由秒表冒充进度正是 issue #19 的三条症状之一）。
    assert "正在提交登录请求" in seg, "loginStart 未改为中性的『正在提交登录请求』"
    assert "正在打开窗口…" not in seg, "loginStart 又在用『正在打开窗口…』冒充进度"
    assert "aria-busy" in seg, "进行中态没给读屏播报"
    assert "b.disabled=true" in seg, "进行中应禁用按钮，避免重复触发"




# ---- merged from tests/test_r805aj_login_wait_progress.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)




