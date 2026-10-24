# -*- coding: utf-8 -*-
"""r326 韧性四钉（观测 agent 挂死归因 observe.md §A/B 落地）。

- 路由级栅栏总超时（main._collect_route_futures）：无超时 playwright
  调用泊车曾把 as_completed 栅栏焊死 30 分钟（00:33 资源耗尽→
  tongcheng 页内 evaluate 永不返回→4 渠道已抓行陪葬未落库，
  executor with 退出 join 放大为整进程停摆）；
- tongcheng 页内 fetch 注入 AbortSignal.timeout（治本：page.evaluate
  设计上无超时，45s 页级超时罩不住页内 promise）；
- apscheduler 警告接入 monitor.log（max_instances 跳轮走专用 logger
  未接入文件=排程层静默跳轮零痕迹）；
- tz 印章按航班日取 DST（base._stamp_intl 抓取时刻印章对跨 DST
  航班日错 60min：SHA→CAI/FRA 211 行实证，修法 tz_offset_min
  收日期串锚正午 UTC）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r326_resilience.py
"""
import concurrent.futures
import logging
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.intl import tz_offset_min  # noqa: E402

_LOG = logging.getLogger("t_r326")


# ---- tz 印章按航班日取 DST ----

def test_tz_offset_min_accepts_flight_date():
    # 'YYYY-MM-DD' 日期串锚定正午 UTC 取 DST 真历法（zoneinfo 实测）：
    # EU 2026-10-25 切冬令时、埃及 10 月末切换——航班日 11-16 与
    # 抓取日 10-18 分属两代时制
    assert tz_offset_min("FRA", when="2026-11-16") == 60
    assert tz_offset_min("FRA", when="2026-10-18") == 120
    assert tz_offset_min("CAI", when="2026-11-16") == 120
    assert tz_offset_min("CAI", when="2026-10-18") == 180
    assert tz_offset_min("NRT", when="2026-11-16") == 540
    # 无 when 回退抓取时刻（现行为不变）
    assert tz_offset_min("FRA") in (60, 120)


def test_stamp_intl_uses_flight_date_tz():
    from crawlers.tuniu import TuniuCrawler
    TN = TuniuCrawler({}, _LOG)
    fs = [{"depDate": "2026-11-16"}, {"depDate": "2026-10-18"}]
    TN._stamp_intl(fs, "SHA", "FRA")
    # 同批两行各按自己航班日取 DST（跨 DST 批次不互染）；
    # 大陆端恒 480 不随航班日漂移
    assert fs[0]["tz_arr"] == 60
    assert fs[1]["tz_arr"] == 120
    assert all(f["tz_dep"] == 480 for f in fs)
    assert all(f["intl"] == 1 for f in fs)


# ---- 路由级栅栏总超时 ----

def test_collect_route_futures_releases_on_park():
    from main import _collect_route_futures
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    ev = threading.Event()

    def park():
        # 模拟无超时 playwright 泊车（测试收尾放行，线程可回收）
        ev.wait(30)
        return []

    try:
        futs = {ex.submit(park): "parked",
                ex.submit(lambda: [1, 2]): "quick"}
        t0 = time.monotonic()
        results, timed = _collect_route_futures(
            futs, timeout_s=0.5, logger=_LOG)
        dt = time.monotonic() - t0
        # 有界放行：泊车 worker 不拖栅栏（旧 as_completed 无 timeout
        # 会在此永久阻塞）
        assert dt < 10
        assert ("quick", [1, 2]) in results
        assert timed == ["parked"]
    finally:
        ev.set()
        ex.shutdown(wait=True)


def test_collect_route_futures_all_done_no_timeout():
    from main import _collect_route_futures
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    try:
        futs = {ex.submit(lambda: [1]): "a", ex.submit(lambda: [2]): "b"}
        results, timed = _collect_route_futures(
            futs, timeout_s=10, logger=_LOG)
        assert timed == []
        assert sorted(results) == [("a", [1]), ("b", [2])]
    finally:
        ex.shutdown(wait=True)


# ---- tongcheng 页内 fetch 超时（源码钉：行为面=playwright 运行时） ----

def test_tongcheng_intl_fetch_has_abort_timeout():
    src = open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "crawlers", "tongcheng.py"), encoding="utf-8").read()
    assert "AbortSignal.timeout" in src


# ---- apscheduler 警告可见化 ----

def test_apscheduler_logger_wired_to_file(tmp_path):
    from core.logger import setup_logger
    setup_logger(str(tmp_path / "m.log"))
    ap = logging.getLogger("apscheduler")
    assert ap.handlers, "apscheduler logger 未接入任何 handler"
    assert ap.level == logging.WARNING
    assert ap.propagate is False


# ---- 城市面板国际页签拼音搜索（README 三路搜索承诺面） ----

def test_intl_city_pinyin_full_coverage():
    # 国际页签城市名必须有全拼（CITYX.npy 合并面）：README 宣称
    # 「中文名/拼音/三字码三路搜索」——拼音路曾在国际 177 城缺席
    # （"dongjing" 无匹配实证）；初字母表由全拼派生同 convention
    from core.intl import INTL_CITY_NAME, INTL_CITY_NPY, INTL_CITY_PY
    missing = [n for n in INTL_CITY_NAME.values()
               if n not in INTL_CITY_NPY or not INTL_CITY_NPY[n]]
    assert not missing, "缺拼音: %s" % missing[:8]
    for n, py in INTL_CITY_NPY.items():
        assert py.isascii() and py.islower(), (n, py)
        assert INTL_CITY_PY[n] == py[0].upper(), (n, py)
