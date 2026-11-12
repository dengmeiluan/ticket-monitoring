# -*- coding: utf-8 -*-
"""r960：`bootprops` —— 改 build.prop 里**真正会到 App 手上**的 build.id。

实测背景（2026-11-04，同日两轮纠错）：
* 逐键比对"文件值 vs 运行时 getprop"发现：`ro.product.system.*`、各分区
  `build.fingerprint`、`ro.build.flavor/description/product` 里的
  `mumu_win_x86_64` **都被 MuMu 在 boot 期覆盖过了**（现值 vivo/V2405A），
  所以改那些文件是白干；
* 真正"文件赢"的只有 build.id 一族（`V417IR`）与 `ro.build.display.id`，
  而这些 App 一次 `getprop ro.build.id` 就读得到。

因此本模块的契约是三条，测试按这三条钉：
1. **只改白名单键**（结构上保证不会碰 `cpu.abilist` / `dalvik.vm.isa.*`
   这类运行期依赖 —— 改那些是真的会把系统写坏）；
2. **写后必须读回校验**（`cp`/`push` 返回 0 不算成功，只读分区会静默失败）；
3. **机型不在池里就不改**（宁可不写，也不凭猜塞一个 build 号进去）。

另外目标值全部取自 `fingerprint.PHONE_POOL`，本模块不另立机型常量。

跑：
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r960_bootprops_build_id.py -q
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.android import bootprops as bp  # noqa: E402
from core.android.fingerprint import PHONE_POOL  # noqa: E402

SYS_PROP = "\n".join([
    "ro.build.id=V417IR",
    "ro.build.display.id=V417IR release-keys",
    "ro.system.build.id=V417IR",
    "ro.system_ext.build.id=V417IR",
    "# ro.product.build.id=V417IR  (注释行不许被改)",
    "ro.product.system.brand=mumu_win",
    "ro.system.product.cpu.abilist=x86_64,arm64-v8a",
    "ro.system.build.fingerprint=mumu_win/mumu_win_x86_64/"
    "mumu_win_x86_64:15/V417IR/1171:user/release-keys",
    "dalvik.vm.isa.x86_64.variant=x86_64",
    "",
]) + "\n"
PRODUCT_PROP = "ro.product.build.id=V417IR\nro.product.brand=mumu_win\n"
VENDOR_PROP = "ro.vendor.build.id=V417IR\n"
ODM_PROP = "ro.odm.build.id=V417IR\n"


class _Dev:
    """内存文件系统 + 可控写入失败。"""

    def __init__(self, model="V2405A", writable=True, empty_files=()):
        self.files = {
            "/system/build.prop": SYS_PROP,
            "/system/system_ext/etc/build.prop": SYS_PROP,
            "/product/etc/build.prop": PRODUCT_PROP,
            "/vendor/build.prop": VENDOR_PROP,
            "/odm/etc/build.prop": ODM_PROP,
        }
        for p in empty_files:
            self.files[p] = ""          # 模拟"读不到"
        self.props = {"ro.product.model": model,
                      "ro.build.fingerprint":
                          "vivo/V2405A/V2405A:15/V417IR/1171:user/release-keys"}
        self.writable = writable
        self.pushed = []
        self.calls = []

    def _sh(self, *a, timeout=None):
        cmd = " ".join(str(x) for x in a)
        self.calls.append(cmd)
        toks = cmd.split()
        if toks[:2] == ["shell", "getprop"] and len(toks) == 2:
            return "\n".join("[%s]: [%s]" % (k, v)
                             for k, v in self.props.items())
        if toks[:2] == ["shell", "cat"] and len(toks) >= 3:
            return self.files.get(toks[2], "")
        if toks[:2] == ["shell", "ls"]:
            args = toks[2:]
            # `ls -d <path>`（存在性检查）与 `ls <path>` 都要能答
            p = args[1] if (args and args[0] == "-d") else (
                args[0] if args else "")
            return p if p in self.files else ""
        if toks[:2] == ["shell", "cp"]:
            _src, dst = toks[3], toks[4]
            if _src in self.files:
                self.files[dst] = self.files[_src]
            return ""
        if toks[:2] == ["shell", "mount"]:
            return ""
        return ""

    def push(self, local, remote):
        if not self.writable:
            return False
        with open(local, encoding="utf-8") as f:
            self.files[remote] = f.read()
        self.pushed.append(remote)
        return True


def _pool_entry(model="V2405A"):
    for p in PHONE_POOL:
        if p.get("model") == model:
            return p
    raise AssertionError("池里没有 %s（机型池被改了？本测试的前提失效）" % model)


# ---------------------------------------------------------------------------
# 1. 取值来自既有机型池，且只有 build.id 一族会被改
# ---------------------------------------------------------------------------
def test_resolve_and_desired_come_from_pool():
    prof = bp.resolve({"ro.product.model": "V2405A"})
    assert prof is _pool_entry(), "取值来源不是 PHONE_POOL（两处定义迟早漂移）"
    want = bp.desired(prof)
    assert want["ro.build.id"] == prof["build_id"]
    assert want["ro.build.display.id"] == "%s release-keys" % prof["build_id"]
    # 绝不该出现 abi / hardware / fingerprint 这类键
    assert not [k for k in want if "abi" in k or "hardware" in k
                or "fingerprint" in k], want


def test_plan_only_touches_allowlisted_keys():
    d = _Dev()
    pl = bp.plan(d)
    assert pl["profile_found"] is True
    todo = pl["files"]["/system/build.prop"]
    keys = {k for k, _o, _n in todo}
    assert keys <= set(bp.KEY_FIELDS) | {bp.DISPLAY_KEY}, keys
    # 反例：这些键在文件里也是 mumu/V417IR，但**不许**被顺手改掉
    for guarded in ("ro.system.product.cpu.abilist",
                    "dalvik.vm.isa.x86_64.variant",
                    "ro.product.system.brand",
                    "ro.system.build.fingerprint"):
        assert guarded not in keys, "白名单漏了，把运行期依赖也圈进来了"


def test_plan_skips_comment_lines():
    d = _Dev()
    pl = bp.plan(d)
    keys = {k for k, _o, _n in pl["files"]["/system/build.prop"]}
    assert "ro.product.build.id" not in keys, "注释行里的键不该进计划"


# ---------------------------------------------------------------------------
# 2. 写入：改对的东西、保住无关内容、可回滚
# ---------------------------------------------------------------------------
def test_apply_rewrites_ids_and_keeps_everything_else():
    d = _Dev()
    prof = _pool_entry()
    rep = bp.apply(d)
    assert rep["ok"] is True and rep["restart_required"] is True, rep
    assert rep["verified"] is True
    body = d.files["/system/build.prop"]
    assert "ro.build.id=%s" % prof["build_id"] in body
    assert "ro.build.display.id=%s release-keys" % prof["build_id"] in body
    # 未动的行必须原样在（尤其 abilist / dalvik / 注释行）
    assert "ro.system.product.cpu.abilist=x86_64,arm64-v8a" in body
    assert "dalvik.vm.isa.x86_64.variant=x86_64" in body
    assert "# ro.product.build.id=V417IR  (注释行不许被改)" in body
    assert len(body.rstrip("\n").splitlines()) == \
        len(SYS_PROP.rstrip("\n").splitlines()), "行数变了（结构被动过）"


def test_apply_backs_up_once_and_is_idempotent():
    d = _Dev()
    first = bp.apply(d)
    assert first["changed"] > 0 and first["backups"], first
    second = bp.apply(d)
    assert second["changed"] == 0, "第二次还在改 → 不幂等"
    assert second["restart_required"] is False, "无事可做却要求重启"
    # 关键：已有备份不能被"改后的版本"覆盖，否则回滚点就没了。
    # 备份路径用 `bp._bak_path()` 取，别在测试里重述命名规则（我第一版
    # 硬编码成 "_system_build.prop…" 猜错了前缀，白挂一条测试）。
    assert d.files[bp._bak_path("/system/build.prop")] == SYS_PROP
    assert len(second["backups"]) == 0


def test_each_partition_gets_its_own_backup():
    """五个文件 basename 全是 `build.prop` —— 共用一个备份名会出大事：

    * 除第一个之外的分区**没有回滚点**（`ls` 已非空 → 跳过备份）；
    * `restore()` 会把 /system 的原件灌进 /product、/vendor、/odm
      → 那是把设备写坏，不是回滚。
    """
    d = _Dev()
    rep = bp.apply(d)
    assert len(set(rep["backups"])) == len(rep["backups"]) == 5, rep["backups"]
    for p in bp.BUILD_PROPS:
        bak = bp._bak_path(p)
        assert bak in rep["backups"], (p, bak)
        assert d.files[bak] == {
            "/system/build.prop": SYS_PROP,
            "/system/system_ext/etc/build.prop": SYS_PROP,
            "/product/etc/build.prop": PRODUCT_PROP,
            "/vendor/build.prop": VENDOR_PROP,
            "/odm/etc/build.prop": ODM_PROP,
        }[p], "备份内容串了"


def test_apply_refuses_when_model_not_in_pool():
    d = _Dev(model="ZZZ-999")
    rep = bp.apply(d)
    assert rep["ok"] is False and rep["changed"] == 0, rep
    assert "不在 PHONE_POOL" in rep["skipped"]
    assert d.pushed == [], "机型认不出来还硬写 = 凭猜塞 build 号"


def test_apply_never_writes_empty_content():
    """文件存在但内容为空 → 必须跳过写入**并让报告带伤**。

    两件事都要成立，缺一都是骗人：
    * 不 push 空内容（那会把设备写坏）；
    * 不能因为"没有可改项"就返回 ok=True —— 那里的 `V417IR` 还在，
      App 依然读得到，这是**部分完成**，不是完成。
    """
    d = _Dev(empty_files=("/vendor/build.prop",))
    rep = bp.apply(d)
    assert "/vendor/build.prop" not in d.pushed, "空内容被 push 上去了"
    assert any("读不到内容" in x for x in rep["failed"]), rep["failed"]
    assert rep["ok"] is False and rep["verified"] is False, rep
    # 其它分区仍应正常完成（一处失败不该拖垮整件事）
    assert "/system/build.prop" in rep["files"]


def test_apply_reports_readonly_partition_honestly():
    """只读分区：push 一直失败 → 绝不能报"全改好了"。"""
    d = _Dev(writable=False)
    rep = bp.apply(d)
    assert rep["ok"] is False and rep["changed"] == 0, rep
    assert rep["verified"] is False
    assert any("只读" in x or "写入失败" in x for x in rep["failed"]), rep["failed"]
    assert rep["restart_required"] is False, "什么都没写成，不该要求重启"


def test_apply_respects_config_off():
    d = _Dev()
    rep = bp.apply(d, config={"android": {"boot_props": {"enabled": False}}})
    assert rep["skipped"] == "config 关闭" and d.pushed == []


# ---------------------------------------------------------------------------
# 3. 回滚
# ---------------------------------------------------------------------------
def test_restore_brings_original_back():
    d = _Dev()
    bp.apply(d)
    assert "ro.build.id=V417IR" not in d.files["/system/build.prop"]
    rep = bp.restore(d)
    assert rep["ok"] is True and "/system/build.prop" in rep["restored"], rep
    assert d.files["/system/build.prop"] == SYS_PROP


def test_offline_device_does_not_crash():
    assert bp.apply(_Dev(model=""))["ok"] is False
