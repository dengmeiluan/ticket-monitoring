# -*- coding: utf-8 -*-
"""设备身份（指纹）：把一台 MuMu 模拟器伪装成**同一台具体真机**，并保持身份稳定。

为什么需要这一层（这是「采集成功率」与「掉登录」的同一个根因）
------------------------------------------------------------
携程 / 飞猪 / 去哪儿 / 同程 / 途牛 都会把「设备」当成账号的一部分：

  * App 首启生成一个设备 ID（携程 ``c_guid`` / 阿里系 ``utdid``+``umid``，
    底层都吃 ``android_id`` / 序列号 / Build 字段）；
  * 登录与查价接口带 ``x-device-*`` 或 SDK 内部埋点做「同设备」校验；
  * 一台设备突然换了机型、换了 ``android_id``、换了分辨率，就是
    「新设备登录」→ 短信/滑块/人脸二次校验，也就是用户看到的「登录不上」。

模拟器的**出厂身份**恰好是最容易被判定的那一类：``ro.product.model``
带 MuMu/Netease、``ro.hardware`` 是 goldfish/ranchu、``ro.build.tags``
是 test-keys、``ro.kernel.qemu=1``、无 SIM、无传感器、``android_id``
重复或全零。这类设备在风控里是一条独立的命中规则，与「频率」无关——
所以「降速」对它是无效的，只能改身份。

三条铁律（本模块的全部设计约束）
--------------------------------
1. **稳定优先于随机**：身份落盘持久化，按实例序号索引；进程重启、
   实例重启、程序升级都读同一份。每次随机 = 每次都是新设备 = 每次都要
   重新验证。真正需要换身份时用 ``rotate()`` 显式换，并记审计。
2. **自洽优先于真实**：机型、品牌、主板、SoC、build 指纹、序列号必须
   互相自洽（``ro.product.model`` 是 Redmi K50，而 ``ro.build.fingerprint``
   是 google/sdk_gphone 就是一眼假）。所以身份从**机型池**里整台取，
   不做字段级随机拼缝。
3. **不冒充改不了的东西**：Play Integrity、传感器数量、内核版本这些改不动
   就别撒谎；ABI 属于「要先验证才能改」的一类——入口是
   ``abi_canary.run()``（带自动回滚），验证 ok 后才由 ``hardening`` 写，
   直接硬写 ``arm64-v8a`` 会复现仓库里记过的 ``Runtime.load0`` ANR 死锁。

生效机制（Android 的事实，别绕过）
--------------------------------
``android.os.Build`` 的字段在 **zygote 预加载**时就定下来了，所以：

    resetprop 改 props  → 已在跑的 App 看不到  → 必须重启框架/重启实例

``ensure()`` 因此只在「本启动周期还没应用过」时动手，应用完按配置执行
``zygote``（``stop; start``，约 8–15s）或 ``full``（实例重启）。同一
boot_id 内重复调用只花一条 adb 命令（读标记文件）。
"""
from __future__ import annotations

import json
import os
import time
import zlib

# 身份文件名（落 user_data/<profile>/device_identity.json，与浏览器渠道的
# 会话档案同一条「本地私有、不上云」的规矩）
IDENTITY_FILE = "device_identity.json"

# 设备内标记：`<identity_id> <boot_id>`。只用来跳过「本周期已应用」的重复
# 工作；标记丢了无非是重应用一次，不影响正确性。
_MARK = "/data/local/tmp/tm_ident_%d.ok"

