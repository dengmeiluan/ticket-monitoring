# 配置页扁平化与图标内衬修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修掉配置页两个用户可见问题——左右两侧视觉重量不一致（不扁平），以及右侧面板与渠道入口的图标紧贴容器边缘。

**Architecture:** 本项目是单文件 SPA（`webui.py`，约 4.4MB 的 `PAGE` 字符串）。所有改动都是 CSS 声明层面的「让位于更后的扁平层不再互相覆盖」：不新增组件、不改 DOM 结构、不动 JS 逻辑。核心手法是**把零内衬的获胜规则改成正内衬**，并给左导航一个与右侧一致的扁平表面。

**Tech Stack:** 纯 CSS（写在 `webui.py` 的 `<style>` 块内）；测试用 pytest 静态断言 + Playwright 运行时几何断言。

**Spec:** 用户口述（2026-10-31）+ 实测缺陷表（见下）。本计划自含全部数值，执行者不需要回看会话。

## 关于本计划里出现的测试文件

本计划要求**新建**测试文件 `tests/test_cfg_flat_panel.py`（未创建，Task 1 待建）。
在 Task 1 Step 1 完成之前，下文所有引用它的 `pytest` 命令都会报
「file or directory not found」——这是预期的，不是文档错误。
执行者按 Task 顺序做即可：先建文件，再运行。

## 实测基线（1512×950，demo 服，真实渲染）

| # | 缺陷 | 现状实测 | 目标 |
| --- | --- | --- | --- |
| A | 右面板内容贴左缘 | `.ucard` `padding:14px 16px 14px 0px`；内容 `minLeft=295.5`＝卡左缘；左内衬 **0**、右 **16** | 左右各 **16**，内容不贴边 |
| B | 渠道登录行图标贴边 | `#loginRows .lgcard` `padding:9px 0px`；`iconInsetFromRow=**0px**` | 图标距行左缘 **≥10px** |
| C | 渠道入口 band 图标贴边 | `.chband` `padding:7px 0px 6px`；`iconInset=**0px**` | 图标距 band 左缘 **≥8px** |
| D | 左导航选中态非扁平 | 渲染 `bg=transparent`、`border-left:2px`、`shadow:none` | 软蓝底 + 无投影 + 无竖线 |
| E | 左导航无表面 | `.cfgnav` `bg=transparent/radius:0/无边框` | 与右卡同为内容表面 |

## Global Constraints

- **绝不整文件 `git add webui.py`**：并行会话正在改同一文件。只按 hunk 暂存，提交前核 `git diff --cached --stat` 的行数等于自己的改动行数。
- **不新增 `skip` / `xfail`**。
- **不改 `config.yaml`、`data/prices.db`、`user_data/`**。
- **不推送、不移动标签、不发 Release**。
- CSS 必须走令牌：颜色用 `--card` / `--line` / `--r-blue-soft` / `--blue` / `--r-hair` 等既有令牌，**不得新造 hex**。
- 圆角只用 `--r`(14) / `--r2`(11) / `--r3`(9) / `--r10`(10) / `--pill`(999)。
- 间距只落 4/6/8/12/16/24 阶（0/1/2 属微间距）。
- 每条新断言都必须**同时有运行时几何证据**（静态断言测不出「被覆盖」）。

---

### Task 1: 右面板左右内衬对称（缺陷 A）

**Files:**
- Modify: `webui.py` 中 `#cfgview .ucard` 与 `#cfgview .ucbody` 两条规则
- Test: `tests/test_cfg_flat_panel.py`（未创建，本计划待建）

**Interfaces:**
- Consumes: 无
- Produces: `.ucard` 在 `#cfgview` 下内衬恒为 `16px`（左右），`.ucbody` 左内衬归 0 由父卡统一提供

**背景**：实测 `.ucard` 计算值 `padding:14px 16px 14px 0px`——右 16、左 0。而 `#cfgview .ucbody{padding-left:16px!important}` 只给内层包裹补了左内衬，导致卡头标题与卡内部分块左缘差 16px（截图里右侧面板内容整体贴住卡片左边缘）。修法是**父卡左右对称给 16，内层不再重复给**。

