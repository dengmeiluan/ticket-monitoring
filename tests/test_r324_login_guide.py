# -*- coding: utf-8 -*-
"""r324 登录引导页钉（r358 随去哪儿网页版停服更新）。

2026-10-10 起 qunar PC /site/ 只留停服通知与 App 下载，原「官网首页
右上角登录」引导已失效；改落统一登录页 user.qunar.com（2026-10-22
实测手机号验证码/扫码可用，Cookie 落 .qunar.com 与 H5 取数共用）。
- qunar：`/site/` 停服 → 统一登录页；
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
        "https://user.qunar.com/passport/login.jsp"), (
        "qunar 引导页须落统一登录页（PC /site/ 已停服只剩 App 下载提示）")
    assert CtripCrawler({}, lg).login_url() == (
        "https://passport.ctrip.com/user/login"), (
        "r678 实测：www.ctrip.com 在移动指纹下是 App 式首页，0 个登录控件")
    from core.login_slots import LOGIN_SLOTS
    assert (CtripCrawler({}, lg).login_url()
            == LOGIN_SLOTS["ctrip"]["login_url"]), "爬虫与登录卡不同源"
    # r678 实测：www.tuniu.com 在采集同款移动指纹下是腾讯云 WAF 拦截页
    # （登录控件 0 个）——用户点「弹窗登录」看到的是拦截页，读作「登不了」。
    # 改到 passport 登录页，且必须与登录卡同源（两处各写一份会再漂移）。
    from core.login_slots import LOGIN_SLOTS
    assert TuniuCrawler({}, lg).login_url() == "https://passport.tuniu.com/login"
    assert (TuniuCrawler({}, lg).login_url()
            == LOGIN_SLOTS["tuniu"]["login_url"]), \
        "爬虫登录入口与登录卡不是同源，修一处漏一处"
    assert TongchengCrawler({}, lg).login_url() == "https://www.ly.com/"
    assert FliggyCrawler({}, lg).login_url() == "https://www.fliggy.com/"
