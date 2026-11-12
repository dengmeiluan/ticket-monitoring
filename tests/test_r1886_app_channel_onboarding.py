# -*- coding: utf-8 -*-
"""门禁：App 渠道「开启引导」必须能照着做（issue #16）。

用户报「App通道无法开启，请指导」时，原先两条提示都只说"你该做什么"，不给能粘的命令：
  ⚠ 配置     未订阅 app_* → 想采就在 users[].platforms 里加上
  ⚠ App 通路  模拟器在跑但 adb 状态是 absent → 跑一次重启即可（--fix 会自动重启）

这条门禁钉住三件事，防止引导再次退化：
1. `docs/APP_CHANNELS.md` 有「开启 App 渠道（三步）」小节，且三条命令齐全；
2. `core/setup_check.py` 的提示直接给出可执行命令并指向该小节；
3. `scripts/setup_device.py` 真的支持 `--enable-app-channels` / `--mumu` / `--vm`。
"""
import io
import os

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
