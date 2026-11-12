"""装机自检与傻瓜化引导（r1063 T43）。

目标：从 GitHub 下载解压后，一条命令告诉用户「还差什么」，并能把**安全的那部分**
自动补齐（复制配置、建目录、装依赖、装浏览器内核）。

设计纪律（与本仓其它自检一致）：
  * **只报能证明的**：每项都给出可复现的判据（文件在不在 / 能不能 import /
    命令能不能跑），不猜；
  * **--fix 只做安全动作**：复制/建目录/装依赖/装浏览器内核。**不碰**账号、不碰
    登录、不改采集策略——那些必须人来做；
  * 退出码：0 = 可以开跑；1 = 还差东西（脚本可直接用 `if !` 判断）。

用法：
    python -m core.setup_check            # 只检查
    python -m core.setup_check --fix      # 检查 + 自动补齐安全项
"""
from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys

MIN_PY = (3, 11)

OK, WARN, BAD = "ok", "warn", "bad"


def _root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# r1886：App 渠道开启的**可直接粘贴**的入口（issue #16 的诉求）。
_APP_ON_HINT = ("想采 App 渠道就三条命令：\n"
                "    1) python -m core.setup_check --fix"
                "（装依赖/内核，必要时重启模拟器）\n"
                "    2) python scripts/setup_device.py --apply --reboot "
                "--enable-app-channels（装 App 并写进 platforms）\n"
                "    3) 打开 http://127.0.0.1:8765「配置」确认 5 个 App 已勾选\n"
                "    细节与卡点见 docs/APP_CHANNELS.md「开启 App 渠道（三步）」")


def _row(level, name, detail, fix="", action=""):
    """一行检查结果。`action` 是**机器可判**的修复动作 id（`fix` 只给人看）。"""
    return {"level": level, "name": name, "detail": detail, "fix": fix,
            "action": action}


def check_python():
    v = sys.version_info
    if v[:2] >= MIN_PY:
        return _row(OK, "Python 版本", "%d.%d.%d" % v[:3])
    return _row(BAD, "Python 版本", "需要 %d.%d+，当前 %d.%d"
                % (MIN_PY[0], MIN_PY[1], v[0], v[1]),
                "装 Python %d.%d 后重开终端" % MIN_PY, action="manual")


def check_platform():
    """宿主平台与本机可用能力（r1453）。

    为什么单列：App 渠道依赖 Windows + MuMu，但自检以前只在
    `android.enabled` 后才提 App；Linux/macOS 用户看到的是「未启用」，
    容易读成「打开开关就能用」。这里第一步就把平台边界说清：
    网页渠道三平台可用；App 渠道仅 Windows + MuMu。
    """
    import platform as _pf
    sysname = _pf.system()
    label = {"Windows": "Windows", "Darwin": "macOS",
             "Linux": "Linux"}.get(sysname, sysname or "未知")
    arch = _pf.machine() or "?"
    detail = "%s %s · Python %d.%d" % (
        label, arch, sys.version_info[0], sys.version_info[1])
    if sysname == "Windows":
        detail += "；网页渠道可用；App 渠道可用（需 MuMu + VT）"
        fix = "App 渠道按 README「Android 模拟器」三步：setup_check → setup_device → --app-status"
    elif sysname in ("Darwin", "Linux"):
        detail += "；网页渠道可用；App 渠道仅 Windows + MuMu，本机不适用"
        fix = ("无头 Linux 缺 Chromium 系统库时："
               "python -m playwright install-deps chromium") if sysname == "Linux" else ""
    else:
        detail += "；网页渠道可能可用；App 渠道仅 Windows + MuMu"
        fix = "按 README「安装与运行」确认系统依赖"
    return _row(OK, "运行平台", detail, fix)


def check_modules(names=("yaml", "httpx", "playwright")):
    miss = []
    for n in names:
        try:
            importlib.import_module(n)
        except Exception:
            miss.append(n)
    if not miss:
        return _row(OK, "Python 依赖", "已装：%s" % "、".join(names))
    return _row(BAD, "Python 依赖", "缺：%s" % "、".join(miss),
                "pip install -r requirements.txt", action="install_deps")


