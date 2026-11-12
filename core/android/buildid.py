# -*- coding: utf-8 -*-
"""给"看起来像真机"补上最后一环：**boot 后一次性把 build.id 家族对齐**。

为什么需要这个模块（2026-11-04 实测，结论是"改文件没用"）
--------------------------------------------------------
运行时 `ro.build.id = V417IR`、`ro.build.display.id = "V417IR release-keys"`，
而 `V417IR` 是 MuMu 自己的 build 号 —— 它同时出现在
`ro.build.fingerprint = vivo/V2405A/V2405A:15/**V417IR**/1171` 里。
`Build.ID` / `Build.FINGERPRINT` 是任何 SDK 都会读的两个字段，
所以这是目前最强的一条"我们是模拟器"的相关性键。

试过并被**证伪**的两条路：
1. 改 `/system/build.prop` 等 5 个分区文件（`bootprops.py`）：
   写成功了、重启后文件里也还在（overlay 持久），但运行时仍是 V417IR
   ⇒ **文件不是这些键的出处**；而且 `/system/build.prop` 是 `0600 root`，
   App 根本读不到文件，只能读到 property service 的值。
2. 改 `device-prop-configs/build.config`：那份文件写的是
   OnePlus8Pro / Android 12 / sdk=32 / eng.nioh.*，与运行时
   （vivo/V2405A/15/35/1171）**全不相符** ⇒ 它是没被应用的模板。

真正在用它们的是 MuMu 的 boot 注入器（同一层把 brand/model/fingerprint
覆盖成 vivo 的，就是它）。所以只能用我们已经验证过的通道去**盖掉它**：
`/data/adb/magisk/magisk` 的 `resetprop --delete` + `set`（§6.31 实测
"先删再写"才有效；这条通道每轮都在清 `ro.nemu`，从没把设备搞挂）。

和 `_NO_HOT_WRITE` 的关系（重要，别搞混）
----------------------------------------
`abi_canary._NO_HOT_WRITE` 禁止的是**批量**热改 `ro.product.*` /
`ro.build.version.*`：今天两次 system_server 重启、一次 linker 打不开 so，
都是那类改动（`sdk` 变了，native 层按 API 等级找库必然失败）。
本模块只碰**纯展示型字符串**（id / display.id / 各分区 fingerprint），
不碰版本等级、不碰 ABI、不碰 hardware/board。默认仍然是**关**的，
因为"没崩过"不等于"安全"，必须在采集空档单独验证。

幂等与成本控制
--------------
先读现值，已经是目标值就**一次 adb 都不发**（这是每轮都会走的路径）；
只有在需要时才走"删+写+读回"。设备离线一律 fail-soft，不影响采集。
"""
from __future__ import annotations

from .fingerprint import (PHONE_POOL, _call, _flag, _magisk, _q, _text,
                          props_of, sh_script)

# **不维护"哪些键要改"的白名单，改成"含旧 build 号的一律改，
# 但结构性键绝不碰"的排除表。**
#
# 为什么（2026-11-04 23:26 我自己制造的事故）：
# 第一版是手写白名单 `SETTABLE`，只列了 `ro.build.id` + 六个分区
# `build.fingerprint`，**漏了七个键**：五个分区
# `ro.system/vendor/odm/product/system_ext.build.id`、`ro.vendor_dlkm.build.id`
# 和 `ro.vendor_dlkm.build.fingerprint`。
# 于是写完之后 `Build.ID=AP3A…` 而 `ro.system.build.id=V417IR` ——
# **半改状态比不改更糟**：自洽性恰恰是风控 SDK 最常查的一项。
#
# 规律：**成套出现、必须整体一致的字段，不能靠手写清单**（清单一定会漏），
# 要按"值里含旧 token"动态发现；能手写的只有**排除表**——
# 排除表漏写的后果是"少改一个"，白名单漏写的后果是"改出一套矛盾"，
# 后者危险得多。
BANNED_SUBSTR = (
    # 版本族：今天两次 system_server 重启 / linker 打不开 so 都是这类键造成的
    "ro.build.version.",
    # ABI / SoC / 板级：改了会让 native 层按不存在的库路径去找
    "ro.product.cpu.", "ro.vendor.product.cpu.", "ro.system.product.cpu.",
    "ro.product.odm.cpu", "ro.product.vendor.cpu", "dalvik.",
    "ro.hardware", "ro.board.platform", "ro.bootimage.",
    # 可信启动链 / 序列号 / adb 行为：动它们会牵连启动与设备标识
    "ro.boot.", "ro.serialno", "ro.bootserial",
    "ro.adb.secure", "ro.debuggable", "ro.secure",
    # 机型与构建元信息：由 MuMu 官方键和注入器负责，不在这里发明
    "ro.product.brand", "ro.product.model", "ro.product.device",
    "ro.product.name", "ro.product.manufacturer",
    "ro.build.date", "ro.build.host", "ro.build.user",
    "ro.build.tags", "ro.build.type", "ro.build.flavor", "ro.build.product",
)


def _old_token(props, new_id):
    """找出"还没对齐的旧 build 号"。

    先从主键取；**主键已经对齐时**（我第一版就是在这里读到自己写的
    新值，于是 `old == new`，七次写入全是原地自写、七个残留一个没匹配到），
    再从分区 `ro.<part>.build.id` 里取那个与主键不同的值。
    """
    cur = str(props.get("ro.build.id") or "").strip()
    if cur and new_id and cur != new_id:
        return cur
    for k, v in props.items():
        if k.endswith(".build.id") and k != "ro.build.id":
            v = str(v or "").strip()
            if v and v != new_id:
                return v
    return ""


