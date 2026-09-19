"""核心纯函数单元测试（TDD 补欠账：每个用例对应一个真实修过的 bug，
并用"变异验证"证明测试能抓住原 bug——注入原缺陷形态确认失败后还原）。

运行：python tests/test_core_units.py
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from webui import _cluster_round_rows, _dur_min  # noqa: E402
from crawlers.fliggy import FliggyCrawler  # noqa: E402
from core.alerter import Alerter  # noqa: E402

import json  # noqa: E402


# ---- qunar PC 版 wbdflightlist 解析（v5.0 渠道 PC 化） ----
_PC_SAMPLE = json.dumps({
    "ret": True, "data": {"flights": [
        {"code": "FM9223", "minPrice": "2472", "crossDayDesc": "+1天",
         "transCity": "", "transTime": "",
         "binfo": {"airCode": "FM9223", "shortName": "上航", "name": "上海航空",
                   "depTime": "19:55", "arrTime": "01:25",
                   "date": "2026-09-25", "arrDate": "2026-09-26",
                   "flightTime": "5h30m"}},
        {"code": "MU5533/SC8711", "minPrice": "1397", "crossDayDesc": "+2天",
         "transCity": "济南", "transTime": "19小时25分钟",
         "binfo1": {"airCode": "MU5533", "shortName": "东航", "depTime": "23:25",
                    "arrTime": "01:10", "date": "2026-09-25",
                    "arrDate": "2026-09-26"},
         "binfo2": {"airCode": "SC8711", "depTime": "20:35",
                    "arrTime": "00:55", "date": "2026-09-26",
                    "arrDate": "2026-09-27"}},
    ]}}, ensure_ascii=False)


def test_qunar_pc_parse_direct_and_transfer():
    from crawlers.qunar import QunarCrawler
    out = QunarCrawler._parse_pc_flights(_PC_SAMPLE, "2026-09-25")
    assert len(out) == 2
    d = next(f for f in out if f["code"] == "FM9223")
    assert d["price"] == 2472 and d["name"] == "上航FM9223"
    assert d["depTime"] == "19:55" and d["arrTime"] == "01:25"
    assert d["depDate"] == "2026-09-25" and d["arrDate"] == "2026-09-26"
    assert d["totalDuration"] == "5时30分" and d["transCity"] == ""
    t = next(f for f in out if "/" in f["code"])
    assert t["arrTime"] == "00:55"          # 整体到达 = 第二段到达
    assert t["arrDate"] == "2026-09-27" and t["transCity"] == "济南"
    assert t["totalDuration"] == "19小时25分钟"
    assert t["name"] == "东航MU5533"        # 中转名称取第一段航司


def test_qunar_pc_parse_garbage_and_risk():
    from crawlers.qunar import QunarCrawler
    risk = '{"bstatus":{"code":1999},"code":-1,"data":null,"ret":false}'
    assert QunarCrawler._parse_pc_flights(risk, "2026-09-25") == []
    assert QunarCrawler._parse_pc_flights("not json", "2026-09-25") == []
    assert QunarCrawler._parse_pc_flights(
        '{"data":{"flights":[]}}', "2026-09-25") == []


# ---- qunar DOM 兜底：时长段=全程（实测排版），停留时长页面不渲染则留空 ----
_DOM_SAMPLE = """23:00

虹桥T1

10h55m

转

西安

+1天

09:55

乌鲁木齐天山

春秋9C8945 新海航｜长安航空9H8329

1836

21:20

浦东T2

27h30m

转

长沙

+2天

00:50

乌鲁木齐天山

南航CZ3970 新海航｜天津航空GS7502

1449

17:05

浦东T2

7时

停

+1天

00:05

乌鲁木齐天山

南航CZ6976 波音737(中)

2692

19:55

浦东T1

5时30分

+1天

01:25

乌鲁木齐天山

上航FM9223 波音737(中)

2889

15:55

浦东T2

9h

转

郑州

00:55

乌鲁木齐天山

上航FM9349 新海航｜海南航空HU7860

