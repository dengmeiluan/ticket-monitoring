# -*- coding: utf-8 -*-
"""策略参数的**唯一求值入口**：三级继承（全局 → 渠道 → 维度 → 链路）+ 来源标注。

为什么要有这个模块
------------------
`core/strategy_contract.py` 只说「这个参数叫什么、config 里是哪个键、默认值与
上下界是多少」；**它不回答「现在到底是多少」**。没有中间这一层时，每个消费方
（节流、闸门、风险分档、雷达、界面）都得自己
`cfg.get("schedule", {}).get("fast_ttl_min", 15)` 抄一遍：

* 抄的那一处一旦忘了读 `crawler.strategy_overrides`，界面上改了值不生效；
* 抄进实例属性（`self._pace = …`）后，`reload_config()` 只换 cfg、不重建对象，
  于是「热生效」名存实亡——这正是本仓库把「配了不生效」列为头号缺陷的原因；
* 谁抄谁就得自己判上下界，于是同一键在两处的夹取范围慢慢分叉。

所以参数**只在**这里求值，别的模块只调 `resolve()`。模块级单例装的是
`cfg` 的引用（不深拷贝）：`set_config()` 可以在任意时刻再调，下一次
`resolve()` 立刻按新值求值，不需要重建任何对象。`invalidate()` 把 cfg 清空
（全部回默认值），给测试与「配置加载失败」留一条退路。

本模块**只缓存声明**（`Param` 索引，来自不可变的 `STRATEGIES`），**从不缓存
值**：热链路的正确性靠这一点。消费方（`core/policy.py` 起）因此必须**在决策
那一刻**调 `resolve()`，不许把结果抄进实例属性或模块常量——门禁
`tests/test_r1063_policy_params_equivalent.py` 用「改配置后再 `decide()` 同一个
引擎对象」钉这条（旧断言是扫源码找 `self._pace =`，两个标识符根本不存在，
用例恒真，已撤）。

覆盖字典（`crawler.strategy_overrides`）
----------------------------------------
键是**作用域串**，由粗到细 `渠道` / `渠道/维度` / `渠道/维度/链路`，值直接是
`{pid: 值}`::

    crawler:
      strategy_overrides:
        fliggy:              {rate_per_minute.value: 9}      # 整个飞猪
        tongcheng/intl:      {rate_per_minute.value: 6}      # 同程国际
        tongcheng/intl/PC:   {rate_per_minute.value: 3}      # 同程国际 PC 链路
        ctrip/intl/H5/API:   {rate_per_minute.value: 4}      # 链路段可含 "/"

分隔规则：**最多切两刀**（`split("/", 2)`）——渠道段与维度段永不含 `/`，链路
段可以含（`core/channels.py` 里就有真实通路 id `H5/API`）；`override_key()` 与
`parse_override_key()` 互为逆运算。

未知渠道/维度/链路、整块不是字典、槽值不是字典、pid 不在策略目录里——**一律
抛 `ValueError`**（`parse_override_key` / `set_config`），绝不静默丢弃：静默丢弃
的覆盖项让用户以为「我配了」，实际什么都没发生，比缺一个功能更难查
（`SPEC:1664`）。整块类型也会查：`strategy_overrides: [...]` 曾经被当成「没有
覆盖」静默放过，那是同一类缺陷（复核 2026-11-06 指出）。

三条边界（写在这里，免得后面有人「顺手补全」）
----------------------------------------------
1. **链路必须带维度**：`渠道/链路` 这种两段式不存在——键的第二段永远是维度，
   第三段才是链路。`resolve(plat=…, path=…)` 不给 `dim` 时链路覆盖不参与。
2. **夹取在求值时做**（`_fit`）：配置文件里写 99999 不该让节流出负数或永不再采。
   人改了值要一句「按上限 1440 生效」的说明时调 `clamp()`，它返回的说明句
   是界面回写用的唯一文案来源。
3. **类型不硬转**：声明 `kind` 与真实 cfg 值不一致时（`crawler.cadence` 是
   `{渠道: 分钟}` 映射、`crawler.proxy_map` 是映射、`crawler.warmup.platforms`
   是列表），`_to_kind` 宁可原样返回也不把字典变成字符串——那会把配置改成
   一句 `"{'ctrip': 30}"` 的废话，属于最难复原的一种破坏。这三种键的
   `kind` 现在如实登记为 `map` / `map` / `list`（r1063 T3 修正），容器值一律
   **原样透传**：不转、不夹取、不改写。
"""
from __future__ import annotations

