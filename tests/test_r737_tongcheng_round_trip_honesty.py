# -*- coding: utf-8 -*-
"""r737 同程国内往返：必须走产品总价接口，不拿单程价冒充。

历史：r736 实测国内 ret_date 仍跑单程列表（¥467 = 上海→北京单程），
当时只能显式 unsupported。r815h 找到 `book1/roundtrips`：接口直接给
`atp` 组合总价（真报文 210/210 满足 `atp == lp + atpd`），裸 httpx
可取，已接线。本门禁守两件事：

1. `fetch` 在国内单程列表循环**之前**把 ret_date 交给 `_fetch_dom_rt`；
2. 行为上国内传 ret_date 不启动单程浏览器。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _src():
    return io.open(os.path.join(ROOT, "crawlers", "tongcheng.py"),
                   encoding="utf-8").read()


def _fetch_body():
    src = _src()
    i = src.index("    def fetch(self")
    j = src.find("\n    def ", i + 10)
    return src[i:j if j > 0 else len(src)]


def test_domestic_round_trip_routes_to_api_before_the_list_loop():
    body = _fetch_body()
    i_rt = body.find("self._fetch_dom_rt(")
    # 国内主路径以 `with self.browser()` 开单程列表
    i_loop = body.find("with self.browser()")
    assert i_rt > 0, "fetch 里没有国内往返的接口分流"
    assert i_loop > 0, "找不到国内单程列表段"
    assert i_rt < i_loop, (
        "国内往返分流出现在单程列表之后——单程价已经先算出来了")


def test_domestic_round_trip_does_not_open_oneway_browser():
    """行为：国内传 ret_date → 只调 _fetch_dom_rt，不启单程浏览器。"""
    import logging
    from crawlers.tongcheng import TongchengCrawler

    inst = TongchengCrawler({"user_data_dir": "user_data"},
                            logging.getLogger("t"))
    opened, seen = [], {}

    class _NoBrowser:
        def __enter__(self):
            opened.append(1)
            raise AssertionError("不该启浏览器跑单程")

        def __exit__(self, *a):
            return False

    inst.browser = lambda *a, **k: _NoBrowser()   # type: ignore

    def fake_rt(frm, to, dates, ret):
        seen["args"] = (frm, to, list(dates), ret)
        return []

    inst._fetch_dom_rt = fake_rt  # type: ignore
    rows = inst.fetch("SHA", "BJS", ["2026-11-20"], ret_date="2026-11-24")
    assert rows == [], rows
    assert opened == [], "国内往返仍然启动了单程浏览器"
    assert seen["args"] == ("SHA", "BJS", ["2026-11-20"], "2026-11-24")


def test_oneway_still_goes_to_the_list_page():
    """负控：不传 ret_date 时照常走单程列表（别把单程也拦掉）。

    r805 起同程国内有**两条**通路（PC 的 getflightlist + H5 的 book1），
    所以一次单程可能开不止一个上下文：PC 先跑、挂了再回落 H5 是设计
    行为，不是「被误拦」。本判据要的仍是原来那件事——**单程没有被往返
    闸门拦死**，即至少走到过一次列表页。
    """
    import logging
    from crawlers.tongcheng import TongchengCrawler

    inst = TongchengCrawler({"user_data_dir": "user_data"},
                            logging.getLogger("t"))
    opened = []

    class _B:
        def __enter__(self):
            opened.append(1)
            raise RuntimeError("到此为止")

        def __exit__(self, *a):
            return False

    inst.browser = lambda *a, **k: _B()      # type: ignore
    try:
        inst.fetch("SHA", "BJS", ["2026-11-20"])
    except RuntimeError:
        pass
    assert opened, "单程没有走到列表页（被误拦）"
    # 也不能无限重试：两条通路各一次是上限
    assert len(opened) <= 2, "单程开了 %d 次上下文，通路重试失控" % len(opened)
    # 更关键的：不许记成 unsupported（那是往返专用状态）
    assert not [p for p in (inst.paths or [])
                if p.get("status") == "unsupported"], (
        "单程被记成了 unsupported：%s" % (inst.paths,))
