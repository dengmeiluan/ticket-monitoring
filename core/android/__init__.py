# -*- coding: utf-8 -*-
"""Android App 渠道支撑层。

只在 `android.enabled: true` 时才被真正驱动；本包顶层刻意不做任何
重量级 import，保证关闭 App 渠道的进程连 subprocess 都不会碰。
"""
from .config import AndroidConfig, is_enabled, normalize

__all__ = ["AndroidConfig", "is_enabled", "normalize"]
