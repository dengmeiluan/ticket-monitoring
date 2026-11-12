# -*- coding: utf-8 -*-
"""r1063 T108：maps 洗白模块的**打包契约**（纯 Python，可离线单测）。

为什么要测打包而不是"顺手 zip 一下"：
模块 zip 的内部路径一旦写错，Magisk 会**静默不加载**（表现为"什么都没发生"），
而这正是本项目里最贵的一类失败——查半天以为是 App 的问题。
所以把"目录必须长成什么样"钉成断言：

```
module.prop
zygisk/arm64-v8a.so
zygisk/x86_64.so
config/global.json
```

同时钉住配置校验：`enabled/packages/markers` 缺一个就拒绝打包
（缺 `markers` 等于过滤器什么都不删，会静默失效）。
"""
import io
import json
import os
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.android.maps_cloak_pack import build_module, load_config  # noqa: E402

GOOD = {"enabled": True, "packages": ["com.taobao.trip"],
        "markers": ["houdini", "nemu"]}


def _cfg(tmp_path, obj):
    p = tmp_path / "global.json"
    p.write_text(json.dumps(obj), encoding="utf-8")
    return str(p)


def test_load_config_ok(tmp_path):
    got = load_config(_cfg(tmp_path, GOOD))
    assert got["packages"] == ["com.taobao.trip"]
    assert got["markers"] == ["houdini", "nemu"]


def test_load_config_rejects_missing_markers(tmp_path):
    with pytest.raises(ValueError):
        load_config(_cfg(tmp_path, {"enabled": True,
                                    "packages": ["com.taobao.trip"]}))


def test_load_config_rejects_missing_packages(tmp_path):
    with pytest.raises(ValueError):
        load_config(_cfg(tmp_path, {"enabled": True, "markers": ["houdini"]}))


def test_load_config_rejects_empty_markers(tmp_path):
    """空词表 = 过滤器不删任何行 = 静默失效，必须拒绝。"""
    with pytest.raises(ValueError):
        load_config(_cfg(tmp_path, {"enabled": True,
                                    "packages": ["a"], "markers": []}))


def test_build_module_layout(tmp_path):
    so = tmp_path / "a.so"
    so.write_bytes(b"\x7fELF")
    out = build_module(str(tmp_path / "o.zip"),
                       {"arm64-v8a": str(so), "x86_64": str(so)}, GOOD)
    names = set(zipfile.ZipFile(out).namelist())
    assert {"module.prop", "zygisk/arm64-v8a.so", "zygisk/x86_64.so",
            "config/global.json"} <= names, names


def test_module_prop_has_required_keys(tmp_path):
    so = tmp_path / "a.so"
    so.write_bytes(b"\x7fELF")
    out = build_module(str(tmp_path / "o.zip"),
                       {"arm64-v8a": str(so), "x86_64": str(so)}, GOOD)
    prop = zipfile.ZipFile(out).read("module.prop").decode("utf-8")
    for key in ("id=tm_maps_cloak", "name=", "version=", "description="):
        assert key in prop, prop


def test_config_inside_zip_matches_input(tmp_path):
    so = tmp_path / "a.so"
    so.write_bytes(b"\x7fELF")
    out = build_module(str(tmp_path / "o.zip"),
                       {"arm64-v8a": str(so), "x86_64": str(so)}, GOOD)
    got = json.loads(zipfile.ZipFile(out).read("config/global.json")
                     .decode("utf-8"))
    assert got == GOOD


def test_build_requires_both_abis(tmp_path):
    so = tmp_path / "a.so"
    so.write_bytes(b"\x7fELF")
    with pytest.raises(ValueError):
        build_module(str(tmp_path / "o.zip"), {"arm64-v8a": str(so)}, GOOD)

def test_zip_contains_service_sh_and_packages_list(tmp_path):
    """开机自动生效的两件东西必须在包里：service.sh 与 packages.list。"""
    so = tmp_path / "a.so"
    so.write_bytes(b"\x7fELF")
    out = build_module(str(tmp_path / "o.zip"),
                       {"arm64-v8a": str(so), "x86_64": str(so)}, GOOD)
    z = zipfile.ZipFile(out)
    names = set(z.namelist())
    assert {"service.sh", "config/packages.list"} <= names, names
    svc = z.read("service.sh").decode("utf-8")
    assert "setprop wrap.$pkg" in svc
    assert "/data/adb/modules" in svc and "disable" in svc
    assert z.read("config/packages.list").decode().strip() == "com.taobao.trip"
