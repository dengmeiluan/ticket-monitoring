# -*- coding: utf-8 -*-
"""r1063 T167：用户在 App 里登录时，**采集必须让位**。

真机现象（07:2x 实测）：
```
POST /api/app-login?plat=app_ctrip      → 200，session.status=pending，can_interact=true
4 秒后 GET /api/app-login/state         → session=null
GET  /api/app-login/frame               → 404
```
根因：同一台模拟器是**串行资源**，定时采集轮次会把别的 App 切到前台，
正在登录的那个 App 被切走，会话随之作废。用户视角就是
「点开后画面没了、也没存下来」——与浏览器侧"无法保存"是同一个病根。

做法：
1. `login_api.active_plat()`：当前有活着的登录会话就返回渠道名（登记表由
   `set_registry()` 注入，采集侧只读）；
2. `AppCrawler.early_skip` 第一道闸：别的渠道在登录 → 本轮让位，
   记 `paced`（我方主动不发请求，不进爬取率分母）。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.android import login_api as LA  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _Sess:
    def __init__(self, alive):
        self._alive = alive

    def alive(self):
        return self._alive


class _Reg:
    def __init__(self, mapping):
        self._m = mapping

    def plats(self):
        return list(self._m)

    def get(self, plat):
        return self._m.get(plat)


def test_active_plat_reports_live_session():
    LA.set_registry(_Reg({"app_ctrip": _Sess(True)}))
    assert LA.active_plat() == "app_ctrip"


def test_active_plat_ignores_dead_and_empty():
    LA.set_registry(_Reg({"app_ctrip": _Sess(False)}))
    assert LA.active_plat() == ""
    LA.set_registry(_Reg({}))
    assert LA.active_plat() == ""


def test_no_registry_is_safe():
    LA.set_registry(None)
    assert LA.active_plat() == ""


def test_early_skip_yields_to_other_channel_login(tmp_path, monkeypatch):
    """别的渠道在登录 → 本渠道本轮让位（记 paced，不是失败）。"""
    monkeypatch.setenv("TM_USER_DATA_DIR", str(tmp_path))
    LA.set_registry(_Reg({"app_fliggy": _Sess(True)}))
    from crawlers.app_ctrip import AppCtripCrawler
    import logging
    c = AppCtripCrawler({"crawler": {"user_data_dir": str(tmp_path)}},
                        logging.getLogger("t"))
    monkeypatch.setattr(c, "user_data_root", str(tmp_path), raising=False)
    notes = []
    monkeypatch.setattr(c, "path_note",
                        lambda path, status, **k: notes.append((path, status)),
                        raising=False)
    assert c.early_skip(["2026-11-16"]) is True
    # 让位必须记 `paced`（我方主动不发请求），不能记失败——否则爬取率被冤枉
    assert notes and notes[0][1] == "paced", notes


def test_own_channel_login_does_not_yield():
    """自己正在登录 ≠ 让位（那是要采的渠道）。"""
    LA.set_registry(_Reg({"app_ctrip": _Sess(True)}))
    src = io.open(os.path.join(ROOT, "crawlers", "app_base.py"),
                  encoding="utf-8").read()
    i = src.index("用户正在 App 登录")
    seg = src[max(0, i - 300):i + 200]
    assert "_who != self.name" in seg, "必须排除自己，否则登录期间永远不采"
