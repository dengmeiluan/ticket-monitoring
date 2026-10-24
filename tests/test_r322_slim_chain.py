# -*- coding: utf-8 -*-
"""r322 slim 降级链两案：

案1（P1·真实账本 9 连轮实锤）：slim 链 `if bt and bd:` 门把剥窗保价
档锁在双类在场域——bd-only（中转池收窄/空）带窗航线整行零价格落
bare+win 地板（10-16 18:43-20:19 九连轮「上海→海口（19:00后出发）
01/29」无价格，同轮兄弟路线均保价）。价格判据最后丢（十九§9）：
剥窗保价档必须对 bd-only 同样可达，改挂 `if bd and dw:`。

案2（P3·域界）：链尾 bare+win 地板在 ≥11 CJK 城市对（阿拉善左旗/
塔什库尔干类，全史 1361 对）超 40（max 46），地板档恒达标律
（十九§1）在真实城市名全域有破口——链尾补无窗裸档兜底
（`> {A}→{B} 09/25` max 31 恒达标）。现行 OD 域不可达此档（非死档：
仅 bare+win 超宽域生效）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r322_slim_chain.py -q
"""
import logging as _lg
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.alerter import Alerter, _disp_dw  # noqa: E402


def _win_route(frm="上海", to="乌鲁木齐", fc="SHA", tc="URC"):
    """带出发窗航线（dep_win_txt 产出「（19:00后出发）」形态）。"""
    from core.models import Route as _R
    return _R(from_code=fc, to_code=tc, from_name=frm, to_name=to,
              dates=["2026-09-25"], alert_direct=1900, alert_transfer=1700,
              dep_time_min="19:00", dep_time_max="")


def _bd_only_sections(price=1950):
    """bd-only 节（中转池空：best_transfer/best_transfer_mkt 双 None）。"""
    return [{"date": "2026-09-25",
             "best_direct": {"price": price, "name": "MU8369",
                             "depTime": "19:55", "arrTime": "01:25",
                             "_platform": "qunar"},
             "best_transfer": None, "best_transfer_mkt": None,
             "seen_plats": ["qunar"]}]


def _slim_desp(route, sections):
    a = Alerter(_lg.getLogger("t"), storage=None, digest=True)
    return a._digest_payload([(route, sections)], fresh=False,
                             with_tables=False, with_charts=False)["desp"]


def test_slim_bd_only_windowed_row_keeps_price():
    """案1：bd-only 带窗航线的 slim 行必须保住价格判据。

    现行 `if bt and bd:` 门下剥窗保价档不挂链：head_full
    （> 上海→乌鲁木齐（19:00后出发） 09/25 ｜ 直飞 ￥1950）超 40、
    bare+win 地板零价格——真实账本 9 连轮零价格形态。修后剥窗档
    `> 上海→乌鲁木齐 09/25 ｜ 直飞 ￥1950`（34/40）落位。"""
    desp = _slim_desp(_win_route(), _bd_only_sections())
    rows = [ln for ln in desp.splitlines() if ln.startswith("> 上海→乌鲁木齐")]
    assert rows, desp[:600]
    row = rows[0]
    assert "直飞 ￥1950" in row, "bd-only 带窗行零价格（案1 病灶）：%r" % row
    assert _disp_dw(row) <= 40, "保价行超宽：%r (%.1f)" % (row, _disp_dw(row))
    # 窗词面按档序有意丢弃（r321 M1 备案：同 OD 无窗行靠日期可辨）
    assert "19:00后出发" not in row, row


def test_slim_floor_survives_longest_city_pair():
    """案2：≥11 CJK 城市对下链尾地板恒达标（无窗裸档兜底）。

    阿拉善左旗→塔什库尔干（12 CJK 字 OD）：bare+win 46/40 超、
    全链超宽时 _fit_line 取末档原样=超宽落位。修后链尾补无窗裸档
    `> 阿拉善左旗→塔什库尔干 09/25`（31/40）恒落位。"""
    desp = _slim_desp(
        _win_route("阿拉善左旗", "塔什库尔干", "ALQ", "HQL"),
        _bd_only_sections())
    rows = [ln for ln in desp.splitlines()
            if ln.startswith("> 阿拉善左旗")]
    assert rows, desp[:600]
    row = rows[0]
    assert _disp_dw(row) <= 40, "地板档超宽（案2 破口）：%r (%.1f)" % (
        row, _disp_dw(row))
    assert "阿拉善左旗" in row and "09/25" in row, row


def test_slim_dual_class_windowed_row_unchanged():
    """双类在场路径零回归：bd+bt 带窗 slim 行仍落剥窗保价档
    （r321 M1 既有行为），档序不变。"""
    secs = _bd_only_sections()
    secs[0]["best_transfer_mkt"] = {"price": 2050, "name": "CZ6976转",
                                    "transCity": "郑州",
                                    "_platform": "ctrip"}
    desp = _slim_desp(_win_route(), secs)
    rows = [ln for ln in desp.splitlines() if ln.startswith("> 上海→乌鲁木齐")]
    assert rows, desp[:600]
    row = rows[0]
    assert "直飞 ￥1950" in row, row
    assert _disp_dw(row) <= 40, row
