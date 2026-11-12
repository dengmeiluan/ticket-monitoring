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
    # 本条钉的是「相对 user_data_dir 一律锚定到仓库根，不随 cwd 漂移」
    # 这个**默认路径行为**，所以必须模拟生产形态——显式去掉 conftest 的
    # 集中重定向（`TM_USER_DATA_DIR`）。conftest docstring 早有这条约定：
    # 「默认路径行为不变」类钉须模拟生产形态显式恢复，语义担保不丢。
    monkeypatch.delenv("TM_USER_DATA_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    c = REGISTRY[platform]({"user_data_dir": "user_data"},
                           logging.getLogger("session-test"))
    expected = Path(__file__).resolve().parents[1] / "user_data"
    assert Path(c.user_data_root) == expected
    monkeypatch.chdir(tmp_path.parent)
    assert Path(c.user_data_root) == expected




















