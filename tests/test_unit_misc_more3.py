# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1068_setup_device.py
- tests/test_r366_source_strip.py
- tests/test_r402_ctrip_no_empty_on_failure.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import importlib.util
import io
import os
import re
import sys


# ---- merged from tests/test_r1068_setup_device.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _mod():
    p = os.path.join(ROOT, "scripts", "setup_device.py")
    spec = importlib.util.spec_from_file_location("setup_device", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class FakeDev:
    """有状态的假设备：`pm install` 会被记进已装集合，便于验证"装后复核"。"""

    def __init__(self, packages="", install_result="Success",
                 install_adds=None):
        self.packages = set(
            x for x in packages.split("\n") if x.startswith("package:"))
        self.install_result = install_result
        self.install_adds = install_adds      # 安装成功后应出现的包名
        self.sent = []

    def sh(self, cmd, timeout=None):
        self.sent.append(cmd)
        if cmd.startswith("pm list packages"):
            return "\n".join(sorted(self.packages)) + ("\n" if self.packages else "")
        if cmd.startswith("pm install"):
            if "Success" in self.install_result and self.install_adds:
                self.packages.add("package:" + self.install_adds)
            return self.install_result
        return ""

    def push(self, a, b):
        self.sent.append("push %s" % a)
        return ""


def test_ensure_config_copies_example_lf(tmp_path, monkeypatch):
    m = _mod()
    monkeypatch.setattr(m, "ROOT", str(tmp_path))
    io.open(os.path.join(str(tmp_path), "config.example.yaml"), "wb").write(
        b"a: 1\r\nb: 2\r\n")
    ok, msg = m.ensure_config(log=lambda *_: None)
    assert ok, msg
    out = io.open(os.path.join(str(tmp_path), "config.yaml"), "rb").read()
    assert b"\r" not in out, "复制出来的配置必须统一成 LF"
    assert out == b"a: 1\nb: 2\n"


def test_ensure_config_keeps_existing(tmp_path, monkeypatch):
    m = _mod()
    monkeypatch.setattr(m, "ROOT", str(tmp_path))
    io.open(os.path.join(str(tmp_path), "config.yaml"), "w").write("mine: 1\n")
    io.open(os.path.join(str(tmp_path), "config.example.yaml"), "w").write(
        "other: 1\n")
    ok, msg = m.ensure_config(log=lambda *_: None)
    assert ok and "已存在" in msg
    assert "mine" in io.open(os.path.join(str(tmp_path), "config.yaml")).read()


def test_missing_apps_reports_all_when_none_installed():
    m = _mod()
    dev = FakeDev(packages="package:com.unrelated.app")
    lack = m.missing_apps(dev)
    assert len(lack) == len(m.APPS)
    assert any("携程" in x for x in lack)


def test_missing_apps_empty_when_all_installed():
    m = _mod()
    pkgs = "\n".join("package:" + p for p in m.APPS)
    assert m.missing_apps(FakeDev(packages=pkgs)) == []


def test_install_apks_without_dir_is_skip_not_failure(tmp_path):
    m = _mod()
    ok, msg = m.install_apks(FakeDev(), os.path.join(str(tmp_path), "nope"))
    assert ok, msg
    assert "跳过" in msg


def test_install_apks_empty_dir_is_skip(tmp_path):
    m = _mod()
    d = os.path.join(str(tmp_path), "apks")
    os.makedirs(d)
    ok, msg = m.install_apks(FakeDev(), d)
    assert ok and "跳过" in msg


def test_install_apks_success(tmp_path):
    m = _mod()
    d = os.path.join(str(tmp_path), "apks")
    os.makedirs(d)
    io.open(os.path.join(d, "ctrip.apk"), "wb").write(b"PK\x03\x04fake")
    dev = FakeDev(install_result="Success",
                  install_adds="ctrip.android.view")
    ok, msg = m.install_apks(dev, d)
    assert ok and "安装=" in msg, msg
    assert any(c.startswith("pm install") for c in dev.sent)


def test_install_apks_skips_already_installed(tmp_path):
    """已装就跳过：原来读了 pm list packages 却没用，每次都全量重装。"""
    m = _mod()
    d = os.path.join(str(tmp_path), "apks")
    os.makedirs(d)
    io.open(os.path.join(d, "ctrip.apk"), "wb").write(b"PK\x03\x04fake")
    dev = FakeDev(packages="package:ctrip.android.view")
    ok, msg = m.install_apks(dev, d)
    assert ok, msg
    assert "已装跳过" in msg
    assert not any(c.startswith("pm install") for c in dev.sent), dev.sent
    assert not any(c.startswith("push") for c in dev.sent), "已装不该再 push"


def test_install_apks_verifies_package_after_install(tmp_path):
    """pm install 回 Success 但包里查不到 → 必须判失败，不能假装装好。"""
    m = _mod()
    d = os.path.join(str(tmp_path), "apks")
    os.makedirs(d)
    io.open(os.path.join(d, "ctrip.apk"), "wb").write(b"PK\x03\x04fake")
    dev = FakeDev(install_result="Success")   # 不往已装集合里加
    ok, msg = m.install_apks(dev, d)
    assert not ok and "装后查不到包" in msg, msg


def test_install_apks_unknown_name_still_installs(tmp_path):
    """文件名认不出是哪个 App 时照装，但要如实标注"未复核包名"。"""
    m = _mod()
    d = os.path.join(str(tmp_path), "apks")
    os.makedirs(d)
    io.open(os.path.join(d, "weird-name.apk"), "wb").write(b"PK\x03\x04fake")
    dev = FakeDev(install_result="Success")
    ok, msg = m.install_apks(dev, d)
    assert ok, msg
    assert "未复核包名" in msg
    assert any(c.startswith("pm install") for c in dev.sent)


def test_guess_package_by_filename():
    m = _mod()
    assert m.guess_package("ctrip.apk") == "ctrip.android.view"
    assert m.guess_package("fliggy-9.0.apk") == "com.taobao.trip"
    assert m.guess_package("qunar.apk") == "com.Qunar"
    assert m.guess_package("tongcheng.apk") == "com.tongcheng.android"
    assert m.guess_package("zhixing.apk") == "cn.suanya.zhixing"
    assert m.guess_package("unknown.apk") == ""


def test_install_apks_failure_is_reported(tmp_path):
    m = _mod()
    d = os.path.join(str(tmp_path), "apks")
    os.makedirs(d)
    io.open(os.path.join(d, "x.apk"), "wb").write(b"PK\x03\x04fake")
    ok, msg = m.install_apks(FakeDev(install_result="Failure [INSTALL_FAILED_]"),
                             d)
    assert not ok and "失败=" in msg


# ---------------- 配置侧零配置（platforms 文本手术） ----------------

def test_add_platforms_inline_form():
    m = _mod()
    out, added = m.add_platforms("platforms: [qunar, fliggy]\nx: 1\n",
                                 ["app_zhixing"])
    assert added == ["app_zhixing"]
    assert "platforms: [qunar, fliggy, app_zhixing]" in out
    assert out.endswith("\n")


def test_add_platforms_block_form():
    m = _mod()
    txt = "platforms:\n  - qunar\nx: 1\n"
    out, added = m.add_platforms(txt, ["app_qunar"])
    assert added == ["app_qunar"]
    assert "  - app_qunar" in out
    # 不能把后续键吃掉
    assert "x: 1" in out


def test_add_platforms_skips_comment_line():
    """真配置里有 `# ... platforms: [] ...` 这类说明行，不能被当成配置段。"""
    m = _mod()
    txt = ("# 恢复方法：把这一行改回 platforms: [] 即可\n"
           "platforms: [qunar]\ny: 2\n")
    out, added = m.add_platforms(txt, ["app_zhixing"])
    assert added == ["app_zhixing"]
    lines = out.splitlines()
    assert lines[0].startswith("#"), "注释行必须原样保留"
    assert "platforms: [qunar, app_zhixing]" in out


def test_add_platforms_idempotent():
    m = _mod()
    txt = "platforms: [qunar, app_zhixing]\n"
    out, added = m.add_platforms(txt, ["app_zhixing"])
    assert added == []
    assert out == txt


def test_enable_app_channels_flips_android_enabled(tmp_path):
    m = _mod()
    p = os.path.join(str(tmp_path), "config.yaml")
    io.open(p, "wb").write(
        b"platforms: [qunar]\nandroid:\n  magisk:\n    enabled: true\n"
        b"  enabled: false\nother:\n  enabled: false\n")
    ok, msg = m.enable_app_channels(p, ids=("app_zhixing",), log=lambda *_: None)
    assert ok, msg
    out = io.open(p, "rb").read().decode("utf-8")
    assert "app_zhixing" in out
    # android 段内的 enabled 要被打开
    assert "  enabled: true" in out
    # 其它段的 enabled: false 不能被误改
    assert "other:\n  enabled: false" in out or out.rstrip().endswith(
        "enabled: false")


# ---- merged from tests/test_r366_source_strip.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = webui_full_src()


def test_source_access_is_compact_strip_not_three_tall_cards():
    assert "#srccap{display:flex;align-items:center;gap:8px 12px" in SRC
    assert ("#srccap .scnode{display:inline-flex;flex-direction:row;"
            "align-items:center") in SRC
    assert "#srccap .scnode em{display:none}" in SRC
    # r873：说明已从「诊断卡直接子元素」再收进来源条 #srccap 内
    # （绝对定位、宽随卡），与触发器同宽同左缘——守「说明默认收起」这一意图。
    assert "#srccap .scnote{display:none" in SRC
    assert 'id="scNoteBtn"' in SRC and 'id="scNote"' in SRC
    assert "function srxToggleScNote(btn){" in SRC
    assert 'title="PC 网页已于 2026-10-10 停服"' in SRC


def test_source_access_mobile_is_two_row_grid_without_tall_stack():
    assert "#srccap .scpath{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr)" in SRC
    assert "#srccap .scnode.gate{grid-column:1/-1;justify-content:flex-start}" in SRC
    assert "#srccap .scarr{display:none}" in SRC


# ---- merged from tests/test_r402_ctrip_no_empty_on_failure.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return open(os.path.join(here, "crawlers", "ctrip.py"),
                encoding="utf-8").read()


def test_no_response_is_error_not_empty():
    s = _src()
    i = s.index('"国际列表请求无响应"')
    block = s[max(0, i - 400):i + 400]
    assert '_status = "blocked" if _blocked else "error"' in block, block


def test_unparsed_is_error_not_empty():
    s = _src()
    i = s.index('"国际列表未解析到航班"')
    block = s[max(0, i - 300):i + 500]
    assert 'else "error"' in block, block
    assert 'else "empty"' not in block, block


def test_login_still_wins_over_error():
    """登录墙仍优先于 error（重登才能解，重试不能）。"""
    s = _src()
    i = s.index('"国际列表未解析到航班"')
    block = s[max(0, i - 300):i + 500]
    assert '"login" if need_login' in block, block


def test_explicit_no_flights_keeps_empty():
    """真正"明确无票"的地方仍应能记 empty（别把修复做过头）。

    携程国际这里没有"明确无票"的措辞分支，故整体不应再出现
    未解析→empty；但 blocked/login/ok 三个分支必须还在。
    """
    s = _src()
    for token in ('"blocked"', '"login"', '"ok"'):
        assert token in s
    assert re.search(r'_status = "blocked" if _blocked else "error"', s)
