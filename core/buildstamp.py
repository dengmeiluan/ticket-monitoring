# -*- coding: utf-8 -*-
"""`core/buildstamp.py`：构建戳的**唯一**定义（webui.py + webui_assets 内容哈希前 12 位）。

为什么单独成模块：模板外置之后，构建戳从"webui.py 一个文件的哈希"变成"webui.py +
webui_assets/* 的哈希"，而 `tools/demo_build.py` 与 `tools/release_align_check.py`
还在各自算 `sha256(webui.py)`——三处定义、两种口径，于是烘焙站点的戳与运行时
对不上（实测：站点 `code:655f0df3083c`、源码 `code:ef83c525b001`）。

这里只做一件事，任何需要"这棵树是哪一版"的地方都调它，别再各算各的。
"""
from __future__ import annotations

import hashlib
import os

__all__ = ["stamp", "stamp_of"]

_CACHE = {"v": ""}


def stamp_of(root: str = "") -> str:
    """按 `<root>/webui.py` + `<root>/webui_assets/*` 算戳（不做缓存）。"""
    root = root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    h = hashlib.sha256()
    with open(os.path.join(root, "webui.py"), "rb") as f:
        h.update(f.read())
    assets = os.path.join(root, "webui_assets")
    if os.path.isdir(assets):
        for name in sorted(os.listdir(assets)):
            p = os.path.join(assets, name)
            if os.path.isfile(p):
                with open(p, "rb") as f:
                    h.update(f.read())
    return h.hexdigest()[:12]


def stamp() -> str:
    """进程内缓存版（服务端每个请求都要用）。"""
    if not _CACHE["v"]:
        try:
            _CACHE["v"] = stamp_of()
        except OSError:
            _CACHE["v"] = "unknown"
    return _CACHE["v"]
