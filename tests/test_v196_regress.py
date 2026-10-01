# -*- coding: utf-8 -*-
"""r196 回归：prate=0 占位守卫三端收口。

数据观测 P2 立案（_scratch/r196_dataquality.md）：ctrip 组合中转行
classinfor.prate=0（DB 6 行实证 GS7486/FM9426 等，2026-09-26/28）——
0 是「组合无单航班准点率」占位非真值，webui 明细次行与推送 PNG 明细
表曾渲染「准点0%」假数据。守卫收口三端：flightnorm.prate_txt 单源
（0 族置空、真值原样）+ ctrip 读层根治（0→""）+ webui/report 消费端
接线（存量 DB 行通吃）。tuniu 恒 20 占位由渠道读层专属守卫先挡
（test_v1552 先例），不在本单源重复。
"""
import json
import logging


# ==================== prate_txt 单源守卫 ====================

class TestPrateTxt:
    def test_placeholder_zero_family(self):
        from core.flightnorm import prate_txt
        for v in (0, 0.0, "0", "0%", "0.0", "0.0%", None, "", "   "):
            assert prate_txt(v) == "", repr(v)

    def test_real_values_passthrough(self):
        from core.flightnorm import prate_txt
        assert prate_txt(94) == "94"
        assert prate_txt("94%") == "94%"
        assert prate_txt("96.67") == "96.67"
        assert prate_txt(100) == "100"
        assert prate_txt(" 97 ") == "97"


# ==================== ctrip 读层根治 ====================

class TestCtripPrateZero:
    """组合中转行 classinfor.prate=0（生产 6 行实证形态）：读层
    置空宁缺勿错（与 563 行脏值弃同律）；真值 97 照常。"""

    def _parse(self, item):
        from crawlers.ctrip import CtripCrawler
        return CtripCrawler._extract_ctrip_flights(
            CtripCrawler, json.dumps({"fltitem": [item]},
                                     ensure_ascii=False))

    @staticmethod
    def _item(prate):
        return {"mutilstn": [{"basinfo": {"flgno": "GS7486/FM9426"},
                              "dateinfo": {"ddate": "2026-10-05 08:00:00",
                                           "adate": "2026-10-05 14:30:00"},
                              "aportinfo": {"city": "上海"}}],
                "policyinfo": [{"tprice": 2050, "quantity": 1,
                                "classinfor": [
                                    {"cgrd": 0, "prate": prate,
                                     "meal": ""}]}]}

    def test_zero_placeholder_dropped(self):
        rows = self._parse(self._item(0))
        assert rows, "夹具应产出航班行"
        assert rows[0]["prate"] == "", rows[0].get("prate")

    def test_real_value_kept(self):
        rows = self._parse(self._item(97))
        assert rows[0]["prate"] == "97"


# ==================== 消费端接线（源码钉） ====================

def test_webui_and_report_wired_to_single_source():
    """webui 明细次行与 report PNG 明细表必须走 prate_txt 单源
    （两消费点直读原始键，源码钉防旁路手抄回潮）。"""
    import io
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for path in ("webui.py", "report.py"):
        src = io.open(os.path.join(root, path), encoding="utf-8").read()
        assert "prate_txt(" in src, f"{path} 未接 prate_txt 单源"


# ==================== transCity 裸码补录 ====================

class TestAirportCnGaps:
    """transCity 机场码补录（数据观测 P2：7 天 DB 实测 4 码漏网——
    WDS 704/UYN 133/LYA 77/YCU 22 行以 IATA 码原样落库，中转城市
    渲染成英文码）。城市级映射与 AIRPORT_CN 现表同风格（城市名）。"""

    def test_normalize_maps_new_codes(self):
        from core.flightnorm import normalize
        for code, cn in (("WDS", "十堰"), ("UYN", "鄂尔多斯"),
                         ("LYA", "洛阳"), ("YCU", "运城")):
            f = {"transCity": code}
            normalize(f, "")
            assert f["transCity"] == cn, code


# ==================== 弹层在途令牌（Soldier P2-1 源码钉） ====================

def test_pv_cancel_seq_token_wired():
    """取消/换代统一走 _PV_SEQ 令牌：单布尔 _PV_CANCEL 曾被新请求
    重置——「Esc 取消→立刻重触发」后被取消请求的迟到响应仍会开层。
    源码钉锁六处同构（fetch 后失配检查 ×3：showLog/previewPush/
    pushLog〔r226 补齐第三入口〕、Esc 令牌递增、finally 按 _sq 清
    pending ×3）；行为面由 uitest「弹层在途 Esc 取消」钉锁。"""
    import io
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = io.open(os.path.join(root, "webui.py"), encoding="utf-8").read()
    assert "let _PV_PENDING=false,_PV_SEQ=0;" in src
    assert src.count("if(_sq!==_PV_SEQ)return;") == 3, \
        "showLog/previewPush/pushLog 三入口失配检查"
    assert "if(_PV_PENDING){++_PV_SEQ;_PV_PENDING=false;return;}" in src
    assert src.count("if(_sq===_PV_SEQ)_PV_PENDING=false;") == 3, \
        "迟到响应不得清新请求 pending"
    assert "_PV_CANCEL" not in src, "旧单布尔取消标志应已退役"


# ==================== 邮件图链本地直嵌 + 降级留痕 ====================

