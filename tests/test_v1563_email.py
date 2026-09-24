# -*- coding: utf-8 -*-
"""邮件通道回归：_md_to_html 子集转换（转义先行/图链接/列表
开闭/引用合并）、EmailNotifier MIME 组装与失败路径（mock SMTP，
零真发）、build_notifier 装配语义（钉钉>Server酱 单选不变；邮件并联
CompositeNotifier；心跳退避聚合——任一通道活着心跳不退避）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v1563_email.py
"""
import logging
import os
import sys
import unittest
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.notifier import (  # noqa: E402
    CompositeNotifier,
    EmailNotifier,
    _email_html,
    _md_to_html,
    build_notifier,
)


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path, monkeypatch):
    """落盘改动后 EmailNotifier.send 会写 logs/
    push_history.jsonl（相对 CWD）——本文件全部测试隔离到 tmp_path，
    防测试样条污染真实推送历史（mock SMTP 的 send 也走落盘路径）。"""
    monkeypatch.chdir(tmp_path)

LOG = logging.getLogger("t1563mail")


# ---- _md_to_html：alerter desp 全语法形态 ----

def test_md_html_heading_quote():
    h = _md_to_html("#### 🚨 已达标——可出手\n\n> 仅当日/次日20前到 ｜ 线￥400")
    assert '<h3 style="' in h and "已达标" in h
    # 引用条带品牌蓝左边线（邮件壳设计令牌）
    assert "border-left:3px solid #0b62d6" in h


def test_md_html_ordered_unordered_lists():
    h = _md_to_html("1. 🔥 **✈️ CA1234** 08:00→11:20 ￥520\n"
                    "2. **✈️ MU5678** ￥480\n"
                    "\n- 暂无满足到达约束的中转\n")
    assert h.count("<ol") == 1 and h.count("</ol>") == 1
    assert h.count("<ul") == 1 and h.count("</ul>") == 1
    assert "<b>✈️ CA1234</b>" in h
    # 列表在空行处正确闭合并切换类型（ol 与 ul 不得嵌套残留）
    assert h.index("</ol>") < h.index("<ul")


def test_md_html_image_link_bold():
    h = _md_to_html("![走势](https://img.example.com/a.png?x=1&y=2)\n\n"
                    "[📲 完整详情（点击直达）](http://127.0.0.1:8765/)")
    # URL 的 & 已转义为 &amp;（先转义后注标签——webui esc 同律）
    assert 'src="https://img.example.com/a.png?x=1&amp;y=2"' in h
    assert 'max-width:100%' in h
    assert '<a href="http://127.0.0.1:8765/"' in h


def test_md_html_escapes_injected_tags():
    h = _md_to_html("正常行 <script>alert(1)</script> & <b>伪粗体</b>")
    assert "<script>" not in h
    assert "&lt;script&gt;" in h
    # 正文里的 & 先转义（不产生裸 & 破坏 HTML 解析）
    assert " &amp; " in h


def test_email_html_shell():
    h = _email_html("正文行")
    assert "机票监控" in h and "ticket-monitoring" in h
    assert "正文行" in h
    # 品牌条 + 页脚 + 正文容器三段齐全（壳结构完整）
    assert h.count('<div style="') >= 3


# ---- EmailNotifier：MIME 组装 / 发送路径（mock SMTP_SSL 零真发） ----

def _em(**kw):
    d = dict(host="smtp.163.com", port=465, user="a@163.com",
             password="pw16", to="b@qq.com, c@163.com；d@qq.com",
             logger=LOG)
    d.update(kw)
    return EmailNotifier(**d)


def test_email_recipient_split_cn_separators():
    # 中文逗号/分号与空白混用都要拆（用户手输形态）
    assert _em().to == ["b@qq.com", "c@163.com", "d@qq.com"]


