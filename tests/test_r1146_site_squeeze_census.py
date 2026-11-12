# -*- coding: utf-8 -*-
"""r1146：全站文字挤压 / 残留侧边抽屉的真实渲染门禁（r1145 改造回归）。

判据（每状态）：
  A 文本被裁切：scrollWidth>clientWidth+1 且无省略号/title/滚动祖先；
  B 兄弟盒相交：只比普通流、非 inline/contents/SVG，>1.5px；
  C 全高侧边抽屉：fixed、>=85vh、280–700px、贴 body 左/右缘、非满宽；
  D 页面横向溢出。
白名单只收已核实无害的光学外扩（见 WL/NEGWL 注释），不是「门禁放水」。
负控：注入窄盒 nowrap 文本 + 假右抽屉 + 重叠对，A/B/C 必须同时报警。
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

pytest.importorskip("playwright", reason="渲染普查依赖 playwright")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CENSUS = r"""
()=>{
 const vw=document.documentElement.clientWidth,vh=innerHeight;
 const br=document.body.getBoundingClientRect();
 const vis=e=>{const c=getComputedStyle(e),r=e.getBoundingClientRect();
   return c.display!=='none'&&c.visibility!=='hidden'&&r.width>1&&r.height>1};
 const tag=e=>String((e&&(e.id||e.className))||'').slice(0,40);
 const leafText=e=>[...e.childNodes].some(n=>n.nodeType===3&&n.textContent.trim());
 const SKIP=new Set(['SCRIPT','STYLE','TEXTAREA','INPUT','SELECT','OPTION','CANVAS','SVG']);
 const all=[...document.body.querySelectorAll('*')].filter(e=>!SKIP.has(e.tagName));
 const leaves=all.filter(e=>vis(e)&&leafText(e));
 const scrollAnc=e=>{let p=e.parentElement,n=0;
   while(p&&p!==document.body&&n++<8){const c=getComputedStyle(p);
     if(['auto','scroll'].includes(c.overflowX))return true;p=p.parentElement;}
   return false;};
 /* 已核实无害的光学外扩：uact2 4px 光学对齐；chhead 8px 触控伪元素；
    srx-times i 8px 盒里的 10px 箭头；cnav 墨迹落内衬；subsec 4px 箭头。 */
 const WL=[['.uact2 a',4],['.chhead',8],['.srx-times i',2],['.cnav',4],['.subsec',4]];
 const wl=(e,over)=>WL.some(x=>{try{return e.matches(x[0])&&over<=x[1]}catch(_){return false}});
 const clip=[],overl=[],drawers=[];
 for(const e of leaves){
   const c=getComputedStyle(e);
   const ell=(c.textOverflow==='ellipsis'&&c.overflow!=='visible')||e.getAttribute('title')
     ||(e.closest('[title]')&&e.closest('[title]')!==e);
   if(e.scrollWidth>e.clientWidth+1&&!ell&&!scrollAnc(e)
      &&!wl(e,e.scrollWidth-e.clientWidth)){
     clip.push({t:tag(e),x:(e.textContent||'').trim().slice(0,20),
       sw:e.scrollWidth,cw:e.clientWidth,
       /* r1526：CI（Linux）CJK 字体比本机宽，同一页面在那边会裁、这边不裁。
          只报 t/x/sw/cw 定位不了盒子（t 为空 = 该节点既无 id 也无 class）。
          这里把**四层祖先链 + 各层宽度**一并带出，失败信息就能直接指到
          "谁只给了 44px"，不必再靠猜。 */
       path:(()=>{const f=n=>n.tagName.toLowerCase()
           + (n.id?('#'+n.id):'')
           + (n.className&&String(n.className).trim()
              ?('.'+String(n.className).trim().split(/\s+/).join('.')):'');
         const out=[];let p=e;
         for(let i=0;i<4&&p&&p!==document.body;i++){out.push(f(p));p=p.parentElement;}
         return out.join(' < ');})(),
       chain:(()=>{const out=[];let p=e;
         for(let i=0;i<4&&p&&p!==document.body;i++){
           out.push(Math.round(p.getBoundingClientRect().width));p=p.parentElement;}
         return out;})(),
       ws:c.whiteSpace,ov:c.overflow});
   }
 }
 const holders=all.filter(e=>vis(e)&&e.children.length>1&&e.children.length<80);
 for(const p of holders){
   const pc=getComputedStyle(p);
   if(['auto','scroll'].includes(pc.overflowX))continue;
   const kids=[...p.children].filter(vis);
   for(let i=0;i<kids.length;i++)for(let j=i+1;j<kids.length;j++){
     const a=kids[i],b=kids[j],ca=getComputedStyle(a),cb=getComputedStyle(b);
     if(!['static','relative'].includes(ca.position))continue;
     if(!['static','relative'].includes(cb.position))continue;
     if(ca.display==='inline'||cb.display==='inline')continue;
     if(ca.display==='contents'||cb.display==='contents')continue;
     if(a.closest('svg')||b.closest('svg'))continue;
     const ra=a.getBoundingClientRect(),rb=b.getBoundingClientRect();
     if(ra.width*rb.height<64)continue;
     const ox=Math.min(ra.right,rb.right)-Math.max(ra.left,rb.left);
     const oy=Math.min(ra.bottom,rb.bottom)-Math.max(ra.top,rb.top);
     if(ox>1.5&&oy>1.5)overl.push({p:tag(p),a:tag(a),b:tag(b),
       ox:Math.round(ox),oy:Math.round(oy)});
   }
 }
 for(const e of all){
   const c=getComputedStyle(e);
   if(c.position!=='fixed'||!vis(e))continue;
   const r=e.getBoundingClientRect();
   if(r.height<vh*0.85||r.width<280||r.width>700)continue;
   if(r.width>=br.width-8)continue;
   if(Math.abs(r.right-br.right)<=2||Math.abs(r.left-br.left)<=2)
     drawers.push({t:tag(e),w:Math.round(r.width),h:Math.round(r.height)});
 }
 return {leafN:leaves.length,clipN:clip.length,clip:clip.slice(0,5),
   overlN:overl.length,overl:overl.slice(0,5),
   drawersN:drawers.length,drawers:drawers.slice(0,3),
   pageOver:document.documentElement.scrollWidth-vw};
}
"""

NEG = r"""
()=>{
 const w=document.createElement('div');
 w.id='sqNegWrap';
 w.style.cssText='position:fixed;left:8px;top:8px;z-index:99999;background:#fff;color:#000;'
  +'font:13px sans-serif;padding:4px';
 w.innerHTML='<div id="sqNegClip" style="width:90px;white-space:nowrap">'
  +'超长文本用来验证裁切探针一定会报警</div>'
  +'<div id="sqNegA" style="display:inline-block;width:120px;height:24px;background:#eee">A</div>'
  +'<div id="sqNegB" style="display:inline-block;width:120px;height:24px;background:#ddd;margin-left:-60px">B</div>'
  +'<div id="sqNegDrawer" style="position:fixed;right:0;top:0;width:460px;height:100vh;'
  +'background:#fafafa;z-index:99998"></div>';
 document.body.appendChild(w);
 return true;
}
"""


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="module")
def srv():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失")
    port = _free_port()
    base = "http://127.0.0.1:%d" % port
    proc = subprocess.Popen([sys.executable, "webui.py", "--demo", "--port", str(port)],
                            cwd=ROOT, stdout=subprocess.DEVNULL,
                            stderr=subprocess.STDOUT)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(120):
        try:
            op.open(base + "/api/state", timeout=2)
            break
        except Exception:
            time.sleep(0.25)
    else:
        proc.kill()
        pytest.fail("demo 未启动")
    yield base
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()


def _bad(d):
    bad = []
    if d["clipN"]:
        bad.append("文本裁切 %d: %s" % (d["clipN"], d["clip"]))
    if d["overlN"]:
        bad.append("兄弟相交 %d: %s" % (d["overlN"], d["overl"]))
    if d["drawersN"]:
        bad.append("残留侧边抽屉 %d: %s" % (d["drawersN"], d["drawers"]))
    if d["pageOver"] > 1:
        bad.append("页面横向溢出 %d" % d["pageOver"])
    if d["leafN"] < 20:
        bad.append("样本过少 leafN=%s（疑似空白面）" % d["leafN"])
    return bad


def test_site_squeeze_and_no_side_drawer(srv):
    from playwright.sync_api import sync_playwright
    states = [("mon", "overview"), ("mon", "specials"), ("mon", "health"),
              ("search", ""), ("cfg", "users")]
    bad = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        for width in (1440, 390):
            pg = b.new_page(viewport={"width": width, "height": 1000})
            pg.goto(srv + "/", wait_until="load")
            pg.wait_for_function("typeof S==='object'&&S&&S.users", timeout=30000)
            pg.wait_for_timeout(900)
            for theme in ("light", "dark"):
                pg.evaluate("(t)=>document.documentElement.dataset.theme=t", theme)
                for view, sub in states:
                    if view == "mon":
                        pg.evaluate("switchView('mon')")
                        pg.evaluate("(t)=>showMonTab(t)", sub)
                        pg.wait_for_timeout(1100 if sub in ("health", "specials") else 600)
                    elif view == "search":
                        pg.evaluate("switchView('search')")
                        pg.wait_for_timeout(700)
                    else:
                        pg.evaluate("switchView('cfg')")
                        pg.evaluate("(p)=>showCfgPanel(p)", sub)
                        pg.wait_for_timeout(700)
                    d = pg.evaluate(CENSUS)
                    label = "%d/%s/%s%s" % (width, theme, view, ("-"+sub) if sub else "")
                    for msg in _bad(d):
                        bad.append(label + ": " + msg)
            if width == 1440:
                pg.evaluate(NEG)
                pg.wait_for_timeout(200)
                dn = pg.evaluate(CENSUS)
                pg.evaluate("()=>{const n=document.getElementById('sqNegWrap');if(n)n.remove()}")
                if not dn["clipN"]:
                    bad.append("负控失明：注入窄盒 nowrap 文本未报警")
                if not dn["overlN"]:
                    bad.append("负控失明：注入重叠对未报警")
                if not dn["drawersN"]:
                    bad.append("负控失明：注入假右抽屉未报警")
            pg.close()
        b.close()
    assert not bad, "全站挤压/侧边抽屉: " + "；".join(bad)
