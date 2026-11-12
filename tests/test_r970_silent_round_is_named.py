# -*- coding: utf-8 -*-
"""r970：**允许说不出原因，不允许什么都不说**。

实测（2026-11-05，修好报表读取路径后第一次看清账本）：

```
app_qunar  paths: TRIP 35 fail / unknown 35 fail / app-login 11 fail /
                 android-runtime 8 / snap-restore 1 / 航班明细 16 ok, 24 fail
```

`unknown` 那 35 条不是"被风控"，也不是任何一种已知失败模式 ——
它们是**既没出数、又一条通路都没记**的轮次：
`safe_fetch()` 里 `fetch()` 返回空且 `self.paths` 为空时，
`statuses_ok([])` 返回空 path，上层 `led.note(name, path or "unknown", ...)`
就落成一个 `unknown`。

后果：报表上"失败"是可见的，**卡在哪一步完全不可见**，
和真正的风控/登录墙混在一起，无法归因、也就无法修。

修法：`safe_fetch()` 在"空结果 + 零通路记录"时显式补一条
`app-silent/error`。它仍然是失败（不洗数据），但**有名字了**：
健康卡会说"App 静默无记录"，而不是让账本猜一个 `unknown`。

注意：`app-silent` **不进** `INFRA_PATHS` —— 我们并不知道这一轮
到底有没有真的打过站点，按"不确定就按失败算"处理，宁保守不乐观。

跑：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r970_silent_round_is_named.py -q
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers.app_base import AppCrawler  # noqa: E402
from core.yield_stats import INFRA_PATHS, statuses_ok  # noqa: E402


class _Log:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


class _Crawler(AppCrawler):
    """最小可运行的 App 渠道：fetch 行为由用例指定。"""

    name = "app_probe"
    package = ""
    LOGIN_FORM_MARKS = ()

    def __init__(self, rows=None, notes=None):
        super().__init__({}, _Log())
        self._rows = rows or []
        self._notes = notes or []

    def _policy_gate(self, dim=""):
        # 签名跟生产入口对齐（`crawlers/app_base.py::safe_fetch` 调
        # `self._policy_gate(dim=…)`，波次二起闸门要吃维度）：替身少这个
        # 关键字参数就当场 TypeError，测的就不是「静默轮次有没有名字」了。
        return True

    def fetch(self, from_city, to_city, dates, ret_date=""):
        for path, status in self._notes:
            self.path_note(path, status)
        return list(self._rows)


def test_silent_round_gets_a_name():
    """空结果 + 一条通路都没记 ⇒ 必须落下 app-silent，而不是留空。"""
    c = _Crawler(rows=[], notes=[])
    c.safe_fetch("SHA", "CAN", ["2026-11-16"])
    paths = [p.get("path") for p in c.paths]
    assert "app-silent" in paths, "静默轮次没有被命名：%r" % (paths,)
    ok, rows, best = statuses_ok(c.paths)
    assert ok is False and rows == 0
    assert best == "app-silent", "账本仍会落成 unknown(%r)" % best


def test_named_failure_is_not_overwritten():
    """已经记了通路的失败**不许**再补 app-silent（不能盖住真原因）。"""
    c = _Crawler(rows=[], notes=[("app-login", "login")])
    c.safe_fetch("SHA", "CAN", ["2026-11-16"])
    paths = [p.get("path") for p in c.paths]
    assert "app-silent" not in paths, "把已归因的失败又盖了一层：%r" % (paths,)
    assert "app-login" in paths


def test_success_gets_no_silent_note():
    c = _Crawler(rows=[object()], notes=[])
    c.safe_fetch("SHA", "CAN", ["2026-11-16"])
    assert "app-silent" not in [p.get("path") for p in c.paths]


def test_silent_note_carries_reason():
    """留痕要带得上原因（last_error 有就带上，没有也要写清"返回空且未记录"）。"""
    c = _Crawler(rows=[], notes=[])
    c.last_error = ""
    c.safe_fetch("SHA", "CAN", ["2026-11-16"])
    rec = [p for p in c.paths if p.get("path") == "app-silent"][0]
    assert rec.get("status") == "error"
    assert rec.get("detail"), "静默记录必须带 detail"


def test_silent_is_not_treated_as_infra():
    """`app-silent` 不能进基础设施白名单：**不确定就按失败算**。

    进了白名单会被 §6.48 的"非采集轮不计样本"排除掉，
    成功率会虚高 —— 那比低估更危险。
    """
    assert "app-silent" not in INFRA_PATHS


def test_label_table_knows_app_silent():
    """r658 门禁会扫 `path_note` 字面量对标签表；新名字必须先在表里。

    否则健康卡上会出现一个没有中文名的裸 key。
    """
    import io
    src = io.open(os.path.join(ROOT, "core", "channels.py"),
                  encoding="utf-8").read()
    assert '"app-silent"' in src, "标签表缺 app-silent（会过不了 r658 对账）"


# ---------------------------------------------------------------------------
# 浏览器渠道同一类缺口（与 App 侧对称补齐，2026-11-05）
# ---------------------------------------------------------------------------
class _WebCrawler:
    """最小浏览器渠道替身：只测 `_yield_note` 的静默留痕分支。

    直接借 `BaseCrawler` 的方法，其余依赖用最小替你补上——
    这样测的是**生产代码里那段 if**，不是我自己抄一份逻辑。
    """

    name = "web_probe"
    PATH_STATUS = ("ok", "empty", "error", "timeout", "soft_reject",
                   "login", "blocked", "paced", "unsupported")

    def __init__(self, results=None):
        self.paths = []
        self.config = {"user_data_dir": "/tmp/nonexistent_tm_ud"}
        self._results = results or []

    def path_note(self, path, status, rows=0, **kw):
        self.paths.append({"path": path, "status": status, "rows": rows})

    def _yield_ledger(self):
        return None            # 不落盘：本用例只验"有没有留痕"


def test_web_silent_note_is_added_via_real_method():
    """`base._yield_note` 在"零通路 + 零结果"时必须先补 web-silent。

    用真实方法而不是复刻逻辑：把 `BaseCrawler._yield_note` 绑到替身上跑，
    断言那段 `if not self.paths and not results` 真的会执行。
    """
    from crawlers.base import BaseCrawler

    c = _WebCrawler()
    BaseCrawler._yield_note(c, [])
    assert [p["path"] for p in c.paths] == ["web-silent"], c.paths


def test_web_silent_not_added_when_a_path_was_noted():
    from crawlers.base import BaseCrawler

    c = _WebCrawler()
    c.path_note("H5", "empty")
    BaseCrawler._yield_note(c, [])
    assert "web-silent" not in [p["path"] for p in c.paths]


def test_label_table_knows_web_silent():
    import io
    src = io.open(os.path.join(ROOT, "core", "channels.py"),
                  encoding="utf-8").read()
    assert '"web-silent"' in src, "标签表缺 web-silent（r658 对账会红）"
