# -*- coding: utf-8 -*-
"""r199 推送层立案（E 路审校 P0×1 + P1×1 + P2×4）。

P0：日报明细表图上传曾硬编码 upload_freeimage（freeimage 端点已
封禁，内部必落 pixhost）——push_history 取证 09-21 起 46 处日报
明细表 URL 全落 img3.pixhost.to（大陆显示端直连不可达，项目自证），
同 desp 走势图走 ghimg/jsDelivr 正常；KPI 已图内化且 turl 非空不
触发文本兜底 → 日报明细/KPI/比价/各渠道最低手机端静默全灭。改走
provider 感知的 upload_chart 统一入口。

P1：upload_chart/upload_freeimage 的 pixhost 兜底档产出「上传成功
但读者拉不到」的死链（9 月 542/2132≈25% 含图轮次明细/走势落
pixhost），URL 非空使 alerter 现成的图挂文本兜底永不触发——pixhost
出局（显示端不可达筛选律 + v1.5.89 用户热修先例），上传链失败返回
None 交文本兜底（构建端信息保全优于死链；单发零重试铁律不涉）。

P2-1：_ops_fallbacks 中间档全角「（截）」6 半角挤爆预算——5 渠道
缺失+飞猪(维护中)打头形态 k=1 档 42/40 全超，塌地板档「无数据：
（截）」渠道清单全灭成病句；截断标记统一半角 (截)（_dw 实值 4 半
角，与渠道名「飞猪(维护中)」括号形态同族），k=1 档 40/40 恰满首
渠道名入预算。
P2-2：直飞组头 5 位数阈值+多日期 41 半角超宽——线价下沉引用行
（_section_title 两分支同律），4 位数既有 40/40 形态不动。
P2-3：携程指引第二行「（…--login ctrip 重新登录）」43 半角超宽
——词面缩短收模块常量（调用点内联字面是守卫失效温床）。
P2-4：风暴连推标题前缀挤占 60 字符预算致尾段静默截——前缀计入
预算重排（notifier title[:60] 同口径），锚点段保全。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v199_push.py -q
"""
import logging
import re

import pytest


# ==================== P0: 日报明细表走 provider 感知上传 ====================

_ROUTE = {"from": "SHA", "to": "URC", "from_name": "上海",
          "to_name": "乌鲁木齐", "dates": ["2026-09-25"],
          "alert_direct": 2000, "alert_transfer": 1800,
          "transfer_arrival_max": "02:00"}
_FLIGHTS = [
    {"price": 2690, "transCity": "", "_platform": "qunar"},
    {"price": 2150, "transCity": "郑州", "depTime": "12:05",
     "arrTime": "00:35", "arrDate": "2026-09-26", "_platform": "ctrip"},
]


def _daily_cfg():
    return {"notifier": {"image_host": {"provider": "ghimg"}},
            "users": [{"name": "u", "routes": [_ROUTE],
                       "notifier": {"image_host": {"provider": "ghimg"}}}]}


def _patch_daily_commons(monkeypatch, rep):
    monkeypatch.setattr(rep, "prepare_round_charts",
                        lambda c, lg, *a, **k: {("SHA", "URC", "2026-09-25"):
                                       "http://x/t.png"})
    monkeypatch.setattr(rep, "_route_latest_flights",
                        lambda db, fc, tc, d, **kw: _FLIGHTS)
    monkeypatch.setattr(rep, "render_flights_table", lambda *a, **k: None)


