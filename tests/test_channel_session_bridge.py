"""会话保存与采集桥：只用临时 profile 和假浏览器，不访问渠道。"""
import json
import logging
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from crawlers import REGISTRY
from crawlers import base


class FakeContext:
    def __init__(self, state=None, close_error=False, export_error=False):
        self.state = state or {"cookies": [], "origins": []}
        self.close_error = close_error
        self.export_error = export_error
        self.closed = False
        self.restored = []

    def add_init_script(self, script):
        pass

    def new_page(self):
        return SimpleNamespace(set_default_timeout=lambda value: None,
                               set_default_navigation_timeout=lambda value: None,
                               goto=lambda *args, **kwargs: None)

    def storage_state(self):
        if self.export_error:
            raise RuntimeError("export failed")
        return self.state

    def cookies(self):
        return list(self.state["cookies"])

    def add_cookies(self, cookies):
        self.restored.extend(cookies)

    def close(self):
        self.closed = True
        if self.close_error:
            raise RuntimeError("close failed")


@pytest.fixture
def browser_stub(monkeypatch):
    contexts = []
    options = []
    next_context = [FakeContext()]

    def launch(**kwargs):
        options.append(kwargs)
        contexts.append(next_context[0])
        return next_context[0]

    @contextmanager
    def playwright():
        yield SimpleNamespace(chromium=SimpleNamespace(
            launch_persistent_context=launch))

    monkeypatch.setattr(base, "sync_playwright", playwright)
    return SimpleNamespace(contexts=contexts, options=options,
                           next_context=next_context)


def crawler(tmp_path, platform="tuniu"):
    return REGISTRY[platform]({"user_data_dir": str(tmp_path)},
                             logging.getLogger("session-test"))


def cookie(name="session", domain=".tuniu.com", expires=-1):
    return {"name": name, "value": "synthetic-test-value", "domain": domain,
            "path": "/flight", "expires": expires, "secure": True,
            "httpOnly": True, "sameSite": "Lax"}


@pytest.mark.parametrize("platform", REGISTRY)
def test_relative_profile_is_anchored_before_cwd_changes(tmp_path, monkeypatch,
                                                       platform):
    monkeypatch.chdir(tmp_path)
    c = REGISTRY[platform]({"user_data_dir": "user_data"},
                           logging.getLogger("session-test"))
    expected = Path(__file__).resolve().parents[1] / "user_data"
    assert Path(c.user_data_root) == expected
    monkeypatch.chdir(tmp_path.parent)
    assert Path(c.user_data_root) == expected


def test_busy_profile_is_rejected_without_blocking_other_platforms(
        tmp_path, browser_stub):
    first, second = crawler(tmp_path), crawler(tmp_path)
    failures = []
    entered = threading.Event()

    def contender():
        try:
            with second.browser():
                entered.set()
        except RuntimeError as exc:
            failures.append(type(exc).__name__)

    with first.browser():
        thread = threading.Thread(target=contender)
        thread.start()
        thread.join(timeout=1)
        assert not thread.is_alive(), "同 profile 忙碌必须立即返回"
        assert not entered.is_set(), "不允许同时打开同一 profile"
        assert failures == ["SessionBusyError"]
        with crawler(tmp_path, "fliggy").browser():
            pass
    with second.browser():
        pass


def test_login_exports_state_only_after_close_and_marks_explicit_save(
        tmp_path, monkeypatch, browser_stub):
    c = crawler(tmp_path)
    ctx = FakeContext({"cookies": [cookie()], "origins": []})
    browser_stub.next_context[0] = ctx
    replace = os.replace
    published = []

    def checked_replace(source, target):
        assert ctx.closed, "关闭完成前不能公布保存成功的快照"
        published.append(target)
        return replace(source, target)

    monkeypatch.setattr(base.os, "replace", checked_replace)
    done = threading.Event()
    done.set()
    started = time.time()
    c._login_window(done)
    assert Path(c.session_state_path).is_file()
    assert published == [c.session_state_path]
    assert c.load_session_cookies(["tuniu.com"]) == [cookie()]
    assert started <= c.session_saved_at <= time.time()


