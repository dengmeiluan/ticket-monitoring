# 配置页扁平等化 + 检索页耦合重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让配置页左右两栏同一套扁平表面语言、图标不贴边；让检索页的「渠道入口」展开时触发器原地不动、面板就地展开、不把 14 日价带推走。

**Architecture:** 单文件 SPA（`webui.py`，`PAGE` 是约 4.4MB 的字符串）。全部改动都在 **CSS 声明层**：不新增组件、不改 DOM 结构、不动数据逻辑。核心是把「零内衬」「display:contents 撑开整行」「实心+辉光选中态」这三类获胜规则改成正解。

**Tech Stack:** 纯 CSS + pytest（静态契约）+ Playwright（运行时几何）。

**Spec:** 用户口述（2026-10-31 两条）＋实测证据（见下，全部为 1512×950 demo 服真实渲染值）。

## Global Constraints

- **绝不整文件 `git add webui.py`**：并行会话正在改它。只按 hunk 暂存，提交前 `git diff --cached --stat` 行数必须等于本次改的行数。
- 不新增 `skip`/`xfail`；不改 `config.yaml`/`data/prices.db`/`user_data/`；不推送、不移标签、不发布。
- 颜色/圆角/间距只走既有令牌，**不得新造 hex**。圆角只用 `--r`(14)/`--r2`(11)/`--r3`(9)/`--r10`(10)/`--pill`。
- 间距只落 4/6/8/12/16/24 阶（0/1/2 为微间距）。
- **每条改动都必须有运行时几何证据**——静态断言测不出「被更后的规则覆盖」。

## 实测证据（1512×950，demo 服）

### 配置页

| # | 现象 | 实测值 | 目标 |
| --- | --- | --- | --- |
| A | 右面板内容贴左缘 | `.ucard` `padding:14px 16px 14px **0px**`；内容 `minLeft=295.5`＝卡左缘；左内衬 **0**、右 16 | 左右各 **16** |
| B | 登录行图标贴边 | `#loginRows .lgcard` `padding:9px 0px`；`iconInsetFromRow=**0**` | ≥**12** |
| C | 渠道入口 band 图标贴边 | `.chband` `padding:7px 0px 6px`；`iconInset=**0**` | ≥**12** |
| D | 左导航选中态非扁平 | 渲染 `bg=transparent`、`border-left:2px`、`shadow:none` | 软蓝底、无投影、无竖线 |
| E | 左导航无表面 | `.cfgnav` `bg=transparent / radius:0 / 无边框`，右侧是白卡 | 与右卡同族表面 |

### 检索页

| # | 现象 | 实测值 | 目标 |
| --- | --- | --- | --- |
| F | **渠道入口展开时触发器消失** | `summary` 的 rect 变 **0×0**；内容盒 **1028×732** 插到下方；14 日价带 `top` **320.9 → 1056.9（+736px）** | 展开前后触发器坐标差 **≤1px**；面板就地展开 |
| G | 面板与触发器不同列 | 内容盒 `left=91.5`，触发器 `left=1131.4`——横向回退 **1039.9px** | 面板落在触发器同一右列 |

F/G 的根因：`#searchview .srx-probefoot .srx-chlinks[open]{display:contents}` 把 `<details>` 拆成透明盒子，于是 summary 与面板变成父网格的直接子项。r523 的意图是「summary 留在原位、面板占满下一整行」，但**面板宽 1028px、高 732px**，等于把整个 7 家渠道 × 4 入口的矩阵塞进探针脚注，把下方所有内容推走。触发器 rect 归零是因为 summary 被 `grid-row:1;grid-column:2` 约束后，在 `display:contents` 下失去了自身盒。

**正确的形态**：渠道入口是**次级面板**，不应内联铺开在探针脚注里。改为「触发器不动 + 面板在同一列的浮层里展示」，既不改页面高度，也不推挤任何邻居。

---

### Task 1: 右面板左右内衬对称（缺陷 A）

**Files:**
- Modify: `webui.py`：`#cfgview .ucard`、`#cfgview .ucbody`
- Test: `tests/test_cfg_search_flat.py`（**未创建，本计划待建**）

**Interfaces:**
- Consumes: 无
- Produces: `#cfgview` 下 `.ucard` 左右内衬均为 16px；`.ucbody` 不再自带左内衬

