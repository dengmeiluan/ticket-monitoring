# -*- coding: utf-8 -*-
"""r1063 T97：把"跑的是旧发行版"这件事变成自检能说出来的结论。

本轮真机撞到的坑：面板上那个实例是**发行版 v1.5.307**，而源码 `main.py` 是
`__version__ = "1.6.0"`。于是这几轮做的所有改进（u2 取树 6 倍、设备脸自洽、
双端固定登录、50003 处置……）**在那个实例里一项都没有**，但界面看起来一切正常。

这属于最贵的误解："我改了怎么没效果"。所以自检要主动比对：

```
⚠ 运行实例   本机在跑 v1.5.307（端口 8765），而这份源码是 v1.6.0 —— 源码里的改进尚未生效
              → 停掉旧实例后从源码跑：python main.py；或重新打包发行版
```

顺带补了 `.gitignore`：`.tmp_*/`、`config.yaml.bak_*`、`prices.db`、
`_mumu_backup_*/` 都不该进库——新 clone 一份干净的仓库是"下载即用"的一部分。
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_source_version_is_read():
    from core import setup_check as sc
    v = sc._source_version()
    assert v and v[0].isdigit(), v
    # 与 main.py 里的一致
    txt = io.open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    assert '__version__ = "%s"' % v in txt


def test_running_instance_row_exists_and_shaped():
    from core import setup_check as sc
    row = sc.check_running_instance(port_hint=1)   # 1 号端口必然连不上
    assert row.get("name") == "运行实例"
    assert row.get("level") in ("ok", "warn", "info")


def test_warns_when_version_differs(monkeypatch):
    """实例版本与源码不一致时必须 warn，并给出两条出路。"""
    import json
    import urllib.request

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"version": "0.0.1-old"}).encode()

    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: _Resp())
    from core import setup_check as sc
    row = sc.check_running_instance(port_hint=8765)
    assert row["level"] == "warn"
    assert "尚未生效" in row["detail"]
    assert "python main.py" in row["fix"]


def test_row_is_wired_into_run_checks():
    src = io.open(os.path.join(ROOT, "core", "setup_check.py"),
                  encoding="utf-8").read()
    i = src.index("def run_checks")
    assert "check_running_instance()" in src[i:i + 500]


def test_gitignore_covers_runtime_artifacts():
    gi = io.open(os.path.join(ROOT, ".gitignore"), encoding="utf-8").read()
    for pat in (".tmp_*/", "config.yaml.bak_*", "prices.db",
                "_mumu_backup_*/"):
        assert pat in gi, pat