def test_email_send_mime_and_smtp_params():
    n = _em()
    with mock.patch("core.notifier.smtplib.SMTP_SSL") as SS:
        inst = SS.return_value.__enter__.return_value
        ok = n.send("✅ 标题", "#### 正文\n\n> 引用行")
    assert ok is True
    SS.assert_called_once_with("smtp.163.com", 465, timeout=15)
    inst.login.assert_called_once_with("a@163.com", "pw16")
    # From 必须等于登录账号（163/QQ 服务端 554 策略）
    args = inst.sendmail.call_args[0]
    assert args[0] == "a@163.com"
    assert args[1] == ["b@qq.com", "c@163.com", "d@qq.com"]
    payload = args[2]
    # multipart/alternative：纯文本在前、HTML 在后（alternative 语义）；
    # 正文默认 base64 编码，内容断言须先 decode（裸查中文只会撞编码块）
    import email as _email
    m = _email.message_from_string(payload)
    parts = m.get_payload()
    assert "multipart/alternative" in payload
    assert parts[0].get_content_type() == "text/plain"
    assert parts[1].get_content_type() == "text/html"
    assert "正文" in parts[0].get_payload(decode=True).decode("utf-8")
    _html = parts[1].get_payload(decode=True).decode("utf-8")
    assert "<h3" in _html and "正文" in _html and "机票监控" in _html
    assert "Subject: =?utf-8?" in payload


def test_email_send_failure_returns_false_and_exposes_err():
    n = _em()
    with mock.patch("core.notifier.smtplib.SMTP_SSL",
                    side_effect=OSError("连接超时")):
        ok = n.send("t", "d")
    assert ok is False
    assert "连接超时" in n.last_err
    assert n._fail_streak == 1


def test_email_incomplete_config_short_circuits():
    n = _em(to="")
    with mock.patch("core.notifier.smtplib.SMTP_SSL") as SS:
        assert n.send("t", "d") is False
    SS.assert_not_called()


# ---- _build_msg：整页截图 CID 内嵌（related）/ 渲染失败降级轻壳 ----
# （形态 v2：首版 DOM 序列化整套发被 QQ 邮箱剥 <style> 实测证伪，
# 用户截图布局散架——改整页截图 CID 直出，视觉不依赖客户端 CSS）

_PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 64   # PNG 魔数开头的假 bytes


def test_build_msg_snapshot_related_with_cid():
    n = _em(snapshot_base="http://127.0.0.1:8765/")
    with mock.patch("core.emailshot.render_console_png",
                    return_value=_PNG) as rc:
        msg = n._build_msg("t", "正文行")
    rc.assert_called_once_with("http://127.0.0.1:8765/", LOG)
    assert msg.get_content_type() == "multipart/related"
    # 三个一级 part：alternative（纯文本+轻壳 HTML）+ PNG（CID 内嵌）
    parts = msg.get_payload()
    assert parts[0].get_content_type() == "multipart/alternative"
    assert parts[1].get_content_type() == "image/png"
    assert parts[1]["Content-ID"] == "<console-shot>"
    alt_parts = parts[0].get_payload()
    assert alt_parts[0].get_content_type() == "text/plain"
    assert alt_parts[1].get_content_type() == "text/html"
    _html = alt_parts[1].get_payload(decode=True).decode("utf-8")
    assert "cid:console-shot" in _html
    assert "正文行" in _html


# ---- 友好壳（形态 v3）：状态横幅色识态 / 分区 / 直达按钮 ----

def test_shell_banner_tier_colors():
    # 🎯 达标绿 / ❌ 中性灰 / 默认品牌蓝——打开邮件 1 秒以色识态
    from core.notifier import _banner_html
    h = _banner_html("🎯 机票监控｜已达标 可出手")
    assert "#e9f4ec" in h and "真达标 · 可出手" in h
    h = _banner_html("❌ 机票监控｜全部未达标")
    assert "#f1f3f6" in h and "未达标" in h
    h = _banner_html("心跳")
    assert "#eef4fc" in h and "机票监控推送" in h
    # 品牌名前缀不复读（Subject 已含），航线/日期等剩余信息保留
    assert "机票监控｜" not in _banner_html("🎯 机票监控｜已达标")


