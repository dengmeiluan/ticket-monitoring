# -*- coding: utf-8 -*-
"""r324 配置面「入口全链路」回归套件（用户令：同族交互 bug 不允许再出现）。

背景：C9（城市面板点选从未写进模型——cityPanelPick 在 cityPanelClose
置 _cpEl=null 之后才 dispatchEvent，TypeError 被吞）暴露出 475 颗 uitest
钉全绿但面板从诞生起就是坏的——因为所有既有测试都绕过入口直接
dispatchEvent/直调处理器。本套件对配置页每一个用户可达的交互入口用
**真实 UI 路径**（Playwright locator click/fill/真实面板点选，禁止
evaluate 直调 setRoute/setN 等处理器，禁止手工 dispatchEvent 代替入口
交互）驱动，然后三面断言：
  ① 模型已写（CFG/GLB 真值）；
  ② UI 已随（卡头/pill/gsum/chips 等投影面）；
  ③ 该步骤零 console error（pageerror+console error 收集器挂 page 上，
     任何一步带入即该用例红——fixture teardown 统一裁决）。

入口覆盖（编号=审计 _scratch/r324_cfgsync_audit.md §一 写点族）：
  §1  W1  用户名输入
  §2  W2  聚合推送/日报时刻/风暴连推/降价涨价阈值/免打扰/🔔弹窗
  §3  W3  监控渠道 chips（togPlat）
  §4  W4/W5/W6  阿里云 URL / ntfy 主题 / Server酱 SendKey（enabled 派生）
  §5  W7-W10  邮件通道：addEm/delEm/emHost 163·QQ/SMTP 五字段/启用
  §6  W11 钉钉 webhook/secret/at_mobile/启用
  §7  W12 图床 provider 三 chip + repo/ghtoken/proxy
  §8  W13 航线卡：城市面板全真链（C9 病灶路径，最高优先）+ 心理价/
      中转最晚到达/最短衔接/直挂
  §9  W14 航线启停开关
  §10 W15 特价：启用/出发城市（城市面板）/心理价/未来天数/返程配对
  §11 W16/W17 日期三通道（文本回车/➕按钮/日期片✕；📅 showPicker 是
      浏览器原生日历，Playwright 无法驱动原生弹层——跳过并在此注明）
  §12 W24/W25 出发时段快捷挡 chips + 手输 time
  §13 W22/W23 复制/删除航线（armConfirm 两段确认走完整机制）
  §14 W19/W20 添加/删除用户（armConfirm 两段确认）
  §15 W26/W27 G 区 globals 输入族 + 无头开关 + glbCheck 校验面
  §16 W29-W33 折叠（分区/航线卡/通道卡）+ 手风琴 + cnav 面板切换 + 配置搜索
  §17 W34/W35/W36 导入文件（Playwright set_input_files 是文件输入的正规
      真实通道：向 #cfgImport 投递真 File 并触发原生 change——与用户
      选完文件点打开完全同构，故不跳过）/保存（demo 只读门 403 拦截
      →失败分支词面钉；403 会产生一条浏览器网络 console error，属该
      失败分支固有产物，本用例显式豁免这一条）/放弃更改
  另：W28 setOpenUser 经 §16 手风琴覆盖；W32 视图切换经 _to_cfg 的
  #navCfg 真点击 + §16 cnav 覆盖。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r324_entry_cfg.py -q
（自起 python webui.py --demo --port <空闲端口>，用完自杀；缺 playwright
 或 chromium SKIP 不 ERROR。）

判定纪律（C9 教训注入）：
- 「UI 值已变」≠「模型已写」——每个用例同时断言 CFG/GLB 与投影面；
- 凡带独立确认机制的入口（城市面板/armConfirm 两段/手风琴/折叠）走完整机制；
- locator.fill 只发 input 不发 change——统一 _fill() 尾按 Tab 真实失焦
  触发 change（同构真实录入）；seed 与 fill 恒不同值（同值 fill 不触发
  change）；
- 深位元素先 scrollIntoView({behavior:'instant'}) 再 locator click
  （本页 flashEl 平滑滚动吃 actionability 预算）。
"""
import os
import sys

import pytest

pytest.importorskip("playwright",
                    reason="行为钉依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = None
BASE = None


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_up(proc):
    import time
    import urllib.request
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(40):
        if proc.poll() is not None:
            return False
        try:
            op.open(BASE + "/api/state", timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


@pytest.fixture(scope="module")
def srv():
    global PORT, BASE
    import subprocess
    import tempfile
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if not os.path.exists(p.chromium.executable_path):
            pytest.skip("chromium 二进制缺失（CI 无 playwright install）")
    logf = tempfile.TemporaryFile(mode="w+", encoding="utf-8",
                                  errors="replace")
    import tempfile as _tf
    priv_tmp = _tf.mkdtemp(prefix="r324en_")
    env = dict(os.environ, TEMP=priv_tmp, TMP=priv_tmp,
               TMPDIR=priv_tmp)
    proc = None
    for _attempt in (1, 2):
        PORT = _free_port()
        BASE = "http://127.0.0.1:%d" % PORT
        proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
             "--port", str(PORT)],
            cwd=ROOT, stdout=logf, stderr=subprocess.STDOUT, env=env)
        if _wait_up(proc):
            break
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass
    else:
        try:
            proc.kill()
        except Exception:
            pass
        pytest.fail("demo 启动失败（两次新端口重试后）")
    yield proc
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    logf.close()


@pytest.fixture()
def page(srv):
    """每用例独立 context（localStorage/FOLD/OPEN_USER 全新）+ 独立
    console/pageerror 收集器；teardown 统一裁决「零带入」（_expected
    里的词面豁免除外——目前仅 demo 保存 403 这条固有网络日志）。"""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        pg = ctx.new_page()
        errs = []
        pg._errs = errs
        pg._expected = []
        pg.on("pageerror", lambda e: errs.append(("pageerror", str(e))))
        pg.on("console", lambda m: errs.append(("console.error", m.text))
              if m.type == "error" else None)
        pg.set_default_timeout(8000)
        yield pg
        leftover = [e for e in errs
                    if not any(pat in e[1] for pat in pg._expected)]
        assert not leftover, "console/pageerror 带入: %r" % leftover
        browser.close()


# ---------- 真实 UI 管线助手（禁止直调处理器/手工 dispatchEvent） ----------

def _to_cfg(pg):
    """监控页→真点击⚙️配置导航→等 CFG→真点击「用户与航线」cnav。
    配置视图初始面板是 login（CFGPANEL 缺省），users 面板必须经 cnav
    真点击进入——这一步本身就是 W31 入口。"""
    pg.goto(BASE + "/")
    pg.wait_for_function("typeof S !== 'undefined' && S && S.users")
    pg.locator("#navCfg").click()
    pg.wait_for_function("typeof CFG !== 'undefined' && CFG && CFG.length")
    pg.locator('.cnav[data-p="users"]').click()
    pg.wait_for_timeout(250)


def _scrollin(pg, sel):
    pg.evaluate(
        "(s)=>{const el=document.querySelector(s);"
        "if(el)el.scrollIntoView({block:'center',behavior:'instant'});}", sel)


def _click(pg, sel):
    """深位元素真点击：先瞬时滚入（平滑滚动吃预算的实锤规避）再
    locator click（完整 actionability 管线，非 JS click）。"""
    _scrollin(pg, sel)
    pg.locator(sel).first.click()


def _fill(pg, sel, val):
    """真 fill + Tab 失焦：fill 只发 input，change 由真实焦点移出触发
    （与手输后点别处同构）。seed 与 fill 恒须不同值（同值不触发）。"""
    _scrollin(pg, sel)
    loc = pg.locator(sel).first
    loc.fill(val)
    pg.keyboard.press("Tab")


def _txt(pg, sel):
    return pg.evaluate(
        "(s)=>{const el=document.querySelector(s);"
        "return el?el.textContent.trim():null;}", sel)


