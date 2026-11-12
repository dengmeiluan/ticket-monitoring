# -*- coding: utf-8 -*-
"""r1063 T43：装机自检（零配置 / 傻瓜化）。

用户要求：「一切又零配置（务必让 github 下载我们项目的安装的时候傻瓜化可自动化
爬取数据）」。这条给出**一条命令**回答"还差什么"，并把**安全的部分**自动补齐。

纪律：
  * 只报能证明的（文件在不在 / 能不能 import / 命令能不能跑），不猜；
  * `--fix` **只做安全动作**（装依赖、装浏览器内核）；账号、登录、策略一律人来做；
  * 退出码 0/1 可直接 `if !` 判断。
"""
import io
import os

from core import setup_check as sc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_rows_have_a_fixed_shape():
    rows = sc.run_checks()
    assert rows, "自检必须至少有一项"
    for r in rows:
        assert set(r) >= {"level", "name", "detail", "fix"}, r
        assert r["level"] in (sc.OK, sc.WARN, sc.BAD), r


def test_python_check_reports_ok_here():
    r = sc.check_python()
    assert r["level"] == sc.OK, r


def test_modules_check_names_what_is_missing():
    r = sc.check_modules(names=("yaml", "definitely_not_a_module_xyz"))
    assert r["level"] == sc.BAD
    assert "definitely_not_a_module_xyz" in r["detail"]
    assert "pip install" in r["fix"]


def test_config_check_reads_platforms():
    r = sc.check_config()
    assert r["level"] in (sc.OK, sc.WARN, sc.BAD), r
    if r["level"] == sc.OK:
        assert "订阅" in r["detail"]


def test_browser_check_uses_the_filesystem_not_a_launch():
    """自检不许真的起浏览器：启动一次会留 asyncio 噪声、还慢。"""
    src = io.open(os.path.join(ROOT, "core", "setup_check.py"),
                  encoding="utf-8").read()
    fn = src[src.index("def check_browser("):]
    fn = fn[:fn.index("\ndef ")]
    assert "sync_playwright" not in fn, "浏览器检查又去启动 Playwright 了"
    assert "ms-playwright" in fn


def test_only_safe_actions_are_auto_fixable():
    rows = [{"level": sc.BAD, "name": "a", "detail": "",
             "fix": "python -m playwright install chromium"},
            {"level": sc.BAD, "name": "b", "detail": "",
             "fix": "启动 MuMu 模拟器"},
            {"level": sc.OK, "name": "c", "detail": "", "fix": ""}]
    todo = sc.fixable(rows)
    assert [r["name"] for r in todo] == ["a"], todo
    # 账号/登录类修复永远不许自动做
    assert all("MuMu" not in r["fix"] for r in todo)


def test_android_check_is_honest_when_no_device():
    r = sc.check_android()
    assert r["level"] in (sc.OK, sc.WARN, sc.BAD), r
    # 已启用但没设备 → 必须是 warn 且说清怎么办
    if r["level"] == sc.WARN and "设备" in r["detail"]:
        assert r["fix"]


def test_main_exit_code_reflects_bad_items(monkeypatch, capsys):
    monkeypatch.setattr(sc, "run_checks",
                        lambda: [sc._row(sc.BAD, "x", "y", "手动作业")])
    assert sc.main([]) == 1
    monkeypatch.setattr(sc, "run_checks",
                        lambda: [sc._row(sc.OK, "x", "y")])
    assert sc.main([]) == 0


def test_unsubscribed_channels_are_named(monkeypatch, tmp_path):
    """未订阅的渠道必须被**点名**——否则用户以为"没有这个能力"。

    飞猪 App 是最鲜活的例子：能力在、注册表也在，只是从未进过 platforms，
    于是近 30 天账本一条记录都没有，而界面上只显示"未启用"占位行。

    这里造一个临时根目录（干净检出里本来没有 config.yaml），
    否则 `check_config()` 会在"配置不存在"就返回，走不到未订阅那一段。
    """
    import yaml

    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump({"users": [{"platforms": ["ctrip"]}]},
                       allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(sc, "_root", lambda: str(tmp_path))
    r = sc.check_config()
    assert r["level"] == sc.WARN, r
    assert "未订阅" in r["detail"], r
    assert "app_fliggy" in r["detail"], r
    assert r["fix"]
