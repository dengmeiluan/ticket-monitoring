# 交接指导书 · 机票监控台（通用：发版流程 / 文档门禁 / 操作纪律）

> **读者对象**：接手继续本项目的会话（AI 或人类协作者）。
> **编写时间**：2026-10-31 20:20（所有数字均为当时实测）。
> **使用方式**：先读 §0–§3 搞清现状，再按 §8 的优先级动手。**开工前必须按 §2 亲自核验一遍**，本文件里的数字会变。
> **本文件也受门禁管辖**：改完后要跑 §10 的验证清单。
>
> **交接文档的分工**（阅读顺序）：
> - **①** `docs/HANDOFF_FULL_SESSION.md` —— **总纲：12 项目标与期望标准 + 验收标准 + 方法论 + 现状**（最先读）
> - ② `docs/HANDOFF_CAPABILITY_MATRIX.md` —— 10 渠道能力一致性专项（10×7 不变式、新增渠道 checklist）
> - **③ 本文** —— **通用层**：发版七步、文档门禁体系、操作纪律、80 条教训清单
> - **④** `docs/SESSION_EXPERIENCE_GUIDE.md` —— **最近一次长会话（r794–r812b）的完整经验书**：用户全部目标与期望、逐轮修法 / 证据 / 门禁、判据陷阱 40 条、开工与交接清单、当前真实状态。**接手新任务前先读它**；本文 §0 的「当前状态」已滞后。

---

## 目录