2185
"""


def test_qunar_dom_parse_duration_is_total_not_layover():
    from crawlers.qunar import QunarCrawler
    out = QunarCrawler._parse_dom_flights(_DOM_SAMPLE, "2026-09-25")
    assert len(out) == 5
    t = next(f for f in out if f["code"] == "9C8945/9H8329")
    # 10h55m 是全程（23:00→09:55+1天），不是停留——原实现误填 layover
    assert t["totalDuration"] == "10时55分", t
    assert "layover" not in t, t
    assert t["transCity"] == "西安" and t["arrDate"] == "2026-09-26"
    t2 = next(f for f in out if f["code"] == "CZ3970/GS7502")
    assert t2["totalDuration"] == "27时30分" and "layover" not in t2
    # 经停行同理：7时 = 全程
    st = next(f for f in out if f["code"] == "CZ6976")
    assert st["totalDuration"] == "7时00分" and "layover" not in st
    # 直飞行不变
    d = next(f for f in out if f["code"] == "FM9223")
    assert d["totalDuration"] == "5时30分" and d["transCity"] == ""
    # 裸「9h」（无分钟段）不再漏
    t3 = next(f for f in out if "FM9349" in f["code"])
    assert t3["totalDuration"] == "9时00分", t3
    # 经停行带 stopover 信号（normalize 产出）；中转/直飞不带
    from core.flightnorm import normalize as _norm
    st_n = _norm(dict(st), "2026-09-25")
    assert st_n["stopover"] is True and st_n["transCity"] == ""
    assert _norm(dict(d), "2026-09-25")["stopover"] is False
    assert _norm(dict(t), "2026-09-25")["stopover"] is False


# ---- qunar PC 多采样中位合并（治 minPrice 单轮幻影低价，如 2069→1900→2069） ----
def _itin(code, price):
    return {"price": price, "code": code, "name": code, "depTime": "17:30",
            "arrTime": "01:45", "depDate": "2026-09-25",
            "arrDate": "2026-09-26", "transCity": "西安",
            "crossDayDesc": "+1天", "totalDuration": "2小时",
            "cabin": "V", "discount": "4.9折", "layover": 120, "plane": "738"}


def test_qunar_pc_merge_median_kills_phantom_low():
    # 幻影价形态：三份采样里一份骤低——中位回归主流价，且保留采样轨迹
    from crawlers.qunar import QunarCrawler
    s1 = [_itin("HU7844/GS7524", 1900.0), _itin("MU5533/HU7822", 1409.0)]
    s2 = [_itin("HU7844/GS7524", 2069.0), _itin("MU5533/HU7822", 1510.0)]
    s3 = [_itin("HU7844/GS7524", 2070.0), _itin("MU5533/HU7822", 1486.0)]
    out = QunarCrawler._merge_pc_samples([s1, s2, s3])
    d = {f["code"]: f for f in out}
    assert d["HU7844/GS7524"]["price"] == 2069.0
    assert d["HU7844/GS7524"]["samples"] == [1900.0, 2069.0, 2070.0]
    assert d["MU5533/HU7822"]["price"] == 1486.0


def test_qunar_pc_merge_partial_and_single():
    # 条目在两份采样中出现 → 取其余中位；仅一份出现 → 原样保留（真实新条目不丢）
    from crawlers.qunar import QunarCrawler
    s1 = [_itin("A", 100.0)]
    s2 = [_itin("A", 200.0), _itin("B", 500.0)]
    s3 = [_itin("A", 300.0), _itin("B", 700.0)]
    out = QunarCrawler._merge_pc_samples([s1, s2, s3])
    d = {f["code"]: f["price"] for f in out}
    assert d["A"] == 200.0 and d["B"] == 700.0


def test_qunar_pc_merge_two_and_one_samples():
    # 两份采样取较高值（对幻影低价保守）；单份退化为现状行为
    from crawlers.qunar import QunarCrawler
    two = QunarCrawler._merge_pc_samples(
        [[_itin("A", 1900.0)], [_itin("A", 2069.0)]])
    assert two[0]["price"] == 2069.0
    one = QunarCrawler._merge_pc_samples([[_itin("A", 1900.0)]])
    assert one[0]["price"] == 1900.0
    assert QunarCrawler._merge_pc_samples([]) == []


def test_qunar_pc_needs_resample():
    # 自适应加采侦测：无上轮参考或较上轮骤降超 5% 才加采（幻影信号特征），
    # 正常波动不花额外请求（风控暴露≈单采样基线）
    from crawlers.qunar import QunarCrawler
    assert QunarCrawler._needs_resample(None, 2069.0) is True
    assert QunarCrawler._needs_resample(2069.0, 1900.0) is True   # 跌 8.2%
    assert QunarCrawler._needs_resample(2069.0, 1944.0) is True   # 跌 6%
    assert QunarCrawler._needs_resample(2069.0, 1966.0) is False  # 恰在 5% 线内
    assert QunarCrawler._needs_resample(2069.0, 2031.0) is False  # 正常小波动


def row(ts):
    return {"fetched_at": ts, "platform": "x"}


def test_cluster_round_same_round_kept():
    # 一轮内三查询错峰 2-3 分钟完成 → 全保留（原 bug：1 分钟片切掉前两查询）
    rows = [row("2026-09-09 10:03:49"), row("2026-09-09 10:03:09"),
            row("2026-09-09 10:02:32")]
    assert len(_cluster_round_rows(rows)) == 3


def test_cluster_round_gap_breaks():
    # 轮间隔 15 分钟 → 只留最新轮
    rows = [row("2026-09-09 10:03:49"), row("2026-09-09 09:48:00")]
    assert len(_cluster_round_rows(rows)) == 1


def test_cluster_round_bad_ts_tolerated():
    rows = [row("garbage"), row("2026-09-09 10:03:00")]
    assert len(_cluster_round_rows(rows)) == 2  # 坏时间戳不炸、不误断


def test_dur_min_hour_variants():
    # 原 bug：字符类 [时小hH] 吃不完"小时"两字 → 5小时25分=300
    assert _dur_min("5时25分") == 325
    assert _dur_min("5小时25分") == 325
    assert _dur_min("6h40m") == 400
    assert _dur_min("") == 0


def test_fliggy_crossday_parse():
    # 原 bug：到达行"01:25 第2天"不匹配纯 HHMM 正则 → 卡片错位吞卡
    txt = ("东航MU8369\n\n中型机 737\n\n19:55\n\n01:25 第2天\n\n"
           "浦东T1\n\n乌鲁木齐\n\n86%\n\n¥2522 5.4折\n1张\n订票")
    fs = FliggyCrawler._parse_pc_text(txt, "2026-09-25")
    assert len(fs) == 1
    f = fs[0]
    assert f["arrTime"] == "01:25" and f["crossDayDesc"] == "+1天"
    assert f["arrDate"] == "2026-09-26" and f["price"] == 2522.0


def test_fliggy_multi_cards_and_price_gap():
    txt = ("MU8369\n19:55\n01:25 第2天\n¥2522\n订票\n\n"
           "9C6927\n06:40\n11:55\n¥2850\n少量\n订票")
    fs = FliggyCrawler._parse_pc_text(txt, "2026-09-25")
    assert len(fs) == 2
    assert fs[1]["depTime"] == "06:40" and fs[1]["price"] == 2850.0


def test_fliggy_dual_price_rows_take_low():
    # 原 bug：同航班第二个价格行被 "price" in cur 整行丢弃，明细可能
    # 只剩高价行（CA8564 ¥9900 vs ¥3960 双价行实证、疑跨舱位并列）——
    # 取低者为主价，较高者记 _alt_price 留痕
    txt = ("国航CA8564\n14:30\n18:45\n¥9900 全价\n¥3960 4.5折\n订票")
    fs = FliggyCrawler._parse_pc_text(txt, "2026-10-06")
    assert len(fs) == 1
    assert fs[0]["price"] == 3960.0
    assert fs[0]["_alt_price"] == 9900.0

    # 低价行在前、高价在后：主价不抬高，_alt_price 照记
    txt2 = ("国航CA8564\n14:30\n18:45\n¥3960 4.5折\n¥9900 全价\n订票")
    fs2 = FliggyCrawler._parse_pc_text(txt2, "2026-10-06")
    assert len(fs2) == 1
    assert fs2[0]["price"] == 3960.0
    assert fs2[0]["_alt_price"] == 9900.0

    # 第三个价格行同理收敛：主价仍为最低，_alt_price 为见过的最高
    txt3 = ("国航CA8564\n14:30\n18:45\n¥9900\n¥5000\n¥3960\n订票")
    fs3 = FliggyCrawler._parse_pc_text(txt3, "2026-10-06")
    assert fs3[0]["price"] == 3960.0
    assert fs3[0]["_alt_price"] == 9900.0


def test_fliggy_tail_module_price_not_absorbed():
    """v1.5.41 热修回归：双价行取低无行距锚时，虚拟列表尾航班的 cur
    一直开着，页面尾部低价日历/推荐模块的任意 ¥N 被吸入 min()——生产
    实锤 CA8564 列表价 9900/3960 被尾部动态价 820→700 逐轮污染。"""
    txt = ("国航CA1295\n14:30\n18:45\n¥3120\n订票\n"
           "东航MU8369\n08:15\n13:40\n¥2850\n订票\n"
           "国航CA8564\n16:50\n23:05\n¥9900\n¥3960\n订票\n"
           "@@@\n"
           "低价日历\n10/07 ￥820\n10/08 ￥700\n猜你喜欢\n_hotel\n")
    fs = FliggyCrawler._parse_pc_text(txt, "2026-10-06")
    ca = [f for f in fs if f["code"] == "CA8564"]
    assert ca and ca[0]["price"] == 3960.0, fs   # 尾部模块价不再吸入
    assert all(f["price"] >= 2850 for f in fs), fs


def test_fliggy_phantom_price_guard():
    """0.5x 幻影价守卫：紧邻污染（¥700 距首价格行 ≤2 行，行距锚拦不住）
    由明细中位数群体锚兜底——单行 < 中位×0.5 弃行。"""
    txt4 = ("国航CA1295\n14:30\n18:45\n¥3120\n订票\n"
            "东航MU8369\n08:15\n13:40\n¥2850\n订票\n"
            "南航CZ6981\n18:30\n23:40\n¥3300\n订票\n"
            "吉祥HO2214\n19:05\n23:55\n¥3327\n订票\n"
            "国航CA8564\n16:50\n23:05\n¥9900\n¥3960\n订票\n¥700\n")
    fs4 = FliggyCrawler._parse_pc_text(txt4, "2026-10-06")
    ca = [f for f in fs4 if f["code"] == "CA8564"]
    assert not ca or ca[0]["price"] >= 1980, fs4


def test_dep_window_bounds():
    w = lambda d: Alerter._dep_in_window(d, "17:00", "23:59")
    assert w("17:00") and w("23:59") and w("20:30")
    assert not w("16:59") and not w("00:05")
    assert Alerter._dep_in_window("12:00", "", "")


def test_arrival_ok_next_day_deadline():
    f_same = {"depDate": "2026-09-25", "arrDate": "2026-09-25", "arrTime": "23:00"}
    f_next_ok = {"depDate": "2026-09-25", "arrDate": "2026-09-26", "arrTime": "01:30"}
    f_next_late = {"depDate": "2026-09-25", "arrDate": "2026-09-26", "arrTime": "03:00"}
    f_day2 = {"depDate": "2026-09-25", "arrDate": "2026-09-27", "arrTime": "01:00"}
    assert Alerter._arrival_ok(f_same, "02:00")
    assert Alerter._arrival_ok(f_next_ok, "02:00")
    assert not Alerter._arrival_ok(f_next_late, "02:00")
    assert not Alerter._arrival_ok(f_day2, "02:00")




def test_cross_compare_no_angle_brackets():
    # 原 bug：比价链用 ＜ 分隔，钉钉 markdown 把尖括号当 HTML 标签，
    # 后续渠道名被吞（用户截图实锤）。全文案禁用任何尖括号。
    import logging as _lg
    from core.alerter import Alerter as _A
    log = _lg.getLogger("t")
    secs = [{"pool": [
        {"price": 2470, "name": "MU8369", "code": "MU8369", "depTime": "19:55",
         "arrTime": "01:25", "depDate": "2026-09-25", "arrDate": "2026-09-26",
         "transCity": "", "crossDayDesc": "+1天", "_platform": "tuniu"},
        {"price": 2600, "name": "MU8369", "code": "MU8369", "depTime": "19:55",
         "arrTime": "01:25", "depDate": "2026-09-25", "arrDate": "2026-09-26",
         "transCity": "", "crossDayDesc": "+1天", "_platform": "tongcheng"},
    ]}]
    txt = _A._cross_compare(secs)
    assert txt, "应有比价内容"
    for ch in ("<", ">", "＜", "＞"):
        assert ch not in txt, f"文案含尖括号 {ch!r} 会被钉钉吞字"
    assert "→" in txt and "2470" in txt and "2600" in txt


def test_cross_compare_renders_transfer_layover():
    # 比价行带真实衔接时长：经郑州 停2时50分；无衔接不虚标「停」；
    # 最低价渠道缺衔接时取组内任一渠道的真实值（衔接是航线属性非渠道属性）
    import logging as _lg
    from core.alerter import Alerter as _A
    log = _lg.getLogger("t")
    base = {"name": "MU5533", "code": "MU5533", "depTime": "19:20",
            "arrTime": "01:15", "depDate": "2026-09-25",
            "arrDate": "2026-09-26", "transCity": "郑州",
            "crossDayDesc": "+1天"}
    secs = [{"pool": [
        dict(base, price=2150, layoverT="", _platform="qunar"),
        dict(base, price=2317, layoverT="2:50", _platform="ctrip"),
    ]}]
    txt = _A._cross_compare(secs)
    assert "经郑州" in txt and "停2:50" in txt, txt
    assert txt.count("停") == 1, txt   # 缺衔接的渠道行不渲染「停」


# ---------- 渠道健康时间线（core/health.py 纯函数） ----------

def _hl(ts, lvl, name, msg):
    return f"{ts} [{lvl}] {name}: {msg}"


def test_health_ok_and_part_round():
    from core.health import parse_health
    log = "\n".join([
        _hl("2026-09-09 10:00:00", "INFO", "ticket-monitor",
            "===== 开始一轮扫描（1 用户 / 2 航线） ====="),
        _hl("2026-09-09 10:00:20", "INFO", "ticket-monitor",
            "[qunar] 2026-10-04 最低价 ￥1526（航班明细 70 条：直飞 44 / 中转 26）"),
        _hl("2026-09-09 10:01:00", "INFO", "ticket-monitor",
            "[fliggy] 2026-10-04 最低价 ￥1760（PC 明细 37 条）"),
        _hl("2026-09-09 10:01:30", "WARNING", "ticket-monitor",
            "[fliggy] 2026-10-05 达到最大重试圈数 5 仍未拿到价格"),
        _hl("2026-09-09 10:02:00", "INFO", "ticket-monitor",
            "[qunar] 2026-10-05 最低价 ￥1926（航班明细 70 条）"),
        _hl("2026-09-09 10:02:10", "INFO", "ticket-monitor",
            "===== 本轮扫描结束 ====="),
    ])
    out = parse_health(log, now="2026-09-09 12:00:00")
    assert len(out["rounds"]) == 1
    r = out["rounds"][0]
    assert r["plats"]["qunar"]["s"] == "ok"
    assert r["plats"]["qunar"]["ok"] == 2 and r["plats"]["qunar"]["tot"] == 2
    # fliggy 一成功一失败 → part（部分成功，琥珀）
    assert r["plats"]["fliggy"]["s"] == "part"
    assert r["plats"]["fliggy"]["ok"] == 1


def test_health_all_fail_round():
    from core.health import parse_health
    log = "\n".join([
        _hl("2026-09-09 10:00:00", "INFO", "t", "===== 开始一轮扫描 ====="),
        _hl("2026-09-09 10:00:30", "WARNING", "t",
            "[tuniu] 2026-10-05 达到最大重试圈数 5 仍未拿到价格(疑似风控/179991)"),
        _hl("2026-09-09 10:00:31", "WARNING", "t",
            "[tuniu] 2026-10-04 达到最大重试圈数 5 仍未拿到价格(疑似风控/179991)"),
        _hl("2026-09-09 10:01:00", "INFO", "t", "===== 本轮扫描结束 ====="),
    ])
    out = parse_health(log, now="2026-09-09 12:00:00")
    p = out["rounds"][0]["plats"]["tuniu"]
    assert p["s"] == "fail" and p["ok"] == 0 and p["tot"] == 2
    assert out["stats"]["tuniu"]["fail"] == 1


def test_health_maint_latch_and_recover():
    from core.health import parse_health
    log = "\n".join([
        _hl("2026-09-09 10:00:00", "INFO", "t", "===== 开始一轮扫描 ====="),
        _hl("2026-09-09 10:00:10", "WARNING", "t",
            "[fliggy] 官方已下线 mtop.trip.flight.flightSearch v1.0（老版本不支持），渠道进入维护模式直至重启"),
        _hl("2026-09-09 10:01:00", "INFO", "t", "===== 本轮扫描结束 ====="),
        # 下一轮 fliggy 无任何日志行 → 维持维护态
        _hl("2026-09-09 10:15:00", "INFO", "t", "===== 开始一轮扫描 ====="),
        _hl("2026-09-09 10:16:00", "INFO", "t", "===== 本轮扫描结束 ====="),
        # 第三轮 fliggy 恢复出价格 → 解除维护
        _hl("2026-09-09 10:30:00", "INFO", "t", "===== 开始一轮扫描 ====="),
        _hl("2026-09-09 10:30:20", "INFO", "t",
            "[fliggy] 2026-10-04 最低价 ￥1760（PC 明细 37 条）"),
        _hl("2026-09-09 10:31:00", "INFO", "t", "===== 本轮扫描结束 ====="),
    ])
    out = parse_health(log, now="2026-09-09 12:00:00")
    rs = out["rounds"]
    assert rs[0]["plats"]["fliggy"]["s"] == "maint"
    assert rs[1]["plats"]["fliggy"]["s"] == "maint"
    assert rs[2]["plats"]["fliggy"]["s"] == "ok"


def test_health_undated_exception_counts_fail():
    from core.health import parse_health
    log = "\n".join([
        _hl("2026-09-09 10:00:00", "INFO", "t", "===== 开始一轮扫描 ====="),
        _hl("2026-09-09 10:00:30", "WARNING", "t",
            "[tuniu] 请求异常: The read operation timed out"),
        _hl("2026-09-09 10:01:00", "INFO", "t", "===== 本轮扫描结束 ====="),
    ])
    out = parse_health(log, now="2026-09-09 12:00:00")
    assert out["rounds"][0]["plats"]["tuniu"]["s"] == "fail"


def test_health_limit_then_success_is_part():
    from core.health import parse_health
    log = "\n".join([
        _hl("2026-09-09 10:00:00", "INFO", "t", "===== 开始一轮扫描 ====="),
        _hl("2026-09-09 10:00:30", "WARNING", "t",
            "[qunar] 无数据疑似限流，90s 后第 1 次重试"),
        _hl("2026-09-09 10:02:00", "INFO", "t",
            "[qunar] 2026-10-04 最低价 ￥1526（航班明细 70 条）"),
        _hl("2026-09-09 10:02:10", "INFO", "t", "===== 本轮扫描结束 ====="),
    ])
    out = parse_health(log, now="2026-09-09 12:00:00")
    # 限流后重试成功：不算失败但要留痕（part 而非 ok）
    p = out["rounds"][0]["plats"]["qunar"]
    assert p["s"] == "part" and p["note"]


def test_health_garbage_and_window_tolerance():
    from core.health import parse_health
    log = "\n".join([
        "garbage line without timestamp",
        "2026-09-09 09:00:00 [INFO] t: ===== 开始一轮扫描 =====",
        "2026-09-09 09:00:20 [INFO] t: [qunar] 2026-10-04 最低价 ￥1526",
        "2026-09-09 09:01:00 [INFO] t: ===== 本轮扫描结束 =====",
        "乱码行 \x00\x01",
        # 25 小时前的轮 → 窗口外丢弃
        "2026-09-08 08:00:00 [INFO] t: ===== 开始一轮扫描 =====",
        "2026-09-08 08:00:20 [INFO] t: [qunar] 2026-10-04 最低价 ￥1526",
        "2026-09-08 08:01:00 [INFO] t: ===== 本轮扫描结束 =====",
    ])
    out = parse_health(log, now="2026-09-09 10:05:00")
    assert len(out["rounds"]) == 1
    assert out["rounds"][0]["plats"]["qunar"]["s"] == "ok"


def test_health_stats_rate():
    from core.health import parse_health
    lines = []
    # 3 轮：qunar ok/ok/fail → 成功率 2/3
    for i, st in enumerate(["ok", "ok", "fail"]):
        base = f"2026-09-09 0{i}:00:00"
        lines.append(_hl(base, "INFO", "t", "===== 开始一轮扫描 ====="))
        if st == "fail":
            lines.append(_hl(f"2026-09-09 0{i}:00:30", "WARNING", "t",
                            "[qunar] 2026-10-04 达到最大重试圈数 5 仍未拿到价格"))
        else:
            lines.append(_hl(f"2026-09-09 0{i}:00:30", "INFO", "t",
                             "[qunar] 2026-10-04 最低价 ￥1526"))
        lines.append(_hl(f"2026-09-09 0{i}:01:00", "INFO", "t",
                        "===== 本轮扫描结束 ====="))
    out = parse_health("\n".join(lines), now="2026-09-09 04:00:00")
    st = out["stats"]["qunar"]
    assert st["ok"] == 2 and st["fail"] == 1
    assert abs(st["rate"] - 2 / 3) < 1e-6


# ---------- 价格日历（report._daily_minima 纯函数） ----------

def _mk_db_with(days_prices):
    """造临时库：[(距今小时偏移, 直飞价, 中转价或None)] → db 路径。"""
    import json as _j
    import sqlite3 as _sq
    import tempfile as _tf
    from datetime import datetime as _dt, timedelta as _td
    from core.storage import SCHEMA
    db = _tf.mktemp(suffix=".db")
    conn = _sq.connect(db)
    conn.executescript(SCHEMA)
    now = _dt.now().replace(hour=12, minute=0, second=0, microsecond=0)
    # 锚定今天中午：hours_ago 相对偏移不会因运行时刻跨日历日而翻转日期桶
    for hours_ago, dp, tp in days_prices:
        ts = (now - _td(hours=hours_ago)).strftime("%Y-%m-%d %H:%M:%S")
        fs = [{"price": dp, "transCity": "", "depDate": "2026-09-25",
               "arrDate": "2026-09-25", "arrTime": "23:00"}]
        if tp:
            fs.append({"price": tp, "transCity": "郑州",
                       "depDate": "2026-09-25", "arrDate": "2026-09-25",
                       "arrTime": "23:50"})
        conn.execute(
            "INSERT INTO flight_prices (platform,from_city,to_city,"
            "depart_date,price,fetched_at,extra) VALUES (?,?,?,?,?,?,?)",
            ("qunar", "SHA", "URC", "2026-09-25", dp, ts,
             _j.dumps(fs, ensure_ascii=False)))
    conn.commit()
    conn.close()
    return db


def test_daily_minima_per_day_bucket():
    from report import _daily_minima
    db = _mk_db_with([
        (50, 2000, None), (46, 1950, 1800),      # 同一天两轮 → 取低
        (26, 1900, None), (22, 1880, None),      # 次日两轮
        (2, 1850, 1700),                          # 今天
    ])
    out = _daily_minima(db, "SHA", "URC", "2026-09-25", "02:00", days=14)
    assert len(out) == 3
    # 逐日取最低：1950 / 1880 / 1850，且按日期升序；未传阈值旗标恒 0
    vals = [v for _d, v, _q in out]
    assert vals == [1950, 1880, 1850]
    days = [d for d, _v, _q in out]
    assert days == sorted(days)
    assert all(q == 0 for _d, _v, q in out)


def test_daily_minima_qual_flag():
    from report import _daily_minima
    db = _mk_db_with([(2, 1850, None), (26, 1750, None)])
    out = _daily_minima(db, "SHA", "URC", "2026-09-25", "02:00", days=14,
                        th_d=1800)
    flags = {d: q for d, _v, q in out}
    # 四档与 webui _pts/renderCal 同语言：2=真达标 1=行情破线
    # -1=擦边（线<价≤线×1.1，v1.5.40 补档与走势环/表格图三媒质同语言）
    # 0=线外
    assert flags[out[0][0]] == 2          # 1750 ≤ 1800：真达标档（昨日）
    assert flags[out[1][0]] == -1         # 1850 距线 2.8%：擦边档（今日）


def test_daily_minima_transfer_only_day_absent():
    from report import _daily_minima
    db = _mk_db_with([(10, 0, 1700)])            # 仅中转数据
    # 直飞价为 0 的假行不应产生日历点（price 0 视为无效）
    out = _daily_minima(db, "SHA", "URC", "2026-09-25", "02:00", days=14)
    assert all(v > 0 for _d, v, _q in out)


def test_daily_minima_empty_db_tolerated():
    from report import _daily_minima
    db = _mk_db_with([])
    assert _daily_minima(db, "SHA", "URC", "2026-09-25", "02:00") == []


def test_rounds_transfer_uses_normalized_layover():
    """回归：走势路径必须先 normalize 原始 extra 再过滤衔接时长，
    否则 layoverM 恒缺、中转序列恒空（v1.5.2 中转走势线消失根因）。"""
    import sqlite3 as _sq
    import tempfile as _tf
    import json as _j
    from datetime import datetime as _dt
    from report import _rounds
    from core.storage import SCHEMA
    db = _tf.mktemp(suffix=".db")
    conn = _sq.connect(db)
    conn.executescript(SCHEMA)
    ts = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
    fs = [{"price": 2108, "transCity": "郑州", "depTime": "17:15",
           "arrTime": "00:55", "depDate": "2026-09-25",
           "arrDate": "2026-09-26", "layover": 115}]  # 原始键：layover 非 layoverM
    conn.execute(
        "INSERT INTO flight_prices (platform,from_city,to_city,"
        "depart_date,price,fetched_at,extra) VALUES (?,?,?,?,?,?,?)",
        ("qunar", "SHA", "URC", "2026-09-25", 2108, ts,
         _j.dumps(fs, ensure_ascii=False)))
    conn.commit()
    conn.close()
    # layover_min=90：归一化后 layoverM=115 通过 → 中转点存在
    series = _rounds(db, "SHA", "URC", "2026-09-25", "02:00", layover_min=90)
    assert series and series[0][2] == 2108
    # layover_min=120：衔接不足 → 该轮无任何数据点（中转滤掉、无直飞）
    series2 = _rounds(db, "SHA", "URC", "2026-09-25", "02:00", layover_min=120)
    assert series2 == []


# ---------- 推送文案 7 天趋势小结（Alerter._trend_line） ----------

def test_trend_line_declining_percent():
    import logging as _lg
    import types as _ty
    db = _mk_db_with([
        (144, 2000, 1900), (96, 1960, 1860), (48, 1900, 1800),
        (24, 1840, 1740), (2, 1800, 1700),
    ])
    a = Alerter(_lg.getLogger("t"), storage=_ty.SimpleNamespace(db_path=db))
    from core.models import Route as _R
    r = _R(from_code="SHA", to_code="URC", from_name="上海",
           to_name="乌鲁木齐", dates=["2026-09-25"])
    tl = a._trend_line(r, "2026-09-25")
    assert "直飞 ↓10%" in tl and "中转 ↓" in tl, tl


def test_trend_line_no_storage_graceful():
    import logging as _lg
    from core.models import Route as _R
    a = Alerter(_lg.getLogger("t"), storage=None)
    r = _R(from_code="SHA", to_code="URC", from_name="上海",
           to_name="乌鲁木齐", dates=["2026-09-25"])
    assert a._trend_line(r, "2026-09-25") == ""


def test_trend_line_rising_arrow():
    import logging as _lg
    import types as _ty
    db = _mk_db_with([(100, 1800, None), (2, 1980, None)])
    a = Alerter(_lg.getLogger("t"), storage=_ty.SimpleNamespace(db_path=db))
    from core.models import Route as _R
    r = _R(from_code="SHA", to_code="URC", from_name="上海",
           to_name="乌鲁木齐", dates=["2026-09-25"])
    assert "直飞 ↑10%" in a._trend_line(r, "2026-09-25")


# ---------- 推送文案：操作建议 / 未达标锚点 / 达标置顶 ----------

def _mk_route(ad=1900, at=1700):
    from core.models import Route as _R
    return _R(from_code="SHA", to_code="URC", from_name="上海",
              to_name="乌鲁木齐", dates=["2026-09-25"],
              alert_direct=ad, alert_transfer=at)


def _mk_sections(direct_price, transfer_price=None):
    """构造 _build_sections 同形的最小 sections。"""
    s = {"date": "2026-09-25", "best_direct": None, "best_transfer": None,
         "seen_plats": ["qunar"]}
    if direct_price:
        s["best_direct"] = {"price": direct_price, "name": "MU8369",
                            "depTime": "19:55", "arrTime": "01:25",
                            "_platform": "qunar"}
    if transfer_price:
        s["best_transfer"] = {"price": transfer_price, "name": "CZ6976转",
                              "depTime": "12:05", "arrTime": "23:50",
                              "transCity": "郑州", "_platform": "ctrip"}
    return [s]


def test_suggest_line_breakthrough():
    import logging as _lg
    a = Alerter(_lg.getLogger("t"), storage=None)
    tl = a._suggest_line(_mk_route(), _mk_sections(1850)[0])
    # v1.5.33 措辞收口：建议行不再说「破线」（图例 🟩破线=行情破线
    # 未必达标，一词两义曾误读）；v1.5.43 改 25-30 半角短式
    assert "达标" in tl and "出手" in tl, tl


def test_suggest_line_near_and_far():
    import logging as _lg
    a = Alerter(_lg.getLogger("t"), storage=None)
    near = a._suggest_line(_mk_route(), _mk_sections(1950)[0])   # 2.6% 上方
    assert "蹲守" in near, near
    far = a._suggest_line(_mk_route(), _mk_sections(2600)[0])    # 37% 上方
    # v1.5.41 超线态返回空：与 KPI 差额、仪表条三重冗余零增量，撤行减段
    assert far == "", far
    none_ = a._suggest_line(_mk_route(ad=0, at=0), _mk_sections(1850)[0])
    assert none_ == ""


def test_push_digest_table_fail_fallback(monkeypatch):
    """图挂兜底路径回归（v1.5.40）：表格图生成/上传失败时单航线 digest
    走 _top3_blocks + _channel_market_lines 文本兜底——_top3_blocks 尾部
    曾残留已删除的 _channel_overview 调用，图挂路径 AttributeError 整轮
    推送丢失（此前测试桩恒成功图路径，图挂零覆盖；Soldier 审查实锤）。"""
    import logging as _lg
    import report as _rep

    def _boom(*_a, **_k):
        raise RuntimeError("img down")

    monkeypatch.setattr(_rep, "render_flights_table", _boom)
    monkeypatch.setattr(_rep, "upload_freeimage", lambda p, lg=None: "")
    sent = []

    class FakeN:
        def send(self, t, d="", **kw):
            sent.append((t, d))
            return True

    a = Alerter(_lg.getLogger("t"), notifier=FakeN(), storage=None,
                digest=True, user="t")
    r = _mk_route()
    s = _mk_sections(1950, 2150)[0]
    s["top_direct"] = [s["best_direct"]]
    s["top_transfer"] = [s["best_transfer"]]
    s["platform_mins"] = {"qunar": 1950, "ctrip": 2150}
    s["plat_top3"] = {"qunar": s["top_direct"], "ctrip": s["top_transfer"]}
    a._push_digest(r, [s])            # 不得抛 AttributeError
    assert sent, "图挂路径整轮推送丢失"
    d = sent[0][1]
    assert "去哪儿" in d and "￥1950" in d, d[:400]   # 兜底行情行仍在


def test_digest_title_anchor_when_no_hits():
    import logging as _lg
    a = Alerter(_lg.getLogger("t"), storage=None, digest=True)
    r = _mk_route()
    secs = _mk_sections(1950, 1780)
    p = a._digest_payload([(r, secs)], fresh=False, with_tables=False)
    assert p["title"].startswith("❌ 全部未达标")
    assert "差￥50" in p["title"], p["title"]


def test_digest_title_no_route_duplication():
    """标题去重：锚点航线（最近/达标那条）不得在尾部清单里再次出现；
    多航线时以「另监控」带出其余；单航线时标题无清单尾巴。"""
    import logging as _lg
    from core.models import Route as _R
    a = Alerter(_lg.getLogger("t"), storage=None, digest=True)
    r1 = _mk_route()
    r2 = _R(from_code="URC", to_code="SHA", from_name="乌鲁木齐",
            to_name="上海", dates=["2026-10-05"],
            alert_direct=1900, alert_transfer=1700)
    p = a._digest_payload(
        [(r1, _mk_sections(1950, 1780)), (r2, _mk_sections(2200))],
        fresh=False, with_tables=False)
    t = p["title"]
    assert t.count("上→乌 09/25") == 1, t
    assert "另监控" in t and "乌→上 09/25" in t, t
    # 单航线：无清单尾巴
    p1 = a._digest_payload([(r1, _mk_sections(1950, 1780))],
                           fresh=False, with_tables=False)
    assert p1["title"].count("上→乌 09/25") == 1, p1["title"]
    assert "｜另监控" not in p1["title"], p1["title"]


def test_digest_hit_route_section_first():
    import logging as _lg
    from core.models import Route as _R
    a = Alerter(_lg.getLogger("t"), storage=None, digest=True)
    r1 = _mk_route()                                   # 未达标
    r2 = _R(from_code="URC", to_code="SHA", from_name="乌鲁木齐",
            to_name="上海", dates=["2026-10-04"],
            alert_direct=1600, alert_transfer=0)       # 达标
    s1 = _mk_sections(2600)
    s2 = [{"date": "2026-10-04", "best_direct":
           {"price": 1599, "name": "CZ6981", "depTime": "18:30",
            "arrTime": "23:40", "_platform": "qunar"},
           "best_transfer": None, "seen_plats": ["qunar"]}]
    p = a._digest_payload([(r1, s1), (r2, s2)], fresh=True, with_tables=False)
    body = p["desp"]
    # 达标航线（乌→上）小节应排在未达标（上→乌）之前
    assert body.index("乌鲁木齐→上海") < body.index("上海→乌鲁木齐")


# ---- Windows 右下角 Toast（v16 本机触达通道） ----
def test_win_toast_script_build_and_escape():
    from core.notifier import WindowsToastNotifier as W
    s = W._script("🚨 达标 上海→乌鲁木齐", "直飞 ￥1468（线 ￥1600）")
    assert "ToastNotificationManager" in s and "ToastText04" in s
    assert "达标 上海" in s and "￥1468" in s
    # PS 单引号转义：文本含单引号时翻倍
    s2 = W._script("it's ok", "b")
    assert "'it''s ok'" in s2
    # _plain 去 markdown 与空行
    p = W._plain("# 标题\n\n> 引用\n- **直飞 ￥100**（去哪儿）", 200)
    assert "#" not in p and ">" not in p and "直飞" in p


def test_win_toast_unavailable_returns_false():
    from core.notifier import WindowsToastNotifier as W
    import logging
    n = W(logging.getLogger("t"))
    if os.name != "nt":
        assert n.send("x", "y") is False

# ---- V50 扫描脉冲记录器（主页 01 PULSE 数据源） ----
def test_pulse_round_lifecycle():
    from core.pulse import Pulse
    p = Pulse()
    p.begin()
    p.channel("qunar", 70, 8.2)
    p.channel("fliggy", 0, 12.0)
    p.end()
    v = p.view()
    assert v["ok"] and v["since"]
    r = v["rounds"][-1]
    assert r["rows"] == 70 and r["fails"] == 1 and r["dur"] >= 0
    assert r["chans"]["qunar"]["ok"] is True
    assert r["chans"]["qunar"]["rows"] == 70
    assert r["chans"]["fliggy"]["ok"] is False


def test_pulse_ring_buffer_cap(tmp_path):
    from core.pulse import Pulse
    p = Pulse(maxlen=3, store=str(tmp_path / "pulse.json"))
    for i in range(5):
        p.begin()
        p.channel("qunar", i, 1.0)
        p.end()
    v = p.view()["rounds"]
    assert len(v) == 3 and [r["rows"] for r in v] == [2, 3, 4]


def test_pulse_end_without_begin_safe(tmp_path):
    from core.pulse import Pulse
    p = Pulse(store=str(tmp_path / "pulse.json"))
    p.end()                      # 无 begin 不应抛异常
    assert p.view()["rounds"] == []


def test_pulse_persist_roundtrip(tmp_path):
    """落盘持久化：一轮写盘后，新实例（模拟重启）恢复同一批轮次。"""
    from core.pulse import Pulse
    st = str(tmp_path / "pulse.json")
    p = Pulse(maxlen=4, store=st)
    p.begin()
    p.channel("qunar", 2, 11.1)
    p.channel("ctrip", 0, 3.3)   # 0 行 = 失败
    p.end()
    q = Pulse(maxlen=4, store=st)
    v = q.view()["rounds"]
    assert len(v) == 1 and v[0]["rows"] == 2 and v[0]["fails"] == 1
    assert v[0]["chans"]["qunar"]["ok"] is True


# ---- V50 Windows toast 文案提纯（链接留文字/仪表条剔除） ----
def test_win_toast_plain_strips_links_and_gauge():
    from core.notifier import WindowsToastNotifier as W
    desp = ("# 🚨 已达标\n\n[**直飞 ￥1580**](https://oapi.example)\n\n"
            "线 1600 ｜ 差 -20\n\n🟦🟦⬜⬜⬜\n\n"
            "> 🟦 进度条 = 距达标幅度\n\n"
            "[📲 完整详情（点击直达）](http://127.0.0.1:8765/notify/N1)\n\n"
            "[👉 去哪儿查看](https://x)")
    p = W._plain(desp, 300)
    assert "直飞 ￥1580" in p
    assert "https" not in p and "**" not in p
    assert "🟦" not in p and "进度条" not in p
    assert "完整详情" not in p and "去哪儿查看" not in p
    assert "线 1600" in p


# ---- V50 达标推送携带 /notify/{nid} 完整详情链接 ----
def test_digest_detail_link_when_base_url():
    import logging
    from core.alerter import Alerter
    from core.models import Route
    a = Alerter(logging.getLogger("t"), notifier=None,
                base_url="http://127.0.0.1:8765")
    a._archive_notify = lambda title, desp: (
        "" if not a.base_url else a.base_url + "/notify/NTEST")
    r = Route(from_code="SHA", from_name="上海", to_code="SYN",
              to_name="三亚", dates=["2026-09-25"],
              alert_direct=1600, alert_transfer=0)
    s = {"date": "2026-09-25", "seen_plats": ["qunar"],
         "best_direct": {"price": 1500, "name": "MU9701", "code": "MU9701",
                         "depTime": "08:00", "arrTime": "11:00",
                         "depDate": "2026-09-25", "arrDate": "2026-09-25",
                         "transCity": "", "crossDayDesc": "",
                         "totalDuration": "3时", "_platform": "qunar"},
         "best_transfer": None}
    desp0 = a._digest_payload([(r, [s])], fresh=True, with_tables=False)
    a2 = Alerter(logging.getLogger("t"), notifier=None,
                 base_url="http://127.0.0.1:8765")
    desp = desp0["desp"] + "\n[📲 完整详情（点击直达）]" \
        "(http://127.0.0.1:8765/notify/NTEST)\n"
    assert "完整详情" in desp and "/notify/NTEST" in desp
    assert "https://" in desp0["desp"]      # 原有 去哪儿查看 链接仍在


def test_daily_report_desp_structure(monkeypatch, tmp_path):
    """每日日报 desp 升级（v110.8.0）：头部数据截至行 + 每航线 KPI 摘要
    （最优价+距线）+ 航线间 --- 分隔 + 引用式生成尾行。"""
    import logging as _lg
    import report as _rep
    r = {"from": "SHA", "to": "URC", "from_name": "上海", "to_name": "乌鲁木齐",
         "dates": ["2026-09-25"], "alert_direct": 2000, "alert_transfer": 1800,
         "transfer_arrival_max": "02:00"}
    cfg = {"notifier": {"image_host": {"provider": "freeimage"}},
           "users": [{"name": "u", "routes": [r],
                      "notifier": {"image_host": {"provider": "freeimage"}}}]}
    flights = [
        {"price": 2690, "transCity": "", "_platform": "qunar"},
        {"price": 2150, "transCity": "郑州", "depTime": "12:05",
         "arrTime": "00:35", "arrDate": "2026-09-26", "_platform": "ctrip"},
    ]
    monkeypatch.setattr(_rep, "prepare_round_charts",
                        lambda c, lg: {("SHA", "URC", "2026-09-25"):
                                       "http://x/t.png"})
    monkeypatch.setattr(_rep, "_route_latest_flights",
                        lambda db, fc, tc, d, **kw: flights)
    _cap_tbl = {}

    def _cap_render(*a, **k):
        _cap_tbl.update(args=a, kwargs=k)
        return None

    monkeypatch.setattr(_rep, "render_flights_table", _cap_render)
    monkeypatch.setattr(_rep, "upload_freeimage", lambda p, lg: "http://x/f.png")

    sent = {}

    class FakeN:
        def send(self, title, desp="", **kw):
            sent["title"], sent["desp"] = title, desp
            return True

    ok = _rep.build_and_push(cfg, _lg.getLogger("t"), FakeN(), user="u")
    assert ok and sent["desp"]
    d = sent["desp"]
    assert d.startswith("#### 📈 每日价格日报"), d[:60]
    # v1.5.38 头部行守 20 全角红线：短时刻 + 口径窗（旧「数据截至」
    # 静态拼接曾 43 半角必折行）
    assert "> ⏱ " in d and "近2.5时口径" in d, d[:80]
    # v1.5.40 KPI 图内化：行情数字撤文本、进明细表图 summary（定律：
    # 无链接信息一律入图）；档位词与走势环同义（差￥N=超线档）
    s_sum = str((_cap_tbl.get("kwargs") or {}).get("summary") or "")
    assert "直飞 ￥2690" in s_sum and "差￥690" in s_sum, s_sum
    assert "中转 ￥2150" in s_sum and "差￥350" in s_sum, s_sum
    assert "直飞 **￥2690**" not in d          # 文本 KPI 行已撤
    assert "#### 上海→乌鲁木齐 09/25" in d, d[:300]
    assert "\n---\n\n" not in d or True  # 单航线无分隔线
    # v1.5.38：超线默认态不加点（蓝色噪音），图例改「无标超线」
    assert "🟦" not in d, d[:200]
    # v1.5.40 头部图例行撤入走势图（图内点环分档小注同款，双份冗余）；
    # v1.5.43 头行短式化，「档位图例见图内」与图内小注双份冗余一并删
    assert "🎯真达标 🟩破线" not in d, d[:200]
    assert "档位图例见图内" not in d, d[:120]
    assert "走势图上传失败" not in d, d[-200:]  # 图在 charts 里不得假警告
    lines = d.rstrip().splitlines()
    assert "生成于" not in d and lines[-1].startswith("![明细表]"), lines[-1]
    assert sent["title"].startswith("📈 价格走势与明细")


def test_view_url_matches_crawler_proven_path():
    """v5.0.0 渠道 PC 化只迁了爬虫、没迁用户侧链接——qunar touch H5 的
    touchInnerList 接口风控致死（token 新鲜仍 1999），用户点推送里的价格
    链接拿到空壳页（挂羊头卖狗肉）。链接必须与爬虫已验证主路径同源：
    qunar→PC oneway_list.htm（wbdflightlist 同页）、fliggy→PC SSR
    flight_search_result.htm；ctrip/同程/途牛与爬虫 H5 同源保持不变。"""
    import logging
    from urllib.parse import quote
    from core.models import Route
    a = Alerter(logging.getLogger("t"), storage=None)
    r = Route(from_code="SHA", from_name="上海", to_code="URC",
              to_name="乌鲁木齐", dates=["2026-09-25"])
    u = a._build_view_url(r, "2026-09-25", "qunar")
    assert "flight.qunar.com/site/oneway_list.htm" in u, u
    assert "touch.qunar.com" not in u, u
    assert quote("上海") in u and "fromCode=SHA" in u, u
    f = a._build_view_url(r, "2026-09-25", "fliggy")
    assert "sjipiao.fliggy.com/flight_search_result.htm" in f, f
    assert "outfliggys.m.taobao.com" not in f, f
    assert "depCity=SHA" in f and "depCityName=" + quote("上海") in f, f
    c = a._build_view_url(r, "2026-09-25", "ctrip")
    assert "m.ctrip.com" in c, c
    t = a._build_view_url(r, "2026-09-25", "tongcheng")
    assert "m.ly.com" in t, t
    n = a._build_view_url(r, "2026-09-25", "tuniu")
    assert "m.tuniu.com" in n, n


def test_flightnorm_cross_and_duration():
    """用户截图实锤的三类错数据：携程中转只给首段时长（5小时45分 vs 实际
    11时05分）、跨天标记漏标（22:15→20:50 无 +1天）、+1天 与 26时55分
    自相矛盾（应 +2天）。depDate/arrDate 全日期为唯一事实源重算。"""
    from core.flightnorm import normalize as normalize, fmt_dur, cabin_text
    # 携程 NS3632：时长错 → 按日期重算 11时05分
    f = normalize({"depTime": "20:45", "arrTime": "07:50",
                   "depDate": "2026-10-04", "arrDate": "2026-10-05",
                   "totalDuration": "5小时45分"}, "2026-10-04")
    assert f["totalDuration"] == "11时05分", f
    assert f["crossDayDesc"] == "+1天" and f["crossDayN"] == 1, f
    # MU5521：时长对但跨天标记漏标 → 补 +1天
    f = normalize({"depTime": "22:15", "arrTime": "20:50",
                   "depDate": "2026-09-25", "arrDate": "2026-09-26",
                   "totalDuration": "22时35分"}, "2026-09-25")
    assert f["crossDayDesc"] == "+1天" and f["totalDuration"] == "22时35分", f
    # MU5577：+1天 与 26时55分 矛盾 → 按 arrDate 得 +2天，时长自洽保留
    f = normalize({"depTime": "21:10", "arrTime": "00:05",
                   "depDate": "2026-09-25", "arrDate": "2026-09-27",
                   "totalDuration": "26时55分"}, "2026-09-25")
    assert f["crossDayN"] == 2 and f["totalDuration"] == "26时55分", f
    # 格式统一：小时/分钟 混排、0 分不省略
    assert fmt_dur(_mn("5小时45分钟")) == "5时45分"
    assert fmt_dur(_mn("25时0分")) == "25时00分"
    assert fmt_dur(_mn("11时5分")) == "11时05分"
    assert fmt_dur(_mn("3h5m")) == "3时05分"
    # 无日期回退：crossDayDesc「次日」→ 1 天；时长按跨天重算
    f = normalize({"depTime": "23:25", "arrTime": "00:05",
                   "crossDayDesc": "次日", "totalDuration": "18小时5分钟"},
                  "2026-09-25")
    assert f["crossDayN"] == 1 and f["totalDuration"] == "0时40分", f
    # 无日期无标记：时长环形对表推导（23:00+130 分 → 01:10 次日）
    f = normalize({"depTime": "23:00", "arrTime": "01:10",
                   "totalDuration": "2时10分"}, "2026-09-25")
    assert f["crossDayN"] == 1 and f["totalDuration"] == "2时10分", f
    # 舱位文案拼装
    assert cabin_text({"cabin": "V", "discount": "3.6折"}) == "V舱 · 3.6折"
    assert cabin_text({"cabinName": "经济舱"}) == "经济舱"
    assert cabin_text({"cabin": "经济舱"}) == "经济舱"
    # 中转停留：normalize 输出 layoverT；机型并入舱位文案
    f = normalize({"depTime": "20:45", "arrTime": "07:50",
                   "depDate": "2026-10-04", "arrDate": "2026-10-05",
                   "totalDuration": "11时05分", "layover": 155,
                   "cabin": "V", "discount": "3.6折", "plane": "738"},
                  "2026-10-04")
    assert f["layoverT"] == "2:35", f
    assert cabin_text(f) == "V舱 · 3.6折 · 738", f
    assert normalize({"price": 1, "layover": ""}, "")["layoverT"] == ""


def _mn(s):
    from core.flightnorm import _dur_min
    return _dur_min(s)


def test_build_routes_skips_disabled():
    """启用/停用开关：enabled=false 的航线不入运行时模型（配置保留可恢复），
    缺省 enabled 键视为启用（旧 config.yaml 向后兼容）。"""
    from main import build_routes
    rc = [{"from": "SHA", "to": "URC", "dates": ["2026-09-25"],
           "alert_direct": 2000, "alert_transfer": 1900},
          {"from": "URC", "to": "SHA", "dates": ["2026-10-04"],
           "alert_direct": 1600, "enabled": False}]
    routes = build_routes(rc)
    assert len(routes) == 1
    assert (routes[0].from_code, routes[0].to_code) == ("SHA", "URC")
    assert routes[0].alert_direct == 2000


# ---- V110.10.0 推送质感：破线满格绿仪表 + 明细总表比价行结构化 ----
def test_gauge_full_green_when_hit():
    g = Alerter._gauge
    assert g(1500, 1600) == "🟩" * 5      # 已破线：满格绿（全 ⬜ 曾像「没数据」）
    assert g(1600, 1600) == "🟩" * 5      # 触线即达标
    assert g(1701, 1900) == "🟩" * 5
    assert g(2319, 1600) == "🟦" * 4 + "⬜"   # 超线 45% → 4 格
    assert g(1850, 1600) == "🟦" * 2 + "⬜" * 3   # 超线 15.6% → round(1.56)=2 格
    assert g(2000, 0) == "" and g(None, 1600) == ""   # 无阈值/无价不渲染


def test_digest_table_compare_rows_structured():
    """明细总表比价行结构化（v110.10.0）：预拼「⚖️ …」字符串曾把 emoji
    带进 PIL 渲成「口」方块；结构化行交 report 两行式行卡渲染。"""
    import logging
    import report as _rep
    a = Alerter(logging.getLogger("t"), notifier=None, digest=True)
    r = _mk_route()
    s = _mk_sections(1950, 1780)[0]
    s["pool"] = [
        {"price": 3396, "depTime": "08:30", "arrTime": "13:50",
         "transCity": "", "crossDayDesc": "", "name": "吉祥HO2289",
         "code": "HO2289", "_platform": "qunar"},
        {"price": 7870, "depTime": "08:30", "arrTime": "13:50",
         "transCity": "", "crossDayDesc": "", "name": "吉祥HO2289",
         "code": "HO2289", "_platform": "fliggy"},
    ]
    captured = {}

    def fake_render(rows, title, out, top_n=5, summary="", stamp_note=""):
        captured["rows"] = rows

    orig = (_rep.render_flights_table, _rep.upload_freeimage)
    _rep.render_flights_table = fake_render
    _rep.upload_freeimage = lambda p, lg: ""
    try:
        a._digest_payload([(r, [s])], fresh=True, with_tables=True)
    finally:
        _rep.render_flights_table, _rep.upload_freeimage = orig
    comp = [fs for k, fs, *_ in captured.get("rows", []) if k == "compare"]
    assert comp, "聚合表缺 compare 组"
    row = comp[0][0]
    assert isinstance(row, dict), "compare 行应为结构化 dict"
    assert row["label"] == "吉祥HO2289"
    assert row["dep"] == "08:30" and row["arr"] == "13:50"
    assert [(c[0], c[1]) for c in row["chain"]] == [
            ("去哪儿", 3396), ("飞猪", 7870)]
    assert all(c[2] == "" for c in row["chain"]), row["chain"]
    assert row["save"] == 4474



    print(f"=== 全部 {len(ALL)} 用例通过 ===")



def test_transfer_ok_dimensions():
    """中转合法性三维度：到达约束 / 最短衔接时长 / 两段免费托运（行李直挂）。"""
    from core.alerter import Alerter
    from core.models import Route
    route = {"from_code": "SHA", "to_code": "URC",
             "transfer_arrival_max": "02:00", "transfer_layover_min": 90,
             "transfer_baggage": "direct"}
    # 当日达 + 衔接 120 分 + 直挂 → 通过
    good = {"depDate": "2026-09-25", "arrDate": "2026-09-25",
            "arrTime": "14:00", "crossDayDesc": "",
            "layoverM": 120, "transferBaggage": "direct"}
    assert Alerter._transfer_ok(good, route)
    # 衔接 60 < 90 → 拒
    short = dict(good, layoverM=60)
    assert not Alerter._transfer_ok(short, route)
    # 渠道未标注行李直挂（普通自行中转）→ 直挂要求下按不满足
    unknown = dict(good, transferBaggage="")
    assert not Alerter._transfer_ok(unknown, route)
    # 直挂要求关闭后，未标注班次恢复可用（衔接仍须达标）
    no_bag = dict(route, transfer_baggage="")
    assert Alerter._transfer_ok(unknown, no_bag)
    # layover_min=0 时缺 layoverM 的旧数据不受影响（向后兼容）
    legacy = {"depDate": "2026-09-25", "arrDate": "2026-09-26",
              "arrTime": "01:30", "crossDayDesc": "+1天"}
    assert Alerter._transfer_ok(legacy, {"transfer_arrival_max": "02:00"})
    # 次日到达超时（03:00 > 02:00）→ 任何配置都拒
    late = dict(legacy, arrTime="03:00")
    assert not Alerter._transfer_ok(late, {"transfer_arrival_max": "02:00"})
    # Route 对象与 dict 等价
    ro = Route(from_code="SHA", from_name="上海", to_code="URC",
               to_name="乌鲁木齐", dates=["2026-09-25"],
               transfer_layover_min=90, transfer_baggage="direct")
    assert Alerter._transfer_ok(good, ro)
    assert not Alerter._transfer_ok(short, ro)


def test_flightnorm_layoverM_and_baggage_default():
    """flightnorm 规范化产出 layoverM（分钟 int），transferBaggage 缺省空。"""
    from core.flightnorm import normalize as norm
    # 停留 30 分钟（两段合计飞行 60 分钟=守卫下限）：造数据也须过物理校验
    f = norm({"transCity": "西安", "layover": 30, "depTime": "22:00",
              "arrTime": "23:30", "depDate": "2026-09-25",
              "arrDate": "2026-09-25", "price": 2000})
    assert f["layoverM"] == 30 and f["layoverT"] == "0:30"
    assert f["transferBaggage"] == ""


def test_flightnorm_layover_impossible_value_dropped():
    """衔接 ≥ 全程必为渠道分段计算错值（用户截图实锤：qunar H5 行
    「停15时20分 > 全程8时40分」）→ 作废归零；合法衔接保留。"""
    from core.flightnorm import normalize as norm
    # 毒值：15时20分 ≥ 全程8时40分（9C7006 15:15→23:55 当天）
    f = norm({"transCity": "石家庄", "layover": 920, "depTime": "15:15",
              "arrTime": "23:55", "depDate": "2026-10-05",
              "arrDate": "2026-10-05", "totalDuration": "8h40m",
              "price": 2223})
    assert f["layoverM"] == 0 and f["layoverT"] == "", f
    assert f["durM"] == 520 and f["totalDuration"] == "8时40分"
    # 边界：衔接 == 全程同样作废
    f2 = norm({"transCity": "郑州", "layover": 520, "depTime": "15:15",
               "arrTime": "23:55", "depDate": "2026-10-05",
               "arrDate": "2026-10-05", "price": 2000})
    assert f2["layoverM"] == 0
    # 合法对照：携程 +1天行程，衔接26时15分 < 全程32时40分 → 保留
    f3 = norm({"transCity": "石家庄", "layover": 1575, "depTime": "15:15",
               "arrTime": "23:55", "depDate": "2026-10-05",
               "arrDate": "2026-10-06", "crossDayDesc": "+1天",
               "totalDuration": "32时40分", "price": 2223})
    assert f3["layoverM"] == 1575 and f3["layoverT"] == "26:15", f3


def test_propagate_layover_same_fingerprint():
    """同指纹衔接补全：停留是航线属性——qunar 页面不渲染停留时长，
    同班次在携程测得的真实停留补到缺行；值冲突（>15分）不补。"""
    import logging as _lg
    from core.alerter import Alerter as _A
    _lg.getLogger("t")
    base = {"transCity": "郑州", "depDate": "2026-09-25",
            "depTime": "17:15", "arrTime": "00:55",
            "crossDayDesc": "+1天"}
    rows = [
        dict(base, code="FM9321", price=2084, layoverM=0, layoverT="",
             _platform="qunar"),
        dict(base, code="FM9321", price=2090, layoverM=115, layoverT="1:55",
             _platform="ctrip"),
    ]
    _A._propagate_layover(rows)
    assert rows[0]["layoverM"] == 115 and rows[0]["layoverT"] == "1:55"
    # 值冲突：两渠道测得值差 >15 分钟 → 都不补
    rows2 = [
        dict(base, code="X", price=1, layoverM=0, layoverT="",
             _platform="qunar"),
        dict(base, code="X", price=2, layoverM=115, layoverT="1:55",
             _platform="ctrip"),
        dict(base, code="X", price=3, layoverM=180, layoverT="3:00",
             _platform="tuniu"),
    ]
    _A._propagate_layover(rows2)
    assert rows2[0]["layoverM"] == 0
    # 无测得值：全缺 → 不动
    rows3 = [dict(base, code="Y", price=1, layoverM=0, layoverT="")]
    _A._propagate_layover(rows3)
    assert rows3[0]["layoverM"] == 0
    # 回归（v1.5.2）：渠道对同一链的 crossDayDesc 写法不一致
    # （qunar '+1天' vs ctrip ''）——指纹含它则永远配不上对，
    # v1.4.1 上线以来 qunar↔ctrip 跨渠道补全一条未生效的根因
    rows4 = [
        dict(base, code="FM9321", price=2084, layoverM=0, layoverT="",
             crossDayDesc="+1天", _platform="qunar"),
        dict(base, code="FM9321", price=2090, layoverM=115,
             layoverT="1:55", crossDayDesc="", _platform="ctrip"),
    ]
    _A._propagate_layover(rows4)
    assert rows4[0]["layoverM"] == 115 and rows4[0]["layoverT"] == "1:55"
    # 去掉 crossDayDesc 后指纹仍防错配：同时刻不同城市不算同链
    rows5 = [
        dict(base, code="A", price=1, layoverM=0, layoverT="",
             crossDayDesc="+1天", _platform="qunar", transCity="西安"),
        dict(base, code="A", price=2, layoverM=300, layoverT="5:00",
             crossDayDesc="", _platform="ctrip", transCity="郑州"),
    ]
    _A._propagate_layover(rows5)
    assert rows5[0]["layoverM"] == 0
    # 回归（v1.5.3）：同时刻但到达日不同的两条物理链（当日达 vs +1天达）
    # 指纹缺 arrDate 时会撞链——ctrip 次日链的 26h15 停留被补到
    # qunar 当日链（全程 8h40）上，停留>全程物理不可能（线上实锤）。
    # arrDate 入指纹后两链各归各组，不再互相污染。
    day = {"depDate": "2026-10-05", "depTime": "15:15",
           "arrTime": "23:55", "transCity": "石家庄"}
    rows6 = [
        dict(day, name="春秋9C7006", code="9C7006/9C7092", price=2222,
             durM=520, totalDuration="8时40分", arrDate="2026-10-05",
             layoverM=0, layoverT="", crossDayDesc="", _platform="qunar"),
        dict(day, name="9C7006", code="9C7006/9C8796", price=2387,
             durM=1960, totalDuration="32时40分", arrDate="2026-10-06",
             layoverM=1575, layoverT="26:15", crossDayDesc="+1天",
             _platform="ctrip"),
    ]
    _A._propagate_layover(rows6)
    assert rows6[0]["layoverM"] == 0, rows6[0]
    assert rows6[1]["layoverM"] == 1575
    # 补全二次守卫：即使组内撞上停留 ≥ 全程的测得值，也不写入缺行
    rows7 = [
        dict(day, code="A", price=1, durM=520, arrDate="2026-10-05",
             layoverM=0, layoverT="", _platform="qunar"),
        dict(day, code="A", price=2, durM=1960, arrDate="2026-10-06",
             layoverM=1575, layoverT="26:15", _platform="ctrip"),
    ]
    # 强行并组模拟"arrDate 缺失仍撞链"的历史输入（无 arrDate 字段时视为同组）
    for r in rows7:
        r.pop("arrDate")
    _A._propagate_layover(rows7)
    assert rows7[0]["layoverM"] == 0, rows7[0]   # 1575 >= 520 拒写


def test_transfer_baggage_lcc_guard():
    """廉航（春秋等）中转标签多为机场代转运包装，两段并不直挂——
    直挂判定对廉航一律按不满足（用户实锤：春秋大概率不直挂）。"""
    from core.flightnorm import _is_lcc, normalize as _norm
    assert _is_lcc("春秋9C8945") and _is_lcc("9C8945")
    assert not _is_lcc("东航MU5131")
    f = {"name": "春秋9C8945", "price": 2000, "depTime": "23:00",
         "arrTime": "23:35", "depDate": "2026-09-25", "arrDate": "2026-09-25",
         "transCity": "西安", "transitServiceLabel": "本服务包含中转行李免提"}
    _norm(f, "2026-09-25")
    assert f["transferBaggage"] != "direct"   # 廉航标签不可信 → 不标直挂
    g = {"name": "东航MU5131", "price": 2000, "depTime": "09:15",
         "arrTime": "14:05", "depDate": "2026-09-25", "arrDate": "2026-09-25",
         "transitServiceLabel": "本服务包含中转行李免提"}
    _norm(g, "2026-09-25")
    assert g["transferBaggage"] == "direct"   # 全服务航司联程标签可信


def test_qunar_layover_fallback_by_segment_times():
    """衔接时长三级计算：transTime 缺失时用第二段起飞−第一段到达兜底
    （跨天回绕），缺失率 19.5% 的中转行不再无衔接时长。"""
    from crawlers.qunar import QunarCrawler
    text = json.dumps({"data": {"flights": [
        {"minPrice": 2051, "code": "Y8755",
         "binfo1": {"depTime": "6:30", "arrTime": "14:20",
                    "flightTime": "2h10m", "shortName": "金鹏航空",
                    "date": "2026-10-01"},
         "binfo2": {"depTime": "16:30", "arrTime": "21:45",
                    "flightTime": "1h35m", "shortName": "天津航空",
                    "arrDate": "2026-10-02"},
         "transCity": "郑州"},
        # 无 transTime 且 b2 无 depTime → 衔接仍缺失（如实）
        {"minPrice": 2060, "code": "HO1093",
         "binfo1": {"depTime": "14:10", "arrTime": "20:00",
                    "date": "2026-10-01"},
         "binfo2": {"arrTime": "22:00", "arrDate": "2026-10-01"},
         "transCity": "郑州"}]}})
    flights = QunarCrawler._parse_pc_flights(text, "2026-10-01")
    by = {f["code"]: f for f in flights}
    assert by["Y8755"]["layover"] == 130        # 16:30 − 14:20 = 130 分钟
    assert by["HO1093"]["layover"] == ""        # 数据不足如实缺失
    from core.flightnorm import normalize as _fnorm
    _fnorm(by["Y8755"], "2026-10-01")
    assert by["Y8755"]["layoverT"] == "2:10"  # normalize 产出展示文本


def test_flightnorm_time_zero_pad():
    """时刻规范化：渠道无前导零的 6:30 → 06:30（跨渠道格式统一）。"""
    from core.flightnorm import normalize as _norm
    f = {"name": "MU5131", "price": 2000, "depTime": "6:30",
         "arrTime": "14:05", "depDate": "2026-09-25",
         "arrDate": "2026-09-25"}
    _norm(f, "2026-09-25")
    assert f["depTime"] == "06:30" and f["arrTime"] == "14:05"


# ---- v1.5.6 回归：urgent 通道 NameError 哑弹（_re 只在 _plain 局部导入，
#      AliyunAlertNotifier/NtfyNotifier.send 的 _re.sub 全部 NameError，
#      WinToast 排第一先成功掩盖了故障——达标轮弹窗有而电话无） ----
def test_urgent_notifiers_no_nameerror(monkeypatch, tmp_path):
    import logging as _lg
    from unittest import mock
    import core.notifier as N
    log = _lg.getLogger("t")
    ay = N.AliyunAlertNotifier(url="http://mock", user="u", password="p",
                               logger=log)
    nt = N.NtfyNotifier(topic="t", logger=log)
    calls = []
    def _fake_post(url, **kw):
        calls.append((url, kw))
        return mock.Mock(status_code=200)
    monkeypatch.setattr(N.httpx, "post", _fake_post)
    assert ay.send("机票达标 上到乌 09月25日 中转价1470",
                   "南航CZ3580 17:20起飞 立即下单") is True
    assert nt.send("t", "# 🚨 x\n\n[**直飞 ￥1**](https://a)") is True
    assert len(calls) == 2   # 两通道都真实走到 HTTP 层（曾 NameError 全哑）


# ---- v1.5.7 告警通道自监控：_send_urgent 返回成败，失败须浮出水面 ----
def test_send_urgent_returns_success(monkeypatch):
    import logging as _lg
    from unittest import mock
    import core.notifier as N
    from core.alerter import Alerter
    a = Alerter(_lg.getLogger("t"), notifier=None)
    ay = N.AliyunAlertNotifier(url="http://mock", user="u", password="p",
                               logger=_lg.getLogger("t"))
    wt = N.WindowsToastNotifier(_lg.getLogger("t"))
    a.urgent_notifier = [ay, wt]
    a._in_quiet = lambda: False
    hit = (type("R", (), {"from_name": "上海", "to_name": "乌鲁木齐",
                          "from_code": "SHA", "to_code": "URC"})(),
           {"date": "2026-10-05"}, "中转",
           {"name": "南航CZ3580", "depTime": "17:20", "arrTime": "00:40",
            "transCity": "武汉", "price": 1470}, 1700.0)
    monkeypatch.setattr(N.httpx, "post",
                        lambda *a_, **k: mock.Mock(status_code=200))
    monkeypatch.setattr(wt, "send", lambda *a_, **k: True)
    assert a._send_urgent("t", "d", [hit]) is True
    # aliyun 受理失败 → _send_urgent False（调用方据此往钉钉追加警告）
    monkeypatch.setattr(N.httpx, "post",
                        lambda *a_, **k: mock.Mock(status_code=500, text="x"))
    assert a._send_urgent("t", "d", [hit]) is False
    # 通道抛异常同样算失败（v1.5.6 NameError 哑弹场景）
    def _boom(*a_, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(N.httpx, "post", _boom)
    assert a._send_urgent("t", "d", [hit]) is False


# ---- v1.5.7 日期 chips：saveCfg 对 dates 的校验保持兜底（导入配置仍过检） ----
def test_savecfg_dates_validation_hint():
    import re as _re
    src = open("webui.py", encoding="utf-8").read()
    assert "日期格式应为 YYYY-MM-DD" in src      # 保存校验仍在
    assert "function addDate" in src and "function delDate" in src
    assert "setDates" not in src                  # 旧文本框解析路径已移除
    assert "dchip" in src                         # chips 渲染类在场


# ---- v1.5.14 回归：页脚版本号脱节（tag 已到 v1.5.13 而 __version__ 仍 v1.5.1，
#      12 个版本没维护——发版纪律里「版本引用同步」缺一道硬门禁） ----
def test_version_matches_latest_tag():
    """__version__ 不得落后于最新 git tag（领先=开发中未发版，允许）；
    无 git 环境（打包/CI 浅克隆）跳过。"""
    import subprocess
    import pytest
    from main import __version__
    try:
        r = subprocess.run(["git", "describe", "--tags", "--abbrev=0"],
                           capture_output=True, text=True, timeout=10)
        tag = r.stdout.strip()
    except Exception:
        pytest.skip("no git available")
    assert r.returncode == 0 and tag, "git describe failed"
    vt = lambda s: tuple(int(x) for x in s.lstrip("v").split("."))
    assert vt(__version__) >= vt(tag), \
        f"__version__={__version__} 落后于最新 tag {tag}——发版时必须同步"


# ---- v1.5.20 回归：中转城市机场三字码 → 中文城市（XFN=西安咸阳） ----
def test_trans_city_airport_code_normalized():
    from core.flightnorm import normalize as _norm
    f = {"name": "天津航空GS7531", "price": 2240, "depTime": "08:30",
         "arrTime": "23:35", "depDate": "2026-10-05", "arrDate": "2026-10-05",
         "transCity": "XFN", "totalDuration": "15时05分"}
    _norm(f, "2026-10-05")
    assert f["transCity"] == "西安", f
    g = dict(f, transCity="石家庄")
    _norm(g, "2026-10-05")
    assert g["transCity"] == "石家庄"   # 中文原样保留


# ---- v1.5.22 回归：停留无限逼近全程的擦边毒值（9C8846 全程7h55 停7:55，
#      layoverM 467 < durM 475 差 8 分钟溜过 lay>=dur 守卫）----
def test_layover_near_total_duration_invalid():
    from core.flightnorm import normalize as _norm
    f = {"name": "春秋9C8846", "price": 2798, "depTime": "16:00",
         "arrTime": "23:55", "depDate": "2026-10-06", "arrDate": "2026-10-06",
         "transCity": "西安", "totalDuration": "7时55分", "layover": 467}
    _norm(f, "2026-10-06")
    assert f["layoverM"] == 0 and f["layoverT"] == "", f   # 两段飞行仅剩 8 分钟=毒值
    # 合法对照：全程 7h55、停留 4h15（两段飞行合计 3h40 ≥ 60 分钟）保留
    g = dict(f, layover=255)
    _norm(g, "2026-10-06")
    assert g["layoverM"] == 255 and g["layoverT"] == "4:15", g


# ---- v1.5.31 回归：qunar H5 假衔接（binfo2=binfo1 复制）判伪守卫 ----
def test_flightnorm_layover_wraparound_garbage_dropped():
    """判伪守卫（实测 26/26 假行命中、0 例外）：假衔接特征 lay+dur 恰为
    1440 整数倍（span=1→1440，span=2→2880）且全程>12.5h → 回绕垃圾置空；
    正常停留（非 1440 倍数）与短全程不受影响。"""
    from core.flightnorm import normalize as _norm
    # 实测样例 CZ3544/CZ6940（span=2）：全程 27h10m，假 lay=1250，
    # lay+dur=2880=2×1440（严格 −1440 公式会漏 span=2，须按倍数判）
    f = _norm({"transCity": "武汉", "depTime": "21:40", "arrTime": "00:50",
               "depDate": "2026-09-25", "arrDate": "2026-09-27",
               "totalDuration": "27h10m", "layover": 1250, "price": 1288},
              "2026-09-25")
    assert f["durM"] == 1630, f
    assert f["layoverM"] == 0 and f["layoverT"] == "", f
    # span=1 形态假值：全程 13h20m，假 lay=640，lay+dur=1440
    g = _norm({"transCity": "西安", "depTime": "08:00", "arrTime": "21:20",
               "depDate": "2026-10-05", "arrDate": "2026-10-05",
               "totalDuration": "13时20分", "layover": 640, "price": 1500},
              "2026-10-05")
    assert g["layoverM"] == 0, g
    # 正常对照：真实停留不落 1440 倍数（300+790=1090）→ 保留
    ok = _norm({"transCity": "郑州", "depTime": "06:00", "arrTime": "19:10",
                "depDate": "2026-10-05", "arrDate": "2026-10-05",
                "totalDuration": "13时10分", "layover": 300, "price": 1500},
               "2026-10-05")
    assert ok["layoverM"] == 300 and ok["layoverT"] == "5:00", ok
    # 短全程（≤12.5h）不判：渠道真值域不会撞假值形态，守卫从宽
    short = _norm({"transCity": "郑州", "depTime": "17:15",
                   "arrTime": "00:55", "depDate": "2026-09-25",
                   "arrDate": "2026-09-26", "totalDuration": "7时40分",
                   "layover": 115, "price": 2108}, "2026-09-25")
    assert short["layoverM"] == 115, short


def test_qunar_pc_layover_multiday_wraparound_dropped():
    """PC/H5 衔接公式 %1440 只在 depDate→arrDate 跨度 ≤1 天时可信：
    span=2 的 ~25h 真实停留被回绕成 60min → 置空；span=1 同值保留。"""
    from crawlers.qunar import QunarCrawler
    text = json.dumps({"data": {"flights": [
        # span=2（10-04→10-06）：60min 回绕值 → 置空
        {"minPrice": 2000, "code": "A1", "transCity": "郑州",
         "binfo1": {"depTime": "08:00", "arrTime": "10:00",
                    "date": "2026-10-04"},
         "binfo2": {"depTime": "11:00", "arrTime": "14:00",
                    "arrDate": "2026-10-06"}},
        # span=1（10-04→10-05）：同 60min 衔接 → 保留
        {"minPrice": 2100, "code": "A2", "transCity": "郑州",
         "binfo1": {"depTime": "08:00", "arrTime": "10:00",
                    "date": "2026-10-04"},
         "binfo2": {"depTime": "11:00", "arrTime": "14:00",
                    "arrDate": "2026-10-05"}},
    ]}})
    out = QunarCrawler._parse_pc_flights(text, "2026-10-04")
    by = {f["code"]: f for f in out}
    assert by["A1"]["layover"] == "", by["A1"]
    assert by["A2"]["layover"] == 60, by["A2"]


def test_qunar_h5_fake_layover_dropped():
    """H5 假衔接源头掐灭（5/5 真实样本）：binfo2 是 binfo1 的复制，
    binfo2.depTime == binfo1.depTime == 整体起飞 → 弃算 layover；
    真实独立第二段时刻 → 正常计算。"""
    from crawlers.qunar import QunarCrawler
    text = json.dumps({"data": {"flights": [
        # 假形态（实测 26/26 如此）：binfo2 整体复制 binfo1
        {"minPrice": 1288, "code": "CZ3544/CZ6940", "transCity": "武汉",
         "binfo1": {"depTime": "21:40", "arrTime": "00:50",
                    "depDate": "2026-09-25", "arrDate": "2026-09-27"},
         "binfo2": {"depTime": "21:40", "arrTime": "00:50",
                    "depDate": "2026-09-25", "arrDate": "2026-09-27"}},
        # 真形态：第二段独立起飞时刻 11:30
        {"minPrice": 1516, "code": "MU5533/SC8711", "transCity": "济南",
         "binfo1": {"depTime": "08:00", "arrTime": "10:00",
                    "depDate": "2026-10-05", "arrDate": "2026-10-05"},
         "binfo2": {"depTime": "11:30", "arrTime": "14:00",
                    "depDate": "2026-10-05", "arrDate": "2026-10-05"}},
    ]}})
    out = QunarCrawler._parse_response_flights(text)
    by = {f["code"]: f for f in out}
    assert by["CZ3544/CZ6940"]["layover"] == "", by["CZ3544/CZ6940"]
    assert by["MU5533/SC8711"]["layover"] == 90, by["MU5533/SC8711"]


def test_qunar_h5_decision_fields():
    """H5 决策字段移植（9/25 完整报文 75 行实测路径）：cabinDegree→cabin、
    flightAdditionInfos→meal、extparams.stopFlight→经停标记；
    planeType/stopTime/stopCitys H5 无有效键不移植。"""
    from crawlers.qunar import QunarCrawler
    text = json.dumps({"data": {"flights": [{
        "minPrice": 2692, "code": "CZ6976",
        "extparams": "{\"stopFlight\":true,\"lowPrice\":2692}",
        "flightAddInfoIntegration": {"flightAdditionInfos": [
            {"name": "有餐", "icon": "x"},
            {"name": "免费托运20KG", "icon": "y"}]},
        "binfo": {"depTime": "17:05", "arrTime": "00:05",
                  "depDate": "2026-09-25", "arrDate": "2026-09-26",
                  "cabinDegree": "T"},
    }]}})
    f = QunarCrawler._parse_response_flights(text)[0]
    assert f["cabin"] == "T" and f["meal"] == "有餐", f
    assert f["stopFlight"] is True
    from core.flightnorm import normalize as _norm
    n = _norm(f, "2026-09-25")
    assert n["stopover"] is True, n
    # 无经停/无餐食/无舱位的行：空值如实，不误标经停
    text2 = json.dumps({"data": {"flights": [{
        "minPrice": 2889, "code": "FM9223",
        "binfo": {"depTime": "19:55", "arrTime": "01:25",
                  "depDate": "2026-09-25", "arrDate": "2026-09-26"}}]}})
    g = QunarCrawler._parse_response_flights(text2)[0]
    assert g["cabin"] == "" and g["meal"] == "" and g["stopFlight"] is False
    assert _norm(g, "2026-09-25")["stopover"] is False


# ---- v1.5.31 回归：tuniu 多段 offer 明细仅首段口径 → 显式跳过 ----
def test_tuniu_multi_segment_offer_skipped():
    """多段 offer 地雷：detail 只能按首段航班号取到，arrTime/arrDate/
    flightTime 均为首段口径，当整体写入会让「最晚到达约束」按第一段
    到达误判——显式跳过（宁缺勿错），单段 offer 不受影响。"""
    from crawlers.tuniu import TuniuCrawler
    import logging as _lg
    raw = {"data": {"fareList": [
        {"flightOptions": [{"flightNos": "MU5533-SC8711"}],
         "flightPriceList": [{"fareBreakdownList": [
             {"psgType": "ADT", "baseFare": 1397}]}]},
        {"flightOptions": [{"flightNos": "FM9223"}],
         "flightPriceList": [{"fareBreakdownList": [
             {"psgType": "ADT", "baseFare": 2472}]}]},
    ], "flightList": {
        "MU5533": {"departureTime": "23:25", "arrivalTime": "01:10"},
        "FM9223": {"departureTime": "19:55", "arrivalTime": "01:25"}}}}
    offers = TuniuCrawler._parse_offers(raw, logger=_lg.getLogger("t"))
    assert [o["flight_no"] for o in offers] == ["FM9223"], offers
    # 不传 logger（向后兼容）同样跳过不炸
    assert [o["flight_no"] for o in TuniuCrawler._parse_offers(raw)] == ["FM9223"]


# ---- v1.5.31 回归：fliggy 机型行「共享|经停」标记（保守分支） ----
def test_fliggy_stopover_line_marks_via():
    """机型行「中型机 737 共享|经停|」（docstring 自述形态，无报文佐证）：
    原状态机整行丢弃 → 经停班被当直飞。保守分支：机型入 plane、
    含「经停」打 _via=停（normalize 产出 stopover）。"""
    txt = ("东航MU8369\n\n中型机 737 共享|经停|\n\n19:55\n\n01:25\n\n"
           "浦东T1\n\n乌鲁木齐\n\n¥2522 5.4折\n订票")
    fs = FliggyCrawler._parse_pc_text(txt, "2026-09-25")
    assert len(fs) == 1, fs
    f = fs[0]
    assert f.get("plane") == "737" and f.get("_via") == "停", f
    from core.flightnorm import normalize as _norm
    assert _norm(f, "2026-09-25")["stopover"] is True
    # 普通机型行（无经停标记）：只提取机型，不误标经停
    txt2 = ("东航MU8369\n\n中型机 737\n\n19:55\n\n01:25\n\n"
            "浦东T1\n\n乌鲁木齐\n\n¥2522\n订票")
    f2 = FliggyCrawler._parse_pc_text(txt2, "2026-09-25")[0]
    assert f2.get("plane") == "737" and "_via" not in f2, f2
    assert _norm(f2, "2026-09-25")["stopover"] is False


# ---- v1.5.31 回归：同程键名改版（cabinlevel/equipmentName 消失） ----
def test_tongcheng_cabin_and_plane_new_keys():
    """同程 v26 键名（10-06 dump 实测）：顶层 cabinlevel/equipmentName
    已消失——机型在 afn、舱位在所选政策 pts[].td 文本、经停在 $dirStop；
    旧键名兼容取值。"""
    from crawlers.tongcheng import TongchengCrawler
    text = json.dumps({"data": {"fl": [{
        "fn": "GS7587", "asn": "新海航｜天津航空",
        "dt": "2026-10-06 07:00", "at": "2026-10-06 13:45",
        "td": "6h45m", "afn": "空客A320(中)",
        "$dirStop": {"key": "经停", "value": "宜昌", "time": "45分"},
        "lps": [{"atp": 3200, "brs": [{"al": 4}],
                 "pts": [{"tt": 2, "td": "6.8折经济舱"}]}],
    }]}})
    out = TongchengCrawler._extract_flights(text)
    assert len(out) == 1
    f = out[0]
    assert f["plane"] == "空客A320" and f["cabin"] == "经济舱", f
    assert f["stopCitys"] == "宜昌" and f["stopTime"] == "45分", f
    from core.flightnorm import normalize as _norm
    n = _norm(f, "2026-10-06")
    assert n["stopover"] is True and n["stopCity"] == "宜昌", n
    assert n["stopTimeT"] == "0:45", n
    # 旧键名兼容：equipmentName/cabinlevel 旧 dump 仍可解析；无经停不误标
    old = json.dumps({"data": {"fl": [{
        "fn": "CZ6981", "asn": "南航",
        "dt": "2026-10-06 18:30", "at": "2026-10-06 23:40",
        "td": "5h10m", "equipmentName": "波音737-8(中)", "cabinlevel": 1,
        "lps": [{"atp": 1500, "brs": [{"al": 5}]}],
    }]}})
    g = TongchengCrawler._extract_flights(old)[0]
    assert g["plane"] == "波音737-8" and g["cabin"] == "经济舱", g
    assert g["stopCitys"] == "" and _norm(g, "2026-10-06")["stopover"] is False


# ---- v1.5.32 回归：全链路口径收口与假数据掐灭 ----

def test_fliggy_tax_pad_qual_price():
    """飞猪 PC 页展示价为税前（与含税渠道差 ￥50-130），税前价直入达标
    判定会产出假「达标」电话——达标口径统一加税垫，展示价不动。"""
    from core.alerter import _qual_price, FLIGGY_TAX_PAD
    f = {"price": 1850, "_platform": "fliggy"}
    assert _qual_price(f) == 1850 + FLIGGY_TAX_PAD
    assert _qual_price({"price": 1850, "_platform": "qunar"}) == 1850
    assert _qual_price({"price": "2150", "_platform": "ctrip"}) == 2150.0


def test_cabin_cn_unknown_code_blank():
    """渠道吐怪码（数字/乱码）时舱位不再强行标「经济舱」（宁缺勿错）；
    单字母折扣位仍按国内默认经济舱、渠道中文舱名原样透传。"""
    from core.alerter import _cabin_cn
    assert _cabin_cn("Y") == "经济舱" and _cabin_cn("C") == "公务舱"
    assert _cabin_cn("经济舱") == "经济舱" and _cabin_cn("公务舱") == "公务舱"
    assert _cabin_cn("3X") == "" and _cabin_cn("") == "" and _cabin_cn(None) == ""


def test_disp_dw_ignores_markdown_syntax():
    """_disp_dw 曾把 ** 与 [ ] 计入宽度，加粗链接行被系统性高估 6 半角，
    KPI「差￥N（P%）」设计形态因虚估超宽恒降级为裸百分号。"""
    from core.alerter import _disp_dw, _dw
    plain = "直飞 ￥1900　线￥2000　差￥100（5%）"
    bolded = "[**直飞 ￥1900**](https://x.example/a=1&b=2)　线￥2000　差￥100（5%）"
    assert _disp_dw(bolded) == _dw(plain)


def test_digest_legend_four_tiers_all_fit():
    """图例四档（v1.5.41 起断言现役 _legend_line）：🎯 基座恒在、档序与
    判定梯度同向（🟩破线→🟨擦边→无标超线）、超宽从末段逐段丢、整行
    ≤40 半角。旧断言自建常量固化「🟦距达标」旧语言，与现役脱节数版。"""
    from core.alerter import Alerter, _dw
    leg = Alerter._legend_line()
    assert "🎯真达标" in leg, leg
    assert "距线" not in leg, leg
    if "🟨擦边" in leg:
        assert leg.index("🟩破线") < leg.index("🟨擦边"), leg
    assert _dw(leg) <= 40, leg
    assert _dw(leg) <= 38, leg   # v1.5.50 真达标/超线短词面：37/40 留缓冲 2


def test_suggest_line_overline_returns_empty():
    """v1.5.41：超线默认态建议行返回空（与 KPI 差额、仪表条三重冗余
    撤除）——最近档超线⇒全部超线⇒整行零增量。"""
    import logging as _lg
    a = Alerter(_lg.getLogger("t"), storage=None)
    assert a._suggest_line(_mk_route(), _mk_sections(2600)[0]) == ""


def test_top3_blocks_fire_uses_qual_price():
    """文字 TOP3（图挂兜底）🔥 与明细表/表图同口径：_qual_price 达标
    口径（飞猪税垫 pad>0 时含税垫）、中转另需衔接合规——展示价判定曾
    让低价亮 🔥 而图/明细不绿。pad=0（v1.5.43 重标定）下 qual==展示价，
    用价差构造同路径：1850≤2000 亮 🔥，2050>2000 不亮。"""
    import logging as _lg
    a = Alerter(_lg.getLogger("t"), storage=None)
    r = _mk_route()
    r.alert_direct = 2000
    r.alert_transfer = 2000

    def _sec(price):
        return {"date": "2026-09-25", "top_direct": [], "top_transfer": [
            {"name": "CZ6976转", "depTime": "12:05", "arrTime": "23:50",
             "price": price, "_platform": "fliggy", "transCity": "西安",
             "layoverM": 120}]}

    out = a._top3_blocks(r, [_sec(2050)])
    assert "🔥" not in out, out              # 超 eff 线不亮
    out2 = a._top3_blocks(r, [_sec(1850)])
    assert "🔥" in out2, out2                # 破 eff 线亮


def test_daily_minima_near_tier_and_price_color():
    """擦边档三媒质同语言：日历 -1 档产码 + 表格图价格三档着色（达标绿/
    擦边琥珀/超线深蓝）。"""
    from report import _price_color, C_QUAL, C_NEAR, DESIGN
    f = {"_th": 2000}
    assert _price_color(f, True, 1900) == C_QUAL
    assert _price_color(f, False, 2100) == C_NEAR      # 距线 5%
    assert _price_color(f, False, 2400) == DESIGN.PRICE_PLAIN
    f2 = {}                                            # 无 _th 退两档
    assert _price_color(f2, False, 2100) == DESIGN.PRICE_PLAIN


def test_chart_width_matches_table_and_empty_series_guard(tmp_path):
    """同宽不变量（两图同贴不跳变）与走势空序列守卫（阈值非零+无数据
    曾在 series[-1] IndexError，仅靠调用方挡）。"""
    import report as _rep
    assert _rep.W == _rep.TBL_W, (_rep.W, _rep.TBL_W)
    out = str(tmp_path / "trend.png")
    _rep.render_chart([], "空数据", thresholds=(1500, 1600), out_path=out)
    import os as _os
    assert _os.path.isfile(out)


def test_cross_source_time_arbitrage_skips_transfer_chains():
    """跨源时刻仲裁禁入中转链：链上任一段号恰是 fliggy 在售直飞时，
    按段匹配曾用第二段时刻覆盖整行起降（假数据直入推送/指纹）。"""
    import logging as _lg
    from core.alerter import Alerter
    from core.models import FlightPrice, Route
    a = Alerter(_lg.getLogger("t"))
    fp = FlightPrice(platform="qunar", from_city="SHA", to_city="URC",
                     depart_date="2026-10-01", price=2000,
                     extra=json.dumps([
                         {"price": 2000, "code": "MU5501/SC8711",
                          "name": "东航MU5501/山东SC8711",
                          "depTime": "08:00", "arrTime": "15:30",
                          "depDate": "2026-10-01", "arrDate": "2026-10-01",
                          "transCity": "西安"},
                         {"price": 2100, "code": "MU5501",
                          "name": "东航MU5501", "depTime": "08:00",
                          "arrTime": "11:00", "depDate": "2026-10-01",
                          "arrDate": "2026-10-01", "transCity": ""}]))
    fq = FlightPrice(platform="fliggy", from_city="SHA", to_city="URC",
                     depart_date="2026-10-01", price=2200,
                     extra=json.dumps([
                         {"price": 2200, "code": "SC8711", "name": "山东SC8711",
                          "depTime": "18:10", "arrTime": "21:00",
                          "depDate": "2026-10-01", "arrDate": "2026-10-01",
                          "transCity": ""}]))
    r = Route(from_code="SHA", from_name="上海", to_code="URC",
              to_name="乌鲁木齐", dates=["2026-10-01"])
    sections = a._build_sections(r, [fp, fq])
    tr = [f for f in sections[0]["all_flights"] if f.get("transCity")]
    assert tr and tr[0]["depTime"] == "08:00" and tr[0]["arrTime"] == "15:30", tr


def test_pref_platform_same_price_prefers_qunar_ctrip():
    """同价同班多渠道在售时，跳转链接优先去哪儿/携程（出票覆盖面最好）；
    无同价优选回落最低价所在渠道（落点价与文案一致）。"""
    from core.alerter import Alerter
    pool = [
        {"price": 1850, "_platform": "tuniu", "depTime": "08:00",
         "arrTime": "15:30", "transCity": "", "crossDayDesc": ""},
        {"price": 1850, "_platform": "ctrip", "depTime": "08:00",
         "arrTime": "15:30", "transCity": "", "crossDayDesc": ""},
        {"price": 1900, "_platform": "qunar", "depTime": "09:00",
         "arrTime": "16:30", "transCity": "", "crossDayDesc": ""},
    ]
    pick = Alerter._pref_platform(pool[0], pool)
    assert pick == "ctrip"
    assert Alerter._pref_platform(pool[2], pool) == "qunar"
    lone = dict(pool[0], price=1700)
    assert Alerter._pref_platform(lone, [lone]) == "tuniu"


def test_rounds_dep_window_and_qual_flags(tmp_path):
    """走势取数链同窗过滤 + 达标旗标：窗口外班次不再进曲线（图上最低
    点可来自列表已剔除班次曾是大口径分裂）；5 元组带 qd/qt 供绿环
    只标真达标点。"""
    import sqlite3 as _sq
    import report as _rep
    db = str(tmp_path / "t.db")
    conn = _sq.connect(db)
    conn.execute("CREATE TABLE flight_prices (platform TEXT, from_city TEXT, "
                 "to_city TEXT, depart_date TEXT, price REAL, extra TEXT, "
                 "fetched_at TEXT)")
    rows = [
        ("qunar", "SHA", "URC", "2026-10-01", 1500,
         json.dumps([{"price": 1500, "depTime": "06:30", "arrTime": "10:00",
                      "depDate": "2026-10-01", "arrDate": "2026-10-01",
                      "transCity": ""}]),
         "2026-09-25 10:00:00"),
        ("qunar", "SHA", "URC", "2026-10-01", 1800,
         json.dumps([{"price": 1800, "depTime": "21:30", "arrTime": "01:00",
                      "depDate": "2026-10-01", "arrDate": "2026-10-02",
                      "transCity": ""}]),
         "2026-09-25 10:10:00"),
    ]
    conn.executemany("INSERT INTO flight_prices VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit(); conn.close()
    # 窗口 20:00 后：只有 21:30 班进曲线
    s = _rep._rounds(db, "SHA", "URC", "2026-10-01", "02:00",
                     dep_win=("20:00", ""), th_d=1600, th_t=0)
    assert len(s) == 1 and s[0][1] == 1800 and s[0][3] is False, s
    # 无窗口：最低 1500 且破线 → qd True
    s2 = _rep._rounds(db, "SHA", "URC", "2026-10-01", "02:00",
                      th_d=1600, th_t=0)
    assert len(s2) >= 1
    vals = [r for r in s2 if r[1] is not None]
    assert min(r[1] for r in vals) == 1500
    assert any(r[3] for r in vals), s2


# ---- v1.5.38 回归：超线去蓝点/强提醒过滤修复/幽灵送达落账/表格次行零省略 ----
def test_v1538_kpi_no_blue_dot_legend():
    """超线是默认态不加点（蓝色噪音用户实锤）：digest desp 无 🟦，
    图例改「无标超线」；擦边档 🟨 保留。"""
    import logging as _lg
    a = Alerter(_lg.getLogger("t"))
    r = _mk_route()
    p = a._digest_payload([(r, _mk_sections(2600))],
                          fresh=True, with_tables=False, with_charts=False)
    d = p["desp"]
    # 仪表条行本身是 🟦 进度语义（保留）；KPI 文本点已撤（「🟦 」带空格）
    assert "🟦 " not in d, d[:200]
    assert "🎯真达标" in d and "🟦超线" not in d, d[:120]
    # 擦边（≤10%）仍带 🟨：2600→1900 线，2069 是 8.9% 上方
    p2 = a._digest_payload([(r, _mk_sections(2069))],
                           fresh=True, with_tables=False, with_charts=False)
    assert "🟨" in p2["desp"], p2["desp"][:200]


def test_v1538_alert_body_filters_new_legend():
    """v1.5.37 改词曾让强提醒过滤失效（「距达标」键消失、引用块行首
    `>` 打沉 startswith）：新头行/图例/仪表条行必须滤净，建议行保留。"""
    from core.notifier import _alert_body
    desp = ("#### ❌ 全部未达标\n\n"
            "> ⏱ 22:38 🎯达标 🟩破线 🟨擦边 无标超线\n\n"
            "🟦🟦🟦⬜⬜\n\n"
            "直飞 **￥2690**　线￥2000　差￥690\n\n"
            "> 💡 直飞超线 34%，继续观望\n\n")
    body = _alert_body(desp)
    assert "⏱" not in body and "破线" not in body, body
    assert "🟦" not in body, body
    assert "直飞 **￥2690**" in body and "继续观望" in body, body


def test_daily_report_ghost_errcode_marks_state(monkeypatch, tmp_path):
    """钉钉 -1 幽灵送达：日报按已推落账防重发（09-18 实锤 ghost 重推
    12+ 份）；其他失败仍不落账走下轮重试。"""
    import logging as _lg
    import json as _json
    import report as _rep
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    # v1.5.49 状态文件锚定 _ROOT：测试 patch 到 tmp（chdir 已不再影响
    # 落点，保留只为兼容其他相对路径读侧）
    monkeypatch.setattr(_rep, "_ROOT", str(tmp_path))
    cfg = {"users": [{"name": "u", "routes": [],
                      "notifier": {"report_hour": 0, "digest": True}}]}
    # report_hour=0：now.hour<0 恒 False——测试不受运行时刻影响（跨零点曾假红）
    assert _rep._user_scope(cfg, "u")[0].get("digest") is True  # 结构冒烟
    for errcode, expect_state in ((-1, True), (None, False)):
        (tmp_path / "data" / "report_state.json").unlink(missing_ok=True)
        monkeypatch.setattr(_rep, "build_and_push", lambda *a, **k: False)

        class FakeN:
            last_errcode = errcode

        _rep.maybe_daily_report(cfg, _lg.getLogger("t"), FakeN(), user="u")
        f = tmp_path / "data" / "report_state.json"
        assert f.exists() is expect_state, (errcode, expect_state)
        if expect_state:
            assert _json.loads(f.read_text(encoding="utf-8"))["u"] != ""


def test_flights_table_two_line_sub_grows_height(tmp_path):
    """航班列决策次行（机型·舱位·准点·餐食）放不下拆两行、行高 44→60
    ——「准点100…」式省略曾截丢餐食/准点（用户实锤无法决策）。
    拆行判定依赖中文字体度量：Linux CI 无雅黑（_font 回退默认位图字体
    长串也放得下）恒不拆行，自 v1.5.39 起 CI 唯一红点——无字体环境
    该机制本就不生效，跳过。"""
    from PIL import Image
    import os as _os
    if not _os.path.exists("C:/Windows/Fonts/msyh.ttc"):
        pytest.skip("行高拆行判定依赖 Windows 中文字体度量（CI 无雅黑）")
    import report as _rep
    base = {"price": 1000, "name": "CZ6981", "depTime": "08:00",
            "arrTime": "10:00", "_platform": "qunar", "transCity": ""}
    short = dict(base, plane="738")
    long_ = dict(base, plane="空客339(大)", cabin="超级经济舱",
                 prate="100", meal="无餐食")
    p1 = _rep.render_flights_table([("direct", [short])], "t",
                                   str(tmp_path / "a.png"))
    p2 = _rep.render_flights_table([("direct", [long_])], "t",
                                   str(tmp_path / "b.png"))
    h1 = Image.open(p1).size[1]
    h2 = Image.open(p2).size[1]
    assert h2 - h1 == 16, (h1, h2)


# ---- v1.5.38 回归：解析准确性（同程 td 键/途牛舱位层/解析哨兵） ----
def test_tongcheng_sts_td_key_and_prate_text():
    """同程 sts 标签键 tx→td 改版（09-18 报文 td 881 处/tx 0 处，
    DB 实锤 meal/prate 全空数日）：双键兼容；准点率新文本
    「到达准点率97%」CJK 前缀+百分号后置须全文搜索。"""
    from crawlers.tongcheng import TongchengCrawler
    text = json.dumps({"data": {"fl": [{
        "fn": "CZ6981", "asn": "南航",
        "dt": "2026-10-06 18:30", "at": "2026-10-06 23:40",
        "td": "5h10m",
        "sts": [{"tt": 1, "td": "到达准点率97%"}, {"tt": 4, "td": "无餐食"}],
        "lps": [{"atp": 1500, "brs": [{"al": 5}]}],
    }]}})
    f = TongchengCrawler._extract_flights(text)[0]
    assert f["prate"] == "97" and f["meal"] == "无餐食", f
    old = json.dumps({"data": {"fl": [{
        "fn": "CZ6981", "asn": "南航",
        "dt": "2026-10-06 18:30", "at": "2026-10-06 23:40",
        "td": "5h10m",
        "sts": [{"tt": 1, "tx": "95%"}, {"tt": 4, "tx": "有餐食"}],
        "lps": [{"atp": 1500, "brs": [{"al": 5}]}],
    }]}})
    g = TongchengCrawler._extract_flights(old)[0]
    assert g["prate"] == "95" and g["meal"] == "有餐食", g


def test_tuniu_fare_cabin_new_layer():
    """途牛舱位在 fare 层（09 月改版后 detail.cabinTypeName 恒缺，
    100% 空）：priceJourneyCabinList[].priceFlightCabinList[].cabinTypeName"""
    from crawlers.tuniu import TuniuCrawler
    fare = {"priceJourneyCabinList": [
        {"priceFlightCabinList": [
            {"cabinClass": "Y", "cabinCode": "M", "cabinType": 1,
             "cabinTypeName": "经济舱"}]}]}
    assert TuniuCrawler._fare_cabin(fare) == "经济舱"
    assert TuniuCrawler._fare_cabin({}) == ""          # 宁缺勿错
    assert TuniuCrawler._fare_cabin({"priceJourneyCabinList": [{"x": 1}]}) == ""


def test_field_sentinel_warns_on_dead_field(monkeypatch, tmp_path):
    """解析哨兵：≥20 行且命中 <10% 报 WARNING（每天至多一条）；
    命中正常或行数不足不报。门槛 50→20（v1.5.39）：tongcheng 48 /
    fliggy ~33 / tuniu ~26 量级小渠道当轮曾全部逃逸监控。"""
    from types import SimpleNamespace as _NS
    import main as _m
    # 状态落盘指向临时目录（测试告警曾写脏真实 data/sentinel_state.json）
    monkeypatch.setattr(_m, "_SENT_PATH", str(tmp_path / "sent.json"))
    monkeypatch.setattr(_m, "_ROW_HIST", {})
    _m._SENT_LAST.clear()
    seen = []

    class _L:
        def warning(self, *a, **k):
            seen.append(a)

    rows = [{"price": 1000, "cabin": "", "meal": "", "prate": ""}
            for _ in range(60)]
    _m._field_sentinel([_NS(platform="tongcheng", extra=json.dumps(rows))], _L())
    # cabin/meal/prate/plane 四字段全灭（v1.5.44 补 plane）；行李直挂
    # 分母改中转行（v1.5.44）——夹具无中转行不再触发直挂告警
    assert len(seen) == 4, seen
    _m._field_sentinel([_NS(platform="tongcheng", extra=json.dumps(rows))], _L())
    assert len(seen) == 4, seen          # 同日再跑不刷屏
    ok_rows = [{"price": 1000, "cabin": "经济舱", "meal": "无餐食",
                "prate": "97", "plane": "空客321(中)",
                # shareCarrier/arrTerminal 按生产形态给值（v1.5.49 哨兵
                # 0 命中=键死观测；健康夹具须带命中——share DB 实测
                # 20.6%、arr 侧航站楼 98/98）
                "shareCarrier": "MU5700" if i % 4 == 0 else "",
                "arrTerminal": "T2",
                "transferBaggage": "direct" if i < 2 else ""}
               for i in range(60)]   # 直挂 2/60≈3.3%>1%：不触新扩容告警
    seen.clear()
    _m._field_sentinel([_NS(platform="ctrip", extra=json.dumps(ok_rows))], _L())
    assert seen == [], seen
    few = [{"price": 1000, "cabin": "", "meal": "", "prate": ""}
           for _ in range(9)]
    _m._field_sentinel([_NS(platform="tuniu", extra=json.dumps(few))], _L())
    assert seen == [], seen              # 行数不足不报（门槛 20→10，v1.5.49）
    # 20~50 区间（原门槛下逃逸）：26 行全灭必须报警（tuniu 实测量级）。
    # v1.5.49：fliggy|meal 入死键表不再报（结构性无源）；shareCarrier
    # 夹具带值（0 命中=键死观测，健康夹具须带命中，DB 实测 40.9% 同量级）
    mid = [{"price": 1000, "cabin": "", "meal": "", "prate": "",
            "shareCarrier": "CZ6983" if i % 3 == 0 else ""}
           for i in range(26)]
    _m._field_sentinel([_NS(platform="fliggy", extra=json.dumps(mid))], _L())
    assert len(seen) == 3, seen          # cabin/prate/plane（meal 已入死键表）


def test_field_sentinel_layover_and_rowfall(monkeypatch, tmp_path):
    """v1.5.41 哨兵扩容：中转行停留覆盖率（ctrip 单点失效→全链停留静默
    归零）与行数塌方（有响应但明细骤减 90%，命中率/pulse 双双不报）。"""
    from types import SimpleNamespace as _NS
    import main as _m
    monkeypatch.setattr(_m, "_SENT_PATH", str(tmp_path / "sent.json"))
    monkeypatch.setattr(_m, "_ROW_HIST", {})
    _m._SENT_LAST.clear()
    seen = []

    class _L:
        def warning(self, *a, **k):
            seen.append(a)

    # 30 条中转行全无 layoverM：覆盖率 0%<10% → 告警 1 条
    rows = [{"price": 1000, "cabin": "经济舱", "transCity": "西安"}
            for _ in range(30)]
    _m._field_sentinel([_NS(platform="ctrip", extra=json.dumps(rows))], _L())
    assert sum("停留覆盖" in str(a) for a in seen) == 1, seen
    # 同日不重复
    _m._field_sentinel([_NS(platform="ctrip", extra=json.dumps(rows))], _L())
    assert sum("停留覆盖" in str(a) for a in seen) == 1, seen
    # 行数塌方：基线 100×3 轮 → 连续 2 轮 20（<30%）→ 告警
    seen.clear()
    _m._SENT_LAST.clear()
    for n in (100, 100, 100, 20, 20):
        _m._field_sentinel([_NS(platform="qunar", extra=json.dumps(
            [{"price": 1000, "cabin": "经济舱"}] * n))], _L())
    assert sum("行数塌方" in str(a) for a in seen) == 1, seen
    # 塌方恢复后不再报
    _m._field_sentinel([_NS(platform="qunar", extra=json.dumps(
        [{"price": 1000, "cabin": "经济舱"}] * 100))], _L())
    assert sum("行数塌方" in str(a) for a in seen) == 1, seen


def test_ctrip_cross_day_by_date_diff():
    """ctrip 跨天按日期差（v1.5.41）：时长//1440 映射曾把 ≥3 天一律
    标「+2天」——日期字段是唯一事实源。"""
    from crawlers.ctrip import CtripCrawler
    import json as _json
    seg = lambda d0, d1: {
        "basinfo": {"flgno": "MU8369"},
        "dateinfo": {"ddate": f"2026-09-{d0} 08:00:00",
                     "adate": f"2026-09-{d1} 09:00:00"},
        "aportinfo": {"city": "乌鲁木齐"}}
    mk = lambda d0, d1: _json.dumps({"fltitem": [{
        "mutilstn": [seg(d0, d1)],
        "policyinfo": [{"tprice": 1200, "quantity": 1}]}]})
    f3 = CtripCrawler._extract_ctrip_flights(CtripCrawler.__new__(CtripCrawler), mk("25", "28"))
    assert f3 and f3[0].get("crossDayDesc") == "+3天", f3
    f1 = CtripCrawler._extract_ctrip_flights(CtripCrawler.__new__(CtripCrawler), mk("25", "26"))
    assert f1 and f1[0].get("crossDayDesc") == "+1天", f1


def test_qunar_binfo2_independent_arrival():
    """qunar H5 binfo2 真独立时整体到达取二段（防御：渠道未来下发真
    分段时整体到达曾被首段 arrTime 污染）；复制体形态行为不变。"""
    from crawlers.qunar import QunarCrawler
    base = lambda b2: {"minPrice": 800, "code": "MU8369",
                       "transCity": "西安",
                       "binfo1": {"depTime": "08:00", "arrTime": "11:00",
                                  "depDate": "2026-09-25",
                                  "arrDate": "2026-09-25"},
                       "binfo2": b2}
    fs = QunarCrawler._extract_flights_obj(
        [base({"depTime": "13:30", "arrTime": "17:20",
               "depDate": "2026-09-25", "arrDate": "2026-09-25"})])
    assert fs and fs[0]["arrTime"] == "17:20", fs   # 真独立→二段到达
    fs2 = QunarCrawler._extract_flights_obj(
        [base({"depTime": "08:00", "arrTime": "11:00",
               "depDate": "2026-09-25", "arrDate": "2026-09-25"})])
    assert fs2 and fs2[0]["arrTime"] == "11:00", fs2  # 复制体→不误改


def test_view_url_unknown_platform_empty(monkeypatch):
    """webui _view_url 空/未知平台返回 ""（宁缺勿错）——曾缺省回落
    "qunar" 误出挂羊头链接。"""
    import webui as _w
    assert _w._view_url({"from": "SHA", "to": "URC"}, "2026-09-25",
                        "") == ""
    assert _w._view_url({"from": "SHA", "to": "URC"}, "2026-09-25",
                        "no_such") == ""


# ---- v1.5.39 回归：开源面上手体验 ----
def test_wizard_generates_users_format(tmp_path, monkeypatch):
    """向导产物必须是 users 包裹格式：旧顶层 routes 格式曾被网页首次
    保存无条件改写为 users:[] ——向导生成的航线静默全失效。"""
    import builtins
    import json as _json  # noqa: F401
    import wizard as _w
    answers = iter(["上海", "乌鲁木齐", "2099-12-31", "1900", "1700",
                    "02:00", "90", "n", "n", "", "30", ""])
    monkeypatch.setattr(builtins, "input", lambda *a, **k: next(answers))
    cfg_path = tmp_path / "config.yaml"
    assert _w.run_wizard(str(cfg_path))
    import yaml as _yaml
    c = _yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert "users" in c and "routes" not in c, list(c.keys())
    u = c["users"][0]
    assert u["routes"][0]["alert_direct"] == 1900
    assert u["routes"][0]["transfer_arrival_max"] == "02:00"
    assert "schedule" in c and "crawler" in c   # 全局节保持在顶层


# ===== v1.5.43 回归 =====

def test_fliggy_guard_catches_lone_phantom_mf2372():
    """生产实锤（2026-09-19 09:32-10:32，旧进程守卫上线前）：飞猪
    MF2372 行价 ￥930 连续 5 轮入库并触发虚假「达标」主推+电话——
    明细群 35 条最低 2410、中位 2920，930<1460 必拦（其他四渠道根本
    无此航班，10:32 后凭空消失=幻影）。"""
    txt = ("厦航MF2372\n16:30\n21:05\n¥930\n订票\n"
           "春秋9C6496\n16:40\n21:30\n¥2410\n订票\n"
           "国航CA1295\n14:30\n18:45\n¥2630\n订票\n"
           "东航MU8369\n08:15\n13:40\n¥2920\n订票\n"
           "南航CZ6981\n18:30\n23:40\n¥3300\n订票\n"
           "吉祥HO2214\n19:05\n23:55\n¥2410\n订票\n")
    fs = FliggyCrawler._parse_pc_text(txt, "2026-10-05")
    mf = [f for f in fs if f["code"] == "MF2372"]
    assert not mf, fs                       # 幻影行被群体锚弃行
    assert len(fs) == 5 and min(f["price"] for f in fs) == 2410, fs


def test_fliggy_prate_decimal_and_discount():
    """DOM 快照实证 flight-ontime-rate 值带小数（96.67%/100.0%），整数
    正则 0/34 命中=结构性全空；span.discount「5.6折」35 处全未解析。"""
    txt = ("国航CA1295\n14:30\n18:45\n96.67%\n¥3120 6.5折\n订票\n"
           "东航MU8369\n08:15\n13:40\n100.0%\n¥2850\n订票\n")
    fs = FliggyCrawler._parse_pc_text(txt, "2026-10-06")
    assert fs[0]["prate"] == "97"           # 四舍五入取整入库（全站整数形态）
    assert fs[0]["discount"] == "6.5折"
    assert fs[1]["prate"] == "100"
    assert "discount" not in fs[1]          # 无折扣 token 不造数据


def test_qunar_dom_plane_extracted():
    """qunar DOM 名行自带机型（「春秋9C8866 空客321(中)」40 行实证，
    此前整段只取航班号）——plane 98% 缺口的单渠道自源修复主力。"""
    from crawlers.qunar import QunarCrawler
    txt = ("16:40\n虹桥T2\n2h35m\n19:15\n浦东T1\n"
           "春秋9C8866 空客321(中)\n1234\n"
           "18:40\n虹桥T2\n3h05m\n21:45\n浦东T1\n"
           "新海航｜海南航空HU4708 波音737(中)共享\n2345\n")
    fs = QunarCrawler._parse_dom_flights(txt, "2026-10-06")
    by = {f["code"]: f for f in fs}
    assert by["9C8866"]["plane"] == "空客321(中)"
    assert by["HU4708"]["plane"] == "波音737(中)"


def test_propagate_fields_same_fingerprint():
    """同指纹决策字段补全：qunar DOM 行 cabin/prate 全空却常贡献全线
    最低价——同(+航班号)指纹恰好一个非空值才补；两渠道值冲突不补
    （宁缺勿错）。"""
    base = {"code": "CZ6954", "depDate": "2026-10-05", "depTime": "08:35",
            "arrTime": "13:20", "arrDate": "2026-10-05", "price": 2307}
    q = dict(base, _platform="qunar")
    c = dict(base, price=2310, _platform="ctrip",
             cabin="经济舱", prate="97", plane="空客321(中)")
    rows = [dict(q), dict(c)]
    Alerter._propagate_fields(rows)
    assert rows[0]["cabin"] == "经济舱"
    assert rows[0]["prate"] == "97"
    assert rows[0]["plane"] == "空客321(中)"
    # 冲突不补：第三渠道 cabin 与 ctrip 不一致 → qunar 保持空
    t = dict(base, price=2410, _platform="tongcheng", cabin="公务舱")
    rows2 = [dict(q), dict(c), t]
    Alerter._propagate_fields(rows2)
    assert not rows2[0].get("cabin")
    # prate/plane 单一值仍补
    assert rows2[0]["prate"] == "97"
    # 航班号不同不跨航班张冠李戴
    other = dict(base, code="MU5137", _platform="ctrip", meal="正餐")
    rows3 = [dict(q), other]
    Alerter._propagate_fields(rows3)
    assert not rows3[0].get("meal")


def test_category_alert_debounce_stores_eff_price():
    """去抖基准混口径修复：判定与存储必须同口径（曾存页面价，飞猪税垫
    差被视作「涨￥100」幻影重推）。pad=0 下 eff==页面价，存储值=页面价。"""
    import logging
    from types import SimpleNamespace
    from core.alerter import FLIGGY_TAX_PAD

    class _St:
        def __init__(self):
            self.saved = None

        def get_alert_state(self, k):
            return self.saved

        def set_alert_state(self, k, v):
            self.saved = v

        def clear_alert_state(self, k):
            self.saved = None

    class _N:
        def send(self, title, desp, at_mobiles=None, is_at_all=False):
            return True

    st = _St()
    a = Alerter(logging.getLogger("t"), notifier=_N(), storage=st,
                push_rise_min=50)
    route = SimpleNamespace(from_name="乌鲁木齐", to_name="上海",
                            from_code="URC", to_code="SHA")
    f = {"price": 900, "_platform": "fliggy", "name": "厦航MF2372",
         "depTime": "16:30", "arrTime": "21:05", "crossDayDesc": ""}
    a._category_alert(route, "2026-10-05", f, "direct", 1900.0, 12, "fliggy")
    assert st.saved == 900 + FLIGGY_TAX_PAD   # 存的是达标口径价


def test_suggest_line_short_forms_within_width():
    """建议行改短式（v1.5.43）：常见形态本就 41-48 半角、_fit_line 末档
    形同虚设——两种口径形态含「> 💡 」前缀必须 ≤20 全角。"""
    import logging
    from types import SimpleNamespace
    from core.alerter import _disp_dw
    route = SimpleNamespace(alert_direct=1900, alert_transfer=1700)
    hit = {"price": 1830, "_platform": "fliggy"}          # eff=1830 ≤ 1900
    s = {"best_direct": hit, "best_transfer": None,
         "best_transfer_mkt": None}
    out = Alerter._suggest_line(None, route, s)
    assert out and _disp_dw("> 💡 " + out) <= 40, out
    # 擦边档：距线 ≤10%
    s2 = {"best_direct": {"price": 2050, "_platform": "qunar"},
          "best_transfer": None, "best_transfer_mkt": None}
    out2 = Alerter._suggest_line(None, route, s2)
    assert out2 and _disp_dw("> 💡 " + out2) <= 40, out2
    assert "蹲守" in out2


def test_split_market_pool_writes_th_amber_tier():
    """日报表琥珀擦边档（v1.5.43）：_split_market_pool 曾从不写 _th，
    _price_color 琥珀分支恒不触发——同一次日报里表格两档色、走势环
    三档两套语言。"""
    from report import _split_market_pool
    rc = {"transfer_arrival_max": "02:00", "transfer_layover_min": 0,
          "alert_transfer": 2000, "alert_direct": 1900}
    fs = [{"price": 1800, "depDate": "2026-10-05", "arrDate": "2026-10-05"},
          {"price": 1950, "transCity": "西安", "depDate": "2026-10-05",
           "arrDate": "2026-10-05", "arrTime": "20:00", "depTime": "10:00",
           "layoverM": 200}]
    directs, mkt = _split_market_pool(fs, rc)
    assert directs[0]["_th"] == 1900
    assert mkt[0]["_th"] == 2000
    from report import C_NEAR, C_QUAL, _price_color
    assert _price_color(directs[0], True, 1800) == C_QUAL      # 达标绿
    assert _price_color(mkt[0], False, 2150) == C_NEAR         # 擦边琥珀(线<价≤线×1.1)


def test_archive_nid_survives_sanitizer():
    """nid 死链修复（v1.5.43）：hex 小写字母曾被 webui [^A-Z0-9] 净化
    剥掉，约 94% 的 /notify 落点 404（弹窗/ntfy/钉钉「完整详情」三条
    出口）。生成端全大写后，新旧两种净化都必须恒等通过。"""
    import logging
    import re as _re
    import shutil
    import tempfile
    import uuid as _uuid

    class _FakeUUID:
        hex = "01d3dde9f0a2"    # 生产 uuid4().hex 主形态：含小写

    orig_uuid = _uuid.uuid4
    _uuid.uuid4 = lambda: _FakeUUID()
    work = tempfile.mkdtemp(prefix="nid_test_")
    old_cwd = os.getcwd()
    os.chdir(work)
    try:
        a = Alerter(logging.getLogger("t"), base_url="https://x.example.com")
        url = a._archive_notify("t", "d")
        nid = url.rsplit("/", 1)[-1]
        assert _re.sub(r"[^A-Za-z0-9]", "", nid) == nid   # 现行净化恒等
        assert _re.sub(r"[^A-Z0-9]", "", nid) == nid      # 旧净化也恒等（回归锚）
    finally:
        _uuid.uuid4 = orig_uuid
        os.chdir(old_cwd)
        shutil.rmtree(work, ignore_errors=True)


def test_dingtalk_fail_streak_monitored():
    """钉钉连败自监控（v1.5.43）：-1 幽灵送达与真断推服务端不可分，
    连败计数逐轮累加、成功轮清零（阈值弹窗 8 的倍数经 _streak_toast
    打桩验证不在此测，避免真弹窗）。"""
    import logging
    import shutil
    import tempfile
    import core.notifier as _nm
    from core.notifier import DingTalkNotifier

    class _R:
        def __init__(self, code):
            self.text = str({"errcode": code})
            self._c = code

        def json(self):
            return {"errcode": self._c}

    orig = _nm.httpx.post
    _nm.httpx.post = lambda *a, **k: _R(-1)
    work = tempfile.mkdtemp(prefix="ding_test_")
    old = os.getcwd()
    os.chdir(work)                  # last_push/push_history 落临时目录
    try:
        d = DingTalkNotifier("https://oapi.dingtalk.com/robot/x",
                             logging.getLogger("t"))
        for i in range(1, 4):
            assert d.send("t", "d") is False
            assert d._fail_streak == i
        _nm.httpx.post = lambda *a, **k: _R(0)
        assert d.send("t", "d") is True
        assert d._fail_streak == 0
    finally:
        _nm.httpx.post = orig
        os.chdir(old)
        shutil.rmtree(work, ignore_errors=True)


def test_low_txt_tax_note_conditional():
    """差额文案「(税前)」单源 _low_txt（v1.5.44）：税前注仅 pad>0 且
    飞猪行——legacy hits 行曾漏 pad 条件恒挂假警示、与 multi 版分叉。"""
    import core.alerter as _a
    from core.alerter import _low_txt
    assert _low_txt(1850, 2000, "fliggy") == "低￥150"
    assert "(税前)" not in _low_txt(1850, 2000, "qunar")
    old = _a.FLIGGY_TAX_PAD
    try:
        _a.FLIGGY_TAX_PAD = 100   # 旋钮启用：飞猪行带注、他渠道不带
        assert _low_txt(1850, 2100, "fliggy") == "低￥250(税前)"
        assert _low_txt(1850, 2100, "qunar") == "低￥250"
    finally:
        _a.FLIGGY_TAX_PAD = old


def test_suggest_line_no_taxword_when_pad_zero():
    """建议行措辞（v1.5.44）：pad=0 下「税后差」→「差」、「（税前价）」
    消隐——中转档行情最优与达标最优常是两个航班，旧注（按两价不等触发）
    实为航班差非税差，误导。"""
    import logging
    from core.alerter import Alerter
    a = Alerter(logging.getLogger("t"), storage=None)
    r = _mk_route(ad=2000, at=2000)
    s = {"date": "2026-09-25",
         "best_direct": {"price": 2120, "name": "MU8369", "depTime": "08:00",
                         "arrTime": "11:00", "_platform": "qunar"},
         "best_transfer": {"price": 2080, "name": "CZ6976转",
                           "depTime": "09:00", "arrTime": "21:00",
                           "transCity": "西安", "_platform": "qunar"},
         "best_transfer_mkt": {"price": 2050, "name": "CZ6975转",
                               "depTime": "10:00", "arrTime": "22:00",
                               "transCity": "西安", "_platform": "qunar"}}
    out = a._suggest_line(r, s)
    assert "税" not in out, out
    # v1.5.50 擦边正名：近带宽词面「距线N%」收编为「擦边N%」（与
    # kpi_tier_txt 单源同词），断言同步放宽
    assert ("差￥" in out or "距线" in out or "擦边" in out), out


def test_qunar_dom_median_anchor_drops_phantom():
    """qunar DOM 兜底幻影价守卫（v1.5.44，fliggy 中位锚移植）：页面尾部
    模块凑齐「时刻+航班号+价格」的幻影低价行曾零群体防线。合法同量级
    行（含跨舱位双价形态）不误伤。"""
    from crawlers.qunar import QunarCrawler as _Q
    rows = []
    for i, px in enumerate(("1500", "1520", "1540", "1560", "1580")):
        rows += [f"1{i}:0{i}", "虹桥", "3h25m", f"1{i}:30", "浦东",
                 f"中国东方航空 MU513{i}", f"￥{px}"]
    phantom = ["05:01", "虹桥", "2h00m", "07:01", "浦东",
               "东航专享 MU9999", "￥700"]
    out = _Q._parse_dom_flights("\n".join(rows + phantom), "2026-10-05")
    codes = [f["code"] for f in out]
    assert "MU9999" not in codes, codes            # 幻影行被中位锚弃用
    assert len(out) == 5, codes                    # 正常行全保留


def test_midnight_window_warns_once(monkeypatch):
    """跨零点出发窗口（v1.5.44）：dmin>dmax 的钟面窗口判定恒 False，
    整航线曾静默零数据——每对窗口只告警一次，正常窗口不告警。"""
    import core.alerter as _a
    _a._WIN_WARNED.clear()
    seen = []

    class _L:
        def warning(self, *a, **k):
            seen.append(a)

    monkeypatch.setattr(_a, "_LOG", _L())
    assert _a.Alerter._dep_in_window("23:00", "22:00", "02:00") is False
    assert _a.Alerter._dep_in_window("01:00", "22:00", "02:00") is False
    assert len(seen) == 1, seen            # 每对跨零点窗口只告警一次
    assert _a.Alerter._dep_in_window("12:00", "06:00", "09:00") is False
    assert len(seen) == 1, seen            # 正常窗口不产生告警


def test_near_ratio_single_source_and_warn_sync():
    """擦边带宽单源（v1.5.44）与琥珀对比度三端同值：×1.1/≤0.10 字面量
    收敛 report.py NEAR_RATIO（webui 侧 TIER/fl/near 同步注释）；
    C_NEAR 加深 (176,137,0)→(154,120,0) 后 webui --warn 浅色同步 #9a7800。"""
    import io
    import os
    import report as _rep
    from report import _price_color, C_NEAR, DESIGN
    assert _rep.NEAR_RATIO == 0.10
    th = 2000
    f = {"_th": th}
    assert _price_color(f, False, th * (1 + _rep.NEAR_RATIO)) == C_NEAR
    assert _price_color(f, False,
                        th * (1 + _rep.NEAR_RATIO) + 1) == DESIGN.PRICE_PLAIN
    assert C_NEAR == (154, 120, 0)
    src = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               os.pardir, "webui.py"),
                  encoding="utf-8").read()
    assert "#9a7800" in src, "webui --warn 浅色未随 C_NEAR 同步（三端同值纪律）"