- [ ] **Step 1: 写失败测试（静态契约）**

待建（未创建）`tests/test_cfg_flat_panel.py`：

```python
# -*- coding: utf-8 -*-
"""配置页扁平化与内衬：右面板左右内衬对称、图标不贴容器边缘、左导航扁平选中。"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    import webui
    return webui.PAGE


def test_cfg_card_padding_is_symmetric():
    """#cfgview 下 .ucard 的左右内衬必须相等，且内层 .ucbody 不再重复补左内衬。

    实测踩过（2026-10-31，1512）：.ucard 计算值 padding 为 14px 16px 14px 0px
    ——右 16、左 0，卡内内容 minLeft 等于卡左缘（左内衬 0），而右内衬 16。
    卡头标题与部分分块左缘相差 16px，整块内容贴住卡片左边缘。
    """
    src = _src()
    i = src.find("#cfgview .ucard{")
    assert i > 0, "找不到 #cfgview .ucard 规则"
    blk = src[i:src.find("}", i) + 1]
    assert "padding:15px 18px" in blk or "padding:16px" in blk or "padding-left:16px" in blk, (
        "右面板卡未给出左右对称内衬：%s" % blk[:160])
    # 内层不得再单独补左内衬（会与父卡叠加成 32px 或再次错位）
    assert "#cfgview .ucbody{padding:4px 0 14px!important}" not in src, (
        "内层 .ucbody 仍带 0 左右内衬的旧写法，需与父卡统一")
```

- [ ] **Step 2: 运行测试，确认失败**

（注意：该文件未创建，须先完成 Task 1 Step 1）
Run: `PYTHONIOENCODING=utf-8 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_cfg_flat_panel.py::test_cfg_card_padding_is_symmetric -q`   # 该文件未创建，先完成 Task 1 Step 1
Expected: FAIL，提示「右面板卡未给出左右对称内衬」

- [ ] **Step 3: 改 CSS**

在 `webui.py` 找到 `#cfgview .ucard{...}`（当前为一行，紧跟 `#cfgview .ucard .ucard` 之前），把内衬改成左右对称：

```css
#cfgview .ucard{border-color:color-mix(in srgb,var(--line) 55%,transparent);box-shadow:0 1px 3px rgba(15,23,42,.035);padding:14px 16px;box-sizing:border-box}
```

再把 `#cfgview .ucbody` 的两条规则合并成一条、去掉左内衬：

```css
/* 内衬由父卡统一提供（左右各 16）。此前父卡左侧 0、内层补 16，
   卡头与分块左缘因此相差 16px（1512 实测 minLeft=卡左缘）。 */
#cfgview .ucbody{padding:4px 0 14px!important}
```

（删除原 `#cfgview .ucbody{padding-left:16px!important}` 那一条。）

- [ ] **Step 4: 运行测试，确认通过**

（注意：该文件未创建，须先完成 Task 1 Step 1）
Run: `PYTHONIOENCODING=utf-8 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_cfg_flat_panel.py -q`   # 该文件未创建，先完成 Task 1 Step 1
Expected: PASS

- [ ] **Step 5: 运行时几何复验**

```bash
PYTHONIOENCODING=utf-8 python _scratch/probe_cfg_states.py
```
Expected: `cardPad.left == "16px"`、`cardPad.right == "16px"`、`cardContent.leftInset ≈ 16`、`rightInset ≈ 16`。

- [ ] **Step 6: 暂存并提交（只暂存自己的 hunk）**

```bash
git diff webui.py > /tmp/cfg1.patch      # 人工确认只含本任务的 hunk
git apply --cached --recount /tmp/cfg1.patch
git diff --cached --stat                 # 行数必须等于本次改动行数，看到几百行=立刻停止
git add tests/test_cfg_flat_panel.py   # 该文件未创建，先完成 Task 1 Step 1
git commit -m "fix(cfg): 右面板左右内衬对称，内容不再贴左缘"
```

---

### Task 2: 渠道登录行图标留出内衬（缺陷 B）

