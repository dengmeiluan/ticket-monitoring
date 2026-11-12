# -*- coding: utf-8 -*-
"""fetch_packages 的校验逻辑测试。

为什么要测：这个脚本是"零配置"的第一道门。如果它把**坏包当成好包**
（GitHub 出错页、被截断的下载、版本不对），后面整条链都会以奇怪的
方式失败（模块显示已安装但不生效、App 秒崩），排查成本极高。
所以每条判据都要有反证。
"""
import importlib.util
import io
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _mod():
    p = os.path.join(ROOT, "scripts", "fetch_packages.py")
    spec = importlib.util.spec_from_file_location("fetch_packages", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _mkzip(tmp_path, entries):
    p = os.path.join(str(tmp_path), "m.zip")
    with zipfile.ZipFile(p, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return p


def test_packages_meta_complete():
    """清单里每个包都必须钉死 url/sha256/size/kind。"""
    m = _mod()
    assert m.PACKAGES
    for name, meta in m.PACKAGES.items():
        assert meta["url"].startswith("https://github.com/"), name
        assert len(meta["sha256"]) == 64, name
        assert meta["size"] > 0, name
        assert meta["kind"] in ("zygisk", "zygisk_impl"), name
        assert meta.get("note"), name


def test_valid_zygisk_module(tmp_path):
    m = _mod()
    p = _mkzip(tmp_path, {"module.prop": "id=x",
                          "zygisk/x86_64.so": b"\x7fELF"})
    ok, why = m.validate_zip(p, "zygisk")
    assert ok, why


def test_module_missing_zygisk_so_is_rejected(tmp_path):
    m = _mod()
    p = _mkzip(tmp_path, {"module.prop": "id=x", "service.sh": "echo"})
    ok, why = m.validate_zip(p, "zygisk")
    assert not ok and "zygisk" in why


def test_zygisk_impl_layout_is_accepted(tmp_path):
    """NeoZygisk 这类实现把库放在 lib/<abi>/libzygisk*.so，不是 zygisk/。"""
    m = _mod()
    p = _mkzip(tmp_path, {"module.prop": "id=zygisksu",
                          "lib/x86_64/libzygisk.so": b"\x7fELF"})
    ok, why = m.validate_zip(p, "zygisk_impl")
    assert ok, why
    # 用错 kind 要判错（这正是真机上踩到的第一版 bug）
    ok2, why2 = m.validate_zip(p, "zygisk")
    assert not ok2, "实现包不应被当成普通 zygisk 模块"


def test_html_error_page_is_rejected(tmp_path):
    """GitHub 出错时可能返回 HTML；不能当 zip 收下。"""
    m = _mod()
    p = os.path.join(str(tmp_path), "err.zip")
    io.open(p, "wb").write(b"<html>rate limited</html>")
    ok, why = m.validate_zip(p, "zygisk")
    assert not ok and "zip" in why.lower()


def test_missing_module_prop_is_rejected(tmp_path):
    m = _mod()
    p = _mkzip(tmp_path, {"zygisk/x86_64.so": b"\x7fELF"})
    ok, why = m.validate_zip(p, "zygisk")
    assert not ok and "module.prop" in why


def test_verify_file_size_and_sha(tmp_path):
    m = _mod()
    p = os.path.join(str(tmp_path), "a.bin")
    io.open(p, "wb").write(b"hello")
    import hashlib
    sha = hashlib.sha256(b"hello").hexdigest()
    ok, _ = m.verify_file(p, {"sha256": sha, "size": 5})
    assert ok
    ok, why = m.verify_file(p, {"sha256": sha, "size": 6})
    assert not ok and "大小" in why
    ok, why = m.verify_file(p, {"sha256": "0" * 64, "size": 5})
    assert not ok and "SHA256" in why
    ok, why = m.verify_file(os.path.join(str(tmp_path), "nope"),
                            {"sha256": sha, "size": 5})
    assert not ok and why == "缺失"