# ---------------------------------------------------------------------------
# 机型池：整台取，不做字段级拼缝。
#
# 只收「真实存在、量足够大、Android 12/13」的机器——量大的机型和风控里
# 的「常见设备」重合，反而更安全（罕见机型本身就是一条特征）。
# display 是这台机器的真实物理分辨率，用于 audit 报告；**默认不改
# ``wm size``**：采集脚本的坐标全部按现有竖屏写死，改分辨率等于让所有
# App 渠道一起瘫（见 device.py 里 lock_portrait 的现场记录）。
# ---------------------------------------------------------------------------
PHONE_POOL = (
    {
        "brand": "Redmi", "manufacturer": "Xiaomi", "model": "Redmi K50",
        "device": "rubens", "product": "rubens", "board": "rubens",
        "hardware": "mt6895", "platform": "mt6895",
        "soc": "MediaTek Dimensity 8100",
        "release": "12", "sdk": "31", "build_id": "SP1A.210812.016",
        "build_display": "V13.0.4.0.SLNCNXM",
        "fingerprint": ("Redmi/rubens/rubens:12/SP1A.210812.016/"
                        "V13.0.4.0.SLNCNXM:user/release-keys"),
        "display": (1080, 2400), "density": 440,
    },
    {
        "brand": "Redmi", "manufacturer": "Xiaomi", "model": "M2102J20SG",
        "device": "ares", "product": "ares", "board": "aresin",
        "hardware": "qcom", "platform": "lito",
        "soc": "Qualcomm Snapdragon 870",
        "release": "12", "sdk": "31", "build_id": "SKQ1.210908.001",
        "build_display": "V13.0.3.0.SKHCNXM",
        "fingerprint": ("Redmi/ares/ares:12/SKQ1.210908.001/"
                        "V13.0.3.0.SKHCNXM:user/release-keys"),
        "display": (1080, 2400), "density": 395,
    },
    {
        "brand": "OPPO", "manufacturer": "OPPO", "model": "PEGM00",
        "device": "OP4CF7", "product": "OP4CF7", "board": "mt6893",
        "hardware": "mt6893", "platform": "mt6893",
        "soc": "MediaTek Dimensity 1200",
        "release": "12", "sdk": "31", "build_id": "SP1A.210812.016",
        "build_display": "PEGM00_11_C.35",
        "fingerprint": ("OPPO/PEGM00/OP4CF7:12/SP1A.210812.016/"
                        "1674205381:user/release-keys"),
        "display": (1080, 2400), "density": 450,
    },
    {
        "brand": "vivo", "manufacturer": "vivo", "model": "V2168A",
        "device": "PD2168", "product": "PD2168", "board": "mt6853",
        "hardware": "mt6853", "platform": "mt6853",
        "soc": "MediaTek Dimensity 700",
        "release": "12", "sdk": "31", "build_id": "SP1A.210812.003",
        "build_display": "PD2168_A_12.0.9.0",
        "fingerprint": ("vivo/PD2168/PD2168:12/SP1A.210812.003/"
                        "compiler11061430:user/release-keys"),
        "display": (1080, 2408), "density": 400,
    },
    {
        "brand": "HONOR", "manufacturer": "HONOR", "model": "ANY-AN00",
        "device": "HONORANY", "product": "HONORANY-AN00", "board": "qcom",
        "hardware": "qcom", "platform": "lahaina",
        "soc": "Qualcomm Snapdragon 778G",
        "release": "12", "sdk": "31", "build_id": "HONORANY-AN00",
        "build_display": "6.1.0.121(C00E121R3P9)",
        "fingerprint": ("HONOR/ANY-AN00/HONORANY:12/HONORANY-AN00/"
                        "6.1.0.121C00E121R3P9:user/release-keys"),
        "display": (1080, 2340), "density": 400,
    },
    {
        "brand": "realme", "manufacturer": "realme", "model": "RMX3350",
        "device": "RE5C7D", "product": "RMX3350", "board": "mt6893",
        "hardware": "mt6893", "platform": "mt6893",
        "soc": "MediaTek Dimensity 1200",
        "release": "12", "sdk": "31", "build_id": "SP1A.210812.016",
        "build_display": "RMX3350_11_C.13",
        "fingerprint": ("realme/RMX3350/RMX3350:12/SP1A.210812.016/"
                        "1660000000:user/release-keys"),
        "display": (1080, 2400), "density": 410,
    },
    {
        "brand": "OnePlus", "manufacturer": "OnePlus", "model": "LE2100",
        "device": "OnePlus9R", "product": "OnePlus9R", "board": "kona",
        "hardware": "qcom", "platform": "kona",
        "soc": "Qualcomm Snapdragon 870",
        "release": "12", "sdk": "31", "build_id": "RKQ1.211103.002",
        "build_display": "LE2100_13.0.0.1",
        "fingerprint": ("OnePlus/OnePlus9R/OnePlus9R:12/RKQ1.211103.002/"
                        "1660000000:user/release-keys"),
        "display": (1080, 2400), "density": 420,
    },
    {
        "brand": "Xiaomi", "manufacturer": "Xiaomi", "model": "2201123C",
        "device": "venus", "product": "venus", "board": "venus",
        "hardware": "qcom", "platform": "taro",
        "soc": "Qualcomm Snapdragon 8 Gen 1",
        "release": "13", "sdk": "33", "build_id": "TKQ1.220829.002",
        "build_display": "V14.0.4.0.TLBCNXM",
        "fingerprint": ("Xiaomi/venus/venus:13/TKQ1.220829.002/"
                        "V14.0.4.0.TLBCNXM:user/release-keys"),
        "display": (1440, 3200), "density": 560,
    },
)

# ABI 说明（写给后来的人，免得再试一次盲改）：
# MuMu 的系统是 x86_64 + ARM 转译层，``ro.product.cpu.abi`` 改成 arm64-v8a
# 之后 PackageManager 会按 arm64 选 native so，而转译层对部分加固 so（携程
# / 去哪儿都带）直接崩——仓库里 record 过 ``Runtime.load0`` 主线程死锁、
# ANR 120s。所以本模块**默认不碰 ABI**；想动就先跑
# ``core/android/abi_canary.py::run()`` 在**这台实例 + 这个包**上实测，
# 拿到 ok 判定后再把 ``android.identity.spoof_abi`` 设成 ``auto``。
ABI_NOTE = "x86_64 是模拟器最强残留特征之一；要改先过 abi_canary 实测（见 hardening）"

