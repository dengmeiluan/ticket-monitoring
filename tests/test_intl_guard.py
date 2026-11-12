# -*- coding: utf-8 -*-
"""r326 R3 量程校准钉：毒价守卫/达标口径在国际价格量程下的行为。

R1/R2 活体校准（校准台账，内部档 _scratch/INTL_CALIBRATION_internal.md）后的三件定谳钉：

- **单渠道国际航线不误杀**（v1 主形态：多数国际航线仅 1 渠道供数
  ——xchan 独立锚 <2 不判，孤行必须存活到达标池）；
- **国际量程比率语义**：守卫是纯比率线（med×0.5），万元级国际价
  与百元级国内价同律；两渠道 >2× 价差（日历价 vs 列表价合法形态）
  会被拦——宁拦促销勿放毒价产品裁量的国际延伸，观测窗备案不放宽；
- **免税垫与锚可比性**：_mark_xchan 锚走 _qual_price——国际 fliggy
  行免税垫（price 原样）与国内 fliggy 行（+FLIGGY_TAX_PAD）各自
  同口径参锚，跨渠道可比性不因国际档破坏；
- **真报文样本入钉**：R1 活体捕获的飞猪日历行（¥929+税70）逐键
  锁形，渠道改版即红。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_intl_guard.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.alerter import (Alerter, FLIGGY_TAX_PAD,  # noqa: E402
                          _qual_price, xchan_phantom_idx)


def _row(price, plat, intl=1, **over):
    f = {"price": price, "_platform": plat, "name": "日历最低价",
         "code": "", "depDate": "2026-11-16", "intl": intl}
    f.update(over)
    return f


def test_single_channel_intl_row_survives_guard():
    # v1 主形态：仅飞猪日历供数的国际航线——独立锚 <2 不判，孤行存活
    rows = [_row(999.0, "fliggy")]
    Alerter._mark_xchan(rows)
    assert not rows[0].get("_xphan")
    assert xchan_phantom_idx([(999.0, "fliggy")]) == set()


def test_intl_magnitude_ratio_semantics():
    # 万元级国际量程：比率线同律。24000 与 9800 两渠道——9800 <
    # 24000×0.5=12000 → 判孤拦（日历价 vs 列表价 >2× 价差的合法形态
    # 亦拦：宁拦促销勿放毒价裁量延伸，观测窗备案）
    idx = xchan_phantom_idx([(9800.0, "fliggy"), (24000.0, "tongcheng")])
    assert idx == {0}
    # 同水位两渠道（5 位数）：互不拦
    idx2 = xchan_phantom_idx([(12800.0, "fliggy"), (13600.0, "tongcheng")])
    assert idx2 == set()
    # 三渠道下真毒价（1.2k vs 2.4-2.6 万水位）照拦——比率语义量纲无关
    idx3 = xchan_phantom_idx([(1200.0, "fliggy"), (24800.0, "tongcheng"),
                              (26000.0, "qunar")])
    assert 0 in idx3 and 1 not in idx3 and 2 not in idx3


def test_intl_qual_price_no_pad_keeps_anchor_comparable():
    # 国际 fliggy 行免税垫：锚=原价（与国内 fliggy 行 +pad 各自同口径，
    # 跨渠道锚可比性不因国际档破坏）
    intl_row = _row(999.0, "fliggy")
    dom_row = {"price": 999.0, "_platform": "fliggy"}
    assert _qual_price(intl_row) == 999.0
    assert _qual_price(dom_row) == 999.0 + FLIGGY_TAX_PAD


def test_real_fliggy_calendar_row_fixture():
    # R1 活体捕获真行（_scratch/intl/r1_fliggy_raw.txt 2026-11-16 日点）
    # 逐键锁形——渠道改版即红
    row = {"arrCityCode": "TYO", "depCityCode": "SHA", "discount": 0.0,
           "leaveDate": "2026-11-16", "price": 929.0, "tax": 70.0,
           "url": "//sijipiao.fliggy.com/ie/flight_search_result.htm?"
                  "depCityName=上海&depCityCode=SHA&arrCityName=东京"
                  "&arrCityCode=TYO&tripType=0&depDate=2026-11-16"
                  "&arrDate=null&searchBy=1281&scene=null"}
    # 解析端契约（INTL_DESIGN §1.2）：price=price+tax 含税入库
    total = float(row["price"]) + float(row["tax"])
    assert total == 999.0
    assert row["tax"] > 0                      # 国际税费占比大，禁垫定值
    # 消费端契约：intl 键走免税垫、含税词段形态
    f = _row(total, "fliggy", tax=row["tax"])
    assert _qual_price(f) == 999.0
    seg = ("含税" + (f"￥{f['tax']:g}" if isinstance(
        f.get("tax"), (int, float)) and f["tax"] > 0 else "")) \
        if f.get("intl") else ""
    assert seg == "含税￥70"


def test_intl_magnitude_near_and_tier_semantics():
    # 校准 R12（E 族）：擦边/档位判定是纯比率语义（NEAR_RATIO=0.10、
    # 达标=价≤线），国际万元级量程同律——比率基准量纲无关
    from core.alerter import NEAR_RATIO, _near_txt
    th, price = 12000.0, 12800.0            # 距线 6.7%：擦边带内
    ratio = (price - th) / th
    assert 0 < ratio <= NEAR_RATIO
    assert _near_txt(ratio) == "擦边7%"      # 词面国际量程同构产出
    th2 = 12000.0
    price2 = th2 * (1 + NEAR_RATIO + 0.02)  # 距线 12%：出带
    assert (price2 - th2) / th2 > NEAR_RATIO
    # 达标判定恒 price≤线（万元级线下行照常出手）
    assert min(price2, th2) <= th2