class TestDailyTableProviderUpload:
    """P0：日报明细表上传必须走 upload_chart（cfg 感知 provider），
    硬编码 upload_freeimage 曾让明细表独走 freeimage→pixhost 死链。"""

    def test_upload_chart_called_with_cfg(self, monkeypatch):
        import report as rep
        _patch_daily_commons(monkeypatch, rep)
        calls = {}

        def _cap_upload(p, c, lg):
            calls["png"], calls["cfg"] = p, c
            return "http://x/table.png"

        monkeypatch.setattr(rep, "upload_chart", _cap_upload)

        def _forbidden(p, lg):
            raise AssertionError(
                "upload_freeimage 不应再被日报明细表路径调用")

        monkeypatch.setattr(rep, "upload_freeimage", _forbidden)
        sent = {}

        class FakeN:
            def send(self, title, desp="", **kw):
                sent["desp"] = desp
                return True

        ok = rep.build_and_push(_daily_cfg(), logging.getLogger("t"),
                                FakeN(), user="u")
        assert ok and sent.get("desp")
        assert calls.get("cfg") == _daily_cfg(), \
            "upload_chart 必须拿到 cfg（provider 感知）"
        assert "![明细总表](http://x/table.png)" in sent["desp"]

    def test_upload_fail_degrades_to_text_kpi(self, monkeypatch):
        """turl=None（P1 后 ghimg 失败形态）→ 明细表留痕 + KPI 文本
        兜底（图挂信息守恒在日报侧闭合）。"""
        import report as rep
        _patch_daily_commons(monkeypatch, rep)
        monkeypatch.setattr(rep, "upload_chart", lambda p, c, lg: None)
        sent = {}

        class FakeN:
            def send(self, title, desp="", **kw):
                sent["desp"] = desp
                return True

        ok = rep.build_and_push(_daily_cfg(), logging.getLogger("t"),
                                FakeN(), user="u")
        assert ok
        d = sent["desp"]
        assert "明细表缺失" in d and "![明细表]" not in d
        assert "直飞 ￥2690" in d, "KPI 文本兜底应接管"


# ==================== P1: pixhost 出局，失败交文本兜底 ====================

class TestPixhostOutOfChain:
    """pixhost 显示端直连不可达（v1.5.89 用户热修先例）：上传链
    失败必须返回 None 交图挂文本兜底，不得产出显示端死链 URL。"""

    def test_upload_chart_terminal_not_pixhost(self, monkeypatch):
        import report as rep
        assert not hasattr(rep, "_upload_pixhost"), \
            "pixhost 上传函数应已随链路撤除"
        monkeypatch.setattr(rep, "upload_ghimg", lambda p, ih, lg: None)
        ih = {"provider": "ghimg", "repo": "o/r", "token": "t"}
        url = rep.upload_chart("/tmp/x.png", {}, logging.getLogger("t"),
                               ih=ih)
        assert url is None, "ghimg 失败后不得落 pixhost 死链"

    def test_freeimage_fail_not_pixhost(self, monkeypatch, tmp_path):
        import report as rep
        png = tmp_path / "x.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n")
        monkeypatch.setattr(rep, "_FREEIMG_STATE", {"n": 0, "probe": 0})

        def _dead(*a, **k):
            raise Exception("freeimage endpoint banned")

        monkeypatch.setattr(rep.httpx, "post", _dead)
        url = rep.upload_freeimage(str(png), logging.getLogger("t"))
        assert url is None, "freeimage 失败后不得落 pixhost 死链"

    def test_unconfigured_host_no_pixhost(self, monkeypatch):
        """ih 空 dict=未配置语义：曾「直走 pixhost」，出局后为 None
        （文本兜底接管）。"""
        import report as rep
        url = rep.upload_chart("/tmp/x.png", {}, logging.getLogger("t"),
                               ih={})
        assert url is None


# ==================== P2-1: ops 降级链截断标记半角化 ====================

class TestOpsFallbacksBudget:
    """5 渠道缺失+飞猪(维护中)打头：k=1 档须入 40 预算（首渠道名
    保全，docstring 声称的语义落地），_fit_line 不塌裸地板。"""

    N = "乌上 10/05 无数据：飞猪(维护中)、去哪儿、携程、同程、途牛"

    def test_first_channel_tier_fits(self):
        from core.alerter import _disp_dw, _fit_line, _ops_fallbacks
        out = _fit_line("> ⚠️ " + self.N,
                        fallbacks=_ops_fallbacks(self.N))
        assert _disp_dw(out) <= 40, f"超宽：{_disp_dw(out)}"
        assert "飞猪(维护中)" in out, f"首渠道名未入预算：{out!r}"
        # r220 校准补让位档:(截) 标记与首渠道名争预算时渠道名优先,
        # 诚实性由「渠道全量对账循控制台」备案兜底
        assert ("(截)" in out) or (_disp_dw("> ⚠️ " + self.N) > 40), \
            f"截标记与渠道名双失:{out!r}"

    def test_floor_nonempty_after_prefix(self):
        from core.alerter import _ops_fallbacks
        floor = _ops_fallbacks(self.N)[-1]
        body = floor.replace("> ⚠️ ", "").removesuffix("(截)")
        assert body.strip(), f"地板档前缀后空（病句形态）：{floor!r}"

    def test_normal_form_unchanged(self):
        from core.alerter import _disp_dw, _fit_line, _ops_fallbacks
        n = "孤低价拦截×3：MU1234、MU5678、MU9012"
        out = _fit_line("> ⚠️ " + n, fallbacks=_ops_fallbacks(n))
        assert "孤低价拦截×3：" in out and _disp_dw(out) <= 40