**Files:**
- Modify: `webui.py` 中 `#loginRows .lgcard` 的 padding 声明（两处，位于「去行线」扁平层）
- Test: `tests/test_cfg_flat_panel.py`（未创建，本计划待建、后续任务追加）

**Interfaces:**
- Consumes: Task 1 的 tests/test_cfg_flat_panel.py（该文件未创建，Task 1 待建）
- Produces: `#loginRows .lgcard` 横向内衬 ≥10px，图标距行左缘 ≥10px

**背景**：`#loginRows .lgcard{...padding:10px 2px!important}` 之后又被另一条 `padding:9px 0px` 覆盖（同特异度、后者胜），实测横向内衬 0，24px 的渠道图标与行左缘完全重合——用户所说的「图标和边缘在一块」。

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_cfg_flat_panel.py`（该文件本计划待建、尚不存在）：

```python
def test_login_rows_leave_room_before_the_icon():
    """渠道登录行必须给图标留左右内衬，不能为 0。

    实测踩过（2026-10-31，1512）：#loginRows .lgcard 计算值 padding 为 9px 0px，
    24px 渠道图标的左缘与行左缘完全重合（iconInsetFromRow=0）。
    """
    src = _src()
    offenders = []
    for m in re.finditer(r"#loginRows \.lgcard\{([^}]*)\}", src):
        body = m.group(1).replace(" ", "")
        pad = re.search(r"padding:([^;}!]+)", body)
        if not pad:
            continue
        val = pad.group(1)
        parts = val.split()
        if len(parts) >= 2:
            horiz = parts[1]
            num = float(re.match(r"(-?[\d.]+)px", horiz).group(1))
            if num <= 0:
                offenders.append(val)
    assert not offenders, (
        "渠道登录行出现 0 横向内衬（图标会贴住行左缘）：%s" % offenders)
```

同文件顶部补 import：

```python
import re
```

- [ ] **Step 2: 运行确认失败**

（注意：该文件未创建，须先完成 Task 1 Step 1）
Run: `PYTHONIOENCODING=utf-8 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_cfg_flat_panel.py::test_login_rows_leave_room_before_the_icon -q`   # 该文件未创建，先完成 Task 1 Step 1
Expected: FAIL，列出 `['10px 2px']` 或 `['9px 0px']`

- [ ] **Step 3: 改 CSS**

把「去行线」扁平层那条（`webui.py` 中 `#loginRows .lgcard{box-shadow:none!important;border:0!important;...}`）的 padding 改成横向 12px：

```css
#loginRows .lgcard{box-shadow:none!important;border:0!important;border-bottom:1px solid var(--r-hair)!important;
 border-radius:0!important;background:transparent!important;padding:10px 12px!important;min-height:0!important}
```

同时找到覆盖它的那条 `padding:9px 0px`（在 `#loginRows .lgcard` 的另一处声明里，含 `border-top:1px solid var(--r-hair)` 与 `min-height:52px`），改成：

```css
 padding:9px 12px!important;min-height:52px!important;box-sizing:border-box!important}
```

- [ ] **Step 4: 运行确认通过**

（注意：该文件未创建，须先完成 Task 1 Step 1）
Run: `PYTHONIOENCODING=utf-8 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_cfg_flat_panel.py -q`   # 该文件未创建，先完成 Task 1 Step 1
Expected: PASS

- [ ] **Step 5: 运行时复验（图标距行左缘）**

```bash
PYTHONIOENCODING=utf-8 python _scratch/probe_cfg_flatness.py
```
Expected: 每行 `iconInsetFromRow >= 10`；`rowH` 仍为 **52**（不得因内衬变高）；`iconVsCardEdge.diff >= 10`。

- [ ] **Step 6: 暂存并提交**

```bash
git diff webui.py > /tmp/cfg2.patch
git apply --cached --recount /tmp/cfg2.patch
git diff --cached --stat
git add tests/test_cfg_flat_panel.py   # 该文件未创建，先完成 Task 1 Step 1
git commit -m "fix(cfg): 渠道登录行给图标留内衬，图标不再贴行左缘"
```

---

