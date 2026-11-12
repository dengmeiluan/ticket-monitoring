# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r684_app_login_saves_right_channel.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
import io
from support_webui_src import webui_full_src

import os
import re
import sys


# ---- merged from tests/test_r684_app_login_saves_right_channel.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBUI = os.path.join(ROOT, "webui.py")


def _src():
    with io.StringIO(webui_full_src()) as f:
        return f.read()


def _snapshot_block():
    src = _src()
    i = src.index("def _snapshot(")
    return src[i:i + 1600]


def test_snapshot_uses_plat_argument_not_hardcoded():
    block = _snapshot_block()
    assert 'cn.suanya.zhixing' not in block, \
        "_snapshot() 仍把包名写死成智行：登录去哪儿会存成智行快照"
    assert '.export("app_zhixing")' not in block, \
        "_snapshot() 仍把快照名写死成 app_zhixing"
    assert "APP_LOGIN_PACKAGES" in block or "packages" in block, \
        "_snapshot() 应按渠道取包名"


def test_finish_handler_passes_plat_to_snapshot():
    """handle_finish 的契约是 snapshot(plat)，不接受无参回调。"""
    p = os.path.join(ROOT, "core", "android", "login_api.py")
    with open(p, encoding="utf-8") as f:
        src = f.read()
    i = src.index("if snapshot is not None:")
    block = src[i:i + 400]
    assert "snapshot(plat)" in block, \
        "handle_finish 没有把 plat 传给快照回调（老签名兼容应保留）"


def test_every_app_channel_has_package_and_cn_name():
    """能登录的 App 渠道必须在包名表里有条目，否则保存会话无从下手。"""
    from crawlers import APP_CHANNELS
    from core.channels import CHANNEL_CN
    src = _src()
    m = re.search(r"APP_LOGIN_PACKAGES\s*=\s*\{(.*?)\}", src, re.S)
    assert m, "找不到 APP_LOGIN_PACKAGES"
    table = m.group(1)
    for p in APP_CHANNELS:
        assert p in table, f"{p} 没有包名，登录后存不了会话"
        assert p in CHANNEL_CN, f"{p} 没有中文名，界面会露裸 id"
