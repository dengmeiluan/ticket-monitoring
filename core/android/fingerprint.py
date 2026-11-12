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
        "device": "RMX3350", "product": "RMX3350", "board": "mt6893",
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
    # ── Android 15 / SDK 35 的真机（2026-11-04 新增）──
    #
    # 为什么必须有：本机 MuMu 是 **Android 15（SDK 35）**，而上面 8 台全是
    # Android 12/13 —— 池里**没有一台能匹配**，于是 `ensure()` 只能退回
    # MuMu 自带的那套配置：`Samsung/a52xq/a52xq:15/...`。
    # 而 **三星 A52 5G 最高只到 Android 13**，"A52 跑 Android 15" 在真机上
    # 不存在 —— 这是逻辑矛盾，任何指纹 SDK 都能判出来（不需要特征库）。
    #
    # 携程登录报 `存在风险，限制登录 50003`，这是最可能的原因之一。
    # 换成一款**原厂就是 Android 15** 的机型，所有字段就自洽了。
    {
        "brand": "google", "manufacturer": "Google",
        "model": "Pixel 8 Pro",
        "device": "husky", "product": "husky", "board": "husky",
        "hardware": "husky", "platform": "zuma",
        "soc": "Google Tensor G3",
        "release": "15", "sdk": "35",
        "build_id": "AP4A.250105.002",
        "build_display": "AP4A.250105.002",
        "fingerprint": ("google/husky/husky:15/AP4A.250105.002/"
                        "12541311:user/release-keys"),
        "display": (1344, 2992), "density": 480,
    },
    {
        # vivo X200 Pro（V2405A）：原厂 Android 15，天玑 9400。
        # 用户的真机是 vivo X300 Pro —— 同品牌，账号历史里的设备画像对得上；
        # 而 X300 Pro 是 Android 16，会和本实例的 Android 15 矛盾（A52 那个坑），
        # 所以选 X200 Pro：**品牌一致 + 版本自洽**。
        "brand": "vivo", "manufacturer": "vivo",
        "model": "V2405A",
        "device": "V2405A", "product": "V2405A", "board": "k6897v1_64",
        "hardware": "mt6991", "platform": "mt6991",
        "soc": "MediaTek Dimensity 9400",
        # SoC 的 OEM 编号：真机 `ro.soc.model` 报 MT6991。
        # 这不是可有可无的字段——`ro.hardware`/`ro.board.platform` 与
        # `ro.soc.model` 三者必须指向同一颗芯片，任何一处留在模拟器的
        # `kona`（骁龙 865）上，就是「自称天玑 9400、实为高通平台」的硬矛盾。
        "soc_model": "MT6991",
        # 构建机名：绝对不能留 `localhost`（那等于自报"这条指纹是就地编的"）。
        # 厂商 OTA 构建机是 `bbzp-...` 这一族内网主机名。
        "build_host": "bbzp-vivo-build-01",
        "release": "15", "sdk": "35",
        "build_id": "AP3A.240905.015",
        "build_display": "AP3A.240905.015",
        "fingerprint": ("vivo/V2405A/V2405A:15/AP3A.240905.015/"
                        "compiler11091536:user/release-keys"),
        "display": (1260, 2800), "density": 453,
    },
    {
        "brand": "Xiaomi", "manufacturer": "Xiaomi",
        "model": "23127PN0CC",
        "device": "shennong", "product": "shennong", "board": "shennong",
        "hardware": "qcom", "platform": "pineapple",
        "soc": "Qualcomm Snapdragon 8 Gen 3",
        "release": "15", "sdk": "35",
        "build_id": "AQ3A.240806.005",
        "build_display": "OS2.0.6.0.VNCCNXM",
        "fingerprint": ("Xiaomi/shennong/shennong:15/AQ3A.240806.005/"
                        "OS2.0.6.0.VNCCNXM:user/release-keys"),
        # 小米 14 实测 1200×2670 / **460dpi**（不是 440）
        "display": (1200, 2670), "density": 460,
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

# SoC 描述 → 真机 `ro.soc.model` 里的 OEM 编号。
#
# 为什么要这张表：`ro.soc.model` 是 Android 12 起真机必报的字段，而模拟器
# 上它要么缺失、要么留着出厂平台的编号。一台宣称「天玑 9400」的机器，
# `ro.hardware` 说 mt6897 而 `ro.soc.model` 说别的，本身就是矛盾。
# 池条目可以自带 `soc_model`（更精确）；没带的用这张表按 SoC 描述兜底，
# 这样 `PROP_KEYS` 里的每一个键在 `props()` 里**恒有值**，不会出现
# 「某个机型少写一个键」导致 apply 静默跳过。
SOC_MODEL_BY_SOC = {
    "MediaTek Dimensity 8100": "MT6895",
    "MediaTek Dimensity 1200": "MT6893",
    "MediaTek Dimensity 700": "MT6833",
    "MediaTek Dimensity 9400": "MT6991",
    "Qualcomm Snapdragon 870": "SM8250",
    "Qualcomm Snapdragon 778G": "SM7325",
    "Qualcomm Snapdragon 8 Gen 1": "SM8450",
    "Qualcomm Snapdragon 8 Gen 3": "SM8650",
    "Google Tensor G3": "GS301",
}

# 机型码 → 对外市场名（r1063 T83）。真机 `ro.product.marketname` 有值；
# 空的会与「品牌 + 型号」对不上，属「设备脸缺件」。
MARKETNAME_BY_MODEL = {
    "V2405A": "vivo X200 Pro",
    "V2168A": "vivo Y31s",
    "23127PN0CC": "Xiaomi 14",
    "2201123C": "Xiaomi 12",
    "M2102J20SG": "Redmi Note 10 Pro",
    "PEGM00": "OPPO Reno7",
    "ANY-AN00": "HONOR X30",
    "RMX3350": "realme GT Neo3",
    "LE2100": "OnePlus 9R",
    "SM-S9280": "Galaxy S24 Ultra",
    "Pixel 8 Pro": "Pixel 8 Pro",
    "Redmi K50": "Redmi K50",
}

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
    # 分区指纹必须一起写（2026-11-05 补）。只改主指纹，`dumpsys` /
    # PackageManager 读到的 `ro.system.build.fingerprint` 还是模拟器原串，
    # 等于把矛盾指给检测方看。
    "ro.system.build.fingerprint",
    "ro.vendor.build.fingerprint",
    "ro.product.build.fingerprint",
    "ro.odm.build.fingerprint",
    # 构建描述三件套：真机的 description 是 flavor+release+id+incremental+tags
    # 的函数，而模拟器这里会留下 `missi_` / `mumu_` 内部代号与自己的构建号。
    "ro.build.description",
    "ro.build.flavor",
    "ro.build.version.incremental",
    "ro.build.tags",
    "ro.build.type",
    "ro.build.user",
    "ro.build.host",
    "ro.hardware",
    "ro.board.platform",
    "ro.boot.hardware",
    # 平台自洽：**不写** first_api_level / vndk.version（2026-11-05 实测：
    # 把 vndk 改成与真实 VNDK 不符会让 App 启动即 SIGSEGV —— 那是 linker
    # 选库的输入，不是描述性字段）。`ro.soc.model` 是纯描述，可以写。
    "ro.soc.model",
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
        """身份 → props 映射（只含 PROP_KEYS，值全部是字符串）。

        所有派生字段都从 **`fingerprint` 这一条**算出来，不另写常量：
        AOSP 的指纹是五段 ``brand/product/device:release/build_id/incremental:tags``，
        `ro.build.flavor` / `ro.build.description` / `ro.build.version.incremental`
        本来就是它的函数值。两处各写一份迟早漂移，一漂移就是
        「description 说 compiler11091536、incremental 说 1171」这种
        一眼假的组合（50003 的直接判据之一）。
        """
        p = self.profile
        model = str(p.get("model") or "")
        brand = str(p.get("brand") or "")
        fp = str(p.get("fingerprint") or "")

        # ---- 从指纹解出 flavor/description/incremental（唯一真源）----
        rel = str(p.get("release") or "")
        bid = str(p.get("build_id") or "")
        inc = ""
        tags = "release-keys"
        flavor = "%s-user" % (str(p.get("device") or model).replace(" ", ""))
        if fp:
            try:
                # AOSP 指纹有**两个**冒号：
                #   brand/product/device : release/build_id/incremental : type/tags
                # 只按第一个冒号切，会把 `:user` 混进 incremental，拼出
                # `compiler11091536:user` 这种一眼假的串（本轮踩到）。
                cols = fp.split(":")
                if len(cols) >= 2:
                    head = cols[0]
                    mid = cols[1].split("/")
                    if len(mid) >= 3:
                        rel = mid[0] or rel
                        bid = mid[1] or bid
                        inc = mid[2]
                    if len(cols) >= 3:
                        tt = cols[2].split("/")
                        tags = (tt[1] if len(tt) >= 2 else tt[0]) or tags
                seg = head.split("/")
                if len(seg) >= 3 and seg[2]:
                    # **保持原始大小写**：真机是 `V2405A-user`，不是
                    # `v2405a-user`。小写化本身就是一条"非厂商拼装"的痕迹。
                    flavor = "%s-user" % seg[2]
            except Exception:
                pass
        if not inc:
            # 兜底：至少不和 build.id 撞成同一个串（那是最明显的假指纹）
            inc = str(p.get("incremental") or "")

        desc = " ".join(x for x in (flavor, rel, bid, inc, tags) if x)
        sdk = str(p.get("sdk") or "")
        soc_model = str(p.get("soc_model")
                        or SOC_MODEL_BY_SOC.get(str(p.get("soc") or ""), ""))

        # 平台代号按 **SoC 推导**（r1063 T83）：之前依赖池里的 platform/hardware
        # 字段，缺了就落回 "qcom" 或旧值 mt6897，而 cpuinfo 说 MT6991 —— 同一
        # 机型两颗芯片，正是风控判"环境异常"的常见依据（对应携程 50003）。
        _soc2plat = {
            "MT6991": ("mt6991", "mt6991"),
            "MT6989": ("mt6989", "mt6989"),
            "MT6897": ("mt6897", "mt6897"),
            "MT6893": ("mt6893", "mt6893"),
            "MT6853": ("mt6853", "mt6853"),
            "MT6895": ("mt6895", "mt6895"),
            "SM8650": ("pineapple", "qcom"),
            "SM8550": ("kalama", "qcom"),
            "SM8475": ("cape", "qcom"),
            "SM7325": ("yupik", "qcom"),
            "SM8250": ("kona", "qcom"),
            "SM8350": ("lahaina", "qcom"),
        }
        _soc_up = str(soc_model or "").upper()
        _plat, _hw = "", ""
        for _k, _v in _soc2plat.items():
            if _soc_up.startswith(_k):
                _plat, _hw = _v
                break
        # **推导优先**（r1063 T83）：池里的旧值可能是错的（V2405A 就填了
        # mt6897，而它是天玑 9400 = MT6991）。SoC 是硬事实，以它为准。
        _plat = _plat or str(p.get("platform") or "")
        _hw = _hw or str(p.get("hardware") or "")
        # SoC 厂商与市场名（真机都有；缺了就是"设备脸"缺件）
        _soc_mfr = str(p.get("soc_manufacturer") or
                       ("MediaTek" if _soc_up.startswith("MT") else
                        ("Qualcomm" if _soc_up.startswith("SM") else "")))
        if not _soc_mfr:
            # 先看 soc 名字前缀（'MediaTek Dimensity 8100' → MediaTek）
            _nm = str(p.get("soc") or "")
            for _m in ("MediaTek", "Qualcomm", "Google"):
                if _nm.startswith(_m):
                    _soc_mfr = _m
                    break
        if not _soc_mfr:
            # 再看平台前缀，别留空
            _pl = str(_plat or "").lower()
            if _pl.startswith("mt"):
                _soc_mfr = "MediaTek"
            elif _pl in ("qcom", "kona", "lahaina", "cape", "yupik",
                         "pineapple", "kalama", "aresin", "venus", "husky"):
                _soc_mfr = "Qualcomm" if _pl != "husky" else "Google"
        _market = str(p.get("marketname") or MARKETNAME_BY_MODEL.get(model, ""))

        out = {
            "ro.product.model": model,
            "ro.product.brand": brand,
            "ro.product.manufacturer": str(p.get("manufacturer") or brand),
            "ro.product.device": str(p.get("device") or ""),
            "ro.product.name": str(p.get("product") or ""),
            "ro.product.board": str(p.get("board") or ""),
            "ro.build.product": str(p.get("device") or ""),
            "ro.build.id": bid,
            "ro.build.display.id": str(p.get("build_display") or bid),
            "ro.build.fingerprint": fp,
            # 指纹必须**五个分区全部同一串**：只改主指纹、留
            # `ro.system.build.fingerprint` 还是模拟器原串，等于自己
            # 指明了矛盾在哪。dumpsys 与 PackageManager 都会读分区串。
            "ro.system.build.fingerprint": fp,
            "ro.vendor.build.fingerprint": fp,
            "ro.product.build.fingerprint": fp,
            "ro.odm.build.fingerprint": fp,
            "ro.build.description": desc,
            "ro.build.flavor": flavor,
            "ro.build.version.incremental": inc,
            "ro.build.tags": tags,
            "ro.build.type": "user",
            "ro.build.user": "builder",
            # host 不能是 `localhost`（那是"容器/模拟器里现编的"特征）
            "ro.build.host": str(p.get("build_host") or "builder"),
            "ro.hardware": _hw or "qcom",
            "ro.board.platform": _plat or "qcom",
            "ro.boot.hardware": _hw or "qcom",

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
            # 真机报的是 `LOADED`（不是 `READY`）。这条不改也不算暴露，
            # 但既然设备本来就报 LOADED，改成一致可以少一条无谓差异 →
            # 少一次 setprop → 少一次"看着像要修"的机会。
            "gsm.sim.state": "LOADED",
        }
        # **`ro.product.first_api_level` / `ro.vndk.version` 绝对不写**
        # （2026-11-05 实测：写了会让 App 启动即 SIGSEGV）。
        #
        # 第一版把它们当"平台自洽"的一部分写成 35（Android 15 的 SDK），
        # 逻辑上很顺：一台 Android 15 的机器 `first_api_level=31` 看着就该改。
        # 但实测后果是**携程启动直接崩**：
        #
        #   11-05 16:56:47 F libc: Fatal signal 11 (SIGSEGV)
        #                in pid 4610 (ip.android.view)
        #
        # 原因是 `ro.vndk.version` 不是"描述性字段"，而是 **linker 选 VNDK
        # 命名空间 / 选哪套 vendor 库**的输入：系统的实际 VNDK 是 31，
        # 你把它改成 35，linker 就会去找一套不存在的 vndk-35 目录，
        # native 库加载失败 → 进程 SIGSEGV。
        # `ro.product.first_api_level` 同理参与 PackageManager 的兼容判定。
        #
        # 判据与 ABI 同类：**改不动的就别撒谎**。宁可留一条"API 级别偏旧"
        # 的弱痕迹，也不能让 App 起不来——起不来的渠道爬取率是 0。
        if soc_model:
            out["ro.soc.model"] = soc_model
        else:
            # 兜底：表里没有的 SoC 宁可报一个与 ro.hardware 同源的平台串，
            # 也不要留空——空值会让 apply 跳过这个键，设备上就继续保留
            # 模拟器出厂时那个"我已经被改过"的编号。
            out["ro.soc.model"] = str(p.get("platform") or "")
        # SoC / 市场名：**有值才写**（r1063 T83）。写空值比不写更糟——
        # 真机这两个 prop 都有值，写成空串等于自己声明"我这台设备缺件"。
        if _soc_mfr:
            out["ro.soc.manufacturer"] = _soc_mfr
        if _market:
            out["ro.product.marketname"] = _market
            out["ro.config.marketing_name"] = _market
        return out


    def props_unsafe_note(self) -> str:
        """给报告用：说明哪些字段是"想改但改不动"的。"""
        return ("ro.product.first_api_level / ro.vndk.version 不伪装："
                "它们是 linker 与 PackageManager 的运行时输入，"
                "改成与真实 VNDK 不符会让 App 启动即 SIGSEGV（实测）")

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

    # **官方只给 brand/model，其它字段必须从"匹配的池机型"补齐**
    # （2026-11-04 修）。不补就会出现"杂交体"：
    #
    #   实测：brand/model = vivo/V2405A（官方键），但 device/board = rubens、
    #   hardware = mt6895、build.id = SP1A.210812.016、fingerprint 带 :12/
    #   —— 因为那些字段还来自 `build()` 池机型（第一台是 Redmi K50）。
    #   这种"vivo 型号 + 红米 device/board + Android 12"比原来还糟。
    #
    # 解法：拿官方 model 去池里找**同型号**的机型，用它的一致性字段补齐
    # （device/product/board/hardware/platform/soc 等）。
    _pool_hit = None
    for _c in PHONE_POOL:
        if str(_c.get("model") or "").lower() == str(miit or model).lower():
            _pool_hit = _c
            break
    if _pool_hit:
        # `release` / `sdk` 也要一起取（2026-11-05 修）。
        #
        # 原先只补 device/product/board/hardware/platform/soc，于是当
        # `build()` 抽到的池条目与官方机型不是同一台时，会出现
        # **"vivo V2405A + Android 12 / sdk 31"** 的杂交体：
        # 机型字段来自 V2405A 池条目，版本字段却还留在 pool[seed] 那台
        # （例如 LE2100 的 Android 12）。后果很具体：
        #   `props()` 会算出 `ro.product.first_api_level=31`、
        #   `ro.vndk.version=31`，与真机 Android 15 的 35 不符，
        #   于是每轮 `apply()` 都判定"有差异" → 去 `adb root` → 把 adbd 弄坏。
        #
        # 取值顺序仍然尊重事实：下面 `ro_values` 的循环会覆盖
        # `release`/`sdk`（它们不在 `_POOL_OWNED` 里），所以设备真实系统
        # 版本优先；官方没给时才用池条目的值。两全。
        for _k in ("device", "product", "board", "hardware", "platform",
                   "soc", "release", "sdk"):
            if _pool_hit.get(_k):
                prof[_k] = _pool_hit[_k]
        # **构建字段也必须取池条目的规范值**（2026-11-05 修）。
        #
        # 原先这里只补了 device/board，然后**照旧拿设备上的 build_id
        # 重拼指纹**，于是拼出：
        #     vivo/V2405A/V2405A:15/V417IR/V417IR release-keys:user/release-keys
        # 其中 `V417IR` 是 **MuMu 自己的构建号**。整台设备宣称自己是
        # vivo X200 Pro，构建号却是模拟器的 —— 这是 50003「设备有风险」
        # 里最硬的一条：机型字段可以伪装，构建号一读就露。
        #
        # 判据来自池条目自带的真机指纹（`vivo/...:15/AP3A.240905.015/
        # compiler11091536:user/release-keys`），它本来就是自洽的，直接用。
        for _k in ("build_id", "build_display", "fingerprint", "soc_model"):
            if _pool_hit.get(_k):
                prof[_k] = _pool_hit[_k]
    # build 指纹：池命中时**保持池的原串**；只有没命中才按设备字段重拼。
    if not (_pool_hit and _pool_hit.get("fingerprint")):
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

    # ── 一致性纠正（2026-11-04）──
    #
    # 官方键只给 brand/model，**不给系统版本**；而设备的
    # `ro.build.version.release/sdk` 是 MuMu 的 `device-prop-configs`
    # 按"最新 Android"注入的。两者拼在一起就可能**自相矛盾**：
    #
    #     实测：phone_miit = SM-A5260（三星 A52 5G，最高 Android 13）
    #           ro.build.version.release = 15 / sdk = 35
    #           → "A52 跑 Android 15" 在真机上不存在
    #
    # 这是**逻辑矛盾**，指纹 SDK 不需要特征库就能判出来。携程登录报
    # `存在风险，限制登录 50003` 很可能就是它（比 `ro.nemu` 更硬）。
    #
    # 纠正方式：拿设备真实 SDK 去池里找一台**原生就是该版本**的机型，
    # 用它的一致性字段（release/sdk/build_id/fingerprint/device/board…）
    # 覆盖掉矛盾部分。这样"机型 + 系统"是真机上存在的组合。
    _real_sdk = str(v.get("ro_sdk") or v.get("build_sdk") or "").strip()
    # **先判断 vendor 自己是否已经自洽**：官方给的 brand/model 如果本来就
    # 能跑这个 SDK，就**不该覆盖**（2026-11-04 修）。
    #
    # 实测踩到的坑：官方键已改成 vivo/V2405A（X200 Pro 原厂就是 Android 15，
    # 与设备自洽），但一致性纠正仍然按"池里优先国内品牌"选了小米 14，
    # 把正确的 vivo 身份盖掉了 —— 设备刚写进去的 vivo 又被改回 Xiaomi。
    #
    # 判据：vendor 的 brand 在已知"能跑该 SDK"的品牌里，且池中存在同品牌
    # 且同 SDK 的机型 → 视为自洽，跳过纠正。
    if _real_sdk:
        _brand_l = (brand or "").lower()
        _same = [c for c in PHONE_POOL
                 if str(c.get("sdk") or "") == _real_sdk
                 and str(c.get("brand") or "").lower() == _brand_l]
        if _same:
            # 官方品牌本身就有该版本的机型 → 自洽，**不覆盖机型**
            # （但要把池里的一致字段补齐，否则 fingerprint 会混进别的版本：
            #  实测出现过 `vivo/V2405A/V2405A:**12**/...` —— 因为 release/
            #  build_id 还来自 `build()` 的池机型（第一台是 Android 12）。
            #  这里只补齐版本相关字段，机型字段保持官方值。）
            _hit = None
            for c in _same:
                if str(c.get("model") or "") == (miit or model):
                    _hit = c
                    break
            _hit = _hit or _same[0]
            for _k in ("release", "sdk", "build_id", "build_display",
                       "fingerprint"):
                if _hit.get(_k):
                    prof[_k] = _hit[_k]
            prof["consistency_note"] = ("vendor %s/%s 与 sdk=%s 自洽，"
                                        "未覆盖机型（版本字段按池补齐）"
                                        % (brand, miit or model, _real_sdk))
            _real_sdk = ""
    if _real_sdk:
        # **优先国内品牌**（2026-11-04 用户提醒）。
        # 去哪儿/携程/同程的用户群几乎全是国内机；一台 Pixel 在国内是
        # 罕见设备（无官方渠道、Google 服务不可用、通常无国内运营商 SIM），
        # 风控引擎普遍把"该地区罕见机型"本身当风险信号。
        # 所以在"版本自洽"的候选里，先挑国内牌子。
        _DOMESTIC = ("Xiaomi", "Redmi", "OPPO", "vivo", "HONOR",
                     "realme", "OnePlus", "Huawei", "honor")
        _cands = [c for c in PHONE_POOL
                  if str(c.get("sdk") or "") == _real_sdk]
        _cands.sort(key=lambda c: 0 if c.get("brand") in _DOMESTIC else 1)
        for cand in _cands:
            prof["brand"] = cand["brand"]
            prof["manufacturer"] = cand.get("manufacturer", cand["brand"])
            prof["model"] = cand["model"]
            prof["device"] = cand["device"]
            prof["product"] = cand["product"]
            prof["board"] = cand["board"]
            prof["hardware"] = cand["hardware"]
            prof["platform"] = cand["platform"]
            prof["release"] = cand["release"]
            prof["sdk"] = cand["sdk"]
            prof["build_id"] = cand["build_id"]
            prof["build_display"] = cand["build_display"]
            prof["fingerprint"] = cand["fingerprint"]
            prof["display"] = list(cand["display"])
            prof["density"] = cand["density"]
            prof["consistency_fixed"] = ("vendor 的 %s/%s 与 sdk=%s 矛盾，"
                                         "已按池机型 %s 纠正"
                                         % (brand or "?", miit or "?",
                                            _real_sdk, cand["model"]))
            break

    # **档案必须记设备上的真实值，不是池里的理想值**（2026-11-04）。
    #
    # 第 3 轮就定过这条：官方注入是唯一真正生效的来源，档案若按池写
    # "Redmi K50"，就会出现"档案说 Redmi、设备是 Samsung"——报告骗自己，
    # 风控读到的却是另一套。
    #
    # 本轮又踩了一次：池里 vivo 条目写的是 `hardware=mt6897`、
    # `build_id=AP3A.240905.015`（真机 vivo X200 Pro 的值），但 MuMu 实际
    # 注入的是 `hardware=vivo`、`build.id=V417IR`（它把品牌名抄进 hardware，
    # build.id 用它自己的）。
    #
    # **2026-11-05 修正**：上面那段的结论（"运行中改这些会把设备搞挂，
    # 所以只能照实记录"）建立在"热写不可行"的前提上，而那个前提已被推翻：
    #
    #   * 热写这 18 个键不会让框架崩，只会让 adbd 掉线；
    #   * adbd 掉线的真因是 `restart_framework` 用了 `stop; start`（连 adbd
    #     一起停），改成 `setprop ctl.restart zygote` 后 adb 连接不变；
    #   * `MuMuManager sh -v 0 -c` 提供了一条不依赖 adb 的 root 通道，
    #     即使 adb 掉了也能确认设备本身一直健康。
    #
    # 所以现在**不再"照实记录设备注入的假值"**：只要能在池里匹配到同型号
    # 条目，那些一致性字段就以**池条目的规范值为准**（设备上的值是要被我们
    # 改写掉的目标，不是真源）。否则会出现最坏的一种循环——
    # 我们刚把 `hardware` 改成 mt6897，下一轮"档案与设备对齐"又把它按设备
    # 的 vivo 改回档案，然后再写回设备，永远收敛不到真机口径。
    #
    # `release` / `sdk` 例外：它们描述**正在运行的系统**，必须以设备为准，
    # 否则档案说 Android 15、系统是 12，比不改更假。
    ro_values = v.get("ro_values") or {}
    _field_from_prop = {
        "brand": "ro.product.brand",
        "manufacturer": "ro.product.manufacturer",
        "model": "ro.product.model",
        "device": "ro.product.device",
        "product": "ro.product.name",
        "board": "ro.product.board",
        "hardware": "ro.hardware",
        "platform": "ro.board.platform",
        "release": "ro.build.version.release",
        "sdk": "ro.build.version.sdk",
        "build_id": "ro.build.id",
        "build_display": "ro.build.display.id",
        "fingerprint": "ro.build.fingerprint",
    }
    # 池命中的机型：这些字段由池（真机规范值）说了算，不让设备注入值覆盖。
    _POOL_OWNED = ("brand", "manufacturer", "model", "device", "product",
                   "board", "hardware", "platform", "build_id",
                   "build_display", "fingerprint")
    for _f, _prop in _field_from_prop.items():
        if _pool_hit and _f in _POOL_OWNED:
            continue
        _real = str(ro_values.get(_prop) or "").strip()
        if _real:
            prof[_f] = _real
    if ro_values:
        prof["values_from"] = ("pool" if _pool_hit else "device")

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


def adb_root(dev, wait_s: float = 12.0) -> bool:
    """**真的执行一次 `adb root`**，而不是只看当前是不是 root。

    为什么需要这个函数（2026-11-05）：
    ``_root()`` 是**探测**，它只读 `id`。我在 ``apply()`` 里写"先拿 root"
    时误用了它 —— 结果什么也没做，`resetprop` 探测照样因为
    `/data/adb/magisk/magisk: inaccessible` 失败，于是退回 `setprop`，
    18 条 `ro.*` 全部静默不生效。日志还诚实写成"需完整 Magisk"，
    把"这一轮没 root"读成了"这台机器没有 Magisk"。

    `adb root` 会让 adbd 重启（TCP 连接会短暂断），所以这里等它回来自我
    验证一次 `id`；期间顺手试一次传输自愈（MuMu 同机有两个序列）。
    """
    if _root(dev):
        return True
    _call(dev, "root")
    end = time.time() + max(2.0, float(wait_s or 12))
    while time.time() < end:
        time.sleep(1.5)
        if _root(dev):
            return True
        _fn = getattr(dev, "recover_transport", None)
        if _fn is not None:
            try:
                _fn()
            except Exception:
                pass
    return _root(dev)


def _su(dev) -> bool:
    """设备上有没有 ``su``。

    **MuMu 的 ``adb root`` 之后 shell 本身就是 uid=0，且常常没有 su 二进制。**
    这时若仍按 ``su -c <script>`` 调用，整段脚本会以
    ``/system/bin/sh: su: not found`` 整体失败——不是某一条 props 失败，是
    全部失败，而报告里只看到 20 个 FAIL。所以先问一次。
    """
    # 整条脚本作为单个 argv：三段 argv 会让设备内层只剩 `sh -c command`
    # （`-v su` 被当位置参数丢掉）→ 永远查不到 su，装了 Magisk 的机器上
    # 会误判成"没有 su"，进而把 `su -c` 那条路整段废掉。
    out = _text(sh_script(dev,
                          "command -v su || ls /system/bin/su /system/xbin/su "
                          "2>/dev/null || true"))
    return "su" in out and "/su" in out


def write_remote(dev, path: str, text: str, *, timeout=None) -> bool:
    """把一小段文本写到设备上。**统一走这一个实现**，别再各自拼
    `sh -c "echo X > path"`。

    为什么必须有它（2026-11-04 实机确诊）：

    ```python
    _call(dev, "shell", "sh" … "-c" …)   # 三段 argv，错误形态
    _call(dev, "shell", "cat", "/data/local/tmp/x.ok")   # → 空！
    ```

    **写入静默失败**：`>` 在 Windows 上被本地命令行截走，命令根本没完整到设备。
    而读（`cat`）是好的，所以没有任何报错——只留下一个"永远不成立"的
    per-boot 门槛：`stealth.prepare()` / `emulator_tuning` / 身份标记
    全都因此**每轮重做全量隐藏**（denylist 读写 sqlite + 抓 logcat 快照），
    慢且白折腾，而且没人察觉。

    实现按能力分两条：

    * 设备支持 `push`（`AdbDevice`）→ 本地临时文件 + push，**最稳**，
      路径里没有引号、管道、重定向这些会被吃掉的字符；
    * 不支持（测试替身等）→ 退回 `sh -c` 写法，保持原语义。

    写完**读回校验**（本仓库第 N 次同条纪律：命令返回码不可信）。
    """
    text = str(text if text is not None else "")
    pushed = False
    try:
        if hasattr(dev, "push"):
            import os as _os
            import tempfile as _tf
            _fd, _local = _tf.mkstemp(suffix=".txt")
            with _os.fdopen(_fd, "w", encoding="utf-8", newline="\n") as _f:
                _f.write(text)
            try:
                pushed = bool(dev.push(_local, path))
            finally:
                try:
                    _os.unlink(_local)
                except OSError:
                    pass
    except Exception:
        pushed = False
    if not pushed:
        # **整条脚本作为单个 argv**（`sh_script`）：写成 `("shell","sh","-c",X)`
        # 时 adb 拼 argv 交给设备 shell 重解析，内层只剩 `sh -c echo`
        # → 文件写出 0 字节（实测）。路径不加引号：它是内部常量，
        # 加引号会让命令形状变成 `> '/path'`，与各测试替身的路由不一致；
        # 真正要防的是值里的怪字符，那由 `_q(text)` 负责。
        sh_script(dev, "echo %s > %s" % (_q(text), path), timeout=timeout)
    got = _text(_call(dev, "shell", "cat", path, timeout=timeout)).strip()
    if got == text.strip():
        return True
    return False


def as_root(dev, script: str, timeout=None):
    """以 root 身份执行一段 shell（自动选 su / 直连 root shell）。

    **必须走"本地临时文件 → `adb push` → 执行"，不能用 `sh -c "<脚本>"`**
    （2026-11-04 实测，同一个函数改了三版才稳）：

    * `adb shell sh -c "echo 'k' 'v'"` —— 单引号在传输中丢失，
      `magisk` 收到被拆散的参数、打印帮助文本，看起来像"执行了但没生效"；
    * `adb shell sh -c "echo x | base64 -d | sh"` —— 管道符被 **Windows
      本地 shell** 解释，**stdout 整个丢掉**（连 `echo hi` 都返回空串）；
    * `adb shell sh -c "echo x > /data/.../f"` —— `>` 同样被本地 shell 吃掉，
      设备上那个文件是**空的**；
    * 手敲 `adb shell "..."` 却一切正常 —— 所以是"参数传递"环节变形，
      不是设备问题。

    走 push 之后整条链路不出现引号、管道、重定向，最稳。
    `push` 的返回码必须检查：曾经有个兜底分支**不看返回码就认定成功**，
    于是脚本没推上去、后续执行的是**上一个残留脚本**。
    """
    _txt = str(script or "")
    if not _txt.strip():
        return ""
    _remote = "/data/local/tmp/.tm_asroot.sh"
    import os as _os
    import tempfile as _tf
    try:
        _fd, _local = _tf.mkstemp(suffix=".sh")
        with _os.fdopen(_fd, "w", encoding="utf-8", newline="\n") as _f:
            _f.write(_txt)
    except Exception:
        return ""
    try:
        # **只有 `dev` 具备 push 能力时才走 push**（真机路径）。
        # 曾经这里有个 subprocess 兜底，并且**不看返回码就认定成功**——
        # 于是"脚本没推上去、执行的是上一个残留脚本"。现在：
        #   有 push → 必须返回 True 才继续；没有 push → 直接原样执行。
        _can_push = hasattr(dev, "push")
        pushed = False
        if _can_push:
            try:
                pushed = bool(dev.push(_local, _remote))
            except Exception:
                pushed = False
        if pushed:
            _call(dev, "shell", "chmod", "755", _remote, timeout=timeout)
            if _su(dev):
                return _call(dev, "shell", "su", "-c", _remote,
                             timeout=timeout)
            return _call(dev, "shell", "sh", _remote, timeout=timeout)
        # **没有 push 能力的设备**（测试替身、只暴露 `_sh` 的旧接口）：
        # 原样把脚本交给 shell。真机不会走到这里——`AdbDevice` 有 `push`，
        # 而 Windows 上这条路会把管道/重定向吃掉（正是本轮修的 bug）。
        # 无 push 能力（测试替身）时退回：整条脚本作为单个 argv，
        # 绝不套 `sh -c`（会被 adb 拆参数，见 `sh_script` 的说明）。
        return sh_script(dev, _txt, timeout=timeout)
    except Exception:
        return ""
    finally:
        try:
            _os.unlink(_local)
        except OSError:
            pass


def _magisk(dev) -> str:
    """返回 **resetprop 的可执行命令前缀**（空=没有可用实现）。

    两种形态，调用方都按「命令前缀 + 参数」拼接，所以可以统一：

    * 装了完整 Magisk → 返回 ``resetprop`` 的路径，可直接当命令用；
    * **只有 Magisk 二进制的镜像**（2026-11-04 实测的 MuMu 场景）——
      把 APK 里的 ``lib/x86_64/libmagisk.so`` 提出来改名 ``magisk``，
      用法是 ``magisk resetprop <k> <v>``。这时返回
      ``"/data/local/tmp/magisk_bin/magisk resetprop"``（**带子命令**）。

    为什么需要第二种：MuMu 只给了 ``adb root``（adbd 跑 root），
    没有 Magisk 守护进程，所以 ``resetprop`` 命令不存在；
    但把 APK 里的 magisk 二进制提出来就能直接用它的 resetprop 子命令
    ——实测成功清掉 ``ro.nemu``（值 ``1`` → 空），系统无副作用。
    """
    # 探测方式必须是 **`ls <path>` 直传**，不能用 `sh -c "test -e '...'"`：
    # 实测经 adb shell 之后引号会丢失，`test -e '路径'` 变成带引号的字面量
    # → 明明存在也返回 `TM_NO`（2026-11-04 踩到，浪费了一轮排查）。
    # `ls` 直传在同样条件下正常返回路径。
    # **顺序很重要**：`/data/adb/magisk/magisk` 必须排在
    # `/data/local/tmp/magisk_bin/magisk` 前面。
    #
    # 实测（2026-11-04）：两个文件的 md5 **完全相同**，但行为不同——
    # `magisk` 二进制会按**自身所在目录**去找配套文件（magisk32/64、
    # sepolicy 等）。放在 `/data/local/tmp/magisk_bin/` 时找不到，于是
    # `resetprop` 退化成普通 `setprop`：
    #
    #   /data/adb/magisk/magisk  resetprop --delete ro.hardware  → 生效（读回空）
    #   /data/local/tmp/.../magisk resetprop --delete ro.hardware → 无效（读回原值）
    #
    # 这条差异极隐蔽：md5 一样、命令一样，只有"从哪跑"不同。
    cands = (
        # **KernelSU 自带的 resetprop 排第一**（2026-11-05 实测）。
        #
        # KernelSU 3.x 会往 `/data/adb/ksu/bin/` 放一套自己的工具：
        #   busybox / ksud / **resetprop**
        # 这个 resetprop 不依赖 magiskd，实测 `resetprop k v` 能写 `ro.*`、
        # `--delete` 能连键删掉（读回空），行为和 Magisk 的一致。
        #
        # 为什么必须排第一：本机（MuMu + KernelSU）真正在管 root 的是
        # KernelSU，Magisk 那一套只是"从 APK 里提出来的二进制"。而那个
        # 二进制**每次实例重启都可能消失**（`/data/adb` 被重建），一旦消失
        # 整条热写路径就退回 `setprop`、18 条 `ro.*` 静默不生效。
        # 用根管理器自己的工具，稳定性高一档。
        ("/data/adb/ksu/bin/resetprop", False),
        ("/data/adb/magisk/resetprop", False),
        ("/data/adb/magisk/magisk", True),
        ("/data/local/tmp/magisk_bin/resetprop", False),
        ("/data/local/tmp/magisk_bin/magisk", True),
        ("/sbin/resetprop", False),
    )
    for path, is_magisk_bin in cands:
        out = _text(_call(dev, "shell", "ls", path))
        if path not in (out or ""):
            continue
        cmd = (path + " resetprop") if is_magisk_bin else path
        # **必须验证它真的能 delete**，不能只看文件在不在（2026-11-04 血泪）。
        #
        # 踩过的坑：`/data/adb/magisk/magisk` 存在但**缺配套文件**
        # （magisk32/64、busybox —— 实例重启后 /data/adb 被清），
        # 它执行 `resetprop --delete` 会**静默失败**（错误被 `>/dev/null`
        # 吞掉），而 `_magisk()` 只看 `ls` 有文件就返回了它。
        # 结果 `apply_props` 全部"写成功但不生效"，`verified` 只有 4 条。
        #
        # 探针：对一个无害的临时键做 delete-then-set，读回对得上才算可用。
        # 探针必须用 ro.* 键：persist.* 不经过 property_service 的
        # 只读校验，用它能写出 "1" 但 ro.* 照样失败（实测：
        # /data/adb/magisk/magisk 探 persist.* 通过，ro.* 却静默失败）。
        # ro.boot.revision 是几乎不被读的键，拿它当探针最安全。
        _probe_k = "ro.boot.revision"
        _old = _text(_call(dev, "shell", "getprop", _probe_k)).strip()
        _call(dev, "shell", cmd, "--delete", _probe_k)
        _call(dev, "shell", cmd, _probe_k, "tmprobe")
        got = _text(_call(dev, "shell", "getprop", _probe_k)).strip()
        if got == "tmprobe":
            _call(dev, "shell", cmd, "--delete", _probe_k)
            if _old:
                _call(dev, "shell", cmd, _probe_k, _old)
            return cmd
    return ""


def apply(dev, ident: Identity, *, use_root=None, uid: bool = True,
          allow_build_props: bool = False) -> dict:
    """把身份写进设备。返回逐键结果，**带读回校验**，不抛异常。

    为什么不再自己拼 setprop 脚本：``setprop ro.*`` 在只读系统盘上
    **返回 0 但值不变**（2026-11-03 实测），只看命令返回码会得出"9 条生效"
    的假结论——而设备上一条都没变。写 props 这件事因此**只保留一份实现**：
    ``abi_canary.apply_props``（写前快照 + 写后 getprop 读回比对）。

    ``allow_build_props=True`` 时连机型/构建字段一起写（50003 的硬判据
    就在这批字段里）。**调用方必须在写完后重启 zygote**，否则已启动的
    App 读到的仍是 zygote 缓存的旧 Build——见 ``ensure()``。

    返回键：``applied``（命令报成功）/ ``verified``（读回真的是新值，
    **只有它可信**）/ ``failed`` / ``mismatch`` / ``unchanged`` /
    ``android_id``。
    """
    from . import abi_canary

    props = ident.props()

    # **差异预检：本来就已经对了就什么都不做**（2026-11-05，重要）。
    #
    # 为什么必须加这一层：写 props 需要 root，而本机拿 root 的唯一方式是
    # `adb root` —— 实测它会重启 adbd，且**经常重启后握手不回来**
    # （`adb devices` 变 offline、shell 挂住，但设备本身一直健康）。
    #
    # 而开机模块（`scripts/identity_boot_module.py`）已经把 props 在
    # zygote 之前写对了，所以稳态下这里根本**没有东西要写**。
    # 之前的实现不管有没有差异都先 `adb_root()`，于是"本来没事"的一轮
    # 把 adb 弄坏了 —— 每轮采集都踩一次，纯粹自伤。
    #
    # 判据用一次 getprop 全表（shell 权限即可）；有差异才去要 root。
    cur = props_of(dev)
    diff = {}
    if cur:
        for k, v in props.items():
            if str(cur.get(k) or "").strip() != str(v).strip():
                diff[k] = v
    _aid = ident.android_id if uid else ""
    _aid_now = ""
    if _aid:
        _aid_now = _text(_call(dev, "shell", "settings", "get", "secure",
                               "android_id")).strip()
    _aid_ok = (not _aid) or (_aid_now == _aid)

    # 真的有差异才拿 root，而且**只有 `ro.*` 类差异才值得拿**。
    #
    # **2026-11-05 最终结论：运行时不调 `adb root`。**
    #
    # `adb root` 会重启 adbd，而本机 adbd 重启后**经常握手卡死**
    # （`adb devices` 变 offline、`adb shell` 挂住；设备本身一直健康）。
    # adb 一死，`uiautomator dump` 也死 —— App 渠道全靠 UI 树定位控件，
    # 于是整轮采集归零。实测这就是"App 渠道数据时有时无"的根因。
    #
    # 而 `ro.*` 现在**由开机模块在 zygote 之前写好**
    # （`scripts/identity_boot_module.py`），稳态下根本没有 ro.* 差异；
    # 即使有（MuMu 某次改了），也不该用"废掉 adb"来换——那是拿爬取率
    # 换一条提示性字段。
    #
    # 所以这里只做**如实报告**：有 ro.* 差异就记下来，交给开机模块在下一次
    # 启动时纠正；运行期只写非 ro 键（`setprop` 普通 shell 就能做）。
    _ro_diff = [k for k in diff if k.startswith("ro.")]
    _use_root = (use_root is None) or bool(use_root)
    _deferred = []
    _props_write = props
    if _ro_diff:
        _deferred = sorted(_ro_diff)
        _props_write = {k: v for k, v in props.items() if k not in _ro_diff}

    if cur and not diff:
        # props 已经全对（开机模块的功劳）：**一条都不写**，也不去要 root。
        rec = {"applied": [], "verified": [], "failed": [], "mismatch": {},
               "unchanged": sorted(props), "resetprop": "",
               "note": "props 已与身份一致（开机期已写入），本轮跳过",
               "hot_write_skipped": [],
               "already_correct": True}
    else:
        rec = abi_canary.apply_props(dev, _props_write, use_root=_use_root,
                                     allow_build_props=bool(allow_build_props))
        if _deferred:
            # ro.* 差异不在运行期写（见上面注释）：如实记进 note，
            # 由开机模块在下一次启动时纠正。
            rec["note"] = ((rec.get("note") or "") +
                           "；%d 条 ro.* 差异留给开机模块（运行期不 adb root，"
                           "避免打断 adbd）" % len(_deferred)).strip("；")
            rec["deferred_ro"] = _deferred
    rep = {"applied": rec.get("applied") or [],
           "verified": rec.get("verified") or [],
           "failed": rec.get("failed") or [],
           "mismatch": rec.get("mismatch") or {},
           "unchanged": rec.get("unchanged") or [],
           # **必须把"被跳过的热改键"透传出来**：不然调用方只看到
           # `verified` 为空、`mismatch` 也为空，会误以为"没东西要写"，
           # 而实际是"这批键**禁止运行中改**"（信息不能在这一层丢掉）。
           "hot_write_skipped": rec.get("hot_write_skipped") or [],
           # ro.* 差异（运行期不写，留给开机模块）—— 必须透传，
           # 否则调用方看到的只有"没写也没错"，又一次"静默糊过去"
           "deferred_ro": rec.get("deferred_ro") or [],
           "note": rec.get("note") or "",
           "resetprop": rec.get("resetprop") or "",
           "android_id": "", "root": _root(dev)}

    if uid:
        aid = ident.android_id
        # 已经一致就别再写：`settings put` 每次都会触发一次设置变更广播，
        # 在稳态（开机模块已写好）里纯属噪音。
        if aid:
            if _aid_ok:
                rep["android_id"] = _aid_now
                rep["android_id_ok"] = True
            else:
                _call(dev, "shell", "settings", "put", "secure",
                      "android_id", aid)
                rep["android_id"] = _text(_call(
                    dev, "shell", "settings", "get", "secure",
                    "android_id")).strip()
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
    # 走统一的 write_remote：`sh -c "echo X > path"` 在 Windows 上**静默失败**
    write_remote(dev, _mark_path(ident.vm), line)
    return line


def restart_framework(dev, mode: str = "zygote", wait_s: int = 90) -> bool:
    """让新的 Build 字段对 App 生效。

    ``android.os.Build`` 的静态字段在 zygote 里定型，只改 props 不重启，
    新身份对已在跑的 App 等于没改。

    **`zygote` 模式用 `setprop ctl.restart zygote`，不用 `stop; start`**
    （2026-11-05 修正）。旧实现是 `stop; start`，而那是 init 的"停掉所有
    service 再按 class 拉起"——**adbd 也在里面**，于是：

        adb devices → 127.0.0.1:16384 offline（且不会自己回来）

    设备本身一直是好的（`sys.boot_completed=1`、props 全对），但从 adb
    这一侧看就像"设备挂了"，历史上被记成"热改 props 会把设备搞挂"。
    实测对照：`setprop ctl.restart zygote` 只重启 zygote/framework，
    adb 连接保持不变。

    ``full`` 交给调用方（MuMu control restart）。
    """
    mode = str(mode or "none").lower()
    if mode in ("none", "no", "0", "false", ""):
        return False
    if mode == "zygote":
        as_root(dev, "setprop ctl.restart zygote")
    # 下限 2s：单测会把 wait_s 调到 1，卡 10s 的硬地板会让一次实验白等 20s+
    end = time.time() + max(2, int(wait_s or 90))
    _tries = 0
    while time.time() < end:
        time.sleep(3)
        _tries += 1
        if _text(_call(dev, "shell", "getprop", "sys.boot_completed")
                 ).strip() == "1":
            return True
        # zygote 重启后 MuMu 的 NAT 序列常会掉成 offline，而同机还有一条
        # 在线的本地序列 —— 轮询里顺手切一次，否则这里会白等满 wait_s
        # 并回报"重启失败"（而设备其实早就起来了）。
        if _tries == 2:
            _fn = getattr(dev, "recover_transport", None)
            if _fn is not None:
                try:
                    _fn()
                except Exception:
                    pass
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


# **改不动、也不该改**的泄漏项（2026-11-04）。
#
# 为什么单列：`ro.product.cpu.abi` / `abilist` 反映的是**这台机器真实的
# CPU 架构**。MuMu 跑在 x86_64 上，这就是事实，不是伪装没做好。
# 把它们"改成 arm64-v8a"会让 linker 去找 arm 的库目录，
# **系统直接起不来**——我今天已经被同类建议坑过一次：
# 按"改 SDK 版本能让指纹更自洽"的思路把 `ro.build.version.sdk` 从 35 降到 33，
# 结果 linker 报 `libdl_android.so is not accessible`，携程**启动失败**。
#
# 真正的缓解手段是**包级 ABI**（`/system/etc/mumu-configs/
# abi-select-android12.config`，让每个包的 `primaryCpuAbi=arm64-v8a`），
# 那部分已经做好并实测过。
#
# 所以这里要显式告诉操作员：**自检分数有个不可清除的上限**，
# 不然"88 分"会变成一个永远解释不了、也永远消不掉的噪音，
# 久而久之大家就不看自检了。
_UNFIXABLE_KEYS = {
    "ro.product.cpu.abi": (
        "本机真实架构就是 x86_64；改成 arm64 会让 linker 找不到库、"
        "系统起不来。已用包级 ABI（abi-select）把每个包的 "
        "primaryCpuAbi 伪装成 arm64-v8a，这才是有效的那一层"),
    "ro.product.cpu.abilist": (
        "同上：这是真实架构列表，不可全局改；包级已伪装"),
    "ro.product.cpu.abi2": ("同上：真实架构，不可全局改"),
    "ro.product.cpu.abilist32": ("同上：真实架构，不可全局改"),
    "ro.product.cpu.abilist64": ("同上：真实架构，不可全局改"),
}


def sh_script(dev, script: str, timeout=None):
    """设备执行脚本的统一入口：**整条脚本作为单个 argv**。

    为什么不写成三段 argv（`shell` + `sh` + `-c` + 脚本）：
    adb 会用空格拼 argv 交给设备 shell **重新解析**，内层只剩
    `sh -c <第一个词>`，`$()`/`|`/`>`/`&&` 全部错位 → 静默失败。
    实测三种对照（单 argv 正常、三段 argv 恒空）：
        ANR 探针、abi-select 表 printf 追加、test -e 存在性判断。
    """
    if getattr(dev, "run_script", None) is not None:
        return dev.run_script(script, timeout=timeout)
    # 测试替身/旧接口：没有 run_script 时，直接把脚本作为 shell 的单个参数
    return _call(dev, "shell", str(script or ""), timeout=timeout)


def _fmt_audit_score(a: dict) -> str:
    """把自检分数渲染成一句人话，**区分"0 分"与"没读到"**。

    `score=None` 是"未知（设备没读到）"，绝不能印成"0 分"——
    0 分意味着"检测到 13 条以上证据"，会让人去修一个不存在的问题。
    说明文字（"已到上限…"）也在这里一并给出，避免调用处各拼一次、
    拼出"自检 88 分（已到上限（…））"这种嵌套括号。
    """
    sc = (a or {}).get("score")
    if not isinstance(sc, int):
        return "未知（设备没读到）"
    note = (a or {}).get("score_note") or ""
    return "%d 分%s" % (sc, "" if not note else "，" + note)


def audit(dev) -> dict:
    """自检：返回 ``{score, leaks, props, notes}``。

    ``score`` 100 = 没有命中（不代表绝对安全，只代表「已知特征全清」）。
    这是给操作员看的**事实清单**：哪条还在、为什么算命中、能不能改。
    """
    props = props_of(dev)
    if not props:
        # **读不到设备时不许算分**（与 stealth.detect 同源，2026-11-04）。
        # 下面有一批规则的 needle 是空串（"运营商信息为空"这类），
        # props 为空时它们**全部命中**，于是自检从 88 直接砸成十几分——
        # 看起来像"身份伪装崩了"，实际只是这条 adb 没读到。
        return {"score": None, "score_ceiling": None,
                "score_note": "",
                "leaks": [], "unfixable": 0, "fixable_left": 0,
                "props": {}, "abi_note": ABI_NOTE, "identity_id": "",
                "error": "device offline"}
    leaks = []
    for key, needle, why in _EMU_PROPS:
        val = str(props.get(key, ""))
        if needle == "":
            if val == "":
                leaks.append({"key": key, "value": "", "why": why,
                              "fix": "identity"})
            continue
        if needle.lower() in val.lower():
            _unfix = _UNFIXABLE_KEYS.get(key)
            if _unfix:
                # 仍然计入 leaks（**不把风险抹成 0 分**），
                # 但 fix 不再指向一个会搞挂系统的动作
                leaks.append({"key": key, "value": val, "why": why,
                              "fix": "包级 ABI（abi-select），全局不可改",
                              "unfixable": True,
                              "note": _unfix})
            else:
                leaks.append({"key": key, "value": val, "why": why,
                              "fix": "identity"})
    # root 残留（文件系统层面的，props 改不掉）
    #
    # **必须用 `test -e` 逐路径判存在**（2026-11-04 实机踩到，与 stealth 同源 bug）：
    # `ls /a /b /c` 在某个参数是目录/符号链接时会把它的**内容**列出来，于是
    # 整个根目录（acct/bin/cache/…）被当成 17 条 root 残留，`-6×17` 直接把自检
    # 分扣到 0。操作员看到「自检 0 分」会以为隐藏失败，实际是误报。
    # 用 stealth 的同名探测保持单一实现，避免两处再次漂移。
    # **与 `stealth.detect()` 同一套判据**：存在 ≠ App 看得见。
    # 自检跑在 `adb root`（uid=0）下，而 `/data/adb` 是 `drwx------ 0700`
    # —— App 连 traverse 都做不到。把它算成风险项只会制造假警报
    # （2026-11-04 差点因此把 resetprop 的工位删掉，白损能力）。
    _see = {}
    for p in ("/system/bin/su", "/system/xbin/su", "/sbin/su",
              "/data/adb/magisk"):
        if _exact_path_exists(dev, p) and app_can_see(dev, p, _see):
            leaks.append({"key": "fs", "value": p,
                          "why": "root 痕迹（props 改不掉，靠 DenyList/Shamiko）",
                          "fix": "magisk-denylist"})
    score = max(0, 100 - 6 * len(leaks))
    _unfixed = [x for x in leaks if x.get("unfixable")]
    # **ceiling = 天花板**：把所有*可清*的泄漏都清掉之后还能拿到的分数，
    # 即 100 - 6*(不可清条数)。所以 score <= ceiling 恒成立：
    # score 低于 ceiling 说明"还有能修的没修"，等于 ceiling 说明"已到顶"。
    ceiling = max(0, 100 - 6 * len(_unfixed))
    fixable_left = len(leaks) - len(_unfixed)
    if _unfixed:
        # 把"上限"算出来并说明原因：这样操作员看到 88 知道**天花板就在这**，
        # 而不是以为自己哪里没配好、反复去折腾那些改不得的键。
        #
        # 措辞分两种，避免把日志写成论文：
        #   * score 已经等于 ceiling → 只说"已到上限"（再展开就是噪音）；
        #   * score 低于 ceiling → 必须点出"还有 N 条可修未修"，
        #     否则那个差额会被误读成"又坏了 6 分"。
        _keys = "、".join(str(x.get("key")) for x in _unfixed[:3])
        if fixable_left <= 0:
            score_note = "已到上限（%d 条为真实架构不可清：%s）" % (
                len(_unfixed), _keys)
        else:
            score_note = ("上限 %d 分：%d 条真实架构不可清（%s），"
                          "另有 %d 条可修未修"
                          % (ceiling, len(_unfixed), _keys, fixable_left))
    else:
        score_note = ""
    return {
        "score": score,
        "score_ceiling": ceiling,
        "score_note": score_note,
        "unfixable": len(_unfixed),
        "fixable_left": fixable_left,
        "leaks": leaks,
        "props": {k: props.get(k, "") for k in PROP_KEYS},
        "abi_note": ABI_NOTE,
        "identity_id": "",
    }


# ---------------------------------------------------------------------------
# 对外唯一入口
# ---------------------------------------------------------------------------
def _is_emulator(props: dict, *, vendor_hint: bool = False) -> bool:
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
    if str(p.get("ro.kernel.qemu", "")).strip() == "1":
        return True
    # **兜底：看键名，不看值**（2026-11-04 踩到的自噬）。
    #
    # 上一版只看"值里有没有 mumu/nemu 字样"。而 `stealth.hide()` 会把
    # `nemud.*`、`ro.nemu`、`ro.build.version.nemux` 的值**清空**——于是
    # 清完之后这台设备"看起来不像模拟器了"，`_is_emulator()` 返回 False，
    # `ensure()` 直接 `skipped: not an emulator`，**身份层整体不工作了**。
    # 实测：硬化报 identity=True，但设备上 `ro.product.model` 还是 SM-A5260。
    #
    # 所以补一组**改不掉**的键名证据：MuMu 的守护进程服务名
    # （`init.svc.nemuinit` 等）和 `ro.boottime.nemu*` 是 init 维护的，
    # 删不掉也清不空，拿它们判"是不是模拟器"最稳。
    _KEYS = ("init.svc.nemuinit", "init.svc.nemud", "init.svc.nemuhotd",
             "init.svc.nemuinput", "init.svc.nemufreepfn",
             "init.svc.nemu_sys_opt", "ro.boottime.nemuinit",
             "ro.hardware.virtual", "ro.emu.", "ro.vbox")
    for k in p:
        kl = str(k).lower()
        if kl in _KEYS or kl.startswith("ro.boottime.nemu"):
            return True
    # **最后兜底：MuMu 官方 API 能读到实例设置 = 这就是 MuMu 实例**
    # （2026-11-04 补）。前面几条都失效的情况真实发生过：
    # `stealth.hide()` 用 `resetprop --delete` 把 `nemud.*`/`ro.nemu`
    # **连键带值全删了**，`getprop | grep -c nemu` 返回 **0** ——
    # 于是这台设备"props 上完全看不出是模拟器"，`_is_emulator()` 判 False，
    # 身份层被整体跳过（硬化报 identity=True 但设备上 model 仍是 SM-A5260）。
    #
    # **外部证据兜底**（`vendor_hint`）：由调用方（`ensure()`）传进来。
    #
    # 为什么不在这里自己问 MuMu：`_is_emulator` 必须是**纯函数**，
    # 否则在装了 MuMu 的机器上跑测试时它会恒为 True（实测就撞到了：
    # `_is_emulator({"ro.product.model": "Redmi K50"})` 返回 True）。
    # 纯函数才能被测试可靠地钉住"只认证据"。
    #
    # 什么时候需要这个口子：`stealth.hide()` 用 `resetprop --delete` 会把
    # `nemud.*` / `ro.nemu` **连键带值删掉**，`getprop | grep -c nemu` 变成 0
    # —— props 上完全看不出是模拟器，身份层会误判"这是真机"而整体跳过。
    if vendor_hint and p:
        return True
    return False


def _ancestor_paths(path: str) -> list:
    """`/a/b/c` → ['/a', '/a/b']（父链，不含自身，不含 '/'）。"""
    parts = [x for x in str(path).split("/") if x]
    return ["/" + "/".join(parts[:i]) for i in range(1, len(parts))]


def _ls_modes(dev, paths) -> dict:
    """一次 `ls -ld p1 p2 ...` 拿到多个目录的权限位。

    **不能包 `sh -c`**：adb 会把命令行按空格拆开送进设备 shell，
    `sh -c ls -ld /a /b` 里 `ls` 实际收到的是 `-ld /a /b` 当作位置参数
    —— 于是 `ls` 不带任何参数、把当前目录整个列一遍。
    2026-11-04 那次"17 条幽灵 root 残留"的真实成因就是这个（当时误记为
    "目录被展开"），所以这里把路径作为独立 argv 传，绝不拼字符串。
    """
    paths = [str(x) for x in paths if x]
    if not paths:
        return {}
    out = _text(_call(dev, "shell", "ls", "-ld", *paths))
    modes = {}
    for line in (out or "").splitlines():
        line = line.strip()
        if not line:
            continue
        cols = line.split()
        if len(cols) < 2 or cols[0][0] not in "dlc-":
            continue
        mode = cols[0]
        # ls 会把多个参数分别成行；用行尾字段反推路径
        tail = cols[-1]
        if tail.startswith("/") or "/" in tail:
            modes[tail.split(" => ")[0].strip()] = mode
    return modes


def app_can_see(dev, path: str, cache=None) -> bool:
    """**非特权 App 能不能 stat 到这个路径**（探针权限 ≠ App 权限）。

    为什么必须有这个判断（2026-11-04 差点因此做错决策）：
    自检是在 `adb root`（uid=0）下跑的，能看到 App 永远看不到的东西。
    实测 /data/adb 是 `drwx------ root:root`（0700），App 连 traverse 都做不到，
    于是 `/data/adb/magisk` 对 App **完全不存在**；
    而 `/data/local/tmp` 是 `drwxrwx--x`（0771，others 有 x），
    它下面的 `magisk_bin/` 反而是**真能被发现**的那一份。

    差点干的事：为了消掉一条 App 看不见的"泄漏"，把 resetprop 的工位删掉，
    换来的是能力损失 + 一次没有收益的改动。
    **判暴露面要按攻击者的权限判，不是按 root 的权限判。**

    规则：父链每一级都对 others 开放 `x`（可穿越）才算 App 看得见。
    拿不到权限位时**保守返回 True**（宁可多报，不要把真泄漏判没）。
    """
    cache = cache if isinstance(cache, dict) else {}
    anc = _ancestor_paths(str(path))
    # **只查父链，不查路径自身**：可见性 = "每一级都能 traverse"，
    # 路径本身的存在性由 `_exact_path_exists` 负责。把目标也塞进这次查询
    # 会让每条路径多一次 adb 往返（detect 每轮都跑，被自己的测试抓到过）。
    need = [a for a in anc if a not in cache]
    if need:
        got = _ls_modes(dev, need)
        for k in need:
            cache[k] = got.get(k)
    for a in anc:
        mode = cache.get(a)
        if not mode or len(mode) < 10:
            return True             # 判不准就当看得见
        if "x" not in mode[7:10]:   # others 无 x → 无法 traverse
            return False
    return True


def _exact_path_exists(dev, path: str) -> bool:
    """路径**本身**是否存在。用 `ls -d <单条路径>`，不用 `sh -c`。

    这个函数在 2026-11-04 一天里错过两次，两个方向都错过：

    **① 假阳性（最早）**：`ls /a /b /c` —— 参数是目录/符号链接时 `ls`
    会把它的**内容**列出来，于是"查有没有 su"变成"把根目录列了一遍"，
    `acct/bin/cache/…` 全被当成 root 残留，`-6×17` 直接把自检打到 0 分。

    **② 假阴性（我为了修 ① 换出来的，更危险）**：
    `sh -c "test -e X && echo TM_YES || echo TM_NO"`。
    adb 会把命令行**按空格拆开**送进设备 shell，于是设备执行的是
    `sh -c test`（内层 `test` 没拿到参数 → **恒假**）+ 外层 `|| echo TM_NO`
    → **任何路径都返回 TM_NO**。
    用 `/system/bin/sh`（必然存在）自测：返回 False。
    也就是说"root 痕迹为空、自检 100 分"**从来没被验证过**，
    探针是个恒假的死件。假阴性比假阳性坏：假阳性吵人，假阴性让人放心。

    所以最终形态必须**完全避开 shell 元字符**（`-c`、`&&`、`||`、`|`、`>`、引号）：
    `ls -d` 加**一条**路径 —— 拆开送过去语义也不变。
    存在 → stdout 就是这个路径本身；不存在 → stdout 为空（报错进 stderr）。
    `-d` 保证不列目录内容，同时消掉 ①。
    """
    out = _text(_call(dev, "shell", "ls", "-d", path))
    # 比对用 strip：设备回包带 `\r\n`
    return out.strip() == str(path).strip()


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
                # 把设备**真实** SDK 带进 vendor 值里——它不在 MuMu 的设置键里，
                # 但一致性纠正需要它：官方键只给 brand/model，系统版本是
                # `device-prop-configs` 另注入的，两者可能自相矛盾
                # （实测 Samsung SM-A5260 + sdk 35 = A52 跑 Android 15，
                #  真机不存在）。有了真实 SDK 才能选一台原生匹配的池机型。
                try:
                    _real_sdk = _text(_call(
                        dev, "shell", "getprop",
                        "ro.build.version.sdk")).strip()
                    if _real_sdk:
                        vend = dict(vend)
                        vend.setdefault("ro_sdk", _real_sdk)
                    # 设备真实 props 一并带上：档案要照实记录（见上面
                    # `build_from_vendor` 的 `values_from=device`）
                    if _props:
                        vend = dict(vend)
                        vend["ro_values"] = dict(_props)
                except Exception:
                    pass
                ident = build_from_vendor(vend, seed, vm=vm)
            else:
                ident = build(seed, vm=vm)
        rep["identity"] = ident.ident_id
        rep["created"] = created

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

        # **身份字段的写入全程改走 MuMu root shell，不碰 adb**（2026-11-05）。
        #
        # 实测：`ensure()` 一整轮下来会把 adbd 打到握手卡死
        # （跑之前 `state=device`、跑之后 `state=offline`，而设备本身一直健康）。
        # 而 adb 一旦卡死，`uiautomator dump` 也就没了——App 渠道全靠 UI 树
        # 定位控件，于是**整轮采集归零**。这是"爬取率"最大的单点。
        #
        # 反过来看：`MuMuManager sh -v N -c` 直接就是 root
        # （`u:r:nemuinit:s0`）、不经过 adbd、永远可用。写这些字段需要的
        # 恰好只是「root 下 setprop/resetprop/settings」——完全不需要 adb。
        # 所以这里把设备临时切到 MuMu 通道，写完再切回来：
        #
        #   * adb 全程不被触碰 → 保持 `device` 态 → dump 继续可用；
        #   * 而且因为 MuMu 通道本来就是 root，连 `adb root` 都不需要了
        #     （`adb root` 本身也会重启 adbd，是另一个搞坏它的源头）。
        _prev_mumu = getattr(dev, "_prefer_mumu", False)
        _switched = False
        try:
            if getattr(dev, "mumu_available", None) and dev.mumu_available():
                dev._prefer_mumu = True
                _switched = True
                if logger:
                    logger.info("[android] 身份字段改走 MuMu root shell（不触碰 adb）")
        except Exception:
            _switched = False

        # 既有身份也要跟官方对齐：操作员可能改了 MuMu 的 phone_* 键，
        # 档案不跟着改就会"档案说 A、设备是 B"。只对齐机型/屏幕，不动
        # android_id / 序列号（那两个变了等于换设备，会触发二次校验）。
        #
        # **必须放在 fast path（"本 boot 已应用"）之后**（2026-11-04）：
        # 那段被测试钉着"只花两条 adb"（boot_id + 标记），是每轮都走的热路径。
        # 我一开始把同步放在它前面，结果每次跳过都要多跑一次完整 `getprop`
        # （热路径回归，被 test_ensure_applies_then_skips_this_boot 抓到）。
        # 放后面之后：本 boot 真正要应用时同步一次，且**复用下面已读的 `plain`**，
        # 两条路径都不多花一条 adb。标记是按 boot 失效的，所以每次开机
        # 都会走到这里一次，档案不会长期停留在旧值。
        if not created and ident.ident_id and \
                _flag(sec.get("prefer_vendor"), True):
            try:
                from . import vendor as vendor_mod
                vend = vendor_mod.read(vm_index=vm) or {}
                if vend:
                    # **同步路径也必须带上 `ro_sdk` 与设备真实 props**
                    # （2026-11-04 修）。之前这里只喂官方键，于是：
                    #   * 没有 `ro_sdk` → "机型与系统版本矛盾"的一致性纠正
                    #     根本不触发（A52+Android15 那类）；
                    #   * 没有 `ro_values` → 档案记的是**池里的理想值**，
                    #     而 MuMu 实际把品牌名抄进了 `ro.hardware`，
                    #     于是"档案说 mt6897、设备是 vivo"。
                    try:
                        # **复用上面已经读好的 `plain`**：再读一次就是多花
                        # 一条完整 getprop（几百个键）的 adb 往返。
                        _sdk = str((plain or {}).get("ro.build.version.sdk")
                                   or "").strip()
                        if _sdk:
                            vend = dict(vend)
                            vend.setdefault("ro_sdk", _sdk)
                        if plain:
                            vend = dict(vend)
                            vend["ro_values"] = dict(plain)
                    except Exception:
                        pass
                    synced = build_from_vendor(vend, 0, vm=vm)
                    cur = ident.profile or {}
                    newp = synced.profile or {}
                    # **比较范围要覆盖全部一致性字段**（2026-11-04 修的第二个洞）。
                    # 原来只比 brand/model/manufacturer/display/density 五个，
                    # 而实测档案脏在 `device=rubens`、`hardware=mt6895`、
                    # `release=12`、`sdk=31`、`build_id=SP1A...`
                    # —— 全都不在比较范围里，于是 diff 永远为空、
                    # 档案**永远不会被纠正**，自检一直卡在 88 分。
                    diff = {k: (cur.get(k), newp.get(k))
                            for k in ("brand", "model", "manufacturer",
                                      "display", "density",
                                      "device", "product", "board",
                                      "hardware", "platform",
                                      "release", "sdk", "build_id",
                                      "build_display", "fingerprint")
                            if newp.get(k) and cur.get(k) != newp.get(k)}
                    if diff:
                        ident.data["profile"] = newp
                        store.put(ident)
                        rep["profile_synced"] = {
                            k: {"from": v[0], "to": v[1]}
                            for k, v in diff.items()}
                        if logger:
                            _desc = "、".join(
                                "%s %s→%s" % (k, v["from"], v["to"])
                                for k, v in
                                list(rep["profile_synced"].items())[:4])
                            logger.info("[android] 档案与设备对齐：%s",
                                        _desc)
            except Exception:
                pass


        # 只在**真的是模拟器**上动手：真机跑这套等于自找麻烦，而测试里的
        # 假设备 props 读不到 → 自然跳过，不会污染既有单测。
        #
        # `vendor_hint`：props 被 `stealth.hide()` 清干净之后（`nemud.*` 连键
        # 带值删掉），props 上已经看不出是模拟器了——这时用 MuMu 官方 API
        # 作为外部证据兜底，否则身份层会误判"这是真机"而整体跳过
        # （实测：硬化报 identity=True，设备上 model 仍是 SM-A5260）。
        # **必须尊重 `prefer_vendor` 开关**：关掉它时不许去问 MuMu
        # （否则 mock 了 `_cfg` 的测试仍会被真实 MuMu 污染——实测撞到过）。
        _vhint = False
        if _flag(sec.get("prefer_vendor", True), True):
            try:
                from . import vendor as _vendor
                _vhint = bool(_vendor.read(vm_index=vm))
            except Exception:
                _vhint = False
        if not _is_emulator(plain, vendor_hint=_vhint) \
                and not _flag(sec.get("force"), False):
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

        # 机型/构建字段是否允许热写（默认**允许**，2026-11-05 起）。
        #
        # 这批字段（ro.build.flavor/description/fingerprint/hardware/board/
        # soc.model/first_api_level…）是携程 50003「当前登录环境存在风险」
        # 的最硬判据：机型可以伪装成 vivo X200 Pro，但 `missi_` 内部代号、
        # MuMu 构建号 `1171`、`kona`（骁龙 865）这些一读就露。
        #
        # 历史上默认关，是因为热写后 adbd 掉线、被记成"设备搞挂了"。2026-11-05
        # 复核：**掉的是 adbd，不是系统** —— 用 MuMu 自己的 shell 通道
        # （`MuMuManager sh -v 0 -c`，不走 adb）在"掉线"后仍能读到
        # `sys.boot_completed=1` 与新的 Build 值。所以这条路径可用，
        # 代价只是写完要重连 adb（下面已经自动做）。
        _allow_build = _flag(sec.get("hot_build_props"), True)
        try:
            ap = apply(dev, ident, use_root=sec.get("use_root"),
                       allow_build_props=_allow_build)
        finally:
            # 身份写完立刻把通道切回 adb（后续 audit/restart 仍按原路径）
            if _switched:
                dev._prefer_mumu = _prev_mumu
        rep["apply"] = ap
        ident.data["applied_at"] = time.time()
        ident.data["applied_boot"] = boot
        ident.data["rotations"] = int(ident.data.get("rotations") or 0)
        store.put(ident)
        write_marker(dev, ident)

        # 改过 ro.* 或 ro.debuggable 这类字段才需要重启框架
        #
        # **只有 `ro.*` 真的变了才重启**（2026-11-05 关键修正）。
        #
        # 原先只要 `applied` 非空就重启 zygote，于是稳态下（本轮只有
        # `gsm.sim.operator.*` / `net.hostname` 这几条非 ro 键不一致）
        # 也会去 `ctl.restart zygote`。而实测：**zygote 重启会把 adbd 打到
        # 握手卡死**（`adb devices` 变 offline、`adb shell` 挂住；设备本身
        # 一直健康）。adb 一死，`uiautomator dump` 也死，App 渠道整轮归零。
        #
        # 判据很自然：`android.os.Build` 只由 `ro.*` 决定，非 ro 键
        # （gsm/net.hostname/settings）改了也不影响 Build，重启纯属白伤。
        _applied = [str(k) for k in (ap.get("applied") or [])]
        _need_zygote = any(k.startswith("ro.") for k in _applied)
        need_restart = bool(_applied) and _need_zygote \
            and not sec.get("no_restart")
        if need_restart and ap.get("resetprop"):
            mode = str(sec.get("reboot") or "zygote")
            rep["changed"] = restart_framework(dev, mode)
            rep["reboot"] = mode
            # **重启 framework 后必须把 adbd 的 root 重新拿回来**。
            # 写 `ro.build.*` / `ro.debuggable` 会让 adbd 重启并按默认
            # 非 root 启动，`adb devices` 变成 offline —— 那之后所有采集
            # 都会失败，而现象看起来像"设备挂了"。实测（2026-11-05）
            # `adb root` 一次就能恢复，且系统本身一直是好的。
            try:
                # 先看传输是不是掉了：zygote 重启后 MuMu 的 16384 那条
                # 会 offline，而同一台实例的 emulator-5554 仍在 —— 不切过去
                # 的话后面每条 adb 都失败，表现为所有字段读回为空。
                _rec = None
                _fn = getattr(dev, "recover_transport", None)
                if _fn is not None:
                    _rec = _fn()
                    rep["transport"] = _rec
                _root(dev)
                # adbd 重启后连接会短暂不可用，给它一点时间再继续
                time.sleep(2.0)
                # **不调 `adb root`**：它会再次重启 adbd（本机上把 adb 弄死的
                # 主要来源）。而且现在也不需要 root——这些字段的写入走的是 MuMu
                # root shell（见 apply 的 `_prefer_mumu` 切换）。
                rep["reroot"] = False
            except Exception:
                rep["reroot"] = False
            # **重启 framework 之后必须再补一轮**（2026-11-05 实测）。
            #
            # 实测现象：zygote 重启完成后
            #   ro.nemu            1   ← 又回来了（这是 50003 的直接判据）
            #   ro.product.first_api_level  31  ← 回到 Android 12 的值
            # 而 ro.build.fingerprint / flavor / hardware / soc.model 都还是对的。
            #
            # 换句话说：MuMu 的 `nemuinit` 与部分平台键会在框架重启后被重新
            # 写入，而"深度设备检测"恰恰要同时看「Build 自洽」和「没有模拟器
            # 标记」两件事。所以这里补两步：重新应用一遍身份（幂等，绝大多数
            # 键是 unchanged）＋ 再清一次厂商 props。
            try:
                rep["reapply"] = apply(dev, ident, use_root=sec.get("use_root"),
                                       allow_build_props=_allow_build)
            except Exception as e:
                rep["reapply"] = {"error": str(e)[:120]}
            try:
                from . import stealth as _st
                rep["post_clean"] = _st.refresh(dev, (config or {}), logger)
            except Exception as e:
                rep["post_clean"] = {"error": str(e)[:120]}
        rep["audit"] = audit(dev)
        rep["audit"]["identity_id"] = ident.ident_id

        # **`ok` 必须看"真的写进去了几条"，不能无条件 True**（2026-11-04）。
        #
        # 实测这台 MuMu：`apply()` 返回
        #     applied=4 / failed=24 / mismatch={ro.product.model: (...)}
        # 而 `ensure()` 照样 `ok=True`、日志写"身份已应用"——
        # 操作员看到"已应用"就以为生效了，实际设备上 `ro.product.model`
        # 还是 SM-A5260。这是**假成功**（本仓库第 4 次踩同类）。
        #
        # 判据：至少 1 条 `verified`（写前≠值、写后==目标）才算应用成功；
        # 全是 mismatch/失败就如实 ok=False，并说明"ro.* 需完整 Magisk"。
        _verified = len(ap.get("verified") or [])
        _mismatch = len(ap.get("mismatch") or {})
        _failed = len(ap.get("failed") or [])
        rep["ok"] = bool(_verified) or bool(ap.get("android_id"))
        rep["verify_count"] = _verified
        if not rep["ok"]:
            rep["why"] = ("设备上没有任何一条身份字段被真正改写"
                          "（verified=0，mismatch=%d，failed=%d）；"
                          "标准 ro.* 需要**完整 Magisk**（patch boot.img）"
                          "才能覆盖，只提取 magisk 二进制不够"
                          % (_mismatch, _failed))
        if logger:
            if rep["ok"]:
                # **措辞要准确**：`android_id` 那条走 `settings put` 是真生效的，
                # 但机型类 `ro.*` 在这一层写不动。所以不能笼统说"身份已应用"
                # ——操作员会以为机型变了（2026-11-04 实测：机型仍是 SM-A5260）。
                _parts = []
                if _verified:
                    _parts.append("%d 条 props verified" % _verified)
                if ap.get("android_id"):
                    _parts.append("android_id 已改")
                if _mismatch:
                    _parts.append("%d 条 ro.* 未生效（需完整 Magisk）"
                                  % _mismatch)
                if ap.get("hot_write_skipped"):
                    _parts.append("%d 条机型/构建字段禁止热改"
                                  "（走官方键+重启）"
                                  % len(ap["hot_write_skipped"]))
                logger.info(
                    "[android] 身份写入 %s：%s；自检 %s",
                    ident.ident_id, "、".join(_parts) or "无变化",
                    _fmt_audit_score(rep["audit"]))
            else:
                logger.warning(
                    "[android] 身份**未生效**（verified=0，mismatch=%d，"
                    "failed=%d）：标准 ro.* 需完整 Magisk 才能覆盖；"
                    "自检 %s",
                    _mismatch, _failed, _fmt_audit_score(rep["audit"]))
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
