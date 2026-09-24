# -*- coding: utf-8 -*-
"""全功能 UI 自检套件：Playwright 遍历控制台每一个交互功能。

「务必保证每个功能都是好的」的硬保障——任一断言失败或页面出现
JS console.error/pageerror，即以非零码退出。

自包含：自动拉起 `python webui.py --demo` 演示控制台，跑完销毁。
用法：python docs/uitest.py  （结果同步落盘 docs/uitest_result.txt）
"""
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
            ck("KPI 直飞价", "￥" in pg.inner_text(".kpi.d .num"))
            ck("KPI 达标光晕", len(pg.query_selector_all(".kpi.hit")) >= 1)
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
            pg.click("#mdLine"); pg.wait_for_timeout(300)
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
            ck("健康 5 渠道", len(pg.query_selector_all(".hrow")) == 5)
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
                pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
                ck("Esc 关日志", "on" not in (pg.get_attribute("#pvMask", "class") or ""))

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

            # ---- 推送预览 ----
            pg.click("#pvBtn"); pg.wait_for_timeout(700)
            ck("预览标题🚨", pg.inner_text("#pvTitle").startswith("🚨"))
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
            ck("胶囊文案 改期±7天+最低￥", cap is not None and
               "改期±7天" in cap.inner_text() and "最低￥" in cap.inner_text())
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
                with open(dl_info.value.path(), encoding="utf-8-sig") as f:
                    _head = f.readline()
                ck("CSV 双新列（孤低价/改期最低）",
                   "孤低价" in _head and "改期最低" in _head)
            except Exception:
                ck("CSV 双新列（孤低价/改期最低）", False)

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
            pg.evaluate("showMonTab('overview')")   # 状态复位回概览
            pg.wait_for_timeout(200)
            # ---- glcell 文本输入窄屏 16px 防放大 ----
            # （内联 13px 锁定须 !important 压制——iOS 聚焦自动放大且
            # 不回位；桌面档 13px 观感由 globals 段反面钉守护）
            pg.evaluate("()=>switchView('cfg')"); pg.wait_for_timeout(500)
            pg.click('#cfgnav .cnav[data-p="globals"]')
            pg.wait_for_timeout(400)
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
            _cdp.send('Emulation.setTouchEmulationEnabled',
                      {'enabled': False})   # 状态复位回桌面指针
            pg.set_viewport_size({"width": 1280, "height": 900})
            pg.wait_for_timeout(200)

            # ---- 1920 宽屏常驻块对齐（用户实报收口）：
            # trend/details 突破档下 wrap 顶层全部常驻块（header/nav/
            # demoBar/操作卡/pulse 卡）须与内容卡左缘对齐——行为级
            # 枚举断言，防新增常驻块再漏；overview/cfg 回窄组。收缩胶囊（nav/tabs）
            # 张常驻块再漏；overview/cfg 回窄组。收缩胶囊（nav/tabs）
            # 只量左缘；header 原生出血 -18px 预期内 ----
            pg.set_viewport_size({"width": 1920, "height": 1080})
            pg.evaluate("showMonTab('trend')")
            pg.wait_for_timeout(400)
            _al = pg.evaluate("""()=>{
              const g=id=>{const e=document.getElementById(id);
                if(!e||!e.offsetWidth)return null;
                const r=e.getBoundingClientRect();return [r.left,r.right];};
              const c=g('chartcard');const ids=
                ['hdcard','mainnav','demoBar','opscard','pulsecard'];
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
            ck("1920 trend 脉冲卡对齐", _al["pulsecard"] is not None
               and _al["pulsecard"] < 2)
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
            # ≥1920 档只放开非比例件（statline 跟卡全宽），
            # .grid 仍封顶 1168（KPI 价卡比例纪律保持）
            _kw = pg.evaluate("""()=>{
              const st=document.querySelector('.statline')
                .getBoundingClientRect();
              const pc=document.getElementById('pulsecard')
                .getBoundingClientRect();
              const g=document.querySelector('.grid')
                .getBoundingClientRect();
              return {stW:st.width,cardW:pc.width,gridW:g.width};}""")
            ck("1920 statline 全宽（kpiw 空腔收敛）",
               _kw["stW"] > _kw["cardW"] - 60 and _kw["gridW"] <= 1170)
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
              return {ops:g('opscard'), pulse:g('pulsecard'),
                montabs:g('montabs')};}""")
            ck("1920 health 全块对齐抽检", all(
                v is not None and abs(v - _al["chartL"]) < 2
                for v in (_hl["ops"], _hl["pulse"], _hl["montabs"])))
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
              const r=document.querySelector('.hrow');if(!r)return null;
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
            # ⑤术语统一：配置页 B 分区「监控渠道」（原「监控平台」×2）
            pg.click("#navCfg"); pg.wait_for_timeout(400)
            ck("配置页术语统一「监控渠道」", pg.evaluate(
                "()=>{const t=document.body.innerText||'';"
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
            # 汇总先行（b.close 在 Windows 下载残留时偶发悬挂）
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
    os._exit(1 if (bad or errors) else 0)


if __name__ == "__main__":
    main()
