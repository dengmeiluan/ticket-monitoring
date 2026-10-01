# -*- coding: utf-8 -*-
"""r233 WD 审校落地钉（_scratch/r233_wd_push.md 消化）：

- P1-1  tie 组达标 OR 五处口径收齐：KPI 行1/总表 summary/单航线 KPI
        与已收口的总表行·日报绿行·🔥 同语言（曾同推送内总表绿行+
        🔥+电话已响、KPI 却挂 🟩+「（行情价）」注自相矛盾）
- P2-1  _local_push_image 路径穿越加固：URL ../ 形态只读 data/ 内
- P2-2  遗留单航线 digest 路径电话去抖（fresh_hits 上移）+ 🔔 持续
        达标档（与 multi 路径时序对齐）
- P2-3  storm_repeat 上限钳制 5（webui 声明域 1-5 互钉）
- P2-6  _channel_market_lines 守卫链尾地板档 + 备1 budget 地板 8
        （长平台键病理形态下行宽恒 ≤40）
- 备2   _send_urgent 分发落账 ch=urgent（控制台推送记录对电话可见）
- 备3a  风暴透传主推 launch（ntfy 点击跳转仅主推有曾缺风暴）
- 备6   _mini_kpi 未设线分支词面与 th 分支同贴法（label 与价格间空格）
- 备7   EmailNotifier 失败落账带 img 注（成功路径已有）

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v15133_wd.py -q
"""
import json
import logging
import os
import sys
import time as _time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.notifier as notifier_mod  # noqa: E402
from core.alerter import Alerter, _disp_dw  # noqa: E402
from core.models import FlightPrice, Route  # noqa: E402
from core.notifier import EmailNotifier, _local_push_image  # noqa: E402
from core.storage import PriceStorage  # noqa: E402

_LOG = logging.getLogger("t15133wd")


def _fp(plat, price=1600, tbg="", code="MU5700", trans="兰州"):
    return {"price": price, "name": "东航" + code, "code": code,
            "depTime": "10:00", "arrTime": "15:00",
            "depDate": "2026-10-06", "arrDate": "2026-10-06",
            "transCity": trans, "crossDayDesc": "",
            "totalDuration": "9时30分", "_platform": plat,
            "transferBaggage": tbg, "layoverM": 120}


def _ps(fs, fc="URC", tc="SHA", d="2026-10-06"):
    return [FlightPrice(platform=f["_platform"], from_city=fc, to_city=tc,
                        depart_date=d, price=f["price"],
                        extra=json.dumps([f], ensure_ascii=False))
            for f in fs]


def _route(**kw):
    d = dict(from_code="URC", to_code="SHA", from_name="乌鲁木齐",
             to_name="上海", dates=["2026-10-06"],
             alert_direct=0, alert_transfer=1700,
             transfer_arrival_max="23:59", transfer_baggage="direct")
    d.update(kw)
    return Route(**d)


class FakeN:
    def __init__(self):
        self.sent = []

    def send(self, t, d, at_mobiles=None, is_at_all=False, launch=""):
        self.sent.append({"title": t, "desp": d, "launch": launch})
        return True


# ---- WD-P1-1 tie 组 OR 五处口径收齐 -------------------------

def test_kpi_transfer_tie_or():
    """直挂筛选航线上同价同班 tie 组任一成员合规即组合规：KPI 行1
    中转位出 🎯 且行情注家族（（行情价）/*行情/行情价 三降级档）全部
    绝迹——首成员单判曾让 KPI 与总表绿行/🔥 同屏自相矛盾。"""
    a = Alerter(_LOG, notifier=FakeN(), storage=None, digest=True, user="t")
    a.check_multi([(_route(), _ps([_fp("fliggy"), _fp("ctrip", tbg="direct")]))])
    desp = a.notifier.sent[0]["desp"]
    assert "🎯" in desp
    assert "行情价" not in desp
    assert "*行情" not in desp


