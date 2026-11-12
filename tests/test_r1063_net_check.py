# -*- coding: utf-8 -*-
"""r1063 T94：出口 IP 定性——换 IP 之前先确认"当前 IP 是不是问题"。

解封阶梯里有一档是"换出口 IP"，但换 IP 成本不低（代理/拨号/换线），
而阿里系与携程都按 **IP 段**聚类：机房 IP 比家宽更容易被判风险。
所以先测一次——本节测试的就是"测得准、判得清、失败不炸"。

本机实测（2026-11-08）：

```
出口 IP : 58.246.127.206   上海联通（CNC Group CHINA169）
代理标记: False | 数据中心: False | 蜂窝: False
判定    : residential —— IP 不是主要风险点
```
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import net_check as NC  # noqa: E402


def test_residential_verdict():
    v, advice = NC.verdict({"proxy": False, "hosting": False, "mobile": False})
    assert v == "residential"
    assert "IP 不是主要风险点" in advice


def test_datacenter_verdict_wins_over_mobile():
    v, advice = NC.verdict({"proxy": True, "hosting": True, "mobile": True})
    assert v == "datacenter"
    assert "换家宽" in advice


def test_hosting_alone_is_datacenter():
    assert NC.verdict({"hosting": True})[0] == "datacenter"


def test_mobile_verdict():
    v, _ = NC.verdict({"proxy": False, "hosting": False, "mobile": True})
    assert v == "mobile"


def test_unknown_when_probe_failed():
    v, advice = NC.verdict({})
    assert v == "unknown"
    assert "别急着换 IP" in advice


def test_probe_never_raises(monkeypatch):
    """网络不通时也必须返回 dict（返回 {}），不许抛。"""
    import httpx

    def _boom(*a, **kw):
        raise httpx.ConnectError("no net")

    monkeypatch.setattr(httpx, "get", _boom)
    assert NC.probe(timeout=0.1) == {}


def test_cli_exists():
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "core", "net_check.py"),
        encoding="utf-8").read()
    assert "def _main" in src and "--json" in src