import warnings
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

from core import channels
from core.strategy_contract import STRATEGIES, Param

# 覆盖字典在 cfg 里的位置（裁决②：键是作用域串，值是 {pid: 值}）
OVERRIDE_CFG = "crawler.strategy_overrides"

# 来源标注的取值域。`effective_table()` 原样给界面，别加新值：
# 界面的「来源」列（默认/全局/渠道/维度/链路）只认这五个。
SOURCES = ("default", "global", "channel", "dimension", "path")

# 渠道段合法值：与 core/channels.py 同一份清单（不许在本模块另写一份）
PLATS: Tuple[str, ...] = tuple(channels.BROWSER_CHANNELS) + tuple(channels.APP_CHANNELS)

_MISSING = object()


class Resolved(NamedTuple):
    """一次求值的结果：`value` 生效值 / `source` 它从哪一层来 / `pid` 是谁。"""

    value: object
    source: str
    pid: str


# ---------------------------------------------------------------- 声明索引
#
# 只索引**声明**（不可变的 STRATEGIES），不索引值——值每次 resolve 现算。

def _index() -> Tuple[Dict[str, Param], Tuple[str, ...]]:
    """`pid → Param` 索引 + 重复 pid 名单（重复是缺陷：求值会自相矛盾）。"""
    idx: Dict[str, Param] = {}
    dups = set()
    for s in STRATEGIES:
        for p in s.params:
            if p.pid in idx:
                dups.add(p.pid)
            idx[p.pid] = p
    return idx, tuple(sorted(dups))


PARAMS, DUP_PIDS = _index()


def _param(pid: str) -> Param:
    """按 pid 取声明。未登记 → KeyError；重复登记 → KeyError（都在点名缺陷）。"""
    key = str(pid or "").strip()
    try:
        p = PARAMS[key]
    except KeyError:
        raise KeyError("未登记的参数 pid：%r —— core/strategy_contract.py 里没有它；"
                       "新键要在加读点的同一步登记，不能只写在代码里"
                       % (pid,)) from None
    if key in DUP_PIDS:
        raise KeyError("参数 pid 重复登记：%r —— 目录里两条策略用了同一个 pid，"
                       "求值会自相矛盾，先在 core/strategy_contract.py 里改名"
                       % (key,))
    return p


# ---------------------------------------------------------------- 配置单例

_CFG: Optional[dict] = None


def set_config(cfg: dict) -> None:
    """装入整份配置（模块级单例）。**可重入**：调完下一次 `resolve()` 即生效。

    存的是传入对象的引用（不深拷贝）：`reload_config()` 换掉 cfg 后再调一次
    本函数，全站立刻按新值走，不需要重建任何持有者。覆盖字典在这里**先校验**
    （未知作用域段/未知 pid 当场 ValueError），把「配了不生效」挡在装载这一步。
    """
    global _CFG
    cfg = cfg if isinstance(cfg, dict) else {}
    _validate_overrides(cfg)
    _CFG = cfg


def get_config() -> dict:
    """当前装入的配置（未装入时返回空字典，不返回 None）。"""
    return _CFG if isinstance(_CFG, dict) else {}


def invalidate() -> None:
    """清空配置：之后所有参数都按 `Param.default` 求值（来源 `default`）。"""
    global _CFG
    _CFG = None


def _dig(cfg: dict, dotted: str) -> Tuple[bool, object]:
    """按点路径取值；任一段缺失 → (False, None)，不抛异常（缺键是常态）。"""
    segs = [x for x in str(dotted or "").split(".") if x]
    if not segs:
        return False, None
    cur: object = cfg
    for seg in segs:
        if not isinstance(cur, dict) or seg not in cur:
            return False, None
        cur = cur[seg]
    return True, cur


def _overrides(cfg: dict) -> dict:
    """覆盖字典（缺失/类型不对时给空字典——校验在 `set_config` 已做过）。"""
    hit, raw = _dig(cfg, OVERRIDE_CFG)
    return raw if (hit and isinstance(raw, dict)) else {}


