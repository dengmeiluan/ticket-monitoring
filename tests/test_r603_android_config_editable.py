# -*- coding: utf-8 -*-
"""r603：Android 真机通道的配置项必须能在配置页改。

并行会话新增了 `core/android/config.py`（智行/美团 App 只能走真机，没有
可用 Web 入口），字段齐全且每项都做了钳制，但**配置页一个控件都没有**——
用户只能去手改 config.yaml。r601 的通用不变式门禁当场抓到了这 5 个键：

    android.install_dir / vm_index / boot_timeout_s / action_timeout_s / snapshot

（`enabled`/`provider` 因为键名与别处重名，当时被宽口径匹配漏过去了；
本轮 7 个字段全部补齐并逐个断言。）

取值范围必须与 `core/android/config.py` 的钳制逐项一致，否则界面能填出
后端会悄悄改掉的值——那本身就是「配了不生效」：
    vm_index        0..64
    boot_timeout_s  10..600
    action_timeout_s 5..900
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

IDS = {"enabled": "glbAndEn", "provider": "glbAndPv",
       "install_dir": "glbAndDir", "vm_index": "glbAndVm",
       "boot_timeout_s": "glbAndBoot", "action_timeout_s": "glbAndAct",
       "snapshot": "glbAndSnap"}


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def test_readback_exposes_android_block():
    w = _w()
    i = w.index('elif self.path == "/api/config":')
    # 按**真实分支**定位（r628）：原先固定取 9000 字符窗口，被 demo 分支的
    # 注释撑爆后会误判成「没回读」。这里跳到 demo 分支配偶之后再看。
    j = w.index('self._json(_demo_config_payload())', i)
    seg = w[j:j + 9000]
    assert '"android": dict(cfg.get("android") or {})' in seg, (
        "GET /api/config 没有回读 android 段，控件只能显示空")


def test_every_android_field_has_a_control():
    w = _w()
    for field, cid in IDS.items():
        assert "'%s'" % cid in w, "缺少 %s 的控件（%s）" % (field, cid)
    i = w.index("Android 真机通道")
    seg = w[i:i + 3000]
    for field in IDS:
        assert field in seg, "Android 配置区没有写回 %s" % field


def test_control_ranges_match_backend_clamps():
    """控件范围必须与后端钳制一致，否则「填了等于没填」。"""
    w = _w()
    i = w.index("Android 真机通道")
    seg = w[i:i + 3000]
    assert "Math.min(64" in seg, "vm_index 上限与后端 64 不一致"
    assert "Math.min(600,parseInt(this.value)||180)" in seg, (
        "boot_timeout_s 未按后端 10..600 / 默认 180 钳制")
    assert "Math.min(900,parseInt(this.value)||60)" in seg, (
        "action_timeout_s 未按后端 5..900 / 默认 60 钳制")


def test_post_persists_android_block():
    w = _w()
    i = w.index('if isinstance(glb.get("android"), dict):')
    seg = w[i:i + 1600]
    assert 'cfg["android"] = _a0' in seg, "POST 没有写回 cfg['android']"
    for field in ("enabled", "provider", "install_dir", "vm_index",
                  "boot_timeout_s", "action_timeout_s", "snapshot"):
        assert '"%s"' % field in seg, "POST 没有落 %s" % field
    # 与后端同界：越界要钳回，不能把脏值写进文件
    assert "max(_alo, min(_ahi, _av))" in seg, "数值没有按后端区间钳制"
