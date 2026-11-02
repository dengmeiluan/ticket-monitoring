# -*- coding: utf-8 -*-
"""r805af：渠道图标「官方图标」必须 7/7 可达，且经中文名也回得去。

用户原话要求「保持使用官方渠道图标作为精致质感的标准」。实测发现的缺陷：
`srxPlatKey` 原是一张**只列 5 家浏览器渠道**的写死中文名表，而两个 App
渠道的行数据 `f.plat` 本来就是中文名（「智行 App」「去哪儿 App」）——
查不到 → `srxPlatKey` 返回 `''` → `srxPlatIcon('')` 拿不到 `SRX_BRAND_IMG`
→ App 明细行与同班链路里**没有官方图标**。

判据三层：
  1. 源层：`SRX_BRAND_IMG` 必须覆盖 `SRX_PLATS` 的每一个 id（有图可画）；
  2. 映射层：每个 id 与它的中文名都必须映射回同一个 key（不能只认 id）；
  3. 渲染层：真浏览器里逐个调 `srxPlatIcon`，量出 `<img>` 的 src 非空，
     且 App 渠道的图标与对应浏览器渠道**不是同一张图**（同源不等于同图标，
     拿携程的图冒充智行是「看起来有图标」的假绿）。
"""
import io
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _plats():
    src = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    i = src.find("const SRX_PLATS=")
    assert i > 0, "SRX_PLATS 锚点失效"
    seg = src[i:src.find("};", i)]
    ids = re.findall(r"([A-Za-z_][A-Za-z0-9_]*):\[", seg)
    return ids


def test_every_platform_has_official_icon():
    src = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    ids = _plats()
    assert len(ids) == 10, "渠道数变了：%s（改声明时同步改本判据）" % ids
    # App 与同品牌浏览器渠道可共用一张官方图（SRX_BRAND_ALIAS）。
    m = re.search(r"const SRX_BRAND_ALIAS=\{([^}]*)\}", src)
    aliases = dict(re.findall(r"([a-z_]+)\s*:\s*'([a-z_]+)'",
                              m.group(1) if m else ""))
    for p in ids:
        key = p if re.search(r'"%s":"data:image' % re.escape(p), src) \
            else aliases.get(p)
        assert key and re.search(r'"%s":"data:image' % re.escape(key or ""),
                                 src), (
            "%s 没有官方图标（SRX_BRAND_IMG 缺这个 key，也无别名）——"
            "用户要求全站渠道都带官方图标" % p)


def test_frontend_has_no_second_name_table():
    src = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8").read()
    i = src.find("function srxPlatKey")
    assert i > 0, "srxPlatKey 锚点失效"
    body = src[i:src.index("\n}", i)]
    assert "SRX_PLATS" in body, (
        "srxPlatKey 没有从 SRX_PLATS 派生——回到写死表就又漏 App 渠道")
    assert "const m={'去哪儿'" not in body, (
        "srxPlatKey 里仍有第二份中文名表")
    # 全仓扫描：任何「中文渠道名 → id」的写死表都只会有 5 家浏览器渠道，
    # 加第三个 App 渠道时必然漏。实测已清掉三处（srxPlatKey / buildChips
    # 的 PK / KPI 胶囊的 PKEY），这条防它们以别的变量名长回来。
    import re as _re
    pat = _re.compile(r"\{[^{}\n]*?'去哪儿'\s*:[^{}\n]*?\}")
    hits = []
    for m in pat.finditer(src):
        s = m.group(0)
        if s.count(":") >= 5 and "SRX_PLATS" not in s:
            hits.append(src[:m.start()].count("\n") + 1)
    assert not hits, (
        "又有写死的「中文渠道名→id」表（%s 行）：只列 5 家，App 渠道"
        "会丢图标——改走 srxPlatKey" % hits)


