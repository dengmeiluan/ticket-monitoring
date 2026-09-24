# -*- coding: utf-8 -*-
"""v1.5.81 webui 回归（源码级钉，同 test_v180_webui.py 模式）。

- D-1 退改费三端消费：白名单透传 returnFee/changeFee（int 协议，-1
  「不可」如实保留）+ 价格格退改徽标（pretax 同位，词面单源 _rc_txt）
  + CSV「退改」列；推送 PNG 明细次行段容量红线 14 已满，推送侧零改动
- audit_v181 P2 六案：页脚 demo 哨兵 vdemo / 页脚端口硬编码（state 带
  svc 实际 host:port）/ 触屏隐藏键盘快捷键提示 / 价格列 🔥 定宽共线 /
  KPI 进度条达标满条+解码 title / .pbar·.pvx hover 过渡律

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v181_webui.py -q
"""


class TestWebuiV181Pins:
    """webui.py 源码级钉死。"""

    @staticmethod
    def _src():
        import webui as _w
        with open(_w.__file__, encoding="utf-8") as f:
            return f.read()

    # ---- D-1 退改费三端消费 ----

    def test_refund_whitelist_passthrough(self):
        """/api/state 载荷白名单透传 returnFee/changeFee（缺它=孤儿键）。"""
        src = self._src()
        assert '"returnFee": _int_or_none(f.get("returnFee"))' in src, \
            "白名单未透传 returnFee"
        assert '"changeFee": _int_or_none(f.get("changeFee"))' in src, \
            "白名单未透传 changeFee"

    def test_refund_badge_pretax_with_title(self):
        """价格格退改徽标（pretax 同位）+ title 说明语义（-1=不可办理）。"""
        src = self._src()
        assert "_rc_txt(f)" in src, "退改词面未走 _rc_txt 单源"
        i0 = src.index("_rc_txt(f)}")
        seg = src[max(0, i0 - 240):i0 + 40]
        assert "pretax" in seg, "退改徽标未复用 pretax 同位样式"
        assert "title=" in seg and "退" in seg and "不可" in seg, \
            "退改徽标缺 title 或未说明 -1 语义"

    def test_refund_wordface_minus1_and_free(self):
        """词面规则：双 0=免费退改；-1=不可退/不可改；有值=退￥N·改￥M。"""
        src = self._src()
        assert "免费退改" in src
        assert "'不可'+lbl" in src.replace('"', "'").replace('"', "'"), \
            "词面缺 -1 不可办理形态"
        i0 = src.index("function _rc_txt")
        seg = src[i0:i0 + 320]
        assert "returnFee===0" in seg and "changeFee===0" in seg, \
            "双 0 免费退改判定缺失"

    def test_refund_csv_column(self):
        """CSV「退改」列与徽标同词面单源（head+行值两处）。"""
        src = self._src()
        assert "'退改'" in src or "退改'" in src, "CSV head 缺退改列"
        assert "_rc_txt(f)" in src, "CSV 行值未走 _rc_txt 单源"

    # ---- audit P2 六案 ----

    def test_p2_footer_demo_sentinel(self):
        """页脚版本哨兵：demo 值不加 v 前缀（演示站不再出现 vdemo）。"""
        src = self._src()
        assert "s.version!=='demo'" in src, \
            "页脚 v 前缀未排除 demo 哨兵值"

    def test_p2_footer_port_dynamic(self):
        """页脚端口随实际监听（state 带 svc，模板不再硬编码 8765）。"""
        src = self._src()
        assert '"svc"' in src, "state 未携带实际 host:port"
        assert "本地服务 127.0.0.1:8765" not in src, \
            "页脚端口硬编码未清除"
        assert "s.svc" in src, "页脚未消费 svc 字段"

    def test_p2_footer_kbd_hidden_on_coarse(self):
        """触屏隐藏键盘快捷键提示（pointer:coarse 媒体块）。
        检测点改全文级：coarse 隐藏块已挪样式区尾（同选择器 ≤760
        块的层叠序钉在 test_v187_webui），邻位检测点失效。"""
        src = self._src()
        assert "kbdtips" in src, "快捷键提示段未挂 kbdtips 类"
        assert "@media(pointer:coarse){.kbdtips{display:none}}" in src, \
            "kbdtips 隐藏未挂 coarse 指针媒体查询"

    def test_p2_price_fire_fixed_width(self):
        """价格列 🔥 定宽占位（qual 行与非 qual 行 ￥ 共起点）。"""
        src = self._src()
        assert 'class="fire"' in src, "🔥 未改定宽占位 span"
        i0 = src.index(".price .fire{")
        seg = src[i0:i0 + 140]
        assert "width:19px" in seg, "fire 占位未定宽"
        assert "(f.qual?'🔥':'')" in src, "fire span 未条件承载 🔥"

    def test_p2_kpi_bar_hit_full_and_title(self):
        """KPI 进度条达标态满条（读的人先问能不能出手）+ title 解码。"""
        src = self._src()
        i0 = src.index('class="bar"')
        seg = src[i0:i0 + 320]
        assert "title=" in seg, "KPI bar 缺解码 title"
        assert "width:${hit?100" in seg.replace(" ", ""), \
            "达标态未满条（width 100%）"

    def test_p2_pbar_pvx_hover_transition(self):
        """脉冲柱/关闭钮 hover 过渡与全站 0.12s 家族同律。"""
        src = self._src()
        ip = src.index(".pbar{")
        seg_p = src[ip:ip + 260]
        assert "transition" in seg_p, ".pbar 缺 transition"
        ix = src.index(".pvx{")
        seg_x = src[ix:ix + 220]
        assert "transition" in seg_x, ".pvx 缺 transition"
