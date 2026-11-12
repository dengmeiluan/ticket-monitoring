# -*- coding: utf-8 -*-
"""r1303：陈旧标签页检测必须按**构建戳**，不能只按版本号。

今天真实踩到：我重启十几次、改了结构与样式，`__version__` 一直是 1.6.0，
页面里 `PGVER` 永远相等 → 「服务端已升级，点此刷新」横幅**从不出现** →
用户对着 47 分钟前的旧 DOM 以为"排版被改坏了"。
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def test_page_has_build_placeholder():
    assert "const PGBUILD='__PAGEBUILD__';" in SRC, "页面没注入构建戳占位符"
    assert '.replace("__PAGEBUILD__", _build_stamp())' in SRC, "服务端没替换构建戳"


def test_state_carries_build():
    assert '"build": _build_stamp(),' in SRC, "state 没带 build 字段"


def test_banner_compares_build_too():
    """横幅判据必须包含构建戳失配（只比版本号时，同日多次重启判不出来）。"""
    i = SRC.find("if((s.version&&PGVER&&s.version!==PGVER)")
    assert i > 0, "找不到横幅判据"
    seg = SRC[i:i + 200]
    assert "s.build" in seg and "PGBUILD" in seg, seg


def test_build_stamp_is_12_hex():
    """构建戳形态：sha256 前 12 位十六进制（与服务端 _build_stamp 实现一致）。"""
    m = re.search(r"_BUILD_STAMP\[\"v\"\] = hashlib\.sha256\(f\.read\(\)\)"
                  r"\.hexdigest\(\)\[:12\]", SRC)
    assert m, "构建戳算法变了？"
