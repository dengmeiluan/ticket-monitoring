# -*- coding: utf-8 -*-
"""r273 WebUI 三案钉面（TDD：P3 候选经 goal_r273_webui.md 审计立案，
断言串自源码 repr 逐字节复制）：

K1 K 线档位环/回落标中心与烛体同款双端钳位——烛体钳位（审计 P3-1
   先例）当年只护蜡烛，末桶环心 X+koff 越过 W-R、环半径再外扩，
   半截环贴 canvas 右缘（K 线模式 bbox 右留白=0，折线模式恒 8）。
K2 链接族下划线语言分野收口——.verbar a/.kpisum a/#foot a/.demoBar a
   补基态去下划线，hover 显形，与 .numlink/a.vw/.pvbody a 同语言
   （四族基态曾落 UA 恒下划线、hover 声明同值零增量）。
K3 字距三档单源收口——0.5px×4 消费点入 --ls05、2px×2 消费点入
   --ls2（裸声明归零；h1 品牌字距/mono 负字距/.erow/.uname 语义
   独立保留不入族）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r273_webui.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webui  # noqa: E402  # 触发 PAGE 常量装配

PAGE = webui.PAGE
NPAGE = webui.NOTIFY_PAGE


def _block(start_anchor, end_anchor):
    m = PAGE.index(start_anchor)
    return PAGE[m:PAGE.index(end_anchor, m + 10)]


# ---------- K1: K 线环标双端钳位 ----------

def test_kline_ring_center_clamped():
    body = _block("const ringK=", "ringK(CD,")
    assert "const cx=Math.max(L+cw/2,Math.min(W-R-cw/2,X(xf(i))+off));" \
        in body, "ringK 缺烛体同款双端钳位：末桶环心越绘图区半截环贴边"
    assert "fallMark(cx,Y(c.l))" in body, "回落标中心未走钳位 cx"
    assert "arc(cx,Y(rp)" in body, "档位环中心未走钳位 cx"
    # 禁复活：环/回落标不得再出现未钳位中心
    assert "arc(X(xf(i))+off" not in body, "档位环退回未钳位中心"
    assert "fallMark(X(xf(i))+off" not in body, "回落标退回未钳位中心"


# ---------- K2: 链接族基态去下划线 ----------

def test_link_underline_base_states():
    assert ".verbar a{color:#8a1f1f;font-weight:700;text-decoration:none}" \
        in PAGE, "verbar 链接缺基态去下划线"
    assert (".kpisum a{position:relative;padding:12px 4px;margin:0 -4px;"
            "text-decoration:none}") in PAGE, "kpisum 链接缺基态去下划线"
    assert "#foot a,.demoBar a{text-decoration:none}" in PAGE, \
        "页脚/演示条链接缺基态去下划线"
    # hover 显形档三处仍在（基态收口不得吞掉可供性反馈）
    assert PAGE.count("a:hover{text-decoration:underline}") >= 3


# ---------- K3: 字距三档单源 ----------

def test_letter_spacing_tokens():
    assert "--ls05:.5px" in PAGE, "--ls05 半像素档令牌缺席"
    assert PAGE.count("letter-spacing:var(--ls05)") == 4, \
        "半像素档消费点应恰 4 处（.seclab .zh/.tag/.pseclab/.rtcode）"
    assert PAGE.count("letter-spacing:var(--ls2)") == 3, \
        "主站两像素档消费点应恰 3 处（.seclab .en/.grouplab .en/15px 展示签）"
    assert NPAGE.count("letter-spacing:var(--ls2)") == 1, \
        "NOTIFY 轻页 15px 展示签消费恰 1 处（:root 令牌区已同步在册）"
    assert "letter-spacing:.5px" not in PAGE, "半像素裸声明残留"
    assert "letter-spacing:2px" not in PAGE, "两像素裸声明残留"
    assert "letter-spacing:2px" not in NPAGE, "NOTIFY 两像素裸声明残留"
