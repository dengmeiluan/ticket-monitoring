# -*- coding: utf-8 -*-
"""r338 渠道会话失效钉钉告警哨（用户提案：渠道问题应告警出来让人
方便干预）。

背景实录：qunar 会话失效后采集每轮空、「三路径空结果」WARNING 刷
日志数小时——日志用户不看，达标推送无达标不发生，UI 卡片 stale 又被
日历价清洗（同轮修复）——用户数小时后自己点开配置页才发现。**需人工
干预类渠道问题必须浮出到推送面**。

哨形态：login_suspect（类级失效证据，采集现场产生点捕获）连续 ≥2 轮
在燃 → 推钉钉（当日去重，_SENT_LAST/_SENT_CNT 复用）；连续 ≥3 日降
INFO 只记不再打扰；恢复（标记清零且昨日/今日在燃）→ 单条恢复通知。
单发零重试铁律不涉（send 一次，失败由下轮哨位自然再评）；正文短词面
（<224B 防指纹带）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r338_login_alert.py -q
"""
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_PLAT = "qunar"


class _FakeN:
    def __init__(self):
        self.sent = []
        # 生产传的是 (user, Alerter) 对，哨读 al.notifier——fake 同构
        # 包一层（mock 尊重公共契约，廿三§8）
        self.notifier = self

    def send(self, title, desp):
        self.sent.append((title, desp))
        return True


def _fresh():
    import main
    from crawlers import REGISTRY
    old = getattr(REGISTRY[_PLAT], "login_suspect", None)
    main._LOGIN_ALERT_STREAK.clear()
    main._SENT_LAST.clear()
    main._SENT_CNT.clear()
    return main, REGISTRY, old


def _teardown(main, REGISTRY, old):
    REGISTRY[_PLAT].login_suspect = old
    main._LOGIN_ALERT_STREAK.clear()
    main._SENT_LAST.clear()
    main._SENT_CNT.clear()


def test_two_burning_rounds_push_once(monkeypatch):
    """连续 ≥2 轮在燃推一条告警；当日去重不重推。"""
    main, REGISTRY, old = _fresh()
    try:
        n = _FakeN()
        monkeypatch.setattr(REGISTRY[_PLAT], "login_suspect", True)
        users = [{"platforms": [_PLAT]}]
        main._channel_login_alert_sentinel([(users[0], n)], logger := logging.getLogger("t"))
        main._channel_login_alert_sentinel([(users[0], n)], logger)
        assert len(n.sent) == 1, "连续 2 轮在燃恰推 1 条（单轮瞬时风控不鸣）"
        title, desp = n.sent[0]
        assert _PLAT in desp and "登录" in desp, "词面带渠道与干预动作"
        main._channel_login_alert_sentinel([(users[0], n)], logger)
        assert len(n.sent) == 1, "当日去重（_SENT_LAST）不重推"
    finally:
        _teardown(main, REGISTRY, old)


def test_single_round_silent(monkeypatch):
    """单轮在燃不推（瞬时风控常态）。"""
    main, REGISTRY, old = _fresh()
    try:
        n = _FakeN()
        monkeypatch.setattr(REGISTRY[_PLAT], "login_suspect", True)
        main._channel_login_alert_sentinel([({"platforms": [_PLAT]}, n)],
                                           logging.getLogger("t"))
        assert n.sent == []
    finally:
        _teardown(main, REGISTRY, old)


def test_recovery_notifies_once(monkeypatch):
    """在燃推过之后恢复 → 单条恢复通知；再一轮恢复不重推。"""
    main, REGISTRY, old = _fresh()
    try:
        n = _FakeN()
        monkeypatch.setattr(REGISTRY[_PLAT], "login_suspect", True)
        main._channel_login_alert_sentinel([({"platforms": [_PLAT]}, n)],
                                           logging.getLogger("t"))
        main._channel_login_alert_sentinel([({"platforms": [_PLAT]}, n)],
                                           logging.getLogger("t"))
        assert len(n.sent) == 1
        monkeypatch.setattr(REGISTRY[_PLAT], "login_suspect", False)
        main._channel_login_alert_sentinel([({"platforms": [_PLAT]}, n)],
                                           logging.getLogger("t"))
        assert len(n.sent) == 2, "恢复推单条通知"
        assert "恢复" in n.sent[1][1]
        main._channel_login_alert_sentinel([({"platforms": [_PLAT]}, n)],
                                           logging.getLogger("t"))
        assert len(n.sent) == 2, "恢复态不重复推"
    finally:
        _teardown(main, REGISTRY, old)


def test_streak_survives_restart(monkeypatch, tmp_path):
    """streak 持久化：跨进程重启累计（生产实录——12:47 重启清内存
    streak，70 分钟长轮+频繁重启下内存态永到不了 2=告警哑火）。
    形态：第一轮尾存盘 → 模拟重启（清内存+重载哨状态）→ 第二轮尾
    直接触发首鸣。"""
    main, REGISTRY, old = _fresh()
    try:
        n = _FakeN()
        monkeypatch.setattr(REGISTRY[_PLAT], "login_suspect", True)
        monkeypatch.setattr(main, "_sent_state_path",
                            lambda: str(tmp_path / "sent.json"))
        users = [{"platforms": [_PLAT]}]
        main._channel_login_alert_sentinel([(users[0], n)],
                                           logging.getLogger("t"))
        assert len(n.sent) == 0, "重启前第一轮 streak=1 不鸣"
        # 模拟进程重启：内存全清 + 从哨状态文件回填
        main._LOGIN_ALERT_STREAK.clear()
        main._SENT_LAST.clear()
        main._SENT_CNT.clear()
        main._sent_load()
        main._channel_login_alert_sentinel([(users[0], n)],
                                           logging.getLogger("t"))
        assert len(n.sent) == 1, (
            "重启后 streak 从持久化继续（=2）应首鸣——内存态在长轮"
            "周期+频繁重启下永到不了 2（生产实录哑火）")
    finally:
        _teardown(main, REGISTRY, old)


def test_unrelated_platform_not_alerted(monkeypatch):
    """用户未启用该渠道 → 不推（多租户告警面按启用平台过滤）。"""
    main, REGISTRY, old = _fresh()
    try:
        n = _FakeN()
        monkeypatch.setattr(REGISTRY[_PLAT], "login_suspect", True)
        for _ in range(3):
            main._channel_login_alert_sentinel(
                [({"platforms": ["ctrip"]}, n)], logging.getLogger("t"))
        assert n.sent == []
    finally:
        _teardown(main, REGISTRY, old)
