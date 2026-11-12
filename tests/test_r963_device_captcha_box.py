# -*- coding: utf-8 -*-
"""r963：App 侧答案框必须按**语义**选，不能按"第一个带 text 的节点"。

旧实现（2026-11-04 复查推翻）：

    re.search(r'text="([^"]*)"[^>]*bounds="\\[..\\]\\[..\\]"', xml)

uiautomator 的 dump 里**每个 node 都有 text 属性**，而答案 `EditText`
通常就是 `text=""`（空占位），有字的往往是题面 `TextView`。
于是这条正则命中的是题面：tap 点在"3+7=?"那行字上，`input_text`
没有落点，答案进了空气；流程却照常往下走并记一次"试过"。
这属于本仓今天反复撞到的同一类：**静默做错事，还留下看似成功的记录**。

正确做法是按语义打分选节点：`class` 含 `EditText`（决定性）、
`resource-id` 含 edit/input/code/captcha/verify（强提示）、
`focusable`/`clickable`（弱提示）；得分全 0 就**明确失败**，
绝不退回去点第一个带 text 的节点（宁可让操作员看见，也不要假尝试）。

顺带两个真实细节，测试各自钉住：
* dump 的属性名带连字符（`resource-id`），属性正则必须允许 `-`，
  否则解析出来的是 `id` 而不是 `resource-id`；
* 提交按钮**找到才点**，很多题输入完自动提交，硬点会误触别的控件。

跑：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r963_device_captcha_box.py -q
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers import captcha  # noqa: E402

# 一份接近真实的算数题 dump：题面在前（有字），答案框在后（text=""），
# 最后有个提交按钮。坐标互不重叠，便于断言点到了谁。
XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<hierarchy rotation="0">'
    '<node index="0" text="" resource-id="" class="android.widget.FrameLayout" '
    'clickable="false" focusable="false" bounds="[0,0][1260,2800]"/>'
    '<node index="1" text="请计算 3+7=? 后输入结果" resource-id="" '
    'class="android.widget.TextView" clickable="false" focusable="false" '
    'bounds="[80,300][1180,380]"/>'
    '<node index="2" text="" resource-id="com.demo:id/captcha_input" '
    'class="android.widget.EditText" clickable="true" focusable="true" '
    'bounds="[80,420][900,500]"/>'
    '<node index="3" text="提交" resource-id="com.demo:id/submit" '
    'class="android.widget.Button" clickable="true" focusable="true" '
    'bounds="[950,420][1180,500]"/>'
    '</hierarchy>'
)
BOX_CENTER = ((80 + 900) // 2, (420 + 500) // 2)          # (490, 460)
TEXT_CENTER = ((80 + 1180) // 2, (300 + 380) // 2)        # (630, 340)
BTN_CENTER = ((950 + 1180) // 2, (420 + 500) // 2)


class _Ctx:
    def __init__(self, body):
        self.plat = "app_demo"
        self.body = body
        self.device = None


class _Dev:
    def __init__(self, after=""):
        self.taps = []
        self.texts = []
        self._after = after

    def tap(self, x, y):
        self.taps.append((x, y))
        return True

    def input_text(self, t):
        self.texts.append(str(t))
        return True

    def dump(self):
        return self._after

    def screencap(self):
        return b""


_UD = os.path.join(tempfile.gettempdir(), "tm_r963_ud")


def _handler(after=""):
    """测试替身必须写**临时目录**，不能落到仓库的 `user_data/`。

    踩过（2026-11-05）：这里原来传 `user_data_dir=""`，而下游
    `note_result` 把空串当假值 → 回落到默认 `user_data/` →
    这些假渠道（plat="app_demo"）真的写进了
    `user_data/app_demo/slider_ledger.json`，于是"试 63 / 过 63（命中 100%）"
    出现在**生产报表**里。测试污染了测量数据，比测试失败更糟：
    报表看起来更"漂亮"，而那是假的。
    """
    return captcha.SolverHandler(config={}, user_data_dir=_UD, profile="",
                                 logger=None), _Dev(after)


# ---------------------------------------------------------------------------
# 1. 选择器本身
# ---------------------------------------------------------------------------
def test_find_input_box_picks_edittext_not_the_question():
    assert captcha.find_input_box(XML) == BOX_CENTER, \
        "点到题面 TextView 了（旧实现就是这个错）"
    assert captcha.find_input_box(XML) != TEXT_CENTER


def test_attribute_regex_supports_hyphenated_keys():
    """`resource-id` 必须解析成 resource-id。

    `resource-id` 含连字符：属性正则若写 [\\w:]+ 会解析出 key=`id`，
    于是 resource-id 提示全部失效，只剩 class 一路 —— 测试用"没有 EditText
    类、只有 resource-id 提示"的 dump 把它钉住。
    """
    xml = ('<hierarchy><node text="" resource-id="xx:id/answer_code_edit" '
           'class="android.view.View" clickable="true" focusable="true" '
           'bounds="[0,10][0,30]"/>'                    # 零尺寸 → 不可点
           '<node text="" resource-id="xx:id/answer_code_edit" '
           'class="android.view.View" clickable="true" focusable="true" '
           'bounds="[10,10][30,30]"/></hierarchy>')
    assert captcha.find_input_box(xml) == (20, 20), "resource-id 没被解析出来"


def test_refuses_to_tap_something_unknown():
    """没有可输入节点时返回 None，不许退回去点第一个带 text 的节点。"""
    xml = ('<hierarchy><node text="验证码错误" class="android.widget.TextView"'
           ' clickable="false" focusable="false" bounds="[0,0][10,10]"/>'
           '</hierarchy>')
    assert captcha.find_input_box(xml) is None


def test_skips_zero_size_nodes():
    xml = ('<hierarchy><node text="" resource-id="a:id/edit" '
           'class="android.widget.EditText" bounds="[5,5][5,9]"/>'
           '</hierarchy>')
    assert captcha.find_input_box(xml) is None, "零尺寸节点不该被当成可点目标"


def test_submit_button_found_only_when_clickable():
    assert captcha.find_submit_button(XML) == BTN_CENTER
    xml = ('<hierarchy><node text="提交" class="android.widget.TextView" '
           'clickable="false" bounds="[0,0][10,10]"/></hierarchy>')
    assert captcha.find_submit_button(xml) is None, "不可点的文字不是按钮"


def test_dump_texts_pulls_human_visible_text():
    t = captcha.dump_texts(XML)
    assert "3+7" in t, t
    assert 'resource-id' not in t and 'bounds' not in t, "把属性也拼进去了"
    assert captcha.dump_texts('<hierarchy><node text=""/></hierarchy>') == ""


def test_solve_arithmetic_cannot_survive_a_raw_dump():
    """本用例钉的是**成因**，不是修法。

    `solve_arithmetic` 为了躲 OCR 把 `?` 认成 `0` 的坑，会在**第一个 `=`**
    处截断 —— 对纯题面是对的，但 dump 里每个属性都是 `k="v"`，
    第一处 `=` 落在 `<?xml version="1.0"`，于是整段被截成一行声明。
    这就是 App 侧算数题"从没解出来过"的原因（一直走"空答案"分支）。
    保留这条断言，是为了防止有人把截断规则当成 bug 直接删掉。
    """
    assert captcha.solve_arithmetic(XML) is None
    assert captcha.solve_arithmetic("请计算 3+7=? 后输入结果") == 10


def test_answer_arithmetic_works_on_dump_and_on_text():
    assert captcha._answer_arithmetic(XML) == "10", "dump 里算不出答案"
    assert captcha._answer_arithmetic("3+7=?") == "10"
    assert captcha._answer_arithmetic("没有算式") == ""


def test_answer_arithmetic_uses_cleaned_text_when_expression_is_only_in_nodes():
    """算式只存在于节点 text 里、且原文被 `=` 干扰时仍要算对。"""
    xml = ('<?xml version="1.0"?>\n<hierarchy>'
           '<node text="6×8=?" resource-id="" class="android.widget.TextView"'
           ' bounds="[0,0][10,10]"/></hierarchy>')
    assert captcha._answer_arithmetic(xml) == "48"


def test_on_device_arithmetic_from_image_falls_back_to_ocr(monkeypatch):
    """题面是图片（dump 里没算式）→ 截图 OCR 再算，别直接放弃。"""
    img_xml = ('<hierarchy><node text="请输入图中算式的结果" '
               'resource-id="a:id/code_edit" class="android.widget.EditText"'
               ' clickable="true" focusable="true" bounds="[0,10][20,30]"/>'
               '</hierarchy>')
    monkeypatch.setattr(captcha, "read_text", lambda png, *a, **k: "4+5=?")
    h, dev = _handler(after='<hierarchy><node text="首页"/></hierarchy>')
    dev.screencap = lambda: b"\x89PNG"
    out = h.on_device(dev, _Ctx(img_xml))
    assert out.handled is True, out
    assert dev.texts == ["9"], dev.texts


def test_on_device_text_captcha_still_ocrs(monkeypatch):
    monkeypatch.setattr(captcha, "read_text", lambda png, *a, **k: "ab12c")
    monkeypatch.setattr(captcha, "clean_answer",
                        lambda t, **kw: "".join(ch for ch in t if ch.isalnum()))
    xml = ('<hierarchy><node text="输入下方验证码" class="android.widget.TextView"'
           ' bounds="[0,0][10,10]"/>'
           '<node text="" resource-id="a:id/captcha_input" '
           'class="android.widget.EditText" clickable="true" focusable="true"'
           ' bounds="[0,50][40,70]"/></hierarchy>')
    h, dev = _handler(after='<hierarchy><node text="首页"/></hierarchy>')
    dev.screencap = lambda: b"\x89PNG"
    out = h.on_device(dev, _Ctx(xml))
    assert out.handled is True, out
    assert dev.texts == ["ab12c"], dev.texts
    assert dev.taps[0] == (20, 60), dev.taps


# ---------------------------------------------------------------------------
# 2. 端到端：答案真的被输进框里，并且点了提交
# ---------------------------------------------------------------------------
def test_on_device_inputs_into_the_real_box():
    h, dev = _handler(after='<hierarchy><node text="首页"/></hierarchy>')
    out = h.on_device(dev, _Ctx(XML))
    assert out.handled is True, out
    assert dev.taps[0] == BOX_CENTER, dev.taps
    assert dev.taps[0] != TEXT_CENTER
    assert dev.texts == ["10"], dev.texts          # 3+7 的答案
    assert BTN_CENTER in dev.taps, "有提交按钮却没点"


def test_on_device_does_not_tap_missing_box():
    """只有题面、没有输入框：必须如实失败，不制造假尝试。"""
    xml = ('<hierarchy><node text="请计算 3+7=?" class="android.widget.TextView"'
           ' clickable="false" bounds="[80,300][1180,380]"/></hierarchy>')
    h, dev = _handler()
    out = h.on_device(dev, _Ctx(xml))
    assert out.handled is False
    assert dev.taps == [], "没有输入框还去点：会点在题面上"


def test_no_submit_button_still_ok():
    """没有提交按钮时不硬点（很多题输入完自动提交）。"""
    xml = XML.replace('<node index="3" text="提交"',
                      '<node index="3" text="')
    h, dev = _handler(after='<hierarchy><node text="首页"/></hierarchy>')
    out = h.on_device(dev, _Ctx(xml))
    assert out.handled is True, out
    assert dev.taps == [BOX_CENTER], dev.taps


def test_strong_captcha_still_untouched():
    """强人机一律不动手（这是用户的边界，不是能力缺陷）。"""
    xml = ('<hierarchy><node text="请完成滑动验证，拖动滑块到最右侧"/>'
           '<node text="请依次点击图中的汽车、自行车" resource-id=""'
           ' class="android.widget.TextView" bounds="[0,0][100,100]"/>'
           '</hierarchy>')
    h, dev = _handler()
    out = h.on_device(dev, _Ctx(xml))
    assert out.handled is False, out
    assert dev.taps == [], "强人机/点选题被自动处理了"


def test_old_broken_selector_would_have_hit_a_non_input_node():
    """反向对照：证明这次修的是真 bug。

    旧写法 `re.search(r'text="([^"]*)"...bounds=...')` 命中的是 dump 里
    **第一个带 text 属性的节点** —— 这里是全屏根容器（`text=""`），
    点到屏幕正中；换成别的排版就会命中的是题面 TextView。
    两种都不是答案框，而流程照样"点了、输了、往下走"。
    """
    import re
    m = re.search(r'text="([^"]*)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
                  XML)
    x = (int(m.group(2)) + int(m.group(4))) // 2
    y = (int(m.group(3)) + int(m.group(5))) // 2
    assert (x, y) != BOX_CENTER, "旧写法居然也命中答案框？那本次修复的前提没了"
    assert (x, y) in (TEXT_CENTER, (630, 1400)), (x, y)
