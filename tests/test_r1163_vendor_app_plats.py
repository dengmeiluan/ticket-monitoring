# -*- coding: utf-8 -*-
"""r1163：`VENDOR_APP_PLATS` 写死了一个不存在的渠道 `app_tuniu`。

后果（不是学术问题）：途牛登录保存后，r1063 T130 的"同厂商一起清墙"和
`_kick_login_probe()` 的"同厂商 App 复探"对途牛**静默失效**——因为
`core.channels.APP_CHANNELS` 只有五家（app_zhixing / app_qunar / app_fliggy /
app_ctrip / app_tongcheng），没有 app_tuniu。用户看到的就是
「APP 也登录了，但页面没变」。

契约：名单必须从 `core.channels` 派生；写死的渠道名一个都不能有。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.channels import APP_CHANNELS, BROWSER_CHANNELS  # noqa: E402

WEBUI = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def test_map_is_derived_from_channel_constants():
    import webui

    m = getattr(webui, "VENDOR_APP_PLATS", None)
    assert isinstance(m, dict) and m, "缺少 VENDOR_APP_PLATS"
    for vendor, apps in m.items():
        assert vendor in BROWSER_CHANNELS, "厂商键不在 BROWSER_CHANNELS：%s" % vendor
        for a in apps:
            assert a in APP_CHANNELS, "指向不存在的 App 渠道：%s（%s）" % (a, vendor)


def test_no_phantom_app_channel_in_source():
    """负控：**代码行**里不许再出现 app_tuniu 这种不存在的渠道名。

    注释里会提到这个名字（解释历史 bug），所以只看非注释行。
    """
    code = "\n".join(ln for ln in WEBUI.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "app_tuniu" not in code, "webui.py 仍写死 app_tuniu（APP_CHANNELS 里没有）"
    for vendor in BROWSER_CHANNELS:
        expect = "app_" + vendor
        if expect not in APP_CHANNELS:
            assert expect not in code, "又出现不存在的渠道名：%s" % expect


def test_tuniu_maps_to_empty_not_phantom():
    import webui

    assert webui.VENDOR_APP_PLATS.get("tuniu") == (), (
        "途牛没有同名 App 渠道，应映射为空元组：%r"
        % (webui.VENDOR_APP_PLATS.get("tuniu"),))


def test_known_pairs_kept():
    import webui

    assert webui.VENDOR_APP_PLATS.get("ctrip") == ("app_ctrip",)
    assert webui.VENDOR_APP_PLATS.get("fliggy") == ("app_fliggy",)
    assert webui.VENDOR_APP_PLATS.get("tongcheng") == ("app_tongcheng",)
    assert webui.VENDOR_APP_PLATS.get("qunar") == ("app_qunar",)
