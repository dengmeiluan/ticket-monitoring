# -*- coding: utf-8 -*-
"""r255 WebUI 三案（审计报告 r255_audit_webui.md P2-1/P3-1/P3-2）。

P2-1 航线卡头「启用/停用」开关（.rop 槽）入触控外扩家族——同簇
ropbtn/danger 均有 36px 增强，唯它全漏（裸目标 36×20）。
P3-1 a.vw/.tj 纯 inline 盒的 ::after 包含块取行内片段 content-box，
-9px 实测只兑现 34px，纵向提到 -11px（同 .hc 先例）。
P3-2 U-6 半落地收尾：500-JSON 错误体冷启动分支 #updated 双词面
残留清空（502-HTML 分支已留空，pill 单源）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r255_webui.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _page():
    return open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "webui.py"), encoding="utf-8").read()


class TestRopSwitchTouchFamily:
    def test_rop_switch_extends_in_all_three_blocks(self):
        """P2-1：.rop .switch::before 外扩声明在三个触控媒体块各一
        （≤900/≤600/≤390 族与 .srow/.fbar/.glcell 同格局）——计数钉
        锁「块内同族清单完整」，漏任一块即红。"""
        n = _page().count(
            ".rop .switch::before{content:'';position:absolute;inset:-8px}")
        assert n == 3, f"预期 3 块各 1 处，实际 {n}"

    def test_rop_family_note_updated(self):
        """家族注释槽位清单随 .rop 同轮更新（防清单漂移）。"""
        assert ".srow/.fbar/.glcell/.rop" in _page()


class TestInlineIntentTouchHeight:
    def test_vw_and_tj_vertical_reach_36(self):
        """P3-1：a.vw/.tj 的 ::after 纵向 -11px（inline 盒包含块律，
        -9px 只兑现 34px 不达 36 触控基准）。"""
        src = _page()
        assert (".pvx::after,a.vw::after{content:'';position:absolute;"
                "inset:-11px -8px}") in src
        assert ".tj::after{content:'';position:absolute;inset:-11px -4px}" in src

    def test_stale_minus_nine_note_purged(self):
        """a.vw/.tj 家族注释不再宣称 -9px 达标（防注释与实现漂移）。
        注：.chhead/.tg 本体为块级盒，-9px 兑现 37px 达标，不在本钉面。"""
        src = _page()
        assert "-9px -8px / -9px -4px" not in src


class TestErrcodeMinusTwoCoverage:
    def test_errcode_tip_explains_minus_two(self):
        """P3-2 展示层随动：errcode=-2（网络异常轮落账）上线后，
        推送记录的悬停词表必须解释 -2，不能让它落进「其他码见通道
        文档」的泛化档（-2 与 -1 语义相反：-1 可能已送达，-2 必然
        未送达）。"""
        src = _page()
        assert "-2=未收到响应" in src, \
            "errcode 悬停词表缺 -2 语义（网络异常轮落账已上线）"

    def test_demo_sample_covers_minus_two_shape(self):
        """DEMO 合成推送记录含 -2 形态样例（词表改动的活体展示位，
        与既有 -1 幽灵送达样例成对）。"""
        src = _page()
        assert '"errcode": -2' in src, "DEMO 样例缺 errcode=-2 形态"


class TestErrorBodyUpdatedPillSingleSource:
    def test_cold_start_500_updated_blank(self):
        """P3-2：500-JSON 冷启动分支 #updated 置空（与 502-HTML 分支
        同律）——pill 是错误词面唯一承载，#updated 不再复读。"""
        src = _page()
        assert "else{$('updated').textContent='';_markStale('服务异常');}" in src

    def test_fuwu_yichang_updated_literal_purged(self):
        """「（服务异常）」updated 词面全页零残留（冷启动分支清空后
        该字面无合法写点；「服务异常」pill 词面不受本钉约束）。"""
        assert "（服务异常）" not in _page()
