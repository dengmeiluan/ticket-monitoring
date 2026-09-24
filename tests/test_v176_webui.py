# -*- coding: utf-8 -*-
"""webui 回归（源码级钉，同 test_v174_webui.py 模式；行为断言在
docs/uitest.py 补钉）。

（WebUI 布局与交互第七轮，六新 lens：亮暗主题逐 token 对账/
三态完备/键盘可达性/术语一致性/窄屏 ≤760 走查/动效一致性；P0=0，P1=0，
P2×1 立案+撤案 1+观察备案）：

 错误态假等待：load fetch 失败分支只更新 pill/updated，三处静态
    骨架（明细表 #ftable / 登录卡 #loginRows / 全局参数 #cfgglobals）
    恒停「加载中…」——pill 说服务未启动、表体说加载中，两处语义矛盾，
    且「加载中」永不到达终态。修法：catch 分支调 _markStale 三处同步
    置「服务未启动，恢复后自动刷新」，恢复轮 render/loadCfg 重写自愈。
    （TDD：_scratch/v175_pin_test.py PIN1 先红后绿。）

撤案正面钉（复盘）：Esc 关推送弹层后焦点回送 opener——
    closePv 的 _PV_RETURN 回送链（落地）实测两路径均绿，D 路
    探针 escClose=false 系探针自身误报；钉住该链防未来重构丢失。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v176_webui.py -q
"""


class TestWebuiV176Pins:
    """webui.py 源码级钉死。"""

    @staticmethod
    def _src():
        import webui as _w
        with open(_w.__file__, encoding="utf-8") as f:
            return f.read()

    def test_p1_mark_stale_defined_and_called_on_fetch_failure(self):
        """：_markStale 定义在位且 fetch 失败冷启动分支必调（假等待回潮）。"""
        src = self._src()
        assert "function _markStale(" in src, "_markStale 帮手丢失"
        i_load = src.index("async function load()")
        i_catch = src.index("catch(e){LASTTXT", i_load)
        i_fin = src.index("finally{LOADN=false;}", i_catch)
        cseg = src[i_catch:i_fin]
        assert "if(S)" in cseg, "catch 分支未按有无旧数据分叉（有旧数据被掀卡）"
        assert "_markStale()" in cseg, \
            "load() catch 冷启动分支未调 _markStale（错误态骨架不同步）"
        assert "_markStale()" not in cseg[:cseg.index("else{")], \
            "有旧数据分支不得掀骨架（保陈旧数据交互不失效）"

    def test_p1_stale_covers_three_skeletons_no_fake_loading(self):
        """：三处骨架全覆盖，且错误态文案不再含「加载中」字样。"""
        import re
        src = self._src()
        i0 = src.index("function _markStale(")
        i1 = src.index("async function load()", i0)
        body = src[i0:i1]
        for dom_id in ("ftable", "loginRows", "cfgglobals"):
            assert dom_id in body, f"骨架 #{dom_id} 未覆盖（假等待残留）"
        assert "(svc||'服务未启动')+'，恢复后自动刷新'" in body, "错误态文案丢失"
        m = re.search(r"const msg=\(svc\|\|'[^']+'\)\+'([^']+)'", body)
        assert m and "加载中" not in m.group(1), \
            "错误态文案不得再出现「加载中」（注释提及不受限）"

    def test_p2_focus_return_chain_intact(self):
        """撤案正面钉：closePv 焦点回送链（_PV_RETURN→focus）在位。"""
        src = self._src()
        assert "function _openPvMask(){_PV_RETURN=document.activeElement;" in src, \
            "开弹层入口未记录 _PV_RETURN（回送链源头缺失）"
        assert "const ret=_PV_RETURN;_PV_RETURN=null;" in src \
            and "ret.focus()" in src, "closePv 焦点回送链丢失"