**背景**：`.ucard` 实测 `padding:14px 16px 14px 0px`——右 16、左 0。内层 `#cfgview .ucbody{padding:4px 0 14px!important}` 与 `padding-left:16px!important` 只给部分分块补了左内衬，卡头与分块因此错位 16px。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_cfg_search_flat.py`（未创建，本计划待建）：

```python
# -*- coding: utf-8 -*-
"""配置页扁平化 + 检索页展开耦合：内衬、图标留白、触发器不位移。"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src():
    import webui
    return webui.PAGE


def test_cfg_card_padding_is_symmetric():
    """#cfgview 下 .ucard 左右内衬必须相等。

    实测踩过（2026-10-31，1512）：.ucard 计算值 padding 为
    `14px 16px 14px 0px`——右 16、左 0，内容 minLeft 等于卡左缘。
    """
    src = _src()
    i = src.find("#cfgview .ucard{")
    assert i > 0, "找不到 #cfgview .ucard 规则"
    blk = src[i:src.find("}", i) + 1]
    m = re.search(r"padding:\s*([^;}]+)", blk)
    assert m, "该规则没有 padding：%s" % blk[:160]
    parts = m.group(1).split()
    assert len(parts) >= 2, parts
    left, right = parts[3] if len(parts) == 4 else parts[1], parts[1]
    if len(parts) == 4:
        left, right = parts[3], parts[1]
    else:
        left = right = parts[1]
    assert left == right, (
        "右面板左右内衬不等（会贴左缘）：%s" % m.group(1))
    assert float(re.match(r"(-?[\d.]+)", left).group(1)) >= 12, (
        "内衬过小：%s" % m.group(1))
```

- [ ] **Step 2: 运行确认失败**

Run: `PYTHONIOENCODING=utf-8 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_cfg_search_flat.py::test_cfg_card_padding_is_symmetric -q`   # 该文件未创建，先完成 Step 1
Expected: FAIL，提示「右面板左右内衬不等」

- [ ] **Step 3: 改 CSS**

把 `#cfgview .ucard` 那条改成左右对称：

```css
#cfgview .ucard{border-color:color-mix(in srgb,var(--line) 55%,transparent);box-shadow:0 1px 3px rgba(15,23,42,.035);padding:14px 16px;box-sizing:border-box}
```

并把 `#cfgview .ucbody` 两条合并为一条（去掉左内衬，交给父卡）：

```css
/* 内衬由父卡统一提供（左右各 16）。此前父卡左侧 0、内层补 16，
   卡头与分块左缘因此相差 16px（1512 实测 minLeft = 卡左缘）。 */
#cfgview .ucbody{padding:4px 0 14px!important}
```

删除原本的 `#cfgview .ucbody{padding-left:16px!important}`。

- [ ] **Step 4: 运行确认通过**

Run: `PYTHONIOENCODING=utf-8 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_cfg_search_flat.py -q`   # 该文件未创建，先完成 Step 1
Expected: PASS

- [ ] **Step 5: 运行时几何复验**

```bash
PYTHONIOENCODING=utf-8 python _scratch/probe_cfg_states.py
```
Expected: `cardPad.left == "16px"`、`cardPad.right == "16px"`、`cardContent.leftInset ≈ 16`、`rightInset ≈ 16`。

- [ ] **Step 6: 暂存并提交（只暂存自己的 hunk）**

```bash
git diff webui.py > /tmp/t1.patch
git apply --cached --recount /tmp/t1.patch
git diff --cached --stat          # 行数必须等于本次改动，看到几百行=停
git add tests/test_cfg_search_flat.py   # 该文件未创建，先完成 Task 1 Step 1
git commit -m "fix(cfg): 右面板左右内衬对称，内容不再贴左缘"
```

---

### Task 2: 渠道登录行图标留内衬（缺陷 B）

**Files:**
- Modify: `webui.py`：`#loginRows .lgcard`（两处 padding）
- Test: `tests/test_cfg_search_flat.py`（追加）   # 该文件未创建，先完成 Task 1 Step 1

**Interfaces:**
- Consumes: Task 1 的测试文件
- Produces: `#loginRows .lgcard` 横向内衬 ≥10px

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_cfg_search_flat.py`（该文件未创建，Task 1 待建）：

```python
def test_login_rows_leave_room_before_the_icon():
    """渠道登录行横向内衬不得为 0（否则 24px 图标贴住行左缘）。

    实测踩过（2026-10-31，1512）：#loginRows .lgcard 计算值 `padding:9px 0px`，
    iconInsetFromRow = 0。
    """
    src = _src()
    offenders = []
    for m in re.finditer(r"#loginRows \.lgcard\{([^}]*)\}", src):
        body = m.group(1).replace(" ", "")
        pad = re.search(r"padding:([^;}!]+)", body)
        if not pad:
            continue
        parts = pad.group(1).split()
        horiz = parts[1] if len(parts) >= 2 else parts[0]
        if float(re.match(r"(-?[\d.]+)px", horiz).group(1)) <= 0:
            offenders.append(pad.group(1))
    assert not offenders, "渠道登录行出现 0 横向内衬：%s" % offenders
```

- [ ] **Step 2: 运行确认失败**

Run: `PYTHONIOENCODING=utf-8 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_cfg_search_flat.py::test_login_rows_leave_room_before_the_icon -q`   # 该文件未创建，先完成 Task 1 Step 1
Expected: FAIL，列出 `['10px 2px']` / `['9px 0px']`

- [ ] **Step 3: 改 CSS（两处都要改）**

第一处（`box-shadow:none!important;border:0!important;border-bottom:...` 那条）：

```css
#loginRows .lgcard{box-shadow:none!important;border:0!important;border-bottom:1px solid var(--r-hair)!important;
 border-radius:0!important;background:transparent!important;padding:10px 12px!important;min-height:0!important}
```

第二处（含 `border-top:1px solid var(--r-hair)` 与 `min-height:52px` 那条）：

```css
 padding:9px 12px!important;min-height:52px!important;box-sizing:border-box!important}
```

- [ ] **Step 4: 运行确认通过**

Run: `PYTHONIOENCODING=utf-8 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_cfg_search_flat.py -q`   # 该文件未创建，先完成 Task 1 Step 1
Expected: PASS

- [ ] **Step 5: 运行时复验**

```bash
PYTHONIOENCODING=utf-8 python _scratch/probe_cfg_flatness.py
```
Expected: 每行 `iconInsetFromRow >= 12`；`rowH` 仍为 **52**（内衬变化不得改行高）。

- [ ] **Step 6: 暂存并提交**

```bash
git diff webui.py > /tmp/t2.patch && git apply --cached --recount /tmp/t2.patch
git diff --cached --stat
git add tests/test_cfg_search_flat.py   # 该文件未创建，先完成 Task 1 Step 1
git commit -m "fix(cfg): 渠道登录行给图标留内衬"
```

---

### Task 3: 渠道入口 band 图标留内衬（缺陷 C）

**Files:**
- Modify: `webui.py`：两条 `.chband{...padding:...}` 规则
- Test: `tests/test_cfg_search_flat.py`（追加）   # 该文件未创建，先完成 Task 1 Step 1

- [ ] **Step 1: 写失败测试**

```python
def test_channel_bands_leave_room_before_the_icon():
    """渠道入口每条 band 横向内衬不得为 0。

    实测踩过（2026-10-31，1512）：.chband 计算值 `padding:7px 0px 6px`，
    iconInset = 0。
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
        if float(re.match(r"(-?[\d.]+)px", horiz).group(1)) <= 0:
            offenders.append(pad.group(1))
    assert not offenders, "渠道入口 band 出现 0 横向内衬：%s" % offenders
