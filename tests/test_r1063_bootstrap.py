# -*- coding: utf-8 -*-
"""r1063 T157：`python -m core.bootstrap` —— github 下载后一条命令跑起来。

objective 原话："务必让 github 下载我们项目的安装的时候傻瓜化可自动化爬取"。

`core.setup_check` 早已定义好安全修复动作（`install_deps` / `install_browser` /
`create_config` / `mkdir` / `launch_emulator` / `restart_emulator`），
但用户得自己跑 `--fix`、自己判断差什么、自己起服务。本模块把这条链串起来：

1. 反复「自检 → 修可修的」，最多 3 轮（装完依赖常才暴露下一项）；
2. 汇总剩余问题（✅/⚠/❌）+ 下一步人话；
3. `--start` 拉起监控。

**边界**：只管"机器能不能跑"，绝不碰账号/登录/策略/订阅。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import bootstrap as B  # noqa: E402
from core import setup_check as SC  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _rows(seq):
    return list(seq)


def test_fixes_until_clean():
    """第一轮有可修项 → 修；第二轮干净 → 停。"""
    calls = {"checks": 0, "fixed": []}
    states = [
        [
            {"level": SC.BAD, "name": "依赖", "detail": "缺 playwright",
             "fix": "pip install -r requirements.txt",
             "action": "install_deps"},
            {"level": SC.OK, "name": "配置", "detail": "ok"},
        ],
        [
            {"level": SC.OK, "name": "依赖", "detail": "ok"},
            {"level": SC.OK, "name": "配置", "detail": "ok"},
        ],
    ]

    def checks():
        i = min(calls["checks"], len(states) - 1)
        calls["checks"] += 1
        return [dict(r) for r in states[i]]

    def apply(row):
        calls["fixed"].append(row["name"])
        return True

    rep = B.bootstrap(echo=lambda *a, **k: None, checks=checks, apply=apply)
    assert rep["ok"] is True, rep
    assert rep["passes"] == 2, rep
    assert rep["fixed"] == ["依赖"], rep
    assert rep["remaining"] == [], rep


def test_stops_after_max_passes_when_never_clean():
    def checks():
        return _rows([{"level": SC.BAD, "name": "依赖", "detail": "x",
                       "fix": "pip install -r requirements.txt",
                       "action": "install_deps"}])

    rep = B.bootstrap(echo=lambda *a, **k: None, checks=checks,
                      apply=lambda row: True, max_passes=2)
    assert rep["passes"] == 2, "必须封顶，不能死循环"
    assert rep["ok"] is False


def test_apply_exception_does_not_break_run():
    def checks():
        return _rows([{"level": SC.WARN, "name": "数据目录", "detail": "缺",
                       "fix": "mkdir data", "action": "mkdir"}])

    def apply(row):
        raise RuntimeError("boom")

    rep = B.bootstrap(echo=lambda *a, **k: None, checks=checks, apply=apply,
                      max_passes=1)
    assert rep["passes"] == 1
    assert rep["fixed"] == []


def test_report_mentions_next_steps():
    lines = []
    B._report({"ok": True, "passes": 1, "fixed": ["依赖"], "remaining": []},
              echo=lines.append)
    txt = "\n".join(lines)
    assert "--start" in txt and "channel_matrix" in txt


def test_never_touches_accounts_or_policy():
    """硬边界：只做机器能否运行的事，不许改账号/策略/订阅。

    注意：不能拿裸 "login" 当判据——模块里有一句**提示语**
    `channel_matrix --login`（告诉用户去哪登），那是帮助文本，不是动作。
    这里查的是"会真的改状态"的调用。
    """
    src = io.open(os.path.join(ROOT, "core", "bootstrap.py"),
                  encoding="utf-8").read()
    for bad in ("set_config(", "strategy_overrides", "login_sessions",
                "save_session", "pm clear", "shutil.rmtree"):
        assert bad not in src, "引导不许碰账号/策略/破坏性操作：%s" % bad
