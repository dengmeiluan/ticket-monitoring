# 采集策略控制面 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让「每个渠道 × 每个维度 × 每个链路」的主动/被动/自动化调整策略都是可配置、可视化、可干预、可中断、可区分、可识别、可建议、可独立的一等公民，并全部热生效。

**Architecture:** 六层归位（L0 事实 ← L1 策略目录与参数 ← L2 决策 ← L3 执行；L4 暴露只读 L1/L2 并写台账；L5 门禁证伪）。参数走「全局唯一提供者」`core/strategy_params.py`（三级继承：默认→全局→渠道→维度/链路），目录与审计走 `core/strategy_contract.py`（十轴矩阵，读真实登记点，不写第二份声明）。参数编辑只走既有 `POST /api/config`；`/api/strategy/*` 只做运行期干预。

**Tech Stack:** Python 3.11（无第三方新增依赖）、`webui.py` 单文件前端（原生 JS）、pytest（`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`）、既有台账 `core/storage.py::save_intervention`。

**Spec:** `docs/superpowers/specs/2026-11-06-crawl-strategy-control-plane-design.md`

## Global Constraints

- 轮次号：**r1063 起**；新门禁文件命名 `tests/test_r1063_*.py`；源码注释用中文，写清「为什么」，不写「做了什么」。
- 运行测试：`$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"; python -m pytest tests/test_r1063_xxx.py -q`（xxx 按任务替换为实际门禁文件名；本计划尚未创建的测试文件标注「待建」）（xxx 按任务替换为实际门禁文件名；本计划尚未创建的测试文件均标注「待建」）（不设这个变量会因 `langsmith→requests_toolbelt` 导入失败而整体崩）。
- 现状基线：`7180 tests collected`，全绿。任何任务结束时不得引入红项。
- **行为等价**：`_PACE`=healthy 1.0 / rehab 1.5 / watch 1.5 / degraded 2.5 / blocked 3.0；`_BLOCK_S`=human 3600 / rotate 3600 / 其余 0；`_STICKY_S`=watch 1800 / degraded 3600 / rehab 1800；产量阈值 `n>=8`、`lo<0.40`、`lo>=0.90`；`_THRESHOLD`=80 human / 65 pause / 45 slow / 25 watch；`LOGIN_BACKOFF`=(0, 90, 300, 900, 1800, 3600, 7200)。
- **热**：任何参数改动下一轮即生效，不需要重启；`strategy_params` 是模块级单例提供者，禁止把参数抄进实例属性。
- **不写第二份声明**：审计只读真实读点/真实控件；不许为了矩阵好看塞没人读的控件。
- **不可逆动作只建议**：换身份/重登不做执行路由；设备身份一律不动。
- **台账三族**：`auto_*`（自动）、`strategy_*`（策略变更与停手）、其余（人工）。前两族都从「人工干预成效/成功率」排除。
- 前端受既有几何门禁：390/320 无横向溢出、按钮 ≥28px、半像素字号 0、零 `pageerror`。
- **（目标扩句 2026-11-06）矩阵是 15 轴**：原 10 轴 + `visualizable` 可可视化 / `adjustable` 可调整 / `clear` 可清晰 / `intent` 可意图理解 / `stats` 可统计（`semantics` 语义清晰保留）。判据见规格 §4.1。
- **（界面铁律）微信级扁平化**：策略行与芯片必须长在既有 `#paceBox` / `#panel-pacing` 骨架上（白卡分组、无描边、无卡中卡、圆角 12~14px、chip 32px、按钮 ≥28px）；文案一律中文短句 ≤20 字，不许露裸 id、不许英文标签；新增节点复用既有 `.pace-row` / `.hbadge` / `.glcell` 家族，不许另起一套视觉。

## Review Focus

1. **配置键改名/搬家的静默失效**：把常量搬成配置后，若某处仍读旧常量，界面显示新值而运行时用旧值——这是「配了不生效」，最坏的一类。测试必须断言**运行时读到的值与配置一致**，而不是断言配置里有这个键。
2. **链路闸门误伤整渠道**：`main.py` 的 `observe()` 把一次查询里所有失败通路聚合成一次渠道级熔断；新增链路级禁用后，被禁用通路记成失败会把整个渠道熔断。必须断言「被策略禁用的通路只记 `paced`，不进熔断、不进成功率分母」。
3. **halt 与既有状态机抢戏**：`policy_state.json` 有 blocked 窗口/余温/rehab 一串「先尊重既成事实」的逻辑；halt 必须**最先生效**且到期自动消失，且 `/api/pacing/reset` 不得顺手清掉人工停手。
4. **三族台账污染指标**：`strategy_*` 若混进 `intervention_effect` / `intervention_success_rate`，用户调一次参就把该渠道的历史对比清空，指标失去意义。
5. **演示态与无样本**：演示模式下策略行不得显示合成百分比，`na`/无样本必须自述理由（不许静默留空）。

---

### Task 1: 策略登记表与十轴审计（`core/strategy_contract.py`）

**Files:**
- Create: `core/strategy_contract.py`
- Test: `tests/test_r1063_strategy_contract.py`

**Interfaces:**
- Produces:
  - `Param(pid: str, cfg: str, kind: str, default, lo=None, hi=None)` — `kind ∈ {"int","float","bool","str"}`；`pid` 形如 `"pace_factor.healthy"`；`cfg` 是 `config.yaml` 里的点路径。
  - `Strategy(id: str, cn: str, family: str, trigger: str, scope: tuple, params: tuple[Param, ...], decide: str, api: tuple = (), advice: str = "", auto_default: bool = True, gate: str = "", na_reason: str = "")` — `trigger ∈ {"proactive","reactive","auto"}`；`scope ⊂ {"global","channel","dimension","path"}`；`decide` 形如 `"core.policy:decide"`。
  - `STRATEGIES: tuple[Strategy, ...]`（28 条，逐条照 Spec 附录 B）
  - `AXES: tuple[tuple[str, str], ...]`（10 条：id + 中文名）
  - `Row(sid, plat, axis, state, note)`，`state ∈ {"y","n","na"}`
  - `audit(plats: Sequence[str] | None = None) -> list[Row]`
  - `defects(rows=None) -> list[Row]`（只返回 `state == "n"`）
  - `matrix_text(plats=None) -> str`；`__main__` 支持 `python -m core.strategy_contract [--strict] [--json]`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_r1063_strategy_contract.py