### Task 3: 渠道入口 band 图标留出内衬（缺陷 C）

**Files:**
- Modify: `webui.py` 中两条 `.chband{...padding:...}` 规则（分别在「渠道入口」扁平层与 v304e 矩阵层）
- Test: `tests/test_cfg_flat_panel.py`（未创建，本计划待建、后续任务追加）

**Interfaces:**
- Consumes: Task 2 的文件
- Produces: `.chband` 横向内衬 ≥8px

**背景**：`.chband` 有两条后置规则把横向内衬清零（`padding:10px 2px!important` 与 `padding:7px 0 6px!important`），实测 `iconInset=0`——16px 渠道图标与 band 左缘重合。注意 band 在窄档（≤600）会变成单列，内衬同样要保留。

- [ ] **Step 1: 写失败测试**

```python
def test_channel_bands_leave_room_before_the_icon():
    """渠道入口每条 band 的横向内衬必须 ≥8px，不能为 0。

    实测踩过（2026-10-31，1512）：.chband 计算值 padding 为 7px 0px 6px，
    16px 图标左缘与 band 左缘重合（iconInset=0）。
    """
    src = _src()
    offenders = []
    for m in re.finditer(r"\.chband\{([^}]*)\}", src):
        body = m.group(1).replace(" ", "")
        pad = re.search(r"padding:([^;}!]+)", body)
        if not pad:
            continue
        parts = pad.group(1).split()
        horiz = parts[1] if len(parts) >= 2 else parts[0]
        num = float(re.match(r"(-?[\d.]+)px", horiz).group(1))
        if num <= 0:
            offenders.append(pad.group(1))
    assert not offenders, (
        "渠道入口 band 出现 0 横向内衬（图标会贴住左缘）：%s" % offenders)
```

- [ ] **Step 2: 运行确认失败**

（注意：该文件未创建，须先完成 Task 1 Step 1）
Run: `PYTHONIOENCODING=utf-8 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_cfg_flat_panel.py::test_channel_bands_leave_room_before_the_icon -q`   # 该文件未创建，先完成 Task 1 Step 1
Expected: FAIL，列出 `['10px 2px']`、`['7px 0 6px']`

- [ ] **Step 3: 改 CSS（两条都要改）**

第一条（「渠道入口：一块表面 + 行 + 文本入口」附近）：

```css
.chband{grid-template-columns:148px minmax(0,1fr)!important;gap:8px!important;
 padding:10px 12px!important;border:0!important;border-bottom:1px solid var(--r-hair)!important;
 border-radius:0!important;background:transparent!important}
```

第二条（v304e 矩阵层，`grid-template-columns:160px` 那条）：

```css
.chband{display:grid!important;grid-template-columns:160px minmax(0,1fr)!important;gap:6px!important;padding:7px 12px 6px!important;border:0!important;border-radius:0!important;background:transparent!important}
```

注意：`.chband` 的**左边框 3px 彩色条**（`.chband` 初版有 `border-left:3px solid var(--chc,...)`）已被后置 `border:0!important` 清掉，本次不加回——但需在提交说明里写明「渠道色条保持移除，靠图标本身区分」。

- [ ] **Step 4: 运行确认通过**

（注意：该文件未创建，须先完成 Task 1 Step 1）
Run: `PYTHONIOENCODING=utf-8 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_cfg_flat_panel.py -q`   # 该文件未创建，先完成 Task 1 Step 1
Expected: PASS

- [ ] **Step 5: 运行时复验 + 四档宽度**

```bash
PYTHONIOENCODING=utf-8 python _scratch/probe_cfg_flatness.py
```
Expected: 每条 band `iconInset >= 8`；band `h` 仍为 **91**。

再在 390 档复测（窄档单列，内衬不应把内容挤出）：

```python
# 在 probe 里把 viewport 换成 390×844 后重跑，确认
# document.documentElement.scrollWidth <= clientWidth + 1
```

- [ ] **Step 6: 暂存并提交**

