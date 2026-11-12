# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r285_webui.py
- tests/test_r321_webui.py
- tests/test_r363_page_snap.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""

import gzip
import os
import pytest
import re
import sys


# ---- merged from tests/test_r285_webui.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _page_src():
    import webui
    return webui.PAGE


# ---------- srv fixture（自包含，形态同 test_r279_webui.py） ----------

def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p




# ---------- W1: 健康格触屏热区（源码序钉 + computed 行为钉） ----------

def test_hc_coarse_hotzone_source_pin():
    """源码钉：coarse+≤900 覆写块（格宽 9px+横滚恢复）在场，且声明
    位置晚于窄带 5px 基础声明（同特异性置尾胜，LESSONS 二十一§1）。
    r286 P2-3 扩带 760→900：iPad 竖屏 768/810/820 真空带入覆写域
    （钉面随行为演进改写，显式落位强度不降）。"""
    src = _page_src()
    assert "@media(pointer:coarse) and (max-width:900px)" in src, \
        "coarse 覆写块缺席（或未扩带 ≤900）"
    assert ".hc{width:9px;flex:none}" in src, "格宽 9px 覆写缺席"
    assert ".hcells{overflow-x:auto;overflow-y:hidden}" in src, \
        "横滚恢复缺席"
    i_base = src.find(".hc{width:5px}")
    i_fix = src.find(".hc{width:9px;flex:none}")
    assert 0 < i_base < i_fix, "覆写块必须晚于窄带 5px 基础声明"




# ---------- W3: 擦边琥珀与飞猪橙分离 ----------

def test_amber_distinct_from_channel_orange():
    """语义钉：--orange（擦边进度条/健康 part 档/中转曲线）与
    --c-fliggy（飞猪渠道身份色）通道差 ≥20（审计实测 ΔRGB=(7,4,10)
    同屏一色两义）；对白对比 ≥3:1（非文字图形档）；JS canvas 取色
    fallback 与令牌同值（漂移=回退双态分叉）。"""
    src = _page_src()
    m = re.search(r"--orange:#([0-9a-fA-F]{6})", src)
    assert m, "--orange 令牌缺席"
    amber = m.group(1).lower()
    assert amber != "c96a10", "旧值未退役"
    assert amber == "c98500", "擦边琥珀未按裁决向黄移: %s" % amber
    mf = re.search(r"--c-fliggy:#([0-9a-fA-F]{6})", src)
    assert mf, "飞猪渠道色缺席"
    fr = tuple(int(mf.group(1)[i:i + 2], 16) for i in (0, 2, 4))
    ar = tuple(int(amber[i:i + 2], 16) for i in (0, 2, 4))
    dmax = max(abs(a - b) for a, b in zip(ar, fr))
    assert dmax >= 20, "与飞猪橙通道差 %d 仍不可辨（<20）" % dmax
    # 对白对比（WCAG 相对亮度）
    def _lum(rgb):
        def _c(c):
            c /= 255.0
            return c / 12.92 if c <= 0.03928 else \
                ((c + 0.055) / 1.055) ** 2.4
        r, g, b = (_c(c) for c in rgb)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    ratio = 1.05 / (_lum(ar) + 0.05)
    assert ratio >= 3.0, "擦边琥珀对白 %.2f:1 <3:1（非文字图形档）" % ratio
    # canvas fallback 同值
    assert src.count("||'#%s'" % amber) == 2, \
        "JS canvas 取色 fallback 与令牌不同值（漂移）"


# ---------- W5: 宽档节奏平滑 ----------

def test_wrap_rhythm_source_pin():
    """源码钉：wrap 渐进带一条连续函数（92vw 随视口、1180 托底、
    1716 封顶）+基础 clamp 留白在场；旧硬顶/旧 1320 上限/带界断缝
    形态退役。"""
    src = _page_src()
    assert ".wrap{max-width:min(1716px,max(1180px,92vw))}" in src, \
        "渐进带连续上限缺席"
    assert "min(1716px,92vw)" not in src, \
        "带界断缝形态复活（下侧无托底的 92vw=1280-1440 恒 1180 与渐进带断缝）"
    assert re.search(r"\.wrap\{max-width:1716px\}", src) is None, \
        "1920 硬顶旧形态复活"
    assert re.search(r"\.wrap\{max-width:min\(1320px,92vw\)\}", src) is None, \
        "旧 1320 上限（跳变断口的另一侧）复活"
    assert "padding:0 clamp(12px,3vw,56px) 18px" in src, \
        "wrap 留白 clamp 缺席"




