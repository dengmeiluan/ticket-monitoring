# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r253_webui.py
- tests/test_r320_webui.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import datetime as dt
import os
import sys
import unittest


# ---- merged from tests/test_r253_webui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _page():
    return webui_full_src()


class TestDemoConfigSingleSource:
    def test_no_hardcoded_demo_date(self):
        """P1-1：demo /api/config 不再硬编码过期日期（与演示数据脱节，
        配置页与其余视图互相矛盾）。注：demo 合成推送日志/健康时间线
        里的叙事日期是合成样本文本，不属本钉面。"""
        src = _page()
        assert '"dates": ["2026-09-25"]' not in src

    def test_demo_config_reuses_demo_routes(self):
        """demo 分支复用 core.demo.demo_routes 单源（滚动日期）。"""
        src = _page()
        assert "from core.demo import demo_routes as _demo_routes" in src
        assert "for r in _demo_routes()" in src

    def test_demo_routes_dates_are_future(self):
        """演示数据日期恒在未来（滚动生成）——单源本身的行为锚。"""
        from core.demo import demo_routes
        today = dt.date.today()
        for r in demo_routes():
            for d in r["dates"]:
                assert dt.date.fromisoformat(d) >= today, d


class TestTouchTargets:
    def test_vw_tj_base_hotspot_not_overridden(self):
        """P2-1（Soldier 复审改向）：↗/📈 热区 base 外扩（既有达标，
        横向 33/32 备案豁免）不得被触控块覆写收窄——覆写曾把触屏
        横向热区压到 ~20px（低于 24px 下限）。"""
        src = _page()
        assert src.count("a.vw::after,.tj::after") == 0,             "coarse 块不得覆写 vw/tj base 外扩"
        # base 外扩仍在（origin/main 既有两处声明）
        assert "a.vw::after" in src and ".tj::after" in src

    def test_flab_switch_scope_filled(self):
        """P2-1：#fnostale 的 .flab 槽位补进 switch 外扩家族
        （.srow/.fbar/.glcell 作用域漏收家族）。"""
        src = _page()
        assert src.count(".flab .switch::before{content:'';position:absolute;inset:-8px}") == 2


class TestTwScrollHint:
    def test_tw_hint_css(self):
        """P2-2：.tw 右缘渐变（xhint 同轨）+ 点亮态。"""
        src = _page()
        assert ".tw::after{content:'';position:absolute;top:0;right:0;bottom:0;width:12px;" in src
        assert ".tw.xhint::after{opacity:1}" in src
        # ::after 定位前提：容器 relative
        assert ".tw{overflow:auto;max-height:clamp(430px,52vh,780px);border-radius:var(--r10);border:1px solid var(--line);position:relative}" in src

    def test_tw_judged_at_all_switch_points(self):
        """P2-2：量纲判定挂齐「变得可见/几何变化/行渲染」三类切换点
        （display:none 容器量纲全零——只挂数据渲染点罩不住）。"""
        src = _page()
        # details 切换点（showMonTab）
        assert "document.querySelectorAll('#montab-details .tabs,.tw')" in src
        # 健康渲染批与 resize 批（既有容器组补 .tw）
        assert src.count("#opscard .opsbtns,.tw") >= 2
        # table() 行渲染后
        assert "document.querySelectorAll('.tw').forEach(x=>" in src


class TestSparseRingDot:
    def test_ring_center_series_dot(self):
        """P2-3：分档环绘制后环心补系列色小点（环内 card 不透明填充
        曾盖住稀疏系列点，图例色票无所指）。"""
        src = _page()
        assert "ctx.arc(X(xf(i)),Y(v),1.4,0,7)" in src
        # 补点须消费 series 系列色参数（color），非 card/档位色
        assert "ctx.fillStyle=color;ctx.fill();" in src


class TestKlineClamp:
    def test_first_bucket_clamped(self):
        """P3-1：K线蜡烛中心双端钳位（首桶左半曾越绘图区压 Y 轴带）。"""
        src = _page()
        assert "Math.max(L+cw/2,Math.min(W-R-cw/2,X(xf(i))+off))" in src


class TestErrorStateWording:
    def test_service_error_updated_blank(self):
        """P3-2：冷启动服务异常时 #updated 留空（pill 单源承载错误
        词面，同屏双份「服务异常」曾互相复读）。"""
        src = _page()
        assert "else{$('updated').textContent='';_markStale('服务异常');}" in src


class TestShareAirlineRenderGate:
    def test_stl_independent_gate(self):
        """D-2 渲染门：stl 段非共享行独立「承运·」档（原门只在
        shareCarrier 在场拼接——非共享中转行落键即孤儿）。"""
        src = _page()
        assert "(f.shareAirline?'承运·'+he(f.shareAirline):'')" in src

    def test_csv_nonshared_branch(self):
        """D-2 CSV「实际承运」列补非共享分支。"""
        src = _page()
        assert "(f.shareCarrier?(f.shareAirline?f.shareAirline+f.shareCarrier:f.shareCarrier):(f.shareAirline||''))" in src


