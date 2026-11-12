# -*- coding: utf-8 -*-
"""r928：app_qunar「档位残留」导致国内城市永远选不上（成功率 26% 的真因）。

数据（最近三天日志，2026-11-02~04）：

======================  ======  ========  ==========
渠道                     轮数    成功率    零结果
======================  ======  ========  ==========
ctrip / fliggy / 同程    235/82/178  100%     0
途牛                     135     98%       2
app_zhixing              192     81%      36
qunar（H5） **234**  **50%**  **117**
**app_qunar（App）** **170**  **26%**  **125**
======================  ======  ========  ==========

两个 qunar 贡献了全部 280 次零结果的 86%，其中 app_qunar 最差。

失败现场（`debug/scene/*_setcity-timeout-arr.txt`）清一色：

    选择目的地 / 搜索国家/城市/景点等 / 国内·港澳台 | 国际
    qd_city_rlTab2                      ← **停在「国际」档**
    qd_tab_name  东南亚 / 日韩 / 欧洲 …
    [app_qunar] 设到达城市失败：海口     ← 国内城市在国际列表里找不到

根因：上一轮跑完**国际航线**后城市页停在「国际」档（跨轮残留），
下一轮国内航线搜"海口"时国际列表里根本没有它 → 等满 45s/12 帧 →
`setcity-timeout-arr`。

代码里原来有一句"**不需要碰「国内/国际」档位**"——那是一半对的：
**无条件**点档位确实有害（22:06 直接回首页、22:08 落到特价页），
所以本修复刻意做成**有条件**：只在「已经输入过、却一条结果都没有」时
切一次档位（`_tab_tried` 保证只切一次），切完重新搜。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r928_qunar_city_tab.py -q
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers import app_qunar as q  # noqa: E402


# ---------------------------------------------------------------------------
# 1. 国际/国内判定
# ---------------------------------------------------------------------------
def test_domestic_cities_are_not_intl():
    for c in ("海口", "上海", "北京", "成都"):
        assert q._looks_intl_city(c) is False, c


def test_foreign_cities_are_intl():
    for c in ("伦敦", "东京", "曼谷", "新加坡"):
        assert q._looks_intl_city(c) is True, c


def test_airport_code_normalized():
    """机场码要先归一成城市再判（NRT/PEK 这类）。"""
    assert q._looks_intl_city("NRT") is True          # 成田 = 国际
    assert q._looks_intl_city("PEK") is False         # 首都 = 国内


def test_empty_city_is_not_intl():
    assert q._looks_intl_city("") is False
    assert q._looks_intl_city(None) is False


# ---------------------------------------------------------------------------
# 2. 档位按钮查找
# ---------------------------------------------------------------------------
_TABS = ('<node resource-id="com.Qunar:id/atom_flight_tab_item_tv" '
         'text="国内/港澳台" bounds="[180,257][310,292]" />'
         '<node resource-id="com.Qunar:id/atom_flight_tab_item_tv" '
         'text="国际" bounds="[671,257][719,292]" />')


def test_find_city_tab():
    assert q._find_city_tab(_TABS, "国内") is not None
    assert q._find_city_tab(_TABS, "国际") is not None
    assert q._find_city_tab(_TABS, "欧洲") is None
    assert q._find_city_tab("", "国内") is None


# ---------------------------------------------------------------------------
# 3. 选中态（两种表达都要认）
# ---------------------------------------------------------------------------
def test_tab_selected_by_attribute():
    xml = ('<node resource-id="com.Qunar:id/atom_flight_tab_item_tv" '
           'text="国内/港澳台" selected="true" bounds="[180,257][310,292]" />'
           + _TABS)
    assert q._tab_is_selected(xml, "国内") is True
    assert q._tab_is_selected(xml, "国际") is False


def test_tab_selected_by_underline():
    """真机上 `_nodes()` 会丢掉 selected 属性，只剩下划线可判。"""
    xml = (_TABS + '<node resource-id="com.Qunar:id/atom_flight_tab_item_line" '
           'bounds="[677,296][713,301]" />')
    assert q._tab_is_selected(xml, "国际") is True
    assert q._tab_is_selected(xml, "国内") is False


def test_tab_selected_false_when_no_marker():
    assert q._tab_is_selected(_TABS, "国内") is False
    assert q._tab_is_selected("", "国内") is False


# ---------------------------------------------------------------------------
# 4. 自愈逻辑存在且只做一次（源码钉）
# ---------------------------------------------------------------------------
def test_self_heal_is_conditional_and_once():
    """必须是"有条件 + 只一次"，不能退回无条件点档位（那已被证有害）。"""
    src = io.open(os.path.join(ROOT, "crawlers", "app_qunar.py"),
                  encoding="utf-8").read()
    # 条件：输入过但没结果
    assert "hit is None and typed and not _tab_tried" in src
    # 只做一次
    assert "_tab_tried = False" in src
    assert "_tab_tried = True" in src
    # 切完允许重新输入
    assert "typed = False" in src


# ---------------------------------------------------------------------------
# 5. **真实失败现场**回归（debug/scene/qunar_app_*_setcity-timeout-arr.txt）
# ---------------------------------------------------------------------------
_REAL_SCENE = (
    '<node resource-id="com.Qunar:id/atom_flight_tab_item_tv" '
    'text="国内/港澳台" bounds="[180,257][310,292]" />'
    '<node resource-id="com.Qunar:id/atom_flight_tab_item_tv" '
    'text="国际" bounds="[671,257][719,292]" />'
    '<node resource-id="com.Qunar:id/atom_flight_tab_item_line" '
    'bounds="[677,296][713,301]" />'
    '<node resource-id="com.Qunar:id/qd_city_rlTab2" '
    'bounds="[0,310][900,1600]" />'
)


def test_real_scene_was_on_intl_tab():
    """2026-11-02 19:02 真实现场：下划线在「国际」下 → 当时停在国际档。

    而那一轮要选的是「海口」（国内城市）——所以必然超时。
    这条用例就是事故现场本身，防止判据以后再漂。
    """
    assert q._tab_is_selected(_REAL_SCENE, "国际") is True
    assert q._tab_is_selected(_REAL_SCENE, "国内") is False
    assert q._looks_intl_city("海口") is False     # 目标是国内城市
    # → 修复动作：切到国内档
    assert q._find_city_tab(_REAL_SCENE, "国内") is not None


def test_real_scene_domestic_target_mismatch():
    """判定组合：目标国内 + 当前国际 → 必须触发一次切档。"""
    want = q._TAB_INTL if q._looks_intl_city("海口") else q._TAB_DOMESTIC
    assert want == q._TAB_DOMESTIC
    assert q._tab_is_selected(_REAL_SCENE, want) is False   # 不在目标档 → 要切