def _open_dtools(pg, rk="0:0"):
    """按卡展开「＋ 添加」工具组（r339g 二合一后 dadd/加日期住在
    display:none 折叠行里；buildForm 重建会重置折叠态，每次变更后
    需再展开——LESSONS 十九§7/§8 + 十一§3 重建吞交互态）。"""
    dsel = '.rline[data-rk="%s"] .dline.dtools' % rk
    if pg.locator(dsel).first.count() \
            and not pg.locator(dsel).first.evaluate(
                "el=>el.classList.contains('open')"):
        _click(pg, '.rline[data-rk="%s"] .dtools-t' % rk)


def _open_rtadv(pg, rk="0:0"):
    """展开「筛选与时段约束」折叠组（r339 起中转/时段/筛选行默认收起——
    A1 P1 修复后 foldRoute 展开路由不再连带展开内层折叠，操作行前须
    显式展开）。"""
    pg.evaluate("""((rk) => {
      const rt=document.querySelector(
        '.rline[data-rk="'+rk+'"] .rthead');
      if(rt&&rt.getAttribute('aria-expanded')==='false')rt.click();
    })""", rk)
    pg.wait_for_timeout(120)


def _open_route(pg, rk="0:0"):
    """真点击航线卡头展开（全新 context 下 FOLD 空 → 默认折叠态确定）。"""
    sel = '.rline[data-rk="%s"] .rhead' % rk
    assert pg.locator(sel).first.get_attribute("aria-expanded") == "false", sel
    _click(pg, sel)
    assert pg.locator(sel).first.get_attribute("aria-expanded") == "true", sel
    _open_dtools(pg, rk)


def _open_ch(pg, key):
    """幂等展开通道卡：addEm 后新卡自动展开（r343），不得再强断言首态。"""
    sel = '.chcard[data-ch="%s"] .chhead' % key
    if pg.locator(sel).first.get_attribute("aria-expanded") == "false":
        _click(pg, sel)
    assert pg.locator(sel).first.get_attribute("aria-expanded") == "true", sel


_SNAP = """
(() => ({glb: JSON.parse(JSON.stringify(GLB)),
        users: JSON.parse(JSON.stringify(CFG))}))()
"""


def _restore(pg, snapshot):
    """模型快照还原 + buildForm 全量重建（测试收尾态复位；测试管线，
    非入口交互）。"""
    pg.evaluate("""((snap) => {
      CFG.length = 0;
      for (const u of snap.users) CFG.push(JSON.parse(JSON.stringify(u)));
      GLB = JSON.parse(JSON.stringify(snap.glb));
      buildForm();
    })""", snapshot)


# ================= §1 用户名（W1） =================

class TestW1Name:
    def test_rename_writes_model_and_head(self, page):
        _to_cfg(page)
        snap = page.evaluate(_SNAP)
        try:
            sel = '#cfgform input[onchange*="CFG[0].name"]'
            _fill(page, sel, "入口改名甲")
            out = page.evaluate("""(() => {
              const head = document.querySelector('#cfgform .ucard .uhead2');
              const del = document.querySelector(
                '#cfgform button[onclick^="delUser"]');
              return {model: CFG[0].name,
                      headName: head.querySelector('b').textContent,
                      uava: head.querySelector('.uava').textContent,
                      delBtn: (del.getAttribute('aria-label')||'').trim()};
            })()""")
            assert out["model"] == "入口改名甲", out
            assert out["headName"] == "入口改名甲", out
            assert out["uava"] == "入", out
            assert "入口改名甲" in out["delBtn"], out
            # S6 巡检面（≤800ms）：未保存徽标亮起
            page.wait_for_timeout(1000)
            disp = page.evaluate(
                "()=>document.getElementById('udirty-0').style.display")
            assert disp == "inline-block", disp
        finally:
            _restore(page, snap)


# ================= §2 推送行为（W2 族） =================

class TestW2Notifier:
    def test_digest_switch(self, page):
        _to_cfg(page)
        snap = page.evaluate(_SNAP)
        try:
            sel = '#cfgform input[onchange*="setN(0,\'digest\'"]'
            _click(page, sel)
            assert page.evaluate("CFG[0].notifier.digest") is True
            assert page.locator(sel).first.is_checked()
        finally:
            _restore(page, snap)

    def test_numeric_notifier_fields(self, page):
        _to_cfg(page)
        snap = page.evaluate(_SNAP)
        try:
            for key, val in (("report_hour", "9"), ("storm_repeat", "5"),
                             ("push_drop_min", "88"), ("push_rise_min", "66")):
                _fill(page,
                      '#cfgform input[onchange*="setN(0,\'%s\'"]' % key, val)
                assert str(page.evaluate(
                    "CFG[0].notifier.%s" % key)) == val, key
        finally:
            _restore(page, snap)

    def test_quiet_window(self, page):
        _to_cfg(page)
        snap = page.evaluate(_SNAP)
        try:
            _fill(page, '#cfgform input[onchange*="\'quiet_start\'"]',
                  "23:00")
            _fill(page, '#cfgform input[onchange*="\'quiet_end\'"]',
                  "07:30")
            assert page.evaluate("CFG[0].notifier.quiet_start") == "23:00"
            assert page.evaluate("CFG[0].notifier.quiet_end") == "07:30"
        finally:
            _restore(page, snap)

    def test_win_toast_pill_follows(self, page):
        _to_cfg(page)
        snap = page.evaluate(_SNAP)
        try:
            sel = '#cfgform input[onchange*="setN(0,\'win_toast\'"]'
            assert page.evaluate("CFG[0].notifier.win_toast") is True
            _click(page, sel)
            out = page.evaluate("""(() => {
              const p = document.querySelectorAll(
                '#cfgform .ucard .uhead2 .upill')[2];
              return {t: p.textContent.trim(), ok: p.classList.contains('ok'),
                      aHead: document.querySelector(
                        '#cfgform .grouplab[data-sec="A"] .gsum').textContent};
            })()""")
            assert page.evaluate("CFG[0].notifier.win_toast") is False
            assert out["t"] == "弹窗 关" and not out["ok"], out
            assert "弹窗关" in out["aHead"], out
        finally:
            _restore(page, snap)


# ================= §3 监控渠道 chips（W3 togPlat） =================

class TestW3Platforms:
    def test_chip_roundtrip_model_and_bhead(self, page):
        _to_cfg(page)
        snap = page.evaluate(_SNAP)
        try:
            sel = '#cfgform .pch.p-ctrip'
            assert page.evaluate("CFG[0].platforms.length") == 5
            _click(page, sel)
            out = page.evaluate("""(() => ({
              n: CFG[0].platforms.length,
              has: CFG[0].platforms.includes('ctrip'),
              on: document.querySelector('#cfgform .pch.p-ctrip')
                   .classList.contains('on'),
              bHead: document.querySelector(
                '#cfgform .grouplab[data-sec="B"] .gsum').textContent}))()""")
            assert out["n"] == 4 and not out["has"] and not out["on"], out
            assert out["bHead"] == "4 / 5 渠道", out
            _click(page, sel)   # 再点回：勾选路径同钉
            out = page.evaluate("""(() => ({
              n: CFG[0].platforms.length,
              has: CFG[0].platforms.includes('ctrip'),
              on: document.querySelector('#cfgform .pch.p-ctrip')
                   .classList.contains('on'),
              bHead: document.querySelector(
                '#cfgform .grouplab[data-sec="B"] .gsum').textContent}))()""")
            assert out["n"] == 5 and out["has"] and out["on"], out
            assert out["bHead"] == "5 / 5 渠道", out
        finally:
            _restore(page, snap)


# ============ §4 通道派生启用（W4 阿里云 / W5 ntfy / W6 Server酱） ============

