# -*- coding: utf-8 -*-
"""渠道字段第十批回归：qunar H5 name 显示名源修复（直飞行
裸码降级补全 binfo.name[0] / binfo1.names[0]，守卫 code 子串）+
DOM 兜底 _via 内部键泄漏清理 + 波1/波2 调研后续批次字段。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v1558_fields.py
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.qunar import QunarCrawler  # noqa: E402
from crawlers.tongcheng import TongchengCrawler  # noqa: E402
from crawlers.fliggy import FliggyCrawler  # noqa: E402

_LOG = logging.getLogger("t1558")


# ---- qunar R1：name 显示名源修复 ----

def _h5_nodisp(**binfo):
    """直飞行、无 mixFlightName（dump 实态：mix 只在中转行在场 49/143，
    直飞行恒缺）——旧解析器此形态 name 恒落裸码。"""
    f = {"minPrice": 1200, "code": "9C8846",
         "binfo": {"depTime": "16:40", "arrTime": "21:30",
                   "depDate": "2026-10-06", "arrDate": "2026-10-06"},
         "extparams": "{}"}
    f["binfo"].update(binfo)
    return f


def test_qunar_h5_name_from_binfo_name0():
    """binfo.name[0] 是直飞行显示名真值（dump 94/94「春秋9C8866」形），
    旧解析从未读取 → DB 24h 55.7% 明细 name 无航司名。"""
    rows = QunarCrawler._extract_flights_obj(
        [_h5_nodisp(name=["春秋9C8846", "空客321(中)"])])
    assert rows[0]["name"] == "春秋9C8846"
    # 机型读取与显示名同源不互扰
    assert rows[0]["plane"] == "空客321(中)"
    assert rows[0]["planeSize"] == "中型机"


def test_qunar_h5_name_guard_rejects_mismatch():
    """守卫：name[0] 不含本行 code 即拒绝采用（防渠道名称与航班号
    错位，「春秋航空」vs「春秋9C8846」字面不含即不过），维持 code
    宁缺勿错；机型读取不受影响。"""
    rows = QunarCrawler._extract_flights_obj(
        [_h5_nodisp(name=["春秋航空", "空客321(中)"])])
    assert rows[0]["name"] == "9C8846"
    assert rows[0]["plane"] == "空客321(中)"


def test_qunar_h5_name_transfer_names0_fallback():
    """中转行 mixFlightName 缺失时 binfo1.names[0] 兜底（混淆码行
    「华夏航G581O1J」全文形态真名）。"""
    f = {"minPrice": 800, "code": "GS7587", "transCity": "石家庄",
         "crossDayDesc": "+1天",
         "binfo1": {"depTime": "14:30", "arrTime": "00:20",
                    "depDate": "2026-10-06", "arrDate": "2026-10-07",
                    "names": ["华夏航GS7587", "金鹏航空Y87520"],
                    "transInfo": {"transCity": "石家庄",
                                  "transTime": "5h45m",
                                  "firstArrInfo": {"airport": "正定",
                                                   "terminal": "T2"},
                                  "secondDepInfo": {"airport": "正定",
                                                    "terminal": "T5",
                                                    "time": "06:05"},
                                  "secondArrInfo": {"airport": "虹桥",
                                                    "terminal": "T1",
                                                    "time": "07:55"}}},
         "binfo2": {"depTime": "06:05", "arrTime": "07:55"},
         "extparams": "{}"}
    rows = QunarCrawler._extract_flights_obj([f])
    assert rows[0]["name"] == "华夏航GS7587"


def test_qunar_h5_name_mix_still_wins():
    """mixFlightName 在场（中转行常态）优先级不变，names[0] 不覆盖。"""
    f = {"minPrice": 800, "code": "GS7587",
         "mixFlightName": "天津航空GS7587/GS7588\n第二段",
         "transCity": "石家庄",
         "binfo1": {"depTime": "14:30", "arrTime": "00:20",
                    "depDate": "2026-10-06", "arrDate": "2026-10-07",
                    "names": ["华夏航GS7587"]},
         "extparams": "{}"}
    rows = QunarCrawler._extract_flights_obj([f])
    assert rows[0]["name"] == "天津航空GS7587/GS7588"


# ---- qunar R2：DOM 兜底 _via 内部键泄漏 ----

def test_qunar_dom_via_key_popped():
    """`_via`（转/停 哨兵）是 flightnorm.normalize 的 stopover 信号载体
    （DOM「停」=同机号经停），清洗点在消费端：normalize 后键消失、
    语义已落 stopover；第二遍 normalize 幂等（哨兵已清不得翻转）。
    DB 全库 23.2% 行曾残留脏键污染 extra schema（调研 R2）。"""
    from core.flightnorm import normalize as _norm
    text = "\n".join([
        "23:00",
        "",
        "虹桥T1",
        "",
        "10h55m",
        "",
        "转",
        "",
        "西安",
        "",
        "+1天",
        "",
        "09:55",
        "",
        "乌鲁木齐天山",
        "",
        "春秋9C8945 新海航｜长安航空9H8329",
        "",
        "1836",
        "",
        "08:00",
        "",
        "虹桥T2",
        "",
        "7h00m",
        "",
        "停",
        "",
        "南阳",
        "",
        "15:00",
        "",
        "乌鲁木齐天山",
        "",
        "南航CZ6976",
        "",
        "1520",
    ])
    rows = QunarCrawler._parse_dom_flights(text, "2026-10-06")
    assert rows, "DOM 兜底应产出行"
    t = next(f for f in rows if "/" in f["code"])
    st = next(f for f in rows if f["code"] == "CZ6976")
    for r in (t, st):
        n = _norm(dict(r), "2026-10-06")
        assert "_via" not in n
        assert "_codes" not in n
        assert "_cross" not in n
    assert t["transCity"] == "西安"
    # 经停行：_via=停 → normalize 产出 stopover=True 且键已清洗
    st_n = _norm(dict(st), "2026-10-06")
    assert st_n["stopover"] is True and "_via" not in st_n
    # 幂等：第二遍 normalize 不翻转（_via 已清、信号已在）
    st_n2 = _norm(dict(st_n), "2026-10-06")
    assert st_n2["stopover"] is True
    # 中转行不带 stopover（_via=转）
    t_n = _norm(dict(t), "2026-10-06")
    assert t_n["stopover"] is False


# ---- tongcheng R3：doc.book1「延误取消免费退改」并入 transferService ----

def _tc_transfer_fp(**extra):
    fp = {"dt": "2026-10-06 08:00", "at": "2026-10-07 18:00",
          "sd": "2h15m", "td": "9h30m", "sc": "西安",
          "ss": [{"fn": "CZ6981"}, {"fn": "MU5700"}],
          "lps": [{"atp": 1800, "brs": [{"al": 3}],
                   "pts": [{"td": "5.2折经济舱"}]}]}
    fp.update(extra)
    return fp


def test_tongcheng_book1_delay_refund_legend():
    """doc.book1「航班延误取消，免费退改」页面级图例并入 transferService
    串尾（五渠道唯一延误/取消免费退改结构化信号，connection 块 4/4
    恒在）；白名单双词精确匹配。"""
    doc = {"book1": "航班延误取消，免费退改", "check": "转机免安检"}
    rows = TongchengCrawler._extract_transfer_flights(
        json.dumps({"data": {"fps": [_tc_transfer_fp()], "doc": doc}}))
    assert len(rows) == 1
    svc = rows[0]["transferService"]
    assert "转机免安检" in svc
    assert svc.endswith("航班延误取消，免费退改")


def test_tongcheng_book1_whitelist_guards():
    """渠道改文案（缺「延误取消」或「免费退改」任一词）即静默不并，
    宁缺勿错；doc 无 book1 键不触。"""
    doc = {"book1": "航班延误免费改期", "check": "转机免安检"}
    rows = TongchengCrawler._extract_transfer_flights(
        json.dumps({"data": {"fps": [_tc_transfer_fp()], "doc": doc}}))
    assert "航班延误免费改期" not in rows[0]["transferService"]
    doc2 = {"check": "转机免安检"}
    rows2 = TongchengCrawler._extract_transfer_flights(
        json.dumps({"data": {"fps": [_tc_transfer_fp()], "doc": doc2}}))
    assert rows2[0]["transferService"] == "转机免安检"


# ---- fliggy R4：中转说明图例 → transferBaggage='recheck' ----

_FLG_TRANS_TXT = "\n".join([
    "春秋9C7006", "中型机 320",
    "春秋9C7310", "中型机 320",
    "10月05日 15:15", "10月05日 19:05",
    "10月06日 06:05", "10月06日 07:55",
    "乌鲁木齐天山国际机场", "石家庄中转", "虹桥国际机场T1",
    "¥2060 5.0折", "订票",
])

_RECHECK_NOTE = ("一.中转说明：<p>1.中转程航班每段均需缴纳机场建设费和"
                 "燃油税；2.转机过程需旅客自行处理，请预留足够时间处理"
                 "行李和重新办理登机手续；3.旅客应预留至少2小时的转机"
                 "时间。</p>")


def test_fliggy_recheck_legend_sets_transfer_baggage():
    """页面级 transfer_note 图例含「重新办理登机手续」→ 中转定证行落
    transferBaggage='recheck'（ctrip「行李代转运」同语义位）。"""
    rows = FliggyCrawler._parse_pc_text(
        _FLG_TRANS_TXT, "2026-10-05", None, None, _RECHECK_NOTE)
    assert len(rows) == 1
    assert rows[0]["transferBaggage"] == "recheck"


def test_fliggy_recheck_guards():
    """守卫：图例缺「重新办理登机手续」子串不落（渠道改文案静默）；
    无图例（直飞页/元素不存在空串）不落；直飞行永不落键。"""
    rows = FliggyCrawler._parse_pc_text(
        _FLG_TRANS_TXT, "2026-10-05", None, None,
        "一.中转说明：中转程航班每段均需缴纳机场建设费和燃油税")
    assert "transferBaggage" not in rows[0]
    rows2 = FliggyCrawler._parse_pc_text(
        _FLG_TRANS_TXT, "2026-10-05", None, None, "")
    assert "transferBaggage" not in rows2[0]
    txt_direct = ("东航MU8369\n中型机 737\n16:40\n21:30\n"
                  "乌鲁木齐天山国际机场\n虹桥国际机场T2\n¥920 5.0折")
    rows3 = FliggyCrawler._parse_pc_text(
        txt_direct, "2026-10-05", None, None, _RECHECK_NOTE)
    assert "transferBaggage" not in rows3[0]


# ---- report：freeimage 连败退避（观测 P2） ----

def test_freeimage_backoff_skips_after_streak(monkeypatch, tmp_path):
    """freeimage 连败 ≥3 跳过主床直走 pixhost（每 10 次上传重探一次，
    成功即清零回归永久图床）——主床 400 封禁期不再每轮打注定失败的
    请求；pixhost 有保存期故次序不可反转只可退避。"""
    import report as _rep
    st = _rep._FREEIMG_STATE
    old = dict(st)
    log = logging.getLogger("t158img")
    png = tmp_path / "x.png"
    png.write_bytes(b"\x89PNG\r\n")
    try:
        st.update(n=0, probe=0)
        calls = {"free": 0, "pix": 0}

        def _boom(*a, **k):
            calls["free"] += 1
            raise RuntimeError("400/111")

        def _pix(p, l):
            calls["pix"] += 1
            return "pix://x"

        monkeypatch.setattr(_rep.httpx, "post", _boom)
        monkeypatch.setattr(_rep, "_upload_pixhost", _pix)
        for _ in range(3):          # 连败 3：次次都试主床
            assert _rep.upload_freeimage(str(png), log) == "pix://x"
        assert calls == {"free": 3, "pix": 3}
        for _ in range(10):         # 第 4 次（probe=1）重探，5-13 跳过
            assert _rep.upload_freeimage(str(png), log) == "pix://x"
        assert calls == {"free": 4, "pix": 13}
        # 第 14 次 probe=11 又逢重探轮：恢复即清零回归主床常态
        # 恢复即清零：重探成功后回到主床常态
        def _ok(*a, **k):
            calls["free"] += 1
            return type("R", (), {"text": "", "json": lambda s: {
                "image": {"url": "iili://ok"}}})()
        monkeypatch.setattr(_rep.httpx, "post", _ok)
        assert _rep.upload_freeimage(str(png), log) == "iili://ok"
        assert st["n"] == 0
    finally:
        st.clear()
        st.update(old)


# ---- 推送审校 P2：hits 行前缀入量纲 / 全线价分支守卫 ----

def test_hits_lines_quote_prefix_in_budget():
    """hits 三行（head/seg/tail）`> ` 前缀（2 半格）入 _fit_line 量纲
    （审校：内容守 40、拼行加前缀实渲染 41-42——同消息与
    KPI 行3/图例/建议行两套预算）。源码钉四处调用点与拼行形态。"""
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "core", "alerter.py"),
        encoding="utf-8").read()
    assert src.count('"> " + _fit_line(') == 0
    # 真入量纲：前缀拼进候选串（head/seg 首参以 "> " 开头 ×2 版）
    assert src.count('f"> 🔥 **{kind}') == 4      # head 主档+fallback ×2 版
    assert src.count('"> " + base_seg') >= 6      # seg 主档+fallback ×2 版
    assert 'f"> {head}' not in src       # 旧拼行形态（前缀在量纲外）
    assert 'f"{head}' in src             # 新拼行（前缀已入量纲）


def test_channel_market_mins_line_guarded():
    """「全线价」分支（图挂兜底）套 _fit_line：现役短渠道名下主形态
    46 半角本就超宽（审校 demo 复现），降级短尾档后 ≤40 且保
    渠道+价格+全线价核心判据。"""
    from core.alerter import Alerter, _disp_dw
    al = Alerter(logging.getLogger("t158push"))
    desp = al._channel_market_lines(
        [{"platform_mins": {"ctrip": 1234.0}, "plat_top3": {}}])
    lines = [l for l in desp.splitlines() if l.strip()]
    assert lines, desp
    for l in lines:
        assert _disp_dw(l) <= 40, l
    assert "全线价" in lines[0] and "￥1234" in lines[0]