```bash
git diff webui.py > /tmp/cfg3.patch
git apply --cached --recount /tmp/cfg3.patch
git diff --cached --stat
git add tests/test_cfg_flat_panel.py   # 该文件未创建，先完成 Task 1 Step 1
git commit -m "fix(cfg): 渠道入口 band 给图标留内衬"
```

---

### Task 4: 左导航扁平选中态（缺陷 D）

**Files:**
- Modify: `webui.py` 中 `.cnav.on` 与 `.cnav:hover`
- Test: `tests/test_cfg_flat_panel.py`（未创建，本计划待建、后续任务追加）

**Interfaces:**
- Consumes: Task 3 的文件
- Produces: `.cnav.on` 无投影、无左侧竖线，用软蓝底表达选中

**背景**：`.cnav.on{background:var(--fill);color:#fff;box-shadow:0 2px 8px -2px var(--glow)}` 是**实心填充 + 辉光**——与微信式扁平语言冲突（扁平语言里选中用软底，不用投影）。而后续扁平层又把它清成 `transparent + 左侧 2px 竖线`，变成另一种非扁平语义。两条路都不对，统一改成「软蓝底 + 品牌色文字 + 无投影 + 无竖线」。

- [ ] **Step 1: 写失败测试**

```python
def test_cnav_selected_state_is_flat():
    """.cnav 选中态必须是软底，不带投影，也不靠左侧竖线。

    实测踩过（2026-10-31，1512）：改前是 --fill 实心填充 + box-shadow 辉光；
    后续扁平层又清成 transparent + border-left:2px。两种都不是扁平选中语言。
    """
    src = _src()
    assert ".cnav.on{background:var(--r-blue-soft)" in src.replace(" ", ""), (
        "选中态不是软蓝底")
    i = src.find(".cnav.on{")
    assert i > 0
    blk = src[i:src.find("}", i) + 1]
    assert "box-shadow" not in blk or "none" in blk, (
        "选中态仍带投影：%s" % blk[:120])
    assert "border-left" not in blk, (
        "选中态仍靠左侧竖线表达：%s" % blk[:120])
```

- [ ] **Step 2: 运行确认失败**

（注意：该文件未创建，须先完成 Task 1 Step 1）
Run: `PYTHONIOENCODING=utf-8 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_cfg_flat_panel.py::test_cnav_selected_state_is_flat -q`   # 该文件未创建，先完成 Task 1 Step 1
Expected: FAIL，提示「选中态不是软蓝底」

- [ ] **Step 3: 改 CSS**

把 `.cnav.on` 那条改成软底（保持既有选择器位置，避免特异性漂移）：

```css
/* 选中态用软蓝底 + 品牌色文字（扁平语言）：不投影、不用左侧竖线。
   改前是 --fill 实心 + 辉光，与全站「选中=浅底」不一致。 */
.cnav.on{background:var(--r-blue-soft);color:var(--blue);box-shadow:none}
```

同时确认 `.cnav.on:focus-visible` 保留焦点环：

```css
.cnav.on:focus-visible{box-shadow:0 0 0 2px var(--blue)}
```

并删除后续扁平层里那条把它清成 `transparent + border-left` 的覆盖（搜索 `border-left:2px` 与 `.cnav.on` 的组合）。

- [ ] **Step 4: 运行确认通过**

（注意：该文件未创建，须先完成 Task 1 Step 1）
Run: `PYTHONIOENCODING=utf-8 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_cfg_flat_panel.py -q`   # 该文件未创建，先完成 Task 1 Step 1
Expected: PASS

- [ ] **Step 5: 运行时复验（选中/未选中/悬停三态）**

```bash
PYTHONIOENCODING=utf-8 python _scratch/probe_cfg_states.py
```
Expected:
- `cnavOn.bg` 为软蓝（非 `rgba(0,0,0,0)`）、`cnavOn.boxShadow == "none"`、`cnavOn.borderLeft` 宽度为 `0px`
- `cnavOff.bg == "rgba(0, 0, 0, 0)"`（未选中不加底）
- 悬停态 `bg` 与未选中不同（hover 有反馈）

- [ ] **Step 6: 暂存并提交**

