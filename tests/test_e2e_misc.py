# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r1076_intervention_all_first.py
- tests/test_r1137_mobile_search_top.py
- tests/test_r599_tip_width_not_shrunk_by_anchor.py
- tests/test_r602_path_failure_class_visible.py
- tests/test_r604_unscanned_channels_visible.py
- tests/test_r632_long_cooldown_is_readable.py
- tests/test_r657_warmup_hint_names_channels.py
- tests/test_r805_modal_aria_label.py
- tests/test_r805ai_rt_needs_return_dates.py
- tests/test_r814b_pip_frame_error.py

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


# ---- merged from tests/test_r1076_intervention_all_first.py ----

pytest.importorskip("playwright",
                    reason="干预行动作可见性依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = None


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p








# ---- merged from tests/test_r1137_mobile_search_top.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_PROBE = """() => {
 const vis=e=>{if(!e)return false;const r=e.getBoundingClientRect();
  const cs=getComputedStyle(e);
  return r.width>2&&r.height>2&&cs.display!=='none'&&cs.visibility!=='hidden'
    &&Number(cs.opacity||1)>0.05;};
 const bar=document.getElementById('srxMobilebar');
 const br=bar.getBoundingClientRect(), bs=getComputedStyle(bar);
 const btns=[...bar.querySelectorAll('.srx-mbtn')].filter(vis).map(b=>{
  const r=b.getBoundingClientRect();
  return {t:(b.innerText||'').trim(),w:Math.round(r.width),
    h:Math.round(r.height),x:Math.round(r.left),
    aria:b.getAttribute('aria-expanded'),
    name:((b.innerText||'').trim()||b.getAttribute('aria-label')||'')};});
 const q=document.querySelector('#srxProbeForm .srx-qrow');
 const ys=q?[...q.children].filter(vis)
   .map(e=>Math.round(e.getBoundingClientRect().top)):[];
 const hero=document.querySelector('.srx-hero');
 const res=document.getElementById('srxResults');
 const topH=(hero&&res)?Math.round(res.getBoundingClientRect().top
   -hero.getBoundingClientRect().top):-1;
 const ch=document.getElementById('srxChannelRow');
 const chr=ch?ch.getBoundingClientRect():null;
 const bare=[];
 for(const b of document.querySelectorAll(
   '#searchview .srx-hero button,#searchview #srxProbe button,#srxMobilebar button')){
  if(!vis(b))continue;
  const t=(b.innerText||'').trim();
  if(!t&&!b.getAttribute('aria-label'))
    bare.push({id:b.id,cls:String(b.className).slice(0,50)});}
 const more=document.querySelector('.srx-hero-act > .srx-more-btn');
 const ov=[...document.querySelectorAll(
   '#srxOvTool,#srxMobilebar [data-mobile="overview"]')].filter(vis);
 return {
  bar:{pos:bs.position,h:Math.round(br.height),w:Math.round(br.width),
    x:Math.round(br.left),right:Math.round(br.right),
    bottomGap:Math.round(innerHeight-br.bottom),z:bs.zIndex},
  btns,formRows:[...new Set(ys)].length,topH,
  probeRows:[...new Set([...document.querySelectorAll('#srxProbe > *')]
    .filter(vis).map(e=>Math.round(e.getBoundingClientRect().top)))].length,
  chH:chr?Math.round(chr.height):-1,
  chRows:(()=>{const p=document.getElementById('srxPlatPick');
    if(!p)return 0;return [...new Set([...p.querySelectorAll('.srx-pchip')]
      .map(e=>Math.round(e.getBoundingClientRect().top)))].length})(),
  bare,moreBefore:more?getComputedStyle(more,'::before').content:null,
  moreW:more?Math.round(more.getBoundingClientRect().width):0,
  ovCount:ov.length,ovTexts:ov.map(e=>(e.innerText||'').trim()),
  over:document.documentElement.scrollWidth-innerWidth};
}"""



def _page(browser, server, width):
    pg = browser.new_page(viewport={"width": width, "height": 950},
                          is_mobile=(width <= 600), has_touch=(width <= 600))
    pg.goto("http://127.0.0.1:%d/" % server, wait_until="domcontentloaded",
            timeout=30000)
    pg.wait_for_timeout(2200)
    pg.evaluate("switchView('search')")
    pg.wait_for_timeout(700)
    return pg










# ---- merged from tests/test_r599_tip_width_not_shrunk_by_anchor.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return webui_full_src()


def _rule(src, sel):
    i = src.index(sel + "{")
    return src[i:src.index("}", i)]


def test_spmon_tip_declares_content_width():
    r = _rule(_w(), ".spmon-tip")
    assert "position:absolute" in r
    assert "width:max-content" in r, (
        "特价监控浮窗没有 width:max-content：左值贴右缘后会被压成 "
        "min-content，落位读到的宽度是假的")


def test_ws_tip_declares_content_width():
    r = _rule(_w(), ".ws-tip")
    assert "position:absolute" in r
    assert "width:max-content" in r, "关注走势浮窗同样会被压窄"


def test_content_width_does_not_remove_the_cap():
    """max-width 必须还在：去掉就变成一条横贯全屏的长条（r374 已修过）。"""
    w = _w()
    assert "max-width:270px" in _rule(w, ".ws-tip")
    assert "max-width:min(270px,calc(100vw - 16px))" in _rule(w, ".spmon-tip")




# ---- merged from tests/test_r602_path_failure_class_visible.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return webui_full_src()


def test_path_label_carries_failure_classes():
    w = _w()
    i = w.index("const _pi=(j.paths||{})[p]||{};")
    seg = w[i:i + 1200]
    assert "_v.login" in seg, "通路小标没有读登录墙计数"
    assert "_v.soft" in seg, "通路小标没有读软拒计数"
    assert "需登录" in seg and "软拒" in seg, "通路小标没有给出中文分类名"


def test_failure_classes_only_shown_when_present():
    """正常通路不得被加上噪声——只在计数 >0 时附注。"""
    w = _w()
    i = w.index("const _pi=(j.paths||{})[p]||{};")
    seg = w[i:i + 1200]
    assert "if((_v.login||0)>0)" in seg, "登录墙没有做 >0 判断"
    assert "if((_v.soft||0)>0)" in seg, "软拒没有做 >0 判断"








def test_pacing_panel_path_line_uses_the_same_classifier():
    """同一份账本在两处渲染，分类口径必须一致（r602）。

    渠道健康卡与节流面板速览都列「通路 成功率」。只在一处加分类，
    同屏会出现「健康卡说需登录 7、节流面板只说 20%」的两种说法——
    这正是用户反复提的「不要两个面板互相矛盾」。
    """
    w = webui_full_src()
    i = w.index("const pws=[];")
    seg = w[i:i + 900]
    assert "w.login" in seg, "节流面板通路行没有读登录墙计数"
    assert "w.soft" in seg, "节流面板通路行没有读软拒计数"
    assert "需登录" in seg and "软拒" in seg, "节流面板通路行缺中文分类名"
    # 两处必须各自都在：一处被删就是口径分叉。
    # 按拼接表达式精确计数——`'需登录 '` 在徽标 caption 里还有一处，
    # 用宽口径会把「少了一处」误判成达标（负控实测）。
    assert "_fx.push('需登录 '+_v.login)" in w, "健康卡通路行的分类被删了"
    assert "_pf.push('需登录 '+w.login)" in w, "节流面板通路行的分类被删了"


# ---- merged from tests/test_r604_unscanned_channels_visible.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _w():
    return webui_full_src()


def test_backend_ships_enabled_platforms():
    w = _w()
    assert "def _enabled_platforms" in w, "缺少已勾选渠道的收集函数"
    i = w.index("def _enabled_platforms")
    seg = w[i:i + 700]
    assert 'u.get("platforms")' in seg, "没有从 users[].platforms 取并集"
    # 两个分支（demo / 真实）都要下发，只给一边会让另一种跑法缺这条
    assert w.count('["enabled_platforms"] = _enabled_platforms()') == 2, (
        "demo 与真实分支没有都下发 enabled_platforms（实际 %d 处）"
        % w.count('["enabled_platforms"] = _enabled_platforms()'))


def test_frontend_reads_payload_not_cfg():
    """健康页的 CFG 是 null——读它等于这段永不出现（已实证）。"""
    w = _w()
    i = w.index("const _miss=_cfgP.filter")
    # 窗口要够宽：r979 之后 enabled_platforms 到 _miss 之间插入了
    # 「未启用渠道」整块（约 900 字符），原来的 -700 已够不到（2026-11-06）。
    seg = w[i - 1600:i + 300]
    assert "j.enabled_platforms" in seg, "前端没有读后端下发的清单"
    assert "(CFG||[]).forEach" not in seg, "前端又去读 CFG 了（健康页为 null）"






# ---- merged from tests/test_r632_long_cooldown_is_readable.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

INJECT = (
    "(()=>{const fake={ok:true,quiet:{},cfg:{warmup_platforms:['qunar']},"
    "last_round:{},effect:{},channels:{},recurrences:[],paths:{platforms:{}},"
    "coverage:{ok:[],sent:[]}};"
    "fake.channels.ctrip={state:'cooldown',remain_s:28800,reason:'captcha',"
    "advice:{state:'path_degraded',hint:'',severity:'act'}};"
    "const o=window.fetch;window.fetch=function(u,x){"
    "if(String(u).indexOf('/api/pacing')>=0)"
    "return Promise.resolve(new Response(JSON.stringify(fake),"
    "{status:200,headers:{'Content-Type':'application/json'}}));"
    "return o.apply(this,arguments)};return true})()"
)

READ = ("(()=>{const b=document.getElementById('paceBox');if(!b)return 'NOBOX';"
        "const g=[...b.querySelectorAll('.glip')].map(x=>x.textContent.trim());"
        "return JSON.stringify(g)})()")




def test_short_cooldown_has_units_not_clock_shape():
    """短冷却也要带单位：`15:00` 会被读成时刻（15 点整）。

    r632 第二版：不仅 ≥1 小时，<1 小时也一律带单位。
    18303 行的注释记录过这个歧义——那里宁可绕开本函数改写成
    「N 分钟」，说明 `m:ss` 在冷却语境里确实误导。
    """
    src = webui_full_src()
    i = src.index("function _paceLeft(s){")
    seg = src[i:i + 500]
    assert "3600" in seg and "' 小时'" in seg, (
        "冷却格式化没有按 1 小时分档：%s" % seg[:220])
    assert "' 分'" in seg and "' 秒'" in seg, (
        "分钟/秒档没有单位词：%s" % seg[:220])
    assert "padStart(2,'0')" not in seg, (
        "仍在拼 `m:ss` 时钟形状（会被读成时刻）：%s" % seg[:220])


# ---- merged from tests/test_r657_warmup_hint_names_channels.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

CN = {"qunar": "去哪儿", "fliggy": "飞猪", "ctrip": "携程",
      "tongcheng": "同程", "tuniu": "途牛", "app_zhixing": "智行 App"}


def _bare_tokens(text):
    """提示里没有紧跟 `=中文` 的裸渠道 id。"""
    out = set()
    for pid in CN:
        for m in re.finditer(r"(?<![A-Za-z_])" + pid + r"(?![A-Za-z_])", text):
            tail = text[m.end():m.end() + 1]
            if tail != "=":
                out.add(pid)
    return out


def test_predicate_rejects_old_hint():
    """负控：旧提示「可填：fliggy、qunar、tuniu」必须被判红。"""
    old = "逗号分隔，可填：fliggy、qunar、tuniu；留空=不预热"
    assert _bare_tokens(old) == {"fliggy", "qunar", "tuniu"}, (
        "判据本身失效了：旧文案应当被判为裸 id")
    assert not _bare_tokens(
        "可填：fliggy=飞猪、qunar=去哪儿；留空=不预热"), "判据误伤新文案"












def test_hint_reuses_platCN_not_a_third_name_table():
    src = webui_full_src()
    i = src.index("glcell('预热渠道'")
    # 只截到这一格结束：再往后就是「渠道节奏」那张表，它自带名字是另一件事。
    j = src.index("'text',null,'qunar, fliggy, tuniu')", i)
    seg = src[i:j]
    assert "platCN(" in seg, "预热提示没有走 platCN()，会多出第三份渠道名表"
    assert "qunar:'去哪儿'" not in seg and '"qunar": "去哪儿"' not in seg, (
        "预热提示里又写了一份渠道名表")
    assert "return n===p?p:(p+'='+n)" in seg, (
        "未知渠道要原样输出，不能拼出 `xxx=xxx`（门禁会把未知值当名字）")


# ---- merged from tests/test_r805_modal_aria_label.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _fn_body(src, name):
    i = src.index("function %s(" % name)
    j = src.index("\nfunction ", i + 1)
    return src[i:j]


def test_every_modal_opener_sets_aria_label():
    src = webui_full_src()
    # r1063 T195：双端开窗已泛化为 lgOpenDual(plat)，aria-label 写在它里面；
    # 老入口 lgOpenFliggy 必须仍转发过来（否则有两条开窗路径、只改一条就漏）。
    body = _fn_body(src, "lgOpenDual")
    assert re.search(r"setAttribute\(\s*'aria-label'", body), (
        "lgOpenDual 没写 aria-label：共用容器的可读名称会停在上一个开窗方")
    assert "LG_DUAL" in body, (
        "lgOpenDual 的 aria-label 必须按渠道取（写死一家=切渠道后念错）")
    assert "lgOpenDual('fliggy')" in _fn_body(src, "lgOpenFliggy"), (
        "lgOpenFliggy 应转发到 lgOpenDual，避免两条开窗路径")
    app = _fn_body(src, "appLoginOpen")
    assert re.search(r"setAttribute\(\s*'aria-label'", app), (
        "appLoginOpen 没写 aria-label")
    # App 侧必须是「跟着渠道名」，不能写死一家
    app = _fn_body(src, "appLoginOpen")
    m = re.search(r"setAttribute\(\s*'aria-label'\s*,\s*([^\n;]+)\)", app)
    assert m, "appLoginOpen 没有写 aria-label 的 setAttribute 语句"
    assert "appPlatName(plat)" in m.group(1), (
        "appLoginOpen 的 aria-label 没跟着渠道名走（写死一家=切 App 后念错）：%s"
        % m.group(1).strip())




# ---- merged from tests/test_r805ai_rt_needs_return_dates.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)




# ---- merged from tests/test_r814b_pip_frame_error.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)