def _profile_for(props):
    """按运行时 model 找池条目（找不到返回 None）。共享给 target_for 与 sync。"""
    model = str(props.get("ro.product.model") or "").strip()
    if not model:
        return None
    for p in PHONE_POOL:
        if str(p.get("model")) == model:
            return p
    return None


def target_for(props):
    """返回 {键: 新值}：所有**值里含旧 build 号**且不在排除表里的键。

    做法是"把旧 token 原地换成新 token"，不是按模板重拼 ——
    注入器已经把 brand/model/device/release/incremental/flavor/tags
    组成一套自洽值，重拼任何一处对不上就又造出矛盾
    （`ro.build.description = missi_V2405A-user 15 V417IR 1171 release-keys`
    必须跟着改，否则 `Build.DESCRIPTION` 与 `Build.ID` 互相打脸）。

    三条硬约束：
    * **只动含旧 build 号的值**：不含就跳过，绝不凭猜写新值；
    * **排除表优先**：`ro.build.version.*` / `cpu.abi` / `hardware` /
      `ro.boot.*` 等结构性键即使含旧号也不碰（版本族是今天的翻车原因，
      所以已知残留 `incremental=1171` 保留，属如实未处理项）；
    * **机型不在池里 → 返回空**，不猜 build 号。
    """
    prof = _profile_for(props)
    if not prof:
        return {}
    new_id = str(prof.get("build_id") or "").strip()
    if not new_id:
        return {}
    old_id = _old_token(props, new_id)
    if not old_id:
        return {}                       # 全部已对齐
    out = {}
    for k, v in props.items():
        v = str(v or "")
        if old_id not in v:
            continue
        if any(b in k for b in BANNED_SUBSTR):
            continue
        nv = v.replace(old_id, new_id)
        if nv != v:
            out[k] = nv
    return out


def sync(dev, config=None, logger=None):
    """把 build.id 家族对齐成自洽值（默认关，需显式开启）。"""
    sec = ((config or {}).get("android") or {}).get("build_id") or {}
    if not _flag(sec.get("enabled", False), False):
        return {"ok": True, "skipped": "未启用（android.build_id.enabled）",
                "changed": 0, "verified": True}

    props = props_of(dev)
    if not props:
        return {"ok": False, "error": "设备没读到 props", "changed": 0,
                "verified": False}
    want = target_for(props)
    new_id = str(( _profile_for(props) or {}).get("build_id") or "")
    old_id = _old_token(props, new_id)
    if not want:
        # **三种"什么都不做"必须能区分开**（否则日志会把好状态说成坏状态）：
        #   ① 机型不在池里 —— 配置/池漂移，操作员该看一眼；
        #   ② build 号已经是池里的值 —— 理想状态，每轮都会走这条路；
        #   ③ 现值里根本没有旧 build 号可替换 —— 被别的工具改过，不动为好。
        # 三者都**不算失败**：写失败会污染成功率账本。
        _prof = _profile_for(props)
        if _prof is None:
            _why = "model=%s 不在 PHONE_POOL，未改动" % props.get(
                "ro.product.model")
        elif str(props.get("ro.build.id") or "").strip() == str(
                _prof.get("build_id") or "").strip():
            _why = "已自洽"
        else:
            _why = "现值里没有旧 build 号可替换，未改动"
        return {"ok": True, "changed": 0, "verified": True, "skipped": _why}
    # 现值已经对 → 一次 adb 都不发
    diff = {k: v for k, v in want.items()
            if str(props.get(k) or "") != v}
    if not diff:
        return {"ok": True, "changed": 0, "verified": True,
                "skipped": "已自洽"}

    rp = _magisk(dev)
    if not rp or "resetprop" not in rp:
        return {"ok": False, "changed": 0, "verified": False,
                "error": "没有可用的 resetprop（这条通道是唯一可行通道）"}

    binp = rp.rsplit(" resetprop", 1)[0] if rp.endswith(" resetprop") else rp
    changed, failed = [], []
    for k, v in diff.items():
        # 先删再写（§6.31：不删直接 set 会被 property area 的"已写过"标记挡掉）
        sh_script(dev, "%s --delete %s >/dev/null 2>&1; %s %s %s" %
                  (binp, k, rp, k, _q(v)))
        got = _text(_call(dev, "shell", "getprop", k)).strip()
        (changed if got == v else failed).append(k)

    # **收尾必须复查残留**（这次的教训）：九次写入全部"成功"，
    # 但另有七个键根本没进入计划，日志却一片 green。
    # 只看"我改的键对不对"不够，要看"全机还有没有旧 token"——
    # 否则半改状态会被当成改完了。
    _after = props_of(dev) or {}
    _residual = sorted(k for k, v in _after.items()
                       if old_id and old_id in str(v or "")
                       and not any(b in k for b in BANNED_SUBSTR))
    rep = {"ok": not failed and not _residual,
           "changed": len(changed),
           "failed": failed, "verified": not failed and not _residual,
           "residual": _residual, "old_token": old_id,
           "keys": sorted(diff),
           "restart_note": "实例重启后 MuMu 注入器会把 V417IR 写回来，"
                           "由 harden() 的 build-id 步骤重新对齐"}
    if logger:
        logger.info("[android] build.id 家族对齐：%d/%d 生效%s%s",
                    len(changed), len(diff),
                    "" if not failed else "，失败：%s" % ",".join(failed),
                    "" if not _residual else
                    "，仍有 %d 个键含旧 build 号未处理：%s"
                    % (len(_residual), ",".join(_residual[:4])))
    return rep
