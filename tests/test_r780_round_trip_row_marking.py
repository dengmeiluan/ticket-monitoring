# -*- coding: utf-8 -*-
"""r780：往返行必须自报口径——`extra` 里带 `tripType="RT"`。

为什么要有这条：往返价是**两段合计**，单程价是**一段**。同一个列表里
两者混排、又没有任何标记时，用户会把 ¥818 的往返和 ¥432 的单程直接比，
这正是本项目的红线（价格口径混用）。

现状（2026-11-01）：
  * tuniu（国内两段 segment）、app_zhixing、app_qunar 都已经在行级
    `extra` 写 `tripType="RT"` + 回程日；
  * fliggy 走日历元素（`element["tripType"]="RT"`），同款契约；
  * ctrip / qunar(web) / tongcheng 声明 n，不产出往返行。

这条门禁做三件事：
  1. 往返行必须有标记（防止新增渠道漏标）；
  2. 单程行**不能**带 RT 标记（防止标记泛化后失去区分力）；
  3. 声明 y 的渠道源码里必须真的写了这个标记。
"""
import glob
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core.channels import BROWSER_CHANNELS, APP_CHANNELS, dim_state

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RT_MARK = 'tripType": "RT"'   # json.dumps 后的形态
RT_MARK_ALT = '"tripType": "RT"'


def _src(plat):
    """渠道主文件 + 同名伴随模块（携程把往返解析拆在 *_roundtrip.py）。

    只看主文件会把「拆到 parser 模块里的 RT 标记」误报成没写；标记的
    真正产出由各渠道自己的夹具用例保证（如 app_ctrip_roundtrip 测试）。
    """
    files = sorted(glob.glob(os.path.join(ROOT, "crawlers", plat + "*.py")))
    return "".join(io.open(f, encoding="utf-8").read() for f in files)


@pytest.mark.parametrize("plat", list(APP_CHANNELS) + list(BROWSER_CHANNELS))
def test_round_trip_capable_channel_marks_rows(plat):
    """声明 y 的渠道，源码里必须真的写 tripType=RT。

    只要求「写了这个标记」，不绑定写法：`{"tripType": "RT"}`（字典字面量）
    与 `dict(f, tripType="RT")`（关键字参数）产出的是**同一份 JSON**，
    按写法判会误报（r780 实测：途牛用后者，被这条断言误判成没标）。
    真正「产出的 JSON 里有没有这个键」由下面用真实夹具的用例保证。
    """
    state = dim_state(plat, "round_trip")
    src = _src(plat)
    if state != "y":
        # 非 y 渠道也必须给一个可证伪的结论：不写 RT 标记就是它的承诺。
        # fliggy App 目前是唯一一家 ""（未声明），若哪天偷偷写标记而不
        # 升声明，用户会在混排里看到无法解释的往返行。
        assert state in ("", "n"), "%s 的 round_trip 状态越界：%r" % (plat, state)
        assert "tripType" not in src, (
            "%s 未声明 round_trip=y，却在源码里写 tripType——声明与行为打架"
            % plat)
        return
    assert "tripType" in src and "RT" in src, (
        "%s 声明支持往返，但源码里没有 tripType=RT 标记——混排时无法区分口径"
        % plat)


def test_tuniu_round_trip_rows_carry_rt_and_back_date():
    """途牛：真实夹具跑一遍，RT 行必须带 tripType 与 backDate。"""
    # 2026-10-31 真实响应的单行裁剪版（一条 MU5100 往返 offer + 对应
    # flightList 详情），放 tests/fixtures 让干净克隆也能复核。
    fx = os.path.join(ROOT, "tests", "fixtures", "tuniu_rt_sample.json")
    assert os.path.isfile(fx), "真实夹具缺失：%s" % fx
    from unittest import mock
    from crawlers.tuniu import TuniuCrawler

    fixture = json.load(io.open(fx, encoding="utf-8")) or {}

    class _Resp:
        text = json.dumps({"success": True, "data": {
            "fareList": fixture.get("fareList") or [],
            "flightList": fixture.get("flightList") or {}}})

    class _Client:
        cookies = mock.MagicMock()

        def get(self, *a, **k):
            return _Resp()

        def close(self):
            pass

    class _Cfg(dict):
        def get(self, k, d=None):
            return dict.get(self, k, d)

    c = TuniuCrawler(_Cfg(), mock.MagicMock())
    c.config = _Cfg()
    c._sleep = lambda: None
    c._rate_acquire = lambda: None
    c._rate_record = lambda: None
    c.max_poll = 1
    c.max_attempts = 1
    c._saved_page_token = lambda *a, **k: "tok"
    c._saved_session_cookies = lambda: []
    c._install_tac_cookies = lambda *_a, **_k: None
    c._fetch_pc_dom = lambda *a, **k: {}
    c._dump_raw = lambda *a, **k: None
    with mock.patch("crawlers.tuniu._net.new_client", return_value=_Client()):
        rt = c.fetch("SHA", "BJS", ["2026-11-27"], ret_date="2026-12-01")
        ow = c.fetch("SHA", "BJS", ["2026-11-27"])

    assert rt and rt[0].extra, "往返没有产出"
    rt_ex = json.loads(rt[0].extra)
    assert rt_ex and all(e.get("tripType") == "RT" for e in rt_ex)
    assert all(e.get("backDate") == "2026-12-01" for e in rt_ex)

    assert ow and ow[0].extra, "单程没有产出"
    ow_ex = json.loads(ow[0].extra)
    assert ow_ex and not any(e.get("tripType") for e in ow_ex), (
        "单程行被错误地标成了往返——标记泛化后就无法区分口径")


def test_round_trip_price_is_not_compared_as_one_way():
    """读端约定：往返行的 price 是两段合计，不能与单程行同比。

    这里守的是**数据契约的文字**——值域说明必须写在渠道矩阵里，
    否则下游没有任何依据区分。矩阵 y 的渠道要能查到「往返总价」字样。
    """
    ch = io.open(os.path.join(ROOT, "core", "channels.py"),
                 encoding="utf-8").read()
    assert "往返总价" in ch, (
        "渠道矩阵里没写明往返行的 price 是「往返总价」——下游无从判断口径")