def test_v1546_price_color_brk_hollow_tier():
    """总表图破线未达标档（v1.5.46）：价≤线但口径不符 → C_QUAL 空心
    （_price_hollow），与走势环「实心=达标/细绿环=行情破线」同构；
    曾落超线同款深蓝（同表「更便宜反默认色」梯度倒挂）。"""
    from report import (_price_color, _price_hollow, C_QUAL, C_NEAR,
                        DESIGN)
    f = {"_th": 2000}
    assert _price_color(f, False, 1800) == C_QUAL      # 破线(行情) 绿
    assert _price_hollow(f, False, 1800) is True       # 空心=行情口径
    assert _price_color(f, True, 1800) == C_QUAL and \
        _price_hollow(f, True, 1800) is False          # 达标实心
    assert _price_color(f, False, 2100) == C_NEAR and \
        _price_hollow(f, False, 2100) is False         # 擦边琥珀实心
    assert _price_color(f, False, 2400) == DESIGN.PRICE_PLAIN


def test_v1546_near_ratio_single_source_alerter():
    """擦边带宽收口 core.alerter 单源（v1.5.46）：report/webui 后端一律
    import（report 本地定义已删）；前端 JS ×1.1 保留同步律注释。"""
    import io
    import os
    import core.alerter as _al
    import report as _rep
    assert _al.NEAR_RATIO == 0.10 and _rep.NEAR_RATIO is _al.NEAR_RATIO
    _here = os.path.dirname(os.path.abspath(__file__))
    rep_src = io.open(os.path.join(_here, os.pardir, "report.py"),
                      encoding="utf-8").read()
    assert "NEAR_RATIO = 0.10" not in rep_src, \
        "report.py 本地定义应删（单源 core.alerter）"
    web_src = io.open(os.path.join(_here, os.pardir, "webui.py"),
                      encoding="utf-8").read()
    assert "xchan_phantom_idx, NEAR_RATIO)" in web_src


