# -*- coding: utf-8 -*-
"""r945：携程的拼图滑块被判 `unknown`，一次都不试。

2026-11-04 实测：携程登录的滑块页面上，文案**只有**「请完成拼图验证」——
不含"滑块/拖动"任何一个字。而 `classify()` 的简单滑块标记表里全是
"拖动滑块/滑动验证/slide-verify…"，于是：

```
classify('', '请完成拼图验证')  →  unknown   solvable=False
```

代价是**一次都不试**（`should_attempt` 直接 False）。而它其实就是标准拼图
滑块：实测缺口能稳定算到 x≈304（两种独立方法交叉一致），拟人轨迹也现成。

修法：把携程（以及同类只写"拼图验证"的站）的文案加进简单滑块标记表。

**边界必须同时守住**：`geetest/极验/天御/tcaptcha/baxia/点选/人脸`
仍然是 `strong`，一律不碰——这是本仓库一贯的红线。

顺带产出 `scripts/ctrip_login.py`：人只给短信码，其余（进登录页、填号、
发码、填码、过拼图、核对登录态）全自动。因为短信码只能人收，
所以"人给一个码"是这条链的自然接口。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r945_ctrip_puzzle_simple.py -q
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers import slider  # noqa: E402


# ---------------------------------------------------------------------------
# 1. 携程拼图文案要判成 simple（可解）
# ---------------------------------------------------------------------------
def test_ctrip_puzzle_is_simple():
    for text in ("请完成拼图验证", "拼图验证", "完成拼图",
                 "拖动滑块完成拼图"):
        tier = slider.classify("", text)
        assert tier.name == "simple", (text, tier.name)
        assert tier.solvable is True, text


# ---------------------------------------------------------------------------
# 2. 强人机边界不许破（这是红线）
# ---------------------------------------------------------------------------
def test_strong_still_not_solvable():
    for text in ("geetest 智能验证", "极验", "天御验证", "tcaptcha",
                 "baxia", "recaptcha", "hcaptcha", "请按顺序点击",
                 "人脸识别"):
        tier = slider.classify("", text)
        assert tier.solvable is False, (text, tier.name)


def test_unknown_text_still_unknown():
    assert slider.classify("", "请选择出发城市").name == "unknown"


# ---------------------------------------------------------------------------
# 3. 登录助手：结构 + 不碰强人机
# ---------------------------------------------------------------------------
_LOGIN = os.path.join(ROOT, "scripts", "ctrip_login.py")


def test_login_helper_exists_with_check_mode():
    src = io.open(_LOGIN, encoding="utf-8").read()
    assert "--check" in src and "--code" in src and "--send-only" in src
    assert "def is_logged_in(" in src
    assert "def solve_slider(" in src


def test_login_helper_skips_strong_tier():
    """滑块分级不是 simple 时**不许拖**（代码里要有这个闸）。"""
    src = io.open(_LOGIN, encoding="utf-8").read()
    i = src.find("def solve_slider(")
    j = src.find("\ndef ", i + 10)
    body = src[i:j]
    assert "tier.solvable" in body, "没有按分级放行"
    assert "不动手" in body, "非 simple 时没有明确放弃"


def test_login_helper_reuses_slider_module():
    """距离/轨迹必须复用 `crawlers.slider`，不许自己再算一遍。"""
    src = io.open(_LOGIN, encoding="utf-8").read()
    assert "from crawlers import slider" in src
    assert "attempt_device" in src
    # 不许自己实现拖动距离
    assert "def trajectory(" not in src, "自己实现了轨迹（会两处漂移）"


def test_login_helper_checks_result_honestly():
    src = io.open(_LOGIN, encoding="utf-8").read()
    # 结束必须核对登录态，而不是"拖完就算成功"
    assert "登录结果:" in src
    assert "成功" in src and "未成功" in src
