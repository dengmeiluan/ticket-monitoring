# -*- coding: utf-8 -*-
"""r324 登录引导页钉（用户实报：qunar 登录窗默认页不落在能直接登录的页）。

设计原则（LESSONS 九）：登录窗开「用户熟悉的官网首页」，用户自己点
右上角登录——不是 passport 直跳页。五渠道逐一实测定谳：
- qunar：`flight.qunar.com/` 根路径会 302 到 www.qunar.com 促销聚合
  门户（首屏无登录词面，入口埋在 JS 后）——引导页必须落
  `/site/`（PC 机票列表页，登录入口右上角、cookie 落 .qunar.com
  主域与 PC 主路径/H5 兜底共用，桌面视口登录）；
- ctrip/tuniu/tongcheng/fliggy：现行官网首页实测登录入口可达
  （渲染页可点「登录」链接/词面在册），维持不动。
钉=五渠道 login_url 字面映射（数据面源码钉；网络跳转属渠道行为
不进离线测试——测试离线可跑纪律）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r324_login_guide.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_login_guide_urls_map():
    from crawlers.ctrip import CtripCrawler
    from crawlers.fliggy import FliggyCrawler
    from crawlers.qunar import QunarCrawler
    from crawlers.tongcheng import TongchengCrawler
    from crawlers.tuniu import TuniuCrawler

    import logging
    lg = logging.getLogger("t324lg")
    assert QunarCrawler({}, lg).login_url() == (
        "https://flight.qunar.com/site/"), (
        "qunar 引导页须落 /site/ 机票列表页（根路径 302 促销门户无登录入口）")
    assert CtripCrawler({}, lg).login_url() == "https://www.ctrip.com/"
    assert TuniuCrawler({}, lg).login_url() == "https://www.tuniu.com/"
    assert TongchengCrawler({}, lg).login_url() == "https://www.ly.com/"
    assert FliggyCrawler({}, lg).login_url() == "https://www.fliggy.com/"
