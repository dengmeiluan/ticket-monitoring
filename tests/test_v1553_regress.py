# 回归：差额词单源终局（_low_txt 并入 gap_txt）+ 强提醒转写
# 剥注防叠词（调研② 挂起项收口）+ 🔥 入转写表 + mini KPI 档位
# 点与主 KPI 贴法对齐。词面/单源纪律的测试侧钉死。
import datetime as _dt
import os


class TestLowTxtSingleSource:
    """_low_txt 词面并入 gap_txt（调研②）：独立拼「低￥N」是
    第二词源（gap_txt docstring「改词必漏」同病）；恰达线 diff==0
    曾读「低￥0」自相矛盾。"""

    def test_word_face_equals_gap_txt(self):
        from core.alerter import _low_txt, gap_txt
        assert _low_txt(1850, 2000, "qunar") == "低￥150"
        assert _low_txt(1850, 2000, "qunar") == gap_txt(1850, 2000, True)

    def test_exact_threshold_reads_qual_word(self):
        from core.alerter import _low_txt
        out = _low_txt(2000, 2000, "qunar")
        assert out == "真达标"
        assert "低￥0" not in out

    def test_fliggy_tax_note_strict_below_only(self):
        """税前注挂严格破线飞猪行；恰达线（真达标）不挂——
        「真达标(税前)」语义不通。"""
        from core import alerter as _a
        from core.alerter import _low_txt
        old = _a.FLIGGY_TAX_PAD
        try:
            _a.FLIGGY_TAX_PAD = 100
            assert _low_txt(1850, 2100, "fliggy") == "低￥250（税前）"
            assert _low_txt(2100, 2100, "fliggy") == "真达标"
        finally:
            _a.FLIGGY_TAX_PAD = old


class TestTranscribeDedup:
    """转写前剥注（调研②）：🟩 转写词「行情价 」与 KPI 行1
    尾注「（行情价）/*行情」、行3 兜底注「行情价」同条重复——
    生产 0/200 共现的挂起项提前收口，共现一现即叠词。"""

    def test_alert_body_strips_market_note(self):
        from core.notifier import _alert_body
        body = _alert_body("🟩 直飞 ￥2500　线￥2600　低￥100（行情价）\n\n"
                           "> 经西安 停2h 行李直挂 行情价")
        assert body.count("行情价") == 1          # 仅剩转写前缀
        assert "（行情价）" not in body

    def test_alert_body_strips_star_note(self):
        from core.notifier import _alert_body
        body = _alert_body("🟩 直飞 ￥2500　线￥2600　低￥100*行情")
        assert body.count("行情价") == 1
        assert "*行情" not in body

    def test_wintoast_plain_strips_market_note(self):
        from core.notifier import WindowsToastNotifier
        body = WindowsToastNotifier._plain(
            "🟩 直飞 ￥2500　线￥2600　低￥100（行情价）", 180)
        assert body.count("行情价") == 1
        assert "（行情价）" not in body


class TestFireHitTranscribed:
    """🔥 入转写表（调研② P2）：hits 行首 🔥 在 ntfy/WinToast 曾保留
    原样，TTS 读「火」或跳读；转「命中 」可播报。"""

    def test_table_entry(self):
        from core.notifier import _EMOJI_TIER_WORDS
        assert ("🔥", "命中 ") in _EMOJI_TIER_WORDS

    def test_alert_body_transcribes(self):
        from core.notifier import _alert_body
        body = _alert_body("🔥 直飞 ￥2500　线￥2600　低￥100(税前)")
        assert "命中" in body
        assert "🔥" not in body

    def test_ntfy_count_captured_pre_transcribe(self):
        """截断留痕「共N条命中」计数须取转写前原文：🔥 进转写表后
        转写后文本已无 🔥，事后计数恒 0 静默消失。"""
        import core.notifier as _n
        src = open(_n.__file__, encoding="utf-8").read()
        assert "_nfire = (desp or \"\").count(\"🔥\")" in src
        assert "_n = _nfire" in src
        assert '_full.count("🔥")' not in src


class TestMiniKpiDotSpacing:
    """mini KPI 档位点补尾随空格（调研② P2）：主 KPI/legacy 带
    空格、mini 无空格，同体系两种贴法。"""

    def test_all_dots_spaced(self):
        import core.alerter as _a
        src = open(_a.__file__, encoding="utf-8").read()
        assert 'dot = "🎯 "' in src
        assert 'dot = "🟩 "' in src
        assert 'dot = "🟨 "' in src
        # 无空格旧形态清零（防新代码再引入）
        assert 'dot = "🎯"' not in src
        assert 'dot = "🟩"' not in src
        assert 'dot = "🟨"' not in src