class TestW456DerivedChannels:
    def test_aliyun_url_enables(self, page):
        _to_cfg(page)
        snap = page.evaluate(_SNAP)
        try:
            _open_ch(page, "aliyun")
            sel = '#cfgform input[onchange*="setAy(0,\'url\'"]'
            _fill(page, sel, "https://monitor.aliyun.com/probe")
            out = page.evaluate("""(() => {
              const c = document.querySelector('.chcard[data-ch="aliyun"]');
              return {ay: CFG[0].notifier.aliyun,
                      on: c.classList.contains('on'),
                      dot: c.querySelector('.lgdot').classList.contains('on'),
                      muted: c.querySelector('.chhead .muted').textContent,
                      eHead: document.querySelector(
                        '#cfgform .grouplab[data-sec="F"] .gsum').textContent};
            })()""")
            assert out["ay"]["url"] == "https://monitor.aliyun.com/probe", out
            assert out["ay"]["enabled"] is True, out
            # r345 如实态：仅 URL 缺 AccessKey 时后端不会实例化通道 → 待完善
            assert not out["on"] and not out["dot"], out
            assert out["muted"] == "待完善", out
            assert "电话待完善" in out["eHead"], out
            _fill(page, '#cfgform input[onchange*="setAy(0,\'user\'"]', "LTAIprobe")
            _fill(page, '#cfgform input[onchange*="setAy(0,\'password\'"]', "secretprobe")
            out = page.evaluate("""(() => {
              const c = document.querySelector('.chcard[data-ch="aliyun"]');
              return {on: c.classList.contains('on'),
                      dot: c.querySelector('.lgdot').classList.contains('on'),
                      muted: c.querySelector('.chhead .muted').textContent,
                      eHead: document.querySelector(
                        '#cfgform .grouplab[data-sec="F"] .gsum').textContent};
            })()""")
            assert out["on"] and out["dot"], out
            assert out["muted"] == "已启用", out
            assert "电话✓" in out["eHead"], out
            _fill(page, sel, "")   # 清空 → enabled 派生回 false
            out = page.evaluate("""(() => ({
              en: CFG[0].notifier.aliyun.enabled,
              on: document.querySelector('.chcard[data-ch="aliyun"]')
                   .classList.contains('on')}))()""")
            assert out["en"] is False and not out["on"], out
        finally:
            _restore(page, snap)

    def test_ntfy_topic_enables(self, page):
        _to_cfg(page)
        snap = page.evaluate(_SNAP)
        try:
            _open_ch(page, "ntfy")
            _fill(page, '#cfgform input[onchange*="setNtfy(0,\'topic\'"]',
                  "entry-topic-1")
            out = page.evaluate("""(() => {
              const c = document.querySelector('.chcard[data-ch="ntfy"]');
              return {nt: CFG[0].notifier.ntfy,
                      on: c.classList.contains('on'),
                      eHead: document.querySelector(
                        '#cfgform .grouplab[data-sec="F"] .gsum').textContent};
            })()""")
            assert out["nt"]["topic"] == "entry-topic-1", out
            assert out["nt"]["enabled"] is True, out
            assert out["on"], out
            assert "ntfy✓" in out["eHead"], out
        finally:
            _restore(page, snap)

    def test_serverchan_sendkey_enables(self, page):
        _to_cfg(page)
        snap = page.evaluate(_SNAP)
        try:
            _open_ch(page, "serverchan")
            _fill(page, '#cfgform input[onchange*="setSc(0,\'send_key\'"]',
                  "SCT-probe-key")
            out = page.evaluate("""(() => {
              const c = document.querySelector(
                '.chcard[data-ch="serverchan"]');
              return {sc: CFG[0].notifier.serverchan,
                      on: c.classList.contains('on'),
                      eHead: document.querySelector(
                        '#cfgform .grouplab[data-sec="F"] .gsum').textContent};
            })()""")
            assert out["sc"]["send_key"] == "SCT-probe-key", out
            assert out["sc"]["enabled"] is True, out
            assert out["on"], out
            assert "微信✓" in out["eHead"], out
        finally:
            _restore(page, snap)


# ================= §5 邮件通道（W7-W10） =================

class TestW7Email:
    def test_add_fill_enable_and_title_face(self, page):
        _to_cfg(page)
        snap = page.evaluate(_SNAP)
        try:
            assert page.evaluate(
                "(CFG[0].notifier.emails||[]).length") == 0
            _click(page, '#cfgform button[onclick="addEm(0)"]')
            page.wait_for_timeout(150)
            assert page.evaluate(
                "(CFG[0].notifier.emails||[]).length") == 1
            _open_ch(page, "email0")
            # SMTP host/port/user/password/to 五字段（W7）；user 键驱动
            # 卡头标题随行（C8 面）；端口同值不触发 change 故填 587
            _fill(page,
                  '#cfgform input[onchange*="setEm(0,0,\'port\'"]', "587")
            _fill(page,
                  '#cfgform input[onchange*="setEm(0,0,\'user\'"]',
                  "entry@163.com")
            _fill(page,
                  '#cfgform input[onchange*="setEm(0,0,\'password\'"]',
                  "auth-code-16")
            _fill(page, '#cfgform input[onchange*="setEm(0,0,\'to\'"]',
                  "dest@163.com")
            out = page.evaluate("""(() => {
              const em = CFG[0].notifier.emails[0];
              const c = document.querySelector('.chcard[data-ch="email0"]');
              const tn = c.querySelector('.chhead .ch-title');
              return {em, title: tn ? tn.textContent : null};
            })()""")
            assert out["em"]["port"] == 587, out
            assert out["em"]["user"] == "entry@163.com", out
            assert out["em"]["password"] == "auth-code-16", out
            assert out["em"]["to"] == "dest@163.com", out
            assert out["title"] == "邮件·entry@163.com", out   # C8 面
            # 启用开关（W7 enabled）→ 卡灯 + E 头计数
            _click(page,
                   '#cfgform input[onchange*="setEm(0,0,\'enabled\'"]')
            out = page.evaluate("""(() => {
              const c = document.querySelector('.chcard[data-ch="email0"]');
              return {en: CFG[0].notifier.emails[0].enabled,
                      on: c.classList.contains('on'),
                      eHead: document.querySelector(
                        '#cfgform .grouplab[data-sec="F"] .gsum').textContent};
            })()""")
            assert out["en"] is True and out["on"], out
            assert "邮件✓×1" in out["eHead"], out
        finally:
            _restore(page, snap)

    def test_emhost_quick_chip(self, page):
        _to_cfg(page)
        snap = page.evaluate(_SNAP)
        try:
            _click(page, '#cfgform button[onclick="addEm(0)"]')
            page.wait_for_timeout(150)
            _open_ch(page, "email0")
            _click(page, '.chcard[data-ch="email0"] .emhchip:nth-child(2)')
            out = page.evaluate("""(() => {
              const c = document.querySelector('.chcard[data-ch="email0"]');
              const chips = [...c.querySelectorAll('.emhchip')];
              return {host: CFG[0].notifier.emails[0].host,
                      inpVal: c.querySelector('.emhost').value,
                      qqOn: chips[1].classList.contains('on'),
                      s163On: chips[0].classList.contains('on')};
            })()""")
            assert out["host"] == "smtp.qq.com", out
            assert out["inpVal"] == "smtp.qq.com", out
            assert out["qqOn"] and not out["s163On"], out
        finally:
            _restore(page, snap)

    def test_delete_channel_confirm(self, page):
        """r343：新邮箱卡自动展开且卡头常驻删除（不再藏进卡体）；
        删除走统一确认层，取消无损、确认才 splice。"""
        _to_cfg(page)
        snap = page.evaluate(_SNAP)
        try:
            _click(page, '#cfgform button[onclick="addEm(0)"]')
            page.wait_for_timeout(150)
            assert page.evaluate(
                "(CFG[0].notifier.emails||[]).length") == 1
            # 自动展开：body 可见、卡头删除可直接命中
            head_sel = '.chcard[data-ch="email0"] .chhead'
            assert page.get_attribute(head_sel, "aria-expanded") == "true"
            sel = '.chcard[data-ch="email0"] .chdel'
            assert page.locator(sel).is_visible()
            _click(page, sel)
            page.wait_for_timeout(150)
            assert page.is_visible("#confirmMask")
            assert page.inner_text("#cmTitle") == "删除邮箱通道？"
            _click(page, "#cmCancel")
            page.wait_for_timeout(120)
            assert page.evaluate(
                "(CFG[0].notifier.emails||[]).length") == 1
            _click(page, sel)
            page.wait_for_timeout(120)
            _click(page, "#cmYes")
            page.wait_for_timeout(200)
            assert page.evaluate(
                "(CFG[0].notifier.emails||[]).length") == 0
            assert page.locator(
                '.chcard[data-ch="email0"]').count() == 0
        finally:
            _restore(page, snap)


