# -*- coding: utf-8 -*-
"""r232 WebUI 落地（审计移交：_scratch/r232d 五档×双主题审计 P1×1/P2×3）。

- demoBar 链接 CJK 断词（P1-1）：「下载源码或发行包」窄带逐字折行
  （LESSONS 十六§6 同族——CJK 无断词边界，词组粒度 nowrap 唯一解）；
  演示站是对外门面。
- brk 描边斑马行提档（P2-2）：--green 空心描边对斑马底 4.526:1 余量
  0.026 擦线（字体/内核渲染漂移即翻车）——斑马域单点提 --ok-txt。
- 开关焦点环双轨（P2-3）：.switch 族 checkbox 走 UA 默认环与全站
  2px 蓝环观感不齐——:focus-visible 显式接管。
- opscard 语义混排（P2-4）：系统行为说明文字嵌在动作按钮行尾——
  主次分离，说明下沉独立行。
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


def test_demobar_link_nowrap():
    """demoBar 链接词组粒度 nowrap：CJK 窄带断词孤字（「下载源 /
    码或发行包」）是门面缺陷；链接 9 字 ≈117px，390 档容器
    342px 容得下无溢出风险。"""
    m = re.search(r"\.demoBar a\{[^}]*\}", src())
    assert m, ".demoBar a 规则不在源码"
    assert "white-space:nowrap" in m.group(0), \
        "demoBar 链接缺词组粒度 nowrap（CJK 断词）"


def _lum(hexc):
    """WCAG 相对亮度（sRGB 线性化）。"""
    def _ch(c):
        c /= 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * _ch(int(hexc[0:2], 16)) + \
        0.7152 * _ch(int(hexc[2:4], 16)) + \
        0.0722 * _ch(int(hexc[4:6], 16))


def _contrast(fg, bg):
    l1, l2 = sorted((_lum(fg), _lum(bg)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


def test_brk_zebra_stroke_contrast():
    """brk 描边斑马行提档 --ok-txt：提档后对斑马底 (--rowalt) 必须
    ≥4.5（AA 正文）且留有余量（旧 --green 4.526 余量 0.026 擦线）。"""
    m = re.search(
        r"\.price\.brk\{color:transparent;\s*"
        r"-webkit-text-stroke:1\.1px var\(--green\)\}", src())
    assert m, "brk 描边规则形态变化（提档钉随之更新）"
    z = re.search(
        r"\.zebra:not\(:hover\) \.price\.brk\{[^}]*--ok-txt[^}]*\}", src())
    assert z, "斑马域 brk 描边未提档 --ok-txt"
    # 变量值算术复算：亮色 --ok-txt #0b6e39 对斑马 --rowalt #f5f8fb
    c = _contrast("0b6e39", "f5f8fb")
    assert c >= 4.5, f"--ok-txt 对斑马底 {c:.3f} 欠 AA"
    assert c >= 5.0, f"--ok-txt 对斑马底 {c:.3f} 余量不足（提档无效）"


def test_switch_focus_visible_ring():
    """开关焦点环显式接管：.switch 族 checkbox 曾走 UA 默认环，
    与全站 2px 蓝环双轨（焦点观感不齐）。outline 形态（box-shadow
    对 appearance:none 件微晕不可辨是既有豁免理由）。"""
    m = re.search(r"\.switch:focus-visible\{[^}]*\}", src())
    assert m, ".switch:focus-visible 规则不在源码"
    assert "outline:2px solid var(--blue)" in m.group(0), \
        "开关焦点环未显式接管"


def test_opscard_muted_below_actions():
    """opscard 系统行为说明下沉独立行：说明文字曾嵌在四个动作按钮
    行尾（主次混排）——移到 userPills 容器之后独占整行。"""
    s = src()
    muted = s.find('<span class="muted" style="display:block;width:100%')
    assert muted > 0, "opscard 说明行未下沉（display:block 独立行形态）"
    pills = s.find('id="userPills"')
    assert 0 < pills < muted, "说明行应在 userPills 容器之后"
    seg = s[s.find('id="opscard"'):muted]
    assert "推送记录</button>" in seg, "说明行与按钮行之间缺换行载体"
