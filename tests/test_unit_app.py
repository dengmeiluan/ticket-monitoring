# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1260_app_qunar_horizon.py
- tests/test_r1886_app_channel_onboarding.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import glob
import io
import os
import re
import sys


# ---- merged from tests/test_r1260_app_qunar_horizon.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

APPS = ["app_ctrip.py", "app_fliggy.py", "app_tongcheng.py",
        "app_zhixing.py", "app_qunar.py"]


def _src(name):
    return io.open(os.path.join(ROOT, "crawlers", name), encoding="utf-8").read()


def test_every_app_crawler_guards_far_dates():
    """五个 App 渠道都要有视野守卫（今天只有 qunar 缺）。"""
    missing = [n for n in APPS if "reject_far_dates(" not in _src(n)]
    assert not missing, "这些 App 渠道没有日期视野守卫：%s" % missing


def test_qunar_orders_guards_before_touching_device():
    s = _src("app_qunar.py")
    i_fetch = s.find("def fetch(self, from_city")
    assert i_fetch > 0
    seg = s[i_fetch:i_fetch + 1200]
    i_early = seg.find("self.early_skip(dates)")
    i_far = seg.find("self.reject_far_dates(dates)")
    i_rt = seg.find("self.runtime()")
    assert i_early > 0 and i_far > i_early, (i_early, i_far)
    assert i_rt > i_far, "视野守卫必须在碰设备之前（否则照样耗设备时间）"


def test_siblings_still_have_it():
    """负控：不许为了"统一"把兄弟渠道那一处删掉。"""
    for n in APPS[:-1]:
        assert "reject_far_dates(" in _src(n), n


# ---- merged from tests/test_r1886_app_channel_onboarding.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    return io.open(os.path.join(ROOT, rel), encoding="utf-8").read()


def test_doc_has_three_step_onboarding():
    d = _read("docs/APP_CHANNELS.md")
    assert "## 开启 App 渠道（三步）" in d, "缺「开启 App 渠道（三步）」小节"
    for k in ("python -m core.setup_check --fix",
              "python scripts/setup_device.py --apply --reboot --enable-app-channels",
              "http://127.0.0.1:8765"):
        assert k in d, "引导缺关键命令：" + k
    # 四个 adb 卡点必须写全（issue 里用户就卡在这）
    for k in ("ADB 调试", "--adb", "--serial", "16384"):
        assert k in d, "卡点说明缺：" + k


def test_setup_check_hint_is_actionable():
    s = _read("core/setup_check.py")
    assert "_APP_ON_HINT" in s, "setup_check 没有可执行的三步提示"
    i = s.index("_APP_ON_HINT")
    seg = s[i:i + 900]
    assert "--enable-app-channels" in seg, "提示里没给开启 App 渠道的命令"
    assert "docs/APP_CHANNELS.md" in seg, "提示没指向操作手册"
    assert "setup_device.py" in seg, "提示没给 setup_device 命令"


def test_setup_device_supports_onboarding_flags():
    s = _read("scripts/setup_device.py")
    for flag in ('"--enable-app-channels"', '"--mumu"', '"--vm"',
                 '"--apply"', '"--reboot"'):
        assert flag in s, "setup_device.py 缺参数：" + flag


def test_setup_device_resolves_mumu_dir_when_dirs_given(tmp_path):
    """`--mumu` 传目录时，要能自动补到 nx_main/MuMuManager.exe。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "sd", os.path.join(ROOT, "scripts", "setup_device.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    assert m._resolve_mumu(None) == ""
    root = tmp_path / "MuMuPlayer-12.0"
    (root / "nx_main").mkdir(parents=True)
    exe = root / "nx_main" / "MuMuManager.exe"
    exe.write_bytes(b"")
    assert m._resolve_mumu(str(root)) == str(exe)
    assert m._resolve_mumu(str(exe)) == str(exe)
