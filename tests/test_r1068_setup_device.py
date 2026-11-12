# -*- coding: utf-8 -*-
"""setup_device（设备侧总入口）的纯逻辑测试。

钉住三件事：
  * 配置生成：缺失时从 example 复制，且**必须 LF**（仓库 EOL 门禁要求）
  * 缺 App 检测：如实报告哪些目标 App 没装，不能默默当成"齐全"
  * APK 安装：目录缺失/为空是**正常的跳过**，不是失败；装失败要判失败
"""
import importlib.util
import io
import os

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
