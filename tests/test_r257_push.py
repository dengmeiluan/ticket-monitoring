# -*- coding: utf-8 -*-
"""r257 推送层三案（TDD 先行，审校报告 _scratch/r257_push_audit.md
P3×1-3，全部「日报↔告警能力不对称」族；零发送路径改动）：

- P-1 (r257-P3-1) 日报对「全窗零数据航线」静默蒸发：告警链有
  「本轮全渠道无数据」对账族，日报缺图对账只覆盖「有数据但图缺」
  （if has:）——零数据航线在每日唯一综合视图里无声消失。
- P-2 (r257-P3-2) 日报空池轮整篇零可点链接：告警链有
  _ensure_jump_link 单源兜底，日报 🔍 链接只在池非空分支——
  剥图后（图挂兜底/纯文本态）可点链接=0。
- P-3 (r257-P3-3) 空池补偿行 p7 参照恒被行宽守卫丢弃：长形 p7 拼
  进守卫链后各档数学上恒超宽（84/65/26），「补近 7 天参照」语义
  100% 空转。（r258-P2-1 演进：紧凑档随同行拼接链退役，参照改
  独立引用行长形——本文件对应钉已随行为改写。）

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r257_push.py -q
"""
import logging as _lg
import re
import sys
from datetime import datetime

import pytest

sys.path.insert(0, __import__("os").path.dirname(
    __import__("os").path.dirname(__import__("os").path.abspath(__file__))))

_DATE = "2026-09-25"
_ROUTES = [
    {"from": "SHA", "to": "URC", "from_name": "上海",
     "to_name": "乌鲁木齐", "dates": [_DATE],
     "alert_direct": 2000, "alert_transfer": 1800,
     "transfer_arrival_max": "02:00"},
]
_ZD_ROUTES = _ROUTES + [
    {"from": "SHA", "to": "SYN", "from_name": "上海",
     "to_name": "三亚", "dates": [_DATE],
     "alert_direct": 1600, "alert_transfer": 0,
     "transfer_arrival_max": "02:00"},
]


def _cfg(routes):
    return {"notifier": {"image_host": {"provider": "freeimage"}},
            "users": [{"name": "u", "routes": routes,
                       "platforms": ["qunar", "ctrip"],
                       "notifier": {"image_host": {"provider": "freeimage"}}}]}


class FakeN:
    def __init__(self):
        self.sent = {}

    def send(self, title, desp="", **kw):
        self.sent["title"], self.sent["desp"] = title, desp
        return True


def _strip_images(desp):
    return re.sub(r"!\[[^\]]*\]\([^)]*\)", "", desp)


@pytest.fixture()
def env(monkeypatch):
    """build_and_push 离线夹具：图床/渲染/明细查询全部桩化，
    _rounds 按 (from,to) 分派（三亚=零数据，上海→乌鲁木齐=旧代
    3 位低价样本供 p7 参照回算）。"""
    import report as rep
    seen = {"rounds": []}

    def _rounds(db, fc, tc, d, am, **kw):
        seen["rounds"].append((fc, tc, d))
        if (fc, tc) == ("SHA", "SYN"):
            return []
        return [(datetime(2026, 9, 20, 8, 0), 576.0, None)]

    monkeypatch.setattr(rep, "_rounds", _rounds)
    monkeypatch.setattr(rep, "prepare_round_charts",
                        lambda c, lg, *a, **k: {("SHA", "URC", _DATE):
                                                "http://x/t.png"})
    monkeypatch.setattr(rep, "render_flights_table", lambda *a, **k: None)
    monkeypatch.setattr(rep, "upload_freeimage",
                        lambda p, lg: "http://x/f.png")
    return {"rep": rep, "seen": seen}


def test_daily_no_data_route_reconciled(env, monkeypatch):
    """P-1：全窗零数据航线补对账行（能力对称）——航线名与
    「近48时无数据」词面在 desp 留痕，不再无声消失。"""
    rep = env["rep"]
    monkeypatch.setattr(
        rep, "_route_latest_flights",
        lambda db, fc, tc, d, **kw: (
            [{"price": 2690, "transCity": "", "_platform": "qunar"}]
            if (fc, tc) == ("SHA", "URC") else []))
    n = FakeN()
    ok = rep.build_and_push(_cfg(_ZD_ROUTES), _lg.getLogger("t"), n, user="u")
    assert ok and n.sent["desp"]
    d = n.sent["desp"]
    assert "近48时无数据" in d, d
    assert "上海→三亚" in d, "零数据航线名应在对账行留痕：" + d


def test_daily_empty_pool_jump_link_fallback(env, monkeypatch):
    """P-2：空池轮 desp 剥图后仍有一个可点查价入口（单源
    _ensure_jump_link 消费；告警链同款兜底）。"""
    rep = env["rep"]
    monkeypatch.setattr(rep, "_route_latest_flights",
                        lambda db, fc, tc, d, **kw: [])
    n = FakeN()
    ok = rep.build_and_push(_cfg(_ROUTES), _lg.getLogger("t"), n, user="u")
    assert ok and n.sent["desp"]
    stripped = _strip_images(n.sent["desp"])
    assert "](http" in stripped, "剥图后零可点链接：" + stripped
    assert "[→ 打开" in stripped, stripped


