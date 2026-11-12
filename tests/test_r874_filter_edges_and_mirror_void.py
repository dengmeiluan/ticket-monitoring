# -*- coding: utf-8 -*-
"""r874/r875 门禁：筛选条三处「对齐线断了」+ 镜像折叠残留空带。

用户最新一轮点名（附三张截图）：
  「看看类似筛选列表中的筛选条件的不对齐的情况，类似的布局不对称、
    不对齐的都要修掉，保证我们微信扁平化的设计风格UI质感。」

修前三处实测（1512 / 1325）：
  1. 明细筛选卡「价格」「属性」两行没有标签槽（靠 `::before` 空心占位），
     行首文字落在内容列 187.5，而「日期 / 航线 / 渠道」的标签在 115.5
     —— 同一张卡两条左缘线，中间空掉 72px，用户截图圈的就是这个断口。
  2. `#attrchips` 是 `.72fr | 1.28fr` 两列，三个不跨行的分组排成
     「两格 + 一格」：448.9 / 798.1 / 448.9，第三格右侧整块空出 798px。
  3. 镜像「收起」后网格是 `minmax(0,1fr) auto`，右列虽塌到按钮宽，
     仍留下一条 82px 宽、贯穿整列的竖直空带（列表右侧一列空白，
     从表头一直空到列表底）。

判据一律走渲染几何（文本首字 / 盒子几何），不检 CSS 声明文本。
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


PORT = _free_port()
BASE = "http://127.0.0.1:%d" % PORT

# 明细筛选卡：每行的「标签文字首字」与「第一个内容控件左缘」
FT = r"""() => {
  const textL = el => {
    if (!el) return null;
    const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = w.nextNode())) {
      if (!n.nodeValue.trim()) continue;
      const r = document.createRange();
      r.selectNodeContents(n);
      const b = r.getBoundingClientRect();
      if (b.width > 0) return +b.left.toFixed(1);
    }
    const inp = el.querySelector('input,select,button');
    if (inp) { const b = inp.getBoundingClientRect(); if (b.width > 0) return +b.left.toFixed(1); }
    return null;
  };
  const R = e => { const b = e.getBoundingClientRect();
    return {l:+b.left.toFixed(1), r:+b.right.toFixed(1), w:+b.width.toFixed(1)}; };
  const wrap = document.getElementById('fltwrap');
  const rows = [];
  const sel = [...wrap.querySelectorAll(':scope > .frow'), wrap.querySelector('#attrchips')]
    .filter(r => r && getComputedStyle(r).display !== 'none');
  for (const r of sel) {
    // 标签可能嵌在 .wingrp / .agrp 里，递归找（但不要把 chip 的文本当标签）
    const lab = r.querySelector(':scope > .chiplab')
             || r.querySelector('.wingrp > .chiplab')
             || r.querySelector('.agrp > .chiplab');
    rows.push({id: r.id || r.className.replace('frow','').trim(),
      labTxt: lab ? lab.textContent.trim().slice(0,6) : null,
      labTextL: textL(lab)});
  }
  const attr = document.getElementById('attrchips');
  const ags = [...attr.children]
    .filter(a => getComputedStyle(a).display !== 'none')
    .map(a => { const b = a.getBoundingClientRect();
      return {txt: a.textContent.trim().slice(0,6),
              box: {l:+b.left.toFixed(1), r:+b.right.toFixed(1),
                    w:+b.width.toFixed(1), h:+b.height.toFixed(1)}}; });
  return {rows, ags, attrCols: getComputedStyle(attr).gridTemplateColumns};
}"""

# 镜像折叠：列表右缘 vs 网格右缘、触发器两态坐标
SNAP = r"""() => {
  const R = e => { const b = e.getBoundingClientRect();
    return {l:+b.left.toFixed(1), r:+b.right.toFixed(1), t:+b.top.toFixed(1),
            w:+b.width.toFixed(1)}; };
  const g = document.getElementById('srxGrid');
  const list = document.querySelector('#srxGrid > .srx-list');
  const mir = document.querySelector('#srxGrid .srx-mirror');
  const fb = document.querySelector('#srxMirrorFold');
  const gr = R(g), lr = R(list);
  return {cols: getComputedStyle(g).gridTemplateColumns,
          gapRight: +(gr.r - lr.r).toFixed(1),
          listW: lr.w, gridW: gr.w,
          btn: R(fb), folded: mir.classList.contains('srx-folded'),
          mirDisp: getComputedStyle(mir).display};
}"""

# ---------------------------------------------------------------- r876
SRF = r"""() => {
  const R = e => { const b = e.getBoundingClientRect();
    return {l:+b.left.toFixed(1), t:+b.top.toFixed(1), w:+b.width.toFixed(1)}; };
  const fm = document.getElementById('srxFmore');
  const common = fm.querySelector('.srf-common');
  const time = fm.querySelector('.srf-time');
  const history = fm.querySelector('.srf-history');
  const firstRow = c => {
    const hd = c.querySelector(':scope > header');
    const kids = [...c.children].filter(k => k !== hd && getComputedStyle(k).display !== 'none');
    return kids.length ? +R(kids[0]).t.toFixed(1) : null;
  };
  const tl = [...(time ? time.querySelectorAll('.srf-tline') : [])].map(e => +R(e).t.toFixed(1));
  const out = {commonTop: common ? R(common).t : null, timeTop: time ? R(time).t : null,
               historyTop: history ? R(history).t : null,
               commonFirst: common ? firstRow(common) : null,
               timeFirst: time ? firstRow(time) : null,
               historyFirst: history ? firstRow(history) : null,
               tlines: tl};
  // 右栏内部行距 vs 左栏「出发机场/到达机场」行的间距
  if (common) {
    const picks = [...common.querySelectorAll('.srf-pick')];
    out.pickTops = picks.map(e => +R(e).t.toFixed(1));
  }
  return out;
}"""



@pytest.fixture(scope="module")
def ui():
    srv = subprocess.Popen([sys.executable, "webui.py", "--demo", "--port", str(PORT)],
                           cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    out = {}
    try:
        ok = False
        for _ in range(90):
            try:
                urllib.request.urlopen(BASE + "/api/state", timeout=2)
                ok = True
                break
            except Exception:
                time.sleep(0.5)
        if not ok:
            pytest.skip("demo 服务未起来")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            br = pw.chromium.launch()
            for w in (1512, 1325, 1280, 1024):
                pg = br.new_page(viewport={"width": w, "height": 950})
                pg.goto(BASE + "/", wait_until="domcontentloaded")
                pg.wait_for_timeout(2500)
                pg.evaluate("switchView('mon')")
                pg.wait_for_timeout(800)
                pg.evaluate("showMonTab('details')")
                pg.wait_for_timeout(1600)
                pg.evaluate("document.getElementById('fltBtn').click()")
                pg.wait_for_timeout(800)
                ft = pg.evaluate(FT)
                pg.close()

                pg = br.new_page(viewport={"width": w, "height": 900})
                pg.goto(BASE + "/", wait_until="domcontentloaded")
                pg.wait_for_timeout(2900)
                pg.evaluate("switchView('search')")
                pg.wait_for_timeout(1900)
                before = pg.evaluate(SNAP)
                pg.evaluate("""() => {
                  const b = document.getElementById('srxMirrorFold');
                  if (b) b.click();
                }""")
                pg.wait_for_timeout(700)
                folded = pg.evaluate(SNAP)
                pg.evaluate("""() => {
                  const b = document.getElementById('srxMirrorFold');
                  if (b) b.click();
                }""")
                pg.wait_for_timeout(700)
                reopen = pg.evaluate(SNAP)
                # r876：同一窗口展开「更多条件」，量左右两卡首行基线
                pg.evaluate("srxToggleCtx()")
                pg.wait_for_timeout(400)
                pg.evaluate("document.getElementById('srxMoreBtn').click()")
                pg.wait_for_timeout(800)
                srf = pg.evaluate(SRF)
                out[w] = {"ft": ft, "before": before, "folded": folded,
                          "reopen": reopen, "srf": srf}
                out.setdefault("more_fold", {})
                pg.close()
            # r879：航司芯片单行普查
            out["air"] = {}
            for aw in (1512, 1325, 1280, 1199, 1101):
                pg = br.new_page(viewport={"width": aw, "height": 960})
                pg.goto(BASE + "/", wait_until="domcontentloaded")
                pg.wait_for_timeout(2400)
                pg.evaluate("switchView('mon')")
                pg.wait_for_timeout(800)
                pg.evaluate("showMonTab('details')")
                pg.wait_for_timeout(1500)
                pg.evaluate("document.getElementById('fltBtn').click()")
                pg.wait_for_timeout(800)
                out["air"][aw] = pg.evaluate(AIR)
                pg.close()
            # r878：更多条件「收起归位」——三档视口高度
            for vh in (950, 760, 640):
                pg = br.new_page(viewport={"width": 1512, "height": vh})
                pg.goto(BASE + "/", wait_until="domcontentloaded")
                pg.wait_for_timeout(2700)
                pg.evaluate("switchView('search')")
                pg.wait_for_timeout(1600)
                pg.evaluate("if(!SRX.ctx)srxToggleCtx()")
                pg.wait_for_timeout(700)
                out.setdefault("more_fold", {})[vh] = pg.evaluate(FOLD_MORE)
                pg.close()
            br.close()
        yield out
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except Exception:
            srv.kill()


@pytest.mark.parametrize("w", [1512, 1325, 1024])
def test_every_filter_row_shares_one_label_edge(ui, w):
    """每一行都必须有自己的标签，且标签文字同一起点（≤1px）。"""
    d = ui[w]["ft"]
    rows = d["rows"]
    assert len(rows) >= 7, "筛选行数不对：%s" % rows
    missing = [r["id"] for r in rows if r["labTxt"] is None]
    assert not missing, (
        "%d 档这些行没有标签（行首会落到内容列，左缘断成两条线）：%s" % (w, missing))
    lefts = [r["labTextL"] for r in rows if r["labTextL"] is not None]
    spread = max(lefts) - min(lefts)
    assert spread <= 1.0, (
        "%d 档标签左缘不齐，跨度 %.1fpx：%s"
        % (w, spread, [(r["id"], r["labTxt"], r["labTextL"]) for r in rows]))


@pytest.mark.parametrize("w", [1512, 1325, 1280, 1024])
def test_attribute_groups_fill_the_row(ui, w):
    """属性区的三个分组必须并排铺满整行，右侧不留整块空，也不折成多行。

    r874 前：`.72fr | 1.28fr` 两列，三个不跨行分组排成「两格 + 一格」，
    第三格右侧空出 798px。r874b 定案：三列按内容分权
    （`minmax(min-content,auto)`），每列先满足自己内容的单行宽度；
    1180–1350 档降为两列（三列会把「到达机场」压成 3 行）。
    等宽不是目标——目标是**不落单、不空块、不折行**。
    """
    d = ui[w]["ft"]
    ags = [a for a in d["ags"] if a["box"]["w"] > 0 and "航司" not in a["txt"][:2]]
    assert len(ags) >= 3, "属性分组不足三格：%s" % ags
    # 1) 不得有任何一个分组折成多行。单行高 32px（标签 + 一行 chip），
    #    折一行即 65px（负控：把列压到 0.4fr 时「到达机场」32→65）。
    tall = [(a["txt"], round(a["box"]["h"], 1)) for a in ags if a["box"]["h"] > 48]
    assert not tall, "%d 档属性分组折行：%s" % (w, tall)
    # 2) 末格必须贴到容器右缘（留 gap 以内）——不许右侧空出一整块
    container_r = max(a["box"]["r"] for a in d["ags"])
    last_r = max(a["box"]["r"] for a in ags[:3])
    assert container_r - last_r <= 2.0, (
        "%d 档第三格右缘离容器右缘还差 %.1fpx" % (w, container_r - last_r))


# 镜像折叠只测「本来就是两列」的宽度：≤1100 网格主动收单列，
# 折叠前后都没有右列，不构成「残留空带」的前提。
@pytest.mark.parametrize("w", [1512, 1325])
def test_folded_mirror_returns_the_whole_row(ui, w):
    """收起镜像后列表必须拿回整行，右侧不得残留竖直空带。"""
    d = ui[w]
    assert not d["before"]["folded"] and d["before"]["gapRight"] > 100, d["before"]
    assert d["folded"]["folded"], d["folded"]
    assert d["folded"]["gapRight"] <= 1.0, (
        "%d 档折叠后列表右侧仍空着 %.1fpx（截图里那条贯穿整列的竖直空带）"
        % (w, d["folded"]["gapRight"]))
    assert abs(d["folded"]["listW"] - d["folded"]["gridW"]) <= 1.0, (
        "%d 档折叠后列表没有拿回整行（列表 %.1f / 网格 %.1f）"
        % (w, d["folded"]["listW"], d["folded"]["gridW"]))
    # 回展开必须复原
    assert d["reopen"]["gapRight"] > 100, "回展开后没有恢复两列：%s" % d["reopen"]


@pytest.mark.parametrize("w", [1512, 1325])
def test_folded_mirror_trigger_does_not_move(ui, w):
    """折叠钮两态必须逐像素同坐标（否则读作「点一下按钮自己跑了」）。"""
    d = ui[w]
    a, b, c = d["before"]["btn"], d["folded"]["btn"], d["reopen"]["btn"]
    assert abs(b["l"] - a["l"]) <= 0.6 and abs(b["t"] - a["t"]) <= 0.6, (
        "%d 档折叠把触发器挪了：%s → %s" % (w, a, b))
    assert abs(c["l"] - a["l"]) <= 0.6 and abs(c["t"] - a["t"]) <= 0.6, (
        "%d 档回展开触发器没回原位：%s → %s" % (w, a, c))



@pytest.mark.parametrize("w", [1512, 1280])
def test_filter_sections_stack_with_one_shared_row(ui, w):
    """筛选分区：共同筛选独占整行；起降时段/加工历史同排对齐。

    r977 起不再让「共同筛选」与「起降时段」并排：前者内容最多，并排时
    左卡 482px、右卡被拉成同高，右卡内部余量摊出大洞。现在共同筛选
    横跨整行（航司/机场三组并排），下一行两张卡同顶、首行同基线。
    """
    d = ui[w]["srf"]
    assert d["commonTop"] < d["timeTop"], (
        "%d 档共同筛选应独占一行、位于时段卡上方：%s vs %s"
        % (w, d["commonTop"], d["timeTop"]))
    assert abs(d["timeTop"] - d["historyTop"]) <= 0.6, (
        "%d 档起降时段/加工历史不同排：%s vs %s"
        % (w, d["timeTop"], d["historyTop"]))
    assert abs(d["timeFirst"] - d["historyFirst"]) <= 1.0, (
        "%d 档两卡首行不在同一基线（左 %s / 右 %s）"
        % (w, d["timeFirst"], d["historyFirst"]))
    # 右栏两组时段之间的行距不得因余量摊分而拉大（≤ 一倍行高 + 20px）
    tl = d["tlines"]
    if len(tl) >= 2:
        gap = tl[1] - tl[0]
        assert gap <= 92, (
            "%d 档右栏「起飞 / 到达」被余量摊开成 %.1fpx（行距应≤92）" % (w, gap))


# ---------------------------------------------------------------- r877
def test_srx_thead_and_rows_share_one_column_grid():
    """检索解析列表：表头六列与数据行六列必须逐列重合。

    r877 前实测 1512：表头 `26/158.1/122/103.4/76/118`，数据行
    `26/171.8/122/91.7/72/96`——除起始列外全部错开（「航班」13.7px、
    「状态」11.7px、「操作」22px），表头文字与它下面的数据整列不齐。
    根因有两条：① ≤981 档只改了数据行的列模板；② 表头内衬 10px / gap 6，
    数据行 12px / 10。两者都把「同一份模板」算出不同宽度。
    """
    import re
    import webui
    src = webui.PAGE
    m = re.search(r"@media\(min-width:981px\)\{\s*#searchview \.srx-thead,#searchview \.srx-row\{([^}]*)\}",
                  src)
    assert m, "981 档没有把表头与数据行绑成同一个选择器"
    assert "1.5fr" in m.group(1) and "72px 96px" in m.group(1), m.group(1)
    i = src.index(" #searchview .srx-thead{padding-left:12px")
    seg = src[i:src.index("}", i) + 1]
    assert "column-gap:10px" in seg, (
        "表头内衬/gap 与数据行不一致——同样的 fr 会算出不同列宽")


# ---------------------------------------------------------------- r878
FOLD_MORE = r"""() => {
  const b = document.getElementById('srxMoreBtn');
  const R = e => { const r = e.getBoundingClientRect();
    return {l:+r.left.toFixed(1), t:+r.top.toFixed(1)}; };
  const a = R(b);
  b.click();
  return new Promise(res => setTimeout(() => {
    const m = R(b);
    b.click();
    setTimeout(() => res({a, open: m, reclosed: R(b)}), 520);
  }, 520));
}"""


@pytest.mark.parametrize("vh", [950, 760, 640])
def test_more_conditions_returns_to_the_same_place(ui, vh):
    """展开「更多条件」后收起，触发器必须回到**原坐标**。

    r878 前：展开时无条件把控件区顶对齐到页头下（scrollY +239），
    收起时不归位——同一颗按钮在「展开停一处、收起停另一处」，正是用户
    说的「展开和收起不在同一个位置，明显不是一个按钮多态的设计」。
    现改为最小必要滚动（只滚到露出面板底部），并在收起时全额归还。
    面板 628.5px 高，在 640px 视口里必然需要滚动——所以这里守的是
    「收起回到原位」，而不是「展开也不许滚」。
    """
    if vh not in (950, 760, 640):
        pytest.skip("unused")
    d = ui["more_fold"][vh]
    assert d["a"] and d["open"] and d["reclosed"], d
    # 负控：旧实现（展开后无条件顶对齐、收起不归还）在这种视口下
    # 收起态会比原坐标高 overscroll−0 —— 这里先证明「差值确实能被测到」，
    # 再断言它必须在 1px 内。
    moved = d["a"]["t"] - d["reclosed"]["t"]
    assert abs(moved) <= 1.0, (
        "%d 视口收起后触发器纵坐标没回原位（%s → %s，移动 %.1fpx）"
        % (vh, d["a"]["t"], d["reclosed"]["t"], moved))
    assert abs(d["reclosed"]["l"] - d["a"]["l"]) <= 1.0, (
        "%d 视口收起后触发器横坐标变了（%s → %s）"
        % (vh, d["a"]["l"], d["reclosed"]["l"]))


# ---------------------------------------------------------------- r879
AIR = r"""() => {
  const chips = document.getElementById('alchips');
  const wide = document.querySelector('#attrchips .ag-wide');
  const rows = new Set([...chips.children].map(c => +c.getBoundingClientRect().top.toFixed(1)));
  const cs = getComputedStyle(chips);
  return {rows: rows.size, n: chips.children.length,
          h: +chips.getBoundingClientRect().height.toFixed(1),
          wideH: +wide.getBoundingClientRect().height.toFixed(1),
          sw: chips.scrollWidth, cw: chips.clientWidth,
          wrap: cs.flexWrap, ox: cs.overflowX};
}"""


@pytest.mark.parametrize("w", [1512, 1325, 1280, 1199, 1101])
def test_airline_chips_never_wrap_into_a_taller_block(ui, w):
    """航司芯片行必须始终保持**单行**高度。

    r879 前实测：12 家航司需 907px，1325 档刚好放下（935），1280 档差 8.4px
    就折成两行——整块 32→65px，与相邻的 32px 行形成「上下不对齐」。
    修法：① 窄档把航司搜索框 92→76px，把宽度还给芯片（1325/1280/1200 单行）；
    ② 1101–1199 档芯片列只剩 ~830px（<907），改单行横滚而不是折行
    （scrollWidth > clientWidth 证明真的能滑，不是假滚动）。
    """
    d = ui["air"][w]
    assert d["n"] >= 10, "航司芯片数量异常：%s" % d
    assert d["rows"] == 1, (
        "%d 档航司芯片折成 %d 行（块高 %s）——与相邻行高度不一致"
        % (w, d["rows"], d["h"]))
    assert d["wideH"] <= 40, "%d 档航司整格被撑高到 %s" % (w, d["wideH"])
    if d["sw"] > d["cw"]:
        assert d["wrap"] == "nowrap" and d["ox"] in ("auto", "scroll"), (
            "%d 档芯片溢出但不可横滚（wrap=%s ox=%s）" % (w, d["wrap"], d["ox"]))
