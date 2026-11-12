# 发版就绪报告 · 2026-11-10

> 结论：**代码就绪，等你点头触发构建**。产物需人审后再挂 Release（我不擅自挂）。

## 一、CI（GitHub Actions，提交 `ff756c7`）

```
CI → success
  test (0) test (1) test (2) test (3)   success   （4 分片全量）
  uitest (0) uitest (1)                 success
  ci-ok                                 success
  pages build and deployment            success
https://github.com/dengmeiluan/ticket-monitoring/actions/runs/42736400041
```

## 二、发版前用户视角冒烟（本机 8765，22 项全过）

| 组 | 项目 | 结果 |
|---|---|---|
| A 渠道健康面板 | 降级行 / 建议行 / 弱环行 / 覆盖行 / 版本行 | ✓ 5/5 |
| A | 诊断链接可见（真机量尺寸） | ✓ 48×16 |
| A | 距离建议链接可见 | ✓ 333×37 |
| B 诊断视图 | 「通路耗时」展开 | ✓ 18 行 |
| B | 「距离分桶」展开 | ✓ 30 行 |
| C | 检查更新（只读） | ✓ 已是最新 |
| D 双端登录弹窗 | 携程 / 飞猪 / 同程 / 途牛（**PC + H5 + 双端标题**） | ✓ 4/4 |
| 全部 | JS 报错 | ✓ 0 |

> 冒烟脚本：`_scratch/r1063_t325_smoke2.py`（每组独立页面；`innerText` 对隐藏节点为空，
> 所以用 `textContent` + `wait_for_function` 显式等待）

## 三、本轮实际改动清单（已全部在 `main`）

| 面 | 内容 |
|---|---|
| 登录/核验（issue #15） | 核验忽略 URL 启发式；PC 槽位读核验结果并显示「核验于 HH:MM」；`page_ok` 按钮改「再核验」 |
| 登录槽位 | H5 槽位"明细可用"改按端面通路账本判定，并抬成 `available`；双端弹窗固定 PC 在前 |
| 智行采集 | 日历限频后明细自开弹层；日历**滚动方向修正**；国际失败不计连败；App 停在列表页则重启；整窗收割 + 失败取证 |
| 升级 | 新增 `core.update`（check/download/apply + 备份回滚）；面板「检查更新 / 立即升级」；跳过 `.git`/`.env` 修正；包装层判定修正 |
| 观测/建议 | `/api/insight`（耗时/距离）+ 面板就地展开；`distance_advice` 结构性建议（可点跳视野字段）；通路口径提示；阈值可配 |
| 配置 | 面板保存后同步 `_State.cfg`（此前改 crawler 选项不生效） |
| 门禁 | `test_r1063_commit_integrity`（27 处标记对账）；AST 守卫禁 `lstrip("./")`；`TM_LIVE_UI=1` 才跑实时 UI |

## 四、航线变更（你已批准）

`SHA→HAK` 增加 `2026-11-20`、`2026-11-27`（`direct_only` 保留）。
08:52–08:57 一轮实测：ctrip / fliggy / tongcheng / tuniu / app_qunar 各已落库；
智行 08:56 那轮 `航班明细 ok` + `日历 52 天有价`，远日期按 45 天视野 `unsupported` 让路。

## 五、发版需要做的两步（第一步等你一句话）

```bash
# 1) 触发四平台构建（push_image 默认 false；要么改 true 连镜像一起）
python _scratch/r1063_dispatch_release.py

# 2) 产物下载 + 校验 + 人审后挂 v1.0 Release（这一步不自动做）
python tools/verify_release_assets.py <产物目录>
```

## 六、遗留（不影响发版）

* `test_sweep_pacing_gate::test_second_round_is_skipped_by_ttl` 与
  `test_r993_pace_tools_flat::test_trace_detail…` 在**负载下**偶发红；
  干净克隆单跑均通过（属时序抖动，非本轮改动引入）。
* 并行会话的 17 条 UI 用例仍在其未提交改动里，未纳入本次提交。


## 七、演示站偏差（发版前需要**重烘一次**，我不擅自做）

线上演示站 <https://dengmeiluan.github.io/ticket-monitoring/site/> 已随我的提交部署成功
（Pages `status=built`，head `330138d`），但**内容是旧的**：

```
站点 HTTP 200 · 6.0MB
  含「检查更新」   False
  含「通路耗时」   False
  含「距离分桶」   False
```

原因：`docs/site/index.html` 是**手工烘焙产物**（`python docs/demo_build.py`），
不随 `webui.py` 自动刷新；仓库里那份目前还是并行会话**未提交**的版本。

**我做了非破坏性验证**：把烘站模块的 `OUT` 指到临时目录烘了一次，结果全部命中：

```
检查更新 True · 通路耗时 True · 距离分桶 True · srxDistJump True · insightBox True
站戳：<meta name="tm-build" content="1.6.0 code:117d6d1edc0f 2026-11-10">
```

**为什么不直接提交这次烘焙**：临时产物是用**当前工作树**烘的，里面含并行会话
尚未提交的 `webui.py` 改动——提交它等于把别人的 WIP 一起发布。

**发版时建议的执行顺序**（一行命令，等并行会话提交后）：
```bash
python docs/demo_build.py    # 重新烘焙 docs/site/index.html
git add docs/site/index.html && git commit -m "chore: 演示站重烘" && git push
```


## 八、发版对齐检查（仓库自带工具 `docs/release_align_check.py`）

跑了一遍（`version=1.6.0 head=53cb937`），**大部分 OK**，9 条 FAIL 逐条归属如下：

| 检查项 | 结果 | 归属 / 处理 |
|---|---|---|
| `site build stamp current` | stale（`code:00cf10ca…` ≠ 当前 `117d6d1e…`） | **需重烘**：`python docs/demo_build.py`（见第七节） |
| `published site stamp matches HEAD` | 线上 `code:1e009b88…`（11-09） | 同上，重烘+推送后即对齐 |
| `release source SHA matches HEAD` | 发布源码 `16b54ea` ≠ HEAD `53cb937` | **需重建 Release**：`release-build` 四平台构建 |
| `working tree clean at release` | `M README.md`（+`README_EN.md`） | **并行会话未提交**的措辞改动（"逐轮"→"逐小时分段"），不是本次改动；发版前需他们提交 |
| `uitest result green and readable` | `docs/uitest_result.txt` 未跟踪 | 同上：UI 自检结果还没提交 |
| `no orphan screenshots` | 4 张未被引用的截图 | 仓库内务：删除或在文档中引用（非本轮引入） |
| `exactly one Pages deployment` | 存在 9 条历史 deployment | 仓库内务：`docs/prune_deployments.py` 清理 |
| `pytest count readable` | collect 失败：`文件名或扩展名太长`（Win MAX_PATH） | **本机环境问题**，CI 上正常（CI 绿） |
| （附）`SHA256SUMS` 下载 | 本地代理连不上 github.com:443 | 已回退到 API 摘要核对 4 个 zip，结论 OK |

**结论**：属于"我这轮改动"的待办**已清零**；剩下的都指向
①重烘演示站 ②重建 Release ③并行会话提交其改动 ④仓库内务（孤儿截图/历史 deployment）。
