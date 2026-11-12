# -*- coding: utf-8 -*-
"""r1580：失败时把「这是哪一页」写进账本 note（用真实 dump 验四种页面）。"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_base import AppCrawler  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAIN = os.path.join(ROOT, "tests", "fixtures", "tongcheng_train_page.xml")


class _Log:
    def __init__(self):
        self.lines = []

    def warning(self, fmt, *a):
        self.lines.append(fmt % a if a else fmt)

    info = warning


class _Dev:
    def __init__(self, xml):
        self._xml = xml

    def dump(self):
        return self._xml


class _Fake(AppCrawler):
    name = "app_tongcheng"
    PATH_STATUS = {"ok", "timeout", "error", "login", "blocked", "calendar",
                   "paced", "unsupported", "captcha"}

    def __init__(self, root, xml):
        self.user_data_root = str(root)
        self.paths = []
        self._last_dev = _Dev(xml)
        self._phase_prev = None
        self.logger = _Log()

    def note_app_stall(self, detail=""):
        pass


def _train_xml():
    return io.open(TRAIN, encoding="utf-8", errors="replace").read()


def test_train_page_hint_lands_in_note(tmp_path):
    c = _Fake(tmp_path, _train_xml())
    c.path_note("app-city", "timeout", detail="点城市位后未打开城市页")
    rec = c.paths[-1]
    assert "页面: 火车票" in rec["detail"], (
        "失败时没把页面种类写进账本：%s" % rec["detail"])
    assert any("火车票" in ln for ln in c.logger.lines), c.logger.lines


def test_pure_text_classification():
    c = _Fake.__new__(_Fake)
    assert c._page_hint('<node text="机票查询"/>') == "页面: 机票表单"
    assert c._page_hint('<node text="查询火车票"/>') == "页面: 火车票"
    assert c._page_hint('<node text="微信登录"/>') == "页面: 登录"
    assert c._page_hint('<node text="拖动滑块"/>') == "页面: 人机验证"
    assert c._page_hint("").startswith("页面: 未知")


def test_success_note_is_untouched(tmp_path):
    c = _Fake(tmp_path, _train_xml())
    c.path_note("航班明细", "ok", rows=3, detail="3 条真实航班")
    assert "页面:" not in c.paths[-1]["detail"], c.paths[-1]