def test_shell_sections_and_launch_button():
    from core.notifier import _email_shell_html
    h = _email_shell_html("🎯 t", "#### 正文行",
                          launch="http://127.0.0.1:8765/")
    assert "🖥 控制台实时快照" in h
    assert "📨 推送详情" in h
    assert 'href="http://127.0.0.1:8765/"' in h
    assert "打开控制台看完整详情" in h
    assert "cid:console-shot" in h
    # 无 launch 不出按钮（不渲染死链接）
    h2 = _email_shell_html("🎯 t", "d", launch="")
    assert "打开控制台看完整详情" not in h2


def test_shell_no_snapshot_mode_omits_img():
    from core.notifier import _email_shell_html
    h = _email_shell_html("🎯 t", "正文行", with_snapshot=False)
    assert "cid:console-shot" not in h
    assert "正文行" in h   # 轻壳内 desp 仍完整可读


def test_build_msg_snapshot_failure_falls_back_to_alternative():
    n = _em(snapshot_base="http://127.0.0.1:8765/")
    with mock.patch("core.emailshot.render_console_png",
                    return_value=None):
        msg = n._build_msg("t", "正文行")
    assert msg.get_content_type() == "multipart/alternative"
    parts = msg.get_payload()
    assert parts[0].get_content_type() == "text/plain"
    assert parts[1].get_content_type() == "text/html"
    _html = parts[1].get_payload(decode=True).decode("utf-8")
    assert "机票监控" in _html and "正文行" in _html


def test_build_msg_no_snapshot_light_shell():
    assert _em()._build_msg("t", "d").get_content_type() == (
        "multipart/alternative")


def test_send_uses_snapshot_for_html_part():
    # 端到端：related 结构整体进 SMTP 载荷，纯文本降级在前
    n = _em(snapshot_base="http://127.0.0.1:8765/")
    with mock.patch("core.emailshot.render_console_png",
                    return_value=_PNG), \
         mock.patch("core.notifier.smtplib.SMTP_SSL") as SS:
        assert n.send("正文行标题", "正文行") is True
    import email as _email
    payload = SS.return_value.__enter__.return_value.sendmail.call_args[0][2]
    m = _email.message_from_string(payload)
    assert m.is_multipart() and "related" in m.get_content_type()
    assert "正文行" in m.get_payload()[0].get_payload()[0].get_payload(
        decode=True).decode("utf-8")


# ---- build_notifier 装配语义 ----

def test_build_email_parallel_with_dingtalk():
    n = build_notifier({"dingtalk": {"enabled": True, "webhook": "https://x"},
                        "email": {"enabled": True, "user": "a@163.com",
                                  "password": "pw", "to": "b@qq.com"}}, LOG)
    assert isinstance(n, CompositeNotifier)
    names = [type(m).__name__ for m in n.members]
    assert names == ["DingTalkNotifier", "EmailNotifier"]


def test_build_email_standalone():
    n = build_notifier({"email": {"enabled": True, "user": "a@163.com",
                                  "password": "pw", "to": "b@qq.com",
                                  "host": "smtp.qq.com"}}, LOG)
    assert isinstance(n, EmailNotifier) and n.host == "smtp.qq.com"


def test_build_dingtalk_priority_over_serverchan_unchanged():
    # 单选语义不得被邮件改动（及之前行为）
    n = build_notifier({"dingtalk": {"enabled": True, "webhook": "https://x"},
                        "serverchan": {"enabled": True,
                                       "send_key": "SCTx"}}, LOG)
    assert type(n).__name__ == "DingTalkNotifier"


def test_build_email_disabled_or_incomplete_not_assembled():
    assert build_notifier({"email": {"enabled": False, "user": "a@163.com",
                                     "password": "pw",
                                     "to": "b"}}, LOG) is None
    # 缺授权码：enabled=true 也不装（心跳会白打日志）
    assert build_notifier({"email": {"enabled": True, "user": "a@163.com",
                                     "to": "b"}}, LOG) is None
    assert build_notifier({}, LOG) is None


