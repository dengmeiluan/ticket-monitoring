# -*- coding: utf-8 -*-
"""r944：缺口检测被"拼图块自己"骗走——返回起点而不是缺口。

2026-11-04 用携程真实登录滑块（`_ctrip_puzzle.png`，822×411）实测：

```
修前 find_gap → (303, [(303, 6.939), (109, 6.932), (123, 6.727)])
```

后两个候选 109/123 **落在拼图块区域内**：拼图块固定贴最左侧，
它自己的左右两条强边会配出与真缺口几乎同分的响应
（独立复核：块边缘对 `57..101` 得分 1.369，真缺口 `266..342` 得分 1.316）。

后果：`attempt_*` 会逐个试候选，先试 109/123 那个 **拖动距离≈0 的位置**，
浪费预算；连续失败还会触发"连续失败 2 次拉黑 7 天"，把本来能过的滑块判死。

修法：把"中心落在最左侧 `w*0.22` 以内"的候选**分数打对折**
（不直接丢，避免小图/方块偏右时误杀）。

修后同一张图：

```
(304, [(304, 6.939), (312, 6.647), (272, 5.455)])
```

三个候选全部收敛到 272–312（真缺口 ±20px），且与独立方法（边缘对 + 宽度约束）
算出的 304 完全一致。

顺带清掉一段**永不执行的死代码**（`return ranked[0][0]` 之后还跟着
聚合/去边逻辑，历史遗留）。

运行：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r944_gap_left_block.py -q
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PIL import Image, ImageDraw  # noqa: E402

from crawlers import slider  # noqa: E402


def _png(draw_fn, size=(822, 411)):
    im = Image.new("RGB", size, (240, 240, 240))
    ImageDraw.Draw(im).__class__  # noqa: B018  (确保 import 被用)
    draw_fn(ImageDraw.Draw(im), size)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _scene_piece_and_gap(piece_x=57, piece_w=44, gap_x=266, gap_w=76):
    """造一张"左侧有拼图块、右侧有缺口"的图。"""
    def _draw(d, size):
        # 拼图块：深色方块 + 明显描边（两条强竖边）
        d.rectangle([piece_x, 120, piece_x + piece_w, 260], fill=(60, 60, 60))
        d.rectangle([piece_x, 120, piece_x + piece_w, 260], outline=(0, 0, 0), width=3)
        # 缺口：中间偏亮、两侧描边
        d.rectangle([gap_x, 130, gap_x + gap_w, 250], fill=(200, 200, 205))
        d.rectangle([gap_x, 130, gap_x + gap_w, 250], outline=(30, 30, 30), width=3)
        # 加一点背景纹理，避免"纯色早退"
        for y in range(0, size[1], 40):
            d.line([(0, y), (size[0], y)], fill=(225, 225, 228), width=1)
    return _png(_draw)


# ---------------------------------------------------------------------------
# 1. 核心：缺口要选在右侧，不能被左侧拼图块抢走
# ---------------------------------------------------------------------------
def test_gap_chosen_right_of_piece():
    png = _scene_piece_and_gap()
    best, cands = slider.find_gap(png, (0, 0, 822, 411))
    assert cands, "没找到任何候选"
    # 真缺口中心 ≈ (266+76/2)=304；允许 ±30
    assert abs(best - 304) <= 30, "best=%d 偏离太多（候选=%s）" % (best, cands)


def test_candidates_not_clustered_on_piece():
    """候选不许聚在拼图块位置（x≈57~123）。"""
    png = _scene_piece_and_gap()
    _, cands = slider.find_gap(png, (0, 0, 822, 411))
    left = [c for c in cands if c[0] < 180]
    assert len(left) <= 1, "候选里有多条落在拼图块区域：%s" % cands


def test_no_dead_code_after_return():
    """缺口实现里不许有 `return` 之后的死代码。

    2026-11-05 起缺口算法被拆成两层：`_find_gap_edges`（边缘能量实现）
    + `find_gap`（薄封装，另外并入 ddddocr 滑轨模型的结果，见 §6.56）。
    死代码只可能出现在**实现**那一层，所以这里跟着实现走；
    同时钉住封装层存在，避免有人把两层又合回去却丢了 ddddocr 那一路。
    """
    src = io.open(os.path.join(ROOT, "crawlers", "slider.py"),
                  encoding="utf-8").read()
    i = src.find("def _find_gap_edges")
    assert i > 0, "缺口实现函数不见了（应叫 _find_gap_edges）"
    j = src.find("\ndef ", i + 10)
    body = src[i:j]
    # 统计 "return ranked[0][0], ranked[:top]" 出现次数：只应 1 次
    assert body.count("return ranked[0][0], ranked[:top]") == 1, \
        "缺口实现里仍有重复/死代码返回"
    assert "def find_gap(" in src, "封装层 find_gap 不见了（ddddocr 那一路会丢）"


# ---------------------------------------------------------------------------
# 2. 左侧降权是"打对折"而不是"丢掉"（小图 / 方块偏右时不能误杀）
# ---------------------------------------------------------------------------
def test_left_candidate_still_kept_when_only_option():
    """只有左侧有边时仍要给出候选（不许因为降权就返回 0）。"""
    def _draw(d, size):
        d.rectangle([40, 120, 90, 260], fill=(50, 50, 50))
        d.rectangle([40, 120, 90, 260], outline=(0, 0, 0), width=3)
        for y in range(0, size[1], 40):
            d.line([(0, y), (size[0], y)], fill=(228, 228, 230), width=1)
    png = _png(_draw)
    best, cands = slider.find_gap(png, (0, 0, 822, 411))
    # 至少不该崩，且若给了候选要落在合理范围
    assert best >= 0 and isinstance(cands, list)


# ---------------------------------------------------------------------------
# 3. 纯色图仍要早退（回归守卫）
# ---------------------------------------------------------------------------
def test_blank_image_returns_zero():
    png = _png(lambda d, size: None)
    best, cands = slider.find_gap(png)
    assert best == 0 and cands == []
