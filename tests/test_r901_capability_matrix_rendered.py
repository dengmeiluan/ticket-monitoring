# -*- coding: utf-8 -*-
"""r901 门禁：配置页「能力对照」必须真的把矩阵渲染上屏，且三态可辨。

用户要求「7 渠道全维度能力一致 + 特色能力可独立识别或聚合」。

实测缺陷（2026-10-31）：`/api/channel-dims` 早就存在且返回完整矩阵
（渠道 × 维度 + App 缺口），但**前端 0 处调用**——矩阵只活在源码与
接口里，配置页上无从核实；用户只能一家家点开猜「这家支不支持往返」。

判据（真渲染，不看源码字面）：
1. 矩阵表格出现在 `#cfgDimMatrix`，列数 = 注册渠道数，行数 = 维度数；
2. 每格是真三态之一（✓ 支持 / × 不支持 / ? 未验证），不是空白；
3. App 缺口清单必须在屏上（`.dimgap` 非空），且点名缺口维度；
4. 无 pageerror；窄档允许横向滚动但不得把内容裁没。
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def server():
    port = _free_port()
    p = subprocess.Popen([sys.executable, "webui.py", "--demo",
                          "--port", str(port)],
                         cwd=ROOT, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    up = False
    for _ in range(120):
        try:
            op.open("http://127.0.0.1:%d/api/state" % port, timeout=1)
            up = True
            break
        except Exception:
            time.sleep(0.25)
    if not up:
        p.terminate()
        pytest.skip("演示服务未在期限内起来")
    yield port
    p.terminate()


def _matrix(port, width):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        try:
            pg = b.new_page(viewport={"width": width, "height": 1100})
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto("http://127.0.0.1:%d/#cfg" % port,
                    wait_until="domcontentloaded", timeout=30000)
            pg.wait_for_timeout(2200)
            pg.evaluate("""()=>{const t=document.querySelector(
                  '.cnav [data-tab=login],#cfgnav [data-tab=login]');
                  if(t)t.click();}""")
            pg.wait_for_timeout(2200)
            out = pg.evaluate("""()=>{
              const w=document.getElementById('cfgDimMatrix');
              const t=w&&w.querySelector('.dimtbl');
              if(!t)return {err:'no table'};
              const heads=[...t.querySelectorAll('thead th')];
              const rows=[...t.querySelectorAll('tbody tr')];
              const cells=[...t.querySelectorAll('tbody td .cell')]
                .map(c=>c.textContent.trim());
              const kinds=new Set(cells);
              const gap=(w.querySelector('.dimgap')||{}).textContent||'';
              const wrap=w.querySelector('.dimwrap');
              /* 端面行：按列序号取内层 .cell 的 title（列序＝CHANNEL_DIMENSIONS
                 的展示序；App 列在这两行是「—」占位、没有 .cell，跳过）。 */
              const surfTitles={};
              for(const tr of rows){
                const th=((tr.querySelector('th')||{}).textContent||'').trim();
                if(th!=='PC 端'&&th!=='H5 端')continue;
                const m={};
                [...tr.querySelectorAll('td')].forEach((td,i)=>{
                  const c=td.querySelector('.cell');
                  if(c)m[i]=c.getAttribute('title')||'';
                });
                surfTitles[th]=m;
              }
              /* 维度行：每列内层 .cell 的 title（列序＝CHANNEL_DIMENSIONS 展示序） */
              const dimTitles={};
              for(const tr of rows){
                const th=((tr.querySelector('th')||{}).textContent||'').trim();
                dimTitles[th]=[...tr.querySelectorAll('td')].map(td=>{
                  const c=td.querySelector('.cell');
                  return c?(c.getAttribute('title')||''):'';
                });
              }
              return {nch:heads.length-1, nrow:rows.length, dimTitles,
                      ncell:cells.length, kinds:[...kinds].sort(),
                      empty:cells.filter(x=>!x).length,
                      gap:gap.trim(), surfTitles,
                      canScroll:wrap.scrollWidth>wrap.clientWidth+2,
                      boxW:Math.round(w.getBoundingClientRect().width)};
            }""")
            return out, errs
        finally:
            b.close()


def test_matrix_shows_every_channel_and_dimension(server):
    from core.channels import CHANNEL_DIMENSIONS, DIMENSIONS, SURFACES
    # r794：矩阵新增「端面（PC/H5）」一轴（r791–r793），行数＝维度数 + 端面数，
    # 外加一行分组标题。断言按真实载荷计算，避免把新增轴误判成多出来的行。
    n_rows = len(DIMENSIONS) + len(SURFACES) + 1
    out, errs = _matrix(server, 1512)
    assert not out.get("err"), out
    assert not errs, "配置页有 JS 报错：%s" % errs[:3]
    assert out["nch"] == len(CHANNEL_DIMENSIONS), (
        "矩阵只显示 %d 家，注册了 %d 家——用户看不出全量"
        % (out["nch"], len(CHANNEL_DIMENSIONS)))
    assert out["nrow"] == n_rows, (
        "矩阵只显示 %d 行，声明了 %d 个维度 + %d 个端面（+1 分组行）"
        % (out["nrow"], len(DIMENSIONS), len(SURFACES)))
    # 分组标题行是跨列的 th，不产格子。端面（PC/H5）只对浏览器渠道有定义：
    # App 渠道没有「PC 端/H5 端」之分（core/channels.CHANNEL_SURFACES 里
    # 根本没有这两家），那两格按约定画 ? 而不是算成数据格，所以期望值
    # 必须按「哪些渠道有端面定义」来算，不能一律乘行数。
    from core.channels import CHANNEL_SURFACES
    n_surf_ch = len([p for p in CHANNEL_DIMENSIONS if p in CHANNEL_SURFACES])
    ncell = len(CHANNEL_DIMENSIONS) * len(DIMENSIONS) + n_surf_ch * len(SURFACES)
    assert out["ncell"] == ncell, (
        "矩阵有 %d 个格子，按「%d 渠道 × %d 维 + %d 家有端面的渠道 × %d 端面」"
        "应为 %d：%s"
        % (out["ncell"], len(CHANNEL_DIMENSIONS), len(DIMENSIONS),
           n_surf_ch, len(SURFACES), ncell, out.get("kinds")))


def test_every_cell_is_one_of_three_states(server):
    out, _ = _matrix(server, 1512)
    assert not out.get("err"), out
    assert out["empty"] == 0, "有 %d 个格子是空的（既不是支持也不是不支持）" % out["empty"]
    assert set(out["kinds"]) <= {"✓", "×", "?"}, (
        "出现了三态以外的标记：%s" % out["kinds"])


def test_app_gaps_are_named_on_screen(server):
    """App 相对浏览器端的缺口必须写在屏上，不能只在接口 JSON 里。"""
    from core.channels import app_alignment_gaps
    out, _ = _matrix(server, 1512)
    assert not out.get("err"), out
    gap = out["gap"]
    assert gap, "能力对照下方没有缺口说明"
    any_gap = any(app_alignment_gaps(p) for p in ("app_zhixing", "app_qunar"))
    if any_gap:
        assert "缺" in gap, "有缺口却没写「缺」：%s" % gap
    else:
        assert "对齐" in gap, "无缺口时应明说已对齐：%s" % gap


def test_surface_note_reaches_the_cell_title(server):
    """端面说明必须挂在**内层 .cell** 上，否则悬停读不到。

    线上实测（2026-11-01）：端面的长说明写在 `<td title>`，而内层
    `.cell` 自带 `title="同程 · 支持"`——浏览器只显示最深层的 title，
    那段「www.ly.com 列表页的 getflightlist（需切桌面身份）…」永远
    看不到。判据按**每列对应的 SURFACE_NOTES** 断言 title 里含该说明。
    """
    from core.channels import CHANNEL_DIMENSIONS, SURFACE_NOTES
    out, _ = _matrix(server, 1512)
    assert not out.get("err"), out
    titles = out.get("surfTitles") or {}
    assert titles.get("PC 端") and titles.get("H5 端"), (
        "端面行没有可读的格子标题：%r" % (list(titles),))
    plats = list(CHANNEL_DIMENSIONS)
    checked = 0
    for row_name, s in (("PC 端", "pc"), ("H5 端", "h5")):
        for idx, title in (titles.get(row_name) or {}).items():
            plat = plats[int(idx)]
            note = SURFACE_NOTES.get((plat, s))
            if not note:
                continue
            checked += 1
            assert note[:12] in title, (
                "%s %s 格子的悬停里没有端面说明（写了但读不到）：%r"
                % (plat, s, title))
    assert checked >= 5, "端面说明的格子数异常：%d" % checked


@pytest.mark.parametrize("width", [900, 430, 320])
def test_matrix_stays_usable_on_narrow(server, width):
    """窄档允许横向滚动，但表格必须仍在且格子不被裁掉。

    320 是发布门禁里的最窄档（r813 实测：`.dimwrap` 内滚 620px、
    文档宽 310 < 320、表头零裁字；此前只验到 430）。
    """
    out, errs = _matrix(server, width)
    assert not out.get("err"), out
    assert not errs, errs[:3]
    assert out["ncell"] > 0 and out["empty"] == 0, out


def test_unsupported_cells_say_why_on_hover(server):
    """每个非 y 格子的悬停都要说清为什么（不是「渠道没这个产品」）。

    矩阵现在三态：y=已验证出数；n=渠道无此能力/停服；""=产品支持但
    采集端未实现或当前风控未出数。n 与 "" 都不能只画符号——携程产品上
    有往返、五个浏览器站点都有多程入口、去哪儿 App 的低价/日历已补齐，
    读者必须能从悬停区分「渠道没有」「我们没做」「当前被风控」。
    """
    from core.channels import CHANNEL_DIMENSIONS, DIMENSION_NOTES
    out, _ = _matrix(server, 1512)
    assert not out.get("err"), out
    dims = out.get("dimTitles") or {}
    LABEL = {"国内": "domestic", "国际": "intl", "日历": "calendar",
             "明细": "detail", "往返": "round_trip", "多程": "multi_city",
             "低价机票": "low_fare"}
    plats = list(CHANNEL_DIMENSIONS)
    checked = 0
    for head, titles in dims.items():
        dim = next((v for k, v in LABEL.items() if head.startswith(k)), None)
        if not dim:
            continue
        for i, plat in enumerate(plats):
            if CHANNEL_DIMENSIONS[plat].get(dim) == "y":
                continue
            note = DIMENSION_NOTES.get((plat, dim)) or ""
            assert note, "%s.%s 非 y 没有说明" % (plat, dim)
            assert note[:10] in titles[i], (
                "%s.%s 的悬停里没有说明（写了但读不到）：%r"
                % (plat, dim, titles[i]))
            checked += 1
    expected = sum(
        1 for plat in plats for dim in LABEL.values()
        if CHANNEL_DIMENSIONS.get(plat, {}).get(dim) != "y")
    assert checked == expected, (
        "非 y 格子未全部校验：checked=%d expected=%d" % (checked, expected))
    assert checked >= 1, "矩阵没有可校验的非 y 格子（加载失败？）"
