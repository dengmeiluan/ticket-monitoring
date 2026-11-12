# -*- coding: utf-8 -*-
"""**不可信压缩包**的唯一解压入口（zip slip / 符号链接穿透防护）。

背景（社区 PR #17 提交的安全报告 + 我们的实测）：

- `ZipFile.extractall()` 会把成员名直接拼到目标目录上；
- 现代 CPython 会**去掉**盘符、前导分隔符和 `..` 分量（实测 3.11 Windows：
  `../escaped.txt` 落成 `dest/escaped.txt`，`/abs.txt`、`C:/evil.txt` 同样被"关进来"），
  所以这两类在 CPython ≥3.6 上**已不可直接利用**；
- 但**符号链接**它不管：成员 `link -> /etc` 先被建成软链，随后成员 `link/passwd`
  就会顺着软链写到目标目录**之外**。Linux/macOS 上 `os.symlink` 无需特权，
  而本项目正好发行 Linux/macOS 包——这条才是真能逃出去的路径。

所以这里的策略是**双保险**：既拒绝 CPython 已经帮我们清掉的 `..`/绝对路径
（换个解释器或将来回归都不再依赖它），也拒绝符号链接/设备节点等特殊成员。

用法（升级包、离线包、任何"别人给的 zip"都走这里）：

    from core.safezip import safe_extract
    with zipfile.ZipFile(path) as z:
        written = safe_extract(z, dest)

失败一律抛 `UnsafeArchiveError`（`RuntimeError` 子类，便于调用方
`except Exception` 兜住并如实回 `{"ok": False, "err": ...}`）。
"""
from __future__ import annotations

import os
import re
import shutil
import stat

__all__ = ["UnsafeArchiveError", "safe_extract", "is_safe_member"]

# Windows 盘符（`C:`、`c:/x`）与 UNC（`\\host\share`、`//host/share`）
_DRIVE_RE = re.compile(r"^[A-Za-z]:")


class UnsafeArchiveError(RuntimeError):
    """压缩包里有不安全成员（越界路径 / 符号链接 / 设备节点 / 成员过多）。"""


def _mode_of(info) -> int:
    try:
        return int((info.external_attr >> 16) & 0xFFFF)
    except Exception:
        return 0


def is_safe_member(name: str, root: str) -> bool:
    """成员名是否安全：非空、非绝对、无 `..` 分量、解析后仍在 root 内。"""
    if not name:
        return False
    norm = name.replace("\\", "/")
    if norm.startswith("/") or norm.startswith("//") or _DRIVE_RE.match(norm):
        return False
    parts = [p for p in norm.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return False
    target = os.path.realpath(os.path.join(root, *parts))
    return target == root or target.startswith(root + os.sep)


def safe_extract(z, dest: str, *, max_entries: int = 200_000,
                 max_total_bytes: int = 0) -> list:
    """把 `z`（ZipFile）解到 `dest`，**先全量校验再落盘**；返回写出的相对路径列表。

    - 任一成员不安全 → 抛 `UnsafeArchiveError`，且**一个字节都不写**；
    - 目录成员只建目录；
    - POSIX 下保留可执行位（升级包里 `start.sh` 之类要能跑）；
    - `max_total_bytes > 0` 时限制解压后总字节（防 zip bomb，默认不限制，
      避免误伤正常的大升级包）。
    """
    root = os.path.realpath(dest)
    os.makedirs(root, exist_ok=True)

    infos = z.infolist()
    if len(infos) > max_entries:
        raise UnsafeArchiveError("成员过多（%d > %d）：%s"
                                 % (len(infos), max_entries, dest))

    plans, total = [], 0
    for info in infos:
        name = info.filename
        mode = _mode_of(info)

        # 特殊成员一律拒绝：符号链接、fifo、字符/块设备、socket。
        # 只看**文件类型位**：`writestr()` 造的成员 external_attr 常只有权限位
        # （没有 S_IFREG），那属于普通文件，不能误杀。
        ftype = mode & 0o170000
        if ftype == stat.S_IFLNK:
            raise UnsafeArchiveError("拒绝符号链接成员：%s" % name)
        if ftype and ftype not in (stat.S_IFREG, stat.S_IFDIR):
            raise UnsafeArchiveError("拒绝特殊文件成员：%s" % name)

        if info.is_dir() or name.endswith(("/", "\\")):
            if not is_safe_member(name.rstrip("/\\") + "/x", root):
                raise UnsafeArchiveError("拒绝不安全的目录成员：%s" % name)
            continue

        if not is_safe_member(name, root):
            raise UnsafeArchiveError("拒绝不安全的升级包成员：%s" % name)

        norm = name.replace("\\", "/")
        parts = [p for p in norm.split("/") if p not in ("", ".")]
        target = os.path.join(root, *parts)

        size = int(getattr(info, "file_size", 0) or 0)
        total += size
        if max_total_bytes and total > max_total_bytes:
            raise UnsafeArchiveError("解压后体积超限（%d > %d）"
                                     % (total, max_total_bytes))
        plans.append((info, target, mode))

    written = []
    for info, target, mode in plans:
        parent = os.path.dirname(target)
        if parent:
            os.makedirs(parent, exist_ok=True)
        # 目标若已存在且是符号链接，realpath 已在上面把它解析出去并拒绝；
        # 这里再兜一层：不顺着任何软链写。
        if os.path.islink(target):
            raise UnsafeArchiveError("目标位置是符号链接，拒绝写入：%s" % target)
        with z.open(info) as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst, 1 << 20)
        if os.name == "posix" and mode & 0o111:
            try:
                os.chmod(target, (mode & 0o777) | 0o600)
            except OSError:
                pass
        written.append(os.path.relpath(target, root))
    return written
