"""爬虫模块"""
from .base import BaseCrawler
from .ctrip import CtripCrawler
from .fliggy import FliggyCrawler
from .tongcheng import TongchengCrawler
from .qunar import QunarCrawler
from .tuniu import TuniuCrawler

REGISTRY = {
    "ctrip": CtripCrawler,
    "fliggy": FliggyCrawler,
    "tongcheng": TongchengCrawler,
    "qunar": QunarCrawler,
    "tuniu": TuniuCrawler,
}

__all__ = ["BaseCrawler", "CtripCrawler", "FliggyCrawler", "TongchengCrawler",
           "QunarCrawler", "TuniuCrawler", "REGISTRY"]
