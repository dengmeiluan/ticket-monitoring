# -*- coding: utf-8 -*-
"""全链路精细化轮（r233）：ctrip 二段起飞时刻组 + tie 组达标 OR +
trend 图租户段 + 截循环浮点累计。

- D-1 ctrip 中转二段起飞时刻组：源 mutilstn[1].dateinfo.ddate（中转行
  双 dump 复证 100% 在场），复用 qunar 既有 lay2dep/transGoDate 键与
  webui「二段 X 起飞」渲染位，零新键。守卫同 qunar 纪律：
  lay2dep≠整体起飞（防渠道复制态假值）、transGoDate 晚于出发日才落
  （跨天辨识信息）、仅中转行落。
- P-1 tie 组达标 OR：同价同班多渠道合并行（_dedup_tie）的达标判定
  曾只看池序首渠道——transferBaggage 渠道差是成员间唯一实质差，
  首成员不合规≠组不合规（同价时点哪家都一样，组语义=「这个价能不
  能合规买到」任一成员合规即真）。_dedup_tie 随行携带第 2+ 成员
  快照 (_platform, transferBaggage, layoverM)（arrTime/depTime/code/
  price 全在合并键内恒同），_tie_any_ok 组 OR 单源消费；report 路径
  _qual 预打（dedup 前逐成员），OR 聚合在 _dedup_tie 内同轮收口。
- P-2 trend PNG 租户段：prepare_round_charts 增 user 参——只遍历该
  用户 routes（多租户同 OD 时首遇配置胜出的内容级渗漏根治）+ 命名
  带 _png_user_tag（本地互覆根治）；main 侧 chart_cache 按用户分片。
- P-3 report 截循环浮点累计：_trim 逐字累计换 _dw_raw——ceil 后单
  字符值把数字 1.125 放大成 2（+78%），含数字的航线名截断点系统性
  提前（alerter 同族五处已改，report 两处漏）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v15133_round.py -q
"""
import json
import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.ctrip import CtripCrawler  # noqa: E402
from core.alerter import _dedup_tie  # noqa: E402
try:
    from core.alerter import _tie_any_ok  # noqa: E402
except ImportError:   # TDD 红：_tie_any_ok 尚未实现（P-1 功能缺失）
    _tie_any_ok = None
import report as rep  # noqa: E402

_LOG = logging.getLogger("t15133")
_CT = CtripCrawler({}, _LOG)


# ---- D-1 ctrip 二段起飞时刻组 -------------------------------

def _seg(dd, ad, flgno="GS7529", city=""):
    ap = {"bsname": "T2", "aport": "SHA"}
    if city:
        ap["city"] = city
    return {"dateinfo": {"ddate": dd, "adate": ad},
            "basinfo": {"flgno": flgno},
            "dportinfo": {"bsname": "", "aport": "URC"},
            "aportinfo": ap}


def _item(segs, price=2457):
    return {"pid": "", "mutilstn": segs,
            "policyinfo": [{"tprice": price, "quantity": 5, "drate": 5.2}]}


def _one(item):
    rows = _CT._extract_ctrip_flights(json.dumps([item]))
    assert rows, "中转行应解析成功"
    return rows[0]


def test_ctrip_lay2dep_crossday():
    """跨天中转：lay2dep=二段起飞 HH:MM，transGoDate=二段出发日期。"""
    r = _one(_item([
        _seg("2026-10-06 16:40:00", "2026-10-06 19:30:00", "GS7529", "兰州"),
        _seg("2026-10-07 07:25:00", "2026-10-07 09:55:00", "MU5700")]))
    assert r["transCity"] == "兰州"
    assert r["lay2dep"] == "07:25"
    assert r.get("transGoDate") == "2026-10-07"


def test_ctrip_lay2dep_sameday_no_tgd():
    """同天中转：lay2dep 照落（换机规划信息），transGoDate 不落
    （晚于出发日才落——同天二段日期无辨识增量）。"""
    r = _one(_item([
        _seg("2026-10-06 08:00:00", "2026-10-06 10:30:00", "GS7529", "兰州"),
        _seg("2026-10-06 13:00:00", "2026-10-06 15:40:00", "MU5700")]))
    assert r["lay2dep"] == "13:00"
    assert "transGoDate" not in r


def test_ctrip_lay2dep_copy_guard():
    """复制态守卫：二段起飞==整体起飞（渠道复制态假值）不落。"""
    r = _one(_item([
        _seg("2026-10-06 08:00:00", "2026-10-06 10:30:00", "GS7529", "兰州"),
        _seg("2026-10-06 08:00:00", "2026-10-06 15:40:00", "MU5700")]))
    assert "lay2dep" not in r