def test_summary_transfer_tie_or(monkeypatch):
    """总表图 summary 中转位同口径：kpi_tier_txt 消费组 OR 的 qual——
    破线档显「·已达标」不显「·行情」（图脱离消息上下文可判可出手）。
    summary 随 render_flights_table(summary=…) 进 PNG，钉捕参数。"""
    import report as rep
    captured = {}
    monkeypatch.setattr(rep, "render_flights_table",
                        lambda *a, **k: captured.update(k) or "x.png")
    monkeypatch.setattr(rep, "upload_chart", lambda *a, **k: "https://c/x.png")
    a = Alerter(_LOG, notifier=FakeN(), storage=None, digest=True, user="t")
    r = _route()
    secs = a._build_sections(
        r, _ps([_fp("fliggy"), _fp("ctrip", tbg="direct")]))
    a._flights_table_md_multi([(r, secs)])
    summary = "｜".join(captured.get("summary") or [])
    assert "低￥100·真达标" in summary
    assert "·行情" not in summary


# ---- WD-P2-2 遗留 digest 路径去抖 + 🔔 档 -------------------

def test_legacy_digest_debounce_and_bell(tmp_path):
    """单航线遗留 digest 路径与 multi 同律：fresh_hits 去抖先于
    _send_urgent——2h 内持续达标第二轮不重拨、主推标题 🔔（曾每轮
    重拨且恒 🚨，与「电话已提醒过」语义相反）。"""
    urgent_calls = []
    a = Alerter(_LOG, notifier=FakeN(),
                storage=PriceStorage(str(tmp_path / "p.db")),
                digest=True, user="t")

    def _no_urgent(*args, **kwargs):
        # 尊重真函数契约：hits 空=不拨（持续达标轮 fresh 空仍会以
        # 空列表调用，真函数早退不拨号）
        hits_arg = args[2] if len(args) > 2 else kwargs.get("hits")
        if hits_arg:
            urgent_calls.append(1)
        return True

    a._send_urgent = _no_urgent
    r = _route()
    p = _ps([_fp("fliggy"), _fp("ctrip", tbg="direct")])
    a.check_and_alert(r, p)
    n1 = len(urgent_calls)
    a.check_and_alert(r, p)
    assert n1 == 1, "首轮应拨且仅拨一次"
    assert len(urgent_calls) == 1, "第二轮持续达标不应重拨（2h 去抖）"
    assert "🔔" in a.notifier.sent[-1]["title"]


# ---- WD-P2-1 图链本地直读路径穿越 ---------------------------