- [0. 一句话现状](#0-一句话现状)
- [1. 项目是什么](#1-项目是什么)
- [2. 开工第一件事：核验现场](#2-开工第一件事核验现场)
- [3. 当前真实差距（交接必读）](#3-当前真实差距交接必读)
- [4. 文档门禁体系](#4-文档门禁体系)
- [5. 发版流程](#5-发版流程)
- [6. 文档漂移的六类模式](#6-文档漂移的六类模式)
- [7. 操作纪律](#7-操作纪律)
- [8. 下一步建议](#8-下一步建议)
- [9. 关键文件速查](#9-关键文件速查)
- [10. 验证清单](#10-验证清单)
- [11. 附录：本会话完整教训清单](#11-附录本会话完整教训清单)

---

## 0. 一句话现状

**发布树 v1.5.307（tag `v1.0` → `e65cee1`，2026-11-03 09:54 由 `ab04c22` 重指）已四端对齐；live 8765 已于 2026-11-03 08:58 切到 `_release_ab04`（10 渠道，PID 47952，live 树仍为 `ab04c22`）。当前工作树另有 r933–r935（多程数据层/配置隔离/实际渠道错峰）未提交。**

| 维度 | 状态 |
|---|---|
| 版本 | `main.py` = **1.5.307** |
| HEAD / 远程 `main` | 以 `git log -1 origin/main` 为准（2026-11-03 21:12 核对 `03a46e6`） |
| 远程 `v1.0` tag | **`e65cee1`**（2026-11-03 09:54 重指） |
| 发布资产 | 四平台包 v1.5.307（2026-11-03T01:54Z 重建），SHA256SUMS 与 API digest **4/4 相等** |
| 工作区 | 10 渠道（5 浏览器 + 5 App）+ 国际往返/日历/多程解析等未提交；10 渠道改动**未发布** |
| 全量非 UI | 以 `docs/EXECUTION_SPEC_LATEST.md` §1.0 为准；最后一次 clean 门禁为 HEAD `bc96947` **6326 passed / 44 skipped / 0 failed**（2026-11-03 20:19，workers 8），此后新增测试由后续门禁覆盖 |
| UI | **670/670**（2026-11-03 15:15 全量复跑，零 JS 错误；含矩阵 ctrip 多程 ✓ 仅 2 段与 r958 的 9 个配置控件；矩阵含携程 App round_trip=国内/国际、同程 App intl=日历/明细、同程 App round_trip=国际；r905 行内按钮另由 r905 + r640 四档覆盖） |
| 发布对齐 | `release_align_check --local` **25/25**（2026-11-03 20:22，HEAD `c985ce0`）；动态字段以工具当次输出为准 |
| live 8765 | **已切 10 渠道**（`_release_ab04`，live 树 `ab04c22`，PID 47952）；切换/回滚记录见 `docs/LIVE_PROMOTION_RUNBOOK.md` |

---

## 1. 项目是什么

自托管的多渠道机票价格监控：明细采集 → 钉钉图文推送 → 达标四层强提醒。

**渠道从 5 家扩到 10 家**：携程、去哪儿、飞猪、同程、途牛（浏览器/H5/HTTP）+ **智行、去哪儿、飞猪、同程、携程 App**（Android App 自动化，见 `crawlers/app_*.py`）。

### 1.1 不可违反的产品边界

1. **合成数据必须诚实标注**。演示站/在线站都是合成数据，绝不标成"正常"；`—` 只表示"没有样本"。
2. **`empty` 必须有站点的明确无票证据**。拿不到/没解析出/门拒 → 记 `error` 或 `soft_reject`，不得记成"无票"。
3. **只认当轮实时数据**。不满足筛选的班次全链路豁免（不进推送/比价/达标判定）。

### 1.2 技术骨架

- `main.py` —— 调度主循环
- `webui.py` —— **单文件内嵌 SPA**（约 4.3MB，含全部 HTML/CSS/JS），同时是本地 HTTP 服务
- `crawlers/` —— 10 个渠道采集器（5 浏览器 + 5 App）
- `core/` —— 节流/熔断、健康、存储、归一等内核
- `docs/` —— 61 份文档 + 门禁脚本 + 静态站

---

## 2. 开工第一件事：核验现场

**这一步不能跳。** 本文件的所有数字都会过期。

```bash
cd /d/idea_project/ticket-monitoring

# ① 版本与提交
grep -n '__version__ = ' main.py
git log --oneline -1

# ② 本地 vs 远程（最关键）
git fetch origin --tags
git rev-list --left-right --count origin/main...HEAD
# 输出 "A B"：A=远程独有, B=本地独有

# ③ 远程历史形态（决定发版策略）
git rev-list --count origin/main    # 项目约定：必须是 1（单根）
git rev-parse --short origin/main
git rev-parse --short origin/main~0 # tag 当前指向

# ④ 工作区
git status --short | wc -l

# ⑤ 并行会话是否活跃（决定能不能发版）
ls -la webui.py
find . -maxdepth 2 -newermt '-30 minutes' \( -name '*.py' -o -name '*.md' \) \
  | grep -v "_scratch\|node_modules\|\.git/"
```

### 2.1 并发判定规则（硬性）

| `webui.py` mtime | 结论 |
|---|---|
| **< 3 分钟** | 并发正在写 → **禁止发版、禁止烘站点** |
| 3–10 分钟 | 谨慎，先观察 90 秒确认哈希不变 |
| **> 10 分钟** | 可视为静默窗口 |

**实测证据**：本会话期间并行会话可在 **45 秒内连改 3 次** `webui.py`，并同时新增测试文件。拉锯没有意义——要么等静默，要么接受"发布的是未完成态"。

### 2.2 冻结验证（跑门禁前后都要做）

```bash
# 记录基线
python -c "
import pathlib,hashlib,json
snap={f: hashlib.sha256(pathlib.Path(f).read_bytes()).hexdigest()
      for f in ('webui.py','main.py','report.py')}
pathlib.Path('_scratch/_freeze_baseline.json').write_text(json.dumps(snap))
print({k:v[:12] for k,v in snap.items()})
"

# 跑完门禁后再查一次，任一变化 → 该轮结论作废
```

---

## 3. 当前真实差距（交接必读）

> **2026-11-03 更新**：本节数字写于 2026-10-31，已被 v1.5.307 发布轮关闭；
> 当前状态见 §0（发布树 `0d4b058` 同源、工作树 6108/20/0、`release_align_check --local` 25/25）。
> 以下保留为当时的差距记录，**不要当现状**。

### 3.1 三个数字不匹配

| 项 | 实际 | README/Release 写的 | 差距 |
|---|---|---|---|
| 版本 | `main.py` = 1.5.307 | Release 正文 = v1.5.306 | 落后 1 版 |
| pytest | `--collect-only` = **5467** | README = **5243** | 差 224 |
| UI 门禁 | `uitest_result.txt` = **667/668** | README = **668** | 差 1 且**未全绿** |

### 3.2 历史已分叉（发版前必须处理）

```
git rev-list --left-right --count origin/main...HEAD  →  1  31
```

**结构真相**（已核实）：

- 远程 `origin/main` 是**单根历史**：`git rev-list --count origin/main` = **1**，内容 v1.5.306。
- 本地是 **31 个提交**的开发历史。
- 远程那条 `5cff7f5` 与本地 `02766a3` **提交信息完全相同**（"调度首轮、POSIX 端口复用、空扫描后的 next_run 新鲜度"），但**内容不同**（远程是重写历史后的新单根，`git diff --stat` 显示 45 文件 / 3735 行差异）。

**这意味着**：不能用普通 push 或 rebase 解决。发版时必须**重建单根提交**再 `push --force`（见 §5）。

### 3.3 当前 5 项对齐红项

`PYTHONIOENCODING=utf-8 python docs/release_align_check.py --local` → **20/25**

| # | 红项 | 实际值 | 修法 |
|---|---|---|---|
| 1 | `CN pytest count current` | 实收 5467，README 写 5243 | 按实收更新 README |
| 2 | `EN pytest count current` | 同上 | 同上（README_EN） |
| 3 | `CN/EN screenshot sets in parity` | `cn-only=['docs/screenshots/console-dims.png']` | 见下 |
| 4 | `all referenced screenshots are tracked` | 同一张图**文件在磁盘但未入库** | `git add` |
| 5 | `site build stamp current` | 站点戳 `a9ebc254699d`，webui 已变 | 静默后重烘 |

> **③ 与 ④ 同根因**：`docs/screenshots/console-dims.png`（44963 字节，10-31 19:01）存在于工作区但未 `git add`。修一处消两项。

### 3.4 未跟踪的关键文件（24 项）

发布必需的：
- `docs/HANDOFF_GUIDE.md`（本文件）
- `docs/HANDOFF_CAPABILITY_MATRIX.md`
- `docs/UI_UNIFICATION_PLAYBOOK.md`
- `docs/RELEASE_BODY.md` ← **发版必需（canonical 正文源；`tests/test_release_body_source.py` 守门禁）**
- `docs/release-notes-v1.5.307.md` ← 历史变更记录（不再直接作为 Release 正文）
- `docs/screenshots/console-dims.png`

17 个新测试（r832–r902 系列）：`test_r832_trigger_not_flanked.py` … `test_r902_no_hardcoded_channel_count.py`

---

## 4. 文档门禁体系

**这是本项目最有价值的资产。** 它解决的核心问题是：*代码改了、文档仍写着相反的话，而没有任何测试会红。*

### 4.1 规模与运行

| 文件 | 内容 | 规模 |
|---|---|---|
| `tests/test_docs_code_contract.py` | 文档 ↔ 代码契约 | **93 项** |
| `tests/test_eol_consistency.py` | 换行符一致性 | **6 项** |

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_docs_code_contract.py tests/test_eol_consistency.py -q
# 实测：98 passed, 1 skipped
```

### 4.2 覆盖范围（93 项大致分类）

| 类别 | 举例 |
|---|---|
| 版本/结构 | 版本号与文档标题一致、HEAD 锚点、markdown 表格列数 |
| 设计令牌 | 圆角 `--r/--r2/--r3/--r10/--pill`、颜色令牌亮暗两套、幽灵令牌 |
| 代码符号 | 文档提到的 `foo()` 必须存在、`SRX.f.<key>` 必须存在、符号锚点可检索 |
| 配置 | 示例配置的键必须被代码读、文档提到的键必须在示例里、启动级 vs 热加载分类 |
| 数据形态 | 途牛「行数 == 不同 fetched_at 数」、`extra` 元素必含 `transCity` 不含 `transfer` |
| 状态枚举 | `CHANNEL_SESSION` 11 个状态、8 后端 + 3 前端派生的划分 |
| 量化数字 | 字号/间距/阴影合规率（带统计口径 + 容差）、分隔线条数 |
| 历史时效 | 37 份 release-notes 必须有「时效边界」声明、SPEC 运行记录必须带日期 |
| 多文档一致性 | 5 份移动端文档结论互校、APK 样本 ABI 逐字节 |
| 读者-facing | `SECURITY.md` 监听声明、`.impeccable.md` 色值、README 示例可解析 |
| 元门禁 | 门禁清单 ↔ 实际函数双向一致、门禁不得在缺失锚点时 skip |

### 4.3 写新门禁的三步铁律

```
① 写门禁  →  ② 做负控  →  ③ 登记 SPEC §8.4
```

**缺一不可**：
- 不做负控 → 门禁可能是恒真的摆设。
- 不登记清单 → 元门禁 `test_spec_gate_index_matches_actual_tests` 会立刻红（有意设计）。

### 4.4 负控标准动作

```bash
# 1. 注入错误
# 2. 跑门禁，确认 rc=1（只接受 FAILED，skipped 一律视为无效负控）
# 3. 按字节还原（不要用文本模式）
# 4. 再跑，确认恢复绿
```

```python
import hashlib, os, pathlib, subprocess, sys
p = pathlib.Path("docs/XXX.md")
orig = p.read_bytes(); d = hashlib.md5(orig).hexdigest()
tmp = p.with_name(p.name + ".mut")
tmp.write_bytes(orig.replace(b"OLD", b"NEW")); os.replace(tmp, p)
try:
    r = subprocess.run([sys.executable,"-m","pytest","-q","-p","no:langsmith_plugin",
                        "tests/test_docs_code_contract.py::test_xxx"], capture_output=True)
    print("RED" if r.returncode == 1 else "NO-FIRE")
finally:
    tmp2 = p.with_name(p.name + ".bak"); tmp2.write_bytes(orig); os.replace(tmp2, p)
assert hashlib.md5(p.read_bytes()).hexdigest() == d, "还原失败！"
```

### 4.5 负控出现 NO-FIRE 时的 5 类排查（我在这上面浪费了大量时间）

| # | 症状 | 原因 | 正确做法 |
|---|---|---|---|
| 1 | 改了没变红 | 同一字符串**出现多次**，只改 1 处 | **全量替换**（不带 count） |
| 2 | 改了没变红 | **大小写不匹配**（代码是 `BarkNotifier`，我替换 `bark`） | `re.sub(..., flags=re.I)` |
| 3 | 改了没变红 | 门禁 `limit 1` 取了**另一行** | 先查出「门禁实际读哪一行」，对那一行注入 |
| 4 | 改了没变红 | 门禁查**表格行**，我改散文；或反之 | 先读门禁代码，确认它限定以竖线开头 |
| 5 | 改了没变红 | **改错了文件**（门禁扫 A，我改 B） | 先确认门禁扫哪些文件 |

### 4.6 门禁自身的四类空转缺陷（写新门禁必遇）

1. **「找不到要检查的东西」被当绿灯** —— 循环没命中任何对象时 `offenders` 恒空。
   **修法**：`assert examined`（至少命中 N 个），不能只 `assert not offenders`。

2. **已入库文件缺失时 skip** —— 对**已入库**文档是假绿（删了文档反而全绿）。
   **修法**：已入库 → `assert p.exists()`；未入库（gitignore 的 HANDOFF、日志）才允许 skip。
   已有元门禁 `test_tracked_targets_referenced_by_gates_exist` 兜住。

3. **元门禁字符集漏字符** —— 旧正则 `test_[a-z0-9_]+` **不匹配中文函数名**，导致该门禁在「清单」与「实际」两侧**同时缺席** → 差集为空 → 永远绿。
   **修法**：`test_[\w\u4e00-\u9fff]+`，并用 `not endswith(".py") and "::" not in x` 排除路径与符号锚点。

4. **判据钉死了已消失的组件** —— 曾硬要求「路径行仍用原口径」这句必须存在，而界面上**已无独立路径行**。
   **修法**：判据跟着代码结构走（检查 `class="hpath"` 在不在），并要求文档**正向声明**旧组件已不存在。

---

## 5. 发版流程

权威文档：**`docs/RELEASE_PROCESS.md`**。以下是适合本机环境的浓缩版。

### 5.1 铁律

| 规则 | 内容 |
|---|---|
| **一个 Release** | 名字**永远不变**：`机票监控台 · 初版（滚动更新）` |
| **一个 tag** | 恒为 `v1.0`，每次发版**移动**到新 SHA |
| **版本位置** | 只写在 **Release 正文**，**不写进 Release 名** |
| **一套资产** | 4 个平台 zip + `SHA256SUMS.txt`，共 5 个 |
| **公开历史** | **单一初始化提交**（`git rev-list --count origin/main` 必须 = 1） |
| **禁止** | 不得从移动中的工作树构建 |

### 5.2 完整执行序列

#### Step 1 · 备份（历史重写前**必须**）

```bash
BK="/d/ticket-monitoring-backup-$(date +%Y%m%d-%H%M%S)"; mkdir -p "$BK"
cd /d/idea_project/ticket-monitoring

# 全部历史 + 所有分支
git bundle create "$BK/repo-all.bundle" --all
git bundle verify "$BK/repo-all.bundle"        # 必须显示 "is okay"

# 已跟踪的未提交改动
git diff --binary HEAD > "$BK/worktree-tracked.patch"

# 未跟踪文件
tar -czf "$BK/untracked.tar.gz" $(git status --short | grep "^??" | sed 's/^?? //')
```

**必须验证可恢复**（我实测过）：

```bash
TMP="/d/tm-restore-test-$$"
git worktree add --detach "$TMP" HEAD
cd "$TMP" && git apply --binary "$BK/worktree-tracked.patch"
# 用 LF 归一后比对，逐字节一致才算通过
python -c "
import pathlib
for f in ('webui.py','main.py','README.md'):
    a=(pathlib.Path('$TMP')/f).read_bytes().replace(b'\r\n',b'\n')
    b=(pathlib.Path('/d/idea_project/ticket-monitoring')/f).read_bytes().replace(b'\r\n',b'\n')
    print(f, '一致' if a==b else '不一致')
"
git worktree remove --force "$TMP"
```

> **为什么要 LF 归一**：仓库有内容过滤器（`.gitattributes`），恢复出的文件可能是 CRLF 而工作区是 LF，直接 md5 会误判为不一致。

#### Step 2 · 确认冻结

`webui.py` mtime ≥ 3 分钟，且按 §2.2 记下基线哈希。

#### Step 3 · 跑门禁

```bash
# ① 文档契约（11 秒，必跑）
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_docs_code_contract.py tests/test_eol_consistency.py -q

# ② UI 自检（约 2 分钟，独占，不与 pytest 并行）
PYTHONIOENCODING=utf-8 python docs/uitest.py

# ③ 全量（15–20 分钟，串行独占）
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/ -q

# ④ 对齐（1 分钟）
PYTHONIOENCODING=utf-8 python docs/release_align_check.py --local
# 必须 25/25
```

> **pytest 与 uitest 不得并行**：二者各自拉起 demo 服务与 Playwright，并行会产生假失败（实测 6 条）。

#### Step 4 · 收敛为单根提交

```bash
git add -A          # 注意：先确认无敏感文件（见 §5.6）
git commit -F- <<'EOF'
ticket-monitoring 初版 · 持续更新

> 自托管的多渠道机票价格监控：航班明细采集 → 钉钉图文推送 → 达标四层强提醒。
> 国内航线与国际航线（五洲目的地）同一套采集-判定-推送链路。
> 数据留在本机，配置全在网页，开源免费。

当前版本 v1.5.307（初版首发 2026-10-23，滚动更新）。
<一两句本版主线>

详见 docs/release-notes-v1.5.XXX.md。
EOF
```

- 提交信息**用产品身份开场**，版本作为**从属行**。
- 若需真正单根（远程是 1 个提交），发版前用 `git checkout --orphan` 重建，或接受"本地多提交 + 强推"（会暴露开发历史，**违反 RELEASE_PROCESS**）。

#### Step 5 · 推送 main

```bash
git push origin main                        # 若本地已含远程历史
# 或（远程是不同单根，必须重建）
git push origin main --force
```

#### Step 6 · 移动 v1.0 tag

```bash
git tag -f v1.0 <new-sha>
git push origin v1.0 --force
```

#### Step 7 · 构建资产

```bash
CRED=$(python -c "
import re,pathlib,urllib.parse
t=pathlib.Path.home().joinpath('.git-credentials').read_text()
m=re.search(r'https://([^:]+):([^@]+)@github\.com', t)
print(m.group(1)+':'+urllib.parse.unquote(m.group(2)) if m else '')
")

# 触发（workflow_dispatch，不是 tag 触发）
curl -s -X POST -u "$CRED" -H "Accept: application/vnd.github+json" \
  -H "Content-Type: application/json" -d '{"ref":"main"}' \
  "https://api.github.com/repos/dengmeiluan/ticket-monitoring/actions/workflows/release-build.yml/dispatches" \
  -o /dev/null -w "HTTP=%{http_code}\n"    # 期望 204

# 确认 head_sha 等于刚推的 SHA（这一步不能省）
curl -s -u "$CRED" \
  "https://api.github.com/repos/dengmeiluan/ticket-monitoring/actions/workflows/release-build.yml/runs?per_page=2"
```

#### Step 8 · 下载与解包

```bash
# 按 artifact id 下载
curl -sL -u "$CRED" -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/dengmeiluan/ticket-monitoring/actions/artifacts/<ID>/zip" \
  -o pkg.zip

# ⚠ artifact 是双层 zip，必须解一层取出真正的发行包
python -c "
import zipfile,pathlib
with zipfile.ZipFile('pkg.zip') as z:
    for n in z.namelist():
        if n.endswith('.zip'): pathlib.Path(n).write_bytes(z.read(n))
"
```

#### Step 9 · 上传资产

```bash
RID=<release-id>

# ⚠ 必须用 uploads.github.com，用 api.github.com 会 404
curl -X POST -u "$CRED" -H "Content-Type: application/zip" \
  --data-binary "@ticket-monitoring-win64.zip" \
  "https://uploads.github.com/repos/dengmeiluan/ticket-monitoring/releases/$RID/assets?name=ticket-monitoring-win64.zip"
# 期望 HTTP 201
```

`SHA256SUMS.txt` 格式（**两个空格**，不是 `*`）：

```
<hash>  ticket-monitoring-win64.zip
<hash>  ticket-monitoring-linux-x64.zip
<hash>  ticket-monitoring-macos-arm64.zip
<hash>  ticket-monitoring-macos-x64.zip
```

#### Step 10 · 更新 Release 正文

```bash
curl -s -X PATCH -u "$CRED" \
  -H "Accept: application/vnd.github+json" -H "Content-Type: application/json" \
  --data-binary @payload.json \
  "https://api.github.com/repos/dengmeiluan/ticket-monitoring/releases/$RID" \
  -o resp.json -w "HTTP=%{http_code}\n"    # 期望 200
```

正文结构（顺序固定）：
1. 规范产品介绍（三行引用块，**不得改写**）
2. `**当前版本：v1.5.XXX · YYYY-MM-DD**（初版首发 2026-10-23）`
3. `源码提交 \`<short-sha>\` · 跟踪测试 N 项 · UI 门禁 N/N 通过`
4. 本版正文（canonical 源 `docs/RELEASE_BODY.md`，替换 `{{VERSION}}`/`{{SOURCE_SHA}}`/`{{DATE}}`/`{{TEST_COUNTS}}`/`{{UI_COUNT}}`/`{{ASSET_TABLE}}`/`{{RELEASE_NOTES}}` 占位符；`tests/test_release_body_source.py` 守 10 渠道/范围/多程/占位符，`docs/release-notes-v1.5.307.md` 只是历史稿件，不再直接作为正文）
5. **不得含内部轮次术语**（`r123` 之类）

### 5.3 发布后必验

```bash
# ① 三处 SHA 一致
git rev-parse --short HEAD
git ls-remote origin refs/heads/main | cut -c1-7
git ls-remote origin refs/tags/v1.0 | cut -c1-7

# ② 包内版本必须等于发布版本（实测，不能只看文件名）
cd _scratch/_wintest && ./TicketMonitor.exe --version     # 应输出 1.5.307

# ③ 包根结构
python -c "
import zipfile
z=zipfile.ZipFile('ticket-monitoring-win64.zip')
roots={n.split('/')[0] for n in z.namelist()}
print('根:', sorted(roots))     # 应为 ['TicketMonitor.exe', '_internal']
bad=[n for n in z.namelist() if any(k in n.lower() for k in
     ('config.yaml','prices.db','ghtoken','user_data/','session-state','logs/'))]
print('禁用项:', bad or '无')
"

# ④ 校验和
cd dist_package && sha256sum -c SHA256SUMS.txt

# ⑤ 对齐（在线模式会额外查 Release/资产）
PYTHONIOENCODING=utf-8 python docs/release_align_check.py
```

### 5.4 三个必踩的坑（我已实测）

| 坑 | 现象 | 正解 |
|---|---|---|
| 上传域名 | `api.github.com` 上传资产返回 **404** | 用 **`uploads.github.com`** |
| 双层 zip | 直接把外层 artifact 当发行包上传 | 内层还有一层，**必须解包** |
| SHA 格式 | `sha256sum` 默认带 `*` 前缀 | 手工写成 `<hash>  <name>`（两空格） |

### 5.5 站点构建戳的双向写冲突

`release_align_check` 的 `site build stamp current` 比对：
- 站点里记录的 `code:<sha12>`
- 当前 `webui.py` 的内容 sha256 前 12 位

**只要 `webui.py` 还在被写，这个值永远追不上。** 我实测过连试 3 次（stash 隔离 / 快照即烘 / 提交即验）全部在窗口内被打破。

**正确做法**：确认静默 → 一次烘好 → 立刻 `git add docs/site/index.html` → 提交 → 立刻验证。

### 5.6 发版前必须确认的敏感文件

```bash
# 这些必须被 gitignore 挡住
for f in config.yaml session-state.json user_data/ data/prices.db logs/; do
  printf "%-22s " "$f"; git check-ignore -q "$f" && echo "ignored ✓" || echo "NOT ignored ✗"
done

# 暂存后复查
git diff --cached --name-only | grep -E "session-state|^config\.yaml|user_data/|\.env$|credential"
# 必须为空
```

### 5.7 并发写文件时的正确姿势

```bash
# 禁止：git add webui.py（会吞掉并行会话的未提交改动，实测丢 1147 行）
# 禁止：git checkout/restore webui.py（抹掉整份改动，不可恢复，实测丢 86 行）
# 禁止：裸 git stash / stash pop（共享工作树互相吞）

# 正确：具名 stash
git stash push -u -m "rXXX-in-flight-parallel-session" -- webui.py
```

---

## 6. 文档漂移的六类模式

### 6.1 数字类断言

**必须写明统计口径。**

反例：SPEC §3 写「825 条 / 93.7%」，但没说统计范围。换口径得到 **826/93.7%**（只取第一个 `<style>` 块）与 **93.9%**（全部三块）——**两组都真实**，不写范围就无从复现。

**优先选稳定的形态，而非会漂的绝对值。**

反例：途牛国际写「286/277/251/205 行」，第二天变 285/274/249/204。
正解：`count(*) == count(distinct fetched_at)` 四条航线**精确相等** → 「每轮只落 1 行」才是稳定判据。

**数字带容差比较**：并行会话持续微调样式，精确相等会变成噪声。

### 6.2 组件会消失

文档描述的东西可能已经不存在。

实例：SPEC 写「控制台路径行（近 24h 路径）用原口径 `query_rate`」→ 界面**已无独立路径行**，分通路并进健康卡 `.hpath`（读 `paths[p].paths[k].rate`）。
更糟的是**门禁曾钉死这个已消失的组件**（硬要求「路径行仍用原口径」必须存在）。

**修法**：判据跟着代码结构走，并要求文档**正向声明**旧组件已不存在。

### 6.3 同一概念散落多处

改一处必须**全文 grep 同一概念**。我曾改完表格第 3 行，30 行后仍写着旧说法，而全量门禁还是绿的（断言只认旧句）。

门禁范围要覆盖**所有**提到该概念的文档（README×2 / INTL_DESIGN / PLAYBOOK / HANDOFF 都要扫）。

### 6.4 历史文档

38 份 `release-notes-v*.md` 里 **37 份没有时效声明**，正文却写满测试计数与渠道状态。

正确处理**不是逐份核内容**，而是：
- 加一行「**时效边界**」头注（当次快照 ≠ 现状）
- 当前版本那份豁免（门禁读 `main.py::__version__` 决定豁免谁）
- 批量加注脚**按每份自身 EOL 写**（这批 13 份 LF / 25 份 CRLF 并存）

### 6.5 安全与读者-facing 文档

`SECURITY.md` 曾自相矛盾：
- 开头：「控制台**只监听** `127.0.0.1`，不暴露公网」
- 末尾：「请不要手动改绑 0.0.0.0」
- 而 `config.example.yaml` 的 `web.host` **本来就支持 `0.0.0.0`**

正确写法：**默认**回环 + 可改绑 + 改绑后无鉴权=对局域网开放。

`.impeccable.md` 写「蓝主色 `#1a73e8` 族」→ 该色值在 `webui.py` **0 命中**，真实是 `--blue:#0b62d6`（亮）/`#63a4f8`（暗）。

### 6.6 示例必须能跑

- README 举的航司示例 `MU`/`东方航空`/`东航`/`!9C,!春秋` 必须都能被 `core.airlines.alias_payload()` 解析。
- README 声称的通知通道（钉钉/Server酱/ntfy/Bark/阿里云/邮件）必须在 `core/notifier.py` 有实现。
- 文档教的命令要**实跑一遍**：曾写一个**从未创建过**的回归用例文件名，读者照抄会 `file or directory not found`，连其余真实用例也跑不成。

---

## 7. 操作纪律

### 7.1 四条绝对禁止

| 禁止 | 后果（实测） |
|---|---|
| `git add webui.py` 整份暂存 | 吞掉并行会话未提交改动，**丢过 1147 行** |
| 对 `webui.py` 用 `git checkout`/`restore` | 抹掉整份改动**且不可恢复**，丢过 86 行 |
| 裸 `git stash` / `stash pop` | 共享工作树互相吞；必须**具名** stash |
| 在 `webui.py` 移动时发版/烘站点 | 从半成品构建，站点戳永远追不上 |

### 7.2 编辑陷阱（每条都踩过）

| 陷阱 | 症状 | 正解 |
|---|---|---|
| **Edit 插入新函数用函数定义行作 old_string** | 把目标函数连同 docstring 首行吃掉，函数体并进上一个函数。**语法仍合法、测试只少一个，极隐蔽** | old_string 用**上一函数最后一行 + 空行**作锚 |
| **文本模式写文件** | 整份 EOL 翻转（2737 行 LF → CRLF） | `read_bytes()`/`write_bytes()`；追加按原形态 |
| **heredoc 折叠转义** | `\n`、`\x00`、`\b` 被 bash 吃掉，甚至吃掉一层正则反斜杠 → `re.error` | 含转义一律用 Write 工具落盘 |
| **Markdown 表格内换行** | 用 `\n` 会物理截断表格行 | 只能用 `<br>` |
| **表格单元格含竖线** | 单元格里出现字面竖线时，门禁会把该行判成多一列 | 改成纯文字描述，不要出现字面竖线 |

### 7.3 EOL 纪律

- **`.gitattributes` 规定仓库文本用 `eol=lf`**（`i/lf w/lf`）。README、docs 都是 LF。
- `core.autocrlf=true` 下「索引 lf / 工作区 crlf」是**本机检出常态**，不是缺陷。
- 追加内容后立刻核：「CRLF 与 LF 只有一个非零」。

---

## 8. 下一步建议

### P0 · 先收敛状态（不然后面都是浮沙）

1. **等 `webui.py` 静默**（mtime ≥3 分钟）。
2. **补齐 5 项对齐红项**：
   - README/README_EN 的 pytest 计数 → 按 `--collect-only` 实收（当前 **5467**）
   - `git add docs/screenshots/console-dims.png`（同时消掉两项红）
   - `uitest` 当前 **667/668** → **先查清哪个断言失败**，别急着改 README 的 668
   - 站点戳 → 静默后 `python docs/demo_build.py`
3. **决定历史策略**：远程是单根（1 提交），本地 31 提交。要么重建单根，要么明确接受暴露开发历史（**违反 RELEASE_PROCESS**）。

### P1 · 把 v1.5.307 发出去

按 §5 全流程。**注意**：`dist_package/` 里的包是 10-29 的 v1.5.304 产物，**必须重新构建**。

### P2 · 继续文档维护

还没做的方向：
- `docs/ACCEPTANCE_MATRIX.md` 验收记录的时效标注
- `docs/superpowers/specs/` 设计稿与实现的落地对照
- `docs/UI_UNIFICATION_PLAYBOOK.md`（并行会话正在改，等稳定）
- `docs/HANDOFF_CAPABILITY_MATRIX.md`（新文档，未纳入门禁）

---

## 9. 关键文件速查

| 用途 | 路径 |
|---|---|
| **执行规范（唯一执行口径）** | `docs/EXECUTION_SPEC_LATEST.md` |
| **发版流程（权威）** | `docs/RELEASE_PROCESS.md` |
| 发布对齐检查（25 项） | `docs/release_align_check.py` |
| UI 自检门禁 | `docs/uitest.py` |
| 并发全量门禁入口 | `tools/test_all.py` |
| 文档契约门禁（93 项） | `tests/test_docs_code_contract.py` |
| EOL 门禁（6 项） | `tests/test_eol_consistency.py` |
| 静态站构建 | `docs/demo_build.py` |
| 部署裁剪 | `docs/prune_deployments.py` |
| 交接文档（**gitignore，不入库**） | `HANDOFF.md` |
| 限流/熔断运维手册 | `docs/RATE_LIMIT_PLAYBOOK.md` |
| 国际通路设计 | `docs/INTL_DESIGN.md` |
| 挑战识别与处置接缝 | `crawlers/challenge.py` |
| App 渠道手册 | `docs/APP_CHANNELS.md` |
| 发版构建 CI | `.github/workflows/release-build.yml` |

**备份**（10-29 那次）：`D:\ticket-monitoring-backup-20261029-174144\`
- `repo-all.bundle`（261MB，全部历史，已 verify）
- `worktree-tracked.patch`（5.2MB）
- `untracked.tar.gz`（24MB）
- `temp-artifacts/`（曾误入工作区的临时补丁）

---

## 10. 验证清单

### 每次改文档/代码后

```bash
# ① 文档契约（11 秒，必跑）
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_docs_code_contract.py tests/test_eol_consistency.py -q

# ② 发布对齐（1 分钟）
PYTHONIOENCODING=utf-8 python docs/release_align_check.py --local
```

### 发版前（四道全过）

```bash
# ③ UI 自检（2 分钟，独占）
PYTHONIOENCODING=utf-8 python docs/uitest.py

# ④ 全量（15–20 分钟，串行独占）
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/ -q
```

### 判定纪律

| 情形 | 结论 |
|---|---|
| 门禁红 | 先分清「**值变了**」（并发改代码 → 更新断言）还是「**设计坏了**」（改代码） |
| 失败项单跑通过 + 源码 mtime 晚于测试启动 | **并发假失败**，该轮作废重跑 |
| 负控 NO-FIRE | 门禁写法有问题，先修门禁（查 §4.5 五类） |
| 没有负控的门禁 | **等于没有门禁** |

---

## 11. 附录：本会话完整教训清单

### A. 文档门禁类（1–38）

1. 圆角「两档 12/9」→ 实际五档 `--r:14/--r2:11/--r3:9/--r10:10/--pill:999`
2. `PCHART.mount/draw/hover/destroy` 从未实现，真实是 `frame/axes/line/area/gaps/pick/placeTip`
3. 画布宽「锁成容器宽」正是 r373 被否决的做法，实际 `max(可视宽, min(点数×间距, 2.4×))`
4. 触屏热区「≥44px」→ 门禁钉 **36px**
5. 间距/阴影写成绝对禁止 → 实测合规率仅 43.7%
6. 颜色令牌整段错 → **两套并存**（主 `:root` 与 `<style id="r364-flat">`），**两套都是真值**
7. 熔断退避表写初稿状态，实际 `soft/ip/captcha/login` + 空串；**缺 `soft` 最危险**（软拒被当 IP 限流）
8. 「查询成功率已按在用口径」需分清徽标 vs 路径行，一刀切就是假陈述
9. `SRX_FIELD_SPECS` 定义 18 字段，列表只展示 13 个
10. HANDOFF 教人直跑 `python tests/test_core_units.py`，而该文件自己写着「一律走 pytest」——**同一文档自相矛盾**
11. HANDOFF 架构速览漏 4 个核心模块
12. PLAYBOOK 点名 `_fc_key` → 全仓不存在（真实 `flight_key`）
13. `crawler.tls_impersonate` 是「隐形开关」：4 个 crawler 在读、文档教人用，但示例配置里没有
14. 「日历 444 已达成 0 次」错：按日期查还有 24 次
15. 结论性文档缺时效边界：`INTL_CALIBRATION.md` 原是无标题裸台账
16. v295 batch1 52 个 / batch2 32 个 `- [ ]` 从未勾选但产物全在 → **checkbox 未勾 ≠ 未完成**
17. `CHANNEL_SESSION.md` 漏 3 个前端派生状态（`read_error`/`loading`/`demo`）
18. 方案文档写了不存在的 `/api/challenge/tickets`（该文档已删除，教训保留）
19. 守卫范围被写过头（PLAYBOOK 说「代码里不得出现 X」，实际只覆盖 1100 字符窗口）
20. 设计稿接口提案整组改名（5 个端点全不存在）
21. 设计稿表结构提案未落地（`special_deals` 无 `user`/`channel` 列）
22. 「本轮」措辞冒充现状
23. 历史 pytest 计数未标注
24. HEAD 锚点长期滞后
25. 文档互相引用会失联
26. 门禁清单本身会腐化 → 需元门禁双向比对
27. 移动端文档体积/状态数字腐化（448MB→768MB、3.6GB→7.1GB）
28. 登录要求有两层（`SESSION_REQUIREMENT` vs `PAGE_LOGIN`），不能混
29. 产品口径变更整段推翻文档（五渠道全 required）
30. **反向结论也要报**：核实准确的部分要说明，只列问题会让人以为整份文档都在腐化
31. 界面文案 ≠ 文档文案（「关注航线走势」vs「航线走势」）
32. 分区名张冠李戴（README 写四分 区，实际 `#cfgnav` 三项）
33. 判定条款比实现超前（D11/D12/D14 均未实现）
34. 「当时」冒充「当前」（设计稿「3/5 渠道」）
35. 同一事实三种口径（13% / 76% / 100%）并存
36. 罚速表口径错（读原口径而非在用口径）
37. 已修的 P0 仍写成待修
38. 裸行号做证据必然失配 → 改用符号锚点，且符号必须真实存在

### B. 门禁工程类（39–60）

39. 门禁跳过（skip）会造成静默失效 → 锚点缺失必须 assert
40. 静默 `continue` 漏检 → 用变异测试验证
41. 正则 `[a-z0-9_]+` 不匹配中文函数名 → 两侧同时缺席 = 永远绿
42. 「找不到检查对象」被当绿灯 → 必须 `assert examined`
43. 已入库文件缺失时 skip = 假绿
44. 判据钉死已消失的组件
45. 门禁只扫 `docs/` 漏掉根目录 README/HANDOFF
46. 门禁只查一份文档，同一概念在别的文档仍错
47. 静态白名单会放行任何未登记名字
48. 「±3 行窗口」太宽 → 改同行或紧邻上一行
49. 表格类判据不能写死列数（会误报 98 行）
50. 变异脚本 `try/finally` 覆盖不全 → 污染 24 文档 106 处
51. 负控 NO-FIRE 五类：漏出现处 / 大小写 / 读错行 / 散文vs表格 / 打错文件
52. 反向擦除别把原生 URL 一起改（`mumu.nie.netease.com/endpoint/`）
53. 负控前先 `git grep HEAD` 证明新串在基线不存在
54. 还原要逐文件校验 md5
55. 用例结束后独立扫一遍变异串
56. 元素/组件选择器别写裸 tag（会同时命中多个组件）
57. 日期类门禁别扫所有日期（车票日期会污染）
58. 「N passed」类运行记录必须带时间锚；「0 failed」是验收标准要豁免
59. 元门禁的字符集过滤别写「含点就排除」（`webui.py::_startup_vals` 会被误杀）
60. Edit 插入新函数用函数定义行作 old_string 会吞掉目标函数（**踩了 3 次**）

### C. 发版工程类（61–80）

61. 上传资产必须用 `uploads.github.com`（`api.github.com` 返回 404）
62. artifact 是双层 zip，必须解一层
63. `SHA256SUMS.txt` 用两个空格，不是 `*`
64. 站点戳是双向写冲突，并行改写时永远追不上
65. 不得从移动中的工作树构建
66. 历史重写前必须备份并**验证可恢复**
67. 恢复比对要 LF 归一（内容过滤器会让 md5 误判）
68. `.next` 分片中间产物会被误提交 → 加 gitignore
69. `uitest_result.txt` CRLF/LF 混排会让校验器 `UnicodeDecodeError`
70. `pytest` 与 `uitest` 不得并行（实测 6 条假失败）
71. 中断 pytest 会留下大量孤儿 `webui.py --demo --port XXX` 进程（实测 60 个）
72. 清理孤儿进程要先按命令行分类，别误杀并行会话的
73. 三个测试计数口径：不带路径 / `tests/` / git 跟踪，必须注明
74. README 计数按 `release_align_check` 口径写（只统计已跟踪文件）
75. Release 名恒定，版本只进正文
76. tag `v1.0` 恒移动，不新建 tag
77. 一个 Release、一套资产、一个部署
78. 包内可执行 `--version` 必须实测等于发布版本
79. 包内不得含 config/data/logs/user_data/session-state/ghtoken
80. 远程单根 vs 本地多提交 → 必须重建单根再强推

---

## 12. 一句话提醒

**这个项目最大的风险不是功能坏了，而是文档说的和代码做的不一致，且没人发现。**

`tests/test_docs_code_contract.py` 那 93 项门禁就是为此存在的。

新增保护时记住三步：**写门禁 → 做负控 → 登记 SPEC §8.4**。缺一不可。
