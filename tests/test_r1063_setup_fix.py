# -*- coding: utf-8 -*-
"""r1063 T46：`--fix` 真的能补齐到「跑起来」+ 一键装机脚本。

用户要求：「一切又零配置（务必让 github 下载我们项目的安装的时候傻瓜化可自动
化爬取数据）」。上一个版本 `--fix` 只会装依赖/装浏览器，缺 `config.yaml` 和目录
时只打印一句提示，新用户照样卡住。

这轮把它补齐，并把"可自动修"改成**机器可判的 action**（不再匹配文案——文案
一改，自动修复就静默失效）。
"""
import io
import os

from core import setup_check as sc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_fixable_uses_actions_not_wording():
    rows = [
        {"level": sc.BAD, "name": "配置", "detail": "", "fix": "换个说法也行",
         "action": "create_config"},
        {"level": sc.BAD, "name": "目录", "detail": "", "fix": "",
         "action": "mkdir"},
        {"level": sc.BAD, "name": "人工", "detail": "", "fix": "手动作业",
         "action": "manual"},
        {"level": sc.OK, "name": "好", "detail": "", "fix": "", "action": ""},
    ]
    got = [r["name"] for r in sc.fixable(rows)]
    assert got == ["配置", "目录"], got


def test_old_rows_without_action_still_work():
    """向后兼容：没有 `action` 时退回匹配文案。"""
    rows = [{"level": sc.BAD, "name": "x", "detail": "",
             "fix": "python -m playwright install chromium"}]
    assert [r["name"] for r in sc.fixable(rows)] == ["x"]


def test_create_config_copies_example_and_never_overwrites(monkeypatch,
                                                          tmp_path):
    import shutil
    from pathlib import Path

    (tmp_path / "config.example.yaml").write_text("users: []\n",
                                                  encoding="utf-8")
    monkeypatch.setattr(sc, "_root", lambda: str(tmp_path))
    row = {"action": "create_config", "fix": ""}
    assert sc.apply_fix(row, echo=lambda *_a: None) is True
    assert (tmp_path / "config.yaml").exists()

    # 已存在时绝不覆盖（用户可能已经填了账号）
    (tmp_path / "config.yaml").write_text("users:\n- name: 我\n",
                                           encoding="utf-8")
    assert sc.apply_fix(row, echo=lambda *_a: None) is True
    assert "我" in (tmp_path / "config.yaml").read_text(encoding="utf-8")


def test_mkdir_creates_data_dirs(monkeypatch, tmp_path):
    monkeypatch.setattr(sc, "_root", lambda: str(tmp_path))
    assert sc.apply_fix({"action": "mkdir", "fix": ""},
                        echo=lambda *_a: None) is True
    assert (tmp_path / "data").is_dir()
    assert (tmp_path / "user_data").is_dir()


def test_one_click_setup_scripts_exist_and_chain_the_same_steps():
    for name in ("setup.ps1", "setup.sh"):
        p = os.path.join(ROOT, name)
        assert os.path.exists(p), name
        txt = io.open(p, encoding="utf-8").read()
        for step in ("requirements.txt", "playwright install chromium",
                     "core.setup_check --fix"):
            assert step in txt, (name, step)


def test_setup_scripts_do_not_touch_accounts_or_strategy():
    """一键装机不许自作主张改账号/策略（那是人的事）。"""
    for name in ("setup.ps1", "setup.sh"):
        txt = io.open(os.path.join(ROOT, name), encoding="utf-8").read()
        for bad in ("notifier", "token", "platforms:", "strategy_overrides"):
            assert bad not in txt, (name, bad)