# 默认写入的 props（顺序稳定，便于审计 diff）。刻意不写 ro.build.version.release
# / sdk：改版本会连带 SDK_INT、资源选择、so 兼容，风险远大于收益。
PROP_KEYS = (
    "ro.product.model",
    "ro.product.brand",
    "ro.product.manufacturer",
    "ro.product.device",
    "ro.product.name",
    "ro.product.board",
    "ro.build.product",
    "ro.build.id",
    "ro.build.display.id",
    "ro.build.fingerprint",
    "ro.build.tags",
    "ro.build.type",
    "ro.build.user",
    "ro.build.host",
    "ro.build.flavor",
    "ro.hardware",
    "ro.board.platform",
    "ro.boot.hardware",
    "ro.serialno",
    "ro.boot.serialno",
    "ro.bootmode",
    "ro.secure",
    "ro.debuggable",
    "ro.adb.secure",
    "net.hostname",
    "gsm.sim.operator.alpha",
    "gsm.sim.operator.numeric",
    "gsm.operator.alpha",
    "gsm.operator.numeric",
    "gsm.operator.iso-country",
    "gsm.sim.state",
)


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _call(dev, *args, timeout=None):
    """调用设备的 shell。兼容 ``AdbDevice.sh``（新）与 ``_sh``（旧/假设备）。

    返回 str 或 None；任何异常都当「这条命令没跑成」，不向上抛——
    设备掉线在本项目里是常态，不是错误。
    """
    fn = getattr(dev, "sh", None) or getattr(dev, "_sh", None)
    if fn is None:
        return None
    try:
        if timeout is None:
            out = fn(*args)
        else:
            out = fn(*args, timeout=timeout)
    except TypeError:
        try:
            out = fn(*args)
        except Exception:
            return None
    except Exception:
        return None
    return out


def _text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    return str(v)


def _q(v) -> str:
    """单引号包裹，供设备端 sh -c 使用。"""
    return "'" + str(v).replace("'", "'\\''") + "'"


def parse_getprop(raw: str) -> dict:
    """把 ``getprop`` 的 ``[key]: [value]`` 输出解析成 dict。"""
    out = {}
    for line in _text(raw).splitlines():
        s = line.strip()
        if not s.startswith("[") or "]: [" not in s:
            continue
        k, _, rest = s[1:].partition("]: [")
        v = rest[:-1] if rest.endswith("]") else rest
        out[k.strip()] = v.strip()
    return out


def props_of(dev) -> dict:
    """当前设备全部 props（一次 adb）。"""
    return parse_getprop(_text(_call(dev, "shell", "getprop")))


def _hex(seed: int, n: int) -> str:
    """由 seed 派生的定长十六进制串（同 seed 稳定）。"""
    out = ""
    i = 0
    while len(out) < n:
        out += "%08x" % zlib.crc32(("tm:%d:%d" % (seed, i)).encode())
        i += 1
    return out[:n]


def _mac(seed: int, oui=("b4", "0f", "3b")) -> str:
    """由 seed 派生一个 OUI 在厂商段的 MAC（避免 02:00:00:00:00:00）。"""
    tail = _hex(seed + 7, 6)
    return ":".join(list(oui) + [tail[i:i + 2] for i in range(0, 6, 2)])


# ---------------------------------------------------------------------------
# 身份对象
# ---------------------------------------------------------------------------
class Identity:
    """一台设备的完整身份：机型 + 派生 ID + 应用状态。"""

    def __init__(self, data: dict):
        self.data = dict(data or {})

    # --- 只读视图 ---
    @property
    def ident_id(self) -> str:
        return str(self.data.get("ident_id") or "")

    @property
    def vm(self) -> int:
        try:
            return int(self.data.get("vm") or 0)
        except (TypeError, ValueError):
            return 0

    @property
    def profile(self) -> dict:
        p = self.data.get("profile")
        return p if isinstance(p, dict) else {}

    @property
    def android_id(self) -> str:
        return str(self.data.get("android_id") or "")

    @property
    def serial(self) -> str:
        return str(self.data.get("serial") or "")

    @property
    def wifi_mac(self) -> str:
        return str(self.data.get("wifi_mac") or "")

    @property
    def bluetooth_mac(self) -> str:
        return str(self.data.get("bluetooth_mac") or "")

    @property
    def created_at(self) -> float:
        try:
            return float(self.data.get("created_at") or 0)
        except (TypeError, ValueError):
            return 0.0

    def props(self) -> dict:
        """身份 → props 映射（只含 PROP_KEYS，值全部是字符串）。"""
        p = self.profile
        model = str(p.get("model") or "")
        brand = str(p.get("brand") or "")
        short = model.replace(" ", "")
        return {
            "ro.product.model": model,
            "ro.product.brand": brand,
            "ro.product.manufacturer": str(p.get("manufacturer") or brand),
            "ro.product.device": str(p.get("device") or ""),
            "ro.product.name": str(p.get("product") or ""),
            "ro.product.board": str(p.get("board") or ""),
            "ro.build.product": str(p.get("device") or ""),
            "ro.build.id": str(p.get("build_id") or ""),
            "ro.build.display.id": str(p.get("build_display") or ""),
            "ro.build.fingerprint": str(p.get("fingerprint") or ""),
            "ro.build.tags": "release-keys",
            "ro.build.type": "user",
            "ro.build.user": "builder",
            "ro.build.host": "localhost",
            "ro.build.flavor": "%s-user" % short.lower(),
            "ro.hardware": str(p.get("hardware") or "qcom"),
            "ro.board.platform": str(p.get("platform") or "qcom"),
            "ro.boot.hardware": str(p.get("hardware") or "qcom"),
            "ro.serialno": self.serial,
            "ro.boot.serialno": self.serial,
            "ro.bootmode": "normal",
            # root / 可调试：这两条是「模拟器 + 可 root」最常被读的两条
            "ro.secure": "1",
            "ro.debuggable": "0",
            "ro.adb.secure": "1",
            "net.hostname": "android-%s" % _hex(hash(self.ident_id) & 0xFFFF, 8),
            # 无 SIM 是模拟器的强特征；给出自洽的「一张中国移动 4G 卡」
            "gsm.sim.operator.alpha": "CHINA MOBILE",
            "gsm.sim.operator.numeric": "46000",
            "gsm.operator.alpha": "CHINA MOBILE",
            "gsm.operator.numeric": "46000",
            "gsm.operator.iso-country": "cn",
            "gsm.sim.state": "READY",
        }

    def as_dict(self) -> dict:
        return dict(self.data)

    def __repr__(self):
        return "<Identity %s vm=%d model=%s>" % (
            self.ident_id, self.vm, self.profile.get("model"))


