# -*- coding: utf-8 -*-
"""fliggy 周边城市特价推荐 nearby（数据层主候选）：PC SSR 页 J_Nearby
模块（「周边城市特价推荐」，10-05/10-15 两代 dump 在场）——读者增量=
「邻近到达城市便宜多少」（样本 URC→NGB ￥600 vs URC→SHA ￥898，同
trendGo「换个日子飞多少钱」读者问句族）。采集=页面级 JS 采集器
（_CAL_JS 同律）+ _parse_nearby 逐点守卫；协议 7 元组
[日期,目的码,目的名,价,折扣词,公里数,锚城市] 挂当轮最低价行（trendGo
同槽同律，逐行重复=extra 膨胀）；消费端=航班名格 title 注记 + CSV
「周边特价」列（seatTilt/childPrice 零布局风险先例）。

附防退化钉：qunar PC cabinCode R2/R3/R4 春秋自有子舱码真值放行
（双渠道同指纹 100% 双证+价位带互锁 R4<R3<R2+tuniu 经济舱词面同现）
——勿加「单字符」守卫误杀。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_nearby_field.py -q
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.fliggy import FliggyCrawler  # noqa: E402
from crawlers.qunar import QunarCrawler  # noqa: E402


# ---- _parse_nearby：协议校验（_parse_cal_points 同律逐点守卫） ----
# 样本形态=10-15 dump 实证（J_Nearby 两目的：NGB 无折扣/NKG 1.8折）

def test_fliggy_nearby_protocol():
    raw = [["2026-10-15", "NGB", "宁波", 600, "", 150, "上海"],
           ["2026-10-15", "NKG", "南京", 600, "1.8折", 286, "上海"]]
    assert FliggyCrawler._parse_nearby(raw) == [
        ["2026-10-15", "NGB", "宁波", 600, "", 150, "上海"],
        ["2026-10-15", "NKG", "南京", 600, "1.8折", 286, "上海"]]


def test_fliggy_nearby_guards():
    # 坏点逐点弃：日期形不正/目的码非 iata3/目的名空/价越界（价带单源
    # 100-50000）/折扣词形坏/元素残缺——按「最坏输入」逐字段守
    raw = [["2026-10-15", "NGB", "宁波", 600, "", 150, "上海"],
           ["bad", "NGB", "宁波", 600, "", 150, "上海"],
           ["2026-10-15", "nb", "宁波", 600, "", 150, "上海"],
           ["2026-10-15", "NGB", "", 600, "", 150, "上海"],
           ["2026-10-15", "NGB", "宁波", 99, "", 150, "上海"],
           ["2026-10-15", "NGB", "宁波", 60000, "", 150, "上海"],
           ["2026-10-15", "NGB", "宁波", "abc", "", 150, "上海"],
           ["2026-10-15", "NGB", "宁波", 600, "五折", 150, "上海"],
           ["2026-10-15", "NGB", "宁波", 600]]
    assert FliggyCrawler._parse_nearby(raw) == [
        ["2026-10-15", "NGB", "宁波", 600, "", 150, "上海"]]
    # 全坏与非 list 输入→None（_parse_cal_points 同律）
    assert FliggyCrawler._parse_nearby(
        [["bad", "NGB", "宁波", 600, "", 150, "上海"]]) is None
    assert FliggyCrawler._parse_nearby([]) is None
    assert FliggyCrawler._parse_nearby(None) is None
    assert FliggyCrawler._parse_nearby("x") is None


# ---- 挂载：trendGo 同槽同律（当轮最低价行，无值不落键） ----

_FLIGGY_TXT = ("MU8369\n19:55\n01:25 第2天\n¥2522\n订票\n\n"
               "9C6927\n06:40\n11:55\n¥900\n订票")


def test_fliggy_nearby_attached_to_min_row():
    fs = FliggyCrawler._parse_pc_text(
        _FLIGGY_TXT, "2026-10-15",
        nearby=[["2026-10-15", "NGB", "宁波", 600, "", 150, "上海"]])
    lo = min(fs, key=lambda f: f["price"])
    assert lo["nearby"] == [
        ["2026-10-15", "NGB", "宁波", 600, "", 150, "上海"]]
    hi = max(fs, key=lambda f: f["price"])
    assert "nearby" not in hi


def test_fliggy_nearby_absent_without_module():
    # 页面无模块/采集失败不落键——行 schema 与既有轮全等
    fs = FliggyCrawler._parse_pc_text(_FLIGGY_TXT, "2026-10-15")
    assert fs and all("nearby" not in f for f in fs)


def test_fliggy_nearby_and_trendgo_coexist():
    # 同挂最低价行互不挤占（trendGo 既有挂载零回归）
    fs = FliggyCrawler._parse_pc_text(
        _FLIGGY_TXT, "2026-10-15", cal_pts=[["10-13", 930]],
        nearby=[["2026-10-15", "NGB", "宁波", 600, "", 150, "上海"]])
    lo = min(fs, key=lambda f: f["price"])
    assert lo["trendGo"] == [["10-13", 930]]
    assert lo["nearby"][0][1] == "NGB"


# ---- _NEARBY_JS 端到端回放：真实 dump 片段 set_content 直注
#      （file:// 快照回放三坑判例：直注是终局形态；禁外链脚本） ----

_NEARBY_HTML = """
<!doctype html><html><head><meta charset="utf-8"></head><body>
<div class="J_Nearby" data-spm="1998393583">
<div class="nearby"><h5>周边城市特价推荐</h5>
<dl class="near-list"><dt><span class="J_NearbyPhoneIcon" data-depcity="URC" data-depcityname="乌鲁木齐" data-arrcity="NGB" data-arrcityname="宁波" data-depdate="2026-10-15"><span class="phone-icon J_PhoneIcon" data-tooltip-type="pcToMobileNearby" data-depcity="URC" data-arrcity="NGB" data-depdate="2026-10-15"></span></span> 乌鲁木齐<em>→</em>宁波</dt><dd><b>10月15日</b> <span class="pi-price pi-price-sm"><i>¥</i>600</span> </dd><dd>上海 距 宁波 150 公里</dd><dd><a class="reserve J_ReserveNB" href="?tripType=0&amp;arrCity=NGB&amp;depDate=2026-10-15"> 查看航班 </a></dd></dl>
<dl class="near-list"><dt><span class="J_NearbyPhoneIcon" data-depcity="URC" data-depcityname="乌鲁木齐" data-arrcity="NKG" data-arrcityname="南京" data-depdate="2026-10-15"><span class="phone-icon J_PhoneIcon" data-tooltip-type="pcToMobileNearby" data-depcity="URC" data-arrcity="NKG" data-depdate="2026-10-15"></span></span> 乌鲁木齐<em>→</em>南京</dt><dd><b>10月15日</b> <span class="pi-price pi-price-sm"><i>¥</i>600</span> <span class="discount">1.8折</span> </dd><dd>上海 距 南京 286 公里</dd><dd><a class="reserve J_ReserveNB" href="?tripType=0&amp;arrCity=NKG&amp;depDate=2026-10-15"> 查看航班 </a></dd></dl>
</div></div>
</body></html>"""


def test_fliggy_nearby_js_replay_dump():
    pytest.importorskip("playwright",
                        reason="JS 端到端回放依赖 playwright")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失")
        b = p.chromium.launch()
        pg = b.new_page()
        pg.set_content(_NEARBY_HTML)
        raw = pg.evaluate(FliggyCrawler._NEARBY_JS)
        b.close()
    assert raw == [["2026-10-15", "NGB", "宁波", 600, "", 150, "上海"],
                   ["2026-10-15", "NKG", "南京", 600, "1.8折", 286, "上海"]]


# ---- qunar PC cabinCode 春秋子舱码真值放行（防退化钉） ----

_PC_CABIN = json.dumps({
    "ret": True, "code": 0, "data": {"flights": [
        {"code": "9C8845", "minPrice": "620", "transCity": "",
         "extparams": {},
         "binfo": {"airCode": "9C8845", "shortName": "春秋",
                   "depTime": "08:30", "arrTime": "13:50",
                   "date": "2026-10-15", "arrDate": "2026-10-15"},
         "binfo1": {"depTime": "08:30", "arrTime": "13:50",
                    "date": "2026-10-15", "arrDate": "2026-10-15",
                    "cabin": "R3"}}]}})


def test_qunar_pc_cabin_code_subcabin_passthrough():
    # R2/R3/R4=春秋自有子舱码真值（75+69 元素双渠道同指纹 100% 双证+
    # 价位带互锁+tuniu 舱名词面同现）——防未来「单字符守卫」误杀
    fl = QunarCrawler._parse_pc_flights(_PC_CABIN, "2026-10-15")
    assert fl and fl[0].get("cabinCode") == "R3"


# ---- webui 消费端源码锚（字符串在场锚；行为面归 uitest/真机） ----

def test_webui_nearby_whitelist_and_gate():
    import webui
    src = open(os.path.join(os.path.dirname(webui.__file__), "webui.py"),
               encoding="utf-8").read()
    # 白名单透传（无值不落→None 不占位）
    assert '"nearby": f.get("nearby")' in src
    # 词面单源互钉：_nb_txt 函数定义在场 + CSV 列头与行值同源
    # （列头词面与 _nb_txt 产出前缀一处手抄删改即红）
    assert 'function _nb_txt(f)' in src
    assert "'周边特价'" in src
    assert '_nb_txt(f),_rt_txt(f)].map(e2).join' in src
    # title 消费端双段钉（r268 Soldier P1/P2）：
    # 实效档=外层门含 nearby（门外漏 nearby=独有行 title 死路）+
    # 渲染链 he(_nb_txt(f)) 转义施加；禁复活=游离冒号形态
    # （`}":`+反引号 曾致全部 title 产出垃圾属性，node --check
    # 不可见、唯执行探针可捉——禁复活钉锁字节形态）
    assert ('f.distance!=null||(f.nearby&&f.nearby.length)'
            '||(f.trendRound&&f.trendRound.length))?` title="' in src)
    assert 'he(_nb_txt(f))' in src
    assert '(f.nearby&&f.nearby.length?' in src
    assert '}":' + '`' + ":''" not in src   # P2 禁复活：游离冒号形态
    # 禁复活二段：title 收尾游离右括号形态（`)}"` 与反引号之间夹 `)`）
    # ——修冒号时的残留变体，同为执行探针可捉、node --check 不可见
    assert (')}")' + '`') not in src
    # 实效档（r269 起 title 末段=trendRound 往返段，终锚随迁
    # test_roundrec_field）：`he(_nb_txt(f)):'')+` 之后必须恰接
    # `(f.trendRound`（段链顺序钉，防两段交换/断裂——段序决定
    # `｜` 前缀归属；三元收尾 `}` 已随末段移交，锚串不带 `}`）
    _anchor = "he(_nb_txt(f)):'')+"
    _at = src.find(_anchor)
    assert _at > 0
    assert src[_at + len(_anchor):].startswith('(f.trendRound')