def test_name_and_id_resolve_to_same_key_and_icon():
    """渲染层：真浏览器里量映射结果与 <img> 的真实 src。"""
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
                pg = b.new_page(viewport={"width": 1440, "height": 1100})
                pg.set_default_timeout(25000)
                pg.goto(base)
                pg.wait_for_function(
                    "()=>typeof S!=='undefined'&&S&&S.users", timeout=30000)
                got = pg.evaluate("""()=>{
                  const rows=[];
                  for(const id in SRX_PLATS){
                    const nm=SRX_PLATS[id][0];
                    const byId=srxPlatKey(id);
                    const byName=srxPlatKey(nm);
                    const html=srxPlatIcon(id);
                    const m=/src="([^"]*)"/.exec(html);
                    rows.push({id:id,name:nm,byId:byId,byName:byName,
                               src:m?m[1]:'',html:html});
                  }
                  return rows;
                }""")
            finally:
                b.close()
        assert len(got) == 10, "渠道数变了：%d" % len(got)
        bad = [r for r in got if r["byId"] != r["id"]]
        assert not bad, "id 映射不回自己：%s" % bad
        bad2 = [r for r in got if r["byName"] != r["id"]]
        assert not bad2, (
            "中文名映射不到 id（图标会丢）：%s"
            % [(r["name"], r["byName"]) for r in bad2])
        bad3 = [r for r in got if not r["src"]]
        assert not bad3, "这些渠道渲染出空图标：%s" % [r["id"] for r in bad3]
        # 图标可否共用，取决于**品牌事实**而不是「看起来有图标」：
        #   去哪儿 App 与去哪儿是同一品牌 → 共用官方标识是对的；
        #   智行 App 与携程是不同品牌 → 必须各用各的（拿携程图冒充
        #   智行就是假绿）。所以只允许「同源对」共用。
        from core.channels import APP_BROWSER_PEER
        same_brand = {frozenset((a, b))
                      for a, b in APP_BROWSER_PEER.items()}
        seen = {}
        for r in got:
            prev = seen.get(r["src"])
            if prev and frozenset((prev, r["id"])) not in same_brand:
                raise AssertionError(
                    "%s 与 %s 用了同一张图标，但不是同一品牌——"
                    "把别家的图当成官方图标" % (r["id"], prev))
            seen.setdefault(r["src"], r["id"])
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()


