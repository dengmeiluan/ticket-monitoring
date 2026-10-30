# v1.5.295 证据优先四线设计（2026-10-24）

> **已落地（2026-10-27 复核）**：本文是 2026-10-24 的设计快照；其中的 P0（`build_users` 未保留 `special_radar`）**已修复**——当前 `main.py` `build_users` 三个入口（默认键、判空、字段赋值）都带 `special_radar`，生产雷达自动循环可正常取到用户条件。引用本文的缺陷清单时，以当前代码为准。

## 0. 基线与结论

- 基线：v1.5.294，单一初始化提交 `830ef698b783047b5ff42e9f3d8af63d2cf47c1a`；live 8765 同版本。
- 8 路只读审计确认一个 **P0**：`main.py` 的 `build_users` 未保留 `special_radar`，生产 `_radar_auto_loop` 取不到用户条件，自动监控实际未运行；现有快照来自手动查询。
- 其余 P1：历史按用户聚合导致跨航线/日期串线；健康诊断无证据也显示绿色；扫描行无入口证据且 RAW 是解析 extra；移动折叠/五源/特价日历存在遮挡；4× CPU 筛选 P95 337.9ms；公开面仍有过期计数与跳过 live 的对齐检查。

本设计只做“证据优先”的增量，不重写控制台、不新增调度器、不绕过验证码/风控、不补造历史。

## 1. 目标与非目标

### 目标

1. 特价监控真正持续运行，能按用户条件积累历史并在“新低/阈值”时可靠提醒。
2. 渠道诊断从字符串猜测升级为证据分型，明确登录、Cookie 过期、验证码、IP/频率风控、超时、部分成功、未扫描。
3. 所有价格尽量可追溯到采集入口与轮次；无法取得原始响应时明确标“路径级/解析 extra”，不冒充 RAW。
4. 关注航线/关注航班共用一套视觉与交互语法；移动端无遮挡；新增一个克制的签派轨签名。
5. 性能目标可复现：4× CPU、50 行筛选 P95 ≤300ms；200% 等效视口、24 行 P95 ≤200ms；真实浏览器缩放的不可测部分如实标注。
6. 公开面、验收矩阵、站点构建戳与 Release 对齐检查可复现。

### 非目标

- 不新增独立监控守护进程；沿用 `_radar_auto_loop`。
- 不把日历价当航班明细；不为缺失历史补值。
- 不做验证码/滑块/风控绕过；不自建代理池规避 IP 限制。
- 不重写五个 crawler 的解析器；证据链先做到“路径级 + 解析 extra”并明确标注。
- 未经单独确认不推送、不改 tag、不发布。

## 2. 监控闭环

### 2.1 配置与运行

- `main.py build_users` 保留 `users[].special_radar`（含 `enabled/from/to/nationwide/start/end/channels/alert`）。
- `start_web` 接收 `alerters`（用户 → Alerter）并挂到 `_State`；雷达提醒只走该用户的通知配置。
- `_radar_auto_loop`：启动后 90 秒首轮，之后每 2 小时；扫描持锁跳过；按用户顺序执行，默认上限 3 个用户，可用 `webui.radar_auto_max_users` 调整并写入日志；单用户失败不阻断后续。
- 自动轮询只处理 `enabled` 且有完整 `from/start/end` 的配置。

### 2.2 查询域与快照

`radar_snapshots` 迁移（SQLite `ALTER TABLE`，幂等）：

- `query_key TEXT NOT NULL DEFAULT ''`
- 索引 `(user, query_key, fetched_at)`。

新表 `radar_runs`（每次运行都记，不污染价格历史）：

```sql
id INTEGER PRIMARY KEY AUTOINCREMENT,
user TEXT, query_key TEXT,
status TEXT, note TEXT, rows INTEGER,
started_at TEXT, finished_at TEXT
```

`query_key` = `from|to|nationwide|start|end|sorted(channels)`。旧快照行回填为 `legacy|<from>|<to>|<nationwide>|<start>|<end>`，不回填渠道、不伪造当前条件。