# ================= §6 钉钉（W11） =================

class TestW11Dingtalk:
    def test_enable_heads_and_fields(self, page):
        _to_cfg(page)
        snap = page.evaluate(_SNAP)
        try:
            _open_ch(page, "dingtalk")
            _click(page, '#cfgform input[onchange*="setDt(0,\'enabled\'"]')
            out = page.evaluate("""(() => {
              const c = document.querySelector('.chcard[data-ch="dingtalk"]');
              const p = document.querySelectorAll(
                '#cfgform .ucard .uhead2 .upill')[3];
              return {model: CFG[0].notifier.dingtalk.enabled,
                      on: c.classList.contains('on'),
                      muted: c.querySelector('.chhead .muted').textContent,
                      pill: p.textContent.trim(),
                      ok: p.classList.contains('ok'),
                      aHead: document.querySelector(
                        '#cfgform .grouplab[data-sec="A"] .gsum').textContent,
                      eHead: document.querySelector(
                        '#cfgform .grouplab[data-sec="F"] .gsum').textContent};
            })()""")
            assert out["model"] is True, out
            # r345：开关打开但 Webhook 空=后端跳过 → 待完善（旧假绿）
            assert not out["on"] and out["muted"] == "待完善", out
            assert out["pill"] == "推送待完善", out
            assert "钉钉待完善" in out["aHead"], out
            assert "钉钉待完善" in out["eHead"], out
            _fill(page, '#cfgform input[onchange*="setDt(0,\'webhook\'"]',
                  "https://oapi.dingtalk.com/robot/send?access_token=probe")
            _fill(page, '#cfgform input[onchange*="setDt(0,\'secret\'"]',
                  "SECprobe")
            _fill(page, '#cfgform input[onchange*="setDt(0,\'at_mobile\'"]',
                  "13900000000")
            page.wait_for_timeout(120)
            out = page.evaluate("""(() => {
              const c = document.querySelector('.chcard[data-ch="dingtalk"]');
              const p = document.querySelectorAll(
                '#cfgform .ucard .uhead2 .upill')[3];
              return {on: c.classList.contains('on'),
                      muted: c.querySelector('.chhead .muted').textContent,
                      pill: p.textContent.trim(),
                      eHead: document.querySelector(
                        '#cfgform .grouplab[data-sec="F"] .gsum').textContent};
            })()""")
            assert out["on"] and out["muted"] == "已启用", out
            assert out["pill"] == "推送已就绪", out
            assert "钉钉✓" in out["eHead"], out
            out = page.evaluate(
                "CFG[0].notifier.dingtalk")
            assert out["webhook"].endswith("access_token=probe"), out
            assert out["secret"] == "SECprobe", out
            assert out["at_mobile"] == "13900000000", out
        finally:
            _restore(page, snap)


# ================= §7 图床（W12） =================

class TestW12ImageHost:
    def test_provider_tri_state(self, page):
        _to_cfg(page)
        snap = page.evaluate(_SNAP)
        try:
            _open_ch(page, "imghost")
            assert page.evaluate(
                "CFG[0].notifier.image_host.provider") == "ghimg"
            # ghimg → sm.ms：卡类/卡头 muted/chip 高亮/Token 行显隐三态
            _click(page, '.chcard[data-ch="imghost"] .ihchip[data-p="smms"]')
            out = page.evaluate("""(() => {
              const c = document.querySelector('.chcard[data-ch="imghost"]');
              return {p: CFG[0].notifier.image_host.provider,
                      cls: c.className,
                      muted: c.querySelector('.chhead .muted').textContent,
                      smmsOn: c.querySelector('.ihchip[data-p="smms"]')
                                .classList.contains('on'),
                      tokenVisible: getComputedStyle(
                        c.querySelector('.ih-token')).display !== 'none'};
            })()""")
            assert out["p"] == "smms" and "ih-smms" in out["cls"], out
            assert out["muted"] == "sm.ms" and out["smmsOn"], out
            assert out["tokenVisible"], out
            # sm.ms → freeimage：Token 行被 !important 藏
            _click(page,
                   '.chcard[data-ch="imghost"] .ihchip[data-p="freeimage"]')
            out = page.evaluate("""(() => {
              const c = document.querySelector('.chcard[data-ch="imghost"]');
              return {p: CFG[0].notifier.image_host.provider,
                      cls: c.className,
                      muted: c.querySelector('.chhead .muted').textContent,
                      tokenVisible: getComputedStyle(
                        c.querySelector('.ih-token')).display !== 'none'};
            })()""")
            assert out["p"] == "freeimage" and "ih-free" in out["cls"], out
            assert out["muted"] == "freeimage", out
            assert not out["tokenVisible"], out
            # 回 ghimg：repo/ghtoken/proxy 行显
            _click(page, '.chcard[data-ch="imghost"] .ihchip[data-p="ghimg"]')
            out = page.evaluate("""(() => {
              const c = document.querySelector('.chcard[data-ch="imghost"]');
              return {p: CFG[0].notifier.image_host.provider,
                      muted: c.querySelector('.chhead .muted').textContent,
                      repoVisible: getComputedStyle(
                        c.querySelector('.ih-repo')).display !== 'none'};
            })()""")
            assert out["p"] == "ghimg" and out["muted"] == "GitHub 图库", out
            assert out["repoVisible"], out
        finally:
            _restore(page, snap)

    def test_repo_token_proxy_fields(self, page):
        _to_cfg(page)
        snap = page.evaluate(_SNAP)
        try:
            _open_ch(page, "imghost")
            _fill(page, '.chcard[data-ch="imghost"] .ih-repo input',
                  "probe/ticket-img")
            _fill(page, '.chcard[data-ch="imghost"] .ih-ghtoken input',
                  "ghp_probe")
            _fill(page, '.chcard[data-ch="imghost"] .ih-proxy input',
                  "http://127.0.0.1:7897")
            ih = page.evaluate("CFG[0].notifier.image_host")
            assert ih["repo"] == "probe/ticket-img", ih
            assert ih["token"] == "ghp_probe", ih
            assert ih["proxy"] == "http://127.0.0.1:7897", ih
        finally:
            _restore(page, snap)


# ============ §8 航线卡（W13；城市面板=C9 病灶路径，最高优先） ============

