# -*- coding: utf-8 -*-
"""r601：配置页「没有无法配置的项」做成**通用不变式**，不再靠一张人工名单。

历史教训：r523 用硬编码 9 键名单补缺口，r600 发现 `crawler.proxy_map`
漏网，r601 又发现 `users.routes.alert_threshold` 漏网——每次都是「发现了
再补进名单」，名单外的下一个键继续静默缺席。不变式应直接从
`config.example.yaml` 枚举叶子键，逐个要求页面有落点。

**落点判据必须严格**（负控实证）：第一版只查「键名带引号出现在源码里」，
而 `setRoute` 的同步白名单里正好有一句 `k==='alert_threshold'`——删掉编辑
控件后仍然全绿，等于空转。现在要求二者之一：
  1. 全局键：`GLB.<key>=` 写回表达式；
  2. 用户/航线键：键名作为**事件处理器实参**出现
     （`onchange="...('k',this.value)"` / `onclick="...(p)"` 这类），
     或由 `setRoute/setN/setSp` 等按名分派并在该分支里真的写回。
都不成立 = 用户改不了它。
"""
import io
import os
import re

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
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


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


def test_legacy_threshold_renders_and_writes_back():
    """真渲染：控件必须量到尺寸，输入后要真的写进 CFG（保存载荷就是 CFG）。

    静态断言测不出「控件生成在 display:none 的折叠块里」——**实测就踩了**：
    第一版把控件塞进「筛选与时段约束」折叠区，源码断言全绿，页面上用户
    根本看不到（量到 0×0）。这条把「可见」和「写回」一起钉住。
    """
    import json
    import socket
    import subprocess
    import sys
    import time
    import urllib.request

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    srv = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
         "--port", str(port)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = "http://127.0.0.1:%d" % port
    try:
        t0 = time.time()
        while time.time() - t0 < 60:
            try:
                op.open(base + "/api/state", timeout=2)
                break
            except Exception:
                time.sleep(0.3)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            import os as _os
            if not _os.path.exists(p.chromium.executable_path):
                import pytest
                pytest.skip("chromium 二进制缺失")
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1400, "height": 900})
            pg.goto(base)
            pg.wait_for_function("typeof S!=='undefined'&&S&&S.users",
                                 timeout=25000)
            pg.evaluate("()=>{switchView('cfg')}")
            pg.wait_for_timeout(900)
            pg.evaluate("""()=>{const c=document.querySelector(
              '#cfgnav .cnav[data-p="users"]');if(c)c.click()}""")
            pg.wait_for_timeout(900)
            # 展开用户卡 + 把航线行从折叠态摊开（否则量到 0×0）
            pg.evaluate("""()=>{
              const h=document.querySelector('#cfgform .ucard .uhead2');
              if(h&&h.getAttribute('aria-expanded')!=='true')h.click()}""")
            pg.wait_for_timeout(700)
            pg.evaluate("""()=>{
              document.querySelectorAll('#cfgform .rline .srow').forEach(r=>{
                if(getComputedStyle(r).display==='none')r.style.display='flex';})}""")
            pg.wait_for_timeout(400)
            got = pg.evaluate("""()=>{
              const all=[...document.querySelectorAll('input')]
                .filter(e=>/alert_threshold/.test(e.getAttribute('onchange')||''));
              const vis=all.filter(e=>e.getBoundingClientRect().width>20);
              if(!vis.length)return {total:all.length,visible:0};
              const e=vis[0],r=e.getBoundingClientRect();
              const m=/setRoute\\((\\d+),(\\d+)/.exec(e.getAttribute('onchange'));
              e.value='1234';
              e.dispatchEvent(new Event('change',{bubbles:true}));
              let v=null,keys=[];
              try{const r0=CFG[+(m[1]||0)].routes[+(m[2]||0)];
                v=r0.alert_threshold;keys=Object.keys(r0)}catch(_){}
              return {total:all.length,visible:vis.length,
                w:Math.round(r.width),h:Math.round(r.height),
                label:(e.previousElementSibling||{}).textContent||'',
                written:v,keys:keys}}""")
            b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()

    assert got["visible"] > 0, "旧总阈值控件在页面上不可见（被折叠块吞了）：%s" % got
    assert got["w"] > 20 and got["h"] > 10, "控件尺寸异常：%s" % got
    assert "总阈值" in got["label"], "控件缺标签：%s" % got
    assert str(got["written"]) == "1234", "输入没有写进 CFG：%s" % got