```bash
git diff webui.py > /tmp/cfg4.patch
git apply --cached --recount /tmp/cfg4.patch
git diff --cached --stat
git add tests/test_cfg_flat_panel.py   # 该文件未创建，先完成 Task 1 Step 1
git commit -m "fix(cfg): 左导航选中态改软蓝底，去掉实心辉光与左竖线"
```

---

### Task 5: 左导航与右面板同层表面（缺陷 E）

**Files:**
- Modify: `webui.py` 中 `.cfgnav` 与其滚动容器
- Test: `tests/test_cfg_flat_panel.py`（未创建，本计划待建、后续任务追加）

**Interfaces:**
- Consumes: Task 4 的文件
- Produces: `.cfgnav` 具备与 `.ucard` 同族的表面（`--card` 底 + `--r` 圆角 + 1px 发丝边 + 内衬）

**背景**：实测 `.cfgnav` 是 `background:transparent / border-radius:0 / border-width:0` 的裸列，右侧却是白底圆角卡——同一屏左右两块视觉重量差一整个层级，正是「左边和右边不够扁平化」的另一半：不是要加装饰，而是**两侧应当同一种表面语言**。

- [ ] **Step 1: 写失败测试**

```python
def test_cfg_nav_shares_the_card_surface():
    """左导航必须与右侧面板同一种表面（同一套令牌），不能是裸列。

    实测踩过（2026-10-31，1512）：.cfgnav 计算值 background:transparent、
    border-radius:0、border-width:0，而右侧 .ucard 是白底 + 14px 圆角，
    同屏左右视觉重量相差一个层级。
    """
    src = _src()
    i = src.find(".cfgnav{")
    assert i > 0, "找不到 .cfgnav 规则"
    blk = src[i:src.find("}", i) + 1].replace(" ", "")
    assert "background:var(--card)" in blk, "左导航没有内容表面：%s" % blk[:150]
    assert "border-radius:var(--r)" in blk, "左导航圆角未走令牌：%s" % blk[:150]
    assert "border:1pxsolidvar(--line)" in blk or "border:1pxsolidvar(--line2)" in blk, (
        "左导航缺 1px 发丝边：%s" % blk[:150])
```

- [ ] **Step 2: 运行确认失败**

（注意：该文件未创建，须先完成 Task 1 Step 1）
Run: `PYTHONIOENCODING=utf-8 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_cfg_flat_panel.py::test_cfg_nav_shares_the_card_surface -q`   # 该文件未创建，先完成 Task 1 Step 1
Expected: FAIL，提示「左导航没有内容表面」

- [ ] **Step 3: 改 CSS**

`.cfgnav` 当前是：

```css
.cfgnav{position:sticky;top:calc(var(--hdh,54px) + 4px);display:flex;flex-direction:column;gap:4px;
 align-self:start;max-height:calc(100vh - var(--hdh,54px) - 16px);overflow:auto}
```

改成带表面（内衬 12，与 `.ucard` 的 16 区分：导航是次级容器用 `--r2` 亦可，这里统一用 `--r` 与右卡同族）：

```css
/* 与右侧面板同一套表面语言（--card + --r + 1px 发丝边）：
   此前是裸列（transparent/0 圆角/0 边框），同屏左右重量差一层级。 */
.cfgnav{position:sticky;top:calc(var(--hdh,54px) + 4px);display:flex;flex-direction:column;gap:4px;
 align-self:start;max-height:calc(100vh - var(--hdh,54px) - 16px);overflow:auto;
 background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:12px}
```

同时把 `.cnav` 自身从「每条一个白卡」降为「列表行」，否则变成卡中卡：

```css
/* 导航项在已上浮的侧栏里不再各自成卡（卡中卡），改为行式：透明底 + 圆角 + 悬停软底 */
.cnav{background:transparent;border:1px solid transparent;border-radius:var(--r3);
 padding:8px 10px;cursor:pointer;font-size:13px;color:var(--tx2);font-weight:600;
 transition:.15s;user-select:none}
.cnav:hover{background:var(--hover)}
```

- [ ] **Step 4: 运行确认通过**

