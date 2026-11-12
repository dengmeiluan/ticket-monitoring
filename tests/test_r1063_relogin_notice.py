# -*- coding: utf-8 -*-
"""r1063 T101：换身份后必须明确告诉用户"哪些 App 要重登"。

真机实证（2026-11-08）：T84 把身份换成 Xiaomi 14 / SM8650 之后，
`app_qunar` 从 **19.2s 正常出数**变成「搜索后要求登录（登录态失效）」。

道理很简单但很容易忘：**换身份 = 换了一台新设备**，服务端看到的会话全部作废。
工具以前只回一句"已轮换"，用户不知道下一步要做什么，于是以为"工具没效果"。

现在 `rotate` / `align` 的返回里都会带：

```
"relogin_required": ["app_zhixing", "app_fliggy", "app_qunar", "app_ctrip"],
"notice": "身份已变，以下 App 需重新登录：app_zhixing、app_fliggy、…"
```
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.android import align, identity, rotate  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_lists_only_subscribed_app_channels():
    cfg = {"users": [{"platforms": ["fliggy", "app_zhixing", "app_qunar",
                                    "tongcheng"]}]}
    got = identity.apps_need_relogin(cfg)
    assert got == ["app_zhixing", "app_qunar"], got


def test_empty_config_is_safe():
    assert identity.apps_need_relogin({"users": []}) == []
    assert identity.apps_need_relogin({}) == []      # 读不到就空，不抛


def test_rotate_dry_run_includes_notice(monkeypatch):
    # 干净检出里没有 config.yaml（被 gitignore），订阅名单为空 →
    # 这里把清单固定下来，测的是"有清单就一定要提示"这条契约。
    monkeypatch.setattr(identity, "apps_need_relogin",
                        lambda cfg=None: ["app_zhixing", "app_ctrip"])
    rep = rotate.rotate("user_data", [], apply=False)
    assert rep["ok"] is True
    assert rep.get("relogin_required") == ["app_zhixing", "app_ctrip"], rep
    assert "重新登录" in (rep.get("notice") or ""), rep


def test_align_dry_run_includes_notice():
    rep = align.apply(None, None, write=False)
    if rep.get("pick"):
        assert rep.get("relogin_required"), rep
        assert "重新登录" in (rep.get("notice") or ""), rep


def test_docs_mention_the_ordering_discipline():
    """手册里要有"换身份 → 必须重登所有 App"这条纪律。"""
    doc = io.open(os.path.join(ROOT, "docs", "CAPABILITY_AND_UNBLOCK.md"),
                  encoding="utf-8").read()
    assert "重登" in doc or "重新登录" in doc
