# -*- coding: utf-8 -*-
"""goal 轮 WebUI 三件源码钉：P2-1 _markStale 骨架全覆盖、P2-2 矮窗
断档吸收、P3-1 montabs tablist 语义（行为钉在 docs/uitest.py 尾段）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webui  # noqa: E402


def _fn_src(name, end_pat="\nasync function "):
    src = webui.PAGE
    i = src.index(name)
    j = src.find(end_pat, i + 1)
    return src[i:j if j > 0 else i + 4000]


def test_mark_stale_covers_all_static_skeletons():
    """P2-1：冷启动失败面静态骨架全落点——#spbody（特价雷达卡首屏
    可见，「加载中…」永不到达=假等待漏网第 6 处）与 #foot（版本/
    服务标识整条消失）补进 _markStale；恢复轮 render()/spCard()
    重写自愈路径已有。"""
    seg = _fn_src("function _markStale", "\nasync function load()")
    assert "$('spbody')" in seg, seg
    assert "$('foot')" in seg, seg


def test_short_window_canvas_band_absorbs_chrome():
    """P2-2：矮窗收档阈值 600→660——720p 主流屏浏览器 chrome 吃掉
    100-170px 后视口高落 601-700 带，旧阈值下过线即回基础档 358px
    （Δ154px 跳变，图表占视口 51-60% 复现短窗挤压病灶）。"""
    src = webui.PAGE
    assert "max-height:660px" in src, "矮窗收档新阈值在场"
    assert "max-height:600px" not in src, "旧阈值退役禁复活"


# montabs 形制裁决备案（不立钉）：P3-1「升 tablist」立案经钉组复核
# 撤案——r275 退役裁决（mtabUser chip 混入 tablist 纯性破缺）与
# v185 实效档钉组维持 button 形制，禁复活钉已在 test_r275_webui.py/
# test_v185_webui.py；PAGE montabs 容器旁注释已写明两修法为何皆新害，
# 防下一轮审计再立同案。
