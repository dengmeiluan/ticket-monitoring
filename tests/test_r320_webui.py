# -*- coding: utf-8 -*-
"""r320：明细行属性筛选族（7 维）+ 特价雷达卡（概览）+ /api/specials。

- 筛选扩展：航司/机型 chips（空集=全部，聚合自全量行，不存在键自净）、
  余票紧张/排除经停/排除共享/隐藏限购高风险四开关、中转时长区间
  （仅中转行生效，layoverM 缺失行剔除——无时长数据无法判定）；
  FLT 快照持久化（saveUI/loadUI 随同排筛选族）。
- 特价雷达：special_deals 留痕（核实通过即记，与推送正交——免打扰/
  无通道形态控制台仍可见）+ /api/specials 轻端点 + 概览卡（空态教学/
  请求失败静默藏卡）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r320_webui.py -q
"""
import os
import sys
import unittest

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
        src = _src("webui.py")
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
        src = _src("webui.py")
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


if __name__ == "__main__":
    unittest.main()
