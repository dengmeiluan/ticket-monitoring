# -*- coding: utf-8 -*-
"""r687：列表页回首页——深链被 RN 栈吞掉时，整轮死在「设到达城市」。

真机现场（2026-10-30）：跑完国际（停在列表页）再切国内，
`_ensure_home` 按 3 次 BACK 没退到首页，接着发 `qunarphone://flight`
深链——`am start` 返回成功，但 RN 导航栈把它当重复入口吞掉，页面
仍停在列表页。函数随后返回 `""` 或旧帧，`_set_city` 拿着列表页的
dump 找城市位必然失败：

    [app_qunar] 设到达城市失败：上海
    path: 航班明细 timeout 未取到可用结果：set-city-arr

用户视角是「去哪儿忽好忽坏」，账本上只有一句 set-city-arr。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_qunar import AppQunarCrawler

LIST_PAGE = ('<hierarchy><node text="CN101" bounds="[10,300][80,340]" />'
             '<node text="08:55" bounds="[34,300][120,340]" />'
             '<node text="13:00" bounds="[499,300][583,340]" /></hierarchy>')
HOME = ('<hierarchy><node text="atom_flight_search_panel" '
        'bounds="[0,0][900,100]" />'
        '<node text="搜索" bounds="[48,580][852,708]" /></hierarchy>')


class Dev:
    """停在列表页：BACK 无效、深链被吞；只有 force-stop 后深链才到首页。"""

    def __init__(self):
        self.stopped = False
        self.calls = []
        self.dumps = 0

    def dump(self):
        self.calls.append(("dump",))
        self.dumps += 1
        return HOME if self.stopped else LIST_PAGE

    def keyevent(self, key):
        self.calls.append(("key", key))
        return True

    def app_stop(self, pkg):
        self.calls.append(("stop", pkg))
        self.stopped = True
        return True

    def deep_link(self, uri):
        self.calls.append(("deep", uri))
        return True

    def current_activity(self):
        return "com.mumu/.Main"


def _crawler():
    c = AppQunarCrawler.__new__(AppQunarCrawler)
    c.name = "app_qunar"
    return c


def test_stops_app_before_deep_link(monkeypatch):
    import crawlers.app_qunar as mod
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    c = _crawler()
    dev = Dev()
    xml = c._ensure_home(dev)
    kinds = [x[0] for x in dev.calls]
    assert "stop" in kinds, "深链兜底前没有 force-stop：%s" % kinds
    assert kinds.index("stop") < kinds.index("deep"), kinds
    assert "atom_flight_search_panel" in xml, "最终没拿到首页：%r" % xml[:80]


def test_returns_empty_when_home_never_comes(monkeypatch):
    import crawlers.app_qunar as mod
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)

    class Dead(Dev):
        def dump(self):
            return LIST_PAGE

    c = _crawler()
    assert c._ensure_home(Dead()) == "", "拿不到首页必须返回空串（调用方按 timeout 入账）"