def test_empty_pool_p7_compact_tier_lands(env, monkeypatch):
    """（r258-P2-1 改写）空池补偿的近 7 天参照真实落行：独立引用行长形
    「> 近7天直飞最低 ￥N（MM/DD HH:MM）」全价位带恒落位——旧「同行
    拼接+紧凑档」形态产「无渠道明细7天最低￥N」连读病句、参照时刻被裁，
    已由独立引用行形态退役（钉面随行为演进改写，参照落行语义担保不变）。"""
    rep = env["rep"]
    monkeypatch.setattr(rep, "_route_latest_flights",
                        lambda db, fc, tc, d, **kw: [])
    n = FakeN()
    ok = rep.build_and_push(_cfg(_ROUTES), _lg.getLogger("t"), n, user="u")
    assert ok and n.sent["desp"]
    d = n.sent["desp"]
    line = [ln for ln in d.splitlines() if "无渠道明细" in ln]
    assert line, d
    assert "7天最低" not in line[0] and "近7天" not in line[0], line[0]
    ref = [ln for ln in d.splitlines() if "近7天直飞最低" in ln]
    assert ref and "￥576" in ref[0], d
    assert rep._dw_line(ref[0]) <= 40, ref[0]
    # 5 位价位带（主价位带上沿）：独立长形恒可落，不塌地板
    monkeypatch.setattr(
        rep, "_rounds",
        lambda db, fc, tc, dd, am, **kw: (
            [] if (fc, tc) == ("SHA", "SYN")
            else [(datetime(2026, 9, 20, 8, 0), 12650.0, None)]))
    n2 = FakeN()
    ok2 = rep.build_and_push(_cfg(_ROUTES), _lg.getLogger("t"), n2, user="u")
    assert ok2
    d2 = n2.sent["desp"]
    ref2 = [ln for ln in d2.splitlines() if "近7天直飞最低" in ln]
    assert ref2 and "￥12650" in ref2[0], "5 位价补偿参照塌地板：" + d2
    assert rep._dw_line(ref2[0]) <= 40, ref2[0]


def test_daily_jump_link_skips_empty_dates_route(env, monkeypatch):
    """兜底锚选取谓词必须滤空 dates 航线：首条启用航线 dates=[] 时
    选取即命中、dates 检查在其后——整篇日报零兜底链接（后随航线
    的 dates 在场也救不回）。谓词内联滤空 dates 后取首条可锚航线。"""
    rep = env["rep"]
    monkeypatch.setattr(rep, "_route_latest_flights",
                        lambda db, fc, tc, d, **kw: [])
    no_dates = {"from": "SHA", "to": "SYN", "from_name": "上海",
                "to_name": "三亚", "dates": [],
                "alert_direct": 1600, "alert_transfer": 0,
                "transfer_arrival_max": "02:00"}
    n = FakeN()
    ok = rep.build_and_push(_cfg([no_dates] + _ROUTES),
                            _lg.getLogger("t"), n, user="u")
    assert ok and n.sent["desp"]
    stripped = _strip_images(n.sent["desp"])
    assert "](http" in stripped, "首航线 dates=[] 曾让整篇零兜底链接：" + stripped


# ---- 备案② bare 档半截码（token 边界律投影） ----

def test_flight_line_bare_cut_at_code_token_boundary():
    """bare 地板档逐字截截进字母数字段=半截码（「川航3U8」形，真函数
    网格实证三形态；三十一§2 token 边界律投影）——截点落码段中时整
    token 回退（丢整段码优于半截噪音，价格+时刻+跨天地板恒落位）。"""
    from core.alerter import Alerter, _disp_dw
    f = {"price": 9876, "name": "川航3U8863", "code": "川航3U8863",
         "depTime": "17:55", "arrTime": "18:50", "crossDayDesc": "+1天",
         "_platform": "qunar", "transCity": "郑州", "layoverT": "2:05"}
    line = Alerter._fmt_flight_line(f, 1)
    assert "川航3U8" not in line, "半截码在场：" + line
    assert "川航" in line, "CJK 名前缀随整 token 回退丢失：" + line
    assert "￥9876" in line and "17:55→18:50" in line and "+1天" in line, line
    assert _disp_dw(line) <= 40, line
    # 全字母数字码（裸航班号行）：码要么完整在、要么整 absent——
    # 无半截第三形态（放得下时全码照常在，子串断言不成立）
    f2 = dict(f, name="3U8863", code="3U8863")
    line2 = Alerter._fmt_flight_line(f2, 1)
    assert "3U8863 17:55" in line2 or "￥9876 17:55" in line2, \
        "半截码形态：" + line2
    assert _disp_dw(line2) <= 40, line2


# ---- 备案③ 日报图挂兜底容量对齐（[:3]→[:5]，与告警 _top3_blocks 同量） ----

def test_daily_fallback_top5_capacity_aligned():
    """日报图挂文本兜底两池各取 5 行——v15133 立项语义=TOP5（与告警
    路径 _top3_blocks[:5] 能力对称），实现曾 [:3] 漂移。"""
    from report import _daily_top_fallback
    pool = [{"price": 1000 + k, "name": "南航CZ697%d" % k,
             "code": "CZ697%d" % k, "depTime": "10:00", "arrTime": "15:00",
             "_platform": "qunar", "transCity": ""} for k in range(6)]
    out = _daily_top_fallback(pool, [])
    assert out.count("CZ697") == 5, "兜底容量应=5（告警侧同量）：" + out