- 只有 `status=ok` 且 `dates` 非空的结果写 `radar_snapshots`。
- 每次运行（含 `cache_hit/fallback/partial/empty/error`）只写 `radar_runs`；非 ok 不更新价格历史、不更新提醒基线。
- `radar_history` 同时返回 `last_run`（状态/时间/原因），UI 在监控卡头显示“最近运行失败/缓存”，但日期价仍来自最后一次 ok 快照。
- `radar_history(user, days, query_key=None)`：
  - 传 `query_key` 时只取该域；
  - 不传时取该用户最近一次 `ok` 快照的 `query_key`，再只返回该域；
  - `query`、`dates`、`lowest`、`series`、`snapshots` 全部来自同一域。
- API `/api/radar/history` 增加 `query_key` 可选参数；前端用当前用户配置生成同一 key。

### 2.3 提醒状态与规则

新表 `radar_alert_state`：

```sql
user TEXT, query_key TEXT, depart_date TEXT,
low_price REAL, low_at TEXT, low_channel TEXT, low_basis TEXT,
last_alert_price REAL, last_alert_at TEXT,
armed INTEGER NOT NULL DEFAULT 1,
PRIMARY KEY(user, query_key, depart_date)
```

新表 `radar_alerts`（证据/历史）：

```sql
id INTEGER PRIMARY KEY AUTOINCREMENT,
user TEXT, query_key TEXT, depart_date TEXT,
price REAL, prev_low REAL, channel TEXT, basis TEXT,
kind TEXT, link TEXT, flights_json TEXT,
status TEXT, err TEXT, sent_at TEXT
```

配置 UI 放在特价监控卡的可折叠条件区（不跳配置页）：

- `enabled`（默认 false；主动推送需显式开启）
- `drop_min`（默认 50；只有新低比历史低至少该值才提醒）
- `threshold`（0=关闭；低于阈值且未武装时提醒）
- `cooldown_h`（默认 12）

规则：

1. 首轮某日期只播种 `low_price`，不发送。
2. 新低且 `prev_low - price >= drop_min` 且冷却已过 → `new_low` 提醒。
3. `threshold>0` 且 `price <= threshold` 且 `armed=1` → `threshold` 提醒，`armed=0`；价格回到 `threshold*1.05` 以上或日期变化后重新 `armed=1`。
4. 只比较同一 `basis`（含税/裸价/未知三者严格相等）；渠道切换导致口径变化时只更新来源，不触发降价提醒。
5. 最近运行 `status!=ok`（`cache_hit/fallback/partial/empty/error`）、演示模式、过去日期、无用户通知配置 → 不发送。
6. 并发：`BEGIN IMMEDIATE` + 主键唯一；同一快照只评估一次。
7. 发送内容：用户、航线、低价日、价格/口径、渠道、较上次低多少、该日真实明细（最多 3 条）或“尚无真实明细”；链接为渠道官方页。发送结果写 `radar_alerts`，失败记录 `err`，不重试超过 1 次。

### 2.4 UI

- 监控卡头显示 `提醒：开/关 · 上次提醒 YYYY-MM-DD HH:mm`；低价日卡显示 `新低/阈值` 徽标。
- 条件区增加提醒开关、降幅、阈值、冷却输入；保存走 `POST /api/radar/alert-config`（同源 JSON、长度限制），读取走 `GET /api/radar/alert-config?user=`。
- 低日明细为空时仍明确“日历价不能生成航班”，不伪造成交。
- 演示模式/静态站：显示“DEMO · 合成监控”，提醒不发送。

## 3. 渠道诊断

### 3.1 单一分类源

新增 `core/health_diag.py`，纯函数：

```python
classify_channel(plat, round_plat, path_rows, login_state, cookie_state) -> dict
```

