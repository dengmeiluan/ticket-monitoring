"""把 maps 洗白模块（seccomp）打成 Magisk/KernelSU 可安装的 zip。

用法：
```
python scripts/build_maps_cloak.py --out dist/tm_maps_cloak.zip \
    --arm64 build/arm64-v8a/libmaps_cloak.so \
    --x86_64 build/x86_64/libmaps_cloak.so \
    --config native/maps_cloak/config/global.json
```

为什么要这个脚本而不是手敲 zip：模块 zip 的内部路径写错时，Magisk 会**静默不加载**
（现象是"什么都没发生"），排错成本极高。这里把路径形状钉死，并有单测覆盖
（`tests/test_r1063_maps_cloak_pack.py`）。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import zipfile

MODULE_ID = "tm_maps_cloak"
REQUIRED_ABIS = ("arm64-v8a", "x86_64")


SERVICE_SH_TMPL = """#!/system/bin/sh
# 开机把 maps 洗白库就位，并对配置里的每个包设 wrap.<pkg>（LD_PRELOAD 注入）。
# 机制：Android 的 Zygote 在 specialize 前会读 wrap.<包名> 并据此设置环境变量。
# 本机 Android 15 镜像自带 native-bridge 是 v2、系统要 v3，Zygisk 全灭，
# 所以这条注入路线不经过 Zygisk。
MODDIR=${0%/*}
LIBDIR=/data/local/tmp
MARKER=$MODDIR/disable

# 被禁用就什么都不做（回滚 = touch disable + 重启）
[ -f "$MARKER" ] && exit 0

# 库文件放到 App 可读的位置（/data/adb/modules 是 0700，App 读不到）
for abi in x86_64 arm64-v8a; do
  src=$MODDIR/zygisk/$abi.so
  dst=$LIBDIR/libmaps_cloak_$abi.so
  [ -f "$src" ] || continue
  cp -f "$src" "$dst"
  chmod 644 "$dst"
  chcon u:object_r:system_lib_file:s0 "$dst" 2>/dev/null
done

# 逐个包设注入点（只对 x86_64 进程有效的场景也一并设，arm64 由库自身匹配）
if [ -f "$MODDIR/config/packages.list" ]; then
  while read -r pkg; do
    case "$pkg" in ""|\#*) continue ;; esac
    setprop wrap.$pkg "LD_PRELOAD=$LIBDIR/libmaps_cloak_x86_64.so"
  done < "$MODDIR/config/packages.list"
fi
"""

PROP_TMPL = """id={id}
name=TM Maps Cloak（maps 洗白）
version=v0.1.0
versionCode=1
author=ticket-monitoring
description=让指定 App 读自己 /proc/self/maps 时看不到 houdini/nemu 痕迹（seccomp 代理）。默认不启用，禁用即回滚。
"""


def load_config(path: str) -> dict:
    """读并校验配置。缺字段/空词表一律报错——静默失效比报错贵得多。"""
    with io.open(path, encoding="utf-8") as f:
        cfg = json.load(f) or {}
    if not isinstance(cfg, dict):
        raise ValueError("配置文件必须是 JSON 对象")
    for key in ("enabled", "packages", "markers"):
        if key not in cfg:
            raise ValueError("配置缺少字段：%s" % key)
    if not isinstance(cfg["packages"], list) or not cfg["packages"]:
        raise ValueError("packages 必须是非空数组")
    if not isinstance(cfg["markers"], list) or not cfg["markers"]:
        raise ValueError("markers 必须是非空数组（空词表等于不过滤）")
    return cfg


def build_module(out_zip: str, so_by_abi: dict, cfg: dict) -> str:
    """产出模块 zip 并返回路径。

    `so_by_abi` 必须同时给 arm64-v8a 与 x86_64——MuMu 两种 ABI 都在跑，
    少一个就会出现"部分 App 没效果"的假象。
    """
    missing = [a for a in REQUIRED_ABIS if a not in (so_by_abi or {})]
    if missing:
        raise ValueError("缺少 ABI 产物：%s" % ", ".join(missing))
    for abi in REQUIRED_ABIS:
        p = so_by_abi[abi]
        if not os.path.isfile(p):
            raise ValueError("找不到 %s 的 .so：%s" % (abi, p))

    os.makedirs(os.path.dirname(os.path.abspath(out_zip)), exist_ok=True)
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("module.prop", PROP_TMPL.format(id=MODULE_ID))
        z.writestr("config/global.json",
                   json.dumps(cfg, ensure_ascii=False, indent=2))
        z.writestr("config/packages.list",
                   "\n".join(cfg["packages"]) + "\n")
        z.writestr("service.sh", SERVICE_SH_TMPL)
        for abi in REQUIRED_ABIS:
            z.write(so_by_abi[abi], "zygisk/%s.so" % abi)
    return out_zip


def _main(argv=None):                              # pragma: no cover - CLI
    ap = argparse.ArgumentParser(description="打包 maps 洗白模块")
    ap.add_argument("--out", required=True)
    ap.add_argument("--arm64", required=True)
    ap.add_argument("--x86_64", required=True)
    ap.add_argument("--config", required=True)
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    out = build_module(a.out, {"arm64-v8a": a.arm64, "x86_64": a.x86_64}, cfg)
    print("已生成:", out, "（%d 字节）" % os.path.getsize(out))


if __name__ == "__main__":                         # pragma: no cover
    _main()
