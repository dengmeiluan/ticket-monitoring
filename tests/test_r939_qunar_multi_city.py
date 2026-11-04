# -*- coding: utf-8 -*-
"""r939：档位残留不止「往返」，还有「多程」——34 次 no-list-page 的真因。

真实现场（`debug/scene/qunar_app_20261104_121050_nolist-2026-11-16.txt`，
这是 r936 的落现场钩子上线后第一份，**直接看到了病根**）：

```
选择航班
抱歉未找到符合条件的多程航班
建议修改搜索条件或分开预订
第一程   上海 → 伦敦   11月16日 出发
第二程   海口 → 东京   2月17日 出发
```

即：App 停在**多程**档（上一轮跑过往返/多程留下的），而本轮要查的是**单程
SHA→LHR**。多程页自然"未找到符合条件的多程航班"。

而 `_switch_to_single()` 的判据只有：

```python
if _ID_BACK_DATE_LL not in (xml or ""):    # atom_flight_ll_back_date
    return xml                             # 认为"已是单程"
```

**多程页没有返程日期位**（它是「第一程 / 第二程」两段），于是判据不命中
→ 认为已是单程 → 不切档 → 直接搜索 → 落到多程结果页 → `detect_state`
拿不到"起降时刻对" → 记 `no-list-page`。

账本实证（近两天，`fetch_paths`）：

    34× | 航班明细 timeout | 未取到可用结果：no-list-page      ← 83% 的失败
    11× | 航班明细 ok      | 1 条真实航班/时刻/价格
     5× | 航班明细 timeout | no-priced-rows
     5× | 航班明细 timeout | pick-date-failed
     2× | app-dump timeout | 没能打开机票首页

修法：判据加上多程特征（`第一程` + `第二程` 同现），并在多程**结果页**
（无档位切换控件）时先 BACK 退回表单再找。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r939_qunar_multi_city.py -q
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from crawlers.app_qunar import AppQunarCrawler, _ID_BACK_DATE_LL  # noqa: E402

_SCENE = os.path.join(ROOT, "debug", "scene",
                      "qunar_app_20261104_121050_nolist-2026-11-16.txt")


def _crawler():
    return AppQunarCrawler({"user_data_dir": "user_data"}, None)


class Dev:
    def __init__(self, frames):
        self.frames = list(frames)
        self.i = 0
        self.taps = []
        self.backs = 0

    def dump(self):
        f = self.frames[min(self.i, len(self.frames) - 1)]
        self.i += 1
        return f

    def tap(self, x, y):
        self.taps.append((x, y))
        return True

    def keyevent(self, code):
        self.backs += 1
        return True


MULTI = ('<node text="选择航班" bounds="[0,0][100,40]" />'
         '<node text="抱歉未找到符合条件的多程航班" bounds="[0,60][900,90]" />'
         '<node text="第一程" bounds="[0,100][60,130]" />'
         '<node text="第二程" bounds="[0,200][60,230]" />')
MULTI_WITH_TAB = (MULTI +
                  '<node text="单程" bounds="[10,300][60,340]" />')
SINGLE = ('<node text="机票查询" bounds="[0,0][100,40]" />'
          '<node text="11月16日" bounds="[10,100][90,130]" />')
ROUND = (f'<node resource-id="{_ID_BACK_DATE_LL}" '
         'bounds="[0,200][100,240]" />'
         '<node text="单程" bounds="[10,300][60,340]" />')


# ---------------------------------------------------------------------------
# 1. 核心：多程必须被识别成"需要切档"
# ---------------------------------------------------------------------------
def test_multi_city_triggers_switch():
    c = _crawler()
    d = Dev([MULTI_WITH_TAB])
    out = c._switch_to_single(d, MULTI_WITH_TAB)
    assert d.taps, "多程档没有点「单程」——这就是 no-list-page 的根因"
    assert out is not None


def test_single_mode_does_not_tap():
    """已是单程：不白点。"""
    c = _crawler()
    d = Dev([SINGLE])
    c._switch_to_single(d, SINGLE)
    assert d.taps == []


def test_round_trip_still_switches():
    """往返档的既有行为不能回归。"""
    c = _crawler()
    d = Dev([ROUND])
    c._switch_to_single(d, ROUND)
    assert d.taps, "往返档不再切单程了"


# ---------------------------------------------------------------------------
# 2. 多程结果页（无档位控件）：先 BACK 退回表单
# ---------------------------------------------------------------------------
def test_multi_result_page_backs_out_then_switches():
    """多程**结果页**（无档位控件）：先 BACK 退回表单，再点「单程」。

    入参是结果页 MULTI（没有「单程」控件），BACK 之后 dump 给带
    「单程」的表单页 —— 所以帧序列只需一帧 MULTI_WITH_TAB。
    """
    c = _crawler()
    d = Dev([MULTI_WITH_TAB])
    c._switch_to_single(d, MULTI)
    assert d.backs >= 1, "多程结果页没有先 BACK 退回表单"
    assert d.taps, "BACK 回表单后没有点「单程」"


# ---------------------------------------------------------------------------
# 3. 真实现场：旧判据漏判、新判据命中
# ---------------------------------------------------------------------------
def test_real_scene_is_multi_city():
    """这份 dump 是病根本身：它不是往返（无返程日期位），是多程。"""
    if not os.path.isfile(_SCENE):
        import pytest
        pytest.skip("真实现场不存在（可能被清理）")
    s = io.open(_SCENE, encoding="utf-8", errors="replace").read()
    assert _ID_BACK_DATE_LL not in s, "现场有返程日期位，那就不是多程问题"
    assert "第一程" in s and "第二程" in s, "现场不是多程页，判据假设失效"
    assert "多程" in s


# ---------------------------------------------------------------------------
# 4. 源码钉：判据必须同时覆盖两种档位残留
# ---------------------------------------------------------------------------
def test_source_covers_both_residues():
    src = io.open(os.path.join(ROOT, "crawlers", "app_qunar.py"),
                  encoding="utf-8").read()
    i = src.find("def _switch_to_single")
    assert i > 0
    body = src[i:i + 2600]
    assert "_ID_BACK_DATE_LL in" in body, "往返判据不见了"
    assert "第一程" in body and "第二程" in body, "没有覆盖多程档"


def test_multi_layer_back_is_supported():
    """多程结果页到表单**可能不止一层**，必须循环退（最多 3 层）。

    现场只见过「结果页」这一层，但退栈路径不保证永远一层：
    结果页 → 查询中间页 → 表单 也是可能的。只 BACK 一次就把
    "退不干净"变成了新的 `no-list-page` 来源。
    """
    c = _crawler()
    # 前两次 BACK 后仍是结果页，第 3 次才回到带「单程」的表单
    d = Dev([MULTI, MULTI, MULTI_WITH_TAB, MULTI_WITH_TAB])
    c._switch_to_single(d, MULTI)
    assert d.backs >= 1, "没有退栈"
    assert d.taps, "退栈后没找到「单程」并点击"


def test_back_is_bounded():
    """退栈次数有上限，不能无限按 BACK。"""
    c = _crawler()
    d = Dev([MULTI])          # 永远是结果页，退不出去
    c._switch_to_single(d, MULTI)
    assert d.backs <= 3, "退栈没有上限：%d 次" % d.backs


# ---------------------------------------------------------------------------
# 6. 多程**结果页**：没有「单程」控件、BACK 也退不出 → 必须重建
# ---------------------------------------------------------------------------
def test_multi_result_page_without_switch_control_is_detected():
    """现场 `nolist-2026-11-16` 第二次：只有「多程」字样、**没有**「单程」。

    说明只认「第一程+第二程」不够——多程**结果页**可能只带「多程」文案。
    判据必须放宽到"出现「多程」即需处理"。
    """
    src = io.open(os.path.join(ROOT, "crawlers", "app_qunar.py"),
                  encoding="utf-8").read()
    i = src.find("def _switch_to_single")
    body = src[i:i + 3200]
    # 必须覆盖多程结果页（用长文案，而不是 tab 上的「多程」二字——
    # 首页本来就有那个 tab，用它当判据会把正常页面判成多程，实测踩过）
    assert '"多程航班" in low' in body, "多程结果页判据缺失"
    assert '"分开预订" in low' in body, "多程结果页文案判据缺失"


def test_force_stop_fallback_exists():
    """切档与 BACK 都失败时，必须有 force-stop + 深链重建的兜底。

    多程结果页不在正常导航栈里，BACK 退不回表单——只能硬重建。
    没有这一步，整轮就在多程页上跑，记 `no-list-page`。
    """
    src = io.open(os.path.join(ROOT, "crawlers", "app_qunar.py"),
                  encoding="utf-8").read()
    assert "force-stop 重建后重试单程" in src, "没有重建兜底"
    assert "多程档残留：切单程与重建均未成功" in src, \
        "重建也失败时没有如实记账"


def test_real_scene_second_occurrence_has_no_single_control():
    """第二份现场确认：多程结果页确实没有「单程」可点。"""
    import glob
    ps = sorted(glob.glob(os.path.join(ROOT, "debug", "scene", "*nolist*")))
    if not ps:
        import pytest
        pytest.skip("现场不存在（可能已清理）")
    s = io.open(ps[-1], encoding="utf-8", errors="replace").read()
    if "多程" not in s:
        import pytest
        pytest.skip("最新现场不是多程页，本用例不适用")
    assert "单程" not in s, "现场有「单程」控件，那就不该走重建兜底"
    assert "抱歉未找到" in s or "第一程" in s


# ---------------------------------------------------------------------------
# 7. **正常首页不许被误判成多程**（本轮修的 bug）
# ---------------------------------------------------------------------------
def test_normal_home_with_multi_tab_is_not_multi_city():
    """首页本来就有「多程」tab —— 不能用 `"多程" in xml` 当判据。

    2026-11-04 我第一版就是这么写的：
    ```python
    is_multi = (("第一程" in low and "第二程" in low) or "多程" in low)
    ```
    实测在一个 **175 节点的正常页面**上 `"多程" in xml` 就是 True ——
    于是每轮都会判成多程、白做一次 force-stop 重建。
    """
    c = _crawler()
    home = ('<node text="机票查询" bounds="[0,0][100,40]" />'
            '<node text="单程" bounds="[10,50][60,90]" />'
            '<node text="往返" bounds="[70,50][120,90]" />'
            '<node text="多程" bounds="[130,50][180,90]" />'      # ← tab 文案
            '<node text="11月16日" bounds="[10,100][90,130]" />')
    d = Dev([home])
    c._switch_to_single(d, home)
    assert d.taps == [], "正常首页被误判成多程并点了「单程」"
    assert d.backs == 0, "正常首页被误判并触发了退栈"


def test_multi_result_page_still_detected_by_long_text():
    """真正的多程结果页用长文案判，仍然命中。"""
    result = ('<node text="选择航班" bounds="[0,0][100,40]" />'
              '<node text="抱歉未找到符合条件的多程航班" '
              'bounds="[0,60][900,90]" />'
              '<node text="建议修改搜索条件或分开预订" '
              'bounds="[0,100][900,130]" />')
    assert "多程航班" in result or "分开预订" in result


def test_precise_criteria_in_source():
    """源码里不许再出现宽判据 `"多程" in low`。"""
    src = io.open(os.path.join(ROOT, "crawlers", "app_qunar.py"),
                  encoding="utf-8").read()
    assert 'or "多程" in low' not in src, "宽判据回来了（会误伤正常首页）"
    assert 'or "多程" in (xml or "")' not in src, "宽判据回来了"