# ---- merged from tests/test_r320_webui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(rel):
    with open(os.path.join(_ROOT, rel), encoding="utf-8") as f:
        return f.read()


class TestStorageSpecialDeals(unittest.TestCase):
    def test_roundtrip_and_purge(self):
        import tempfile
        from core.storage import PriceStorage
        db = os.path.join(tempfile.mkdtemp(prefix="r320_"), "t.db")
        st = PriceStorage(db)
        st.save_special_deal("ctripbd", "SHA", "LHW", "2026-10-20",
                             200.0, 200.0)
        st.save_special_deal("ctrip", "SHA", "KMG", "2026-10-25",
                             382.0, 382.0, ret_date="2026-10-27",
                             ret_price=410.0)
        rows = st.recent_specials(10)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["to_city"], "KMG")   # id 倒序
        self.assertEqual(rows[0]["ret_date"], "2026-10-27")
        self.assertEqual(rows[0]["ret_price"], 410.0)
        # purge 不误删（fetched_at=now）
        st.purge(days=14)
        self.assertEqual(len(st.recent_specials(10)), 2)


class TestSourcePins(unittest.TestCase):
    def test_webui_drawer_and_predicate(self):
        src = webui_full_src()
        # 抽屉控件（行属性族 + 更多筛选折叠区）
        for i in ('alchips', 'pschips', 'cabchips', 'ffew', 'fnostop',
                  'fnoshare', 'fsafe', 'flaymin', 'flaymax',
                  'morefltBtn', 'morefltN', 'fdurmin', 'fdurmax',
                  'fprate', 'fage', 'fbag', 'fmeal', 'fnolcc', 'fcross',
                  'fchild'):
            self.assertIn(f'id="{i}"', src, i)
        # 谓词（行属性 7 维 + 更多筛选 8 维 + 舱位）；航司键 r324 改
        # 码首段单源（词形漂移拆片根治），钉面随行演进改写
        for s in ('FLT.airlines.size&&!FLT.airlines.has(carrierKeyOf(f))',
                  'if(FLT.few&&!(f.fewTicket||(f.leftTickets>0&&f.leftTickets<10)))return false',
                  'if(FLT.nostop&&f.stop)return false',
                  'if(FLT.noshare&&(f.shareCarrier||f.shareAirline))return false',
                  'if(FLT.cross&&!(Number(f.crossDayN)>0)&&!String(f.cross||\'\').trim())return false',
                  'if(FLT.safe&&(f.agePolicy||f.riskPolicy||f.lurePrice!=null||f.ticketRisk))return false',
                  'if((FLT.laymin||FLT.laymax)&&f.transfer){const m=f.layoverM',
                  'if(FLT.durmin&&(!f.durM||f.durM<FLT.durmin))return false',
                  'if(FLT.durmax&&(!f.durM||f.durM>FLT.durmax))return false',
                  'if(FLT.prate&&(f.prate==null||f.prate<FLT.prate))return false',
                  'if(FLT.bag&&!_hasFreeBag(f))return false',
                  'if(FLT.meal&&!f.meal)return false',
                  'if(FLT.nolcc&&f.lcc)return false',
                  'if(FLT.cross&&!(Number(f.crossDayN)>0)&&!String(f.cross||\'\').trim())return false',   # 跨天=crossDayN 或文本 cross（两源同判）
                  'if(FLT.child&&f.childPrice==null)return false',
                  # r329 M-1 起筛选门带空值放行（cabinOf 连串档返回
                  # 空串=缺维度行不被任何舱位档静默滤除）
                  'if(FLT.cabins.size&&cabinOf(f)&&!FLT.cabins.has(cabinOf(f)))return false'):
            self.assertIn(s, src, s)
        # 自适应显隐（区分度门）+ 渐进披露
        self.assertIn('vis[el.dataset.flt]', src)
        self.assertIn('function togMoreFlt()', src)
        self.assertIn('function moreFltActive()', src)
        # 持久化快照
        self.assertIn('airlines:[...FLT.airlines]', src)
        self.assertIn('dmin:FLT.durmin||0', src)
        self.assertIn('if(Array.isArray(j.airlines))FLT.airlines=new Set(j.airlines);', src)

    def test_specials_card_wiring(self):
        src = webui_full_src()
        self.assertIn('"/api/specials"', src)
        self.assertIn('id="spcard"', src)
        self.assertIn('async function spCard(', src)
        self.assertIn('spCard();', src)   # render 挂点
        self.assertIn("还没有核实通过的特价", src)   # 空态教学词

    def test_main_records_verified_deals(self):
        src = _src("main.py")
        self.assertIn("storage.save_special_deal(d.src, d.from_code,",
                      src)
        self.assertIn("与推送正交", src)

# ---- __main__ from tests/test_r320_webui.py ----

if __name__ == "__main__":
    unittest.main()