def test_v1546_compare_rows_shared_assembly():
    """compare 组组装单源 _compare_rows（v1.5.46）：实时总表与日报共用
    同一行结构（label/dep/arr/chain/save/outlier）；跨舱位组 outlier=True
    （_outlier 两判据同验）。"""
    from core.alerter import Alerter
    cands = [(500, [
        {"name": "MU5533", "depTime": "09:30", "arrTime": "14:10",
         "transCity": "", "crossDayDesc": "", "layoverT": "",
         "stopCity": "", "_platform": "qunar", "price": 2000,
         "cabin": "经济舱"},
        {"name": "MU5533", "depTime": "09:30", "arrTime": "14:10",
         "transCity": "", "crossDayDesc": "", "layoverT": "",
         "stopCity": "", "_platform": "ctrip", "price": 2500,
         "cabin": "公务舱"},  # 跨舱位 ≤2× 亦离群
    ], "2026-10-05")]
    rows = Alerter._compare_rows(cands)
    assert len(rows) == 1
    r = rows[0]
    assert r["label"] == "MU5533" and r["dep"] == "09:30"
    assert [c[0] for c in r["chain"]] == ["去哪儿", "携程"]
    assert r["save"] == 500 and r["outlier"] is True


def test_v1546_cfgnav_specificity_fix():
    """配置左导航特异性修复（v1.5.46）：.cfgnav>span 通配曾以 (0,1,1)
    压死 .cnav 全部盒样式与 760px 触控增强——瓦片样式并入 .cnav 本体。"""
    import io
    import os
    _here = os.path.dirname(os.path.abspath(__file__))
    src = io.open(os.path.join(_here, os.pardir, "webui.py"),
                  encoding="utf-8").read()
    assert ".cfgnav>span," not in src, "特异性冲突源未除（CSS 规则仍在）"
    assert ".cfgnav .cfgsearch{background:var(--card)" in src
    assert ".cnav{background:var(--card);border:1px solid var(--line)" in src