输出字段：`kind`（`ok/calendar_only/partial/login/cookie_expired/captcha/ip/timeout/empty/maintenance/unscanned/unknown`）、`label`、`action`、`evidence`、`round_status`、`login_status`、`cookie_status`。

规则：

- 本轮无该渠道记录 → `unscanned`，不绿。
- `ok` 且 `detail_ok>0` → `ok`；只有日历 → `calendar_only`。
- `part` → `partial`，显示成功/尝试数；不因一条拒绝就判整渠道失败。
- 笔记含 `179991/风控/限流/IP/403/429/封` → `ip`；动作“停止重试、等待冷却/更换出口网络”，禁止循环重试。
- 含 `验证码/滑块/人机/challenge` → `captcha`；动作“打开可见窗口人工完成”，不自动重试。
- 明确登录标记（`need_login/未登录硬拒/请登录/会话失效`）→ `login`；**1999 + “没有符合条件的航班” → `empty`，不是登录**。
- `超时/timeout` → `timeout`；`maint` → `maintenance`；其余 → `unknown`。
- Cookie 本地检查（只读 storage-state JSON）：无文件 `missing`；全部 `expires` 已过 `expired`；否则 `unverified`。`expired` 单独成 `cookie_expired`，不混同登录失效。

### 3.2 证据账本

- `core/health.py` 笔记截断 40 → 160 字符，保留 `179991` 等标记。
- 明确 Qunar 1999 空结果日志标记归为 `empty`，不计失败。
- 新增 `logs/channel_evidence.jsonl` 追加账本（capped 500 行）：`ts/plat/scope/kind/status/path/rows/note/source`；只记录证据，不合成 monitor.log 行。
- `POST /api/channel/selfcheck`：同源 JSON，单渠道单飞；只做本地 Cookie 过期检查 + 最近轮次证据归并，不启动外网请求、不写会话、不绕过验证码。返回分类卡与动作。
- `GET /api/health` 增加 `diag` 字段，由 `classify_channel` 生成；`webui.py` 的 `renderHealthDiag` 改为纯渲染，不再用正则猜测。

### 3.3 UI

- 诊断卡 5/3/2/1 断点，不再 4+1 孤儿。
- 颜色不是唯一信号：`登录失效/验证码/IP/超时/未扫描` 都有文案与动作。
- 动作：`打开登录`（login/captcha）、`停止重试/检查出口`（ip）、`查看该轮日志`（timeout/unknown）、`等待下一轮`（unscanned）。
- 无证据不显示绿色“正常”。

## 4. 证据链

### 4.1 数据

`flight_prices.prov TEXT`（JSON，幂等迁移）与 `fetch_paths`：

```sql
id INTEGER PRIMARY KEY AUTOINCREMENT,
fetched_at TEXT, platform TEXT, from_city TEXT, to_city TEXT,
depart_date TEXT, entry_path TEXT, path_status TEXT,
request_url TEXT, http_status INTEGER, rows INTEGER,
note TEXT, evidence_level TEXT
```

`prov` 字段：`entryPath/pathId/pathStatus/requestUrl/evidenceLevel/kind`。`evidence_level` 只允许：

- `path`：渠道路径账本（可证明入口/状态，非逐行原始响应）；
- `parsed_extra`：解析后的 extra；
- `unknown`：历史无记录。

本轮不声称 `raw_http`；`/api/probe/raw` 只返回 `extra` 时必须标注 `evidence_level=parsed_extra`，UI 不再写“原始行与解析逐项一致”，改为“解析 extra 对照（非原始响应）”。

### 4.2 写入与展示

- 扫描：`main.py` 保存 FlightPrice 时取 crawler `paths` 的最后成功 entry（日历行优先日历路径），写 `fetch_paths` 与 `prov`；缺失写 `unknown`。
- 探针：`_entry_path` 升级为 `pathId/pathStatus`；混合路径按行 kind 选择，无法判定时标 `unknown`，不把最后入口套给所有行。
- `/api/state` 行带 `prov`；搜索行徽标、详情“采集入口”、CSV（entry/fetched_at/row_id/evidence_level）、推送、雷达低价航班都消费同一字段。
- 历史/推送时间使用行 `fetched_at`，不是发送时的 `now()`；推送打印来源渠道，链接渠道与实际来源不一致时标“来源渠道 X / 链接渠道 Y”。
- 雷达低价航班返回 `rowId/rawIdx/entryPath`；无记录明确“未记录”。

