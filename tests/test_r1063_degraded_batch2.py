# -*- coding: utf-8 -*-
"""r1063 T61：再清三处「静默失败 = 能力悄悄失效」（降级账本的第二批）。

挑的标准仍是 T60 那条：**失败等于某项能力静默失效**，不是单次网络抖动。

| 位置 | 失败意味着 |
|---|---|
| `crawlers/base.py` 注入 stealth init script | **整个伪装没生效**（页面依旧是自动化特征） |
| `crawlers/captcha.py` 点选题截图 | 没有图就没有识别输入（≠「检测不到目标」） |
| `crawlers/captcha.py` 点选题刷新 | 刷新重试能力失效，挑战态可能卡住 |
"""
import io
import os

from core import degraded as dg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = io.open(os.path.join(ROOT, "crawlers", "base.py"),
               encoding="utf-8").read()
CAPTCHA = io.open(os.path.join(ROOT, "crawlers", "captcha.py"),
                  encoding="utf-8").read()
SRC = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()


def test_stealth_injection_failure_is_recorded():
    assert 'note("stealth_init"' in BASE
    i = BASE.index('note("stealth_init"')
    seg = BASE[max(0, i - 600):i + 300]
    assert "add_init_script" in seg, "记账点不在注入失败的分支里"


def test_captcha_screenshot_failure_is_recorded():
    assert 'note("captcha_shot"' in CAPTCHA
    i = CAPTCHA.index('note("captcha_shot"')
    seg = CAPTCHA[max(0, i - 500):i + 400]
    assert "screenshot" in seg, "记账点不在截图失败的分支里"
    # 必须与「检测不到目标」分开：后者不是降级
    assert "检测不到可点目标" in seg or "detect_targets" in seg


def test_degraded_caps_have_chinese_labels():
    seg = SRC[SRC.index("const CN={app_geo"):][:600]
    for cap in ("app_geo", "captcha_det", "ua_kernel", "stealth_init",
                "captcha_shot"):
        assert cap in seg, cap
    # 中文名不许出现空串/英文原文当标签
    assert "伪装注入" in seg and "识别截图" in seg


def test_notes_are_capability_level_not_network_noise():
    """降级账本只收能力级：这三个 key 都不带渠道/时间细节，是"能力名"。"""
    for cap in ("stealth_init", "captcha_shot", "captcha_det", "app_geo",
                "ua_kernel"):
        assert cap.islower() and "/" not in cap and " " not in cap, cap


def test_ledger_records_with_channel():
    dg.reset()
    dg.note("stealth_init", "qunar", "注入失败")
    snap = dg.snapshot()
    assert snap["stealth_init"]["plats"].get("qunar") == 1, snap
    dg.reset()

def test_degraded_line_says_what_to_do_next():
    """只报次数等于让人自己猜：每类降级都要给出**下一步**。"""
    seg = SRC[SRC.index("const _DGFIX="):][:900]
    for cap in ("app_geo", "captcha_det", "ua_kernel", "stealth_init",
                "captcha_shot"):
        assert cap + ":" in seg, cap
    assert "setup_check" in seg and "ddddocr" in seg
    assert "tips.push('→ '" in SRC, "提示里没带下一步"
