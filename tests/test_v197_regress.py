# -*- coding: utf-8 -*-
"""r197 回归：五路调研立案七案（观测 C×1 / WebUI D×3 / 推送 E×3）。

C 路（r197 观测）：ctrip InTimeTag 真源下发 0%（组合/codeshare 填槽，
GS7486 id 17893/17902 连续两轮）时 573 行覆盖绕过 568 行 0 值挡——
prate='0' 再流入；且伪源（{100,97}，交叉一致率 1.2%）会借 0 占位
兜底落库，渲染「准点100%」比「准点0%」更隐蔽。InTimeTag 在场即定谳：
有值覆盖伪源、0 占位连同伪源一并置空。

E 路（r197 推送审校）：①build_and_push 提前 return（无图床/无图）
不清 notifier 陈旧 errcode，上轮 -1 残留把当日日报误按「幽灵送达
已推」落账静默吞；②push_history 落盘截断前 desp，控制台记录≠群内
实收；③近 7 天趋势行撤常驻的依据失实（走势图窗 48h vs 文本 7 天，
图内无承载）——违反「图内容量≥被撤文本版」，恢复常驻。

D 路（r197 WebUI 审计）：📈 跳走势门在「单启用航线×多日期」最常见
形态恒假（route 全表为空，走势入口消失）；走势入场动画 clip 死区
残留早帧像素；48h 双系列「低」标注必撞时完全同位互盖。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v197_regress.py -q
"""
import json
import logging
import sqlite3
import datetime as dt

import pytest


# ==================== D1: ctrip InTimeTag 0 占位绕挡 ====================

class TestCtripIntimeZero:
    """InTimeTag 下发 0%（组合行填槽，结构性占位）时不得落库：
    覆盖分支同过 0 值挡，且伪源不得借 0 占位兜底落「准点100%」。"""

    def _parse(self, item):
        from crawlers.ctrip import CtripCrawler
        return CtripCrawler._extract_ctrip_flights(
            CtripCrawler, json.dumps({"fltitem": [item]},
                                     ensure_ascii=False))

    @staticmethod
    def _item(intime_tag, prate=100):
        """classinfor.prate 恒给伪源 100（生产常态）：真源在场时
        伪源必须被覆盖或置空，不得落库。"""
        item = {"mutilstn": [{"basinfo": {"flgno": "GS7486/FM9426"},
                              "dateinfo": {"ddate": "2026-10-06 08:00:00",
                                           "adate": "2026-10-06 14:30:00"},
                              "aportinfo": {"city": "上海"}}],
                "policyinfo": [{"tprice": 2050, "quantity": 1,
                                "classinfor": [
                                    {"cgrd": 0, "prate": prate,
                                     "meal": ""}]}]}
        if intime_tag is not None:
            item["aset"] = [{"tagarea": [{"tcode": "InTimeTag",
                                          "tagcnt": intime_tag}]}]
        return item

    def test_intime_zero_is_placeholder_not_truth(self):
        rows = self._parse(self._item("准点率0%"))
        assert rows, "夹具应产出航班行"
        assert rows[0]["prate"] == "", \
            f"InTimeTag 0% 占位落库为 {rows[0]['prate']!r}（渲染准点0%）"

    def test_intime_real_overrides_pseudo_source(self):
        rows = self._parse(self._item("准点率94%"))
        assert rows[0]["prate"] == "94", "真源覆盖伪源失效"

    def test_intime_absent_pseudo_zero_still_blocked(self):
        """InTimeTag 缺席时伪源 0 由既有挡位拦（v196 钉不回退）。"""
        rows = self._parse(self._item(None, prate=0))
        assert rows[0]["prate"] == ""


# ==================== E1: build_and_push 入口清陈旧 errcode ====================