def _validate_overrides(cfg: dict) -> None:
    """装载即校验：整块类型、作用域段、pid 都必须认识，否则抛 `ValueError`。

    **整块类型也要查**：`strategy_overrides: [...]`（或字符串/数字）这种写法
    以前被当成「没有覆盖」静默放过——装载不报错、求值全走默认值、用户以为
    配了，正是本项目定义为最糟的「配了不生效」。所以这里先看 `_dig` 是否命中
    键，再看类型，最后才看内容。

    已知边界：`set_config` 之后原地改 cfg 里的覆盖字典会绕过这道校验（引用语义
    换来的是「改完立刻生效」）。正常路径（`reload_config` 换整份 cfg 再调
    `set_config`）不会走到这个边界。
    """
    hit, raw = _dig(cfg, OVERRIDE_CFG)
    if not hit:
        return
    if raw is None:
        # YAML 里写了空节（`strategy_overrides:` 后面什么都没有）→ 解析成 None。
        # 这里没有内容可丢，按「没有覆盖」对待；写成 `[]` / `"x"` / `5` 才是
        # 配置错误（下发过一次就会当场报错，见下）。
        return
    if not isinstance(raw, dict):
        raise ValueError("%s 必须是 {作用域: {pid: 值}} 的字典（当前是 %s）："
                         "整块覆盖都会被忽略，等于这条覆盖永远不会生效"
                         "（配了不生效比没配更糟）"
                         % (OVERRIDE_CFG, type(raw).__name__))
    for key, val in raw.items():
        parse_override_key(key)
        if not isinstance(val, dict):
            raise ValueError("%s[%r] 必须是 {pid: 值} 的字典，实际是 %s"
                             % (OVERRIDE_CFG, key, type(val).__name__))
        for pid in val:
            if str(pid) not in PARAMS:
                raise ValueError("%s[%r] 里的 pid %r 不在策略目录里——"
                                 "这条覆盖永远不会生效（配了不生效比没配更糟）"
                                 % (OVERRIDE_CFG, key, pid))


# ---------------------------------------------------------------- 作用域键

def _path_ok(path: str) -> bool:
    """链路段是否已知：`PATH_CN` 的键里含模板（`app-city-%s`），按前缀认。

    **模板前缀必须吃掉整段**：`app-city-bjs` 认得（模板的 `%s` 就是 `bjs`），
    但 `app-city-bjs/x` 不认——它多带了一段 `/x`，装载时能过、求值时永远匹配
    不上 `PATH_CN` 里的任何通路名，于是覆盖项「配了不生效」（复核 2026-11-06
    指出的 `app-city-*` 漏洞）。字面量键（如 `H5/API`）不受这条限制：它自己
    就含 `/`，走第一个分支。
    """
    if path in channels.PATH_CN:
        return True
    for k in channels.PATH_CN:
        if "%s" not in k:
            continue
        head = k.replace("%s", "")
        if path.startswith(head) and "/" not in path[len(head):]:
            return True
    return False


def parse_override_key(key: str) -> Tuple[str, str, str]:
    """`"渠道[/维度[/链路]]"` → `(plat, dim, path)`（缺的段补空串）。

    **分隔符最多切两刀**（`split("/", 2)`）：渠道段与维度段永不含 `/`，而链路
    段可能含——`core/channels.py` 里就有真实通路 id `H5/API`（账本里跑了
    30+ 次的生产通路）。按固定三段切会把它判成四段、当场拒掉，于是这条通路
    永远配不上覆盖（复核裁决 2026-11-06）。

    任何一段不认识都抛 `ValueError`——覆盖项不许被静默丢弃。
    """
    text = str(key or "").strip()
    if not text:
        raise ValueError("覆盖键为空：作用域至少要给渠道（可选：%s）"
                         % "、".join(PLATS))
    segs = [x.strip() for x in text.split("/", 2)]
    plat = segs[0]
    dim = segs[1] if len(segs) > 1 else ""
    path = segs[2] if len(segs) > 2 else ""
    if plat not in PLATS:
        raise ValueError("覆盖键 %r 的渠道段 %r 不认识（只认 core/channels.py 的 "
                         "BROWSER_CHANNELS + APP_CHANNELS：%s）"
                         % (key, plat, "、".join(PLATS)))
    if dim and dim not in channels.DIMENSIONS:
        raise ValueError("覆盖键 %r 的维度段 %r 不认识（只认 %s）"
                         % (key, dim, "、".join(channels.DIMENSIONS)))
    if path and not dim:
        raise ValueError("覆盖键 %r 有链路段却没有维度段：键的第二段永远是维度，"
                         "两段式的「渠道/链路」不存在" % (key,))
    if path and not _path_ok(path):
        raise ValueError("覆盖键 %r 的链路段 %r 不认识（只认 core/channels.py "
                         "PATH_CN 里的通路名，如 PC/H5/日历/H5\\/API/app-list）"
                         % (key, path))
    return plat, dim, path