# ==================== P2-2: 直飞组头线价下沉 ====================

def _mk_alerter():
    from core.alerter import Alerter
    return Alerter(logging.getLogger("t"), notifier=None,
                   base_url="http://127.0.0.1:8765")


class TestTop3DirectHeaderBudget:
    """5 位数阈值+多日期组头 41 半角：线价下沉引用行，渲染行恒 ≤40，
    线价信息不丢（信息守恒）。4 位数形态 r220 校准后同降（带日期组头
    「（线￥N）· MM/DD」数字计宽上浮破 40），与中转组头「> 线￥N」
    引用行形态两端统一。"""

    def _desp(self, alert_direct):
        from core.models import Route
        r = Route(from_code="SHA", from_name="上海", to_code="URC",
                  to_name="乌鲁木齐", dates=["2026-10-05", "2026-10-06"],
                  alert_direct=alert_direct, alert_transfer=1800)
        sections = [{"date": "2026-10-05", "top_direct": [],
                     "top_transfer": []},
                    {"date": "2026-10-06", "top_direct": [],
                     "top_transfer": []}]
        return _mk_alerter()._top3_blocks(r, sections)

    def test_wide_header_degrades_with_quote(self):
        from core.alerter import _disp_dw
        desp = self._desp(12345)
        assert "线￥12345" in desp, "线价信息丢失"
        for ln in desp.split("\n"):
            if ln.strip():
                assert _disp_dw(ln) <= 40, f"超宽行：{ln!r}"
        assert "#### ✈️ 直飞最优TOP5（线￥12345）" not in desp

    def test_narrow_header_unchanged(self):
        desp = self._desp(1234)
        # r220 校准:带日期组头「（线￥N） · MM/DD」超 40,线值降档到
        # 紧跟引用行(与 5 位数同形态,信息守恒)
        assert "#### ✈️ 直飞最优TOP5 · 10/05\n\n> 线￥1234" in desp
        assert "#### ✈️ 直飞最优TOP5 · 10/06\n\n> 线￥1234" in desp


# ==================== P2-3: 携程指引行词面收常量 ====================

class TestCtripLoginNoteWidth:
    """「（持续无数据请运行 --login ctrip 重新登录）」43 半角超宽
    ——词面缩短并收模块常量（内联字面是守卫失效温床）。"""

    def test_constant_within_budget(self):
        from core.alerter import _CTIP_LOGIN_NOTE, _disp_dw
        assert _disp_dw(_CTIP_LOGIN_NOTE) <= 40, \
            f"{_CTIP_LOGIN_NOTE!r} = {_disp_dw(_CTIP_LOGIN_NOTE)}"

    def test_old_long_form_absent(self):
        with open("core/alerter.py", encoding="utf-8") as f:
            src = f.read()
        assert "重新登录）" not in src, "43 半角长词面残留"


# ==================== P2-4: 风暴标题前缀计入预算 ====================

class TestStormTitleBudget:
    """前缀「📞 达标提醒 N/M 」计入 60 字符预算（notifier title[:60]
    同口径）——满额主推 title 直拼曾静默截尾丢「｜另监控」段。"""

    def test_full_title_truncated_to_60(self):
        from core.alerter import _storm_title
        t = _storm_title(2, 3, "达标！乌→上 10/05 直飞￥1500 " + "x" * 60)
        assert len(t) <= 60
        assert t.startswith("📞 达标提醒 2/3 达标！乌→上"), t
        assert "达标！乌→上 10/05 直飞￥1500" in t, "锚点段被截"

    def test_short_title_untouched(self):
        from core.alerter import _storm_title
        t = _storm_title(3, 3, "达标！乌→上 10/05 直飞￥1500")
        assert t == "📞 达标提醒 3/3 达标！乌→上 10/05 直飞￥1500"

    def test_storm_path_uses_helper(self):
        with open("core/alerter.py", encoding="utf-8") as f:
            src = f.read()
        assert "_storm_title(" in src
        i = src.index("def _storm(")
        assert "_storm_title(" in src[i:], "风暴路径未走 helper"
        assert 'f"📞 达标提醒' not in src[i:], "内联直拼残留"