def test_ctrip_lay2dep_direct_absent():
    """直飞行：两键均不落（仅中转行）。"""
    r = _one(_item([_seg("2026-10-06 16:40:00", "2026-10-06 21:30:00")]))
    assert "lay2dep" not in r
    assert "transGoDate" not in r


# ---- P-1 tie 组达标 OR -------------------------------

def _tie_row(plat, tbg="", lm=None, qual=None, price=1000):
    f = {"code": "MU5700", "depTime": "10:00", "arrTime": "15:00",
         "transCity": "兰州", "crossDayDesc": "", "stopover": "",
         "price": price, "_platform": plat,
         "transferBaggage": tbg, "layoverM": lm}
    if qual is not None:
        f["_qual"] = qual
    return f


def test_dedup_tie_qual_or_aggregate():
    """report 路径（_qual 预打）：首成员不合规、第二成员合规——
    合并行 _qual 应为组 OR（现状只保首成员=假，漏标达标）。"""
    a = _tie_row("qunar", "", None, qual=False)
    b = _tie_row("ctrip", "direct", 120, qual=True)
    out = _dedup_tie([a, b])
    assert len(out) == 1
    assert out[0]["_qual"] is True
    # 双 False 保持 False（无假绿）
    out2 = _dedup_tie([_tie_row("qunar", "", None, qual=False),
                       _tie_row("ctrip", "", None, qual=False)])
    assert out2[0]["_qual"] is False


def test_dedup_tie_snapshot_members():
    """合并行携带第 2+ 成员快照 (platform, transferBaggage, layoverM)。"""
    out = _dedup_tie([_tie_row("qunar", "direct", 120),
                      _tie_row("ctrip", "", None),
                      _tie_row("fliggy", "direct", 90)])
    assert out[0]["_tie_rows"] == [("ctrip", "", None),
                                   ("fliggy", "direct", 90)]
    # 无合并的单行不携带快照（零漂移）
    assert "_tie_rows" not in _dedup_tie([_tie_row("qunar")])[0]


class _Route:
    transfer_arrival_max = "02:00"
    transfer_layover_min = 0
    transfer_baggage = "direct"


def test_tie_any_ok_transfer_member():
    """alerter 路径（dedup 后设判定）：首成员无直挂标注、成员快照
    有——transfer_baggage=direct 配置下组 OR 应真（现状假=漏标达标）。"""
    g = _dedup_tie([_tie_row("qunar", "", None),
                    _tie_row("ctrip", "direct", 100)])[0]
    assert _tie_any_ok(g, 1200, _Route, transfer=True) is True
    # 全员不合规保持不真（无假绿）
    g2 = _dedup_tie([_tie_row("qunar", "", None),
                     _tie_row("ctrip", "", None)])[0]
    assert _tie_any_ok(g2, 1200, _Route, transfer=True) is False


def test_tie_any_ok_fliggy_pad_member(monkeypatch):
    """首成员 fliggy 税垫后超线、qunar 成员合规：直飞 kind 组 OR 真。
    （FLIGGY_TAX_PAD 生产现值 0=潜伏态，monkeypatch 激活验证语义。）"""
    import core.alerter as _al
    monkeypatch.setattr(_al, "FLIGGY_TAX_PAD", 50)
    g = _dedup_tie([_tie_row("fliggy", price=1000),
                    _tie_row("qunar", price=1000)])[0]
    assert _tie_any_ok(g, 1049, _Route, transfer=False) is True
    assert _tie_any_ok(g, 999, _Route, transfer=False) is False


def test_tie_any_ok_no_snapshot_zero_drift():
    """无快照行按本体判定（无合并的普通行零漂移）。"""
    f = _tie_row("qunar", "direct", 120)
    assert _tie_any_ok(f, 1200, _Route, transfer=True) is True
    f2 = _tie_row("qunar", "", None)
    assert _tie_any_ok(f2, 1200, _Route, transfer=True) is False


# ---- P-2 trend PNG 租户段 -------------------------------

def _cfg2users():
    def _r(th_d):
        return {"from": "URC", "to": "SHA", "dates": ["2026-10-05"],
                "from_name": "乌鲁木齐", "to_name": "上海",
                "enabled": True, "alert_direct": th_d,
                "alert_transfer": th_d + 200}
    return {"notifier": {"image_host": {"provider": "ghimg"}},
            "users": [
                {"name": "甲", "notifier": {}, "routes": [_r(1000)]},
                {"name": "乙", "notifier": {}, "routes": [_r(2000)]}]}


