"""检测更新 + 热更新：`python -m core.update [--check|--download|--apply]`（r1063 T251）

为什么要有：issue #15 的用户直接问「如果更新新版本，是需要卸载掉再重新下载吗」——
一个自托管项目让用户"卸载重装"才能升级，那是产品缺失，不是用户问题。

三档能力，逐档更"自动"，也逐档更需要人确认：

1. `--check`（默认）：读 GitHub Releases 最新 tag，和本机 `__version__` 比，
   结果缓存 6 小时（面板多次轮询不该打爆 API）。**只读，零风险**。
2. `--download`：把最新 release 的 zip 下到 `user_data/update/<tag>.zip`，
   打印"怎么替换"的一句话。**只下载，不动现有文件**。
3. `--apply`：把 zip 解到临时目录 → **备份当前目录** → 覆盖 → 失败自动回滚。
   成功后提示重启进程（Python 无法安全热替换已加载模块，所以"热更新"的诚实
   定义是：**文件换好 + 一次重启**，而不是假装能不断电升级）。

安全边界（写死在代码里，别为了"更自动"删掉）：
* 只从 `dengmeiluan/ticket-monitoring` 官方 release 下载；
* 覆盖前必须备份，且备份失败就中止；
* 不删用户数据目录（user_data/data/logs/config.yaml 一律跳过）。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

REPO = "dengmeiluan/ticket-monitoring"
API_LATEST = "https://api.github.com/repos/%s/releases/latest" % REPO
#: 列表接口（含 pre-release）——`/releases/latest` 会跳过 pre-release，
#: 真机实测：它返回 v1.0，而实际最新是 pre-release 的 v1.6.0。
RELEASES_LIST = ("https://api.github.com/repos/%s/releases"
                 "?per_page=30" % REPO)
USER_DATA = "user_data"
CACHE_TTL_S = 6 * 3600
#: 覆盖时**一律跳过**的路径（用户数据/配置/日志/虚拟环境）
#: 覆盖时**一律跳过**的路径。注意 `config.yaml` 也在里面——升级绝不能
#: 覆盖用户的航线/心理线/钉钉配置（写错一次就是灾难级）。
SKIP_PREFIXES = ("user_data", "data", "logs", "debug", ".git", ".venv", "venv",
                 "node_modules", "packages", "config.yaml", "config.local.yaml")


def _ssl_ctx():
    """返回 (ssl_context, 说明)。优先 certifi；都不行返回 (None, 原因)。"""
    try:
        import ssl
        ctx = ssl.create_default_context()
        try:
            import certifi
            ctx.load_verify_locations(certifi.where())
            return ctx, "certifi"
        except Exception:
            return ctx, "system"
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, str(e)[:80])


def _get(url: str, timeout: float = 8.0, headers: dict = None):
    """取 url 内容，返回 (bytes, tls_note)。

    **优先 requests**：真机实测本机 urllib 的 SSL 上下文报
    `CERTIFICATE_VERIFY_FAILED`，而 requests 的 verify=True 正常能通。
    """
    hdrs = dict(headers or {})
    hdrs.setdefault("User-Agent", "ticket-monitoring-update")
    try:
        import requests
        r = requests.get(url, timeout=timeout, headers=hdrs)
        r.raise_for_status()
        return r.content, "requests"
    except ImportError:
        pass
    except Exception as e:
        # requests 失败（断网/证书/MITM）→ 再用 urllib 试一次
        _req_err = e
        try:
            return _open_url(url, timeout=timeout, headers=hdrs)
        except Exception:
            raise _req_err
    return _open_url(url, timeout=timeout, headers=hdrs)


def _open_url(url: str, timeout: float = 8.0, headers: dict = None):
    """urllib 兜底通道（统一处理 TLS）。返回 (bytes, tls_note)。"""
    req = urllib.request.Request(url, headers=dict(
        headers or {}, **{"User-Agent": "ticket-monitoring-update"}))
    ctx, note = _ssl_ctx()
    if os.environ.get("TM_UPDATE_INSECURE") == "1":
        import ssl as _ssl
        ctx = _ssl._create_unverified_context()
        note = "insecure(按 TM_UPDATE_INSECURE=1 跳过校验)"
    if ctx is None:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(), note
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return r.read(), note


def _root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def local_version() -> str:
    try:
        import main as _m  # noqa: WPS433
        return str(getattr(_m, "__version__", "") or "")
    except Exception:
        pass
    try:
        txt = open(os.path.join(_root(), "main.py"), encoding="utf-8").read()
        m = re.search(r'__version__\s*=\s*"([^"]+)"', txt)
        return m.group(1) if m else ""
    except Exception:
        return ""


def _cache_path() -> str:
    return os.path.join(_root(), USER_DATA, "update_check.json")


def _load_cache() -> dict:
    try:
        with open(_cache_path(), encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _save_cache(rec: dict) -> None:
    try:
        p = _cache_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
    except Exception:
        pass


def _invalidate_cache() -> None:
    """升级/回滚后清掉 6 小时检查缓存。

    事故口径（r1352）：`apply()` 成功换完文件后，状态接口仍按旧缓存回答
    `has_update=true`，于是页面在“已经是最新版本”的机器上继续劝人升级，
    用户点“下载并升级”又下一遍同一个包。文件语义变了就必须让版本判定
    重新问一次远端；取不到时由 check() 自己落 err，不沿用旧结论。
    """
    try:
        os.remove(_cache_path())
    except Exception:
        pass


def _vtuple(v: str) -> tuple:
    nums = re.findall(r"\d+", str(v or ""))
    return tuple(int(x) for x in nums[:4]) or (0,)


def check(force: bool = False, timeout: float = 8.0) -> dict:
    """查最新 release 并和本机版本比。只读；结果缓存 6 小时。"""
    cached = _load_cache()
    if (not force and cached.get("at")
            and time.time() - float(cached["at"]) < CACHE_TTL_S):
        # r1213：`zip` 是**按部署形态**算出来的地址。源码部署若命中旧缓存
        # （里面只有 win64.zip、没有 zipball_url），会继续下发行包——所以
        # 这种情况强制刷新一次，之后的缓存就带 zipball_url 了。
        if deploy_mode() == "source" and not cached.get("zipball_url"):
            return check(force=True, timeout=timeout)
        cached["cached"] = True
        return cached
    out = {"ok": False, "local": local_version(), "latest": "",
           "has_update": False, "url": "", "published_at": "", "notes": "",
           "at": time.time(), "cached": False}
    try:
        raw, _tls = _get(
            RELEASES_LIST, timeout=timeout,
            headers={"Accept": "application/vnd.github+json"})
        items = json.loads(raw.decode("utf-8") or "[]")
        if isinstance(items, dict):          # 出错时 API 回对象
            raise RuntimeError(str(items.get("message") or "API 返回异常")[:80])
        best = None
        for it in items or []:
            if it.get("draft"):
                continue
            t = str(it.get("tag_name") or "").strip()
            if not t:
                continue
            if best is None or _vtuple(t) > _vtuple(best.get("tag_name")):
                best = it
        if best is None:
            raise RuntimeError("release 列表为空")
        data = best
        tag = str(data.get("tag_name") or "").strip()
        out.update({"ok": True, "tls": _tls, "latest": tag,
                    "prerelease": bool(data.get("prerelease")),
                    "url": str(data.get("html_url") or ""),
                    "published_at": str(data.get("published_at") or ""),
                    "notes": str(data.get("body") or "")[:600],
                    # r1213：源码部署要靠它拿源码归档（GitHub 永远提供）
                    "zipball_url": str(data.get("zipball_url") or ""),
                    # r1261：显式按部署形态选资产（源码→源码包；exe→发行包）
                    "zip": _pick_zip(data, deploy_mode())})
        # 滚动 release：tag 恒为 v1.0，真实版本在正文里。
        _body_ver = _parse_release_version(str(data.get("body") or ""))
        _body_commit = _parse_release_commit(str(data.get("body") or ""))
        _local_commit, _csrc = local_commit()
        if _body_ver:
            out["latest"] = "v" + _body_ver if not _body_ver.startswith("v") \
                else _body_ver
        out["latest_commit"] = _body_commit
        out["local_commit"] = _local_commit
        _new_ver = bool(out["latest"]) and \
            _vtuple(out["latest"]) > _vtuple(out["local"])
        # 只有**打包安装**才比提交（开发树 HEAD 领先发布是常态，比了就是误报）
        _same_ver_new_build = (
            _csrc == "build"
            and bool(out["latest"])
            and _vtuple(out["latest"]) == _vtuple(out["local"])
            and bool(_body_commit) and bool(_local_commit)
            and not _body_commit.startswith(_local_commit)
            and not _local_commit.startswith(_body_commit))
        out["commit_source"] = _csrc
        out["has_update"] = _new_ver or _same_ver_new_build
        out["reason"] = ("新版本 %s" % out["latest"]) if _new_ver else (
            "同版本(%s)但有新构建（源码 %s ≠ 本机 %s）"
            % (out["local"], _body_commit[:8], _local_commit[:8])
            if _same_ver_new_build else "已是最新")
    except Exception as e:
        out["err"] = "%s: %s" % (type(e).__name__, str(e)[:120])
    _save_cache(out)
    return out


def deploy_mode() -> str:
    """当前部署形态：`binary`（PyInstaller 冻结的 exe）/ `source`（源码 checkout）。"""
    return "binary" if getattr(sys, "frozen", False) else "source"


def _pick_zip(release: dict, mode: str = "") -> str:
    """挑下载资产——**必须按部署形态选**。

    r1209 实测事故：源码部署下这里一律挑 `*-win64.zip`，而那个包的顶层是
    `TicketMonitor.exe` + `_internal/`，**没有 `main.py`/`webui.py`**。
    于是「一键升级」备份了 300 MB、把 exe 载荷重铺一遍、源码一行没变，还返回成功。
    """
    # r1261：**默认仍是 legacy（binary）语义**——存量调用方（含测试夹具）不传 mode 时
    # 行为不变；只有 `check()` 会显式传 `deploy_mode()`，由部署形态决定选哪种资产。
    mode = mode or "binary"
    assets = release.get("assets") or []
    zips = [a for a in assets if str(a.get("name", "")).lower().endswith(".zip")]
    if mode == "source":
        for kw in ("source", "src", "code"):
            for a in zips:
                if kw in str(a.get("name", "")).lower():
                    return str(a.get("browser_download_url") or "")
        # GitHub 永远给源码归档：release 没挂 source 资产时用它
        zb = str(release.get("zipball_url") or release.get("tarball_url") or "")
        if zb:
            return zb
        # r1261：连 zipball 都没有（离网/私有/测试夹具）→ 退回普通 zip 资产。
        # 真下成发行包也不会误装：`apply()` 有形状校验会拒绝（r1211）。
        return str(zips[0].get("browser_download_url") or "") if zips else ""
    if not zips:
        return ""
    for kw in ("win", "windows"):
        for a in zips:
            if kw in str(a.get("name", "")).lower():
                return str(a.get("browser_download_url") or "")
    return str(zips[0].get("browser_download_url") or "")


def download(url: str = "", timeout: float = 120.0) -> dict:
    """下载 release zip 到 `user_data/update/<tag>.zip`（不动现有文件）。"""
    info = check()
    # r1352：没有新版本时**不许下载**。旧实现只看“有没有 zip 地址”，
    # 于是“立即升级”会把当前版本再下一遍、再覆盖一遍（用户看到的就是
    # “最新版本仍然需要更新”）。显式传 url 的调用（测试/高级用法）不拦。
    if not url and info.get("ok") and not info.get("has_update"):
        return {"ok": False, "err": "已是最新版本（%s），无需下载"
                                    % (info.get("latest") or info.get("local") or "")}
    url = url or str(info.get("zip") or "")
    if not url:
        return {"ok": False, "err": "没有可下载的 zip 资产（或检查更新失败）"}
    tag = str(info.get("latest") or "latest").replace("/", "_")
    d = os.path.join(_root(), USER_DATA, "update")
    os.makedirs(d, exist_ok=True)
    dst = os.path.join(d, "%s.zip" % tag)
    try:
        blob, _tls = _get(url, timeout=timeout)
        with open(dst, "wb") as f:
            f.write(blob)
        size = os.path.getsize(dst)
        return {"ok": size > 0, "path": dst, "size": size, "tag": tag}
    except Exception as e:
        return {"ok": False, "err": "%s: %s" % (type(e).__name__, str(e)[:120])}


#: 项目根标志（zip 包装层判定用）
_ROOT_MARKERS = ("main.py", "webui.py", "requirements.txt", "core", "crawlers")


def _looks_like_project_root(path: str) -> bool:
    """该目录是否像本项目根（而不是恰好只有一个顶层目录的 zip）。"""
    try:
        names = set(os.listdir(path))
    except Exception:
        return False
    return any(m in names for m in _ROOT_MARKERS)


def _skip(rel: str) -> bool:
    """该相对路径是否属于"升级不得覆盖"的用户资产/环境目录。

    r1063 T288：归一化**不能**用 `lstrip("./")`——它会剥掉开头所有 `.`，
    于是 `.git/config` 变成 `git/config`，`.git` 前缀永远匹配不上，
    `.git/` 这条保护形同虚设（升级包若带 `.git/` 会覆盖用户仓库）。
    """
    rel = str(rel or "").replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    rel = rel.lstrip("/")
    return any(rel == p or rel.startswith(p + "/") for p in SKIP_PREFIXES)


def _git_dirty(root: str) -> list:
    """工作树里相对 git HEAD 有改动的文件（取不到 git 时返回空 = 不拦）。

    r1243：这是**用血换来的护栏**。2026-11-10 15:24，一次「一键升级」用源码包
    覆盖了整个工作树，当天 24 处未提交改动被当成"待覆盖文件"直接抹掉。
    `apply()` 自己的备份救不了这种情况——它只备份"将被覆盖的文件"，
    而连续几次升级后，备份里存的可能已经是上一次覆盖后的状态。
    """
    try:
        p = subprocess.run(["git", "status", "--porcelain"], cwd=root,
                           capture_output=True, text=True, timeout=20)
        if p.returncode != 0:
            return []
        return [ln for ln in (p.stdout or "").splitlines() if ln.strip()]
    except Exception:
        return []


_TREE_SKIP = {".git", "user_data", "user_data_free", "data", "logs", "debug",
              "__pycache__", "node_modules", "dist", "dist_package", "_internal",
              ".venv", "venv", "_scratch", "_tools", "_vendor", "_build_check",
              "site-packages", ".mypy_cache", ".pytest_cache",
              # 构建产物与安装包不是"源码树"，而且体积巨大（本机实测
              # `_build` 一家 100+MB、`build` 50MB、根目录 exe 12MB）——
              # 打进安全网只会把 8 秒的备份拖成几分钟、几百 MB。
              "_build", "build", "packages", "sdk", "sdk_tools"}
_TREE_SKIP_EXT = (".exe", ".pkg", ".pyz", ".dll", ".so", ".dylib", ".zip",
                  ".7z", ".tar", ".gz", ".whl")
_TREE_SNAP_DIR = "treetars"


def snapshot_tree(root: str = "", tag: str = "") -> str:
    """把**源码树**打成 zip（升级前先存一份，出事了能整树还原）。

    为什么需要（r1346，用事故换的）：`apply()` 原本只备份"将被覆盖的文件"，
    15:24 那次用源码包覆盖工作树时，连做三次后备份里存的已经是**上一次覆盖后**
    的状态——当天 24 处未提交改动就是这么丢的。整树快照与"覆盖清单"无关，
    任何覆盖动作都不可能把它变成脏数据。

    扫描范围只含**可执行/可测试/文档**那部分：`_scratch`、`_tools`、`user_data`、
    `.git` 等一律跳过（本机实测 `_scratch` 一家就 12.7GB/3.2 万文件，
    真机上会把升级前的快照拖到 7 分钟以上——安全网不能比风险还慢）。
    """
    root = root or _root()
    out_dir = os.path.join(root, USER_DATA, "update", _TREE_SNAP_DIR)
    os.makedirs(out_dir, exist_ok=True)
    name = tag or time.strftime("%Y%m%d_%H%M%S")
    out = os.path.join(out_dir, "tree_%s.zip" % name)
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED,
                         compresslevel=1) as z:
        for dirpath, dirnames, filenames in os.walk(root):
            rel_dir = os.path.relpath(dirpath, root)
            if rel_dir != ".":
                top = rel_dir.split(os.sep)[0]
                if top in _TREE_SKIP:
                    dirnames[:] = []
                    continue
            dirnames[:] = [d for d in dirnames if d not in _TREE_SKIP]
            for fn in filenames:
                if fn.endswith(".pyc") or fn.lower().endswith(_TREE_SKIP_EXT):
                    continue
                full = os.path.join(dirpath, fn)
                try:
                    z.write(full, os.path.relpath(full, root))
                    n += 1
                except Exception:
                    continue
    return out if n else ""


def prune_tree_snaps(root: str = "", keep: int = 2) -> list:
    """只留最近 keep 份整树快照（每份几十 MB，不设上限会把盘吃光）。"""
    root = root or _root()
    out_dir = os.path.join(root, USER_DATA, "update", _TREE_SNAP_DIR)
    if not os.path.isdir(out_dir):
        return []
    files = [os.path.join(out_dir, f) for f in os.listdir(out_dir)
             if f.startswith("tree_") and f.endswith(".zip")]
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    removed = []
    for p in files[max(0, int(keep)):]:
        try:
            os.remove(p)
            removed.append(p)
        except Exception:
            pass
    return removed


def apply(zip_path: str = "", force: bool = False) -> dict:
    """把 zip 覆盖到项目目录：**先备份，失败回滚**；用户数据目录一律跳过。"""
    root = _root()
    if not zip_path:
        info = check()
        tag = str(info.get("latest") or "latest").replace("/", "_")
        zip_path = os.path.join(root, USER_DATA, "update", "%s.zip" % tag)
    if not os.path.isfile(zip_path):
        return {"ok": False, "err": "找不到更新包：%s（先跑 --download）"
                                    % zip_path}
    tmp = tempfile.mkdtemp(prefix="tm_update_")
    bak = os.path.join(root, USER_DATA, "update",
                       "backup_%s" % time.strftime("%Y%m%d_%H%M%S"))
    # r1243：**未提交改动不许被静默覆盖**。工作树脏时直接拒绝，让用户先收口
    # （或显式 force）。这条护栏就是在 15:24 那次事故之后加的。
    if not force:
        dirty = _git_dirty(root)
        if dirty:
            return {"ok": False,
                    "err": ("工作树有 %d 处未提交改动，升级会覆盖它们；"
                            "请先提交/备份，或显式传 force=true 强行覆盖"
                            % len(dirty)),
                    "dirty": dirty[:20], "dirty_n": len(dirty),
                    "how": "面板「版本与更新」默认不带 force；命令行可用 "
                           "python -m core.update --apply --force"}
    try:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp)        # zip 里可能多套一层目录
        base = tmp
        entries = os.listdir(tmp)
        if len(entries) == 1 and os.path.isdir(os.path.join(tmp, entries[0])):
            # r1063 T264b：**只在它确实像项目根时才剥一层**。
            # 早期版本只看"唯一且是目录"，于是 zip 里只有 `core/` 时把它当成
            # 包装层，`relpath` 退化成 `mod.py`，文件被静默摊到项目根——
            # 由 tests/test_r1063_update_apply_safety.py 逮到。
            cand = os.path.join(tmp, entries[0])
            if _looks_like_project_root(cand):
                base = cand
        # r1211：**形状校验**。源码根不接受发行包——exe 包里没有业务代码，
        # 铺一遍只会白占 300 MB 备份、源码一行不变，却报成功（r1209 实测）。
        try:
            _root_names = set(os.listdir(root))
        except Exception:
            _root_names = set()
        try:
            _pkg_names = set(os.listdir(base))
        except Exception:
            _pkg_names = set()
        # 只有**确实像发行包**时才拦（TicketMonitor.exe / _internal 等）。
        # 其它"啥也没有"的包仍然走老分支报「没有可覆盖的文件」——口径更准，
        # 也保住既有门禁 test_r1189::test_all_skipped_is_an_error。
        _looks_binary = bool(
            {"TicketMonitor.exe", "TicketMonitor", "_internal"} & _pkg_names)
        if (({"main.py", "webui.py"} & _root_names) and _looks_binary
                and not ({"main.py", "webui.py"} & _pkg_names)):
            return {"ok": False,
                    "err": ("这个包是发行包（TicketMonitor.exe / _internal），"
                            "里面没有 main.py / webui.py；当前是源码部署，"
                            "升级请下载源码包或 git pull。已拒绝，未改动任何文件。"),
                    "pkg_top": sorted(_pkg_names)[:6]}
        # r1346：覆盖任何文件之前，先打一份**与覆盖清单无关**的源码树快照。
        # 放在形状校验**之后**：被拒绝的包不该在磁盘上留下任何东西
        # （test_r1211 的口径就是「拒绝时不留新目录」）。
        try:
            tree_snap = snapshot_tree(root)
        except Exception:
            tree_snap = ""
        if not tree_snap:
            return {"ok": False,
                    "err": "升级前源码树快照失败，已中止（无安全网不覆盖工作树）"}
        try:
            prune_tree_snaps(root, keep=2)
        except Exception:
            pass
        # ① 备份（只备份将被覆盖的代码文件）
        os.makedirs(bak, exist_ok=True)
        copied = 0
        for dirpath, _dirnames, filenames in os.walk(base):
            for fn in filenames:
                src = os.path.join(dirpath, fn)
                rel = os.path.relpath(src, base).replace("\\", "/")
                if _skip(rel):
                    continue
                dst = os.path.join(root, rel)
                os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
                if os.path.isfile(dst):
                    bp = os.path.join(bak, rel)
                    os.makedirs(os.path.dirname(bp) or ".", exist_ok=True)
                    shutil.copy2(dst, bp)
                copied += 1
        if copied == 0:
            return {"ok": False, "err": "更新包里没有可覆盖的文件"}
        # ② 覆盖
        for dirpath, _dirnames, filenames in os.walk(base):
            for fn in filenames:
                src = os.path.join(dirpath, fn)
                rel = os.path.relpath(src, base).replace("\\", "/")
                if _skip(rel):
                    continue
                dst = os.path.join(root, rel)
                os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
                shutil.copy2(src, dst)
        # r1210：成功即按保留策略清理老备份（默认留 3 个）——否则一天点几次
        # 「一键升级」就会攒下几个 GB（本机实测 26 个 = 7.58 GB）。
        pruned = {}
        try:
            pruned = prune_backups(3)
        except Exception:
            pruned = {}
        # r1352：文件已换，旧“有新版本”缓存立即作废；否则状态接口在 6 小时内
        # 仍会回答 has_update=true，页面就会在最新版本上继续劝升级/重复下载。
        _invalidate_cache()
        return {"ok": True, "files": copied, "backup": bak,
                "pruned": pruned,
                "next": "请重启程序生效（python main.py 或关闭后重开）"}
    except Exception as e:
        # ③ 回滚
        rolled = 0
        try:
            for dirpath, _dn, filenames in os.walk(bak):
                for fn in filenames:
                    src = os.path.join(dirpath, fn)
                    rel = os.path.relpath(src, bak)
                    dst = os.path.join(root, rel)
                    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
                    shutil.copy2(src, dst)
                    rolled += 1
        except Exception:
            pass
        return {"ok": False, "err": "%s: %s" % (type(e).__name__, str(e)[:140]),
                "rolled_back": rolled, "backup": bak}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def list_backups() -> list:
    """历次升级留下的备份目录（**新→旧**）。

    为什么要有：`apply()` 失败能自动回滚，但**成功之后**用户仍可能需要退回去
    （新版本某些渠道不通、页面不习惯）。没有这个列表，"回滚"就只是代码里
    一句好听的话。目录形如 `user_data/update/backup_YYYYmmdd_HHMMSS`。
    """
    root = _root()
    d = os.path.join(root, USER_DATA, "update")
    out = []
    try:
        for name in os.listdir(d):
            p = os.path.join(d, name)
            if not name.startswith("backup_") or not os.path.isdir(p):
                continue
            try:
                at = os.path.getmtime(p)
            except OSError:
                at = 0.0
            files = sum(len(fs) for _dp, _dn, fs in os.walk(p))
            out.append({"path": p, "name": name, "at": at, "files": files})
    except Exception:
        return []
    out.sort(key=lambda x: x["at"], reverse=True)
    return out


def rollback(bak: str = "") -> dict:
    """把某个备份目录里的文件**拷回项目根**（缺省用最新一个）。

    边界与 `apply()` 完全一致：只覆盖备份里存在的文件；用户数据/配置/日志
    依然不会被写（备份里本来就不含它们，`_skip` 再加一道）。
    """
    root = _root()
    if not bak:
        cands = list_backups()
        if not cands:
            return {"ok": False, "err": "没有可用的备份（升级成功后才会留下备份）"}
        bak = cands[0]["path"]
    if not os.path.isdir(bak):
        return {"ok": False, "err": "备份目录不存在：%s" % bak}
    rolled = 0
    try:
        for dirpath, _dn, filenames in os.walk(bak):
            for fn in filenames:
                src = os.path.join(dirpath, fn)
                rel = os.path.relpath(src, bak).replace("\\", "/")
                if _skip(rel):
                    continue
                dst = os.path.join(root, rel)
                os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
                shutil.copy2(src, dst)
                rolled += 1
    except Exception as e:
        return {"ok": False, "err": "%s: %s" % (type(e).__name__, str(e)[:140]),
                "rolled": rolled, "backup": bak}
    # r1352：回滚同样换了文件，旧检查结果必须作废。
    _invalidate_cache()
    return {"ok": True, "rolled": rolled, "backup": bak,
            "next": "请重启程序生效（回滚同样是文件替换）"}


def prune_backups(keep: int = 3) -> dict:
    """只保留最近 `keep` 个备份，其余删掉（默认 3）。

    为什么必须要有：每次 `apply()` 都会把**将被覆盖的代码文件**整份备份下来
    （实测一次 ≈ 996 个文件 / ≈ 300 MB）。没有保留策略时，一天点几次
    「一键升级」就能吃掉几个 GB —— 本机实测 26 个备份 = **7.58 GB**。
    删除只发生在 `user_data/update/backup_*` 内部，绝不碰用户数据。
    """
    try:
        keep = max(1, int(keep))
    except (TypeError, ValueError):
        keep = 3
    baks = list_backups()
    removed, freed = [], 0
    for b in baks[keep:]:
        p = b["path"]
        try:
            size = sum(os.path.getsize(os.path.join(dp, f))
                       for dp, _dn, fs in os.walk(p) for f in fs)
            shutil.rmtree(p, ignore_errors=True)
            if not os.path.isdir(p):
                removed.append(b["name"])
                freed += size
        except Exception:
            continue
    return {"ok": True, "kept": [b["name"] for b in baks[:keep]],
            "removed": removed, "freed_bytes": freed}


def _main(argv=None) -> int:                        # pragma: no cover - CLI
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--apply" in argv:
        z = ""
        for i, a in enumerate(argv):
            if a == "--zip" and i + 1 < len(argv):
                z = argv[i + 1]
        print(json.dumps(apply(z, force="--force" in argv), ensure_ascii=False,
                         indent=1))
        return 0
    if "--download" in argv:
        print(json.dumps(download(), ensure_ascii=False, indent=1))
        return 0
    rep = check(force="--force" in argv)
    if not rep.get("ok"):
        print("✗ 检查更新失败：%s" % rep.get("err", "未知"))
        return 1
    print("本机版本：%s" % rep["local"])
    print("最新版本：%s（%s）" % (rep["latest"], rep.get("published_at", "")))
    if rep.get("has_update"):
        print("→ 有新版本。升级：python -m core.update --download 然后 --apply")
        print("  发布页：%s" % rep.get("url", ""))
    else:
        print("✓ 已是最新")
    return 0


if __name__ == "__main__":                           # pragma: no cover
    raise SystemExit(_main())

def _parse_release_version(body: str) -> str:
    """从 release 正文取「当前版本：X.Y.Z」（滚动 release 的唯一可信版本号）。"""
    import re as _re
    m = _re.search(r"当前版本[:：]\s*v?([\d.]+)", body or "")
    return m.group(1) if m else ""


def _parse_release_commit(body: str) -> str:
    """从 release 正文取「源码 <hash>」（用于判断"同版本但已重建"）。"""
    import re as _re
    m = _re.search(r"源码[^0-9a-f]{0,6}([0-9a-f]{7,40})", body or "")
    return m.group(1) if m else ""


def local_commit() -> tuple:
    """本机源码提交 → `(hash, 来源)`；来源 `git`=开发树，`build`=打包安装。

    为什么要分来源：开发树的 HEAD 通常**领先**于已发布源码，
    拿它跟 release 里的源码比会误报"有新构建"；只有打包安装（无 .git，
    靠 `BUILD_COMMIT` 记录构建来源）才该做这个比较。
    """
    import subprocess
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=_root(),
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and (r.stdout or "").strip():
            return (r.stdout or "").strip(), "git"
    except Exception:
        pass
    try:
        with open(os.path.join(_root(), "BUILD_COMMIT"), encoding="utf-8") as f:
            return f.read().strip(), "build"
    except Exception:
        return "", ""
