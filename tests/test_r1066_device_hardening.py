# -*- coding: utf-8 -*-
"""device_hardening 的判据测试（用假设备，不需要真机）。

为什么值得钉：这套体检是"换机/重装后靠它告诉我漏了什么"，
判据写错就会给出**假绿**——那比没有更危险。所以每条判据都要有反证：
正常设备应全 PASS，缺项设备应精确指出缺哪条。
"""
import importlib.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _mod():
    p = os.path.join(ROOT, "scripts", "device_hardening.py")
    spec = importlib.util.spec_from_file_location("device_hardening", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class FakeDev:
    """按命令前缀返回预置输出；未匹配的命令返回空串。"""

    def __init__(self, answers, root=True):
        self.answers = answers
        self._root = root
        self.sent = []

    def is_root(self):
        return self._root

    def root(self):
        return self._root

    def sh(self, cmd, timeout=None):
        self.sent.append(cmd)
        # 取**最长**匹配的键：否则 "ls /data/adb/modules" 会抢走
        # "ls /data/adb/modules/mumu_cloak/disable" 的答案（前缀重叠）
        for k in sorted(self.answers, key=len, reverse=True):
            if cmd.startswith(k):
                return self.answers[k]
        return ""

    def push(self, a, b):
        return ""


GOOD = {
    "su -c 'magisk -V'": "31100",
    "getprop ro.product.model": "V2405A",
    "getprop ro.product.cpu.abilist": "arm64-v8a,armeabi-v7a,x86_64",
    "head -2 /proc/cpuinfo": "processor\t: 0\nBogoMIPS\t: 38.40",
    "getenforce": "Enforcing",
    "getprop gsm.version.ril-impl": "MediaTek RIL 1.0",
    "getprop ro.carrier": "OPEN",
    "getprop gsm.network.type": "LTE",
    "pm list packages": "package:com.taobao.trip\npackage:com.nemu.oaidmanager",
    "pidof zygote64": "758",
    "grep -c zygisk": "3",
    "ls /data/adb/modules": "zygisksu\nzygisk_shamiko\nmumu_cloak\ntm_identity",
    "su -c 'magisk --denylist ls'":
        "com.taobao.trip|com.taobao.trip\n"
        "ctrip.android.view|ctrip.android.view\n"
        "com.Qunar|com.Qunar\n"
        "com.tongcheng.android|com.tongcheng.android\n"
        "cn.suanya.zhixing|cn.suanya.zhixing",
    "ls /data/adb/modules/mumu_cloak/disable": "",
}


def by_name(checks):
    return {n: (ok, d) for n, ok, d in checks}


def test_good_device_all_pass():
    m = _mod()
    checks = m.inspect(FakeDev(GOOD))
    ok, report = m.verdict(checks)
    assert ok, report


def test_intel_cpuinfo_is_caught():
    m = _mod()
    d = dict(GOOD)
    d["head -2 /proc/cpuinfo"] = ("processor\t: 0\nvendor_id\t: GenuineIntel")
    checks = by_name(m.inspect(FakeDev(d)))
    assert checks["/proc/cpuinfo = ARM 视图"][0] is False


def test_reference_ril_is_caught():
    """AOSP 的 reference-ril 是教科书级模拟器指纹，必须判红。"""
    m = _mod()
    d = dict(GOOD)
    d["getprop gsm.version.ril-impl"] = "android reference-ril 1.0"
    checks = by_name(m.inspect(FakeDev(d)))
    assert checks["电话层去模拟器化"][0] is False


def test_hspa_network_is_caught():
    m = _mod()
    d = dict(GOOD)
    d["getprop gsm.network.type"] = "HSPA"
    checks = by_name(m.inspect(FakeDev(d)))
    assert checks["电话层去模拟器化"][0] is False


def test_permissive_is_caught():
    m = _mod()
    d = dict(GOOD)
    d["getenforce"] = "Permissive"
    checks = by_name(m.inspect(FakeDev(d)))
    assert checks["SELinux 视图 Enforcing"][0] is False


def test_package_leak_is_caught_but_oaid_exempt():
    """magisk/kernelsu 这类必须判红；oaidmanager 是有意保留的，不算泄漏。"""
    m = _mod()
    d = dict(GOOD)
    d["pm list packages"] = ("package:com.taobao.trip\n"
                             "package:com.topjohnwu.magisk\n"
                             "package:com.nemu.oaidmanager")
    checks = by_name(m.inspect(FakeDev(d)))
    assert checks["包名暴露面"][0] is False
    # 只有 oaidmanager 时应判绿
    d["pm list packages"] = ("package:com.taobao.trip\n"
                             "package:com.nemu.oaidmanager")
    checks = by_name(m.inspect(FakeDev(d)))
    assert checks["包名暴露面"][0] is True


def test_missing_module_is_caught():
    m = _mod()
    d = dict(GOOD)
    d["ls /data/adb/modules"] = "zygisksu"
    checks = by_name(m.inspect(FakeDev(d)))
    ok, detail = checks["Magisk 模块齐全"]
    assert ok is False and "mumu_cloak" in detail


def test_denylist_gap_is_caught():
    m = _mod()
    d = dict(GOOD)
    d["su -c 'magisk --denylist ls'"] = "com.Qunar|com.Qunar"
    checks = by_name(m.inspect(FakeDev(d)))
    assert checks["目标 App 已在隐藏名单"][0] is False


def test_zygote_not_injected_is_caught():
    m = _mod()
    d = dict(GOOD)
    d["grep -c zygisk"] = "0"
    checks = by_name(m.inspect(FakeDev(d)))
    assert checks["Zygisk 已注入 zygote"][0] is False


def test_parse_helpers():
    m = _mod()
    assert m.parse_packages("package:a.b\npackage:c.d\n") == {"a.b", "c.d"}
    assert m.parse_denylist("a.b|a.b\nc.d|c.d:remote\n") == {"a.b", "c.d"}
    assert m.module_ids("zygisksu\nmumu_cloak\n") == {"zygisksu", "mumu_cloak"}


def test_no_dev_assumption_in_check_mode():
    """默认必须是只读：不传 --apply 时不应有任何写操作。"""
    m = _mod()
    fake = FakeDev(GOOD)
    m.inspect(fake)
    for cmd in fake.sent:
        assert not cmd.startswith(("magisk --install-module", "push")), cmd


# ---------------- 本会话新增：有害模块 / 轮询等待 ----------------

class FakeDevWithFlags(FakeDev):
    """支持 touch disable 语义的假设备：记录被 touch 的模块。"""

    def __init__(self, answers, installed, already_disabled=()):
        super().__init__(answers)
        self.installed = list(installed)
        self.disabled = set(already_disabled)

    def sh(self, cmd, timeout=None):
        self.sent.append(cmd)
        if cmd.startswith("touch /data/adb/modules/"):
            name = cmd.split("/data/adb/modules/")[1].split("/")[0]
            self.disabled.add(name)
            return ""
        if cmd.startswith("ls /data/adb/modules/") and cmd.endswith("/disable"):
            name = cmd.split("/data/adb/modules/")[1].split("/")[0]
            return "/data/adb/modules/%s/disable" % name \
                if name in self.disabled else ""
        if cmd.startswith("ls /data/adb/modules"):
            return "\n".join(self.installed)
        return super().sh(cmd)


def test_bad_modules_are_disabled():
    m = _mod()
    d = FakeDevWithFlags(GOOD,
                         installed=list(m.BAD_MODULES) + ["zygisksu"])
    ok, detail = m.disable_bad_modules(d)
    assert ok, detail
    assert set(m.BAD_MODULES) <= d.disabled


def test_bad_module_left_enabled_is_flagged():
    """体检必须把「有害模块仍在启用」判红——否则用户会以为一切正常。"""
    m = _mod()
    hma = list(m.BAD_MODULES)[0]
    answers = dict(GOOD)
    answers["ls /data/adb/modules"] = "zygisksu\nzygisk_shamiko\nmumu_cloak\n" + hma
    d = FakeDevWithFlags(answers, installed=[hma])
    checks = {n: (ok, det) for n, ok, det in m.inspect(d)}
    ok, det = checks["有害模块已停用"]
    assert ok is False and hma in det


def test_wait_for_hardening_polls_until_ready():
    """开机伪装 2–3 分钟才生效：必须轮询等到，而不是一次判死。"""
    m = _mod()
    seq = [
        {"head -2 /proc/cpuinfo": "processor: 0\nvendor_id: GenuineIntel",
         "getenforce": "Permissive",
         "getprop gsm.version.ril-impl": "android reference-ril 1.0"},
        {"head -2 /proc/cpuinfo": "processor: 0\nBogoMIPS: 1", "getenforce": "Enforcing",
         "getprop gsm.version.ril-impl": "MediaTek RIL 1.0"},
    ]

    class Stepper(FakeDev):
        def __init__(self):
            super().__init__({})
            self.i = 0

        def sh(self, cmd, timeout=None):
            ans = seq[min(self.i, len(seq) - 1)]
            hit = ""
            for k, v in ans.items():
                if cmd.startswith(k):
                    hit = v
                    break
            # 每轮的最后一条读取（ril）之后推进一格，模拟"下一轮伪装生效了"
            if cmd.startswith("getprop gsm.version.ril-impl"):
                self.i += 1
            return hit

    d = Stepper()
    # 用很小的 interval，靠 fake 永远返回最后一格来结束
    ok, detail = m.wait_for_hardening(d, timeout=3, interval=0.01)
    assert ok, detail


def test_wait_for_hardening_times_out_honestly():
    m = _mod()
    d = FakeDev({"head -2 /proc/cpuinfo": "vendor_id: GenuineIntel",
                 "getenforce": "Permissive"})
    ok, detail = m.wait_for_hardening(d, timeout=1, interval=0.05)
    assert ok is False and "cpuinfo_arm=False" in detail


# ---------------- 路径自动探测（别人 clone 下来能跑） ----------------

def test_find_adb_and_manager_in_first_candidate(tmp_path, monkeypatch):
    m = _mod()
    base = str(tmp_path)
    nx = os.path.join(base, "nx_main")
    os.makedirs(nx)
    for exe in ("adb.exe", "MuMuManager.exe"):
        open(os.path.join(nx, exe), "wb").write(b"x")
    monkeypatch.setattr(m, "_mumu_candidates", lambda: [base])
    assert m.find_adb() == os.path.join(nx, "adb.exe")
    assert m.find_mumu_manager() == os.path.join(nx, "MuMuManager.exe")


def test_find_adb_returns_empty_when_absent(monkeypatch):
    m = _mod()
    monkeypatch.setattr(m, "_mumu_candidates", lambda: [])
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert m.find_adb() == ""
    assert m.find_mumu_manager() == ""


def test_candidates_cover_common_drives(monkeypatch):
    """常见盘符与 Program Files 都要在候选里，不能只有一处。"""
    m = _mod()
    cands = [c.lower() for c in m._mumu_candidates()]
    assert any("netease" in c for c in cands), cands
    joined = " ".join(cands)
    assert "net ease" not in joined
    # 至少覆盖两个不同盘符（本机 D 盘、别人 C 盘）
    drives = {c[:2] for c in cands if len(c) > 1 and c[1] == ":"}
    assert len(drives) >= 2, cands


# ---------------- Magisk 预检（从零开始的第一道门） ----------------

def test_magisk_missing_is_flagged():
    """没有 Magisk 时，后面所有模块都装不了，体检必须单独判红。"""
    m = _mod()
    d = dict(GOOD)
    d["magisk -V"] = ""
    d["su -c 'magisk -V'"] = ""
    checks = {n: (ok, det) for n, ok, det in m.inspect(FakeDev(d))}
    ok, det = checks["Magisk 已安装"]
    assert ok is False
    assert "Magisk" in det and "docs/" in det


def test_magisk_present_passes():
    m = _mod()
    d = dict(GOOD)
    d["su -c 'magisk -V'"] = "31100"
    checks = {n: (ok, det) for n, ok, det in m.inspect(FakeDev(d))}
    assert checks["Magisk 已安装"][0] is True


def test_apply_stops_early_without_magisk():
    """没 Magisk 时 apply 必须提前返回并说明，而不是抛一串 not found。"""
    m = _mod()

    class NoMagisk(FakeDev):
        def sh(self, cmd, timeout=None):
            if "magisk -V" in cmd:
                return ""
            return super().sh(cmd)

    steps = m.apply(NoMagisk(GOOD), "packages")
    assert steps and steps[0][0] == "Magisk 预检"
    assert steps[0][1] is False
    assert "Magisk" in steps[0][2]
    # 关键：不能继续往下装模块
    assert len(steps) == 1


def test_apply_continues_when_magisk_present():
    m = _mod()
    d = dict(GOOD)
    d["su -c 'magisk -V'"] = "31100"
    steps = m.apply(FakeDev(d), "packages")
    assert steps[0][0] == "Magisk 预检" and steps[0][1] is True
    assert len(steps) > 1


# ---------------- 补 x86_64 库：失败不许静默 ----------------

class _ShellStub(FakeDev):
    def __init__(self, out):
        super().__init__({})
        self.out = out

    def sh(self, cmd, timeout=None):
        self.sent.append(cmd)
        return self.out


def test_fill_x64_no_unzip_is_failure():
    """没有解压工具时必须判失败——静默跳过会让故障跑到很远的地方才暴露。"""
    m = _mod()
    ok, msg = m._fill_x64(_ShellStub("NO_UNZIP\n"))
    assert ok is False
    assert "解压工具" in msg


def test_fill_x64_reports_filled_modules():
    m = _mod()
    ok, msg = m._fill_x64(_ShellStub("filled:zygisksu\nfilled:zygisk_shamiko\nDONE\n"))
    assert ok is True
    assert "zygisksu" in msg and "zygisk_shamiko" in msg


def test_fill_x64_failure_is_reported():
    m = _mod()
    ok, msg = m._fill_x64(_ShellStub("fail:mumu_cloak(解压不出 x86_64.so)\nDONE\n"))
    assert ok is False
    assert "mumu_cloak" in msg


def test_fill_x64_all_present_is_success():
    m = _mod()
    ok, msg = m._fill_x64(_ShellStub("ok:zygisksu(已齐全)\nDONE\n"))
    assert ok is True
    assert "齐全" in msg


def test_fill_x64_truncated_output_is_failure():
    """脚本没跑到 DONE（比如被中断）不能当成功。"""
    m = _mod()
    ok, msg = m._fill_x64(_ShellStub("ok:zygisksu(已齐全)\n"))
    assert ok is False
    assert "未正常结束" in msg


# ---------------- 批量体检（快路径） ----------------

GOOD_REPORT = """MODEL=V2405A
ABI=arm64-v8a,armeabi-v7a,x86_64
CPU=processor\t: 0 BogoMIPS\t: 38.40 
ENF=Enforcing
RIL=MediaTek RIL 1.0
CARRIER=OPEN
NET=LTE
PKGS=package:com.taobao.trip package:com.nemu.oaidmanager 
ZPID=758
ZYG=3
MODS=zygisksu zygisk_shamiko mumu_cloak tm_identity 
MV=31100
DENY=com.Qunar|com.Qunar ctrip.android.view|ctrip.android.view \
com.tongcheng.android|com.tongcheng.android cn.suanya.zhixing|cn.suanya.zhixing \
com.taobao.trip|com.taobao.trip 
ROOT=1
CLOAK_OFF=
END
"""


def _rep(**over):
    """在好报告上做单点篡改，返回报告文本。"""
    txt = GOOD_REPORT
    for k, v in over.items():
        # 用行首锚定替换，避免误伤其它键
        import re as _re
        txt = _re.sub(r"(?m)^%s=.*$" % k, "%s=%s" % (k, v), txt, count=1)
    return txt


def test_probe_report_requires_end():
    """没有 END 的报告不可信（可能被截断），必须返回 None 走回退。"""
    m = _mod()
    assert m.parse_probe_report("") is None
    assert m.parse_probe_report("MODEL=V2405A\n") is None
    assert m.parse_probe_report(GOOD_REPORT) is not None


def test_fast_path_all_pass():
    m = _mod()
    checks = m.checks_from_report(m.parse_probe_report(GOOD_REPORT))
    ok, rep = m.verdict(checks)
    assert ok, rep
    assert len(checks) == 13


def test_fast_path_catches_violations():
    m = _mod()
    cases = [
        ({"ENF": "Permissive"}, "SELinux 视图 Enforcing"),
        ({"CPU": "vendor_id: GenuineIntel"}, "/proc/cpuinfo = ARM 视图"),
        ({"RIL": "android reference-ril 1.0"}, "电话层去模拟器化"),
        ({"NET": "HSPA"}, "电话层去模拟器化"),
        ({"ZYG": "0"}, "Zygisk 已注入 zygote"),
        ({"MV": ""}, "Magisk 已安装"),
        ({"MODS": "zygisksu"}, "Magisk 模块齐全"),
        ({"CLOAK_OFF": "/data/adb/modules/mumu_cloak/disable"},
         "mumu_cloak 已启用"),
    ]
    for over, label in cases:
        rep = m.parse_probe_report(_rep(**over))
        d = {n: (ok, det) for n, ok, det in m.checks_from_report(rep)}
        assert d[label][0] is False, (over, label, d[label])


def test_fast_path_catches_bad_module_active():
    """有害模块在位但没 disable 文件 → 必须判红。"""
    m = _mod()
    txt = _rep(MODS="zygisksu zygisk_shamiko mumu_cloak hma_oss_zygisk")
    rep = m.parse_probe_report(txt)
    d = {n: (ok, det) for n, ok, det in m.checks_from_report(rep)}
    assert d["有害模块已停用"][0] is False


def test_fast_path_package_leak():
    m = _mod()
    txt = _rep(PKGS="package:com.taobao.trip package:com.topjohnwu.magisk")
    rep = m.parse_probe_report(txt)
    d = {n: (ok, det) for n, ok, det in m.checks_from_report(rep)}
    assert d["包名暴露面"][0] is False


def test_inspect_prefers_single_round_trip():
    """真机路径必须只用一次 adb 调用（19 次 → 1 次是这轮的优化目标）。"""
    m = _mod()

    class OneShot(FakeDev):
        def sh(self, cmd, timeout=None):
            self.sent.append(cmd)
            return GOOD_REPORT

    d = OneShot(GOOD)
    checks = m.inspect(d)
    assert len(d.sent) == 1, d.sent
    assert len(checks) == 13


def test_inspect_falls_back_when_no_report():
    """拿不到汇总报告时退回逐条探测（老设备/受限 su 也能体检）。"""
    m = _mod()

    class NoReport(FakeDev):
        def sh(self, cmd, timeout=None):
            self.sent.append(cmd)
            for k in sorted(self.answers, key=len, reverse=True):
                if cmd.startswith(k):
                    return self.answers[k]
            return ""

    d = NoReport(GOOD)
    checks = m.inspect(d)
    assert len(d.sent) > 1, "应走回退路径"
    ok, rep = m.verdict(checks)
    assert ok, rep
