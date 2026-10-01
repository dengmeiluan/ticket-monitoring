# -*- coding: utf-8 -*-
"""v1.5.83 webui 回归（源码级钉，同 test_v182_webui.py 模式）。

Soldier v1.5.82 Minor 收口（load() 异常终点三态完备性 + 读屏截断）：
- Minor-1 fetch 失败 catch 分支按有无旧数据分叉：有旧数据→保旧标注
  「服务异常/保留上次结果」不掀骨架（与错误体分支、renderHealth
  保陈旧政策对齐）；冷启动→原错误态不动。错误体（服务在线）分支
  pill 词面同步改中性「服务异常」，消除与「保留上次结果」同屏矛盾
- Minor-2 LASTTXT 先解后存：畸形 200 体不再污染签名（同体重试可重入，
  恢复轮必被处理）
- Minor-3 heFriendly 按字素截断：Array.from 劈不开代理对（emoji 尾端
  不出孤立替身符）

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v183_webui.py -q
"""


class TestWebuiV183Pins:
    """webui.py 源码级钉死。"""

    @staticmethod
    def _src():
        import webui as _w
        with open(_w.__file__, encoding="utf-8") as f:
            return f.read()

    # ---- Minor-1 catch 分支按 S 分叉，保旧不掀卡 ----

    def test_load_catch_branch_split(self):
        src = self._src()
        i0 = src.index("async function load()")
        seg = src[i0:i0 + 2000]
        ci = seg.index("catch(e){LASTTXT")
        cseg = seg[ci:ci + 560]
        assert "if(S)" in cseg, "fetch 失败 catch 分支未按有无旧数据分叉"
        assert "服务异常" in cseg, \
            "catch 有旧数据未落中性词面（「服务未启动」与服务在线自相矛盾）"
        assert "保留上次结果" in cseg, "catch 有旧数据未标注保旧"
        assert "LASTTXT=''" in cseg, \
            "catch 未失效签名：恢复轮同文本将被跳过，「服务异常」词面驻留不退场"
        assert "_markStale()" in cseg, "冷启动 catch 仍需错误态落点"
        pre = cseg[:cseg.index("else{")]
        assert "_markStale()" not in pre, "有旧数据分支不得掀骨架（保陈旧数据交互不失效）"

    def test_state_errbody_wordface(self):
        src = self._src()
        i0 = src.index("async function load()")
        seg = src[i0:i0 + 2000]
        ei = seg.index("错误体分支")
        eseg = seg[ei:ei + 560]
        assert "服务异常" in eseg, "错误体（服务在线）分支 pill 词面过重"

    # ---- Minor-2 先解后存 ----

    def test_load_parse_before_lasttxt(self):
        src = self._src()
        i0 = src.index("async function load()")
        seg = src[i0:i0 + 400]
        pi = seg.index("JSON.parse(t)")
        li = seg.index("LASTTXT=t")
        assert pi < li, "LASTTXT 先于 JSON.parse 写定：畸形 200 体一次即驻留"

    # ---- Minor-3 heFriendly 字素安全截断 ----

    def test_hefriendly_grapheme_safe(self):
        src = self._src()
        i0 = src.index("function heFriendly")
        seg = src[i0:i0 + 320]
        assert "Array.from(e).slice(0,80).join('')" in seg, \
            "heFriendly 仍按 UTF-16 码元截断（emoji 尾端劈出孤立代理对）"
        assert "e.slice(0,80)" not in seg, "旧码元截断残留"

    # ---- audit v183 P2-1 health/pulse 脱离 state 签名门 ----

    def test_health_pulse_outside_signature_gate(self):
        src = self._src()
        i0 = src.index("async function load()")
        i1 = src.index("function pct(", i0)
        seg = src[i0:i1]
        hp = seg.rindex("health();pulse();")
        assert hp > seg.index("catch(e){", seg.index("LASTTXT=t")), \
            "health/pulse 仍在 state 签名门内：state 文本不变时健康/脉冲永不刷新（错误词面驻留）"

    # ---- audit v183 P2-2 冷启动错误体词面同轨 ----

    def test_markstale_wordface_param(self):
        src = self._src()
        i0 = src.index("function _markStale(")
        seg = src[i0:i0 + 400]
        assert "(svc||'服务未启动')" in seg, \
            "_markStale 未参数化词面（冷启动 500 错误体与服务在线状态混轨）"
        i1 = src.index("async function load()")
        seg1 = src[i1:i1 + 2000]
        ei = seg1.index("错误体分支")
        eseg = seg1[ei:ei + 560]
        assert "_markStale('服务异常')" in eseg, \
            "错误体冷启动分支未传「服务异常」词面（骨架与 pill 混轨）"