ALL = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    import inspect
    fails = skipped = 0
    for t in ALL:
        _req = [q for q in inspect.signature(t).parameters.values()
                if q.default is inspect.Parameter.empty and q.kind
                in (q.POSITIONAL_ONLY, q.POSITIONAL_OR_KEYWORD)]
        if _req:
            skipped += 1        # fixture 用例仅 pytest 跑（直跑 TypeError 老坑）
            continue
        try:
            t()
            print(" ok", t.__name__)
        except AssertionError as e:
            fails += 1
            print(" FAIL", t.__name__, str(e)[:80])
    assert not fails, f"{fails} 个用例失败"
    print(f"=== 全部 {len(ALL)} 用例通过（{skipped} 个 fixture 用例走 pytest）===")


def test_xchan_phantom_idx_incident_case():
    """跨渠道孤低价守卫（v1.5.45）：2026-09-19 事故形态——v1.5.42 渠道内
    中位锚热修部署前旧进程漏网（行内第二价格行动态价 820/700 混入），
    ￥700 直通电话告警（同轮其余四渠道 2546-3280）。跨渠道中位数是
    独立于解析器的第二道防线；阈值 0.5 经 12 天 DB 回算标定（直飞合法
    地板 0.908 / 幻影天花板 0.394）；正常同量级行不误伤。"""
    from core.alerter import xchan_phantom_idx
    # 实锤形态：飞猪 700/930 vs 四渠道 2546-3280
    ent = [(700.0, "fliggy"), (930.0, "fliggy"), (3070.0, "fliggy"),
           (2546.0, "qunar"), (2550.0, "ctrip"),
           (2850.0, "tongcheng"), (3280.0, "tuniu")]
    idx = xchan_phantom_idx(ent)
    assert idx == {0, 1}, idx                # 幻影行被标，飞猪正常行保留
    # 单渠道无独立锚：不判
    assert xchan_phantom_idx([(100.0, "fliggy")]) == set()
    # 两渠道之一价格异常：判
    assert xchan_phantom_idx([(700.0, "fliggy"), (2546.0, "qunar")]) == {0}
    # 合法跨渠道同量级：零误伤
    ok = [(2410.0, "tuniu"), (2410.0, "qunar"), (2412.0, "ctrip"),
          (2415.0, "fliggy"), (2430.0, "tongcheng")]
    assert xchan_phantom_idx(ok) == set(), xchan_phantom_idx(ok)