@pytest.mark.parametrize("failure", ["close", "export", "replace"])
def test_failed_login_does_not_publish_a_new_saved_session(
        tmp_path, monkeypatch, browser_stub, failure):
    c = crawler(tmp_path)
    path = tmp_path / "tuniu" / "session-state.json"
    path.parent.mkdir()
    original = {"cookies": [], "origins": [], "saved_at": 123.0}
    path.write_text(json.dumps(original), encoding="utf-8")
    browser_stub.next_context[0] = FakeContext(
        {"cookies": [cookie()], "origins": []},
        close_error=failure == "close", export_error=failure == "export")
    if failure == "replace":
        def fail_replace(*args):
            raise OSError("replace failed")
        monkeypatch.setattr(base.os, "replace", fail_replace)
    done = threading.Event()
    done.set()
    with pytest.raises((RuntimeError, OSError), match="failed"):
        c._login_window(done)
    assert json.loads(path.read_text(encoding="utf-8")) == original
    assert sorted(p.name for p in path.parent.iterdir()) == [path.name]
    assert c.use_mobile is True


def test_existing_profile_is_migrated_without_claiming_new_login(
        tmp_path, browser_stub):
    (tmp_path / "tuniu" / "Default").mkdir(parents=True)
    c = crawler(tmp_path)
    browser_stub.next_context[0] = FakeContext(
        {"cookies": [cookie()], "origins": []})
    assert c.load_session_cookies(["tuniu.com"]) == [cookie()]
    assert c.session_saved_at == 0
    assert browser_stub.options[0]["headless"] is True
    assert c.load_session_cookies(["tuniu.com"]) == [cookie()]
    assert len(browser_stub.contexts) == 1


def test_missing_profile_does_not_launch_browser_or_create_profile(
        tmp_path, browser_stub):
    c = crawler(tmp_path)
    assert c.load_session_cookies(["tuniu.com"]) == []
    assert c.session_saved_at == 0
    assert not (tmp_path / "tuniu").exists()
    assert not browser_stub.contexts


def test_loaded_cookies_keep_scope_and_reject_expired_or_foreign_values(
        tmp_path, browser_stub):
    c = crawler(tmp_path)
    path = tmp_path / "tuniu" / "session-state.json"
    path.parent.mkdir()
    live = cookie(expires=time.time() + 3600)
    rows = [live, cookie("expired", expires=time.time() - 1),
            cookie("foreign", domain=".example.com"),
            cookie("lookalike", domain=".nottuniu.com")]
    path.write_text(json.dumps({"cookies": rows, "origins": [],
                                "saved_at": 123.0}), encoding="utf-8")
    assert c.load_session_cookies(["tuniu.com"]) == [live]
    assert c.session_saved_at == 123.0
    assert not browser_stub.contexts


def test_cookie_reader_sees_new_snapshot_without_recreating_crawler(
        tmp_path, browser_stub):
    c = crawler(tmp_path)
    path = tmp_path / "tuniu" / "session-state.json"
    path.parent.mkdir()
    for name in ("old", "new"):
        path.write_text(json.dumps({"cookies": [cookie(name)], "origins": [],
                                    "saved_at": 123.0}), encoding="utf-8")
        assert c.load_session_cookies(["tuniu.com"])[0]["name"] == name


def test_browser_close_failure_propagates_and_releases_profile_lock(
        tmp_path, browser_stub):
    c = crawler(tmp_path)
    browser_stub.next_context[0] = FakeContext(close_error=True)
    with pytest.raises(RuntimeError, match="close failed"):
        with c.browser():
            pass
    browser_stub.next_context[0] = FakeContext()
    with c.browser():
        pass


def test_browser_restores_session_cookies_lost_between_profile_launches(
        tmp_path, browser_stub):
    c = crawler(tmp_path)
    path = tmp_path / "tuniu" / "session-state.json"
    path.parent.mkdir()
    saved = cookie()
    expired = cookie("expired", expires=time.time() - 10)
    path.write_text(json.dumps({"cookies": [saved, expired], "origins": [],
                                "saved_at": 123.0}), encoding="utf-8")
    ctx = browser_stub.next_context[0]
    with c.browser():
        assert ctx.restored == [saved]
    assert c.session_saved_at == 123.0


def test_browser_keeps_existing_profile_cookie_over_older_export(
        tmp_path, browser_stub):
    c = crawler(tmp_path)
    path = tmp_path / "tuniu" / "session-state.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"cookies": [cookie()], "origins": []}),
                    encoding="utf-8")
    current = dict(cookie(), value="current-profile-value")
    ctx = FakeContext({"cookies": [current], "origins": []})
    browser_stub.next_context[0] = ctx
    with c.browser():
        assert ctx.restored == []
        assert ctx.cookies() == [current]
