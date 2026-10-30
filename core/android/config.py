# -*- coding: utf-8 -*-
"""App 渠道配置：缺省关闭，数值一律钳制，坏类型不抛异常。

设计意图（spec §5）：`android.enabled` 是总开关。关闭时整条链路连
subprocess 都不该碰——所以本模块只做纯数据归一化，不得在此 import
任何运行时模块。
"""
from dataclasses import dataclass
from typing import Any, Dict, Optional

DEFAULT_INSTALL_DIRS = (
    r"D:\Program Files\Netease\MuMu",
    r"C:\Program Files\Netease\MuMu",
    r"D:\Program Files\Netease\MuMu Player 12",
    r"C:\Program Files\Netease\MuMu Player 12",
)

DEFAULT_BOOT_TIMEOUT = 180
DEFAULT_ACTION_TIMEOUT = 60


@dataclass
class AndroidConfig:
    enabled: bool = False
    provider: str = "mumu"
    install_dir: str = ""
    vm_index: int = 0
    boot_timeout_s: int = DEFAULT_BOOT_TIMEOUT
    action_timeout_s: int = DEFAULT_ACTION_TIMEOUT
    snapshot: bool = True

    def as_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "provider": self.provider,
            "install_dir": self.install_dir,
            "vm_index": self.vm_index,
            "boot_timeout_s": self.boot_timeout_s,
            "action_timeout_s": self.action_timeout_s,
            "snapshot": self.snapshot,
        }


def _as_int(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("1", "true", "yes", "on"):
            return True
        if v in ("0", "false", "no", "off", ""):
            return False
    if value is None:
        return default
    return bool(value)


def _as_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip()
    return str(value)


def normalize(raw: Optional[dict]) -> AndroidConfig:
    """把 config.yaml 的 android: 段归一化成 AndroidConfig。

    raw 为空 / 非 dict / 字段类型坏掉，都退化为「关闭 + 默认值」或钳制后
    的值，绝不抛异常——配置文件写错不能把整个进程带崩。
    """
    if not isinstance(raw, dict):
        return AndroidConfig()
    return AndroidConfig(
        enabled=_as_bool(raw.get("enabled"), False),
        provider=_as_str(raw.get("provider"), "mumu") or "mumu",
        install_dir=_as_str(raw.get("install_dir"), ""),
        vm_index=_as_int(raw.get("vm_index"), 0, 0, 64),
        boot_timeout_s=_as_int(raw.get("boot_timeout_s"),
                               DEFAULT_BOOT_TIMEOUT, 10, 600),
        action_timeout_s=_as_int(raw.get("action_timeout_s"),
                                 DEFAULT_ACTION_TIMEOUT, 5, 900),
        snapshot=_as_bool(raw.get("snapshot"), True),
    )


def is_enabled(cfg: Optional[dict]) -> bool:
    """总开关判定：只认 android.enabled，任何其他段都不影响。"""
    if not isinstance(cfg, dict):
        return False
    return _as_bool((cfg.get("android") or {}).get("enabled")
                    if isinstance(cfg.get("android"), dict) else False, False)


def resolve_install_dir(cfg: AndroidConfig) -> str:
    """显式配置优先；否则按已知安装位置探测；都没有返回空串。"""
    import os

    if cfg.install_dir:
        return cfg.install_dir if os.path.isdir(cfg.install_dir) else ""
    for path in DEFAULT_INSTALL_DIRS:
        if os.path.isdir(path):
            return path
    return ""
