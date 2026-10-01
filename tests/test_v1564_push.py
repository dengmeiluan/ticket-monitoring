"""推送回归钉：v163 备案收口（////）。

 测试邮件 launch 回环过滤（launch_is_public 单源，webui 同挂）；
 邮件页脚「链接请点上方按钮」两态（launch 空不出指引）；
 横幅副行不复读主字（❌ 首段纯档位复读整段消失、🔔 剥词面留
航线价、🚨/📈 异形保留原样）；
 _esc_md 补 &quot;（href/src 属性上下文收口）；
 build_notifier 装配门形态防御（emails 非 list/项非 dict/port
非数字/to 缺失）。
"""

import inspect
import logging

from core.notifier import (EmailNotifier, _banner_html, _email_shell_html,
                           _esc_md, build_notifier, launch_is_public)


# ---- 横幅副行不复读主字 ----------

def test_banner_sub_strips_pure_tier_head():
    """❌ 支（实发 91%）：首段纯档位复读，副行只剩最近/另监控信息。"""
    h = _banner_html("❌ 全部未达标｜最近 乌→上 10/05 直飞差￥400｜另监控 乌→上 10/06")
    assert "未达标" in h          # 主字仍在
    assert "全部未达标" not in h  # 副行不复读
    assert "最近 乌→上 10/05 直飞差￥400" in h
    assert "另监控 乌→上 10/06" in h


def test_banner_sub_strips_word_keeps_route():
    """🔔 支：只剥档位词面，航线价信息保留。"""
    h = _banner_html("🔔 持续达标上→乌 09/25 中转￥1790｜另监控 乌→上 10/06")
    assert "持续达标" in h                    # 主字
    assert "持续达标上→乌" not in h           # 副行不再复读词面
    assert "上→乌 09/25 中转￥1790" in h      # 航线价保留


def test_banner_sub_strips_interp_and_single_seg():
    """/：🔔「持续达标·」剥词后行首不残留间隔号；
    无「｜」单段达标 title（单航线单日期形态）同样剥档位复读。"""
    h1 = _banner_html("🔔 持续达标·上→乌 10/05 真达标￥930")
    assert "持续达标" in h1
    assert "持续达标·" not in h1 and "·上→乌" not in h1
    assert "上→乌 10/05 真达标￥930" in h1
    h2 = _banner_html("❌ 全部未达标")
    assert "未达标" in h2 and "全部未达标" not in h2


def test_banner_sub_keeps_irregular_forms():
    """🚨/📈 支：主词不中或非档位命中，副行原样保留。"""
    h1 = _banner_html("🚨 达标！乌→上 10/05 直飞￥930")
    assert "达标！乌→上 10/05 直飞￥930" in h1
    assert "🚨" not in h1
    h2 = _banner_html("📈 价格走势与明细｜最近 上→乌")
    assert "价格走势与明细" in h2  # 默认横幅不误剥
    h3 = _banner_html("↩️ 回落出线｜最近 上→乌 10/05")
    assert "↩️" not in h3 and "回落出线" in h3  # ↩️ 支剥 emoji 留余段


# ---- 页脚按钮指引两态 ----------

def test_shell_footer_button_hint_two_states():
    desp = "正文"
    h0 = _email_shell_html("t", desp, launch="", with_snapshot=False)
    assert "链接请点上方按钮" not in h0
    h1 = _email_shell_html("t", desp, launch="https://x.example/",
                           with_snapshot=False)
    assert "链接请点上方按钮" in h1


# ---- _esc_md 引号转义 ----------

def test_esc_md_quotes():
    assert _esc_md('a"b<c>&d') == "a&quot;b&lt;c&gt;&amp;d"
    # href 属性上下文：launch 含引号不得破属性边界
    h = _email_shell_html("t", "d", launch='https://x/"onmouseover="x',
                          with_snapshot=False)
    assert '"onmouseover' not in h


# ---- 装配门形态防御 ----------

def _lg():
    return logging.getLogger("v1564")


