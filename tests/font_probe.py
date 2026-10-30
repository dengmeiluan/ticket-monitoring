# -*- coding: utf-8 -*-
"""测试用的中文字体探测（可移植，不写死任何本机路径）。

渲染类烟测需要一把真实中文字体来度量字宽/行高。此前多个测试文件直接
写 `C:/Windows/Fonts/msyh.ttc`：在 Linux/CI 上该断言直接不执行（假绿），
对读者也暴露了与项目无关的本机目录。

`cjk_font_path()` 依次尝试：环境变量 `TM_CJK_FONT` → 平台常见位置 →
Pillow 内置解析。都没有则返回空串，调用方跳过依赖字体度量的用例。
"""
import os
import sys

_CACHE = {}


def cjk_font_path() -> str:
    """返回一个可用的中文字体文件路径；找不到返回空串。"""
    if "p" in _CACHE:
        return _CACHE["p"]
    cands = []
    env = (os.environ.get("TM_CJK_FONT") or "").strip()
    if env:
        cands.append(env)
    if sys.platform.startswith("win"):
        root = os.path.join(os.environ.get("WINDIR", ""), "Fonts")
        for name in ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "simsun.ttc"):
            cands.append(os.path.join(root, name))
    else:
        for p in ("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
                  "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                  "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
                  "/System/Library/Fonts/PingFang.ttc"):
            cands.append(p)
    found = ""
    for p in cands:
        try:
            if p and os.path.isfile(p):
                found = p
                break
        except OSError:
            continue
    if not found:
        try:
            from PIL import ImageFont
            f = ImageFont.truetype("DejaVuSans.ttf", 12)
            if f is not None:
                found = "DejaVuSans.ttf"
        except Exception:
            found = ""
    _CACHE["p"] = found
    return found


def has_cjk_font() -> bool:
    return bool(cjk_font_path())
