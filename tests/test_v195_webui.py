# -*- coding: utf-8 -*-
"""r195 WebUI 回归（源码级钉，同 test_v192 模式）。

P2-1（审计 r195-webui）：明细表切片续载每滚动事件只补一片——焦点在
表内按 End（或拖动滚动条快滚）落点距真底数千 px（549 班实测
gap≈9135px），需多按才能收敛到底。修法：滚动监听 while 化，单事件
循环补齐至落点可见（上限 4 片=480 行，防单帧长任务回潮）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v195_webui.py -q
"""


class TestWebuiV195Pins:
    """webui.py 源码级钉死。"""

    @staticmethod
    def _src():
        import webui as _w
        with open(_w.__file__, encoding="utf-8") as f:
            return f.read()

    def test_scroll_listener_batch_append(self):
        """滚动续载 while 化：单事件补齐至落点可见，上限 4 片。"""
        src = self._src()
        i = src.index("querySelector('#tablecard .tw').addEventListener")
        seg = src[i:src.index("},{passive:true})", i)]
        assert "while(n<4&&" in seg.replace(" ", ""), \
            "滚动续载仍是单片 if（End 跳底落点距真底需多按收敛）或缺上限"

    def test_end_key_explicit_jump_bottom(self):
        """End 键显式跳底路径（真机定谳：补片推远底边会打断平滑滚动、
        「距底<600」条件被自身补片失效——键盘路径必须显式补全量再滚
        到底并交接焦点，不依赖滚动事件接力）。"""
        src = self._src()
        assert "function _jumpTableBottom(" in src, \
            "缺 _jumpTableBottom（End 跳底在切片表上不可达真底）"
        i = src.index("function _jumpTableBottom(")
        seg = src[i:i + 700]
        assert "while(_ROWS&&_NDRAW*_CHUNK<_ROWS.length)" in \
            seg.replace(" ", ""), "跳底前未补片至全量"
        assert "rows[rows.length-1].focus()" in seg.replace(" ", ""), \
            "焦点未交接末行（连续 End/Enter 落空）"
        assert "event.key==='End'" in src, "行级键盘未挂 End"

    def test_deep_position_backfill_while_kept(self):
        """轮询刷新深位回填 while 既有形态不被本次改动误伤
        （st 界条件自然收敛，与滚动监听是两条路径）。"""
        src = self._src()
        assert "while(st>0&&tw.scrollHeight<st+tw.clientHeight&&_tblAppend()){}" \
            in src.replace(" ", ""), \
            "table() 深位补齐 while 形态被误改"
