# -*- coding: utf-8 -*-
"""r318 钉钉正文防内容指纹时刻行：

钉钉机器人查重为**正文主体模糊指纹**（探针矩阵实锤：与心跳轮仅差
图链时间戳的相似变体仍 -1「系统繁忙」，全新内容 ok；-1 响应 ~3.2s
慢回暴露服务端查重处理，ok 响应 ~0.2s）——价格平稳期心跳正文主体
逐轮恒定（仅图链文件名带时刻，URL 不参与指纹），命中重复指纹后
**应答恒 -1 但照常投递**（幽灵送达族：用户实锤 558 条 -1 零丢失），
连带连败退避、日报防重发走幽灵分支、弹窗告警常亮。

修复：send 出站正文尾部携带生成时刻 ⏰ HH:MM——指纹逐轮变化不再
命中查重（恢复真 ok），同时向读者交代推送时刻。放 send 层（钉钉
通道专属，其他通道零影响）；置于截断之后恒落位（地板档纪律）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r318_dingfp.py -q
"""
import logging
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime as _real_dt
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.notifier as _nm  # noqa: E402
from core.notifier import DingTalkNotifier  # noqa: E402


class _R:
    def __init__(self):
        self.text = str({"errcode": 0})

    def json(self):
        return {"errcode": 0}


def test_dingtalk_desp_carries_fingerprint_time():
    """出站正文尾部携带 ⏰ HH:MM 生成时刻（防内容指纹行恒落位）。"""
    captured = {}

    def _fake_post(url, json=None, **k):
        captured["payload"] = json
        return _R()

    orig = _nm.httpx.post
    orig_dt = _nm.datetime
    _nm.httpx.post = _fake_post
    # 时刻来源钉到固定值：证明词面取自 datetime.now() 而非写死
    _nm.datetime = SimpleNamespace(now=lambda: _real_dt(2026, 10, 16, 14, 7))
    work = tempfile.mkdtemp(prefix="ding_fp_")
    old = os.getcwd()
    os.chdir(work)
    try:
        d = DingTalkNotifier("https://oapi.dingtalk.com/robot/x",
                             logging.getLogger("t"))
        assert d.send("标题", "正文内容") is True
        text = captured["payload"]["markdown"]["text"]
        assert "正文内容" in text, "原正文须保留"
        assert re.search(r"⏰ 14:07\s*$", text), repr(text[-40:])
    finally:
        _nm.httpx.post = orig
        _nm.datetime = orig_dt
        os.chdir(old)
        shutil.rmtree(work, ignore_errors=True)


def test_dingtalk_fingerprint_time_after_truncation():
    """超长 desp 截断后时刻行仍恒落位（地板档：截断产物+⏰ 行）。"""
    captured = {}

    def _fake_post(url, json=None, **k):
        captured["payload"] = json
        return _R()

    orig = _nm.httpx.post
    orig_dt = _nm.datetime
    _nm.httpx.post = _fake_post
    _nm.datetime = SimpleNamespace(now=lambda: _real_dt(2026, 10, 16, 9, 30))
    work = tempfile.mkdtemp(prefix="ding_fp2_")
    old = os.getcwd()
    os.chdir(work)
    try:
        d = DingTalkNotifier("https://oapi.dingtalk.com/robot/x",
                             logging.getLogger("t"))
        big = "很长的正文" * 5000   # 远超 18000 字节
        assert d.send("标题", big) is True
        text = captured["payload"]["markdown"]["text"]
        assert len(text.encode("utf-8")) <= 18000, len(text.encode("utf-8"))
        assert re.search(r"⏰ 09:30\s*$", text), repr(text[-40:])
    finally:
        _nm.httpx.post = orig
        _nm.datetime = orig_dt
        os.chdir(old)
        shutil.rmtree(work, ignore_errors=True)


# ---- 未达标心跳正文小型化（方案 A：防内容指纹的产品级正解） ----

def _route():
    from core.models import Route as _R
    return _R(from_code="SHA", to_code="URC", from_name="上海",
              to_name="乌鲁木齐", dates=["2026-09-25"],
              alert_direct=1900, alert_transfer=1700)