def test_build_notifier_emails_non_list_ignored():
    assert build_notifier({"emails": {"user": "a@x.com"}}, _lg()) is None
    assert build_notifier({"emails": "a@x.com"}, _lg()) is None


def test_build_notifier_skips_bad_items():
    ns = build_notifier({"emails": ["str-item", 42,
                                    {"enabled": True, "user": "a@x.com",
                                     "password": "pw", "to": "b@x.com"}]},
                        _lg())
    assert ns is not None and not isinstance(ns, list)
    # 唯一有效项 → 单对象而非 Composite
    assert isinstance(ns, EmailNotifier)


def test_build_notifier_to_required_and_port_fallback():
    # to 缺失：不装配（免每轮空转不落盘不计数）
    assert build_notifier({"emails": [{"enabled": True, "user": "a@x.com",
                                       "password": "pw"}]}, _lg()) is None
    n = build_notifier({"emails": [{"enabled": True, "user": "a@x.com",
                                    "password": "pw", "to": "b@x.com",
                                    "port": "abc"}]}, _lg())
    assert isinstance(n, EmailNotifier) and n.port == 465


# ---- emailshot 端口预探快速降级 ----------

def test_emailshot_port_probe_fast_fail():
    from core.emailshot import _port_rejects, render_console_png
    import logging
    # 回环未监听端口 → 拒绝 → 预探 True，render 不进 Playwright 直接 None
    assert _port_rejects("http://127.0.0.1:1/") is True
    assert _port_rejects("") is False            # 空基址不判拒（上层已短路）
    assert _port_rejects("not a url") is False   # 解析失败保守放行走 goto
    lg = logging.getLogger("v1565")
    t0 = __import__("time").monotonic()
    assert render_console_png("http://127.0.0.1:1/", lg) is None
    assert __import__("time").monotonic() - t0 < 5, "端口拒绝未快速降级"


# ---- launch_is_public 单源 + webui 源钉 ----------

def test_launch_is_public_matrix():
    assert launch_is_public("") is False
    assert launch_is_public("http://127.0.0.1:8765/") is False
    assert launch_is_public("http://localhost:8765/") is False
    assert launch_is_public("http://192.168.1.8:8765/") is True


def test_alerter_launch_public_delegates_to_single_source():
    from core.alerter import Alerter
    src = inspect.getsource(Alerter._launch_public)
    assert "launch_is_public" in src, "alerter 判定应挂单源防回潮"


def test_webui_test_email_launch_filtered():
    """源钉+执行级（/ P0+）：测试邮件 launch 必经
    _test_email_launch（内含 launch_is_public），禁裸透传回潮；
    函数本体执行断言（曾内联表达式变量名 NameError 被吞，grep 钉
    抓不到执行错误）。"""
    src = open("webui.py", encoding="utf-8").read()
    i = src.find('self.path == "/api/test-email"')
    assert i > 0
    seg = src[i:i + 5000]
    assert "launch=_test_email_launch()" in seg
    assert 'launch="http://%s/" % host' not in seg
    # chip.on 三色已令牌化，裸 hex 不回潮
    chip_lines = [ln for ln in src.splitlines() if ".chip.on .bd" in ln]
    assert chip_lines, "chip.on 规则丢失"
    assert all("#" not in ln for ln in chip_lines), \
        "chip.on 档色应挂令牌（裸 hex 回潮）"
    assert "--chip-on-warn" in src and "--chip-on-red" in src
    import webui
    try:
        webui._State.cfg = None
        assert webui._test_email_launch() == ""     # 未配置 base_url → 不带按钮
        webui._State.cfg = {"web": {"base_url": "http://127.0.0.1:8765"}}
        assert webui._test_email_launch() == ""     # 回环 → 过滤
        webui._State.cfg = {"web": {"base_url": "http://192.168.1.8:8765"}}
        assert webui._test_email_launch() == "http://192.168.1.8:8765"
    finally:
        webui._State.cfg = None                     # 全局态还原防污染