class TestW13Route:
    def test_city_panel_full_chain_from_to(self, page):
        """C9 病灶全真链：真点输入框→面板弹出→面板内真点城市→
        模型+输入框+卡头三面随行。禁 cityPanelOpen/Pick 直调。"""
        _to_cfg(page)
        snap = page.evaluate(_SNAP)
        try:
            _open_route(page, "0:0")
            _open_rtadv(page, "0:0")
            fin = '.rline[data-rk="0:0"] input[onchange*="\'from_name\'"]'
            _click(page, fin + ' + .rt-citymore')   # ▾ 全量城市面板
            page.wait_for_selector("#citypanel", state="visible")
            assert page.locator(
                "#cpbody .cp-city").count() > 100   # 全量城表面在场
            page.locator('#cpbody .cp-city[data-n="北京"]').first.click()
            page.wait_for_timeout(120)
            out = page.evaluate("""(() => {
              const r = CFG[0].routes[0];
              const head = document.querySelector(
                '.rline[data-rk="0:0"] .rhead');
              return {from: r.from, fromName: r.from_name,
                      inp: document.querySelector(
                        '.rline[data-rk="0:0"] input[onchange*=\\'from_name\\']')
                            .value,
                      headName: head.querySelector('b').textContent,
                      rtcode: head.querySelector('.rtcode').textContent,
                      panel: document.getElementById('citypanel').style.display};
            })()""")
            assert out["from"] == "BJS" and out["fromName"] == "北京", out
            assert out["inp"] == "北京", out
            assert out["headName"] == "北京 → 乌鲁木齐", out
            assert out["rtcode"] == "BJS→URC", out
            assert out["panel"] == "none", out   # 选后即关
            # 到达城市同链
            tin = '.rline[data-rk="0:0"] input[onchange*="\'to_name\'"]'
            _click(page, tin + ' + .rt-citymore')
            page.wait_for_selector("#citypanel", state="visible")
            page.locator('#cpbody .cp-city[data-n="长沙"]').first.click()
            page.wait_for_timeout(120)
            out = page.evaluate("""(() => {
              const r = CFG[0].routes[0];
              const head = document.querySelector(
                '.rline[data-rk="0:0"] .rhead');
              return {to: r.to, toName: r.to_name,
                      headName: head.querySelector('b').textContent,
                      rtcode: head.querySelector('.rtcode').textContent};
            })()""")
            assert out["to"] == "CSX" and out["toName"] == "长沙", out
            assert out["headName"] == "北京 → 长沙", out
            assert out["rtcode"] == "BJS→CSX", out
        finally:
            _restore(page, snap)

    def test_city_panel_search_then_pick(self, page):
        """面板内搜索框（cpq oninput→cityPanelFilter）过滤后点首个可见项。"""
        _to_cfg(page)
        snap = page.evaluate(_SNAP)
        try:
            _open_route(page, "0:0")
            _open_rtadv(page, "0:0")
            _click(page, '.rline[data-rk="0:0"] input[onchange*="\'to_name\'"] + .rt-citymore')
            page.wait_for_selector("#citypanel", state="visible")
            page.locator("#cpq").fill("长沙")
            page.wait_for_timeout(120)
            page.locator("#cpbody .cp-city:visible").first.click()
            page.wait_for_timeout(120)
            out = page.evaluate("""(() => ({
              to: CFG[0].routes[0].to, toName: CFG[0].routes[0].to_name,
              inp: document.querySelector(
                '.rline[data-rk="0:0"] input[onchange*=\\'to_name\\']').value}))()""")
            assert out["to"] == "CSX" and out["toName"] == "长沙", out
            assert out["inp"] == "长沙", out
        finally:
            _restore(page, snap)

    def test_city_panel_close_button_writes_nothing(self, page):
        """面板 ✕ 关闭：纯关闭不写模型（误触不留半截选择）。"""
        _to_cfg(page)
        snap = page.evaluate(_SNAP)
        try:
            _open_route(page, "0:0")
            _open_rtadv(page, "0:0")
            before = page.evaluate(
                "[CFG[0].routes[0].from_name, CFG[0].routes[0].to_name]")
            _click(page, '.rline[data-rk="0:0"] input[onchange*="\'to_name\'"] + .rt-citymore')
            page.wait_for_selector("#citypanel", state="visible")
            _click(page, "#citypanel .cp-x")
            page.wait_for_timeout(120)
            assert page.evaluate(
                "document.getElementById('citypanel').style.display") == "none"
            after = page.evaluate(
                "[CFG[0].routes[0].from_name, CFG[0].routes[0].to_name]")
            assert before == after, (before, after)
        finally:
            _restore(page, snap)

    def test_threshold_and_constraint_fields(self, page):
        _to_cfg(page)
        snap = page.evaluate(_SNAP)
        try:
            _open_route(page, "0:0")
            _open_rtadv(page, "0:0")
            rk = '.rline[data-rk="0:0"]'
            _fill(page, rk + ' input[onchange*="alert_direct"]', "1234")
            _fill(page, rk + ' input[onchange*="alert_transfer"]', "1555")
            out = page.evaluate("""(() => {
              const r = CFG[0].routes[0];
              return {d: r.alert_direct, t: r.alert_transfer,
                      muted: document.querySelector(
                        '.rline[data-rk="0:0"] .rhead .muted').textContent};
            })()""")
            assert out["d"] == 1234 and out["t"] == 1555, out
            assert "直飞≤￥1234" in out["muted"], out
            assert "中转≤￥1555" in out["muted"], out
            _fill(page, rk + ' input[onchange*="transfer_arrival_max"]',
                  "23:30")
            _fill(page, rk + ' input[onchange*="transfer_layover_min"]',
                  "120")
            out = page.evaluate(
                "[CFG[0].routes[0].transfer_arrival_max,"
                " CFG[0].routes[0].transfer_layover_min]")
            # layover 槽在 demo GET 载荷缺键（只下发 7 键）→ _coerce 无
            # number 槽可归一，字符串落模是 demo 数据形态非入口病；
            # 生产 config.yaml 载荷带 number 槽时归一为 120
            assert out[0] == "23:30" and str(out[1]) == "120", out
            # 行李直挂开关：demo GET 载荷缺 transfer_baggage 键 → 初始未勾；
            # 勾选 → 'direct'，再点 → ''（双向真路径）
            bag = rk + ' input[onchange*="transfer_baggage"]'
            assert not page.evaluate("CFG[0].routes[0].transfer_baggage")
            _click(page, bag)
            out = page.evaluate(
                "CFG[0].routes[0].transfer_baggage")
            assert out == "direct", out
            assert page.locator(bag).first.is_checked()
            _click(page, bag)
            assert page.evaluate(
                "CFG[0].routes[0].transfer_baggage") == ""
            assert not page.locator(bag).first.is_checked()
        finally:
            _restore(page, snap)


# ================= §9 航线启停（W14） =================

class TestW14RouteEnabled:
    def test_toggle_off_on(self, page):
        _to_cfg(page)
        snap = page.evaluate(_SNAP)
        try:
            rk = '.rline[data-rk="0:0"]'
            sw = rk + ' .rop input[onchange*="setRouteEnabled"]'
            _click(page, sw)
            out = page.evaluate("""(() => {
              const rl = document.querySelector('.rline[data-rk="0:0"]');
              return {en: CFG[0].routes[0].enabled,
                      off: rl.classList.contains('off'),
                      badge: rl.querySelector('.rbadge').textContent,
                      csum: document.getElementById('csum-0').textContent};
            })()""")
            assert out["en"] is False and out["off"], out
            assert out["badge"] == "已停用", out
            # 汇总词随航线数派生（demo 航线数是可变语料规模，硬编码
            # 条数在数据面扩容当日即红——模型态为唯一真值）
            out2 = page.evaluate(
                "(()=>({on:CFG[0].routes.filter(r=>r.enabled!==false).length,"
                "n:CFG[0].routes.length}))()")
            assert out["csum"] == (
                "%d 条监控中 · %d 条已停用"
                % (out2["on"], out2["n"] - out2["on"])), out
            _click(page, sw)
            out = page.evaluate("""(() => {
              const rl = document.querySelector('.rline[data-rk="0:0"]');
              return {hasKey: 'enabled' in CFG[0].routes[0],
                      off: rl.classList.contains('off'),
                      badge: rl.querySelector('.rbadge').textContent,
                      csum: document.getElementById('csum-0').textContent};
            })()""")
            assert out["hasKey"] is False, out   # 启用态删键（不留 true 垃圾）
            assert not out["off"] and out["badge"] == "", out
            assert out["csum"] == "%d 条监控中" % out2["n"], out
        finally:
            _restore(page, snap)


# ================= §10 特价（W15） =================

