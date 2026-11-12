# -*- coding: utf-8 -*-
"""r1063 T158：通路清单必须能被界面枚举（新通路才谈得上"进策略面板行"）。

背景：用户明确要求"例如 H5/API、PC、API 这类通路也算作独立维度，进策略面板行"。
本轮新增了 `PC·国际`（途牛国际 PC 页）与 `PC·周历`（跨日期低价条）。

* 已注册进 `core.channels.PATH_CN` → 覆盖键 `ctrip/domestic/PC·周历` 可校验通过、
  链路闸门也能单独停它；
* `/api/strategy` 新增 `paths` 字段（id + 中文名），界面据此把"链路级"覆盖按行渲染，
  用户不必手打作用域键。

真机实测：`/api/strategy.paths` 共 42 条，`PC·国际` / `PC·周历` 都在。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import channels as CH  # noqa: E402
from core.strategy_params import parse_override_key  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_new_paths_registered_with_cn_labels():
    assert "PC·国际" in CH.PATH_CN
    assert "PC·周历" in CH.PATH_CN
    # 标签要有含义（不是空串），面板直接显示它
    assert "国际" in CH.PATH_CN["PC·国际"]
    assert "周历" in CH.PATH_CN["PC·周历"]


def test_override_key_accepts_new_paths():
    assert parse_override_key("tuniu/intl/PC·国际") == ("tuniu", "intl",
                                                        "PC·国际")
    assert parse_override_key("ctrip/domestic/PC·周历") == ("ctrip", "domestic",
                                                            "PC·周历")


def test_strategy_api_exposes_path_list():
    src = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    i = src.index('out["paths"] = [{"id": _k, "cn": _v}')
    seg = src[max(0, i - 400):i + 200]
    assert "from core.channels import PATH_CN" in seg, \
        "通路清单必须从唯一口径 PATH_CN 取，不能另抄一份"
    assert 'out["paths"]' in src


def test_calendar_and_list_paths_are_classified():
    """口径分类（日历类/列表类）必须覆盖这些真实通路名。"""
    from core.channel_matrix import path_kind
    assert path_kind("PC·周历") == "calendar"
    assert path_kind("窗历") == "calendar"
    assert path_kind("PC·国际") == "list"
    assert path_kind("H5/API") == "list"