class TestBuildPushErrcodeReset:
    """build_and_push 在 send 之前提前 return（无图床 provider/
    无可画数据）时，notifier.last_errcode 仍是上一条告警轮的 -1
    留痕——maybe_daily_report 的「-1 幽灵按已推落账」守卫误命中，
    当日日报被静默吞。入口清零：本轮尚未发送，任何残留皆陈旧。"""

    def test_stale_errcode_cleared_on_early_return(self):
        from report import build_and_push

        class _StaleN:
            last_errcode = -1          # 上轮告警轮残留（类属性即实例可见）

            def send(self, *a, **kw):
                return True

        n = _StaleN()
        ok = build_and_push({}, logging.getLogger("t"), n)
        assert ok is False, "无图床 cfg 应走提前 return"
        assert getattr(n, "last_errcode", "missing") is None, \
            "提前 return 未清陈旧 errcode（幽灵守卫将误吞当日日报）"

    def test_reset_at_function_head(self):
        """清零必须位于函数入口（provider 判空之前）：两个提前
        return 分支都要被覆盖。"""
        import webui  # noqa: F401  (确保 CWD 无关的 import 面)
        import report as _rep
        with open(_rep.__file__, encoding="utf-8") as f:
            src = f.read()
        i0 = src.index("def build_and_push(")
        i1 = src.index("ih = _image_host_cfg(cfg)", i0)
        head = src[i0:i1]
        assert "last_errcode" in head, \
            "清零不在入口段（provider 判空前），第二个提前 return 不受覆盖"


# ==================== E2: push_history 落盘实收形态 ====================

class TestPushHistorySentForm:
    """钉钉 send 超 18000 字节截断后，push_history 落盘的应是
    群内实收形态（含截断尾注），不是截断前的原始 desp——控制台
    「推送记录」与群里实际收到的内容不一致曾无从对账。"""

    def test_history_records_truncated_form(self, monkeypatch):
        import core.notifier as N
        cap = {}

        def fake_hist(title, desp, ok, ch="serverchan", img=None):
            cap["desp"] = desp

        monkeypatch.setattr(N, "_append_push_history", fake_hist)

        class _Resp:
            status_code = 200
            text = '{"errcode":0,"errmsg":"ok"}'

            def json(self):
                return {"errcode": 0}

        monkeypatch.setattr(N.httpx, "post", lambda *a, **kw: _Resp())
        n = N.DingTalkNotifier(
            "https://oapi.dingtalk.com/robot/send?access_token=x",
            logging.getLogger("t"))
        tail = "TAILMARK-被切尾段"
        desp = "x" * 19000 + tail
        assert n.send("t", desp) is True
        assert cap["desp"] != desp, "落盘=截断前原文（与群内实收不一致）"
        assert "已截断" in cap["desp"], "落盘缺截断留痕尾注"
        assert tail not in cap["desp"], "被切尾段混入落盘（非实收形态）"

    def test_history_normal_round_is_untouched(self, monkeypatch):
        """未超限轮：落盘=发送文本（尾空段收口后的形态），零回归。"""
        import core.notifier as N
        cap = {}

        def fake_hist(title, desp, ok, ch="serverchan", img=None):
            cap["desp"] = desp

        monkeypatch.setattr(N, "_append_push_history", fake_hist)

        class _Resp:
            status_code = 200
            text = '{"errcode":0,"errmsg":"ok"}'

            def json(self):
                return {"errcode": 0}

        monkeypatch.setattr(N.httpx, "post", lambda *a, **kw: _Resp())
        n = N.DingTalkNotifier(
            "https://oapi.dingtalk.com/robot/send?access_token=x",
            logging.getLogger("t"))
        n.send("t", "正常内容\n\n")
        assert cap["desp"] == "正常内容", "未超限轮落盘被意外改写"


