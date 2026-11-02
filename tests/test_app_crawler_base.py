# -*- coding: utf-8 -*-
"""AppCrawler 基类：账本契约与既有 BaseCrawler 对齐。"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawlers.app_base import AppCrawler
from crawlers.base import BaseCrawler


class Dummy(AppCrawler):
    name = "app_dummy"
    package = "com.example.dummy"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.raise_in_fetch = False

    def fetch(self, from_city, to_city, dates, ret_date=""):
        if self.raise_in_fetch:
            raise RuntimeError("boom")
        self.path_note("app-calendar", "ok", rows=1, date=dates[0])
        return []

    def login_url(self):
        return "app://dummy"


def _crawler():
    return Dummy({"user_data_dir": "user_data"}, logging.getLogger("t"))


def test_path_status_covers_base_vocabulary():
    """App 渠道必须能表达 base 的全部状态，不能漏。"""
    missing = set(BaseCrawler.PATH_STATUS) - set(AppCrawler.PATH_STATUS)
    assert missing == set(), missing


def test_path_note_shape_matches_base():
    c = _crawler()
    c.path_reset()
    rec = c.path_note("app-calendar", "calendar", rows=3, date="2026-11-16",
                      detail="d", ms=12)
    base = BaseCrawler({"user_data_dir": "user_data"}, logging.getLogger("t"))
    brec = base.path_note("app-calendar", "calendar", rows=3,
                          date="2026-11-16", detail="d", ms=12)
    assert set(rec) == set(brec)


def test_illegal_status_becomes_error():
    c = _crawler()
    assert c.path_note("x", "nonsense")["status"] == "error"


def test_safe_fetch_swallows_exception():
    c = _crawler()
    c.raise_in_fetch = True
    out = c.safe_fetch("SHA", "BJS", ["2026-11-16"])
    assert out == []
    assert c.last_status == "error"


def test_safe_fetch_logs_platform_prefix(caplog):
    c = _crawler()
    with caplog.at_level(logging.INFO):
        c.safe_fetch("SHA", "BJS", ["2026-11-16"])
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "[app_dummy]" in joined


def test_path_reset_clears():
    c = _crawler()
    c.path_note("a", "ok")
    c.path_reset()
    assert c.paths == []


def test_login_url_is_abstract():
    c = _crawler()
    assert c.login_url() == "app://dummy"


# ---- r639：登录态快照必须能在下次采集前自动恢复 ----
def test_restore_runs_once_per_process():
    """一个进程只尝试恢复一次，且没有快照时静默跳过、不记失败。"""
    import logging
    import os
    import tempfile
    from crawlers.app_zhixing import AppZhixingCrawler

    d = tempfile.mkdtemp()
    c = AppZhixingCrawler(
        {"android": {"enabled": True, "snapshot": True},
         "user_data_dir": d}, logging.getLogger("t"))

    class Dev:
        pass

    assert c.restore_login_snapshot(Dev()) is False
    assert c._snapshot_restored is True, "没快照也该标记为「试过了」"
    assert not [p for p in c.paths if p["path"] == "snap-restore"], \
        "没有快照时不该记任何失败"


def test_restore_skipped_when_snapshot_disabled():
    """android.snapshot=false 时不得动设备。"""
    import logging
    from crawlers.app_zhixing import AppZhixingCrawler

    c = AppZhixingCrawler(
        {"android": {"enabled": True, "snapshot": False}}, logging.getLogger("t"))
    assert c._snapshot_manager(object()) is None
    assert c.restore_login_snapshot(object()) is False


def test_snapshot_dir_matches_between_export_and_restore():
    """导出端与恢复端必须解析到同一个目录。

    实测踩过：配置页按相对路径 join（随 cwd 漂移），采集端按仓库根
    解析——两边各找一处，导出了也永远恢复不到，表现为「登录过还要重登」。
    """
    import os
    import re
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    w = open(os.path.join(root, "webui.py"), encoding="utf-8",
             newline="").read()
    i = w.index("android_snapshots")
    seg = w[i - 700:i + 60]
    assert "_anchored(" in seg, (
        "登录完成导出快照时没有锚定仓库根，会与采集端解析出不同目录")


# ---- r641：系统权限弹窗必须自动点掉（换机/重装后首次启动会遇到） ----
class _PD:
    def __init__(self, frames, activity="com.android.permissioncontroller/"
                 ".permission.ui.GrantPermissionsActivity"):
        self.frames = list(frames)
        self.taps = []
        self.activity = activity

    def current_activity(self):
        return self.activity

    def dump(self):
        if self.frames:
            return self.frames.pop(0)
        return self.frames_last

    def tap(self, x, y):
        self.taps.append((x, y))
        return True


def _dlg(texts, ys):
    cells = "".join(
        '<node index="%d" text="%s" class="android.widget.Button"'
        ' bounds="[0,%d][100,%d]" />' % (i, t, y, y + 60)
        for i, (t, y) in enumerate(zip(texts, ys)))
    return ('<?xml version="1.0"?><hierarchy rotation="0">'
            '<node index="0" text="" class="android.widget.FrameLayout">'
            + cells + '</node></hierarchy>')


def test_permission_dialog_is_dismissed():
    """权限框盖住首页时必须点「允许」，否则采集读成「首页未就绪」。"""
    import logging
    from crawlers.app_zhixing import AppZhixingCrawler

    c = AppZhixingCrawler({"android": {"enabled": True}},
                          logging.getLogger("t"))
    d = _PD([_dlg(["要允许“智行旅行”向您发送通知吗？", "允许", "不允许"],
                  [100, 200, 300])])
    d.frames_last = _dlg(["机票查询"], [100])
    n = c._dismiss_system_prompts(d)
    assert n == 1, "没点掉权限框（handled=%s）" % n
    assert len(d.taps) == 1


def test_permission_dialog_not_confused_with_app_buttons():
    """首页正常时不点任何东西——不能把普通按钮误当成权限确认。"""
    import logging
    from crawlers.app_zhixing import AppZhixingCrawler

    c = AppZhixingCrawler({"android": {"enabled": True}},
                          logging.getLogger("t"))
    d = _PD([_dlg(["机票查询", "上海", "广州"], [100, 200, 300])])
    d.frames_last = d.frames[0] if d.frames else _dlg(["机票查询"], [100])
    assert c._dismiss_system_prompts(d) == 0
    assert d.taps == [], "不该在正常页面上乱点"


def test_snapshot_skip_when_device_newer_is_not_error():
    """「设备登录态比快照新」是刻意保留，不能记成 error。

    记成 error 会让健康卡显示「快照恢复失败」，而实际情况正相反——
    用户在 App 里刚登过，此时恢复才是错的。
    """
    import logging
    from crawlers.app_zhixing import AppZhixingCrawler

    c = AppZhixingCrawler({"android": {"enabled": True, "snapshot": True}},
                          logging.getLogger("t"))

    class Store:
        def exists(self, plat):
            return True

    class Mgr:
        store = Store()

        def restore(self, plat):
            return False, "设备上的登录态比快照新，已保留设备数据"

    c._snapshot_manager = lambda dev: Mgr()
    c.restore_login_snapshot(object())
    recs = [p for p in c.paths if p["path"] == "snap-restore"]
    assert recs, "跳过恢复也要留痕"
    assert recs[0]["status"] == "ok", "跳过不是失败：%s" % recs[0]
    assert "跳过恢复" in recs[0]["detail"], recs[0]["detail"]
