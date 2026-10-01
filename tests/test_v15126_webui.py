# -*- coding: utf-8 -*-
"""WebUI 精细化（r226 审计落地）：pushLog 换代令牌 / chips 键盘焦点
恢复 / 两处死类钩子清理 / delUser 手风琴索引 / FGDK 令牌单源 /
.tj 跳走势注入面收口 / 预览无表占位注。

背景（_scratch/r226_report_webui.md）：
- pushLog 是弹层三入口（showLog/previewPush/pushLog）唯一缺换代
  令牌的——27s 的预览响应可覆盖正在阅读的推送记录、Esc 取消不了
  在途请求（令牌契约 _PV_SEQ/_PV_PENDING 写在 L3001 注释，showLog/
  previewPush 都执行了）；
- 五处 chips（userPills/datechips/routechips/platchips/chartRoutes）
  innerHTML 重建无焦点恢复——表格行/表头已救，chips 是最后一处缺口；
- .qbrk（JS 产出 CSS 零消费）与 .hlb（图例色票零声明）死类钩子；
- delUser 展开态删前方用户：OPEN_USER 索引不调整→重建后错位卡片
  自动展开；
- renderCal 的 FGDK='#0a0f16' 是 --bg 令牌手抄副本（JS 侧唯一
  字面量取色，其余走 cssv() 单源）；
- .tj 内联 onclick 拼 he(f.route)——he() 在 JS 串上下文因实体解码
  还原引号而无效（团队既有结论），行键应走 dataset 源头取值；
- /api/preview with_tables=False 整段无明细总表且无占位注——构建
  参考读者会误以为实发也无表。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v15126_webui.py -q
"""
import inspect
import re

import webui

_SRC = None


def src():
    global _SRC
    if _SRC is None:
        _SRC = inspect.getsource(webui)
    return _SRC


def _func_body(name: str) -> str:
    """提取 PAGE 段内 `async function name()` / `function name()` 的
    函数体（到下一个顶层 function 为止的近似切片）。"""
    s = src()
    m = re.search(r"(?:async )?function %s\b" % re.escape(name), s)
    assert m, f"function {name} 不在源码"
    return s[m.start():m.start() + 2200]


# ---------------- pushLog 换代令牌 ----------------

def test_pushlog_has_seq_token():
    body = _func_body("pushLog")
    assert "++_PV_SEQ" in body, "pushLog 入口未捕获换代令牌"
    assert "_PV_PENDING=true" in body, "pushLog 未置在途标志"


def test_pushlog_stale_response_discarded():
    body = _func_body("pushLog")
    assert "_sq!==_PV_SEQ" in body, "迟到响应未按令牌弃放"


def test_pushlog_pending_reset_in_finally():
    body = _func_body("pushLog")
    assert "finally" in body and "_PV_PENDING=false" in body, \
        "在途标志未在 finally 复位"


# ---------------- chips 键盘焦点恢复 ----------------

def test_chips_refocus_helper_exists():
    s = src()
    assert "function chipsRefocus" in s, "chips 焦点恢复 helper 缺失"


def test_chips_rebuilds_routed_through_helper():
    """五处 chips 重建（userPills/datechips/routechips/platchips/
    chartRoutes）全部经 chipsRefocus——innerHTML 直赋的裸重建点
    归零（表格行/表头已有 data-k 回焦，chips 是最后一处缺口）。"""
    s = src()
    for cid in ("userPills", "datechips", "routechips", "platchips",
                "chartRoutes"):
        assert f'chipsRefocus("{cid}"' in s or \
               f"chipsRefocus('{cid}'" in s or \
               f'chipsRefocus({cid}' in s, f"{cid} 重建未走 helper"


# ---------------- 死类钩子清理 ----------------

def test_qbrk_dead_class_removed():
    assert "qbrk" not in src(), ".qbrk 死类（JS 产出 CSS 零消费）应删"


def test_hlb_dead_class_removed():
    assert "hlb" not in src(), ".hlb 死类钩子（图例色票零声明）应删"


# ---------------- delUser 手风琴索引 ----------------

def test_deluser_open_user_index_shift():
    s = src()
    m = re.search(r"function delUser\b.{0,900}", s, re.S)
    assert m, "delUser 不在源码"
    body = m.group(0)
    assert "OPEN_USER===i" in body and "OPEN_USER--" in body, \
        "删除用户未调整 OPEN_USER 索引（重建后错位卡片自动展开）"


# ---------------- FGDK 令牌单源 ----------------

def test_rendercal_fgdk_from_cssv():
    s = src()
    assert "FGDK=cssv('--bg')" in s, \
        "FGDK 手抄字面量应改 cssv('--bg') 单源"


# ---------------- .tj 注入面收口 ----------------

def test_tj_jump_uses_dataset():
    """.tj 跳走势经 dataset 取参：onclick 字符串里不再拼接
    he(f.route)（he() 在 JS 串上下文因实体解码还原引号而无效）。"""
    s = src()
    assert "jumpRowTrend(this.dataset.r,this.dataset.d)" in s, \
        ".tj 应改 dataset 取参"
    assert "jumpRowTrend('${he(f.route)}'" not in s, \
        "内联拼接 f.route 的旧形态应退役"


# ---------------- 预览无表占位注 ----------------

def test_preview_no_table_note():
    assert "预览态无明细总表图" in src(), \
        "with_tables=False 预览缺占位注（r227 P3-8 词面收窄≤40，" \
        "行宽钉 tests/test_v15127_push.py）"