class TestServerChanHistorySentForm:
    """ServerChan 同族收口（Soldier P2-1）：31800 字节截断后落盘
    应为实收形态（含尾注），记录≠实收的缺陷不随通道切换复发。"""

    def test_history_records_truncated_form(self, monkeypatch):
        import core.notifier as N
        cap = {}
        monkeypatch.setattr(
            N, "_append_push_history",
            lambda t, d, ok, ch="serverchan", img=None:
            cap.update(desp=d, ok=ok))

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b'{"code":0}'

        monkeypatch.setattr(N.urllib.request, "urlopen",
                            lambda *a, **kw: _Resp())
        n = N.ServerChanNotifier("SCT123", logging.getLogger("t"))
        tail = "TAILMARK-被切尾段"
        desp = "x" * 33000 + tail
        assert n.send("t", desp) is True
        assert cap["desp"] != desp, "落盘=截断前原文（记录≠实收）"
        assert "已截断" in cap["desp"], "落盘缺截断留痕尾注"
        assert tail not in cap["desp"], "被切尾段混入落盘"


# ==================== E3: 近 7 天趋势行恢复常驻 ====================

def _mk_db(tmp_path, rows, date="2026-10-06"):
    """(hours_ago, 直飞价, 中转价) 多轮库；样本时刻动态生成+锚定
    今天中午（168h 相对窗，固定时刻会随日历滑出窗「上午绿下午红」，
    裸 now 相对偏移跨日历日会翻转日期桶）。"""
    from core.storage import SCHEMA
    db = str(tmp_path / "t.db")
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA)
    now = dt.datetime.now().replace(hour=12, minute=0, second=0,
                                    microsecond=0)
    for h, dprice, tprice in rows:
        ts = (now - dt.timedelta(hours=h)).strftime("%Y-%m-%d %H:%M:%S")
        fs = [{"price": dprice, "name": "CZ6976", "code": "CZ6976",
               "transCity": "", "depTime": "08:00", "arrTime": "11:00",
               "depDate": date, "arrDate": date, "totalDuration": "3时"}]
        if tprice is not None:
            fs.append({"price": tprice, "name": "MU8370", "code": "MU8370",
                       "transCity": "郑州", "depTime": "09:00",
                       "arrTime": "15:30", "depDate": date,
                       "arrDate": date, "totalDuration": "6时30分"})
        conn.execute(
            "INSERT INTO flight_prices (platform,from_city,to_city,"
            "depart_date,price,fetched_at,extra) VALUES (?,?,?,?,?,?,?)",
            ("qunar", "SHA", "URC", date, dprice, ts,
             json.dumps(fs, ensure_ascii=False)))
    conn.commit()
    conn.close()
    return db


