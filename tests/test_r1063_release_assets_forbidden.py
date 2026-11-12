# -*- coding: utf-8 -*-
"""r1063 T289：发布包校验工具的禁止项必须**真的生效**。

`tools/verify_release_assets.py::_forbidden` 原来用 `lstrip("./")` 归一化，
会把 `.env` 剥成 `env`、`.git/` 剥成 `git/` —— 于是"包里带了密钥/仓库历史"
这种最该拦的情况**永远不报**。校验工具的空洞比产品 bug 更危险：
它保护的是每一次发布。
"""
import importlib.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(ROOT, "tools", "verify_release_assets.py")


def _mod():
    spec = importlib.util.spec_from_file_location("vra", SPEC)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_secrets_and_repo_history_are_forbidden():
    m = _mod()
    for name in (".env", ".git/config", "./.env", "ghtoken", "config.yaml",
                 "user_data/a.json", "data/prices.db", "logs/monitor.log"):
        assert m._forbidden(name) is True, "%s 必须被拦（原来 .env/.git 拦不住）" % name


def test_normal_release_content_is_allowed():
    m = _mod()
    for name in ("ticket-monitoring-win64.zip", "webui.py",
                 "_internal/tzdata/x", "_internal/numpy/core/x.pyd",
                 ".envrc", ".github/workflows/ci.yml"):
        assert m._forbidden(name) is False, "%s 不该被拦（避免误伤）" % name