def build_from_vendor(vendor_values: dict, seed: int = 0,
                      vm: int = 0) -> Identity:
    """用 **MuMu 官方设置**当身份来源（池只做兜底）。

    为什么必须这样：2026-11-03 实测这台实例上——

    * MuMu 官方 `phone_brand=Samsung` / `phone_miit=SM-A5260`，
      设备里 ``ro.product.brand/model`` 就是 **Samsung / SM-A5260**；
    * 而我们在设备侧 ``setprop ro.product.model <池里的机型>`` **静默无效**
      （系统盘只读）。

    也就是说**官方注入是唯一真正生效的来源**。如果身份档案还按池写 Redmi K50，
    就会出现"档案说 Redmi、设备是 Samsung"——报告骗自己，风控读到的却是另一套。

    所以身份改为：**官方有值就用官方**，缺的字段（序列号/android_id/gsm）
    才由这里派生；官方一个都读不到时才退回 ``build()`` 的机型池。
    """
    base = build(seed, vm=vm)
    prof = dict(base.profile)
    v = vendor_values or {}

    brand = str(v.get("phone_brand") or "").strip()
    model = str(v.get("phone_model") or "").strip()
    miit = str(v.get("phone_miit") or "").strip()
    if not brand and not model and not miit:
        return base                       # 官方没值：保持池的行为

    if brand:
        prof["brand"] = brand
        prof["manufacturer"] = brand
    # ro.product.model 实际由 phone_miit 注入（实测 SM-A5260），
    # phone_model 是营销名（Galaxy A52 5G）——两者都留着，各归其位。
    if miit:
        prof["model"] = miit
    if model:
        prof["marketing_model"] = model
    # build 指纹跟着自洽（官方没给 build 字段，用品牌与型号重拼）
    short = (miit or model or prof.get("device") or "device")
    prof["fingerprint"] = ("%s/%s/%s:%s/%s/%s:user/release-keys"
                           % (prof.get("brand", ""), short, short,
                              prof.get("release", ""),
                              prof.get("build_id", ""),
                              prof.get("build_display", "")))
    # 屏幕也以官方为准（对齐后 identity 不再声明一个设备没有的分辨率）。
    # **注意方向**：MuMu 的 resolution_width=1600 / height=900 是**窗口**尺寸，
    # 而 Android 侧 `wm size` 报 900×1600（竖屏）。实测两者是转置关系，
    # 这里统一折算成「短边×长边」，避免档案写 1600×900 横屏而设备是竖屏。
    try:
        w = int(float(v.get("resolution_width") or 0))
        h = int(float(v.get("resolution_height") or 0))
        d = int(float(v.get("resolution_dpi") or 0))
        if w and h:
            prof["display"] = [min(w, h), max(w, h)]
        if d:
            prof["density"] = d
    except (TypeError, ValueError):
        pass

    data = base.as_dict()
    data["profile"] = prof
    data["source"] = "vendor"            # 便于报告里区分身份来源
    if v.get("phone_imei"):
        data["imei"] = str(v["phone_imei"])
    return Identity(data)


def build(seed: int = 0, vm: int = 0, pool=None) -> Identity:
    """按 seed 生成一台自洽的身份（同 seed 同身份，不随机）。"""
    pool = tuple(pool or PHONE_POOL)
    if not pool:
        raise ValueError("empty phone pool")
    prof = dict(pool[int(seed) % len(pool)])
    sid = _hex(seed * 131 + vm * 17 + 3, 8)
    ident = {
        "ident_id": "id-%s-%02d" % (sid, vm),
        "vm": int(vm),
        "pool_index": int(seed) % len(pool),
        "profile": prof,
        "android_id": _hex(seed * 7 + vm, 16),
        "serial": _hex(seed * 13 + vm, 16).upper()[:16],
        "wifi_mac": _mac(seed * 3 + vm, ("b4", "0f", "3b")),
        "bluetooth_mac": _mac(seed * 5 + vm + 1, ("c8", "1f", "66")),
        "created_at": time.time(),
        "applied_at": 0,
        "applied_boot": "",
        "rotations": 0,
    }
    return Identity(ident)


