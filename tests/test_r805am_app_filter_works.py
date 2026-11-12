# -*- coding: utf-8 -*-
"""r805am：App 渠道的**筛选过滤**必须真的筛出 App 的行。

此前只验证过「筛选 chip 里存在 App 渠道」（`test_r805ag`），那是「控件在不在」。
用户要的是「筛选过滤和其他渠道一致」——控件在、点了没效果同样是缺陷。

判据（三层，全部在真实数据上跑）：
  1. chip 可点（不是 disabled）；
  2. 只选 App 时，剩余行**全部**属于该 App，且行数 > 0
     （空集冒充成功是最常见的假绿）；
  3. 取消筛选后行数回到基准（筛选可逆，不是单向粘死）。

**demo 原生就有 App 价格行**（实测 2026-11-01：268 行里智行 App 37 /
去哪儿 App 37）——旧笔记「demo 没有 App 行」已过时。再按那个前提去注入
反而会污染状态：注入后 `flights` 与 `platAge` 不同源，`buildChips` 的
keep 回填会留下「已选中但控件已消失」的中间态，实测混进 2 条 ctrip 行。
**结论：不要注入，用原生数据；并在开头断言锚点存在。**
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def test_app_channel_filter_actually_filters():
    import pytest

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
        for _ in range(160):
            try:
                op.open(base + "/api/state", timeout=1)
                break
            except Exception:
                time.sleep(0.25)
        else:
            pytest.skip("演示服务未在期限内起来")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            if not os.path.exists(pw.chromium.executable_path):
                pytest.skip("chromium 二进制缺失")
            b = pw.chromium.launch()
            try:
                pg = b.new_page(viewport={"width": 1512, "height": 1100})
                errs = []
                pg.on("pageerror", lambda e: errs.append(str(e)))
                pg.set_default_timeout(25000)
                pg.goto(base)
                pg.wait_for_function(
                    "()=>typeof S!=='undefined'&&S&&S.users", timeout=30000)
                native = pg.evaluate("""()=>{
                  const u=S.users[U];
                  const plats={};
                  u.flights.forEach(f=>{plats[f.plat]=(plats[f.plat]||0)+1;});
                  return {n:u.flights.length, app:(plats['智行 App']||0)};
                }""")
                assert native["app"] > 0, (
                    "demo 数据里没有「智行 App」行（%s），本判据无从验证"
                    % native)

                pg.evaluate("()=>showMonTab('details',false)")
                pg.wait_for_timeout(1500)
                pg.evaluate(
                    "()=>{const f=document.getElementById('fltBtn');"
                    "if(f&&f.getAttribute('aria-expanded')!=='true')f.click();}")
                pg.wait_for_timeout(1200)

                info = pg.evaluate("""()=>{
                  const chips=[...document.querySelectorAll('#platchips .chip')];
                  const app=chips.find(c=>(c.dataset.p||'').includes('智行'));
                  const rows=[...document.querySelectorAll('#ftable tbody tr')]
                    .filter(tr=>tr.querySelector('td[data-plat]'));
                  return {hasApp:!!app, disabled:app?!!app.disabled:null,
                          baseRows:rows.length};
                }""")
                assert info["hasApp"], "渠道筛选里没有「智行 App」chip"
                assert not info["disabled"], "「智行 App」chip 是 disabled，点不了"
                assert info["baseRows"] > 0, "基准行数为 0，本判据失去锚点"

                # 只选 App
                pg.evaluate("""()=>{
                  [...document.querySelectorAll('#platchips .chip')]
                    .forEach(c=>{if(c.classList.contains('on'))c.click();});
                  const app=[...document.querySelectorAll('#platchips .chip')]
                    .find(c=>(c.dataset.p||'').includes('智行'));
                  app.click();
                }""")
                # 表格是**分片异步**渲染：旧分片里的别家行会被逐步替换，
                # 实测 0.8s/2s/4s 都可能还残留 2 条 ctrip（是渲染中间态，
                # 不是筛选漏网——纯函数 filteredRows() 当场就只有 App 行）。
                # 因此这里等「DOM 稳定」：连续两次采样结果一致再判。
                def _snap():
                    return pg.evaluate("""()=>{
                      const trs=[...document.querySelectorAll('#ftable tbody tr')]
                        .filter(tr=>tr.querySelector('td[data-plat]'));
                      const plats={};
                      trs.forEach(tr=>{const k=tr.querySelector('td[data-plat]')
                        .getAttribute('data-plat');plats[k]=(plats[k]||0)+1;});
                      return {rows:trs.length, plats:plats};
                    }""")
                prev, after = None, _snap()
                for _ in range(12):
                    if prev is not None and prev == after:
                        break
                    pg.wait_for_timeout(600)
                    prev, after = after, _snap()
                # 纯函数口径（不经过渲染）：筛选谓词必须只放行 App 行
                pure = pg.evaluate("""()=>{
                  const fr=filteredRows();
                  return {n:fr.length,
                          odd:fr.filter(f=>f.plat!=='智行 App')
                                .map(f=>String(f.plat)).slice(0,5)};
                }""")
                assert pure["n"] > 0, (
                    "filteredRows() 在只选智行 App 时返回 0 行——筛选没生效")
                assert pure["odd"] == [], (
                    "筛选谓词放行了别家渠道：%s" % pure["odd"])
                assert after["rows"] > 0, (
                    "选中智行 App 后表格 0 行——渲染没跟上筛选（空集不是成功）")
                assert after["rows"] <= pure["n"], (
                    "表格行数(%d)超过筛选结果(%d)——渲染残留旧行"
                    % (after["rows"], pure["n"]))
                assert set(after["plats"]) == {"app_zhixing"}, (
                    "渲染后混进了别的渠道：%s（纯谓词口径 %s）"
                    % (after["plats"], pure))

                # 恢复
                pg.evaluate("""()=>{
                  [...document.querySelectorAll('#platchips .chip')]
                    .forEach(c=>{if(!c.classList.contains('on')&&!c.disabled)
                      c.click();});
                }""")
                pg.wait_for_timeout(1800)
                back = pg.evaluate(
                    "()=>[...document.querySelectorAll('#ftable tbody tr')]"
                    ".filter(tr=>tr.querySelector('td[data-plat]')).length")
            finally:
                b.close()
        assert not errs, "页面报错：%s" % errs[:3]
        assert back == info["baseRows"], (
            "取消筛选后没回到基准行数（筛选单向后粘死）：%d != %d"
            % (back, info["baseRows"]))
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()