def test_demobar_link_touch_floor():
    """demoBar 链接触控地板 36px（源码钉：padding 8px 0 形态）。"""
    src = _page_src()
    assert re.search(
        r"\.demoBar a\{[^}]*padding:8px 0", src), \
        "demoBar 链接触控地板缺席"


# ---- merged from tests/test_r321_webui.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _page_src():
    import webui
    return webui.PAGE


# ---------- srv fixture（自包含，形态同 test_r286_webui.py） ----------

def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p




# ---------- P3-1: 城市面板触控地板（源码钉 + coarse 行为钉） ----------

def test_demo_statecache_disabled_unit():
    """单元钉（r321 复现案）：demo 态快照读写禁用——demo 的
    _State.version 恒 'demo'，快照跨版本守卫（meta.ver != 当前版）
    在 demo 永真；demo 临时库路径/内容恒定 → sig 恒匹配（sig 不含
    进程态端口）。双守卫同时失效，旧 demo 进程的快照永久顶替当前
    进程构建：svc（页脚服务地址）冻结为旧进程端口，且 /api/state
    未来的任何新键都会被旧快照吞掉（结构性风险）。demo 响应构建
    毫秒级，快照零收益——demo 态 _state_cache_path 恒 None（读写
    同断一处收口）。"""
    import webui
    old_ver = webui._State.version
    old_cfg = webui._State.cfg
    try:
        webui._State.cfg = {"output": {"db_path": "data/x.db"}}
        webui._State.version = "demo"
        assert webui._state_cache_path() is None, \
            "demo 态仍落快照路径（跨版本守卫在 demo 永真=旧结构永续）"
        webui._State.version = "9.9.9"
        assert webui._state_cache_path() is not None, \
            "非 demo 态快照路径被误伤（生产 SWR 语义必须保留）"
    finally:
        webui._State.version = old_ver
        webui._State.cfg = old_cfg






def test_citypanel_touch_floor_source_pin():
    """源码钉：coarse 置尾块两条触控地板声明在场，且位置晚于
    .cp-city/.cp-abc span 基础声明（同特异性置尾胜——LESSONS
    二十一§1；早插会被基础块盖回=死声明）。"""
    src = _page_src()
    m = re.search(
        r"@media\(pointer:coarse\)\{"
        r"\s*\.cp-city\{min-height:36px\}\s*"
        r"\.cp-abc span\{min-width:28px;min-height:36px\}\}", src)
    assert m, "coarse 触控地板块缺失（或声明形态漂移）"
    i_city = src.find(".cp-city{display:inline-flex")
    i_abc = src.find(".cp-abc span{min-width:22px")
    assert 0 < i_city < i_abc < m.start(), (
        "置尾块必须晚于两条基础声明（层叠地位）")




# ---- merged from tests/test_r363_page_snap.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _src():
    import webui
    return webui


def test_page_snap_caches_by_version():
    w = _src()
    body1, etag1, gz1 = w._page_snap("r363-test-v1")
    body2, etag2, gz2 = w._page_snap("r363-test-v1")
    assert body1 is body2 and gz1 is gz2 and etag1 == etag2
    assert b"__PAGEVER__" not in body1
    assert b"r363-test-v1" in body1
    assert gzip.decompress(gz1) == body1
    # 内嵌 92 枚 PNG 已压缩，gzip 只收文本层（3.28→1.92MB）；至少省 25%
    assert len(gz1) < len(body1) * 0.75
    assert etag1.startswith('"p-') and etag1.endswith('"')

    body3, etag3, gz3 = w._page_snap("r363-test-v2")
    assert etag3 != etag1
    assert body3 != body1
    assert gzip.decompress(gz3) == body3


def test_root_sends_etag_304_and_gzip():
    s = _src().PAGE  # noqa: F841  (imports/bakes PAGE before reading source)
    # r1409：取**方法体全文**而不是固定字符窗口。do_GET 现在包了一层慢请求计时，
    # 路由主体在 `_do_GET_impl`；gzip/Vary 那些头在方法体靠后位置，3200 字符
    # 的窗口切不到（CI 实测 `Content-Encoding` 断言假红）。
    import inspect
    import webui
    block = (inspect.getsource(webui._Handler.do_GET)
             + inspect.getsource(webui._Handler._do_GET_impl))
    assert "_page_snap(_State.version)" in block
    assert 'If-None-Match' in block
    assert 'self.send_response(304)' in block
    assert 'Content-Encoding", "gzip"' in block
    assert 'Vary", "Accept-Encoding"' in block
    assert 'Cache-Control", "no-cache"' in block
    # 旧实现整页明文下发：无 ETag/压缩
    assert 'body = _page_html(_State.version).encode("utf-8")' not in block
