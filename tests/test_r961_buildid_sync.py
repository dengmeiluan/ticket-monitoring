# -*- coding: utf-8 -*-
"""r961：`buildid.sync` —— 把 V417IR 盖掉，但只许碰展示型字符串。

背景（§6.41，两个被证伪的假设）：
* 我以为 build.prop 是 `ro.build.id` 的出处：改完 5 个分区、重启后文件里
  仍是改后的值，但运行时照旧 `V417IR` ⇒ **文件不是出处**，MuMu 的 boot
  注入器盖在上面。判"谁赢"要用**改了会不会变**来测，不能看当前是否相等
  （相等可能只是同源巧合）。
* 我以为 `device-prop-configs/build.config` 是注入源：它写的是
  OnePlus8Pro / Android 12 / sdk=32 / eng.nioh.*，与运行时
  vivo/V2405A/15/35/1171 全不相符 ⇒ 是没被应用的模板。

唯一可用通道是已验证的 `resetprop --delete` + set。风险边界必须钉死：
`ro.build.version.*` / `ro.product.cpu.*` / `ro.hardware` 一类改动今天
两次让 system_server 重启、一次让 linker 打不开 so，**不许**进这个模块。

跑：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r961_buildid_sync.py -q
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.android import buildid as bi  # noqa: E402

PROPS = {
    "ro.product.model": "V2405A",
    "ro.product.brand": "vivo",
    "ro.product.device": "V2405A",
    "ro.build.version.release": "15",
    "ro.build.version.sdk": "35",
    "ro.build.version.incremental": "1171",
    "ro.build.id": "V417IR",
    "ro.build.display.id": "V417IR release-keys",
    "ro.build.fingerprint":
        "vivo/V2405A/V2405A:15/V417IR/1171:user/release-keys",
}


class _Dev:
    def __init__(self, props=None):
        self.props = dict(props if props is not None else PROPS)
        self.set_calls = []
        self.calls = []

    def _sh(self, *a, timeout=None):
        cmd = " ".join(str(x) for x in a)
        self.calls.append(cmd)
        if cmd.strip() == "shell getprop":
            return "\n".join("[%s]: [%s]" % (k, v)
                             for k, v in self.props.items())
        if cmd.startswith("shell getprop "):
            return self.props.get(cmd.split(" ", 2)[2], "")
        return ""


def _fake_magisk(monkey, path="/data/adb/magisk/magisk resetprop"):
    """resetprop 写成功 = 让 getprop 读回目标值（真实写用 sh_script 记录）。

    注意脚本里的值是 `_q()` 加过单引号的，必须脱引号再落到 props 上，
    否则读回比对会因为多两个引号字符而假失败。
    """
    import re
    monkey.setattr(bi, "_magisk", lambda dev: path)

    def fake_sh(dev, script, timeout=None):
        dev.set_calls.append(script)
        m = re.search(r"resetprop\s+(\S+)\s+(.+)$", script)
        if m:
            v = m.group(2).strip()
            if v.startswith("'") and v.endswith("'"):
                v = v[1:-1]
            dev.props[m.group(1)] = v
        return ""

    monkey.setattr(bi, "sh_script", fake_sh)


# ---------------------------------------------------------------------------
# 1. 边界：改什么由"值里含旧 build 号"**动态发现**，安全边界靠**排除表**兜
# ---------------------------------------------------------------------------
def test_banned_list_covers_structural_keys():
    """不再断言"白名单里没有危险键"，而是断言**排除表覆盖**危险键。

    白名单一定会漏：第一版只列了 `ro.build.id` + 六个分区 fingerprint，
    漏掉五个分区 `ro.<part>.build.id` 与 `ro.vendor_dlkm.*`，
    结果写出 `Build.ID=AP3A…` 而 `ro.system.build.id=V417IR` 的**半改状态**
    —— 比不改更糟，因为自洽性正是风控 SDK 最常查的一项。
    现在模型是"含旧号就改"，兜底的只能是排除表，所以它必须显式覆盖：
    版本族 / ABI / SoC / 启动链 / 序列号 / adb 开关 / dalvik。
    """
    need = ("ro.build.version.", "ro.product.cpu.", "ro.hardware",
            "ro.board.platform", "ro.boot.", "ro.serialno",
            "ro.adb.secure", "ro.debuggable", "dalvik.")
    for n in need:
        assert n in bi.BANNED_SUBSTR, "%s 必须在排除表里" % n


def test_target_for_emits_only_keys_it_was_given():
    """计划里的键全部来自传入的 props，一个都不发明（这就是动态发现）。"""
    props = dict(PROPS)
    props["ro.vendor.build.id"] = "V417IR"      # 模拟分区 id 落后
    props["ro.build.description"] = "missi_V2405A-user 15 V417IR 1171 x"
    want = bi.target_for(props)
    assert want, "含旧 build 号却没生成计划"
    assert set(want) <= set(props), set(want) - set(props)
    for k in ("ro.build.id", "ro.build.display.id", "ro.build.description",
              "ro.build.fingerprint", "ro.vendor.build.id"):
        assert k in want, "%s 含旧号却漏发现（成套字段漏一个=半改）" % k
    assert all("V417IR" not in v for v in want.values()), want


def test_target_for_invents_nothing_for_absent_keys():
    """设备上没读到的键，绝不凭空生成写入。

    这不是吹毛求疵：白名单版本会给设备上**并不存在**的键硬写一个值，
    于是"改了什么"和"设备上有什么"两套事实开始分叉。
    动态发现天然只会处理真存在的值 —— 这正是放弃白名单的理由。
    """
    props = {"ro.product.model": "V2405A", "ro.build.id": "V417IR"}
    want = bi.target_for(props)
    assert set(want) <= set(props), set(want) - set(props)
    assert "ro.build.description" not in want, \
        "props 里没有 description，不该凭模板造一个写进去"


def test_banned_key_is_skipped_even_if_it_holds_old_id():
    """排除表优先于动态发现：版本族键哪怕含旧号也不许改。"""
    props = dict(PROPS)
    props["ro.build.version.incremental"] = "15.V417IR"
    want = bi.target_for(props)
    assert "ro.build.version.incremental" not in want, \
        "改到版本族键：这正是今天两次 system_server 重启的成因"


def test_target_for_keeps_version_and_incr_untouched():
    """fingerprint 里的 release/incremental **沿用现值**，不自己造版本。"""
    want = bi.target_for(PROPS)
    fp = want["ro.build.fingerprint"]
    assert ":15/" in fp and fp.endswith("1171:user/release-keys"), fp
    assert "V417IR" not in fp, "fingerprint 里还留着 MuMu 的 build 号"
    assert want["ro.build.id"] != "V417IR"


def test_target_for_refuses_unknown_model():
    """机型不在池里 → 空 dict（不凭猜写一个 build 号进去）。"""
    assert bi.target_for({"ro.product.model": "NOPE-1",
                          "ro.build.id": "V417IR"}) == {}


def test_target_for_is_inplace_replace_not_recompose():
    """只替换旧 build 号那一段，其余部分**原样保留**。

    MuMu 注入器已经把 flavor/release/incremental/tags 组成一套自洽值，
    自己按模板重拼任何一处对不上，就制造出新矛盾（比统一像模拟器更可疑）。
    """
    props = {
        "ro.product.model": "V2405A",
        "ro.build.id": "V417IR",
        "ro.build.display.id": "V417IR release-keys",
        "ro.build.description": "missi_V2405A-user 15 V417IR 1171 release-keys",
        "ro.build.fingerprint":
            "vivo/V2405A/V2405A:15/V417IR/1171:user/release-keys",
        "ro.vendor.build.fingerprint":
            "vivo/V2405A/V2405A:15/V417IR/1171:user/release-keys",
    }
    want = bi.target_for(props)
    assert want["ro.build.display.id"] == "AP3A.240905.015 release-keys", want
    assert want["ro.build.description"] == (
        "missi_V2405A-user 15 AP3A.240905.015 1171 release-keys"), want
    assert want["ro.build.fingerprint"] == (
        "vivo/V2405A/V2405A:15/AP3A.240905.015/1171:user/release-keys"), want
    # description 也要被发现：漏了它就会出现 ID 与 DESCRIPTION 互相矛盾
    assert "ro.build.description" in want, want
    # 不含旧 build 号的键一律不动；设备上是空值的键也不发明
    assert all("V417IR" not in v for v in want.values()), want
    assert set(want) <= set(props), set(want) - set(props)


def test_already_coherent_is_not_a_failure():
    """已经自洽时返回空目标，且 `sync` 必须算 ok（不能污染成功率账本）。"""
    props = {"ro.product.model": "V2405A",
             "ro.build.id": "AP3A.240905.015",
             "ro.build.fingerprint":
                 "vivo/V2405A/V2405A:15/AP3A.240905.015/1171:user/release-keys"}
    assert bi.target_for(props) == {}


def test_sync_reports_residual_and_refuses_to_claim_success(monkeypatch):
    """写完必须复查"全机还有没有旧 token"。

    只检查"我改过的键对不对"是不够的：真实事故里九个键**全部写成功**，
    而另外七个键压根没进入计划，日志一片 green —— 半改状态被当成改完了。
    这条用例把"有残留 ⇒ ok=False / verified=False"钉住。
    """
    monkeypatch.setattr(bi, "_magisk",
                        lambda dev: "/data/adb/magisk/magisk resetprop")

    def fake_sh(dev, script, timeout=None):
        # 只写入 props 里**已存在**的键：分区 id 不在计划里 → 留下残留
        import re
        m = re.search(r"resetprop\s+(\S+)\s+(.+)$", script)
        if m:
            k = m.group(1)
            v = m.group(2).strip().strip("'")
            # **只让主命名空间写成功**，分区键模拟"没生效" ——
            # 动态发现之后分区键本来就在计划里，若照原写法全部写成功，
            # 这个用例根本测不到残留。
            if k.startswith("ro.build."):
                dev.props[k] = v
        dev.set_calls.append(script)
        return ""

    monkeypatch.setattr(bi, "sh_script", fake_sh)
    props = dict(PROPS)
    props["ro.system.build.id"] = "V417IR"     # 在计划内，但假写不生效 → 残留
    d = _Dev(props=props)
    rep = bi.sync(d, CFG)
    assert rep.get("residual"), rep
    assert rep["ok"] is False and rep["verified"] is False, rep


# ---------------------------------------------------------------------------
# 2. 默认关：不许有任何设备动作
# ---------------------------------------------------------------------------
def test_disabled_by_default(monkeypatch):
    d = _Dev()
    rep = bi.sync(d)
    assert rep["changed"] == 0 and "未启用" in rep["skipped"], rep
    assert d.set_calls == [], "开关没生效，默认就在写设备"


def test_no_resetprop_channel_reports_failure():
    import pytest
    d = _Dev()
    monkey = pytest.MonkeyPatch()
    monkey.setattr(bi, "_magisk", lambda dev: "")
    try:
        rep = bi.sync(d, config={"android": {"build_id": {"enabled": True}}})
        assert rep["ok"] is False and rep["changed"] == 0, rep
        assert "resetprop" in rep["error"]
    finally:
        monkey.undo()


# ---------------------------------------------------------------------------
# 3. 开启后：写、读回、失败不谎报
# ---------------------------------------------------------------------------
CFG = {"android": {"build_id": {"enabled": True}}}


def test_sync_applies_and_verifies(monkeypatch):
    _fake_magisk(monkeypatch)
    d = _Dev()
    rep = bi.sync(d, CFG)
    assert rep["ok"] is True and rep["changed"] > 0, rep
    assert rep["verified"] is True and not rep["failed"]
    assert any("--delete" in c for c in d.set_calls), \
        "没先 --delete：property area 的『已写过』标记会让 set 静默失效（§6.31）"
    assert d.props["ro.build.id"] != "V417IR"
    assert "V417IR" not in d.props["ro.build.fingerprint"]


def test_sync_is_cheap_when_already_coherent(monkeypatch):
    """已自洽时不该再发任何 resetprop（这条路径每轮都会走）。"""
    _fake_magisk(monkeypatch)
    d = _Dev()
    bi.sync(d, CFG)                       # 第一次真写
    n = len(d.set_calls)
    rep2 = bi.sync(d, CFG)                # 第二次应零写入
    assert rep2["changed"] == 0 and rep2["skipped"] == "已自洽", rep2
    assert len(d.set_calls) == n, "已自洽还在重复写"


def test_sync_refuses_unknown_model_on_device():
    """机型不认识时**什么都不写**，但这是"无事可做"，不是失败。"""
    d = _Dev(props={"ro.product.model": "MYSTERY",
                    "ro.build.id": "V417IR",
                    "ro.build.fingerprint": "x"})
    rep = bi.sync(d, CFG)
    assert rep["changed"] == 0 and rep["verified"] is True, rep
    assert rep["skipped"] and "不在 PHONE_POOL" in rep["skipped"], rep


def test_sync_does_not_claim_success_when_readback_mismatches(monkeypatch):
    """核心诚实条款：写命令返回 0 不算成功，必须读回相等。"""
    monkeypatch.setattr(bi, "_magisk",
                        lambda dev: "/data/adb/magisk/magisk resetprop")

    def fake_sh(dev, script, timeout=None):
        dev.set_calls.append(script)      # 记录写入，但 props **不变**
        return ""

    monkeypatch.setattr(bi, "sh_script", fake_sh)
    d = _Dev()
    rep = bi.sync(d, CFG)
    assert rep["ok"] is False, "读回没变却报成功（假成功）"
    assert rep["failed"], rep
    assert rep["verified"] is False


# ---------------------------------------------------------------------------
# 4. 接进流水线（否则又是一个只写不读的死模块）
# ---------------------------------------------------------------------------
def test_wired_into_harden():
    src = io.open(os.path.join(ROOT, "core", "android", "hardening.py"),
                  encoding="utf-8").read()
    assert "buildid" in src and '"build-id"' in src, "没接进 harden()"
    # 在 magisk 步之后：这条通道依赖 resetprop 已就位
    assert src.find("magisk-resetprop") < src.find("buildid"), \
        "顺序错了：resetprop 还没部署就想去盖"


def test_off_in_example_config():
    ex = io.open(os.path.join(ROOT, "config.example.yaml"),
                 encoding="utf-8").read()
    i = ex.find("build_id:")
    assert i > 0 and "enabled: false" in ex[i:i + 60], \
        "示例配置默认必须是关（要人工在采集空档验证）"
