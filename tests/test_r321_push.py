# -*- coding: utf-8 -*-
"""r321 推送审校落地钉（M1 slim 窗口头路线价格判据恒灭）：

r320 P1-1 中间档修复半落地的残留面：slim 心跳窗口头路线
（dep_time_min/max 配置，头带「（19:00后出发）」15.5 半角）下
「剥中转保直飞价」档数学不可达（实宽 50/40）→ 旧链直落地板裸
身份行（34/40 零价格=价格判据全灭，实发 18:43-19:35 五连轮
`> 上海→海口（19:00后出发） 01/29` 恒裸）。修复=剥中转档与地板
档之间插「剥窗保价」档（`> 上海→海口 01/29 ｜ 直飞 ￥N` 34/40
可落位；r320 P1-1 四档链设计的第三档，实施漏落）。档序律：价格
判据最后丢（十九§9）；剥窗后与同 OD 无窗行靠日期可辨。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r321_push.py -q
"""
import logging
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.alerter import Alerter, _disp_dw  # noqa: E402
from core.models import Route as _R  # noqa: E402

_LOG = logging.getLogger("r321pf")


def _route_win():
    """窗口头路线夹具：上海→海口 19:00 后出发（实发 M1 同构）。"""
    return _R(from_code="HAK", to_code="SHA", from_name="上海",
              to_name="海口", dates=["2027-01-29"],
              alert_direct=1900, alert_transfer=1700,
              dep_time_min="19:00", dep_time_max="")


def _sec_dual():
    """双类在场：直飞+中转行情最优（均超线→未达标→slim 路径）。"""
    return [{"date": "2027-01-29",
             "best_direct": {"price": 1950, "name": "MU8369",
                             "depTime": "19:55", "arrTime": "01:25",
                             "_platform": "qunar", "_stale_h": 4.2},
             "best_transfer": None,
             "best_transfer_mkt": {"price": 1780, "name": "CZ6976转",
                                   "depTime": "12:05", "arrTime": "23:50",
                                   "transCity": "郑州",
                                   "_platform": "ctrip"},
             "seen_plats": ["qunar", "ctrip"]}]


def test_heartbeat_slim_win_head_price_survives():
    """M1：窗口头路线 slim 轮价格判据必须存活（剥窗档）。"""
    a = Alerter(_LOG, storage=None, digest=True)
    a.round_charts = {}
    p = a._digest_payload([(_route_win(), _sec_dual())],
                          fresh=False, with_tables=False)
    body = [ln for ln in p["desp"].splitlines()
            if ln.startswith(">") and "上海→海口" in ln]
    assert body, p["desp"][:400]
    ln = body[0]
    assert "￥" in ln, f"窗口头路线价格判据全灭（裸身份行）: {ln!r}"
    assert _disp_dw(ln) <= 40, f"摘要行超宽: {ln!r}"
    # 剥窗后日期仍在（同 OD 无窗行的辨识信息）
    assert "01/29" in ln, f"日期被剥（辨识信息丢失）: {ln!r}"
    # 触发前提自检：带窗+价形态在旧链中间档下确实超线
    # （50/40 数学不可达=本案成立条件，夹具漂移时此钉先红）
    assert _disp_dw(f"> 上海→海口（19:00后出发） 01/29 ｜ 直飞 ￥1950") > 40, \
        "夹具已不触发（窗口头变窄？样本需随形态演进重选）"