def test_local_push_image_traversal(tmp_path, monkeypatch):
    """URL ../ 形态不得越出 data/（穿越曾可读仓库内任意 .png 并 CID
    内嵌进外发邮件）；正常 URL 直读行为不变。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    # 本地名=URL stem（无时分段）——确定性映射「{stem}_{HHMMSS}.png ↔
    # data/{stem}.png」的 fixture 须对齐生产构造
    (tmp_path / "data" / "trend_u_URC_SHA.png").write_bytes(b"PNGOK")
    (tmp_path / "secret_123456.png").write_bytes(b"TOPSECRET")
    assert _local_push_image(
        "https://cdn/charts/20261006/../secret_123456.png") == b""
    assert _local_push_image(
        "https://cdn/charts/20261006/trend_u_URC_SHA_123456.png") == b"PNGOK"


# ---- WD-P2-3 storm_repeat 声明域钳制 ------------------------

def test_storm_repeat_clamp():
    """storm_repeat 入模钳制 1-5（webui 声明域互钉）：8 曾实发 5 而
    标题写「n/8」，5/8-8/8 永不出现。"""
    assert Alerter(_LOG, notifier=None, storage=None,
                   storm_repeat=8).storm_repeat == 5
    assert Alerter(_LOG, notifier=None, storage=None,
                   storm_repeat=0).storm_repeat == 1
    assert Alerter(_LOG, notifier=None, storage=None,
                   storm_repeat=3).storm_repeat == 3


# ---- WD-P2-6 + 备1 守卫链尾地板档 ---------------------------

def test_channel_market_lines_floor_tops():
    """tops 分支长平台键（病理形态 >34 半角前缀）：整行渲染宽恒
    ≤40 半角（前缀自身进预算 + budget 地板 8）。"""
    a = Alerter(_LOG, notifier=None, storage=None, user="t")
    key = "X" * 40
    s = {"date": "2026-10-06", "platform_mins": {key: 1234.0},
         "plat_top3": {key: [_fp("qunar", price=1234.0)]}}
    for ln in (l for l in a._channel_market_lines([s]).split("\n")
               if l.strip()):
        assert _disp_dw(ln) <= 40, ln


def test_channel_market_lines_floor_else():
    """else 分支（无明细只有全线价）长平台键：链尾地板档恒达标
    （曾两档 fallback 均含渠道名原文，71 半角原样吐出）。"""
    a = Alerter(_LOG, notifier=None, storage=None, user="t")
    s = {"date": "2026-10-06", "platform_mins": {"X" * 40: 1234.0}}
    for ln in (l for l in a._channel_market_lines([s]).split("\n")
               if l.strip()):
        assert _disp_dw(ln) <= 40, ln


# ---- 备2 _send_urgent 分发落账 ------------------------------

def test_send_urgent_history(tmp_path, monkeypatch):
    """强提醒分发落账 ch=urgent：控制台「推送记录」对电话/弹窗不再
    失明（钉钉单发落账已有，urgent 三通道曾不入账）。"""
    monkeypatch.setenv("PUSH_HISTORY_FILE", str(tmp_path / "ph.jsonl"))
    a = Alerter(_LOG, notifier=FakeN(), storage=None, user="t")
    r = _route()
    hit = (r, {"date": "2026-10-06"}, "中转",
           _fp("ctrip", tbg="direct"), 1700.0)
    a._send_urgent("T", "D", [hit])
    if not (tmp_path / "ph.jsonl").exists():
        recs = []
    else:
        recs = [json.loads(l) for l in (tmp_path / "ph.jsonl")
                .read_text(encoding="utf-8").splitlines() if l.strip()]
    assert any(x.get("ch") == "urgent" for x in recs)


# ---- 备3a 风暴透传主推 launch -------------------------------

def test_storm_launch_passthrough(monkeypatch):
    """风暴条与主推同 launch（ntfy 点击跳转曾仅主推有）。"""
    raw_sleep = _time.sleep
    monkeypatch.setattr(_time, "sleep", lambda s: None)
    calls = []

    class CapN:
        def send(self, t, d, at_mobiles=None, is_at_all=False, launch=""):
            calls.append(launch)
            return True

    a = Alerter(_LOG, notifier=CapN(), storage=None, storm_repeat=2,
                user="t", base_url="https://pub.example")
    a._storm("T", "D", [], launch="https://pub.example/n/1")
    for _ in range(100):
        if calls:
            break
        raw_sleep(0.05)
    assert calls and calls[0] == "https://pub.example/n/1"


# ---- 备6 _mini_kpi 未设线词面贴法 ---------------------------

def test_mini_kpi_noline_spacing():
    """未设线分支「中转￥1600」与 th 分支「{dot}中转 ￥N」贴法对齐
    （label 与价格间空格，同消息内两种贴法曾并存；mini 仅多日期
    航线渲染——两日期数据驱动）。"""
    a = Alerter(_LOG, notifier=FakeN(), storage=None, digest=True, user="t")
    r = _route(alert_direct=1700, alert_transfer=0,
               dates=["2026-10-06", "2026-10-07"])
    fs = [_fp("qunar", code="CZ1234", price=1500, trans=""),
          _fp("fliggy", code="MU5700", price=1600),
          _fp("qunar", code="CZ1234", price=1520, trans=""),
          _fp("fliggy", code="MU5700", price=1620)]
    a.check_multi([(r, _ps(fs)[:2] + _ps(fs[2:], d="2026-10-07"))])
    desp = a.notifier.sent[0]["desp"]
    # mini 未设线分支裸贴形态「中转[￥1620](url)」（label 紧贴链接壳）
    # vs th 分支「{dot}中转 [￥N](url)」——对齐后裸贴绝迹
    assert "中转[￥" not in desp
    assert "中转 [￥" in desp


# ---- 备7 email 失败落账带 img 注 ----------------------------

def test_email_fail_history_img_kwarg(tmp_path, monkeypatch):
    """EmailNotifier 失败路径 _append_push_history 带 img 参（成功
    路径已有）：图挂＋发送同败时控制台可见图内嵌状态。"""
    cap = {}
    monkeypatch.setenv("PUSH_HISTORY_FILE", str(tmp_path / "ph.jsonl"))
    monkeypatch.setattr(notifier_mod, "_append_push_history",
                        lambda *a, **k: cap.update(k))
    import smtplib

    class Boom:
        def __init__(self, *a, **k):
            raise OSError("smtp down")

    monkeypatch.setattr(smtplib, "SMTP_SSL", Boom)
    monkeypatch.setattr(smtplib, "SMTP", Boom)
    en = EmailNotifier("smtp.test", 465, "a@b.c", "pw", "d@e.f", _LOG)
    en.send("T", "D")
    assert cap.get("ch") == "email"
    assert "img" in cap


# ---- WD-P2-4 日报图挂 TOP5 文本兜底（能力对称） --------------

def test_daily_table_fail_text_top3(monkeypatch):
    """日报明细图挂（turl=None）时 TOP5 明细不再整段蒸发：文本式
    明细行兜底（与告警路径 _top3_blocks/_channel_market_lines 能力
    对称——日报是每日唯一综合视图，容量曾只剩 KPI 三行）。"""
    import report as rep
    monkeypatch.setattr(rep, "prepare_round_charts",
                        lambda c, lg, *a, **k: {("SHA", "URC", "2026-09-25"):
                                                "http://x/t.png"})
    monkeypatch.setattr(rep, "_route_latest_flights",
                        lambda db, fc, tc, d, **kw: [
                            {"price": 2690, "transCity": "",
                             "_platform": "qunar", "depTime": "10:00",
                             "arrTime": "15:00", "depDate": "2026-09-25",
                             "arrDate": "2026-09-25", "crossDayDesc": "",
                             "code": "CZ6976", "name": "南航CZ6976",
                             "totalDuration": "5时"},
                            {"price": 2150, "transCity": "郑州",
                             "_platform": "ctrip", "depTime": "12:05",
                             "arrTime": "00:35", "arrDate": "2026-09-26",
                             "crossDayDesc": "+1天", "code": "MU2301",
                             "name": "东航MU2301", "totalDuration": "12时30分"}])
    monkeypatch.setattr(rep, "render_flights_table", lambda *a, **k: None)
    monkeypatch.setattr(rep, "upload_chart", lambda *a, **k: None)
    sent = {}

    class FakeN:
        def send(self, title, desp="", **kw):
            sent["desp"] = desp
            return True

    cfg = {"notifier": {"image_host": {"provider": "ghimg"}},
           "users": [{"name": "u", "routes": [
               {"from": "SHA", "to": "URC", "from_name": "上海",
                "to_name": "乌鲁木齐", "dates": ["2026-09-25"],
                "alert_direct": 2000, "alert_transfer": 1800,
                "transfer_arrival_max": "02:00"}],
               "notifier": {"image_host": {"provider": "ghimg"}}}]}
    ok = rep.build_and_push(cfg, _LOG, FakeN(), user="u")
    assert ok
    desp = sent["desp"]
    assert "明细表上传失败" in desp or "明细表生成失败" in desp
    # 兜底区独有断言（S-P2-3：价格由 KPI 兜底本就携带，弱钉漏过
    # 删兜底的变异——锚兜底头行与航班号明细本体）
    assert "明细图未出，文本兜底" in desp
    assert "CZ6976" in desp and "MU2301" in desp
    assert "￥2690" in desp, "直飞池最低价文本兜底缺失"
    assert "￥2150" in desp, "中转池最低价文本兜底缺失"


# ---- WD-P2-5 日报对账注补两族（能力对称） --------------------

def test_daily_ops_notes_direct_missing_and_xphan():
    """日报运维对账注补「直挂标注缺失」「孤低价拦截」两族（与告警
    侧 _ops_notes 同族同语言）：曾读者无法区分「没有便宜班次」与
    「有班被守卫/判据剔除」。"""
    from report import _daily_ops_notes
    notes = _daily_ops_notes(
        ["qunar"], {"qunar"}, ("上海", "乌鲁木齐"), "2026-09-25",
        mkt_t=[{"price": 2150, "transCity": "郑州", "_platform": "ctrip"}],
        xphans=[("fliggy", 1899.0)], transfer_baggage="direct")
    joined = "｜".join(notes)
    assert "中转直挂标注缺失" in joined
    assert "孤低价拦截×1" in joined and "￥1899" in joined
    # 非直挂配置/无缺勤 → 两族不注（全勤返空不漂移）
    assert _daily_ops_notes(["qunar"], {"qunar"}, ("上海", "乌鲁木齐"),
                            "2026-09-25") == []