def _sections():
    return [{"date": "2026-09-25",
             "best_direct": {"price": 1950, "name": "MU8369",
                             "depTime": "19:55", "arrTime": "01:25",
                             "_platform": "qunar"},
             "best_transfer": None,
             "seen_plats": ["qunar"]}]


def test_digest_heartbeat_body_slim():
    """未达标心跳正文小型化：3815 字节恒定大正文每轮命中钉钉模糊查重
    （绝对相似量 ~2000 字节阈值，探针矩阵实锤）→ 应答恒 -1 但照常投
    递；224 字节小正文恒定连发实测零命中。断言：未达标轮 desp ≤700
    字节、含每航线 KPI 摘要行、不含图例行（总表图内自含）。"""
    import logging
    from core.alerter import Alerter
    a = Alerter(logging.getLogger("t"), storage=None, digest=True)
    a.round_charts = {}
    p = a._digest_payload([(_route(), _sections())],
                          fresh=False, with_tables=False)
    desp = p["desp"]
    assert len(desp.encode("utf-8")) <= 700, (
        len(desp.encode("utf-8")), desp[:200])
    assert "全部未达标" in desp
    assert "直飞 ￥1950" in desp, desp
    assert "🟩" not in desp, "图例行应省略（总表图内自含）"


# ---- 心跳形态三态配置（可配置/建议化/健壮降级） ----

def _mk(style, fail_streak=None):
    import logging
    from core.alerter import Alerter

    class _N:
        _fail_streak = 0 if fail_streak is None else fail_streak

    a = Alerter(logging.getLogger("t"), storage=None, digest=True,
                notifier=_N(), heartbeat_style=style)
    a.round_charts = {}
    return a


def test_heartbeat_style_slim_default():
    """slim（默认推荐）：未达标心跳轻量摘要——防钉钉正文模糊查重
    （绝对相似量 ~2000 字节阈值实测），状态恢复真 ok。未知配置值
    同落 slim（安全默认）。"""
    for style in ("slim", "", "未知值"):
        a = _mk(style)
        assert a._hb_slim() is True, style
        p = a._digest_payload([(_route(), _sections())],
                              fresh=False, with_tables=False,
                              slim=a._hb_slim())
        assert len(p["desp"].encode("utf-8")) <= 700


def test_heartbeat_style_full():
    """full：全量图文形态（用户显式选择）——正文主体超钉钉判重阈值，
    应答将恒 -1「系统繁忙」（消息仍送达）；选此档即接受假失败状态，
    配置页须如实标注。形态断言用结构词面（小节标题/KPI 行），夹具
    数据量小、字节数断言不适用。"""
    a = _mk("full")
    assert a._hb_slim() is False
    p = a._digest_payload([(_route(), _sections())],
                          fresh=False, with_tables=False,
                          slim=a._hb_slim())
    assert "#### ✈️" in p["desp"], "全量小节标题在场"
    assert "MU8369" in p["desp"], "KPI 行含航班身份（轻量形态仅价格）"


def test_heartbeat_style_auto_downgrades_on_streak():
    """auto：全量优先（前期观感完整），钉钉连败 ≥3（判重实锤）自动
    降为轻量——健壮形态：最后能完全成功（状态恢复真 ok）。跨轮形态
    自适应，单发零重试铁律不动。非钉钉通道（无 _fail_streak）恒全量
    （无指纹问题）。形态断言用结构词面（小节标题 vs 单行摘要）。"""
    a = _mk("auto", fail_streak=0)
    assert a._hb_slim() is False, "auto 前期按全量"
    p = a._digest_payload([(_route(), _sections())],
                          fresh=False, with_tables=False,
                          slim=a._hb_slim())
    assert "#### ✈️" in p["desp"], "前期全量小节"
    a2 = _mk("auto", fail_streak=3)
    assert a2._hb_slim() is True, "连败 ≥3 降轻量"
    p2 = a2._digest_payload([(_route(), _sections())],
                            fresh=False, with_tables=False,
                            slim=a2._hb_slim())
    assert "#### ✈️" not in p2["desp"], "降级后轻量行（无小节标题）"
    a3 = _mk("auto")   # notifier 无 _fail_streak（非钉钉通道）
    a3.notifier = None
    assert a3._hb_slim() is False, "非钉钉通道无指纹，auto 恒全量"