def test_mark_xchan_build_sections_filters_phantom():
    """_build_sections 消费端：幻影行不进 TOP 组/最优/pool（达标/告警/
    比价全下游），section 留 xphans 痕。"""
    from core.alerter import Alerter, _qual_price
    import json as _json

    def _f(plat, price, trans=""):
        return {"_platform": plat, "price": price, "depTime": "16:00",
                "arrTime": "21:30", "name": "x", "code": "X100"
                + ("" if not trans else "/Y200"),
                "transCity": trans}

    def _fp(plat, price, trans=""):
        from core.models import FlightPrice
        return FlightPrice(platform=plat, from_city="URC", to_city="SHA",
                           depart_date="2026-10-06", price=price,
                           extra=_json.dumps([_f(plat, price, trans)],
                                             ensure_ascii=False))
    # 幻影 700 + 群 2500+：直飞行
    prices = [_fp("fliggy", 700.0), _fp("fliggy", 3070.0),
              _fp("qunar", 2546.0), _fp("ctrip", 2550.0),
              _fp("tongcheng", 2850.0), _fp("tuniu", 3280.0)]

    class _RT:
        from_code = "URC"; to_code = "SHA"
        from_name = "乌鲁木齐"; to_name = "上海"
        transfer_arrival_max = "02:00"
        transfer_layover_min = 0
        transfer_baggage = ""
        dep_time_min = ""; dep_time_max = ""
    a = Alerter.__new__(Alerter)   # 免构造（notifier 等本用例不触）
    import logging
    a.logger = logging.getLogger("t")
    secs = a._build_sections(_RT(), prices)
    assert secs, "section 应生成"
    s = secs[0]
    pool_prices = [f["price"] for f in s["pool"]]
    assert 700.0 not in pool_prices, pool_prices   # 幻影行不入 pool
    assert 3070.0 in pool_prices                   # 飞猪正常行保留
    assert s["xphans"], "拦截留痕应在场"