```

- [ ] **Step 2: 运行确认失败**

Run: `PYTHONIOENCODING=utf-8 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_cfg_search_flat.py::test_channel_bands_leave_room_before_the_icon -q`   # 该文件未创建，先完成 Task 1 Step 1
Expected: FAIL，列出 `['10px 2px']`、`['7px 0 6px']`

- [ ] **Step 3: 改 CSS（两条）**

第一条（`grid-template-columns:148px`）：

```css
.chband{grid-template-columns:148px minmax(0,1fr)!important;gap:8px!important;
 padding:10px 12px!important;border:0!important;border-bottom:1px solid var(--r-hair)!important;
 border-radius:0!important;background:transparent!important}
```

第二条（v304e，`grid-template-columns:160px`）：

```css
.chband{display:grid!important;grid-template-columns:160px minmax(0,1fr)!important;gap:6px!important;padding:7px 12px 6px!important;border:0!important;border-radius:0!important;background:transparent!important}
```

- [ ] **Step 4: 运行确认通过**

Run: `PYTHONIOENCODING=utf-8 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_cfg_search_flat.py -q`   # 该文件未创建，先完成 Task 1 Step 1
Expected: PASS

- [ ] **Step 5: 运行时复验（含 390 档不溢出）**

```bash
PYTHONIOENCODING=utf-8 python _scratch/probe_cfg_flatness.py
```
Expected: 每条 band `iconInset >= 12`；band `h` 仍为 **91**；390 档 `scrollWidth <= clientWidth + 1`。

- [ ] **Step 6: 暂存并提交**

```bash
git diff webui.py > /tmp/t3.patch && git apply --cached --recount /tmp/t3.patch
git diff --cached --stat
git add tests/test_cfg_search_flat.py   # 该文件未创建，先完成 Task 1 Step 1
git commit -m "fix(cfg): 渠道入口 band 给图标留内衬"
```

---

### Task 4: 左导航扁平选中态（缺陷 D）

**Files:**
- Modify: `webui.py`：`.cnav.on`、并删除后续那条把它清成 `transparent + border-left` 的覆盖
- Test: `tests/test_cfg_search_flat.py`（追加）   # 该文件未创建，先完成 Task 1 Step 1

- [ ] **Step 1: 写失败测试**

```python
def test_cnav_selected_state_is_flat():
    """.cnav 选中态用软底，不带投影、不靠左侧竖线。

    实测踩过（2026-10-31，1512）：改前是 --fill 实心 + box-shadow 辉光，
    后续扁平层又清成 transparent + border-left:2px。两者都不是扁平选中语言。
    """
    src = _src()
    assert ".cnav.on{background:var(--r-blue-soft)" in src.replace(" ", ""), \
        "选中态不是软蓝底"
    i = src.find(".cnav.on{")
    blk = src[i:src.find("}", i) + 1]
    assert "border-left" not in blk, "选中态仍靠左侧竖线：%s" % blk[:120]
    assert "0 2px 8px" not in blk, "选中态仍带辉光投影：%s" % blk[:120]