def override_key(plat: str, dim: str = "", path: str = "") -> str:
    """拼作用域键（`fliggy` / `tongcheng/intl` / `tongcheng/intl/H5/API`）。

    与 `parse_override_key` **互为逆运算**：链路段自己带 `/`（`H5/API`）也拼得
    回去、解得回来。拼的同时校验——写覆盖项的人和读覆盖项的人用同一套规则，
    才不会出现「界面上配了一个库里对不上的键」。
    """
    if not plat:
        return ""
    key = "/".join(x for x in (plat, dim, path) if x)
    if parse_override_key(key) != (plat, dim, path):
        # 兜底：段里出现空串之类的畸形输入（例：dim 空、path 有值）会被上面
        # 的校验挡住；这一句保证「拼出来的键解不回原值」时绝不返回半个键。
        raise ValueError("作用域三段拼不回原值：plat=%r dim=%r path=%r → %r"
                         % (plat, dim, path, key))
    return key


def _lookup_keys(plat: str, dim: str, path: str) -> Tuple[Tuple[str, str], ...]:
    """由粗到细的查找链（后者覆盖前者）。

    这里**故意不校验**渠道/维度/链路：这是「查表」不是「写表」——未知渠道
    自然查不到覆盖项，回落到全局值；写表那一侧（`override_key` /
    `parse_override_key` / `set_config`）已经把非法项挡住了。
    """
    plat = str(plat or "").strip()
    dim = str(dim or "").strip()
    path = str(path or "").strip()
    if not plat:
        return ()
    chain = [(plat, "channel")]
    if dim:
        chain.append(("/".join((plat, dim)), "dimension"))
        if path:
            chain.append(("/".join((plat, dim, path)), "path"))
    return tuple(chain)


# ---------------------------------------------------------------- 类型与夹取

_TRUE = ("1", "true", "yes", "on", "y", "是", "开")
_FALSE = ("0", "false", "no", "off", "n", "否", "关")


def _to_kind(kind: str, value: object) -> object:
    """尽力把值转成声明的 kind；**转不了就原样返回**（绝不硬转成字符串）。

    容器 kind（`map` / `list`）与 `str` 都走最后一条：容器值原样返回。
    `str(dict)` 会把配置毁成一句不可逆的字符串，比「类型不对」糟得多。
    """
    if isinstance(value, bool):
        if kind == "int":
            return int(value)
        if kind == "float":
            return float(value)
        return value
    if kind == "int":
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(round(value))
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                try:
                    return int(round(float(value.strip())))
                except ValueError:
                    return value
        return value
    if kind == "float":
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                return value
        return value
    if kind == "bool":
        if isinstance(value, int):
            return bool(value)
        if isinstance(value, str):
            low = value.strip().lower()
            if low in _TRUE:
                return True
            if low in _FALSE:
                return False
        return value
    # kind == "str" / "map" / "list"：非字符串原样返回（`crawler.proxy_map` 是
    # 映射、`crawler.warmup.platforms` 是列表；`str(dict)` 会把配置毁成一句
    # 不可逆的字符串，而 dict 也不该被转成 list）
    return value


def _fmt(v: object) -> str:
    """给说明句用的值格式。

    不做「整数值的 float 去掉 .0」这种美化：界说的界宽是声明类型带的
    （`near_window.ratio` 的上限就是 `1.0`），写成 `1` 会让人以为是整数界。
    """
    if isinstance(v, bool):
        return "开" if v else "关"
    return "%s" % (v,)


def _fit(p: Param, value: object) -> object:
    """求值时的类型规整 + 越界夹取（夹取静默，说明句由 `clamp()` 给）。"""
    v = _to_kind(p.kind, value)
    if p.kind not in ("int", "float") or isinstance(v, bool):
        return v
    if not isinstance(v, (int, float)):
        return v
    if p.lo is not None and v < p.lo:
        return p.lo
    if p.hi is not None and v > p.hi:
        return p.hi
    return v


