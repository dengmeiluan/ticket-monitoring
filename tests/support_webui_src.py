# -*- coding: utf-8 -*-
"""webui.py 源码读取的同构适配：模板外置（webui_assets/）后，
把 PAGE/NOTIFY_PAGE 按原位置回填，与拆分前的源码文本同构——
历史钉的 substring/find/切片/负向断言语义全部保真。"""
import os

import webui

_CACHE = {"src": None}


def webui_full_src() -> str:
    if _CACHE["src"] is None:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src = open(os.path.join(root, "webui.py"),
                   encoding="utf-8").read()
        src = src.replace('PAGE = _load_asset("page.html")',
                          'PAGE = r"""' + webui.PAGE + '"""')
        src = src.replace('NOTIFY_PAGE = _load_asset("notify.html")',
                          'NOTIFY_PAGE = r"""' + webui.NOTIFY_PAGE + '"""')
        _CACHE["src"] = src
    return _CACHE["src"]