def _is_retired(root: str, plat: str) -> bool:
    """该渠道是不是**永久停服已退役**（读它的停服记忆）。"""
    try:
        import json
        import time
        p = os.path.join(root, "user_data", str(plat), "service_closed.json")
        with open(p, encoding="utf-8") as f:
            rec = json.load(f) or {}
        return bool(rec.get("permanent")) and float(
            rec.get("until") or 0) > time.time()
    except Exception:
        return False


def check_captcha_backend():
    """简易验证码识别后端（ddddocr）在不在。

    为什么单列一行：它是**可选的**，不装也能采；但装了才能自动过
    「简单滑块 / 文字 / 算数」这类通用验证（强人机验证不在此列）。
    以前它只躺在 requirements 的注释里，自检不查、一键引导不装——
    用户看到面板写「识别后端缺失」却不知道怎么办。
    """
    try:
        import ddddocr  # noqa: F401
        return _row(OK, "识别后端", "ddddocr 已装（简易滑块/文字/算数可自动尝试）")
    except Exception:
        pass
    return _row(WARN, "识别后端",
                "未装 ddddocr：简易滑块/文字/算数类验证只能走基础兜底"
                "（强人机验证不受影响）",
                "pip install ddddocr", action="install_deps")


def check_browser():
    """Playwright 的 Chromium 有没有装好（下载后第一次必须先装内核）。

    判据走**文件系统**（`ms-playwright` 缓存目录里有没有 `chromium-*`），
    不真的启动 Playwright：启动一次会留下未回收的 asyncio 任务，在自检里
    刷一脸噪声，还慢好几秒。
    """
    try:
        import playwright  # noqa: F401
    except Exception:
        return _row(BAD, "浏览器内核", "playwright 没装，无法检查",
                    "pip install -r requirements.txt")
    roots = []
    for env in ("PLAYWRIGHT_BROWSERS_PATH",):
        v = os.environ.get(env)
        if v:
            roots.append(v)
    la = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    roots += [os.path.join(la, "ms-playwright"),
              os.path.expanduser("~/.cache/ms-playwright")]
    for root in roots:
        try:
            names = os.listdir(root)
        except OSError:
            continue
        if any(n.startswith("chromium") for n in names):
            return _row(OK, "浏览器内核", "chromium 就绪（%s）" % root)
    return _row(BAD, "浏览器内核", "没找到 chromium（缓存目录都不存在或为空）",
                "python -m playwright install chromium",
                action="install_browser")