## 5. 视觉与移动

### 5.1 令牌与组件

- 单一圆角：卡片 14、容器 12、控件 8、胶囊 `--pill`；移除 `.monwatch/.ws-row` 旧 9/8px 与 `--r/--r2` 消费。
- 卡片统一 `shadow:none`；仅弹层/浮层保留阴影；hover 不位移。
- 关注航班去掉重复标题；KPI 条与关注航线同构；范围按钮统一 `.rngchip` 语法。
- 登录卡从 `card > lgcard > lgslot` 三层收为两层；标签 12px、触控 ≥36（coarse）。
- 价格语法统一为 `.price-lg/md/sm`；颜色只编码状态（达标/关注/错误），不按页面换色。

### 5.2 Sector Strip 签名

一个 44px 航线轨：`SHA ───●─── URC`，目标价作为缺口，右侧价格戳，末尾两字状态（如 `新低/达标/仅历`）。使用于：

- 概览关注航线卡；
- 关注台航线摘要；
- 特价监控低价日卡；
- 检索列表行的紧凑变体。

替换 31px 大数字、装饰性火花线和 3px 渠道竖条；渠道 logo 保持唯一多彩元素。颜色方向：冷灰底 + 墨色 + 信号朱红（仅目标/新低）+ 清绿（成功）；不使用通用奶油衬线/黑底荧光绿/报纸栏默认。

### 5.3 折叠与移动

- 统一 `srxSetFold()`：class/text/aria-expanded/aria-controls/localStorage 同步；刷新后按钮文案与状态一致。
- `#srxBrief` 在 901–1024 按容器宽度切换 5 列/横向 148px，不压字；`srx-src-h` 可省略但 title 完整。
- 320/390 hero 折叠按钮进入文档流，不覆盖 eyebrow/说明。
- `#srxMirror` 折叠后网格收为一列，不留 650px 空列。
- 特价日历 `xhint` 遮罩 + 选中日 `scrollIntoView({inline:'nearest'})`；日期按钮 `aria-pressed`。
- `#spMonChart` 增加 `role=img` + 隐藏数据表（日期/最低价/渠道），键盘可读。
- 低日航班 ≤360 两行网格，航班号/时刻/价格不重叠。
- 诊断卡 5/3/2/1；日历/条件输入触控 ≥36。

## 6. 性能

### 6.1 已测基线

- live 8765，1440×900，50 行，CDP 4× CPU：P50 246.3 / P95 337.9 / max 395.4ms。
- 成本：整表 innerHTML 重建 ~43%；每行 5 SVG + 2 IMG；筛选面板关闭仍重建 facets（~21% P95）。
- 200% 等效视口（720×450，24 行）：P50 140.8 / P95 167.1ms。

### 6.2 改动与目标

1. `srxRenderFacets` 仅在面板打开时重建（打开路径强制重建）。
2. 行图标改为 CSS mask/sprite 或缓存模板，移除每行重复 `<svg><use>`；保留主题/打印/forced-colors 回退。
3. 避免同数据重复渲染：筛选只重建变化行；矩阵/列表切换复用已构建行。
4. 目标：4× 50 行 P95 ≤300ms；200% 24 行 P95 ≤200ms；1× 50 行 P95 ≤100ms。若 50 行/4× 仍 >300，如实记录，不宣称达标。
5. 新增 `docs/perf_gate.py`：固定 demo 数据/50 行、CDP 4×、25 次、P50/P95/max，输出 JSON；不进入默认 CI 的硬门禁，发布前必跑。

### 6.3 缩放

