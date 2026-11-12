# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r283_fields.py
- tests/test_v1558_fields.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import json
import logging
import os
import sys

from crawlers.ctrip import CtripCrawler
from crawlers.fliggy import FliggyCrawler
from crawlers.qunar import QunarCrawler
from crawlers.tongcheng import TongchengCrawler
from font_probe import cjk_font_path, has_cjk_font


# ---- merged from tests/test_r283_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG = logging.getLogger("r283")
_CT = CtripCrawler({}, _LOG)


def _ctrip_item(segs, policies):
    return {"mutilstn": segs, "policyinfo": policies}


def _ctrip_seg(dd, ad, flgno="CZ6981"):
    return {"dateinfo": {"ddate": dd, "adate": ad},
            "basinfo": {"flgno": flgno},
            "dportinfo": {"bsname": "", "aport": "URC"},
            "aportinfo": {"bsname": "T2", "aport": "SHA"}}


def _ctrip_policy(price=1610, ci=None):
    p = {"tprice": price, "quantity": 9, "drate": 3.7}
    if ci is not None:
        p["classinfor"] = [ci]
    return p


def _extract(item):
    return _CT._extract_ctrip_flights(json.dumps([item]))[0]


# ---- 解析层：两字符收编 ----

def test_ctrip_cabin_code_b0_direct_two_char():
    """C-49 B0：nt=2 'B0'（AQ1733 直飞全价，pid grade 同价互证 2/2）
    → cabinCode='B0' 落值。"""
    dd, ad = "2027-02-13 21:10:00", "2027-02-14 02:35:00"
    ci = {"cgrd": 0, "classNoteList": [{"notetype": 2, "notecnt": "B0"}]}
    row = _extract(_ctrip_item([_ctrip_seg(dd, ad)], [_ctrip_policy(ci=ci)]))
    assert row.get("cabinCode") == "B0", row


def test_ctrip_cabin_code_r1_transfer_first_seg():
    """C-49 R1：中转行首段 nt=2 'R1'（9C8815/SC2251 3.7 折深折，与
    qunar 已转正的春秋子舱码同族同指纹）→ cabinCode='R1' 落值。"""
    dd1, ad1 = "2027-01-30 08:00:00", "2027-01-30 11:20:00"
    dd2, ad2 = "2027-01-30 13:30:00", "2027-01-30 16:40:00"
    ci = {"cgrd": 0, "classNoteList": [{"notetype": 2, "notecnt": "R1"}]}
    row = _extract(_ctrip_item(
        [_ctrip_seg(dd1, ad1, "9C8815"), _ctrip_seg(dd2, ad2, "SC2251")],
        [_ctrip_policy(ci=ci)]))
    assert row.get("cabinCode") == "R1", row


def test_ctrip_cabin_code_single_char_family_unchanged():
    """单字母家族（Y/B/M/H…既有真值）行为零变化。"""
    dd, ad = "2027-02-13 21:10:00", "2027-02-14 02:35:00"
    ci = {"cgrd": 0, "classNoteList": [{"notetype": 2, "notecnt": "Y"}]}
    row = _extract(_ctrip_item([_ctrip_seg(dd, ad)], [_ctrip_policy(ci=ci)]))
    assert row.get("cabinCode") == "Y", row


def test_ctrip_cabin_code_dirty_values_still_rejected():
    """宁缺勿错边界维持：数字开头 '1B'、三字符 'ABC'、小写 'r1'、
    纯数字 '12' 全部拒收不落键。"""
    dd, ad = "2027-02-13 21:10:00", "2027-02-14 02:35:00"
    for dirty in ("1B", "ABC", "r1", "12"):
        ci = {"cgrd": 0,
              "classNoteList": [{"notetype": 2, "notecnt": dirty}]}
        row = _extract(_ctrip_item([_ctrip_seg(dd, ad)],
                                   [_ctrip_policy(ci=ci)]))
        assert "cabinCode" not in row, (dirty, row)


# ---- 渲染层：括注门同步放宽（值域扩充消费点等值门同步律）----

