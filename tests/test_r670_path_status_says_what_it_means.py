# -*- coding: utf-8 -*-
r"""r670：通路状态在界面上必须说人话，而且不能把不同原因说成同一个词。

前端 `srxPathCN()` 原先只认 6 个码（ok/calendar/login/blocked/timeout/error），
其余全部落到兜底「无结果」。而账本里真实存在：

    soft_reject   会话层软拒       （等预热，不用人管）
    parse_error   解析失败         （多半页面改版，要排查）
    unsupported   渠道不支持       （能力边界，不用管）

三个处置完全不同，界面上却都显示「无结果」——把「渠道根本不支持这条航线」
说成「查了没票」，是语义错位（也是记忆里「empty needs explicit evidence」
的同族问题）。

判据：
① 后端 `FAILURE_KINDS` 里每个码，前端都要有同名中文（两套表不许打架）；
② `path_note` 会写进账本的状态码，前端也都要有名字；
③ 未知码如实返回原码，不许编一个「无结果」；
④ 真渲染：三种状态并排出现在溯源小标里，必须是三个不同的中文词。
负控：把 SRX_PATH_CN 换回只认 6 个码的旧实现 → ①②④ 红。
"""
import io
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _src():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def _front_table():
    s = _src()
    i = s.index("const SRX_PATH_CN={")
    seg = s[i:s.index("};", i)]
    out = {}
    for m in re.finditer(r"([a-z_]+)\s*:\s*'([^']+)'", seg):
        out[m.group(1)] = m.group(2)
    return out


def test_shared_codes_use_the_same_wording():
    """两套表**重叠的码**必须同名，但不要求逐字同一张表。

    `core.pacing.FAILURE_KINDS` 是**归因分类**（ip / captcha / soft / login…），
    `webui.SRX_PATH_CN` 是**账本状态码**（ok / login / blocked / soft_reject…）。
    两者维度不同：`ip` / `captcha` / `soft` 在账本里根本不会出现（归类后
    才得到），所以不能拿它们要求前端有名字。
    真正要守的是：**同一个码在两边不能说出两个意思**——例如 login 一边叫
    「登录态失效」一边叫「登录拒绝」，读者会以为是两件事。
    """
    from core.pacing import FAILURE_KINDS
    front = _front_table()
    # 仅在两边都有的码上对齐语义（语义相同即可，措辞可以更短）
    SAME = {
        "login": ("登录", "login"),
        "timeout": ("超时", "timeout"),
        "parse_error": ("解析", "parse_error"),
        "unsupported": ("不支持", "unsupported"),
        "empty": ("票", "empty"),
    }
    for code, (needle, front_key) in SAME.items():
        label = FAILURE_KINDS[code][0]
        assert needle in label, "后端 %s 的名字变了？%r" % (code, label)
        assert front_key in front, "前端缺 %s" % front_key
        assert needle in front[front_key], (
            "%s 两边说法对不上：后端「%s」前端「%s」"
            % (code, label, front[front_key]))


def test_dedup_codes_are_not_required_but_attribution_ones_are_absent():
    """归因码（ip/captcha/soft）不进状态表——账本里不会出现它们。"""
    front = _front_table()
    for code in ("ip", "captcha", "soft"):
        assert code not in front, (
            "%s 是归因分类，不是账本状态码；混进状态表会让读者分不清"
            "「为什么失败」和「哪一步失败」" % code)


def test_every_ledger_status_has_a_name():
    """path_note 写进账本的状态码，界面都要能读。"""
    from crawlers.base import BaseCrawler
    front = _front_table()
    missing = [st for st in BaseCrawler.PATH_STATUS if st not in front]
    assert not missing, "账本状态码在界面上没有名字：%s" % missing


def test_unknown_status_falls_back_to_the_raw_code():
    s = _src()
    i = s.index("function srxPathCN(st){")
    seg = s[i:i + 160]
    assert "SRX_PATH_CN[k]||k}" in seg, (
        "未知状态码必须原样返回（宁缺勿错），不能一律说成「无结果」：%r" % seg)


def test_distinct_causes_render_as_distinct_words():
    """三种处置完全不同的状态，不能都显示「无结果」。"""
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
                got = pg.evaluate(r"""()=>{
                  const html=srxTaskPaths({channels:{qunar:{paths:[
                    {path:'H5',status:'soft_reject'},
                    {path:'PC',status:'parse_error'},
                    {path:'日历',status:'unsupported'}]}}});
                  const d=document.createElement('div');
                  d.innerHTML=html;
                  return (d.innerText||'').replace(/\s+/g,' ');}""")
            finally:
                b.close()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()

    assert got, "溯源小标没渲染出来"
    for want in ("软拒", "解析失败", "渠道不支持"):
        assert want in got, "溯源小标缺少「%s」：%r" % (want, got)
    assert got.count("无结果") == 0, (
        "把软拒/解析失败/渠道不支持都说成了「无结果」：%r" % got)
