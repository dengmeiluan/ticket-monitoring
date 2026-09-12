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
            urllib.request.urlopen(BASE + "/api/state", timeout=2)
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
            pg.on("pageerror", lambda e: errors.append(str(e)))
            step("goto")
            pg.goto(BASE, wait_until="domcontentloaded")
            pg.wait_for_timeout(2500)

            # ---- 总览区（默认概览子视图） ----
            ck("页面标题", "机票监控台" in pg.title())
            ck("达标 pill", "已达标" in pg.inner_text("#pill"))
            ck("演示横幅", pg.is_visible("#demoBar"))
            ck("KPI 直飞价", "￥" in pg.inner_text(".kpi.d .num"))
            ck("KPI 达标光晕", len(pg.query_selector_all(".kpi.hit")) >= 1)
            ck("航线 chips≥3", len(pg.query_selector_all("#chartRoutes .chip")) >= 3)

            # ---- V50 子视图工作台 ----
            ck("子视图 4 tab",
               len(pg.query_selector_all("#montabs .mtab")) == 4)
            ck("概览默认可见", pg.is_visible("#montab-overview"))
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

            # ---- 渠道健康子视图 + 日志弹层 ----
            pg.click('.mtab[data-t="health"]'); pg.wait_for_timeout(400)
            ck("健康 5 渠道", len(pg.query_selector_all(".hrow")) == 5)
            cells = pg.query_selector_all(".hc.ok")
            ck("健康格可点", bool(cells))
            if cells:
                cells[0].click(); pg.wait_for_timeout(600)
                ck("日志弹层", pg.query_selector(".logpre") is not None)
                pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
                ck("Esc 关日志", "on" not in (pg.get_attribute("#pvMask", "class") or ""))

            # ---- V50 运行脉冲 ----
            ck("脉冲 statline 4 格",
               len(pg.query_selector_all("#statline .stat")) == 4)
            ck("脉冲轮次柱≥30",
               len(pg.query_selector_all("#pulsebars .pbar")) >= 30)
            ck("脉冲柱含渠道分段",
               len(pg.query_selector_all("#pulsebars .seg")) > 0)
            ck("脉冲图例渠道色",
               len(pg.query_selector_all("#pulseLegend .pseg-qunar")) >= 1)
            ck("/api/pulse 端点", pg.evaluate(
                "()=>fetch('/api/pulse').then(r=>r.json())"
                ".then(j=>j.ok&&j.rounds.length>0)"))

            # ---- 推送预览 ----
            pg.click("#pvBtn"); pg.wait_for_timeout(700)
            ck("预览标题🚨", pg.inner_text("#pvTitle").startswith("🚨"))
            ck("预览含链接", len(pg.query_selector_all("#pvBody a")) > 0)
            ck("预览含进度条", "🟦" in pg.inner_text("#pvBody")
               or "⬜" in pg.inner_text("#pvBody"))
            pg.keyboard.press("Escape"); pg.wait_for_timeout(200)

            # ---- 推送记录回看（v3.0）----
            pg.click('button:has-text("推送记录")'); pg.wait_for_timeout(700)
            ck("推送记录弹层", "推送记录" in pg.inner_text("#pvTitle"))
            ck("推送记录条目", len(pg.query_selector_all(".plitem")) >= 1)
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

            # ---- 航班明细子视图 ----
            pg.click('.mtab[data-t="details"]'); pg.wait_for_timeout(400)
            n_all = len(pg.query_selector_all("#ftable tbody tr"))
            pg.click('#tabs span[data-f="d"]'); pg.wait_for_timeout(300)
            tags = pg.query_selector_all("#ftable tbody tr .tag")
            ck("直飞 tab 过滤", tags and all(
                "直飞" in t.inner_text() for t in tags))
            pg.click('#tabs span[data-f="all"]'); pg.wait_for_timeout(200)
            pg.fill("#fq", "MU"); pg.keyboard.press("Enter")
            pg.wait_for_timeout(300)
            n_mu = len(pg.query_selector_all("#ftable tbody tr"))
            ck("搜索 MU 过滤", 0 < n_mu < n_all)
            pg.fill("#fq", ""); pg.keyboard.press("Enter")
            pg.wait_for_timeout(200)
            pg.click("th.srt"); pg.wait_for_timeout(200)
            ck("排序切换", "on" in (pg.get_attribute("th.srt", "class") or ""))
            rows = pg.query_selector_all("#ftable tbody tr:not(.xrow)")
            if rows:
                n_tr = pg.evaluate(
                    "document.querySelectorAll('#ftable tr').length")
                rows[0].click(); pg.wait_for_timeout(300)
                ck("同班比价展开", pg.evaluate(
                   "()=>{const x=document.querySelector('#ftable tr.xrow');"
                   "return !!x&&x.style.display!=='none';}"))
                ck("展开零节点插拔（扩展/翻译免疫）",
                   n_tr == pg.evaluate(
                       "document.querySelectorAll('#ftable tr').length"))
                pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
                ck("Esc 收起展开", pg.evaluate(
                   "()=>[...document.querySelectorAll('#ftable tr.xrow')]"
                   ".every(x=>x.style.display==='none')"))

            # ---- CSV 导出 ----
            step("csv download")
            with pg.expect_download() as dl_info:
                pg.click("text=⬇ 导出CSV")
            ck("CSV 导出", dl_info.value.suggested_filename.endswith(".csv"))

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
            ck("筛选抽屉按钮", pg.is_visible("#fltBtn"))
            pg.click("#fltBtn"); pg.wait_for_timeout(300)
            ck("抽屉展开", "open" in (pg.get_attribute(".fbar", "class") or ""))
            pg.set_viewport_size({"width": 1280, "height": 900})

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
            ck("全局热配置项", all(pg.query_selector(s) for s in
               ["#glbIv", "#glbJt", "#glbPort", "#glbHl",
                "#glbTo", "#glbDn", "#glbDx", "#glbUa"]))
            ck("热加载文案（旧重启话术已移除）",
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
                for t in ("基础", "监控平台", "航线", "通知渠道")))
            ck("通道卡四张", len(pg.query_selector_all(
               "#cfgform .chcard")) == 4)
            ck("Server酱通道卡", pg.query_selector(
               '#cfgform .chcard[data-ch="serverchan"]') is not None)
            ck("通道测试按钮", pg.query_selector("text=🔔 发测试弹窗")
               is not None and pg.query_selector("text=🔔 测试 ntfy")
               is not None)
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
            ck("启动级只读", pg.evaluate(
                "()=>{const e=document.getElementById('glbDbp');"
                "return !!e&&e.readOnly;}"))
            pg.keyboard.press("Control+s")
            pg.wait_for_timeout(600)
            ck("Ctrl+S 保存", (pg.inner_text("#cfgmsg") or "").strip() != "")
            ck("配置分区导航", len(pg.query_selector_all("#cfgnav .cnav")) == 3)
            ck("浮出保存条", pg.is_visible("#savebar"))
            ck("脏计数显示", "处" in pg.inner_text("#saveTxt"))
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
