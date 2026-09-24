# -*- coding: utf-8 -*-
"""v1.5.86 webui 三端同轮钉。

① tuniu childPrice/infantPrice 消费端补齐(渠道调研:爬虫已采、
   webui 白名单无出口的采集-消费缺口):白名单 float 协议透传
   (儿童票半价可能出现 X.5,_int_or_none 截断丢 5 角——_num_or_none
   float 转写)+渲染门=航班名格悬停 title 注记 + CSV「儿童/婴儿」列
   (明细次行段容量红线 14 已满不加段元素;title/CSV 零布局风险,
   seatTilt 先例)。
② qunar 退改费「当前档」口径注明(调研语义结论:渠道只下发
   当前时点所落阶梯档,非全程恒定费率——价格格退改徽标 title 补
   语义,防「退改费恒定」误读)。

运行:PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v186_webui.py -q
"""


class TestWebuiChildFare:
    @staticmethod
    def _src():
        import webui as _w
        with open(_w.__file__, encoding="utf-8") as f:
            return f.read()

    def test_whitelist_passthrough_num(self):
        src = self._src()
        # 白名单透传:float 协议转写(_num_or_none;儿童半价 X.5 不截断)
        assert '"childPrice": _num_or_none(f.get("childPrice"))' in src, \
            "webui 白名单缺 childPrice 透传(float 协议)"
        assert '"infantPrice": _num_or_none(f.get("infantPrice"))' in src, \
            "webui 白名单缺 infantPrice 透传(float 协议)"

    def test_num_or_none_helper(self):
        src = self._src()
        # float 协议帮手:_int_or_none 同型(脏值→None 前端不占位)
        assert "def _num_or_none(v):" in src, "_num_or_none 帮手缺"
        i0 = src.index("def _num_or_none(v):")
        assert "float(v)" in src[i0:i0 + 200], "_num_or_none 未用 float 转写"

    def test_name_cell_title_annotation(self):
        src = self._src()
        # 渲染门:航班名格悬停 title 注记儿童/婴儿价(有值才注)
        assert "儿童价" in src and "childPrice" in src, \
            "航班名 title 缺儿童价注记"
        assert "婴儿价" in src and "infantPrice" in src, \
            "航班名 title 缺婴儿价注记"

    def test_name_cell_title_gate_covers_child_fare(self):
        src = self._src()
        # 外层渲染门必须把童婴价纳入:labels/labelNote/bizPrice 三键
        # 全空(tuniu 窄体无公务舱多数形态、qunar H5)时童婴价仍可独立
        # 成注——门漏扩=注记段整段不渲染(内层分隔符按独立成注设计,
        # 内外门自相矛盾的功能空转形态)
        i0 = src.index('<td${((f.labels||f.labelNote||f.bizPrice!=null)')
        seg = src[i0:i0 + 140]
        assert "f.childPrice!=null" in seg and "f.infantPrice!=null" in seg, \
            "航班名 title 外层渲染门未纳入童婴价(三键全空形态整段不渲染)"

    def test_csv_column(self):
        src = self._src()
        # CSV「儿童/婴儿」列:表头尾部追加(既有列序零位移)
        assert "'儿童/婴儿'" in src, "CSV 表头缺「儿童/婴儿」列"
        i0 = src.index("改期最低")
        assert "childPrice" in src[i0:i0 + 1600], \
            "CSV 行值缺 childPrice 消费(表头后近邻)"


class TestWebuiRefundCurrentTier:
    @staticmethod
    def _src():
        import webui as _w
        with open(_w.__file__, encoding="utf-8") as f:
            return f.read()

    def test_price_badge_title_declares_tier(self):
        src = self._src()
        # 价格格退改徽标 title:注明「当前档位」语义(调研结论 N8:
        # qunar 渠道仅下发当前时点阶梯档,起飞前分档变动)
        assert "当前档位" in src, "退改徽标 title 缺当前档语义注明"


class TestWebuiV186Audit:
    """WebUI 审计 P2×5 落地钉(布局/自适应/交互打磨)。"""

    @staticmethod
    def _src():
        import webui as _w
        with open(_w.__file__, encoding="utf-8") as f:
            return f.read()

    def test_p2_1_coarse_901_touch_checklist(self):
        src = self._src()
        # >901px coarse 触控块补齐姊妹块清单(.cnav/.hbtn/输入 38px/
        # switch 热区/16px 字号)——iPad Pro 横屏触控基准欠账
        i0 = src.index("@media(pointer:coarse) and (min-width:901px){")
        seg = src[i0:i0 + 1400]
        for needle in (".cnav{padding:10px 14px}",
                       ".hbtn{min-height:36px;min-width:36px}",
                       ".switch::before{content:'';position:absolute;inset:-8px}",
                       "font-size:16px"):
            assert needle in seg, f"901+ 触控块缺 {needle}"

    def test_p2_2_ssub_wrap_at_760(self):
        src = self._src()
        # 「用时」尾段截断带 391-509px:ssub 放行换行上提到 ≤760 档
        assert "@media(max-width:760px){.stat .ssub{white-space:normal}}" in src, \
            "≤760 档缺 ssub 换行放行"

    def test_p2_3_hdmeta_wrap_at_900(self):
        src = self._src()
        # 生产态(cdt 倒计时在场)窄机临界溢出:≤900 补 flex-wrap
        assert "@media(max-width:900px){.hdmeta{flex-wrap:wrap}}" in src, \
            "≤900 档缺 hdmeta 折行"

    def test_p2_4_resize_rejudge_xhint(self):
        src = self._src()
        # resize 跨 1024 几何变化点重判健康格滚动暗示(showMonTab 同式)
        i0 = src.index("window.addEventListener('resize'")
        assert "xhint" in src[i0:i0 + 500], "resize 回调缺 xhint 重判"

    def test_p2_5_kbdtips_margin_not_inline(self):
        src = self._src()
        # 内联 margin-left:14px 在 ≤760 独立成行后造成右偏——
        # 挪为基础 CSS(媒体块 margin 简写可覆写),内联清零
        assert 'class="kbdtips" style=' not in src, \
            "kbdtips 内联 margin 残留"
        assert ".kbdtips{margin-left:14px}" in src, "kbdtips 基础 margin 缺"
