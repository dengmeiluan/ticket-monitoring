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