class TestQunarH5Labels:
    """H5 决策标签（调研④）：priceBottomLabels 按 text 显式
    白名单采（id 被营销词共用勿按 id）；transNotice 占位「转」不采。"""

    def test_whitelist_rejects_marketing_words(self):
        from crawlers.qunar import QunarCrawler
        f = {"listLabel": {"priceBottomLabels": [
                {"id": "reduceShowLabel", "text": "中转低价"},
                {"id": "x", "text": "出票后2小时内错购退票"}]},
             "transNotice": "转"}
        out = QunarCrawler._h5_labels_of(f)
        assert out == "出票后2小时内错购退票"
        assert "中转低价" not in out

    def test_trans_notice_non_default_only(self):
        from crawlers.qunar import QunarCrawler
        assert QunarCrawler._h5_labels_of(
            {"transNotice": "华夏联程"}) == "华夏联程"
        assert QunarCrawler._h5_labels_of({"transNotice": "转"}) == ""
        assert QunarCrawler._h5_labels_of({}) == ""


class TestCrawlerFieldPins:
    """调研④ 落地钉死：ctrip transTerminal 值级兜底、tuniu 宽体机
    标签、dump 截断上限提升。"""

    @staticmethod
    def _src(path):
        return open(path, encoding="utf-8").read()

    def test_ctrip_trans_term_value_level_fallback(self):
        src = self._src("crawlers/ctrip.py")
        assert 'trans_term = (str((segs[1].get("dportinfo") or {})' in src

    def test_tuniu_widebody_label(self):
        src = self._src("crawlers/tuniu.py")
        assert '"labels": ("宽体机" if str(detail.get("planeModelName")' in src

    def test_dump_cap_raised(self):
        for p in ("crawlers/ctrip.py", "crawlers/tongcheng.py"):
            src = self._src(p)
            assert "[:1000000]" not in src and "[:4000000]" in src


class TestPriceBandSingleSource:
    """价格带单源（调研③ P1-A）：曲线侧曾独用 300 下界而列表
    无下界——100–299 真实低价「列表可见、图上不可见」是曲线-列表含义
    一致的破口。五处取数链统一 core.models PRICE_MIN/PRICE_MAX。"""

    def test_constants(self):
        from core.models import PRICE_MAX, PRICE_MIN
        assert (PRICE_MIN, PRICE_MAX) == (100, 50000)

    def test_no_scattered_bands(self):
        import core.alerter as _a
        import report as _r
        for src in (open(_a.__file__, encoding="utf-8").read(),
                    open(_r.__file__, encoding="utf-8").read()):
            assert "300 <= p <= 50000" not in src
            assert "0 < lo <= 50000" not in src
            assert '0 < f["price"] <= 50000' not in src
            assert '0 < _v2 <= 50000' not in src

    def test_rounds_accepts_low_band_price(self):
        """曲线侧下界 300→100 后，150 元真实低价行不再被曲线剔除。"""
        import json as _json
        import os as _os
        import sqlite3 as _sq
        import tempfile as _tf
        from report import _rounds
        with _tf.TemporaryDirectory() as td:
            dbp = _os.path.join(td, "t.db")
            db = _sq.connect(dbp)
            db.execute("CREATE TABLE flight_prices (platform TEXT, extra "
                       "TEXT, fetched_at TEXT, from_city TEXT, to_city "
                       "TEXT, depart_date TEXT)")
            extra = _json.dumps([
                {"price": 150, "depTime": "10:00", "arrTime": "13:00"},
                {"price": 900, "depTime": "12:00", "arrTime": "15:00"}])
            # fetched_at 动态化——原硬编码 2026-09-20 10:00 在
            # 48h 回看窗语义下随真实时钟漂移出窗（09-22 10:00 后恒红），
            # 测试本意（150 元低价行不被曲线剔除）与绝对时刻无关
            _ts = (_dt.datetime.now() - _dt.timedelta(hours=1)
                   ).strftime("%Y-%m-%d %H:%M:%S")
            db.execute("INSERT INTO flight_prices VALUES ('qunar',?,"
                       "?,'A','B','2026-10-01')", (extra, _ts))
            db.commit()
            hist = _rounds(dbp, "A", "B", "2026-10-01", "02:00", hours=48)
            db.close()
        assert hist and hist[0][1] == 150


class TestRoundSeriesAnchorOrder:
    """_rounds 幻影锚池判定与列表链同序（调研③ P1-B）：锚池
    判定必须先于到达/衔接过滤（曲线侧曾对过滤后残池判幻影）。"""

    def test_source_pin(self):
        import report as _r
        src = open(_r.__file__, encoding="utf-8").read()
        # 到达过滤不再在桶收集期发生
        assert "if Alerter._arrival_ok(f, arrival_max):\n                    b[2].append" not in src
        # 幻影判定先于 ok_t 过滤
        assert src.index("_no_x = [x for i, x in enumerate(tsf)") < \
            src.index("ok_t = [(f, p, pl) for f, p, pl in _no_x")