# ---- 多邮件渠道（emails 列表）：163/QQ 各配各的，自发自收互不依赖 ----

def test_build_multiple_emails_parallel_with_primary():
    n = build_notifier({
        "dingtalk": {"enabled": True, "webhook": "https://x"},
        "emails": [
            {"enabled": True, "host": "smtp.163.com", "user": "a@163.com",
             "password": "pw1", "to": "a@163.com"},
            {"enabled": True, "host": "smtp.qq.com", "user": "b@qq.com",
             "password": "pw2", "to": "b@qq.com"},
        ]}, LOG)
    assert isinstance(n, CompositeNotifier)
    names = [type(m).__name__ for m in n.members]
    assert names == ["DingTalkNotifier", "EmailNotifier", "EmailNotifier"]
    # 两个邮件实例各自独立（不同账号不同收件人）
    assert n.members[1].user == "a@163.com" and n.members[1].to == ["a@163.com"]
    assert n.members[2].user == "b@qq.com" and n.members[2].host == "smtp.qq.com"


def test_build_emails_only_multi():
    n = build_notifier({"emails": [
        {"enabled": True, "user": "a@163.com", "password": "pw",
         "to": "a@163.com"},
        {"enabled": False, "user": "x@qq.com", "password": "pw",
         "to": "x"},
        {"enabled": True, "user": "c@qq.com", "password": "pw",
         "to": "c@qq.com, a@163.com"},
    ]}, LOG)
    # 停用项不装；纯邮件多通道也是 Composite 并联
    assert isinstance(n, CompositeNotifier)
    assert [m.user for m in n.members] == ["a@163.com", "c@qq.com"]


def test_build_emails_takes_precedence_over_legacy_email():
    # emails 与旧 email 单对象同时在场：以 emails 为准（防同账号双发）
    n = build_notifier({
        "email": {"enabled": True, "user": "old@163.com",
                  "password": "pw", "to": "old@163.com"},
        "emails": [{"enabled": True, "user": "new@163.com",
                    "password": "pw", "to": "new@163.com"}],
    }, LOG)
    assert isinstance(n, EmailNotifier)
    assert n.user == "new@163.com"


# ---- CompositeNotifier：聚合语义与心跳退避 ----

class _Fake:
    def __init__(self, ok):
        self.ok = ok
        self.sent = []

    def send(self, title, desp="", at_mobiles=None, is_at_all=False,
             launch=""):
        self.sent.append((title, desp, launch))
        return self.ok


def test_composite_any_success_is_true_and_fanout():
    a, b = _Fake(True), _Fake(False)
    c = CompositeNotifier([a, b], LOG)
    assert c.send("t", "d", launch="http://x/") is True
    # 全通道收到同样参数（launch 透传——测试端点与正式链路同参）
    assert a.sent == [("t", "d", "http://x/")]
    assert b.sent == [("t", "d", "http://x/")]
    assert c._fail_streak == 0


def test_composite_all_fail_counts_streak_heartbeat_backoff():
    c = CompositeNotifier([_Fake(False), _Fake(False)], LOG)
    for _ in range(6):
        assert c.send("t", "d") is False
    # 连败 6 轮（HB_BACKOFF_AFTER）起心跳退避：放行计数从 1 起
    assert c._fail_streak == 6
    assert c.heartbeat_allow() is False   # 第 1 个跳过轮
    # 主通道复活（如邮件通而钉钉仍挂）→ 连败清零、心跳恢复
    c.members[0].ok = True
    assert c.send("t", "d") is True
    assert c._fail_streak == 0 and c.heartbeat_allow() is True


def test_composite_member_exception_does_not_kill_others():
    class _Boom:
        def send(self, *a, **k):
            raise TypeError("通道实现抛错")

    ok_m = _Fake(True)
    c = CompositeNotifier([_Boom(), ok_m], LOG)
    assert c.send("t", "d") is True      # 异常被兜，后续通道照发


if __name__ == "__main__":
    unittest.main()