def _patch_charts(monkeypatch, cap):
    def _rounds(db_path, fc, tc, date, am, layover_min=0, dep_win=None,
                rc=None, th_d=0.0, th_t=0.0):
        cap["th_d"] = th_d
        cap["th_t"] = th_t
        return {"09:00": (1000, 0, ""), "10:00": (1100, 0, "")}
    def _render(series, title, thresholds=(), out_path="", hours=48):
        cap["out_path"] = out_path
    monkeypatch.setattr(rep, "_rounds", _rounds)
    monkeypatch.setattr(rep, "render_chart", _render)
    monkeypatch.setattr(rep, "upload_chart",
                        lambda png, cfg, logger: "http://x/t.png")


def test_prepare_round_charts_user_scoped(tmp_path, monkeypatch):
    """user 参：只遍历该用户 routes——乙的阈值画乙的图（首遇配置
    胜出的内容级渗漏根治）。"""
    cap = {}
    _patch_charts(monkeypatch, cap)
    monkeypatch.setattr(rep, "_anchored_db", lambda cfg: ":memory:")
    rep.prepare_round_charts(_cfg2users(), _LOG, user="乙")
    assert cap["th_d"] == 2000.0
    rep.prepare_round_charts(_cfg2users(), _LOG, user="甲")
    assert cap["th_d"] == 1000.0


def test_prepare_round_charts_user_tag(tmp_path, monkeypatch):
    """命名带租户段：user 非空 trend_{tag}{OD}_{date}.png，空 user
    文件名不变（单用户零回归）。"""
    cap = {}
    _patch_charts(monkeypatch, cap)
    monkeypatch.setattr(rep, "_anchored_db", lambda cfg: ":memory:")
    rep.prepare_round_charts(_cfg2users(), _LOG, user="乙")
    assert cap["out_path"].endswith("trend_乙_URC_SHA_2026-10-05.png")
    rep.prepare_round_charts(_cfg2users(), _LOG, user="")
    assert cap["out_path"].endswith("trend_URC_SHA_2026-10-05.png")


def test_build_and_push_charts_user_scoped(tmp_path, monkeypatch):
    """build_and_push 的图表生成按用户取（不再是全量生成后过滤）。"""
    seen = {}
    def _prc(cfg, logger, route_override=None, user=""):
        seen["user"] = user
        return {}
    monkeypatch.setattr(rep, "prepare_round_charts", _prc)
    monkeypatch.setattr(rep, "_image_host_cfg",
                        lambda cfg: {"provider": "ghimg"})
    cfg = _cfg2users()
    cfg["alert"] = {}
    try:
        rep.build_and_push(cfg, _LOG, notifier=None, user="乙")
    except Exception:
        pass   # 后续链路缺依赖无妨——本钉只看图表生成的 user 透传
    assert seen["user"] == "乙"


def test_chart_cache_per_user_source_pin():
    """main.py 扫描循环 chart_cache 按用户分片（源码钉：多租户同 OD
    时各用户 alerters 收到自己的图 URL）。"""
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "main.py"), encoding="utf-8").read()
    assert "chart_cache[ui]" in src, "chart_cache 应按用户索引分片"
    assert "charts_fn(fc, tc, d, users[ui][\"name\"])" in src


# ---- P-3 截循环浮点累计 -------------------------------

def test_miss_chart_line_float_accumulation():
    """含数字航线名截断不提前：13 位数字名侧预算 8 半角（room=(40-5-
    16-2)//2），浮点累计 7 位=7.875≤8 全进；ceil 旧算法每数字按 2 计
    4 位即误停（截烂一半）。"""
    out = rep._miss_chart_line("1234567890123→上海", "2026-10-05")
    assert "1234567→" in out   # 浮点累计：7 位真实宽 7.875 全进
    assert "1234→" not in out  # ceil 放大形态（每数字按 2 计）不得出现


# ---- W-4 NOTIFY 页触控地板（源码钉：轻页静态 CSS 声明在案） --

def test_notify_touch_floor_source_pin():
    """NOTIFY_PAGE CTA/页脚链触控外扩声明：主站同位件（#foot a/
    .kpisum a）已有热区外扩，轻页同族清点补齐。"""
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "webui.py"), encoding="utf-8").read()
    seg = src[src.find("NOTIFY_PAGE"):]
    assert ".md a::after" in seg and ".foot a::after" in seg
    assert "inset:-10px -4px" in seg