# ---------------------------------------------------------------------------
# 持久化
# ---------------------------------------------------------------------------
class IdentityStore:
    """身份档案：``{vm_index: identity_dict}``，原子写、坏文件不致命。"""

    def __init__(self, path: str):
        self.path = str(path)

    def load(self) -> dict:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError, TypeError):
            return {}
        return data if isinstance(data, dict) else {}

    def save(self, data: dict) -> bool:
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
            os.replace(tmp, self.path)
            return True
        except (OSError, ValueError, TypeError):
            return False

    def get(self, vm: int) -> Identity:
        data = self.load()
        rec = data.get(str(int(vm)))
        return Identity(rec) if isinstance(rec, dict) else Identity({})

    def put(self, ident: Identity) -> bool:
        data = self.load()
        data[str(ident.vm)] = ident.as_dict()
        return self.save(data)

    def drop(self, vm: int) -> bool:
        data = self.load()
        if data.pop(str(int(vm)), None) is None:
            return False
        return self.save(data)


def default_store(user_data_dir: str, profile: str = "") -> IdentityStore:
    """默认档案位置：``<user_data>/<profile>/device_identity.json``。"""
    base = os.path.join(str(user_data_dir or "user_data"),
                        str(profile or "")) if profile else str(
                            user_data_dir or "user_data")
    return IdentityStore(os.path.join(base, IDENTITY_FILE))


# ---------------------------------------------------------------------------
# 应用（写设备）
# ---------------------------------------------------------------------------
def _root(dev) -> bool:
    out = _text(_call(dev, "shell", "id"))
    return "uid=0" in out


def _su(dev) -> bool:
    """设备上有没有 ``su``。

    **MuMu 的 ``adb root`` 之后 shell 本身就是 uid=0，且常常没有 su 二进制。**
    这时若仍按 ``su -c <script>`` 调用，整段脚本会以
    ``/system/bin/sh: su: not found`` 整体失败——不是某一条 props 失败，是
    全部失败，而报告里只看到 20 个 FAIL。所以先问一次。
    """
    out = _text(_call(dev, "shell", "sh", "-c",
                      "command -v su || ls /system/bin/su /system/xbin/su "
                      "2>/dev/null || true"))
    return "su" in out and "/su" in out


def as_root(dev, script: str, timeout=None):
    """以 root 身份执行一段 shell（自动选 su / 直连 root shell）。"""
    if _su(dev):
        return _call(dev, "shell", "su", "-c", script, timeout=timeout)
    return _call(dev, "shell", "sh", "-c", script, timeout=timeout)


def _magisk(dev) -> str:
    """返回 resetprop 的可执行路径（空=没有 Magisk）。"""
    out = _text(_call(
        dev, "shell", "sh", "-c",
        "command -v resetprop 2>/dev/null || "
        "ls /data/adb/magisk/resetprop 2>/dev/null || true"))
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("/") and "resetprop" in s:
            return s
    return ""


def apply(dev, ident: Identity, *, use_root=None, uid: bool = True) -> dict:
    """把身份写进设备。返回逐键结果，**带读回校验**，不抛异常。

    为什么不再自己拼 setprop 脚本：``setprop ro.*`` 在只读系统盘上
    **返回 0 但值不变**（2026-11-03 实测），只看命令返回码会得出"9 条生效"
    的假结论——而设备上一条都没变。写 props 这件事因此**只保留一份实现**：
    ``abi_canary.apply_props``（写前快照 + 写后 getprop 读回比对）。

    返回键：``applied``（命令报成功）/ ``verified``（读回真的是新值，
    **只有它可信**）/ ``failed`` / ``mismatch`` / ``unchanged`` /
    ``android_id``。
    """
    from . import abi_canary

    props = ident.props()
    rec = abi_canary.apply_props(dev, props, use_root=True if use_root is None
                                 else bool(use_root))
    rep = {"applied": rec.get("applied") or [],
           "verified": rec.get("verified") or [],
           "failed": rec.get("failed") or [],
           "mismatch": rec.get("mismatch") or {},
           "unchanged": rec.get("unchanged") or [],
           "resetprop": rec.get("resetprop") or "",
           "android_id": "", "root": _root(dev)}

    if uid:
        aid = ident.android_id
        if aid:
            _call(dev, "shell", "settings", "put", "secure", "android_id", aid)
            rep["android_id"] = _text(_call(
                dev, "shell", "settings", "get", "secure", "android_id")).strip()
            # android_id 是 settings 里的（不是 ro.*），这条路在不改系统盘时
            # 也可能真生效——所以单独校验，别和 props 的成功率混在一起。
            rep["android_id_ok"] = bool(rep["android_id"]) and \
                rep["android_id"] == aid
        # 蓝牙名/设备名跟着机型走：这两条在「同设备」校验里常被一起读
        name = str(ident.profile.get("model") or "")
        if name:
            _call(dev, "shell", "settings", "put", "secure", "bluetooth_name",
                  name)
            _call(dev, "shell", "settings", "put", "global", "device_name",
                  name)
    return rep