class TestW15Specials:
    def test_toggle_heads(self, page):
        _to_cfg(page)
        snap = page.evaluate(_SNAP)
        try:
            assert page.evaluate(
                "CFG[0].specials[0].enabled") is True
            sel = '#cfgform input[onchange*="setSp(0,\'enabled\'"]'
            _click(page, sel)
            out = page.evaluate("""(() => {
              const p = document.querySelectorAll(
                '#cfgform .ucard .uhead2 .upill')[1];
              return {m: CFG[0].specials[0].enabled,
                      t: p.textContent.trim(), ok: p.classList.contains('ok'),
                      dHead: document.querySelector(
                        '#cfgform .grouplab[data-sec="E"] .gsum').textContent};
            })()""")
            assert out["m"] is False, out
            assert out["t"] == "特价 关" and not out["ok"], out
            assert out["dHead"] == "官方特价频道", out
            _click(page, sel)
            out = page.evaluate("""(() => {
              const p = document.querySelectorAll(
                '#cfgform .ucard .uhead2 .upill')[1];
              return {m: CFG[0].specials[0].enabled,
                      t: p.textContent.trim(), ok: p.classList.contains('ok'),
                      dHead: document.querySelector(
                        '#cfgform .grouplab[data-sec="E"] .gsum').textContent};
            })()""")
            assert out["m"] is True, out
            assert out["t"] == "特价 开" and out["ok"], out
            assert out["dHead"] == "官方特价频道 · 低价提醒开", out
        finally:
            _restore(page, snap)

    def test_city_panel_and_fields(self, page):
        _to_cfg(page)
        snap = page.evaluate(_SNAP)
        try:
            _click(page, '#cfgform input[data-sp="from_name"]')
            page.wait_for_selector("#citypanel", state="visible")
            page.locator('#cpbody .cp-city[data-n="北京"]').first.click()
            page.wait_for_timeout(120)
            out = page.evaluate("""(() => ({
              name: CFG[0].specials[0].from_name,
              inp: document.querySelector(
                '#cfgform input[data-sp="from_name"]').value}))()""")
            assert out["name"] == "北京" and out["inp"] == "北京", out
            _fill(page, '#cfgform input[onchange*="setSp(0,\'max_price\'"]',
                  "388")
            _fill(page, '#cfgform input[onchange*="setSp(0,\'days\'"]', "60")
            _fill(page,
                  '#cfgform input[onchange*="setSp(0,\'round_trip_days\'"]',
                  "9")
            _click(page, '#cfgform input[onchange*="setSp(0,\'round_trip\'"]')
            sp = page.evaluate("CFG[0].specials[0]")
            assert sp["max_price"] == 388, sp
            assert sp["days"] == 60, sp
            assert sp["round_trip_days"] == 9, sp
            assert sp["round_trip"] is False, sp
        finally:
            _restore(page, snap)


# ================= §11 日期（W16/W17；📅 showPicker 跳过） =================

class TestW1617Dates:
    def test_add_via_native_date_button_and_guard(self, page):
        """native date 单通道（r339g 二合一：dpick 文本框+📅 隐藏件
        退役）两路真路径：选完即加（fill+Tab 失焦触发 change）与 ➕
        按钮；空值走 cfgErr 词面且不入模（原生件拒绝非法字面，旧
        「99 手输」非法态不可达）。"""
        _to_cfg(page)
        snap = page.evaluate(_SNAP)
        try:
            _open_route(page, "0:0")
            _open_rtadv(page, "0:0")
            # r345：一次只开一个编辑器；指定日面板需先切模式
            page.evaluate("setDateMode('d',0,0,'single')")
            base = page.evaluate("CFG[0].routes[0].dates.length")
            dp = '#dadd-0-0'
            _fill(page, dp, "2031-05-06")
            _click(page, 'button[onclick="addDate(0,0)"]')
            page.wait_for_timeout(200)
            dates = page.evaluate("CFG[0].routes[0].dates")
            assert len(dates) == base + 1, dates
            assert "2031-05-06" in dates, dates
            _fill(page, dp, "2032-01-09")
            _click(page, 'button[onclick="addDate(0,0)"]')
            page.wait_for_timeout(200)
            dates = page.evaluate("CFG[0].routes[0].dates")
            assert "2032-01-09" in dates, dates
            assert page.locator(
                '.rline[data-rk="0:0"] .dchip').count() == base + 2
            _fill(page, dp, "")
            _click(page, 'button[onclick="addDate(0,0)"]')
            page.wait_for_timeout(200)
            msg = page.evaluate("document.getElementById('cfgmsg').textContent")
            assert msg.startswith("❌ 请先选择"), msg
            assert page.evaluate(
                "CFG[0].routes[0].dates.length") == base + 2
        finally:
            _restore(page, snap)

    def test_delete_via_chip_x(self, page):
        _to_cfg(page)
        snap = page.evaluate(_SNAP)
        try:
            _open_route(page, "0:0")
            _open_rtadv(page, "0:0")
            base = page.evaluate("CFG[0].routes[0].dates.length")
            _click(page, '.rline[data-rk="0:0"] .dchip .dx')
            page.wait_for_timeout(200)
            dates = page.evaluate("CFG[0].routes[0].dates")
            assert len(dates) == base - 1, dates
            assert page.locator(
                '.rline[data-rk="0:0"] .dchip').count() == base - 1
        finally:
            _restore(page, snap)


# ================= §12 出发时段（W24/W25） =================

class TestW2425DepWin:
    def test_quick_dep_chip(self, page):
        _to_cfg(page)
        snap = page.evaluate(_SNAP)
        try:
            _open_route(page, "0:0")
            _open_rtadv(page, "0:0")
            rk = '.rline[data-rk="0:0"]'
            _click(page, rk + ' .schip[title="00:00–06:00"]')
            out = page.evaluate("""(() => {
              const r = CFG[0].routes[0];
              /* r339 起「出发→到达城市」行也带往返 chip（.schip）、
                 「中转最晚到达」行带单个 time 输入——定位锚按
                 「出发时段窗口」slab 语义锁定，不锚输入形态计数 */
              const row = [...document.querySelectorAll(
                '.rline[data-rk="0:0"] .srow')]
                .find(b => (b.querySelector('.slab b')||{}).textContent
                           === '出发时段窗口');
              const box = row.querySelector('.sctl');
              const t = box.querySelectorAll('input[type=time]');
              const chips = [...box.querySelectorAll('.schip')];
              return {mn: r.dep_time_min, mx: r.dep_time_max,
                      t0: t[0] ? t[0].value : null,
                      t1: t[1] ? t[1].value : null,
                      onCnt: chips.filter(c => c.classList.contains('on')).length,
                      muted: document.querySelector(
                        '.rline[data-rk="0:0"] .rhead .muted').textContent};
            })()""")
            assert out["mn"] == "00:00" and out["mx"] == "06:00", out
            assert out["t0"] == "00:00" and out["t1"] == "06:00", out
            assert out["onCnt"] == 1, out
            assert "00:00–06:00 出发" in out["muted"], out   # C7 面
            _click(page, rk + ' .schip[title="不限"]')
            out = page.evaluate("""(() => ({
              mn: CFG[0].routes[0].dep_time_min,
              mx: CFG[0].routes[0].dep_time_max,
              muted: document.querySelector(
                '.rline[data-rk="0:0"] .rhead .muted').textContent}))()""")
            assert out["mn"] == "" and out["mx"] == "", out
            assert "出发" not in out["muted"], out
        finally:
            _restore(page, snap)

    def test_custom_dep_window_clears_chips(self, page):
        _to_cfg(page)
        snap = page.evaluate(_SNAP)
        try:
            _open_route(page, "0:0")
            _open_rtadv(page, "0:0")
            rk = '.rline[data-rk="0:0"]'
            # 挡位 chip 的 title 是时间窗（词面在文本节点）；凌晨=00:00–06:00。
            # r341 起到达窗也有同形挡位行——选择器限定出发 .sctl（:has
            # dep 输入），防跨组误点
            _click(page, rk
                   + ' .sctl:has(input[onchange*="dep_time_min"])'
                   + ' .schip[title="00:00–06:00"]')
            t0 = page.locator(
                rk + ' input[onchange*="dep_time_min"]').first
            _scrollin(page, rk + ' input[onchange*="dep_time_min"]')
            t0.fill("07:15")
            page.keyboard.press("Tab")
            page.wait_for_timeout(120)
            out = page.evaluate("""(() => {
              const chips = [...document.querySelector(
                '.rline[data-rk="0:0"] input[onchange*="dep_time_min"]')
                .closest('.sctl').querySelectorAll('.schip')];   // r341 到达窗挡位行在场：探针限定出发组，防跨组误计
              return {mn: CFG[0].routes[0].dep_time_min,
                      onCnt: chips.filter(c => c.classList.contains('on')).length,
                      muted: document.querySelector(
                        '.rline[data-rk="0:0"] .rhead .muted').textContent};
            })()""")
            assert out["mn"] == "07:15", out
            assert out["onCnt"] == 0, out   # 手输=自定义窗口：挡位全熄
            assert "07:15" in out["muted"], out
        finally:
            _restore(page, snap)


