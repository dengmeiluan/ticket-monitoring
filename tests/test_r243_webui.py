# -*- coding: utf-8 -*-
"""r243 WebUI 落地（审计 _scratch/worker_r243_webui.md）。

P2-1 .pvbody a 触控热区欠账：r234 P2-3 修法按「13px×1.75 行高≈23px」
估算落 inset:-7px，inline 锚盒实测 17px（不含行距）→ 有效命中高 31px
< 36px 家族基准。对齐 NOTIFY 轻页 .md a::after 判例（webui.py 同值
-10px -4px，17+20=37px 达标）。行为钉在 docs/uitest.py 触控家族段
（有效高 ≥36 断言）。

P3-1 popstate 回退跨 cfg→mon 深链清洗：hashchange 白名单分支先
switchView('mon')（内部无条件 replaceState('#mon') 覆写入站 hash），
MONTAB 已等于目标页签时不再补写——回退到离开时同一页签场景深链段
（tab+uN）永久丢失，此后分享/刷新落到概览。修法：白名单分支内
switchView 后回写入站 hash（replaceState 不触发 hashchange 无回环）。
行为钉在 docs/uitest.py 深链段（后退断言 hash 终态）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r243_webui.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webui  # noqa: E402


def test_p2_1_pvbody_link_touch_inset_11px():
    src = webui.PAGE
    # 正向锁弹层规则完整串（NOTIFY 轻页 .md a::after 同值 -10px 是
    # 另一合法消费点，inline-block 盒更高零欠账，勿跨语境误伤）
    assert ("#pvMask .pvbody a::after{content:'';position:absolute;"
            "inset:-11px -4px}") in src, "弹层链接触控外扩应 -11px -4px"
    # 旧欠账规则零残留（-7px 系估算口径；-10px 系 Windows 单环境
    # 校准，CI Linux 15px 锚盒下欠 1px）——均带弹层选择器锚
    assert ("#pvMask .pvbody a::after{content:'';position:absolute;"
            "inset:-7px -4px}") not in src, "旧 -7px 规则应已退役"
    assert ("#pvMask .pvbody a::after{content:'';position:absolute;"
            "inset:-10px -4px}") not in src, "旧 -10px 规则应已退役"


def test_p3_1_popstate_deep_link_restored():
    src = webui.PAGE
    # 白名单分支内 switchView 之后必须回写入站 hash；入站带 /uN 段时
    # 原样回写（'#details/u0' 后退恢复主洞），入站裸 tab（无 /uN）时
    # 对齐 showMonTab 写点补用户段——裸回写 '#'+_h 会把 showMonTab
    # 刚写的 '#trend/u2' 洗回 '#trend'（用户段丢失，URL 深链退化）
    i = src.index("['overview','trend','details','health'].indexOf(_tab)>=0")
    block = src[i:i + 640]
    assert ("replaceState(null,'',(_s>0?'#'+_h:'#'+_tab+'/u'+U))" in block), block
    # 旧裸回写形态零残留（洗用户段退化面）
    assert "replaceState(null,'','#'+_h)" not in block, block
