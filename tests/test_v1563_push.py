"""推送回归钉：Composite 成员 send 必须收下 launch 形参。

背景（用户实报「钉钉推送怎么没了」）：邮件通道 v3 起 Composite
统一透传 launch=…，DingTalkNotifier.send 漏该形参 → TypeError → 钉钉
通道每轮静默炸（Composite 任一成员成功即 True，邮件成功吞掉聚合真值）。
钉死：全部 Composite 可装配成员的 send 签名必须含 launch。
"""

import inspect

from core.notifier import (CompositeNotifier, DingTalkNotifier,
                           EmailNotifier, NtfyNotifier, ServerChanNotifier,
                           WindowsToastNotifier)


def test_all_member_send_accept_launch():
    for cls in (DingTalkNotifier, ServerChanNotifier, EmailNotifier,
                NtfyNotifier, WindowsToastNotifier, CompositeNotifier):
        params = inspect.signature(cls.send).parameters
        assert "launch" in params, f"{cls.__name__}.send 缺 launch 形参"


# ---- 横幅词表对齐真实 title（push_history 941 条实发词表） ----------

def test_banner_real_title_prefixes():
    from core.notifier import _banner_html
    real = (("🚨 达标！上→乌 10/05 真达标￥1850", "真达标"),
            ("🔔 持续达标·上→乌 10/05 真达标￥1850", "持续达标"),
            ("❌ 全部未达标｜最近 上→乌 10/05 直飞差￥400", "未达标"),
            ("↩️ 回落出线｜最近 上→乌 10/05", "达标回落"))
    for t, word in real:
        h = _banner_html(t)
        assert "#eef4fc" not in h, f"{t} 落默认蓝横幅（色识态失效）"
        assert word in h
    # 🎯🟩🟨🟨 档位键维持（desp 场景），词面挂 TIER_FULL 投影
    assert "行情破线" in _banner_html("🟩 机票监控｜x")


# ---- 降级轻壳 desp 单渲染 ----------

def test_shell_degraded_renders_desp_once():
    from core.notifier import _email_shell_html
    desp = "#### 状态唯一头\n\n正文标记XYZ\n\n- 条目一"
    h = _email_shell_html("❌ 机票监控｜t", desp, with_snapshot=False)
    assert h.count("状态唯一头") == 1
    assert h.count("XYZ") == 1
    assert h.count("自动推送") == 1   # 页脚不重复
    assert "快照生成失败" in h


# ---- Email 通道落盘 push_history ----------

def test_email_writes_push_history(tmp_path, monkeypatch):
    import json as _j
    import logging
    import core.notifier as cn
    monkeypatch.chdir(tmp_path)

    class _FakeSMTP:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, *a):
            pass

        def sendmail(self, *a):
            pass

    monkeypatch.setattr(cn.smtplib, "SMTP_SSL", _FakeSMTP)
    n = EmailNotifier("smtp.163.com", 465, "a@163.com", "pw",
                      "b@163.com", logging.getLogger("t"))
    assert n.send("标题", "内容") is True
    rec = _j.loads((tmp_path / "logs" / "push_history.jsonl")
                   .read_text(encoding="utf-8").strip().splitlines()[-1])
    assert rec["ch"] == "email" and rec["ok"] is True


# ---- 邮件 Date/Message-ID 头 ----------

def test_email_date_msgid_headers():
    import logging
    n = EmailNotifier("smtp.163.com", 465, "a@163.com", "pw",
                      "b@163.com", logging.getLogger("t"))
    msg = n._build_msg("t", "d")
    assert msg["Date"] and msg["Message-ID"]
    assert "163.com" in msg["Message-ID"]


# ---- 有序列表正则不吞「N.数字」 ----------

def test_md_ol_regex_not_eat_decimal():
    from core.notifier import _md_to_html
    h = _md_to_html("3.9折 限时")
    assert "<ol" not in h and "3.9折" in h
    h2 = _md_to_html("1. 行李直达")
    assert "<ol" in h2 and "<li>行李直达</li>" in h2


# ---- Composite 成员异常计入连败 ----------

def test_composite_counts_member_exception_streak():
    import logging

    class Boom:
        def __init__(self):
            self._fail_streak = 3

        def send(self, *a, **k):
            raise RuntimeError("x")

    class OkCh:
        def __init__(self):
            self._fail_streak = 0

        def send(self, *a, **k):
            return True

    boom, okch = Boom(), OkCh()
    c = CompositeNotifier([boom, okch], logging.getLogger("t"))
    assert c.send("t", "d") is True          # 邮件成功聚合仍 True
    assert boom._fail_streak == 4            # 异常路径计入连败（可弹窗）


# ---- emailshot 空配置态排除（源钉） ----------

def test_emailshot_wait_excludes_unconfigured():
    src = open("core/emailshot.py", encoding="utf-8").read()
    assert "未配置" in src


# ---- M-2 邮件按钮 launch 回环过滤（源钉） ----------

def test_alerter_send_launch_loopback_filtered():
    import re
    src = open("core/alerter.py", encoding="utf-8").read()
    n = len(re.findall(
        r"launch=\(launch if self\._launch_public\(\) else \"\"\)", src))
    assert n >= 2, \
        f"alerter launch 过滤点仅 {n} 处（应 ≥2：聚合主路径+报告推送）"
    assert not re.search(r"notifier\.send\([^)]*launch=launch\)", src, re.S), \
        "notifier.send 存在裸 launch=launch 透传（回环死链回潮）"


# ---- 挂账① 「另监控 等 N 条」预算拼接 ----------

def test_rest_seg_budget():
    from core.alerter import _rest_seg
    base = "❌ 全部未达标｜最近 上→乌 10/05 直飞差￥400"
    out = _rest_seg(base, ["上→乌 10/06"] * 5)
    assert len(out) <= 60 and out.startswith(base)
    assert "另监控" in out and "等" in out and "条" in out
    out2 = _rest_seg(base, ["乌→上 10/06"])
    assert out2.endswith("｜另监控 乌→上 10/06") and "等" not in out2
    assert _rest_seg(base, []) == base