# ================= §13 复制/删除航线（W22/W23） =================

class TestW2223RouteOps:
    def test_copy_route(self, page):
        _to_cfg(page)
        snap = page.evaluate(_SNAP)
        try:
            n0 = page.evaluate("CFG[0].routes.length")
            _click(page, '.rline[data-rk="0:0"] button[onclick^="copyRoute"]')
            page.wait_for_timeout(250)
            # 复制件=末位追加（索引随航线数派生，硬编码 4 在数据面
            # 扩容当日即红）
            out = page.evaluate("""((k) => ({
              n: CFG[0].routes.length,
              cpEn: CFG[0].routes[k].enabled,
              cpFrom: CFG[0].routes[k].from_name,
              card: !!document.querySelector('.rline[data-rk="0:'+k+'"]')}))(
              CFG[0].routes.length - 1)""")
            assert out["n"] == n0 + 1 and out["cpEn"] is False, out
            assert out["cpFrom"] == "上海", out
            assert out["card"], out
        finally:
            _restore(page, snap)

    def test_delete_route_confirm(self, page):
        """r343：删除航线走统一确认层（不再原地 arming 3s 超时复位）。"""
        _to_cfg(page)
        snap = page.evaluate(_SNAP)
        try:
            n0 = page.evaluate("CFG[0].routes.length")
            sel = '.rline[data-rk="0:0"] button.danger[onclick^="delRoute"]'
            _click(page, sel)
            page.wait_for_timeout(150)
            assert page.is_visible("#confirmMask")
            assert page.inner_text("#cmTitle") == "删除航线？"
            assert page.evaluate("CFG[0].routes.length") == n0
            _click(page, "#cmCancel")
            page.wait_for_timeout(120)
            assert page.evaluate("CFG[0].routes.length") == n0
            _click(page, sel)
            page.wait_for_timeout(120)
            _click(page, "#cmYes")
            page.wait_for_timeout(200)
            assert page.evaluate("CFG[0].routes.length") == n0 - 1
            # 末位行卡随删退场（索引随删除前规模派生）
            assert page.locator(
                '.rline[data-rk="0:%d"]' % n0).count() == 0
        finally:
            _restore(page, snap)


# ================= §14 添加/删除用户（W19/W20） =================

class TestW1920Users:
    def test_add_user(self, page):
        _to_cfg(page)
        snap = page.evaluate(_SNAP)
        try:
            _click(page, '#panel-users .cfgtoolbar button[onclick="addUser()"]')
            page.wait_for_timeout(250)
            out = page.evaluate("""(() => {
              const cards = document.querySelectorAll('#cfgform .ucard');
              return {n: CFG.length,
                      name: CFG[1].name,
                      cards: cards.length,
                      newOpen: cards[1].querySelector('.uhead2')
                                .getAttribute('aria-expanded')};
            })()""")
            assert out["n"] == 2 and out["cards"] == 2, out
            assert out["name"] == "新用户", out
            assert out["newOpen"] == "true", out   # 新卡自动展开
        finally:
            _restore(page, snap)

    def test_delete_user_confirm(self, page):
        _to_cfg(page)
        snap = page.evaluate(_SNAP)
        try:
            _click(page, '#panel-users .cfgtoolbar button[onclick="addUser()"]')
            page.wait_for_timeout(250)
            sel = '#cfgform button.danger[onclick^="delUser(1"]'
            _click(page, sel)
            page.wait_for_timeout(150)
            assert page.is_visible("#confirmMask")
            assert page.inner_text("#cmTitle") == "删除用户？"
            assert page.evaluate("CFG.length") == 2
            _click(page, "#cmYes")
            page.wait_for_timeout(200)
            assert page.evaluate("CFG.length") == 1
            assert page.evaluate("CFG[0].name") == "演示用户"
        finally:
            _restore(page, snap)


# ============ §15 G 区 globals（W26/W27 + glbCheck 校验面） ============

class TestW2627Globals:
    def _to_globals(self, page):
        _to_cfg(page)
        page.locator('.cnav[data-p="globals"]').click()
        page.wait_for_timeout(200)

    def test_globals_inputs(self, page):
        self._to_globals(page)
        snap = page.evaluate(_SNAP)
        try:
            port_to = "9000" if PORT != 9000 else "9001"
            _fill(page, "#glbIv", "42")
            _fill(page, "#glbJt", "7")
            _fill(page, "#glbPort", port_to)
            _fill(page, "#glbHost", "0.0.0.0")
            _fill(page, "#glbBu", "http://192.168.1.9:%s" % PORT)
            _fill(page, "#glbTo", "60")
            _fill(page, "#glbDn", "2")
            _fill(page, "#glbDx", "21")
            _fill(page, "#glbUa", "entry-ua-probe")
            _fill(page, "#glbProxy", "http://127.0.0.1:7897")
            _click(page, "#glbRos")   # run_on_start true→false
            _click(page, "#glbDbg")   # debug false→true
            g = page.evaluate("GLB")
            assert g["interval_minutes"] == 42, g
            assert g["jitter_minutes"] == 7, g
            assert g["port"] == int(port_to), g
            assert g["host"] == "0.0.0.0", g
            assert g["base_url"].endswith(str(PORT)), g
            assert g["timeout_seconds"] == 60, g
            assert g["delay_min"] == 2 and g["delay_max"] == 21, g
            assert g["user_agent"] == "entry-ua-probe", g
            assert g["proxy"] == "http://127.0.0.1:7897", g
            assert g["run_on_start"] is False, g
            assert g["debug"] is True, g
        finally:
            _restore(page, snap)

    def test_glbcheck_invalid_face_and_clamp(self, page):
        self._to_globals(page)
        snap = page.evaluate(_SNAP)
        try:
            _fill(page, "#glbIv", "1")
            out = page.evaluate("""(() => ({
              cls: document.getElementById('glbIv').className,
              verr: document.getElementById('glbIvErr').textContent,
              glb: GLB.interval_minutes}))()""")
            assert "invalid" in out["cls"], out
            assert "扫描周期须为 5-10080" in out["verr"], out
            assert out["glb"] == 5, out   # onchange 钳位下限兜底
        finally:
            _restore(page, snap)

    def test_headless_toggle_text(self, page):
        self._to_globals(page)
        snap = page.evaluate(_SNAP)
        try:
            assert page.evaluate("GLB.headless") is True
            _click(page, "#glbHl")
            out = page.evaluate("""(() => ({
              hl: GLB.headless,
              txt: document.getElementById('glbHlTxt').textContent}))()""")
            assert out["hl"] is False, out
            assert out["txt"] == "弹窗可见调试", out
        finally:
            _restore(page, snap)


# ===== §16 折叠/手风琴/cnav 面板/搜索（W29-W33） =====