def check_config():
    root = _root()
    cfg = os.path.join(root, "config.yaml")
    example = os.path.join(root, "config.example.yaml")
    if os.path.exists(cfg):
        try:
            import yaml
            with open(cfg, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            users = data.get("users") or []
            plats = (users[0].get("platforms") if users else []) or []
            if not plats:
                return _row(WARN, "配置", "config.yaml 里还没有订阅渠道",
                            "在 config.yaml 的 users[].platforms 里填渠道名")
            # 未订阅但要能采的渠道必须**点名**：飞猪 App 之所以一条都没采到，
            # 就是因为"未订阅"这件事没人告诉他（实测近 30 天账本零记录）。
            try:
                from core.channels import (APP_CHANNELS as _A,
                                           BROWSER_CHANNELS as _B)
                universe = list(_B) + list(_A)
            except Exception:
                universe = []
            # 区分「没订阅」与「**已退役（停服）**」（r1063 T68）：
            # 后者不该再劝人去开——开了也是白跑。
            retired, rest = [], []
            for p in universe:
                if p in plats:
                    continue
                if _is_retired(root, p):
                    retired.append(p)
                else:
                    rest.append(p)
            if retired:
                head = _row(
                    OK, "配置",
                    "%d 个用户，订阅 %d 个渠道；已退役 %d 个通路：%s"
                    "（永久停服，数据由 App 通路承担）"
                    % (len(users), len(plats), len(retired),
                       "、".join(retired)))
                if rest:
                    head["detail"] += "；未订阅 %d 个：%s" % (
                        len(rest), "、".join(rest))
                    head["fix"] = _APP_ON_HINT
                return head
            if rest:
                return _row(WARN, "配置",
                            "%d 个用户，订阅 %d 个渠道；未订阅 %d 个：%s"
                            % (len(users), len(plats), len(rest),
                               "、".join(rest)),
                            _APP_ON_HINT)
            return _row(OK, "配置", "%d 个用户，订阅 %d 个渠道（全集已覆盖）"
                        % (len(users), len(plats)))
        except Exception as e:
            return _row(BAD, "配置", "config.yaml 读不动：%s" % str(e)[:80],
                        "检查 YAML 缩进/编码（必须是 UTF-8）")
    if os.path.exists(example):
        return _row(BAD, "配置", "没有 config.yaml（有示例）",
                    "cp config.example.yaml config.yaml 然后填账号/渠道",
                    action="create_config")
    return _row(BAD, "配置", "config.yaml 与示例都缺失", "重新下载仓库",
                action="manual")


def check_dirs():
    root = _root()
    need = ("data", "user_data")
    miss = [d for d in need if not os.path.isdir(os.path.join(root, d))]
    if not miss:
        return _row(OK, "数据目录", "data/ 与 user_data/ 都在")
    return _row(WARN, "数据目录", "缺：%s" % "、".join(miss),
                "程序首次启动会自建；也可以手动 mkdir",
                action="mkdir")


def _source_version() -> str:
    """源码版本（`main.py` 的 `__version__`）。读不到返回空串。"""
    try:
        import re
        txt = io_open("main.py").read()
        m = re.search(r'__version__\s*=\s*"([^"]+)"', txt)
        return m.group(1) if m else ""
    except Exception:
        return ""


def io_open(path: str):
    import io
    return io.open(path, encoding="utf-8", errors="replace")


def check_running_instance(port_hint: int = 0) -> dict:
    """本机是否有实例在跑，以及**它跑的是不是这份源码**（r1063 T97）。

    为什么要单列：发行版和源码版本不一致时，界面一切正常、但源码里的改进
    **一项都没生效**——这是最贵的误解（"我改了怎么没效果"）。
    """
    src = _source_version() or "未知"
    ports = [port_hint] if port_hint else [8765, 8000, 5000]
    for port in ports:
        try:
            import json
            import urllib.request
            with urllib.request.urlopen(
                    "http://127.0.0.1:%d/api/state" % port, timeout=2.0) as r:
                st = json.loads(r.read().decode("utf-8") or "{}")
        except Exception:
            continue
        run = str(st.get("version") or "?")
        if st.get("version") == "demo":
            continue
        if run and src and run != src and run != "?":
            return _row(
                WARN, "运行实例",
                "本机在跑 v%s（端口 %d），而这份源码是 v%s —— "
                "源码里的改进**尚未生效**" % (run, port, src),
                fix="停掉旧实例后从源码跑：python main.py；"
                    "或重新打包发行版（scripts/ 里的打包脚本）")
        return _row(OK, "运行实例",
                    "v%s（端口 %d），与源码一致" % (run, port))
    return _row(OK, "运行实例", "本机没检测到在跑的实例（端口 8765/8000/5000）")


def check_dump_backend() -> dict:
    """App 取树后端：u2 快 / CLI 慢 6 倍（r1063 T95）。

    为什么要单列一行：这是**纯性能**差异，功能上 u2 缺了也能跑，
    于是最容易在"装完能用"的假象里被忽略——实测整轮差 24 秒。
    """
    try:
        import importlib.metadata as _md
        ver = _md.version("uiautomator2")
    except Exception:
        return _row(
            WARN, "取树后端",
            "未装 uiautomator2 —— App 渠道会退回 CLI 取树（单次 2–3 秒，整轮慢 6 倍）",
            fix="python -m pip install 'uiautomator2>=3.0'")
    return _row(OK, "取树后端", "uiautomator2 %s（App 取树走 u2，单次约 0.07 秒）" % ver)


def check_android():
    """App 通路（可选）：android.enabled 打开且模拟器目录存在。"""
    root = _root()
    cfg = os.path.join(root, "config.yaml")
    if not os.path.exists(cfg):
        return _row(WARN, "App 通路（可选）", "还没有 config.yaml，跳过")
    try:
        import yaml
        with open(cfg, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        return _row(WARN, "App 通路（可选）", "配置读不动，跳过")
    sec = data.get("android") or {}
    if not sec.get("enabled"):
        return _row(OK, "App 通路（可选）", "未启用（只采网页渠道）")
    inst = str(sec.get("install_dir") or "")
    if inst and not os.path.isdir(inst):
        return _row(BAD, "App 通路", "模拟器目录不存在：%s" % inst,
                    "改 android.install_dir 指向 MuMu 安装目录",
                    action="manual")
    # 走真实运行时（r1063 T64 修）：以前这里 `from core.android.device import
    # list_devices` —— 那个函数**不存在**，异常被吞，于是明明连着设备也报
    # "没连到设备"，把人引去修一个不存在的问题。
    try:
        from core.android.runtime import AndroidRuntime
        rt = AndroidRuntime(sec, None, full=data)
        dev = rt.device()
    except Exception as e:
        return _row(WARN, "App 通路", "设备层初始化失败：%s" % str(e)[:60],
                    "看 logs/ 里的 [android] 日志", action="manual")
    if dev is None:
        return _row(BAD, "App 通路", "找不到模拟器（MuMuManager 不可用）",
                    "装/启动 MuMu；或把 android.install_dir 指向安装目录",
                    action="launch_emulator")
    try:
        st = str(dev.state() or "")
    except Exception:
        st = ""
    if st != "device":
        return _row(WARN, "App 通路",
                    "模拟器在跑但 adb 状态是 %s" % (st or "未知"),
                    "自检 --fix 会尝试重启模拟器；仍连不上就按四步核对："
                    "① MuMu 实例在跑 ② MuMu 设置→其他→打开「ADB 调试」"
                    "③ --adb <adb.exe 全路径> ④ 端口不同就 --serial "
                    "127.0.0.1:<端口>。详见 docs/APP_CHANNELS.md"
                    "「开启 App 渠道（三步）」",
                    action="restart_emulator")
    # 版本信息：用户最关心的"它升级了吗"
    try:
        from core.android import appversion as _av
        from crawlers import REGISTRY as _REG
        # 包名的唯一真源：注册表里各 App crawler 的 `package` 类属性
        pkgs = {str(c.package): p for p, c in _REG.items()
                if str(p).startswith("app_") and getattr(c, "package", "")}
        ver = _av.read_versions(dev, list(pkgs)) if pkgs else {}
    except Exception:
        ver = {}
    if ver:
        # 显示**渠道名**（包名尾段 `view`/`android` 读不出是哪家）
        label = {}
        try:
            label = {str(c.package): str(getattr(c, "label", "") or p)
                     for p, c in _REG.items() if str(p).startswith("app_")}
        except Exception:
            label = {}
        detail = "已连到设备（%s）；App：%s" % (
            getattr(dev, "serial", ""),
            "、".join("%s %s" % (label.get(p, p), v["name"])
                     for p, v in list(ver.items())[:5]))
        return _row(OK, "App 通路", detail)
    return _row(OK, "App 通路", "已连到设备（%s）" % getattr(dev, "serial", ""))


def check_device_env() -> dict:
    """设备脸自洽性（r1063 T96）：机型/平台/GPU/ABI 是否自相矛盾。

    这是"0 条"最常见、又最容易被忽略的根因（携程 50003 / 阿里强制滑块都可能
    源于它），而且它不出现在任何采集日志里——所以单列一行，并把结论记进
    降级账本，面板「降级」那行才看得见。

    只在自检里跑（约 1–2 秒的 getprop/dumpsys），不进每轮采集。
    """
    try:
        from core.android import consistency as _ck
        from core.android import emulator as _emu
        dev = _emu.device(_State_cfg())
        if dev is None:
            return _row(OK, "设备环境", "拿不到设备，跳过审计")
        rep = _ck.note_if_issues(dev, _State_cfg())
    except Exception as e:
        return _row(OK, "设备环境", "审计跳过：%s" % type(e).__name__)
    if rep.get("high"):
        first = next(i for i in rep["items"] if i["level"] == "high")
        return _row(
            WARN, "设备环境",
            "%s → 高风险：%s 现 %s / 应 %s"
            % (rep.get("summary", ""), first.get("key", ""),
               str(first.get("got", ""))[:22], str(first.get("want", ""))[:26]),
            fix="python -m core.android.consistency 看全部矛盾；"
                "改完身份要 python scripts/identity_boot_module.py 再重启实例")
    if rep.get("total"):
        return _row(OK, "设备环境",
                    "%s（低风险，可不处理）" % rep.get("summary", ""))
    return _row(OK, "设备环境", "设备脸自洽（无矛盾）")


def _State_cfg() -> dict:
    """当前配置（自检内部用；读不到给空 dict）。"""
    try:
        import yaml
        with open("config.yaml", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def check_geo():
    """App 定位有没有钉住（r1063 T45）。

    出厂定位是加州山景城，而出口 IP 与系统时区都在国内 ——「IP 上海 / 时区上海 /
    GPS 加州」是风控里最便宜的一条矛盾。这条把"有没有钉"直接报出来。
    """
    root = _root()
    cfg = os.path.join(root, "config.yaml")
    if not os.path.exists(cfg):
        return _row(WARN, "App 定位", "还没有 config.yaml，跳过")
    try:
        import yaml
        with open(cfg, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        return _row(WARN, "App 定位", "配置读不动，跳过")
    sec = data.get("android") or {}
    if not sec.get("enabled"):
        return _row(OK, "App 定位", "App 通路未启用，不需要定位")
    g = sec.get("geo") or {}
    if g.get("enabled") is False:
        return _row(WARN, "App 定位", "已显式关闭（android.geo.enabled=false）",
                    "想让设备定位与出口 IP 一致就打开它")
    try:
        from core.android import geo as _geo
        pos = _geo.coords_from({"android": sec})
    except Exception as e:
        return _row(WARN, "App 定位", "读不到默认坐标：%s" % str(e)[:60])
    if not pos:
        return _row(WARN, "App 定位", "没有可用坐标", "在 android.geo 里填 lat/lon")
    return _row(OK, "App 定位", "%s（%.4f, %.4f）"
                % (pos.get("name", ""), pos["lat"], pos["lon"]))


def check_wechat_flat_assets():
    """静态资源自检（页面内嵌，不需要单独文件）——只确认模板能渲染。"""
    root = _root()
    w = os.path.join(root, "webui.py")
    if not os.path.exists(w):
        return _row(BAD, "页面", "webui.py 缺失", "重新下载仓库")
    try:
        size = os.path.getsize(w)
    except OSError:
        size = 0
    if size < 100_000:
        return _row(BAD, "页面", "webui.py 只有 %d 字节，像没下载全" % size,
                    "重新 clone（不要用断点续传中断的文件）")
    return _row(OK, "页面", "webui.py %d KB" % (size // 1024))


def run_checks():
    return [
        check_platform(),
        check_python(),
        check_modules(),
        check_config(),
        check_browser(),
        check_captcha_backend(),
        check_dump_backend(),
        check_running_instance(),
        check_dirs(),
        check_android(),
        check_device_env(),
        check_geo(),
        check_wechat_flat_assets(),
    ]


# ---------------------------------------------------------------- 自动补齐
SAFE_ACTIONS = ("install_deps", "install_browser", "create_config",
                "mkdir", "launch_emulator", "restart_emulator")
_SAFE_TEXT = ("python -m playwright install chromium",
              "pip install -r requirements.txt",
              # r1063 T95 取树后端（没装会慢 6 倍）：与上面两条同类，都是装依赖
              "uiautomator2")


def fixable(rows):
    """只有**安全动作**允许自动做。

    按 `action`（机器可判）而不是文案：文案随时会改，靠匹配文案的话哪天把
    "cp config.example.yaml config.yaml" 改个说法，自动修复就静默失效了。
    老调用方/旧行没有 `action` 时退回匹配文案（向后兼容）。
    """
    out = []
    for r in rows:
        if r["level"] not in (BAD, WARN):
            continue
        act = str(r.get("action") or "")
        if act in SAFE_ACTIONS or (not act and r.get("fix") in _SAFE_TEXT):
            out.append(r)
    return out


def apply_fix(row, echo=print):
    """执行一条安全修复；返回是否成功。**不碰账号/登录/策略。**"""
    root = _root()
    cmd = row["fix"]
    if cmd.startswith("pip install"):
        # r1063 T192：**按提示装**。以前不管提示是什么都跑
        # `pip install -r requirements.txt`；而 ddddocr 在 requirements 里是
        # 注释掉的可选项，于是"提示装 ddddocr"实际什么都没装。
        _target = cmd[len("pip install"):].strip()
        if _target.startswith("-r"):
            echo("→ 安装依赖：%s（可能需要几分钟）" % cmd)
            _args = [sys.executable, "-m", "pip", "install", "-r",
                     os.path.join(root, "requirements.txt")]
        else:
            _pkgs = [x for x in _target.split() if x and not x.startswith("-")]
            if not _pkgs:
                return False
            echo("→ 安装包：%s（可能需要几分钟）" % " ".join(_pkgs))
            _args = [sys.executable, "-m", "pip", "install"] + _pkgs
        r = subprocess.run(_args)
        return r.returncode == 0
    if row.get("action") in ("launch_emulator", "restart_emulator"):
        # 用户要求：模拟器该由程序自己拉起/重启（r1063 T64）。
        # 只动"机器开没开"，不碰账号与配置。
        try:
            from core.android import emulator as _emu
            cfg = {}
            try:
                import yaml
                with open(os.path.join(_root(), "config.yaml"),
                          encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}
            except Exception:
                cfg = {}
            if row["action"] == "launch_emulator":
                rep = _emu.ensure_running(cfg)
            else:
                rep = _emu.restart(cfg)
            echo("→ 模拟器：%s" % (rep.get("why") or ""))
            return bool(rep.get("ok"))
        except Exception as e:
            echo("→ 模拟器操作失败：%s" % str(e)[:100])
            return False
    if row.get("action") == "create_config":
        root = _root()
        cfg = os.path.join(root, "config.yaml")
        example = os.path.join(root, "config.example.yaml")
        if os.path.exists(cfg):
            echo("→ config.yaml 已存在，不覆盖")
            return True
        if not os.path.exists(example):
            return False
        shutil.copy2(example, cfg)
        echo("→ 已从示例生成 config.yaml（请按需改 users[].platforms）")
        return True
    if row.get("action") == "mkdir":
        root = _root()
        ok = True
        for d in ("data", "user_data"):
            p = os.path.join(root, d)
            try:
                os.makedirs(p, exist_ok=True)
            except OSError:
                ok = False
        echo("→ 已建数据目录 data/ user_data/" if ok else "→ 建目录失败")
        return ok
    if cmd.startswith("python -m playwright install"):
        echo("→ 安装浏览器内核：%s（下载约 100MB）" % cmd)
        r = subprocess.run([sys.executable, "-m", "playwright", "install",
                            "chromium"])
        return r.returncode == 0
    return False


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    do_fix = "--fix" in argv
    rows = run_checks()
    icon = {OK: "✅", WARN: "⚠ ", BAD: "❌"}
    print("=== 装机自检 ===")
    for r in rows:
        print("%s %-14s %s" % (icon.get(r["level"], "?"), r["name"],
                               r["detail"]))
        if r["level"] != OK and r["fix"]:
            print("    → %s" % r["fix"])
    bad = [r for r in rows if r["level"] == BAD]
    if do_fix and bad:
        todo = fixable(bad)
        if not todo:
            print("\n没有可自动补齐的项（剩下的必须人来做）。")
        for r in todo:
            ok = apply_fix(r)
            print("   %s %s" % ("已处理" if ok else "失败", r["name"]))
        if todo:
            rows = run_checks()
            bad = [r for r in rows if r["level"] == BAD]
    print("\n结论：%s" % ("还差 %d 项，见上面的 → 提示" % len(bad)
                         if bad else "可以开跑：python main.py"))
    return 0 if not bad else 1


if __name__ == "__main__":                       # pragma: no cover
    raise SystemExit(main())
