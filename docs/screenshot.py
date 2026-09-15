# -*- coding: utf-8 -*-
"""控制台 README 截图生成（演示模式 + Playwright，JS 错误顺带体检）。

用法：
    python webui.py --demo --port 8799        # 先起演示控制台
    python docs/screenshot.py                 # 截图到 docs/screenshots/

产出：console-light / console-dark / console-preview / console-mobile。
任何 JS console.error / pageerror 都会以非零码退出（发版前兜底）。
"""
import os
import sys

from playwright.sync_api import sync_playwright

BASE = os.environ.get("CONSOLE_URL", "http://127.0.0.1:8799")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots")


def main():
    os.makedirs(OUT, exist_ok=True)
    errors = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1280, "height": 900})
        pg.on("console",
              lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(BASE, wait_until="networkidle")
        pg.wait_for_timeout(1500)

        def theme(t):
            pg.evaluate(
                "localStorage.setItem('jptheme','%s');location.reload()" % t)
            pg.wait_for_timeout(1100)

        theme("light")
        pg.screenshot(path=os.path.join(OUT, "console-light.png"),
                      full_page=True)
        # 走势子视图（折线+日历）暗色：覆盖 canvas 暗色渲染
        pg.click('.mtab[data-t="trend"]')
        pg.wait_for_timeout(700)
        theme("dark")
        pg.screenshot(path=os.path.join(OUT, "console-dark.png"),
                      full_page=True)
        # 推送预览弹层（暗色下再截一张，覆盖弹层渲染）
        pg.click("#pvBtn")
        pg.wait_for_timeout(700)
        pg.screenshot(path=os.path.join(OUT, "console-preview.png"))
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(300)
        # K线模式（蜡烛图组件）
        pg.click("#mdK")
        pg.wait_for_timeout(600)
        pg.screenshot(path=os.path.join(OUT, "console-kline.png"))
        pg.click("#mdLine")
        pg.wait_for_timeout(300)
        # 航班明细子视图（工作台表格）
        pg.click('.mtab[data-t="details"]')
        pg.wait_for_timeout(400)
        pg.screenshot(path=os.path.join(OUT, "console-details.png"))
        # 配置页（面板式设置台：用户与航线面板）
        pg.click("#navCfg")
        pg.wait_for_timeout(900)
        pg.click('#cfgnav .cnav[data-p="users"]')
        pg.wait_for_timeout(700)
        pg.screenshot(path=os.path.join(OUT, "console-config.png"))
        # 全局配置中心（调度/采集热载 + 启动级只读三组）
        pg.click('#cfgnav .cnav[data-p="globals"]')
        pg.wait_for_timeout(700)
        pg.screenshot(path=os.path.join(OUT, "console-globals.png"))
        # 移动端（筛选抽屉 + 首列吸附）
        pg.set_viewport_size({"width": 390, "height": 844})
        pg.click("#navMon")
        pg.wait_for_timeout(600)
        theme("light")
        pg.screenshot(path=os.path.join(OUT, "console-mobile.png"),
                      full_page=True)
        b.close()
    if errors:
        print("!! 页面 JS 错误：")
        for e in errors[:10]:
            print("   -", e[:200])
        sys.exit(1)
    print("截图完成（无 JS 错误）：")
    for f in sorted(os.listdir(OUT)):
        print("  ", os.path.join(OUT, f))


if __name__ == "__main__":
    main()