class TestTrendLineResident:
    """近 7 天趋势行恢复常驻：走势图窗 48h 承载不了 168h 文本信息，
    撤常驻让正常有图轮的 7 天趋势彻底消失（图内容量≥被撤文本版）。"""

    def test_trend_line_present_in_charted_round(self, tmp_path):
        from core.alerter import Alerter
        from core.models import FlightPrice, Route
        import types as _ty

        db = _mk_db(tmp_path, [(3, 2000, None), (1, 1500, None)])
        captured = []

        class FakeN:
            def send(self, t, d, at_mobiles=None, is_at_all=False,
                     launch=""):
                captured.append((t, d, at_mobiles))
                return True

        a = Alerter(logging.getLogger("t"), notifier=FakeN(),
                    storage=_ty.SimpleNamespace(db_path=db), digest=True)
        # 有图场景（走势图上传成功的正常轮）：撤常驻的形态下此轮
        # desp 无「近7天」——回归钉
        a.round_charts = {("SHA", "URC", "2026-10-06"):
                          "https://iili.io/fake1.png"}
        r = Route(from_code="SHA", to_code="URC", from_name="上海",
                  to_name="乌鲁木齐", dates=["2026-10-06"],
                  alert_direct=1600, alert_transfer=0)
        extra = json.dumps([{"price": 1500, "name": "CZ6976",
                             "code": "CZ6976", "depTime": "08:00",
                             "arrTime": "11:00", "depDate": "2026-10-06",
                             "arrDate": "2026-10-06", "transCity": "",
                             "totalDuration": "3时"}])
        ps = [FlightPrice(platform="qunar", from_city="SHA", to_city="URC",
                          depart_date="2026-10-06", price=1500,
                          extra=extra)]
        a.check_multi([(r, ps)])
        assert captured, "达标轮应产生聚合推送"
        desp = captured[0][1]
        assert "近7天" in desp, \
            "有图正常轮 7 天趋势行缺席（撤常驻后图内无 168h 承载）"
        assert "直飞" in desp and "↓" in desp

    def test_missing_chart_fallback_still_present(self, tmp_path):
        """趋势行全文恰一次：常驻一处 + 缺图分支不补位（防双份回归
        用行为钉——源码钉抓不住「恢复补位」的静默回归）。"""
        from core.alerter import Alerter
        from core.models import FlightPrice, Route
        import types as _ty

        db = _mk_db(tmp_path, [(3, 2000, None), (1, 1500, None)])
        captured = []

        class FakeN:
            def send(self, t, d, at_mobiles=None, is_at_all=False,
                     launch=""):
                captured.append((t, d, at_mobiles))
                return True

        a = Alerter(logging.getLogger("t"), notifier=FakeN(),
                    storage=_ty.SimpleNamespace(db_path=db), digest=True)
        a.round_charts = {}   # 缺图场景
        r = Route(from_code="SHA", to_code="URC", from_name="上海",
                  to_name="乌鲁木齐", dates=["2026-10-06"],
                  alert_direct=1600, alert_transfer=0)
        extra = json.dumps([{"price": 1500, "name": "CZ6976",
                             "code": "CZ6976", "depTime": "08:00",
                             "arrTime": "11:00", "depDate": "2026-10-06",
                             "arrDate": "2026-10-06", "transCity": "",
                             "totalDuration": "3时"}])
        ps = [FlightPrice(platform="qunar", from_city="SHA", to_city="URC",
                          depart_date="2026-10-06", price=1500,
                          extra=extra)]
        a.check_multi([(r, ps)])
        assert captured, "达标轮应产生聚合推送"
        desp = captured[0][1]
        assert desp.count("近7天") == 1, \
            f"趋势行出现 {desp.count('近7天')} 次（常驻+补位双份或缺席）"


# ==================== D 路 WebUI 三案（源码级钉） ====================

class TestWebuiV197Pins:
    @staticmethod
    def _src():
        import webui as _w
        with open(_w.__file__, encoding="utf-8") as f:
            return f.read()

    def test_route_label_gate_includes_dates(self):
        """📈 跳走势门：单启用航线×多日期（最常见形态）也须产出
        route 标签——len(routes)>1 恒假曾让 599/599 行无走势入口。"""
        src = self._src()
        i = src.index("rt_label = (")
        seg = src[i:i + 260]
        assert 'rr.get("dates")' in seg.replace("'", '"'), \
            "route 门未含日期维度（单启用航线多日期形态全表无📈入口）"

    def test_anim_clip_covers_tag_zone(self):
        """入场动画 clip 终帧须覆盖标签可达域（低标注可画到 W-3）：
        (W-L-R+4) 死区曾残留早帧悬浮字。"""
        src = self._src()
        assert "(W-L-R+4)*e" not in src, "动画 clip 死区未收口"
        assert "(W-L+2)*e" in src, "clip 终帧宽度未覆盖标签可达域"

    def test_min_tag_overlap_forces_vertical_stagger(self):
        """「低」标注互叠罚分带纵向错距梯度：必撞时错开 ≥16px 的
        候选胜出，不再完全同位互盖。"""
        src = self._src()
        assert "16-Math.abs(cy-b[1])" in src, \
            "互叠罚分无纵向错距梯度（双系列低标注同位互盖）"
        assert "?999:0)" not in src, "旧常数罚分形态残留"


# ==================== 版本门禁随批 ====================

def test_version_bumped_this_round():
    """发版批内 bump（铁律：版本号与功能改动同批）；>= 元组比较
    只拦落后允许领先。"""
    import re
    import subprocess
    from main import __version__ as v
    m = re.match(r"(\d+)\.(\d+)\.(\d+)", v)
    assert m, v
    cur = tuple(map(int, m.groups()))
    assert cur >= (1, 5, 96), f"版本未随本轮 bump: {v}"
