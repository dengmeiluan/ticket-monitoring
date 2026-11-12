# -*- coding: utf-8 -*-
"""r794 飞猪淘宝 H5：表单操作与风控识别。

三条缺陷都是「看起来成功、实际什么都没发生」：
  1. `_pick_city` 用「第一个以城市名开头的叶节点」做判据，新首页的促销
     模块（flight-onsale-od-select-od-text）也含同名文本且排在结果行前面，
     点它无效却 return True；
  2. 航线不匹配分支选完城市**从不点搜索**，一次请求都不发；
  3. mtop 在响应体里返回 FAIL_SYS_USER_VALIDATE（滑块风控），HTTP 仍是
     200、页面照常渲染结果壳页，账本记成「解析 0 行」＝把风控说成解析问题。

这里只测「判据」与「报文识别」，不联网、不驱动浏览器：
渲染行为由 _scratch/r794*.py 的实测记录背书（见 docs 与 HANDOFF）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "crawlers", "fliggy_h5.py"),
           encoding="utf-8").read()


def test_risk_of_flags_mtop_rejection_at_all():
    """r794 的原始样本（H5 当时 0 行的真身）：必须被识别成拒绝，不是正常结果。"""
    from crawlers.fliggy_h5 import risk_of
    p = {"ret": ["FAIL_SYS_USER_VALIDATE",
                 "RGV587_ERROR::SM::哎哟喂,被挤爆啦,请稍后重试"],
         "data": {"url": "https://h5api.m.taobao.com/h5/_____tmd_____/punish"}}
    assert risk_of(p), "mtop 拒绝体被当成正常结果，会退回「解析 0 行」"


def test_risk_of_detects_validate_shell_without_ret():
    """验证壳：ret 为 null，data 只有 url —— 只看 ret 会漏。"""
    from crawlers.fliggy_h5 import risk_of
    p = {"api": "mtop.trip.flight.listingsearch", "ret": None,
         "data": {"url": "https://h5api.m.taobao.com/h5/_____tmd_____/punish"}}
    assert risk_of(p) == "wall:USER_VALIDATE"


def test_risk_of_is_quiet_on_real_results():
    """正控：真的带 items 的结果页不能被判成风控，否则真数据也会被丢。"""
    from crawlers.fliggy_h5 import risk_of
    ok = {"api": "mtop.trip.flight.listingsearch",
          "ret": ["SUCCESS::调用成功"],
          "data": {"success": True, "items": [
              {"itemType": "FLIGHT_DIRECT", "data": [{"priceInfo": {}}]}]}}
    assert risk_of(ok) == ""
    assert risk_of({}) == ""
    assert risk_of(None) == ""


def test_risk_of_separates_rate_limit_from_validate_wall():
    """RGV587 的原文是「被挤爆啦,请稍后重试」——是限流，不是验证墙。

    r795 实测：冷却后单次请求 4 条响应全 SUCCESS 并正常出数。
    把限流记成 blocked 会引导用户去解一个不存在的验证。
    """
    from crawlers.fliggy_h5 import risk_of
    rate = {"ret": ["FAIL_SYS_USER_VALIDATE",
                    "RGV587_ERROR::SM::哎哟喂,被挤爆啦,请稍后重试"]}
    assert risk_of(rate).startswith("rate:"), risk_of(rate)

    wall = {"ret": ["FAIL_SYS_USER_VALIDATE", "请完成验证"]}
    assert risk_of(wall).startswith("wall:"), risk_of(wall)

    shell = {"ret": None,
             "data": {"url": "https://h5api.m.taobao.com/h5/_____tmd_____/punish"}}
    assert risk_of(shell).startswith("wall:"), risk_of(shell)


def test_rate_limit_maps_to_soft_reject_not_blocked():
    """限流必须落 soft_reject（等一会自愈），不能落 blocked（要人去验证）。"""
    assert 'self._last_soft = True' in SRC
    assert '"soft_reject" if getattr(self, "_last_soft", False)' in SRC
    # 只有 wall 分支才置 blocked
    i_kind = SRC.index('kind = risk.split(":", 1)[0]')
    i_soft = SRC.index("self._last_soft = True", i_kind)
    i_block = SRC.index("self._last_blocked = True", i_kind)
    assert i_soft < i_block, "rate 分支必须先于 wall 分支"
    assert SRC[i_soft:i_block].count("return []") == 1, (
        "rate 分支要直接返回，不能落到 wall 的 blocked")


def test_risk_detail_text_is_used_by_ledger():
    """账本 detail 必须分别落到「限流」与「风控验证」两种文案。"""
    assert "H5 限流（mtop %s，冷却后自愈）" in SRC
    assert "H5 风控验证（mtop %s）" in SRC
    # 顺序：限流分支在前，验证分支在后；两者都必须在「解析 0 行」之前
    i_rate = SRC.index('"H5 限流（mtop %s，冷却后自愈）" % marker')
    i_wall = SRC.index('"H5 风控验证（mtop %s）" % marker')
    i_parse = SRC.index('"H5 listingsearch 解析 0 行（响应 %d 条）"')
    assert i_rate < i_wall < i_parse


def test_city_pick_targets_result_row_and_verifies_form():
    """选城市必须以结果行 class 为目标，并以表单读数复核。"""
    from crawlers.fliggy_h5 import FliggyH5Crawler
    js = FliggyH5Crawler._PICK_ROW_JS
    assert "flight-city-picker-search-line-item-name-wrapper" in js
    # 旧判据的三个特征都必须消失
    assert "querySelectorAll('*')" not in js
    assert "所有机场" not in js
    assert "city-picker|city-item|city-list|row" not in js
    # 复核：点完要回到表单读数确认，不能只信 click 的返回值
    body = SRC[SRC.index("def _pick_city"):SRC.index("def _read_form")]
    assert "_read_form(page)" in body
    assert "now[idx] == name" in body


def test_search_is_triggered_on_both_branches():
    """原来只在日期已匹配的分支点搜索；选完城市直接 return 导致零请求。"""
    body = SRC[SRC.index("def _fetch_one"):SRC.index("def fetch(")]
    i_pick = body.index("self._pick_city(page, 1, want_arr)")
    i_trig = body.index("self._trigger_search(page)")
    assert i_pick < i_trig, "点搜索必须在选完城市之后统一执行"
    # 只允许一处调用（两条分支合并成一条），不再分散
    assert body.count("self._trigger_search(page)") == 1


def test_search_click_tolerates_navigation():
    """点搜索会整页导航，evaluate 可能抛上下文销毁——这不是失败。"""
    body = SRC[SRC.index("def _trigger_search"):SRC.index("def _select_date")]
    assert "Execution context was destroyed" in body
    assert "return True" in body


def test_wait_loop_parses_incrementally():
    """首页会自动重放上次搜索：不能因 buffer 非空就退出。"""
    body = SRC[SRC.index("self._trigger_search(page)\n            # 首页会"):
               SRC.index("best = {}")]
    assert "scanned" in body
    assert "while time.time() < deadline:" in body
    assert "not payloads" not in body, "旧循环只要非空就退出，会读到旧航线"


class _CalPage:
    """日历弹层替身：只记录 evaluate 的入参，并按脚本特征返回预设结果。"""

    def __init__(self, shown, moved=True, clicked=True):
        self.shown = shown
        self.moved = moved
        self.clicked = clicked
        self.calls = []

    def evaluate(self, script, arg=None):
        self.calls.append((script, arg))
        if isinstance(arg, dict):
            if "scrollIntoView" in script:
                return self.moved
            if "date-item-container" in script:
                return self.clicked
        if "traffic-show-date" in script and "innerText" in script:
            return self.shown
        return None

    def wait_for_timeout(self, ms):
        pass


def test_select_date_reaches_far_month_and_never_accepts_wrong_month():
    """跨月选日：必须带着目标 `YYYY-MM` 去滚月，并且校验只认目标月份。

    实测（2026-11-01）：日历把所有月份排在同一条纵向列表里（`.month-header-text`
    文案 `YYYY-MM`，2026-11 → 2027-06），原实现只点「当前可见月里等于 day 的
    第一个元素」——目标 2027-01-30 时点到 11 月的 30 日，随后校验月份不符，
    记「日期选择未匹配」，等于 90 天外的日期根本选不了。
    """
    from crawlers.fliggy_h5 import FliggyH5Crawler
    c = FliggyH5Crawler.__new__(FliggyH5Crawler)
    page = _CalPage("1 月 30 日 周六")
    assert c._select_date(page, "2027-01-30") is True
    args = [a for (_s, a) in page.calls if isinstance(a, dict)]
    assert args and all(a.get("ym") == "2027-01" for a in args), args
    assert all(a.get("day") == "30" for a in args), args

    # 负控：表单落在 11 月 30 日（选错月）绝不能算成功
    bad = _CalPage("11 月 30 日 周日")
    assert c._select_date(bad, "2027-01-30") is False

    # 月标题不存在（超出日历覆盖范围）→ 直接失败，不乱点
    miss = _CalPage("1 月 30 日 周六", moved=False)
    assert c._select_date(miss, "2028-01-30") is False