```

- [ ] **Step 2: 运行确认失败**

Run: `PYTHONIOENCODING=utf-8 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_cfg_search_flat.py::test_cnav_selected_state_is_flat -q`   # 该文件未创建，先完成 Task 1 Step 1
Expected: FAIL，提示「选中态不是软蓝底」

- [ ] **Step 3: 改 CSS**

```css
/* 选中态用软蓝底 + 品牌色文字（扁平语言）：不投影、不用左侧竖线。
   改前是 --fill 实心 + 辉光；后续层又清成 transparent + 竖线，两败。 */
.cnav.on{background:var(--r-blue-soft);color:var(--blue);box-shadow:none}
```

保留焦点环：

```css
.cnav.on:focus-visible{box-shadow:0 0 0 2px var(--blue)}
```

并找到后续把它清成 `transparent + border-left:2px` 的那条规则（含 `.cnav.on` 与 `border-left`），整条删除。

- [ ] **Step 4: 运行确认通过**

Run: `PYTHONIOENCODING=utf-8 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_cfg_search_flat.py -q`   # 该文件未创建，先完成 Task 1 Step 1
Expected: PASS

- [ ] **Step 5: 运行时复验三态**

```bash
PYTHONIOENCODING=utf-8 python _scratch/probe_cfg_states.py
```
Expected: `cnavOn.bg` 非透明且为软蓝、`cnavOn.boxShadow == "none"`、`cnavOn.borderLeft` 宽 `0px`、`cnavOff.bg == "rgba(0, 0, 0, 0)"`。

- [ ] **Step 6: 暂存并提交**

```bash
git diff webui.py > /tmp/t4.patch && git apply --cached --recount /tmp/t4.patch
git diff --cached --stat
git add tests/test_cfg_search_flat.py   # 该文件未创建，先完成 Task 1 Step 1
git commit -m "fix(cfg): 左导航选中态改软蓝底，去实心辉光与左竖线"
```

---

### Task 5: 左导航与右面板同层表面（缺陷 E）

**Files:**
- Modify: `webui.py`：`.cfgnav`、`.cnav`
- Test: `tests/test_cfg_search_flat.py`（追加）   # 该文件未创建，先完成 Task 1 Step 1

- [ ] **Step 1: 写失败测试**

```python
def test_cfg_nav_shares_the_card_surface():
    """左导航要与右侧面板同一种表面，不能是裸列。

    实测踩过（2026-10-31，1512）：.cfgnav background:transparent、radius:0、
    无边框，右侧 .ucard 是白底 + 14px 圆角，同屏左右重量差一层级。
    """
    src = _src()
    i = src.find(".cfgnav{")
    assert i > 0, "找不到 .cfgnav"
    blk = src[i:src.find("}", i) + 1].replace(" ", "")
    assert "background:var(--card)" in blk, "左导航没有内容表面：%s" % blk[:150]
    assert "border-radius:var(--r)" in blk, "左导航圆角未走令牌：%s" % blk[:150]
    assert "border:1pxsolidvar(--line)" in blk, "左导航缺 1px 发丝边：%s" % blk[:150]