def test_report_cabin_annotation_two_char(monkeypatch, tmp_path):
    """PNG 总表次行括注「经济舱(B0)」：cabinCode 两字符形态与单字母
    同律出括注（退改等级之根）；qunar R2/R3 既有两字符码同样受益。"""
    if not has_cjk_font():
        pytest_skip = __import__("pytest").skip
        pytest_skip("渲染烟测依赖中文字体度量（CI 无雅黑）")
    import report as _rep
    seen = []
    _orig = _rep._fit_text

    def _spy(d, txt, *a, **kw):
        seen.append(str(txt))
        return _orig(d, txt, *a, **kw)

    monkeypatch.setattr(_rep, "_fit_text", _spy)
    f = {"price": 2550, "code": "AQ1733", "name": "北部湾航空AQ1733",
         "depTime": "21:10", "arrTime": "02:35", "depDate": "2027-02-13",
         "arrDate": "2027-02-14", "transCity": "", "crossDayDesc": "",
         "totalDuration": "5时25分", "cabin": "经济舱", "cabinCode": "B0",
         "plane": "", "planeSize": "", "lcc": False,
         "prate": "", "meal": "", "baggage": "", "discount": "",
         "fewTicket": "", "shareCarrier": "",
         "depTerminal": "", "arrTerminal": "",
         "depAirport": "", "arrAirport": "",
         "_platform": "ctrip", "stopover": False}
    out = str(tmp_path / "t.png")
    _rep.render_flights_table([("direct", [f])], "测试标题", out_path=out)
    assert any("经济舱(B0)" in s for s in seen), \
        f"两字符括注未出，实绘: {[s for s in seen if '经济舱' in s]}"

def _has_cjk_font():
    """本机是否有可用的中文字体（不写死任何盘符/安装路径）。

    Windows 用 fonts 目录下的雅黑系文件探测，其它平台交给 fontconfig/
    Pillow 自己找；探测不到就跳过依赖字体度量的渲染烟测。
    """
    import os as _os
    import sys as _sys
    if _sys.platform.startswith("win"):
        root = _os.path.join(_os.environ.get("WINDIR", ""), "Fonts")
        if not _os.path.isdir(root):
            return False
        return any(_os.path.isfile(_os.path.join(root, n))
                   for n in ("msyh.ttc", "msyhbd.ttc", "simhei.ttf"))
    try:
        from PIL import ImageFont
        ImageFont.truetype("DejaVuSans.ttf", 12)
        return True
    except Exception:
        return False


# ---- merged from tests/test_v1558_fields.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
    """freeimage 连败 ≥3 跳过主床（每 10 次上传重探一次，成功即清零
    回归永久图床）——主床 400 封禁期不再每轮打注定失败的请求。
    r199 后跳档返回 None 交文本兜底（pixhost 死链已撤出降级链）。"""
    import report as _rep
    st = _rep._FREEIMG_STATE
    old = dict(st)
    log = logging.getLogger("t158img")
    png = tmp_path / "x.png"
    png.write_bytes(b"\x89PNG\r\n")
    try:
        st.update(n=0, probe=0)
        calls = {"free": 0}

        def _boom(*a, **k):
            calls["free"] += 1
            raise RuntimeError("400/111")

        monkeypatch.setattr(_rep.httpx, "post", _boom)
        for _ in range(3):          # 连败 3：次次都试主床
            assert _rep.upload_freeimage(str(png), log) is None
        assert calls == {"free": 3}
        for _ in range(10):         # 第 4 次（probe=1）重探，5-13 跳过
            assert _rep.upload_freeimage(str(png), log) is None
        assert calls == {"free": 4}
        # 第 14 次 probe=11 又逢重探轮：恢复即清零回归主床常态
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
    # r253 起 hits head 与 legacy 版各走单源（_head_base/_lg_base，
    # 双名剥档 fallbacks 同款）；「> 」前缀入量纲语义由单源字面保留
    assert src.count('f"> 🔥 **{kind}') == 2
    assert '_head_base = f"> 🔥 **{kind}' in src
    assert '_lg_base = f"> 🔥 **{kind}' in src
    assert src.count('"> " + base_seg') >= 6      # seg 主档+fallback ×2 版
    # 旧拼行形态（前缀在量纲外）禁复活；r318 心跳轻量行（未达标单行
    # 摘要）以同族字面拼行但整行走 _fit_line——前缀入量纲语义同 hits，
    # 拼行形态受控枚举：轻量行三档分支 6 处 + r320 审校 P1-1 价格
    # 中间档 1 处 + r324 推送审校 P2-1 _bare_identity_floor 裸身份
    # 地板档 1 处 + c330 审校 C1 _bare_price_line 截名保价档 1 处
    # （_bare_price_line 内 f"> {head} …" 产出本体）= 9，多出即有新裸拼
    assert src.count('f"> {head}') == 9
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
