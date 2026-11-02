# -*- coding: utf-8 -*-
r"""r658：采集通路在界面上一律中文，别再让读者读 `android-runtime`。

账本 `fetch_paths.entry_path` 是各 crawler 自己写的字面量：浏览器渠道
大多是中文（日历 / H5 / PC / 窗历 / 往返 / H5·API），App 渠道是英文 id
（app-list / android-runtime / snap-restore …）。健康卡的「分通路」小标
把键名直接拼进句子，App 渠道整行就成了：

    智行 App 60%
    app-list 单次 80%（5 次） · android-runtime 无有效样本（63 次）

读者读不出这是「设航线 / 航班列表 / 模拟器运行时」里的哪一步。

判据分三层：
① 单源：core/channels.PATH_CN 覆盖源码里 **每一处** path_note() 的字面量
   （扫 crawlers 源码对账，新增通路漏登记就红）—— 名字不许在两边各写一份；
② 真渲染：健康卡拿到 App 通路载荷后，分通路小标里不出现裸 id；
③ 行为负控：把 pathCN 换成恒等函数（旧行为等价物）再渲染，同一判据必须红。

另有一条后端判据：core.pacing 的路径劣化提示同样走 path_cn()。
"""
import io
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 账本里出现过的、不是中文的通路 id（中文那些本来就能读，不必进表）
LATIN_IDS = ("app-list", "app-route", "app-blocker", "app-dump",
             "app-error", "android-runtime", "android-device",
             "snap-restore")


def _src(rel):
    return io.open(os.path.join(ROOT, rel), encoding="utf-8",
                   newline="").read()


def test_every_literal_path_note_has_a_display_name():
    """源码里 path_note("xxx") 的字面量，个个都要在 PATH_CN 里。

    这是「加通路必漏登记」的守门人：crawler 里新写一条通路名，界面就会
    退回裸 id，而没有任何测试会红——除非有这一条。
    """
    from core.channels import PATH_CN
    seen = set()
    for fn in os.listdir(os.path.join(ROOT, "crawlers")):
        if not fn.endswith(".py"):
            continue
        src = _src(os.path.join("crawlers", fn))
        # 只看真正的调用；注释里提到别的通路名不算
        for m in re.finditer(r"path_note\(\s*\"([^\"]+)\"", src):
            seen.add(m.group(1))
    assert seen, "没扫到任何 path_note 字面量，判据本身失效了"
    missing = sorted(p for p in seen if p not in PATH_CN)
    assert not missing, (
        "这些通路在界面上没有中文名（健康卡会打出裸 id）：%s\n"
        "在 core/channels.py 的 PATH_CN 里补上。" % missing)


def test_no_latin_path_id_is_left_nameless():
    """英文 id 必须全部有名字（中文通路名不进表也能读，放宽）。"""
    from core.channels import PATH_CN
    missing = [p for p in LATIN_IDS if p not in PATH_CN]
    assert not missing, "英文通路 id 没有中文名：%s" % missing
    for p in LATIN_IDS:
        assert PATH_CN[p] != p, "%s 的「中文名」就是它自己" % p


def test_unknown_path_falls_back_to_raw_key():
    """未知通路原样返回 —— 宁缺勿错，不编造名字。"""
    from core.channels import path_cn
    assert path_cn("未来新通路") == "未来新通路"


def test_pacing_hints_use_the_display_name():
    """后端提示也要用中文名（它同样会出现在节流行上）。"""
    src = _src("core/pacing.py")
    assert "path_cn(" in src, "core/pacing 没有接 path_cn，提示仍是裸 id"
    assert "_shown = path_cn(_name)" in src
    # 提示里不许再用原始键名
    assert "% (_dom, _name," not in src, (
        "还有提示仍在拼原始通路键名")


def _render(payload, identity_names=False):
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
                pg = b.new_page(viewport={"width": 1440, "height": 1400})
                pg.set_default_timeout(20000)
                pg.add_init_script("window.setInterval=()=>1;")
                pg.goto(base)
                pg.wait_for_function(
                    "typeof S!=='undefined'&&S&&S.users", timeout=30000)
                pg.evaluate("""()=>{try{switchView('mon')}catch(e){}
                  try{showMonTab&&showMonTab('health',true)}catch(e){}}""")
                pg.wait_for_timeout(1200)
                if identity_names:
                    pg.evaluate("()=>{window.pathCN=function(k){return k;};}")
                return pg.evaluate("""(j)=>{
                  renderHealth(j);
                  const hb=document.getElementById('hbody');
                  const p=hb&&hb.querySelector('.hpath');
                  return p?p.innerText:'';}""", payload)
            finally:
                b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()


def _app_payload():
    return {
        "rounds": [{"ts": "10-30 0%d:00" % i,
                    "plats": {"app_zhixing": {"s": "ok", "ok": 3, "tot": 3,
                                              "cal": 0, "detail": 3}}}
                   for i in range(4)],
        "stats": {"app_zhixing": {"ok": 3, "part": 1, "fail": 1, "rate": 0.6,
                                  "cal": 0, "detail": 3, "auth": 0,
                                  "maint": 0}},
        "paths": {"app_zhixing": {
            "scopes": {}, "retired": [],
            "paths": {
                "app-list": {"attempts": 5, "ok": 4, "rate": 0.8,
                             "rate_excl_empty": 0.8, "login": 0, "soft": 0,
                             "empty": 0, "unsupported": 0},
                "android-runtime": {"attempts": 63, "ok": 0, "rate": 0,
                                    "rate_excl_empty": None, "login": 0,
                                    "soft": 0, "empty": 0, "unsupported": 63},
                "snap-restore": {"attempts": 2, "ok": 1, "rate": 0.5,
                                 "rate_excl_empty": 0.5, "login": 1,
                                 "soft": 0, "empty": 0, "unsupported": 0}}}},
        "by_scope": {},
        "enabled_platforms": ["app_zhixing"],
        "push": {"channels": {}},
    }


def _bare(text):
    return sorted({p for p in LATIN_IDS
                   if re.search(r"(?<![A-Za-z_-])" + re.escape(p)
                                + r"(?![A-Za-z_-])", text)})


def test_path_chip_renders_chinese_names():
    txt = _render(_app_payload())
    assert txt, "分通路小标没渲染出来，判据无从生效"
    bare = _bare(txt)
    assert not bare, "分通路小标里还有英文通路 id：%s（实测 %r）" % (bare, txt)
    for want in ("App 航班列表", "模拟器运行时", "登录态快照恢复"):
        assert want in txt, "缺少中文通路名 %s：%r" % (want, txt)


def test_render_negative_control_turns_the_gate_red():
    """负控：pathCN 换成恒等函数（旧行为的等价物）后，同一判据必须红。"""
    txt = _render(_app_payload(), identity_names=True)
    assert txt, "负控没渲染出小标"
    assert _bare(txt), (
        "负控没有红：换回恒等名字函数后仍是中文（%r），判据测不到东西" % txt)


def test_page_injects_the_single_source_table():
    """名字表由服务端注入，前端不许另抄一份。"""
    import webui
    html = webui._page_html("r658t")
    assert "__PATH_CN__" not in html, "PATH_CN 占位符没被替换"
    assert "function pathCN(k)" in html, "页面里没有通路名解析函数"
    from core.channels import PATH_CN
    for k in LATIN_IDS:
        assert ('"%s": "%s"' % (k, PATH_CN[k])) in html, (
            "页面里没有 %s 的名字，注入表与实际表不一致" % k)