def clamp(pid: str, value: object) -> Tuple[object, str]:
    """把用户输入夹到参数声明的范围内，返回 `(夹后值, 说明句)`。

    说明句**必须点名是哪条界**（`"ttl_tier.fast 的上限是 1440…"`）：界面把它
    显示成「你填的 99999 已按上限 1440 生效」，用户才知道自己被改了哪里。
    没夹取时返回空串（界面据此不显示提示）。`value=None` 时按默认值处理。

    值转不成声明的类型（例如往整参数里填 `"abc"`）→ `ValueError`：这是界面
    要一句「不是合法的整数」的场景，不能吞。**容器值例外**：`crawler.cadence`
    （`map`）/ `crawler.warmup.platforms`（`list`）这类键原样返回、说明句为空
    ——与 `resolve()` 同口径：容器不夹取、不转类型，界面照着原值回写。
    """
    p = _param(pid)
    raw = p.default if value is None else value
    got = _to_kind(p.kind, raw)
    if isinstance(got, (dict, list, tuple, set)):
        return got, ""
    if p.kind in ("int", "float") and not isinstance(got, bool) \
            and not isinstance(got, (int, float)):
        raise ValueError("%s 需要%s，%r 转不过去"
                         % (p.pid, "整数" if p.kind == "int" else "小数", value))
    if p.kind not in ("int", "float") or isinstance(got, bool):
        return got, ""
    if p.lo is not None and got < p.lo:
        return p.lo, "%s 的下限是 %s：填的 %s 低于下限，已按 %s 生效" % (
            p.pid, _fmt(p.lo), _fmt(raw), _fmt(p.lo))
    if p.hi is not None and got > p.hi:
        return p.hi, "%s 的上限是 %s：填的 %s 高于上限，已按 %s 生效" % (
            p.pid, _fmt(p.hi), _fmt(raw), _fmt(p.hi))
    return got, ""


# ---------------------------------------------------------------- 求值

def resolve(pid: str, *, plat: str = "", dim: str = "",
            path: str = "") -> Resolved:
    """求一个参数此刻的生效值：默认值 → 全局 cfg → 渠道 → 维度 → 链路。

    后一层覆盖前一层；`source` 说明命中的是哪一层（界面「来源」列直接用它）。
    每次调用都现读模块级 cfg，**不缓存**——这就是 `set_config()` 热生效的实现。
    """
    p = _param(pid)
    cfg = get_config()
    value: object = p.default
    source = "default"
    hit, raw = _dig(cfg, p.cfg)
    if hit:
        value, source = raw, "global"
    ov = _overrides(cfg)
    for key, layer in _lookup_keys(plat, dim, path):
        slot = ov.get(key)
        if not isinstance(slot, dict):
            continue
        got = slot.get(p.pid, _MISSING)
        if got is not _MISSING:
            value, source = got, layer
    return Resolved(_fit(p, value), source, p.pid)


# ---------------------------------------------------------------- 开关求值
#
# 策略开关（`<sid>.enabled`）的读法：`resolve()` 之上的**薄**一层，只多两件事
# ——把「读不懂的值」按开启留痕、给「本来就写在 cfg 里」的老开关一个兜底值。
#
# 为什么读点搬到这一层（r1063 fix-wave 2）：消费方不止一处——节流/熔断在
# `core/pacing.py`，统一闸门在两个采集器基类（`crawlers/base.py`、
# `crawlers/app_base.py`）。跨模块 import 一个下划线名等于把「私有」当装饰；
# 而契约的「可开启」轴认的正是「pid 作为实参交给一个能走到 `resolve(` 的
# 函数」——公开名让这条判据读得懂，也让下一个接线的人找得到唯一读法。
#
# 三条边界（与迁移前逐条相同）：
#   1. **默认 True**：参数层一层都没配过就走老分支，行为逐位等价；
#   2. **读不懂按开启处理**（fail-open）并留痕：拼错的 `flase` 若静默把策略
#      关掉，用户会以为在跑、其实整条策略没生效——比报错更难查；
#   3. **每次决策现读**，绝不缓存成实例属性：热改配置下一次决策就生效。

# 布尔词表：手写 config.yaml 里 `enabled: "false"`（带引号）是**字符串**，
# `bool("false")` 是 True —— 开关会静默失效（r519 实测三处全中）。
# 只有这一份：`core/pacing.py` 的 `_path_enabled()` 绑的是同一批对象。
TRUE_WORDS = ("1", "true", "yes", "on", "y", "是", "开")
FALSE_WORDS = ("0", "false", "no", "off", "n", "否", "关")