```

- [ ] **Step 2: 运行确认失败**

Run: `PYTHONIOENCODING=utf-8 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_cfg_search_flat.py::test_cfg_nav_shares_the_card_surface -q`   # 该文件未创建，先完成 Task 1 Step 1
Expected: FAIL，提示「左导航没有内容表面」

- [ ] **Step 3: 改 CSS**

```css
/* 与右侧面板同一套表面语言（--card + --r + 1px 发丝边）：
   此前是裸列（transparent / 0 圆角 / 0 边框），左右重量差一层级。 */
.cfgnav{position:sticky;top:calc(var(--hdh,54px) + 4px);display:flex;flex-direction:column;gap:4px;
 align-self:start;max-height:calc(100vh - var(--hdh,54px) - 16px);overflow:auto;
 background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:12px}
```

导航项降为行（否则卡中卡）：

```css
/* 侧栏已上浮，导航项不再各自成卡（卡中卡）：透明底 + r3 圆角 + 悬停软底 */
.cnav{background:transparent;border:1px solid transparent;border-radius:var(--r3);
 padding:8px 10px;cursor:pointer;font-size:13px;color:var(--tx2);font-weight:600;
 transition:.15s;user-select:none}
.cnav:hover{background:var(--hover)}
```

- [ ] **Step 4: 运行确认通过**

Run: `PYTHONIOENCODING=utf-8 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_cfg_search_flat.py -q`   # 该文件未创建，先完成 Task 1 Step 1
Expected: PASS

- [ ] **Step 5: 运行时复验 + 卡中卡 + 顶边对齐**

```bash
PYTHONIOENCODING=utf-8 python _scratch/probe_cfg_states.py
```
Expected: `navSurface.bg == "rgb(255, 255, 255)"`、`navSurface.radius == "14px"`、`navSurface.border` 以 `1px` 开头；`cnavOff.bg == "rgba(0, 0, 0, 0)"`；`nav.top == card.top`。

- [ ] **Step 6: 暂存并提交**

```bash
git diff webui.py > /tmp/t5.patch && git apply --cached --recount /tmp/t5.patch
git diff --cached --stat
git add tests/test_cfg_search_flat.py   # 该文件未创建，先完成 Task 1 Step 1
git commit -m "fix(cfg): 左导航与右面板同层表面，去整列裸边"
```

---

### Task 6: 检索页「渠道入口」触发器不动 + 面板就地展开（缺陷 F/G）

**Files:**
- Modify: `webui.py`：`#searchview .srx-probefoot .srx-chlinks[open]` 相关 4 条规则
- Test: `tests/test_cfg_search_flat.py`（追加静态契约）+ `_scratch/probe_search_chlinks.py`（运行时证据）   # 该文件未创建，先完成 Task 1 Step 1

**Interfaces:**
- Consumes: Task 1–5 的测试文件
- Produces: 展开前后 `#srxChLinks` 的 `left/top/width/height` 差 ≤1px；面板 `max-height` 受限并可滚动

**背景（实测）**：展开后 `summary` 的 rect 变 **0×0**，内容盒 **1028×732** 整行插入，14 日价带 `top` 从 **320.9** 被推到 **1056.9（+736px）**。用户原话「渠道入口按钮点击都位置变了」。

**修法**：放弃「内联铺开整行」，改成**触发器原地不动 + 面板在触发器下方就地展开且限高滚动**。面板宽度与触发器同列（右列），不再横跨整行——它属于「渠道入口」这一项，不属于整条探针脚注。

