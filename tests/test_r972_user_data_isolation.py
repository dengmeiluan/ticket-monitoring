# -*- coding: utf-8 -*-
"""r972：账本根目录必须可被**集中**重定向，别再把测试数据写进真 user_data。

同类问题前两次都是逐用例打补丁，结果第三次又犯：

| 来源 | 落点 | 被报表读成 |
|---|---|---|
| `test_r963` 传 `user_data_dir=""` | `user_data/app_demo/slider_ledger.json` | 滑块"试 63 / 过 63 命中 100%" |
| `test_intl_rt.py` 假渠道 `name="probe"` | `user_data/probe/yield_stats.json` | 渠道 probe，0 成功，建议间隔 75 分钟 |
| `test_app_crawler_base.py` `name="app_dummy"` | `user_data/app_dummy/yield_stats.json` | 渠道 app_dummy，89/178 |

脏文件只是表面：`scripts/yield_report.py` 会把它们当**真渠道**渲染，
**污染的是爬取率那张决策表**（本次修复的初衷就是让那张表可信）。

修法（与 conftest 既有 `PUSH_HISTORY_FILE` / `TM_RENDER_DIR` 同律）：
1. 生产侧收敛成唯一口径 `core.yield_stats.user_data_root(config)`：
   **config 显式值 > `TM_USER_DATA_DIR` > `"user_data"`**；
2. conftest 加 autouse fixture 把 `TM_USER_DATA_DIR` 指向 `tmp_path`；
3. 四个写点全部改用它：`base._yield_ledger`、`app_base._note_round_yield`、
   `app_base._ledger`、`policy.PolicyEngine.__init__`。

为什么 config 优先：生产 `main.py` 总传绝对 `session_root`（环境变量对生产无效），
而"显式传 tmp 并断言落在那里"的既有用例也不该被环境变量改写。

跑：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r972_user_data_isolation.py -q
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.yield_stats import user_data_root  # noqa: E402

REPO_USER_DATA = os.path.join(ROOT, "user_data")


# ---------------------------------------------------------------------------
# 1. 唯一口径的优先级
# ---------------------------------------------------------------------------
def test_config_explicit_wins(monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", "/tmp/from_env")
    assert user_data_root({"user_data_dir": "/tmp/from_cfg"}) == "/tmp/from_cfg"


def test_env_used_when_config_silent(monkeypatch):
    monkeypatch.setenv("TM_USER_DATA_DIR", "/tmp/from_env")
    assert user_data_root({}) == "/tmp/from_env"
    assert user_data_root(None) == "/tmp/from_env"


def test_default_when_nothing_set(monkeypatch):
    monkeypatch.delenv("TM_USER_DATA_DIR", raising=False)
    assert user_data_root({}) == "user_data"
    assert user_data_root({}, default="ud2") == "ud2"


def test_blank_values_fall_through(monkeypatch):
    """空串/空白必须当"没给"，不能变成空路径。"""
    monkeypatch.delenv("TM_USER_DATA_DIR", raising=False)
    assert user_data_root({"user_data_dir": "  "}) == "user_data"


def test_explicit_default_value_is_not_explicit_config(monkeypatch):
    """**显式传默认值 ≠ 显式配置**（本次修复的关键判据）。

    全仓 16 个测试文件、22 处都写 `{"user_data_dir": "user_data"}`；
    若把它当显式配置，集中重定向就永远漏这些用例，
    `app_dummy` / `app_probe` 这类脏账本会继续长出来。
    语义上它和不传完全等价（都是"用默认目录"），所以可被重定向。
    """
    monkeypatch.setenv("TM_USER_DATA_DIR", "/tmp/redirected")
    assert user_data_root({"user_data_dir": "user_data"}) == "/tmp/redirected"


def test_real_alternative_dir_is_still_respected(monkeypatch):
    """真的换了目录就要听它的——否则会破坏"显式传 tmp 并断言落点"的用例。"""
    monkeypatch.setenv("TM_USER_DATA_DIR", "/tmp/redirected")
    assert user_data_root({"user_data_dir": "/tmp/explicit"}) == "/tmp/explicit"
    assert user_data_root({"user_data_dir": "ud_x"}) == "ud_x"


# ---------------------------------------------------------------------------
# 2. conftest 的隔离真的生效（这条是本次修复的核心）
# ---------------------------------------------------------------------------
def test_conftest_redirects_user_data_root():
    """测试进程里必须已经被重定向到 tmp，而不是仓库的 user_data。"""
    root = os.path.abspath(user_data_root({}))
    assert root != os.path.abspath(REPO_USER_DATA), \
        "测试仍在用真实 user_data：conftest 的 _isolate_user_data 没生效"
    assert "user_data" in root


# ---------------------------------------------------------------------------
# 3. 假渠道真的不会再写进仓库 user_data
# ---------------------------------------------------------------------------
def test_dummy_app_channel_writes_outside_repo_user_data():
    """`app_dummy` 这类假渠道必须落在隔离目录，且仓库 user_data 不长新目录。"""
    from crawlers.app_base import AppCrawler

    class _Log:
        def info(self, *a, **k): pass
        def warning(self, *a, **k): pass
        def error(self, *a, **k): pass

    class _Dummy(AppCrawler):
        name = "app_dummy"
        package = ""
        LOGIN_FORM_MARKS = ()

    c = _Dummy({}, _Log())
    led = c._ledger()
    assert led is not None
    path = os.path.abspath(getattr(led, "path", "") or "")
    if path:
        assert os.path.abspath(REPO_USER_DATA) not in path, \
            "登录账本写进了真 user_data：%s" % path
        assert os.environ.get("TM_USER_DATA_DIR") in path


def test_browser_dummy_channel_writes_outside_repo_user_data():
    from crawlers.base import BaseCrawler

    class _Log:
        def info(self, *a, **k): pass
        def warning(self, *a, **k): pass
        def error(self, *a, **k): pass

    class _Dummy(BaseCrawler):
        name = "probe"

    c = _Dummy({"enabled": True}, _Log())
    led = c._yield_ledger()
    assert led is not None
    path = os.path.abspath(getattr(led, "path", "") or "")
    if path:
        assert os.path.abspath(REPO_USER_DATA) not in path, \
            "成功率账本写进了真 user_data：%s" % path


# ---------------------------------------------------------------------------
# 4. 结构约束：四个写点都必须走唯一口径
# ---------------------------------------------------------------------------
def test_all_four_write_sites_use_the_shared_helper():
    """写点分散在 4 处 —— 任何一处漏改，下次又会悄悄写进真 user_data。"""
    import io
    for rel in ("crawlers/base.py", "crawlers/app_base.py", "core/policy.py"):
        src = io.open(os.path.join(ROOT, rel), encoding="utf-8").read()
        assert "user_data_root(" in src, "%s 没用唯一口径" % rel
        assert 'get("user_data_dir") or "user_data"' not in src, \
            "%s 还留着旧的硬编码默认路径" % rel