# -*- coding: utf-8 -*-
"""r1063：策略目录的十轴矩阵必须无缺口，且判据不是恒真。

十轴沿用 core/channel_contract.py 的语言：可配置/可观测/可干预/可开启/
可中断/可区分/可识别/可建议/可独立/语义清晰。每一格都去读**真实登记点**
（config 键被生产代码读、路由真存在、控件真有落点），不读第二份声明。

注意（preflight 裁决）：本文件只钉「目录自身完整性 + 可配置/语义清晰/可识别」
三轴——另外四轴（可观测/可干预/可开启/可中断/可区分/可建议/可独立）要等
T6/T12/T13 把接口与界面建起来才可能存在，十轴全绿的断言在 T12。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_registry_has_28_strategies_with_unique_ids():
    from core.strategy_contract import STRATEGIES
    assert len(STRATEGIES) == 28
    ids = [s.id for s in STRATEGIES]
    assert len(ids) == len(set(ids))
    assert {"ttl_tier", "rate_per_minute", "policy_gate", "block_window"} <= set(ids)


def test_configurable_axis_reads_real_production_code():
    """可配置轴：cfg 点路径的末段必须出现在生产代码里。

    负控（本测试下半段）：把一个 pid 的 cfg 改成不存在的键 → 必须报 n。
    """
    from core import strategy_contract as sc
    rows = [r for r in sc.audit() if r.axis == "configurable"]
    assert rows, "audit 没求值"
    assert not [r for r in rows if r.state == "n"], [
        (r.sid, r.plat, r.note) for r in rows if r.state == "n"][:5]

    import dataclasses
    bad = dataclasses.replace(
        sc.STRATEGIES[0],
        params=(sc.Param("ttl_tier.fast", "schedule.no_such_key_xyz",
                         "int", 15),))
    rows2 = sc.audit(strategies=(bad,))
    assert [r for r in rows2 if r.state == "n"], "判据恒真：伪键没被抓出来"


def test_semantics_and_identifiable_axes_are_clean():
    from core import strategy_contract as sc
    for axis in ("semantics", "identifiable"):
        bad = [r for r in sc.audit() if r.axis == axis and r.state == "n"]
        assert not bad, (axis, [(r.sid, r.plat, r.note) for r in bad][:5])


def test_na_cells_must_say_why():
    rows = [r for r in _audit() if r.state == "na"]
    assert rows, "一个 na 都没有，说明判据没真的求值"
    assert all(r.note.strip() for r in rows), "na 必须写明理由"


def test_cli_prints_the_matrix():
    import subprocess
    import sys
    out = subprocess.run([sys.executable, "-m", "core.strategy_contract"],
                         cwd=ROOT, capture_output=True, text=True,
                         encoding="utf-8")
    assert out.returncode == 0, out.stdout[-800:] + out.stderr[-800:]
    assert "策略" in out.stdout
```

- [ ] **Step 2: 跑测试确认失败**

Run: `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"; python -m pytest tests/test_r1063_strategy_contract.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.strategy_contract'`

- [ ] **Step 3: 实现 `core/strategy_contract.py`**

模块 docstring 必须写清三条设计约束（照 `core/channel_contract.py` 的体例）：
①不写第二份声明；②状态只有 `y/n/na` 三种；③新策略/新渠道的验收就是 `audit()` 无 `n`。

`STRATEGIES` 按 Spec 附录 B 的 28 行逐条填，**一行都不能少**（`test_registry_has_28_strategies_with_unique_ids` 会数）。
两条 preflight 裁决写进模块 docstring：
① `crawler.policy.*` / `crawler.risk.*` 这类**新键**的 `Param` 不在本任务登记，
由 T3/T4 在「加读点」的同一步补上（否则可配置轴当场为 `n`，等于自欺）；
② 人工停手（halt）不是一条可配置策略，它是 `block_window` 的干预动作，
登记在 `block_window.api` 上，不单独占一条 `Strategy`。
填法示例（第一行，其余同构）：

```python
Strategy(id="ttl_tier", cn="分层 TTL", family="节奏", trigger="proactive",
         scope=("global", "channel", "dimension"),
         params=(Param("ttl_tier.fast", "schedule.fast_ttl_min", "int", 15, 5, 1440),
                 Param("ttl_tier.slow", "schedule.slow_ttl_min", "int", 120, 5, 1440)),
         decide="core.pacing:plan_query", api=(), advice="core.pacing:advise",
         gate="tests/test_r1063_strategy_contract.py")
```

`audit()` 的十轴判据（每轴一个私有函数，都读源码，不读声明）：

| axis | 判据 |
|---|---|
| `configurable` | 对每个 `Param.cfg`，末段字面量出现在 `core/*.py`、`crawlers/*.py`、`main.py` 之一（`re.search`）；缺一即 `n`，note 写「谁没读」 |
| `observable` | `webui.py` 里有 `/api/strategy` 且 `matrix_text`/`audit` 被引用；否则 `n` |
| `intervenable` | `Strategy.api` 里每个路由字面量在 `webui.py` 出现（`self.path == "/api/x"` 或 `elif self.path == "/api/x"`（`/api/x` 为示意占位，均未按此名实现））|
| `toggleable` | 该策略至少有一个 `kind == "bool"` 的 `Param`，或 `auto_default is False`（只建议类）→ 否则 `n` |
| `interruptible` | 该策略的 `api` 含 `/api/strategy/halt` 或在 `path` 粒度策略的 `api` 含 `/api/probe/cancel`；否则 `na` + 理由 |
| `distinguishable` | `webui.py` 含 `data-strategy` 与 `auto_`、`strategy_` 两个前缀判定 |
| `identifiable` | `Strategy.cn` 非空且在 `webui.py` 出现（渲染器从目录取，此轴对 `STRATEGY_CN` 兜底表求值）|
| `advisable` | `Strategy.advice` 存在且该函数名在对应模块里可 `getattr` 到 |
| `independent` | 该策略 `scope` 含 `channel`，或 `na` + 理由（只全局的调度类记 `na`）|
| `semantics` | `trigger`/`scope`/`family` 取值都在枚举内，`params` 非空（只建议类可为空并给 `na_reason`）|

`--strict`：`sys.exit(1 if defects() else 0)`。

- [ ] **Step 4: 跑测试确认通过**

Run: `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"; python -m pytest tests/test_r1063_strategy_contract.py -q`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add core/strategy_contract.py tests/test_r1063_strategy_contract.py
git commit -m "feat(r1063): 策略目录与十轴审计矩阵"
```

---

### Task 2: 三级继承参数提供者（`core/strategy_params.py`）

**Files:**
- Create: `core/strategy_params.py`
- Test: `tests/test_r1063_strategy_params.py`

**Interfaces:**
- Consumes: `core.strategy_contract.STRATEGIES`、`Param`
- Produces:
  - `set_config(cfg: dict) -> None`（模块级单例；可重入；`reload_config()` 里调用一次即全站热生效）
  - `get_config() -> dict`
  - `resolve(pid: str, *, plat: str = "", dim: str = "", path: str = "") -> Resolved`，`Resolved = NamedTuple("Resolved", [("value", object), ("source", str), ("pid", str)])`，`source ∈ {"default","global","channel","dimension","path"}`
  - `override_key(plat: str, dim: str = "", path: str = "") -> str`；`parse_override_key(key: str) -> tuple[str, str, str]`（未知段抛 `ValueError`）
  - `clamp(pid: str, value) -> tuple[object, str]`（返回 `(夹后值, 说明or空串)`）
  - `effective_table(plats: Sequence[str]) -> list[dict]`（给 `/api/strategy`：`{pid, plat, value, source, default, lo, hi}`）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_r1063_strategy_params.py
# -*- coding: utf-8 -*-
"""r1063：参数三级继承、来源标注、粒度独立、钳制回写。"""
import pytest

from core import strategy_params as sp


@pytest.fixture(autouse=True)
def _cfg():
    sp.set_config({"schedule": {"fast_ttl_min": 30},
                   "crawler": {"rate": {"per_minute": 0},
                               "policy": {"pace": {"watch": 2.0}},
                               "strategy_overrides": {
                                   "fliggy": {"rate_per_minute.value": 9},
                                   "tongcheng/intl/PC":
                                       {"rate_per_minute.value": 3}}}})
    yield
    sp.invalidate()


def test_default_when_nothing_configured():
    got = sp.resolve("ttl_tier.fast")
    assert (got.value, got.source) == (15, "default")


def test_global_beats_default():
    got = sp.resolve("ttl_tier.fast")
    assert got.value == 30 and got.source == "global"


def test_channel_override_beats_global():
    assert sp.resolve("rate_per_minute.value", plat="fliggy").value == 9
    assert sp.resolve("rate_per_minute.value", plat="ctrip").source == "global"


def test_path_override_beats_channel_override():
    got = sp.resolve("rate_per_minute.value", plat="tongcheng",
                     dim="intl", path="PC")
    assert (got.value, got.source) == (3, "path")
    # 只给渠道、不给维度时落在渠道（已配的渠道覆盖）
    assert sp.resolve("rate_per_minute.value",
                      plat="tongcheng").source == "global"


def test_override_key_rejects_unknown_segments():
    with pytest.raises(ValueError):
        sp.parse_override_key("nosuchchan/intl/PC")
    with pytest.raises(ValueError):
        sp.parse_override_key("ctrip/nosuchdim/PC")
    with pytest.raises(ValueError):
        sp.parse_override_key("ctrip/intl/nosuchpath")


def test_clamp_returns_note_so_ui_can_write_back():
    v, note = sp.clamp("ttl_tier.fast", 99999)
    assert v == 1440 and note


def test_no_module_may_cache_params_on_instances():
    """热链路的硬约束：参数只在提供者里，不许抄进实例属性。"""
    import io
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    body = io.open(os.path.join(root, "core", "policy.py"),
                   encoding="utf-8").read()
    assert "self._pace =" not in body and "self._block_s =" not in body
```

- [ ] **Step 2: 跑测试确认失败**

Run: `... pytest tests/test_r1063_strategy_params.py -q` → FAIL（模块不存在）

- [ ] **Step 3: 实现**

解析优先级（后者覆盖前者）：`Param.default` → `cfg` 里 `Param.cfg` 的点路径 →
`crawler.strategy_overrides[override_key(plat)]` → `[override_key(plat, dim)]` →
`[override_key(plat, dim, path)]`。覆盖字典的键是 `Param.pid`，值直接是值。
`parse_override_key` 用 `core.channels.BROWSER_CHANNELS + APP_CHANNELS`、
`core.channels.DIMENSIONS`、`core.channels.PATH_CN` 三张表校验，未知段抛 `ValueError`
（不许静默丢弃——`SPEC:1664`）。`PATH_CN` 的键含 `%s` 模板（`app-city-%s`），
校验时先做 `k.replace("%s", "")` 前缀匹配。

- [ ] **Step 4: 跑测试确认通过** → 7 passed

- [ ] **Step 5: 提交**

```bash
git add core/strategy_params.py tests/test_r1063_strategy_params.py
git commit -m "feat(r1063): 三级继承的参数提供者（热生效单例）"
```

---

### Task 3: `core/policy.py` 参数化（行为逐位等价）

**Files:**
- Modify: `core/policy.py`（`_PACE`/`_BLOCK_S`/`_STICKY_S`/产量阈值）
- Test: `tests/test_r1063_policy_params_equivalent.py`

**Interfaces:**
- Consumes: `strategy_params.resolve`
- Produces: 同签名 `decide(...)`；新增 `POLICY_PIDS: dict[str, str]`（`{"pace.healthy": "pace_factor.healthy", ...}`）便于门禁对账

- [ ] **Step 1: 写失败测试**

```python
# tests/test_r1063_policy_params_equivalent.py
# -*- coding: utf-8 -*-
"""r1063：常量搬进参数层后，取值必须与搬家前逐位相等（行为不变）。"""
from core import strategy_params as sp


def test_pace_block_sticky_values_are_identical_to_pre_r1063():
    sp.set_config({})
    want = {"pace_factor.healthy": 1.0, "pace_factor.rehab": 1.5,
            "pace_factor.watch": 1.5, "pace_factor.degraded": 2.5,
            "pace_factor.blocked": 3.0,
            "block_window.human": 3600, "block_window.rotate": 3600,
            "residue_window.watch": 1800, "residue_window.degraded": 3600,
            "residue_window.rehab": 1800,
            "health_bands.min_samples": 8, "health_bands.ok_low": 0.40,
            "health_bands.ok_high": 0.90}
    for pid, val in want.items():
        got = sp.resolve(pid)
        assert (got.value, got.source) == (val, "default"), pid


def test_decide_reads_params_not_hardcoded_constants():
    """改配置后决策必须跟着变——这是「热生效」的最小证据。"""
    from core.policy import PolicyEngine
    sp.set_config({"crawler": {"policy": {"pace": {"healthy": 2.0}}}})
    eng = PolicyEngine({}, repo_root=".", profile="zz_r1063")
    p = eng.decide("ctrip", two_way=True)
    assert p.pace_factor == 2.0
```

- [ ] **Step 2: 跑测试确认失败** → FAIL（`resolve` 认不出的 pid / pace 仍 1.0）

- [ ] **Step 3: 实现**

- 在 `core/strategy_contract.py` 的 `pace_factor`/`block_window`/`residue_window`/`health_bands`
  四条策略的 `params` 里补上上述 pid（`cfg` 指向新键
  `crawler.policy.pace.<state>`、`crawler.policy.block_s.<state>`、
  `crawler.policy.sticky_s.<state>`、`crawler.health.*`）。
- `core/policy.py` 里删掉 `_PACE/_BLOCK_S/_STICKY_S` 三个常量，改成模块级函数
  `_pace(state)`、`_block(level)`、`_sticky(state)`，内部 `sp.resolve(...).value`。
- 产量阈值改为 `sp.resolve("health_bands.min_samples")` 等三处。

- [ ] **Step 4: 跑测试** → 2 passed；再跑既有 `tests/test_r913_policy_engine.py` 确认仍绿
Run: `... pytest tests/test_r913_policy_engine.py tests/test_r1063_policy_params_equivalent.py -q`

- [ ] **Step 5: 提交**

```bash
git add core/policy.py core/strategy_contract.py tests/test_r1063_policy_params_equivalent.py
git commit -m "refactor(r1063): 策略常量搬进参数层，取值逐位等价"
```

---

### Task 4: `core/riskscore.py` 参数化（阈值与登录退避阶梯）

**Files:**
- Modify: `core/riskscore.py`（`_THRESHOLD`、`LOGIN_BACKOFF`）
- Test: `tests/test_r1063_risk_params_equivalent.py`

**Interfaces:** Consumes `strategy_params.resolve`；Produces 同签名 `evaluate(signals) -> dict`、`LoginLedger.backoff_s(plat)`。

- [ ] **Step 1: 写失败测试**

```python
def test_thresholds_and_backoff_defaults_unchanged():
    sp.set_config({})
    assert [sp.resolve("risk_bands.%s" % k).value
            for k in ("watch", "slow", "pause", "human")] == [25, 45, 65, 80]
    assert sp.resolve("risk_bands.login_backoff_s").value == \
        [0, 90, 300, 900, 1800, 3600, 7200]


def test_backoff_reads_config():
    sp.set_config({"crawler": {"risk": {"login_backoff_s": [0, 10, 20]}}})
    from core.riskscore import LoginLedger
    led = LoginLedger("/tmp/_r1063_ll.json")
    assert led.backoff_s("ctrip") == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"; python -m pytest tests/test_r1063_risk_params_equivalent.py -q`
Expected: FAIL — `resolve("risk_bands.watch")` 抛 `KeyError`（该 pid 还没登记）

- [ ] **Step 3: 实现**

`risk_bands` 策略补齐 5 个 `Param`（`risk_bands.watch/slow/pause/human` +
`risk_bands.login_backoff_s`，`kind="json"` 表示列表）；`core/riskscore.py` 的
`_THRESHOLD` 改成函数 `_levels()` 返回 `((80,"human"),(65,"pause"),(45,"slow"),(25,"watch"))`
按五个 pid 组装（顺序仍按分数降序，短路语义不变）；`LoginLedger.backoff_s()`
改读列表并按 `streak` 索引、超界取末元素。

- [ ] **Step 4: 跑测试确认通过**

Run: `... pytest tests/test_r911_web_stealth_human_risk.py tests/test_r1063_risk_params_equivalent.py -q`
Expected: 全绿

- [ ] **Step 5: 提交**

```bash
git add core/riskscore.py core/strategy_contract.py tests/test_r1063_risk_params_equivalent.py
git commit -m "refactor(r1063): 风险阈值与登录退避阶梯参数化"
```

---

### Task 5: `decide()` 出决策明细 + 人工停手最先生效

**Files:**
- Modify: `core/policy.py`、`core/strategy_contract.py`（新增 `halt_now` 策略）
- Test: `tests/test_r1063_strategy_interrupt.py`（前半）

**Interfaces:**
- Produces:
  - `ChannelPolicy.decisions: list[dict]`，每项 `{"pid": str, "value": object, "source": str, "why": str}`；`as_dict()` 增 `"decisions"` 键
  - `core/policy.py::read_halt(profile_dir: str) -> dict`，返回 `{plat: {"until": float, "note": str}}`；带 mtime 缓存
  - `core/policy.py::set_halt(profile_dir: str, plat: str, minutes: int, note: str = "") -> dict`
  - `core/policy.py::clear_halt(profile_dir: str, plat: str) -> bool`
  - `PolicyEngine.reset_auto() -> None`（只清 `policy_state.json` 里的 blocked/余温，**不碰** halt）
  - 落盘文件 `user_data/<profile>/strategy_halt.json`

- [ ] **Step 1: 写失败测试**

```python
def test_halt_beats_state_machine(tmp_path):
    from core.policy import PolicyEngine, set_halt
    eng = PolicyEngine({}, repo_root=str(tmp_path), profile="ctrip")
    set_halt(eng.base_dir, "ctrip", 5, "人工核查中")
    p = eng.decide("ctrip", two_way=True)
    assert p.allow is False and p.state == "blocked"
    assert any("人工停手" in r for r in p.reasons)


def test_halt_expires_by_itself(tmp_path):
    from core.policy import PolicyEngine, set_halt
    eng = PolicyEngine({}, repo_root=str(tmp_path), profile="ctrip")
    set_halt(eng.base_dir, "ctrip", 0, "一秒后失效")   # minutes=0 → 立即过期
    assert eng.decide("ctrip", two_way=True).allow is True


def test_reset_does_not_clear_halt(tmp_path):
    """「解除自动熔断」与「恢复人工停手」是两件事。"""
    from core.policy import PolicyEngine, set_halt, read_halt
    eng = PolicyEngine({}, repo_root=str(tmp_path), profile="ctrip")
    set_halt(eng.base_dir, "ctrip", 30, "人工")
    eng.reset_auto()   # 新增：只清 policy_state 里的 blocked/余温
    assert "ctrip" in read_halt(eng.base_dir)


def test_decisions_expose_source_so_ui_can_say_who_decided(tmp_path):
    from core.policy import PolicyEngine
    from core import strategy_params as sp
    sp.set_config({"crawler": {"policy": {"pace": {"watch": 2.0}}}})
    p = PolicyEngine({}, repo_root=str(tmp_path), profile="x").decide(
        "ctrip", two_way=True)
    d = {x["pid"]: x for x in p.decisions}
    assert d["pace_factor.healthy"]["source"] in ("default", "global")
```

- [ ] **Step 2: 跑确认失败** → Step 3: 实现（`decide()` 第一段插 halt 判定；每个被读参数记录 `Resolved` 进 `decisions`；新增 `reset_auto()`）→ Step 4: 跑 → Step 5: commit `feat(r1063): 决策明细带来源 + 人工停手最先生效`

---

### Task 6: 停手/恢复接口与台账第三族

**Files:**
- Modify: `webui.py`（新增 `/api/strategy/halt`、`/api/strategy/resume`、`/api/round/abort`）、`core/storage.py`（SQL 分界）
- Test: `tests/test_r1063_strategy_ledger_class.py`

**Interfaces:**
- Consumes: `core.policy.set_halt/clear_halt`、`core.storage.PriceStorage.save_intervention`
- Produces: 三个路由；`save_intervention(plat, "strategy_halt", ok=True, scope="<plat>", before=..., after=..., note="[<sid>] ...")`

- [ ] **Step 1: 写失败测试**

```python
def test_strategy_actions_do_not_pollute_manual_intervention_effect(tmp_path):
    from core.storage import PriceStorage
    ps = PriceStorage(str(tmp_path / "t.db"))
    ps.save_intervention("ctrip", "probe", ok=True, rows=5)
    ps.save_intervention("ctrip", "strategy_toggle", ok=True,
                         before="on", after="off", note="[breaker_switch] 关")
    eff = ps.intervention_effect("ctrip", 24)
    assert eff.get("action") == "probe", "策略变更顶掉了人工干预分界"


def test_strategy_actions_are_excluded_from_success_rate(tmp_path):
    from core.storage import PriceStorage
    ps = PriceStorage(str(tmp_path / "t.db"))
    ps.save_intervention("ctrip", "warmup", ok=True)
    for _ in range(5):
        ps.save_intervention("ctrip", "strategy_set", ok=False)
    rate = ps.intervention_success_rate()
    rows = {r["action"]: r for r in rate}
    assert "strategy_set" not in rows


def test_halt_route_is_wired_and_ledgered():
    import io, os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    w = io.open(os.path.join(root, "webui.py"), encoding="utf-8").read()
    assert '"/api/strategy/halt"' in w and '"/api/strategy/resume"' in w
    assert '"strategy_halt"' in w
    assert '"/api/round/abort"' in w
```

- [ ] **Step 2: 跑确认失败** → Step 3: 实现（`intervention_effect` 与 `intervention_success_rate` 的 WHERE 各加 `AND substr(action,1,9) <> 'strategy_'`；三路由；`/api/round/abort` 复用 `rt["_round_gen"]` 递增）→ Step 4: 跑（3 passed）+ 既有 `test_r506*` 绿 → Step 5: commit `feat(r1063): 停手/恢复/中断接口 + 台账第三族分界`

---

### Task 7: 链路闸门与按 `(渠道, 链路)` 记账的令牌桶/熔断

**Files:**
- Modify: `core/pacing.py`（`TokenBucket`、`ChannelBreaker`、新增 `gate_path`）
- Test: `tests/test_r1063_path_gate.py`

**Interfaces:**
- Produces:
  - `Pacing.gate_path(plat: str, dim: str, path: str) -> tuple[bool, float, str]`（`allow, wait_s, why`）
  - `TokenBucket` 的键从 `plat` 变 `plat|path`（`record`/`wait_hint` 增可选 `path=""`，缺省等于旧行为）
  - `ChannelBreaker.trip/allow/reset` 增可选 `path=""`，键 `plat` 或 `plat|path`

- [ ] **Step 1: 写失败测试**

```python
def test_path_gate_denies_only_the_named_path():
    from core.pacing import Pacing
    from core import strategy_params as sp
    sp.set_config({"crawler": {"strategy_overrides": {
        "tongcheng/intl/PC": {"path_fallback.enabled": False}}}})
    pac = Pacing({"crawler": {"rate": {"min_gap_s": 0, "per_minute": 0}}})
    ok, wait, why = pac.gate_path("tongcheng", "intl", "PC")
    assert ok is False and "策略" in why
    ok2, _, _ = pac.gate_path("tongcheng", "intl", "H5")
    assert ok2 is True, "禁用 PC 不许连坐 H5"


def test_per_path_token_bucket_does_not_block_the_other_path():
    from core.pacing import TokenBucket
    tb = TokenBucket(min_gap_s=5, per_minute=0)
    tb.record("ctrip", path="PC")
    assert tb.wait_hint("ctrip", path="PC") > 0
    assert tb.wait_hint("ctrip", path="H5") == 0


def test_snapshot_still_aggregates_per_channel():
    """兼容：快照按渠道聚合，前端与既有门禁不受链路键影响。"""
    from core.pacing import Pacing
    pac = Pacing({"crawler": {"rate": {"min_gap_s": 0, "per_minute": 0}}})
    pac.record("ctrip", path="PC")
    assert "ctrip" in pac.snapshot()["channels"]
```

- [ ] **Step 2: 跑确认失败** → Step 3: 实现（`gate_path` 读 `path_fallback.enabled` 与 `rate_min_gap`/`rate_per_minute` 的 path 覆盖；禁用的通路一律 `("paced")` 记账；桶按复合键懒建、`snapshot()` 仍按渠道聚合输出以保兼容）→ Step 4: 跑 + 既有 `test_r420*`/`test_r380*` 绿 → Step 5: commit `feat(r1063): 链路闸门 + 按渠道×链路的限速与冷却键`

---

### Task 8: 浏览器五家接入链路闸门

**Files:**
- Modify: `crawlers/base.py`（新增 `BaseCrawler.path_gate(path, dim="") -> bool` 包装：调 `pacing.gate_path` 并按需 sleep/记 paced）、`crawlers/fliggy.py:212-301`、`crawlers/qunar.py:558`、`crawlers/ctrip.py`、`crawlers/tongcheng.py`、`crawlers/tuniu.py`（各自 PC/H5/日历分支入口）
- Test: `tests/test_r1063_browser_path_gate.py`

**Interfaces:** Consumes `Pacing.gate_path`；Produces `path_gate(path, dim="") -> bool`（False 时调用点直接跳过该通路，**不 return 整个查询**）

- [ ] **Step 1: 写失败测试**（源码锚点式，逐家断言「分支入口处先问闸门」）

```python
def test_each_browser_crawler_consults_the_path_gate_before_using_a_path():
    import io, os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for fn in ("fliggy.py", "qunar.py", "ctrip.py", "tongcheng.py", "tuniu.py"):
        body = io.open(os.path.join(root, "crawlers", fn), encoding="utf-8").read()
        assert "path_gate(" in body, "%s 没有问链路闸门" % fn
    base = io.open(os.path.join(root, "crawlers", "base.py"),
                   encoding="utf-8").read()
    assert 'path_note(path, "paced"' in base, "被停用的通路没记 paced（会误伤整渠道）"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `... pytest tests/test_r1063_browser_path_gate.py -q` → FAIL（五家都没 `path_gate(`）

- [ ] **Step 3: 实现**

`crawlers/base.py` 新增：

```python
def path_gate(self, path: str, dim: str = "") -> bool
```

内部取 `self._pacing`（已有节流上下文，没有则从 `self.config` 构造一次的
`Pacing`），调 `gate_path(self.name, dim, path)`；`allow=False` 时
`self.path_note(path, "paced", detail="通道被策略停用：" + why)` 并返回 False；
`wait_s > 0` 时睡（**必须封顶**，取 `min(wait_s, 15)`，符合铁律 I6）。

五家接入点（各 1–3 处，都在**用这条通路之前**）：
`fliggy.py`（`fetch()` 的 PC 段与 `_h5_fallback()` 入口、日历分支）、
`qunar.py`（`fetch()` 的 PC 段、H5 段、日历）、`ctrip.py`/`tongcheng.py`/`tuniu.py`
（各自的 PC/H5/日历/往返分支入口）。被拒时只跳过**这条通路**，不 `return` 整个查询。

- [ ] **Step 4: 跑测试确认通过**

Run: `... pytest tests/test_r1063_browser_path_gate.py tests/test_*fliggy* tests/test_*qunar* -q` → 全绿

- [ ] **Step 5: 提交**

```bash
git add crawlers/base.py crawlers/fliggy.py crawlers/qunar.py \
        crawlers/ctrip.py crawlers/tongcheng.py crawlers/tuniu.py \
        tests/test_r1063_browser_path_gate.py
git commit -m "feat(r1063): 浏览器五家接入链路闸门"
```

---

### Task 9: App 五家接入链路闸门

**Files:** Modify: `crawlers/app_base.py`（`AppCrawler.path_gate` 同构）、`app_ctrip.py`、`app_qunar.py`、`app_fliggy.py`、`app_tongcheng.py`、`app_zhixing.py`（`app-login` / `app-list` / `app-calendar` / `往返` / `low-fare` 五个阶段入口）
**Test:** `tests/test_r1063_app_path_gate.py`

- [ ] **Step 1: 写失败测试**

```python
def test_app_channels_gate_the_main_stages_but_not_the_sub_steps():
    import io, os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for fn in ("app_ctrip.py", "app_qunar.py", "app_fliggy.py",
               "app_tongcheng.py", "app_zhixing.py"):
        body = io.open(os.path.join(root, "crawlers", fn),
                       encoding="utf-8").read()
        assert "path_gate(" in body, "%s 没问链路闸门" % fn
    base = io.open(os.path.join(root, "crawlers", "app_base.py"),
                   encoding="utf-8").read()
    assert "细段属单次交互内部" in base, "细段不接闸门的理由没写进源码"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `... pytest tests/test_r1063_app_path_gate.py -q`  → FAIL

- [ ] **Step 3: 实现**

`AppCrawler.path_gate(path, dim="")` 与 `BaseCrawler` 同构（共用
`Pacing.gate_path`，App 渠道的 `dim` 传 `detail`/`calendar`/`round_trip`/`low_fare`）。
五家在 `app-login`、列表（`app-list`/`app-route` 之后取列表那一步）、
`app-calendar`、`往返`、`low-fare` 五个阶段入口各问一次；`app-city`/`app-date`/
`app-form`/`app-search` 等细段**不问**，并在 `app_base.py` 注释写明理由
（停细段等于停整条链路，矩阵对它们记 `na`）。

- [ ] **Step 4: 跑测试确认通过**

Run: `... pytest tests/test_r1063_app_path_gate.py tests/test_app_crawler_base.py -q` → 全绿

- [ ] **Step 5: 提交**

```bash
git add crawlers/app_base.py crawlers/app_ctrip.py crawlers/app_qunar.py \
        crawlers/app_fliggy.py crawlers/app_tongcheng.py crawlers/app_zhixing.py \
        tests/test_r1063_app_path_gate.py
git commit -m "feat(r1063): App 五家接入链路闸门"
```

---

### Task 10: `main.py` 闸门接受维度/链路，且禁用通路不连坐

**Files:** Modify: `main.py:2593-2820`（`_timed_fetch` 增 `dim` 参数、调用点传入；`pac.observe` 前过滤被禁用通路的证据）
**Test:** `tests/test_r1063_main_gate_dimension.py`

**Interfaces:** Consumes `Pacing.gate_path`；Produces `_timed_fetch(c, fc_, tc_, d_, th_min=None, gen=None, chans=None, dim="detail")`

- [ ] **Step 1: 写失败测试**

```python
def test_observe_ignores_paced_paths_when_tripping_breaker():
    """某条通路被策略停用（记 paced）不得把整渠道熔断（Review Focus 2）。"""
    import io, os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    body = io.open(os.path.join(root, "main.py"), encoding="utf-8").read()
    seg = body[body.index("_kind, _cd = pac.observe("):][:600]
    assert "paced" in seg, "observe 前没过滤 paced 证据"
```

- [ ] **Step 2: 跑确认失败** → Step 3: 实现（`_timed_fetch` 增 `dim`；`dim` 由调用点按「列表/日历/往返/多程」传入；`observe` 的 `statuses` 列表先剔除 `status == "paced"` 的条目并留一条 INFO）→ Step 4: 跑 + `tests/test_r193*`/轮次相关绿 → Step 5: commit `feat(r1063): 闸门接维度/链路 + 停用通路不连坐熔断`

---

### Task 11: 特价雷达接闸门与预算

**Files:** Modify: `core/special_radar.py`（`_ctrip_deals`/`_fliggy_deals`/`_tuniu_deals`/`_tongcheng_deals` 入口先问闸门；每源加 `budget_s`）
**Test:** `tests/test_r1063_radar_path_gate.py`

- [ ] **Step 1: 写失败测试**

```python
def test_radar_sources_ask_the_gate_and_read_a_budget():
    import io, os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    body = io.open(os.path.join(root, "core", "special_radar.py"),
                   encoding="utf-8").read()
    for fn in ("_ctrip_deals", "_fliggy_deals", "_tuniu_deals",
               "_tongcheng_deals"):
        seg = body[body.index("def %s(" % fn):][:1200]
        assert "gate_path(" in seg, "%s 没问链路闸门" % fn
    assert "budget.value" in body
```

- [ ] **Step 2: 跑测试确认失败**

Run: `... pytest tests/test_r1063_radar_path_gate.py -q` → FAIL

- [ ] **Step 3: 实现**

四个源函数入口先 `gate_path(plat, dim, path)`；被禁用时返回
`_status("unsupported", "通道被策略停用")`（**不许**伪装成 0 行/无票——
`YIELD…:3802-3803`）。每源预算读 `strategy_params.resolve("budget.value", plat=...)`，
超预算按现有 `elapsed` 判定提前收工并 `_status("timeout", "预算耗尽")`。

- [ ] **Step 4: 跑测试确认通过**

Run: `... pytest tests/test_r1063_radar_path_gate.py -q` + `grep -l special_radar tests/*.py` 命中的文件全跑 → 全绿

- [ ] **Step 5: 提交**

```bash
git add core/special_radar.py tests/test_r1063_radar_path_gate.py
git commit -m "feat(r1063): 特价雷达按源接闸门与预算"
```

---

### Task 11b: 矩阵扩到十五轴（可可视化 / 可调整 / 可清晰 / 可意图理解 / 可统计）

**Files:**
- Modify: `core/strategy_contract.py`（`AXES` 10→15、五个新探针、`Strategy` 增 `label/intent/effect` 三个可选字段）
- Test: `tests/test_r1063_strategy_axes15.py`

**Interfaces:**
- Consumes: 既有 `audit()` / `Row` / `_Ctx`
- Produces: `AXES` 15 条（新增 `("visualizable","可可视化")`、`("adjustable","可调整")`、`("clear","可清晰")`、`("intent","可意图理解")`、`("stats","可统计")`）；`Strategy.label: str = ""`、`Strategy.intent: str = ""`、`Strategy.effect: str = ""`

- [ ] **Step 1: 写失败测试**

```python
def test_axes_are_fifteen_and_include_the_objective_extension():
    from core.strategy_contract import AXES, AXIS_IDS
    assert len(AXES) == 15
    for a in ("visualizable", "adjustable", "clear", "intent", "stats"):
        assert a in AXIS_IDS, "缺轴 " + a


def test_every_strategy_has_a_short_clear_label():
    """可清晰：≤20 字的中文短句，不许露裸 id。"""
    from core.strategy_contract import STRATEGIES
    for s in STRATEGIES:
        assert 0 < len(s.label) <= 20, (s.id, s.label)
        assert s.id not in s.label, (s.id, s.label)
        assert all("\u4e00" <= ch <= "\u9fff" or ch in "·（）0123456789/" for ch in s.label), (s.id, s.label)


def test_every_strategy_states_intent_and_effect():
    from core.strategy_contract import STRATEGIES
    for s in STRATEGIES:
        assert s.intent and s.effect, s.id
        assert len(s.intent) <= 40 and len(s.effect) <= 40, s.id


def test_stats_axis_is_evaluated_not_dropped():
    from core.strategy_contract import audit
    rows = [r for r in audit() if r.axis == "stats"]
    assert rows, "stats 轴没求值"
    assert not [r for r in rows if r.state == "y" and not r.note.strip()], \
        "y 必须有可数的口径说明"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `... pytest tests/test_r1063_strategy_axes15.py -q` → FAIL（`len(AXES) == 10`、`Strategy` 无 `label`）

- [ ] **Step 3: 实现**

五个探针的判据照规格 §4.1，全部读真实登记点：
- `visualizable`：`webui.py` 里有渲染器消费该 `sid`（`data-strategy` 模板由目录驱动 → 判据是「渲染器存在且从目录取 id」，外加 `uitest` 用例名提到该族）；
- `adjustable`：`/api/config` 的 `glb` 侧有该策略某个 pid 的键 + `GLB_RANGES`/`_DYN` 有边界；
- `clear`：`Strategy.label` 非空、≤20 字、不含裸 id；
- `intent`：`Strategy.intent` 与 `effect` 非空且 ≤40 字（并在 T13 断言两者真渲染）；
- `stats`：`sid` 以 `strategy:` 前缀出现在 `core/storage.py` 的统计口径里，或该策略为 `auto_default=False`（只建议）→ `na` + 理由。

`STRATEGIES` 的 28 条逐条补 `label/intent/effect`（作者按附录 B 的「中文名 + 族」写，
不许照抄 `cn`）。此时 `--strict` 仍会红（缺 UI），属预期（Ruling P5）。

- [ ] **Step 4: 跑测试确认通过** → 4 passed；并跑 `tests/test_r1063_strategy_contract.py` 确认 T1 门禁仍绿

- [ ] **Step 5: 提交**

```bash
git add core/strategy_contract.py tests/test_r1063_strategy_axes15.py
git commit -m "feat(r1063): 矩阵扩到十五轴并给每条策略补清晰标签与意图说明"
```

---

### Task 12: `GET /api/strategy` + 配置页「策略控制」重构（目录驱动）

**Files:** Modify: `webui.py`（新路由；`panel-pacing` 渲染器改目录驱动；`GLB_RANGES`/`GLB_RANGES_DYN` 登记新键；`/api/config` 的 `glb` 增 `strategy_overrides` 读写；分区标题改「策略控制」且 `id` 仍为 `pacing`）
**Test:** `tests/test_r1063_strategy_panel.py`（T12b 落地，已入库）

**Interfaces:** Consumes `strategy_contract.STRATEGIES`、`strategy_params.effective_table`、`resolve`、`clamp`；Produces `GET /api/strategy -> {"strategies": [...], "matrix": [...], "overrides": {...}}`

- [ ] **Step 1: 写失败测试**

```python
def test_panel_is_directory_driven_and_has_no_second_declaration():
    import io, os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    w = io.open(os.path.join(root, "webui.py"), encoding="utf-8").read()
    assert "/api/strategy" in w
    assert "data-strategy" in w
    # 不许在模板里逐条写 28 个策略 id
    assert w.count('data-strategy="rate_per_minute"') == 0


def test_new_numeric_keys_are_registered_for_range_check():
    import io, os, re
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    w = io.open(os.path.join(root, "webui.py"), encoding="utf-8").read()
    i = w.index("const GLB_RANGES=[")
    seg = w[i:w.index("function glbRangeOf(", i)]
    for fid in ("glbPaceWatch", "glbPaceDegraded", "glbStickyWatch",
                "glbBlockHuman", "glbRiskPause"):
        assert re.search(r"id:'%s'" % fid, seg), "%s 没进 GLB_RANGES" % fid


def test_partition_title_and_deeplink_stay_working():
    import io, os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    w = io.open(os.path.join(root, "webui.py"), encoding="utf-8").read()
    assert "let CFGPANEL='pacing'" in w, "深链分区 id 被改掉"
    assert "function cfgGoThrottle(" in w, "健康卡直达入口丢了"
    assert "<span class=\"zh\">策略控制</span>" in w
    assert "<span class=\"zh\">渠道节流</span>" not in w, "旧标题仍在"


def test_full_fifteen_axis_matrix_is_green_for_all_channels():
    """十五轴全绿在这一步才可能成立：可观测/可干预/可区分都要等界面与接口存在。"""
    import subprocess
    import sys
    from core.channels import APP_CHANNELS, BROWSER_CHANNELS
    from core import strategy_contract as sc
    plats = tuple(BROWSER_CHANNELS) + tuple(APP_CHANNELS)
    bad = [r for r in sc.audit() if r.plat in plats and r.state == "n"]
    assert not bad, [(r.sid, r.plat, r.axis, r.note) for r in bad][:8]
    out = subprocess.run([sys.executable, "-m", "core.strategy_contract",
                          "--strict"], cwd=root, capture_output=True,   # 建议：路径参数由调用方给
                         text=True, encoding="utf-8")
    assert out.returncode == 0, out.stdout[-1200:] + out.stderr[-600:]
```

- [ ] **Step 2: 跑确认失败**
- [ ] **Step 3: 实现**：渲染器从 `/api/strategy` 取 `strategies`，每行输出
  `<div class="srow" data-strategy="<id>" data-family="<族>">` + 触发 chip + 粒度 select
  + 值控件（`data-pid`）+ 来源徽标 + 开/关 + 「停 N 分钟」+ 建议（带动作按钮）。
  值控件 `onchange` 写 `GLB.Strategy` 或 `GLB.strategy_overrides`，**保存仍走 `saveCfg()` 整表 POST**。
  `clamp()` 返回的说明用既有 `glbClamp` 同款文案当场回写。
- [ ] **Step 4: 跑 + 既有配置页门禁（`test_r342*`/`test_r606*`/`test_r638*`/`test_goal_requirements::test_goal_c`）绿**
- [ ] **Step 5: commit** `feat(r1063): 策略控制分区（目录驱动）+ /api/strategy`

---

### Task 12c: 把十五轴矩阵补到零缺口（可开启 / 可干预 / 可建议 / 可调整）

**Files:**
- Modify: `core/strategy_contract.py`（28 条补 `enabled` 参数、补 `api`、补 `advice`）
- Create: `core/strategy_advice.py`（按族给建议，返回动作码 + 中文短句）
- Modify: `core/policy.py` / `core/pacing.py` / `core/riskscore.py` / `core/special_radar.py`（让 `enabled` 真的被读到）
- Modify: `webui.py`（把 8 条未绑定的参数接到既有控件或新控件；`GLB_RANGES` 登记）
- Test: `tests/test_r1063_strategy_axes_closure.py`

**Interfaces:**
- Consumes: `STRATEGIES` / `Param` / `audit()`；`strategy_params.resolve`；既有路由 `/api/strategy/halt|resume`、`/api/pacing/reset`、`/api/channel/{warmup,probe,selfcheck}`、`/api/run`、`/api/challenge/open`、`/api/probe/cancel`
- Produces: 每条策略一个 `<sid>.enabled` bool 参数（`crawler.strategy_enabled.<sid>`，默认 `True`，缺省即旧行为）；`core.strategy_advice.advise(sid, ctx)` → `{"action": str, "text": str}`（`action` 属于 `ACTIONS`，`text` ≤40 字中文）；`python -m core.strategy_contract --strict` **退出码 0**

**现状（`d5fa72c` 实测，62 格 `n`）**

| 轴 | 缺口策略数 | 缺什么 |
|---|---|---|
| `advisable` | 21 | 没有建议器，只出数字不出动作 |
| `toggleable` | 19 | 没有 `enabled` 开关，只能调不能关 |
| `intervenable` | 14 | 没声明干预路由 |
| `adjustable` | 8 | 参数没绑到界面控件（`budget` / `block_window` / `breaker_*` / `pace_factor` / `risk_bands` / `warmup` / `path_fallback`） |

- [ ] **Step 1: 写失败测试**

```python
# tests/test_r1063_strategy_axes_closure.py
def test_strict_matrix_has_zero_defects():
    import os, subprocess, sys
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = subprocess.run([sys.executable, "-m", "core.strategy_contract", "--strict"],
                         cwd=root, capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0, out.stdout[-1500:] + out.stderr[-500:]


def test_every_strategy_can_be_switched_off_and_defaults_to_on():
    from core.strategy_contract import STRATEGIES
    from core import strategy_params as sp
    sp.invalidate()
    for s in STRATEGIES:
        pid = s.id + ".enabled"
        assert pid in sp.PARAMS, s.id
        assert sp.resolve(pid).value is True, s.id


def test_switching_a_strategy_off_actually_changes_behaviour():
    from core import strategy_params as sp
    from core.policy import PolicyEngine
    sp.set_config({"crawler": {"policy": {"pace": {"watch": 2.0}},
                               "strategy_enabled": {"pace_factor": False}}})
    p = PolicyEngine({}, repo_root=".", profile="zz_12c").decide("ctrip", two_way=True)
    assert p.pace_factor == 1.0


def test_every_strategy_has_a_real_advice_action():
    from core.strategy_contract import STRATEGIES
    from core import strategy_advice as sa
    for s in STRATEGIES:
        got = sa.advise(s.id, {})
        assert set(got) >= {"action", "text"}, s.id
        assert got["action"] in sa.ACTIONS, (s.id, got)
        assert 0 < len(got["text"]) <= 40, s.id


def test_declared_intervention_routes_exist_in_the_console():
    import io, os
    from core.strategy_contract import STRATEGIES
    w = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "webui.py"), encoding="utf-8").read()
    for s in STRATEGIES:
        for r in s.api:
            assert '"%s"' % r in w, (s.id, r)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `... pytest tests/test_r1063_strategy_axes_closure.py -q`
Expected: FAIL（`--strict` 退 1、`<sid>.enabled` 未登记、`core.strategy_advice` 不存在）

- [ ] **Step 3: 实现**

1. **可开启**：给 28 条都补 `Param("<sid>.enabled", "crawler.strategy_enabled.<sid>", "bool", True)`（已有 bool 开关的策略复用，不重复造）。每个决策点读它：关掉 = 该策略「不生效」的语义（`pace_factor` 关 → 1.0；`breaker_*` 关 → 不冷却；`ttl_tier` 关 → 不分层；`rate_*` 关 → 不限速），**默认 True 保持今天的行为**。
2. **可干预**：给 14 条声明**真实存在**的入口（`api=(...)`），审计会逐条核对 `webui.py`；不许声明不存在的路由。
3. **可建议**：新建 `core/strategy_advice.py`：`ACTIONS` 常量 + `advise(sid, ctx)` 按族返回 `{action, text}`；`text` 中文短句 ≤40 字，`action` 必须对应既有可执行入口。`STRATEGIES[i].advice` 指向它。
4. **可调整**：把 8 条未绑定的参数接到界面（`budget.fetch_s` 走既有 Android 预算控件；`block_window`/`risk_bands`/`pace_factor` 在策略行内渲染；`breaker_*`/`warmup`/`path_fallback` 同理），控件 id 登记进 `GLB_RANGES`/`GLB_RANGES_DYN`。结构上不该上界面的（只读影子）在矩阵里记 `na` 并写明理由，不许假装可调。

- [ ] **Step 4: 跑测试确认通过**

Run: `... pytest tests/test_r1063_strategy_axes_closure.py tests/test_r1063_strategy_contract.py tests/test_r1063_strategy_axes15.py tests/test_r1063_strategy_panel.py tests/test_r1063_strategy_api.py tests/test_r913_policy_engine.py tests/test_r1063_policy_params_equivalent.py -q`
Expected: 全绿；`python -m core.strategy_contract --strict` 退出 0。

- [ ] **Step 5: 提交**

```bash
git add core/strategy_contract.py core/strategy_advice.py core/policy.py core/pacing.py \
        core/riskscore.py core/special_radar.py webui.py tests/test_r1063_strategy_axes_closure.py
git commit -m "feat(r1063): 补齐十五轴——可开启/可干预/可建议/可调整全部落地"
```

---

### Task 15: 成功率保护（降频）真正按维度独立

**背景**：`health_penalty` 现在只到渠道级——`core/storage.py::path_stats()` 只出 `platform × 入口 × 域`，`core/pacing.py::set_health(plat, rate, attempts)` 也只落渠道一个惩罚值，`plan_query` 用它拉长整家渠道的 TTL。目标原话要求「每个维度每个链路都可独立调整」，所以降频必须能按维度（国内/国际/日历/明细/往返/多程/低价）分别生效。

**Files:**
- Modify: `core/storage.py`（`path_stats` 增维度级节点）
- Modify: `core/pacing.py`（`set_health`/`plan_query`/`_rate_limits` 认 `dim`）
- Modify: `main.py`（把维度级读数喂给 `set_health`，把 `dim` 传给 `plan_query`）
- Modify: `core/strategy_contract.py`（`health_penalty.scope` 补 `dimension`，`intent`/`effect` 照实改）
- Test: `tests/test_r1063_health_by_dimension.py`

**Interfaces:**
- Consumes: `DIMENSIONS`（`core/channels.py`）、`is_intl_route`、既有 `path_stats` 节点形状
- Produces:
  - `PriceStorage.path_stats(hours=24)` 每个 platform 节点新增 `dims: {dim: node}`，其中 dim ∈ `DIMENSIONS`，节点与既有 `scopes` 子节点同形（`attempts/ok/rate/query_attempts/query_ok/query_rate/...`）；
  - `Pacing.set_health(plat, rate, attempts, dim="")`：`dim=""` 写渠道级（今天的行为逐位不变），非空写该维度；两条都落 `self._health[("plat", dim)]` 形状的键（渠道级用 `(plat, "")`）；
  - `Pacing.plan_query(plat, key, threshold=0, days_ahead=None, dim="")`：该维度样本 ≥ `health_min_samples` 时用维度级 penalty，否则回落渠道级（渠道级也没有则 1.0）；
  - `Pacing.health_penalty_on(plat, dim="", path="")` 已是参数化的（T12c 起），本任务只需让 `set_health`/`plan_query` 真的按 `dim` 取值。

**维度归属口径（写死在代码里并注释）**：账本行只有 `entry_path` 与航线，没有维度列，所以按既有约定映射——
`日历`/`窗历` → `calendar`；`往返`/`TRIP` → `round_trip`；`多程` → `multi_city`；`low-fare` → `low_fare`；
其余（`PC`/`H5`/`H5/API`/`API`/`QUERY`/`航班明细`/`app-*`）→ `detail`。
**不许**为了分类去改抓取口径或新增列；映射表就是单一事实源，放在 `core/storage.py` 里一个 `_DIM_OF_PATH` 常量 + 一个 `dim_of_path(path)` 函数，注释写清「账本无维度列，这是唯一可复现的映射」。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_r1063_health_by_dimension.py
# -*- coding: utf-8 -*-
"""r1063 T15：成功率保护按维度独立——日历烂不等于明细烂。"""
import os
import tempfile

from core.storage import PriceStorage


def _seed(ps):
    """造一组账：calidar 全失败、明细全成功（同一渠道）。"""
    for i in range(6):
        ps.note_path("ctrip", "日历", "error", attempt_id="cal-%d" % i)
        ps.note_path("ctrip", "PC", "ok", rows=3, attempt_id="det-%d" % i)


def test_path_stats_exposes_dimension_nodes():
    d = tempfile.mkdtemp()
    ps = PriceStorage(os.path.join(d, "t.db"))
    ps.init_schema() if hasattr(ps, "init_schema") else None
    _seed(ps)
    node = ps.path_stats(24)["platforms"]["ctrip"]
    assert set(node["dims"]) >= {"calendar", "detail"}
    assert node["dims"]["calendar"]["attempts"] == 6
    assert node["dims"]["calendar"]["ok"] == 0
    assert node["dims"]["detail"]["ok"] == 6


def test_dimension_penalty_does_not_leak_to_other_dimensions():
    from core import strategy_params as sp
    from core.pacing import Pacing
    sp.set_config({})
    pac = Pacing({})
    pac.set_health("ctrip", 0.1, 10, dim="calendar")     # 日历烂
    pac.set_health("ctrip", 0.95, 10, dim="detail")      # 明细好
    cal = pac.plan_query("ctrip", ("SHA", "BJS", "2027-01-29"), dim="calendar")
    det = pac.plan_query("ctrip", ("SHA", "BJS", "2027-01-30"), dim="detail")
    assert cal[0] in ("slow", "skip"), cal
    assert det[0] == "fast", det


def test_channel_level_still_works_and_is_the_fallback():
    from core import strategy_params as sp
    from core.pacing import Pacing
    sp.set_config({})
    pac = Pacing({})
    pac.set_health("ctrip", 0.1, 10)                      # 渠道级烂
    # 该维度没有自己的样本 → 回落渠道级
    assert pac.plan_query("ctrip", ("SHA", "BJS", "2027-01-29"),
                          dim="detail")[0] in ("slow", "skip")


def test_dimension_mapping_is_single_source():
    from core.storage import dim_of_path
    assert dim_of_path("日历") == "calendar"
    assert dim_of_path("往返") == "round_trip"
    assert dim_of_path("多程") == "multi_city"
    assert dim_of_path("low-fare") == "low_fare"
    assert dim_of_path("PC") == "detail"
    assert dim_of_path("app-calendar") == "calendar"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `... pytest tests/test_r1063_health_by_dimension.py -q`
Expected: FAIL（`dims` 不存在 / `set_health` 不接受 `dim` / `plan_query` 不接受 `dim` / `dim_of_path` 不存在）

- [ ] **Step 3: 实现**

1. `core/storage.py`：加 `_DIM_OF_PATH` 映射与 `dim_of_path()`；`path_stats()` 在既有 `platforms`/`scopes` 之外再产 `dims`，节点形状与 `scopes` 子节点一致（复用同一 `new_node`/`bump` 逻辑，**不许复制一份统计代码**）；`query_*` 口径在维度内同样按「一次查询只要该维度有一条路径出数就算成功」。
2. `core/pacing.py`：`_health` 的键改成 `(plat, dim)`（`dim=""` 为渠道级）；`set_health(..., dim="")`；`plan_query(..., dim="")` 按「维度样本足 → 用维度；否则渠道级」取 penalty；`_rate_limits`/`gate_path` 若需要 penalty 也按同一口径取。
3. `main.py`：把 `_node["dims"]` 逐维度喂 `pac.set_health(_p, rate, n, dim=_d)`（样本门槛与渠道级同口径），并把 `plan_query` 的 `dim=` 传进去。
4. `core/strategy_contract.py`：`health_penalty.scope` 补 `dimension`；`intent`/`effect` 改成「按维度自动拉长 TTL」的如实描述。

- [ ] **Step 4: 跑测试确认通过**

Run: `... pytest tests/test_r1063_health_by_dimension.py tests/test_r1063_strategy_contract.py tests/test_r1063_strategy_axes_closure.py tests/test_r1063_strategy_axes15.py tests/test_r1063_strategy_panel.py tests/test_r1063_strategy_api.py tests/test_r1063_hot_reload.py tests/test_pacing.py tests/test_r420_pacing_panel_rebuild.py tests/test_r380_soft_budget.py -q`
Expected: 全绿；`python -m core.strategy_contract --strict` 退出 0。

- [ ] **Step 5: 提交**

```bash
git add core/storage.py core/pacing.py main.py core/strategy_contract.py tests/test_r1063_health_by_dimension.py
git commit -m "feat(r1063): 成功率保护按维度独立（path_stats 出维度级口径，plan_query 按维度取惩罚）"
```

---

### Task 13: 健康卡「策略条」

**Files:** Modify: `webui.py`（`#paceBox` 渲染：每渠道行后追加一行 chips；新增 `cfgGoStrategy(id)`）
**Test:** `tests/test_r1063_health_strategy_strip.py`（T13 落地，已入库）

- [ ] **Step 1: 写失败测试**

```python
def test_health_card_renders_a_strategy_strip_with_actions():
    import io, os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    w = io.open(os.path.join(root, "webui.py"), encoding="utf-8").read()
    assert "function paceStripHTML(" in w
    assert 'data-strip="' in w
    assert "function cfgGoStrategy(" in w
    # 停手/恢复必须复用同一套接口，不许另写一条
    assert "/api/strategy/halt" in w and "/api/strategy/resume" in w


def test_strip_chips_are_wechat_flat_and_speak_chinese_short():
    """微信级扁平化 + 可清晰：芯片长在既有家族里，文案是短句，不露裸 id。"""
    import io, os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    w = io.open(os.path.join(root, "webui.py"), encoding="utf-8").read()
    assert ".pchip{" in w, "芯片没自己的扁平样式"
    seg = w[w.index(".pchip{"):][:400]
    assert "background:var(--r-surface)" in seg or "var(--r-blue-soft)" in seg
    assert "border-radius:var(--pill)" in seg or "border-radius:12px" in seg
    assert "border:0" in seg.replace(" ", "") or "border:none" in seg
    # 芯片文案来自策略目录的 label（≤20 字），不是拼 id
    fn = w[w.index("function paceStripHTML("):][:1500]
    assert "s.label" in fn or "st.label" in fn, "芯片没消费目录的 label"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `... pytest tests/test_r1063_health_strategy_strip.py -q` → FAIL（该文件尚未创建，计划 T13 落地时建立）

- [ ] **Step 3: 实现**

`paceStripHTML(plat)` 从 `GET /api/strategy` 的该渠道生效表里只挑
「非默认」或「本渠道生效中」的项，最多 6 颗 chip，其余折进「更多…」；
每颗 chip `<button class="pchip" data-strip="<sid>">` 文案三种形态：
`自动降频中（来自全局）`、`人工停手 4 分钟`、`已停用（渠道覆盖）`。
点击 = 打开该策略行（`cfgGoStrategy(sid)` → `switchView('cfg')` +
`showCfgPanel('pacing')` + 滚动并高亮 `[data-strategy="<sid>"]`）。
停手按钮直接 `POST /api/strategy/halt`，在途改文案为「停手中…」再回读。

- [ ] **Step 4: 跑测试确认通过**

Run: `... pytest tests/test_r1063_health_strategy_strip.py tests/test_r977_channel_health_surface_unity.py tests/test_r999_health_selfcheck_baseline.py -q` → 全绿（该文件尚未创建，计划 T13 建立）

- [ ] **Step 5: 提交**

```bash
git add webui.py tests/test_r1063_health_strategy_strip.py   # 该文件尚未创建，计划 T13 建立
git commit -m "feat(r1063): 渠道健康策略条与一键停手"
```

---

### Task 14: 热链路收口 + uitest + 全量回归 + 文档

**Files:** Modify: `main.py:3486`（`reload_config()` 里 `strategy_params.set_config(cfg)` + 日志一行）、`docs/uitest.py`（策略行渲染/改值/保存/回读、停手/恢复）、`docs/EXECUTION_SPEC_LATEST.md`（新增小节写七条裁决与本轮口径）
**Test:** `tests/test_r1063_hot_reload.py`（T14 落地，已入库）

- [ ] **Step 1: 写失败测试**

```python
def test_reload_config_feeds_the_param_provider():
    import io, os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    body = io.open(os.path.join(root, "main.py"), encoding="utf-8").read()
    seg = body[body.index("def reload_config():"):][:2500]
    assert "strategy_params.set_config(" in seg, "热重载没喂参数提供者"


def test_saving_config_changes_next_decision_without_restart(tmp_path):
    from core import strategy_params as sp
    from core.policy import PolicyEngine
    sp.set_config({})
    eng = PolicyEngine({}, repo_root=str(tmp_path), profile="hot")
    assert eng.decide("ctrip", two_way=True).pace_factor == 1.0
    sp.set_config({"crawler": {"policy": {"pace": {"healthy": 1.3}}}})
    assert eng.decide("ctrip", two_way=True).pace_factor == 1.3
```

- [ ] **Step 2: 跑确认失败** → Step 3: 实现 + 补 uitest 用例 → Step 4:
  跑 `... pytest tests/ -q`（期望 ≥7180+新增，0 failed）与 `python docs/uitest.py`（零 pageerror）→ Step 5: commit `feat(r1063): 热链路收口 + uitest 与全量回归`

---

## Self-Review

**1. Spec coverage**：§1 缺口 G1→T3/T4；G2→T7–T11；G3→T5/T12/T13；G4→T5/T6；G5→T6；G6→T12/T13。§2 六层→各任务 docstring + T1/T2 分层；§2.1 十三条铁律→I1 落在 T7（禁用记 paced）、I7 落在 T12 钳制、I9 落在 T13（关闭清残留）、I12 落在 T6（before/after 入账）；§3 归位表→T3–T13 逐行；§4 目录→T1；§5 参数模型→T2；§6 接口→T6/T12/T13；§7.2 七裁决→C1→T12、C2→T13、C3→T12、C7→T13、C4/C5/C6→T12/T14 文案；§8.1 热链路→T14；附录 B 28 条→T1。

**2. Step scan**：每个 Step 一件可核事；无「TBD / 适当校验 / 写测试」类空话。测试代码给到断言与确切数值，实现只给签名与判据表。

**3. Type consistency**：`Resolved(value, source, pid)`、`Row(sid, plat, axis, state, note)`、`Param(pid, cfg, kind, default, lo, hi)`、`Strategy(...)`、`gate_path(plat, dim, path) -> (allow, wait_s, why)`、`path_gate(path, dim="") -> bool` 全文一致；`decisions` 项键 `{pid, value, source, why}` 在 T5/T12/T13 三处一致。

**4. Review Focus 落点**：①配置键搬家 → T3/T4 等价门禁 + T14 热链路行为测试；②链路误伤整渠道 → T7 第 3 例 + T10 第 1 例；③halt 与状态机 → T5 前三例；④台账污染 → T6 前两例；⑤演示/无样本 → T12「来源徽标」与 T13「na 自述」文案断言。

**5. Proportion**：计划 ≈880 行 vs 规格 ≈490 行。超出部分几乎全是**可执行的测试断言**
（每个任务 3–5 个带确切数值的用例）与判据表；没有任何整段函数体——
实现者仍要自己写每个函数体。

## 落地状态

**已完成**（T14 收口，2026-11-06）：16 个任务全部落地，`python -m core.strategy_contract --strict`
退出 0（15 轴 × 10 家渠道 × 28 条策略零缺口），热链路已接线（`main.reload_config()`
与启动路径各喂一次 `strategy_params.set_config(cfg)`）。

已完成并入库的产物（下列路径均真实存在）：

- `core/strategy_contract.py`
- `core/strategy_params.py`
- `core/policy.py`
- `core/riskscore.py`
- `core/pacing.py`
- `core/storage.py`
- `core/special_radar.py`
- `core/yield_stats.py`
- `core/strategy_advice.py`
- `main.py`
- `webui.py`
- `crawlers/base.py`
- `crawlers/app_base.py`
- `tests/test_r1063_strategy_contract.py`
- `tests/test_r1063_strategy_params.py`
- `tests/test_r1063_policy_params_equivalent.py`
- `tests/test_r1063_risk_params_equivalent.py`
- `tests/test_r1063_strategy_interrupt.py`
- `tests/test_r1063_strategy_ledger_class.py`
- `tests/test_r1063_path_gate.py`
- `tests/test_r1063_browser_path_gate.py`
- `tests/test_r1063_app_path_gate.py`
- `tests/test_r1063_main_gate_dimension.py`
- `tests/test_r1063_radar_path_gate.py`
- `tests/test_r1063_strategy_axes15.py`
- `tests/test_r1063_strategy_axes_closure.py`
- `tests/test_r1063_strategy_api.py`
- `tests/test_r1063_strategy_panel.py`（12b 落地）
- `tests/test_r1063_health_strategy_strip.py`（13 落地）
- `tests/test_r1063_hot_reload.py`（14 落地）

界面证据：`docs/uitest.py` 第 50 段（策略行渲染 / 改值进 GLB / 保存回执 / 行值来自载荷 /
健康条芯片点按落到策略行 / 停手·恢复按钮走同一套接口 / 390·320 零横向溢出 / 零 pageerror）；
单段实跑 `UITEST_SECTIONS=50` 15/15 通过、零 pageerror。

执行台账（逐任务的复核结论与裁决）见 `.superpowers/sdd/2026-11-06-crawl-strategy-control-plane/progress.md`（该目录不入库）。