def boot_id(dev) -> str:
    return _text(_call(dev, "shell", "cat", "/proc/sys/kernel/random/boot_id")
                 ).strip()


def _mark_path(vm: int) -> str:
    return _MARK % int(vm)


def applied_marker(dev, vm: int) -> str:
    return _text(_call(dev, "shell", "cat", _mark_path(vm))).strip()


def write_marker(dev, ident: Identity) -> str:
    """写标记：``<ident_id> <boot_id>``。失败不影响正确性。"""
    line = "%s %s" % (ident.ident_id, boot_id(dev))
    _call(dev, "shell", "sh", "-c",
          "echo %s > %s" % (_q(line), _mark_path(ident.vm)))
    return line


def restart_framework(dev, mode: str = "zygote", wait_s: int = 90) -> bool:
    """让新的 Build 字段对 App 生效。

    ``android.os.Build`` 的静态字段在 zygote 里定型，只改 props 不重启，
    新身份对已在跑的 App 等于没改。``zygote`` 用 ``stop; start``（8–15s，
    保留模拟器与 adb）；``full`` 交给调用方（MuMu control restart）。
    """
    mode = str(mode or "none").lower()
    if mode in ("none", "no", "0", "false", ""):
        return False
    if mode == "zygote":
        as_root(dev, "stop; start")
    # 下限 2s：单测会把 wait_s 调到 1，卡 10s 的硬地板会让一次实验白等 20s+
    end = time.time() + max(2, int(wait_s or 90))
    while time.time() < end:
        time.sleep(3)
        if _text(_call(dev, "shell", "getprop", "sys.boot_completed")
                 ).strip() == "1":
            return True
    return False


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------
# 模拟器痕迹 → (判定说明, 建议)。值靠子串/正则匹配，宁可漏报不误报。
_EMU_PROPS = (
    ("ro.kernel.qemu", "1", "内核是 qemu（模拟器最硬的一条证据）"),
    ("ro.hardware", "goldfish", "ro.hardware=goldfish（经典 AVD）"),
    ("ro.hardware", "ranchu", "ro.hardware=ranchu（现代 AVD）"),
    ("ro.hardware", "vbox86", "ro.hardware=vbox86（VirtualBox 系）"),
    ("ro.product.model", "mumu", "机型名带 MuMu"),
    ("ro.product.model", "sdk_gphone", "机型名是 AVD 默认值"),
    ("ro.product.brand", "mumu", "品牌是 MuMu"),
    ("ro.product.manufacturer", "netease", "厂商是网易"),
    ("ro.build.fingerprint", "generic", "指纹含 generic"),
    ("ro.build.tags", "test-keys", "test-keys（可调试签名）"),
    ("ro.build.type", "eng", "ro.build.type=eng"),
    ("ro.debuggable", "1", "全局可调试（adb root 后必现）"),
    ("ro.secure", "0", "ro.secure=0（adbd 直接给 root）"),
    ("ro.adb.secure", "0", "adbd 不做认证"),
    ("ro.board.platform", "goldfish", "主板平台是 goldfish"),
    ("ro.product.cpu.abi", "x86", "CPU 架构是 x86（真机没有）"),
    ("ro.product.cpu.abilist", "x86", "ABI 列表含 x86"),
    ("gsm.sim.state", "ABSENT", "没有 SIM 卡"),
    ("gsm.sim.operator.numeric", "", "运营商信息为空"),
    ("init.svc.qemud", "running", "qemud 服务在跑"),
    ("ro.build.user", "android-build", "build 用户名是 AVD 默认值"),
)


def audit(dev) -> dict:
    """自检：返回 ``{score, leaks, props, notes}``。

    ``score`` 100 = 没有命中（不代表绝对安全，只代表「已知特征全清」）。
    这是给操作员看的**事实清单**：哪条还在、为什么算命中、能不能改。
    """
    props = props_of(dev)
    leaks = []
    for key, needle, why in _EMU_PROPS:
        val = str(props.get(key, ""))
        if needle == "":
            if val == "":
                leaks.append({"key": key, "value": "", "why": why,
                              "fix": "identity"})
            continue
        if needle.lower() in val.lower():
            leaks.append({"key": key, "value": val, "why": why,
                          "fix": "identity"})
    # root 残留（文件系统层面的，props 改不掉）
    #
    # **必须用 `test -e` 逐路径判存在**（2026-11-04 实机踩到，与 stealth 同源 bug）：
    # `ls /a /b /c` 在某个参数是目录/符号链接时会把它的**内容**列出来，于是
    # 整个根目录（acct/bin/cache/…）被当成 17 条 root 残留，`-6×17` 直接把自检
    # 分扣到 0。操作员看到「自检 0 分」会以为隐藏失败，实际是误报。
    # 用 stealth 的同名探测保持单一实现，避免两处再次漂移。
    for p in ("/system/bin/su", "/system/xbin/su", "/sbin/su",
              "/data/adb/magisk"):
        if _exact_path_exists(dev, p):
            leaks.append({"key": "fs", "value": p,
                          "why": "root 痕迹（props 改不掉，靠 DenyList/Shamiko）",
                          "fix": "magisk-denylist"})
    score = max(0, 100 - 6 * len(leaks))
    return {
        "score": score,
        "leaks": leaks,
        "props": {k: props.get(k, "") for k in PROP_KEYS},
        "abi_note": ABI_NOTE,
        "identity_id": "",
    }


