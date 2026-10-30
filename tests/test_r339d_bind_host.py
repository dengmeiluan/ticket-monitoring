# -*- coding: utf-8 -*-
"""TM_WEB_HOST 环境变量出口（r339d Docker 交付面根治）：容器内服务
绑 127.0.0.1 回环时 `-p 8765:8765` 端口映射不可达（CI 冒烟 curl 与
NAS compose 双双不可达实录）——容器镜像经 ENV 内置 0.0.0.0。优先级：
config web.host 显式值 > TM_WEB_HOST env > 默认 127.0.0.1（非容器
默认行为不变）。"""
import os


def test_bind_host_default_loopback(monkeypatch):
    import webui
    monkeypatch.delenv("TM_WEB_HOST", raising=False)
    assert webui._bind_host({}) == "127.0.0.1"
    assert webui._bind_host({"web": {}}) == "127.0.0.1"


def test_bind_host_env_exit(monkeypatch):
    import webui
    monkeypatch.setenv("TM_WEB_HOST", "0.0.0.0")
    assert webui._bind_host({}) == "0.0.0.0"
    # config 显式值仍最优先（配置优先律）
    assert webui._bind_host(
        {"web": {"host": "192.168.1.10"}}) == "192.168.1.10"


def test_bind_host_config_beats_env(monkeypatch):
    import webui
    monkeypatch.setenv("TM_WEB_HOST", "0.0.0.0")
    assert webui._bind_host(
        {"web": {"host": "127.0.0.1"}}) == "127.0.0.1"


def test_bind_host_wired_at_both_bind_sites():
    src = open("webui.py", encoding="utf-8").read()
    assert src.count("_bind_host(") >= 3  # 定义+两处装配点
    assert 'get("host", "127.0.0.1")' not in src, \
        "裸默认装配残留（须走 _bind_host 单源）"
