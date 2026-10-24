# -*- coding: utf-8 -*-
"""全功能 UI 自检套件：Playwright 遍历控制台每一个交互功能。

「务必保证每个功能都是好的」的硬保障——任一断言失败或页面出现
JS console.error/pageerror，即以非零码退出。

自包含：自动拉起 `python webui.py --demo` 演示控制台，跑完销毁。
用法：python docs/uitest.py  （结果同步落盘 docs/uitest_result.txt）
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = int(os.environ.get("UITEST_PORT", "8891"))
BASE = "http://127.0.0.1:%d" % PORT
RESULT = os.environ.get(
    "UITEST_RESULT",
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "uitest_result.txt"))


def wait_up(timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            # 本地探活绕过系统代理（代理环境曾把 127.0.0.1 也
            # 劫持致 wait_up 恒败——curl --noproxy 同款先例）
            op = urllib.request.build_opener(
                urllib.request.ProxyHandler({}))
            op.open(BASE + "/api/state", timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def free_port():
    """清掉 PORT 上的残留监听（上一轮 TaskStop/异常退出留下的旧代码演示服，
    曾致新特性断言全在旧服上跑而假失败）。"""
    try:
        # 字节捕获+容错解码：netstat 中文窗输出为 GBK，text=True 会被
        # PYTHONUTF8 环境强解成 utf-8 而崩掉读线程（只匹配 ASCII 关键字）
        r = subprocess.run(["netstat", "-ano"], capture_output=True)
        out = r.stdout.decode("utf-8", errors="ignore")
        for ln in out.splitlines():
            if ("127.0.0.1:%d" % PORT) in ln and "LISTENING" in ln:
                subprocess.run(["taskkill", "/PID", ln.split()[-1], "/F"],
                               capture_output=True)
    except Exception:
        pass


def main():
    # GBK 控制台打不出 ✓/✗ 会让收尾 print 抛异常、吞掉 os._exit 判定；
    # 输出去不掉的字符用 ? 代替，门禁结果本身保持原样。
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    from playwright.sync_api import sync_playwright
    free_port()
    srv = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
         "--port", str(PORT)],
        cwd=ROOT,
        # 渲染落盘重定向（TM_RENDER_DIR）：自检期服务端若触达渲染链
        # 路（/api/preview 等），图表落系统临时目录而非仓库 data/
        env=dict(os.environ,
                 TM_RENDER_DIR=tempfile.mkdtemp(prefix="uitest_render_")),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    checks = []
    errors = []
    _aborted = False
    prog = open(RESULT, "w", encoding="utf-8")

    def ck(name, cond, detail=""):
        checks.append((name, bool(cond)))
        prog.write((" ✓ " if cond else " ✗ ") + name +
                   ((" :: " + str(detail)) if (detail and not cond) else "") + "\n")
        prog.flush()

    def step(name):
        prog.write(" … %s\n" % name)
        prog.flush()

    try:
        if not wait_up():
            print("演示控制台启动失败")
            sys.exit(1)
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1280, "height": 900})
            pg.set_default_timeout(10000)
            pg.set_default_navigation_timeout(20000)
            pg.on("console",
                  lambda m: errors.append(m.text)
                  if m.type == "error" and "403 (Forbidden)" not in m.text
                  else None)
            pg.on("pageerror", lambda e: errors.append(
                (getattr(e, "stack", None) or str(e))[:500]))
            step("goto")
            pg.goto(BASE, wait_until="domcontentloaded")
            pg.wait_for_timeout(2500)

            # ---- 总览区（默认概览子视图） ----
            ck("页面标题", "机票监控台" in pg.title())
            # 焦点环 box-shadow 迁移（真实键盘 Tab 路径）：UA 焦点
            # 环系统性接管 outline 通道（msedge 真实内核复证，主按钮白
            # 字蓝底白环≈隐形），环改走 box-shadow 不受接管、outline 恒关
            _ring = False
            for _ in range(10):   # r340 顶栏新增检索入口（多一枚焦点停）
                pg.keyboard.press("Tab")
                if pg.evaluate(
                        "()=>document.activeElement.tagName") == "BUTTON":
                    _ring = pg.evaluate(
                        "()=>{const c=getComputedStyle("
                        "document.activeElement);"
                        "return c.boxShadow.indexOf('11, 98, 214')>=0"
                        "&&c.outlineStyle==='none';}")
                    break
            ck("键盘焦点环 box-shadow 迁移", _ring)
            ck("达标 pill", "已达标" in pg.inner_text("#pill"))
            # okbg 底绿词面 --ok-txt #0b6e39（--green 4.28:1 欠 AA）
            ck("AA 达标绿词面（--ok-txt 5.63:1）", pg.evaluate(
                "()=>getComputedStyle(document.getElementById('pill'))"
                ".color==='rgb(11, 110, 57)'"))
            # .dn 降绿字 --ok-txt（--ok-strong 白卡 4.21 欠，同族最后一枚）
            ck("AA 降绿字面（.dn --ok-txt）", pg.evaluate(
                "()=>{const d=document.createElement('span');"
                "d.className='dn';document.body.appendChild(d);"
                "const c=getComputedStyle(d).color;d.remove();"
                "return c==='rgb(11, 110, 57)';}"))
            ck("演示横幅", pg.is_visible("#demoBar"))
            # verbar 链接触控外扩（::after 纯命中区家族）：demo 态
            # verbar 隐藏，临时置显断言后还原——版本失配横幅的刷新链
            # 触发场景恰是用户必须点它的紧急时刻，曾全站最小可点件
            ck("verbar 链接触控外扩", pg.evaluate(
                """()=>{const v=document.getElementById('verbar');
                const prev=v.style.display;v.style.display='';
                const a=v.querySelector('a');
                const r=a.getBoundingClientRect();
                const hit=document.elementFromPoint(
                 r.x+r.width/2, r.y-6);   /* 裸高上方 6px=外扩区 */
                v.style.display=prev;
                return hit===a
                 &&getComputedStyle(a).position==='relative';}"""))
            # demo 页脚语境中立（本地 --demo 与烘焙静态站双态皆实）
            ck("demo 页脚语境中立", "演示模式 · 合成数据" in
               pg.inner_text("#foot")
               and "在线演示" not in pg.inner_text("#foot"))
            ck("KPI 直飞价", "￥" in pg.inner_text(".kpi.d .num"))
            ck("KPI 达标光晕", len(pg.query_selector_all(".kpi.hit")) >= 1)
            # KPI 主数字文字级令牌（r230 P2-2）：橙档 --orange-txt
            # #a45508=rgb(164,85,8)、达标档 --ok-txt #0b6e39=rgb(11,110,57)，
            # computed 行为钉（源码钉验不了令牌真实消费）。取首个非 hit
            # 的 .kpi.t（demo 卡是 kpi t hit 复合类，首个即达标绿）
            ck("KPI 主数字文字级令牌", pg.evaluate(
                "()=>{const t=[...document.querySelectorAll('.kpi.t .num')]"
                ".find(x=>!x.closest('.kpi').classList.contains('hit'));"
                "const h=document.querySelector('.kpi.hit .num');"
                "return !!t&&!!h"
                "&&getComputedStyle(t).color==='rgb(164, 85, 8)'"
                "&&getComputedStyle(h).color==='rgb(11, 110, 57)';}"))
            ck("航线 chips≥3", len(pg.query_selector_all("#chartRoutes .chip")) >= 3)

            # ---- V50 子视图工作台 ----
            ck("子视图 5/6 tab（demo 含特价）",
               len(pg.query_selector_all("#montabs .mtab")) in (5, 6))
            # 1280 桌面五等分：active 徽标不得撑宽单格；相邻格不得贴线
            _mt = pg.evaluate("""()=>{
              const box=document.getElementById('montabs');
              const ts=[...box.querySelectorAll('.mtab')];
              const rs=ts.map(x=>x.getBoundingClientRect());
              const br=box.getBoundingClientRect();
              return {n:ts.length,
                eq:Math.max(...rs.map(r=>r.width))-Math.min(...rs.map(r=>r.width))<=1,
                overlap:rs.slice(0,-1).some((r,i)=>r.right>rs[i+1].left+1),
                inside:rs.every(r=>r.left>=br.left-1&&r.right<=br.right+1)};}""")
            ck("1280 五/六 tab 等宽无贴线",
               _mt["n"] in (5, 6) and _mt["eq"] and not _mt["overlap"] and _mt["inside"])
            ck("概览默认可见", pg.is_visible("#montab-overview"))
            ck("r353 总览关注卡容器挂载", pg.evaluate(
                "()=>!!document.getElementById('monWatchCard')"
                "&&!!document.getElementById('monWatchList')"
                "&&!!document.getElementById('monWatchRoutes')"))
            ck("查看明细→明细子视图", pg.evaluate(
                "()=>{const a=[...document.querySelectorAll('#users a')]"
                ".find(x=>x.textContent.indexOf('查看明细')>=0);"
                "if(!a)return false;a.click();"
                "return document.getElementById('montab-details')"
                ".style.display==='';}"))
            pg.click('.mtab[data-t="overview"]'); pg.wait_for_timeout(300)
            # kpisum 链接 hover 反馈（真实鼠标路径，:hover 不可脚本
            # 合成；「查看明细/走势」直达链曾悬停零反馈）
            _ka = pg.query_selector(".kpisum a")
            if _ka:
                _ka.hover(); pg.wait_for_timeout(150)
                ck("kpisum 链接 hover underline", pg.evaluate(
                    "()=>getComputedStyle(document.querySelector("
                    "'.kpisum a')).textDecorationLine"
                    ".indexOf('underline')>=0"))
            else:
                ck("kpisum 链接 hover underline", False)
            # 概览 kpisum 补「走势 ▾」直达（jumpRowTrend('')
            # 空路由=当前视图，与「查看明细 ▾」对称；唯一跳转缺口收口）
            ck("概览走势直达→走势子视图", pg.evaluate(
                "()=>{const a=[...document.querySelectorAll('#users a')]"
                ".find(x=>x.textContent.indexOf('走势')>=0);"
                "if(!a)return false;a.click();"
                "return document.getElementById('montab-trend')"
                ".style.display==='';}"))
            pg.click('.mtab[data-t="overview"]'); pg.wait_for_timeout(300)
            node0 = pg.evaluate(
                "document.querySelectorAll('#monview *').length")
            pg.click('.mtab[data-t="trend"]'); pg.wait_for_timeout(600)
            ck("子视图切换零插拔", node0 == pg.evaluate(
                "document.querySelectorAll('#monview *').length"))
            ck("切走势显图表", pg.is_visible("#chartcard"))
            ck("走势图非空白", pg.evaluate(
                "()=>{const c=document.getElementById('chart');"
                "const d=c.getContext('2d').getImageData(0,0,c.width,c.height).data;"
                "for(let i=3;i<d.length;i+=4){if(d[i]>0)return true;}return false;}"))
            # 走势 hover 十字线：鼠标扫过画布 → HPTS 命中数据点
            bb = pg.query_selector("#chart").bounding_box()
            if bb:
                pg.mouse.move(bb["x"] + bb["width"] * 0.5,
                              bb["y"] + bb["height"] * 0.5)
                pg.mouse.move(bb["x"] + bb["width"] * 0.7,
                              bb["y"] + bb["height"] * 0.5)
                pg.wait_for_timeout(200)
                ck("走势 hover 十字线", pg.evaluate("()=>!!HPTS"))
            else:
                ck("走势 hover 十字线", False)
            # 入场动画旧帧竞态回归：切 7 天后画布点数必须多于 48h
            n48 = pg.evaluate("()=>HPTS.d.length")
            pg.evaluate("setRange('7d')"); pg.wait_for_timeout(900)
            ck("7 天范围生效", pg.evaluate(
                "()=>curRoute().range==='7d'"
                "&&HPTS.d.length>%d" % max(150, n48)))

            # ---- K线 / 范围 ----
            pg.click("#mdK"); pg.wait_for_timeout(400)
            ck("K线切换无错", True)
            # K线专有释义（开/收=桶内首末轮；绿桶=桶内回落）折行第二行
            # （宽画布单行 ~90 字超读）
            ck("K线图例专有释义折行", pg.evaluate(
                "()=>{const r=document.getElementById('ringNote');"
                "const th=curRoute().r.th||{};"
                "if(!((th.direct||0)>0||(th.transfer||0)>0))"
                " return '前提失效：环标段以心理价在位为门，烘焙面 th=0 时"
                "本钉须随行为改写';"
                "return r.innerHTML.indexOf('<br>')>=0"
                "&&r.textContent.indexOf('开/收')>=0;}"))
            # 系列色票随模式切换（r230 P2-1）：K线隐藏无所指的
            # 「直飞■蓝/中转■橙」+ ringNote 补簇位语义；切回折线恢复
            ck("K线系列色票隐藏+簇位语义", pg.evaluate(
                "()=>{const a=document.getElementById('lgDirect'),"
                "b=document.getElementById('lgTrans'),"
                "r=document.getElementById('ringNote');"
                "return !!a&&!!b&&!!r"
                "&&a.style.display==='none'"
                "&&b.style.display==='none'"
                "&&r.textContent.indexOf('左簇=直飞')>=0;}"))
            pg.hover("#mdK"); pg.wait_for_timeout(120)
            # 选中态悬停反馈（r230 P2-3）：.on 族 brightness 行为钉
            # （源码钉验不了层叠胜负）
            ck("选中态悬停反馈", pg.evaluate(
                "()=>getComputedStyle(document.getElementById('mdK'))"
                ".filter.indexOf('brightness')===0"))
            pg.click("#mdLine"); pg.wait_for_timeout(300)
            ck("折线模式色票恢复", pg.evaluate(
                "()=>{const a=document.getElementById('lgDirect');"
                "return !!a&&a.style.display==='';}"))
            pg.click("#rng7d"); pg.wait_for_timeout(400)
            ck("7 天范围", "7天" in pg.inner_text("#chartTitle"))
            pg.click("#rng48"); pg.wait_for_timeout(300)

            # ---- 价格日历 ----
            cal = pg.query_selector_all(".calcell")
            # 近 14 天窗口含边界日：日历格随运行时刻在 14/15 间摆动
            ck("日历 14-15 格", len(cal) in (14, 15))
            ck("日历悬停文案", bool(cal) and (
                "达标" in (cal[-1].get_attribute("title") or "")
                or "超线" in (cal[-1].get_attribute("title") or "")))
            ck("7天洞察统计", "最低" in pg.inner_text("#calStats")
               and "降价" in pg.inner_text("#calStats"))
            ck("日历最低日徽标", pg.evaluate(
                "()=>{const b=document.querySelector('.calcell.best .cx');"
                "return !!b&&b.textContent.indexOf('最低')>=0;}"))
            ck("日历差价副行", pg.evaluate(
                "()=>[...document.querySelectorAll('.calcell .cx')]"
                ".some(x=>x.textContent.indexOf('+￥')===0)"))
            # 亮色日历白字不变量——白字只许出现在实色达标底
            # （rgba 合成白字 2.27~3.91:1 全欠 AA 已根除，白字改实色/深字）
            ck("亮色日历白字仅实色达标底", pg.evaluate(
                "()=>[...document.querySelectorAll('#calgrid .calcell')]"
                ".every(c=>{const s=getComputedStyle(c);"
                "return s.color!=='rgb(255, 255, 255)'"
                "||s.backgroundColor==='rgb(14, 131, 69)';})"))
            # 「点击格看该日明细」承诺句条件化——有 link 格才在场
            ck("日历承诺句条件化", pg.evaluate(
                "()=>{const t=document.getElementById('calStats').textContent;"
                "return !!document.querySelector('#calgrid .calcell.link')"
                "||t.indexOf('点击格看该日明细')<0;}"))
            # 真达标格小字免 opacity 税——qhit 格 .cd/.cx
            # computed opacity 恒 1（.85 税曾把白字拖到 3.94:1）
            ck("达标格 qhit 小字不透明", pg.evaluate(
                "()=>{const c=document.querySelector('#calgrid .calcell.qhit');"
                "if(!c)return false;"
                "return [...c.querySelectorAll('.cd,.cx')]"
                ".every(x=>getComputedStyle(x).opacity==='1');}"))
            # 破线格小字同免税（qbrk）——demo
            # 合成数据无 q=1 档样本，插桩格验 CSS 规则真实生效
            ck("破线格 qbrk 小字不透明", pg.evaluate(
                "()=>{const g=document.getElementById('calgrid');"
                "const c=document.createElement('div');"
                "c.className='calcell qbrk';"
                "c.innerHTML='<div class=\"cd\">T</div>"
                "<div class=\"cx\">+￥1</div>';"
                "g.appendChild(c);"
                "const ok=[...c.querySelectorAll('.cd,.cx')]"
                ".every(x=>getComputedStyle(x).opacity==='1');"
                "c.remove();return ok;}"))
            # --fill2 顶带收深（渐变顶行白字 4.25~4.44 欠）
            ck("--fill2 双主题收深", pg.evaluate(
                "()=>getComputedStyle(document.documentElement)"
                ".getPropertyValue('--fill2').trim()==='#1d6fd8'"))
            # 日历格保持纯展示收口（格键=扫描观察日域与明细出发日域
            # 恒不相交，格级点击跳明细恒为空过滤死通道；真机证伪判例）
            ck("日历格纯展示无假 affordance", pg.evaluate(
                "()=>!document.querySelector("
                "'#calgrid .calcell[role=button]')"))

            # ---- C-1 走势点→该轮明细 ----
            # 点击画布数据点=看该系列（航线+出发日）明细：jumpCalDate
            # 同款联动（明细子视图+锁出发日+多航线锁路由）。承诺句
            # 条件在场（N>0 有点可点 + date 有处可跳，空态死承诺防线）；
            # 跳完 resetFlt 复位（新钉自带状态复位律）
            ck("走势承诺句条件在场", pg.evaluate(
                "()=>document.getElementById('ringNote')"
                ".textContent.indexOf('点击看该航线当日明细')>=0"))
            _c1d = pg.evaluate("()=>curRoute().r.date||''")
            _bb1 = pg.query_selector("#chart").bounding_box()
            if _bb1 and _c1d:
                pg.mouse.click(_bb1["x"] + _bb1["width"] * 0.5,
                               _bb1["y"] + _bb1["height"] * 0.5)
                pg.wait_for_timeout(400)
                ck("走势点点击→明细子视图", pg.evaluate(
                    "()=>document.getElementById('montab-details')"
                    ".style.display===''"))
                ck("走势点点击锁定该系列出发日", pg.evaluate(
                    "d=>FLT.dates.size===1&&[...FLT.dates][0]===d", _c1d))
                # 键盘路径 + 焦点交接（审计 P2-1）：聚焦画布按
                # Enter 跳明细，焦点落到明细 tab 钮（不坠 body）
                pg.evaluate(
                    "()=>{gotoMonTab('trend');"
                    "document.getElementById('chart').focus();}")
                pg.keyboard.press("Enter"); pg.wait_for_timeout(400)
                ck("C-1 Enter 跳转+焦点交接明细 tab", pg.evaluate(
                    "()=>{const a=document.activeElement;"
                    "return !!a&&a.dataset&&a.dataset.t==='details';}"))
                pg.evaluate("()=>resetFlt()"); pg.wait_for_timeout(200)
            else:
                ck("走势点点击→明细子视图", False)
                ck("走势点点击锁定该系列出发日", False)

            # ---- 渠道健康子视图 + 日志弹层 ----
            pg.click('.mtab[data-t="health"]'); pg.wait_for_timeout(400)
            # 作用域钉 #hbody：推送通道区(#pushhl)同用 .hrow 类，
            # 全页计数被通道行撑爆（5 渠道+2 通道恒 7）
            ck("健康 5 渠道", len(pg.query_selector_all("#hbody .hrow")) == 5)
            # r358 来源接入板：PC 停服 → H5 → 登录门；demo 不伪造登录态
            ck("来源接入板可见", pg.is_visible("#srccap"))
            ck("来源接入三节点", len(
                pg.query_selector_all("#srccap .scnode")) == 3)
            _sc = pg.inner_text("#srccap")
            ck("来源接入路径词面", all(
                x in _sc for x in ("PC 网页", "已停服", "H5 机票",
                                   "登录后可用", "登录态")))
            ck("来源接入 demo 登录态", "DEMO" in pg.inner_text("#scQState"))
            ck("来源接入 demo 隐藏登录钮", pg.evaluate(
                "()=>document.getElementById('scLoginBtn').hidden"))
            ck("来源接入 H5 落地", pg.evaluate(
                "()=>{const a=document.querySelector('#srccap a.scbtn');"
                "return !!a&&a.href==='https://touch.qunar.com/h5/flight/';}"))
            ck("来源接入板无横向溢出", pg.evaluate(
                "()=>{const e=document.getElementById('srccap');"
                "return e.scrollWidth<=e.clientWidth+1;}"))
            pg.set_viewport_size({"width": 600, "height": 900})
            pg.wait_for_timeout(250)
            ck("600 来源接入按钮 32 地板", pg.evaluate(
                "()=>{const b=document.querySelector('#srccap .scbtn.ghost');"
                "return !!b&&b.getBoundingClientRect().height>=32;}"))
            pg.set_viewport_size({"width": 1280, "height": 900})
            pg.wait_for_timeout(250)
            cells = pg.query_selector_all(".hc.ok")
            ck("健康格可点", bool(cells))
            # 点击有动作（开日志弹层）必须 pointer 光标
            # （help=仅悬停读说明，与真实点击动作失配=affordance 反信号）
            ck("健康格 cursor:pointer", bool(cells) and pg.evaluate(
                "()=>getComputedStyle(document.querySelector('.hc'))"
                ".cursor==='pointer'"))
            # 弹性档门槛 1024——1280 主流本带格宽须 >6px
            # （旧档 1440 时 1180-1439 恒 214px 左聚空腔，弹性档
            # 同病灶半幅残留；固定档恰 6px 作判据分界）
            ck("健康格 1280 弹性铺满", pg.evaluate(
                "()=>{const cs=[...document.querySelectorAll('.hc')];"
                "return cs.length>0&&Math.max(...cs.map("
                "e=>e.getBoundingClientRect().width))>6.5;}"))
            if cells:
                # 健康格随轮询整带重渲：ElementHandle 在 query 与 click
                # 之间可能已脱离 DOM（偶发中断），改在页面内取当前格点击。
                pg.evaluate("()=>{const c=document.querySelector('.hc');"
                            "if(c)c.click()}")
                pg.wait_for_timeout(600)
                ck("日志弹层", pg.query_selector(".logpre") is not None)
                # showLog 入口 aria-label 随可见标题切换
                ck("日志弹层 aria-label 随入口", pg.get_attribute(
                    "#pvMask .pvcard", "aria-label") == "渠道轮日志")
                # 底注随入口（P2-2）：前序预览/推送记录入口先开过，
                # 底注不得残留它们的文案（uitest 语境=demo，r236 P3-1
                # 起底注随 s.demo 出演示词面——入口可区分语义不变）
                ck("日志弹层底注随入口", ("原文直读" in pg.inner_text("#pvFoot"))
                   or ("合成轮日志回放" in pg.inner_text("#pvFoot")))
                pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
                ck("Esc 关日志", "on" not in (pg.get_attribute("#pvMask", "class") or ""))
                # ::after 热区下缘命中（格中心下方 6px 点击开本格弹层）
                # ——纵向对称外扩的行为钉：审计探针曾报下缘未命中，
                # elementFromPoint 复测与触屏仿真 tap 均 PASS（探针状态
                # 伪影撤案），本钉锁真实点击路径防未来回归。
                # 断言对象=「弹层当前开着」：closePv 只摘 #pvMask 的
                # on 类、不清 pvBody——早段 cells[0].click() 开过的
                # .logpre 从此驻留 DOM，断言其存在对「本次点击是否真
                # 开层」零鉴别力（失靶也绿的恒真式）；mask on 且内含
                # .logpre 双证才是「本次点击开了日志层」。
                # 重试取件：取件与取框之间隔着轮询重渲染面，旧 handle
                # 脱附（bounding_box 返 None / evaluate 抛脱附错）产出
                # 环境瞬态红（CI 首跑红复跑绿恒形态）——每轮先 Esc 复
                # 位弹层、新鲜取件，脱附即重试共 3 次，任一次命中即
                # PASS、全部失败才落红：瞬态归零，真回归仍必红。
                # 先滚动到视口中部再取框点击：卡内推送通道区增高后
                # 矮视口（CI runner）格子可滚出视口，视口外 mouse.click
                # 落空；scroll_into_view 的最小滚动还可把格子停在吸顶
                # 条正下方，不透明 header 盖住格心、+6px 下缘点落进
                # 遮盖层——block:center 落点恒在视口中部安全带，与吸顶
                # 件零几何交叠。
                _hot_ok = False
                for _hot_i in range(3):
                    pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
                    _cell = pg.query_selector(".hc.ok")
                    if not _cell:
                        continue
                    try:
                        _cell.evaluate(
                            "el=>el.scrollIntoView({block:'center'})")
                        pg.wait_for_timeout(300)
                        _bb = _cell.bounding_box()
                    except Exception:
                        _bb = None   # handle 脱附抛错：下一轮新鲜取件
                    if not _bb:
                        continue
                    pg.mouse.click(_bb["x"] + _bb["width"] / 2,
                                   _bb["y"] + _bb["height"] / 2 + 6)
                    pg.wait_for_timeout(600)
                    _hot_ok = pg.evaluate(
                        "()=>{const m=document.getElementById('pvMask');"
                        "return m.classList.contains('on')"
                        "&&!!m.querySelector('.logpre');}")
                    if _hot_ok:
                        break
                ck("健康格热区下缘命中", _hot_ok)
                pg.keyboard.press("Escape"); pg.wait_for_timeout(200)

            # 健康错误体双分支语义（保陈旧政策收口）：已有时间线时
            # 错误体保陈旧（瞬态 500 不再把整条格带掀成错误文案）；
            # 冷启动（无卡）错误体仍点亮错误词面。200+无 rounds 体
            # 等价触发 renderHealth 同一分支（生产 500 同体），且不制
            # 造预期内 500 console 噪音污染「零 JS 错」门
            # mock /api/state 变体前先抄 webui._user_state 契约：
            # history/th/best 恒 {direct,transfer} 对象、best 内层
            # brief 才可 null（r333 三连撤备案，勿再造数组/null 形态）
            pg.route("**/api/health", lambda r: r.fulfill(
                status=200, content_type="application/json",
                body='{"err":"boom"}'))
            pg.evaluate("()=>{document.getElementById('healthcard')"
                        ".style.display='none';HL=null;health();}")
            pg.wait_for_timeout(400)
            ck("健康500冷启动错误词面", pg.evaluate(
                "()=>{const e=document.getElementById('healthEmpty'),"
                "c=document.getElementById('healthcard');"
                "return e.style.display===''&&c.style.display==='none'"
                "&&e.textContent.indexOf('读取失败')>=0;}"))
            pg.unroute("**/api/health")
            pg.evaluate("()=>{HL=null;health();}")
            pg.wait_for_timeout(500)
            ck("健康恢复渲染", pg.evaluate(
                "()=>document.getElementById('healthcard')"
                ".style.display===''"))
            # 已有时间线 + 错误体 → 保陈旧（卡在场、错误文案不点亮）
            pg.route("**/api/health", lambda r: r.fulfill(
                status=200, content_type="application/json",
                body='{"err":"boom"}'))
            pg.evaluate("()=>{HL=null;health();}")
            pg.wait_for_timeout(400)
            ck("健康500保陈旧不掀卡", pg.evaluate(
                "()=>{const e=document.getElementById('healthEmpty'),"
                "c=document.getElementById('healthcard');"
                "return c.style.display===''&&e.style.display==='none';}"))
            pg.unroute("**/api/health")
            pg.evaluate("()=>{HL=null;health();}")
            pg.wait_for_timeout(500)

            # ---- 推送通道健康行（/api/health j.push） ----
            # 合成载荷：钉钉连败 5（-1 幽灵期形态）+ 邮件全绿——主推送
            # 面零可见（逐条 ⚠️ 仅推送记录弹窗），通道级聚合补盲区
            _pj = {"rounds": [
                    {"ts": "10-01 15:00", "plats": {"qunar": {
                        "s": "ok", "ok": 3, "tot": 3}}},
                    {"ts": "10-01 14:40", "plats": {"qunar": {
                        "s": "ok", "ok": 3, "tot": 3}}}],
                "stats": {"qunar": {"ok": 2, "part": 0, "fail": 0,
                                    "rate": 1.0}},
                "push": {"window_hours": 24, "channels": {
                    "dingtalk": {"ok": 2, "fail": 5, "fail_streak": 5,
                                 "last": "10-01 15:24",
                                 "last_ok": "10-01 09:08"},
                    "email": {"ok": 7, "fail": 0, "fail_streak": 0,
                              "last": "10-01 15:24",
                              "last_ok": "10-01 15:24"}}}}
            pg.route("**/api/health", lambda r: r.fulfill(
                status=200, content_type="application/json",
                body=json.dumps(_pj)))
            pg.evaluate("()=>{HL=null;health();}")
            pg.wait_for_timeout(400)
            ck("推送通道行×2",
               len(pg.query_selector_all("#pushhl .hrow")) == 2)
            ck("钉钉连败词红态", pg.evaluate(
                "()=>{const t=document.querySelector('#pushhl .pst.bad');"
                "return !!t&&t.textContent.indexOf('连败 5')>=0;}"))
            ck("邮件正常绿态", pg.evaluate(
                "()=>{const t=document.querySelector('#pushhl .pst.ok');"
                "return !!t&&t.textContent==='正常';}"))
            ck("通道成功率徽标", pg.evaluate(
                "()=>{const b=[...document.querySelectorAll("
                "'#pushhl .hbadge')].map(x=>x.textContent);"
                "return b.indexOf('29%')>=0&&b.indexOf('100%')>=0;}"))
            pg.unroute("**/api/health")
            pg.evaluate("()=>{HL=null;health();}")
            pg.wait_for_timeout(500)
            # demo 分支恒走 demo_health 合成通道（不读真实账本）——
            # mock 撤销后 pushhl 应回渲染合成通道行（非空文案）
            ck("推送通道恢复合成渲染", pg.evaluate(
                "()=>{const h=document.getElementById('pushhl');"
                "return !!h&&h.textContent.indexOf('推送通道')>=0"
                "&&h.querySelectorAll('.hrow').length===2;}"))

            # ---- V50 运行脉冲 ----
            ck("脉冲 statline 4 格",
               len(pg.query_selector_all("#statline .stat")) == 4)
            ck("脉冲轮次柱≥30",
               len(pg.query_selector_all("#pulsebars .pbar")) >= 30)
            ck("脉冲柱含渠道分段",
               len(pg.query_selector_all("#pulsebars .seg")) > 0)
            # 脉冲柱点击跳渠道健康，光标须 pointer 同律
            ck("脉冲柱 cursor:pointer", pg.evaluate(
                "()=>getComputedStyle(document.querySelector('.pbar'))"
                ".cursor==='pointer'"))
            ck("脉冲图例渠道色",
               len(pg.query_selector_all("#pulseLegend .pseg-qunar")) >= 1)
            ck("/api/pulse 端点", pg.evaluate(
                "()=>fetch('/api/pulse').then(r=>r.json())"
                ".then(j=>j.ok&&j.rounds.length>0)"))
            # 删光用户保存后残留态回收（pulsecard/userPills
            # 亮过即保持 display:''）——合成空 users 走 render() 空分支
            ck("末用户删除残留回收", pg.evaluate(
                """()=>{const pc=document.getElementById('pulsecard'),
                 up=document.getElementById('userPills');
                pc.style.display='';up.style.display='';
                const _s=S.users;S.users=[];render();
                const hid=pc.style.display==='none'
                 &&up.style.display==='none';
                S.users=_s;render();
                pc.style.display='';up.style.display='none';   /* 还原 demo 实况 */
                return hid;}"""))
            # P1-1 行为钉：非概览子栏停留时删光用户——空分支切回概览
            # （hero 教学卡在概览 pane 内，曾被埋葬成空白死区且 jpmontab
            # 持久化刷新不自救）；chart/table 守卫收紧后切子栏不抛
            ck("空配置非概览子栏自愈+守卫", pg.evaluate(
                """()=>{const _s=S.users,_t=MONTAB;let ok=true;
                S.users=[];render();
                ok=ok&&MONTAB==='overview'
                 &&document.getElementById('montab-overview')
                   .style.display==='';
                try{showMonTab('trend');}catch(e){ok=false;}
                S.users=_s;render();showMonTab(_t,true);   /* 无条件回位（状态复位律） */
                return ok;}"""))

            # ---- 推送预览 ----
            # busy 锁宽须盖 busy 终态（r242 Soldier Minor-1）：min-width
            # 是下限，busy 文案比首态宽时同排按钮仍被挤一拍；量测在
            # add('busy') 之前（spinner 会撑大 offsetWidth 量值）。
            # mock 挂起 /api/preview 保持 busy 窗口内抓锁值；段尾令牌
            # 换代复位（挂起请求永不返回，走 finally 同款清理）
            pg.route("**/api/preview", lambda r: None)
            pg.click("#pvBtn"); pg.wait_for_timeout(300)
            ck("预览 busy 锁宽≥文案终态", pg.evaluate(
                """()=>{
                const b=$('pvBtn');
                const cs=getComputedStyle(b);
                const m=document.createElement('span');
                m.style.cssText='position:absolute;visibility:hidden;white-space:nowrap;font:'+cs.font;
                m.textContent='构建中 · 约需半分钟…';
                document.body.appendChild(m);
                const need=m.offsetWidth+parseFloat(cs.paddingLeft)
                  +parseFloat(cs.paddingRight)+17;
                m.remove();
                return b.classList.contains('busy')
                  &&b.textContent==='构建中 · 约需半分钟…'
                  &&(parseFloat(b.style.minWidth)||0)>=need-1;}"""))
            pg.unroute("**/api/preview")
            pg.evaluate("++_PV_SEQ;_PV_PENDING=false;"
                        "const _b=$('pvBtn');_b.classList.remove('busy');"
                        "_b.style.minWidth='';_b.textContent='👁 预览推送';")
            pg.wait_for_timeout(100)
            pg.click("#pvBtn")
            # 预览载荷随航线数增重（服务端现渲染 PNG 组），固定等待
            # 会采样早于标题落画——等 pvBody 装载信号（静态骨架恒空，
            # 文本 >50 即真数据在画）再断言标题
            pg.wait_for_function(
                "()=>{const b=document.querySelector('#pvBody');"
                "return !!b&&b.innerText.length>50;}", timeout=15000)
            ck("预览标题🚨", pg.inner_text("#pvTitle").startswith("🚨"))
            # 预览入口底注回设（P2-2 三入口显式回设律：静态初始值
            # 只兜第一次，前序入口先开过会残留自己的文案）
            ck("预览底注随入口", "近似渲染" in pg.inner_text("#pvFoot"))
            ck("预览含链接", len(pg.query_selector_all("#pvBody a")) > 0)
            ck("预览撤超线仪表条", "🟦" not in pg.inner_text("#pvBody")
               and "⬜" not in pg.inner_text("#pvBody"))
            ck("预览图例真达标词面",
               "🎯真达标" in pg.inner_text("#pvBody"))
            # 弹层开着全局快捷键不透传背景页（1/2/3-6/R//）
            ck("弹层开启快捷键不透传", pg.evaluate(
                "()=>{const v0=VIEW;"
                "document.dispatchEvent(new KeyboardEvent('keydown',{key:'2'}));"
                "return VIEW===v0;}"))
            # previewPush 入口 aria-label 保持「钉钉推送预览」
            ck("预览弹层 aria-label 保持", pg.get_attribute(
                "#pvMask .pvcard", "aria-label") == "钉钉推送预览")
            # 空态教导词面对齐真实按钮（词面与在场按钮一致）
            ck("空态教导词面无旧按钮名", pg.evaluate(
                "()=>document.body.innerText.indexOf('立即抓取')<0"
                "&&!![...document.querySelectorAll('button')].find("
                "b=>b.textContent.indexOf('立即扫描一轮')>=0)"))
            pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
            # 守卫只封弹层开启窗口：关闭后快捷键照常（'2'→cfg，'1'→还原）
            ck("弹层关闭后快捷键恢复", pg.evaluate(
                "()=>{document.dispatchEvent("
                "new KeyboardEvent('keydown',{key:'2'}));"
                "const ok=VIEW==='cfg';"
                "document.dispatchEvent("
                "new KeyboardEvent('keydown',{key:'1'}));"
                "return ok&&VIEW==='mon';}"))

            # ---- 推送记录回看 ----
            pg.click('button:has-text("推送记录")'); pg.wait_for_timeout(700)
            ck("推送记录弹层", "推送记录" in pg.inner_text("#pvTitle"))
            # pushLog 入口 aria-label 随可见标题切换
            ck("推送记录弹层 aria-label 随入口", pg.get_attribute(
                "#pvMask .pvcard", "aria-label") == "推送记录")
            # 底注随入口（P2-2）：预览先开过，底注不得残留「近似渲染」
            # （uitest 语境=demo，r236 P3-1 起底注随 s.demo 出演示词面）
            ck("推送记录底注随入口", ("本地存档回放" in pg.inner_text("#pvFoot")
               or "合成推送记录回放" in pg.inner_text("#pvFoot"))
               and "近似渲染" not in pg.inner_text("#pvFoot"))
            ck("推送记录条目", len(pg.query_selector_all(".plitem")) >= 1)
            ck("推送记录状态色条", pg.evaluate(
                "()=>{const el=document.querySelector('.plitem');"
                "return !!el&&getComputedStyle(el).borderLeftWidth==='3px';}"))
            pl = pg.query_selector(".plitem")
            if pl:
                pl.click(); pg.wait_for_timeout(300)
                ck("记录展开全文", pg.evaluate(
                   "()=>{const d=document.querySelector('.pldesp');"
                   "return !!d&&d.style.display!=='none';}"))
                ck("展开零插拔", pg.evaluate(
                   "()=>document.querySelectorAll('.pldesp').length==="
                   "document.querySelectorAll('.plitem').length"))
            pg.keyboard.press("Escape"); pg.wait_for_timeout(200)

            # ---- /notify 落地页（弹窗点击直达轻页）----
            pg.goto(BASE + "/notify/NDEMO"); pg.wait_for_timeout(600)
            ck("notify 页 md 渲染",
               len(pg.query_selector_all("#md h1,#md .h3")) >= 1)
            ck("notify CTA 胶囊", pg.evaluate(
                "()=>{const a=document.querySelector('#md a');"
                "return !!a&&getComputedStyle(a).borderRadius==='999px';}"))
            # notify 独立页 :root 令牌区须自带 --pill
            # （漏补则 var(--pill) 无定义、CTA 圆角塌 0——回归即上一行先红）
            ck("notify --pill 令牌在册", pg.evaluate(
                "()=>getComputedStyle(document.documentElement)"
                ".getPropertyValue('--pill').trim()==='999px'"))
            # notify 令牌在册对齐——亮 --mut 随主站 AA 收深
            # 值（#5a6c7d）；.logo 圆角走 --r3 令牌（旧 7px 硬编码脱队）
            ck("notify --mut 对齐主站", pg.evaluate(
                "()=>getComputedStyle(document.documentElement)"
                ".getPropertyValue('--mut').trim()==='#5a6c7d'"))
            ck("notify --r3 圆角令牌", pg.evaluate(
                "()=>{const l=document.querySelector('.logo');"
                "return !!l&&getComputedStyle(l).borderRadius==='9px';}"))
            ck("notify 达标横幅动效", pg.evaluate(
                "()=>{const h=document.querySelector('.hitbar');"
                "return !!h&&h.classList.contains('ok');}"))
            pg.goto(BASE + "/"); pg.wait_for_timeout(600)

            # ---- 航班明细子视图 ----
            pg.click('.mtab[data-t="details"]'); pg.wait_for_timeout(400)
            # 筛选默认折叠：明细交互门先展开抽屉（与生产入口一致）
            pg.evaluate("()=>{const fb=document.querySelector('.fbar');"
                        "if(fb&&getComputedStyle(fb).display==='none')togFlt();}")
            pg.wait_for_timeout(300)
            n_all = len(pg.query_selector_all("#ftable tbody tr"))
            pg.click('#tabs span[data-f="d"]'); pg.wait_for_timeout(300)
            pg.evaluate("()=>{while(_tblAppend()){}}")   # 切片只渲首 120 行，断言全量先补片
            # 行语义锚 .catt 内直飞/中转胶囊（排除 t-i 国际徽标——
            # r326 A3 起国际徽标与直飞/中转同槽双胶囊，宽集合口径
            # 会把「国际」误读进过滤词面）
            _dchk = pg.evaluate(
                """()=>{const rows=[...document.querySelectorAll(
                  '#ftable tbody tr[data-k]')];
                  if(!rows.length)return {n:0,ok:false};
                  let ok=true;
                  for(const r of rows){
                    const t=[...r.querySelectorAll('.catt .tag')]
                      .find(x=>!x.classList.contains('t-i'));
                    /* r51：日历薄行类别 tag 改显「日历」（原伪装
                       「直飞」=薄行非具体航班），直飞 tab=非中转语义
                       下日历 tag 合法 */
                    if(!t||(t.innerText.indexOf('直飞')<0&&t.innerText.indexOf('日历')<0)){ok=false;break;}}
                  return {n:rows.length,ok};}""")
            ck("直飞 tab 过滤（n=%d）" % _dchk["n"],
               _dchk["ok"] and _dchk["n"] > 0)
            pg.click('#tabs span[data-f="bag"]'); pg.wait_for_timeout(300)
            bag_rows = pg.query_selector_all("#ftable tbody tr")
            bag_ok = all("中转" in t.inner_text()
                         for t in pg.query_selector_all(
                             "#ftable tbody tr .catt .tag"
                             ":not(.t-i)"))
            ck("直挂 tab 过滤（仅中转/空表）", bag_rows == [] or bag_ok)
            pg.click('#tabs span[data-f="all"]'); pg.wait_for_timeout(200)
            pg.fill("#fq", "MU"); pg.keyboard.press("Enter")
            pg.wait_for_timeout(300)
            n_mu = len(pg.query_selector_all("#ftable tbody tr"))
            ck("搜索 MU 过滤", 0 < n_mu < n_all)
            pg.fill("#fq", ""); pg.keyboard.press("Enter")
            pg.wait_for_timeout(200)
            pg.click("th.srt"); pg.wait_for_timeout(200)
            ck("排序切换", "on" in (pg.get_attribute("th.srt", "class") or ""))
            # ---- 首列表头 hover 反馈（价格列=sticky 吸附打底与 th.srt:hover
            # 同特异性源码序压制，形成 9 列唯一 hover 死区；置尾复声明
            # 层叠胜负以 computed 行为钉锁——源码钉只证声明在场）----
            pg.mouse.move(5, 5); pg.wait_for_timeout(150)  # 排序点击残留 hover 复位
            _th0bg = pg.evaluate(
                "()=>getComputedStyle(document.querySelector("
                "'#ftable th')).backgroundColor")
            pg.hover("#ftable th"); pg.wait_for_timeout(150)
            ck("首列表头 hover 反馈", pg.evaluate(
                "()=>getComputedStyle(document.querySelector("
                f"'#ftable th')).backgroundColor!=={_th0bg!r}"))
            # ---- tabs 族 hover 底色反馈（字色微移与 chip 族
            # 反馈语言不一；底色令牌归一）----
            _tb = pg.query_selector("#tabs span:not(.on)")
            if _tb:
                pg.mouse.move(5, 5); pg.wait_for_timeout(100)
                _tb0 = _tb.evaluate(
                    "e=>getComputedStyle(e).backgroundColor")
                _tb.hover(); pg.wait_for_timeout(150)
                ck("tabs hover 底色反馈", pg.evaluate(
                    "()=>{const e=document.querySelector("
                    "'#tabs span:not(.on)');"
                    f"return getComputedStyle(e).backgroundColor!=={_tb0!r};}}"))
                pg.mouse.move(5, 5); pg.wait_for_timeout(100)
            else:
                ck("tabs hover 底色反馈", False)
            ck("明细达标行绿底", pg.evaluate(
                "()=>{const tr=document.querySelector('#ftable tr.qual');"
                "if(!tr)return false;const s=getComputedStyle(tr);"
                "return s.backgroundColor.indexOf('14, 131, 69')>=0"
                "&&s.boxShadow.indexOf('inset')>=0;}"))
            # 子行段间分隔 ' ｜ '（与段内 '·' 两级
            # 分明；demo 合成行 ≥2 段即渲染 ｜，段内复合词保持 · 不受扰）
            ck("明细子行段间 ｜ 分隔", pg.evaluate(
                "()=>{const els=[...document.querySelectorAll("
                "'#ftable .stl')];return els.some("
                "e=>e.textContent.indexOf(' ｜ ')>0);}"
                ))
            # ---- 吸附格 gradient 打底（横滚不透+
            # 双层绿底根除）+ 价格绿字 --ok-txt（AA 5.18:1；--green 4.19~4.35 欠）----
            ck("达标行吸附格 gradient 打底", pg.evaluate(
                "()=>{const td=document.querySelector('#ftable tr.qual td');"
                "if(!td)return false;"
                "return getComputedStyle(td).backgroundImage.indexOf("
                "'linear-gradient')===0;}"))
            ck("达标行价格绿字 --ok-txt（AA）", pg.evaluate(
                "()=>{const td=document.querySelector("
                "'#ftable tr.qual td.price');if(!td)return false;"
                "return getComputedStyle(td).color==='rgb(11, 110, 57)';}"))
            # .fbar 开关键盘焦点环（outline:none 未豁免
            # .switch——36×20 灰胶囊上 box-shadow 14% 微晕不可辨）
            ck("fbar 开关键盘焦点环", pg.evaluate(
                "()=>{const el=document.getElementById('fnostale');"
                "if(!el)return false;"
                "el.focus({focusVisible:true});"   # 程序化 focus 不触发 :focus-visible 启发式，强制可见焦点（真实 Tab 路径同款 UA 环）
                "return getComputedStyle(el).outlineStyle!=='none';}"))
            rows = pg.query_selector_all("#ftable tbody tr:not(.xrow)")
            if rows:
                n_tr = pg.evaluate(
                    "document.querySelectorAll('#ftable tr').length")
                rows[0].click(); pg.wait_for_timeout(300)
                ck("同班比价展开", pg.evaluate(
                   "()=>{const x=[...document.querySelectorAll("
                   "'#ftable tr.xrow')].find(el=>"
                   "!el.classList.contains('tgrow'));"
                   "return !!x&&x.style.display!=='none';}"))
                ck("展开零节点插拔（扩展/翻译免疫）",
                   n_tr == pg.evaluate(
                       "document.querySelectorAll('#ftable tr').length"))
                pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
                ck("Esc 收起展开", pg.evaluate(
                   "()=>[...document.querySelectorAll('#ftable tr.xrow')]"
                   ".every(x=>x.style.display==='none')"))

            # ---- 改期窗口（trendGo 消费端）----
            # tabs 档位图例常驻（触屏读不到 title 的补位）/
            # chartEmpty 初始显示态 / 1440 档 --kpiw 1168 合档
            # 词面随「实绿→深绿」统一（与日历同语言）
            ck("tabs 档位图例常驻", pg.evaluate(
                "()=>{const b=[...document.querySelectorAll('#tabs b')]"
                ".find(x=>x.textContent.indexOf('深绿=真达标')===0);"
                "return !!b&&getComputedStyle(b).fontSize==='11px';}"))
            ck("chartEmpty 初始显示态", pg.evaluate(
                "()=>document.getElementById('chartEmpty')"
                ".style.display==='flex'"))
            # ---- 明细行→走势页内跳转（结构性建议：
            # 跳转图谱唯一缺口，行尾 📈 与 ↗ 成对）——置于 chartEmpty
            # 初始态断言之后：跳转触发 chart() 会隐藏空态，勿污染前提 ----
            pg.click('.mtab[data-t="details"]'); pg.wait_for_timeout(300)
            tj = pg.query_selector_all("#ftable .tj")
            ck("明细行走势跳转件在场", len(tj) > 0)
            # .tj 入触控热区外扩家族（::after absolute；
            # 本体 ~24.5×18px 纵向扩到触控基准，横向 -4px 同 .tg 防吃 ↗）
            ck("tj 热区外扩在场", pg.evaluate(
                "()=>{const t=document.querySelector('#ftable .tj');"
                "if(!t)return false;"
                "const a=getComputedStyle(t,'::after');"
                "return a.position==='absolute'&&a.content!=='none';}"))
            if tj:
                tj[0].click(); pg.wait_for_timeout(400)
                ck("明细行跳走势（标签切换+图渲染）", pg.evaluate(
                   "()=>document.querySelector('#montab-trend')"
                   ".style.display===''&&document.querySelector("
                   "'#montab-details').style.display==='none'"))
                # ---- chip 高亮须跟随跳转（buildChartChips
                # 显式重建律）——点「非当前 CHR.i 航线」的行抓真回归
                # （首行恰好默认航线时 chip 本就正确、抓不到漏重建）----
                picked = pg.evaluate(
                    "()=>{const st0=CHR[S.users[U].name];"
                    "const cur=typeof st0==='object'?(st0?st0.i:0):(st0||0);"
                    "const tjs=[...document.querySelectorAll('#ftable .tj')];"
                    "const t=tjs.find(x=>{const m=(x.getAttribute('onclick')||'')"
                    ".match(/jumpRowTrend\\('([^']+)'/);if(!m)return false;"
                    "const arr=S.users[U].routesArr||[];"
                    "const ix=arr.findIndex(r=>r.label===m[1]||"
                    "r.label.startsWith(m[1]+' '));"
                    "return ix>=0&&ix!==cur;});"
                    "if(!t)return '';"
                    "const m=t.getAttribute('onclick').match(/jumpRowTrend[^;]+/);"
                    "return m?m[0]:'';}")
                if picked:
                    pg.evaluate("()=>{" + picked + ";}")
                    pg.wait_for_timeout(400)
                    ck("跳走势 chip 高亮跟随", pg.evaluate(
                        "()=>{const u=S.users[U];const st=CHR[u.name];"
                        "const idx=typeof st==='object'?(st?st.i:0):(st||0);"
                        "const on=document.querySelector('#chartRoutes .chip.on');"
                        "const arr=u.routesArr||[];"
                        "return arr.length>=2&&!!on&&on.textContent==="
                        "(arr[idx]||{}).label;}"))
                pg.click('.mtab[data-t="details"]'); pg.wait_for_timeout(300)
                # .tj 键位 Space=Enter 同义跳走势（Space
                # 冒泡到行级 tr 的 Enter||Space 处理器会误开同班比价面板）
                pg.evaluate(
                    "()=>{const t=document.querySelector('#ftable .tj');"
                    "if(t)t.focus();}")
                pg.keyboard.press(" "); pg.wait_for_timeout(400)
                ck("tj Space 跳走势不误开比价", pg.evaluate(
                   "()=>document.querySelector('#montab-trend')"
                   ".style.display===''&&EXP===null"))
                pg.click('.mtab[data-t="details"]'); pg.wait_for_timeout(300)
                # 跳转把 CHR[nm].i 锚到明细行航线并随 saveUI 持久化，
                # reload 后日历/走势渲染该航线——复位回默认航线，
                # 后续依赖初始视图态的断言（暗色日历 AA）不背状态污染
                pg.evaluate("()=>{for(const k in CHR){if(CHR[k]&&"
                            "typeof CHR[k]==='object')CHR[k].i=0;}saveUI();}")
            pg.set_viewport_size({"width": 1500, "height": 900})
            pg.wait_for_timeout(300)
            # --kpiw 流式 min(1168px,100%)——1440+ 宽容器下视觉
            # 封顶仍是 1168（grid 实际 max-width），断言读 .grid 实算值
            ck("1440 档 kpiw 封顶 1168", pg.evaluate(
                "()=>{const g=document.querySelector('.grid');"
                "return g&&Math.round(g.getBoundingClientRect().width)<=1170;}"))
            # 1440 断点缝收敛——非比例敏感件（statline/
            # pulsewrap/legend）随 1440 块解锁 max-width:none（几何跟卡
            # 实测 1500 概览 diff=38px；此处钉 computed 值不依赖当前视图
            # ——本断言点位于日历/走势段之后，display 翻转下几何不可靠）
            # r302 W1：四族同上限 min(1440px,100%)——「同拍」语义从恒
            # none 改为与 grid 同值，右缘恒等由 1920/1440 行为钉兜底
            ck("1500 档 statline 解锁（断点缝收敛）", pg.evaluate(
                "()=>{const g=document.querySelector('.grid');"
                "return g&&['.statline','.pulsewrap','#pulseLegend'].every("
                "s=>{const e=document.querySelector(s);return e&&"
                "getComputedStyle(e).maxWidth==="
                "getComputedStyle(g).maxWidth;});}"))
            pg.set_viewport_size({"width": 1280, "height": 900})
            # 切片渲染首拍只渲首 120 行，排序后 trendGo 行可能整体被
            # 切出首片——胶囊族断言先补全切片，锁「全表最低价行」而非
            # 「首片幸存数」
            pg.evaluate("()=>{while(_tblAppend()){}}")
            # 胶囊渲染（demo 每航线最低价行合成 trendGo）
            ck("胶囊 ≥3 行（3 航线最低价行）",
               len(pg.query_selector_all("#ftable .tg")) >= 3)
            cap = pg.query_selector("#ftable .tg")
            ck("胶囊文案 改期+最低￥", cap is not None and
               cap.inner_text().startswith("改期") and "最低￥" in cap.inner_text())
            ck("胶囊 ↓% 段（demo 最低点-15%）", cap is not None and
               "↓15%" in cap.inner_text())
            ck("胶囊 title 改期窗口语义", cap is not None and
               "改期窗口" in (cap.get_attribute("title") or ""))
            ck("胶囊键盘可达（tabindex+role）", cap is not None and
               cap.get_attribute("tabindex") == "0"
               and cap.get_attribute("role") == "button")
            ck("tgrow 预置隐藏（零插拔渲染）", pg.evaluate(
                "()=>{const t=[...document.querySelectorAll("
                "'#ftable tr.tgrow')];"
                "return t.length>=3&&t.every(x=>"
                "x.style.display==='none');}"))
            ck("非 trendGo 行无胶囊", pg.evaluate(
                "()=>document.querySelectorAll('#ftable .tg').length==="
                "document.querySelectorAll('#ftable tr.tgrow').length"))
            # 点击胶囊 → tgrow 展开（15 柱+三档类+轴）
            row = pg.evaluate(
                "()=>{const c=document.querySelector('#ftable .tg');"
                "c.click();const tr=c.closest('tr');"
                "const tg=tr.nextElementSibling;"
                "return {open:tg.style.display!=='none',"
                "bars:tg.querySelectorAll('.tgb').length,"
                "lo:!!tg.querySelector('.tgb.lo'),"
                "cheap:tg.querySelectorAll('.tgb.cheap').length,"
                "cur:!!tg.querySelector('.tgb.cur'),"
                "axis:tg.querySelector('.tgaxis').textContent,"
                "cls:tg.className};}")
            ck("点击胶囊 tgrow 展开", row["open"])
            ck("tgrow 类名 xrow tgrow", row["cls"] == "xrow tgrow")
            ck("15 柱齐全", row["bars"] == 15)
            ck("lo/cheap/cur 档齐全",
               row["lo"] and row["cheap"] > 0 and row["cur"])
            ck("三坐标轴含(出发)", "(出发)" in row["axis"])
            # 互斥：开比价收改期，开改期收比价
            st = pg.evaluate(
                "()=>{const c=document.querySelector('#ftable .tg');"
                "const tr=c.closest('tr');const tg=tr.nextElementSibling;"
                "const xr=tg.nextElementSibling;"
                "tr.click();const expOpen=xr.style.display!=='none';"
                "const tgClosed=tg.style.display==='none';"
                "c.click();"
                "return {expOpen,tgClosed,"
                "tgReopen:tg.style.display!=='none',"
                "xrClosed:xr.style.display==='none',"
                "TG:TGOPEN!==null,EXP:EXP===null};}")
            ck("同行开比价收改期", st["expOpen"] and st["tgClosed"])
            ck("再开改期收比价", st["tgReopen"] and st["xrClosed"]
               and st["TG"] and st["EXP"])
            # 10s 重建保态：TGOPEN===k 渲染为展开
            ck("table() 重建保 tgrow 开态", pg.evaluate(
                "()=>{table();const c=document.querySelector("
                "'#ftable .tg');"
                "return c.closest('tr').nextElementSibling"
                ".style.display==='';}"))
            pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
            ck("Esc 收改期行", pg.evaluate(
                "()=>[...document.querySelectorAll('#ftable tr.tgrow')]"
                ".every(x=>x.style.display==='none')")
               and pg.evaluate("()=>TGOPEN===null"))
            # togRow 回归：tgrow 行点行体开的是比价行（跳过 tgrow）
            ck("tgrow 行点行体开比价（跳过 tgrow）", pg.evaluate(
                "()=>{const c=document.querySelector('#ftable .tg');"
                "const tr=c.closest('tr');const tg=tr.nextElementSibling;"
                "const xr=tg.nextElementSibling;"
                "tr.click();const ok=xr.style.display!=='none'"
                "&&tg.style.display==='none'&&EXP!==null;"
                "EXP=null;xr.style.display='none';return ok;}"))
            # ---- 胶囊键盘（P2-1 回归钉）：Enter/Space 开微图且不冒泡
            #      成比价行（行内联 onkeydown 会被冒泡触发拆台） ----
            ck("胶囊 Enter 开微图（stopPropagation 不冒泡）", pg.evaluate(
                "()=>{const c=document.querySelector('#ftable .tg');"
                "c.focus();const ev=new KeyboardEvent('keydown',"
                "{key:'Enter',bubbles:true,cancelable:true});"
                "c.dispatchEvent(ev);"
                "const tr=c.closest('tr');const tg=tr.nextElementSibling;"
                "const xr=tg.nextElementSibling;"
                "const ok=tg.style.display!=='none'"
                "&&xr.style.display==='none'&&TGOPEN!==null;"
                "TGOPEN=null;tg.style.display='none';return ok;}"))
            # ---- 同组双胶囊（P1-1 回归钉）：展开态键必须带行实例维度
            #      （同物理班跨渠道两行共用 fp 分组键，曾首点假死+残留）；
            #      改共享 S 先例造双行，按 filteredRows 索引定位两行，
            #      测毕自复位（越界即红防假绿） ----
            ck("双胶囊组 各行独立展开互斥收对侧", pg.evaluate(
                "()=>{const u=S.users[U];"
                "const f0=u.flights.find(x=>(x.trendGo||[]).length>0);"
                "if(!f0)return false;"
                "const f2=JSON.parse(JSON.stringify(f0));"
                "f2.plat=f2.plat==='去哪儿'?'同程':'去哪儿';"
                # 切片下 DOM 行=首 120：双行索引对齐 filteredRows 前先补全切片
                "u.flights.unshift(f2);table();while(_tblAppend()){}"
                "const rows=filteredRows();"
                "const i2=rows.indexOf(u.flights[0]),i0=rows.indexOf(f0);"
                "const trs=document.querySelectorAll("
                "'#ftable tbody tr[data-k]');"
                "const bad=i2<0||i0<0||i2>=trs.length||i0>=trs.length;"
                "if(bad){u.flights.shift();table();return false;}"
                "const c1=trs[i2].querySelector('.tg'),"
                "c2=trs[i0].querySelector('.tg');"
                "if(!c1||!c2){u.flights.shift();table();return false;}"
                "c1.click();"
                "const tg1=trs[i2].nextElementSibling;"
                "const open1=tg1.classList.contains('tgrow')"
                "&&tg1.style.display!=='none';"
                "c2.click();"
                "const tg2=trs[i0].nextElementSibling;"
                "const ok=open1&&tg2.classList.contains('tgrow')"
                "&&tg2.style.display!=='none'"
                "&&tg1.style.display==='none';"
                "TGOPEN=null;u.flights.shift();table();return ok;}"))

            # ---- 改期微图盒约束 + 图例 + 新字段次行段 ----
            # .tgbox 须 display:block（span 内联不吃 max-width，漏则
            # 15 柱拉伸成整表宽）
            ck("tgbox 宽度≤462px（内联 max-width 修复）", pg.evaluate(
                "()=>{const c=document.querySelector('#ftable .tg');"
                "c.click();const el=document.querySelector('.tgbox');"
                "const w=el?el.getBoundingClientRect().width:-1;"
                "c.click();"
                "return w>0&&w<=462;}"))
            ck("微图图例行（与达标线无关撇清）", pg.evaluate(
                "()=>{const c=document.querySelector('#ftable .tg');"
                "c.click();const l=document.querySelector('.tgleg');"
                "const ok=!!l&&l.textContent.indexOf('绿=窗口最低')===0"
                "&&l.textContent.indexOf('与达标线无关')>0;"
                "return ok;}"))
            pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
            ck("Esc 收改期行（新字段段后复位）", pg.evaluate(
                "()=>[...document.querySelectorAll('#ftable tr.tgrow')]"
                ".every(x=>x.style.display==='none')"))
            det = pg.evaluate(
                "()=>document.querySelector('#ftable tbody').innerText")
            ck("中转航站楼段（换乘·新郑T2）", "换乘·新郑T2" in det)
            ck("余票数段（余3张）", "余3张" in det)
            ck("飞猪余票紧张（少量）", "少量" in det)
            ck("到达航站楼段（机场+楼号·码旁注）",
               "天山T1 (URC)" in det or "天山T2 (URC)" in det
               or "虹桥T1 (SHA)" in det or "虹桥T2 (SHA)" in det)

            # ---- CSV 导出 ----
            step("csv download")
            pg.evaluate("()=>{const fb=document.querySelector('.fbar');"
                        "if(fb&&getComputedStyle(fb).display==='none')togFlt();}")
            pg.wait_for_timeout(250)
            with pg.expect_download() as dl_info:
                pg.click("text=⬇ 导出CSV")
            ck("CSV 导出", dl_info.value.suggested_filename.endswith(".csv"))
            # 孤低价/改期最低两列入档（页面可见信号不跨媒质丢失）
            try:
                import csv as _csv
                with open(dl_info.value.path(), encoding="utf-8-sig",
                          newline="") as f:
                    _rd = list(_csv.reader(f))
                _head = _rd[0]
                ck("CSV 双新列（孤低价/改期最低）",
                   "孤低价" in ",".join(_head)
                   and "改期最低" in ",".join(_head))
                # 改期最低列数据行值=数字或空串（P0 回归钉：箭头函数
                # 曾漏调用括号，整列落函数源码字符串）
                _tgi = _head.index("改期最低")
                ck("CSV 改期最低列值为数字或空", all(
                    row[_tgi] == "" or row[_tgi].isdigit()
                    for row in _rd[1:] if len(row) > _tgi))
            except Exception:
                ck("CSV 双新列（孤低价/改期最低）", False)
                ck("CSV 改期最低列值为数字或空", False)

            # ---- 主题 / 通知 ----
            t0 = pg.evaluate("localStorage.getItem('jptheme')||'auto'")
            pg.click("#themeBtn"); pg.wait_for_timeout(300)
            ck("主题切换", pg.evaluate(
                "localStorage.getItem('jptheme')||'auto'") != t0)
            nt0 = pg.get_attribute("#ntBtn", "aria-pressed")
            pg.click("#ntBtn"); pg.wait_for_timeout(200)
            ck("通知开关", pg.get_attribute("#ntBtn", "aria-pressed") != nt0)
            pg.click("#ntBtn")

            # ---- toast / 内联二次确认（v2.0 交互） ----
            step("arming + toast")
            btn = pg.query_selector("text=立即扫描一轮")
            ck("动作按钮存在", btn is not None)
            if btn:
                btn.click(); pg.wait_for_timeout(300)
                arm = pg.query_selector("button.arming")
                ck("危险按钮确认态", arm is not None
                   and "再点一次" in arm.inner_text())
                if arm:
                    arm.click(); pg.wait_for_timeout(700)
                    ck("toast 出现",
                       len(pg.query_selector_all("#toasts .toast")) >= 1)
            # toast 可点击关闭须有 hover 反馈（.pvx 同语言；
            # var() 引用走 cssText 序列化——属性级 getter 对 var 不可靠）
            ck("toast hover 反馈", pg.evaluate(
                "()=>{for(const sh of document.styleSheets){"
                "try{for(const r of sh.cssRules){"
                "if(r.selectorText==='.toast:hover')"
                "return r.style.cssText.replace(/\\s/g,'')"
                ".includes('background:var(--hover)');}}catch(e){}}"
                "return false;}"))
            ck("KPI 数字锚点",
               len(pg.query_selector_all("a.numlink[data-v]")) >= 1)
            ck("favicon 就位", pg.evaluate(
                "()=>!!document.querySelector('link[rel=icon]')"))
            # r368：单用户以吸顶用户 chip 常显当前范围（多用户再加 pills 行）
            ck("单用户显示用户范围", pg.is_visible("#mtabUser")
               and "👤" in (pg.inner_text("#mtabUser") or ""))

            # ---- V50 快捷键 ----
            pg.keyboard.press("2"); pg.wait_for_timeout(500)
            ck("快捷键 2 切配置", pg.is_visible("#cfgview"))
            pg.keyboard.press("1"); pg.wait_for_timeout(400)
            ck("快捷键 1 切监控", pg.is_visible("#monview"))
            pg.keyboard.press("/"); pg.wait_for_timeout(300)
            ck("快捷键 / 聚焦搜索", pg.evaluate(
                "()=>document.activeElement&&"
                "document.activeElement.id==='fq'"))
            pg.evaluate("document.activeElement&&document.activeElement.blur()")
            pg.keyboard.press("r"); pg.wait_for_timeout(300)
            ck("快捷键 R 两段确认", any(
                "再按一次" in t.inner_text()
                for t in pg.query_selector_all("#toasts .toast")))

            # ---- 移动端抽屉 ----
            pg.set_viewport_size({"width": 390, "height": 844})
            pg.wait_for_timeout(400)
            ck("390 无横向滚动", pg.evaluate(
                "document.documentElement.scrollWidth") <= 391)
            pg.evaluate("showMonTab('health')"); pg.wait_for_timeout(250)
            ck("390 来源接入板单列无溢出", pg.evaluate(
                "()=>{const e=document.getElementById('srccap');"
                "return e.scrollWidth<=e.clientWidth+1;}"))
            ck("390 来源接入节点不拉高", pg.evaluate(
                "()=>{const ns=[...document.querySelectorAll('#srccap .scnode')];"
                "return ns.length===3&&ns.every(n=>n.getBoundingClientRect().height<=90);}"))
            ck("390 来源接入按钮 32 地板", pg.evaluate(
                "()=>{const b=document.querySelector('#srccap .scbtn:not([hidden])');"
                "return !!b&&b.getBoundingClientRect().height>=32;}"))
            ck("390 来源接入 H5 CTA 不被箭头遮挡", pg.evaluate(
                "()=>{const b=document.querySelector('#srccap .scbtn.ghost');"
                "if(!b)return false;const r=b.getBoundingClientRect();"
                "const el=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);"
                "return el===b||b.contains(el);}"))
            pg.evaluate("showMonTab('overview')"); pg.wait_for_timeout(200)
            # r219 P1-1：概览 kpisum 内联链（查看明细 ▾/走势 ▾）触控
            # 热区实体扩张（inline 垂直 padding 纯扩命中区不占布局）——
            # ::after 外扩不计 bounding box，36 地板以盒高验收；量纲
            # 断言先落概览 tab，量完复位明细（视图上下文律）
            pg.evaluate("showMonTab('overview')")
            pg.wait_for_timeout(200)
            ck("390 kpisum 链触控高 36 地板", pg.evaluate(
                "(()=>{const a=document.querySelector('.kpisum a');"
                "return !!a&&a.getBoundingClientRect().height>=36;})()"))
            pg.evaluate("showMonTab('details')")
            pg.wait_for_timeout(200)
            ck("筛选抽屉按钮", pg.is_visible("#fltBtn"))
            pg.evaluate("()=>{const fb=document.querySelector('.fbar');"
                        "if(fb&&fb.classList.contains('open'))setFltOpen(false);}")
            pg.wait_for_timeout(150)
            pg.click("#fltBtn"); pg.wait_for_timeout(300)
            ck("抽屉展开", "open" in (pg.get_attribute(".fbar", "class") or ""))
            # ---- ≤760 图例/柱簇同轴（computed 值不随 display 翻转）
            # 与头部 .pill（唯一 jumpQual 入口）36px 触控热区 ----
            ck("窄档图例同轴居中", pg.evaluate(
                "()=>getComputedStyle(document.getElementById('pulseLegend'))"
                ".justifyContent==='center'"))
            ck("窄档 pill 触控热区", pg.evaluate(
                "()=>getComputedStyle(document.querySelector('.pill'))"
                ".minHeight==='36px'"))
            # ---- savebar 实高动态单源 --sbh（r264）：toast 抬升
            # 量「底在 savebar 顶之上」的相对关系（恒差呼吸缝 ≥8px），
            # 不锁绝对值——固定值断言在动态化当日即成假钉
            # （LESSONS 二十一§7）；savebar 收起回 96px 基础位 ----
            ck("移动端 toast 避让 header/savebar（r346）", pg.evaluate(
                "()=>{toast('探针');const t=document.querySelector('.toast');"
                "const tr=t.getBoundingClientRect();"
                "const hb=document.querySelector('header').getBoundingClientRect().bottom;"
                "const sb=document.getElementById('savebar');"
                "sb.classList.add('on');"
                "const sr=sb.getBoundingClientRect();"
                "sb.classList.remove('on');"
                "t.remove();"
                "return tr.top>=hb-1&&tr.bottom<sr.top-4;}"))
            # ---- 筛选角标全选不计（dates 全选回填=零筛选，
            # 否则幻影「筛选 1」；与 plats/routes 守卫同构。全程自复位） ----
            ck("筛选角标全选不计", pg.evaluate(
                "()=>{const u=S.users[U];const el=document.getElementById('fltN');"
                "const ds=[...new Set(u.flights.map(f=>f.date).filter(Boolean))];"
                "if(ds.length<2)return true;"
                "FLT.dates=new Set(ds);updFltN();"
                "const fullHidden=el.style.display==='none';"
                "FLT.dates=new Set([ds[0]]);updFltN();"
                "const oneShown=el.style.display!=='none'&&el.textContent==='1';"
                "FLT.dates=new Set(ds);updFltN();"
                "return fullHidden&&oneShown;}"))
            # ---- 健康时间线 xhint 判定若发生在隐藏容器
            # （首渲 sw=0 恒 false，「默认加载→点健康」主路径死档）——
            # 清类后经 showMonTab 切回须补拍挂回 ----
            pg.evaluate("setFltOpen(false)")   # 收起抽屉复位（显式闭合，防状态翻转）
            pg.evaluate("document.querySelectorAll('.hcells')"
                        ".forEach(x=>x.classList.remove('xhint'));"
                        "showMonTab('overview')")
            pg.wait_for_timeout(200)
            pg.evaluate("showMonTab('health')")
            pg.wait_for_timeout(300)
            ck("健康 xhint 切回补拍", pg.evaluate(
                "()=>{const x=document.querySelector('.hcells');"
                "return !!x&&x.scrollWidth>x.clientWidth+4"
                "&&x.classList.contains('xhint');}"))
            # ---- 健康格触控热区不被 overflow 裁剪（.hcells overflow-x
            # auto 强制 overflow-y auto，::after 纵向外扩落裁剪区外=热区
            # 形同虚设+隐藏纵滚；修法=容器 padding 外衬+事件穿透）----
            # v1.5.274：健康页激活会自动滚到最新轮，首格可能已在屏外左侧；
            # 热区判据与滚动位无关，先复位再取首格
            pg.evaluate("()=>{const x=document.querySelector('.hcells');"
                        "if(!x)return;x.scrollLeft=0;"
                        "const c=x.querySelector('.hc');"
                        "if(c)c.scrollIntoView({block:'center'});}")
            pg.wait_for_timeout(200)
            ck("健康格热区 37px 可达", pg.evaluate(
                "()=>{const x=document.querySelector('.hcells');"
                "if(!x)return false;const c=x.querySelector('.hc');"
                "if(!c)return false;const r=c.getBoundingClientRect();"
                "const el=document.elementFromPoint(r.x+r.width/2,r.y-10);"
                "const hit=el===c||(el&&c.contains(el));"
                "return hit&&(x.scrollHeight-x.clientHeight)<=1;}"))
            # ---- 明细表切片续载 End 跳底（≤540 档明细跟页滚架构：
            # .tw 放开内滚、tabs 吸顶可达，End=显式补全量+页面滚底+
            # 末行焦点交接，不依赖滚动事件接力——「补片推远底边打断
            # 平滑滚动」判例的页滚档投影）----
            pg.evaluate("showMonTab('details')"); pg.wait_for_timeout(400)
            pg.evaluate("(()=>{const tw=document.querySelector("
                        "'#tablecard .tw');const r="
                        "tw.querySelector('tbody tr[data-k]');"
                        "if(r)r.focus();})()")
            pg.keyboard.press("End"); pg.wait_for_timeout(600)
            ck("明细 End 跳底切片补齐", pg.evaluate(
                "(()=>{const tw=document.querySelector('#tablecard .tw');"
                "const rows=tw.querySelectorAll('tbody tr[data-k]');"
                "const m=(document.getElementById('fcnt').textContent"
                ".match(/(\\d+) 条报价/)||[])[1];"
                "const last=rows.length?rows[rows.length-1]:null;"
                "const nearBottom=document.documentElement.scrollHeight"
                "-window.innerHeight-window.scrollY<=300;"
                "return !!m&&rows.length===+m&&!!last&&"
                "document.activeElement===last&&nearBottom;})()"))
            # ---- ≤540 sticky 吸顶行为钉：.tw 放开内滚后页面可滚至
            # 触发点——旧架构下源码钉绿而 sticky 是死代码（触发点滚动
            # 821px > 页面最大滚动 756px），几何行为钉是唯一真相。
            # 视图切换器 montabs 吸顶贴 header 实高底（top=var(--hdh)
            # 动态单源）；明细筛选条 top 联动 var(--hdh)+--mtabsh(52)
            # （吸顶双条不重叠）----
            pg.evaluate("window.scrollTo(0,900)"); pg.wait_for_timeout(300)
            ck("390 montabs 吸顶贴 header 底", pg.evaluate(
                "(()=>{const t=document.getElementById('montabs'),"
                "h=document.querySelector('header');"
                "if(!t||!h)return false;"
                "const m=t.getBoundingClientRect().top,"
                "b=h.getBoundingClientRect().bottom;"
                "return m>=b-2&&m<=b+6;})()"))
            # 触控高 36 地板：#montabs .mtab 的 ID 特异性 (1,1,0) 恒压
            # .tabs .mtab 触控增强块，竖向 padding 由本档块自承（9px）
            ck("390 montabs 触控高 36 地板", pg.evaluate(
                "(()=>{const m=document.querySelector('#montabs .mtab');"
                "return !!m&&m.getBoundingClientRect().height>=36;})()"))
            # 吸顶条满血铺贴：左缘归零（负 margin 随 390 档 wrap padding
            # 10px 联动）且右缘贴 .wrap 边盒右。参照系=wrap 边盒非
            # innerWidth——桌面内核的样式化竖滚条吃布局宽（html 380@390
            # 视口），真机 overlay 滚条不占宽，wrap 右在两种语境都是
            # 满血基准
            ck("390 montabs 吸顶条满血铺贴", pg.evaluate(
                "(()=>{const t=document.getElementById('montabs'),"
                "w=document.querySelector('.wrap');"
                "if(!t||!w)return false;"
                "const r=t.getBoundingClientRect(),"
                "wr=w.getBoundingClientRect();"
                "return r.left>=-0.5&&r.left<=1&&"
                "Math.abs(r.right-wr.right)<=1;})()"))
            ck("390 明细 tabs 吸顶贴切换器底", pg.evaluate(
                "(()=>{const t=document.querySelector("
                "'#montab-details .tabs'),"
                "m=document.getElementById('montabs');"
                "if(!t||!m)return false;"
                "return Math.abs(t.getBoundingClientRect().top"
                "-m.getBoundingClientRect().bottom)<=3;})()"))
            # 吸顶条单行化（旧吸顶态 3 行高 131px 占屏 ~31%）：高 ≤60、
            # 图例隐藏（语义并入 fltBtn title）
            ck("390 吸顶筛选条单行化", pg.evaluate(
                "(()=>{const t=document.querySelector("
                "'#montab-details .tabs');const b=t&&t.querySelector"
                "('b.muted');return !!t&&t.getBoundingClientRect().height"
                "<=60&&!!b&&getComputedStyle(b).display==='none';})()"))
            # P1-W1 明细吸顶条横滚暗示+筛选入口常在：可滚时 xhint
            # 点亮（::after 渐隐装饰层 opacity 1——非容器 mask，
            # mask 会把 sticky 入口一起淡出）；fltBtn sticky 钉可视
            # 右缘（筛选抽屉 ≤760 唯一入口，不依赖滚动可达）
            ck("390 明细条横滚暗示 xhint 点亮", pg.evaluate(
                "(()=>{const t=document.querySelector("
                "'#montab-details .tabs');"
                "return !!t&&t.classList.contains('xhint')&&"
                "t.scrollWidth>t.clientWidth+4&&"
                "getComputedStyle(t,'::after').opacity==='1';})()"))
            ck("390 fltBtn 常在视口内", pg.evaluate(
                "(()=>{const b=document.getElementById('fltBtn');"
                "if(!b)return false;const r=b.getBoundingClientRect();"
                "return r.left>=0&&r.right<=document.documentElement."
                "clientWidth&&r.width>0;})()"))
            # 深滚位开抽屉落点可见（入口吸顶、面板留文档流原位曾落
            # 视口上方 ~1000px+滚动锚定抵消位移=按钮无响应观感；
            # setFltOpen 开方向把面板顶拉到吸顶筛选条下缘。-2 容差：
            # 亚像素取整；vin 入场动画首帧 translateY 曾污染量测使
            # 校正恒欠 4px（旧 6px 容差恰好吞掉），源码侧量测已剔
            # transform 位移，钉随真值收紧——容差放宽回 6 会重新
            # 掩护欠校正回归）
            pg.evaluate("window.scrollTo(0,1510)"); pg.wait_for_timeout(300)
            pg.evaluate("()=>{const fb=document.querySelector('.fbar');"
                        "if(fb&&fb.classList.contains('open'))setFltOpen(false);}")
            pg.click("#fltBtn"); pg.wait_for_timeout(400)
            ck("390 深滚开抽屉落点可见", pg.evaluate(
                "(()=>{const f=document.querySelector('.fbar');"
                "if(!f||!f.classList.contains('open'))return false;"
                "const t=document.querySelector('#montab-details .tabs');"
                "return f.getBoundingClientRect().top>="
                "t.getBoundingClientRect().bottom-2&&"
                "f.getBoundingClientRect().top<window.innerHeight;})()"))
            # CTA 贴底工具条：底缘与视口齐平（不留 12px 缝隙漏内容），
            # 抽屉尾部让位 ≥60px，最后一行可完整滚到 CTA 上方。
            ck("390 筛选 CTA 贴底且抽屉末行让位", pg.evaluate(
                "(()=>{const c=document.querySelector('.fdrawer-cta');"
                "const f=document.querySelector('.fbar.open');"
                "if(!c||!f)return false;"
                "return Math.abs(c.getBoundingClientRect().bottom"
                "-window.innerHeight)<=1"
                "&&parseFloat(getComputedStyle(f).paddingBottom)>=60;})()"))
            pg.evaluate("setFltOpen(false)")   # 收起抽屉复位（显式闭合，防状态翻转）
            # Esc 同拍回收：toast 分支序在展开行之后——toast 驻留期
            # 按 Esc 曾只关 toast（return 早退），展开行要等 toast
            # 自然消散（toast 只读即点即关，不得挡内容态回收）
            pg.evaluate("showMonTab('overview')"); pg.wait_for_timeout(300)
            ck("390 Esc 展开行+toast 同拍回收", pg.evaluate(
                "(()=>{const rows=document.querySelectorAll("
                "'#ftable tbody tr[data-k]');"
                # 空表=fixture 退化，静默恒绿即假绿失保护
                "if(!rows.length)return false;"
                "rows[0].click();toast('esc-t');"
                "const vis=[...document.querySelectorAll("
                "'#ftable tr.xrow')].filter(x=>x.style.display!=='none')"
                ".length;const ts=document.querySelectorAll("
                "'#toasts .toast').length;"
                "window.__escBefore={vis,ts};return vis>0&&ts>0;})()"))
            pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
            ck("390 Esc 同拍回收生效", pg.evaluate(
                "(()=>{const vis=[...document.querySelectorAll("
                "'#ftable tr.xrow')].filter(x=>x.style.display!=='none')"
                ".length;return vis===0&&"
                "document.querySelectorAll('#toasts .toast').length===0;"
                "})()"))
            pg.evaluate("showMonTab('overview')")   # 状态复位回概览
            pg.wait_for_timeout(200)
            # ---- 走势 y 轴标签满血正面钉（390 档）：y 轴「￥2000」类
            # 标签被截成尾二字（「00」）时左缘前缀区像素归零——本钉
            # getImageData 量 27px 前缀区有无笔迹（非空白版全画布判，
            # 后者抓不住「图在但标签截断」）。前提：现实价带 100~50000
            # 下 y 轴标签 ≥「￥100」5 字符、绘制起点 x=6，笔迹必入
            # 27px 带（更短标签才可能假红）。uitest 全程零截图：截图
            # 链路的 CDP metrics 会扰动 canvas 重绘时序产出截断伪影
            # （探针伪影非真实缺陷），canvas 字面断言勿与截图同页 ----
            pg.evaluate("showMonTab('trend')"); pg.wait_for_timeout(2500)
            ck("390 走势 y 轴标签满血", pg.evaluate(
                "(()=>{const c=document.getElementById('chart');"
                "if(!c||!c.offsetWidth)return false;"
                "const d=c.getContext('2d').getImageData("
                "0,0,27,c.height).data;"
                "for(let i=3;i<d.length;i+=4){if(d[i]>0)return true;}"
                "return false;})()"))
            pg.evaluate("showMonTab('overview')")   # 状态复位回概览
            pg.wait_for_timeout(200)
            # ---- glcell 文本输入窄屏 16px 防放大 ----
            # （内联 13px 锁定须 !important 压制——iOS 聚焦自动放大且
            # 不回位；桌面档 13px 观感由 globals 段反面钉守护）
            pg.evaluate("()=>switchView('cfg')"); pg.wait_for_timeout(500)
            pg.click('#cfgnav .cnav[data-p="globals"]')
            pg.wait_for_timeout(400)
            # 选中态悬停反馈第三样本（配置导航选中片，.cnav.on:hover
            # 族成员行为钉——源码钉验不了层叠胜负）
            pg.hover('#cfgnav .cnav.on'); pg.wait_for_timeout(120)
            ck("配置导航选中片悬停反馈", pg.evaluate(
                "()=>{const e=document.querySelector('#cfgnav .cnav.on');"
                "return !!e&&getComputedStyle(e)"
                ".filter.indexOf('brightness')===0;}"))
            ck("390 glcell 文本 16px", pg.evaluate(
                "()=>{const e=document.getElementById('glbUa');"
                "return !!e&&getComputedStyle(e).fontSize==='16px';}"))
            # 新钉自带状态复位（CHR.i 同律）：CFGPANEL 复位回默认
            # login，防污染后续「面板互斥：登录显」断言
            pg.click('#cfgnav .cnav[data-p="login"]')
            pg.wait_for_timeout(300)
            pg.evaluate("()=>switchView('mon')"); pg.wait_for_timeout(300)
            # ---- 320 档：六视图、横向溢出、图标/文字与层级 ----
            pg.set_viewport_size({"width": 320, "height": 844})
            pg.evaluate("showMonTab('overview')")
            pg.wait_for_timeout(350)
            ck("320 无横向滚动", pg.evaluate(
                "document.documentElement.scrollWidth") <= 321)
            ck("320 六视图全部在视口内", pg.evaluate(
                "()=>{const ns=[...document.querySelectorAll('#montabs .mtab')];"
                "if(ns.length<6)return false;"
                "return ns.every(n=>{const r=n.getBoundingClientRect();"
                "return r.width>20&&r.left>=-1&&r.right<=innerWidth+1;});}"))
            ck("320 切换器 3×2 网格", pg.evaluate(
                "()=>{const s=getComputedStyle(document.getElementById('montabs'));"
                "return s.display==='grid'&&s.gridTemplateColumns.split(' ').length===3;}"))
            ck("320 头部状态 pill 不裁字", pg.evaluate(
                "()=>{const p=document.querySelector('.pill');if(!p)return true;"
                "const s=getComputedStyle(p);return s.overflow==='visible'"
                "&&s.textOverflow==='clip'&&s.whiteSpace==='normal';}"))
            ck("toast 层级高于登录弹层", pg.evaluate(
                "()=>parseInt(getComputedStyle(document.getElementById('toasts')).zIndex||0)"
                ">parseInt(getComputedStyle(document.getElementById('lgMask')).zIndex||0)"))
            pg.evaluate("showMonTab('health')"); pg.wait_for_timeout(300)
            ck("健康状态不只靠颜色", pg.evaluate(
                "()=>{const p=document.querySelector('.hc.part'),f=document.querySelector('.hc.fail');"
                "if(!p||!f)return true;"
                "return getComputedStyle(p).backgroundImage!==getComputedStyle(f).backgroundImage;}"))
            pg.evaluate("showMonTab('overview')"); pg.wait_for_timeout(200)
            # ---- 审计 P2 行为固防（源码钉只验「声明在场」，层叠胜负
            # 与断点档位由 computed 行为钉定谳）----
            # 391-509 截断带中点 450px：ssub「时间戳 · 用时」复合信息
            # 换行放行（省略号裁掉用时尾段=信息丢失）
            pg.set_viewport_size({"width": 450, "height": 844})
            pg.wait_for_timeout(300)
            ck("450 ssub 换行放行", pg.evaluate(
                "()=>{const e=document.querySelector('.stat .ssub');"
                "return !!e&&getComputedStyle(e).whiteSpace==='normal';}"))
            # 生产态 hdmeta（下轮倒计时在场）窄机折行放行
            # （cdt+updated 双元素 nowrap 临界溢出、360px 必溢）
            ck("450 hdmeta 折行放行", pg.evaluate(
                "()=>{const e=document.querySelector('.hdmeta');"
                "return !!e&&getComputedStyle(e).flexWrap==='wrap';}"))
            # resize 防抖回调重判健康格滚动暗示（几何变化点补拍，
            # 与 showMonTab 切回补拍同式）——清类后派发 resize，
            # 断言「可滚性↔暗示类」一致（不依赖样本是否真横滚）
            pg.evaluate("showMonTab('health')")
            pg.wait_for_timeout(200)
            pg.evaluate("document.querySelectorAll('.hcells')"
                        ".forEach(x=>x.classList.remove('xhint'));"
                        "window.dispatchEvent(new Event('resize'))")
            pg.wait_for_timeout(400)
            ck("resize 后 xhint 重判", pg.evaluate(
                "()=>{const x=document.querySelector('.hcells');"
                "return !!x&&(x.scrollWidth>x.clientWidth+4)"
                "===x.classList.contains('xhint');}"))
            # ---- r224 P1-2 行为钉：mkact 不打穿 roving 初态——健康格/
            # 脉冲柱模板带 tabindex 0/-1（每族首格可停靠）且
            # role="button" 命中 mkactAll，旧无条件 tabIndex=0 在内联
            # onkeydown 早退之前把 -1 族改写（族内逐格 Tab 回归）。
            # 健康格是懒渲染件、mkactAll 是否触达随渲染时序浮动——
            # 单元直调 mkact 验行为本质（LESSONS 十九§14）：带属性者
            # 不改写、无属性者补 0 ----
            ck("mkact 保模板 tabindex", pg.evaluate(
                "()=>{const a=document.createElement('i');"
                "a.setAttribute('tabindex','-1');mkact(a);"
                "const b=document.createElement('i');mkact(b);"
                "const c=document.createElement('i');"
                "c.setAttribute('tabindex','0');mkact(c);"
                "return a.getAttribute('tabindex')==='-1'"
                "&&b.getAttribute('tabindex')==='0'"
                "&&c.getAttribute('tabindex')==='0';}"))
            # 单格族无 roving 面（demo 极端小数据边界）：格数 <2 跳过
            ck("roving -1 初态在场", pg.evaluate(
                "()=>{const el=[...document.querySelectorAll("
                "'[role=\"button\"][tabindex]')];"
                "if(el.length<2)return true;"
                "return el.some(e=>e.getAttribute('tabindex')==='-1');}"))
            pg.evaluate("showMonTab('overview')")
            pg.wait_for_timeout(200)
            pg.set_viewport_size({"width": 1280, "height": 900})
            pg.wait_for_timeout(200)
            # >901 粗指针触控清单（iPad Pro 横屏 1366 落带）——CDP
            # 触屏模拟令 pointer:coarse 生效，computed 验姊妹块
            # 清单真实生效（setEmulatedMedia features 不支持 pointer）
            _cdp = pg.context.new_cdp_session(pg)
            _cdp.send('Emulation.setTouchEmulationEnabled',
                      {'enabled': True, 'maxTouchPoints': 5})
            pg.set_viewport_size({"width": 1366, "height": 1024})
            pg.wait_for_timeout(300)
            ck("1366 coarse 触控清单生效", pg.evaluate(
                "()=>{const c=document.querySelector('.cnav');"
                "const h=document.querySelector('.hbtn');"
                "return !!c&&!!h"
                "&&getComputedStyle(c).paddingTop==='10px'"
                "&&getComputedStyle(c).paddingLeft==='14px'"
                "&&getComputedStyle(h).minHeight==='36px';}"))
            ck("1366 coarse 裸 button 36px", pg.evaluate(
                "()=>{const b=[...document.querySelectorAll('button')]"
                ".find(x=>!x.className);"
                "return !!b&&getComputedStyle(b).minHeight==='36px';}"))
            # P2-2 行为钉：nav span 触控 36 地板（三触控块同律，本档
            # 实测视高——inline 元素 min-height 须 flex 化才生效）
            ck("1366 coarse nav span 36px 地板", pg.evaluate(
                "()=>{const n=document.querySelector('nav span');"
                "return !!n&&n.getBoundingClientRect().height>=36;}"))
            # ---- 触控横向热区近邻映射 + 未扫描格假手型
            # （M-1）：健康格/脉冲柱横向仅 4-9px 且缝缘命中邻格
            # （::after 吃缝 off-by-one，点格 N 右缘修正带系统性开到
            # N+1 日志）。coarse 指针下容器捕获阶段按点击 x 到动作格
            # 本体矩形的距离最近邻重判（等距取先遍历=左格）；覆写
            # showLog 只记录不弹层，测毕清覆写+指针复位
            pg.evaluate("showMonTab('health')")
            pg.wait_for_timeout(300)
            # P3-1 行为钉：>901 coarse 健康格 9px 触控地板（弹性带
            # flex 均分 8.4px 欠标、基础 6px 更窄）+ 横滚恢复（coarse
            # 无 hover，clip 语言动机不在）——computed 验层叠胜者
            # （源码钉验不了媒体块胜负），量纲在 health tab 可见语境
            ck("1366 coarse 健康格 9px 地板+横滚恢复", pg.evaluate(
                "()=>{const c=document.querySelector('.hcells .hc');"
                "const w=document.querySelector('.hcells');"
                "return !!c&&!!w"
                "&&parseFloat(getComputedStyle(c).width)>=9"
                "&&getComputedStyle(w).overflowX==='auto';}"))
            pg.evaluate("window._hit=null;"
                "window._showLog0=window.showLog;"
                # null 防御与生产签名同律：playwright evaluate 注入语境
                # 存在一条 showLog(null) 幽灵调用（真机正常流零出现、
                # 生产 if(el&&el.dataset) 防御零害，r317 探针定谳），
                # 覆写体无防御会把幽灵调用炸成 evaluate 异常
                "window.showLog=(el)=>{window._hit=el&&el.dataset?el.dataset.p+'|'+el.dataset.ts:'';};")
            _tz = pg.evaluate("""()=>{
              const c=document.querySelector('.hcells');
              const cells=[...c.querySelectorAll('.hc')]
                .filter(x=>x.onclick&&!x.classList.contains('none'));
              if(cells.length<2)return null;
              const m=(cells[0].dataset.p!=null)?cells[0].dataset.p:'';
              const r=cells[0].getBoundingClientRect();window._hcCell=cells[0];
              return {x:r.right+1,y:r.top+r.height/2,
                want:m};}""")
            if _tz and _tz["want"]:
                pg.evaluate("()=>window._hcCell.click()")
                pg.wait_for_timeout(200)
                _hit1 = pg.evaluate("()=>window._hit||''")
                ck("coarse 缝缘点击近邻命中本格（off-by-one 修复）",
                   _hit1.split("|")[0] == _tz["want"], str(_tz) + " hit=" + _hit1)
            else:
                ck("coarse 缝缘点击近邻命中本格（off-by-one 修复）", False)
            # 非首行直击（Soldier P0-1 变异钉）：健康区多行同列，距离
            # 只算 X 维时跨行 d=0 平手塌向 DOM 序首行——直击第 3 行格
            # 中心必须命中本行（距离含 Y 维后直击行胜出）
            _tz2 = pg.evaluate("""()=>{
              const rows=[...document.querySelectorAll('.hcells')];
              if(rows.length<3)return null;
              const cells=[...rows[2].querySelectorAll('.hc')]
                .filter(x=>x.onclick&&!x.classList.contains('none'));
              if(!cells.length)return null;
              const r=cells[0].getBoundingClientRect();const m=(cells[0].dataset.p!=null)?cells[0].dataset.p:'';window._hcCell2=cells[0];
              return {x:r.left+r.width/2,y:r.top+r.height/2,
                want:m};}""")
            if _tz2 and _tz2["want"]:
                _hit2 = pg.evaluate("""()=>{window._hit=null;
                  const rows=[...document.querySelectorAll('.hcells')];
                  const c=[...rows[2].querySelectorAll('.hc')]
                    .find(x=>x.onclick&&!x.classList.contains('none'));
                  if(!c)return '';
                  c.onclick();return window._hit||'';}""")
                ck("coarse 非首行直击命中本行（跨行塌陷修复）",
                   _hit2.split("|")[0] == _tz2["want"], str(_tz2) + " hit=" + _hit2)
            else:
                ck("coarse 非首行直击命中本行（跨行塌陷修复）", False)
            pg.evaluate("window.showLog=window._showLog0;"
                "window._hit=null;window._showLog0=null;"
                "showMonTab('overview')")
            pg.wait_for_timeout(200)
            ck("未扫描格无假手型", pg.evaluate(
                """()=>{
                  const c=document.querySelector('.hcells .hc:not(.none)');
                  if(!c)return false;
                  const t=c.cloneNode(false);
                  t.className='hc none';t.removeAttribute('style');
                  c.parentNode.insertBefore(t,c);
                  const v=getComputedStyle(t).cursor==='default';
                  t.remove();return v;}"""))
            _cdp.send('Emulation.setTouchEmulationEnabled',
                      {'enabled': False})   # 状态复位回桌面指针
            pg.set_viewport_size({"width": 1280, "height": 900})
            pg.wait_for_timeout(200)
            # ---- 幽灵坐标轴守卫：已配置未扫描航线
            # （hist 空 + th 在场）走势 tab 必须出空态文案——阈值并入
            # 量纲源后 vals 恒非空、空态分支永不可达，首轮扫描前打开
            # 走势是只有达标虚线的空坐标系（服务端对未扫描航线照常
            # 产出 routes_arr，生产可达）。改共享 S 测毕自复位
            pg.evaluate("window._SArr=S.users[U].routesArr;")
            pg.evaluate("""()=>{
              const r0=window._SArr[0];
              S.users[U].routesArr=[{label:r0.label,date:r0.date,
                th:{direct:1900,transfer:2000},
                history:{direct:[],transfer:[]},
                history7:{direct:[],transfer:[]},cal:[]}];}""")
            pg.evaluate("showMonTab('trend')")
            pg.wait_for_timeout(300)
            pg.evaluate("togChart(0)")
            pg.wait_for_timeout(700)
            ck("空数据+有阈值走势出空态（幽灵坐标轴守卫）", pg.evaluate(
                "()=>{const e=document.getElementById('chartEmpty');"
                "return e.style.display==='flex'"
                "&&e.textContent.indexOf('暂无走势数据')>=0;}"))
            pg.evaluate("S.users[U].routesArr=window._SArr;togChart(0)")
            pg.wait_for_timeout(300)

            # ---- 触屏走势首 tap 读数（备案收口：tap 读数管线
            # 自动化覆盖）——独立 hasTouch context（touchscreen.tap
            # 要求 context 级开关；主 context 形态不动）+ 落点取绘图区
            # 中带（不依赖数据点，hover 映射取最近点画十字线）；像素级
            # 验证读数帧产出，且首 tap 不跳转（同点二 tap 才放行）。
            # context 用完即关（共享状态复位律）----
            pg.evaluate("showMonTab('trend')")
            pg.wait_for_timeout(200)
            _tctx = b.new_context(has_touch=True,
                                  viewport={"width": 1280, "height": 900})
            _tp = _tctx.new_page()
            _tp.set_default_timeout(10000)
            _tp.goto(f"{BASE}/#trend")
            _tp.wait_for_timeout(1500)
            _tp.evaluate("togChart(0)")
            _tp.wait_for_timeout(400)
            _tap = _tp.evaluate("""()=>{
              const c=document.getElementById('chart');
              if(!c||!c.offsetWidth)return null;
              const r=c.getBoundingClientRect();
              return {x:Math.round(r.left+r.width*0.55),
                      y:Math.round(r.top+r.height*0.5),
                      before:c.toDataURL()};}""")
            if _tap:
                _tp.touchscreen.tap(_tap["x"], _tap["y"])
                _tp.wait_for_timeout(250)
                ck("触屏走势首 tap 画十字线读数（不跳转）", _tp.evaluate(
                    """(b)=>{const c=document.getElementById('chart');
                      const on=document.querySelector('#montabs .mtab.on');
                      return c.toDataURL()!==b&&!!on&&on.dataset.t==='trend';}""",
                    _tap["before"]))
            else:
                ck("触屏走势首 tap 画十字线读数（不跳转）", False)
            _tctx.close()

            # ---- 1920 宽屏常驻块对齐（用户实报收口）：
            # trend/details 突破档下 wrap 顶层全部常驻块（header/nav/
            # demoBar/操作卡）须与内容卡左缘对齐——行为级
            # 枚举断言，防新增常驻块再漏；overview/cfg 回窄组。收缩胶囊（nav/tabs）
            # 只量左缘；header 原生出血 -18px 预期内
            # （pulse 卡已入概览 tab，不再属于 trend 页常驻块——其对齐
            # 由下方 overview 组的 _bk.pulse 承接）
            pg.set_viewport_size({"width": 1920, "height": 1080})
            pg.evaluate("showMonTab('trend')")
            pg.wait_for_timeout(400)
            _al = pg.evaluate("""()=>{
              const g=id=>{const e=document.getElementById(id);
                if(!e||!e.offsetWidth)return null;
                const r=e.getBoundingClientRect();return [r.left,r.right];};
              const c=g('chartcard');const ids=
                ['hdcard','mainnav','demoBar','opscard'];
              const out={chartL:c[0]};
              ids.forEach(id=>{const e=g(id);
                out[id]=(e===null)?null:Math.abs(e[0]-c[0]);});
              return out;}""")
            ck("1920 trend 标题条对齐", _al["hdcard"] is not None
               and _al["hdcard"] < 2)
            ck("1920 trend 视图 nav 对齐", _al["mainnav"] is not None
               and _al["mainnav"] < 2)
            ck("1920 trend 演示横幅对齐", _al["demoBar"] is not None
               and _al["demoBar"] < 2)
            ck("1920 trend 操作卡对齐", _al["opscard"] is not None
               and _al["opscard"] < 2)
            pg.evaluate("showMonTab('overview')")
            pg.wait_for_timeout(400)
            _bk = pg.evaluate("""()=>{
              const g=id=>{const e=document.getElementById(id);
                if(!e||!e.offsetWidth)return null;
                return e.getBoundingClientRect().left;};
              return {kpi:g('montab-overview'),ops:g('opscard'),
                pulse:g('pulsecard'),hdr:g('hdcard'),nav:g('mainnav')};}""")
            # 统一 1680：概览与 trend 同宽组，全部常驻块随 KPI 对齐
            ck("1920 overview 常驻块与 KPI 对齐", all(
                _bk[k] is not None and abs(_bk[k] - _bk["kpi"]) < 2
                for k in ("ops", "pulse", "hdr", "nav")))
            ck("1920 切标签零横移", abs(_bk["kpi"] - _al["chartL"]) < 2)
            # ≥1920 档放开非比例件（statline 跟卡全宽），
            # .grid/.kpisum 放宽 1440（空腔收敛）；1400 下界防
            # 「放宽声明未生效」回归（层叠被盖回时退回 1168 即红）
            _kw = pg.evaluate("""()=>{
              const st=document.querySelector('.statline')
                .getBoundingClientRect();
              const pc=document.getElementById('pulsecard')
                .getBoundingClientRect();
              const g=document.querySelector('.grid')
                .getBoundingClientRect();
              return {stW:st.width,cardW:pc.width,gridW:g.width};}""")
            # r302 W1：statline 族「跟卡」语义到网格 1440 上限为止
            # （右缘通线恒等），旧「全宽超卡宽-60」断言锁的是回潮病灶形态
            ck("1920 statline 与网格同上限 + KPI 行放宽 1440（空腔收敛）",
               abs(_kw["stW"] - _kw["gridW"]) <= 2
               and 1400 < _kw["gridW"] <= 1441)
            # header 右区单行同轴（用户实报:两行堆叠参差臃肿）+
            # 收紧 ≤64;cfgnav sticky 联动（top 58）不被盖
            _hd = pg.evaluate("""()=>{
              const hdr=document.querySelector('header');
              const box=hdr.querySelector('.hdx');
              const kids=[...box.children].filter(e=>e.offsetWidth>0);
              const cs=kids.map(e=>{const r=e.getBoundingClientRect();
                return (r.top+r.bottom)/2;});
              return {hH:hdr.getBoundingClientRect().height,
                      spread:Math.max(...cs)-Math.min(...cs)};}""")
            ck("1920 header 右区单行同轴", _hd["spread"] < 3)
            ck("1920 header 紧凑 ≤64", _hd["hH"] <= 64)
            # 版本失配刷新横幅：代际一致时恒隐藏（demo 下
            # PGVER=state.version='demo'）；亮起路径由 pytest 源钉
            ck("版本失配横幅默认隐藏", pg.evaluate(
                "document.getElementById('verbar').style.display")
                == 'none')
            # health 视图与 overview 同为统一宽组（矩阵抽检，全站 1680
            # 全站 1680 无窄组——对齐基准随 trend 的 chartL）
            pg.evaluate("showMonTab('health')")
            pg.wait_for_timeout(400)
            _hl = pg.evaluate("""()=>{
              const g=id=>{const e=document.getElementById(id);
                if(!e||!e.offsetWidth)return null;
                return e.getBoundingClientRect().left;};
              return {ops:g('opscard'), montabs:g('montabs')};}""")
            ck("1920 health 全块对齐抽检", all(
                v is not None and abs(v - _al["chartL"]) < 2
                for v in (_hl["ops"], _hl["montabs"])))
            # 横滚抽检 1920
            _sw = pg.evaluate(
                "document.documentElement.scrollWidth")
            ck("1920 无横向滚动", _sw <= 1920 + 1)
            # 配置视图与监控宽视图同宽（用户实报：两视图切换宽度跳变割裂
            # ——cfg 下 header/nav/横幅/cfgview 整体随监控页突破 1680）
            pg.evaluate("switchView('cfg')")
            pg.wait_for_timeout(600)
            _cw = pg.evaluate("""()=>{
              const g=id=>{const e=document.getElementById(id);
                if(!e||!e.offsetWidth)return null;
                const r=e.getBoundingClientRect();return [r.left,r.right];};
              return {cv:g('cfgview'), hd:g('hdcard'), nav:g('mainnav')};}""")
            # r349 设计变更：配置工作区与监控页同宽突破，不再额外收口居中；
            # 侧栏/主视图 nav 与服务端内容左缘同轴，页头 18px 满幅包住。
            ck("1920 cfg 内容卡随监控页拓宽", _cw["cv"] is not None
               and _cw["cv"][1] - _cw["cv"][0] > 1400
               and abs(_cw["cv"][0] - _al["chartL"]) < 3)
            ck("1920 cfg 标题条包住内容卡", _cw["hd"] is not None
               and _cw["hd"][0] <= _cw["cv"][0] + 1
               and _cw["hd"][1] >= _cw["cv"][1] - 1)
            ck("1920 cfg 视图 nav 对齐", _cw["nav"] is not None
               and abs(_cw["nav"][0] - _cw["cv"][0]) < 3)
            pg.evaluate("switchView('mon')")
            # 健康时间线 ≥1440 弹性格铺满——防 96 格左聚，
            # 1920 档徽标前 ~740px 空白横在卡片正中；格带右缘贴徽标
            pg.evaluate("showMonTab('health')")
            pg.wait_for_timeout(400)
            _hw = pg.evaluate("""()=>{
              const r=document.querySelector('#hbody .hrow');
              if(!r)return null;
              const c=r.querySelector('.hcells').getBoundingClientRect();
              const b=r.querySelector('.hbadge').getBoundingClientRect();
              const h=r.querySelector('.hc').getBoundingClientRect();
              return {gap:b.left-c.right, cw:h.width};}""")
            # cw>6 防格宽归零误过（容器收缩模型下格 0 宽假铺满）
            ck("1920 健康时间线铺满",
               _hw is not None and _hw["gap"] < 24 and _hw["cw"] > 6)
            pg.set_viewport_size({"width": 1280, "height": 900})
            ck("1280 无横向滚动", pg.evaluate(
                "document.documentElement.scrollWidth") <= 1281)

            # ---- 配置页（V50 面板式：同屏只显一个分区） ----
            step("config view")
            pg.click("#navCfg"); pg.wait_for_timeout(800)
            ck("面板互斥：登录显", pg.is_visible("#sec-login"))
            ck("面板互斥：用户隐", not pg.is_visible("#sec-users"))
            ck("面板互斥：全局隐", not pg.is_visible("#sec-globals-card"))
            ck("渠道登录卡网格", len(
                pg.query_selector_all("#loginRows .lgcard")) == 5)
            ck("Qunar 登录卡 H5 标", pg.evaluate(
                "()=>{const t=document.querySelector('#loginRows .lgcard[data-channel=\"qunar\"] .lgtag');"
                "return !!t&&t.textContent.trim()==='H5';}"))
            ck("Qunar 必须登录", "必须登录" in pg.inner_text(
                "#loginRows .lgcard[data-channel=\"qunar\"]"))
            ck("Qunar 停服登录说明", "2026-10-10" in pg.inner_text(
                "#loginRows .lgnote"))
            _lg = pg.evaluate("""()=>{
              const g=document.querySelector('#loginRows .lggrid');
              const cs=g?[...g.querySelectorAll('.lgcard')]:[];
              if(!g||cs.length!==5)return {ok:false,why:'no-login-grid'};
              const rows={};cs.forEach(c=>{const r=c.getBoundingClientRect();
                const k=Math.round(r.top);(rows[k]=rows[k]||[]).push(+r.width.toFixed(1));});
              const equal=Object.values(rows).every(a=>
                Math.max(...a)-Math.min(...a)<2);
              const flat=cs.every(c=>getComputedStyle(c).transform==='none');
              const singles=cs.filter(c=>c.dataset.channel!=='fliggy');
              const bs=singles.map(c=>{const b=c.querySelector('.btn2');
                return b?+b.getBoundingClientRect().width.toFixed(1):0});
              const fl=cs.find(c=>c.dataset.channel==='fliggy');
              const fbs=fl?[...fl.querySelectorAll('.btn2')].map(
                b=>+b.getBoundingClientRect().width.toFixed(1)):[];
              const bOk=bs.length&&Math.max(...bs)-Math.min(...bs)<1.5;
              const fOk=fbs.length<2||Math.max(...fbs)-Math.min(...fbs)<1.5;
              return {ok:equal&&flat&&bOk&&fOk,
                rows:Object.keys(rows).length,equal,flat,btn:bs,fbtn:fbs};}
            """)
            ck("r349d 登录卡等宽同顶/无位移/按钮等宽 %s" % _lg, _lg["ok"])
            ck("渠道登录行渲染", len(
                pg.query_selector_all("#loginRows .btn2")) >= 5)
            cnode0 = pg.evaluate(
                "document.querySelectorAll('#cfgview *').length")
            pg.click('#cfgnav .cnav[data-p="users"]')
            pg.wait_for_timeout(600)
            ck("面板切换零插拔", cnode0 == pg.evaluate(
                "document.querySelectorAll('#cfgview *').length"))
            ck("面板切换：用户显", pg.is_visible("#sec-users"))
            ck("面板切换：登录隐", not pg.is_visible("#sec-login"))
            ck("配置表单", len(pg.query_selector_all("#cfgform input")) > 0)
            # ---- buildForm 重建不坠焦（回车加日期承诺
            # 通道连续录入）。航线卡默认折叠
            # 须先展开才有可聚焦件；测后复位折叠态防污染后续断言 ----
            ck("cfg 重建回焦", pg.evaluate(
                "()=>{const rl=document.querySelector('#cfgform .rline[data-rk]');"
                "if(!rl)return false;"
                "if(FOLD.route[rl.dataset.rk]!==false)rl.querySelector('.rhead').click();"
                "const tab=rl.querySelector('.dctab[data-dm=\"single\"]');"  # r345 一次只开一个编辑器
                "if(tab&&!tab.classList.contains('on'))tab.click();"
                "const inp=rl.querySelector('[id^=\"dadd-\"]');"
                "if(!inp||!inp.offsetParent)return false;"
                "inp.focus();const id=inp.id;buildForm();"
                "const ok=!!document.activeElement"
                "&&document.activeElement.id===id;"
                "FOLD.route={};saveFold();applyFolds();"   # 状态复位：默认折叠态（saveFold 同步清 localStorage，CHR.i 同律）
                "return ok;}"))
            # esc 补转义 & < >（& 必须最先防二次转义）
            ck("esc 补转义 &<>", pg.evaluate(
                "()=>esc('<b>&\"')==='&lt;b&gt;&amp;&quot;'"))
            ck("全局热配置项", all(pg.query_selector(s) for s in
               ["#glbIv", "#glbJt", "#glbPort", "#glbHl",
                "#glbTo", "#glbDn", "#glbDx", "#glbUa"]))
            ck("热加载文案",
               "仍需改 config.yaml 重启" not in pg.content())
            ck("免打扰时段配置", "免打扰 · 开始" in pg.content())
            ck("Windows 弹窗开关", "Windows 右下角弹窗" in pg.content())
            ck("Windows 弹窗默认勾选", pg.evaluate(
                "()=>{const c=[...document.querySelectorAll("
                "'#cfgform input[type=checkbox]')].find("
                "x=>(x.getAttribute('onchange')||'').includes("
                "'win_toast'));return !!c&&c.checked;}"))
            ck("用户卡头弹窗状态", "弹窗开" in pg.inner_text("#cfgform"))
            ck("分组标签 A-D", all(
                t in pg.inner_text("#cfgform")
                for t in ("基础", "监控渠道", "航线", "通知渠道")))
            ck("通道卡六张（未配邮件；r339 +Bark）", len(pg.query_selector_all(
               "#cfgform .chcard")) == 6)
            ck("Server酱通道卡", pg.query_selector(
               '#cfgform .chcard[data-ch="serverchan"]') is not None)
            ck("添加邮箱通道出卡（email0 含密码框+host 输入）",
               pg.evaluate(
                "()=>{document.querySelector("
                "'#cfgform button[onclick^=\"addEm\"]').click();"
                "const c=document.querySelector("
                "'#cfgform .chcard[data-ch=\"email0\"]');"
                "if(!c)return false;"
                "const p=[...c.querySelectorAll('input')].filter("
                "i=>i.type==='password');"
                "return p.length>=1&&c.querySelector('.emhost')"
                "!==null;}"))
            ck("邮件卡勾选启用灯不灭（chSync 读 emails[k]）",
               pg.evaluate(
                "()=>{const c=document.querySelector("
                "'#cfgform .chcard[data-ch=\"email0\"]');"
                "const cb=c&&c.querySelector("
                "'input[type=\"checkbox\"].switch');"
                "if(!cb)return false;"
                "cb.click();"
                "return c.classList.contains('todo')"
                "&&c.querySelector('.chhead .muted')"
                ".textContent==='待完善';}"))   # r345：空凭据启用的如实态
            ck("图床通道卡", pg.query_selector(
               '#cfgform .chcard[data-ch="imghost"]') is not None)
            ck("图床 sm.ms 引导链接", pg.query_selector(
               '#cfgform a[href="https://sm.ms/home/apitoken"]')
               is not None)
            ck("图床切换显隐 Token 行（三态循环：gh/smms/free）", pg.evaluate(
                "()=>{const c=document.querySelector("
                "'#cfgform .chcard[data-ch=\"imghost\"]');"
                "const disp=sel=>getComputedStyle(c.querySelector(sel)).display;"
                "const vis=sel=>disp(sel)!=='none';"
                "const head=c.querySelector('.chhead');"
                "if(head.nextElementSibling.style.display==='none')head.click();"
                "const chip=p=>[...c.querySelectorAll('.ihchip')]"
                ".find(x=>x.dataset.p===p);"
                "chip('ghimg').click();"
                "const gh=c.classList.contains('ih-ghimg')"
                "&&vis('.ih-repo')&&vis('.ih-ghtoken')&&vis('.ih-proxy')"
                "&&!vis('.ih-token');"
                "chip('smms').click();"
                "const sm=c.classList.contains('ih-smms')&&vis('.ih-token')"
                "&&!vis('.ih-repo')&&!vis('.ih-ghtoken');"
                "chip('freeimage').click();"
                "const fr=c.classList.contains('ih-free')&&!vis('.ih-token')"
                "&&!vis('.ih-repo')&&!vis('.ih-ghtoken');"
                "chip('ghimg').click();   /* 还原演示夹具态 */"
                "const lbl=c.querySelector('.chhead .muted')"
                ".textContent==='GitHub 图库';"
                "return gh&&sm&&fr&&lbl;}"))
            ck("通道测试按钮", pg.query_selector("text=发测试弹窗")
               is not None and pg.query_selector("text=测试 ntfy")
               is not None)
            # 图床卡「测试上传」两段式——ghimg 夹具无 Token：客户端守卫
            # 早退（结果行不出、不发请求）；填 Token 后再点：demo 只读
            # 拦截，结果行如实回显 403 摘要（按钮+守卫+JS 链路+结果行四合一）
            _ihib = pg.evaluate("""()=>{
              const c=document.querySelector(
                '#cfgform .chcard[data-ch="imghost"]');
              const head=c.querySelector('.chhead');
              const folded=head.nextElementSibling.style.display==='none';
              if(folded)head.click();
              const b=[...c.querySelectorAll('button')].find(
                x=>x.textContent.indexOf('测试上传')>=0);
              if(b)b.click();
              return !!b;}""")
            pg.wait_for_timeout(400)
            # 守卫早退的可观察态=结果行无「演示模式」（demo 下任何真实
            # 请求都会被拦截并写入 403 词面；行可见性会被 foldCh 展开
            # 复位清成空行——只认内容不认 display，十九§4 同族）
            _ihguard = pg.evaluate(
                "()=>{const r=document.getElementById('ihtest-0');"
                "return !!r&&(r.textContent||'').indexOf('演示模式')<0;}")
            pg.evaluate("setIh(0,'token','ghp_demo_token')")
            pg.evaluate("""()=>{const c=document.querySelector(
              '#cfgform .chcard[data-ch="imghost"]');
              const b=[...c.querySelectorAll('button')].find(
                x=>x.textContent.indexOf('测试上传')>=0);
              if(b)b.click();}""")
            pg.wait_for_timeout(600)
            ck("图床测试上传按钮（ghimg 守卫早退+demo 拦截如实报错）",
               _ihib and _ihguard and pg.evaluate(
                "()=>{const r=document.getElementById('ihtest-0');"
                "return !!r&&r.style.display!=='none'"
                "&&r.textContent.indexOf('演示模式')>=0;}"))
            pg.evaluate("""()=>{const c=document.querySelector(
              '#cfgform .chcard[data-ch="imghost"]');
              c.querySelector('.chhead').click();}""")   # 还原折叠态
            ck("聚合推送开关", "多航线合并推送" in pg.content())
            ck("再推阈值配置", "降价再推阈值" in pg.content()
               and "涨价再推阈值" in pg.content())
            # V100 子卡折叠：分区/航线卡/通道卡（display 切换零插拔）
            ck("分区折叠再展开", pg.evaluate(
                "()=>{const g=document.querySelector("
                "'#cfgform .grouplab[data-sec=\"B\"]');"
                "g.click();const hid=g.nextElementSibling"
                ".style.display==='none';g.click();"
                "return hid&&g.nextElementSibling"
                ".style.display!=='none';}"))
            ck("航线卡默认收起可展开", pg.evaluate(
                "()=>{const rl=document.querySelector("
                "'#cfgform .rline[data-rk]');"
                "const rh=rl.querySelector('.rhead');"
                "if(rh.getAttribute('aria-expanded')!=='false')"
                "rh.click();"   # 前置归位：前序钉失败级联可留展开态
                "const hid0=rh.nextElementSibling"
                ".style.display==='none';rh.click();"
                "const vis=rh.nextElementSibling"
                ".style.display!=='none';rh.click();"
                "return hid0&&vis;}"))
            ck("航线停用开关（置灰+徽标+摘要+脏标）", pg.evaluate(
                "()=>{const rl=document.querySelector("
                "'#cfgform .rline[data-rk]');"
                "const sw=rl.querySelector('.rhead input.switch');"
                "if(!sw)return 'noswitch';"
                "sw.click();"   # stopPropagation 已挡折叠
                "const off=rl.classList.contains('off');"
                "const badge=rl.querySelector('.rbadge').textContent;"
                "const sum=document.querySelector('[id^=csum-]').textContent;"
                "const dirty=cfgIsDirty();"
                "sw.click();"
                "return off&&badge==='已停用'&&/已停用/.test(sum)&&dirty&&"
                "!rl.classList.contains('off');}"))
            ck("通道卡默认收起可展开", pg.evaluate(
                "()=>{const c=document.querySelector('#cfgform .chcard');"
                "const ch=c.querySelector('.chhead');"
                "const hid0=ch.nextElementSibling"
                ".style.display==='none';ch.click();"
                "const vis=ch.nextElementSibling"
                ".style.display!=='none';ch.click();"
                "return hid0&&vis;}"))
            ck("钉钉开关 checkbox", len(pg.query_selector_all(
               "#cfgform input[type=checkbox]")) >= 2)
            danger = pg.query_selector("#cfgform .danger")
            if danger:
                danger.click(); pg.wait_for_timeout(300)
                ck("删除确认层",
                   pg.is_visible("#confirmMask")
                   and bool(pg.inner_text("#cmTitle").strip()))
                pg.click("#cmCancel"); pg.wait_for_timeout(150)
            ipt = pg.query_selector("#cfgform .ucard input")
            if ipt:
                # 表单绑定 onchange——fill 后须 dispatch 才触发脏标记
                ipt.fill("测试城市")
                ipt.evaluate("el=>el.dispatchEvent(new Event('change'))")
                pg.wait_for_timeout(1800)
                ck("未保存守卫", pg.is_visible("#cfgDirty"))
            # 全局参数面板（扫描周期同守）
            pg.click('#cfgnav .cnav[data-p="globals"]')
            pg.wait_for_timeout(600)
            ck("面板切换：全局显", pg.is_visible("#sec-globals-card"))
            ck("面板切换：用户隐", not pg.is_visible("#sec-users"))
            glb = pg.query_selector("#glbIv")
            if glb:
                glb.fill("21")
                glb.evaluate("el=>el.dispatchEvent(new Event('change'))")
                pg.wait_for_timeout(1800)
                # cfgDirty 徽标随用户面板隐藏；守卫以常驻 savebar 为准
                ck("全局项未保存守卫", pg.is_visible("#savebar"))
            _gt = pg.inner_text("#sec-globals-card")
            ck("全局配置中心分组", all(t in _gt for t in ("调度", "采集",
               "启动级")) and "🔥" in _gt and "♻" in _gt)
            pg.evaluate("openRestartCenter&&openRestartCenter()")
            pg.wait_for_timeout(400)
            ck("重启中心浮层让位保存条", pg.evaluate("""()=>{
              const rc=document.getElementById('restartCenter');
              const sb=document.querySelector('.savebar');
              return !!rc&&rc.classList.contains('on')
                &&(!sb||getComputedStyle(sb).visibility==='hidden');}"""))
            pg.evaluate("closeRestartCenter&&closeRestartCenter()")
            pg.wait_for_timeout(200)
            # glsec 输出归一 class="subsec"（带 hairline 收尾线，
            # margin 恒定；glsec 类残留 0=归一彻底）
            ck("glsec 归一 subsec", pg.evaluate(
                "()=>document.querySelectorAll('#sec-globals-card .subsec')"
                ".length>=2&&document.querySelectorAll('#sec-globals-card .glsec')"
                ".length===0"))
            ck("subsec hairline 线", pg.evaluate(
                "()=>{const el=document.querySelector('#sec-globals-card .subsec');"
                "return !!el&&getComputedStyle(el,'::after').height==='1px';}"))
            # glcell 内衬 12px 14px 档（.lgcard/.chcard 同档，
            # 11px 垂直档游离值不复存）
            ck("glcell 内衬 12px 14px", pg.evaluate(
                "()=>{const el=document.querySelector('.glcell');"
                "return !!el&&getComputedStyle(el).paddingTop==='12px'"
                "&&getComputedStyle(el).paddingRight==='14px';}"))
            # glcell 三枚开关键盘焦点环不被 outline:none
            # 吞（focusVisible 程序化触发 UA 环，fbar 同款先例）
            ck("glcell 开关焦点环", pg.evaluate(
                "()=>{const sw=document.querySelector('.glcell .switch');"
                "if(!sw)return false;sw.focus({focusVisible:true});"
                "const o=getComputedStyle(sw).outlineStyle;"
                "sw.blur();return o!=='none';}"))
            # 桌面档 glcell 文本输入内联 13px
            # （16px!important 仅移动媒体内生效，桌面观感不变）
            ck("glcell 文本桌面 13px", pg.evaluate(
                "()=>{const e=document.getElementById('glbUa');"
                "return !!e&&getComputedStyle(e).fontSize==='13px';}"))
            ck("启动级路径可编辑+📂 打开钮（r339d 可变更化：三件 ro→text）",
               pg.evaluate(
                "()=>{const e=document.getElementById('glbDbp');"
                "return !!e&&!e.readOnly&&e.value.indexOf('prices.db')>=0"
                "&&!!document.querySelector('[data-which=\"db\"]');}"))
            pg.keyboard.press("Control+s")
            pg.wait_for_timeout(600)
            ck("Ctrl+S 保存", (pg.inner_text("#cfgmsg") or "").strip() != "")
            ck("配置分区导航", len(pg.query_selector_all("#cfgnav .cnav")) == 3)
            # r368 用户级 IA：关注航班/特价雷达移入用户卡 D/E 区，全局
            # watch 导航已删；旧 panel-watch 仅保留为兼容容器，直接从
            # 代码打开做样式钉，不再要求可点导航。
            pg.evaluate("()=>{showCfgPanel('users');"
                        "if(OPEN_USER<0)document.querySelector('.uhead2').click();}")
            pg.wait_for_timeout(800)
            ck("用户卡 D/E 区（内联关注+官方雷达）", pg.evaluate(
                "()=>{"
                "const t=document.getElementById('panel-users').innerText;"
                "return t.indexOf('关注航线')>=0&&t.indexOf('特价雷达')>=0"
                "&&!!document.querySelector('[data-rad=\"start\"]')"
                "&&!!document.querySelector('[data-rad=\"from_name\"]')"
                "&&!!document.getElementById('uradLinks-0');}"))
            ck("关注航班内联在用户卡 D 区", pg.evaluate(
                "()=>{const host=document.getElementById('uwatch-0');"
                "const cw=document.getElementById('cfgWatch');"
                "return !!host&&!!cw&&host.contains(cw)"
                "&&getComputedStyle(document.getElementById('panel-watch')).display==='none';}"))
            # r353 样式落地钉（r368 改为内联 D 区）：工具条/字段网格/表单
            # 边框与容器 containment，任何整段丢失即红。
            pg.wait_for_timeout(300)
            # 关注编排默认取首条航线/日期；前面的配置测试可能改动过状态，
            # 显式选一个未过期日期再刷新候选，保证航司图标有真实行可挂。
            pg.evaluate("""()=>{try{loadCfgWatch(true)}catch(e){}}""")
            pg.wait_for_timeout(900)
            pg.evaluate("""()=>{const ds=document.getElementById('cwDate');
              if(ds&&ds.options.length){
                const o=[...ds.options].find(x=>x.value
                  &&x.textContent.indexOf('已过期')<0)||ds.options[0];
                ds.value=o.value;}
              if(typeof cfgWatchFormRefresh==='function')cfgWatchFormRefresh();}""")
            pg.wait_for_timeout(900)
            _cw = pg.evaluate("""()=>{
              const tool=document.querySelector('#uwatch-0 .cfgwatch-toolbar');
              const grid=document.querySelector('#uwatch-0 .cwf-grid');
              const form=document.querySelector('#uwatch-0 .cfgwatch-form');
              const host=document.getElementById('uwatch-0');
              if(!tool||!grid||!form)return {ok:false};
              const tr=tool.getBoundingClientRect(),pr=host.getBoundingClientRect();
              return {ok:getComputedStyle(tool).display==='flex'
                &&getComputedStyle(grid).display==='grid'
                &&getComputedStyle(form).borderTopWidth!=='0px'
                &&tr.left>=pr.left-1&&tr.right<=pr.right+1};}""")
            ck("关注航班内联样式落地", bool(_cw.get("ok")))
            _cwi = pg.evaluate("""()=>{const im=[...document.querySelectorAll(
                '#uwatch-0 img.bic')];
              return {n:im.length,bad:im.filter(i=>!i.complete||!i.naturalWidth).length,
                ota:document.querySelectorAll('#uwatch-0 img.bic-ota').length,
                air:document.querySelectorAll('#uwatch-0 img.bic-air').length};}""")
            try:
                pg.wait_for_function("""()=>{const im=[...document.querySelectorAll(
                  '#uwatch-0 img.bic')];
                  return im.length>0&&im.every(i=>i.complete&&i.naturalWidth>0);}""",
                  timeout=8000)
            except Exception:
                pass
            # 打开添加表单：即使演示用户暂时没有关注卡，也能验证 5 个渠道
            # 官方图标与候选航班的圆形航司图标；有卡时再核对卡内图标。
            _cards = pg.evaluate(
                "document.querySelectorAll('#cfgWatchList .cw-item').length")
            if pg.locator('#uwatch-0 [data-cwact="add"]').count():
                pg.locator('#uwatch-0 [data-cwact="add"]').first.click()
                pg.wait_for_timeout(1200)
            _cwi = pg.evaluate("""()=>{const im=[...document.querySelectorAll(
                '#uwatch-0 img.bic')];
              return {n:im.length,bad:im.filter(i=>!i.complete||!i.naturalWidth).length,
                ota:document.querySelectorAll('#uwatch-0 img.bic-ota').length,
                air:document.querySelectorAll('#uwatch-0 img.bic-air').length,
                cards:document.querySelectorAll('#cfgWatchList .cw-item').length};}""")
            ck("r353 配置台渠道/航司图标随行落地",
               _cwi["ota"] >= 5 and _cwi["bad"] == 0
               and (_cwi["cards"] == 0 or _cwi["air"] > 0))
            pg.evaluate("try{cfgWatchReset()}catch(e){}")
            pg.wait_for_timeout(300)
            pg.click('#cfgnav .cnav[data-p="globals"]'); pg.wait_for_timeout(300)
            # 演示模式不得泄露运行机真实路径：runtime/storage/globals 全部
            # 指向合成目录；该钉同时保护截图与在线静态站。
            ck("演示模式路径脱敏", pg.evaluate("""()=>{
              if(typeof RUNTIME==='undefined')return false;
              const r=RUNTIME.root||'';
              const a=((GLB_STORE||{}).db||{}).abs||'';
              const b=((GLB_STORE||{}).bdir||{}).abs||'';
              return RUNTIME.demo===true
                && /TicketMonitor|ticket-monitor/.test(r)
                && /TicketMonitor|ticket-monitor/.test(a)
                && a.indexOf('idea_project')<0
                && b.indexOf('idea_project')<0;}"""))
            _pv = pg.evaluate("""async()=>await (await fetch(
              '/api/path-check?which=ud&path=user_data_migrated')).json()""")
            ck("演示模式迁移路径脱敏",
               str(_pv.get("abs", "")).endswith("user_data_migrated")
               and "idea_project" not in str(_pv.get("abs", ""))
               and "idea_project" not in str(
                   (_pv.get("migration") or {}).get("to", "")))
            ck("浮出保存条", pg.is_visible("#savebar"))
            ck("脏计数显示", "处" in pg.inner_text("#saveTxt"))
            # ---- savebar 泄漏钉：弄脏态切监控视图浮条必须回收
            #      （巡检早退曾压过 toggle，浮条永久驻留监控页）。
            #      等待须覆盖最坏相位：巡检 tick 800ms + .savebar.on
            #      过渡 ~300ms，1400ms 双钉同窗防相位假红
            pg.click("#navMon"); pg.wait_for_timeout(1400)
            ck("弄脏切监控 savebar 回收", not pg.is_visible("#savebar"))
            pg.click("#navCfg"); pg.wait_for_timeout(1400)
            ck("切回配置 savebar 复现", pg.is_visible("#savebar"))
            # ---- V50 配置搜索（搜索态临时展示全部分区）+ 导入导出 ----
            ck("配置搜索框", pg.is_visible("#cfgSearch"))
            pg.fill("#cfgSearch", "免打扰"); pg.wait_for_timeout(300)
            vis_f = pg.evaluate(
                "()=>[...document.querySelectorAll("
                "'#cfgview .fgrid>div,#cfgview .qgrid>div,#cfgview .srow')]"
                ".filter(d=>d.style.display!=='none').length")
            tot_f = pg.evaluate(
                "()=>document.querySelectorAll("
                "'#cfgview .fgrid>div,#cfgview .qgrid>div,#cfgview .srow').length")
            ck("搜索字段级过滤", 0 < vis_f < tot_f)
            # r281 容器壳收尾：命中集中于用户面板时非命中面板卡壳
            # 退场（空白残影条收口），命中面板卡壳在位
            ck("搜索态命中面板在位孤儿卡壳退场", pg.is_visible("#sec-users")
               and not pg.is_visible("#sec-login")
               and not pg.is_visible("#sec-globals-card"))
            pg.fill("#cfgSearch", ""); pg.wait_for_timeout(300)
            ck("清空还原单面板", pg.is_visible("#sec-globals-card")
               and not pg.is_visible("#sec-users"))
            # 搜索并入 .rhead 摘要行索引（三字码/日期盲区）——
            # URC 只在 rhead，命中整卡显示且 cfgHits 计数不再假阴性
            pg.fill("#cfgSearch", "URC"); pg.wait_for_timeout(300)
            _rh = pg.evaluate("""()=>[...document.querySelectorAll(
              '#cfgview .rline')].some(r=>r.style.display!=='none'
              &&r.querySelector('.rhead').textContent.indexOf('URC')>=0)""")
            ck("搜索索引 rhead 三字码", _rh and
               "无匹配项" not in (pg.inner_text("#cfgHits") or ""))
            # 登录卡（.lgcard）并入字段级过滤——URC
            # 不命中登录卡，5 张应整卡隐藏（防非命中滞留顶走真命中）
            ck("搜索态登录卡隐藏", pg.evaluate(
                "()=>[...document.querySelectorAll('#cfgview .lgcard')]"
                ".every(d=>d.style.display==='none')"))
            # 光晕复位三态钉：rhead 独命中 rline 打光晕 → 换无匹配查询
            # 生产实测三步定案）：rhead 独命中 rline 打光晕 → 换无匹配查询
            # 旧光晕清零不残留双圈 → 清空复位
            _g1 = pg.evaluate(
                "()=>[...document.querySelectorAll('#cfgview .rline[data-rk]')]"
                ".map(r=>r.style.boxShadow)")
            ck("搜索命中 rline 光晕", any("0px 0px 0px 2px" in b for b in _g1))
            pg.fill("#cfgSearch", "zzz9x9"); pg.wait_for_timeout(300)
            _g2 = pg.evaluate(
                "()=>[...document.querySelectorAll('#cfgview .rline[data-rk]')]"
                ".map(r=>r.style.boxShadow+'|'+r.style.display)")
            ck("无匹配旧光晕清零", _g2 and all(
                b.split("|")[0] == "" and b.split("|")[1] == "none"
                for b in _g2))
            ck("无匹配计数", "无匹配项" in (pg.inner_text("#cfgHits") or ""))
            # r275 P3-1：0 命中档孤儿头全退场（结构头+动作钮）——
            # 无匹配字段却让分区头/用户卡头/添加航线钮悬空漂浮
            ck("无匹配孤儿头隐藏", pg.evaluate(
                "()=>[...document.querySelectorAll("
                "'#cfgview .grouplab,#cfgview .uhead2,#cfgview .uhead,"
                "#cfgview .subsec,#cfgview .addrbtn')]"
                ".every(d=>d.style.display==='none')"))
            # 动作钮收编真命中：搜「添加关注航线」钮文本精确命中可见
            pg.fill("#cfgSearch", "添加关注航线"); pg.wait_for_timeout(300)
            ck("搜索收编添加关注航线钮", pg.is_visible(".addrbtn")
               and "无匹配项" not in (pg.inner_text("#cfgHits") or ""))
            pg.fill("#cfgSearch", ""); pg.wait_for_timeout(300)
            ck("清空登录卡复位", pg.evaluate(
                "()=>[...document.querySelectorAll('#cfgview .lgcard')]"
                ".every(d=>d.style.display===''&&d.style.boxShadow==='')"))
            pg.fill("#cfgSearch", ""); pg.wait_for_timeout(300)
            # 回用户面板做导入导出
            pg.click('#cfgnav .cnav[data-p="users"]')
            pg.wait_for_timeout(400)
            ck("导入导出按钮", pg.query_selector("text=导出配置")
               is not None and pg.query_selector("text=导入配置")
               is not None)
            with pg.expect_download() as cfgdl:
                pg.click("text=导出配置")
            ck("配置导出 JSON",
               cfgdl.value.suggested_filename.endswith(".json"))
            try:
                pg.set_input_files("#cfgImport", cfgdl.value.path())
                pg.wait_for_timeout(600)
                ck("配置导入回灌", any(
                    "已导入" in t.inner_text()
                    for t in pg.query_selector_all("#toasts .toast")))
            except Exception:
                ck("配置导入回灌", False)
            pg.click("#navMon"); pg.wait_for_timeout(400)
            # 暗色日历 AA 对比：--green 高 alpha 浅底上深字
            # （白字对比不足）；applyTheme 重渲后 .calcell 内联色生效
            pg.evaluate("localStorage.setItem('jptheme','dark')")
            pg.reload(wait_until="networkidle"); pg.wait_for_timeout(900)
            ck("暗色日历达标格深字（AA 对比）", pg.evaluate(
                "()=>{const hit=[...document.querySelectorAll("
                "'#calgrid .calcell')].find(c=>getComputedStyle(c)"
                ".backgroundColor.indexOf('67, 192, 114')>=0);"
                "return !!hit&&getComputedStyle(hit).color==="
                "'rgb(10, 15, 22)';}"))
            # --fill2 暗值断言（亮值断言在趋势段；
            # 钉名「双主题」需两侧闭合，暗色 #3771c4）
            ck("--fill2 暗色收深", pg.evaluate(
                "()=>getComputedStyle(document.documentElement)"
                ".getPropertyValue('--fill2').trim()==='#3771c4'"))
            pg.evaluate("localStorage.setItem('jptheme','auto')")
            pg.reload(wait_until="networkidle"); pg.wait_for_timeout(600)
            # ---- 错误态（非 JSON 200 体）：全部静态骨架语义 ----
            # r244 W-3 行为演进：非 JSON 体=服务应答了（真实世界 502/
            # 错误页同形：r.text() 成功而 JSON.parse 抛错），词面归
            # 「服务异常」档；「服务未启动」保留给真网络不可达（fetch
            # 抛错进外层 catch）。钉面语义担保不变：pill 与四处骨架
            # （ftable/cfgglobals/users/chartEmpty）同步置错误态、不再
            # 假等待「加载中…」；恢复轮 render()/loadCfg() 重写自愈。
            # 不用 abort：资源级 ERR_FAILED 会进 console error 污染套件。
            pg.route("**/api/state", lambda r: r.fulfill(
                status=200, content_type="text/plain",
                body="service unavailable"))
            pg.reload(wait_until="domcontentloaded"); pg.wait_for_timeout(1500)
            ck("错误态 pill 服务异常",
               "服务异常" in (pg.text_content("#pill") or ""))
            ck("错误态表体不再假等待「加载中…」", pg.evaluate(
                "()=>{const t=(document.getElementById('ftable')"
                ".innerText||'').trim();"
                "return t.indexOf('加载中')<0&&t.indexOf('服务异常')>=0;}"))
            ck("错误态配置区同步置错误态", pg.evaluate(
                "()=>{const g=document.getElementById('cfgglobals');"
                "return !!g&&(g.innerText||'').indexOf('服务异常')>=0;}"))
            ck("错误态概览骨架不再假等待", pg.evaluate(
                "()=>{const u=document.getElementById('users');"
                "return !!u&&(u.innerText||'').indexOf('服务异常')>=0"
                "&&u.querySelectorAll('.sk').length===0;}"))
            # （错误态家族第 5 处收口）走势空态在错误体时
            # 同步置错误态——静态教学词面「完成第一轮扫描」不再与
            # pill「服务异常」同屏自证矛盾（空态在场才翻新，
            # 已绘制图表 display:none 不动）
            ck("错误态走势空态不再假教学", pg.evaluate(
                "()=>{const e=document.getElementById('chartEmpty');"
                "const t=(e.textContent||'');"
                "return t.indexOf('服务异常')>=0"
                "&&t.indexOf('完成第一轮扫描')<0;}"))
            pg.unroute("**/api/state")
            pg.reload(wait_until="networkidle"); pg.wait_for_timeout(600)
            # ---- fetch 失败错误态（有旧数据）：保旧不掀卡 ----
            # S 已有数据时 catch 分支只标注不掀骨架：pill 落中性
            # 「服务异常」+「保留上次结果」（与错误体分支、renderHealth
            # 保陈旧政策同轨）；畸形 200 体不污染 LASTTXT（同体重试可
            # 重入，恢复轮必被处理）
            pg.route("**/api/state", lambda r: r.fulfill(
                status=200, content_type="text/plain",
                body="<html>gateway error</html>"))
            pg.evaluate("table()"); pg.wait_for_timeout(200)
            n0 = pg.evaluate("document.querySelectorAll('#ftable tr').length")
            pg.evaluate("load()"); pg.wait_for_timeout(400)
            ck("错误态(有旧数据) pill 落中性「服务异常」",
               "服务异常" in (pg.text_content("#pill") or ""))
            ck("错误态(有旧数据) 表体保旧不掀卡", pg.evaluate(
                "(n)=>{const t=(document.getElementById('ftable')"
                ".innerText||'');return t.indexOf('服务未启动')<0"
                "&&document.querySelectorAll('#ftable tr').length===n;}", n0))
            ck("错误态(有旧数据) LASTTXT 未被畸形体污染", pg.evaluate(
                "()=>LASTTXT.indexOf('gateway error')<0"))
            pg.evaluate("load()"); pg.wait_for_timeout(300)
            pg.unroute("**/api/state")
            pg.evaluate("load()"); pg.wait_for_timeout(800)
            ck("恢复轮自动回流（服务异常词面退场）", pg.evaluate(
                "()=>(document.getElementById('pill').textContent||'')"
                ".indexOf('服务异常')<0"))
            # ---- 冷启动 500 错误体：词面同轨（audit v183 P2-2）----
            # 服务在线但 /api/state 500：pill 与骨架同落「服务异常」
            # （曾 pill 服务异常而骨架「服务未启动」同屏混轨）
            pg.route("**/api/state", lambda r: r.fulfill(
                status=200, content_type="application/json",
                body='{"err":"boom"}'))
            pg.reload(wait_until="domcontentloaded"); pg.wait_for_timeout(1500)
            ck("冷启动错误体 pill「服务异常」",
               "服务异常" in (pg.text_content("#pill") or ""))
            ck("冷启动错误体骨架同轨「服务异常」", pg.evaluate(
                "()=>{const t=(document.getElementById('ftable')"
                ".innerText||'');return t.indexOf('服务异常')>=0"
                "&&t.indexOf('服务未启动')<0;}"))
            pg.unroute("**/api/state")
            pg.reload(wait_until="networkidle"); pg.wait_for_timeout(600)
            # ---- 状态完备性与交互直达五钉（audit 落地回归）----
            # ⑤术语统一：配置页 B 分区「监控渠道」（原「监控平台」×2）。
            # 先显式落用户面板（B 分区所在）：钉曾隐式依赖「搜索态残留
            # 让 B 分区保持可见」的旧缺陷行为——r233 W-2 修复（导航=
            # 离开搜索模式复位单面板）后残留态不复存在，断言落位显式化
            pg.click("#navCfg"); pg.wait_for_timeout(400)
            ck("配置页术语统一「监控渠道」", pg.evaluate(
                "()=>{showCfgPanel('users',true);"
                "const t=document.body.innerText||'';"
                "return t.indexOf('监控渠道')>=0&&t.indexOf('监控平台')<0;}"))
            pg.click("#navMon"); pg.wait_for_timeout(400)
            # ④状态 pill 直达「仅达标」：点击→明细 tab+🔥 档高亮
            # （复位：点回「全部」档，saveUI 持久化 F 还原）
            pg.click("#pill"); pg.wait_for_timeout(500)
            ck("pill 点击跳明细 tab", pg.evaluate(
                "()=>{const t=document.getElementById('montab-details');"
                "return !!t&&getComputedStyle(t).display!=='none';}"))
            ck("pill 点击切「仅达标」档高亮", pg.evaluate(
                "()=>{const q=document.querySelector('#tabs span[data-f=q]');"
                "return !!q&&q.classList.contains('on');}"))
            pg.evaluate(
                "document.querySelector('#tabs span[data-f=all]').click()")
            pg.wait_for_timeout(300)
            # ③桌面档 savebar×toast 抬升：computed 值钉（几何/computed
            # 断言不随 display 翻转——LESSONS 二十一 §2）；≤760 档
            # 148px 先例的桌面档补账，1px 巧合缝收口。toast 容器系
            # toast() 首次调用懒创建，先真发一枚再量。加类→读→移除
            # 同一 evaluate 原子化：savebar 泄漏巡检全视图每拍
            # 回收 on 类（含监控视图），拆两条语句会被 800ms 拍竞态摘类
            pg.evaluate("()=>toast('钉','ok')")
            pg.wait_for_timeout(80)
            # r264：抬升走 --sbh 实高动态单源，钉面量相对关系
            # （toast 底 ≥ savebar 顶+呼吸缝），不锁绝对像素值
            ck("桌面 savebar 在场 toast 抬升", pg.evaluate(
                "()=>{const sb=document.querySelector('.savebar');"
                "const b=document.getElementById('toasts');"
                "if(!b) return false;"
                "sb.classList.add('on');"
                "const bot=parseFloat(getComputedStyle(b).bottom);"
                "const sbB=parseFloat(getComputedStyle(sb).bottom);"
                "const ok=bot>=sb.offsetHeight+sbB+8;"
                "sb.classList.remove('on');return ok;}"))
            # ①health() 失败不再静默：fulfill 非 JSON 200（不用 abort：
            # ERR_FAILED 会进 console error 污染零 JS 错门禁）后 reload，
            # 健康空态点亮错误文案；healthcard 已有时保陈旧不闪错
            pg.route("**/api/health", lambda r: r.fulfill(
                status=200, content_type="text/plain",
                body="service unavailable"))
            pg.reload(wait_until="networkidle"); pg.wait_for_timeout(900)
            ck("健康接口失败点亮错误文案", pg.evaluate(
                "()=>{const e=document.getElementById('healthEmpty');"
                "const c=document.getElementById('healthcard');"
                "return !!e&&e.style.display===''&&(e.textContent||'')"
                ".indexOf('健康数据读取失败')>=0"
                "&&!!c&&c.style.display==='none';}"))
            pg.unroute("**/api/health")
            # ---- 弹层在途取消 ----
            # showLog → /api/logtail 在途时按 Esc：曾被级联处理器无视、
            # 响应到达后弹层照样弹出（previewPush ~27s 构建期把不可取
            # 消窗放大两个数量级）。hold 放行制走真实响应路径；先切健
            # 康 tab 保证 .hc 可点（display 翻转架构下隐藏容器点不到），
            # 测后状态复位回概览（CHR.i 同律）。
            _gate = {"open": False}

            def _hold_logtail(route):
                import time as _t
                _t0 = _t.time()
                while not _gate["open"] and _t.time() - _t0 < 5:
                    pg.wait_for_timeout(50)
                route.continue_()

            pg.route("**/api/logtail*", _hold_logtail)
            # 前一枚健康失败钉把 healthcard 留在错误态（.hc 未渲染）：
            # 先 reload 恢复正常健康区再等格子出现
            pg.reload(wait_until="networkidle")
            pg.evaluate("switchView('mon');showMonTab('health')")
            pg.wait_for_selector(".hc", timeout=8000)
            pg.evaluate("document.querySelector('.hc').click()")
            pg.wait_for_timeout(200)
            ck("弹层在途 hold 期未现", not pg.evaluate(
                "$('pvMask').classList.contains('on')"))
            pg.keyboard.press("Escape")
            _gate["open"] = True
            pg.wait_for_timeout(900)
            ck("弹层在途 Esc 取消后响应到达不弹",
               not pg.evaluate("$('pvMask').classList.contains('on')"))
            pg.unroute("**/api/logtail*")
            pg.evaluate("showMonTab('overview')"); pg.wait_for_timeout(200)
            # ---- 推送记录降级留痕渲染 ----
            # img 注仅在降级条目出现（琥珀小注），正常/无注条目不受扰
            pg.route("**/api/pushlog", lambda r: r.fulfill(
                status=200, content_type="application/json",
                body=json.dumps({"ok": True, "items": [
                    {"ts": "2026-09-28 20:00:00", "ok": True,
                     "ch": "email", "img": "图0/1内嵌",
                     "title": "t1", "desp": "d"},
                    {"ts": "2026-09-28 19:45:00", "ok": True,
                     "ch": "dingtalk", "title": "t2", "desp": "d"},
                ]}, ensure_ascii=False)))
            pg.evaluate("pushLog()"); pg.wait_for_timeout(500)
            ck("推送记录降级 img 注渲染", pg.evaluate(
                "()=>{const b=document.getElementById('pvBody');"
                "return !!b&&b.innerHTML.indexOf('图0/1内嵌')>=0;}"))
            ck("推送记录正常条目无 img 注", pg.evaluate(
                "()=>{const b=document.getElementById('pvBody');"
                "return !!b&&(b.innerText.match(/图\\d\\/\\d内嵌/g)||[])"
                ".length===1;}"))
            pg.evaluate("closePv()")
            pg.unroute("**/api/pushlog")

            # ---- EN 增强：脉冲卡入概览（首屏税）/桌面吸顶/中转列条件
            #      隐藏/配置即时校验/价格字号阶梯 ----
            # EN-1 脉冲卡移入概览 tab：details/trend/health 首屏省 ~252px。
            # DOM 位置钉 + tab 联动可见性钉 + 概览内 KPI 先于脉冲的序钉
            ck("EN-1 脉冲卡位于概览 tab 内", pg.evaluate(
                "()=>!!document.querySelector('#montab-overview #pulsecard')"))
            ck("EN-1 明细 tab 下脉冲卡随容器隐藏", pg.evaluate(
                "()=>{showMonTab('details');table();"
                "const w=document.getElementById('pulsecard').offsetWidth;"
                "showMonTab('overview');return w===0;}"))
            ck("EN-1 概览 KPI 先于脉冲卡", pg.evaluate(
                "()=>{const p=document.getElementById('pulsecard');"
                "if(!p)return false;const d=p.style.display;p.style.display='';"
                "const k=document.querySelector('#montab-overview .kpi');"
                "const ok=!!k&&k.getBoundingClientRect().top"
                "<p.getBoundingClientRect().top;"
                "p.style.display=d;return ok;}"))
            # 红帽徽标：采集失败或推送连败（双源合成）点亮概览 tab
            # 红点——渠道/推送异常在其他 tab 仍全局可见（可见性定律）
            ck("EN-1 红帽徽标随最新轮失败点亮/熄灭", pg.evaluate(
                "()=>{if(typeof renderPulseAlert!=='function')return false;"
                "renderPulseAlert(2);"
                "const on=document.getElementById('ovAlert')"
                ".style.display!=='none';"
                "renderPushChannels({channels:{}});renderPulseAlert(0);"
                "const off=document.getElementById('ovAlert')"
                ".style.display==='none';return on&&off;}"))
            # EN-1b 红帽徽标几何行为钉：点亮态实际盒须有形状（空 <i>
            # 内联元素 width 不参与布局，曾是 0 宽死档——display 态钉
            # 锁「状态」锁不了「形状」，几何实测是唯一真相）
            ck("EN-1b 红帽徽标点亮态实盒有形状", pg.evaluate(
                "()=>{renderPulseAlert(2);"
                "const a=document.getElementById('ovAlert');"
                "const w=a.getBoundingClientRect().width;"
                "renderPushChannels({channels:{}});renderPulseAlert(0);"
                "return w>=6;}"))
            # EN-9（WebUI 审计）：徽标读屏语义——role+aria-label 静态
            # 在位（display:none 天然从可访问性树移除，点亮即暴露），
            # 渠道异常可见性定律对读屏不再缺失
            ck("EN-9 红帽徽标读屏语义在位", pg.evaluate(
                "()=>{const a=document.getElementById('ovAlert');"
                "return !!a&&a.getAttribute('role')==='img'"
                "&&(a.getAttribute('aria-label')||'')"
                ".indexOf('通道有异常')>=0;}"))
            # EN-2 桌面视图切换器吸顶：深滚切视图不回滚（≤540 同款能力）。
            # 几何行为钉（LESSONS：源码钉只证声明在场，几何钉是唯一真相）
            pg.set_viewport_size({"width": 1440, "height": 900})
            pg.evaluate("gotoMonTab('details');setFltOpen(true)"); pg.wait_for_timeout(500)
            pg.evaluate("window.scrollTo(0,1400)"); pg.wait_for_timeout(300)
            ck("EN-2 桌面 montabs 深滚吸顶贴 header", pg.evaluate(
                "()=>{const m=document.getElementById('montabs')"
                ".getBoundingClientRect();"
                "const h=document.querySelector('header')"
                ".getBoundingClientRect();"
                "return window.scrollY>100&&m.top>=h.bottom-2"
                "&&m.top<=h.bottom+6;}"))
            # EN-2 带内覆写（Soldier P1-1）：761-900 带 header 折行实高
            # ~72px，吸顶单值 54px 时吸顶条 58% 面积被不透明 header 盖
            # （tab 词面不可读）——带内 top:76px 覆写+锚点补偿同块联动；
            # 1440 钉只量宽档，该带行为由本钉守护
            pg.set_viewport_size({"width": 800, "height": 900})
            pg.wait_for_timeout(300)
            pg.evaluate("gotoMonTab('details');setFltOpen(true)"); pg.wait_for_timeout(400)
            pg.evaluate("window.scrollTo(0,1200)"); pg.wait_for_timeout(300)
            ck("EN-2 800 带吸顶贴折行 header 底", pg.evaluate(
                "()=>{const m=document.getElementById('montabs')"
                ".getBoundingClientRect();"
                "const h=document.querySelector('header')"
                ".getBoundingClientRect();"
                "return window.scrollY>100&&m.top>=h.bottom-2"
                "&&m.top<=h.bottom+6;}"))
            ck("EN-2 800 带锚点补偿过吸顶双条", pg.evaluate(
                "()=>{const spt=parseInt(getComputedStyle("
                "document.documentElement).scrollPaddingTop);"
                "const h=document.querySelector('header').offsetHeight;"
                "return spt>=h+30&&spt<=h+40;}"))
            pg.set_viewport_size({"width": 1440, "height": 900})
            pg.wait_for_timeout(300)
            ck("EN-1 明细首屏可见数据行", pg.evaluate(
                "()=>{showMonTab('details');table();"
                "window.scrollTo(0,0);"
                "const r=document.querySelector('#ftable tbody tr[data-k]');"
                "if(!r)return false;"
                "return r.getBoundingClientRect().bottom"
                "<=window.innerHeight;}"))
            # EN-7 价格字号阶梯：主判据 15px 与次要字段拉开（compact 档
            # 保持 13px 密度语义）；1440 档零横滚是字号加档的前提前钉
            ck("EN-7 cozy 档明细价格 15px", pg.evaluate(
                "()=>{const td=document.querySelector('#ftable td.price');"
                "return !!td&&getComputedStyle(td).fontSize==='15px';}"))
            ck("EN-7 compact 档价格保持 13px", pg.evaluate(
                "()=>{document.documentElement.dataset.density='compact';"
                "const td=document.querySelector('#ftable td.price');"
                "const s=td&&getComputedStyle(td).fontSize;"
                "document.documentElement.dataset.density='cozy';"
                "return s==='13px';}"))
            ck("EN-7 1440 明细窗零横向滚动", pg.evaluate(
                "()=>{const tw=document.querySelector('#tablecard .tw');"
                "return tw.scrollWidth<=tw.clientWidth+1;}"))
            # EN-5 中转列条件隐藏：全直飞视图整列「—」零信息 → 隐藏整列
            # （按当前筛选结果集判定，非全库）；xrow colspan 展开行不受扰
            ck("EN-5 全直飞视图中转列隐藏", pg.evaluate(
                "()=>{F='d';table();"
                "const t=document.getElementById('ftable');"
                "const ok=t.classList.contains('no-transfer')"
                "&&getComputedStyle(t.querySelector('th:nth-child(8)'))"
                ".display==='none';"
                "F='all';table();return ok;}"))
            ck("EN-5 混入中转行后中转列回显", pg.evaluate(
                "()=>{const u=S.users[U];"
                "u.flights.push(Object.assign({},u.flights[0],"
                "{transfer:true,trans:'西安'}));table();"
                "const t=document.getElementById('ftable');"
                "const ok=!t.classList.contains('no-transfer')"
                "&&getComputedStyle(t.querySelector('th:nth-child(8)'))"
                ".display!=='none';"
                "u.flights.pop();table();return ok;}"))
            ck("EN-5 全直飞档展开行仍横贯表宽", pg.evaluate(
                "()=>{F='d';table();"
                "const x=document.querySelector('#ftable tr.xrow');"
                "if(!x){F='all';table();return true;}"   # 无比价样本免测
                "const tb=document.getElementById('ftable')"
                ".getBoundingClientRect().width;"
                "x.style.display='';"
                "const w=x.querySelector('td')"
                ".getBoundingClientRect().width;"
                "x.style.display='none';F='all';table();"
                "return w>=tb-60;}"))
            # EN-6 配置即时校验：输入即标红+行内提示、改对即清；与
            # saveCfg 共用同一张规则表（校验单源，防两处漂移）
            pg.evaluate("switchView('cfg')"); pg.wait_for_timeout(400)
            pg.click('#cfgnav .cnav[data-p="globals"]')
            pg.wait_for_timeout(400)
            ck("EN-6 周期越界即时标红+行内提示", pg.evaluate(
                "()=>{const el=document.getElementById('glbIv');"
                "if(!el||typeof glbCheck!=='function')return false;"
                "el.value='3';glbCheck(el);"
                "const bad=el.classList.contains('invalid');"
                "const eb=document.getElementById('glbIvErr');"
                "const msg=(eb&&eb.textContent||'').indexOf('5-10080')>=0;"
                "el.value='30';glbCheck(el);"
                "const good=!el.classList.contains('invalid');"
                "return bad&&msg&&good;}"))
            ck("EN-6 端口越界同表校验", pg.evaluate(
                "()=>{const el=document.getElementById('glbPort');"
                "if(!el||typeof glbCheck!=='function')return false;"
                "el.value='80';glbCheck(el);"
                "const bad=el.classList.contains('invalid');"
                "el.value='8765';glbCheck(el);"
                "return bad&&!el.classList.contains('invalid');}"))
            # 状态复位（CHR.i 同律）：面板回 login、视图回监控、视口回主档
            pg.click('#cfgnav .cnav[data-p="login"]')
            pg.wait_for_timeout(300)
            pg.evaluate("switchView('mon');showMonTab('overview')")
            pg.wait_for_timeout(300)
            pg.set_viewport_size({"width": 1280, "height": 900})
            pg.wait_for_timeout(300)

            # ---- hash 用户段恒随 tab 写点（M-1）/跳明细重置
            # 告知（M-2）/CSV 导出成功反馈（增强③）。行为钉：源码钉
            # （tests/test_v15113_webui.py）只证声明在场，此处证真实
            # 生效；toast 检查先清 #toasts 防前序残留假绿 ----
            ck("M-1 tab 写点 hash 带用户段", pg.evaluate(
                "()=>{pickUser(0);showMonTab('trend');"
                "return location.hash.indexOf('/u0')>0;}"))
            ck("M-2 跳明细重置筛选告知", pg.evaluate(
                "()=>{const old=document.getElementById('toasts');"
                "if(old)old.innerHTML='';jumpTrendDetail();"
                "const t=document.getElementById('toasts');"
                "return !!(t&&t.textContent.indexOf('已重置现有筛选')>=0);}"))
            ck("CSV 导出成功反馈", pg.evaluate(
                "()=>{const old=document.getElementById('toasts');"
                "if(old)old.innerHTML='';expCsv();"
                "const t=document.getElementById('toasts');"
                "return !!(t&&t.textContent.indexOf('已导出')>=0);}"))
            # 状态复位：清筛选锁、回概览（jumpTrendDetail 落的日期
            # 锁不还原会漏进后续断言）
            pg.evaluate("resetFlt();buildChips();buildRouteChips();"
                        "buildDateChips();showMonTab('overview')")
            pg.wait_for_timeout(300)

            # ---- P0 修复钉：启动恢复的 silent 写点不得污染深链 ----
            # 预置 jpmontab=details（模拟回访者 localStorage），带
            # #trend/u0 双段深链冷开：tab 应跟深链（启动块解析 /u 段）、
            # hash 应原样保留（silent 档不写 hash）。修复前：MONTAB
            # 被 localStorage 拉成 details、hash 被 silent 写点覆写成
            # #details/u0（深链用户段连带被 U=0 污染，回访者静默丢人）
            pg.evaluate("try{localStorage.setItem('jpmontab','details')"
                        "}catch(e){}")
            pg.goto(BASE + "#trend/u0", wait_until="domcontentloaded")
            pg.wait_for_timeout(1500)
            ck("启动深链双段恢复+hash 零污染", pg.evaluate(
                "()=>(typeof MONTAB!=='undefined'&&MONTAB==='trend'"
                "&&location.hash==='#trend/u0')"))

            # ---- 擦边词面双端同语言钉：pctTxt 半点向上 + ≤0.5 边界
            # 档（与推送 _near_txt 同契约）；输入式与 near 判定同式
            # ((p-t)*100/t)，先除后减的浮点在 x.5 中点向下偏曾致
            # 同价两端词面一档分叉 ----
            ck("pctTxt 半点向上+0.5 边界档", pg.evaluate(
                "()=>(typeof pctTxt==='function'"
                "&&pctTxt(2.5)===3&&pctTxt(1.5)===2"
                "&&pctTxt(0.5)==='不足1'&&pctTxt(0.51)===1"
                "&&pctTxt(0.49)==='不足1')"))
            ck("擦边输入式与判定同式（中点不偏）", pg.evaluate(
                "()=>(typeof pctTxt==='function'"
                "&&pctTxt((2050-2000)*100/2000)===3)"))
            # ---- E-P3-1 恰达线词面钉：diffTxt d===0 显式分支——
            # 旧 d<=0 合并分支在价恰等线（整数价×整数阈值域可达）
            # 出「已低于线 ￥0」字面自相矛盾；恰达线白话=「已达线」
            # （推送端 gap_txt 恰达线专门词面「真达标」同域），负差
            # 额与超线两邻域形态不随分支拆分漂移 ----
            ck("diffTxt 恰达线分支（d===0 不出 ￥0 病态）", pg.evaluate(
                "()=>(typeof diffTxt==='function'"
                "&&diffTxt(2400,2400).includes('已达线')"
                "&&!diffTxt(2400,2400).includes('￥0')"
                "&&diffTxt(2300,2400).includes('已低于线 ￥100')"
                "&&diffTxt(2500,2400).startsWith('差￥100'))"))

            # ---- W-2 行为钉：入场动画首帧负 p 钳零——初入走势
            # 900ms 后 y 轴标签带 [2,18) 必有 ￥ 墨迹（负宽 clip 曾把
            # 首帧行归一进标签带，clearRect 擦带后永不回补）。取墨迹
            # 前后无截图动作（getImageData 与截图分页判例） ----
            pg.evaluate("CHART_ANIM=1;showMonTab('trend')")
            pg.wait_for_timeout(1300)
            ck("走势首入 y 轴标墨迹在带", pg.evaluate(
                "()=>{const c=document.getElementById('chart');"
                "const ctx=c.getContext('2d');"
                "const img=ctx.getImageData(2,30,16,"
                "Math.max(10,c.height-60)).data;let ink=0;"
                "for(let i=3;i<img.length;i+=4)if(img[i]>40)ink++;"
                "return ink>15;}"))

            # ---- W-1 行为钉：390 档视图切换器单行横滚——第 4 格
            # 完整高度落容器内（折行曾被锁高裁成 10px 残条）+ 真溢出
            # 时 xhint 暗示点亮。先测后拍（本段无截图动作） ----
            pg.set_viewport_size({"width": 390, "height": 780})
            pg.wait_for_timeout(500)
            _w1 = pg.evaluate(
                "()=>{const mb=document.getElementById('montabs');"
                "const cr=mb.getBoundingClientRect();"
                "const ts=[...mb.querySelectorAll('.mtab')];"
                "const r=ts[ts.length-1].getBoundingClientRect();"
                "return {h:r.height,inside:r.top>=cr.top-1&&"
                "r.bottom<=cr.bottom+1,n:ts.length,"
                "sw:mb.scrollWidth,cw:mb.clientWidth,"
                "xh:mb.classList.contains('xhint'),"
                "vis:mb.offsetParent!==null};}")
            ck("390 档切换器末格完整在容器", bool(
                _w1 and _w1.get("n") in (5, 6) and _w1.get("h", 0) >= 30
                and _w1.get("inside") and _w1.get("vis")))
            # 溢出暗示阈值判定：EN-6 字号归并后 390 档内容溢出收窄至
            # 3px（<4px「可滚才挂」阈值）——暗示不亮是正确行为（3px
            # 裁角不值得横滚），钉住「容差内放下不误挂」新事实
            # r368 更长的用户级 tab 名（关注航线走势/关注航班走势/关注航班明细）
            # 在 390 必然可横滚：暗示灯必须与「真溢出」同拍，不误挂也不漏挂
            ck("390 档切换器溢出暗示同拍", bool(
                _w1 and _w1.get("xh") == (
                    _w1.get("sw", 0) > _w1.get("cw", 0) + 4)))

            # ---- EN-W4 行为钉：mtab 方向键族移动 + Enter 激活 ----
            pg.evaluate(
                "()=>{const ts=document.querySelectorAll('#montabs .mtab');"
                "ts[ts.length-2].focus()}")
            pg.keyboard.press("ArrowRight")
            ck("mtab 方向键族移动", pg.evaluate(
                "()=>document.activeElement&&"
                "document.activeElement.dataset&&"
                "document.activeElement.dataset.t==='health'"))
            pg.keyboard.press("Enter")
            pg.wait_for_timeout(300)
            ck("mtab Enter 激活切 tab", pg.evaluate(
                "()=>(typeof MONTAB!=='undefined'&&MONTAB==='health')"))
            # 状态复位：视口回默认、tab 回走势（防漏进汇总断言）
            pg.set_viewport_size({"width": 1280, "height": 900})
            pg.evaluate("showMonTab('trend')")
            pg.wait_for_timeout(300)

            # ---- WD P1-1 行为钉：--hdh 动态 header 高度单源——JS 撑高
            # header 后变量实时跟随、吸顶条贴新实高底（固定像素家族在
            # 倒计时折行下曾盖住切换器 33px）。状态复位：height 清空 ----
            pg.set_viewport_size({"width": 800, "height": 900})
            pg.wait_for_timeout(300)
            pg.evaluate("gotoMonTab('details');setFltOpen(true)")
            pg.evaluate(
                "document.getElementById('hdcard').style.height='120px'")
            pg.wait_for_timeout(400)
            pg.evaluate("window.scrollTo(0,1200)")
            pg.wait_for_timeout(300)
            ck("--hdh 随 header 实高实时跟随", pg.evaluate(
                "()=>document.documentElement.style.getPropertyValue"
                "('--hdh')==='120px'"))
            ck("--hdh 吸顶贴动态实高底", pg.evaluate(
                "()=>{const m=document.getElementById('montabs')"
                ".getBoundingClientRect();"
                "const h=document.querySelector('header')"
                ".getBoundingClientRect();"
                "return window.scrollY>100&&m.top>=h.bottom-2"
                "&&m.top<=h.bottom+6;}"))
            pg.evaluate(
                "document.getElementById('hdcard').style.height=''")
            pg.wait_for_timeout(400)
            # --hdh 视口折行跟随钉（媒体查询驱动的布局变化路径——生产
            # 768 带 header 折行 54→109 是真实触发形态；style 内联撑高
            # 钉只验了 RO 链路，本钉验布局驱动路径。IAB 嵌入视口 RO
            # 不派发属测试环境伪影，行为真相以真实 Chromium 为准）
            pg.set_viewport_size({"width": 800, "height": 900})
            pg.wait_for_timeout(600)
            ck("--hdh 随视口折行跟随", pg.evaluate(
                "()=>{const hd=document.getElementById('hdcard');"
                "return document.documentElement.style.getPropertyValue"
                "('--hdh')==hd.offsetHeight+'px';}"))
            pg.set_viewport_size({"width": 1280, "height": 900})
            pg.wait_for_timeout(600)
            ck("--hdh 回宽档跟随", pg.evaluate(
                "()=>{const hd=document.getElementById('hdcard');"
                "return document.documentElement.style.getPropertyValue"
                "('--hdh')==hd.offsetHeight+'px';}"))

            # ---- M-4 行为钉：cfgnav sticky top 贴 header 动态实高
            # （--hdh 同族单源：配置页导航固定像素在 header 实高变化时
            # 被盖。demo cfg 内容不足一屏 sticky 行程不足——向内容列
            # 注入 spacer 撑出行程；量完逐项复位）----
            pg.evaluate("switchView('cfg')")
            pg.evaluate(
                "const d=document.createElement('div');"
                "d.id='m4spacer';d.style.height='2500px';"
                "document.getElementById('cfgmain').appendChild(d)")
            pg.evaluate(
                "document.getElementById('hdcard').style.height='120px'")
            pg.wait_for_timeout(400)
            pg.evaluate("window.scrollTo({top:400,behavior:'instant'})")
            pg.wait_for_timeout(300)
            ck("cfgnav 吸顶贴动态实高底", pg.evaluate(
                "()=>{const n=document.getElementById('cfgnav')"
                ".getBoundingClientRect();"
                "const h=document.querySelector('header')"
                ".getBoundingClientRect();"
                "return window.scrollY>80&&n.top>=h.bottom+2"
                "&&n.top<=h.bottom+6;}"))
            pg.evaluate(
                "document.getElementById('hdcard').style.height=''")
            pg.evaluate("document.getElementById('m4spacer').remove()")
            pg.wait_for_timeout(400)
            pg.evaluate("gotoMonTab('details')")
            pg.evaluate("window.scrollTo({top:0,behavior:'instant'})")
            pg.wait_for_timeout(200)

            # ---- WD P2-2 行为钉：kpisum 行内链接触控外扩（本体 h=16
            # 曾为全站最小可点件；::after inset 补命中区，视觉零变化）----
            _kz = pg.evaluate(
                "()=>{const a=document.querySelector('.kpisum a');"
                "if(!a)return null;"
                "const s=getComputedStyle(a,'::after');"
                "return s.position==='absolute'&&s.content!=='none';}")
            ck("kpisum 链接触控外扩在位", bool(_kz))

            # ---- M-1 行为钉：numlink 触控热区外扩在位 ----
            ck("numlink 触控热区外扩在位", pg.evaluate(
                "()=>{const a=document.querySelector('a.numlink');"
                "if(!a)return false;"
                "const s=getComputedStyle(a,'::after');"
                "return s.position==='absolute'&&s.content!=='none';}"))

            # ---- M-2 行为钉：文本链接焦点环并入全站清单 ----
            ck("文本链接焦点环清单", pg.evaluate(
                "()=>{let ok=false;"
                "for(const sh of document.styleSheets){"
                "try{for(const r of sh.cssRules){"
                "const s=r.selectorText||'';"
                "if(s.indexOf('a.numlink:focus-visible')>=0"
                "&&s.indexOf('.kpisum a:focus-visible')>=0)ok=true;}}"
                "catch(e){}}return !!ok;}"))

            # ---- EN-4 行为钉：montab 方向键族——541-760 已随 EN-5
            # 收敛为单行形制（2×2 网格场景退场）：单行 ↓/↑ 自然 no-op
            # 不误跳（_rovingV 几何分组保留为防御路径）----
            pg.set_viewport_size({"width": 600, "height": 900})
            pg.wait_for_timeout(400)
            pg.evaluate("showMonTab('overview')")
            pg.wait_for_timeout(200)
            pg.evaluate(
                "document.querySelectorAll('#montabs .mtab')[0].focus()")
            pg.keyboard.press("ArrowDown")
            ck("montab ↓ 单行 no-op 不误跳", pg.evaluate(
                "()=>document.activeElement&&"
                "document.activeElement.dataset&&"
                "document.activeElement.dataset.t==='overview'"))
            pg.keyboard.press("ArrowUp")
            ck("montab ↑ 单行 no-op 不误跳", pg.evaluate(
                "()=>document.activeElement&&"
                "document.activeElement.dataset&&"
                "document.activeElement.dataset.t==='overview'"))

            # ---- EN-5 行为钉：541-760 带切换器吸顶贴 header 实高 ----
            ck("541-760 切换器吸顶贴 header", pg.evaluate(
                "()=>{const m=document.getElementById('montabs'),"
                "hd=document.querySelector('header');"
                "window.scrollTo(0,999999);"
                "return new Promise(r=>setTimeout(()=>{"
                "const h=hd.offsetHeight,t=m.getBoundingClientRect().top;"
                "r(getComputedStyle(m).position==='sticky'"
                "&&t>=h-2&&t<=h+6);},350));}"))
            # P2-1 行为钉：明细栏吸顶可达（.tw 放开跟页滚是结构前提——
            # 内滚 max-height 锁死页高时触发点 237px>最大滚动 129px=
            # 声明死代码；概览档恒绿曾掩盖本面）
            ck("541-760 明细栏切换器吸顶可达", pg.evaluate(
                """()=>{gotoMonTab('details');
                window.scrollTo(0,999999);
                return new Promise(r=>setTimeout(()=>{
                const m=document.getElementById('montabs')
                  .getBoundingClientRect(),h=document.querySelector('header')
                  .getBoundingClientRect();
                const ok=window.scrollY>150
                 &&m.top>=h.bottom-2&&m.top<=h.bottom+6;
                showMonTab('overview',true);
                window.scrollTo({top:0,behavior:'instant'});
                r(ok);},350));}"""))

            # ---- r224 P1-1 行为钉：541-760 带锚点补偿覆盖吸顶双件——
            # --mtabsh 带内无定义时整条 calc 塌 0（computed 落 auto，
            # 锚点被 header+切换器遮挡实测 102px）。钉=computed
            # scroll-padding-top ≥ header+切换器实高 ----
            ck("541-760 锚点补偿过吸顶双件", pg.evaluate(
                "()=>{const sp=parseFloat(getComputedStyle("
                "document.documentElement).scrollPaddingTop);"
                "const hd=document.querySelector('header').offsetHeight;"
                "const mt=document.getElementById('montabs').offsetHeight;"
                "return sp>=hd+mt-2;}"))
            ck("541-760 锚点跳转落点不被遮挡", pg.evaluate(
                """()=>{gotoMonTab('details');
                const t=document.querySelector('#ftable tbody tr');
                t.scrollIntoView({block:'start'});
                return new Promise(r=>setTimeout(()=>{
                const top=t.getBoundingClientRect().top;
                const hd=document.querySelector('header').offsetHeight;
                const mt=document.getElementById('montabs').offsetHeight;
                const ok=top>=hd+mt-6&&top<hd+mt+150;   /* r302 T1：demo 倒计时 chip 进 header 后实高按内容漂移，绝对上限 200 是旧单行头校准值——「不被遮挡」的本体语义=落在双吸顶件下方近处，改相对断言（二十一§7：动态化同轮固定值钉改相对） */
                showMonTab('overview',true);
                window.scrollTo({top:0,behavior:'instant'});
                r(ok);},350));}"""))

            # ---- EN-3 行为钉：显式重置入口恢复默认排序+告知；跳转类
            # 直调 resetFlt 不播报（单条 toast 纪律）----
            ck("resetFltUI 排序复位+告知", pg.evaluate(
                "()=>{SORT={k:'date',dir:-1};resetFltUI();"
                "const told=[...document.querySelectorAll('.toast')]"
                ".some(t=>t.textContent.indexOf('排序')>=0);"
                "return SORT.k==='price'&&SORT.dir===1&&told;}"))
            ck("resetFlt 直调不重复播报", pg.evaluate(
                "()=>{const n=document.querySelectorAll('.toast').length;"
                "SORT={k:'date',dir:-1};resetFlt();"
                "return SORT.k==='price'"
                "&&document.querySelectorAll('.toast').length===n;}"))

            # ---- EN-6 行为钉：全页字号阶梯无 x.5 半步 ----
            ck("字号阶梯无半步", pg.evaluate(
                "()=>[...document.querySelectorAll('body *')]"
                ".filter(e=>e.getClientRects().length>0)"
                ".every(e=>!/\\.5px$/.test("
                "getComputedStyle(e).fontSize))"))

            # 状态复位：视口回默认、tab 回走势
            pg.set_viewport_size({"width": 1280, "height": 900})
            pg.evaluate("showMonTab('trend')")
            pg.wait_for_timeout(300)

            # ---- r224 P2-3 行为钉：选中态 rngchip 键盘焦点环不被同
            # 特异性辉光盖掉（.rngchip.on 声明序压过环块，LESSONS
            # 廿一§1）——程序化强焦取值后 blur 复位（焦点状态复位律） ----
            ck("选中 rngchip 聚焦蓝环", pg.evaluate(
                "()=>{const c=document.querySelector('.rngchip.on');"
                "if(!c)return false;"
                "c.focus({focusVisible:true});"
                "const s=getComputedStyle(c).boxShadow;"
                "c.blur();"
                "return s.indexOf('0px 0px 0px 2px')>=0;}"))

            # ---- EN-1 行为钉：768 带头部两行制（hdmeta 与 pill 同 flex 行；
            # 同行元素高不同，判据=垂直区间重叠而非 top 相等）----
            pg.set_viewport_size({"width": 768, "height": 900})
            pg.wait_for_timeout(400)
            ck("768 头部两行制", pg.evaluate(
                "()=>{const p=document.getElementById('pill')"
                ".getBoundingClientRect();"
                "const m=document.querySelector('.hdmeta')"
                ".getBoundingClientRect();"
                "return p.top<m.bottom&&m.top<p.bottom;}"))
            # 状态复位：视口回默认
            pg.set_viewport_size({"width": 1280, "height": 900})
            pg.wait_for_timeout(300)

            # ---- r221 行为钉：刻度悬崖/双卡地板/按钮顶线/kpisum 分隔符/
            # 徽标折行/焦点环即时 ----
            # P1-1 刻度悬崖：48h 默认窗 demo 数据落悬崖带（lo≈1630/
            # hi≈2060，raw≈107.5，旧档步长 200 仅 2 条网格线）——
            # fillText 钩原型按 x<30 计 Y 轴 ￥ 标签 ≥4
            pg.evaluate("showMonTab('trend')")
            pg.wait_for_timeout(400)
            ck("走势 Y 轴刻度悬崖带 ≥4 条", pg.evaluate(
                """()=>{
                  let n=0;
                  const orig=CanvasRenderingContext2D.prototype.fillText;
                  CanvasRenderingContext2D.prototype.fillText=function(t,x){
                    if(String(t).lastIndexOf('￥',0)===0&&x<30)n++;
                    return orig.apply(this,arguments);};
                  try{chart();}catch(e){}
                  return new Promise(res=>setTimeout(()=>{
                    CanvasRenderingContext2D.prototype.fillText=orig;
                    res(n);},1200));}""") >= 4)
            # P2-2 双卡地板：600-659 带回落基础 auto-fit（280 地板），
            # 620 实测卡宽 ≥280（旧固定双卡 252-282 曾破下限）
            pg.evaluate("showMonTab('overview')")
            pg.set_viewport_size({"width": 620, "height": 900})
            pg.wait_for_timeout(400)
            ck("620 带 KPI 卡 ≥280 地板", pg.evaluate(
                "()=>{const cs=[...document.querySelectorAll('.grid>*')]"
                ".map(e=>e.getBoundingClientRect().width).filter(w=>w>0);"
                "return !!cs.length&&Math.min(...cs)>=280;}"))
            pg.set_viewport_size({"width": 1280, "height": 900})
            pg.wait_for_timeout(400)
            # P2-3 按钮顶线：warn 边框改 inset 环后主/次按钮同高同顶线
            ck("opscard 按钮顶线齐", pg.evaluate(
                """()=>{
                  const bs=document.querySelectorAll('#opscard .row button');
                  if(bs.length<2)return false;
                  const a=bs[0].getBoundingClientRect(),
                        b=bs[1].getBoundingClientRect();
                  return Math.abs(a.top-b.top)<0.6
                    &&Math.abs(a.height-b.height)<=1;}"""))
            # P2-4 分隔符悬空：｜ 全部收进 nowrap 单元，kpisum 直接
            # 子级零裸 ｜ 文本节点（360 折行后行尾不再孤挂）
            ck("kpisum 分隔符不悬空", pg.evaluate(
                """()=>{const k=document.querySelector('.kpisum');
                  if(!k)return false;
                  for(const n of k.childNodes)
                    if(n.nodeType===3
                       &&n.textContent.indexOf('｜')>=0)return false;
                  return true;}"""))
            # P2-5 桌面档价格列 ≥2 徽标折第二行（:has 计数），单徽标
            # 维持行内（税前独挂形态不折）
            pg.evaluate("showMonTab('details')")
            pg.wait_for_timeout(300)
            ck("价格列 ≥2 徽标桌面折行", pg.evaluate(
                """()=>{
                  const tb=document.querySelector('#ftable tbody')
                    ||document.querySelector('#ftable');
                  if(!tb)return false;
                  const t1=document.createElement('tr');
                  t1.innerHTML='<td class="price">￥100'
                    +'<span class="pretax">税前</span>'
                    +'<span class="pretax">退改￥50</span></td><td></td>';
                  const t2=document.createElement('tr');
                  t2.innerHTML='<td class="price">￥100'
                    +'<span class="pretax">税前</span></td><td></td>';
                  tb.insertBefore(t2,tb.firstChild);
                  tb.insertBefore(t1,t2);
                  const d1=getComputedStyle(
                    t1.querySelectorAll('.pretax')[0]).display;
                  const d2=getComputedStyle(
                    t2.querySelector('.pretax')).display;
                  t1.remove();t2.remove();
                  return d1==='block'&&d2==='inline';}"""))
            pg.evaluate("showMonTab('overview')")
            pg.wait_for_timeout(300)
            # P2-6 焦点环即时呈现：基座 .15s transition 曾把环拖成
            # 淡入（Tab 巡航滞后 ~150ms）——focus 规则内 box-shadow 0s。
            # focus({focusVisible:true}) 强制 :focus-visible（Tab 序受
            # 前序小节焦点状态漂移影响，程序化直焦确定性）+ 环在位双证
            ck("焦点环即时呈现（无淡入）", pg.evaluate(
                """()=>{
                  const b=document.querySelector('#opscard .row button');
                  if(!b)return false;
                  b.focus({focusVisible:true});
                  const c=getComputedStyle(b);
                  return c.transitionDuration==='0s'
                    &&c.boxShadow.indexOf('11, 98, 214')>=0;}"""))
            # 状态复位：视口回默认、tab 回走势
            pg.set_viewport_size({"width": 1280, "height": 900})
            pg.evaluate("showMonTab('trend')")
            pg.wait_for_timeout(300)

            # ---- r227 WebUI 审计钉四件：P1-1 断词孤字（fb 行「经X」
            # 词组粒度 nowrap——CJK 逐字断行曾把「经郑州」折成「经郑/
            # 州」）；P1-2 中带日历孤格（1280 档 15 格 14+1 悬挂，
            # 1000-1439 带改 grid 等分恒单行）；P2-1 暗色 qual 底
            # stoptag 与 .stl 成对提亮；P2-2 .switch UA 黑收口 ----
            pg.set_viewport_size({"width": 768, "height": 900})
            pg.evaluate("showMonTab('overview')")
            pg.wait_for_timeout(400)
            ck("fb 行中转段词组粒度不折行", pg.evaluate(
                """()=>{
                  const els=[...document.querySelectorAll('.kpi .fb .nw')];
                  return els.length>0&&els.every(e=>
                    getComputedStyle(e).whiteSpace==='nowrap');}"""))
            pg.set_viewport_size({"width": 1280, "height": 900})
            pg.evaluate("showMonTab('trend')")
            pg.wait_for_timeout(400)
            ck("1280 档日历格恒单行", pg.evaluate(
                """()=>{
                  const cs=[...document.querySelectorAll(
                    '.calgrid .calcell')];
                  if(cs.length<10)return false;
                  const tops=new Set(cs.map(c=>
                    Math.round(c.getBoundingClientRect().top)));
                  return tops.size===1;}"""))
            ck("暗色 qual 行 stoptag 提亮", pg.evaluate(
                """()=>{
                  document.documentElement.dataset.theme='dark';
                  const t=document.querySelector(
                    'tr.qual .stoptag');
                  const c=t&&getComputedStyle(t).color;
                  document.documentElement.dataset.theme='';
                  return c==='rgb(139, 160, 180)';}"""))
            ck("switch UA 黑收口", pg.evaluate(
                """()=>{
                  const s=document.querySelector('input.switch');
                  if(!s)return false;
                  const c=getComputedStyle(s);
                  return c.color!=='rgb(0, 0, 0)'
                    &&parseFloat(c.borderTopWidth)===0;}"""))
            # 状态复位：主题清空、视口回默认、tab 回走势
            pg.evaluate("try{localStorage.removeItem('jptheme')"
                        "}catch(e){}")
            pg.evaluate("showMonTab('trend')")
            pg.wait_for_timeout(300)
            # ---- WebUI 审计钉：chips 重建键盘焦点恢复——焦点停在
            # chip 上时整组重建（轮询/重置/联动走 render()）后同序号
            # 回焦，键盘用户不坠 body。细节：先落明细视图再取件（隐藏
            # 容器 focus 失败=idx=-1 假绿）；demo 数据静态，等 10s 轮询
            # 是假绿源，直调 render() 复现真实重建路径；取件走 .chip
            # 集合（chiplab 标签占 children[0] 且不可聚焦）；日期容器
            # 取首片（尾片 srtchip 自带 tabindex，会掩盖恢复缺陷=假绿）----
            pg.set_viewport_size({"width": 1440, "height": 900})
            ck("chips 重建焦点恢复·渠道", pg.evaluate(
                """()=>{
                  showMonTab('details');setFltOpen(true);
                  const el=document.querySelector('#platchips');
                  let chips=[...el.querySelectorAll('.chip')];
                  if(!chips.length)return false;
                  chips[0].focus();
                  if(document.activeElement!==chips[0])return false;
                  render();
                  chips=[...document.querySelectorAll(
                    '#platchips .chip')];
                  return document.activeElement===chips[0];}"""))
            ck("chips 重建焦点恢复·日期", pg.evaluate(
                """()=>{
                  const el=document.querySelector('#datechips');
                  let chips=[...el.querySelectorAll('.chip')]
                    .filter(c=>!c.classList.contains('srtchip'));
                  if(!chips.length)return false;
                  chips[0].focus();
                  if(document.activeElement!==chips[0])return false;
                  render();
                  chips=[...document.querySelectorAll(
                    '#datechips .chip')]
                    .filter(c=>!c.classList.contains('srtchip'));
                  return document.activeElement===chips[0];}"""))
            # 状态复位：焦点归还 body、tab 回走势
            pg.evaluate(
                "document.activeElement&&document.activeElement.blur()")
            pg.evaluate("showMonTab('trend')")
            pg.set_viewport_size({"width": 1280, "height": 900})
            pg.wait_for_timeout(300)

            # ---- r233 WebUI 五案（放流程最末：既有段前置状态零污染；
            # 显式锚/搜索态复位/nowrap/busy 防双击） ----
            step("r233 webui 五案")
            # W-1 动作件显式 this 锚：window.event 是 Chromium 专属，
            # Firefox/Safari 上 5 个动作件曾全哑（空锚静默降级）——
            # 行为钉直调传锚形态：不依赖全局 event 也进确认态
            ck("W-1 动作件显式锚进确认层", pg.evaluate(
                "()=>{const b=document.createElement('button');"
                "document.body.appendChild(b);let ok=false;"
                "try{delUser(0,b);}catch(e){b.remove();return false;}"
                "const m=document.getElementById('confirmMask');"
                "ok=!!(m&&m.classList.contains('on'));"
                "closeConfirm();b.remove();"
                "return ok;}"))
            # W-2 搜索态点导航=离开搜索模式：命中残留与陈旧计数复位
            # （面板化与搜索两条 display 控制线曾互相打架——导航后面
            # 板大面积空白 + cfgHits 挂陈旧文案）。跑完回 login 面板
            # （ uitest 惯例：末段无后续受众，复位仅防 e.value 残留）
            ck("W-2 搜索态导航复位", pg.evaluate(
                "()=>{const inp=document.querySelector('#cfgSearch');"
                "inp.value='间隔';CFGQ='间隔';cfgFilter('间隔');"
                "showCfgPanel('globals');"
                "const els=[...document.querySelectorAll("
                "'#panel-globals .glgrid>div,#panel-globals .srow')];"
                "const ok=els.length>0"
                "&&els.every(e=>e.style.display!=='none')"
                "&&document.querySelector('#cfgSearch').value===''"
                "&&document.querySelector('#cfgHits').textContent==='';"
                "cfgFilter('');showCfgPanel('login',true);return ok;}"))
            # W-3 CJK 词组 nowrap（十六§6 家族残留清点）：KPI 副行
            # route 段与用户卡头 routesTxt 分段——断词孤字在源头关闭
            # （锚含 → 的 nw=route 段；既有 trans 段「经X」不含箭头）
            ck("W-3 KPI 副行 route 词组 nowrap", pg.evaluate(
                "()=>{const nw=[...document.querySelectorAll('.fb .nw')]"
                ".find(e=>e.textContent.includes('→'));"
                "return !!nw&&getComputedStyle(nw).whiteSpace"
                "==='nowrap';}"))
            ck("W-3 用户卡头 routes 分段 nowrap", pg.evaluate(
                "()=>{const s=[...document.querySelectorAll("
                "'.uroutes .nw')];return s.length>0&&s.every("
                "e=>getComputedStyle(e).whiteSpace==='nowrap');}"))
            # W-5 loginFinish busy 防双击：busy 期第二击不发第二次请求
            # （fetch spy 计数；demo 态 /api/login-finish 无会话安全）
            ck("W-5 loginFinish busy 防双击", pg.evaluate(
                "async ()=>{let n=0;const of=window.fetch;"
                "window.fetch=function(...a){n++;return of.apply(this,a)};"
                "const b=document.createElement('button');"
                "document.body.appendChild(b);"
                "try{loginFinish('ctrip',b);loginFinish('ctrip',b);}"
                "finally{window.fetch=of;"
                "setTimeout(()=>{if(b.parentNode)b.remove();},50);}"
                "await new Promise(r=>setTimeout(r,150));"
                "return n===1;}"))

            # ---- r233 WC 九案（审计报告 _scratch/r233_wc_webui.md；
            # P1×2+P2×4+备案×3 全行为钉/真态钉，B-1 维持备案不钉） ----
            step("r233 WC 九案")
            # WC-P1-1 glcell 读屏名：loadCfg aria 后处理内层选择器
            # 曾漏 .glab 支——15 个全局参数输入恒 aria-label=null
            ck("WC-P1-1 glcell 输入读屏名", pg.evaluate(
                "()=>['glbIv','glbPort','glbUa'].every(id=>{"
                "const e=document.getElementById(id);"
                "return !!e&&!!e.getAttribute('aria-label');})"))
            # WC-P1-2 busy 守卫七漏员：预置 busy 单调 fetch 计数恒 0
            # （pointer-events:none 只挡指针，键盘 Enter 合成 click 照发——
            # 守卫必须在函数首行；previewPush 锚在页面真实 pvBtn）
            ck("WC-P1-2 busy 守卫七件", pg.evaluate(
                "async ()=>{let n=0;const of=window.fetch;"
                "window.fetch=function(...a){n++;return of.apply(this,a)};"
                "const b=document.createElement('button');"
                "document.body.appendChild(b);b.classList.add('busy');"
                "const pv=$('pvBtn');pv.classList.add('busy');"
                "try{loginStart('ctrip',b);previewPush();testToast(b);"
                "testEm(0,0,b);testNtfy(0,b);testImghost(0,b);testPush(0,b);}"
                "finally{window.fetch=of;"
                "setTimeout(()=>{if(b.parentNode)b.remove();},50);}"
                "await new Promise(r=>setTimeout(r,120));"
                "return n===0;}"))
            # WC-P2-1 delEm 确认层：打开不 splice，取消无损（r343）
            ck("WC-P2-1 delEm 确认层不直删", pg.evaluate(
                "()=>{const n0=(ems(0)||[]).length;"
                "const b=document.createElement('button');"
                "document.body.appendChild(b);let ok=false;"
                "try{delEm(0,0,b);}catch(e){b.remove();return false;}"
                "const m=document.getElementById('confirmMask');"
                "ok=!!(m&&m.classList.contains('on'))"
                "&&(ems(0)||[]).length===n0;"
                "closeConfirm();b.remove();"
                "return ok;}"))
            # WC-P2-2 弹层内动态链接焦点环（链接在折叠详情 .pldesp 里——
            # 先展开首条记录再 focus；外域图链 route 拦截防资源失败
            # 进零 JS 错收集器；诊断串随 prog 落盘）
            def _blk_ext(route):
                u = route.request.url
                if ("//127.0.0.1" in u) or ("//localhost" in u):
                    return route.continue_()
                return route.fulfill(status=200, content_type="image/png",
                                     body="")
            pg.route("**/*", _blk_ext)
            _p22diag = pg.evaluate(
                "async ()=>{pushLog();"
                "await new Promise(r=>setTimeout(r,700));"
                "const its=[...document.querySelectorAll('#pvMask .plitem')];"
                "for(const it of its){it.click();"
                " await new Promise(r=>setTimeout(r,80));"
                " const a=document.querySelector('#pvMask .pvbody a');"
                " if(a){a.focus({focusVisible:true});"
                "  const sh=getComputedStyle(a).boxShadow;closePv();"
                "  return 'sh='+sh+' active='+(document.activeElement===a)"
                "   +' items='+its.length;}}"
                "closePv();return 'no-a items='+its.length;}")
            pg.unroute("**/*")
            prog.write("WC-P2-2 诊断: %s\n" % _p22diag)
            ck("WC-P2-2 pvbody 链接焦点环",
               "0px 0px 0px 2px" in str(_p22diag))
            # WC-P2-3 jumpQual 空态不再静默（S 未载点击 pill 有 toast
            # 兜底；静态 title 词面由修法中性化，pillState 接管后不钉）
            ck("WC-P2-3 jumpQual 空态兜底", pg.evaluate(
                "()=>{const _s=S;S=null;"
                "try{jumpQual();}catch(e){S=_s;return false;}"
                "const ok=[...document.querySelectorAll('.toast')]"
                ".some(t=>t.textContent.indexOf('稍候')>=0);"
                "S=_s;"
                "document.querySelectorAll('.toast').forEach("
                "t=>t.parentNode&&t.parentNode.removeChild(t));"
                "return ok;}"))
            # WC-P2-4 确认层焦点落在确认钮 + 取消不执行（替代旧锁宽）
            ck("WC-P2-4 确认层焦点/取消语义", pg.evaluate(
                "async()=>{const b=document.createElement('button');"
                "b.className='danger';b.textContent='✕ 删除用户 测试';"
                "document.body.appendChild(b);"
                "try{delUser(0,b);}catch(e){b.remove();return false;}"
                "await new Promise(r=>setTimeout(r,80));"
                "const ok=document.activeElement"
                "&&document.activeElement.id==='cmCancel';"   # r345 默认焦点落取消
                "closeConfirm();b.remove();return ok;}"))
            # B-2 cfgnav 窄档残留约束闭环（≤900 转 static 后 sticky
            # 伴生的 max-height/overflow 不再有意义）
            pg.set_viewport_size({"width": 800, "height": 900})
            pg.wait_for_timeout(200)
            ck("B-2 cfgnav 窄档无内滚约束", pg.evaluate(
                "()=>{const s=getComputedStyle("
                "document.querySelector('.cfgnav'));"
                "return s.overflow==='visible'&&s.maxHeight==='none';}"))
            pg.set_viewport_size({"width": 1280, "height": 900})
            pg.wait_for_timeout(200)
            # B-3 md-at 双主题令牌化（规则表真态：.md-at 消费 var +
            # 亮暗双定义在场；硬编码 #ffd24d 曾暗色不换谱）
            ck("B-3 md-at 双主题令牌", pg.evaluate(
                "()=>{let hit=0;"
                "const walk=rs=>{for(const r of rs){"
                "if(r.cssRules&&r.cssRules.length){walk(r.cssRules);continue;}"
                "const t=r.cssText||'';"
                "if(t.indexOf('.md-at')>=0"
                "&&t.indexOf('var(--at-bg)')>=0)hit++;"
                "if(t.indexOf('--at-bg:')>=0)hit++;}};"
                "for(const sh of document.styleSheets){"
                "try{walk(sh.cssRules);}catch(e){}}"
                "return hit>=3;}"))
            # B-4 upill 行盒齐平（emoji 行盒曾 +2px 参差）：规则表真态
            # 钉（demo 单用户下几何钉无分辨力——line-height:1 声明在场
            # 由浏览器规则表实证，非源码串）
            ck("B-4 upill 行盒声明", pg.evaluate(
                "()=>{let ok=false;"
                "const walk=rs=>{for(const r of rs){"
                "if(r.cssRules&&r.cssRules.length){walk(r.cssRules);continue;}"
                "const t=r.cssText||'';"
                "if(t.indexOf('.upill')===0"
                "&&t.indexOf('line-height: 1')>=0)ok=true;}};"
                "for(const sh of document.styleSheets){"
                "try{walk(sh.cssRules);}catch(e){}}"
                "return ok;}"))

            # ---- S-M-1 pushLog 渠道小标（r234 Soldier 清零：备2 落账
            # ch=urgent 后，主推与强提醒两条同标题记录并排可辨；
            # CH_CN 全局单源，健康面板同源消费）----
            step("S-M-1 pushLog 渠道小标")
            ck("S-M-1 渠道小标渲染", pg.evaluate(
                "async ()=>{pushLog();"
                "await new Promise(r=>setTimeout(r,400));"
                "const els=[...document.querySelectorAll('#pvBody .plch')];"
                "const txt=els.map(e=>e.textContent);"
                "const ok=txt.includes('钉钉')&&txt.includes('邮件');"
                "closePv();"
                "await new Promise(r=>setTimeout(r,120));"
                "return ok;}"))
            # ---- WP-P2-3 弹层正文链接触控外扩（::after 不入 bounding
            # box，以命中采样验收：链接下缘外 6px 仍命中本链接=外扩
            # 真态；NOTIFY 轻页同位件先例，主站弹层家族最后漏点。
            # 链接在折叠详情 .pldesp 里——先展开首条记录再量，量纲
            # 死档律同 WC-P2-2）----
            ck("WP-P2-3 弹层链接触控外扩", pg.evaluate(
                "async ()=>{pushLog();"
                "await new Promise(r=>setTimeout(r,400));"
                "const it=document.querySelector('#pvBody .plitem');"
                "if(it)it.click();"
                "await new Promise(r=>setTimeout(r,150));"
                "const a=document.querySelector('#pvBody .pldesp a');"
                "if(!a){closePv();return false;}"
                "const rc=a.getBoundingClientRect();"
                "const hit=document.elementFromPoint("
                "rc.x+rc.width/2, rc.bottom+6);"
                "const ok=!!hit&&(hit===a||a.contains(hit));"
                "closePv();"
                "await new Promise(r=>setTimeout(r,120));"
                "return ok;}"))

            # ---- r237 WebUI 四案（P1-1 消毒/P2-1 K线桶起点/P2-2 brk
            # 角标豁免/P3-1 cfgglobals CTA）：注入载荷一次覆盖三钉
            # （XSS 面+错峰 history+brk 行），/api/config 500 单独拦；
            # 段在全流程最末，段尾 unroute+reload 复位不扰下游 ----
            step("r237 WebUI 四案")
            _real = pg.request.get(BASE + "/api/state").json()
            _u0 = _real["users"][0]

            def _poison(b):
                b["name"] = "<b id=probe_kb>KB</b>"
                b["trans"] = "<b id=probe_kt>KT</b>"
                b["route"] = "<u id=probe_kr>KR</u>"

            _poison((_u0.get("best") or {}).get("direct") or {})
            _bbd = _u0.get("best_by_date") or {}
            for _slot in ("direct", "transfer"):
                for _b in (_bbd.get(_slot) or {}).values():
                    if isinstance(_b, dict):
                        _poison(_b)
            if _u0.get("routesArr"):
                _u0["routesArr"][0]["label"] = "<u id=probe_rt>RT</u>"
                _u0["routesArr"][0]["cal"] = [["<u id=probe_cal>CA</u>", 900, 2]]
                _hit = False
                for _rr in _u0["routesArr"]:
                    for _f in (_rr.get("flights") or []):
                        if isinstance(_f, dict) and _f.get("price"):
                            _f["brk"] = True
                            _f["platKey"] = "fliggy"
                            _hit = True
                            break
                    if _hit:
                        break
                if not _hit and isinstance(_u0.get("flights"), list):
                    for _f in _u0["flights"]:
                        if isinstance(_f, dict) and _f.get("price"):
                            _f["brk"] = True
                            _f["platKey"] = "fliggy"
                            break
                # 错峰双系列：中转 +5 分钟同 2h 桶 → t0 桶起点对齐钉。
                # 样本铺在桶中心带（:30/:35，距桶界 ≥25 分钟）——按整点
                # 直铺时 CI 的 UTC 相位会让末点 +5 分钟跨进下桶，双系列
                # 桶数不齐使按索引配对假红（本地绿 CI 红的环境差异型）；
                # 且全部铺在过去（now-8h 起锚），防「未来回退一年」分支
                _now = datetime.now().replace(minute=0, second=0)
                _base = (_now.replace(hour=_now.hour - _now.hour % 2)
                         - timedelta(hours=8))
                _dpts, _tpts = [], []
                for _i in range(4):
                    _td = _base + timedelta(hours=2 * _i, minutes=30)
                    _tt = _td + timedelta(minutes=5)
                    _dpts.append([_td.strftime("%m-%d %H:%M"), 1800 + _i * 7, 0])
                    _tpts.append([_tt.strftime("%m-%d %H:%M"), 1650 + _i * 5, 0])
                _u0["routesArr"][0]["history"] = {"direct": _dpts,
                                                  "transfer": _tpts}
            pg.route("**/api/state", lambda r: r.fulfill(
                status=200, content_type="application/json",
                body=json.dumps(_real, ensure_ascii=False)))
            pg.route("**/api/config", lambda r: r.fulfill(
                status=200, content_type="application/json",
                body='{"err":"boom"}'))   # 业务层失败形态：err 体走 loadCfg
            # 同一 throw→catch 分支，不制造预期内 500 console 噪音污染
            # 「零 JS 错」门（与 /api/health 钉同款）
            pg.goto(BASE, wait_until="domcontentloaded")
            pg.wait_for_selector("#users .kpi", state="attached",
                                 timeout=30000)
            pg.wait_for_timeout(600)
            ck("r237-1 自由文本注入不落 DOM", pg.evaluate(
                "()=>!(document.getElementById('probe_kb')||"
                "document.getElementById('probe_kt')||"
                "document.getElementById('probe_kr')||"
                "document.getElementById('probe_rt')||"
                "document.getElementById('probe_cal'))"))
            pg.evaluate("gotoMonTab('trend')")
            pg.wait_for_timeout(400)
            pg.evaluate("setMode('kline')")
            pg.wait_for_timeout(900)
            ck("r237-2 K线同桶双簇轴位对齐", pg.evaluate(
                "()=>HPTS.cd.length>0&&HPTS.cd.every((c,i)=>"
                "HPTS.ct[i]&&HPTS.ct[i]._ax===c._ax)"))
            ck("r237-2b 桶起点词面两位月形态", pg.evaluate(
                "()=>HPTS.cd.every(c=>/^(0[1-9]|1[0-2])-[0-3][0-9] "
                "[0-2][0-9]:[0-5][0-9]$/.test(c.t0))"))
            pg.evaluate("gotoMonTab('details')")
            pg.wait_for_timeout(600)
            ck("r237-3 brk 行角标描边豁免", pg.evaluate(
                """()=>{const td=document.querySelector(
                  '#ftable td.price.brk');
                  if(!td)return false;
                  /* 构造式：demo 现形态 brk×pretax 组合不产出（r326
                     实测 2 brk 行均无角标）——在真 brk 底上注入同族
                     span 验同一层叠豁免，验毕移除零残留 */
                  const s=document.createElement('span');
                  s.className='pretax';s.textContent='退￥0·改￥0';
                  td.appendChild(s);
                  const c=getComputedStyle(s);
                  const ok=parseFloat(c.webkitTextStrokeWidth)===0
                    &&c.color.indexOf('transparent')<0;
                  s.remove();
                  return ok;}"""))
            pg.evaluate("switchView('cfg')")
            pg.wait_for_timeout(900)
            ck("r237-4 cfgglobals 失败 CTA 同词面", pg.evaluate(
                "()=>{const t=(document.getElementById('cfgglobals')"
                "||{}).innerText||'';"
                "return t.indexOf('恢复后刷新页面')>=0"
                "&&t.indexOf('重进配置页重试')<0;}"))

            # ---- r241 P2-2 行为钉（全流程最末段，段尾复位）：541-760
            # 明细筛选条吸顶对 + 落点过「吸顶三件」（--tabsh 动态单源，
            # 同公式覆盖 ≤540——390 实测同族遮挡 43px 一并收口）----
            pg.evaluate("switchView('mon')")
            pg.wait_for_timeout(400)
            pg.set_viewport_size({"width": 600, "height": 900})
            pg.wait_for_timeout(400)
            pg.evaluate("gotoMonTab('details')")
            pg.wait_for_timeout(500)
            pg.evaluate("window.scrollTo(0,999999)")
            pg.wait_for_timeout(400)
            ck("541-760 筛选条吸顶贴切换器底", pg.evaluate(
                "()=>{const t=document.querySelector("
                "'#montab-details .tabs'),"
                "m=document.getElementById('montabs');"
                "if(!t||!m)return false;"
                "return getComputedStyle(t).position==='sticky'"
                "&&Math.abs(t.getBoundingClientRect().top"
                "-m.getBoundingClientRect().bottom)<=3;}"))
            ck("541-760 筛选条单行化", pg.evaluate(
                "()=>{const t=document.querySelector("
                "'#montab-details .tabs');const b=t&&t.querySelector"
                "('b.muted');return !!t&&t.getBoundingClientRect().height"
                "<=60&&!!b&&getComputedStyle(b).display==='none';}"))
            ck("541-760 落点过吸顶三件", pg.evaluate(
                """()=>{const bar=document.querySelector(
                '#montab-details .tabs'),m=document.getElementById(
                'montabs');
                if(!bar||!m)return false;
                if(getComputedStyle(bar).position!=='sticky')return false;
                const br=bar.getBoundingClientRect();
                if(Math.abs(br.top-m.getBoundingClientRect().bottom)>3)
                  return false;
                const rows=[...document.querySelectorAll(
                '#ftable tbody tr')].filter(r=>r.offsetHeight>10);
                if(!rows.length)return false;
                const row=rows[Math.min(30,rows.length-1)];
                row.scrollIntoView({block:'start'});
                return new Promise(r=>setTimeout(()=>{
                r(row.getBoundingClientRect().top>=br.bottom-6);},350));}"""))
            ck("541-760 --tabsh 贴筛选条实高", pg.evaluate(
                "()=>{const ts=parseFloat(getComputedStyle("
                "document.documentElement).getPropertyValue("
                "'--tabsh'))||0;"
                "const t=document.querySelector("
                "'#montab-details .tabs');"
                "return !!t&&Math.abs(ts-t.offsetHeight)<=1;}"))
            # ≤540 同公式落点收口（390 档）
            pg.set_viewport_size({"width": 390, "height": 844})
            pg.wait_for_timeout(400)
            ck("≤540 落点过吸顶三件（同族遮挡收口）", pg.evaluate(
                """()=>{const bar=document.querySelector(
                '#montab-details .tabs'),m=document.getElementById(
                'montabs');
                if(!bar||!m)return false;
                if(getComputedStyle(bar).position!=='sticky')return false;
                const br=bar.getBoundingClientRect();
                if(Math.abs(br.top-m.getBoundingClientRect().bottom)>3)
                  return false;
                const rows=[...document.querySelectorAll(
                '#ftable tbody tr')].filter(r=>r.offsetHeight>10);
                if(!rows.length)return false;
                const row=rows[Math.min(30,rows.length-1)];
                row.scrollIntoView({block:'start'});
                return new Promise(r=>setTimeout(()=>{
                r(row.getBoundingClientRect().top>=br.bottom-6);},350));}"""))
            # 600 档深滚点筛选（本段最末位：抽屉开合+深滚前置态会
            # 污染几何检查，故置于全部几何钉之后）——抽屉顶拉 assist
            # 随在流形制扩带（540 旧门下新带深滚开面板=落在视口上方，
            # 按钮无响应病灶复活）
            pg.set_viewport_size({"width": 600, "height": 900})
            pg.wait_for_timeout(400)
            pg.evaluate("gotoMonTab('details')")
            pg.wait_for_timeout(300)
            pg.evaluate("window.scrollTo(0,999999)")
            pg.wait_for_timeout(300)
            pg.click("#fltBtn")
            pg.wait_for_timeout(400)
            ck("541-760 深滚开抽屉顶拉 assist", pg.evaluate(
                """()=>{const f=document.querySelector('.fbar'),
                t=document.querySelector('#montab-details .tabs');
                if(!f||!t||!f.classList.contains('open'))return false;
                return f.getBoundingClientRect().top
                  >=t.getBoundingClientRect().bottom-3;}"""))
            pg.evaluate("setFltOpen(false)")
            pg.wait_for_timeout(200)
            # 状态复位：视口回默认、tab 回走势、回页顶
            pg.set_viewport_size({"width": 1280, "height": 900})
            pg.wait_for_timeout(300)
            pg.evaluate("showMonTab('trend')")
            pg.evaluate("window.scrollTo({top:0,behavior:'instant'})")
            pg.wait_for_timeout(300)

            # ---- r243 WebUI 两案（P2-1 弹层链触控有效高 / P3-1
            # popstate 深链回写）：段在全流程最末，钉尾复位不扰下游 ----
            step("r243 WebUI 两案")
            # P2-1：有效命中高（锚盒 + ::after 上下外扩）≥36 家族基准
            # ——「23px 行盒」估算落 -7px 实得 31px（inline 锚盒实测
            # 17px 不含行距），存在性钉抓不住欠账，有效高断言防再欠
            _p21 = pg.evaluate(
                "async ()=>{pushLog();"
                "await new Promise(r=>setTimeout(r,400));"
                "const it=document.querySelector('#pvBody .plitem');"
                "if(it)it.click();"
                "await new Promise(r=>setTimeout(r,150));"
                "const a=document.querySelector('#pvBody .pldesp a');"
                "if(!a){closePv();return 'NO_LINK';}"
                "const h=a.getBoundingClientRect().height;"
                "const ext=Math.abs(parseFloat("
                "getComputedStyle(a,'::after').top)||0);"
                "closePv();"
                "await new Promise(r=>setTimeout(r,120));"
                "return (h+'|'+ext);}")
            prog.write("   r243 P2-1 量测 h|ext = %s\n" % _p21)
            prog.flush()
            ck("r243 P2-1 弹层链触控有效高≥36",
               _p21 not in ("NO_LINK",)
               and (lambda _v: (_v[0] + 2 * _v[1]) >= 36)(
                   [float(x) for x in _p21.split("|")]))
            # P3-1：回退跨 cfg→mon 到离开时同一页签——深链段必须原样
            # 恢复（switchView 的 replaceState('#mon') 曾覆写入站 hash，
            # MONTAB 已等时不再补写，#details/u0 永久清洗成 #mon）
            ck("r243 P3-1 后退恢复深链段", pg.evaluate(
                "async ()=>{"
                "location.hash='#details/u0';"
                "await new Promise(r=>setTimeout(r,200));"
                "location.hash='#cfg';"
                "await new Promise(r=>setTimeout(r,200));"
                "history.back();"
                "await new Promise(r=>setTimeout(r,300));"
                "const ok=location.hash==='#details/u0';"
                "try{history.replaceState(null,'','#mon')}catch(e){}"
                "return ok;}"))
            # P2-1b：入站裸 tab（无 /uN 段）——回写必须对齐 showMonTab
            # 写点带用户段；裸回写 '#'+_h 会把 showMonTab 刚写的
            # '#trend/uN' 洗回 '#trend'（URL 深链用户段丢失）
            ck("r243 P2-1b 裸tab入站回写保用户段", pg.evaluate(
                "async ()=>{"
                "location.hash='#trend';"
                "await new Promise(r=>setTimeout(r,250));"
                "const h=location.hash;"
                "const ok=h.slice(0,8)==='#trend/u'&&h.length>8;"
                "try{history.replaceState(null,'','#mon')}catch(e){}"
                "return ok;}"))

            pg.unroute("**/api/state")
            pg.unroute("**/api/config")
            pg.goto(BASE, wait_until="domcontentloaded")
            pg.wait_for_timeout(400)

            # ---- r247 WebUI 两案（W1 opsbtns 横滚暗示 / W2 排序 chip
            # 态同步）：段在全流程最末，钉尾复位不扰下游 ----
            step("r247 WebUI 两案")
            # W2：SORT 变化的全部路径（chip 点击/表头点击/重置筛选）
            # 尾补 chip 就地同步——旧码点表头/重置后 chip 滞留旧态
            # aria 至下轮渲染自愈（探针实录形态）。evaluate 严格
            # ===true 判定：NO_CHIP 守卫串为真值，裸传 ck 会假绿
            # （Soldier P3-1 收口，诊断串落 prog 保留）
            _w2r = pg.evaluate(
                "async ()=>{"
                "showMonTab('details');"
                "await new Promise(r=>setTimeout(r,200));"
                "const chip=document.querySelector('.srtchip');"
                "if(!chip)return 'NO_CHIP';"
                "dateSortChip(chip);"
                "await new Promise(r=>setTimeout(r,60));"
                "const s1=chip.getAttribute('aria-pressed')==='true'"
                "&&chip.dataset.dir==='asc';"
                "sortCol('price');"
                "await new Promise(r=>setTimeout(r,60));"
                "const s2=chip.getAttribute('aria-pressed')==='false'"
                "&&chip.dataset.dir==='';"
                "const l2=chip.getAttribute('aria-label');"
                "sortCol('date');"
                "await new Promise(r=>setTimeout(r,60));"
                "const s3=chip.dataset.dir==='asc'"
                "&&chip.getAttribute('aria-pressed')==='true';"
                "dateSortChip(chip);"
                "await new Promise(r=>setTimeout(r,60));"
                "const s4=chip.dataset.dir==='desc';"
                "resetFlt();"
                "await new Promise(r=>setTimeout(r,60));"
                "const c2=document.querySelector('.srtchip');"   # reset 重建日期片→芯片换新
                "const s5=!!c2&&c2.getAttribute('aria-pressed')==='false'"
                "&&c2.dataset.dir==='';"
                "return !!(s1&&s2&&l2.indexOf('未启用')>=0&&s3&&s4&&s5);}")
            prog.write("   r247 W2 evaluate = %r\n" % (_w2r,))
            ck("r247 W2 排序chip全路径同步", _w2r is True)
            # W1：≤760 窄档 opsbtns 横滚且滚动条隐藏——溢出时 xhint
            # 挂载（mask 渐隐暗示）；恢复桌面档后 resize 批次摘除
            # （折行无溢出恒惰性）。viewport 改动钉尾复原；evaluate
            # 同上严格 ===true（NO_BTN 守卫串真值假绿防同律）
            _vp0 = pg.viewport_size
            pg.set_viewport_size({"width": 390, "height": 844})
            pg.wait_for_timeout(700)   # resize 批次 debounce 200ms 余量
            # r349 设计变更：390 档从横滚+渐隐改为四列全可见，
            # 消灭「预览推送」被裁的可发现性缺陷；<=360 再落 2x2。
            _w1a = pg.evaluate(
                "()=>{const b=document.querySelector('#opscard .opsbtns');"
                "if(!b)return 'NO_BTN';"
                "const cs=getComputedStyle(b);"
                "const cols=cs.gridTemplateColumns.split(' ').filter(Boolean).length;"
                "const bs=[...b.querySelectorAll('button')];"
                "const br=b.getBoundingClientRect();"
                "const vis=bs.length===4&&bs.every(x=>{const r=x.getBoundingClientRect();"
                "return r.width>0&&r.right<=br.right+1&&r.left>=br.left-1;});"
                "return !!(cs.display==='grid'&&cols===4&&vis"
                "&&b.scrollWidth<=b.clientWidth+4);}")
            ck("r247 W1 窄档opsbtns四列全可见", _w1a is True)
            _w1b = pg.evaluate(
                "()=>{const b=document.querySelector('#opscard .opsbtns');"
                "if(!b)return 'NO_BTN';"
                "const rs=[...b.querySelectorAll('button')]"
                ".map(x=>x.getBoundingClientRect());"
                "return !!(rs.length===4"
                "&&Math.max(...rs.map(r=>r.height))<=38"
                "&&Math.min(...rs.map(r=>r.width))>60);}")
            ck("r247 W1 窄档opsbtns等宽同高", _w1b is True)
            pg.set_viewport_size(_vp0)
            pg.wait_for_timeout(700)
            _w1c = pg.evaluate(
                "()=>{const b=document.querySelector('#opscard .opsbtns');"
                "if(!b)return 'NO_BTN';"
                "return !b.classList.contains('xhint');}")
            ck("r247 W1 桌面档暗示摘除", _w1c is True)

            # ---- r249 WebUI 三案（首列焦点环/输入环即时/renderCal
            # 实色）：段在全流程最末，钉尾 blur 复位不扰统计 ----
            step("r249 WebUI 三案")
            _r9a = pg.evaluate(
                "()=>{const th=document.querySelector("
                "'#ftable thead th.srt:first-child');"
                "if(!th)return 'NO_TH';"
                "th.focus({focusVisible:true});"
                "const bs=getComputedStyle(th).boxShadow;"
                "const hx=getComputedStyle(document.documentElement)"
                ".getPropertyValue('--blue').trim();"
                "const n=parseInt(hx.slice(1),16);"
                "const rgb='rgb('+((n>>16)&255)+', '+((n>>8)&255)+', '"
                "+(n&255)+')';"
                "const ok=bs.indexOf('inset')>=0&&bs.indexOf(rgb)>=0"
                "&&/2px 0(px)? 0(px)?/.test(bs);"
                "th.blur();"
                "return ok;}")
            ck("r249 P1-1 首列表头聚焦双影环", _r9a is True)
            pg.evaluate("()=>{const fb=document.querySelector('.fbar');"
                        "if(fb&&getComputedStyle(fb).display==='none')setFltOpen(true);}")
            _r9b = pg.evaluate(
                "()=>{const el=document.getElementById('fq');"
                "if(!el)return 'NO_FQ';"
                "el.focus();"
                "const d=getComputedStyle(el).transitionDuration;"
                "el.blur();"
                "return d==='0s';}")
            ck("r249 P2-1 输入焦点环即时呈现", _r9b is True)
            _r9c = pg.evaluate(
                "()=>(typeof renderCal==='function') ? renderCal.toString()"
                ".indexOf('var(--green)')<0 : 'NO_FN';")
            ck("r249 P2-2 renderCal 加载态无活变量", _r9c is True)

            # ---- r252 W-1 行为钉：明细行交互件触控双轴聚合清单
            # （审计 r252_webui_audit P3-1 建议进资产）：现网触控钉只量
            # 纵向，横向地板纳入防未来新交互件只在纵向达标。纵向判定锚
            # 「::after 外扩结构在位」而非渲染测量：外扩家族件（inset
            # 负值=主动触控补足）对基盒行高的字体环境差免疫（CI Linux
            # 基盒 17px vs 本地 18px 曾让纯测量钉 35<35.5 确定性红——
            # r243 字体 ±1px 同族），无外扩且自身矮的件才违例（新件漏
            # 进外扩家族即抓）。a.vw(33)/.tj(32) 横向 <36 是在案设计取舍
            # （右邻命中互吃约束——webui L998/L1009 注释，备案豁免）----
            pg.click('.mtab[data-t="details"]'); pg.wait_for_timeout(300)
            _r10 = pg.evaluate(
                "()=>{const tb=document.querySelector('#ftable tbody');"
                "if(!tb)return 'NO_TABLE';"
                "const els=new Set();"
                "['#ftable tbody a','#ftable tbody .tj',"
                "'#ftable tbody button'].forEach(s=>document.querySelectorAll(s)"
                ".forEach(e=>els.add(e)));"
                "const num=v=>v&&v!=='auto'?(parseFloat(v)||0):0;"
                "const badV=[],badW=[];"
                "els.forEach(el=>{const rc=el.getBoundingClientRect();"
                "if(rc.width===0&&rc.height===0)return;"
                "const a=getComputedStyle(el,'::after');"
                "let exT=0,exR=0,exB=0,exL=0;"
                "if(a.position==='absolute'&&a.content!=='none'){"
                "exT=num(a.top);exR=num(a.right);exB=num(a.bottom);exL=num(a.left);}"
                "const effH=rc.height-exT-exB,effW=rc.width-exL-exR;"
                "const vext=exT<0&&exB<0;"
                "const tag=el.tagName+'.'+((el.className||'').split(' ')[0]||'');"
                "if(!vext&&effH<35.5)"
                "badV.push(tag+'|'+Math.round(effW)+'x'+Math.round(effH));"
                "const wl=el.classList.contains('tj')||"
                "(el.tagName==='A'&&el.classList.contains('vw'));"
                "if(effW<35.5&&!wl)"
                "badW.push(tag+'|'+Math.round(effW)+'x'+Math.round(effH));});"
                "return {n:els.size,badV:badV,badW:badW};}")
            ck("r252 W-1 明细交互件纵向触控 36 地板（外扩家族在位）",
               isinstance(_r10, dict) and _r10.get("n", 0) > 0
               and not _r10.get("badV"))
            ck("r252 W-1 明细交互件横向触控 36 地板（vw/tj 备案豁免）",
               isinstance(_r10, dict) and _r10.get("n", 0) > 0
               and not _r10.get("badW"))

            # ---- r253 WebUI 行为钉（审计 P1-1/P2-2）：段在流程最末
            # （统计落盘前），窄视探测后恢复视口（共享 page 状态复位律）----
            step("r253 WebUI 两案")
            # P1-1 demo 配置单源：/api/config 航线日期复用演示数据
            # （滚动日期恒 ≥ 今日）——日期硬编码曾与监控/走势/明细
            # 各视图互相矛盾且随时间越来越旧
            _r11a = pg.evaluate(
                "async()=>{try{const r=await fetch('/api/config');"
                "const j=await r.json();"
                "if(!j.demo||!j.users||!j.users.length)return 'NO_DEMO_CFG';"
                "const ds=j.users.flatMap(u=>(u.routes||[])"
                ".map(x=>(x.dates||[])[0]));"
                "if(!ds.length)return 'NO_DATES';"
                "const td=new Date();td.setHours(0,0,0,0);"
                "return {n:j.users[0].routes.length,"
                "allFuture:ds.every(d=>new Date(d+'T00:00:00')>=td)};}"
                "catch(e){return 'ERR:'+e;}}")
            ck("r253 P1-1 demo 配置日期单源（滚动未来日期）",
               isinstance(_r11a, dict) and _r11a.get("n", 0) >= 3
               and _r11a.get("allFuture") is True)
            # P2-2 表内横滚提示：390 视口 .tw.xhint 点亮（右缘渐变与
            # xhint 机制同轨；判定挂行渲染/切换/resize 三点——窄视
            # 触发 resize 批重判），测毕恢复视口
            _vp0 = pg.viewport_size
            pg.set_viewport_size({"width": 390, "height": 844})
            pg.wait_for_timeout(400)
            _r11b = pg.evaluate(
                "()=>{const tw=document.querySelector('.tw');"
                "if(!tw)return 'NO_TW';"
                "return {on:tw.classList.contains('xhint'),"
                "sw:tw.scrollWidth,cw:tw.clientWidth};}")
            pg.set_viewport_size(_vp0)
            pg.wait_for_timeout(200)
            # v1.5.274：390 明细改卡片后容器不再横滚，提示应熄灭且不溢出
            ck("r253 P2-2 窄档卡片化后无横滚提示",
               isinstance(_r11b, dict) and _r11b.get("on") is False
               and _r11b.get("sw", 0) <= _r11b.get("cw", 0))

            # ---- r261 词面单源钉（放流程末尾：钉内视图切换不污染
            # 下游——本段之后仅剩统计落盘） ----
            pg.click('.mtab[data-t="overview"]'); pg.wait_for_timeout(400)
            # P3-1 日历悬停词面与格面同簇同格式：格面 .cd 是 MM/DD，
            # 悬停 title 曾裸 MM-DD 横杠（同簇双格式=词面统一案判据）；
            # dSlash 双形态（YYYY-MM-DD 与协议 MM-DD）函数级页面真调用
            _r261 = pg.evaluate(
                "()=>{try{if(typeof dSlash!=='function')return 'NO_FN';"
                "if(dSlash('2026-10-08')!=='10/08'"
                "||dSlash('10-08')!=='10/08')return 'BAD_FN';"
                "const c=document.querySelector('#calgrid .calcell');"
                "if(!c)return 'NO_CAL';"
                "const face=(c.querySelector('.cd')||{}).textContent||'';"
                "const bare=/\\d{2}-\\d{2}/.test(c.getAttribute('title')||'');"
                "return {face:face,bare:bare};}catch(e){return 'ERR:'+e;}}")
            ck("r261 P3-1 日历悬停词面与格面同格式",
               isinstance(_r261, dict) and _r261.get("bare") is False
               and "/" in (_r261.get("face") or ""))

            # ---- r280 WebUI 三钉（P1-1 顺序搜索/P2-1 孤儿头/P3-1 齐线）：
            # 段在流程最末（统计落盘前）；钉内搜索态测毕复位清空，
            # 几何钉切视口测毕恢复（共享 page 状态复位律） ----
            step("r280 WebUI 三案")
            pg.evaluate("switchView('cfg')"); pg.wait_for_timeout(600)
            # P1-1 顺序搜索假零：守卫先清上轮自写 inline 再判——
            # 命中判定在前时，前轮被藏行本轮即使命中也在复位前被
            # return（第二轮起假零，清空才复活）
            _s = lambda q: (pg.evaluate("(q)=>cfgFilter(q)", q),
                            pg.wait_for_timeout(200))
            _s("演示用户")
            _s("扫描周期")
            _s("演示用户")
            _r280a = pg.evaluate("""()=>{
              const vis=e=>e&&getComputedStyle(e).display!=='none';
              const row=[...document.querySelectorAll('#cfgview .srow')]
                .find(d=>{const i=d.querySelector('input');
                          return i&&i.value==='演示用户';});
              return {hits:document.querySelector('#cfgHits').textContent,
                      rowVis:row?vis(row):null};}""")
            pg.evaluate("cfgFilter('')"); pg.wait_for_timeout(200)
            ck("r280 P1-1 顺序搜索第二轮不假零（先复位再判）",
               isinstance(_r280a, dict) and _r280a.get("rowVis") is True
               and "✓" in (_r280a.get("hits") or ""))
            # P2-1 孤儿头：命中集中于单面板时其余面板结构头退场
            # （只随全页命中数判定只覆盖 0 命中档）
            _s("扫描周期")
            _r280b = pg.evaluate("""()=>{
              const vis=e=>getComputedStyle(e).display!=='none';
              const all=[...document.querySelectorAll(
                '#cfgview .grouplab,#cfgview .uhead2,#cfgview .uhead,'
                +'#cfgview .subsec')];
              return {visN:all.filter(vis).length,
                      uh2:all.filter(e=>e.classList.contains('uhead2'))
                          .filter(vis).length};}""")
            pg.evaluate("cfgFilter('')"); pg.wait_for_timeout(200)
            ck("r280 P2-1 部分命中档非命中面板头退场（孤儿头）",
               isinstance(_r280b, dict) and _r280b.get("uh2") == 0
               and _r280b.get("visN", 0) > 0)
            # P3-1 ≥1920 h1↔nav 18px 差已定谳备案（nav 留盒轴通线，
            # h1 内缩=header 卡内呼吸；裁决注释在 webui ≥1920 块，
            # 禁缩进反断言在 tests/test_v1555_webui.py）——钉位不另设

            # ---- r282 WebUI 两案（搜索态折叠卡头 aria/chev 三同步 /
            # OPEN_USER 持久化）：段在流程最末（统计落盘前）；
            # addUser 注入第二卡不保存（reload 即逝）、localStorage 槽
            # 测毕清空（共享 page 状态复位律） ----
            step("r282 WebUI 两案")
            pg.evaluate("switchView('cfg')"); pg.wait_for_timeout(600)
            # 前序段（cfgglobals CTA 等）会把配置页面板留在非用户面
            # ——显式回用户面板，#cfgform 的 uhead2 才在可视链上
            pg.evaluate("showCfgPanel('users',true)")
            pg.evaluate(
                "try{localStorage.removeItem('jpcfguseropen')}catch(e){};"
                "addUser()")
            pg.wait_for_timeout(200)
            pg.evaluate(
                "toggleUser(document.querySelectorAll('#cfgform .uhead2')[0])")
            pg.wait_for_timeout(200)
            _hs = lambda: pg.evaluate("""()=>{
              const vis=e=>{if(getComputedStyle(e).display==='none')return false;
                let p=e.parentElement;
                while(p){if(getComputedStyle(p).display==='none')return false;
                 p=p.parentElement;}
                return true;};
              return [...document.querySelectorAll('#cfgform .uhead2')].map(
                h=>({a:h.getAttribute('aria-expanded'),
                     b:vis(h.nextElementSibling),
                     c:h.querySelector('.chev').classList.contains('open')}));}""")
            _b0 = _hs()
            ck("r282 手风琴基线 aria/body/chev 三同步（0开1收）",
               isinstance(_b0, list) and len(_b0) == 2
               and _b0[0]["a"] == "true" and _b0[0]["b"] and _b0[0]["c"]
               and _b0[1]["a"] == "false" and not _b0[1]["b"]
               and not _b0[1]["c"])
            pg.evaluate("(q)=>cfgFilter(q)", "新用户"); pg.wait_for_timeout(300)
            _b1 = _hs()
            ck("r282 搜索态折叠卡头 aria/chev 随 body 展开三同步",
               isinstance(_b1, list) and len(_b1) == 2
               and _b1[1]["a"] == "true" and _b1[1]["b"] and _b1[1]["c"])
            pg.evaluate("cfgFilter('')"); pg.wait_for_timeout(300)
            _b2 = _hs()
            ck("r282 清空回手风琴（OPEN_USER 单源回写，非 aria 全开）",
               isinstance(_b2, list) and len(_b2) == 2
               and _b2[0]["a"] == "true" and _b2[0]["b"] and _b2[0]["c"]
               and _b2[1]["a"] == "false" and not _b2[1]["b"]
               and not _b2[1]["c"])
            _slot0 = pg.evaluate("localStorage.getItem('jpcfguseropen')")
            pg.evaluate(
                "toggleUser(document.querySelectorAll('#cfgform .uhead2')[1])")
            pg.wait_for_timeout(200)
            _slot1 = pg.evaluate("localStorage.getItem('jpcfguseropen')")
            ck("r282 OPEN_USER 持久化槽随开合写点",
               _slot0 == "0" and _slot1 == "1")
            pg.evaluate(
                "try{localStorage.removeItem('jpcfguseropen')}catch(e){}")

            # ---- r283 WebUI 行为钉（≤760 抽屉档位图例）：段在流程最末
            # （统计落盘前）；钉内视口切换测毕恢复、抽屉测毕收起
            # （共享 page 状态复位律） ----
            step("r283 WebUI 抽屉图例")
            _vp0 = pg.viewport_size
            pg.evaluate("switchView('mon')")   # 前段留在 cfg 视图
            pg.set_viewport_size({"width": 375, "height": 812})
            pg.evaluate("showMonTab('details')"); pg.wait_for_timeout(300)
            pg.evaluate("(()=>{const fb=document.querySelector('.fbar');"
                        "if(fb&&!fb.classList.contains('open'))togFlt();})()")
            pg.wait_for_timeout(300)
            ck("375 抽屉图例可见（触屏档位色唯一解码位）", pg.evaluate(
                """()=>{const e=document.getElementById('fltlegend');
                  if(!e)return false;
                  if(getComputedStyle(e).display==='none')return false;
                  let p=e.parentElement;
                  while(p){if(getComputedStyle(p).display==='none')return false;
                   p=p.parentElement;}
                  return /深绿=真达标/.test(e.textContent);}"""))
            pg.set_viewport_size({"width": 1280, "height": 900})
            pg.wait_for_timeout(300)
            ck("1280 抽屉图例隐藏（宽档常驻图例不重复）", pg.evaluate(
                """()=>{const e=document.getElementById('fltlegend');
                  if(!e)return false;
                  /* 行级开关（.flgrow）语义在祖先链：span 自身 computed
                     display 不随祖先 none 变，隐藏判定必须爬链 */
                  let p=e;
                  while(p){if(getComputedStyle(p).display==='none')return true;
                   p=p.parentElement;}
                  return false;}"""))
            pg.evaluate("(()=>{const fb=document.querySelector('.fbar');"
                        "if(fb&&fb.classList.contains('open'))togFlt();})()")
            pg.evaluate("showMonTab('overview')")
            pg.set_viewport_size(_vp0); pg.wait_for_timeout(200)

            # ---- r283v WebUI 行为钉（触屏双拍读数驻留）：段在流程最末
            # （统计落盘前）；CDP 触屏仿真测毕关、tab/视图测毕复位
            # （共享 page 状态复位律）----
            step("r283v 触屏双拍读数")
            pg.evaluate("switchView('mon')")   # 前段可能留在 cfg 视图
            pg.evaluate("showMonTab('trend')"); pg.wait_for_timeout(1100)
            _cdp = pg.context.new_cdp_session(pg)
            _cdp.send("Emulation.setTouchEmulationEnabled",
                      {"enabled": True, "maxTouchPoints": 5})
            _tch = pg.evaluate("""(async () => {
              const c=document.getElementById('chart');
              const h=()=>c.toDataURL().slice(-48);
              const base=h();
              const r=c.getBoundingClientRect();
              const x=r.left+r.width*0.45, y=r.top+r.height*0.5;
              const fire=(type,cx,cy)=>c.dispatchEvent(new TouchEvent(type,
                {bubbles:true,cancelable:true,
                 touches:type==='touchend'||type==='touchcancel'?[]:
                   [new Touch({identifier:1,target:c,clientX:cx,clientY:cy})],
                 changedTouches:[new Touch({identifier:1,target:c,
                   clientX:cx,clientY:cy})]}));
              fire('touchstart',x,y);
              await new Promise(rs=>setTimeout(rs,350));
              const afterStart=h();
              fire('touchend',x,y);
              await new Promise(rs=>setTimeout(rs,350));
              const afterEnd1=h();
              /* cancel 段：pinned 必须等十字线真画上（全量会话 rAF
                 排队慢于演示会话，固定 300ms 会在锚未落时采样，cancel
                 相对 base 零变化=假红）；轮询等画面变化再记锚 */
              fire('touchstart',x,y);
              let pinned=h();
              for(let i=0;i<15;i++){
                await new Promise(rs=>setTimeout(rs,100));
                if(h()!==base){pinned=h();break;}}
              fire('touchcancel',x,y);
              await new Promise(rs=>setTimeout(rs,350));
              const afterCancel=h();
              /* cancel 已把双拍状态机清零（生产行为）：随后的同点
                 二次拍在状态机里是「首拍」不跳转——先来一发预备拍
                 重建 _tPin，再同点二次拍才是真二次 */
              fire('touchstart',x,y);
              await new Promise(rs=>setTimeout(rs,200));
              fire('touchend',x,y);
              await new Promise(rs=>setTimeout(rs,250));
              const tabBefore=MONTAB;
              fire('touchstart',x,y);
              await new Promise(rs=>setTimeout(rs,200));
              fire('touchend',x,y);
              c.dispatchEvent(new MouseEvent('click',{clientX:x,clientY:y,
                bubbles:true,button:0}));
              await new Promise(rs=>setTimeout(rs,500));
              return {startPainted:base!==afterStart,
                endKept:afterStart===afterEnd1,
                cancelCleared:pinned!==afterCancel,
                jumped:tabBefore!==MONTAB};
            })()""")
            _cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": False})
            ck("触屏首拍抬指读数驻留（旧无条件清线监听已退役）",
               bool(_tch.get("startPainted")) and bool(_tch.get("endKept")))
            ck("touchcancel 手势接管全清（十字线不滞留）",
               bool(_tch.get("cancelCleared")))
            ck("同点二次 tap 放行跳明细（双拍跳转路径不回归）",
               bool(_tch.get("jumped")))
            pg.evaluate("showMonTab('overview')"); pg.wait_for_timeout(200)

            # ---- r283v P3 钉（图例首屏可达 + 搜索态导航降饱和）----
            step("r283v 图例首屏与搜索态导航")
            pg.evaluate("switchView('mon')")
            pg.set_viewport_size({"width": 375, "height": 812})
            # 前序段的页面滚动位跨视口残留会把图例推出首屏（几何相对
            # 视口）——首屏可达语义从页顶起算，先归零再量
            pg.evaluate("window.scrollTo(0,0)")
            pg.evaluate("showMonTab('details')"); pg.wait_for_timeout(300)
            pg.evaluate("(()=>{const fb=document.querySelector('.fbar');"
                        "if(fb&&!fb.classList.contains('open'))togFlt();})()")
            pg.wait_for_timeout(300)
            _lgd = pg.evaluate(
                """()=>{const e=document.getElementById('fltlegend');
                  if(!e)return {ok:false,why:'no-el'};
                  const disp=getComputedStyle(e).display;
                  const r=e.getBoundingClientRect();
                  return {ok:disp!=='none'&&r.top>=0
                          &&r.top<window.innerHeight&&r.height>0,
                          why:'disp='+disp+' top='+Math.round(r.top)
                          +' h='+Math.round(r.height)+' vh='+window.innerHeight
                          +' fb='+(document.querySelector('.fbar')||{}).className
                          +' chips='+document.querySelectorAll('#routechips .chip').length
                          +'/'+document.querySelectorAll('#datechips .chip').length
                          +' scrollY='+window.scrollY};}""")
            ck("375 图例补位行首屏可达（预设行后，免滚动）（%s）"
               % _lgd.get("why"), _lgd["ok"])
            pg.evaluate("(()=>{const fb=document.querySelector('.fbar');"
                        "if(fb&&fb.classList.contains('open'))togFlt();})()")
            pg.set_viewport_size(_vp0); pg.wait_for_timeout(200)
            pg.evaluate("switchView('cfg')"); pg.wait_for_timeout(900)
            pg.evaluate("(()=>{const si=document.getElementById('cfgSearch');"
                        "const st=Object.getOwnPropertyDescriptor("
                        "HTMLInputElement.prototype,'value').set;"
                        "st.call(si,'扫描周期');si.dispatchEvent("
                        "new Event('input',{bubbles:true}));cfgFilter('扫描周期');})()")
            pg.wait_for_timeout(300)
            ck("配置搜索态左导航高亮降饱和（暂态去处语义）", pg.evaluate(
                """()=>{const on=document.querySelector('#cfgnav .cnav.on');
                  return !!on && parseFloat(getComputedStyle(on).opacity)<1;}"""))
            pg.evaluate("cfgSearchClear();showCfgPanel('users',true)")
            pg.wait_for_timeout(300)
            ck("搜索清空后左导航高亮满饱和回归", pg.evaluate(
                """()=>{const on=document.querySelector('#cfgnav .cnav.on');
                  return !!on && parseFloat(getComputedStyle(on).opacity)>=1;}"""))
            pg.evaluate("switchView('mon')"); pg.wait_for_timeout(300)

            # ---- 吸顶切换器滚轮横滚通道钉 ----
            # 主动制造溢出（注入临时宽件）：转写守卫「真横向可滚才
            # 抢滚轮」的阈值是 +4，字体回退链随环境漂移会让自然溢出
            # 量不稳定（窄了守卫短路=功能语义正确、钉却假红）——
            # 钉面验证的是「溢出在场时转写必须生效」这个行为本身，
            # 不依赖环境字体量纲
            step("吸顶切换器滚轮横滚")
            pg.set_viewport_size({"width": 375, "height": 812})
            pg.evaluate("showMonTab('overview')"); pg.wait_for_timeout(300)
            # r368 用户级 tab 名更长：375 允许容器内横滚（xhint 提示），
            # 但不得撑破页面；触控高仍须 ≥36
            ck("375 切换器容器内横滚且触控高≥36",
               pg.evaluate(
                """()=>{
                  const m=document.getElementById('montabs');
                  if(!m)return false;
                  const ts=[...m.querySelectorAll('.mtab')];
                  return (ts.length===5||ts.length===6)
                    &&m.scrollWidth>=m.clientWidth
                    &&ts.every(t=>t.getBoundingClientRect().height>=36)
                    &&document.documentElement.scrollWidth
                      <=document.documentElement.clientWidth+1;
                }"""))
            pg.set_viewport_size(_vp0); pg.wait_for_timeout(200)
            pg.evaluate("switchView('cfg')"); pg.wait_for_timeout(300)

            # ---- 带界连续性钉（r289 P3-1）：wrap 渐进带 1280 起（92vw
            # 托底 1180 连续函数），相邻带界两侧内容宽差 <2%——十六§12
            # 验收口径=跨带病灶窗口量原症状指标（r285 修 ≥1440 侧时
            # 900-1439 恒 1180 与 92vw 的下侧断缝 +12.3% 在案） ----
            step("带界连续性 1439/1441")
            pg.evaluate("switchView('mon');showMonTab('overview')")
            pg.wait_for_timeout(200)
            def _wrap_w(w):
                pg.set_viewport_size({"width": w, "height": 900})
                pg.wait_for_timeout(120)
                return pg.evaluate(
                    "document.querySelector('.wrap').getBoundingClientRect().width")
            w1439, w1441 = _wrap_w(1439), _wrap_w(1441)
            ck("wrap 1439→1441 内容宽差 <2%%（实测 %.1f→%.1f）"
               % (w1439, w1441), abs(w1441 - w1439) / w1439 < 0.02)
            step("带界连续性 1275/1285")
            w1275, w1285 = _wrap_w(1275), _wrap_w(1285)
            ck("wrap 1275→1285 托底释放差 <2%%（实测 %.1f→%.1f）"
               % (w1275, w1285), abs(w1285 - w1275) / w1275 < 0.02)
            step("带界连续性 1919/1921")
            w1919, w1921 = _wrap_w(1919), _wrap_w(1921)
            ck("wrap 1919→1921 封顶平稳（实测 %.1f→%.1f）"
               % (w1919, w1921), abs(w1921 - w1919) < 2)
            step("1439 解锁同拍（statline≡grid 右缘）")
            pg.set_viewport_size({"width": 1439, "height": 900})
            pg.wait_for_timeout(120)
            ck("1439 statline 与 grid 同宽（解锁随 wrap 渐进同拍）",
               pg.evaluate(
                """()=>{
                  const s=document.querySelector('.statline'),
                        g=document.querySelector('.grid');
                  if(!s||!g)return false;
                  return Math.abs(s.getBoundingClientRect().width
                                 -g.getBoundingClientRect().width)<2;
                }"""))
            pg.set_viewport_size(_vp0); pg.wait_for_timeout(200)

            # ---- r291 城市守卫/保存反馈/动作行/搜索空态（流程末位：
            #      段内操纵 CFG 与搜索态，段尾全量复位防下游污染） ----
            step("r291 cfg 城市守卫与保存反馈")
            pg.evaluate("switchView('cfg');showCfgPanel('users')")
            pg.wait_for_timeout(250)
            # 动作条唯一性（r348）：添加入口只在工具条出现一次；保存
            # 不在面板内平铺（脏态由全局 savebar 承担）；数据动作同排同高
            _btnrow = pg.evaluate("""()=>{
              const bs=[...document.querySelectorAll('#sec-users .cfgtoolbar-act button')];
              const hs=bs.map(b=>Math.round(b.getBoundingClientRect().height));
              return {n:bs.length, spread:hs.length?Math.max(...hs)-Math.min(...hs):-1,
                      add:document.querySelectorAll('#sec-users button[onclick="addUser()"]').length,
                      save:document.querySelectorAll('#sec-users button[onclick="saveCfg()"]').length};
            }""")
            ck("P3-1 动作条三钮同高且添加/保存唯一（spread=%s n=%s add=%s save=%s）"
               % (_btnrow["spread"], _btnrow["n"], _btnrow["add"], _btnrow["save"]),
               _btnrow["n"] == 3 and _btnrow["spread"] <= 3
               and _btnrow["add"] == 1 and _btnrow["save"] == 0)
            # P1-1 归一例：「哈尔滨市」剥市后缀命中 HRB（wizard 先例：
            # 剥「市」归一成功是正路，非拦截）——saveCfg 同步校验段
            # 在首个 await 前执行完，快照即校验产物
            _norm = pg.evaluate("""()=>{
              const r=CFG[0].routes[0];
              const keep={fn:r.from_name,tn:r.to_name,f:r.from,t:r.to};
              r.from_name='哈尔滨市';
              saveCfg();
              const after={f:r.from,n:r.from_name};
              r.from_name=keep.fn;r.to_name=keep.tn;r.from=keep.f;r.to=keep.t;
              return after;
            }""")
            ck("P1-1 「哈尔滨市」归一成功切 HRB（实测 from=%s name=%s）"
               % (_norm["f"], _norm["n"]),
               _norm["f"] == "HRB" and _norm["n"] == "哈尔滨")
            # P1-1 拦截例（真表外名）+ P2-1 双通道必达。
            # 样本随 r320 全国城市表扩容换名：旧样本「景德镇」已入
            # 289 城官方表（归一放行是正确语义），拦截样本改真表外名
            _blk = pg.evaluate("""()=>{
              const r=CFG[0].routes[0];
              const keep={fn:r.from_name,f:r.from};
              r.from_name='乌有市';
              saveCfg();
              const snap={msg:document.getElementById('cfgmsg').textContent,
                toasts:[...document.querySelectorAll('#toasts .toast')]
                  .map(t=>t.textContent)};
              r.from_name=keep.fn;r.from=keep.f;
              return snap;
            }""")
            ck("P1-1b 表外城市名保存被拦（cfgmsg=%s）" % _blk["msg"][:20],
               "不支持的城市" in _blk["msg"] and "乌有市" in _blk["msg"])
            ck("P2-1a 校验失败 toast 必达（双通道非仅视口外 cfgmsg）",
               any("不支持的城市" in t for t in _blk["toasts"]))
            # P1-1c 前缀名拦截（UI 不做前缀联想——歧义面保守，wizard 的
            # 唯一前缀联想属 CLI 交互形态）
            _pre = pg.evaluate("""()=>{
              const r=CFG[0].routes[0];
              const keep={fn:r.from_name,f:r.from};
              r.from_name='哈尔';
              saveCfg();
              const m=document.getElementById('cfgmsg').textContent;
              r.from_name=keep.fn;r.from=keep.f;
              return m;
            }""")
            ck("P1-1c 前缀名「哈尔」保存被拦（cfgmsg=%s）" % _pre[:20],
               "不支持的城市" in _pre)
            # P1-1d 存量缺名行兼容：名字槽空而码槽合法三字码 → 码即名
            # 放行（外部 yaml/手写来源的存量行不被新守卫卡死整次保存）
            _miss = pg.evaluate("""()=>{
              const r=CFG[0].routes[0];
              const keep={fn:r.from_name,f:r.from};
              r.from_name='';r.from='SHA';
              saveCfg();
              const after={fn:r.from_name,f:r.from,
                msg:document.getElementById('cfgmsg').textContent};
              r.from_name=keep.fn;r.from=keep.f;
              return after;
            }""")
            ck("P1-1d 空名+合法码放行（实测 name=%s from=%s）"
               % (_miss["fn"], _miss["f"]),
               _miss["fn"] == "SHA" and _miss["f"] == "SHA")
            # P2-1b 重复航线 toast 必达
            _dup = pg.evaluate("""()=>{
              const r=CFG[0].routes[0];
              const keep=r.dates.slice();
              r.dates.push(r.dates[0]);
              saveCfg();
              const toasts=[...document.querySelectorAll('#toasts .toast')]
                .map(t=>t.textContent);
              r.dates=keep;
              return toasts;
            }""")
            ck("P2-1b 重复航线 toast 必达", any("重复航线" in t for t in _dup))
            # P3-2：配置搜索零命中时主区有教学引导行（空态教导清空
            # 恢复，不留全空白主区）
            _empty = pg.evaluate("""()=>{
              cfgFilter('zzq不存在词');
              const e=document.getElementById('cfgEmpty');
              const vis=e&&e.style.display!=='none'&&e.offsetHeight>0;
              cfgSearchClear();
              const off=!e||e.style.display==='none';
              return {vis,off,txt:e?e.textContent.slice(0,40):''};
            }""")
            ck("P3-2 搜索零命中主区引导行在位（实测 txt=%s）" % _empty["txt"],
               _empty["vis"] and _empty["off"])
            pg.evaluate("switchView('mon')")
            pg.wait_for_timeout(150)

            # ---- r292 登录轮询视图生命周期（流程末位）：真实
            #      switchView 路径的启停行为钉——进配置停登录分区
            #      （主路径，不经 showCfgPanel）必须拉起 30s 轮询；
            #      切回监控视图必须停表（「切走即停」在视图出口兑现）。
            #      段尾复原函数与视图（共享 page 状态复位律） ----
            step("r292 登录轮询视图生命周期")
            pg.evaluate("""()=>{
              showCfgPanel('login',true);   /* 前段可能停在别的分区 */
              window.__lgRaw={s:lgWatchStart,p:lgWatchStop};
              window.__lg={s:0,p:0};
              lgWatchStart=function(){window.__lg.s++;
                return window.__lgRaw.s();};
              lgWatchStop=function(){window.__lg.p++;
                return window.__lgRaw.p();};}""")
            # 前段（r291 尾）已 switchView('mon')：此处直接清计数
            pg.evaluate("window.__lg={s:0,p:0}")
            pg.evaluate("switchView('cfg')")
            _lg1 = pg.evaluate("()=>({s:window.__lg.s,t:LGTIMER!==''})")
            ck("r292 进配置停登录分区轮询拉起（主路径，实测 s=%s）"
               % _lg1["s"], _lg1["s"] >= 1 and _lg1["t"])
            pg.evaluate("switchView('mon')")
            _lg2 = pg.evaluate("()=>({p:window.__lg.p,t:LGTIMER!==''})")
            ck("r292 切回监控视图轮询停表（实测 p=%s）" % _lg2["p"],
               _lg2["p"] >= 1 and not _lg2["t"])
            pg.evaluate("""()=>{lgWatchStart=window.__lgRaw.s;
              lgWatchStop=window.__lgRaw.p;}""")
            pg.wait_for_timeout(150)

            # ---- r295 渠道胶囊缺口教学 toast（流程末位）：行情面
            #      （胶囊行级收集不过出发时段窗）与购买面（明细池过
            #      _keep 窗）缺口在场时，点击教学句点名「全线最低为何
            #      不在列表」。demo 合成数据携程最低价在时段窗外
            #      （确定性缺口）→ 教学句必在场。段尾清筛选锁、还原
            #      概览与 toast（共享 page 状态复位律） ----
            step("r295 渠道胶囊缺口教学 toast")
            pg.evaluate("""()=>{
              const old=document.getElementById('toasts');
              if(old)old.innerHTML='';
              document.querySelectorAll('.mchip')[0].click();}""")
            pg.wait_for_timeout(200)
            _mc = pg.evaluate("()=>{const t=document.getElementById('toasts');"
                              "return t?t.textContent:'';}")
            ck("r295 胶囊点击重置告知（实测=%s）" % _mc[:30],
               "已重置现有筛选" in _mc)
            ck("r295 缺口教学句在场（demo 携程窗外缺口，实测含=%s）"
               % ("未入明细" in _mc), "未入明细" in _mc)
            pg.evaluate("""()=>{FLT.plats.clear();buildChips();table();
              showMonTab('overview');
              const old=document.getElementById('toasts');
              if(old)old.innerHTML='';}""")
            pg.wait_for_timeout(150)

            # ---- r299 配置页语义配色（流程末位）：渠道胶囊按渠道
            #      识别色着装（五颗同蓝不可辨）+航线头颜色跟读者视线
            #      走（中文名上主色、三字码弱化）。computed 级行为钉
            #      （源码钉只证声明在场）；段尾回监控视图（复位律） ----
            step("r299 配置页语义配色")
            pg.evaluate("""()=>{
              switchView('cfg');
              const pills=[...document.querySelectorAll('.chip.pch.on')];
              window.__w1=pills.slice(0,2).map(x=>getComputedStyle(x).borderColor);
              const b=document.querySelector('.rhead>b');
              const tc=document.querySelector('.rtcode');
              window.__w2b=b?getComputedStyle(b).color:'';
              window.__w2t=tc?getComputedStyle(tc).color:'';}""")
            pg.wait_for_timeout(250)
            ck("r299 渠道胶囊选中态按渠道异色（前两颗 borderColor 异）",
               pg.evaluate("()=>window.__w1.length>=2 && "
                           "window.__w1[0]!==window.__w1[1]"))
            ck("r299 航线头中文名上主色、三字码弱化（computed 实测）",
               pg.evaluate("""()=>{
                 const probe=document.createElement('i');
                 probe.style.color='var(--blue)';
                 document.body.appendChild(probe);
                 const blue=getComputedStyle(probe).color;
                 probe.remove();
                 return window.__w2b===blue && window.__w2t!==blue;}"""))
            pg.evaluate("()=>switchView('mon')")
            pg.wait_for_timeout(150)

            # ---- r301 canvas 高度带界连续（审计 F-1）：旧 ≥1920 档
            #      （42vh）与 wrap 封顶点 ~1865 不同拍——1919→360 vs
            #      1920→454 在 vh=1080 产 Δ+94/+26% 整点跳变，1865-1919
            #      窗 1680×360=4.67:1 失比（宽屏拉扁形态在收窄窗残留）。
            #      修复=断点随封顶同拍 1866 起坡+带内 vw 连续函数爬升
            #      460 封顶。验收口径=跨带病灶窗口量原症状指标（相邻带
            #      界两侧值差 < 视觉可察阈）----
            step("r301 canvas 高度带界连续")
            pg.evaluate("switchView('mon');showMonTab('trend')")
            pg.wait_for_timeout(300)
            def _cv_h(w):
                pg.set_viewport_size({"width": w, "height": 1080})
                pg.wait_for_timeout(150)
                return pg.evaluate(
                    "()=>{const c=document.querySelector('#chart');"
                    "return c?c.getBoundingClientRect().height:0;}")
            h1865, h1866 = _cv_h(1865), _cv_h(1866)
            ck("canvas 1865→1866 起坡无跳变（实测 %.1f→%.1f）"
               % (h1865, h1866), abs(h1866 - h1865) < 2)
            h1919, h1920 = _cv_h(1919), _cv_h(1920)
            ck("canvas 1919→1920 高度差 <3px（病灶 Δ+94 消除，"
               "实测 %.1f→%.1f）" % (h1919, h1920),
               abs(h1920 - h1919) < 3)
            ck("canvas 1920 高度在坡带内 [385,435]（实测 %.1f）" % h1920,
               385 <= h1920 <= 435)
            pg.set_viewport_size(_vp0); pg.wait_for_timeout(200)

            # ---- r302 WebUI 审计 P3 五案（W1 宽屏双轴 / W2 改期微图
            #      锚视口 / W3 toast 断词 / W4 Esc 焦点归还 / W5 跳转
            #      词缀单形）+ T1 demo next_run 倒计时覆盖。行为钉，
            #      验收口径取自审计实测病灶带 ----
            step("r302 WebUI 审计 P3 五案+T1")
            # W1 ≥1726 概览双轴收口：statline 族与 grid 同上限
            # （min(1440px,100%)）后右缘恒等——1920 实测 Δ126px 收零；
            # 1440 带内零回归（内容宽 <1440 时 min 恒=100% 无级）
            pg.evaluate("switchView('mon');showMonTab('overview')")
            pg.wait_for_timeout(300)
            def _axes(w):
                pg.set_viewport_size({"width": w, "height": 1080})
                pg.wait_for_timeout(250)
                return pg.evaluate(
                    "()=>{const rr=s=>{const e=document.querySelector(s);"
                    "return e?Math.round(e.getBoundingClientRect().right)"
                    ":null;};"
                    "return {g:rr('.grid'),s:rr('#statline'),"
                    "k:rr('.kpisum')};}")
            a1920 = _axes(1920)
            ck("W1 1920 statline 右缘==grid 右缘（实测 %s vs %s）"
               % (a1920["s"], a1920["g"]),
               a1920["s"] is not None and a1920["s"] == a1920["g"])
            ck("W1 1920 kpisum 右缘==grid 右缘（实测 %s vs %s）"
               % (a1920["k"], a1920["g"]),
               a1920["k"] is not None and a1920["k"] == a1920["g"])
            ks = pg.evaluate(
                "()=>[...document.querySelectorAll('.kpisum a')]"
                ".map(a=>a.textContent.trim()).join('|')")
            ck("W5 跳转词缀单形 ▸（实测 %s）" % ks,
               "▸" in ks and "▾" not in ks)
            a1440 = _axes(1440)
            ck("W1 1440 带内零回归三族同线（实测 %s/%s/%s）"
               % (a1440["g"], a1440["s"], a1440["k"]),
               a1440["g"] == a1440["s"] == a1440["k"])
            # W2 ≤760 改期微图锚视口：390 档 tgbox 收进一屏（≤366），
            # 表宽不变零新增横滚；状态复位律——点开验完即收回
            pg.set_viewport_size({"width": 390, "height": 844})
            pg.evaluate("switchView('mon');showMonTab('details')")
            pg.wait_for_timeout(400)
            tg_w = pg.evaluate(
                "()=>{const t=document.querySelector('.tg');"
                "if(!t)return -1;t.click();"
                "const b=document.querySelector('.tgbox');"
                "return b?Math.round(b.getBoundingClientRect().width):-2;}")
            hscroll = pg.evaluate(
                "()=>document.documentElement.scrollWidth"
                "-document.documentElement.clientWidth")
            ck("W2 390 改期微图锚视口 ≤366px（实测 %s）" % tg_w,
               0 < tg_w <= 366)
            ck("W2 390 零新增横滚（溢出 %spx）" % hscroll, hscroll <= 0)
            pg.evaluate("()=>{const t=document.querySelector('.tg');"
                        "if(t)t.click();}")
            # W3 toast 断词纪律：word-break 交还 normal（CJK 无断点
            # 不受影响），长 token 溢出改由 overflow-wrap:anywhere
            # 承接（优先词边界，不再 CS/V 逐字断）
            wbr = pg.evaluate(
                "()=>{const t=document.createElement('div');"
                "t.className='toast';t.style.display='none';"
                "document.body.appendChild(t);"
                "const c=getComputedStyle(t);"
                "const out={wb:c.wordBreak,ow:c.overflowWrap};"
                "t.remove();return out;}")
            ck("W3 toast word-break=normal+overflow-wrap=anywhere"
               "（实测 %s/%s）" % (wbr["wb"], wbr["ow"]),
               wbr["wb"] == "normal" and wbr["ow"] == "anywhere")
            # W4 ≤760 Esc 关筛选抽屉焦点归还 fltBtn（closePv 先例
            # 同款）：开抽屉→聚焦 #fq→Esc→焦点落 fltBtn 可 Enter 重开
            pg.set_viewport_size({"width": 700, "height": 800})
            pg.wait_for_timeout(250)
            foc = pg.evaluate(
                "()=>{const b=document.getElementById('fltBtn');"
                "if(!b)return 'nobtn';b.click();"
                "const q=document.getElementById('fq');"
                "if(!q)return 'noq';q.focus();"
                "document.dispatchEvent(new KeyboardEvent('keydown',"
                "{key:'Escape',bubbles:true}));"
                "const a=document.activeElement;"
                "return a?(a.id||a.tagName):'null';}")
            ck("W4 Esc 关抽屉焦点归还 fltBtn（实测 %s）" % foc,
               foc == "fltBtn")
            # T1 demo next_run 合成：倒计时 chip（生产常态元素）在
            # demo 可见——「⏱ 下轮」词面在场且非 display:none
            nr = pg.evaluate(
                "()=>{const c=document.getElementById('nextrun');"
                "return c?{t:c.textContent.trim(),"
                "d:getComputedStyle(c).display}:null;}")
            ck("T1 demo 倒计时 chip 可见（实测 %s）"
               % (nr and (nr["t"][:14] + "/" + nr["d"])),
               nr is not None and nr["d"] != "none"
               and nr["t"][:1] in ("⏱", "🔄"))   # 采样窗容忍：页面静置逾 5min 时 chip 进「🔄 扫描中…」至 +4s 自动重拉（每 ~5min 暴露 ~4s），两态均为「生产常态元素在场」的证成
            pg.set_viewport_size(_vp0); pg.wait_for_timeout(200)

            # ---------- 三钉（新钉段置尾：全部既有断言之后、统计之前） ----------
            # R1 hdmeta 独占行断点 ≤600：病灶带内 flexBasis=100%（独占行）、
            #    601+ 回单行，页面级零横滚双证。缺陷本体只在经典滚条内核
            #    （竖滚条吃 ~10px 布局宽）显形，本 harness 为 overlay 滚条
            #    环境——行为钉锁断点生效位置，横滚不变式作回归守卫
            pg.set_viewport_size({"width": 560, "height": 960})
            pg.wait_for_timeout(250)
            _fb560 = pg.evaluate(
                "()=>({fb:getComputedStyle(document.querySelector('.hdmeta')).flexBasis,"
                "sw:document.documentElement.scrollWidth,"
                "cw:document.documentElement.clientWidth})")
            ck("R1a hdmeta 560 带独占行（flexBasis=%s）" % _fb560["fb"],
               _fb560["fb"] == "100%")
            ck("R1b 560 带页面零横滚（sw=%s cw=%s）"
               % (_fb560["sw"], _fb560["cw"]), _fb560["sw"] <= _fb560["cw"])
            pg.set_viewport_size({"width": 620, "height": 960})
            pg.wait_for_timeout(250)
            _fb620 = pg.evaluate(
                "()=>getComputedStyle(document.querySelector('.hdmeta')).flexBasis")
            ck("R1c 620 带回单行（flexBasis=%s）" % _fb620, _fb620 != "100%")
            pg.set_viewport_size(_vp0); pg.wait_for_timeout(200)

            # R2 数字配置「改回原值」清脏：route 数字槽（string→number 写入
            #    归一）+ notifier 缺席键槽（清空落空串，比对侧 _canon 剥空）
            #    双样本；幽灵「N 处未保存的修改」+beforeunload 常驻的回归防线。
            #    事件用 JS 派发（值+change 与真实 onchange 语义同构）：折叠/
            #    搜索态下输入框不可见，playwright click/fill 会被可见性卡死
            #    （前序钉段留下的面板态是状态变量，不依赖）
            pg.evaluate("switchView('cfg')")
            pg.wait_for_timeout(600)   # loadCfg 异步窗：CFG_CLEAN 就绪
            # 入口自净：前序钉段可能留下 addUser 类残留（CFG 比快照多
            # 实体）——不净则 before 恒真、断言退化恒真式。只净「多出的
            # 实体」；净后仍脏（字段级残留）则退化 sig 档仍有证
            pg.evaluate(
                "if(CFG.length>JSON.parse(CFG_CLEAN).length)CFG.pop()")
            _dirty_ok = True; _dirty_msg = []
            for _sel in ('input[onchange*="alert_direct"]',
                         'input[onchange*="report_hour"]'):
                _r2 = pg.evaluate(
                    """(sel)=>{const i=document.querySelector(sel);
                     if(!i)return {err:'无输入'};
                     const C=()=>JSON.stringify(_canon(CFG,JSON.parse(CFG_CLEAN)));
                     const s0=C();
                     const clean0=cfgIsDirty();
                     const o=i.value;
                     i.value='7';i.dispatchEvent(new Event('change',{bubbles:true}));
                     const d1=cfgIsDirty();
                     i.value=o;i.dispatchEvent(new Event('change',{bubbles:true}));
                     return {d1,d2:cfgIsDirty(),clean0,sig:C()===s0};}""", _sel)
                # 强断言（入口干净）：变脏→改回复位；兜底断言（任何入口
                # 态）：CFG 规范形逐字节还原（类型残留在此现形；清空键
                # 的空串残留经 _canon 剥空豁免——与 dirty 语义同口径）
                if _r2.get("err") or not _r2.get("sig") or (
                        not _r2.get("clean0")
                        and (_r2.get("d1") is not True
                             or _r2.get("d2") is not False)):
                    _dirty_ok = False
                    _dirty_msg.append("%s %s" % (_sel, _r2))
            ck("R2 数字配置改回原值清脏（%s）" %
               ("; ".join(_dirty_msg) or "双样本过"), _dirty_ok)
            pg.evaluate("switchView('mon')")
            pg.wait_for_timeout(300)

            # R3 chart 同值零 childList：hover 三帧 MutationObserver 计数=0
            #    （savebar 同值守卫先例；监听 childList 的用户扩展全页重扫
            #    卡顿面。chartTitle 同值跳过/ringNote 备忘式守卫/尾注在
            #    场跳过三口同守）
            pg.evaluate("showMonTab('trend')")
            pg.wait_for_timeout(800)
            _hov = pg.evaluate(
                "()=>{const t=document.getElementById('chartTitle'),"
                "n=document.getElementById('ringNote');"
                "if(!t||!n)return 'missing';"
                "window.__r3cl=0;"
                "const io=new MutationObserver(ms=>{for(const m of ms){"
                "if(m.type==='childList')window.__r3cl+="
                "m.addedNodes.length+m.removedNodes.length;}});"
                "io.observe(t,{childList:true});io.observe(n,{childList:true});"
                "const c=document.getElementById('chart');"
                "const r=c.getBoundingClientRect();"
                "return {x:r.left,y:r.top,w:r.width,h:r.height};}")
            if _hov == "missing":
                ck("R3 chart 同值零 childList（目标缺失）", False)
            else:
                pg.mouse.move(_hov["x"] + _hov["w"] * 0.3,
                              _hov["y"] + _hov["h"] * 0.5)
                pg.wait_for_timeout(200)
                pg.mouse.move(_hov["x"] + _hov["w"] * 0.6,
                              _hov["y"] + _hov["h"] * 0.5)
                pg.wait_for_timeout(200)
                pg.mouse.move(_hov["x"] + _hov["w"] * 0.3,
                              _hov["y"] + _hov["h"] * 0.5)
                pg.wait_for_timeout(250)
                _cl = pg.evaluate("window.__r3cl")
                ck("R3 chart 同值零 childList（hover 三帧 %s 节点）" % _cl,
                   _cl == 0)

            # R4 chhead 状态右聚拢：muted+chev 贴卡右缘（双 auto 平分
            #   曾把状态词面顶到卡/面板中央——展开态 1180px 面板 muted
            #   距右缘 549px 实锤）。展开态图床卡 + 一张收起卡双样本。
            #   先切回配置视图（R3 留在监控视图——隐藏容器 rect 全零
            #   会产出 gap=0 的恒真式），并带可见性哨卫防恒真。
            #   用户卡若被前序钉段折叠，chcard 随折叠体隐藏——先走真实
            #   展开路径（uhead2 真点，十九§7），不用 display 硬掰
            pg.evaluate("switchView('cfg');cfgFilter('');showCfgPanel('users',true)")
            pg.wait_for_timeout(400)
            pg.evaluate(
                """(()=>{const u=document.querySelector('#cfgform .ucard .uhead2');
                 if(u&&u.nextElementSibling&&u.nextElementSibling.getBoundingClientRect().width===0)u.click();})()""")
            pg.wait_for_timeout(300)
            _r4 = pg.evaluate(
                """(()=>{
                  const probe=(card)=>{
                    const cr=card.getBoundingClientRect();
                    const m=card.querySelector('.chhead .muted'),
                          cv=card.querySelector('.chhead .chev');
                    if(!m||!cv)return null;
                    const mr=m.getBoundingClientRect(),cvr=cv.getBoundingClientRect();
                    if (!mr.width || !cr.width) return {invis:true};
                    return {gap:Math.round(cr.right-mr.right),
                            chevRightOfMuted:Math.round(cvr.left-mr.right)};};
                  return {exp:probe(document.querySelector('.chcard[data-ch="imghost"]')),
                          col:probe(document.querySelector('.chcard[data-ch="dingtalk"]'))};})()""")
            if not _r4 or not _r4.get("exp") or not _r4.get("col") \
                    or _r4["exp"].get("invis") or _r4["col"].get("invis"):
                _diag = pg.evaluate(
                    """(()=>{const c=document.querySelector('.chcard[data-ch="imghost"]');
                     const m=c&&c.querySelector('.chhead .muted');
                     const cr=c&&c.getBoundingClientRect();
                     return {VIEW, cfg:document.getElementById('cfgview').style.display,
                             panel:document.getElementById('panel-users').style.display,
                             cardCls:c?c.className:null,
                             crW:cr?Math.round(cr.width):-1,
                             mW:(m&&cr)?Math.round(m.getBoundingClientRect().width):-1,
                             q:(document.getElementById('cfgSearch')||{}).value};})()""")
                ck("R4 chhead 状态右聚拢（目标缺失或不可见 %s | %s）"
                   % (_r4, _diag), False)
            else:
                ck("R4 展开态 muted 距右缘 %spx（<120）+ chev 在 muted 右侧 %s"
                   % (_r4["exp"]["gap"], _r4["exp"]["chevRightOfMuted"] >= 0),
                   _r4["exp"]["gap"] < 120 and _r4["exp"]["chevRightOfMuted"] >= 0)
                ck("R4 收起态 muted 距右缘 %spx（<120）"
                   % _r4["col"]["gap"], _r4["col"]["gap"] < 120)

            # R5 图床 ghimg 形态（demo 夹具=生产主通路形态）：header 词面
            #   「GitHub 图库」+ ghimg chip 选中 + repo/proxy 行随类可见。
            #   演示态曾恒缺 image_host——生产形态在 demo/审计里永久隐身
            #   的扫盲盲区回归防线。先走真实展开路径（foldCh 内联 none
            #   压过 CSS 类显隐，折叠态 offsetParent 恒 null=假红）
            pg.evaluate(
                "document.querySelector('.chcard[data-ch=\\'imghost\\'] .chhead').click()")
            pg.wait_for_timeout(300)
            _r5 = pg.evaluate(
                """(()=>{
                  const c=document.querySelector('.chcard[data-ch="imghost"]');
                  if(!c)return {err:'无图床卡'};
                  const m=c.querySelector('.chhead .muted');
                  const chip=c.querySelector('.ihchip[data-p="ghimg"]');
                  const repo=c.querySelector('.ih-repo');
                  const tok=c.querySelector('.ih-token');
                  return {label:m&&m.textContent,
                          ghOn:!!(chip&&chip.classList.contains('on')),
                          repoVisible:!!(repo&&repo.offsetParent!==null),
                          smmsTokenHidden:!!(tok&&tok.offsetParent===null)};})()""")
            if _r5.get("err"):
                ck("R5 ghimg 形态（%s）" % _r5["err"], False)
            else:
                ok5 = (_r5.get("label") == "GitHub 图库" and _r5.get("ghOn")
                       and _r5.get("repoVisible") and _r5.get("smmsTokenHidden"))
                ck("R5 ghimg 形态（label=%s chip=%s repo行=%s smmsToken藏=%s）"
                   % (_r5.get("label"), _r5.get("ghOn"), _r5.get("repoVisible"),
                      _r5.get("smmsTokenHidden")), ok5)

            # R6 通道网格语义序：动作按钮（添加邮箱通道）收尾——配置卡
            #   一组、动作件最后（动作件曾被图床卡隔在中间，用户立案）
            _r6 = pg.evaluate(
                """(()=>{const g=document.querySelector('#cfgform .chgrid');
                 if(!g||!g.lastElementChild)return {err:'无网格'};
                 const last=g.lastElementChild;
                 return {tag:last.tagName,
                         isAdd:last.tagName==='BUTTON'
                         &&(last.getAttribute('onclick')||'').indexOf('addEm')>=0};})()""")
            if _r6.get("err"):
                ck("R6 动作按钮收尾（%s）" % _r6["err"], False)
            else:
                ck("R6 动作按钮收尾（chgrid 尾件=%s addEm=%s）"
                   % (_r6["tag"], _r6["isAdd"]), _r6["isAdd"] is True)

            # R7 删除用户入口从卡内底部移到卡头：收起态也一眼可达，
            #   不再要求「展开→滚到最底」；卡内底部不得残留同一动作
            _r7 = pg.evaluate(
                """(()=>{const h=document.querySelector('#cfgform .uhead2');
                 if(!h)return {err:'缺卡头'};
                 const was=h.getAttribute('aria-expanded');
                 if(was==='true')h.click();
                 const del=h.querySelector('.uact.danger');
                 const r=del?del.getBoundingClientRect():{width:0,height:0};
                 const out={visible:!!del&&r.width>12&&r.height>12,
                            label:del?(del.getAttribute('aria-label')||''):'',
                            bottom:document.querySelectorAll('#cfgform .ucard > button.danger').length,
                            collapsed:h.getAttribute('aria-expanded')};
                 if(was==='true')h.click();
                 return out;})()""")
            if _r7.get("err"):
                ck("R7 卡头删除入口（%s）" % _r7["err"], False)
            else:
                ck("R7 删除用户入口收起态可达（label=%s bottom=%s）"
                   % (_r7["label"][:14], _r7["bottom"]),
                   _r7["visible"] and "删除用户" in _r7["label"]
                   and _r7["bottom"] == 0 and _r7["collapsed"] == "false")

            # ---- r312 P3-1 header 出血随 wrap padding 同函数（几何行为
            #   钉，三带巡检）：391-599 带旧 -18px 常量出血 > clamp 地板
            #   12px，左缘越出视口被裁、右缘露底色缝（经典滚条环境还潜
            #   伏 6px 横滚）；修后 bleed=-clamp(12px,3vw,18px) 与 padding
            #   相抵→本带两缘齐平。≤390（-10px 覆写）与 ≥600（inset 设计
            #   =pad-18）带锁原形防反向伤害（LESSONS 十六§10 带界巡检）。
            #   几何断言先落概览视图（display 翻转架构，廿一§2）
            step("r312 header bleed")
            pg.evaluate("switchView('mon');showMonTab('overview',true)")
            _hdr = {}
            for _w in (390, 450, 760):
                pg.set_viewport_size({"width": _w, "height": 844})
                pg.wait_for_timeout(250)
                _hdr[_w] = pg.evaluate(
                    """(()=>{const h=document.querySelector('header')
                       .getBoundingClientRect();
                       const w=document.querySelector('.wrap')
                       .getBoundingClientRect();
                       return {dl:+(h.left-w.left).toFixed(1),
                               dr:+(w.right-h.right).toFixed(1)};})()""")
            # 390/450：bleed 与 padding 相抵→两缘齐平（dl≈dr≈0）
            ck("r312 header ≤390 带齐平（dl=%s dr=%s）"
               % (_hdr[390]["dl"], _hdr[390]["dr"]),
               abs(_hdr[390]["dl"]) <= 0.5 and abs(_hdr[390]["dr"]) <= 0.5)
            ck("r312 header 391-599 带齐平（dl=%s dr=%s）"
               % (_hdr[450]["dl"], _hdr[450]["dr"]),
               abs(_hdr[450]["dl"]) <= 0.5 and abs(_hdr[450]["dr"]) <= 0.5)
            # 760：inset 设计=pad-18（本例 22.8-18=4.8），两侧对称
            ck("r312 header ≥600 带 inset 设计保持（dl=%s 应≈4.8）"
               % _hdr[760]["dl"],
               abs(_hdr[760]["dl"] - 4.8) <= 0.6
               and abs(_hdr[760]["dr"] - 4.8) <= 0.6)
            pg.set_viewport_size({"width": 1280, "height": 900})

            # ---- r312 P1-1 失败态点击状态 pill 的 toast 词面分路（行为
            #   钉）：首载失败（S=null）+ pill 已明示「服务异常」时，点击
            #   播「数据加载中」与 pill 自相矛盾（词面误导家族）——修后按
            #   pill bad 旗标播「服务异常，恢复后自动刷新」。业务层失败
            #   模拟（200 非 JSON 体，route.fulfill）不污染零 JS 错门禁
            #   （廿三§2）；钉段置尾+unroute+reload 自净（十八§6）
            step("r312 svc-bad pill toast")
            pg.route("**/api/state", lambda r: r.fulfill(
                status=200, content_type="text/plain",
                body="502 Bad Gateway"))
            pg.reload(wait_until="domcontentloaded")
            pg.wait_for_timeout(900)
            _ptxt = pg.evaluate(
                "document.getElementById('pill').textContent")
            pg.evaluate("jumpQual()")
            _ttxt = pg.evaluate(
                """(()=>{const ts=document.querySelectorAll('#toasts .toast');
                   return ts.length?ts[ts.length-1].textContent:'';})()""")
            ck("r312 失败态 pill 词面（pill=%s toast=%s）"
               % (_ptxt, _ttxt),
               _ptxt == "服务异常" and "服务异常" in _ttxt
               and "数据加载中" not in _ttxt)
            pg.unroute("**/api/state")
            pg.reload(wait_until="networkidle")
            pg.wait_for_timeout(400)

            # ---- r313 R2-1 词组断词孤字钉（行为钉，置尾十八§6）：明细
            #   次行段 .stl 内含 CJK 的 span 折行时首行 <1.8em 即断词孤
            #   字（「中型机」曾拆成「中／型机…」，机型 span 漏挂 .nw）。
            #   Range 行盒按 Y 聚类归行（容差 4px，span 边界多 rect 与
            #   inline 基线错位非折行，廿一§15）；三窄带逐一实测。
            #   注：_orphan_js 非 raw 串，CJK 范围在 Python 编译期已成
            #   字面字符，JS 正则语义等价
            step("r313 stl orphan")
            _orphan_js = """
              (()=>{const res=[];
                document.querySelectorAll('#ftable .stl span').forEach(sp=>{
                  const t=sp.textContent||'';
                  if(!/[\u4e00-\u9fff]/.test(t))return;
                  const r=document.createRange();r.selectNodeContents(sp);
                  const rects=[...r.getClientRects()].filter(x=>x.width>1);
                  if(!rects.length)return;
                  const rows=[];
                  rects.forEach(x=>{const row=rows.find(
                    y=>Math.abs(y.top-x.top)<4);
                    if(row)row.w+=x.width;
                    else rows.push({top:x.top,w:x.width});});
                  const fs=parseFloat(getComputedStyle(sp).fontSize)||11;
                  if(rows.length>1&&rows[0].w<fs*1.8)
                    res.push(t.slice(0,12)+'@'+Math.round(rows[0].w));
                });
                return res;})()"""
            for _ow in (390, 600, 768):
                pg.set_viewport_size({"width": _ow, "height": 900})
                pg.goto(pg.url.split("#")[0] + "#details/u0")
                # v1.5.274：≤900 表头也收起，旧选择器首命中 thead 行会判不可见
                pg.wait_for_selector("#ftable tbody tr[data-k]",
                                     timeout=15000)
                pg.wait_for_timeout(400)
                _oh = pg.evaluate(_orphan_js)
                ck("r313 %d 带次行段零断词孤字%s" % (_ow, _oh[:2]),
                   not _oh)
            pg.set_viewport_size({"width": 1280, "height": 900})
            pg.goto(pg.url.split("#")[0])
            pg.wait_for_timeout(400)

            # ---- r315 防退化锚（审计探针采样伪影两族）：段在流程最末
            # （统计落盘前）。两钉锁「媒体重算窗口/真实键入管线」的正
            # 面形态——审计探针在仿真开启后固定短等待内采样（媒体重算
            # 未完成）与用 fill 直设 value（不发 change）曾双双把在场
            # 行为测成缺席（撤案同轮补锚，防下一轮审计重蹈）----
            step("r315 CDP coarse 媒体重算窗锚")
            pg.evaluate("switchView('mon')")
            pg.evaluate("showMonTab('trend')"); pg.wait_for_timeout(300)
            _cdp2 = pg.context.new_cdp_session(pg)
            _cdp2.send("Emulation.setTouchEmulationEnabled",
                       {"enabled": True, "maxTouchPoints": 5})
            # 媒体重算非同步且触控档 padding 带 transition：仿真开启后
            # matchMedia 翻 coarse 要等帧边界、padding 6→9px 有过渡动
            # 画——两层都轮询等稳定值再断言，固定等待采样早于重算/落
            # 在过渡帧（实测 8.56px 中间态）都是伪影
            _coarse = False
            for _ in range(20):
                pg.wait_for_timeout(100)
                if pg.evaluate(
                        "()=>matchMedia('(pointer:coarse)').matches"):
                    _coarse = True
                    break
            _mtp = ""
            for _ in range(15):
                pg.wait_for_timeout(100)
                _mtp = pg.evaluate(
                    "()=>{const m=document.querySelector('#montabs .mtab')"
                    "||document.querySelector('.mtab');"
                    "return m?getComputedStyle(m).paddingTop:'';}")
                if _mtp == "9px":
                    break
            _cdp2.send("Emulation.setTouchEmulationEnabled",
                       {"enabled": False})
            pg.wait_for_timeout(200)
            ck("CDP coarse 媒体重算翻真（仿真开启非同步生效）", _coarse)
            ck("coarse 下 mtab 触控档 paddingTop=9px", _mtp == "9px")

            step("r315 savebar change 原生管线锚")
            # 真实键入管线：逐键输入（input 事件）+失焦（change 由浏
            # 览器对 value 变化原生触发）——fill 直设 value 不发
            # change、漏 dispatch 的探针曾把在场管线测成缺席；本钉锁
            # 真实管线不需任何手工 dispatch 也能点亮脏态守卫
            pg.evaluate("switchView('cfg')")
            pg.wait_for_timeout(400)
            pg.click('#cfgnav .cnav[data-p="globals"]')
            pg.wait_for_timeout(500)
            _gl = pg.query_selector("#glbIv")
            if _gl:
                # 逐键输入（type=真实键事件管线，触发 input；本环境
                # Playwright 无 press_sequentially，type 同语义）
                pg.type("#glbIv", "9")
                pg.evaluate(
                    "()=>{if(document.activeElement)"
                    "document.activeElement.blur();}")
                # 脏态点亮走 800ms 巡检 tick：blur 落在 tick 刚过后时
                # 固定 800ms 等待跨不到下一 tick（相位假红）——轮询等
                # savebar 真亮，等待余量覆盖最坏相位（tick+过渡 ~1.1s）
                _sb = False
                for _ in range(20):
                    pg.wait_for_timeout(100)
                    if pg.is_visible("#savebar"):
                        _sb = True
                        break
                ck("真实键入+失焦点亮 savebar（change 原生管线）", _sb)
            pg.evaluate("switchView('mon')"); pg.wait_for_timeout(200)

            # ---- r322 WebUI 行为钉（审计 P3-2）：段在流程最末（统计
            #   落盘前）。≤900 带 .cfgnav 转 row+wrap 后空态 .cfghit（0 宽）
            #   占 flex 行首吃 column-gap 4px——搜索框与首个导航片左缘
            #   错位 4px（760 实测 22.8 vs 26.8）。钉锁双态左缘同线：空态
            #   与命中态（cfgHits 有文本时宽度更大，错位面更大）导航片
            #   都必须回到搜索框同线。命中态走真实 input 管线+防抖余量
            #   （cfgFilterD 250ms，等 600ms）。段尾复原视口与视图 ----
            step("r322 cfgnav 左缘对齐")
            pg.set_viewport_size({"width": 760, "height": 900})
            pg.evaluate("switchView('cfg')")
            pg.wait_for_timeout(400)
            _align_js = (
                "()=>{const s=document.querySelector('.cfgnav .cfgsearch');"
                "const n=document.querySelector('.cfgnav .cnav');"
                "if(!s||!n)return -1;"
                "return Math.abs(s.getBoundingClientRect().left"
                " - n.getBoundingClientRect().left);}")
            pg.evaluate(
                "()=>{const h=document.querySelector('#cfgHits');"
                "if(h)h.textContent='';}")
            pg.wait_for_timeout(100)
            _al0 = pg.evaluate(_align_js)
            ck("r322 760 cfg 空态搜索框与导航片左缘同线(差%.1fpx)" % _al0,
               0 <= _al0 < 1.0)
            pg.type("#cfgSearch", "邮箱")
            pg.wait_for_timeout(600)
            _hit = pg.evaluate(
                "()=>(document.querySelector('#cfgHits')||{}).textContent||''")
            _al1 = pg.evaluate(_align_js)
            ck("r322 760 cfg 命中态(%s)左缘同线(差%.1fpx)"
               % (_hit[:6], _al1), _hit and 0 <= _al1 < 1.0)
            pg.evaluate(
                "()=>{const e=document.querySelector('#cfgSearch');"
                "if(e){e.value='';}"
                "const h=document.querySelector('#cfgHits');"
                "if(h)h.textContent='';}")
            pg.set_viewport_size({"width": 1280, "height": 900})
            pg.evaluate("switchView('mon')")
            pg.wait_for_timeout(200)

            # ---- r322 WebUI 行为钉（审计 P3-1）：健康格弹性档实判定。
            #   静态 ≥1024 弹性档按 96 格满密度校准，901-1023 带现网
            #   81 轮格带 ~647px 放得下却走固定 6px 左聚档——空腔随带
            #   宽放大至 132px。demo 数据 ~125 轮格带 ~760px 在病灶带
            #   全溢出（横滚形态=正确行为），「放得下却左聚」病灶形态
            #   用删格构造。全同步单 evaluate：删格留 8 → 直调判定单源
            #   _hfit（typeof 探测——RED 时代码无此函数，走摘除等价
            #   =现状固定档）→ 量空腔 → insertBefore 复原（DOM 引用不
            #   跨 evaluate 边界；同步形态避开 Promise 与页面轮询并发
            #   的 evaluate 坑）。钉三面：1000 病灶带删格铺满、1280 原
            #   样弹性保持（退役媒体档回归面）、760 删格 fit 真挂载 ----
            step("r322 健康格弹性实判定")
            _probe_js = (
                "()=>{const el=document.querySelector('.hcells');"
                "if(!el)return null;"
                "const cells=[...el.querySelectorAll('.hc')];"
                "if(cells.length<=8)return null;"
                "const removed=cells.slice(8);"
                "removed.forEach(c=>el.removeChild(c));"
                "if(typeof _hfit==='function')_hfit(el);"
                "const r=el.getBoundingClientRect();"
                "const cs=el.querySelectorAll('.hc');"
                "const last=cs[cs.length-1].getBoundingClientRect();"
                "const out={gap:r.right-last.right,"
                "fit:el.classList.contains('fit')};"
                "for(let i=removed.length-1;i>=0;i--)"
                "el.appendChild(removed[i]);"
                "return out;}")
            _gap_js = (
                "()=>{const el=document.querySelector('.hcells');"
                "if(!el)return -1;"
                "const cells=el.querySelectorAll('.hc');"
                "if(!cells.length)return -2;"
                "const r=el.getBoundingClientRect();"
                "const last=cells[cells.length-1].getBoundingClientRect();"
                "return r.right-last.right;}")
            pg.set_viewport_size({"width": 1000, "height": 900})
            pg.evaluate("switchView('mon')")
            pg.evaluate("showMonTab('health')")
            pg.wait_for_timeout(400)
            _o1000 = pg.evaluate(_probe_js) or {}
            _g1000 = _o1000.get("gap")
            ck("r322 1000 带删格弹性铺满(空腔%.0fpx)"
               % (_g1000 if isinstance(_g1000, (int, float)) else -9),
               isinstance(_g1000, (int, float)) and 0 <= _g1000 < 8)
            pg.set_viewport_size({"width": 1280, "height": 900})
            pg.wait_for_timeout(400)
            _g1280 = pg.evaluate(_gap_js)
            ck("r322 1280 带弹性保持(空腔%.0fpx)" % _g1280,
               0 <= _g1280 < 8)
            pg.set_viewport_size({"width": 760, "height": 900})
            pg.wait_for_timeout(400)
            _o760 = pg.evaluate(_probe_js) or {}
            _g760 = _o760.get("gap")
            ck("r322 760 带删格 fit 挂载(空腔%s)"
               % (_g760 if isinstance(_g760, (int, float)) else "n/a"),
               bool(_o760.get("fit"))
               and isinstance(_g760, (int, float)) and 0 <= _g760 < 8)
            pg.set_viewport_size({"width": 1280, "height": 900})
            pg.wait_for_timeout(300)

            # ---- r323 半年走势行为钉（P2-1/P2-2）：段在流程最末（统计
            #   落盘前）。P2-1 锁「切长窗同档仅 1 发 /api/trend」——
            #   setRange 与 chart 空态分支双路径曾同档双发（seq 弃首包=
            #   确定性双倍后端负载）；fetch 包一层计数器，测毕不移除
            #   （后续无其他段）。P2-2 直调 toCandles 纯函数：日桶按本
            #   地自然日聚合（UTC 午夜桶界在 UTC+8 曾把本地日劈两半、
            #   桶标带「08:00」伪影），t0=纯日期。段尾复原视图 ----
            step("r323 半年走势双发去重与日桶")
            pg.evaluate("switchView('mon')")
            pg.evaluate("showMonTab('trend')")
            pg.wait_for_timeout(400)
            pg.evaluate(
                "()=>{window._tlN=0;const _of=window.fetch;"
                "window.fetch=(u,...a)=>{"
                "if(String(u).indexOf('/api/trend')===0)window._tlN++;"
                "return _of(u,...a);};}")
            pg.evaluate("setRange('30d')")
            pg.wait_for_timeout(1500)
            _tlN = pg.evaluate("window._tlN")
            ck("r323 切 30d 长窗 /api/trend 恰 1 发(实发 %s)" % _tlN,
               _tlN == 1)
            _dk = pg.evaluate(
                "()=>{const f=(d)=>{const x=new Date(Date.now()-d*864e5);"
                "return String(x.getMonth()+1).padStart(2,'0')+'-'"
                "+String(x.getDate()).padStart(2,'0');};"
                "const pts=[[f(1)+' 08:00',1560,0],"
                "[f(1)+' 21:00',1570,0],[f(0),1580,0]];"
                "const cs=toCandles(pts,1440);"
                "return {n:cs.length,t0s:cs.map(c=>c.t0),"
                "y1:f(1),y0:f(0)};}")
            _ok_dk = (isinstance(_dk, dict) and _dk.get("n") == 2
                      and _dk.get("t0s") == [_dk.get("y1"), _dk.get("y0")])
            ck("r323 日K本地自然日分桶+纯日期t0(%s)" % (_dk,), _ok_dk)
            pg.evaluate("setRange('48h')")
            pg.wait_for_timeout(200)

            # ---- r324 改期 chip 格缘热区钉（21§5「实际命中谁」口径）：
            #   .tg 本体 ~21px 低于触控 36px 地板，命中带靠 ::after
            #   inset:-9px -4px 纵向外扩（横向只 -4px 防吃同行 ↗）——
            #   重构若吞外扩，格缘修正带点落到邻件=钉红。采样取带内
            #   ±5px：净外扩=9px−1px 边框=8px，恰取 8px 点落在伪元素
            #   外边界上，命中判定舍入上下不对称会产假 miss（变异探针
            #   实测）。elementFromPoint 对伪元素盒返回宿主，触控仿真
            #   非必需；段在流程最末（统计落盘前），视口/视图测毕复位 ----
            step("r324 改期 chip 格缘热区")
            _vp0 = pg.viewport_size   # 段首捕获（同文件惯例：不复用上游段的捕获值）
            pg.set_viewport_size({"width": 390, "height": 844})
            pg.evaluate("switchView('mon')")
            pg.evaluate("showMonTab('details')"); pg.wait_for_timeout(400)
            _tgh = pg.evaluate(
                """()=>{
                  const tg=[...document.querySelectorAll('span.tg')]
                    .find(e=>{const r=e.getBoundingClientRect();
                      return r.width>0&&r.height>0;});
                  if(!tg)return 'no-.tg';
                  tg.scrollIntoView({block:'center'});   /* 首颗胶囊落点随数据/滚动位可贴视口底缘，采样点出视口=elementFromPoint null 假 miss；居中落位后采样锁热区本身 */
                  const r=tg.getBoundingClientRect();
                  const cx=r.left+r.width/2, cy=r.top+r.height/2;
                  const pts=[['center',cx,cy],
                             ['top+5',cx,cy-r.height/2-5],
                             ['bot-5',cx,cy+r.height/2+5]];
                  for(const [lab,x,y] of pts){
                    const el=document.elementFromPoint(x,y);
                    if(!(el&&(el===tg||tg.contains(el))))
                      return 'miss@'+lab+'->'
                        +(el?(el.className||el.tagName):'null');
                  }
                  return 'ok';
                }""")
            ck("r324 改期 chip 纵向格缘带内命中本体（实测 %s）" % _tgh,
               _tgh == "ok")
            pg.set_viewport_size(_vp0); pg.wait_for_timeout(200)
            pg.evaluate("showMonTab('overview')"); pg.wait_for_timeout(200)

            # ---- r326 国际配置面三钉（r325 国际交互的配置面收口）：
            #   演示数据无国际航线，模型构造定性（页内直调，校验段在
            #   首个 await 前同步执行完——同 P1-1 归一钉口径）。段在
            #   流程最末（统计落盘前），CFG 快照/视图段内自复位 ----
            step("r326 国际配置面")
            pg.evaluate("switchView('cfg')"); pg.wait_for_timeout(300)
            _intl3 = pg.evaluate("""()=>{
              document.getElementById('cfgmsg').textContent='';
              const r=CFG[0].routes[0];
              const keep={fn:r.from_name,tn:r.to_name,f:r.from,t:r.to};
              r.from='SHA';r.to='NRT';r.from_name='上海';r.to_name='东京成田';
              // 钉1（P1-3）：初始渲染链应用 syncRouteHead——存量国际
              // 航线打开配置页徽标即亮，不依赖「改任一字段」触发
              buildForm();
              const rl=document.querySelector('.rline[data-rk="0:0"]');
              const ri=rl&&rl.querySelector('.rintl');
              const shown=!!(ri&&getComputedStyle(ri).display!=='none');
              // 钉2（P0-1）：国际中文名保存放行，码回写走 INTLN 名→码
              saveCfg();
              const msg=document.getElementById('cfgmsg').textContent;
              const norm={f:r.from,t:r.to,
                blocked:msg.indexOf('不支持的城市')>=0};
              r.from_name=keep.fn;r.to_name=keep.tn;
              r.from=keep.f;r.to=keep.t;
              buildForm();
              // 钉3（P1-2）：国际节按码查名（INTL.map）渲染——反方向
              // 查表曾是 33 城恒空节。R36 双 Tab 后 INTL 节只在
              // _cpTab='intl' 分支渲染（dom 缺省 Tab）：显式切 Tab
              // 再 build，测毕切回国内 Tab（状态复位律）
              cityPanelTab('intl');
              // R36 后 data-l="INTL:地区名" 带冒号——不带引号的属性
              // 选择器只匹配恰为 INTL 的值（死选择器：字面在场命中
              // 0），带引号前缀匹配锁前缀族
              const ih=document.querySelectorAll(
                '.cp-sec[data-l^="INTL:"] .cp-city').length;
              const hotN=(INTL&&INTL.hot||[]).length;
              cityPanelTab('dom');
              return {shown,norm,ih,hotN};
            }""")
            ck("r326 存量国际航线徽标首渲即亮（display 在场=%s）"
               % _intl3["shown"], _intl3["shown"] is True)
            ck("r326 国际中文名保存放行+码回写（blocked=%s from=%s to=%s）"
               % (_intl3["norm"]["blocked"], _intl3["norm"]["f"],
                  _intl3["norm"]["t"]),
               _intl3["norm"]["blocked"] is False
               and _intl3["norm"]["f"] == "SHA"
               and _intl3["norm"]["t"] == "NRT")
            ck("r326 国际全量节码查名渲染 %s（热门源 %s）"
               % (_intl3["ih"], _intl3["hotN"]),
               _intl3["hotN"] > 0 and _intl3["ih"] >= _intl3["hotN"])
            pg.evaluate("switchView('mon')"); pg.wait_for_timeout(200)
            pg.evaluate("showMonTab('overview')"); pg.wait_for_timeout(200)

            # ---- goal 轮 trend 长窗失败态钉（loadTrend catch 落点）：
            #   业务层失败（200 非 JSON → r.json() 抛错进 catch，禁
            #   abort 防 console 污染）后空态容器须覆写失败词面，
            #   不驻留「正在加载」（失败分支无落点家族）；失败不写
            #   缓存=切档自然重试，恢复段断言数据面回归。段在流程
            #   最末（统计落盘前），route 段内自拆、档位段内自复位 ----
            step("goal trend 长窗失败态")
            pg.evaluate("showMonTab('trend')"); pg.wait_for_timeout(400)
            pg.click("#rng48"); pg.wait_for_timeout(400)
            pg.route("**/api/trend*", lambda r: r.fulfill(
                status=200, content_type="text/plain", body="gateway oops"))
            pg.click("#rng180"); pg.wait_for_timeout(800)
            _tf1 = pg.evaluate(
                "()=>document.getElementById('chartEmpty').textContent")
            ck("trend 失败词面落点（驻留=缺陷）: %s" % _tf1[:20],
               _tf1.find("加载失败") >= 0)
            pg.unroute("**/api/trend*")
            pg.click("#rng48"); pg.wait_for_timeout(300)
            pg.click("#rng180"); pg.wait_for_timeout(1500)
            _tf2 = pg.evaluate(
                "()=>document.getElementById('chartEmpty').style.display")
            _tf3 = pg.evaluate(
                "()=>document.getElementById('chartEmpty').textContent")
            ck("trend 恢复数据面（disp=%s txt=%s）"
               % (_tf2, _tf3[:12]),
               _tf2 == "none")
            pg.click("#rng48"); pg.wait_for_timeout(200)
            pg.evaluate("showMonTab('overview')"); pg.wait_for_timeout(200)

            # ---- goal 轮 P3 打磨钉（.dlab hairline 前缀 + .kbdtips
            #   语义分隔）：computed 双证防装饰漂移。段在流程最末 ----
            step("goal P3 打磨")
            _p3 = pg.evaluate("""()=>{
              const d=document.querySelector('.dlab');
              const bs=d&&getComputedStyle(d,'::before');
              const k=document.querySelector('.kbdtips');
              const ks=k&&getComputedStyle(k);
              return {dlab:!!(bs&&bs.content&&bs.content!=='none'
                       &&parseFloat(bs.width)>0),
                      kbd:!!(ks&&ks.borderLeftWidth!=='0px')};}""")
            ck("goal dlab hairline 前缀在场=%s" % _p3["dlab"], _p3["dlab"])
            ck("goal kbdtips 语义分隔线在场=%s" % _p3["kbd"], _p3["kbd"])

            # ---- goal 轮 P2-1 冷启动失败骨架全覆盖钉：_markStale
            #   七处落点（spbody 特价雷达/foot 页脚为漏网收口）——
            #   业务层失败形态（200 非 JSON，禁 abort 防 console 污染）
            #   触发解析门档；S=null 模拟冷启动（_markStale 只挂
            #   !S 分支：有旧数据→保旧只标注是设计内落点矩阵，二十
            #   三§3）；恢复轮 render()/spCard() 重写自愈（spCard 60s
            #   节流，spbody 自愈可滞后 ≤60s；foot 即时）。段在
            #   流程最末（统计落盘前），unroute+load 自愈段内收口 ----
            step("goal P2-1 失败骨架全覆盖")
            pg.route("**/api/state", lambda r: r.fulfill(
                status=200, content_type="text/plain", body="oops"))
            pg.route("**/api/specials", lambda r: r.fulfill(
                status=200, content_type="text/plain", body="oops"))
            pg.evaluate("S=null;load()"); pg.wait_for_timeout(600)
            _sb = pg.evaluate(
                "()=>(document.getElementById('spbody')||{}).textContent||''")
            _ft = pg.evaluate(
                "()=>(document.getElementById('foot')||{}).textContent||''")
            ck("goal spbody 失败词面落点: %s" % _sb[:16],
               _sb.find("恢复后自动刷新") >= 0)
            ck("goal foot 失败词面落点: %s" % _ft[:16],
               _ft.find("恢复后自动刷新") >= 0)
            pg.unroute("**/api/state"); pg.unroute("**/api/specials")
            pg.evaluate("load()"); pg.wait_for_timeout(1800)
            _ft2 = pg.evaluate(
                "()=>(document.getElementById('foot')||{}).textContent||''")
            ck("goal foot 恢复自愈: %s" % _ft2[:20],
               _ft2.find("恢复后自动刷新") < 0 and _ft2.strip() != "")

            # ---- goal 轮 P2-2 矮窗 660 档行为钉：640（新档内）canvas
            #   收矮窗档（≤280），680（档外）回基础档——先落位走势
            #   视图（隐藏容器量纲全零，廿一§8）；媒体重算窗口轮询
            #   等稳定值（固定等待采样早于重算=假红）。测毕视口/视图
            #   复位。段在流程最末（统计落盘前） ----
            step("goal P2-2 矮窗 660 档")
            pg.evaluate("showMonTab('trend')"); pg.wait_for_timeout(500)
            pg.set_viewport_size({"width": 1280, "height": 640})
            _cv1 = None
            for _ in range(10):
                pg.wait_for_timeout(200)
                _cv1 = pg.evaluate(
                    "()=>{const c=document.querySelector('#chart');"
                    "return c?c.getBoundingClientRect().height:0;}")
                if 0 < _cv1 <= 285:
                    break
            ck("goal 640 带矮窗档生效 h=%s" % _cv1, 0 < _cv1 <= 285)
            pg.set_viewport_size({"width": 1280, "height": 680})
            _cv2 = None
            for _ in range(10):
                pg.wait_for_timeout(200)
                _cv2 = pg.evaluate(
                    "()=>{const c=document.querySelector('#chart');"
                    "return c?c.getBoundingClientRect().height:0;}")
                if _cv2 and _cv2 > 300:
                    break
            ck("goal 680 带基础档回位 h=%s" % _cv2, bool(_cv2 and _cv2 > 300))
            pg.set_viewport_size({"width": 1280, "height": 900})
            pg.evaluate("showMonTab('overview')"); pg.wait_for_timeout(300)

            # ---- r326 审计收口钉（A2 税前假警示豁免档 + A3 桌面国际
            #   徽标承载）：demo 夹具自带三国际航线×五渠道明细。可见性
            #   判定用 rect 真值（display:none 祖先的后代 computed 保持
            #   指定值，廿一§16 祖先链律）。段在流程最末（统计落盘前），
            #   视图/视口段内复位 ----
            step("r326 审计收口")
            pg.evaluate("switchView('mon')")
            pg.evaluate("resetFltUI()"); pg.wait_for_timeout(450)
            pg.evaluate("showMonTab('details')"); pg.wait_for_timeout(500)
            pg.evaluate("()=>{while(_tblAppend()){}}")
            _a3 = pg.evaluate(
                """()=>{
                  const tr=[...document.querySelectorAll(
                    '#ftable tbody tr[data-k]')]
                    .find(r=>r.querySelector('.tag.t-i'));
                  if(!tr)return {found:false};
                  const b=tr.querySelector('.tag.t-i');
                  const r=b.getBoundingClientRect();
                  return {found:true, w:Math.round(r.width),
                          h:Math.round(r.height)};}""")
            ck("r326 桌面带国际行「国际」紫标承载（%sx%s）"
               % (_a3.get("w"), _a3.get("h")),
               _a3.get("found") and _a3["w"] > 0 and _a3["h"] > 0)
            _a2 = pg.evaluate(
                """()=>{
                  const intlF=[...document.querySelectorAll(
                    '#ftable tbody tr[data-k]')]
                    .find(r=>r.querySelector('.tag.t-i')
                          &&r.querySelector('[data-plat="fliggy"]'));
                  const domF=[...document.querySelectorAll(
                    '#ftable tbody tr[data-k]')]
                    .find(r=>!r.querySelector('.tag.t-i')
                          &&r.querySelector('[data-plat="fliggy"]'));
                  return {intlNoPretax: intlF
                           ? !intlF.querySelector('.pretax') : null,
                          domHasPretax: domF
                           ? !!domF.querySelector('.pretax') : null};}""")
            ck("r326 飞猪国际行无「税前」假警示（intl=%s dom=%s）"
               % (_a2["intlNoPretax"], _a2["domHasPretax"]),
               _a2["intlNoPretax"] is True and _a2["domHasPretax"] is True)
            pg.evaluate("showMonTab('overview')"); pg.wait_for_timeout(200)

            # ---- r331 触屏双击缩放免疫钉：段在流程最末（统计落盘前）。
            # viewport meta 只消灭 300ms 点击延迟，不消灭双击缩放手势
            # ——coarse 下快速双触按钮/chips/明细行会整页放大，canvas
            # 双拍状态机（首拍读数、二拍确认）的第二拍尤其会被缩放
            # 手势劫持。钉锁交互家族 computed touchAction=manipulation
            # （真实仿真窗内采样——源码钉锁不住层叠胜负，廿一§1）；
            # .cp-city 动态创建且依赖 CITYX，先 loadCfg 再构建（取件
            # 在触发后，十九§12）----
            step("r331 触屏双击缩放免疫")
            pg.evaluate("switchView('mon')")
            pg.evaluate("showMonTab('trend')"); pg.wait_for_timeout(400)
            _cdp3 = pg.context.new_cdp_session(pg)
            _cdp3.send("Emulation.setTouchEmulationEnabled",
                       {"enabled": True, "maxTouchPoints": 5})
            _coarse3 = False
            for _ in range(20):
                pg.wait_for_timeout(100)
                if pg.evaluate(
                        "()=>matchMedia('(pointer:coarse)').matches"):
                    _coarse3 = True
                    break
            pg.evaluate("showMonTab('details')"); pg.wait_for_timeout(300)
            pg.evaluate("()=>{while(_tblAppend()){}}")
            pg.evaluate("loadCfg()"); pg.wait_for_timeout(800)
            pg.evaluate(
                "()=>{if(!_cpBuilt||!document.querySelector("
                "'#cpbody .cp-sec')){cityPanelBuild();_cpBuilt=true}}")
            pg.wait_for_timeout(200)
            _ta = pg.evaluate(
                """()=>{
                  const sel=['button','.hbtn','.mtab','.chip','.pill',
                             'th.srt','canvas','#ftable tbody tr[data-k]',
                             '.cp-city','#tabs span','nav span',
                             '.cnav','.uhead2','.grouplab','.rhead',
                             '.chhead','.kpi.clk','.hc','.pbar','.pvx',
                             '.dx','input.switch'];
                  const out={};
                  for(const s of sel){
                    const el=document.querySelector(s);
                    if(!el){out[s]='(absent)';continue;}
                    out[s]=getComputedStyle(el).touchAction;}
                  return out;}""")
            # r333 coarse 输入件精细化：#cpq 16px 防放大（iOS 聚焦
            # 自缩放阈值）+ glcell 输入 36px 触控地板（姊妹族
            # .srow/.fbar 38px 同律；配置容器 display:none 子树的
            # 非布局 computed 仍可取——探针实证，无需展开视图）
            _inp3 = pg.evaluate(
                """()=>{
                  const cpq=document.getElementById('cpq');
                  const gi=document.querySelector(
                    '.glcell input:not(.switch)');
                  return {fs: cpq?getComputedStyle(cpq).fontSize:null,
                          mh: gi?getComputedStyle(gi).minHeight:null};}""")
            ck("coarse #cpq 16px 防放大+glcell 36px 地板",
               _inp3["fs"] == "16px" and _inp3["mh"] == "36px")
            _cdp3.send("Emulation.setTouchEmulationEnabled",
                       {"enabled": False})
            pg.wait_for_timeout(200)
            ck("CDP coarse 翻真（触控免疫钉前置）", _coarse3)
            _ta_bad = {k: v for k, v in _ta.items() if v != "manipulation"}
            ck("coarse 下交互家族 touchAction=manipulation（违例=%s）"
               % (_ta_bad or "无"), not _ta_bad)
            pg.evaluate("showMonTab('overview')"); pg.wait_for_timeout(200)

            # ---- r339 航线卡高频重排行为钉：段在流程最末（统计落盘
            # 前）。锁五件：日期快速选写模+回显；范围选含两端；高级约
            # 束折叠默认收起+展开；只要直飞写模+收起中转价；筛选四行
            # 写模与 intl 条件渲染。全程只动客户端模型不 POST（真机
            # 只读边界），段尾 loadCfg() 拉服务端配置重建即天然自净；
            # 折叠态 localStorage 先存后还（共享全局态自净三件套）----
            step("r339 航线卡高频重排")
            pg.evaluate("switchView('cfg')"); pg.wait_for_timeout(400)
            # 前序段可能遗留搜索态（expandFolds 全开 folds）——折叠
            # 默认态断言前先归一（cfgSearchClear 单源复位+重建）
            pg.evaluate("cfgSearchClear()"); pg.wait_for_timeout(400)
            pg.evaluate("loadCfg()"); pg.wait_for_timeout(800)
            _fold0 = pg.evaluate(
                "()=>localStorage.getItem('jpcfgfold')||''")
            _rk = pg.evaluate(
                "()=>(document.querySelector('.rline[data-rk]')||{}"
                ").dataset?.rk||null")
            _has_intl = pg.evaluate(
                "()=>CFG.some(u=>(u.routes||[]).some("
                "r=>isIntlCode(r.from)||isIntlCode(r.to)))")
            ck("r339 前置：cfg 表单就绪且拿到首航线", _rk is not None)
            # ① 快速选未来7天：真实点击 → 模型 7 日期、首日=今天、片回显
            pg.evaluate("""()=>{
              const rk=document.querySelector('.rline[data-rk]').dataset.rk;
              const [i,j]=rk.split(':').map(Number);
              clearDates('d',i,j,true);   /* r346 直调绕过确认层，测试前置 */
              const chip=[...document.querySelectorAll(
                `.rline[data-rk="${rk}"] .schip`)]
                .find(c=>c.textContent==='未来7天');
              chip.click();}""")
            pg.wait_for_timeout(300)
            _q7 = pg.evaluate("""()=>{
              const t=new Date();
              const today=t.getFullYear()+'-'+
                String(t.getMonth()+1).padStart(2,'0')+'-'+
                String(t.getDate()).padStart(2,'0');
              const rk=document.querySelector('.rline[data-rk]').dataset.rk;
              const [i,j]=rk.split(':').map(Number);
              const ds=CFG[i].routes[j].dates||[];
              return {n:ds.length, first:ds[0]===today,
                      chips:document.querySelectorAll(
                        `.rline[data-rk="${rk}"] .dchip`).length};}""")
            ck("r339 快速选未来7天：模型7日期+首日今天+片回显",
               _q7["n"] == 7 and _q7["first"] and _q7["chips"] == 7)
            # ② 范围选：起止含两端（实效锚=直调 rangeDates，十八§14）
            _r3 = pg.evaluate("""()=>{
              const rk=document.querySelector('.rline[data-rk]').dataset.rk;
              const [i,j]=rk.split(':').map(Number);
              const f=new Date(Date.now()+10*864e5),
                    t=new Date(Date.now()+12*864e5);
              const fm=d=>d.getFullYear()+'-'+
                String(d.getMonth()+1).padStart(2,'0')+'-'+
                String(d.getDate()).padStart(2,'0');
              clearDates('d',i,j,true);   /* 区间=合并语义，先清空验证含两端 */
              document.getElementById('dfrom-'+i+'-'+j).value=fm(f);
              document.getElementById('dto-'+i+'-'+j).value=fm(t);
              rangeDates(i,j);
              return {n:CFG[i].routes[j].dates.length};}""")
            ck("r339 范围选含两端（3 天窗）", _r3["n"] == 3)
            # ③ 高级约束折叠：默认收起→点击展开（aria 单源）
            _fd = pg.evaluate("""()=>{
              const h=document.querySelector('.rline[data-rk] .rthead');
              const folded=h.getAttribute('aria-expanded')==='false';
              const sib=[];let n=h.nextElementSibling;
              while(n){sib.push(n);n=n.nextElementSibling;}
              const hidden=folded&&sib.every(b=>b.style.display==='none');
              h.click();
              return {folded, hidden,
                      open:h.getAttribute('aria-expanded')==='true'};}""")
            ck("r339 高级折叠默认收起且点击展开（%s）"
               % json.dumps(_fd, ensure_ascii=False),
               _fd["folded"] and _fd["hidden"] and _fd["open"])
            # ④ 只要直飞：旗标写模+中转价收起，再点恢复（在卡内取
            # .trprice——首 .sctl 是城市行，取不到价格件）
            _do = pg.evaluate("""()=>{
              const rk=document.querySelector('.rline[data-rk]').dataset.rk;
              const [i,j]=rk.split(':').map(Number);
              const card=document.querySelector(`.rline[data-rk="${rk}"]`);
              const chip=[...card.querySelectorAll('.schip')]
                .find(c=>c.textContent.indexOf('只要直飞')>=0);
              const tr=card.querySelector('.trprice');
              if(!chip||!tr)return {nullpart:!chip?'chip':'trprice'};
              const prev=tr.value;
              chip.click();
              const on={t:CFG[i].routes[j].alert_transfer,
                        f:CFG[i].routes[j].direct_only===true,
                        hid:tr.style.display==='none'};
              chip.click();
              const off={f:CFG[i].routes[j].direct_only===true,
                         show:tr.style.display==='', prev};
              return {on, off};}""")
            if "nullpart" in _do:
                ck("r339 只要直飞：取件失败 %s" % _do["nullpart"], False)
            else:
                ck("r339 只要直飞：中转阈清零+收起+恢复",
                   _do["on"]["t"] == 0 and _do["on"]["f"]
                   and _do["on"]["hid"] and not _do["off"]["f"]
                   and _do["off"]["show"])
            # ⑤ 筛选四行：intl 条件渲染 + 写模
            _f4 = pg.evaluate("""()=>{
              const rk=document.querySelector('.rline[data-rk]').dataset.rk;
              const [i,j]=rk.split(':').map(Number);
              const inp=document.querySelector(
                `.rline[data-rk="${rk}"] input[onchange*="airlines"]`);
              inp.value='MU,春秋';
              inp.dispatchEvent(new Event('change',{bubbles:true}));
              return {v:CFG[i].routes[j].airlines,
                      intlRows:document.querySelectorAll(
                        'input[onchange*="min_baggage"]').length,
                      wl:document.querySelectorAll(
                        'input[onchange*="widebody_only"]').length};}""")
            ck("r339 航司白名单写模+intl 行条件渲染",
               _f4["v"] == "MU,春秋"
               and (_f4["intlRows"] > 0) == _has_intl
               and (_f4["wl"] > 0) == _has_intl)
            # r349b 航司常用 chips：8 个快捷片必须全部落在 quick 容器内，
            # 且每片文字不被 overflow:hidden 裁掉；≥1500 单行 8 列、
            # 541–1499 两行 4 列（标签独占一行），≤540 两列四行。
            pg.evaluate("""()=>{
              try{cfgSearchClear&&cfgSearchClear()}catch(e){}
              try{cfgScopeSet&&cfgScopeSet('all')}catch(e){}
              try{cfgStatusSet&&cfgStatusSet('all')}catch(e){}
              const nav=document.querySelector('#cfgnav .cnav[data-p="users"]');
              if(nav)nav.click();
              try{OPEN_USER=0;buildForm()}catch(e){}
              const u=document.querySelector('#cfgform .uhead2');
              if(u&&u.getAttribute('aria-expanded')!=='true')toggleUser(u);
              const sec=document.querySelector('.grouplab[data-sec="C"]');
              if(sec&&sec.getAttribute('aria-expanded')!=='true')sec.click();
              const rh=document.querySelector('.rline[data-rk] .rhead');
              if(rh&&rh.getAttribute('aria-expanded')!=='true')rh.click();
              const th=document.querySelector('.rline[data-rk] .rthead');
              if(th&&th.getAttribute('aria-expanded')!=='true')th.click();
            }""")
            pg.wait_for_timeout(500)
            _q = pg.evaluate("""()=>{
              const q=document.querySelector('.rline[data-rk] .airquick');
              if(!q)return {ok:false,why:'no-airquick'};
              const qr=q.getBoundingClientRect();
              const chips=[...q.querySelectorAll('.chip')];
              const rs=chips.map(c=>c.getBoundingClientRect());
              const allIn=chips.every((c,i)=>rs[i].width>0
                &&rs[i].left>=qr.left-1&&rs[i].right<=qr.right+1);
              const noClip=chips.every(c=>c.scrollWidth<=c.clientWidth+1);
              const rows=new Set(rs.map(r=>Math.round(r.top))).size;
              const expect=innerWidth>=1500?1:(innerWidth>=541?2:4);
              return {ok:chips.length===8&&allIn&&noClip
                &&q.scrollWidth<=q.clientWidth+1
                &&(expect==null||rows===expect),
                n:chips.length,allIn,noClip,rows,expect,
                qw:Math.round(qr.width),sw:q.scrollWidth,cw:q.clientWidth};}
            """)
            ck("r349 航司常用 chips 全在容器内且不裁字 %s" % _q, _q["ok"])
            _vp_q = pg.viewport_size
            pg.set_viewport_size({"width": 390, "height": 844})
            pg.wait_for_timeout(700)
            pg.evaluate("""()=>{
              try{cfgSearchClear&&cfgSearchClear()}catch(e){}
              try{cfgScopeSet&&cfgScopeSet('all')}catch(e){}
              try{cfgStatusSet&&cfgStatusSet('all')}catch(e){}
              const nav=document.querySelector('#cfgnav .cnav[data-p="users"]');
              if(nav)nav.click();
              try{OPEN_USER=0;buildForm()}catch(e){}
              const u=document.querySelector('#cfgform .uhead2');
              if(u&&u.getAttribute('aria-expanded')!=='true')toggleUser(u);
              const sec=document.querySelector('.grouplab[data-sec="C"]');
              if(sec&&sec.getAttribute('aria-expanded')!=='true')sec.click();
              const rh=document.querySelector('.rline[data-rk] .rhead');
              if(rh&&rh.getAttribute('aria-expanded')!=='true')rh.click();
              const th=document.querySelector('.rline[data-rk] .rthead');
              if(th&&th.getAttribute('aria-expanded')!=='true')th.click();
            }""")
            pg.wait_for_timeout(500)
            _q390 = pg.evaluate("""()=>{
              const q=document.querySelector('.rline[data-rk] .airquick');
              if(!q)return {ok:false,why:'no-airquick'};
              const qr=q.getBoundingClientRect();
              const chips=[...q.querySelectorAll('.chip')];
              const rs=chips.map(c=>c.getBoundingClientRect());
              const allIn=chips.every((c,i)=>rs[i].width>0
                &&rs[i].left>=qr.left-1&&rs[i].right<=qr.right+1);
              const noClip=chips.every(c=>c.scrollWidth<=c.clientWidth+1);
              const rows=new Set(rs.map(r=>Math.round(r.top))).size;
              return {ok:chips.length===8&&allIn&&noClip
                &&q.scrollWidth<=q.clientWidth+1&&rows===4
                &&document.documentElement.scrollWidth<=innerWidth+1,
                n:chips.length,allIn,noClip,rows,docW:document.documentElement.scrollWidth};}
            """)
            ck("r349 390 航司常用 chips 不越界 %s" % _q390, _q390["ok"])
            pg.set_viewport_size(_vp_q)
            pg.wait_for_timeout(700)
            # ⑥ 往返多返程日：开→返程行在场→去程起7天→ret_dates 7
            # 且首日=最早出发日（能力与去程一致）。toggleRT/quickRet
            # 各自 buildForm 重建 DOM——每次点击后重新取件（ detachment
            # 律：重建后旧引用查不到新行）
            pg.evaluate("""()=>{
              const card=document.querySelector('.rline[data-rk]');
              const chip=[...card.querySelectorAll('.schip')]
                .find(c=>c.textContent.indexOf('往返')>=0);
              chip.click();}""")
            pg.wait_for_timeout(300)
            _rt = pg.evaluate("""()=>{
              const rk=document.querySelector('.rline[data-rk]').dataset.rk;
              const [i,j]=rk.split(':').map(Number);
              const row=document.getElementById('rdchips-'+i+'-'+j);
              const rowOn=!!row;
              const card=document.querySelector(`.rline[data-rk="${rk}"]`);
              const q=[...card.querySelectorAll('.schip')]
                .find(c=>c.textContent==='去程起7天');
              if(q)q.click();
              const ds=CFG[i].routes[j].ret_dates||[];
              const anchor=(CFG[i].routes[j].dates||[])
                .slice().sort()[0];
              const rr=document.querySelector(
                `.rline[data-rk="${rk}"] .rrt`);
              return {rowOn, n:ds.length, first:ds[0]===anchor,
                      badge:rr?rr.textContent:''};}""")
            ck("r339 往返开合+返程快速选7天（锚最早出发日）+badge×7",
               _rt["rowOn"] and _rt["n"] == 7 and _rt["first"]
               and '×7' in _rt["badge"])
            # ⑦ Bark 通道卡：写模在场（enabled/key/server 三件）
            _bk = pg.evaluate("""()=>{
              const u=0;
              setBark(u,'enabled',true);
              setBark(u,'key','bk_test');
              /* 写入即时值捕获（b 是引用——复位批后再读=恒假自伤） */
              const seen=CFG[u].notifier.bark.key==='bk_test';
              const card=!!document.querySelector('.chcard[data-ch="bark"]');
              const btn=!!document.querySelector(
                'button[onclick*="testBark"]');
              setBark(u,'enabled',false);setBark(u,'key','');
              return {seen, cleared:CFG[u].notifier.bark.enabled===false,
                      card, btn};}""")
            ck("r339 Bark 通道卡+写模+测试钮在场",
               _bk["card"] and _bk["btn"] and _bk["seen"]
               and _bk["cleared"])
            # 段内自净：折叠态还原 + 服务端配置重建表单
            pg.evaluate("""f0=>{
              if(f0)localStorage.setItem('jpcfgfold',f0);
              else localStorage.removeItem('jpcfgfold');}""", _fold0)
            pg.evaluate("loadCfg()"); pg.wait_for_timeout(600)
            pg.evaluate("switchView('mon')"); pg.wait_for_timeout(200)

            # ---- r341 置尾钉：航线卡三新门 + 全局页绝对路径展示 ----
            pg.evaluate("""()=>{switchView('mon');
              const card=document.querySelector('.rline[data-rk]');
              if(card){const adv=[...card.querySelectorAll('button,span.chip')]
                .find(b=>/高级|折叠|更多/.test(b.textContent));
                if(adv)adv.click();}}""")
            pg.wait_for_timeout(400)
            _g341 = pg.evaluate("""()=>{const rows=[
              ...document.querySelectorAll('.rline .srow')];
              let priceIn=false,crossChk=false,arrWin=false,arrChip=false;
              rows.forEach(r=>{const t=r.innerText||'';
                if(t.indexOf('价格上限')>=0&&r.querySelector('input[type=number]'))priceIn=true;
                if(t.indexOf('排除跨天')>=0&&r.querySelector('input[type=checkbox]'))crossChk=true;
                if(t.indexOf('到达时段窗口')>=0){arrWin=true;
                  arrChip=[...r.querySelectorAll('.schip')].some(c=>c.textContent.indexOf('凌晨')>=0);}});
              const bang=[...document.querySelectorAll('.rline')]
                .some(c=>c.innerHTML.indexOf('!9C')>=0);
              return {priceIn,crossChk,arrWin,arrChip,bang};}""")
            ck("r341 航线卡三新门在场（价格上限/排除跨天/到达窗+快捷挡）",
               _g341["priceIn"] and _g341["crossChk"] and _g341["arrWin"]
               and _g341["arrChip"])
            ck("r341 航司白名单 ! 排除语法提示", _g341["bang"])
            pg.evaluate("""()=>{switchView('cfg');
              const nav=document.querySelector('.cnav[data-p=globals]');
              if(nav)nav.click();}""")
            pg.wait_for_timeout(500)
            _a341 = pg.evaluate("""()=>{const abs=[...document.querySelectorAll('.glabs')]
                .map(e=>e.textContent);
              return {n:abs.length,
                absLike:abs.filter(t=>t.indexOf('绝对路径：')>=0).length,
                bdirBtn:!!document.querySelector('[data-which="bdir"]')};}""")
            ck("r341 启动级四件绝对路径展示+bdir 📂 钮",
               _a341["n"] >= 3 and _a341["absLike"] >= 3 and _a341["bdirBtn"])
            pg.evaluate("""()=>{const nav=document.querySelector('.cnav[data-p=users]');
              if(nav)nav.click();}""")
            pg.wait_for_timeout(300)

            # ---- r342 配置工作台：日期双通道/航司自动完成/智能预设/
            # 存储元数据/重启中心；明细筛选摘要与智能预设 ----
            step("r342 配置工作台")
            pg.evaluate("""()=>{switchView('cfg');showCfgPanel('users',true);
              const rl=document.querySelector('.rline[data-rk="0:0"]');
              const h=rl&&rl.querySelector('.rhead');
              if(h&&h.getAttribute('aria-expanded')==='false')h.click();
              const rt=rl&&rl.querySelector('.rthead');
              if(rt&&rt.getAttribute('aria-expanded')==='false')rt.click();}""")
            pg.wait_for_timeout(500)
            _d342 = pg.evaluate("""()=>{
              const rl=document.querySelector('.rline[data-rk="0:0"]');
              const tabs=[...rl.querySelectorAll('.dctab')];
              const pans=[...rl.querySelectorAll('.dpanel')];
              const vis=pans.filter(p=>!p.hasAttribute('hidden'));
              const rng=!!rl.querySelector('#dfrom-0-0'),
                    one=!!rl.querySelector('#dadd-0-0');
              rl.querySelector('.dctab[data-dm="single"]').click();
              const vis2=[...rl.querySelectorAll('.dpanel')].filter(p=>!p.hasAttribute('hidden'));
              const mode2=rl.querySelector('.dctab.on')?.dataset.dm;
              rl.querySelector('.dctab[data-dm="range"]').click();
              return {tabs:tabs.length,vis:vis.length,vis2:vis2.length,mode2,rng,one};}""")
            ck("r345 日期模式条：两入口常显、编辑器一次只开一个",
               _d342["tabs"] == 2 and _d342["vis"] == 1 and _d342["vis2"] == 1
               and _d342["mode2"] == "single" and _d342["rng"] and _d342["one"])
            _dd342 = pg.evaluate("""()=>{
              const f=document.getElementById('dfrom-0-0'),
                    t=document.getElementById('dto-0-0'),
                    a=document.getElementById('dadd-0-0');
              f.value='2031-05-06';t.value='2031-05-08';
              setDateMode('d',0,0,'single');
              a.value='2031-06-03';addDate(0,0);
              const r=CFG[0].routes[0];
              return {keep:f.value,t2:t.value,last:r.dates[r.dates.length-1]};}""")
            ck("r345 切模式后草稿保留 + 显式加入（%s→%s）"
               % (_dd342["keep"], _dd342["t2"]),
               _dd342["keep"] == "2031-05-06"
               and _dd342["t2"] == "2031-05-08"
               and _dd342["last"] == "2031-06-03")
            pg.evaluate("""()=>{const rl=document.querySelector('.rline[data-rk="0:0"]');
              const rt=rl.querySelector('.rthead');
              if(rt.getAttribute('aria-expanded')==='false')rt.click();
              const inp=rl.querySelector('.airfield input');
              inp.value='东';inp.dispatchEvent(new Event('input',{bubbles:true}));}""")
            pg.wait_for_timeout(250)
            _as342 = pg.evaluate("""()=>{
              const box=document.getElementById('airsug-0-0');
              const n=box?box.querySelectorAll('.asg').length:0;
              if(n)box.querySelector('.asg').click();
              const inp=document.querySelector('.rline[data-rk="0:0"] .airfield input');
              const ch=document.getElementById('airchips-0-0');
              return {n, val:inp.value, chip:ch?ch.innerText:''};}""")
            ck("r342 航司自动完成（候选%d→结果%s/chip=%s）"
               % (_as342["n"], _as342["val"], _as342["chip"][:12]),
               _as342["n"] >= 1 and _as342["val"] == "MU"
               and "MU" in _as342["chip"])
            pg.evaluate("""()=>{const inp=document.querySelector(
                '.rline[data-rk="0:0"] .airfield input');
              inp.value='东航,!9C';inp.dispatchEvent(new Event('input',{bubbles:true}));
              inp.dispatchEvent(new Event('change',{bubbles:true}));}""")
            pg.wait_for_timeout(200)
            _ap342 = pg.evaluate("""()=>{
              const ch=document.getElementById('airchips-0-0');
              const pv=document.getElementById('airpv-0-0');
              return {txt:ch?ch.innerText:'',pv:pv?getComputedStyle(pv).display:''};}""")
            ck("r342 航司全识别→chips 可读且不再重复解析行",
               "东航" in _ap342["txt"] and "9C" in _ap342["txt"]
               and _ap342["pv"] == "none")
            pg.evaluate("loadCfg()"); pg.wait_for_timeout(700)
            pg.evaluate("""()=>{const rl=document.querySelector('.rline[data-rk="0:0"]');
              const h=rl.querySelector('.rhead');
              if(h.getAttribute('aria-expanded')==='false')h.click();
              const rt=rl.querySelector('.rthead');
              if(rt.getAttribute('aria-expanded')==='false')rt.click();
              rl.querySelector('.rfpresets .chip').click();}""")
            pg.wait_for_timeout(400)
            _ps342 = pg.evaluate("""()=>{const r=CFG[0].routes[0];
              const b=document.querySelector('.rline[data-rk="0:0"] .rfltbadge');
              return {d:!!r.direct_only,l:!!r.no_lcc,s:!!r.exclude_stop,
                      h:!!r.exclude_share,badge:b?b.textContent:''};}""")
            ck("r342 智能预设「省心直飞」四项写模+badge",
               _ps342["d"] and _ps342["l"] and _ps342["s"] and _ps342["h"]
               and "筛" in _ps342["badge"])
            pg.evaluate("loadCfg()"); pg.wait_for_timeout(700)
            # r343：渠道改单列手风琴；新增邮箱自动展开且卡头即可删除
            pg.locator('#cfgform button[onclick="addEm(0)"]').click()
            pg.wait_for_timeout(500)
            _ch343 = pg.evaluate("""()=>{const g=document.querySelector('#cfgform .chgrid');
              const c=document.querySelector('.chcard[data-ch="email0"]');
              const cs=g?getComputedStyle(g):null;
              const order=g?[...g.querySelectorAll('.chcard')]
                .map(x=>x.dataset.ch):[];
              return {dir:cs?cs.display+'/'+cs.flexDirection:'',
                      open:c?c.querySelector('.chhead').getAttribute('aria-expanded'):'',
                      del:c?!!c.querySelector('.chdel'):false,
                      imgFirst:order.indexOf('imghost')>=0
                        &&order.indexOf('imghost')<order.indexOf('email0'),
                      order};}""")
            ck("r343 渠道单列手风琴+邮箱末位+自动展开+卡头删除（%s）"
               % _ch343["dir"], _ch343["dir"] == "flex/column"
               and _ch343["open"] == "true" and _ch343["del"]
               and _ch343["imgFirst"])
            pg.locator('.chcard[data-ch="email0"] .chdel').click()
            pg.wait_for_timeout(250)
            _cd343 = pg.evaluate("""()=>({show:document.getElementById('confirmMask')
              .classList.contains('on'),title:document.getElementById('cmTitle')
              .textContent,n:(CFG[0].notifier.emails||[]).length})""")
            ck("r343 邮箱删除确认层（%s）" % _cd343["title"],
               _cd343["show"] and _cd343["title"] == "删除邮箱通道？"
               and _cd343["n"] == 1)
            pg.click("#cmCancel"); pg.wait_for_timeout(200)
            ck("r343 邮箱删除可取消且不误删",
               pg.evaluate("(CFG[0].notifier.emails||[]).length") == 1)
            pg.evaluate("loadCfg()"); pg.wait_for_timeout(700)
            pg.evaluate("""()=>{const nav=document.querySelector('.cnav[data-p=globals]');
              if(nav)nav.click();}""")
            pg.wait_for_timeout(500)
            _pm342 = pg.evaluate("""()=>{const cards=[...document.querySelectorAll('.pathcard')];
              const abs=[...document.querySelectorAll('.pathcard .glabs')]
                .map(e=>e.textContent);
              return {n:cards.length,glabs:abs.length,
                abs:abs.filter(t=>t.indexOf('绝对路径：')>=0).length,
                bdir:!!document.querySelector('[data-which="bdir"]')};}""")
            ck("r342 存储四卡：绝对路径/体积/打开动作齐备",
               _pm342["n"] == 4 and _pm342["glabs"] >= 4
               and _pm342["abs"] >= 4 and _pm342["bdir"])
            # r349c 配置文件卡：三个路径动作必须在同一顶部动作组，且不得
            # 与 PID/监听/命令等元信息文本相交；元信息自身不得横向裁字。
            _po = pg.evaluate("""()=>{
              const h=document.querySelector('.storehead');
              if(!h)return {ok:false,why:'no-storehead'};
              const meta=h.querySelector('.sh-meta');
              const acts=[...h.querySelectorAll('button,.chip[role=button]')];
              const mr=meta?meta.getBoundingClientRect():null;
              const overlap=acts.some(a=>{const r=a.getBoundingClientRect();
                return mr&&r.left<mr.right-1&&r.right>mr.left+1
                  &&r.top<mr.bottom-1&&r.bottom>mr.top+1;});
              const hr=h.getBoundingClientRect();
              const inHead=acts.every(a=>{const r=a.getBoundingClientRect();
                return r.left>=hr.left-1&&r.right<=hr.right+1;});
              return {ok:!!meta&&acts.length===3&&!overlap&&inHead
                &&meta.scrollWidth<=meta.clientWidth+1,
                n:acts.length,overlap,inHead,
                metaClip:!!meta&&meta.scrollWidth>meta.clientWidth+1};}
            """)
            ck("r349 配置文件元信息与动作不重叠 %s" % _po, _po["ok"])
            _vp_p = pg.viewport_size
            pg.set_viewport_size({"width": 671, "height": 844})
            pg.wait_for_timeout(700)
            _p671 = pg.evaluate("""()=>{const h=document.querySelector('.storehead');
              const m=h&&h.querySelector('.sh-meta');
              const bs=h?[...h.querySelectorAll('.sh-act')]:[];
              if(!h||!m||bs.length!==3)return {ok:false,n:bs.length};
              const rs=bs.map(b=>b.getBoundingClientRect());
              const mr=m.getBoundingClientRect();
              const sameRow=new Set(rs.map(r=>Math.round(r.top))).size===1;
              const equal=Math.max(...rs.map(r=>r.width))-Math.min(...rs.map(r=>r.width))<=2;
              const noOverlap=rs.every(r=>r.left>=mr.left-1&&r.right<=mr.right+1
                &&r.bottom<=mr.top+1);
              const inHead=rs.every(r=>r.left>=h.getBoundingClientRect().left-1
                &&r.right<=h.getBoundingClientRect().right+1);
              return {ok:sameRow&&equal&&noOverlap&&inHead
                &&m.scrollWidth<=m.clientWidth+1,
                sameRow,equal,noOverlap,inHead};}
            """)
            ck("r349 671 配置文件动作三列等宽 %s" % _p671, _p671["ok"])
            pg.set_viewport_size(_vp_p)
            pg.wait_for_timeout(700)
            _pc342 = pg.evaluate("""async()=>{
              const r=await fetch('/api/path-check?which=ud&path=user_data_probe');
              const j=await r.json();
              return {ok:j.ok,parent:j.parent_exists,mode:j.migration_mode,
                      abs:j.abs};}""")
            ck("r342 路径预检（父目录存在/迁移模式）",
               _pc342["ok"] and _pc342["parent"]
               and _pc342["mode"] == "move")
            pg.evaluate("""()=>{const i=document.getElementById('glbUdd');
              i.value='user_data_probe';
              i.dispatchEvent(new Event('change',{bubbles:true}));}""")
            pg.wait_for_timeout(650)
            _rh342 = pg.evaluate("""()=>{
              const h=document.getElementById('restartHint');
              const c=document.getElementById('cfgChromeRestart');
              openRestartCenter();
              return {hint:h.style.display!=='none',
                      diff:document.querySelectorAll('#rcBody .rcdiff').length,
                      chrome:c?c.textContent:''};}""")
            ck("r342 改启动级路径→弱提示+重启中心差量可读",
               _rh342["hint"] and _rh342["diff"] >= 1
               and "1" in _rh342["chrome"])
            pg.evaluate("closeRestartCenter();loadCfg()"); pg.wait_for_timeout(700)
            pg.evaluate("""()=>{switchView('mon');showMonTab('details');}""")
            pg.wait_for_timeout(500)
            pg.evaluate("applyFltPreset('direct')")
            pg.wait_for_timeout(400)
            _df342 = pg.evaluate("""()=>{const s=document.getElementById('fltsum');
              return {sum:s?s.innerText:'',n:document.querySelectorAll(
                '#fltpresets .fltpreset.on').length};}""")
            ck("r342 明细智能预设+生效摘要",
               "直飞" in _df342["sum"] and _df342["n"] >= 1)
            pg.evaluate("resetFltUI()"); pg.wait_for_timeout(350)
            ck("r342 明细清除全部→摘要收空",
               pg.evaluate("!document.getElementById('fltsum').innerText.trim()"))
            pg.evaluate("showMonTab('overview')"); pg.wait_for_timeout(250)

            # ---- r340 生产实时检索页 ----
            pg.evaluate("switchView('search')")
            pg.wait_for_timeout(800)
            _pr = pg.evaluate("""()=>({
              f:!!document.getElementById('srxFrom'),t:!!document.getElementById('srxTo'),
              d:!!document.getElementById('srxDate'),go:!!document.getElementById('srxGo'),
              chips:document.querySelectorAll('#srxPlatPick input').length})""")
            ck("r340c 主动探针表单完整", _pr["f"] and _pr["t"] and _pr["d"] and _pr["go"] and _pr["chips"] == 5)
            _srx = pg.evaluate("""()=>({
              view:getComputedStyle(document.getElementById('searchview')).display,
              rows:document.querySelectorAll('#srxRows .srx-row').length,
              mch:document.querySelectorAll('#srxMirror [data-mch]').length,
              mrows:document.querySelectorAll('#srxMirror .srx-mrow').length,
              nav:document.getElementById('navSearch').classList.contains('on')})""")
            ck("r340b 解析列表+五渠道原页镜像",
               _srx["view"] == "block" and _srx["rows"] > 0
               and _srx["mch"] == 5 and _srx["mrows"] > 0 and _srx["nav"])
            # r353 官方品牌图标层：渠道方形 App 图标 / 航司圆形图标；
            # 到达 +1 徽标不得改变文本基线。
            _bic = pg.evaluate("""()=>{
              const rows=[...document.querySelectorAll('#srxRows .srx-row')];
              const txtTop=el=>{const r=document.createRange();
                r.selectNodeContents(el.childNodes[0]);
                return r.getBoundingClientRect().top;};
              const offs=rows.map(row=>{
                const b=row.querySelectorAll('.srx-times b');
                return b.length<2?0:Math.abs(txtTop(b[0])-txtTop(b[1]));});
              const imgs=[...document.querySelectorAll(
                '#srxRows .srx-plat img.bic-ota,#srxRows .srx-airline img.bic-air')];
              const xd=document.querySelector('#srxRows .xday');
              return {chan:document.querySelectorAll(
                        '#srxRows .srx-plat img.bic-ota').length,
                air:document.querySelectorAll(
                        '#srxRows .srx-airline img.bic-air').length,
                bad:imgs.filter(i=>!i.complete||!i.naturalWidth).length,
                mtab:document.querySelectorAll(
                        '#srxMirror .srx-mtab img.bic-ota').length,
                xdays:document.querySelectorAll('#srxRows .xday').length,
                xinside:xd?!!xd.closest('.arr'):false,
                maxOff:offs.length?Math.max(...offs):0};}""")
            ck("r353 渠道方形/航司圆形官方图标",
               _bic["chan"] > 0 and _bic["air"] > 0
               and _bic["bad"] == 0 and _bic["mtab"] == 5)
            ck("r353 起降时刻基线零漂移",
               _bic["maxOff"] <= 0.6
               and (_bic["xdays"] == 0 or not _bic["xinside"]))
            # r349：直接打开首条非日历真实行——全局「解析详情」跟随
            # 选中行，日历薄行无 raw 时会让字段→raw 高亮用例假红。
            # 先闭合可能驻留的详情抽屉，并给 raw 拉取留足并发余量。
            pg.evaluate("""()=>{const d=document.getElementById('srxDetail');
              const c=d&&d.querySelector('[data-srxclose]');
              if(c&&d.classList.contains('open'))c.click();}""")
            pg.wait_for_timeout(250)
            pg.evaluate("""()=>{const b=document.querySelector(
              '#srxRows .srx-row:not(.cal) [data-openbtn]');if(b)b.click();}""")
            pg.wait_for_timeout(1500)
            _srxd = pg.evaluate("""()=>({
              open:document.getElementById('srxDetail').classList.contains('open'),
              fields:document.querySelectorAll('#srxDetail .srx-f').length,
              raw:document.querySelectorAll('#srxRawBox .rk').length,
              tabs:document.querySelectorAll('#srxDetail .srx-dtab').length})""")
            # demo 的 /api/state 行是合成行号，/api/probe/raw 按真实 DB 行
            # 回放会返回 "row not found"——这是 demo 边界，不是生产缺陷；
            # 生产 raw 由 docs/search_live_gate.py 对 8765 真库验证。
            _rawtxt = pg.locator("#srxRawWrap").inner_text() if pg.locator("#srxRawWrap").count() else ""
            ck("r340b 三重对齐抽屉+原始行",
               _srxd["open"] and _srxd["fields"] >= 14
               and _srxd["tabs"] >= 5
               and (_srxd["raw"] > 0 or "原始行回放失败" in _rawtxt
                    or "无当轮 raw" in _rawtxt))
            _bicd = pg.evaluate("""()=>({
              air:document.querySelectorAll(
                '#srxDetail .srx-dtitle img.bic-air').length,
              ota:document.querySelectorAll(
                '#srxDetail .srx-dtitle img.bic-ota').length,
              bad:[...document.querySelectorAll('#srxDetail img.bic')]
                .filter(i=>!i.complete||!i.naturalWidth).length})""")
            ck("r353 详情头渠道/航司双语义",
               _bicd["air"] == 1 and _bicd["ota"] == 1
               and _bicd["bad"] == 0)
            # 字段聚焦是纯前端行为：demo 合成行注入一条 raw，验证点击
            # 字段必须高亮被点字段 + 对应 raw 键（生产真 raw 另有 live gate）
            pg.evaluate("""()=>{const f=srxFindSel();if(!f)return;
              const k=srxRawKey(f);SRX_RAW[k]={ok:true,raw:{
                price:f.price,code:f.code,depTime:f.depTime,arrTime:f.arrTime,
                name:f.name,transCity:f.trans},row:{platform:f.platKey}};
              srxRenderDetail(true);}""")
            pg.wait_for_timeout(250)
            pg.evaluate("""()=>{const f=document.querySelector(
              '#srxDetail .srx-f[data-rk*="price"]');if(f)f.click();}""")
            pg.wait_for_timeout(250)
            try:
                pg.wait_for_function(
                    "()=>document.querySelectorAll('#srxRawBox .hit').length===1",
                    timeout=5000)
            except Exception:
                pass
            ck("r340b 字段聚焦 raw 键高亮",
               pg.evaluate("document.querySelectorAll('#srxRawBox .hit').length") == 1)
            pg.evaluate("document.querySelector('#srxDetail [data-srxclose]').click()")
            pg.wait_for_timeout(200)
            pg.click('.srx-hero-act button:has-text("五平台校准册")'); pg.wait_for_timeout(400)
            _srxg = pg.evaluate("""()=>({
              open:document.getElementById('srxGallery').classList.contains('open'),
              rails:document.querySelectorAll('#srxGallery [data-galch]').length,
              views:document.querySelectorAll('#srxGallery [data-galview]').length})""")
            ck("r340b 五平台校准册四视图", _srxg["open"] and _srxg["rails"] == 5 and _srxg["views"] == 4)
            pg.evaluate("srxCloseGallery()"); pg.wait_for_timeout(200)
            pg.evaluate("""()=>{const d=document.querySelectorAll(
              '#srxDates [data-date]');if(d.length>1)d[1].click();}""")
            pg.wait_for_timeout(350)
            ck("r340 日期筛选后仍有真实行",
               pg.evaluate("document.querySelectorAll('#srxRows .srx-row').length") > 0)
            pg.evaluate("switchView('mon');showMonTab('overview')")
            pg.wait_for_timeout(300)

            # ===== r354 UI 质量回归门（按缺陷出现的视口钉死） =====
            # 1) 分区编号在单页内唯一（旧 04/04、05/05 重复）
            _dupn = []
            for _tab in ["overview", "trend", "watch", "details", "health"]:
                pg.evaluate("showMonTab('%s')" % _tab)
                pg.wait_for_timeout(250)
                _nos = pg.evaluate("""()=>[...document.querySelectorAll(
                  '#monview [role=tabpanel]')].filter(p=>p.offsetParent!==null)
                  .flatMap(p=>[...p.querySelectorAll('.seclab .no')]
                  .map(x=>x.textContent.trim()))""")
                if len(_nos) != len(set(_nos)):
                    _dupn.append((_tab, _nos))
            ck("r354 分区编号单页唯一", not _dupn, str(_dupn[:2]))
            # 2) 关注台无 <10px 文字（旧 8px 标签）
            pg.evaluate("showMonTab('watch')")
            pg.wait_for_timeout(400)
            _tiny = pg.evaluate("""()=>[...document.querySelectorAll(
              '#montab-watch *')].filter(e=>{const s=getComputedStyle(e);
              return e.children.length===0&&e.textContent.trim()
                &&parseFloat(s.fontSize)<10}).length""")
            ck("r354 关注台无 <10px 文字", _tiny == 0, str(_tiny))
            # 3) 总览迷你走势不再画 7px SVG 文本（标签下沉 DOM 图例）
            pg.evaluate("showMonTab('overview')")
            pg.wait_for_timeout(300)
            ck("r354 迷你走势无 SVG 文本",
               pg.evaluate(
                   "document.querySelectorAll('#monWatchList svg text').length") == 0)
            # 4) 明细每行都有走势入口（单航线×单日期也不再消失）
            pg.evaluate("showMonTab('details')")
            pg.wait_for_timeout(400)
            ck("r354 明细行行有走势入口",
               pg.evaluate(
                   "document.querySelectorAll('#ftable tbody tr .tj').length") > 0)
            ck("r354 时长统一 X时YY分",
               pg.evaluate(
                   "()=>[durTxt('10小时45分钟'),durTxt('11时05分钟'),"
                   "durTxt('25h40m')].join('|')") ==
               "10时45分|11时05分|25时40分")
            # 5) 1280×900 首屏露出解析列表表头（旧 grid 顶到 899px）
            pg.set_viewport_size({"width": 1280, "height": 900})
            pg.evaluate("switchView('search')")
            pg.wait_for_timeout(700)
            _gt = pg.evaluate("""()=>{const e=document.querySelector(
              '#srxGrid');return e?e.getBoundingClientRect().top:9999}""")
            ck("r354 1280×900 首屏见列表", _gt < 880, "%.0f" % _gt)
            # 6) ≤1100 吸顶概览/筛选条与视图 tab 不重叠
            pg.set_viewport_size({"width": 1024, "height": 768})
            pg.evaluate("window.scrollTo(0,900)")
            pg.wait_for_timeout(500)
            _ov = pg.evaluate("""()=>{const a=document.querySelector(
              '#srxMobilebar').getBoundingClientRect(),
              b=document.querySelector('.srx-mtabs').getBoundingClientRect();
              return Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)}""")
            ck("r354 移动吸顶条不重叠", _ov <= 4, "%.1f" % _ov)
            # 7) 1683×820 短屏桌面不再误入移动模式（价带/五源/KPI 可见）
            pg.set_viewport_size({"width": 1683, "height": 820})
            pg.wait_for_timeout(500)
            ck("r354 短屏桌面保留证据面",
               pg.evaluate("""()=>getComputedStyle(
                 document.querySelector('#srxBand')).display!=='none'
                 &&getComputedStyle(document.querySelector(
                   '#srxMobilebar')).display==='none'"""))
            # 8) 390 弹层左右各 12px，页面无横溢
            pg.set_viewport_size({"width": 390, "height": 844})
            pg.evaluate("srxOpenHealth()")
            pg.wait_for_timeout(400)
            _mr = pg.evaluate("""()=>{const e=document.querySelector(
              '#srxModal');const r=e.getBoundingClientRect();
              return {x:r.x,right:r.right,sw:document.documentElement.scrollWidth,
                cw:document.documentElement.clientWidth}}""")
            ck("r354 390 弹层贴边 12px 且无横溢",
               abs(_mr["x"] - 12) <= 1 and abs(_mr["right"] - (_mr["cw"] - 12)) <= 1
               and _mr["sw"] <= _mr["cw"] + 1, str(_mr))
            pg.evaluate("srxCloseModal()")
            # 9) 城市面板底部 >=8px 且锁定背景滚动
            pg.evaluate("""async()=>{await srxEnsureCityData();
              document.querySelector('#srxProbe').classList.add('open');
              srxOpenCityPanel('srxFrom')}""")
            pg.wait_for_timeout(500)
            _cp = pg.evaluate("""()=>({gap:window.innerHeight-
              document.querySelector('#citypanel').getBoundingClientRect().bottom,
              ov:getComputedStyle(document.body).overflow})""")
            ck("r354 城市面板底距/滚动锁",
               _cp["gap"] >= 8 and _cp["ov"] == "hidden", str(_cp))
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(200)
            # 10) 移动筛选 Esc 可收起 + 两面板互斥
            pg.evaluate("srxToggleMobile('filters')")
            pg.wait_for_timeout(150)
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(200)
            ck("r354 移动筛选 Esc 收起",
               pg.evaluate("""()=>!document.querySelector('#searchview')
                 .classList.contains('show-filters')"""))
            # 11) 重启中心焦点圈闭 + 关闭归还触发点
            pg.set_viewport_size({"width": 1512, "height": 950})
            pg.evaluate("switchView('cfg')")
            pg.wait_for_timeout(400)
            pg.evaluate("""()=>{const t=document.querySelector(
              '#cfgChromeRestart');t.focus();openRestartCenter()}""")
            pg.wait_for_timeout(300)
            _trap = True
            for _ in range(12):
                pg.keyboard.press("Tab")
                if not pg.evaluate("""()=>document.querySelector(
                  '#restartCenter').contains(document.activeElement)"""):
                    _trap = False
                    break
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(200)
            _ret = pg.evaluate("""()=>document.activeElement===
              document.querySelector('#cfgChromeRestart')""")
            ck("r354 重启中心焦点圈闭/归还", _trap and _ret,
               "trap=%s ret=%s" % (_trap, _ret))
            # 12) 航班监控表单有取消且底栏吸底可达
            pg.evaluate("switchView('cfg');showCfgPanel('users');"
                        "if(OPEN_USER<0)document.querySelector('.uhead2').click()")
            pg.wait_for_timeout(600)
            pg.evaluate("cfgWatchAddOpen()")
            pg.wait_for_timeout(400)
            _cw = pg.evaluate("""()=>{const c=document.querySelector(
              '#cwCancel'),f=document.querySelector('.cwf-foot'),
              s=document.querySelector('.cwf-switches');
              return {cancel:!!c&&c.offsetParent!==null,
                sticky:f?getComputedStyle(f).position:'',
                overlap:!!(f&&s)&&f.getBoundingClientRect().top<s.getBoundingClientRect().bottom-1}}""")
            # v1.5.274：吸底页脚在长表单滚动中持续盖字段，改为表单尾部
            # 常驻段；门禁从「sticky」反转为「static 且不压开关行」
            ck("r354 监控表单取消/页脚不吸底",
               _cw["cancel"] and _cw["sticky"] == "static"
               and not _cw["overlap"], str(_cw))
            pg.evaluate("cfgWatchReset()")
            pg.wait_for_timeout(200)
            pg.evaluate("switchView('mon');showMonTab('overview')")
            pg.wait_for_timeout(300)

            # ===== r355 UI 语义/布局回归门 =====
            pg.set_viewport_size({"width": 1360, "height": 900})
            pg.evaluate("switchView('search')")
            pg.wait_for_timeout(900)
            pg.evaluate("""()=>{window.scrollTo(0,0);
              const p=document.querySelector('#srxProbe');
              if(p)p.classList.remove('open');
              document.querySelectorAll('#searchview details[open]')
                .forEach(d=>d.open=false);
              const c=document.querySelector('#srxContext');
              if(c&&!c.classList.contains('ctx-collapsed'))
                document.querySelector('#srxFilterBtn').click()}""")
            pg.wait_for_timeout(300)
            _fs = pg.evaluate("""()=>{const r=document.querySelector(
              '#srxRows .srx-row');const c=document.querySelector('#srxContext');
              const f=r?r.getBoundingClientRect():null;
              const R=s=>{const e=document.querySelector(s);if(!e)return null;
                const q=e.getBoundingClientRect();return {h:+q.height.toFixed(1),
                  y:+q.y.toFixed(1),disp:getComputedStyle(e).display}};
              return {bottom:f?f.bottom:9999,ih:window.innerHeight,
                collapsed:c.classList.contains('ctx-collapsed'),
                chips:document.querySelectorAll('#srxCapbar .capchip').length,
                cap:document.querySelector('#srxCapbar').innerText,
                filt:document.querySelector('#srxFilterBtn').innerText,
                probe:R('#srxProbe'),brief:R('#srxBrief'),sp:R('#srxSp'),
                restore:R('#srxRestoreNote'),task:R('#srxTaskPanel'),
                blocks:[...document.querySelectorAll('#searchview>*')]
                  .map(e=>({id:e.id,cls:String(e.className).slice(0,40),
                    h:+e.getBoundingClientRect().height.toFixed(1),
                    disp:getComputedStyle(e).display}))
                  .filter(x=>x.h>0&&x.disp!=='none')}}""")
            ck("r355 1360 首屏完整列表行", _fs["bottom"] <= _fs["ih"] + 1, str(_fs))
            ck("r355 筛选默认折叠+入口可见",
               _fs["collapsed"] and "筛选" in _fs["filt"], str(_fs))
            ck("r355 国际能力条五渠道语义",
               _fs["chips"] == 0 or ("国际数据能力" in _fs["cap"]
               and _fs["chips"] >= 5), str(_fs))
            pg.click("#srxFilterBtn")
            pg.wait_for_timeout(250)
            _exp = pg.evaluate("""()=>!document.querySelector('#srxContext')
              .classList.contains('ctx-collapsed')""")
            pg.click("#srxFilterBtn")
            pg.wait_for_timeout(200)
            ck("r355 筛选展开/收起", _exp, "")
            pg.evaluate("""()=>{const p=document.querySelector('#srxProbe');
              if(p)p.classList.add('open')}""")
            pg.wait_for_timeout(300)
            _ic = pg.evaluate("""()=>{const b=document.querySelector(
              '#searchview .srx-citychev');const s=b&&b.querySelector('svg');
              if(!b||!s)return {skip:true};
              const br=b.getBoundingClientRect(),sr=s.getBoundingClientRect();
              return {bw:br.width,bh:br.height,sw:sr.width,sh:sr.height,
                      pad:getComputedStyle(b).padding}}""")
            ck("r355 探针城市箭头可见", _ic.get("skip")
               or (_ic["sw"] >= 10 and _ic["sh"] >= 10 and _ic["bw"] >= 24),
               str(_ic))
            pg.evaluate("""()=>{const p=document.querySelector('#srxProbe');
              if(p)p.classList.remove('open')}""")
            pg.wait_for_timeout(200)
            _lk = pg.evaluate("""()=>{const s=document.querySelector(
              '.srx-src[data-src]');const a=s&&s.querySelector('a[data-openlink]');
              if(!a)return {skip:true};window.open=()=>null;
              const b=s.getAttribute('aria-pressed');a.click();
              return {b,after:s.getAttribute('aria-pressed')}}""")
            ck("r355 渠道原页链接不劫持筛选",
               _lk.get("skip") or _lk["b"] == _lk["after"], str(_lk))
            pg.set_viewport_size({"width": 1024, "height": 900})
            pg.wait_for_timeout(300)
            pg.locator('#srxGrid').scroll_into_view_if_needed()
            pg.wait_for_timeout(250)
            _ov = pg.evaluate("""()=>{const a=document.querySelector(
              '.srx-mtabs').getBoundingClientRect();const b=document.querySelector(
              '.srx-listhead').getBoundingClientRect();
              return {overlap:Math.max(0,Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top))}}""")
            ck("r355 1024 吸顶条不遮列表头", _ov["overlap"] <= 0, str(_ov))
            # 配置航线卡：键盘焦点即可联想，Enter 精确回填码+名
            pg.set_viewport_size({"width": 1512, "height": 950})
            pg.evaluate("switchView('cfg')")
            pg.wait_for_timeout(400)
            pg.evaluate("showCfgPanel('users')")
            pg.wait_for_timeout(600)
            pg.evaluate("""()=>{const i=document.getElementById('rtTo_0_0');
              if(!i||i.offsetParent===null){const h=document.querySelector(
                '.rline[data-rk="0:0"] .rhead');if(h)h.click()}}""")
            pg.wait_for_timeout(300)
            _rc = pg.evaluate("""()=>{const b=[...document.querySelectorAll(
              '.rt-citymore')].find(x=>x.offsetParent!==null);
              if(!b)return {skip:true};const r=b.getBoundingClientRect();
              return {w:r.width,h:r.height,pad:getComputedStyle(b).padding}}""")
            ck("r355 配置城市箭头可见", _rc.get("skip")
               or (_rc["w"] >= 12 and _rc["h"] >= 20), str(_rc))
            pg.evaluate("""()=>{const i=document.getElementById('rtTo_0_0');
              if(!i)return;i.value='';i.dispatchEvent(new Event('input',
                {bubbles:true}));i.focus()}""")
            pg.keyboard.type("长沙", delay=60)
            pg.wait_for_timeout(650)
            _co = pg.evaluate("""()=>({n:document.querySelectorAll(
              '#rtTo_0_0Drop .cwf-cityopt').length,
              vis:!document.getElementById('rtTo_0_0Drop').hidden})""")
            pg.keyboard.press("Enter")
            pg.wait_for_timeout(300)
            _cm = pg.evaluate("""()=>({to:CFG[0].routes[0].to,
              name:CFG[0].routes[0].to_name})""")
            _res = pg.evaluate("""()=>cfgCityLookup('长沙')""")
            ck("r355 配置城市联想+码名解析", _co["n"] > 0 and _co["vis"]
               and _res.get("code") == "CSX", str({"drop": _co, "res": _res}))
            pg.evaluate("switchView('mon');showMonTab('overview')")
            pg.wait_for_timeout(200)

            # ---- v1.5.273 检索台诚实性与矩阵身份列 ----
            pg.set_viewport_size({"width": 1512, "height": 950})
            pg.evaluate("switchView('search')")
            pg.wait_for_selector("#searchview .srx-row", timeout=15000)
            pg.wait_for_timeout(500)
            _hon = pg.evaluate("""()=>({
              live:document.getElementById('srxLiveTag').textContent.trim(),
              mode:document.getElementById('srxModeLabel').textContent.trim(),
              sub:document.getElementById('srxHeroSub').textContent})""")
            ck("v15273 演示检索不冒充 LIVE", _hon["live"] == "DEMO"
               and "演示数据" in _hon["mode"] and "演示库" in _hon["sub"],
               str(_hon))
            pg.evaluate("srxToggleView()")
            pg.wait_for_selector("#searchview .srx-mx", timeout=10000)
            pg.wait_for_timeout(250)
            _mx = pg.evaluate("""()=>{
              const thd=document.querySelector('#searchview .srx-thead');
              const th=document.querySelector('#searchview .srx-mx th');
              const td=document.querySelector('#searchview .srx-mx td');
              const a=getComputedStyle(th),c=getComputedStyle(td);
              return {thd:getComputedStyle(thd).display,pos:a.position,
                      top:a.top,tdpos:c.position,left:c.left};}""")
            ck("v15273 矩阵表头吸附且不压列表头",
               _mx["thd"] == "none" and _mx["pos"] == "sticky"
               and _mx["top"] == "0px" and _mx["tdpos"] == "sticky"
               and _mx["left"] == "0px", str(_mx))
            pg.evaluate("srxToggleView()")
            pg.set_viewport_size({"width": 390, "height": 844})
            pg.wait_for_timeout(400)
            _mob = pg.evaluate("""()=>{
              const r=document.querySelector('#searchview .srx-row');
              const q=document.getElementById('srxQ');
              const note=document.getElementById('srxBandNote');
              return {cols:getComputedStyle(r).gridTemplateColumns,
                      q:getComputedStyle(q).fontSize,
                      band:getComputedStyle(note,'::after').content,
                      ow:document.documentElement.scrollWidth-window.innerWidth};}""")
            ck("v15273 移动端操作列与输入不缩放",
               _mob["cols"].endswith("118px") and _mob["q"] == "16px"
               and _mob["ow"] <= 0, str(_mob))
            ck("v15273 移动价带滑动提示在场",
               "左右滑动查看更多日期" in _mob["band"], str(_mob))
            # ---- v1.5.274 平板卡片 / 空态行 / 表单页脚 / 城市全量 ----
            pg.set_viewport_size({"width": 768, "height": 900})
            pg.evaluate("switchView('mon');showMonTab('details')")
            pg.wait_for_timeout(700)
            _v274 = pg.evaluate("""()=>{const tw=document.querySelector('#tablecard .tw');
              const tr=document.querySelector('#ftable tbody tr[data-k]');
              const cs=getComputedStyle(tw);
              return {sw:tw.scrollWidth,cw:tw.clientWidth,
                disp:tr?getComputedStyle(tr).display:null,
                mask:cs.maskImage||cs.webkitMaskImage||'none',
                th:getComputedStyle(document.querySelector('#ftable thead')).display};}""")
            ck("v15274 768 明细转卡片零横滚",
               _v274["sw"] <= _v274["cw"] and _v274["disp"] == "grid"
               and _v274["th"] == "none" and _v274["mask"] == "none", str(_v274))
            pg.set_viewport_size({"width": 390, "height": 844})
            pg.wait_for_timeout(300)
            pg.click("#fltBtn")
            pg.fill("#fq", "ZZZZ")
            pg.wait_for_timeout(450)
            _er = pg.evaluate("""()=>{const tr=document.querySelector('#ftable tr.erow');
              if(!tr)return {found:false};
              const td=tr.querySelector('td'),r=tr.getBoundingClientRect();
              return {found:true,h:Math.round(r.height),
                w:Math.round(td.getBoundingClientRect().width),
                row:Math.round(r.width)};}""")
            ck("v15274 无结果行不塌陷",
               _er.get("found") and _er["h"] > 40
               and abs(_er["w"] - (_er["row"] - 24)) < 6, str(_er))
            pg.evaluate("resetFltUI();document.querySelector('.fbar')?.classList.remove('open')")
            pg.evaluate("switchView('cfg');showCfgPanel('users');"
                        "if(OPEN_USER<0)document.querySelector('.uhead2').click()")
            pg.wait_for_timeout(900)
            pg.evaluate("document.querySelector('#uwatch-0 [data-cwact=add]')?.click()")
            pg.wait_for_timeout(450)
            _cf = pg.evaluate("""()=>{const f=document.querySelector('.cwf-foot'),
                s=document.querySelector('.cwf-switches');
              if(!f||!s)return {found:false};
              const fr=f.getBoundingClientRect(),sr=s.getBoundingClientRect();
              const bs=[...f.querySelectorAll('.btn2')].map(b=>Math.round(b.getBoundingClientRect().width));
              return {found:true,pos:getComputedStyle(f).position,
                overlap:fr.top<sr.bottom-1,bs};}""")
            ck("v15274 关注页脚不吸底且主次对称",
               _cf.get("found") and _cf["pos"] == "static" and not _cf["overlap"]
               and _cf["bs"][0] >= _cf["bs"][1] * 1.8
               and _cf["bs"][1] == _cf["bs"][2], str(_cf))
            # 新语义下新增关注只能从已配置航线/日期选择，自定义城市仅用于
            # 编辑历史身份；组件能力仍在编辑态验证，不能把新增态当唯一入口。
            _custom = pg.evaluate("""()=>{
              let b=document.querySelector('[data-cwmode=custom]');
              if(!b){const w=(CFG_WATCH.list||[])[0];if(w&&typeof cfgWatchEdit==='function'){cfgWatchEdit(w.id);b=null}}
              if(!b)b=document.querySelector('[data-cwmode=custom]');
              if(b){b.click();return true}return false;}""")
            pg.wait_for_timeout(400)
            ck("goal 历史身份自定义城市入口", bool(_custom), str(_custom))
            pg.fill("#cwFromCity", "")
            pg.focus("#cwFromCity")
            pg.wait_for_timeout(500)
            _city = pg.evaluate("""()=>{const d=document.getElementById('cwFromCityDrop');
              return {n:d.querySelectorAll('.cwf-cityopt').length,
                more:!!d.querySelector('[data-cwshowall]'),hidden:d.hidden};}""")
            ck("v15274 关注城市全量入口在场",
               not _city["hidden"] and _city["n"] >= 8 and _city["more"], str(_city))
            pg.evaluate("document.querySelector('#cwFromCityDrop [data-cwshowall]')?.click()")
            pg.wait_for_timeout(450)
            _cityall = pg.evaluate("""()=>{const d=document.getElementById('cwFromCityDrop');
              return {n:d.querySelectorAll('.cwf-cityopt').length,
                regions:[...d.querySelectorAll('.cwf-citynone')].map(x=>x.textContent).join('|')};}""")
            ck("v15274 全部城市可浏览", _cityall["n"] > 200
               and "国内" in _cityall["regions"], str(_cityall))
            pg.evaluate("cfgWatchReset();switchView('mon');showMonTab('health')")
            pg.set_viewport_size({"width": 390, "height": 844})
            pg.wait_for_timeout(800)
            _h274 = pg.evaluate("""()=>[...document.querySelectorAll('#hbody .hcells')]
              .map(x=>({sl:Math.round(x.scrollLeft),
                        max:Math.round(x.scrollWidth-x.clientWidth)}))""")
            ck("v15274 健康最新轮滚到右端",
               bool(_h274) and all(x["sl"] >= x["max"] - 2 for x in _h274),
               str(_h274))
            pg.set_viewport_size({"width": 1280, "height": 900})
            pg.evaluate("switchView('mon');showMonTab('overview')")
            pg.wait_for_timeout(200)

            # ---- r357 配置首屏 / 就地交换起降 / 登录区表面 ----
            _c357 = b.new_context(viewport={"width": 767, "height": 1000})
            _p357 = _c357.new_page()
            _p357.set_default_timeout(10000)
            _p357.on("console", lambda m: errors.append(m.text)
                     if m.type == "error" and "403 (Forbidden)" not in m.text
                     else None)
            _p357.on("pageerror", lambda e: errors.append(
                (getattr(e, "stack", None) or str(e))[:500]))
            _p357.goto(BASE, wait_until="domcontentloaded")
            _p357.wait_for_timeout(1800)
            _p357.click("#navCfg")
            _p357.wait_for_timeout(800)
            _w357 = _p357.evaluate("""()=>({
              loaded:CFG_WATCH.loadedOnce,loading:CFG_WATCH.loading,
              items:document.querySelectorAll('#cfgWatch .cw-item').length,
              badge:(document.getElementById('navN-watch')||{}).textContent||''})""")
            ck("r357 配置首屏预热关注航班",
               _w357["loaded"] and not _w357["loading"]
               and _w357["items"] >= 1,
               str(_w357))
            _l357 = _p357.evaluate("""()=>{
              const R=e=>{const r=e.getBoundingClientRect();return [r.left,r.top,r.right,r.bottom]};
              const ic=document.querySelector('#cfgview .secicon'),
                    zh=document.querySelector('#cfgview .seclab .zh'),
                    hd=document.querySelector('#cfgview .uhead'),
                    gr=document.querySelector('#cfgview .lggrid');
              const ir=R(ic),zr=R(zh),hr=R(hd),grr=R(gr);
              const cs=[...gr.querySelectorAll('.lgcard')],rows={};
              cs.forEach(c=>{const r=c.getBoundingClientRect();
                const k=Math.round(r.top);rows[k]=(rows[k]||0)+1});
              return {overlap:!(ir[2]<=zr[0]||zr[2]<=ir[0]||ir[3]<=zr[1]||zr[3]<=ir[1]),
                      gap:grr[1]-hr[3],cols:Math.max(...Object.values(rows)),
                      overflow:document.documentElement.scrollWidth-window.innerWidth};}""")
            ck("r357 登录区标题/卡片不挤压",
               not _l357["overlap"] and _l357["gap"] >= 8
               and _l357["cols"] == 3 and _l357["overflow"] <= 0, str(_l357))
            # r365：飞猪等长状态文案不得把按钮顶下去；同一行按钮必须
            # 底对齐（旧 .lgcard .btn2{margin:0} 覆盖 margin-top:auto，
            # 文案换行后飞猪按钮比其余四张低 15px）
            _lg365 = _p357.evaluate("""()=>{
              const cards=[...document.querySelectorAll('#cfgview .lgcard')];
              const c=cards[cards.length-1],sub=c.querySelector('.lgsub');
              const old=sub.textContent;c.classList.add('stale');
              sub.textContent='无需登录 · 会话可能失效，建议重登并检查登录窗口是否被占用';
              const groups={};
              cards.forEach(x=>{const r=x.getBoundingClientRect(),
                b=x.querySelector('.btn2').getBoundingClientRect();
                const k=Math.round(r.top);(groups[k]=groups[k]||[]).push(
                  {h:+r.height.toFixed(1),b:+b.bottom.toFixed(1)})});
              sub.textContent=old;c.classList.remove('stale');
              const gs=Object.values(groups);
              return {groups:gs,
                aligned:gs.every(g=>Math.max(...g.map(x=>x.b))
                  -Math.min(...g.map(x=>x.b))<=0.5),
                same:gs.every(g=>Math.max(...g.map(x=>x.h))
                  -Math.min(...g.map(x=>x.h))<=0.5)};}""")
            ck("r365 登录卡片按钮底对齐",
               _lg365["aligned"] and _lg365["same"], str(_lg365))
            _p357.locator(".cnav").filter(has_text="用户与航线").click()
            _p357.wait_for_timeout(600)
            _b357 = _p357.evaluate(
                "()=>document.querySelector('#cfgview .rhead .rtcode').textContent")
            _p357.locator("#cfgview .ropbtn").filter(has_text="交换起降").first.click()
            _p357.wait_for_timeout(1100)
            _s357 = _p357.evaluate("""()=>({
              after:document.querySelector('#cfgview .rhead .rtcode').textContent,
              dirty:cfgIsDirty(),
              savebar:!!document.querySelector('.savebar.on'),
              copyTitle:([...document.querySelectorAll('#cfgview .ropbtn')]
                .find(x=>x.textContent.includes('复制'))||{}).title||''})""")
            ck("r357 航线就地交换起降",
               _s357["after"] != _b357 and _s357["dirty"] and _s357["savebar"]
               and "同方向" in _s357["copyTitle"], str(_s357))
            _c357.close()

            # ===== r358 密度/层级/数据身份回归门 =====
            _c358 = b.new_context(viewport={"width": 390, "height": 844})
            _p358 = _c358.new_page()
            _p358.on("pageerror", lambda e: errors.append(str(e)))
            _p358.goto(BASE + "/")
            _p358.wait_for_function(
                "typeof S !== 'undefined' && S && S.users")
            _p358.wait_for_timeout(600)
            _p358.evaluate("switchView('search')")
            _p358.wait_for_timeout(700)
            _p358.evaluate(
                "()=>{const p=document.getElementById('srxProbe');"
                "if(p)p.classList.remove('open')}")
            _m358 = _p358.evaluate("""()=>{
              const p=document.getElementById('srxProbe'),
                    a=document.querySelector('.srx-hero-act');
              return {ph:p.getBoundingClientRect().height,
                cols:getComputedStyle(a).gridTemplateColumns.split(' ').length,
                desc:getComputedStyle(
                  document.querySelector('.srx-probehint')).display}}""")
            ck("r358 390 探针收起单行/工具两列",
               _m358["ph"] <= 55 and _m358["cols"] == 2
               and _m358["desc"] == "none", str(_m358))
            _p358.evaluate(
                "()=>{const v=document.getElementById('searchview');"
                "if(!v.classList.contains('show-overview'))"
                "document.querySelector('[data-mobile=overview]').click()}")
            _p358.wait_for_timeout(600)
            _b358 = _p358.evaluate("""()=>{
              const b=document.getElementById('srxBrief'),
                    s=getComputedStyle(b);
              return {xh:b.classList.contains('xhint'),
                mask:(s.maskImage||s.webkitMaskImage)!=='none',
                sw:b.scrollWidth,cw:b.clientWidth}}""")
            ck("r358 390 来源卡横滑暗示",
               _b358["xh"] and _b358["mask"]
               and _b358["sw"] > _b358["cw"], str(_b358))
            _c358.close()

            _c358 = b.new_context(viewport={"width": 768, "height": 900})
            _p358 = _c358.new_page()
            _p358.on("pageerror", lambda e: errors.append(str(e)))
            _p358.goto(BASE + "/")
            _p358.wait_for_function(
                "typeof S !== 'undefined' && S && S.users")
            _p358.wait_for_timeout(600)
            _p358.evaluate("switchView('search')")
            _p358.wait_for_timeout(700)
            # 中性首屏没有选中日期；先建立同条件航线/日期，再验日期带
            _p358.evaluate(
                "()=>{SRX.pair='SHA|BKK';SRX.date='2026-11-16';"
                "srxSave();renderSearch();const v=document.getElementById('searchview');"
                "if(!v.classList.contains('show-overview'))"
                "document.querySelector('[data-mobile=overview]').click()}")
            _p358.wait_for_timeout(1400)
            # 未采日期带默认收起为空态提示（减少空日期卡，r366 布局
            # 契约）；显式“展开日期带”后再验横滑暗示，避免把空态
            # 当成横滑缺失。
            _p358.evaluate(
                "()=>{const b=document.querySelector('[data-bandexpand]');"
                "if(b)b.click()}")
            _p358.wait_for_timeout(500)
            _d358 = _p358.evaluate("""()=>{
              const b=document.getElementById('srxBandDays'),
                    s=getComputedStyle(b);
              return {xh:b.classList.contains('xhint'),
                mask:(s.maskImage||s.webkitMaskImage)!=='none',
                sw:b.scrollWidth,cw:b.clientWidth}}""")
            ck("r358 768 价带横滑暗示",
               _d358["xh"] and _d358["mask"]
               and _d358["sw"] > _d358["cw"], str(_d358))
            _c358.close()

            _c358 = b.new_context(viewport={"width": 1024, "height": 900})
            _p358 = _c358.new_page()
            _p358.on("pageerror", lambda e: errors.append(str(e)))
            _p358.goto(BASE + "/")
            _p358.wait_for_function(
                "typeof S !== 'undefined' && S && S.users")
            _p358.wait_for_timeout(600)
            _p358.evaluate("switchView('search')")
            _p358.wait_for_timeout(700)
            _p358.evaluate("srxOpenDetail()")
            _p358.wait_for_timeout(600)
            _h358 = _p358.evaluate("""()=>{
              const R=e=>{const r=e.getBoundingClientRect();
                return {y:+r.y.toFixed(1),r:+r.right.toFixed(1),
                        b:+r.bottom.toFixed(1)}};
              const d=document.getElementById('srxDetail');
              return {d:R(d),close:R(d.querySelector('.srx-close')),
                acts:R(d.querySelector('.srx-dhead>.srx-dacts'))}}""")
            ck("r358 1024 详情关闭钮贴右缘/动作第二行",
               _h358["close"]["r"] >= _h358["d"]["r"] - 30
               and _h358["acts"]["y"] >= _h358["close"]["b"] - 1
               and _h358["acts"]["r"] <= _h358["d"]["r"] - 10,
               str(_h358))
            _p358.evaluate("srxCloseDetail();showMonTab('health')")
            _p358.wait_for_timeout(800)
            _hc358 = _p358.evaluate("""()=>{
              const c=[...document.querySelectorAll('#hbody .hc')]
                .find(x=>x.hasAttribute('data-ts'));
              if(!c)return null;
              const o={ts:c.dataset.ts,p:c.dataset.p};c.click();return o}""")
            _p358.wait_for_timeout(500)
            _hl358 = _p358.evaluate("""()=>({
              title:document.getElementById('pvTitle').textContent,
              body:document.getElementById('pvBody').innerText})""")
            ck("r358 健康日志轮次/渠道与格一致",
               bool(_hc358) and _hc358["ts"] in _hl358["title"]
               and ("[" + _hc358["p"] + "]") in _hl358["body"],
               str({"cell": _hc358, "title": _hl358["title"]}))
            _c358.close()

            # ===== r359 起降对齐 / 日期字段按内容定宽 / 整字段唤起 =====
            _c359 = b.new_context(viewport={"width": 1512, "height": 982})
            _p359 = _c359.new_page()
            _p359.on("pageerror", lambda e: errors.append(str(e)))
            _p359.goto(BASE + "/")
            _p359.wait_for_function(
                "typeof S !== 'undefined' && S && S.users")
            _p359.wait_for_timeout(600)
            _p359.evaluate("switchView('search')")
            _p359.wait_for_timeout(700)
            _l360 = _p359.evaluate("""()=>{
              let small=0;
              document.querySelectorAll('#searchview *').forEach(e=>{
                const direct=[...e.childNodes].some(n=>n.nodeType===3
                  && n.textContent.trim().length>1);
                if(!direct)return;
                const s=getComputedStyle(e);
                if(s.display==='none'||s.visibility==='hidden')return;
                const r=e.getBoundingClientRect();
                if(r.width<1||r.height<1)return;
                if(parseFloat(s.fontSize)<=10.5)small++});
              const srcs=[...document.querySelectorAll('#searchview .srx-src')]
                .filter(e=>e.getBoundingClientRect().height>0);
              const tops=[...new Set(srcs.map(e=>
                Math.round(e.getBoundingClientRect().top)))];
              const hs=srcs.map(e=>+e.getBoundingClientRect().height.toFixed(1));
              const ic=document.querySelector('#searchview .srx-src-h .p');
              const counts=srcs.map(e=>parseInt(
                (e.querySelector('.srx-src-big')||{}).textContent||'0',10)||0);
              const mirc=[...document.querySelectorAll(
                '#srxMirror .srx-mtab .n')].map(e=>parseInt(e.textContent,10)||0);
              const desc=a=>a.every((v,i)=>i===0||v<=a[i-1]);
              return {small:small,count:srcs.length,tops:tops,
                maxH:hs.length?Math.max(...hs):null,
                icon:ic?+ic.getBoundingClientRect().width.toFixed(1):0,
                counts:counts,sorted:desc(counts),mirc:mirc,msorted:desc(mirc)}}""")
            ck("r360 检索页微字/五源条/可用渠道优先",
               _l360["small"] == 0 and _l360["count"] == 5
               and len(_l360["tops"]) == 1 and _l360["maxH"] <= 60
               and _l360["icon"] >= 20 and _l360["sorted"]
               and _l360["msorted"], str(_l360))
            # ===== r361 图标/文案不相交 + 时刻列/探针控件按内容定宽 =====
            # 1280 是历史重叠真实宽度（+1 曾压到「仅观察」），不只在 1512 验。
            _p359.set_viewport_size({"width": 1280, "height": 982})
            _p359.wait_for_timeout(350)
            _p359.evaluate("""()=>{const p=document.querySelector('#srxProbe');
              if(p&&!p.classList.contains('open'))srxToggleProbe()}""")
            _p359.wait_for_timeout(350)
            _r361 = _p359.evaluate("""()=>{
              const rows=[...document.querySelectorAll('#srxRows .srx-row')];
              let gap=999,over=false;
              rows.forEach(r=>{const t=r.querySelector('.srx-times'),
                b=r.querySelector('.srx-badges');
                if(!t||!b)return;
                gap=Math.min(gap,b.getBoundingClientRect().left
                  -t.getBoundingClientRect().right);
                if(t.scrollWidth>t.clientWidth+1)over=true});
              const f=document.querySelector(
                '#searchview .srx-probeform').getBoundingClientRect();
              const from=document.querySelector(
                '#srxFrom').getBoundingClientRect();
              const pick=document.querySelector(
                '#srxPlatPick').getBoundingClientRect();
              const head=document.querySelector(
                '#searchview .srx-probehead').getBoundingClientRect();
              const qrow=document.querySelector(
                '.srx-qrow').getBoundingClientRect();
              const probe=document.querySelector(
                '#srxProbe').getBoundingClientRect();
              return {n:rows.length,gap:+gap.toFixed(1),over,
                fromW:+from.width.toFixed(1),formH:+f.height.toFixed(1),
                fromLeft:+from.left.toFixed(1),
                pickLeft:+pick.left.toFixed(1),pickTop:+pick.top.toFixed(1),
                qrowBottom:+qrow.bottom.toFixed(1),
                qrowRight:+qrow.right.toFixed(1),
                pickRight:+pick.right.toFixed(1),
                headRight:+head.right.toFixed(1),
                probeH:+probe.height.toFixed(1),
                doc:document.documentElement.scrollWidth,iw:innerWidth}}""")
            ck("r361 时刻列不压状态/探针字段按内容定宽/宽屏渠道片同排紧邻查询控件",
               _r361["n"] >= 8 and _r361["gap"] >= 3
               and not _r361["over"] and _r361["fromW"] <= 200
               and _r361["formH"] <= 100
               and _r361["pickLeft"] >= _r361["fromLeft"] - 2
               and _r361["pickTop"] < _r361["qrowBottom"]
               and -2 <= _r361["pickLeft"] - _r361["qrowRight"] <= 60
               and _r361["pickRight"] <= _r361["headRight"] + 1
               and _r361["probeH"] <= 200
               and _r361["doc"] <= _r361["iw"] + 1, str(_r361))
            _ico361 = _p359.evaluate("""()=>{
              const vis=e=>{const r=e.getBoundingClientRect(),
                s=getComputedStyle(e);return r.width>0&&r.height>0
                &&s.display!=='none'&&s.visibility!=='hidden'};
              const bad=[];
              for(const ic of document.querySelectorAll(
                '#searchview svg,#searchview .bic,#searchview .bic-air,'
                +'#searchview img')){
                if(!vis(ic)||!ic.parentElement)continue;
                const p=ic.parentElement,ir=ic.getBoundingClientRect();
                for(const n of p.childNodes){
                  if(n.nodeType!==3||!n.textContent.trim())continue;
                  const rg=document.createRange();
                  rg.selectNodeContents(n);
                  for(const tr of rg.getClientRects()){
                    const ox=Math.min(ir.right,tr.right)
                      -Math.max(ir.left,tr.left);
                    const oy=Math.min(ir.bottom,tr.bottom)
                      -Math.max(ir.top,tr.top);
                    if(ox>.5&&oy>.5)bad.push(
                      (n.textContent.trim()||'').slice(0,18)
                      +'@'+Math.round(ox)+'x'+Math.round(oy));
                  }}}
              return bad.slice(0,8)}""")
            ck("r361 检索页图标与文案零相交",
               len(_ico361) == 0, str(_ico361))
            _p359.evaluate("switchView('mon');showMonTab('overview')")
            _p359.wait_for_timeout(2400)
            _mw361 = _p359.evaluate("""()=>{
              const card=document.querySelector('.monwatch');if(!card)
                return {none:true};
              const box=card.querySelector('.monwatch-chs'),
                cov=card.querySelector('.monwatch-foot > span:nth-of-type(2)'),
                svg=card.querySelector('.monwatch-svg'),
                lg=card.querySelector('.monwatch-svg .lg'),
                bic=card.querySelector('.monwatch-ch .bic');
              const b=box&&box.getBoundingClientRect(),
                c=cov&&cov.getBoundingClientRect(),
                s=svg&&svg.getBoundingClientRect(),
                l=lg&&lg.getBoundingClientRect();
              return {n:card.querySelectorAll('.monwatch-ch').length,
                icon:bic?+bic.getBoundingClientRect().width.toFixed(1):0,
                gap:(b&&c)?+(c.left-b.right).toFixed(1):null,
                legendFits:!!(s&&l)&&l.bottom<=s.bottom-1,
                over:document.documentElement.scrollWidth>innerWidth+1}}""")
            ck("r361 关注卡渠道图标/图例不重叠",
               not _mw361.get("none")
               and _mw361["n"] == 5 and _mw361["icon"] >= 17
               and _mw361["gap"] >= 4 and _mw361["legendFits"]
               and not _mw361["over"], str(_mw361))
            _p359.evaluate("switchView('search')")
            _p359.wait_for_timeout(700)
            # 中性首屏不再自动锁定日期；价带门禁显式选择一个有数据日期
            _p359.evaluate("""()=>{const ds=[...new Set(srxAll().map(f=>f.date).filter(Boolean))].sort();
              if(ds.length){SRX.date=ds[0];SRX.bandAnchor='';SRX._init=true;srxSave();renderSearch()}}""")
            _p359.wait_for_timeout(1300)
            # ===== r361 价带：点日不重置窗口；可前后翻并回到所选日 =====
            _b361 = _p359.evaluate("""()=>{
              const ds=()=>[...document.querySelectorAll(
                '#srxBandDays [data-calday]')];
              if(ds().length<3)return null;
              const first=ds()[0].getAttribute('data-calday');
              const date=SRX.date;
              ds()[2].click();
              return {first:first,date:date}}""")
            _p359.wait_for_timeout(600)
            _b361a = _p359.evaluate("""()=>{
              const ds=[...document.querySelectorAll(
                '#srxBandDays [data-calday]')];
              const sel=document.querySelector('#srxBandDays .srx-day.sel');
              const r=document.querySelector('#srxBandReset');
              return {first:ds.length?ds[0].getAttribute('data-calday'):'',
                last:ds.length?ds[ds.length-1].getAttribute('data-calday'):'',
                sel:sel?sel.getAttribute('data-calday'):'',
                reset:!!r&&!r.hidden}}""")
            # 全未采窗口默认收敛为说明条；翻窗门禁先显式展开日期带
            _p359.evaluate("SRX.bandExpand=true;srxRenderBand()")
            _p359.wait_for_timeout(250)
            _p359.evaluate(
                "document.querySelectorAll('.srx-bandnav button')[0].click()")
            _p359.wait_for_timeout(1300)
            _b361p = _p359.evaluate("""()=>{
              const ds=[...document.querySelectorAll(
                '#srxBandDays [data-calday]')];
              return {first:ds.length?ds[0].getAttribute('data-calday'):'',
                last:ds.length?ds[ds.length-1].getAttribute('data-calday'):'',
                doc:document.documentElement.scrollWidth,iw:innerWidth}}""")
            _p359.evaluate(
                "document.querySelector('#srxBandReset').click()")
            _p359.wait_for_timeout(1200)
            _b361r = _p359.evaluate("""()=>{
              const ds=[...document.querySelectorAll(
                '#srxBandDays [data-calday]')];
              const sel=document.querySelector('#srxBandDays .srx-day.sel');
              return {first:ds.length?ds[0].getAttribute('data-calday'):'',
                sel:sel?sel.getAttribute('data-calday'):''}}""")
            ck("r361 价带点日不重置窗口/可前后翻",
               bool(_b361) and bool(_b361a)
               and _b361a["first"] == _b361["first"]
               and _b361a["sel"] != _b361a["first"]
               and _b361a["reset"]
               and _b361p["first"] < _b361["first"]
               and _b361p["first"] != _b361p["last"]
               and _b361r["first"] == _b361a["sel"]
               and _b361r["first"] == _b361r["sel"]
               and _b361p["doc"] <= _b361p["iw"] + 1,
               str({"pick": _b361, "after": _b361a,
                    "prev": _b361p, "reset": _b361r}))
            # 价带翻页会切到无行日期；还原初始日再验时刻列。
            _p359.evaluate("""()=>{SRX.plats=[];SRX.q='';
              SRX.f={...SRX_DEFAULT_F};SRX.agg=false;SRX.view='list';
              const ds=[...new Set(srxBase().filter(f=>!srxIsCal(f))
                .map(f=>f.date).filter(Boolean))].sort();
              SRX.date=ds[0]||SRX.date;SRX.bandAnchor='';SRX.sel=null;
              SRX._init=true;srxSave();renderSearch()}""")
            _p359.wait_for_timeout(1200)
            _t359 = _p359.evaluate("""()=>{
              const arr=[...document.querySelectorAll(
                '#srxRows .srx-row .srx-times .arr')]
                .map(e=>+e.getBoundingClientRect().x.toFixed(1));
              const cells=[...document.querySelectorAll(
                '#srxRows .srx-row .srx-times')];
              return {n:arr.length,
                min:arr.length?Math.min(...arr):null,
                max:arr.length?Math.max(...arr):null,
                over:cells.some(e=>e.scrollWidth>e.clientWidth+1)}}""")
            ck("r359 起降时刻左缘对齐",
               _t359["n"] >= 8
               and _t359["max"] - _t359["min"] <= 1
               and not _t359["over"], str(_t359))
            _p359.evaluate(
                "switchView('cfg');"
                "document.querySelector('#cfgview .cnav[data-p=users]').click()")
            _p359.wait_for_timeout(900)
            _p359.evaluate("""()=>{const h=document.querySelector(
                '#cfgform .rline[data-rk] .rhead');
              if(h&&h.getAttribute('aria-expanded')==='false')h.click()}""")
            _p359.wait_for_timeout(300)
            _p359.evaluate("setDateMode('d',0,0,'single')")
            _p359.wait_for_timeout(400)
            _p359.evaluate("""()=>{window._sp359=0;
              const o=HTMLInputElement.prototype.showPicker;
              HTMLInputElement.prototype.showPicker=function(){
                window._sp359++;try{return o&&o.call(this)}catch(e){}}}""")
            _p359.locator("#cfgform .dateSrow .dpanel:not([hidden]) "
                          "input[type=date]").first.click()
            _p359.wait_for_timeout(250)
            _d359 = _p359.evaluate("""()=>{
              const pn=document.querySelector(
                '#cfgform .dateSrow .dpanel:not([hidden])');
              const inp=pn.querySelector('input[type=date]'),
                    ap=pn.querySelector('.dapply');
              const r=inp.getBoundingClientRect(),
                    a=ap.getBoundingClientRect();
              return {w:+r.width.toFixed(1),
                sameRow:Math.abs(r.top-a.top)<3,hits:window._sp359,
                over:document.documentElement.scrollWidth>innerWidth+1}}""")
            ck("r359 日期字段内容定宽/整字段唤起",
               _d359["w"] <= 200 and _d359["sameRow"]
               and _d359["hits"] >= 1 and not _d359["over"], str(_d359))
            _p359.set_viewport_size({"width": 390, "height": 844})
            _p359.wait_for_timeout(500)
            _d359b = _p359.evaluate("""()=>{
              const pn=document.querySelector(
                '#cfgform .dateSrow .dpanel:not([hidden])');
              const inp=pn.querySelector('input[type=date]'),
                    ap=pn.querySelector('.dapply');
              const r=inp.getBoundingClientRect(),
                    a=ap.getBoundingClientRect();
              return {w:+r.width.toFixed(1),
                sameRow:Math.abs(r.top-a.top)<3,
                over:document.documentElement.scrollWidth>innerWidth+1}}""")
            ck("r359 390 日期字段与加入按钮同排",
               _d359b["w"] > 120 and _d359b["sameRow"]
               and not _d359b["over"], str(_d359b))
            _c359.close()

            # goal: 关注航线/关注航班曲线与检索/明细筛选统一
            pg.set_viewport_size({"width": 1440, "height": 900})
            pg.evaluate("switchView('mon');showMonTab('overview')")
            pg.wait_for_timeout(800)
            _u = pg.evaluate("""()=>({
              routeCard:getComputedStyle(document.querySelector('#monRouteCard')).display!=='none',
              routes:document.querySelectorAll('#monRouteList .monroute').length,
              routeSvg:document.querySelectorAll('#monRouteList .monroute svg').length,
              watchCard:getComputedStyle(document.querySelector('#monWatchCard')).display!=='none',
              watchSvg:document.querySelectorAll('#monWatchList .monwatch svg').length})""")
            ck("goal 关注航线卡与共享迷你曲线",
               _u["routeCard"] and _u["routes"] > 0 and _u["routeSvg"] > 0, str(_u))
            ck("goal 关注航班卡与独立迷你曲线",
               _u["watchCard"] and _u["watchSvg"] > 0, str(_u))
            pg.evaluate("showMonTab('watch')")
            pg.wait_for_timeout(2200)
            _ws = pg.evaluate("""()=>({
              scope:document.querySelector('#wsRouteWatch')?.innerText||'',
              spark:document.querySelectorAll('#wsRouteWatch .ws-rwspark svg').length})""")
            ck("goal 关注台子集过滤摘要", "关注航班 = 配置关注航线 + 同日期明细中的指定航班" in _ws["scope"], str(_ws["scope"][:80]))
            ck("goal 关注台航线共享曲线", _ws["spark"] > 0, str(_ws))
            pg.evaluate("switchView('search')")
            pg.wait_for_timeout(1200)
            pg.evaluate("document.querySelector('#srxFilterBtn').click()")
            pg.wait_for_timeout(200)
            pg.evaluate("document.querySelector('#srxMoreBtn').click()")
            pg.wait_for_timeout(350)
            _sf = pg.evaluate("""()=>({
              common:!!document.querySelector('#srxFmore .srx-fcommon'),
              depA:!!document.querySelector('#srxFmore [data-srf=depAs]'),
              shareMode:!!document.querySelector('#srxFmore select[data-fs=shareMode]'),
              detailFields:document.querySelectorAll('#srxFmore [data-fn=laymin],#srxFmore [data-fn=durmin],#srxFmore [data-fn=prate],#srxFmore [data-fn=age],#srxFmore [data-fn=bagkg]').length,
              clear:!!document.querySelector('#srxFmore [data-fclear=common]')})""")
            ck("goal 检索共同筛选组", _sf["common"] and _sf["depA"] and _sf["shareMode"], str(_sf))
            ck("goal 检索明细级超集字段", _sf["detailFields"] >= 5 and _sf["clear"], str(_sf))
            pg.evaluate("""()=>{SRX.f.hasView=true;SRX.f.laymin=60;srxClearCommonFilters()}""")
            _sc = pg.evaluate("()=>({laymin:SRX.f.laymin,hasView:!!SRX.f.hasView})")
            ck("goal 共同筛选清理保留检索特有", _sc["laymin"] == 0 and _sc["hasView"] is True, str(_sc))
            pg.evaluate("switchView('mon');showMonTab('details')")
            pg.wait_for_timeout(900)
            pg.evaluate("document.querySelector('#fltBtn').click()")
            pg.wait_for_timeout(250)
            pg.evaluate("togMoreFlt()")
            pg.wait_for_timeout(250)
            _df = pg.evaluate("""()=>({
              scope:document.querySelector('.fltscope')?.innerText||'',
              share:!!document.querySelector('#fshareonly'),
              hideCal:!!document.querySelector('#fhidecal'),
              onlyQual:!!document.querySelector('#fonlyqual')})""")
            ck("goal 明细共同能力入口", "共同筛选" in _df["scope"] and _df["share"] and _df["hideCal"] and _df["onlyQual"], str(_df))
            pg.set_viewport_size({"width": 1360, "height": 900})
            pg.evaluate("switchView('search')")
            pg.wait_for_timeout(1000)
            pg.evaluate("""()=>{const p=document.querySelector('#srxProbe');
              if(p&&!p.classList.contains('open'))srxToggleProbe()}""")
            pg.wait_for_timeout(350)
            _pr = pg.evaluate("""()=>{const R=s=>{const e=document.querySelector(s);if(!e)return null;const r=e.getBoundingClientRect();return{r:+r.right.toFixed(1),h:+r.height.toFixed(1),b:+r.bottom.toFixed(1)}};
              return{head:R('#srxProbe .srx-probehead'),form:R('#srxProbe .srx-probeform'),acts:R('#srxProbe .srx-probeacts'),
               go:R('#srxGo'),date:R('#srxDate'),pick:R('#srxPlatPick'),
               overflow:document.documentElement.scrollWidth>innerWidth+1}}""")
            ck("goal 探针头部单行对齐", _pr["head"]["h"] <= 30 and _pr["acts"]["r"] == _pr["head"]["r"] and not _pr["overflow"], str(_pr))
            ck("goal 探针表单紧凑", _pr["form"]["h"] <= 54, str(_pr))
            ck("goal 探针提交与输入同基线", abs(_pr["go"]["b"] - _pr["date"]["b"]) <= 1 and _pr["pick"]["h"] <= 32, str(_pr))
            pg.evaluate("()=>{const p=document.querySelector('#srxProbe');if(p&&p.classList.contains('open'))srxToggleProbe()}")
            pg.wait_for_timeout(300)
            _tc = pg.evaluate("""()=>{const t=document.querySelector('#srxProbeToggle');const r=t.getBoundingClientRect();
              return {open:document.querySelector('#srxProbe').classList.contains('open'),
               visible:r.width>0&&r.height>0,text:t.textContent.trim()}}""")
            ck("goal 探针收起后仍可展开", (not _tc["open"]) and _tc["visible"] and _tc["text"] == "展开", str(_tc))
            pg.evaluate("document.querySelector('#srxProbeToggle').click()")
            pg.wait_for_timeout(300)
            _to = pg.evaluate("()=>({open:document.querySelector('#srxProbe').classList.contains('open'),form:document.querySelector('.srx-probeform').getBoundingClientRect().height})")
            ck("goal 探针展开恢复表单", _to["open"] and _to["form"] > 30, str(_to))
            _pair = pg.evaluate("""()=>{const all=(S.users[0]||{}).flights||[];const f=all.find(x=>x.intl&&x.from&&x.to);return f?f.from+'|'+f.to:''}""")
            if _pair:
                pg.evaluate("p=>{SRX.pair=p;SRX.date='';SRX._init=true;renderSearch()}", _pair)
                pg.wait_for_timeout(800)
            _cb = pg.evaluate("""()=>{const e=document.querySelector('#srxCapbar');if(!e||e.hidden)return null;const r=e.getBoundingClientRect();return{h:+r.height.toFixed(1),chips:e.querySelectorAll('.capchip').length,text:e.innerText.slice(0,120),scroll:e.scrollWidth>e.clientWidth}}""")
            ck("goal 渠道/会话单行不换行", bool(_cb) and _cb["h"] <= 40 and _cb["chips"] == 5 and "会话" not in _cb["text"], str(_cb))

            # v294 特价监控：演示快照 3 次，日历/走势/低价日真实航班不空
            pg.evaluate("switchView('mon');showMonTab('specials')")
            pg.wait_for_timeout(1600)
            _sm = pg.evaluate("""()=>{const d=[...document.querySelectorAll('#spMonCal .spmon-day')];
              const c=document.getElementById('spMonChart');
              return{days:d.length,sel:document.querySelectorAll('#spMonCal .spmon-day.sel').length,
               low:!!document.querySelector('#spMonLow .spmon-lowday'),chart:c?c.width:0,
               empty:!!document.querySelector('#spMonCal .spmon-empty'),
               delta:(document.querySelector('.spmon-day .b')||{}).textContent||''}}""")
            ck("v294 特价监控日历年/走势/低价日",
               _sm["days"] == 7 and _sm["sel"] == 1 and _sm["low"]
               and _sm["chart"] > 0 and not _sm["empty"], str(_sm))
            # v294 渠道诊断：五渠道都有分型卡与动作说明
            pg.evaluate("showMonTab('health')")
            pg.wait_for_timeout(1200)
            _dg = pg.evaluate("""()=>{const c=[...document.querySelectorAll(
              '#healthDiagBody .hdiag-card')];return{n:c.length,
               labels:c.map(x=>(x.querySelector('.hdiag-st')||{}).textContent||''),
               acts:c.filter(x=>(x.querySelector('.hdiag-a')||{}).textContent).length}}""")
            ck("v294 渠道诊断五渠道分型",
               _dg["n"] == 5 and len(set(_dg["labels"])) >= 1
               and _dg["acts"] == 5, str(_dg))
            # v294 检索首屏大块均可折叠（说明/价带/五源）
            pg.evaluate("switchView('search')")
            pg.wait_for_timeout(900)
            _fd = pg.evaluate("""()=>{
              const has=s=>!!document.querySelector(s);
              return{hero:has('[onclick*="srxHeroCopy"]'),
               band:has('[onclick*="srxBand"]'),
               brief:has('[data-foldtarget="srxBrief"]')}}""")
            ck("v294 检索大块折叠入口", _fd["hero"] and _fd["band"]
               and _fd["brief"], str(_fd))

            bad0 = [n for n, v in checks if not v]
            prog.write("JS 错误: %s\n" % (errors[:3] if errors else "无"))
            prog.write("=== %d/%d 通过 ===\n"
                       % (len(checks) - len(bad0), len(checks)))
            prog.flush()
            try:
                b.close()
            except Exception:
                pass
    except Exception as e:
        _aborted = True   # 中断≠全绿：不置位会被 exit 判定吞成 0（CI 假绿）
        prog.write(" !! 中断于异常: %r\n" % e)
        prog.flush()
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()

    bad = [n for n, v in checks if not v]
    prog.close()
    with open(RESULT, encoding="utf-8") as f:
        print(f.read())
    # 硬退出：规避 Windows 下 playwright/子进程拆卸悬挂（结果已落盘）
    os._exit(1 if (_aborted or bad or errors) else 0)


if __name__ == "__main__":
    main()
