# -*- coding: utf-8 -*-
"""r1339：登录卡「加载态给出方向」+ 慢 GET 留痕。

背景（2026-11-10 21:0x 实测，本机真服务）：
* `/api/login-state` 平时 0.1–2s，但在采集轮次占着设备锁时会拖到 **34.9s**；
* 前端原来只写「加载中…」，用户看到的就是"卡死了"，只能反复刷新；
* 这类慢请求在日志里**完全看不见**，用户报"页面卡住"时无从对账。

契约：
1. 登录卡占位必须说明"在读什么"，并**每秒刷新已等待秒数**（证明还活着）；
2. `do_GET` 超过 2s 必须记一条 WARNING（`[api] GET <路径> 耗时 X.Xs`）；
3. 慢请求记账**只加日志、不改响应**（异常不外抛，正常路径零影响）。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def test_login_placeholder_explains_and_counts():
    i = SRC.find('<div id="loginRows">')
    assert i > 0, "找不到登录卡占位"
    seg = SRC[i:i + 260]
    assert "正在读取登录状态" in seg, seg
    assert "lgwait" in seg, "占位没有可计数的节点"
    assert "本机设备依次探测中" in seg, "没说明在等什么"


def test_wait_counter_ticks_every_second():
    i = SRC.find("#loginRows .lgwait")
    assert i > 0, "找不到计数逻辑"
    seg = SRC[max(0, i - 400):i + 400]
    assert "setInterval" in seg and "已等待" in seg, seg


def test_slow_get_is_logged():
    assert "def _do_GET_impl(self):" in SRC, "do_GET 没有被包一层计时"
    i = SRC.find("def do_GET(self):")
    seg = SRC[i:i + 900]
    assert "time.time()" in seg and "> 2.0" in seg, seg
    assert "[api] GET %s 耗时" in seg, "日志文案缺失"


def test_slow_logging_cannot_break_response():
    """负控：记账在 finally 里且自身包裹 try——绝不能让"记日志"把响应打断。

    r1392：改用 `inspect.getsource` 取**方法体全文**再断言三件事，不再按
    字符窗口切片——do_GET 里加了一层「替身 handler 回退」后偏移就变了，
    窗口切片的断言会假红（CI 实测）。
    """
    import inspect
    import webui
    src = inspect.getsource(webui._Handler.do_GET)
    assert "finally:" in src, "计时不在 finally 里，异常路径会丢日志"
    assert "[api] GET %s 耗时" in src, "日志文案缺失"
    # 日志调用必须被 try/except 包住（否则日志异常会打断响应）
    i = src.index("[api] GET %s 耗时")
    tail = src[i:]
    assert "except Exception" in tail, "日志调用没有自保"