class TestLocalPushImage:
    """P1 邮件图链（推送审校+数据观测双立案）：jsDelivr 与 raw 直链
    同路由间歇可达（各 1/4 成功率，3.5 天失败 241 次）——不稳在路由
    级，换域名无效。cid 内嵌改本地直嵌优先：图在推送前几秒刚渲染落
    盘（URL 尾段 {stem}_{HHMM}.png ↔ 本地 data/{stem}.png），零网络
    失败面。防陈旧：mtime 超 30 分钟（风暴延迟重发时本地文件已被下
    轮覆盖=图文不同源，比丢图更糟）不直嵌走下载，宁慢勿错。
    铁律：仅下载资产层，钉钉消息单发零重试不受影响。"""

    def test_local_hit(self, monkeypatch, tmp_path):
        import os
        monkeypatch.chdir(tmp_path)
        os.makedirs("data")
        (tmp_path / "data" / "trend_URC_SHA_2026-10-05.png").write_bytes(
            b"\x89PNG fake")
        from core.notifier import _local_push_image
        data = _local_push_image(
            "https://cdn.jsdelivr.net/gh/o/r@main/charts/20260928/"
            "trend_URC_SHA_2026-10-05_2018.png")
        assert data == b"\x89PNG fake"

    def test_stale_local_miss(self, monkeypatch, tmp_path):
        import os
        import time
        monkeypatch.chdir(tmp_path)
        os.makedirs("data")
        p = tmp_path / "data" / "trend_X.png"
        p.write_bytes(b"\x89PNG")
        old = time.time() - 3600
        os.utime(p, (old, old))
        from core.notifier import _local_push_image
        assert _local_push_image(
            "https://cdn.jsdelivr.net/gh/o/r@main/charts/20260928/"
            "trend_X_1234.png") == b""

    def test_non_chart_url_miss(self):
        from core.notifier import _local_push_image
        assert _local_push_image("https://sm.ms/x.png") == b""

    def test_inline_prefers_local_no_network(self, monkeypatch, tmp_path):
        import os
        monkeypatch.chdir(tmp_path)
        os.makedirs("data")
        (tmp_path / "data" / "t.png").write_bytes(b"\x89PNGxxxx")
        import core.notifier as nm
        from core.notifier import _inline_push_images

        def _boom(url):
            raise AssertionError("本地命中时不应走网络下载")

        monkeypatch.setattr(nm, "_fetch_push_image", _boom)
        out, parts = _inline_push_images(
            "![走势](https://cdn.jsdelivr.net/gh/o/r@main/charts/"
            "20260928/t_1200.png)", logging.getLogger("t"))
        assert len(parts) == 1 and parts[0][0] == "push-img-1"
        assert "cid:push-img-1" in out

    def test_stats_reports_fallback(self, monkeypatch, tmp_path):
        """降级留痕出参（P2-1）：本地 miss+网络失败 → total=1
        inlined=0，控制台「推送记录」对图挂不再失明（332 发全 ok=true
        曾让 3.5 天丢图完全不可见）。"""
        monkeypatch.chdir(tmp_path)   # 无 data/ 本地文件 → miss
        import core.notifier as nm
        from core.notifier import _inline_push_images
        monkeypatch.setattr(nm, "_fetch_push_image",
                            lambda u: (_ for _ in ()).throw(
                                RuntimeError("boom")))
        st = {}
        out, parts = _inline_push_images(
            "![总表](https://cdn.jsdelivr.net/gh/o/r@main/charts/"
            "20260928/f_1300.png)", logging.getLogger("t"), st)
        assert parts == [] and "cid:" not in out   # 外链保留旧行为
        assert st == {"total": 1, "inlined": 0}, st

    def test_email_history_carries_img_note(self, monkeypatch, tmp_path):
        """email 落账带 img 注（降级时），全成功/无图不带——
        push_history 消费端整条透传，前端按值渲染。last_img_note 由
        _build_msg 每轮重算（防跨轮残留），故走真实降级路径驱动：
        本地 miss+网络炸 → note='图0/1内嵌' 随落账带出。"""
        monkeypatch.chdir(tmp_path)   # 无 data/ 本地文件
        import core.notifier as nm
        captured = []

        def _fake_hist(title, desp, ok, ch="serverchan", img=None):
            captured.append((ch, img))

        monkeypatch.setattr(nm, "_append_push_history", _fake_hist)
        monkeypatch.setattr(
            nm, "_fetch_push_image",
            lambda u: (_ for _ in ()).throw(RuntimeError("boom")))
        n = nm.EmailNotifier.__new__(nm.EmailNotifier)
        n.host, n.port, n.user = "smtp.test", 465, "a@test"
        n.password, n.to = "x", ["b@test"]
        n.sender_name = "机票监控"
        n.logger = logging.getLogger("t")
        n._fail_streak = 0
        n.snapshot_base = None
        monkeypatch.setattr(nm, "smtplib", _FakeSMTPModule())
        desp = ("![总表](https://cdn.jsdelivr.net/gh/o/r@main/charts/"
                "20260928/f_1300.png)")
        assert n.send("t", desp) is True
        assert captured == [("email", "图0/1内嵌")], captured

        # 无图 desp：重算回 None，落账不带 img（防跨轮残留面）
        captured.clear()
        assert n.send("t", "纯文本") is True
        assert captured == [("email", None)], captured


class _FakeSMTP:
    """SMTP_SSL 替身：with 协议 + login/sendmail 零操作。"""

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, *a):
        pass

    def sendmail(self, *a, **k):
        pass


class _FakeSMTPModule:
    """smtplib 模块替身（send 调 smtplib.SMTP_SSL(...)）。"""

    SMTP_SSL = _FakeSMTP
