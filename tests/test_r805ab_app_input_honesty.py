# -*- coding: utf-8 -*-
"""r805ab：内嵌画面的「输入文字」不许谎报成功。

用户原话：「问题内嵌画面切换 app 的时候没有正确切换 …… 然后整体能力
感觉比较有限」。

真机实测（2026-11-01，MuMu 127.0.0.1:16384，去哪儿 App）：

    tap 城市位      → 帧 sha1 变化、进入城市页「选择出发地」     ✅
    input "bei"     → **帧 sha1 完全相同、视图树文本零变化**，
                      而 `/api/app-login/input` 回的是 ok        ❌

根因：`adb shell input text` 在**没有聚焦输入框**时同样返回成功——命令
发出去了，字掉在地上。原 `input_text` 只判「命令没报错」，于是用户点
「输入文字」后接口回 ok、画面一动不动，读作「这个功能是假的」。

修复：输入后回读视图树，确认目标文本真的出现；没有就返回 False，
前端提示改成可操作的一句话（「先在手机画面里点一下输入框」）。

判据（三层，各自可独立证伪）：
  1. 源码层：`input_text` 必须回读视图树校验，不能只判 subprocess；
  2. 行为层：**用真实 AdbDevice 的替身**喂两种 dump（无文本/有文本），
     返回值必须分别是 False / True——防「加了校验但永远返回 True」；
  3. 前端层：失败提示要含下一步动作，不能只说「输入失败」。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _src(rel):
    return io.open(os.path.join(ROOT, rel), encoding="utf-8").read()


def test_input_text_verifies_ui_not_just_command():
    body = _src("core/android/device.py")
    i = body.index("    def input_text(")
    j = body.index("\n    def ", i + 10)
    seg = body[i:j]
    assert "self.dump()" in seg, (
        "input_text 没有回读视图树：无焦点时 adb 照样回成功，"
        "函数会谎报「已输入」")
    assert "return want in page" in seg or "want in page" in seg, (
        "input_text 读了 dump 却没拿它做判定，等于没校验")


def test_input_text_returns_false_when_text_absent(monkeypatch=None):
    """行为层：文本没进界面时必须返回 False（用替身，不连设备）。"""
    from core.android.device import AdbDevice

    dev = AdbDevice.__new__(AdbDevice)          # 不跑 __init__（无设备）

    class _D:
        n = 0

        def __call__(self):
            _D.n += 1
            return '<node text="出发城市"/>'     # 页面里没有 zzQ9

    dev.dump = _D()
    dev._sh = lambda *a, **k: ""                # 「命令成功」
    got = dev.input_text("zzQ9")
    assert got is False, (
        "文本没出现在视图树里却返回 %r：用户会看到「已输入」而画面没变" % got)

    class _D2:
        def __call__(self):
            return '<node text="zzQ9"/>'

    dev.dump = _D2()
    got2 = dev.input_text("zzQ9")
    assert got2 is True, "文本确实进了界面却返回 %r（校验过头）" % got2


def test_frontend_input_failure_tells_next_step():
    src = _src("webui.py")
    i = src.index("function appLoginText(")
    seg = src[i:src.index("\nfunction ", i)]
    assert "没输进去" in seg or "点一下输入框" in seg, (
        "输入失败只回「输入失败」，用户不知道下一步该做什么")
