# -*- coding: utf-8 -*-
"""r654：App 渠道要有和 PC 渠道同等的干预入口。

用户要求「App 渠道跟 PC/H5 一样 N 维度记录、识别、区分、干预」。
记录/识别已验证；这条守干预的两处缺失（实测均是真的没有）：

1) 健康卡不出诊断卡 → 没有「自检」按钮（classify_round 默认只遍历
   5 家浏览器渠道，智行 App 跑过也不出卡）；
2) 节流面板的「最小间隔」写死 5 家，智行 App 配不到自己的节奏
   （后端 cadence 本就按渠道 key 读，是纯界面遗漏）。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def test_diag_platforms_includes_enabled_app_channel():
    """用户启用了 App 渠道时，诊断卡要覆盖它（才有自检入口）。"""
    import webui
    got = webui._diag_platforms(["app_zhixing"])
    assert "app_zhixing" in got, got
    # 默认 5 家仍在
    for p in ("ctrip", "qunar", "fliggy", "tongcheng", "tuniu"):
        assert p in got, got


def test_diag_platforms_excludes_unconfigured_app_channel():
    """没启用 App 渠道时不能多出一张「本轮未扫描」的空卡。"""
    import webui
    got = webui._diag_platforms([])
    assert "app_zhixing" not in got, got


def test_cadence_ui_covers_app_channel():
    """节流面板的「最小间隔」要能为 App 渠道生成控件。"""
    w = _w()
    i = w.index("glbCad_")
    seg = w[i - 200:i + 1200]
    assert "APP_PLAT_NAME" in seg, "节流面板仍是写死 5 家，App 配不到节奏"
    assert "'glbCad_'+p" in seg, seg[:200]


def test_cadence_save_accepts_app_channel():
    """保存侧白名单必须含 App 渠道，否则界面上填了会被静默丢弃。

    实测踩过：界面已经为「智行 App」生成了节奏控件，但保存循环只放行
    5 家浏览器渠道——用户填 45 分钟、保存后仍是 0，且不报任何错。
    """
    from core.channels import APP_CHANNELS, BROWSER_CHANNELS
    w = _w()
    i = w.index("_cad_ok")
    seg = w[i - 400:i + 400]
    assert "APP_CHANNELS" in seg, "保存侧白名单没接 App 渠道"
    assert "BROWSER_CHANNELS" in seg, seg[:200]
    # 与清单同源（不是又抄一份字面量）
    assert "from core.channels import" in seg or "core.channels" in seg
    assert set(APP_CHANNELS) and set(BROWSER_CHANNELS)
