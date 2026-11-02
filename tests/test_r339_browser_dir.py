# -*- coding: utf-8 -*-
"""crawler.browser_dir 配置键：chromium 内核缓存位可配置（论坛用户反馈
「WIN 安装的依赖文件全堆在 C 盘」——playwright 默认装进
%LOCALAPPDATA%\\ms-playwright，约 500MB 不可选盘）。默认空=渠道默认
位行为不变；配置后安装与查找经 PLAYWRIGHT_BROWSERS_PATH 全部指向
该目录。启动级语义：内核安装发生在启动检查点，运行中改配置不迁移
已装内核（全局卡标注 ♻ 重启生效）。
"""
import os

import main


def test_browser_dir_sets_env(monkeypatch):
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    try:
        assert main._apply_browser_dir(
            {"crawler": {"browser_dir": "~/pw-cache"}}) is True
        v = os.environ["PLAYWRIGHT_BROWSERS_PATH"]
        assert os.path.isabs(v) and v.endswith("pw-cache")
        assert "~" not in v  # expanduser 已展开
    finally:
        # _apply_browser_dir 直写 os.environ 不经 monkeypatch——delenv
        # 对缺席变量不登记 undo，直接写入会泄漏全程（后位一切
        # chromium.launch 找去 pw-cache 全灭实录）；显式还原
        os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)


def test_browser_dir_empty_keeps_default(monkeypatch):
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    assert main._apply_browser_dir({"crawler": {"browser_dir": ""}}) is False
    assert "PLAYWRIGHT_BROWSERS_PATH" not in os.environ


def test_browser_dir_missing_key_keeps_default(monkeypatch):
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    assert main._apply_browser_dir({}) is False
    assert "PLAYWRIGHT_BROWSERS_PATH" not in os.environ


def test_browser_dir_overrides_existing_env(monkeypatch):
    # 配置优先律：显式配置压过进程外继承的旧环境变量（如用户手动
    # set 过旧路径后改用配置文件——配置是单一事实源）
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", r"D:\old-cache")
    assert main._apply_browser_dir(
        {"crawler": {"browser_dir": r"D:\new-cache"}}) is True
    # 断言值=配置路径的 abspath（实现语义：env 落绝对形态——Linux 上
    # 盘符路径是相对形态会被 abspath 加 cwd 前缀，Windows 原样；两
    # 平台各自成立，直接对表实现同式，CI-Linux 差异当日红定谳）
    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == \
        os.path.abspath(os.path.expanduser(r"D:\new-cache"))


def test_browser_dir_wired_at_startup():
    # 接线钉：main() 在 ensure_chromium 之前应用（内核安装与查找同轨）
    src = open("main.py", encoding="utf-8").read()
    apply_pos = src.index("def _apply_browser_dir")
    call_pos = src.index("_apply_browser_dir(cfg)")
    chrom_pos = src.index("ensure_chromium(cfg.get(\"platforms\")")
    assert apply_pos < call_pos < chrom_pos


def test_browser_dir_four_way_domain():
    # 配置面四方域律（LESSONS 十四§8）：选项域==消费域==验证域==演示域
    # 同轮对齐——任一方单独缺席当日红
    src = open("webui.py", encoding="utf-8").read()
    assert '"browser_dir": str(' in src, "供给域（/api/config globals）缺席"
    assert 'glb.get("browser_dir") is not None' in src, "保存域缺席"
    assert "'glbBdir'" in src, "选项域（全局卡 glcell 行）缺席"
    assert '"browser_dir": ""' in src, "演示域（demo 夹具取值形态）缺席"
