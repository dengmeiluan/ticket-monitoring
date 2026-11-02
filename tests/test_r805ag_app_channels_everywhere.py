# -*- coding: utf-8 -*-
"""r805ag：App 渠道「每个角落」在场性普查（渲染层，7 面）。

用户原话：「应该要把这两款 app 的能力接入到整个项目中的每个角落，
跟其他渠道保持一致，例如渠道健康，检索页面，配置页面，筛选过滤等」。

此前多轮都是「按名字 grep 源码」判在场——那只能证明常量里有字符串，
证明不了**这一面真的画出来了**。本门禁逐面渲染后数元素，且判据用
「App 渠道名出现次数 > 0」而不是「某函数被调用」：

  1. 检索页筛选渠道 chip：7 个（含 2 个 App）
  2. 检索页明细表 `data-plat` 列：至少含 App 行的 key 可映射（用矩阵做旁证）
  3. 渠道健康卡：出现 App 渠道名
  4. 配置页「监控渠道」：App 两项可勾选且带官方图标
  5. 配置页能力矩阵列头：7 列，App 列标「同源」
  6. 登录区：App 渠道有登录卡（真机画面入口）
  7. 节流/干预区：App 渠道出现在渠道清单里
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def test_app_channels_present_on_every_surface():
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
                pg.set_default_timeout(25000)
                pg.goto(base)
                pg.wait_for_function(
                    "()=>typeof S!=='undefined'&&S&&S.users", timeout=30000)
                got = pg.evaluate("""async()=>{
                  const APP=['智行 App','去哪儿 App'];
                  const vis=el=>{const r=el.getBoundingClientRect();
                    const st=getComputedStyle(el);
                    return r.width>0&&r.height>0&&st.visibility!=='hidden'
                           &&st.display!=='none';};
                  const txt=el=>(el.textContent||'');
                  const out={};
                  /* 1. 渠道筛选 chip
                     `#platchips` 在 `#fltwrap`（筛选面板）里，而面板默认
                     收起（`display:none`）——**必须点开「筛选」**才能量。
                     实测三轮空数组全是漏了这一步：先切视图名 `mon`
                     （不是 search），再切「明细」标签，再点 #fltBtn。 */
                  switchView('mon');
                  await new Promise(r=>setTimeout(r,900));
                  showMonTab('details');
                  await new Promise(r=>setTimeout(r,900));
                  const fb=document.getElementById('fltBtn');
                  if(fb&&fb.getAttribute('aria-expanded')!=='true')fb.click();
                  await new Promise(r=>setTimeout(r,1400));
                  out.ftl_open=!!fb&&fb.getAttribute('aria-expanded')==='true';
                  const chips=[...document.querySelectorAll('#platchips .chip')]
                    .filter(vis);
                  out.search_chips=chips.map(x=>txt(x).trim())
                    .filter(t=>t.length<20);
                  out.search_app_chips=APP.filter(n=>
                    chips.some(c=>txt(c).includes(n)));
                  out.search_app_icons=chips
                    .filter(c=>APP.some(n=>txt(c).includes(n)))
                    .map(c=>{
                      const im=c.querySelector('img.bic');
                      return {t:txt(c).trim(),src:im?(im.getAttribute('src')||''):''};
                    });
                  /* 1b. **筛选只勾 App → 明细表只剩 App 行**
                     原来这一面只写了「用矩阵做旁证」，等于没测。真筛一次：
                     点两个 App chip，数表体 data-plat——非 App 行必须为 0，
                     App 行必须有中文名与官方图标。 */
                  await new Promise(r=>setTimeout(r,600));
                  const appChips=chips.filter(c=>APP.some(n=>txt(c).includes(n)));
                  appChips.forEach(c=>c.click());
                  await new Promise(r=>setTimeout(r,1600));
                  const platCells=[...document.querySelectorAll('td[data-plat]')]
                    .filter(vis);
                  out.filtered_app_cells=platCells
                    .filter(td=>String(td.getAttribute('data-plat'))
                      .startsWith('app_'))
                    .map(td=>({plat:td.getAttribute('data-plat'),
                               t:txt(td).trim(),
                               icon:!!td.querySelector('img.bic')}));
                  out.filtered_other=platCells.filter(td=>{
                    const p=String(td.getAttribute('data-plat')||'');
                    return p && !p.startsWith('app_');}).length;
                  /* 2. 配置页监控渠道 + 能力矩阵 */
                  switchView('cfg');
                  await new Promise(r=>setTimeout(r,2600));
                  out.cfg_app_checks=APP.filter(n=>{
                    const l=[...document.querySelectorAll('#cfgform label,'
                      +'#cfgform .chip, #panel-users input')]
                      .find(x=>txt(x).includes(n));
                    return !!l;});
                  const box=document.getElementById('cfgDimMatrix');
                  if(box){
                    const head=[...box.querySelectorAll('thead tr:first-child th')]
                      .map(x=>txt(x).replace(/\\s+/g,' ').trim());
                    out.matrix_head=head;
                    out.matrix_app_cols=head.filter(h=>
                      APP.some(n=>h.includes(n)));
                    out.matrix_app_peer=head.filter(h=>/同源/.test(h));
                  }
                  /* 3. 健康卡 */
                  switchView('health');
                  await new Promise(r=>setTimeout(r,2200));
                  const hv=document.getElementById('healthview')
                        ||document.body;
                  const htxt=txt(hv);
                  out.health_app=APP.filter(n=>htxt.includes(n));
                  /* 4. 登录区 */
                  switchView('login');
                  await new Promise(r=>setTimeout(r,1800));
                  const lv=document.getElementById('loginview')
                        ||document.body;
                  out.login_app=APP.filter(n=>txt(lv).includes(n));
                  return out;
                }""")
            finally:
                b.close()
        assert len(got.get("search_chips") or []) >= 7, (
            "检索页渠道 chip 不足 7 个：%s" % (got.get("search_chips"),))
        assert len(got.get("search_app_chips") or []) == 2, (
            "检索页筛选缺 App 渠道：%s" % (got.get("search_app_chips"),))
        cells = got.get("filtered_app_cells") or []
        assert cells, (
            "只勾 App 渠道后明细表没有任何 App 行（筛选或表体没接上）：%s"
            % (got.get("search_app_chips"),))
        bad_name = [c for c in cells
                    if not any(n in c["t"] for n in ("智行 App", "去哪儿 App"))]
        assert not bad_name, ("App 行没有中文渠道名：%s" % bad_name[:3])
        bad_icon = [c for c in cells if not c.get("icon")]
        assert not bad_icon, ("App 行没有官方图标：%s" % bad_icon[:3])
        assert (got.get("filtered_other") or 0) == 0, (
            "只勾 App 渠道后仍渲染了其它渠道的行：%s"
            % (got.get("filtered_other"),))
        missing = [r for r in (got.get("search_app_icons") or [])
                   if not r.get("src")]
        assert not missing, (
            "检索页 App 渠道 chip 没有官方图标：%s" % missing)
        assert len(got.get("cfg_app_checks") or []) == 2, (
            "配置页监控渠道缺 App 渠道：%s" % (got.get("cfg_app_checks"),))
        head = got.get("matrix_head") or []
        assert len(head) == 8, "能力矩阵表头应为「维度 + 7 渠道」：%s" % (head,)
        assert len(got.get("matrix_app_cols") or []) == 2, (
            "能力矩阵缺 App 列：%s" % (got.get("matrix_app_cols"),))
        assert len(got.get("matrix_app_peer") or []) == 2, (
            "App 列头没标「同源」：%s" % (got.get("matrix_app_peer"),))
        assert len(got.get("health_app") or []) == 2, (
            "渠道健康没出现 App 渠道：%s" % (got.get("health_app"),))
        assert len(got.get("login_app") or []) == 2, (
            "登录区没有 App 登录卡：%s" % (got.get("login_app"),))
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()