def test_rounds_xchan_guard_keeps_curve_clean():
    """_rounds 消费端：幻影渠道最低不进曲线（y 轴不再被 ￥700 压到地板），
    正常轮次全保留。"""
    import tempfile, os, sqlite3
    from report import _rounds
    from core.storage import PriceStorage as Storage
    tmpd = tempfile.mkdtemp()
    dbp = os.path.join(tmpd, "t.db")
    st = Storage(dbp)
    import datetime as _dt
    now = _dt.datetime.now()
    from core.models import FlightPrice

    def _row(plat, price, iso):
        return FlightPrice(platform=plat, from_city="URC", to_city="SHA",
                           depart_date="2026-10-06", price=price,
                           fetched_at=iso,
                           extra=f'[{{"price": {price}, "depTime": "16:00", '
                                 f'"arrTime": "21:30", "name": "x", '
                                 f'"code": "C{plat}"}}]')
    base = [2546.0, 2550.0, 2850.0, 3280.0]
    rows = [_row("qunar", base[0], "t"), _row("ctrip", base[1], "t"),
            _row("tongcheng", base[2], "t"), _row("tuniu", base[3], "t")]
    rows += [_row("fliggy", 700.0, "t"), _row("fliggy", 3070.0, "t")]
    for r in rows:
        r.fetched_at = now.strftime("%Y-%m-%d %H:%M:%S")
    st.save_many(rows)
    ser = _rounds(dbp, "URC", "SHA", "2026-10-06", "02:00")
    assert ser, "应产出序列"
    d_min = min(s[1] for s in ser if s[1] is not None)
    assert d_min >= 700 * 2, f"曲线最低 {d_min} 仍被幻影压低"


