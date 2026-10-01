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
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8891
BASE = "http://127.0.0.1:%d" % PORT
RESULT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "uitest_result.txt")


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
    from playwright.sync_api import sync_playwright
    free_port()
    srv = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
         "--port", str(PORT)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    checks = []
    errors = []
    _aborted = False
    prog = open(RESULT, "w", encoding="utf-8")

    def ck(name, cond):
        checks.append((name, bool(cond)))
        prog.write((" ✓ " if cond else " ✗ ") + name + "\n")
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
            for _ in range(8):
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
            ck("子视图 4 tab",
               len(pg.query_selector_all("#montabs .mtab")) == 4)
            ck("概览默认可见", pg.is_visible("#montab-overview"))
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
                cells[0].click(); pg.wait_for_timeout(600)
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
                # 先 scroll_into_view 再取框点击：卡内推送通道区增高后
                # 矮视口（CI runner）格子可滚出视口，视口外 mouse.click
                # 落空=环境差异假红
                cells[0].scroll_into_view_if_needed()
                pg.wait_for_timeout(200)
                bb = cells[0].bounding_box()
                if bb:
                    pg.mouse.click(bb["x"] + bb["width"] / 2,
                                   bb["y"] + bb["height"] / 2 + 6)
                    pg.wait_for_timeout(600)
                    ck("健康格热区下缘命中",
                       pg.query_selector(".logpre") is not None)
                    pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
                else:
                    ck("健康格热区下缘命中", False)

            # 健康错误体双分支语义（保陈旧政策收口）：已有时间线时
            # 错误体保陈旧（瞬态 500 不再把整条格带掀成错误文案）；
            # 冷启动（无卡）错误体仍点亮错误词面。200+无 rounds 体
            # 等价触发 renderHealth 同一分支（生产 500 同体），且不制
            # 造预期内 500 console 噪音污染「零 JS 错」门
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
            pg.click("#pvBtn"); pg.wait_for_timeout(700)
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
            n_all = len(pg.query_selector_all("#ftable tbody tr"))
            pg.click('#tabs span[data-f="d"]'); pg.wait_for_timeout(300)
            tags = pg.query_selector_all("#ftable tbody tr .tag")
            ck("直飞 tab 过滤", tags and all(
                "直飞" in t.inner_text() for t in tags))
            pg.click('#tabs span[data-f="bag"]'); pg.wait_for_timeout(300)
            bag_rows = pg.query_selector_all("#ftable tbody tr")
            bag_ok = all("中转" in t.inner_text()
                         for t in pg.query_selector_all("#ftable tbody tr .tag"))
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
            ck("1500 档 statline 解锁（断点缝收敛）", pg.evaluate(
                "()=>['.statline','.pulsewrap','#pulseLegend'].every("
                "s=>{const e=document.querySelector(s);return e&&"
                "getComputedStyle(e).maxWidth==='none';});"))
            pg.set_viewport_size({"width": 1280, "height": 900})
            # 胶囊渲染（demo 3 航线最低价行合成 trendGo）
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
                "u.flights.unshift(f2);table();"
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
            nt0 = pg.inner_text("#ntBtn")
            pg.click("#ntBtn"); pg.wait_for_timeout(200)
            ck("通知开关", pg.inner_text("#ntBtn") != nt0)
            pg.click("#ntBtn")

            # ---- toast / 内联二次确认（v2.0 交互） ----
            step("arming + toast")
            btn = pg.query_selector("text=🔄 立即扫描一轮")
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
            # 演示为单用户：切换 pills 应隐藏不占位
            ck("单用户不显切换", not pg.is_visible("#userPills"))

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
            # ---- savebar 双行（112px）时 toast 恒差
            # 34px 重叠（视口高度无关）——savebar.on 在场抬到 148px，
            # 收起回 96px（:has 选择器行为钉） ----
            ck("savebar 在场 toast 抬升", pg.evaluate(
                "()=>{const sb=document.getElementById('savebar');"
                "const ts=document.getElementById('toasts');"
                "sb.classList.add('on');"
                "const up=getComputedStyle(ts).bottom;"
                "sb.classList.remove('on');"
                "const dn=getComputedStyle(ts).bottom;"
                "return up==='148px'&&dn==='96px';}"))
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
            pg.evaluate("togFlt()")   # 收起抽屉复位
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
                ".match(/(\\d+) \\/ /)||[])[1];"
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
            pg.click("#fltBtn"); pg.wait_for_timeout(400)
            ck("390 深滚开抽屉落点可见", pg.evaluate(
                "(()=>{const f=document.querySelector('.fbar');"
                "if(!f||!f.classList.contains('open'))return false;"
                "const t=document.querySelector('#montab-details .tabs');"
                "return f.getBoundingClientRect().top>="
                "t.getBoundingClientRect().bottom-2&&"
                "f.getBoundingClientRect().top<window.innerHeight;})()"))
            pg.evaluate("togFlt()")   # 收起抽屉复位
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
            pg.evaluate("window._hit=null;"
                "window._showLog0=window.showLog;"
                "window.showLog=(p,t)=>{window._hit=p+'|'+t;};")
            _tz = pg.evaluate("""()=>{
              const c=document.querySelector('.hcells');
              const cells=[...c.querySelectorAll('.hc')]
                .filter(x=>x.onclick&&!x.classList.contains('none'));
              if(cells.length<2)return null;
              const m=cells[0].getAttribute('onclick')
                .match(/'([^']*)','([^']*)'/);
              const r=cells[0].getBoundingClientRect();
              return {x:r.right+1,y:r.top+r.height/2,
                want:m?(m[1]+'|'+m[2]):''};}""")
            if _tz and _tz["want"]:
                pg.mouse.click(_tz["x"], _tz["y"])
                pg.wait_for_timeout(200)
                ck("coarse 缝缘点击近邻命中本格（off-by-one 修复）",
                   pg.evaluate("()=>window._hit||''") == _tz["want"])
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
              const r=cells[0].getBoundingClientRect();
              const m=cells[0].getAttribute('onclick')
                .match(/'([^']*)','([^']*)'/);
              return {x:r.left+r.width/2,y:r.top+r.height/2,
                want:m?(m[1]+'|'+m[2]):''};}""")
            if _tz2 and _tz2["want"]:
                pg.mouse.click(_tz2["x"], _tz2["y"])
                pg.wait_for_timeout(200)
                ck("coarse 非首行直击命中本行（跨行塌陷修复）",
                   pg.evaluate("()=>window._hit||''") == _tz2["want"])
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
            pg.wait_for_timeout(300)
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
            ck("1920 statline 全宽 + KPI 行放宽 1440（空腔收敛）",
               _kw["stW"] > _kw["cardW"] - 60
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
            ck("1920 cfg 内容卡随监控页突破", _cw["cv"] is not None
               and abs(_cw["cv"][0] - _al["chartL"]) < 3)
            ck("1920 cfg 标题条对齐", _cw["hd"] is not None
               and abs(_cw["hd"][0] - _cw["cv"][0]) < 3)
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
                "const inp=rl.querySelector('[id^=\"dpick-\"]');"
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
            ck("通道卡五张（未配邮件）", len(pg.query_selector_all(
               "#cfgform .chcard")) == 5)
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
                "return c.classList.contains('on')"
                "&&c.querySelector('.chhead .muted')"
                ".textContent==='已启用';}"))
            ck("图床通道卡", pg.query_selector(
               '#cfgform .chcard[data-ch="imghost"]') is not None)
            ck("图床 sm.ms 引导链接", pg.query_selector(
               '#cfgform a[href="https://sm.ms/home/apitoken"]')
               is not None)
            ck("图床切换显隐 Token 行（含展开态）", pg.evaluate(
                "()=>{const c=document.querySelector("
                "'#cfgform .chcard[data-ch=\"imghost\"]');"
                "const disp=()=>getComputedStyle("
                "c.querySelector('.ih-token')).display;"
                "const head=c.querySelector('.chhead');"
                "const folded=head.nextElementSibling"
                ".style.display==='none';"
                "head.click();"
                "const hiddenOnFree=folded&&disp()==='none'"
                "&&c.classList.contains('ih-free');"
                "const sm=[...c.querySelectorAll('.ihchip')]"
                ".find(x=>x.dataset.p==='smms');"
                "sm.click();"
                "const visOnSmms=c.classList.contains('ih-smms')"
                "&&disp()!=='none';"
                "const fi=[...c.querySelectorAll('.ihchip')]"
                ".find(x=>x.dataset.p==='freeimage');"
                "fi.click();"
                "const hiddenAgain=disp()==='none';"
                "head.click();"
                "delete (CFG[0].notifier||{}).image_host;"
                "return hiddenOnFree&&visOnSmms&&hiddenAgain;}"))
            ck("通道测试按钮", pg.query_selector("text=🔔 发测试弹窗")
               is not None and pg.query_selector("text=🔔 测试 ntfy")
               is not None)
            # 图床卡「测试上传」——demo 只读拦截下点按钮，
            # 结果行如实回显 403 摘要（按钮在场+JS 链路+结果行三合一）
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
            pg.wait_for_timeout(600)
            ck("图床测试上传按钮（demo 拦截如实报错）", _ihib and pg.evaluate(
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
                ck("删除确认态",
                   "arming" in (danger.get_attribute("class") or ""))
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
            ck("启动级只读", pg.evaluate(
                "()=>{const e=document.getElementById('glbDbp');"
                "return !!e&&e.readOnly;}"))
            pg.keyboard.press("Control+s")
            pg.wait_for_timeout(600)
            ck("Ctrl+S 保存", (pg.inner_text("#cfgmsg") or "").strip() != "")
            ck("配置分区导航", len(pg.query_selector_all("#cfgnav .cnav")) == 3)
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
            ck("搜索态全分区可见", pg.is_visible("#sec-login")
               and pg.is_visible("#sec-users")
               and pg.is_visible("#sec-globals-card"))
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
            pg.fill("#cfgSearch", ""); pg.wait_for_timeout(300)
            ck("清空登录卡复位", pg.evaluate(
                "()=>[...document.querySelectorAll('#cfgview .lgcard')]"
                ".every(d=>d.style.display===''&&d.style.boxShadow==='')"))
            pg.fill("#cfgSearch", ""); pg.wait_for_timeout(300)
            # 回用户面板做导入导出
            pg.click('#cfgnav .cnav[data-p="users"]')
            pg.wait_for_timeout(400)
            ck("导入导出按钮", pg.query_selector("text=📤 导出配置")
               is not None and pg.query_selector("text=📥 导入配置")
               is not None)
            with pg.expect_download() as cfgdl:
                pg.click("text=📤 导出配置")
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
            # ---- fetch 失败错误态：全部静态骨架语义 ----
            # pill 已明说「服务未启动」而表体仍静态「加载中…」=永不到达
            # 的假等待（两处语义矛盾）。fulfill 非 JSON 200（真实世界
            # 502/错误页同形：r.text() 成功而 JSON.parse 抛错进同一
            # catch）后 reload，四处骨架（ftable/loginRows/cfgglobals/
            # users）应同步置错误态；恢复轮 render()/loadCfg() 重写自愈。
            # 不用 abort：资源级 ERR_FAILED 会进 console error 污染套件。
            pg.route("**/api/state", lambda r: r.fulfill(
                status=200, content_type="text/plain",
                body="service unavailable"))
            pg.reload(wait_until="domcontentloaded"); pg.wait_for_timeout(1500)
            ck("错误态 pill 服务未启动",
               "服务未启动" in (pg.text_content("#pill") or ""))
            ck("错误态表体不再假等待「加载中…」", pg.evaluate(
                "()=>{const t=(document.getElementById('ftable')"
                ".innerText||'').trim();"
                "return t.indexOf('加载中')<0&&t.indexOf('服务未启动')>=0;}"))
            ck("错误态配置区同步置错误态", pg.evaluate(
                "()=>{const g=document.getElementById('cfgglobals');"
                "return !!g&&(g.innerText||'').indexOf('服务未启动')>=0;}"))
            ck("错误态概览骨架不再假等待", pg.evaluate(
                "()=>{const u=document.getElementById('users');"
                "return !!u&&(u.innerText||'').indexOf('服务未启动')>=0"
                "&&u.querySelectorAll('.sk').length===0;}"))
            # （错误态家族第 5 处收口）走势空态在 fetch 失败时
            # 同步置错误态——静态教学词面「完成第一轮扫描」不再与
            # pill「服务未启动」同屏自证矛盾（空态在场才翻新，
            # 已绘制图表 display:none 不动）
            ck("错误态走势空态不再假教学", pg.evaluate(
                "()=>{const e=document.getElementById('chartEmpty');"
                "const t=(e.textContent||'');"
                "return t.indexOf('服务未启动')>=0"
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
            # 同一 evaluate 原子化：savebar 泄漏修复后巡检全视图每拍
            # 回收 on 类（含监控视图），拆两条语句会被 800ms 拍竞态摘类
            pg.evaluate("()=>toast('钉','ok')")
            pg.wait_for_timeout(80)
            ck("桌面 savebar 在场 toast 抬升 96px", pg.evaluate(
                "()=>{const sb=document.querySelector('.savebar');"
                "sb.classList.add('on');"
                "const b=document.getElementById('toasts');"
                "const v=!!b&&getComputedStyle(b).bottom==='96px';"
                "sb.classList.remove('on');return v;}"))
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
            # 红帽徽标：最新轮有渠道失败时概览 tab 点亮红点（脉冲卡移入
            # 概览后，渠道异常在其他 tab 仍全局可见——渠道健康可见定律）
            ck("EN-1 红帽徽标随最新轮失败点亮/熄灭", pg.evaluate(
                "()=>{if(typeof renderPulseAlert!=='function')return false;"
                "renderPulseAlert(2);"
                "const on=document.getElementById('ovAlert')"
                ".style.display!=='none';"
                "renderPulseAlert(0);"
                "const off=document.getElementById('ovAlert')"
                ".style.display==='none';return on&&off;}"))
            # EN-9（WebUI 审计）：徽标读屏语义——role+aria-label 静态
            # 在位（display:none 天然从可访问性树移除，点亮即暴露），
            # 渠道异常可见性定律对读屏不再缺失
            ck("EN-9 红帽徽标读屏语义在位", pg.evaluate(
                "()=>{const a=document.getElementById('ovAlert');"
                "return !!a&&a.getAttribute('role')==='img'"
                "&&(a.getAttribute('aria-label')||'')"
                ".indexOf('渠道失败')>=0;}"))
            # EN-2 桌面视图切换器吸顶：深滚切视图不回滚（≤540 同款能力）。
            # 几何行为钉（LESSONS：源码钉只证声明在场，几何钉是唯一真相）
            pg.set_viewport_size({"width": 1440, "height": 900})
            pg.evaluate("gotoMonTab('details')"); pg.wait_for_timeout(500)
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
            pg.evaluate("gotoMonTab('details')"); pg.wait_for_timeout(400)
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
                "()=>{window.scrollTo(0,0);"
                "const r=document.querySelector('#ftable tbody tr[data-k]');"
                "if(!r)return false;"
                "return r.getBoundingClientRect().top"
                "<window.innerHeight*0.72;}"))
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
                "const msg=(eb&&eb.textContent||'').indexOf('5-720')>=0;"
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
                "const r=ts[3].getBoundingClientRect();"
                "return {h:r.height,inside:r.top>=cr.top-1&&"
                "r.bottom<=cr.bottom+1,n:ts.length,"
                "sw:mb.scrollWidth,cw:mb.clientWidth,"
                "xh:mb.classList.contains('xhint'),"
                "vis:mb.offsetParent!==null};}")
            ck("390 档切换器第四格完整在容器", bool(
                _w1 and _w1.get("n") == 4 and _w1.get("h", 0) >= 30
                and _w1.get("inside") and _w1.get("vis")))
            # 溢出暗示阈值判定：EN-6 字号归并后 390 档内容溢出收窄至
            # 3px（<4px「可滚才挂」阈值）——暗示不亮是正确行为（3px
            # 裁角不值得横滚），钉住「容差内放下不误挂」新事实
            ck("390 档切换器容差内放下暗示不误挂", bool(
                _w1 and not _w1.get("xh")
                and _w1.get("sw", 0) <= _w1.get("cw", 0) + 4))

            # ---- EN-W4 行为钉：mtab 方向键族移动 + Enter 激活 ----
            pg.evaluate(
                "document.querySelectorAll('#montabs .mtab')[2].focus()")
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
            pg.evaluate("gotoMonTab('details')")
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
                const ok=top>=hd+mt-6&&top<200;
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
                  showMonTab('details');
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
            ck("W-1 动作件显式锚进确认态", pg.evaluate(
                "()=>{const b=document.createElement('button');"
                "document.body.appendChild(b);let ok=false;"
                "try{delUser(0,b);}catch(e){b.remove();return false;}"
                "ok=b.classList.contains('arming');"
                "setTimeout(()=>{if(b.parentNode)b.remove();},3200);"
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
            # WC-P2-1 delEm 二次确认：首击进 arming 不 splice（.danger
            # 家族行为对齐 delRoute/delUser）
            ck("WC-P2-1 delEm 首击确认态", pg.evaluate(
                "()=>{const n0=(ems(0)||[]).length;"
                "const b=document.createElement('button');"
                "document.body.appendChild(b);let ok=false;"
                "try{delEm(0,0,b);}catch(e){b.remove();return false;}"
                "ok=b.classList.contains('arming')"
                "&&(ems(0)||[]).length===n0;"
                "delete b.dataset.arming;"
                "setTimeout(()=>{if(b.parentNode)b.remove();},50);"
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
                "const it=document.querySelector('#pvMask .plitem');"
                "if(it)it.click();"
                "await new Promise(r=>setTimeout(r,80));"
                "const a=document.querySelector('#pvMask .pvbody a');"
                "if(!a)return 'no-a items='+(!!it);"
                "a.focus({focusVisible:true});"
                "const sh=getComputedStyle(a).boxShadow;"
                "closePv();"
                "return 'sh='+sh+' active='+(document.activeElement===a);}")
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
            # WC-P2-4 armConfirm 锁首态宽（对齐 api()——确认文案更短
            # 曾让同排控件整体位移）
            ck("WC-P2-4 armConfirm 锁宽", pg.evaluate(
                "()=>{const b=document.createElement('button');"
                "b.className='danger';b.textContent='✕ 删除用户 测试';"
                "document.body.appendChild(b);"
                "const w0=b.getBoundingClientRect().width;"
                "try{delUser(0,b);}catch(e){b.remove();return false;}"
                "const w1=b.getBoundingClientRect().width;"
                "delete b.dataset.arming;"
                "setTimeout(()=>{if(b.parentNode)b.remove();},50);"
                "return w1>=w0-0.5;}"))
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
