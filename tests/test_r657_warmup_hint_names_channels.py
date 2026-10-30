# -*- coding: utf-8 -*-
r"""r657：预热渠道的提示要用中文名，别让用户在英文 id 和中文标签之间猜。

这一格填的是**渠道标识**（后端 `_warmable()` 只认 id），所以输入框里
必须是 `fliggy` 这种写法。但提示原先直接列「可填：fliggy、qunar、tuniu」——
同一行左边是中文标签「预热渠道」，右边一列英文 id，用户不知道 fliggy
就是飞猪，填错一个字母就被静默丢弃（`warmup_platforms` 过滤掉不认识的值）。

判据（真渲染）：提示里每个可预热渠道都写成 `id=中文名`，且不再出现
「孤零零的英文 id」。另有静态判据：提示不得自带第三份名字表，必须走
`platCN()`（SRX_PLATS + APP_PLAT_NAME 的单一入口）。
负控在 `test_predicate_rejects_old_hint`：同一判据套在旧文案上必须报红。
"""
import os
import re
import sys

import pytest

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


@pytest.fixture(scope="module")
def rendered():
    import socket
    import subprocess
    import time
    import urllib.request

    from playwright.sync_api import sync_playwright

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    srv = subprocess.Popen(
        [sys.executable, "webui.py", "--demo", "--port", str(port)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, env=env)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = "http://127.0.0.1:%d" % port
    try:
        up = False
        for _ in range(160):
            try:
                op.open(base + "/api/state", timeout=1)
                up = True
                break
            except Exception:
                time.sleep(0.25)
        if not up:
            pytest.skip("演示服务未在期限内起来")
        with sync_playwright() as pw:
            if not os.path.exists(pw.chromium.executable_path):
                pytest.skip("chromium 二进制缺失")
            b = pw.chromium.launch()
            try:
                pg = b.new_page(viewport={"width": 1440, "height": 1200})
                pg.set_default_timeout(20000)
                pg.add_init_script("window.setInterval=()=>1;")
                pg.goto(base)
                pg.wait_for_function(
                    "typeof S!=='undefined'&&S&&S.users", timeout=30000)
                pg.evaluate("()=>{switchView('cfg')}")
                pg.wait_for_timeout(1500)
                pg.evaluate("""()=>{const c=document.querySelector(
                  '#cfgnav .cnav[data-p="pacing"]');if(c)c.click()}""")
                pg.wait_for_timeout(1000)
                out = pg.evaluate(r"""()=>{
                  const box=document.getElementById('glbWarmP');
                  const cell=box&&box.closest('.glcell');
                  const hint=cell&&cell.querySelector('.gsub');
                  const r=hint?hint.getBoundingClientRect():null;
                  return {hint:hint?(hint.innerText||''):'',
                          w:r?r.width:0, sw:hint?hint.scrollWidth:0,
                          warmable:(window.GLB&&GLB.warmable)||[],
                          platCN:[platCN('fliggy'),platCN('app_zhixing')]};}""")
                # 有被忽略的渠道时的分支：改 GLB 后重渲染
                out["ignored"] = pg.evaluate(r"""()=>{
                  GLB.warmup_ignored=['ctrip','qunar'];
                  buildForm();
                  const box=document.getElementById('glbWarmP');
                  const cell=box&&box.closest('.glcell');
                  const hint=cell&&cell.querySelector('.gsub');
                  const t=hint?(hint.innerText||''):'';
                  return t;}""")
                # 窄档：390px 下提示不许横向溢出
                pg.set_viewport_size({"width": 390, "height": 900})
                pg.wait_for_timeout(600)
                out["narrow"] = pg.evaluate(r"""()=>{
                  const box=document.getElementById('glbWarmP');
                  const cell=box&&box.closest('.glcell');
                  const hint=cell&&cell.querySelector('.gsub');
                  if(!hint)return null;
                  const r=hint.getBoundingClientRect();
                  return {w:r.width,sw:hint.scrollWidth,
                          doc:document.documentElement.scrollWidth};}""")
                # 行为负控：把名字解析换回「原样返回」，走同一条渲染路径。
                # 不改 webui.py（有并行会话在改），只在页面里替换函数。
                out["negHint"] = pg.evaluate(r"""()=>{
                  GLB.warmup_ignored=[];
                  window.platCN=function(p){return p;};
                  buildForm();
                  const box=document.getElementById('glbWarmP');
                  const cell=box&&box.closest('.glcell');
                  const hint=cell&&cell.querySelector('.gsub');
                  return hint?(hint.innerText||''):'';}""")
                return out
            finally:
                b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()


def test_hint_names_every_channel_in_chinese(rendered):
    hint = rendered["hint"]
    assert hint, "预热渠道这一格没有提示文案"
    bare = _bare_tokens(hint)
    assert not bare, "提示里还有裸的英文渠道 id，用户认不出是哪家：%r（%r）" % (
        sorted(bare), hint)
    for pid in rendered["warmable"]:
        name = CN.get(pid)
        assert name, "门禁自己的名字表缺 %s" % pid
        assert pid + "=" + name in hint, (
            "可预热渠道 %s 没写成 `%s=%s`：%r" % (pid, pid, name, hint))


def test_hint_fits_without_horizontal_overflow(rendered):
    assert rendered["w"] > 0, "提示元素宽度为 0，量不到溢出"
    assert rendered["sw"] <= rendered["w"] + 1, (
        "提示横向溢出：scrollWidth %s > width %s"
        % (rendered["sw"], rendered["w"]))
    nar = rendered["narrow"]
    assert nar and nar["w"] > 0, "窄档下提示元素量不到尺寸"
    assert nar["sw"] <= nar["w"] + 1, (
        "390px 档提示横向溢出：%s > %s" % (nar["sw"], nar["w"]))


def test_ignored_branch_also_uses_chinese_names(rendered):
    t = rendered["ignored"]
    assert "⚠" in t, "填了没有入口的渠道要给出警示，实测：%r" % t
    assert "ctrip=携程" in t, "被忽略的渠道也是英文 id：%r" % t
    assert not _bare_tokens(t), "警示分支里仍有裸 id：%r" % t


def test_render_negative_control_turns_the_gate_red(rendered):
    """负控：把 platCN 换成恒等函数（旧行为的等价物），同一判据必须报红。

    这一步证明 `test_hint_names_every_channel_in_chinese` 真的能抓住
    「英文 id 上屏」，而不是永远为真——不碰 webui.py，页面内替换即可。
    """
    neg = rendered["negHint"]
    assert neg, "负控没渲染出提示，判据无从生效"
    assert _bare_tokens(neg), (
        "负控没有红：换回恒等名字函数后提示仍是中文（%r），"
        "说明这条判据测不到东西" % neg)


def test_hint_reuses_platCN_not_a_third_name_table():
    src = open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
               newline="").read()
    i = src.index("glcell('预热渠道'")
    # 只截到这一格结束：再往后就是「渠道节奏」那张表，它自带名字是另一件事。
    j = src.index("'text',null,'qunar, fliggy, tuniu')", i)
    seg = src[i:j]
    assert "platCN(" in seg, "预热提示没有走 platCN()，会多出第三份渠道名表"
    assert "qunar:'去哪儿'" not in seg and '"qunar": "去哪儿"' not in seg, (
        "预热提示里又写了一份渠道名表")
    assert "return n===p?p:(p+'='+n)" in seg, (
        "未知渠道要原样输出，不能拼出 `xxx=xxx`（门禁会把未知值当名字）")
