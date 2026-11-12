# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1038_cfg_320_login.py
- tests/test_r1503_cfg_pacing_layout.py
- tests/test_r601_every_config_key_reachable.py
- tests/test_r629_config_page_template_chain.py
- tests/test_r811_cfg_900_breakpoint_exclusive.py
- tests/test_r996_cfg_notes_compact.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import io
import json
import os
import pytest
import re
import socket
import subprocess
import sys
import time
import urllib.request


# ---- merged from tests/test_r1038_cfg_320_login.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_static_narrow_login_and_hint_rules():
    with io.StringIO(webui_full_src()) as f:
        src = f.read()
    i = src.index("r1038：320 档卡名被")
    block = src[i:i + 700]
    assert "@media(max-width:360px)" in block
    assert "#loginRows .lgcard .lgreq{display:none!important}" in block
    assert '#loginRows .lgcard[data-channel^="app_"] .lgtag{display:none!important}' in block
    j = src.index("r1038：能力矩阵常在配置页隐藏时返回")
    hint = src[j:j + 400]
    assert "requestAnimationFrame(()=>{try{dimScrollHint()}catch(e){}})" in hint
    # 提示仍只在真实溢出时出现（不是固定显示）
    k = src.index("function dimScrollHint()")
    assert "scrollWidth>wrap.clientWidth+2" in src[k:k + 260]


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


MEASURE = """()=>{
  const disp=el=>getComputedStyle(el).display;
  const names=[...document.querySelectorAll('#loginRows .lgnm')].map(el=>({
    t:el.textContent.trim(),sw:el.scrollWidth,cw:el.clientWidth,w:+el.getBoundingClientRect().width.toFixed(1)}));
  const req=[...document.querySelectorAll('#loginRows .lgreq')].map(disp);
  const appTags=[...document.querySelectorAll('#loginRows .lgcard[data-channel^="app_"] .lgtag')].map(disp);
  const webTags=[...document.querySelectorAll('#loginRows .lgcard:not([data-channel^="app_"]) .lgtag')].map(disp);
  const wrap=document.querySelector('#cfgDimMatrix .dimwrap');
  const hint=document.querySelector('#cfgDimMatrix .dimscroll');
  const before=wrap.scrollLeft;
  wrap.scrollLeft=9999;
  const th=wrap.querySelector('tbody th:not([colspan])');
  const wr=wrap.getBoundingClientRect(), tr=th.getBoundingClientRect();
  const out={names,req,appTags,webTags,hint:disp(hint),
    mx:{sw:wrap.scrollWidth,cw:wrap.clientWidth,thL:+tr.left.toFixed(1),thR:+tr.right.toFixed(1),
        wrapL:+wr.left.toFixed(1),wrapR:+wr.right.toFixed(1),maxScroll:wrap.scrollLeft},
    pageOF:document.documentElement.scrollWidth-innerWidth};
  wrap.scrollLeft=before;
  return out;
}"""




# ---- merged from tests/test_r1503_cfg_pacing_layout.py ----

pytest.importorskip("playwright", reason="渲染门禁依赖 playwright")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p






def open_pacing(browser, width):
    ctx = browser.new_context(viewport={"width": width, "height": 900})
    page = ctx.new_page()
    page.goto(BASE + "/", wait_until="networkidle", timeout=45000)
    page.wait_for_function("typeof switchView==='function'", timeout=25000)
    page.evaluate("switchView('cfg');showCfgPanel('pacing')")
    # /api/strategy 真实环境 ~6s，并发门禁下会超过 25s（gate8 实测）
    page.wait_for_function("document.querySelectorAll('#cfgpacingRows .srow').length>0", timeout=45000)
    page.wait_for_timeout(600)
    return ctx, page