class TestSentinelTuniuPrateKept:
    """tuniu|prate 守卫后不入死键表（生产实证 09-19/20 真实覆盖
    80%+、占位 20 清零）——哨兵死键表不得收入 tuniu prate，
    观测口径跟着守卫改的前提不成立。"""

    def test_tuniu_prate_not_in_dead_keys(self):
        import main as _m
        src = open(_m.__file__, encoding="utf-8").read()
        dead = _m._field_sentinel.__code__.co_consts
        assert not any(
            isinstance(c, (set, frozenset)) and ("tuniu", "prate") in c
            for c in dead)
        assert src.count('("tuniu", "prate")') == 0


class TestOpsNotesIntoImage:
    """运维对账注入图（，用户截图反馈）：直挂标注缺失/无数据
    渠道/孤低价拦截/全渠道无数据四类对账行自钉钉文本段撤入总表 PNG
    小注——「跳转文案才用文本，其余只出图」定律补口；
    图挂兜底分支才回退文本（信息不能跟图一起消失）。"""

    @staticmethod
    def _fixture():
        import logging as _lg
        from core.alerter import Alerter
        from core.models import Route as _R
        a = Alerter(_lg.getLogger("t"), notifier=None, digest=True)
        r = _R(from_code="SHA", to_code="URC", from_name="上海",
               to_name="乌鲁木齐", dates=["2026-09-25"],
               alert_direct=1900, alert_transfer=1700)
        s = {"date": "2026-09-25", "seen_plats": [],          # 全渠道缺
             "best_direct": None, "best_transfer": None,
             "xphans": [("qunar", 313), ("ctrip", 350)]}      # 拦截留痕
        return a, r, [s]

    def test_ops_notes_pass_to_render_and_desp_clean(self):
        import report as _rep
        a, r, sections = self._fixture()
        cap = {}
        orig = (_rep.render_flights_table, _rep.upload_chart)
        _rep.render_flights_table = (
            lambda rows_, title, out, top_n=5, summary="", stamp_note="",
            ops_notes="": cap.update(ops=list(ops_notes or [])) or out)
        _rep.upload_chart = (lambda p, cfg=None, lg=None, ih=None:
                                "https://iili.io/fake.png")
        try:
            pv = a._digest_payload([(r, sections)], fresh=True,
                                   with_tables=True)
        finally:
            _rep.render_flights_table, _rep.upload_chart = orig
        ops = " ｜ ".join(cap.get("ops") or [])
        assert "无数据" in ops and "孤低价拦截×2" in ops
        assert "￥313" in ops                       # 拦截价随行入图
        desp = pv["desp"]
        assert "孤低价拦截" not in desp              # 文本段已撤
        assert "无数据：" not in desp

    def test_transfer_baggage_note_in_image(self):
        import report as _rep
        a, r, sections = self._fixture()
        r.transfer_baggage = "direct"
        sections[0]["top_transfer"] = [{"price": 1650, "transCity": "郑州",
                                        "transferBaggage": ""}]
        cap = {}
        orig = (_rep.render_flights_table, _rep.upload_chart)
        _rep.render_flights_table = (
            lambda rows_, title, out, top_n=5, summary="", stamp_note="",
            ops_notes="": cap.update(ops=list(ops_notes or [])) or out)
        _rep.upload_chart = (lambda p, cfg=None, lg=None, ih=None:
                                "https://iili.io/fake.png")
        try:
            a._digest_payload([(r, sections)], fresh=True, with_tables=True)
        finally:
            _rep.render_flights_table, _rep.upload_chart = orig
        assert any("直挂标注缺失" in _n for _n in cap.get("ops") or [])

    def test_fallback_text_keeps_notes_when_image_fails(self):
        import report as _rep
        a, r, sections = self._fixture()
        orig = (_rep.render_flights_table, _rep.upload_chart)
        _rep.render_flights_table = (
            lambda rows_, title, out, top_n=5, summary="", stamp_note="",
            ops_notes="": out)
        _rep.upload_chart = (lambda p, cfg=None, lg=None, ih=None: ""     # 图挂
                             )
        try:
            pv = a._digest_payload([(r, sections)], fresh=True,
                                   with_tables=True)
        finally:
            _rep.render_flights_table, _rep.upload_chart = orig
        desp = pv["desp"]
        assert "⚠️" in desp and "无数据" in desp      # 兜底回退文本

    def test_render_draws_ops_box(self):
        """渲染端烟测：ops_notes 有注时画布增高（盒体+间距）。"""
        import tempfile as _tf
        import report as _rep
        rows = [("direct", [{"price": 1500, "name": "MU8369",
                             "depTime": "19:55", "arrTime": "01:25",
                             "_platform": "qunar"}], "✈️ 直飞最优 · SHA 25")]
        with _tf.TemporaryDirectory() as td:
            p0, p1 = (os.path.join(td, n) for n in ("a.png", "b.png"))
            _rep.render_flights_table(rows, "测试", p0, summary=[],
                                      ops_notes=[])
            _rep.render_flights_table(rows, "测试", p1, summary=[],
                                      ops_notes=["SHA 09/25 无数据：去哪儿"])
            from PIL import Image as _I
            h0 = _I.open(p0).height
            h1 = _I.open(p1).height
            assert h1 > h0