def test_heartbeat_slim_win_head_floor_semantics():
    """地板语义双面：真实城市名域（≤4 字/名）剥窗档恒可达（带价
    落位）；病理长名全链超线时 _fit_line 全超取末档=带窗裸身份
    （地板档形态不变；宽度在病理配置域可超——十九§15 地板档自身
    超预算=备案形态，恒达标律约束现实可达域）。"""
    a = Alerter(_LOG, storage=None, digest=True)
    a.round_charts = {}
    # 真实域：城市对（2+4 全角，剥窗带价实测 ≈37/40 落位带——
    # 4+4 组合实测 41/40 恰卡出带，样本按真实计宽网格选形）
    r = _R(from_code="LXA", to_code="DSN", from_name="拉萨",
           to_name="鄂尔多斯", dates=["2027-01-29"],
           alert_direct=1900, alert_transfer=1700,
           dep_time_min="19:00", dep_time_max="")
    p = a._digest_payload([(r, _sec_dual())],
                          fresh=False, with_tables=False)
    body = [ln for ln in p["desp"].splitlines()
            if ln.startswith(">") and "拉萨→鄂尔多斯" in ln]
    assert body, p["desp"][:400]
    ln = body[0]
    assert "￥" in ln and _disp_dw(ln) <= 40, \
        f"真实域剥窗档未落位（价格判据丢失）: {ln!r}"
    assert "（19:00后出发）" not in ln, \
        f"真实域应走剥窗档（窗口头先丢）: {ln!r}"
    # 病理域：配置自由文本超长名 → 全链超线 → 末档带窗裸身份
    r2 = _R(from_code="URC", to_code="SHA",
            from_name="乌鲁木齐地窝堡国际机场", to_name="鄂尔多斯伊金霍洛",
            dates=["2027-01-29"], alert_direct=1900, alert_transfer=1700,
            dep_time_min="19:00", dep_time_max="")
    p2 = a._digest_payload([(r2, _sec_dual())],
                           fresh=False, with_tables=False)
    body2 = [ln for ln in p2["desp"].splitlines()
             if ln.startswith(">") and "地窝堡" in ln]
    assert body2, p2["desp"][:400]
    ln2 = body2[0]
    # c330 审校 C1 再改写：链中截名保价档（_bare_price_line）在该域
    # 可达并先于 bare 被选中——截名机制（_clip_dw 浮点逐字截+剥未配
    # 对「（」）前移一步保价格判据（十九§9「价格判据最后丢」；r321/
    # r322 两轮修复间的名域残留空档）。裸身份地板档仍在链尾兜底
    # （head 全舍+预算 <2 的病理形态），选中档=截名+日期+直飞价
    assert ln2 == "> 乌鲁木齐地窝堡 01/29 ｜ 直飞 ￥1950", \
        f"病理域应走截名保价档（价格判据存活）: {ln2!r}"
    assert _disp_dw(ln2) <= 40, f"截名保价档守宽: {ln2!r}"
    assert _disp_dw(ln2) <= _disp_dw(
        "> 乌鲁木齐地窝堡国际机场→鄂尔多斯伊金霍洛（19:00后出发） 01/29"), \
        f"剥窗地板档不得长于带窗形态: {ln2!r}"


def test_source_pin_win_bare_tier():
    """源码钉：剥窗保价档在案（防四档链回退三档）。r322 起挂载面
    从双类域扩至 bd-only（`if bd and dw:` 门），钉锁 f-string 产出
    字面本体（append 调用换行形态不参与）。"""
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "core", "alerter.py"),
        encoding="utf-8").read()
    assert 'f"> {head[:-len(dw)]} {d_short} ｜ {bits[0]}"' in src, (
        "剥窗保价档缺失（M1 复活：窗口头路线价格判据恒灭）")


def test_source_pin_heartbeat_style_wiring():
    """源码钉（Soldier Major-1 收口）：heartbeat_style 配置→构造接线
    在案——消费层三态语义完备，缺的是 main 构造一根线（配置 full/
    auto 将静默无效果=文档承诺不存在的可配置性）；示例键层级与生产
    config 一致（notifier 顶层，与 dingtalk 平级）。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "main.py"), encoding="utf-8").read()
    assert 'heartbeat_style=str((ncfg or {}).get("heartbeat_style")' in src, (
        "heartbeat_style 配置线缺失（示例键=死键文档）")
    ex = open(os.path.join(root, "config.example.yaml"),
              encoding="utf-8").read()
    assert re.search(r"^    # heartbeat_style", ex, re.M), (
        "example 的 heartbeat_style 必须在 notifier 顶层（4 空格，"
        "与 dingtalk 平级；段内嵌套=层级错位接线也读不到）")