（注意：该文件未创建，须先完成 Task 1 Step 1）
Run: `PYTHONIOENCODING=utf-8 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_cfg_flat_panel.py -q`   # 该文件未创建，先完成 Task 1 Step 1
Expected: PASS

- [ ] **Step 5: 运行时复验 + 卡中卡检查**

```bash
PYTHONIOENCODING=utf-8 python _scratch/probe_cfg_states.py
```
Expected:
- `navSurface.bg == "rgb(255, 255, 255)"`、`navSurface.radius == "14px"`、`navSurface.border` 以 `1px` 开头
- `cnavOff.bg == "rgba(0, 0, 0, 0)"`（项本身不做表面）
- 左右两卡顶边对齐：`nav.top == card.top`（实测均应为 206.5）

- [ ] **Step 6: 暂存并提交**

```bash
git diff webui.py > /tmp/cfg5.patch
git apply --cached --recount /tmp/cfg5.patch
git diff --cached --stat
git add tests/test_cfg_flat_panel.py   # 该文件未创建，先完成 Task 1 Step 1
git commit -m "fix(cfg): 左导航与右面板同层表面，去掉整列裸边"
```

---

### Task 6: 全档宽度与暗色复验 + 全量门禁

**Files:**
- Test: `tests/test_cfg_flat_panel.py`（未创建，本计划待建、Task 6 追加）
- 不改产品代码

**Interfaces:**
- Consumes: Task 1–5 的全部改动
- Produces: 跨 4 档宽度、2 主题的证据

- [ ] **Step 1: 写跨档测试**

```python
def test_cfg_flat_fix_holds_at_every_breakpoint():
    """四个断点下，右面板左右内衬相等、图标不贴边、左导航有表面。

    这是运行时断言（Playwright），因为静态断言测不出级联覆盖。
    """
    import subprocess, sys, time, urllib.request
    import pytest
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    port = 9199
    proc = subprocess.Popen([sys.executable, "webui.py", "--demo", "--port", str(port)],
                            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        t0 = time.time()
        while time.time() - t0 < 90:
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=2)
                break
            except Exception:
                time.sleep(0.5)
        else:
            pytest.fail("demo 服未能启动")

        with sync_playwright() as p:
            b = p.chromium.launch()
            for w in (1512, 1280, 900, 390):
                pg = b.new_page(viewport={"width": w, "height": 950})
                pg.goto("http://127.0.0.1:%d/" % port, wait_until="domcontentloaded")
                pg.wait_for_function(
                    "()=>typeof S!=='undefined'&&S&&S.users&&S.users.length>0", timeout=25000)
                pg.evaluate("()=>switchView('cfg')")
                pg.wait_for_timeout(500)
                pg.click('#cfgnav .cnav[data-p="login"]')
                pg.wait_for_timeout(800)
                m = pg.evaluate("""()=>{
                  const cs=(e,p)=>e?getComputedStyle(e)[p]:null;
                  const r=e=>e?e.getBoundingClientRect():null;
                  const card=document.querySelector('#sec-login')||document.querySelector('.ucard');
                  const nav=document.querySelector('#cfgnav');
                  const row=document.querySelector('#loginRows .lgcard');
                  const band=document.querySelector('#panel-login .chband');
                  const ic=row?row.querySelector('.bic,.logo,svg'):null;
                  const bic=band?band.querySelector('.chband-name svg,.chband-name .bic'):null;
                  return {
                    padL:parseFloat(cs(card,'paddingLeft')),
                    padR:parseFloat(cs(card,'paddingRight')),
                    iconInsetRow: ic? +(r(ic).left - r(row).left).toFixed(1) : null,
                    iconInsetBand: bic? +(r(bic).left - r(band).left).toFixed(1) : null,
                    navBg: cs(nav,'backgroundColor'),
                    navRadius: cs(nav,'borderRadius'),
                    overflow: document.documentElement.scrollWidth
                              > document.documentElement.clientWidth + 1,
                  };}""")
                pg.close()
                assert m["padL"] == m["padR"], "%d 档左右内衬不等：%s" % (w, m)
                assert m["padL"] >= 12, "%d 档内衬过小：%s" % (w, m)
                if m["iconInsetRow"] is not None:
                    assert m["iconInsetRow"] >= 8, "%d 档登录行图标贴边：%s" % (w, m)
                if m["iconInsetBand"] is not None:
                    assert m["iconInsetBand"] >= 6, "%d 档 band 图标贴边：%s" % (w, m)
                assert m["navBg"] not in ("rgba(0, 0, 0, 0)", "transparent"), (
                    "%d 档左导航仍无表面：%s" % (w, m))
                assert not m["overflow"], "%d 档出现横向溢出" % w
            b.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
```