- [ ] **Step 1: 写失败测试（静态）**

```python
def test_channel_entry_expands_in_place_without_moving_trigger():
    """渠道入口展开不得把触发器移走、也不得把下方内容推走。

    实测踩过（2026-10-31，1512）：展开后 summary rect 变 0×0，
    内容盒 1028×732 整行插入，14 日价带 top 从 320.9 推到 1056.9（+736px）。
    """
    src = _src()
    # 禁止再用 display:contents 拆盒（它会让 summary 失去自身盒 → rect 0×0）
    i = src.find(".srx-probefoot .srx-chlinks[open]")
    assert i > 0, "找不到渠道入口展开态规则"
    seg = src[i:i + 600]
    assert "display:contents" not in seg, (
        "展开态仍用 display:contents 拆盒，触发器会失去盒子（rect 0×0）")
    # 面板必须有高度上限，否则长矩阵会把页面撑开
    j = src.find("#searchview .srx-probefoot .srx-chlinks[open]>#srxChLinksBox")
    assert j > 0, "找不到面板展开规则"
    box = src[j:src.find("}", j) + 1]
    assert "max-height" in box, (
        "展开面板没有 max-height，长内容会推走下方所有内容：%s" % box[:200])
    assert "overflow" in box, "展开面板没有 overflow（不可滚动）：%s" % box[:200]
```

- [ ] **Step 2: 运行确认失败**

Run: `PYTHONIOENCODING=utf-8 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_cfg_search_flat.py::test_channel_entry_expands_in_place_without_moving_trigger -q`   # 该文件未创建，先完成 Task 1 Step 1
Expected: FAIL，提示「展开态仍用 display:contents 拆盒」

- [ ] **Step 3: 改 CSS**

把这一组（`[open]{display:contents}` / `[open]>summary{grid-row:1;grid-column:2}` / `[open]>#srxChLinksBox{grid-row:2;grid-column:1/-1}`）替换成：

```css
/* 渠道入口展开：触发器原地不动，面板在**同一右列**就地展开并限高滚动。
   旧实现用 display:contents 把 details 拆成透明盒，让面板横跨整行
   （实测宽 1028 / 高 732），把 14 日价带从 320.9 推到 1056.9（+736px），
   summary 自身 rect 归零 —— 用户读作「点了按钮，按钮和整页都跑了」。
   渠道入口是「一个次级面板」，不是页面级内容区：定高滚动即可。 */
#searchview .srx-probefoot .srx-chlinks{position:relative}
#searchview .srx-probefoot .srx-chlinks[open]>#srxChLinksBox{
  grid-column:2;justify-self:end;width:min(560px,calc(100vw - 32px));
  max-height:min(52vh,420px);overflow:auto;margin-top:6px;
  padding:10px 12px;border:1px solid var(--line);border-radius:var(--r10);
  background:var(--card);box-shadow:0 8px 24px -12px rgba(15,23,42,.18)}
```

同时删除窄档那两条把面板改成 `grid-row:2/3;grid-column:1` 的规则（`@media` 内的 7835/7836 行），改成同一条在窄档铺满宽度：

```css
@media(max-width:760px){
 #searchview .srx-probefoot .srx-chlinks[open]>#srxChLinksBox{
   grid-column:1/-1;justify-self:stretch;width:auto}
}
```

**注意**：`.srx-probefoot` 是 `grid-template-columns:minmax(0,1fr) auto` 两列网格，面板放第 2 列并 `justify-self:end` 即与触发器右缘对齐；`max-height` + `overflow:auto` 保证长内容不撑页面。

- [ ] **Step 4: 运行确认通过**

Run: `PYTHONIOENCODING=utf-8 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_cfg_search_flat.py -q`   # 该文件未创建，先完成 Task 1 Step 1
Expected: PASS

- [ ] **Step 5: 运行时复验（最关键的一步）**

```bash
PYTHONIOENCODING=utf-8 python _scratch/probe_search_chlinks.py
```
Expected:
- `== 探针展开后 ==` 与 `== 渠道入口展开后 ==` 两段里，`chlinks` 的 `l/t/w/h` **完全一致**
- 面板 `box.h <= 420`，`box` 右缘与 summary 右缘差 ≤2px
- `bandTop`（14 日价带）在展开前后**不变**（允许 ≤4px）
- `== 收起后 ==` 的坐标与展开前一致

