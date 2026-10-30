# -*- coding: utf-8 -*-
"""r684：登录「保存会话」必须保存**当前登录的那个渠道**。

现场（2026-10-30）：在去哪儿 App 里完成手机号登录后点「保存会话」，
落盘的却是 `app_zhixing.tar.gz`——`webui._app_login_ctx()` 里的
`_snapshot()` 把包名与快照名**写死成智行**：

    mgr = SnapshotManager(dev, store, "cn.suanya.zhixing")
    return mgr.export("app_zhixing")

`handle_finish` 的契约是 `snapshot: (plat) -> (ok, detail)`，回调本来就
拿得到渠道 id，只是实现没接。结果：去哪儿登录一次也没存下来，下次
采集永远「快照已失效」——而界面显示过「已保存」。

这条缺陷不抛异常、日志还写着「快照 0.6 MB」，属于「看起来成功」的一类。
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBUI = os.path.join(ROOT, "webui.py")


def _src():
    with open(WEBUI, encoding="utf-8") as f:
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