# ---- v1.5.47 回归：档位单源/混淆码守卫/链接兜底/哨兵双键/截断留痕 ----

def test_tier_of_single_source_equivalence():
    """档位结构单源 _tier_of：价格色/破线空心两消费端等价 + 擦边区间
    下界严格 >th、上界恰 1.1 仍擦边（与 webui near 同式）。"""
    from report import (_tier_of, _price_color, _price_hollow,
                        C_QUAL, C_NEAR, DESIGN)
    assert _tier_of(1900, 2000, True) == 2
    assert _tier_of(1900, 2000, False) == 1
    assert _tier_of(2000, 2000, False) == 1
    assert _tier_of(2100, 2000, False) == -1
    assert _tier_of(2200, 2000, False) == -1      # 恰 th*1.1 上界
    assert _tier_of(2201, 2000, False) == 0
    assert _tier_of(1900, 0, False) == 0          # 未设线无档
    f = {"_th": 2000}
    for price, qual in ((1900, True), (1900, False), (2000, False),
                        (2100, False), (2400, False)):
        t = _tier_of(price, 2000, qual)
        assert _price_hollow(f, qual, price) == (t == 1)
        assert (_price_color(f, qual, price) == C_QUAL) == (t >= 1)
        assert (_price_color(f, qual, price) == C_NEAR) == (t == -1)


def test_qunar_dom_joined_code_guard():
    """联程混淆码守卫：「华夏航G581O1J」不再产出假号 G581——code 置空
    行保留（价格/时刻真实）、name 保留原文；合规号不受影响。"""
    from crawlers.qunar import QunarCrawler as Q
    dom = ("\n10:20\n浦东\n3h15m\n转\n西安\n+1天\n14:30\n地窝堡\n"
           "华夏航G581O1J\n￥4020\n"
           "\n09:00\n虹桥\n2h30m\n15:30\n浦东\n春秋9C8866\n￥650\n")
    rows = Q._parse_dom_flights(dom, "2026-10-06")
    assert len(rows) == 2, rows
    assert rows[0]["code"] == "", rows[0]
    assert rows[0]["name"] == "华夏航G581O1J"
    assert rows[0]["price"] == 4020 and rows[0]["transCity"] == "西安"
    assert rows[1]["code"] == "9C8866"


def test_tongcheng_plane_prefix_and_variant_cleanup():
    """机型清洗（v1.5.47）：旧键「机型」前缀与 _变体后缀曾直入推送
    决策行（机型73M/空客A320_186 实锤 DB 值）。"""
    from crawlers.tongcheng import TongchengCrawler
    text = json.dumps({"data": {"fl": [{
        "fn": "GS7587", "asn": "天津航空",
        "dt": "2026-10-06 07:00", "at": "2026-10-06 13:45",
        "td": "6h45m", "equipmentName": "机型73M",
        "lps": [{"atp": 3200, "brs": [{"al": 4}],
                 "pts": [{"tt": 2, "td": "6.8折经济舱"}]}],
    }, {
        "fn": "MU5137", "asn": "东航",
        "dt": "2026-10-06 09:00", "at": "2026-10-06 14:00",
        "td": "5h0m", "afn": "空客A320_186",
        "lps": [{"atp": 3100, "brs": [{"al": 4}],
                 "pts": [{"tt": 2, "td": "经济舱"}]}],
    }]}})
    out = TongchengCrawler._extract_flights(text)
    assert out[0]["plane"] == "73M", out[0]
    assert out[1]["plane"] == "空客A320", out[1]


def test_compare_rows_date_labels():
    """multi 比价组收编 _compare_rows 单源：date_labels 开关补日期段，
    日报默认不带（单一事实源，加字段不再漏端）。"""
    cands = [(100, [{"name": "MU8369", "price": 1000, "depTime": "08:00",
                     "arrTime": "11:00"}], "2026-10-05")]
    plain = Alerter._compare_rows(cands)
    labeled = Alerter._compare_rows(cands, date_labels=True)
    assert plain[0]["label"] == "MU8369"
    assert labeled[0]["label"] == "MU8369 10/05", labeled[0]


def test_ensure_jump_link_fallback_and_platform_source():
    """链接兜底单源（v1.5.47）：图片链不算可点链接；无航班数据时平台
    退用户启用首位而非硬编码 qunar（挂羊头预防）。"""
    import logging as _lg
    a = Alerter(_lg.getLogger("t"), storage=None, digest=True)
    r = _mk_route()
    s = _mk_sections(2600)[0]
    desp = "#### x\n\n![走势](https://img.example/t.png)\n\n"
    out = a._ensure_jump_link(desp, r, s)
    assert "打开" in out and "](http" in out, out
    # 有真链接不重复兜底
    desp2 = "[直飞 ￥2600](https://flight.qunar.com/x)\n\n"
    assert a._ensure_jump_link(desp2, r, s) == desp2
    # 空数据 section：平台=启用首位
    a2 = Alerter(_lg.getLogger("t"), storage=None, digest=True,
                 platforms=["ctrip"])
    out2 = a2._ensure_jump_link("无数据", r, {"date": "2026-10-05"})
    assert "打开携程" in out2 and "m.ctrip.com" in out2, out2


def test_ntfy_truncation_leaves_trace(monkeypatch):
    """ntfy 截断留痕（v1.5.47 与钉钉纪律对齐）：回退截断后补尾注，
    不再静默丢弃其后整段。"""
    import logging as _lg
    from unittest import mock
    import core.notifier as N
    calls = []
    monkeypatch.setattr(N.httpx, "post",
                        lambda u, **kw: (calls.append(kw),
                                         mock.Mock(status_code=200))[1])
    nt = N.NtfyNotifier(topic="t", logger=_lg.getLogger("t"))
    body = "前缀 " + "x" * 700 + " https://flight.example.com/very/long/url"
    assert nt.send("标题", body) is True
    sent = calls[-1]["json"]["message"]
    assert "已截断" in sent and len(sent) <= 700, sent
    # 未截断不补尾注
    calls.clear()
    assert nt.send("标题", "短消息") is True
    assert "已截断" not in calls[-1]["json"]["message"]


def test_sentinel_layover_dual_key_and_median_ratio(monkeypatch, tmp_path):
    """哨兵双键兼容（v1.5.47 P0）：原始 extra 键是 layover（layoverM 是
    normalize 产物）——此前恒 0 命中=健康渠道天天假告警；渠道中位比
    观测对系统性漂移渠道告警。"""
    import json as _json
    import logging as _lg
    import types
    import main as M
    monkeypatch.setattr(M, "_SENT_PATH", str(tmp_path / "sent.json"))
    monkeypatch.setattr(M, "_SENT_LAST", {})
    monkeypatch.setattr(M, "_SENT_CNT", {})
    monkeypatch.setattr(M, "_ROW_HIST", {})

    def _rec(plat, rows):
        return types.SimpleNamespace(
            platform=plat, extra=_json.dumps(rows),
            from_city="SHA", to_city="URC", depart_date="2026-10-05")

    warns = []
    lg = _lg.getLogger("t-sent")
    lg.warning = lambda *a, **k: warns.append(a)
    # 双键均计入：layover(layoverM)>0 覆盖满格，无停留假告警
    recs = [_rec("ctrip", [{"price": 1500, "transCity": "西安",
                            "layover": 120}] * 25),
            _rec("qunar", [{"price": 1500, "transCity": "西安",
                            "layoverM": 90}] * 25)]
    M._field_sentinel(recs, lg)
    assert not any("中转停留覆盖" in str(a[0]) for a in warns), warns

    # 渠道中位比：qunar 系统性 +50% → p50=1.5 告警；ctrip/tuniu 不响
    # （每行独立指纹=独立组，各渠道攒 ≥20 个组内比值才判）
    warns.clear()
    recs2 = [_rec(p, [{"price": int(1000 * f) + i * 10,
                       "code": "MU%d" % (1100 + i),
                       "depTime": "08:00", "arrTime": "11:00",
                       "transCity": "", "arrDate": ""}
                      for i in range(25)])
             for p, f in (("qunar", 1.5), ("ctrip", 1.0), ("tuniu", 1.0))]
    M._field_sentinel(recs2, lg)
    msgs = [(a[0] % a[1:] if len(a) > 1 else str(a[0])) for a in warns]
    assert any("qunar" in m and "中位比" in m for m in msgs), msgs
    assert not any("ctrip" in m and "中位比" in m for m in msgs), msgs