PROBE = r"""
() => {
  function textX(el){
    if(!el) return null;
    var w=document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null), n;
    while((n=w.nextNode())){ if((n.nodeValue||'').trim()){ var r=document.createRange();
      r.setStart(n,0); r.setEnd(n,Math.min(1,n.length)); return +r.getBoundingClientRect().x.toFixed(1);} }
    return null;
  }
  var rows=[...document.querySelectorAll('#cfgpacingRows .srow')];
  var out=[];
  rows.forEach(function(r){
    var hd=r.querySelector('.shd'); if(!hd) return;
    var rb=r.getBoundingClientRect();
    var q=function(s){return hd.querySelector(s)};
    var box=function(e){var b=e.getBoundingClientRect();return {x:+b.x.toFixed(1),y:+b.y.toFixed(1),right:+b.right.toFixed(1),bottom:+b.bottom.toFixed(1),w:+b.width.toFixed(1),h:+b.height.toFixed(1)}};
    var kid={scn:q('.scn'),typ:q('.chip.strg'),slab:q('.slab'),src:q('.hbadge'),val:q('.sval'),fold:q('.sfold')};
    out.push({h:+rb.height.toFixed(1), y:+rb.y.toFixed(1), x:+rb.x.toFixed(1), right:+rb.right.toFixed(1),
      kids:{scn:kid.scn?box(kid.scn):null,typ:kid.typ?box(kid.typ):null,slab:kid.slab&&kid.slab.offsetParent?box(kid.slab):null,
            src:kid.src?box(kid.src):null,val:kid.val?box(kid.val):null,fold:kid.fold?box(kid.fold):null}});
  });
  var gut=[];
  [['#sec-pacing-card .uhead .zh',textX(document.querySelector('#sec-pacing-card .uhead .zh'))],
   ['#cfgpacing .subsec',textX(document.querySelector('#cfgpacing .subsec'))],
   ['#cfgpacing .sintro',textX(document.querySelector('#cfgpacing .sintro'))],
   ['#cfgpacingRows .sfam',textX(document.querySelector('#cfgpacingRows .sfam'))],
   ['#cfgpacingRows .scn',textX(document.querySelector('#cfgpacingRows .scn'))]].forEach(function(a){gut.push(a)});
  return {n:rows.length, rows:out, gut:gut,
          docDx:document.documentElement.scrollWidth-document.documentElement.clientWidth};
}
"""


def _col_range(rows, key):
    xs = [r["kids"][key]["x"] for r in rows if r["kids"][key]]
    return max(xs) - min(xs) if xs else 0


def _gutter_spread(gut):
    vals = [x for _, x in gut if x is not None]
    return max(vals) - min(vals) if vals else 0








EXPANDED = r"""
() => {
  const r=document.querySelector('#cfgpacingRows .srow.open');
  if(!r) return null;
  const g=s=>{const e=r.querySelector(s);if(!e)return null;const b=e.getBoundingClientRect();return {x:+b.x.toFixed(1),y:+b.y.toFixed(1),w:+b.width.toFixed(1),h:+b.height.toFixed(1)}};
  return {sbd:g('.sbd'),sgrid:g('.sgrid'),glab:g('.sgrid .glab'),sadv:g('.sadv'),sadvB:g('.sadv b'),
          sadvV:g('.sadv-r>span'),stip:g('.snote.stip'),stipK:g('.stip-k'),stipV:g('.stip-v'),
          sact:g('.sact'),runPseudo:getComputedStyle(r.querySelector('.sact'),'::before').content,
          fakeChip:!!r.querySelector('.snote.stip .chip'),docDx:document.documentElement.scrollWidth-document.documentElement.clientWidth};
}
"""






# ---- merged from tests/test_r601_every_config_key_reachable.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 每条豁免都要给「页面用什么承载它」的实证，不能只写一句理由。
EXEMPT = {
    # 图床 provider 由「图床」卡片整体切换承载：setIh(…,'provider',…) 的
    # 值只在 ghimg/smms 两个枚举间切换，没有独立的自由输入框。
    "users.notifier.image_host.provider":
        "setIh 按卡片切换 provider（ghimg/smms 枚举）",
}


def _leaf_keys():
    cfg = io.open(os.path.join(ROOT, "config.example.yaml"),
                  encoding="utf-8").read()
    keys, stack = [], []
    for ln in cfg.splitlines():
        if not ln.strip() or ln.strip().startswith("#"):
            continue
        m = re.match(r"^(\s*)([A-Za-z_][\w]*):", ln)
        if not m:
            continue
        d, k = len(m.group(1)), m.group(2)
        while stack and stack[-1][0] >= d:
            stack.pop()
        stack.append((d, k))
        keys.append(".".join(x[1] for x in stack))
    return [k for k in keys
            if not any(o.startswith(k + ".") for o in keys)]


def _w():
    return webui_full_src()


