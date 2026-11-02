# -*- coding: utf-8 -*-
"""r302 推送层两案行为/源码钉（先红后绿）：

P3-星注换词：_MKT_NOTE「*行情」→「·行情」——裸 * 是钉钉 markdown
强调标记字符，跨段双星结构可达（聚合推送逐 entry 展开 KPI，审校
S7 真实构造实证），换非强调分隔符从结构上除名配对危害类（防
FLIGGY_TAX_PAD>0 回潮 + mini 能力位复活）。· U+00B7 生产安全集在产
（KPI pct 中档「低￥199·10%」、PNG summary「低￥59·行情」同词面），
计宽与 * 同 1 半角（审校 S2/S7 网格实测渲染宽 39/40 不变）。

P2-1 组头守卫同律：_top3_blocks 降档判定从 _disp_dw 收口 _dw_bold
（#### 加粗字模入模型，r295/r296 判例）——「#### ✈️ 直飞最优TOP5
（线￥1900） · 9/9」形态 _disp_dw=39 判过而 _dw_bold=41.08 真超；
当前 MM/DD 日期段词面下泄漏窗数学不可达，守卫对齐是判例律收口。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r302_push.py -q
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.alerter as A  # noqa: E402


# ---------- P3：星注换「·行情」 ----------

def test_mkt_note_is_middle_dot_word():
    """常量钉：星注定义式退役（裸 * 强调字符禁复活），新词面=·+行情。"""
    src = open("core/alerter.py", encoding="utf-8").read()
    assert '"*" + _MKT_SHORT' not in src, (
        "星注定义式复活：裸 * 是钉钉 markdown 强调标记字符（跨段双星"
        "结构可达面），短注分隔符必须用非强调字符")
    assert A._MKT_NOTE == "·" + A._MKT_SHORT, (
        "_MKT_NOTE 词面漂移：预期「·行情」（· 计宽与 * 同 1 半角，"
        "降级链档位边界零移动）")


def test_mkt_note_width_neutral():
    """宽度中性钉：· 与 * 同按 1 半角计——换词不得移动降级链档位
    （r260 网格形态的边界样本须保持原档位判定）。"""
    assert A._dw("·") == A._dw("*") == 1, (
        "分隔符计宽漂移：· 须与 * 同按 1 半角（审校 S2/S7 网格，"
        "降级链档位边界零移动的前提）")
    assert A._dw(A._MKT_NOTE) == 5, "·行情 应=1+4（行情两全角）半角"


def test_mini_split_strips_middle_dot_note():
    """行为钉：去注档剥掉新词面干净——剥段消费与产出同出单源
    （_mini_split 消费 _MKT_NOTE，常量改版自动跟随；此钉锁真实常量
    形态的端到端产物，与 r262 的 monkeypatch 形态钉互补）。"""
    # r260 已验证的单段形态：head+seg 原样超宽、剥注后达标（恰走
    # 去注档；双段样本剥注仍超会正确走拆行档——词面保留非分叉）
    head = "📍 10/06　"
    seg = (A.tier_dot(False, -655, 19000) + "直飞 ￥12345 低￥6655"
           + A._MKT_NOTE)
    assert A._disp_dw(head + seg) > 40, "样本未进降级面"
    assert A._disp_dw(head + seg.replace(A._MKT_NOTE, "")) <= 40, \
        "样本未卡「去短注档」（剥注后须达标）"
    out = A._mini_split(head, [seg])
    assert A._MKT_NOTE not in out, "去注档未剥新词面（剥段与产出分叉）"
    assert "*" not in out, "产物残留裸 *（强调字符零容忍）"
    assert "￥6655" in out, "差额词必须完整在场"


def test_transcribe_strip_table_follows():
    """跨模块钉：notifier 剥注表对「·行情」剥注干净（ntfy/短信/TTS
    转写前消费链自动跟随单源，无 * 残留）。"""
    import core.notifier as N
    from core.notifier import _MKT_NOTE_DUPS
    seg = "🎯 直飞 ￥1701 低￥199" + A._MKT_NOTE
    out = seg
    for note in _MKT_NOTE_DUPS:
        out = out.replace(note, "")
    assert A._MKT_NOTE not in out, "剥注表未跟随新词面"
    assert "*" not in out and "·行情" not in out


# ---------- P2-1：_top3_blocks 组头守卫走加粗投影 ----------

def test_top3_head_guard_uses_bold_projection():
    """源码钉：组头降档判定与 _section_title 同律（_dw_bold 判例），
    旧 _disp_dw 形态禁复活。"""
    src = open("core/alerter.py", encoding="utf-8").read()
    assert "if _disp_dw(head) > 40:" not in src, (
        "组头守卫未走加粗投影：#### 标题按加粗字模渲染，_disp_dw 低估"
        "数字密集标题 11% 膨胀（39 判过实超 41.08 泄漏窗）")
    assert "if math.ceil(_dw_bold(head)) > 40:" in src, \
        "组头守卫未收口 _dw_bold 判例律"


def test_bold_projection_gap_sample_in_leak_window():
    """自证钉：泄漏窗样本「旧模型判过、新模型判拦」——证明两模型
    在该形态上有可分辨输出，测试具备捕获力（守卫对齐后该形态降档）。"""
    head = "#### ✈️ 直飞最优TOP5（线￥1900） · 9/9"
    assert A._disp_dw(head) <= 40, "样本须落旧模型判过带"
    assert math.ceil(A._dw_bold(head)) > 40, "样本须落新模型拦截带"
