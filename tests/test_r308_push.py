# -*- coding: utf-8 -*-
"""r308 推送审校收口：加粗行粗字模投影守卫（E-P2-1）+ webui 恰达线词面。

E-P2-1：加粗行（**…**）在钉钉以粗字模渲染，ASCII advance 按实测因子
膨胀（_TITLE_BOLD_ASCII，msyh16 纯数字串 1.111）——_disp_dw 剥 ** 后
按常规字模计宽，恰卡 40/40 的加粗 KPI 行1 真实渲染 41.31 半角超红线
（实发账本 663 条，手机窄屏折行断点不受控）。修复：_disp_dw 增 bold
投影（ASCII 走 _dw_bold 同因子）、_fit_line 增 bold 形参选档判定；
加粗产生点（KPI 行1/_push_digest 直飞+中转/日报 _kpi 两分支）同轮接
bold——非加粗行 bold 缺省 False 旧行为逐字节不变（零回归面）。

E-P3-1：webui diffTxt 缺 d===0 分支，价恰等线（整数价×整数阈值域
可达）出「已低于线 ￥0」字面自相矛盾——推送端 gap_txt 恰达线有专门
词面（qual「真达标」/mkt「行情破线」），webui 补同域词面「已达线」。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r308_push.py -q
"""
import math

from core.alerter import (  # noqa: E402
    _disp_dw, _dw_bold, _fit_line,
)

# 审校工单恰卡实锤样本（_disp_dw=40 旧模型放行、粗字模投影 41.31）
_BOLD_SAMPLE = ("[**直飞 ￥2400**](https://q.example/a)"
                "　线￥1900　差￥500（26%）")
_BOLD_SAMPLE_FB = "[**直飞 ￥2400**](https://q.example/a)　线￥1900　差￥500"


def test_bold_projection_reveals_exact_fit_overflow():
    """粗字模投影揭穿恰卡放行：_disp_dw 旧模型 40 放行（缺陷前提），
    bold 投影 ceil 后 42 超红线——膨胀只来自 ASCII 段（CJK/全角不膨胀）。"""
    assert _disp_dw(_BOLD_SAMPLE) == 40
    assert _disp_dw(_BOLD_SAMPLE, bold=True) > 40


def test_fit_line_bold_param_downgrades_exact_fit_row():
    """行为级：恰卡加粗行 bold=True 选档时落 fallback（丢尾注档），
    bold 缺省 False 维持旧行为放行（非加粗行零回归）。"""
    assert _fit_line(_BOLD_SAMPLE, fallbacks=[_BOLD_SAMPLE_FB],
                     bold=True) == _BOLD_SAMPLE_FB
    assert _fit_line(_BOLD_SAMPLE,
                     fallbacks=[_BOLD_SAMPLE_FB]) == _BOLD_SAMPLE


def test_bold_projection_cjk_only_row_unchanged():
    """纯 CJK 加粗行投影恒等（粗字模只膨胀 ASCII advance，CJK 方块字
    两权重恒等）——纯中文行不因 bold 判定被白白降档（_dw_bold 判例的
    同族保证）。注：半角空格属 ASCII，粗字模下同样膨胀（真实渲染
    语义），纯 CJK 样本不含空格。"""
    cjk_bold = "[**直飞低价蹲守提醒**](https://q.example/a)"
    assert _disp_dw(cjk_bold, bold=True) == _disp_dw(cjk_bold)


def test_kpi_block_bold_row_uses_projection():
    """端到端：KPI 行1 加粗形态（链接壳+全角空格分隔）的恰卡样本
    经守卫选档时按粗字模投影降档——构造恰卡 40 形态（无 emoji 点，
    与 _BOLD_SAMPLE 同构的 KPI 链接壳形态）断言降档含守卫后的完整行。"""
    s = ("[**直飞 ￥2400**](https://q.example/flights?a=1)"
         "　线￥1900　差￥500（26%）")
    plain_w = _disp_dw(s)
    bold_w = _disp_dw(s, bold=True)
    assert plain_w <= 40 < bold_w  # 恰卡带：旧模型放行、投影揭穿
    fb = "[**直飞 ￥2400**](https://q.example/flights?a=1)　线￥1900　差￥500"
    assert _fit_line(s, fallbacks=[fb], bold=True) == fb


def test_bold_factor_in_valid_band():
    """膨胀因子在实测带内（1.05-1.15 夹取档）——投影不是恒等伪装。"""
    from core.alerter import _TITLE_BOLD_ASCII
    assert 1.05 <= _TITLE_BOLD_ASCII <= 1.15
    assert math.isclose(
        _disp_dw("￥2400", bold=True) / max(1, _disp_dw("￥2400")),
        1.0, abs_tol=0.5)  # 短串不炸