def _event_bound(w, name):
    """键名是否被真正绑定到控件（而不是散落的字符串常量）。"""
    q = re.escape(name)
    pats = (
        # onchange="setX(…,'k',this.value)" / onclick="toggleX(this,p)"
        r"(?:onchange|oninput|onclick|onkeyup|onkeydown)\s*=\s*[\"'][^\"']*"
        r"[\"']" + q + r"[\"']",
        # data-k="k"（程序化绑定）
        r"data-k\s*=\s*[\"']" + q + r"[\"']",
        # glcell('…','glbX','GLB.k=…')：键名作为 glcell 实参
        r"glcell\([^)]*[\"']" + q + r"[\"']",
        # 动态表：['k',…].map(p=>glcell(…'glbX_'+p…)) 或 [p].map(…)
        r"\[[^\]]*[\"']" + q + r"[\"'][^\]]*\]\s*\.\s*map\(",
        # 平台/渠道 chip 列表数据源：['qunar','fliggy',…] 驱动勾选控件
        r"\[\s*[^\]]*[\"']" + q + r"[\"']\s*[^\]]*\]\s*\.\s*(?:map|forEach)\(",
    )
    if any(re.search(p, w) for p in pats):
        return True
    # 控件 id 承载：键名 kebab/驼峰化成控件 id（glbBbs / glbCad_ / spRadarCool）
    ident = "".join(part.capitalize() for part in re.split(r"[_\W]+", name) if part)
    for cand in (name, ident, ident[0].lower() + ident[1:] if ident else ident):
        if cand and re.search(r"[\"'][A-Za-z]*" + re.escape(cand) + r"[\"']", w):
            return True
    return False


def test_every_example_config_key_has_a_control():
    w = _w()
    missing = []
    for k in _leaf_keys():
        if k in EXEMPT:
            continue
        short = k.split(".")[-1]
        if re.search(r"GLB\." + re.escape(short) + r"\s*=", w):
            continue
        if _event_bound(w, short):
            continue
        missing.append(k)
    assert not missing, (
        "这些配置项在页面上没有落点（用户只能改文件）：%s" % missing)


def test_exemptions_carry_evidence():
    leaves = set(_leaf_keys())
    w = _w()
    for k, why in EXEMPT.items():
        assert k in leaves, "豁免了一个不存在的键：%s" % k
        assert len(why) > 8, "豁免 %s 没写清承载方式" % k
        # 豁免的理由必须是可验证的：里面提到的函数名要真在源码里
        fn = re.match(r"(\w+)\s", why)
        assert fn and ("function " + fn.group(1) in w
                       or (fn.group(1) + "(") in w), (
            "豁免 %s 的理由里提到的入口 %r 在 webui.py 里找不到" % (k, why))


def test_legacy_threshold_is_editable_and_saved():
    """`alert_threshold` 是 r601 实际补的那一个：控件 + 写回都要在。"""
    w = _w()
    assert "setRoute(${i},${j},'alert_threshold',this.value)" in w, (
        "旧总阈值没有编辑控件")
    i = w.index("function setRoute(i,j,k,v)")
    seg = w[i:i + 700]
    assert "'alert_threshold'" in seg, "setRoute 没有分派 alert_threshold"




# ---- merged from tests/test_r629_config_page_template_chain.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return webui_full_src()




# ---- merged from tests/test_r811_cfg_900_breakpoint_exclusive.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

M = r"""() => {
  const lay = document.querySelector('#cfgview .cfglayout');
  const nav = document.querySelector('#cfgview .cfgnav');
  if (!lay || !nav) return {err: 'no cfglayout/cfgnav'};
  const cols = getComputedStyle(lay).gridTemplateColumns.trim().split(/\s+/);
  const items = [...nav.querySelectorAll('.cnav')].map(e => {
    const r = e.getBoundingClientRect();
    return {txt: (e.textContent || '').trim().slice(0, 10),
            w: +r.width.toFixed(1), scrollW: e.scrollWidth, clientW: e.clientWidth,
            lost: e.scrollWidth - e.clientWidth};
  });
  return {nCols: cols.length, cols: cols.join(' '),
          navW: +nav.getBoundingClientRect().width.toFixed(1), items};
}"""

REVERT = ("@media(min-width:900px) and (max-width:901px){"
          ".cfglayout{grid-template-columns:188px minmax(0,1fr)!important}"
          # r1405：900 档导航现为两列网格，单注回两列不再让文字溢出；
          # 负控要复现原缺陷，必须同时注回「四项一行、每项 44px」的旧形态。
          ".cfgnav{display:grid!important;"
          "grid-template-columns:repeat(4,minmax(0,1fr))!important}}")


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p










# ---- merged from tests/test_r996_cfg_notes_compact.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    with io.StringIO(webui_full_src()) as f:
        return f.read()


def test_login_section_has_one_policy_sentence_only():
    src = _src()
    block = src[src.index('id="sec-login"'):src.index('id="sec-chlinks"')]
    assert "都必须登录（入口页可匿名浏览" in block
    assert block.count("都必须登录") == 1, "登录分区重复了政策句"
    assert "去哪儿" not in block and "停服" not in block, (
        "去哪儿停服说明又回到登录卡")
    assert "lgAppNames" not in block, "App 名称仍在卡头整段罗列"
    # JS 里也不得再生成重复脚注
    assert "lgnote" not in src, "登录卡仍在拼重复脚注 .lgnote"
    assert "保存后按实际请求核验" in block