- 用 viewport(W/z × H/z)+DSF z 作为浏览器缩放的等效布局条件；记录该方法与真实浏览器缩放的区别（子像素/字体 hinting/滚动条几何不可证）。
- 验收：100%/125%/200% 等效无横溢、无遮挡；200% 24 行 P95 ≤200ms。

## 7. 文档与发布

- README/EN：五个子视图 → 六个；平台/能力计数与实现一致。
- `docs/ACCEPTANCE_MATRIX.md` 重写为 v1.5.295 本轮真实矩阵（不沿用 v293 行数/旧 PID）；证据 JSON 纳入仓库或明确标注不可复现。
- `docs/site/index.html` 增加构建戳（版本 + 源 SHA + 生成日）；`demo_build.py` 注入；对齐检查读取。
- `release_align_check.py`：live 8765 不可跳过；校验远端资产 digest、tag SHA、CI/release-build `head_sha`、Pages 部署、站点构建戳；`release-build.yml` sidecar 路径修正为 `dist_package/<asset>.zip.sha256` 或直接不传 sidecar。
- 版本 v1.5.295；本地候选，只有单独确认后才 force-with-lease、重建资产、更新 Release、最后移动 tag。

## 8. 验收

### 行为

- 配置 `special_radar` 后自动轮询真正取数；首轮 90 秒，下一轮 2 小时；扫描持锁跳过。
- A 用户改航线/日期后，B 用户/旧条件不会串入；历史只返回当前 query_key。
- 首轮不提醒；新低≥drop_min 且冷却外提醒一次；同价/回升不提醒；阈值跌破一次后重新武装；fallback/cache/partial/演示不提醒。
- 健康：无本轮不绿；部分成功不绿；179991→IP；Qunar 1999 空结果→empty；CAPTCHA→人工验证；Cookie 过期单独显示；动作不触发自动重试。
- 扫描行/探针行/CSV/详情/推送/雷达低价航班都有来源或明确 unknown；RAW 标 parsed_extra。
- 320/390 折叠按钮不压字；五源 901/1024 不压字；日历选中日可见；图表有可读数据表；低日航班不重叠。
- 4× 50 行 P95 ≤300ms；200% 24 行 P95 ≤200ms；无 JS 错误。

### 门禁

- 新增 pytest：雷达 query_key/提醒规则/并发/演示/口径；健康分类/日志截断/Qunar 空；prov 迁移/CSV/RAW 标签；折叠 aria/移动选择器源码钉。
- UI：628+ 新断言，覆盖 320/390/1024/1280/1440/1512、亮暗、折叠持久、五源、日历、诊断、Sector Strip。
- live：真实 8765 探针 1 条验证 entryPath；特价监控 7 日/3 快照；诊断 5 卡。
- 公开：截图/站点/README/矩阵/Release 对齐检查全绿。

## 9. 实施批次

同一个 v1.5.295 候选分两批，批次间都跑聚焦测试与 320/390/1440 冒烟，不发布：

- **批次 1（真实性与监控）**：配置持久化 → query_key/radar_runs → 提醒状态/规则/推送 → 健康分类与证据账本 → provenance 表/字段/CSV/RAW 标签。
- **批次 2（体验与性能）**：令牌/登录/价格语法 → Sector Strip → 折叠/移动/图表可读 → 性能守卫与图标复用 → 截图/站点/矩阵/门禁。

若批次 1 发现 schema 或提醒语义阻塞，先停在可回滚的批次 1，不强行在同期做视觉大改。

## 10. 风险与回滚

- 迁移只加列/表，旧库可读；失败不删除旧快照。
- 提醒默认关闭；用户显式开启后首轮只播种，避免上线即推送。
- 证据链只承诺路径级，不承诺逐行原始响应；无法证明的字段标 unknown。
- 视觉改动集中在 token/共享组件，保留 v1.5.294 截图作回滚参照。
- 发布前备份 bundle/diff/untracked；任何共享历史改写用 lease 保护。
