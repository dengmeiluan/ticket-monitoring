# -*- coding: utf-8 -*-
"""r964：OCR 把运算符认成汉字时，简易算数题不能直接放弃。

真实触发过程（2026-11-04）：`ddddocr` **没装**（ModuleNotFoundError），
后端静默退到 `windows-ocr`；拿一张写着 `3+7=?` 的图喂进去，
返回的是 **`3爷7=`** —— `+` 被认成了"爷"。
于是上一轮刚加好的"算式在图里 → 截图 OCR 再算"兜底
**结构上通、结果永远为空**：`solve_arithmetic('3爷7=')` 找不到 ASCII 运算符 → None
→ App 侧走"空答案"分支放弃。这正是本仓今天反复撞到的那类
"看起来接上了、其实一步都没走通"。

修法刻意保守，四条边界各有用例：
1. **先按原样解，解不动才纠正**：正常输入绝不被字形替换污染；
2. **只换"夹在两个数字之间"的可疑字形**：不全局 replace，
   否则题面里正常出现的汉字会被当成运算符；
3. **认不出的一律不猜**：`3?7` → None。
   答错验证码比不答更容易触发风控 —— 这是本模块的取舍方向；
4. **多运算符仍放弃**：纠正之后也不许把 `1+2+3` 猜成某一段。

另外钉住一个既有事实（不是本模块引入的）：`_normalize` 把 `x` 当乘号，
所以 `9x9` → 81。第一版用例把它当"不该猜"写错了预期 ——
**测试要编码真实行为，不是编码我的假设。**

跑：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r964_ocr_operator_confusion.py -q
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers import captcha as c  # noqa: E402


# ---------------------------------------------------------------------------
# 1. 本机实测的那个坏样本必须能算对
# ---------------------------------------------------------------------------
def test_measured_ocr_failure_now_solves():
    """windows-ocr 实测返回 `3爷7=`（`+` 认成"爷"）。"""
    assert c.solve_arithmetic("3爷7=") == 10
    assert c._answer_arithmetic("3爷7=") == "10"


def test_operator_confusion_variants():
    assert c.solve_arithmetic("3丁7") == 10
    assert c.solve_arithmetic("6－2") == 4        # 全角减号（_normalize 已处理）
    assert c.solve_arithmetic("8x2") == 16       # x 当乘号（既有行为）


# ---------------------------------------------------------------------------
# 2. 顺序：正常能解的输入，绝不经过字形替换
# ---------------------------------------------------------------------------
def test_clean_input_untouched():
    for txt, want in (("3+7=?", 10), ("3 + 7 = ?", 10), ("9-3", 6)):
        assert c.solve_arithmetic(txt) == want, txt


def test_fix_ops_only_between_digits():
    """题面里正常出现的汉字不许被当运算符。"""
    assert c._ocr_fix_ops("爷孙3人") == "爷孙3人"
    assert c._ocr_fix_ops("3爷7") == "3+7"
    assert c._ocr_fix_ops("") == ""


# ---------------------------------------------------------------------------
# 3. 认不出就不猜（答错比不答更危险）
# ---------------------------------------------------------------------------
def test_unknown_glyph_refuses_to_guess():
    assert c.solve_arithmetic("3?7") is None
    assert c.solve_arithmetic("3~7") is None


def test_multi_operator_still_refused():
    assert c.solve_arithmetic("1+2+3") is None
    # 纠正之后也不会把两个可疑位当作单一算式来蒙
    assert c.solve_arithmetic("1爷2爷3") is None


def test_divide_by_zero_refused():
    assert c.solve_arithmetic("8/0") is None


# ---------------------------------------------------------------------------
# 4. 真实图片链路（离线，不碰设备）
# ---------------------------------------------------------------------------
def test_real_image_pipeline_end_to_end():
    """给定 OCR 的返回，兜底必须真的能出答案；OCR 本身的质量不在断言范围内。

    第一版我拿 PIL 画的图去断言"引擎认得出 3+7"，结果同一张图两次跑出
    **不同**结果：`3爷7=` 与 `37=1`（`backend_name()` = `windows-ocr`，
    因为 `ddddocr` 没装）。把测试绑在引擎质量上，得到的是一个会随机
    变红的用例，而不是一条契约 —— **我们只能承诺"自己的那段逻辑正确"**。

    所以这里：
    * 用**实测到的**引擎输出当输入，验证我们的解析确实救得回来；
    * 对救不回来的输出（`37=1`），断言它**返回空而不是蒙一个**
      —— 蒙错答案比不答更容易触发风控，这是本模块的取舍方向。
    """
    for ocr_text, want in (("3+7=?", "10"),      # 引擎读对
                           ("3爷7=", "10"),      # 实测：+ 认成"爷"
                           ("3丁7", "10"),       # 实测：+ 认成"丁"
                           ("37=1", ""),         # 彻底读乱 → 不猜
                           ("", "")):
        assert c._answer_arithmetic(ocr_text) == want, ocr_text


def test_read_text_never_raises_and_returns_str():
    """真调引擎只验"不崩、返回 str"，不验内容。

    环境里没有 ddddocr 时会退到 windows-ocr；退到什么质量是环境属性，
    不该由本仓的单测来担保（也不该由代码假装它一定可用）。
    """
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (180, 56), "white")
    ImageDraw.Draw(im).text((16, 18), "3+7=?", fill="black")
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    out = c.read_text(buf.getvalue())
    assert isinstance(out, str), type(out)


def test_vendor_path_is_appended_not_prepended():
    """`_vendor` 必须 **append** 到 sys.path 末尾。

    2026-11-04 用 `pip install --target=_vendor ddddocr` 装解码后端时，
    顺带把 `numpy 2.4.6` / `Pillow 13` / `opencv 5` 也落了进去。
    实测全局仍是 `numpy 2.2.6 / PIL 12.3.0 / cv2 4.12.0`，
    因为 `_ensure_vendor_path()` 用的是 `sys.path.append`——
    **改成 insert 的那一刻，_vendor 里那套副本就会盖掉监控进程正在用的全局库**，
    而这种事不会有任何报错，只会以"莫名崩库"的形式在几周后浮现。
    所以把 append 钉成契约。（真正需要的只有 `ddddocr` 本身，它只存在于 _vendor。）
    """
    src = io.open(os.path.join(ROOT, "crawlers", "captcha.py"),
                  encoding="utf-8").read()
    i = src.find("def _ensure_vendor_path")
    body = src[i:src.find("\ndef ", i + 10)]
    assert "sys.path.append(" in body, "不再是 append：会遮蔽全局 numpy/PIL/cv2"
    assert "sys.path.insert" not in body


def test_ddddocr_backend_reports_honestly():
    """装了就要真的出字；`backend_name()` 不许说 ddddocr 而实际不可用。"""
    name = c.backend_name()
    if name != "ddddocr":
        # 没装也不失败：兜底引擎照样要能返回 str（见上一个用例）
        return
    png = _tiny_png("3+7=?")
    out = c.read_text(png)
    assert isinstance(out, str) and out.strip(), \
        "报自己是 ddddocr 却读不出任何字符——后端名与实际能力不一致"


def _tiny_png(text: str) -> bytes:
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (200, 64), "white")
    ImageDraw.Draw(im).text((12, 16), text, fill="black")
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()