# ---------------------------------------------------------------------------
# 对外唯一入口
# ---------------------------------------------------------------------------
def _is_emulator(props: dict) -> bool:
    """这台设备是不是模拟器（只认**证据**，不认机型名）。

    为什么要先判：身份层只对模拟器有意义。真机上跑这套 props 覆盖等于
    自找麻烦（可能把真机型号改成别的，反而更像伪装）。测试里的假设备
    读不到 props，也会因此被跳过，既不需要改测试也不用担心副作用。
    """
    p = props or {}
    joined = " ".join(str(v) for v in p.values()).lower()
    if any(k in joined for k in ("mumu", "netease", "goldfish", "ranchu",
                                 "vbox86", "bluestacks", "qemu")):
        return True
    return str(p.get("ro.kernel.qemu", "")).strip() == "1"


def _exact_path_exists(dev, path: str) -> bool:
    """路径**本身**是否存在（用 ``test -e``，绝不用 ``ls``）。

    ``ls /a /b /c`` 在某个参数是目录或符号链接时会把它的内容列出来，
    于是"有没有 su"变成"把根目录列了一遍"——这正是 2026-11-04 自检 0 分
    误报的根因。``test -e`` 只回 0/1，不存在这个歧义。
    """
    out = _text(_call(dev, "shell", "sh", "-c",
                      "test -e %s && echo TM_YES || echo TM_NO" % _q(path)))
    return out.strip() == "TM_YES"


def _cfg(raw) -> dict:
    """读 ``android.identity`` 段（缺省=开，与 crawler.stealth 同一约定）。"""
    android = raw.get("android") if isinstance(raw, dict) else None
    sec = (android or {}).get("identity") if isinstance(android, dict) else None
    return sec if isinstance(sec, dict) else {}


def _flag(v, default=True) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("1", "true", "yes", "on"):
            return True
        if s in ("0", "false", "no", "off", ""):
            return False
    return bool(v)


def _seed_for(ident_id: str) -> int:
    return zlib.crc32(str(ident_id).encode("utf-8"))


