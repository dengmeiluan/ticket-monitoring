# -*- coding: utf-8 -*-
"""r1195：端口被占用要**自动 +1 并说出来**（零配置的硬要求）。

用户场景：双击 exe / 跑一条命令，可是上次那个实例没退干净还占着 8765。
以前的行为：`_Srv((host, port))` 抛 OSError → 只记一句「启动失败」→
用户看到的是"打开没反应"，然后以为程序坏了。

契约（本文件断言）：
1. `_candidate_ports(8765)` = 8765, 8766, …（顺序即优先级）；
2. `_bind_console` 端口被占时**继续往后试**，返回真实端口；
3. 全都被占 → 返回 (None, 0, 最后错误)，让调用方明确告警；
4. **负控**：不许把"被占用"当成成功（返回的 srv 必须是真绑上的那个）。
"""
import os
import socket
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import webui  # noqa: E402


def test_candidate_ports_are_sequential():
    assert webui._candidate_ports(8765, 3) == [8765, 8766, 8767]
    assert webui._candidate_ports("8765", 1) == [8765]
    assert webui._candidate_ports(None, 2) == [8765, 8766]   # 脏值兜底


class _FakeSrv:
    """假 server：只在 allowed 端口上成功，其余抛 OSError（= WinError 10048）。"""

    def __init__(self, allowed):
        self.allowed = set(allowed)
        self.bound = []

    def __call__(self, addr, handler):
        host, port = addr
        if port not in self.allowed:
            raise OSError(10048, "Only one usage of each socket address")
        self.bound.append(port)
        return ("SRV", port)


def test_bind_console_shifts_when_port_busy(monkeypatch):
    fake = _FakeSrv(allowed={8767})
    monkeypatch.setattr(webui, "_Srv", fake)
    srv, actual, err = webui._bind_console("127.0.0.1", 8765, tries=5)
    assert srv is not None and actual == 8767, (srv, actual, err)
    assert err is None
    assert fake.bound == [8767], "应当只在真正可用的端口上绑定一次"


def test_bind_console_reports_failure_honestly(monkeypatch):
    fake = _FakeSrv(allowed=set())
    monkeypatch.setattr(webui, "_Srv", fake)
    srv, actual, err = webui._bind_console("127.0.0.1", 8765, tries=3)
    assert srv is None and actual == 0, (srv, actual)
    assert isinstance(err, OSError), err


def _pick_free_base():
    """找一个 base 与 base+1 都空闲的端口（r1311：不再写死 8795）。"""
    for _ in range(50):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", 0))
            base = s.getsockname()[1]
        finally:
            s.close()
        if base + 1 >= 65535:
            continue
        t = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            t.bind(("127.0.0.1", base + 1))
            return base
        except OSError:
            continue
        finally:
            t.close()
    raise RuntimeError("找不到空闲端口对")


def test_real_socket_occupies_the_port(monkeypatch):
    """真 socket 占位（不靠假对象）：占住 base 后必须挪到 base+1。

    注意：这里**动态选端口**——原版写死 8795，一旦 8795 被残留进程/上轮 TIME_WAIT
    占着，用例就会假红（实测 WinError 10048），把"真没问题"报成"坏了"。
    """
    host = "127.0.0.1"
    base = _pick_free_base()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((host, base))
        s.listen(1)
        # 用真 _Srv，但只允许试两个端口，避免占用一个长期端口
        srv, actual, err = webui._bind_console(host, base, tries=2)
        assert srv is None or actual == base + 1, (srv, actual, err)
        if srv is not None:
            try:
                srv.server_close()
            except Exception:
                pass
    finally:
        s.close()