- [ ] **Step 6: 四档宽度复验**

把 `probe_search_chlinks.py` 的 viewport 改成 1280 / 900 / 390 各跑一次，Expected：每档触发器坐标三态一致、无横向溢出。

- [ ] **Step 7: 暂存并提交**

```bash
git diff webui.py > /tmp/t6.patch && git apply --cached --recount /tmp/t6.patch
git diff --cached --stat
git add tests/test_cfg_search_flat.py   # 该文件未创建，先完成 Task 1 Step 1
git commit -m "fix(search): 渠道入口就地展开，触发器不动、不再推走价带"
```

---

### Task 7: 全档 + 暗色 + 回归 + 全量门禁

**Files:**
- Test: `tests/test_cfg_search_flat.py`（追加运行时跨档用例）   # 该文件未创建，先完成 Task 1 Step 1
- 不改产品代码

- [ ] **Step 1: 写跨档运行时测试**

```python
def test_flat_fixes_hold_at_every_breakpoint():
    """四档宽度下：配置页内衬对称、图标不贴边、左导航有表面；
    检索页渠道入口三态触发器坐标一致。"""
    import subprocess, sys, time, urllib.request
    import pytest
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    port = 9198
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

                # --- 配置页 ---
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
                  return {padL:parseFloat(cs(card,'paddingLeft')), padR:parseFloat(cs(card,'paddingRight')),
                          iconRow: ic? +(r(ic).left-r(row).left).toFixed(1):null,
                          iconBand: bic? +(r(bic).left-r(band).left).toFixed(1):null,
                          navBg: cs(nav,'backgroundColor'),
                          overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth+1};}""")
                assert m["padL"] == m["padR"] >= 12, "%d 档右面板内衬不对称：%s" % (w, m)
                if m["iconRow"] is not None:
                    assert m["iconRow"] >= 8, "%d 档登录行图标贴边：%s" % (w, m)
                if m["iconBand"] is not None:
                    assert m["iconBand"] >= 6, "%d 档 band 图标贴边：%s" % (w, m)
                assert m["navBg"] not in ("rgba(0, 0, 0, 0)", "transparent"), \
                    "%d 档左导航无表面：%s" % (w, m)
                assert not m["overflow"], "%d 档配置页横向溢出" % w

                # --- 检索页 ---
                pg.evaluate("()=>switchView('search')")
                pg.wait_for_timeout(1200)
                geo = "()=>{const e=document.querySelector('#srxChLinks');const r=e.getBoundingClientRect();" \
                      "return {l:+r.left.toFixed(1),t:+r.top.toFixed(1),w:+r.width.toFixed(1),h:+r.height.toFixed(1),}" \
                      "}" if False else """()=>{const e=document.querySelector('#srxChLinks');
                        const r=e.getBoundingClientRect();
                        return {l:+r.left.toFixed(1),t:+r.top.toFixed(1),
                                w:+r.width.toFixed(1),h:+r.height.toFixed(1)};}"""
                before = pg.evaluate(geo)
                pg.evaluate("""()=>{const d=document.querySelector('#srxChLinks');
                    if(d&&!d.open){d.open=true;d.dispatchEvent(new Event('toggle'));}}""")
                pg.wait_for_timeout(900)
                opened = pg.evaluate(geo)
                pg.evaluate("""()=>{const d=document.querySelector('#srxChLinks');
                    if(d&&d.open){d.open=false;d.dispatchEvent(new Event('toggle'));}}""")
                pg.wait_for_timeout(700)
                closed = pg.evaluate(geo)
                for label, got in (("展开", opened), ("收起", closed)):
                    assert abs(got["l"] - before["l"]) <= 1, \
                        "%d 档%s后触发器左移 %s → %s" % (w, label, before, got)
                    assert abs(got["t"] - before["t"]) <= 1, \
                        "%d 档%s后触发器上移 %s → %s" % (w, label, before, got)

                pg.close()
            b.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
```

- [ ] **Step 2: 运行**

Run: `PYTHONIOENCODING=utf-8 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_cfg_search_flat.py -q`   # 该文件未创建，先完成 Task 1 Step 1
Expected: 全部 PASS

- [ ] **Step 3: 相关既有套件防回归**

