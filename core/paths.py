# -*- coding: utf-8 -*-
"""冻结态（PyInstaller）下，落盘根目录要用 exe 所在目录而不是 _internal。

打包后 `__file__` 指向 `_internal/`，于是 `data/prices.db`、`user_data/`、
日志全被拼到程序内部目录：用户在安装目录下看不到自己的数据，升级/重装
一次就随包一起被清掉。这必须与源码态区分开。
"""
from __future__ import annotations

import os
import sys


def app_root() -> str:
    """数据根目录：冻结态 = exe 所在目录；源码态 = 仓库根。

    源码态要连上两级：本文件在 `core/` 里，只上一级会得到 `core/` 本身。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve(p: str, default: str = "") -> str:
    """相对路径锚到 app_root()；绝对路径原样返回。"""
    p = (str(p) if p else "").strip() or default
    if not p:
        return app_root()
    return p if os.path.isabs(p) else os.path.join(app_root(), p)
