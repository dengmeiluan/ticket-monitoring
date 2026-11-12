# -*- coding: utf-8 -*-
"""r499：同端口起第二个 demo 必须在动数据**之前**退出。

旧顺序：`build_demo_db` → 绑定端口。而 `build_demo_db` 里有一句
`DELETE FROM flight_prices`（演示库按需重建）。Windows 下
`allow_reuse_address = False`，绑定必然失败——但那时第一个实例
**正在用的数据已经被清空**，且第二个实例只是抛 traceback 崩掉，
用户完全看不出「我刚刚把第一个实例的数据毁了」。

实测（隔离子进程，两个 demo 同端口同库）：
  旧顺序：首实例写入的行被清掉（1 → 0），第二个实例 exit=1 无提示；
  新顺序：数据完好（1 → 1），第二个实例 exit=0 并打印「端口已被占用」。

为什么第二个实例退出码是 0：demo 是可选演示，端口被占时友好提示后
正常返回才对——报错误码会被脚本包装误判成崩溃。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_bind_happens_before_building_the_db():
    """先占端口再建库：顺序反了会毁掉正在运行实例的数据。"""
    w = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                newline="").read()
    i = w.index("def _demo_main(")
    seg = w[i:i + 4000]
    bind = seg.index("_Srv((\"127.0.0.1\", args.port)", 0)
    build = seg.index("build_demo_db(db)")
    assert bind < build, (
        "绑定端口必须在建库之前：否则第二个实例会先把库里数据 DELETE 掉，"
        "再绑定失败退出，第一个实例的数据无声丢失")


def test_duplicate_demo_prints_a_clear_hint():
    w = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                newline="").read()
    i = w.index("def _demo_main(")
    seg = w[i:i + 4000]
    assert "已被占用" in seg, "端口被占时没有给人看得懂的提示"
    assert "return" in seg[seg.index("已被占用") - 200:], \
        "端口被占后未直接返回（会继续建库毁数据）"


def test_srv_is_bound_only_once():
    """绑定后不得在后续流程里再建一次（二次绑定必失败）。"""
    w = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                newline="").read()
    i = w.index("def _demo_main(")
    j = w.index("\ndef ", i + 10) if "\ndef " in w[i + 10:] else len(w)
    seg = w[i:j]
    n = seg.count("_Srv((\"127.0.0.1\", args.port)")
    assert n == 1, "demo 入口里 _Srv 创建了 %d 次（应恰好 1 次）" % n