# 同一个坏值只喊一次：链路闸门是每请求必经的路径，逐次告警会刷爆日志。
_SWITCH_WARNED: set = set()


def switch_on(pid: str, *, plat: str = "", dim: str = "", path: str = "",
              fallback: Optional[bool] = None) -> bool:
    """读一条策略的 `enabled` 开关（`pid` 形如 `rate_min_gap.enabled`）。

    `plat` / `dim` / `path` 是**作用域**，由粗到细：给了 `dim` 才命中
    `渠道/维度` 层，`dim`+`path` 都给了才命中 `渠道/维度/链路` 层（只给
    `path` 不给 `dim` 在 `_lookup_keys()` 里不参与求值——键的第二段永远是
    维度，见模块 docstring 边界 1）。三者全空 = 全局层。

    为什么作用域要一路递到决策点：`crawler.strategy_overrides` 的
    `渠道/维度` 与 `渠道/维度/链路` 两层的意义就是「这一条路单独关掉熔断 /
    单独放开限速」。读点只拿到 `plat` 时这两层形同虚设——界面按
    `source=dimension/path` 渲染成「已按维度停用」，熔断照旧，正是本项目列
    为头号缺陷的「配了不生效」。

    `fallback`：**参数层一层都没配过**（`source == "default"`）时的兜底值，
    给四个「本来就写在 cfg 里」的老开关用——`crawler.breaker.enabled` /
    `crawler.warmup.enabled` / `crawler.health_penalty_enabled` 由
    `parse_pacing` 归一成扁平值，`crawler.policy_gate` 由采集器直读。它们
    已经登记成对应 pid 的 `Param.cfg`（参数层的**全局层**），所以只在没人
    配过时才用兜底值：不是第二份权威，是旧值的退路。`None`（缺省）保持老
    语义——参数层缺省即「开启」。
    """
    try:
        got = resolve(str(pid), plat=str(plat or ""), dim=str(dim or ""),
                      path=str(path or ""))
    except Exception:                # 参数层不可用：按开启处理（缺省即旧行为）
        return True if fallback is None else bool(fallback)
    if got.source == "default" and fallback is not None:
        return bool(fallback)
    value = got.value
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if not text:                     # 写了键却没有值：等于没配
        return True
    if text in TRUE_WORDS:
        return True
    if text in FALSE_WORDS:
        return False
    _warn_switch_once(
        value, "%s 的值 %r 读不懂（%s）：已按开启处理，要关掉请写 false"
               % (pid, value, "/".join(x for x in (plat, dim, path) if x)))
    return True


def _warn_switch_once(tag: object, msg: str) -> None:
    """读不懂的开关值只喊一次（按值去重）。

    不能只是「按启用处理」了事：拼错的 `flase` 会让用户以为这条策略已经停了，
    而它照常跑——「配了不生效」最难查的一类。
    """
    key = repr(tag)
    if key in _SWITCH_WARNED:
        return
    _SWITCH_WARNED.add(key)
    warnings.warn(msg, RuntimeWarning, stacklevel=3)


def effective_table(plats: Sequence[str] = ()) -> List[dict]:
    """给 `/api/strategy` 的生效值表：`{pid, plat, value, source, default, lo, hi}`。

    `plats` 为空按 `["*"]`（不分渠道）展开；`*` 行等价于不带 plat 求值。
    只展开**声明了参数**的策略——没有参数的策略（只建议档）不出现在表里。
    """
    names = tuple(plats) or ("*",)
    rows: List[dict] = []
    for s in STRATEGIES:
        for p in s.params:
            for plat in names:
                got = (resolve(p.pid) if plat in ("", "*")
                       else resolve(p.pid, plat=plat))
                rows.append({"pid": p.pid, "plat": plat, "value": got.value,
                             "source": got.source, "default": p.default,
                             "lo": p.lo, "hi": p.hi})
    return rows


__all__ = [
    "OVERRIDE_CFG", "SOURCES", "PLATS", "PARAMS", "DUP_PIDS", "Resolved",
    "TRUE_WORDS", "FALSE_WORDS",
    "set_config", "get_config", "invalidate",
    "resolve", "switch_on", "override_key", "parse_override_key", "clamp",
    "effective_table",
]