class TestW2933FoldsNavSearch:
    def test_fold_section_route_channel(self, page):
        _to_cfg(page)
        try:
            # A 分区：默认展开 → 点头折叠 → 首行藏、aria 翻转 → 再点还原
            a = '.grouplab[data-sec="A"]'
            _click(page, a)
            page.wait_for_timeout(100)
            out = page.evaluate("""(() => ({
              aria: document.querySelector(
                '#cfgform .grouplab[data-sec="A"]').getAttribute('aria-expanded'),
              rowHidden: document.querySelector(
                '#cfgform .grouplab[data-sec="A"]')
                .nextElementSibling.style.display === 'none'}))()""")
            assert out["aria"] == "false" and out["rowHidden"], out
            _click(page, a)
            page.wait_for_timeout(100)
            out = page.evaluate("""(() => ({
              aria: document.querySelector(
                '#cfgform .grouplab[data-sec="A"]').getAttribute('aria-expanded'),
              rowHidden: document.querySelector(
                '#cfgform .grouplab[data-sec="A"]')
                .nextElementSibling.style.display === 'none'}))()""")
            assert out["aria"] == "true" and not out["rowHidden"], out
            # 航线卡：默认折叠 → 展开后再折叠（真点击两段）
            rh = '.rline[data-rk="0:0"] .rhead'
            _open_route(page, "0:0")
            _open_rtadv(page, "0:0")
            _click(page, rh)
            page.wait_for_timeout(100)
            assert page.locator(
                rh).first.get_attribute("aria-expanded") == "false"
            # 通道卡：默认折叠 → 真点击展开（foldCh + expanded 类）
            ch = '.chcard[data-ch="dingtalk"] .chhead'
            _click(page, ch)
            page.wait_for_timeout(100)
            out = page.evaluate("""(() => {
              const c = document.querySelector('.chcard[data-ch="dingtalk"]');
              return {aria: c.querySelector('.chhead')
                             .getAttribute('aria-expanded'),
                      expanded: c.classList.contains('expanded')};
            })()""")
            assert out["aria"] == "true" and out["expanded"], out
        finally:
            pass   # 折叠态是 UI 态（context 级），无需模型还原

    def test_user_accordion(self, page):
        _to_cfg(page)
        try:
            head = '#cfgform .ucard .uhead2'
            assert page.locator(
                head).first.get_attribute("aria-expanded") == "true"
            _click(page, head)
            page.wait_for_timeout(100)
            out = page.evaluate("""(() => ({
              aria: document.querySelector('#cfgform .uhead2')
                             .getAttribute('aria-expanded'),
              open: OPEN_USER}))()""")
            assert out["aria"] == "false" and out["open"] == -1, out
            _click(page, head)
            page.wait_for_timeout(100)
            out = page.evaluate("""(() => ({
              aria: document.querySelector('#cfgform .uhead2')
                             .getAttribute('aria-expanded'),
              open: OPEN_USER}))()""")
            assert out["aria"] == "true" and out["open"] == 0, out
        finally:
            pass

    def test_cnav_panel_switch(self, page):
        _to_cfg(page)
        try:
            page.locator('.cnav[data-p="globals"]').click()
            page.wait_for_timeout(150)
            out = page.evaluate("""(() => ({
              users: document.getElementById('panel-users').style.display,
              globals: document.getElementById('panel-globals').style.display,
              on: document.querySelector('.cnav[data-p="globals"]')
                            .classList.contains('on'),
              pressed: document.querySelector('.cnav[data-p="globals"]')
                              .getAttribute('aria-pressed')}))()""")
            assert out["users"] == "none" and out["globals"] == "", out
            assert out["on"] and out["pressed"] == "true", out
            page.locator('.cnav[data-p="users"]').click()
            page.wait_for_timeout(150)
            out = page.evaluate(
                "document.getElementById('panel-users').style.display")
            assert out == "", out
        finally:
            pass

    def test_cfg_search_filter_and_clear(self, page):
        _to_cfg(page)
        try:
            sr = "#cfgSearch"
            _fill(page, sr, "webhook")   # oninput→cfgFilterD 250ms 防抖
            page.wait_for_timeout(650)
            out = page.evaluate("""(() => ({
              hits: document.getElementById('cfgHits').textContent,
              qsearch: document.getElementById('cfgnav')
                             .classList.contains('qsearch')}))()""")
            assert out["hits"] == "✓ 2 项匹配", out
            assert out["qsearch"], out
            _fill(page, sr, "查无此词xyz")
            page.wait_for_timeout(650)
            assert page.evaluate(
                "document.getElementById('cfgEmpty').style.display") != "none"
            # 空态页内「清空搜索恢复全部分区」真点击 → cfgSearchClear 单源
            _click(page, "#cfgEmpty button")
            page.wait_for_timeout(250)
            out = page.evaluate("""(() => ({
              q: CFGQ, hits: document.getElementById('cfgHits').textContent,
              empty: document.getElementById('cfgEmpty').style.display,
              usersPanel: document.getElementById('panel-users').style.display}))()""")
            assert out["q"] == "" and out["hits"] == "", out
            assert out["empty"] == "none", out
            assert out["usersPanel"] == "", out
        finally:
            pass


# ===== §17 保存/放弃/导入（W34/W35/W36） =====

class TestW3436SaveDiscardImport:
    def test_save_demo_readonly_gate(self, page):
        """demo 只读门：POST 被 403 拦截 → 失败分支词面钉（cfgmsg+toast）。
        403 网络日志是浏览器对该失败分支的固有 console error——显式豁免
        这一条（失败分支本身即被钉行为），其余仍零容忍。"""
        page._expected.append("403 (Forbidden)")
        _to_cfg(page)
        snap = page.evaluate(_SNAP)
        try:
            _fill(page, '#cfgform input[onchange*="CFG[0].name"]',
                  "保存门探针")
            page.wait_for_selector("#savebar.on")
            _click(page, '#savebar button[onclick="saveCfg()"]')
            page.wait_for_function(
                "document.getElementById('cfgmsg').textContent"
                ".startsWith('❌')", timeout=6000)
            out = page.evaluate("""(() => {
              const ts = [...document.querySelectorAll('#toasts .toast')];
              return {msg: document.getElementById('cfgmsg').textContent,
                      toast: ts.length ? ts[ts.length - 1].textContent : ''};
            })()""")
            assert "演示模式只读" in out["msg"], out
            assert "❌ 保存失败" in out["toast"], out
        finally:
            _restore(page, snap)

    def test_discard_restores_server_truth(self, page):
        _to_cfg(page)
        try:
            _fill(page, '#cfgform input[onchange*="CFG[0].name"]',
                  "放弃门探针")
            # savebar 巡检面 ≤800ms 亮起
            page.wait_for_function(
                "document.getElementById('savebar').classList.contains('on')",
                timeout=3000)
            _click(page, '#savebar button[onclick="discardCfg()"]')
            page.wait_for_function("CFG[0].name === '演示用户'", timeout=6000)
            page.wait_for_timeout(1200)   # 巡检一拍内 savebar 灭
            out = page.evaluate("""(() => ({
              dirty: document.getElementById('savebar')
                             .classList.contains('on'),
              name: CFG[0].name}))()""")
            assert out["name"] == "演示用户", out
            assert not out["dirty"], out
        finally:
            pass   # loadCfg 已回滚到服务器真值

    def test_import_file_full_chain(self, page):
        """导入（W34）：set_input_files 向隐藏 #cfgImport 投递真 File 并
        触发原生 change——与用户「选文件→打开」完全同构的真实管线
        （Playwright 对文件输入的唯一正规驱动通道，非 dispatch 模拟）。
        断言整链：模型整体替换 + dates 补年归一 + 重建 + toast 词面。"""
        import json
        import tempfile
        _to_cfg(page)
        snap = page.evaluate(_SNAP)
        try:
            payload = {"users": [{
                "name": "导入甲",
                "routes": [{"from": "PEK", "from_name": "北京",
                            "to": "SHA", "to_name": "上海",
                            "dates": ["10-08"],
                            "alert_direct": 0, "alert_transfer": 0}],
                "platforms": ["qunar"],
                "notifier": {}}],
                "globals": {"interval_minutes": 20}}
            fd, path = tempfile.mkstemp(suffix=".json")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            try:
                page.locator("#cfgImport").set_input_files(path)
                page.wait_for_function("CFG.length === 1", timeout=6000)
                page.wait_for_timeout(300)
                out = page.evaluate("""(() => {
                  const ts = [...document.querySelectorAll('#toasts .toast')];
                  return {name: CFG[0].name,
                          dates: CFG[0].routes[0].dates,
                          plats: CFG[0].platforms,
                          iv: GLB.interval_minutes,
                          open: OPEN_USER,
                          toast: ts.length ? ts[ts.length-1].textContent : ''};
                })()""")
                assert out["name"] == "导入甲", out
                assert out["dates"] and out["dates"][0].endswith("-10-08"), out
                assert out["plats"] == ["qunar"], out
                assert out["iv"] == 20, out
                assert out["open"] == 0, out
                assert "已导入 1 个用户" in out["toast"], out
            finally:
                os.unlink(path)
        finally:
            _restore(page, snap)
