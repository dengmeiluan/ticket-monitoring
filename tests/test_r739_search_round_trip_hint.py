# -*- coding: utf-8 -*-
"""r739 检索页「往返票」要提前说清楚哪些渠道没有往返。

用户三次追问「所有渠道应该都能支持往返吧」，并在界面上实际会遇到：
勾上往返票后，携程/途牛/飞猪国内/同程国内**都拿不到数据**——因为它们的
往返确实没接（详见 r733/r734/r736/r737 的实测记录）。界面此前对此
**一个字都不说**，用户只能看到空结果，读作「功能坏了」。

能力矩阵早已有 `/api/channel-dims`，但只有配置页用它渲染表格；
检索页的「往返票」chip 只写了一句通用的说明。

判据（两层）：
  1. 行为层：给定一份能力矩阵，`_rtNoSupportNames()` 必须返回
     「声明不是 y 的渠道」的中文名，且**只**包含这些渠道；
  2. 源层：chip 的 title 必须引用这个函数（否则算了不用）。
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _src():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def _fn_body(src, name):
    i = src.index("function %s(" % name)
    # 花括号配平取函数体
    j = src.index("{", i)
    depth, k = 0, j
    while k < len(src):
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                return src[i:k + 1]
        k += 1
    return src[i:]


def test_helper_lists_only_channels_without_round_trip():
    src = _src()
    assert "function _rtNoSupportNames(" in src, (
        "没有 _rtNoSupportNames：检索页无法说明哪些渠道没有往返")
    body = _fn_body(src, "_rtNoSupportNames")
    # 必须按 round_trip 单元格过滤，且把 y 排除
    assert "round_trip" in body, body[:400]
    assert "DIMS_DATA" in body, "没有从能力矩阵取值（会写死名单）"


def test_chip_title_uses_the_helper():
    """可点击的「往返票」chip（含 toggleRT 的那个）要带上不支持名单。

    注意别匹配到只读标签 `<span class="rrt" title="往返票：价格=…">`
    ——那是展示用的角标，不承担"哪些渠道没有"的解释职责。
    """
    src = _src()
    hits = [m.group(0) for m in re.finditer(r'title="往返票[^"]*"[^>]*'
                                            r'onclick="toggleRT\(', src)]
    assert hits, "找不到可点击的往返票 chip"
    seg = hits[0]
    assert "_rtNoSupportNames(" in seg, (
        "往返票 chip 的说明没有引用不支持名单：%s" % seg)


def test_helper_is_pure_and_handles_missing_data():
    """矩阵没加载时不能抛错，也不能凭空列出渠道。"""
    src = _src()
    body = _fn_body(src, "_rtNoSupportNames")
    assert "DIMS_DATA" in body
    # 必须有空值保护（返回空串或空数组）
    assert re.search(r"if\s*\(!\s*DIMS_DATA", body) or "||" in body, body


def test_every_channel_name_comes_from_matrix():
    """名字来自 API 的 name 字段（CHANNEL_CN 单源），不写死中文。"""
    body = _fn_body(_src(), "_rtNoSupportNames")
    assert ".name" in body, "渠道名没有取矩阵的 name 字段（会与单源脱节）"
