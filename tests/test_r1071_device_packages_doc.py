# -*- coding: utf-8 -*-
"""文档与代码同源校验：`docs/DEVICE_PACKAGES.md` ↔ `scripts/fetch_packages.py`

为什么值得钉：这张表是用户唯一的"包从哪来"来源。一旦代码换了版本
（url/sha256/size）而文档没跟，用户会照旧地址下载到旧包、或按旧哈希校验失败，
表现为"脚本说包不对，但我明明按文档下的"。所以让测试替我们对齐。
"""
import importlib.util
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

DOC = os.path.join(ROOT, "docs", "DEVICE_PACKAGES.md")
PKG_README = os.path.join(ROOT, "packages", "README.md")


def _mod(name, filename):
    p = os.path.join(ROOT, "scripts", filename)
    spec = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _doc():
    return open(DOC, encoding="utf-8").read()


def test_packages_table_matches_code():
    """每个模块的地址/大小/SHA256 都必须原样出现在文档里。"""
    m = _mod("fetch_packages", "fetch_packages.py")
    doc = _doc()
    for name, meta in m.PACKAGES.items():
        assert meta["url"] in doc, "%s 的下载地址不在文档里" % name
        assert meta["sha256"] in doc, "%s 的 SHA256 不在文档里" % name
        assert str(meta["size"]) in doc, "%s 的大小不在文档里" % name
        assert name in doc, "%s 文件名不在文档里" % name


def test_mumu_url_matches_code():
    """MuMu 官网地址与 bootstrap 里的提示常量同源。"""
    from core.android import bootstrap as bs
    assert bs.MUMU_DOWNLOAD_HINT in _doc()


def test_ndk_url_present_and_plausible():
    doc = _doc()
    assert "android-ndk-r27c-windows.zip" in doc
    assert "dl.google.com" in doc


def test_app_package_names_match_setup_device():
    """文档里列的包名必须与 setup_device.APPS 一致（不多不少）。"""
    m = _mod("setup_device", "setup_device.py")
    doc = _doc()
    for pkg in m.APPS:
        assert pkg in doc, "文档缺少包名 %s" % pkg
    # 反向：文档里出现的 ctrip/android 形态包名也应被覆盖（防漏更新）
    found = set(re.findall(r"`([a-z]+\.[a-z0-9_.]+)`", doc))
    app_like = {f for f in found if f.startswith(
        ("ctrip.", "com.taobao", "com.Qunar", "com.tongcheng", "cn.suanya"))}
    assert app_like <= set(m.APPS), app_like - set(m.APPS)


def test_doc_declares_not_redistributing_apks():
    """必须明确写"仓库不分发 APK"——否则用户会以为能直接拿到。"""
    doc = _doc()
    assert "不分发" in doc


def test_packages_readme_points_to_doc():
    txt = open(PKG_README, encoding="utf-8").read()
    assert "docs/DEVICE_PACKAGES.md" in txt, "packages/README.md 应指向地址清单"


def test_dir_convention_documented():
    """目录约定（packages/、packages/apks/、build/）要写在文档里。"""
    doc = _doc()
    for p in ("packages/", "packages/apks/", "build/"):
        assert p in doc, p
