"""爬虫模块

浏览器渠道（Playwright）与 App 渠道（Android + adb）共用同一个
REGISTRY，但基类不同：前者 BaseCrawler，后者 AppCrawler。
调用方只依赖 `cls(config, logger)` + `safe_fetch()` 契约，不关心实现端。

App 渠道必须显式加进用户 `platforms:` 才会被实例化；`android.enabled`
为假时它们连设备都不会碰（见 core/android/runtime.py）。
"""
from .base import BaseCrawler
from .ctrip import CtripCrawler
from .fliggy import FliggyCrawler, FliggyH5Login
from .tongcheng import TongchengCrawler
from .qunar import QunarCrawler
from .tuniu import TuniuCrawler
from .app_base import AppCrawler
from .app_zhixing import AppZhixingCrawler
from .app_qunar import AppQunarCrawler

REGISTRY = {
    "ctrip": CtripCrawler,
    "fliggy": FliggyCrawler,
    "tongcheng": TongchengCrawler,
    "qunar": QunarCrawler,
    "tuniu": TuniuCrawler,
    # App 渠道（可选）：需 android.enabled 且用户 platforms 里显式列出
    "app_zhixing": AppZhixingCrawler,
    "app_qunar": AppQunarCrawler,
}

# App 渠道 id 集合：供健康/节流/UI 区分「浏览器渠道」与「设备渠道」
APP_CHANNELS = ("app_zhixing", "app_qunar")

__all__ = ["BaseCrawler", "CtripCrawler", "FliggyCrawler", "FliggyH5Login",
           "TongchengCrawler", "QunarCrawler", "TuniuCrawler",
           "AppCrawler", "AppZhixingCrawler", "AppQunarCrawler",
           "APP_CHANNELS", "REGISTRY"]
