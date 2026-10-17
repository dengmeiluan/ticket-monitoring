# -*- coding: utf-8 -*-
"""推送回归（真执行级，同 test_v170_push.py 模式）。

 审校立案 P1×1——日报「🔍 打开渠道查现价」链接自引入恒死码：
report.py 调 `Alerter._build_view_url(_vs, date, _plat)` 少传 self 占位
（方法签名 (self, route, date, platform)），3 参类调用恒抛 TypeError，
被 `except Exception: pass` 静默吞——push_history 全量 72 条日报
（09-11→09-22）「🔍」出现 0 次，功能从未生效。修法=webui.py:3657 在案
范式 `Alerter._build_view_url(None, ns, date, plat)`（方法体不消费 self）；
裸 pass 降 logger.debug 留痕。

钉：
1. 源码形态钉——report.py 必须 4 参 None 占 self 调用；3 参死码形态消失；
   except 不再裸 pass（debug 留痕）。
2. 执行级钉——None 占 self 范式对五渠道逐一真调 _build_view_url，
   断言返回非空且与爬虫主路径同域（空平台返回 ""=宁缺勿错契约保持）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v171_push.py -q
"""
from types import SimpleNamespace

_NS = SimpleNamespace(from_code="URC", from_name="乌鲁木齐",
                      to_code="SHA", to_name="上海")
_DATE = "2026-10-05"


class TestDailyViewUrlV171:
    """日报「🔍 打开渠道查现价」链接修复钉。"""

    @staticmethod
    def _report_src():
        import report as _r
        with open(_r.__file__, encoding="utf-8") as f:
            return f.read()

    def test_report_calls_with_none_self_placeholder(self):
        """源码钉：4 参 None 占 self 范式在位，3 参死码形态消失。"""
        src = self._report_src()
        assert "Alerter._build_view_url(None, _vs, date, _plat)" in src, \
            "report.py 未按 None 占 self 范式调用 _build_view_url（🔍 链接恒死码回潮）"
        assert "Alerter._build_view_url(_vs, date, _plat)" not in src, \
            "3 参死码调用形态残留（少 self 占位恒 TypeError）"

    def test_report_no_silent_pass_on_link(self):
        """源码钉：🔍 段 except 不再裸 pass（降 logger.debug 留痕）。"""
        src = self._report_src()
        i = src.find("_build_view_url")
        seg = src[i:i + 900]
        assert "except Exception:\n            pass" not in seg, \
            "🔍 段仍是裸 pass 静默吞异常（故障不可观测）"
        assert "logger.debug" in seg, "🔍 段异常未留痕"

    def test_none_self_paradigm_real_execute(self):
        """执行级钉：None 占 self 对五渠道真调返回与爬虫同域的 URL。"""
        from core.alerter import Alerter
        expect = {
            "qunar": "https://flight.qunar.com",
            "ctrip": "https://m.ctrip.com",
            "tuniu": "https://m.tuniu.com",
            "tongcheng": "https://m.ly.com",
            "fliggy": "https://sjipiao.fliggy.com",
        }
        for plat, domain in expect.items():
            url = Alerter._build_view_url(None, _NS, _DATE, plat)
            assert url and url.startswith(domain), \
                "%s 链接异常: %r" % (plat, url)
            assert _DATE.replace("-", "") in url or _DATE in url, \
                "%s 链接缺日期参数: %r" % (plat, url)

    def test_unknown_platform_returns_empty(self):
        """执行级钉：未知/空平台返回 ""（宁缺勿错契约保持——report 端
        if _vu 跳过，不出死链）。"""
        from core.alerter import Alerter
        assert Alerter._build_view_url(None, _NS, _DATE, "") == ""
        assert Alerter._build_view_url(None, _NS, _DATE, "nosuch") == ""