- [ ] **Step 2: 运行**

（注意：该文件未创建，须先完成 Task 1 Step 1）
Run: `PYTHONIOENCODING=utf-8 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_cfg_flat_panel.py -q`   # 该文件未创建，先完成 Task 1 Step 1
Expected: PASS（6 条）

- [ ] **Step 3: 跑相关既有套件（防回归）**

```bash
PYTHONIOENCODING=utf-8 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r872_cfg_layers_one_left_edge.py \
  tests/test_r412_login_rows_alignment.py \
  tests/test_r870_cfg_fold_keeps_heads.py \
  tests/test_r837_channel_band_indent.py -q
```
Expected: 全 PASS。

**若 `test_r872` 红**：它钉的是「四层首字落点极差 ≤6px」。本次把父卡内衬从 0 改成 16 会整体平移首字——需要把该用例里的参考边一起改（从「按容器边」改成「按卡内容边」），并在提交说明里写明「契约变更，不是回归」。**不要**为了让它绿而把内衬改回 0。

- [ ] **Step 4: 截图为证**

```bash
PYTHONIOENCODING=utf-8 python _scratch/probe_cfg_flatness.py   # 会自动落 _scratch/cfg_login_1512.png
```
人工看图确认：图标与边框之间有肉眼可见的间距；左导航与右卡表面一致。

- [ ] **Step 5: 全量门禁（哈希定格）**

```bash
md5sum webui.py                                  # 记录哈希
python tools/test_all.py                          # ~7 分钟
md5sum webui.py                                  # 必须与记录一致
```
Expected: 摘要行 `pytest … passed N / failed 0`、`uitest … 644/644`，退出码 0。
若退出码 3 → 跑测期间被并行会话改写，**结果作废，重跑**，不要当成失败。

- [ ] **Step 6: 提交测试并收尾**

```bash
git add tests/test_cfg_flat_panel.py   # 该文件未创建，先完成 Task 1 Step 1
git commit -m "test(cfg): 扁平化与图标内衬的跨档运行时门禁"
```

---

## Self-Review

**1. Spec coverage**

| 用户诉求 | 任务 |
| --- | --- |
| 「右侧面板的图标和边缘都在一块了」 | Task 2（登录行图标 0→12）、Task 3（band 图标 0→12） |
| 「左侧和右侧页面不够扁平化」 | Task 1（右卡左右内衬对称）、Task 4（选中态软底，去辉光/竖线）、Task 5（左右同为内容表面，去卡中卡） |
| 跨档不回归 | Task 6 |

**2. Placeholder scan**：无 TBD / 「适当处理」/ 「类似 Task N」。每个 CSS 改动都给了完整声明原文。

**3. Type consistency**：测试文件全程为 tests/test_cfg_flat_panel.py（本计划待建，未创建）；探针为 `_scratch/probe_cfg_flatness.py`（几何）与 `_scratch/probe_cfg_states.py`（状态）；选择器 `#loginRows .lgcard` / `.chband` / `.cfgnav` / `.cnav` 在计划与测试中一致。

**4. 已知风险**

- `test_r872_cfg_layers_one_left_edge` 可能因内衬平移而红——已给出处置方式（改参考边，不改回 0）。
- `.cnav.on` 的改动可能影响 `ui test` 里按颜色认选中态的断言；若红，改断言守意图（「选中与未选中背景不同」），不要改回实心辉光。
- 并行会话随时可能改写 `webui.py`：每次提交前必须 `git diff --cached --stat` 核对行数。