```bash
PYTHONIOENCODING=utf-8 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_r872_cfg_layers_one_left_edge.py \
  tests/test_r412_login_rows_alignment.py \
  tests/test_r837_channel_band_indent.py \
  tests/test_r870_cfg_fold_keeps_heads.py -q
```
（基线已实测：这 4 个文件当前 **53 passed**。）

**若 `test_r872` 红**：它钉「四层首字落点极差 ≤6px」。父卡内衬 0→16 会整体平移首字——把用例的参考边改成「卡内容边」，并在提交说明写明「契约变更，非回归」。**不要**把内衬改回 0。

- [ ] **Step 4: 截图人工确认**

```bash
PYTHONIOENCODING=utf-8 python _scratch/probe_cfg_flatness.py     # 产出 _scratch/cfg_login_1512.png
PYTHONIOENCODING=utf-8 python _scratch/probe_search_chlinks.py   # 产出 _scratch/search_chlinks_open.png
```
目视确认：图标与左边框之间有可见间距；左右两栏同一表面；渠道入口面板不再横跨整页。

- [ ] **Step 5: 全量门禁（哈希定格）**

```bash
md5sum webui.py
python tools/test_all.py
md5sum webui.py        # 必须与上面一致
```
Expected: `pytest … passed N / failed 0`、`uitest … N/N`、退出码 0。
退出码 3 = 跑测期间被并行会话改写，**结果作废、重跑**，不是失败。

- [ ] **Step 6: 提交测试**

```bash
git add tests/test_cfg_search_flat.py   # 该文件未创建，先完成 Task 1 Step 1
git commit -m "test(cfg/search): 扁平化与渠道入口就地展开的跨档运行时门禁"
```

---

## Self-Review

**1. Spec coverage**

| 用户诉求 | 任务 |
| --- | --- |
| 「配置页左侧和右侧不够扁平化」 | Task 1（右卡内衬对称）、Task 4（选中态软底）、Task 5（左右同表面，去卡中卡） |
| 「右边面板的图标和边缘都在一块了」 | Task 2（登录行 0→12）、Task 3（band 0→12） |
| 「渠道入口按钮点击位置变了」 | Task 6（触发器三态坐标差 ≤1px） |
| 「整体布局排版约束继续重构」 | Task 6（面板限高滚动，不再推走价带）+ Task 7（四档运行时约束） |
| 「不允许按钮乱跑乱飘」 | Task 6 Step 5/6 的三态坐标断言 + Task 7 的跨档断言 |
| 「组件之间元素协调不割裂」 | Task 5（左右同表面）、Task 6（面板落回自己那一列） |

**2. Placeholder scan**：无 TBD / 「适当处理」。每处 CSS 都给了可粘贴的完整声明。

**3. Type consistency**：测试文件统一 `tests/test_cfg_search_flat.py`（未创建，本计划待建）；探针 `_scratch/probe_cfg_flatness.py`（几何）/`probe_cfg_states.py`（状态）/`probe_search_chlinks.py`（检索页三态）；选择器 `#loginRows .lgcard` / `.chband` / `.cfgnav` / `.cnav` / `#srxChLinks` 全文一致。

**4. 已知风险**

- `test_r872` 可能因内衬平移变红（已给处置：改参考边）。
- `.cnav` 从白卡降为行，可能影响按「每条都是卡」写断言的用例；若红，改断言守意图（「选中与未选中背景不同」）。
- 渠道入口面板改浮层后，`srxChLinksToggle()` 里若有按宽度算布局的逻辑需要复核（Task 6 Step 5 运行时会暴露）。
- 并行会话随时改写 `webui.py`：每次提交前 `git diff --cached --stat` 核行数。
---

**落地状态（2026-10-31 复核）**：本清单的 43 个复选框未逐项回填，但其中若干项**已经落地**——
`webui.py` 里已能看到 `#cfgnav .cnav.on` 的透明底 + 2px 左线选中标记、`.ucard{padding-left:16px}`
单源内衬、`.ucbody` / `.uhead` 归零、`srf-card` 使用 `--r10` 令牌等；
对应的门禁 `tests/test_cfg_search_flat.py`、`tests/test_r872_cfg_layers_one_left_edge.py`、
`tests/test_r645_config_single_indent.py`、`tests/test_r314_webui_polish.py` 均已存在。
清单本身保留为「计划原文」，未勾选**不代表未开工**；后续按实际代码与门禁为准。