def test_no_visible_channel_name_without_official_icon_anywhere():
    """全站普查：可见的渠道中文名，祖先链里必须有官方图标。

    用户要求「官方渠道图标作为精致质感的标准，继续扫盲统一」。此前只按
    *命名的表面*逐个断言（矩阵表头、筛选 chip、健康卡、登录卡…），
    那是「列清单」——新加一个表面不会被覆盖。这里换成**普查**：遍历
    三个视图 × 监控全部六个标签页 + 配置四个分区，找出所有可见叶子，
    凡含渠道中文名而祖先链无 `img.bic` 的全部记下。

    2026-11-01 实测 12 个面合计 **0 处**。负控已验：注入一个
    `<div>携程 裸名字测试</div>` 后判据立刻命中该元素——「0」不是判据
    没跑，是确实没有裸名字。
    """
    import socket
    import subprocess
    import time
    import urllib.request

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
    CENSUS = r"""() => {
      const NAMES=['携程','去哪儿','飞猪','同程','途牛','智行 App','去哪儿 App',
                   '飞猪 App','携程 App','同程 App'];
      const vis=el=>{const r=el.getBoundingClientRect();
        if(r.width<=0||r.height<=0)return false;
        const st=getComputedStyle(el);
        return st.visibility!=='hidden'&&st.display!=='none'&&st.opacity!=='0';};
      /* 判据两级：
         ① **裸名字**：可见叶子含渠道中文名，而整条祖先链里没有任何
            `img.bic` —— 这是「这个渠道名根本没有图标」。
         ② **张冠李戴**：文字恰好等于某渠道名时，**直接父级**里若已有
            图标，那个图标必须就是该渠道的（防止「携程」旁边挂着去哪儿的
            图）。只看父级是为了可归因：扫描整页再按标签页归面会把别的
            可见区域算到当前面头上（实测误报过 specials）。
         名字匹配**最长优先**：「去哪儿 App」里含「去哪儿」，先匹配短的
         会把 App 判成浏览器渠道。原生 `<option>` 放不了图片，跳过。 */
      const byLen=[...NAMES].sort((a,b)=>b.length-a.length);
      const keyOf=(name)=>{
        for(const k in SRX_PLATS){
          if(SRX_PLATS[k]&&SRX_PLATS[k][0]===name)return k;
        }
        return '';
      };
      const hits=[];
      for(const el of document.querySelectorAll('body *')){
        if(el.children.length)continue;
        if(el.tagName==='OPTION')continue;
        if(!vis(el))continue;
        const t=(el.textContent||'').trim();
        if(!t||t.length>40)continue;
        const hit=byLen.find(n=>t.includes(n));
        if(!hit)continue;
        const want=keyOf(hit);
        let im=null;
        for(let p=el;p&&p!==document.body;p=p.parentElement){
          const cand=p.querySelector&&p.querySelector('img.bic');
          if(cand){im=cand;break}
        }
        if(!im){
          hits.push({name:hit,text:t.slice(0,30),got:'(无图标)',
                     cls:(el.className||'').toString().slice(0,40)});
          continue;
        }
        if(t===hit){
          const par=el.parentElement;
          const pim=par&&par.querySelector&&par.querySelector('img.bic');
          const got=pim?(pim.getAttribute('data-plat')||''):'';
          if(pim&&got!==want){
            hits.push({name:hit,text:t.slice(0,30),got:got||'(空)',
                       cls:(el.className||'').toString().slice(0,40)});
          }
        }
      }
      const seen=new Set();const out=[];
      for(const h of hits){const k=h.name+'|'+h.text+'|'+h.cls+'|'+h.got;
        if(seen.has(k))continue;seen.add(k);out.push(h);}
      return out;
    }"""
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
                report = {}
                det_rows = [0]
                for view in ("mon", "search", "cfg"):
                    pg.evaluate("v=>switchView(v)", view)
                    pg.wait_for_timeout(1500)
                    tabs = (["overview", "specials", "trend", "watch",
                             "details", "health"] if view == "mon" else [None])
                    for t in tabs:
                        if t:
                            # 必须**非 silent**：silent 会跳过表体重建，明细
                            # 页只剩「加载中…」骨架，普查扫到的就是 0 行假空。
                            pg.evaluate("t=>showMonTab(t,false)", t)
                            pg.wait_for_timeout(1200)
                        key = view + ("/" + t if t else "")
                        if key == "mon/details":
                            # 明细是分片异步渲染（2s/4s 仍是骨架，8s 才出
                            # 240 行）；等真实行出现再扫。
                            try:
                                pg.wait_for_function(
                                    "()=>{const tb=document.querySelector("
                                    "'#ftable tbody');return tb&&tb"
                                    ".querySelectorAll('tr').length>5;}",
                                    timeout=25000)
                                pg.wait_for_timeout(400)
                            except Exception:
                                pass
                            det_rows[0] = pg.evaluate(
                                "()=>{const tb=document.querySelector("
                                "'#ftable tbody');"
                                "return tb?tb.querySelectorAll('tr').length:0;}")
                        report[key] = pg.evaluate(CENSUS)
                for panel in ("users", "globals", "login", "pacing"):
                    try:
                        pg.evaluate("p=>showCfgPanel(p)", panel)
                        pg.wait_for_timeout(1200)
                        report["cfg/" + panel] = pg.evaluate(CENSUS)
                    except Exception:
                        pass
            finally:
                b.close()
        bad = {k: v for k, v in report.items() if v}
        assert len(report) >= 12, (
            "只扫到 %d 个面，普查覆盖面不足：%s" % (len(report), sorted(report)))
        # 覆盖面自证：明细页若只有「加载中…」骨架行，这次普查等于没看那一面
        # （2026-11-01 实测踩到：silent 切页 + 过早扫描 → 0 行，结论是假阴性）。
        assert det_rows[0] > 5, (
            "明细页只扫到 %d 行（多半是骨架或 silent 未渲染）——"
            "少扫一面得到的「0 处」不算数" % det_rows[0])
        assert not bad, (
            "这些表面上渠道名没有官方图标：%s"
            % {k: v[:3] for k, v in bad.items()})
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()
