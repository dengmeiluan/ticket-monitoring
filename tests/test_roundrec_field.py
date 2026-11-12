# -*- coding: utf-8 -*-
"""fliggy 往返程推荐 trendRound（数据层主候选）：PC SSR 页 J_RoundRecommend
模块（「往返程 推荐」，10-05/10-06/10-15 三代 dump 在场，条目 1/5/1）——
读者增量=「往返一起订多少钱」（打包价 vs 两张单程；trendGo 换日子/
nearby 换目的地同族第三读者问句）。采集=页面级 JS 采集器（_NEARBY_JS
同律，模块静态不随虚拟列表销毁）+ _parse_round 逐点守卫；协议 5 元组
[去程日期,返程日期,价,去程码,返程码] 挂当轮最低价行（trendGo/nearby
同槽第三兄弟，逐行重复=extra 膨胀）；消费端=航班名格 title 注记 + CSV
「往返推荐」列（_nb_txt 零布局风险先例）；推送面零消费（r268 nearby
五点论证同律：次行容量红线+页面级模块挂航班行语义错配+单渠道孤源）。

fixture 按 10-15/10-06 dump 实证形态构造：结构化载体=li 内
span.J_ReturnPhoneIcon 的 data-depdate/retdate/depcity/arrcity 槽
（城市名槽为 URL 编码形态——码槽明文，名字槽不采），价=span.pi-price
innerText。运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest
tests/test_roundrec_field.py -q
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.fliggy import FliggyCrawler  # noqa: E402


# ---- _parse_round：协议校验（_parse_nearby 同律逐点守卫） ----
# 样本形态=10-15 dump 实证（去 10-16 返 10-18 ￥1239）

def test_fliggy_round_protocol():
    raw = [["2026-10-16", "2026-10-18", 1239, "URC", "SHA"],
           ["2026-10-09", "2026-10-11", 1510, "urc", "SHA"]]
    assert FliggyCrawler._parse_round(raw) == [
        ["2026-10-16", "2026-10-18", 1239, "URC", "SHA"],
        ["2026-10-09", "2026-10-11", 1510, "URC", "SHA"]]


def test_fliggy_round_guards():
    # 坏点逐点弃：去/返日期形不正/码非 iata3/价越界（价带单源
    # 100-50000）/返程早于去程/元素残缺——按「最坏输入」逐字段守
    raw = [["2026-10-16", "2026-10-18", 1239, "URC", "SHA"],
           ["bad", "2026-10-18", 1239, "URC", "SHA"],
           ["2026-10-16", "x", 1239, "URC", "SHA"],
           ["2026-10-16", "2026-10-18", 1239, "UR", "SHA"],
           ["2026-10-16", "2026-10-18", 1239, "URC", "S1A"],
           ["2026-10-16", "2026-10-18", 99, "URC", "SHA"],
           ["2026-10-16", "2026-10-18", 60000, "URC", "SHA"],
           ["2026-10-16", "2026-10-18", "abc", "URC", "SHA"],
           ["2026-10-18", "2026-10-16", 1239, "URC", "SHA"],
           ["2026-10-16", "2026-10-18", 1239, "URC"]]
    assert FliggyCrawler._parse_round(raw) == [
        ["2026-10-16", "2026-10-18", 1239, "URC", "SHA"]]
    # 全坏与非 list 输入→None（_parse_nearby 同律）
    assert FliggyCrawler._parse_round(
        [["bad", "x", 1239, "URC", "SHA"]]) is None
    assert FliggyCrawler._parse_round([]) is None
    assert FliggyCrawler._parse_round(None) is None
    assert FliggyCrawler._parse_round("x") is None


# ---- 挂载：trendGo/nearby 同槽第三兄弟（当轮最低价行，无值不落键） ----

_FLIGGY_TXT = ("MU8369\n19:55\n01:25 第2天\n¥2522\n订票\n\n"
               "9C6927\n06:40\n11:55\n¥900\n订票")


def test_fliggy_round_attached_to_min_row():
    fs = FliggyCrawler._parse_pc_text(
        _FLIGGY_TXT, "2026-10-15",
        round_pts=[["2026-10-16", "2026-10-18", 1239, "URC", "SHA"]])
    lo = min(fs, key=lambda f: f["price"])
    assert lo["trendRound"] == [
        ["2026-10-16", "2026-10-18", 1239, "URC", "SHA"]]
    hi = max(fs, key=lambda f: f["price"])
    assert "trendRound" not in hi


def test_fliggy_round_absent_without_module():
    # 页面无模块/采集失败不落键——行 schema 与既有轮全等
    fs = FliggyCrawler._parse_pc_text(_FLIGGY_TXT, "2026-10-15")
    assert fs and all("trendRound" not in f for f in fs)


def test_fliggy_round_coexist_with_trendgo_nearby():
    # 三兄弟同挂最低价行互不挤占（trendGo/nearby 既有挂载零回归）
    fs = FliggyCrawler._parse_pc_text(
        _FLIGGY_TXT, "2026-10-15", cal_pts=[["10-13", 930]],
        nearby=[["2026-10-15", "NGB", "宁波", 600, "", 150, "上海"]],
        round_pts=[["2026-10-16", "2026-10-18", 1239, "URC", "SHA"]])
    lo = min(fs, key=lambda f: f["price"])
    assert lo["trendGo"] == [["10-13", 930]]
    assert lo["nearby"][0][1] == "NGB"
    assert lo["trendRound"][0][2] == 1239


# ---- _ROUND_JS 端到端回放：真实 dump 片段 set_content 直注
#      （file:// 快照回放三坑判例：直注是终局形态；禁外链脚本） ----

_ROUND_HTML = """
<!doctype html><html><head><meta charset="utf-8"></head><body>
<div class="J_RoundRecommend" data-spm="1998550846"> <div class="round-recommend"> <h5><strong>往返程</strong> 推荐</h5> <div class="return-recommend-route"> <div class="return-recommend-city city-left">乌鲁木齐</div> <s>⇋</s> <div class="return-recommend-city city-right">上海</div> </div> <ul class="J_RecommendItem">  <li class="round-recommend-item"> <a href="javascript:void(0);" data-jump-url="/flight_search_result.htm?&amp;tripType=1&amp;depCity=SHA&amp;depDate=2026-10-16&amp;arrCity=URC&amp;arrDate=2026-10-18" class="clearfix" target="_top"> <div class="return-recommend-price"> <span class="J_ReturnPhoneIcon" data-depcity="URC" data-depcityname="%E4%B9%8C%E9%B2%81%E6%9C%A8%E9%BD%90" data-arrcity="SHA" data-arrcityname="%E4%B8%8A%E6%B5%B7" data-depdate="2026-10-16" data-retdate="2026-10-18">  <span class="phone-icon  J_PhoneIcon" data-tooltip-type="pcToMobileReturn" data-depcity="URC" data-depdate="2026-10-16" data-retdate="2026-10-18"></span>  </span> <span class="pi-price"><i>¥</i>1239</span> </div> <div class="return-recommend-date"> <div> 2026-10-16&nbsp;&nbsp;<span class="week-info">星期五</span>&nbsp;&nbsp;<span class="round-type">去程</span> </div> <div> 2026-10-18&nbsp;&nbsp;<span class="week-info">星期天</span>&nbsp;&nbsp;<span class="round-type">返程</span> </div> </div> </a> </li>  <li class="round-recommend-item"> <a href="javascript:void(0);" class="clearfix" target="_top"> <div class="return-recommend-price"> <span class="J_ReturnPhoneIcon" data-depcity="URC" data-arrcity="SHA" data-depdate="2026-10-09" data-retdate="2026-10-11"></span> <span class="pi-price"><i>¥</i>1510</span> </div> <div class="return-recommend-date"> <div> 2026-10-09 星期五 去程 </div> <div> 2026-10-11 星期天 返程 </div> </div> </a> </li>  </ul> </div> </div>
</body></html>"""


def test_fliggy_round_js_replay_dump():
    pytest.importorskip("playwright",
                        reason="JS 端到端回放依赖 playwright")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失")
        b = p.chromium.launch()
        pg = b.new_page()
        pg.set_content(_ROUND_HTML)
        raw = pg.evaluate(FliggyCrawler._ROUND_JS)
        b.close()
    assert raw == [["2026-10-16", "2026-10-18", 1239, "URC", "SHA"],
                   ["2026-10-09", "2026-10-11", 1510, "URC", "SHA"]]


# ---- webui 消费端源码锚（字符串在场锚；行为面归 uitest/真机） ----

def test_webui_round_whitelist_and_gate():
    import webui
    src = open(os.path.join(os.path.dirname(webui.__file__), "webui.py"),
               encoding="utf-8").read()
    # 白名单透传（无值不落→None 不占位）
    assert '"trendRound": f.get("trendRound")' in src
    # 词面单源互钉：_rt_txt 函数定义在场 + CSV 列头与行值同源
    # （列头词面与 _rt_txt 产出前缀一处手抄删改即红）
    assert 'function _rt_txt(f)' in src
    assert "'往返推荐'" in src
    assert '_rt_txt(f)].map(e2).join' in src
    # title 消费端双段钉（r268 Soldier P1/P2 判例同律）：
    # 实效档=外层门含 trendRound（门外漏 trendRound=独有行 title 死路）+
    # 渲染链 he(_rt_txt(f)) 转义施加；游离字符形态（`}":`/`)}"`+反引号）
    # 禁复活钉在 test_nearby_field 同款锁字节
    assert ('(f.nearby&&f.nearby.length)'
            '||(f.trendRound&&f.trendRound.length))?` title="' in src)
    assert 'he(_rt_txt(f))' in src
    assert '(f.trendRound&&f.trendRound.length?' in src
    # 实效档：`he(_rt_txt(f)):'')}` 之后必须恰为 `"`+反引号（title 末段
    # 属性闭合即模板闭合）——`"` 与反引号之间夹任何字符都是游离字符
    # 缺陷（执行探针可捉、node --check 不可见，r268 P2 判例）
    _anchor = "he(_rt_txt(f)):'')}"
    _at = src.find(_anchor)
    assert _at > 0
    assert src[_at + len(_anchor):].startswith('"' + '`')
