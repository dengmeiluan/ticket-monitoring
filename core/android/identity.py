# -*- coding: utf-8 -*-
'''r1063 T82（续）：把「解封手段」做成可执行工具——MuMu 底层标识查看/轮换。

用户问「是否可能是 mumu 底层 id 已经被封禁，还有什么手段可以进行解封」。
取证结论（T81）：不是整机被封（同机智行/去哪儿 19 秒正常出数），
是**分渠道**的风控状态。但"换一张设备脸"仍是可用的手段之一。

MuMu 的可写键实测（`MuMuManager.exe setting -v 0 --all_writable`）里
与设备身份直接相关的是：

    phone_imei   865247046277134
    phone_brand  vivo
    phone_model  vivo X200 Pro
    phone_miit   V2405A

所以做两件事：
* `show()`：把当前设备身份打出来（面板/CLI 都能看）；
* `rotate_id()`：换一套（imei 随机、机型从内置清单里挑），**需要先关机再开机**；
  默认只演练，`apply=True` 才写。
'''
from __future__ import annotations

import json
import random

from .mumu import MuMuManager

# 常见真机机型（品牌, 型号, miit 认证码）。挑真实存在的型号——
# 编造的型号本身就是异常信号，比不换更糟。
DEVICE_MODELS = (
    ("vivo", "vivo X200 Pro", "V2405A"),
    ("HONOR", "PGT-AN10", "PGT-AN10"),
    ("Xiaomi", "24129PN74C", "24129PN74C"),
    ("OPPO", "PJZ110", "PJZ110"),
    ("samsung", "SM-S9280", "SM-S9280"),
)

ID_KEYS = ("phone_imei", "phone_brand", "phone_model", "phone_miit")


def _mgr(cfg: dict = None) -> MuMuManager:
    install = ""
    try:
        install = str(((cfg or {}).get("android") or {}).get("install_dir") or "")
    except Exception:
        install = ""
    return MuMuManager(install or None)


def _unwrap(key: str, raw):
    """MuMuManager 的 setting 返回 JSON 文本（`{"phone_imei": "..."}`），取里面的值。"""
    try:
        obj = json.loads(str(raw))
        if isinstance(obj, dict):
            return str(obj.get(key, raw))
    except Exception:
        pass
    return str(raw)


def apps_need_relogin(cfg: dict = None) -> list:
    """换身份/清数据后**必须重登**的 App 渠道（取当前订阅的 App 名单）。

    为什么要有这个清单：换身份 = 换了一台新设备，服务端看到的会话全部作废。
    真机实证（2026-11-08）：身份换成 Xiaomi 14 之后，`app_qunar` 从 19.2s
    正常出数变成「搜索后要求登录（登录态失效）」。不提示的话，用户会以为
    工具"没效果"。
    """
    try:
        import yaml
        plats = []
        if cfg is not None:
            # 显式传了就**只信它**（空就是空，别偷偷回退读文件）
            plats = (((cfg.get("users") or [{}])[0]).get("platforms") or [])
        else:
            with open("config.yaml", encoding="utf-8") as f:
                c = yaml.safe_load(f) or {}
            plats = ((c.get("users") or [{}])[0].get("platforms") or [])
        from core.channels import APP_CHANNELS
        return [p for p in plats if p in APP_CHANNELS]
    except Exception:
        return []


def show(cfg: dict = None, vm: int = 0) -> dict:
    """当前 MuMu 底层设备身份（读不到就返回空 + 原因）。"""
    m = _mgr(cfg)
    out = {"ok": False, "vm": vm, "id": {}, "why": ""}
    try:
        rows = {}
        for k in ID_KEYS:
            v = m.setting(k, vm=vm)
            if v is not None:
                rows[k] = _unwrap(k, v)
        out["id"] = rows
        out["ok"] = bool(rows)
        if not rows:
            out["why"] = "读不到（MuMuManager 不可用或实例未创建）"
    except Exception as e:
        out["why"] = "%s: %s" % (type(e).__name__, str(e)[:80])
    return out


def luhn_ok(digits: str) -> bool:
    """IMEI/信用卡通用 Luhn 校验（从右往左，第 2 位起每两位翻倍）。"""
    total = 0
    for i, ch in enumerate(reversed(str(digits))):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _rand_imei(rng: random.Random) -> str:
    """15 位 IMEI（带 Luhn 校验位）——校验位错的 IMEI 一眼假。

    实现方式：随机出前 14 位，再**穷举**最后一位让 `luhn_ok()` 成立。
    比自己推公式稳：生成与校验共用同一个函数，不可能算歪
    （第一版就因为翻倍位取反了，生成的全是非法 IMEI）。
    """
    body = [rng.randint(1, 9)] + [rng.randint(0, 9) for _ in range(13)]
    head = "".join(str(d) for d in body)
    for check in range(10):
        cand = head + str(check)
        if luhn_ok(cand):
            return cand
    return head + "0"      # 理论不可达


def rotate_id(cfg: dict = None, vm: int = 0, *, apply: bool = False,
              seed: int = 0) -> dict:
    """换一套 MuMu 底层设备身份。默认只演练。

    顺序纪律：**必须先关机**（`control shutdown`）再改，改完再开机；
    运行中改 imei/机型，App 侧看到的会是半新半旧，比不换更可疑。
    """
    rng = random.Random(seed or None)
    brand, model, miit = rng.choice(DEVICE_MODELS)
    want = {"phone_imei": _rand_imei(rng), "phone_brand": brand,
            "phone_model": model, "phone_miit": miit}
    rep = {"ok": False, "applied": False, "vm": vm, "want": want,
           "before": show(cfg, vm).get("id") or {}, "why": "",
           "need_restart": True}
    if not apply:
        rep["ok"] = True
        rep["why"] = "演练（未写入；apply=True 才写）"
        return rep
    m = _mgr(cfg)
    try:
        m.control("shutdown", vm=vm)
    except Exception:
        pass
    wrote = {}
    for k, v in want.items():
        try:
            wrote[k] = bool(m.setting(k, v, vm=vm))
        except Exception:
            wrote[k] = False
    rep["wrote"] = wrote
    rep["ok"] = all(wrote.values())
    rep["applied"] = rep["ok"]
    rep["why"] = ("已写入，需重启实例生效" if rep["ok"]
                  else "部分键写入失败：%s" % json.dumps(wrote, ensure_ascii=False))
    return rep


def _main(argv=None):                              # pragma: no cover - CLI
    import sys

    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "show"
    apply = "--apply" in argv
    vm = 0
    for i, a in enumerate(argv):
        if a == "--vm" and i + 1 < len(argv):
            vm = int(argv[i + 1])
    if cmd == "show":
        print(json.dumps(show({}, vm), ensure_ascii=False, indent=1))
        return 0
    if cmd == "rotate":
        rep = rotate_id({}, vm, apply=apply)
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        return 0 if rep.get("ok") else 1
    print("用法: python -m core.android.identity show|rotate [--apply] "
          "[--vm N]")
    return 2


if __name__ == "__main__":                         # pragma: no cover
    raise SystemExit(_main())