def ensure(dev, config: dict = None, logger=None, *, user_data_dir="user_data",
           profile="", vm: int = 0, force: bool = False) -> dict:
    """确保设备带着**稳定身份**且本启动周期已应用。返回报告 dict。

    调用时机只有一处：``AndroidRuntime.ensure_ready()`` 在 adb 连通之后、
    任何 App 启动之前。这样 App 进程读到的就是新身份，不需要「先进 App
    再改」那种打补丁的顺序。

    报告键：``{"ok", "changed", "skipped", "identity", "apply", "audit",
    "error"}``；``ok=False`` 时 ``error`` 说明原因（设备离线/无 root 等）。
    """
    sec = _cfg(config)
    rep = {"ok": False, "changed": False, "skipped": "", "identity": "",
           "apply": {}, "audit": {}, "error": ""}
    if not _flag(sec.get("enabled"), True):
        rep["skipped"] = "identity disabled"
        rep["ok"] = True
        return rep
    try:
        store = default_store(user_data_dir, profile)
        ident = store.get(vm)
        # 新身份先只放在内存里，**等确认能在真模拟器上应用再落盘**。
        # 否则跑一次单测/在真机上试跑，就会在 user_data 里留下一个
        # 「从没生效过」的身份；等真机第一次跑时它会被当成既有身份沿用，
        # 机型与 android_id 就这么被测试随机定了下来。
        created = not ident.ident_id
        if created:
            seed = _seed_for("tm-%s-%d-%d" % (profile, vm, int(time.time())))
            # 身份来源优先级：**MuMu 官方设置** > 机型池。
            # 官方是唯一真正生效的来源（设备侧 setprop ro.* 在只读系统盘上
            # 静默无效），所以让档案服从官方，而不是让两者各说一套。
            vend = {}
            if _flag(sec.get("prefer_vendor"), True):
                try:
                    from . import vendor as vendor_mod
                    vend = vendor_mod.read(vm_index=vm) or {}
                except Exception:
                    vend = {}
            if vend:
                ident = build_from_vendor(vend, seed, vm=vm)
            else:
                ident = build(seed, vm=vm)
        rep["identity"] = ident.ident_id
        rep["created"] = created

        # 既有身份也要跟官方对齐：操作员可能改了 MuMu 的 phone_* 键，
        # 档案不跟着改就会"档案说 A、设备是 B"。只对齐机型/屏幕，不动
        # android_id / 序列号（那两个变了等于换设备，会触发二次校验）。
        if not created and ident.ident_id and \
                _flag(sec.get("prefer_vendor"), True):
            try:
                from . import vendor as vendor_mod
                vend = vendor_mod.read(vm_index=vm) or {}
                if vend:
                    synced = build_from_vendor(vend, 0, vm=vm)
                    cur = ident.profile or {}
                    newp = synced.profile or {}
                    diff = {k: (cur.get(k), newp.get(k))
                            for k in ("brand", "model", "manufacturer",
                                      "display", "density")
                            if newp.get(k) and cur.get(k) != newp.get(k)}
                    if diff:
                        ident.data["profile"] = newp
                        store.put(ident)
                        rep["profile_synced"] = {
                            k: {"from": v[0], "to": v[1]}
                            for k, v in diff.items()}
            except Exception:
                pass

        # 已在本 boot 周期应用过 → 只花两条 adb（boot_id + 标记）。
        #
        # 必须带上 boot_id 一起比：``/data/local/tmp`` 是持久的，重启后标记
        # 还在。只比 identity_id 的话，重启后会被误判成「已应用」→ 身份永远
        # 不重写（props 是内存态，重启即回 MuMu），而这正是「刚登录又被踢」
        # 的形态。所以宁可多花一条 adb，也不拿过期标记当证据。
        boot = boot_id(dev)
        marker = applied_marker(dev, vm)
        if boot and not force and marker == "%s %s" % (ident.ident_id, boot):
            rep["ok"] = True
            rep["skipped"] = "applied this boot"
            return rep

        plain = props_of(dev)
        if not plain:
            rep["error"] = "device offline"
            return rep
        # 只在**真的是模拟器**上动手：真机跑这套等于自找麻烦，而测试里的
        # 假设备 props 读不到 → 自然跳过，不会污染既有单测。
        if not _is_emulator(plain) and not _flag(sec.get("force"), False):
            # 例外：身份来自 **MuMu 官方设置**时，那些值已经就是设备事实
            # （官方注入在虚拟机启动时生效），不需要我们"应用"任何东西，
            # 因此可以安全落盘——否则会出现"报告说 Samsung、档案是空"的偏差。
            if created and (ident.data.get("source") == "vendor"):
                store.put(ident)
                rep["saved"] = "vendor-source"
            rep["ok"] = True
            rep["skipped"] = "not an emulator"
            return rep

        if created:
            store.put(ident)
            if logger:
                logger.info("[android] 分配设备身份 %s（%s %s）",
                            ident.ident_id, ident.profile.get("brand", ""),
                            ident.profile.get("model", ""))

        ap = apply(dev, ident, use_root=sec.get("use_root"))
        rep["apply"] = ap
        ident.data["applied_at"] = time.time()
        ident.data["applied_boot"] = boot
        ident.data["rotations"] = int(ident.data.get("rotations") or 0)
        store.put(ident)
        write_marker(dev, ident)

        # 改过 ro.* 或 ro.debuggable 这类字段才需要重启框架
        need_restart = bool(ap.get("applied")) and not sec.get("no_restart")
        if need_restart and ap.get("resetprop"):
            mode = str(sec.get("reboot") or "zygote")
            rep["changed"] = restart_framework(dev, mode)
            rep["reboot"] = mode
        rep["audit"] = audit(dev)
        rep["audit"]["identity_id"] = ident.ident_id
        rep["ok"] = True
        if logger:
            logger.info(
                "[android] 身份已应用 %s：%d 条生效 / %d 条失败，自检 %d 分",
                ident.ident_id, len(ap.get("applied") or []),
                len(ap.get("failed") or []), rep["audit"].get("score", 0))
        return rep
    except Exception as e:      # 身份层永远不许把采集带崩
        rep["error"] = "%s: %s" % (type(e).__name__, str(e)[:160])
        if logger:
            logger.warning("[android] 身份层异常：%s", rep["error"])
        return rep


def rotate(dev, config: dict = None, logger=None, *, user_data_dir="user_data",
           profile="", vm: int = 0, pool=None) -> dict:
    """显式换一台设备（换机型 + 换派生 ID）。

    **只在真的被判定为设备风险时用**：换身份本身就是一次「新设备登录」，
    携程/飞猪会走一轮二次校验；频繁换比不换更糟。所以这里不自动调用，
    由操作员或 ``riskscore`` 的强提示触发。
    """
    sec = _cfg(config)
    store = default_store(user_data_dir, profile)
    old = store.get(vm)
    idx = int(old.data.get("pool_index") or 0) + 1
    seed = _seed_for("rotate-%s-%d-%d" % (profile, vm, int(time.time())))
    new = build(seed + idx, vm=vm, pool=pool or PHONE_POOL)
    new.data["rotations"] = int(old.data.get("rotations") or 0) + 1
    new.data["rotated_from"] = old.ident_id
    store.put(new)
    try:
        os.remove(_mark_path(vm))
    except OSError:
        pass
    rep = ensure(dev, config, logger, user_data_dir=user_data_dir,
                 profile=profile, vm=vm, force=True)
    rep["rotated"] = True
    rep["from"] = old.ident_id
    if logger:
        logger.warning("[android] 已更换设备身份 %s → %s（第 %d 次）",
                       old.ident_id, new.ident_id, new.data["rotations"])
    return rep
