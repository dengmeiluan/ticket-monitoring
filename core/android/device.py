# -*- coding: utf-8 -*-
"""ADB 设备原语：截图、点击、输入、UI 树、启停 App。

所有方法失败返回空值（b"" / "" / False），不抛异常——设备掉线是常态，
采集层需要把它变成一条 `path_note`，而不是一个调用栈。

实测基准（2026-10-27，MuMu 实例 0）：
  exec-out screencap -p  ≈ 63–91ms
  uiautomator dump + cat ≈ 75–77ms
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import time

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_OFFLINE_MARKS = ("device offline", "device not found", "no devices",
                  "device '", "unauthorized")

# UI dump 落到设备内的固定路径，避免每次随机名堆积
# UI dump 落点：/sdcard 是 media_rw 挂载，shell 删不掉旧文件（实测 rm 返回空
# 但 ls 文件仍在），只能换成 shell 自己的可写目录才能保证「读到的是这一屏」。
_DUMP_TMP_PATH = "/data/local/tmp/tm_ui.xml"


def _run(cmd, timeout, binary=False):
    kwargs = {"capture_output": True, "timeout": timeout}
    if os.name == "nt":
        kwargs["creationflags"] = _CREATE_NO_WINDOW
    try:
        return subprocess.run(cmd, **kwargs)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None


def _text(raw) -> str:
    if not raw:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", "replace")
    return str(raw)


class AdbDevice:
    """一台已连接设备（真机 / 模拟器同接口）。"""

    def __init__(self, adb_path: str, serial: str, timeout: int = 60):
        self.adb_path = adb_path
        self.serial = serial
        self.timeout = int(timeout or 60)
        self.last_error = ""
        # CLI dump 撞上 u2 已注册的 UiAutomation 后，本进程改用 u2
        self._prefer_u2 = False
        # 设计坐标系（默认 None = 不做任何换算，行为与改造前逐字一致）。
        # 只有在 ``display.spoof()`` 真改了 wm size 之后才该设置它：那时脚本
        # 里写死的常量属于「设计坐标」，而 UI 树 bounds 属于「设备坐标」。
        self.design = None
        self._size_cache = None
        # 协作式截止时间（2026-11-04）：为 0 表示不限制。
        # 为什么需要：路由级超时只是"不再等 future"，worker **仍在跑**并继续
        # 占着设备锁——实测导致 apscheduler 连续 10 小时全部 skipped。
        # 截止时间让 worker 在**下一个 adb 调用**处主动放弃，从而真正释放锁。
        self._deadline = 0.0
        self.deadline_hits = 0
        # adb 掉线后是否改走 MuMu root shell（见 _mumu_fallback）
        self._prefer_mumu = False
        self._mgr = None

    # ---------- 协作式截止 ----------
    def set_deadline(self, budget_s: float = 0, now: float = None) -> float:
        """arm 一个"从现在起 budget_s 秒后过期"的截止时间；0=解除。

        返回绝对过期时间戳（0 表示不限制）。所有 adb 指令在发出前都会检查，
        过期就当场返回 None（调用方本来就按 None 处理失败），于是整条
        采集链路会在**几毫秒内**退回、释放设备锁，而不是挂到天荒地老。
        """
        try:
            b = float(budget_s or 0)
        except (TypeError, ValueError):
            b = 0.0
        if b <= 0:
            self._deadline = 0.0
            return 0.0
        base = float(now if now is not None else time.time())
        self._deadline = base + b
        return self._deadline

    def deadline_left(self, now: float = None) -> float:
        """剩余预算秒数（0=不限或不剩）。"""
        if not self._deadline:
            return 0.0
        return max(0.0, self._deadline - float(
            now if now is not None else time.time()))

    def _expired(self, now: float = None) -> bool:
        return bool(self._deadline) and self.deadline_left(now) <= 0

    # ---------- 基础 ----------
    def _base(self):
        return [self.adb_path, "-s", self.serial]

    # ---------- MuMu root shell 降级通道 ----------
    #
    # 为什么需要（2026-11-05 反复实测）：这台 MuMu 的 adbd 很脆——
    # 跑完一轮设备操作后经常卡在握手阶段（`adb devices` 变 offline、
    # `adb shell` 挂住，**但设备本身一直健康**：`sys.boot_completed=1`、
    # props 全对、App 正常运行）。此时唯一还能用的通道是
    # `MuMuManager sh -v N -c <cmd>`——它走 VMMDev，不经过 adbd，
    # 而且直接就是 root（`u:r:nemuinit:s0`）。
    #
    # 所以设备层做成"adb 优先、MuMu shell 兜底"：adb 一旦回 offline，
    # 后续命令**自动改走 MuMu shell**，采集不再因为一条通道坏掉而整轮归零。
    def _mumu_mgr(self):
        if getattr(self, "_mgr", None) is not None:
            return self._mgr
        try:
            from .vendor import _manager
            mgr = _manager(vm_index=int(getattr(self, "vm_index", 0) or 0))
            self._mgr = mgr if mgr.available() else None
        except Exception:
            self._mgr = None
        return self._mgr

    def mumu_available(self) -> bool:
        return self._mumu_mgr() is not None

    def mumu_sh(self, cmd: str, timeout=None):
        """用 MuMu root shell 执行一条命令，返回 stdout（失败返回 None）。"""
        mgr = self._mumu_mgr()
        if mgr is None:
            return None
        try:
            out = mgr._call(["sh", "-v", str(mgr._vm(None)), "-c", str(cmd)],
                            timeout=timeout or self.timeout)
        except Exception:
            return None
        return out

    def _as_shell(self, args):
        """把 adb shell 参数拼成一条设备端命令（去掉开头的 ``shell``）。"""
        parts = list(args)
        if parts and parts[0] == "shell":
            parts = parts[1:]
        # 参数都是纯标识符/路径时才拼（带空格的命令调用方应直接传字符串）
        return " ".join(shlex.quote(str(p)) for p in parts)

    def _sh(self, *args, timeout=None):
        # 截止时间守卫放在**最前面**：卡死都发生在 adb 上，这里拦住就等于
        # 把"挂 900s"压缩成"立刻放弃 + 释放锁"。
        if self._expired():
            self.deadline_hits += 1
            self.last_error = "deadline exceeded"
            return None
        proc = _run(self._base() + list(args), timeout or self.timeout)
        if proc is None:
            self.last_error = "timeout or spawn failure"
            return self._mumu_fallback(args, timeout)
        out = _text(proc.stdout)
        err = _text(proc.stderr)
        if proc.returncode != 0:
            low = (out + err).lower()
            self.last_error = next(
                (m for m in _OFFLINE_MARKS if m in low),
                (err or out).strip()[:200] or f"rc={proc.returncode}")
            if any(m in self.last_error for m in _OFFLINE_MARKS):
                fb = self._mumu_fallback(args, timeout)
                if fb is not None:
                    return fb
        return out

    def _mumu_fallback(self, args, timeout=None):
        """adb 掉线时的兜底：把这条 shell 命令改走 MuMu root shell。

        **两个必须守的边界**（2026-11-05，踩过）：

        1. 只接管 ``adb shell ...``。``push`` / ``screencap`` 各有专门实现，
           不能把二进制内容当文本传。
        2. **`uiautomator` 类命令不许兜底**。实测 MuMu 的 shell 跑在
           `u:r:nemuinit:s0` 域，起不了 UI 自动化服务——`uiautomator dump`
           在那里**返回 0 节点**。而"0 节点"在下游看起来和"页面没这个控件"
           一模一样：App 渠道靠 UI 树定位控件，一旦 dump 走这条路就
           永远判"不是表单/列表"，整轮 0 条而账本只记 timeout。
           比报错更糟——这是**静默错判**。
        """
        if list(args[:1]) != ["shell"] or not self.mumu_available():
            return None
        lowered = " ".join(str(a) for a in args).lower()
        if "uiautomator" in lowered or "dump" in lowered:
            return None
        cmd = self._as_shell(args)
        out = self.mumu_sh(cmd, timeout=timeout)
        if out is not None:
            self.last_error = ""
            return out
        return None

    def recover_transport(self) -> dict:
        """把 adb 传输修回来：先**原序列断开重连**，再退到"换同机别名"。

        为什么需要（2026-11-05 实测）：
        MuMu 的同一台实例会以**多个** adb 序列同时出现：

            127.0.0.1:16384   ← 项目配置里用的那个（NAT 端口转发）
            127.0.0.1:5555    ← 实例自带 adbd 直连端口
            emulator-5554     ← 模拟器控制台别名

        `setprop ctl.restart zygote` 之后，16384 那条常会变成 `offline`
        甚至"显示 device 但 shell 不响应"；而设备本身一直健康
        （`MuMuManager sh -v 0 -c` 能读到 `sys.boot_completed=1`）。
        所以从 adb 这一侧看像"设备挂了"，其实是**传输层**坏了。

        修法分两步，先便宜后兜底：

        1. **原序列 disconnect + connect**（只对 ``host:port`` 形态）：
           adb 客户端会缓存一条死掉 socket 的会话状态，"显示 device 但
           shell 挂住"就是这种状态；断开重连能把它清掉。
        2. 仍然不通 → 换到**能真正应答 `getprop` 的同机别名**。

        安全约束：换序列前必须确认目标能应答 `getprop ro.serialno`。
        多实例环境下每条别名都会应答，所以这里**额外要求序列号一致**
        （与本机已知序列号比对；不知道就只接受"唯一候选"）。
        乱切会把命令打到另一台虚拟机上，那比"调用失败"危险得多。

        返回 ``{"switched", "from", "to", "online", "reconnected"}``。
        """
        rep = {"switched": False, "from": self.serial, "to": self.serial,
               "online": [], "reconnected": False}
        if self._shell_alive():
            return rep
        # ---- 第一步：原序列断开重连 ----
        if ":" in str(self.serial):
            _run([self.adb_path, "disconnect", self.serial],
                 max(10, self.timeout // 3))
            time.sleep(0.8)
            _run([self.adb_path, "connect", self.serial],
                 max(10, self.timeout // 3))
            time.sleep(1.5)
            rep["reconnected"] = True
            if self._shell_alive():
                rep["to"] = self.serial
                return rep
        # ---- 第二步：换同机别名 ----
        proc = _run([self.adb_path, "devices"], max(10, self.timeout // 3))
        if proc is None:
            return rep
        online = []
        for line in _text(proc.stdout).splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                online.append(parts[0])
        rep["online"] = online
        want = self._known_serial()
        others = [s for s in online if s != self.serial]
        for target in others:
            got = self._prop_via(target, "ro.serialno")
            if not got:
                continue
            if want and got != want:
                continue
            if not want and len(others) > 1:
                continue          # 无法判定同机时宁可不切
            self.serial = target
            self._size_cache = None
            rep["switched"] = True
            rep["to"] = target
            return rep
        if not rep["switched"]:
            self.last_error = ("adb 传输不可用（在线序列=%s，已知序列号=%s）"
                               % (",".join(online) or "无", want or "未知"))
        return rep

    def _shell_alive(self, timeout: float = 8.0) -> bool:
        """shell 通道是否真的能用（不是只看 `adb devices` 的 device 字样）。"""
        proc = _run([self.adb_path, "-s", self.serial, "shell", "echo", "ok"],
                    timeout)
        if proc is None or proc.returncode != 0:
            return False
        return "ok" in _text(proc.stdout).lower()

    def _prop_via(self, serial: str, key: str, timeout: float = 8.0) -> str:
        proc = _run([self.adb_path, "-s", serial, "shell", "getprop", key],
                    timeout)
        if proc is None or proc.returncode != 0:
            return ""
        return _text(proc.stdout).strip()

    def _known_serial(self) -> str:
        """本机已知的硬件序列号（用来确认"同机"）。读不到返回空串。"""
        got = self._prop_via(self.serial, "ro.serialno")
        if got:
            self._cached_serialno = got
            return got
        return getattr(self, "_cached_serialno", "") or ""

    def push(self, local: str, remote: str, timeout=None) -> bool:
        """把本地文件推到设备。**返回是否真推成功**。

        为什么单独有这个方法：`as_root()` 要把脚本写到设备上再执行
        （Windows 上 `sh -c "... | ... > ..."` 的管道和重定向会被本地
        shell 吃掉，命令根本到不了设备）。以前它靠 `hasattr(dev, "push")`
        兜圈子，而 `AdbDevice` 其实**没有** push，于是每次都走 subprocess
        兜底分支——那个分支**不看返回码就认定成功**（又一处假成功）。

        adb 掉线时走 MuMu root shell 兜底（base64 落盘），否则
        `as_root()` 整条失效、身份写入全盘归零。
        """
        proc = _run(self._base() + ["push", str(local), str(remote)],
                    timeout or self.timeout)
        if proc is None:
            self.last_error = "push timeout or spawn failure"
            return self._push_mumu(local, remote)
        out = _text(proc.stdout) + _text(proc.stderr)
        if proc.returncode != 0:
            low = out.lower()
            self.last_error = next(
                (m for m in _OFFLINE_MARKS if m in low),
                out.strip()[:200] or "rc=%d" % proc.returncode)
            return self._push_mumu(local, remote)
        # adb 某些版本 push 失败也返回 0，所以还要看输出里有没有 "error"
        if "error" in out.lower() and "files pushed" not in out.lower():
            self.last_error = out.strip()[:200]
            return self._push_mumu(local, remote)
        return True

    def _push_mumu(self, local: str, remote: str) -> bool:
        """通过 MuMu root shell 写文件（base64），adb 不可用时的兜底。"""
        import base64
        if not self.mumu_available():
            return False
        try:
            with open(local, "rb") as fh:
                raw = fh.read()
        except OSError:
            return False
        b64 = base64.b64encode(raw).decode("ascii")
        # 单条命令：base64 无 shell 元字符，不会再遇到"引号被吃"
        out = self.mumu_sh("echo %s | base64 -d > %s && echo TMPUSH_OK"
                           % (b64, str(remote)),
                           timeout=max(self.timeout, 60))
        if "TMPUSH_OK" in str(out or ""):
            self._prefer_mumu = True
            self.last_error = ""
            return True
        return False

    def pull(self, remote: str, local: str, timeout=None) -> bool:
        """从设备取文件到本地。返回是否真取到。"""
        proc = _run(self._base() + ["pull", str(remote), str(local)],
                    timeout or self.timeout)
        if proc is None:
            self.last_error = "pull timeout or spawn failure"
            return False
        return proc.returncode == 0 and bool((self._sh("shell", "ls", remote)
                                              or "").strip())

    def run_script(self, script: str, timeout=None) -> str:
        """在设备上执行一段**带 shell 元字符**的脚本（`$()`、`|`、`>`、`&&`…）。

        唯一正确姿势是把整条脚本作为**单个 argv** 交给 `adb shell`：

            adb -s <serial> shell "f=$(ls -t /d | head -1); head -1 /d/$f"

        **不要写成三段 argv**（`shell` / `sh` / `-c` / 脚本 分四个参数）：adb 会把
        `shell sh -c <script>` 用空格拼成一条命令交给设备 shell 重新解析，
        于是内层实际只拿到 `sh -c <第一个词>`，后面的部分被外层吃掉 →
        命令静默失败（实测写文件写出 0 字节、ANR 探针恒返回空串、
        `test -e` 探针恒返回 NO）。这个坑在今天修掉了 6 处。
        """
        return self._sh("shell", str(script or ""), timeout=timeout) or ""

    def connect(self) -> bool:
        proc = _run([self.adb_path, "connect", self.serial], self.timeout)
        if proc is None:
            self.last_error = "connect spawn failure"
            return False
        return "connected" in _text(proc.stdout).lower()

    def _devices_map(self, timeout=None) -> dict:
        """`adb devices` → {serial: state}。解析只保留一份实现。"""
        proc = _run([self.adb_path, "devices"], timeout or self.timeout)
        if proc is None:
            return {}
        out = {}
        for line in _text(proc.stdout).splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2:
                out[parts[0]] = parts[1]
        return out

    def state(self, timeout=None) -> str:
        """该 serial 在 `adb devices` 里的状态：device/offline/unauthorized/absent。

        **为什么要区分**（2026-11-04 血泪）：`offline` 绝大多数是
        **adb 端点问题**，不是 Android 挂了——
        * `adb root` 会重启 adbd，TCP 会话被打断；
        * `adb kill-server` 直接清掉本地侧握手；
        * MuMu 同一实例还会有第二个端点（`emulator-5554`），
          它显示 `device` 而 TCP 端点显示 `offline`，就是端点问题无疑。

        我前两轮把这种 offline 归因成"我 `--delete` 了 `ro.adb.secure`
        / 热改了 `ro.product.*` 把系统搞挂了"，于是去做**重启实例**这种重操作
        ——实际只需 `kill-server` + `connect` 九秒就好。
        **误诊比故障更贵**：它让人去修一个不存在的问题，还顺手制造新的。
        """
        return self._devices_map(timeout).get(self.serial, "absent")

    def disconnect(self, timeout=None) -> bool:
        """断开本地侧的 TCP 挂接（不动设备）。"""
        return _run([self.adb_path, "disconnect", self.serial],
                    timeout or self.timeout) is not None

    def restart_server(self, timeout=None) -> bool:
        """`kill-server` + `start-server`：清掉 adb **本地**的坏状态。

        为什么需要：adb server 缓存了设备握手信息，握手坏了之后
        单纯 `adb connect` 会一直返回 already connected 却仍是 offline。
        """
        _run([self.adb_path, "kill-server"], timeout or self.timeout)
        return _run([self.adb_path, "start-server"],
                    timeout or self.timeout) is not None

    def reconnect(self, logger=None, settle_s: float = 2.0) -> str:
        """**逐级**恢复 adb 端点，返回最终状态字符串（含 `recovered` 前缀时
        表示是恢复成功的）。

        阶梯（从轻到重，能在上一级好起来就不做下一级）：

        1. `connect`：MuMu 首次查询时会话可能还没建立（原有行为）；
        2. `disconnect` + `connect`：清掉本地侧的僵尸挂接；
        3. `kill-server` + `start-server` + `connect`：清掉 **adb server
           自己缓存的坏握手**——这一步是这次真正需要的，
           单纯 1/2 在 server 状态坏掉时会一直"已连接但 offline"。

        为什么要有这个方法（2026-11-04）：我把 adb 端点的 offline
        误判成"Android 被我改挂了"，去重启了整个实例，白白丢了
        一轮采集。端点问题和系统问题**必须先分辨再处置**。
        """
        import time as _t
        if self.online():
            return "device"
        st = self.state()
        # 1) 直接 connect
        self.connect()
        _t.sleep(settle_s)
        if self.online():
            if logger:
                logger.info("[adb] %s 由 %s 恢复（connect）", self.serial, st)
            return "recovered:connect"
        # 2) disconnect 再 connect
        self.disconnect()
        _t.sleep(1.0)
        self.connect()
        _t.sleep(settle_s)
        if self.online():
            if logger:
                logger.info("[adb] %s 由 %s 恢复（disconnect+connect）",
                            self.serial, st)
            return "recovered:rehandshake"
        # 3) 重启本地 adb server
        self.restart_server()
        _t.sleep(settle_s)
        self.connect()
        _t.sleep(settle_s)
        if self.online():
            if logger:
                logger.warning("[adb] %s 由 %s 恢复（重启本地 adb server）——"
                               "这是端点问题，不是设备故障", self.serial, st)
            return "recovered:server"
        return self.state()


    def online(self) -> bool:
        """`adb devices` 里该 serial 处于 device 态。"""
        out = _text((_run([self.adb_path, "devices"], self.timeout)
                     or type("X", (), {"stdout": b""})()).stdout)
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[0] == self.serial:
                return parts[1] == "device"
        return False

    def prop(self, key: str) -> str:
        return (_self_out(self._sh("shell", "getprop", str(key))) or "").strip()

    # ---------- 观测 ----------
    def dump(self, retries: int = 2) -> str:
        """UI 层级 XML；拿不到返回空串（不缓存上一轮结果）。

        必须校验**新鲜度与归属**。实测（MuMu Android 12）两种失效：
          ① `/sdcard/tm_ui.xml` 属 media_rw，shell 删不掉，旧文件一直在；
          ② uiautomator 服务卡死时照样打印 "dumped to"，但文件是 0 字节
             或未被改写。
        两种情况下读到的都是**上一屏**——按它点击等于在旧界面上盲操作，
        比拿不到更危险。所以这里写到 shell 自己可写的 /data/local/tmp，
        并且要求「文件存在 + 大小 > 0 + 内容带 <hierarchy>」，连续失败
        就重启 uiautomator 再试一次。
        """
        # r1063 T80：**先试 u2**——实测同样一屏，CLI 2.1–3.1s、u2 0.54s（复用连接后
        # 0.2–0.3s）。一次采集要取树 5–6 次，这是整轮最大的固定成本。
        # u2 不可用（没装/服务坏）就本会话不再试，直接走下面的 CLI 老路径。
        if getattr(self, "_u2_first", True) and not self._prefer_u2:
            xml = self.dump_u2()
            if xml and "<hierarchy" in xml:
                return xml
            self._u2_first = False
        for attempt in range(retries + 1):
            # u2 的 UiAutomation 服务已注册时，CLI 每次都会以
            # 「already registered」崩掉；继续跑 CLI 只会在 logcat 里刷
            # FATAL，还可能把 u2 服务一起 pkill 掉。一旦确认这种状态，
            # 本进程后续直接走 u2。
            if self._prefer_u2:
                xml = self.dump_u2()
                if xml:
                    return xml
                self._prefer_u2 = False
            self._sh("shell", "rm", "-f", _DUMP_TMP_PATH)
            out = self._sh("shell", "uiautomator", "dump", _DUMP_TMP_PATH,
                           timeout=max(self.timeout, 60)) or ""
            if "dumped to" in out:
                xml = self._sh("shell", "cat", _DUMP_TMP_PATH) or ""
                if "<hierarchy" in xml:
                    return xml
            # 动画页（WebView）的 CLI dump 会直接报 idle 状态拿不到；立刻走
            # u2 回退，别再重试/pkill（实测重试+等待要 37s，u2 只要 0.3s）。
            low = ((out or "") + " " + (self.last_error or "")).lower()
            if "idle state" in low or "already registered" in low:
                xml = self.dump_u2()
                if xml:
                    if "already registered" in low:
                        self._prefer_u2 = True
                    return xml
                if "already registered" in low:
                    # 注册者可能就是 u2 自己的服务：pkill 会把回退也杀掉
                    break
            # 卡死自愈：pkill 掉僵住的 uiautomator，下一轮重新拉服务
            if attempt < retries:
                self._sh("shell", "pkill", "-f", "uiautomator")
                time.sleep(1.0)
        # CLI dump 在「持续动画的 WebView」上会报 could not get idle state；
        # uiautomator2 的 dump 不等 idle，能读到同程结果页的完整文本。
        # 它是**可选回退**：未安装时静默返回空，不改变既有依赖。
        xml = self.dump_u2()
        if xml:
            return xml
        if not self.last_error:
            self.last_error = "dump failed"
        return ""

    def _u2_device(self):
        """懒建并**复用** u2 连接（r1063 T80）。

        实测：每次 `u2.connect()` + `dump_hierarchy()` = 0.54s，其中连接占大头。
        复用连接后单次取树约 0.2–0.3s——一次采集要 dump 5–6 次，省下的
        正好是整轮最容易白花的那十几秒。
        """
        dev = getattr(self, "_u2_conn", None)
        if dev is not None:
            return dev
        import uiautomator2 as u2  # type: ignore
        self._u2_conn = u2.connect(self.serial)
        return self._u2_conn

    def dump_u2(self) -> str:
        """可选：用 uiautomator2 取层级（WebView 动画页的 CLI dump 会卡 idle）。"""
        try:
            dev = self._u2_device()
            xml = dev.dump_hierarchy() or ""
        except Exception as e:
            # 连接坏了就丢掉缓存的连接，下一轮重建
            self._u2_conn = None
            self.last_error = "u2 dump: %s" % str(e)[:120]
            return ""
        if "<hierarchy" not in xml:
            self.last_error = "u2 dump: no hierarchy"
            return ""
        return xml

    def screencap(self) -> bytes:
        """PNG 字节流；失败返回 b""。

        adb 掉线时走 MuMu root shell 兜底：设备端落盘 → base64 → 解码。
        比 adb 慢（多两次进程 + base64 33% 膨胀），但**通道坏了还能截**，
        滑块的缺口识别完全依赖截图，不能因为一条通道废掉就整轮归零。
        """
        if not self.adb_path:
            return self._screencap_mumu()
        proc = _run([self.adb_path, "-s", self.serial,
                     "exec-out", "screencap", "-p"],
                    max(self.timeout, 30))
        if proc is None or proc.returncode != 0:
            self.last_error = "screencap failed"
            return self._screencap_mumu()
        data = proc.stdout or b""
        if not data.startswith(b"\x89PNG"):
            self.last_error = "screencap returned non-png"
            return self._screencap_mumu()
        return data

    def _screencap_mumu(self) -> bytes:
        """MuMu root shell 兜底截图（设备端 base64 → 本地解码）。"""
        import base64
        if not self.mumu_available():
            return b""
        path = "/data/local/tmp/tm_cap.png"
        out = self.mumu_sh("screencap -p %s >/dev/null 2>&1; "
                           "base64 %s" % (path, path),
                           timeout=max(self.timeout, 60))
        txt = "".join(str(out or "").split())
        if not txt:
            return b""
        try:
            data = base64.b64decode(txt)
        except Exception:
            return b""
        if not data.startswith(b"\x89PNG"):
            return b""
        self._prefer_mumu = True
        self.last_error = ""
        return data

    def current_activity(self) -> str:
        out = self._sh("shell", "dumpsys", "activity", "activities",
                       timeout=max(self.timeout, 30)) or ""
        m = re.search(r"topResumedActivity=ActivityRecord\{\S+ \S+ (\S+?)\s",
                      out)
        if m:
            return m.group(1)
        m = re.search(r"mResumedActivity.*? (\S+/\S+)", out)
        return m.group(1) if m else ""

    # ---------- 交互 ----------
    def set_design(self, width, height) -> tuple:
        """开启「设计坐标系 → 设备坐标系」换算；``(0,0)/None`` = 关闭。

        什么时候需要：``display.spoof()`` 改过 ``wm size`` 之后。这时脚本里
        **写死的常量**是设计坐标（按 900×1600 写的），而点击要的是设备坐标。
        不改屏幕就别开这个——开了会给每条坐标多乘一个比例。
        """
        try:
            w, h = int(width or 0), int(height or 0)
        except (TypeError, ValueError):
            w = h = 0
        self.design = (w, h) if (w > 0 and h > 0) else None
        self._size_cache = None
        return self.design

    def _scale(self) -> tuple:
        """(sx, sy)：设备像素 / 设计像素。读不到真实尺寸时退回 1.0。"""
        if not self.design:
            return (1.0, 1.0)
        if self._size_cache is None:
            try:
                self._size_cache = self.window_size() or (0, 0)
            except Exception:
                self._size_cache = (0, 0)
        w, h = self._size_cache
        dw, dh = self.design
        if min(int(w), int(h), int(dw), int(dh)) <= 0:
            return (1.0, 1.0)
        return (w / float(dw), h / float(dh))

    def to_device(self, x, y) -> tuple:
        """设计坐标 → 设备坐标（未开启换算时原样返回）。"""
        sx, sy = self._scale()
        return int(round(float(x) * sx)), int(round(float(y) * sy))

    def to_design(self, x, y) -> tuple:
        """设备坐标 → 设计坐标：UI 树 ``bounds`` 读出来的点要走这一层，
        再与写死的设计坐标比较/运算，否则会算错两倍。"""
        sx, sy = self._scale()
        return (int(round(float(x) / sx)),
                int(round(float(y) / sy)))

    # r1226（重放）：设计基准(900×1600) → 设备像素换算，只给写死坐标的调用点用
    def _design_scale(self) -> tuple:
        try:
            w, h = self.window_size() or (0, 0)
        except Exception:
            w, h = 0, 0
        dw, dh = DESIGN_BASIS
        if min(int(w or 0), int(h or 0)) <= 0:
            return (1.0, 1.0)
        return (w / float(dw), h / float(dh))

    def design_to_device(self, x, y) -> tuple:
        sx, sy = self._design_scale()
        return int(round(float(x) * sx)), int(round(float(y) * sy))

    def tap_design(self, x: int, y: int) -> bool:
        dx, dy = self.design_to_device(x, y)
        if not self._coord_ok(dx) or not self._coord_ok(dy):
            return False
        return self._sh("shell", "input", "tap", str(dx), str(dy)) is not None

    def swipe_design(self, x1: int, y1: int, x2: int, y2: int,
                     duration_ms: int = 300) -> bool:
        ax, ay = self.design_to_device(x1, y1)
        bx, by = self.design_to_device(x2, y2)
        if not all(self._coord_ok(v) for v in (ax, ay, bx, by)):
            return False
        return self._sh("shell", "input", "swipe", str(ax), str(ay),
                        str(bx), str(by), str(int(duration_ms))) is not None

    def tap(self, x: int, y: int) -> bool:
        if not self._coord_ok(x) or not self._coord_ok(y):
            return False
        dx, dy = self.to_device(x, y)
        out = self._sh("shell", "input", "tap", str(dx), str(dy))
        return out is not None

    def swipe(self, x1: int, y1: int, x2: int, y2: int,
              duration_ms: int = 300) -> bool:
        if not all(self._coord_ok(v) for v in (x1, y1, x2, y2)):
            return False
        ax, ay = self.to_device(x1, y1)
        bx, by = self.to_device(x2, y2)
        out = self._sh("shell", "input", "swipe",
                       str(ax), str(ay), str(bx), str(by),
                       str(int(duration_ms)))
        return out is not None

    def getprop(self, key: str) -> str:
        """读一个系统属性（读不到返回空串，不抛）。"""
        try:
            out = self._sh("shell", "getprop", str(key))
        except Exception:
            return ""
        return str(out or "").strip()

    def u2_swipe_points(self, points, duration: float = 1.0) -> bool:
        """按**多段轨迹**做一次手势（r1063 T81：滑块自动用）。

        为什么不用 `input swipe`：那是单段等速直线，阿里 NC 会直接判机器
        （真机回报 `请点我重试(error:x2VW8)`）。u2 的 `swipe_points` 能把
        我们生成的变速轨迹一次性下发，更接近人手。
        """
        pts = [(int(x), int(y)) for x, y in (points or [])]
        if len(pts) < 2:
            return False
        try:
            dev = self._u2_device()
            mv = getattr(dev, "swipe_points", None)
            if not callable(mv):
                return False
            mv(pts, float(duration or 1.0))
            return True
        except Exception as e:
            self._u2_conn = None
            self.last_error = "u2 swipe: %s" % str(e)[:120]
            return False

    def input_text(self, text: str) -> bool:
        """输入文本。空格转 %s（input text 的约定），并做 shell 转义。

        **必须校验文本真的进了界面**（r805ab 真机实测）：`adb shell input
        text` 在没有聚焦输入框时**同样是返回成功**——命令发出去了，字却
        掉在地上。内嵌画面此前只判「命令没报错」，于是用户点「输入文字」
        后接口回 ok、画面一动不动（真机：城市页输入 "bei"，前后两帧 sha1
        完全相同、视图树文本零变化）。

        这里输入后读一次视图树，确认目标文本真的出现；读不到（或无焦点
        导致没进去）就如实返回 False——调用方据此提示「请先点一下输入框」，
        而不是让用户对着一个撒谎的 ok 发呆。
        """
        if text is None:
            return False
        s = str(text)
        payload = s.replace(" ", "%s")
        out = self._sh("shell", "input", "text",
                       shlex.quote(payload))
        if out is None:
            return False
        # 校验：视图树里要出现该文本（去空格后比对，容忍输入法与转义差异）
        want = s.replace(" ", "").strip()
        if not want:
            return True
        try:
            page = self.dump() or ""
        except Exception:
            return True      # 读不到页面时不否决（dump 自身可能超时）
        return want in page.replace(" ", "")

    def keyevent(self, key: str) -> bool:
        out = self._sh("shell", "input", "keyevent", str(key))
        return out is not None

    # ---------- App ----------
    def lock_portrait(self) -> bool:
        """锁定竖屏（关自动旋转 + user_rotation=0）。

        采集脚本的元素坐标与滑动距离都按 900×1600 竖屏写。现场实证
        （2026-11-01 18:30）：模拟器 `accelerometer_rotation=1`，某一轮 App
        转成 **1600×900 横屏**——首页控件都在，但硬编码的
        `swipe(800,1200,…,600)` 的 y 已超出 900 屏高，整轮点不动，账本只记
        `set-city-dep`，人眼看是「这条通路时好时坏」。
        失败不影响采集（下一轮会再锁）。
        """
        ok = True
        for cmd in (("shell", "settings", "put", "system",
                     "accelerometer_rotation", "0"),
                    ("shell", "settings", "put", "system",
                     "user_rotation", "0")):
            if self._sh(*cmd) is None:
                ok = False
        return ok

    def app_start(self, pkg: str) -> bool:
        out = self._sh("shell", "monkey", "-p", pkg,
                       "-c", "android.intent.category.LAUNCHER", "1",
                       timeout=max(self.timeout, 60))
        if out is None:
            return False
        return "Events injected" in out or "No activities found" not in out

    def app_stop(self, pkg: str) -> bool:
        out = self._sh("shell", "am", "force-stop", pkg)
        return out is not None

    def deep_link(self, uri: str) -> bool:
        """用 scheme 深链启动 App 的目标页。

        有些 App 的首屏是强制登录页，但深链能直达功能页（去哪儿实测：
        首屏 UCLoginByPhoneActivity，qunarphone://flight 直接进机票首页）。
        失败返回 False，调用方回落到 app_start。
        """
        out = self._sh("shell", "am", "start", "-a",
                       "android.intent.action.VIEW", "-d", uri,
                       timeout=max(self.timeout, 60))
        if out is None:
            return False
        low = out.lower()
        return "error" not in low and "unable to resolve" not in low

    def start_component(self, component: str) -> bool:
        """用显式 `pkg/activity` 启动页面（App 没有可用深链时的入口）。

        携程 App 实测：`ctrip.business.planthome.CtripPlantHomeActivity`
        可以显式拉起机票查询页；没有可解析的 scheme 深链。
        """
        if not component or "/" not in component:
            return False
        out = self._sh("shell", "am", "start", "-n", component,
                       timeout=max(self.timeout, 60))
        if out is None:
            return False
        low = out.lower()
        return "error" not in low and "unable to resolve" not in low

    def app_installed(self, pkg: str) -> bool:
        out = self._sh("shell", "pm", "list", "packages") or ""
        return any(line.strip() == f"package:{pkg}"
                   for line in out.splitlines())

    def window_size(self) -> tuple:
        """当前**生效的**屏幕 (w, h)；解析失败返回 (0, 0)。

        ⚠ 必须优先取 ``Override size``：``wm size`` 的输出有两行
        （``Physical size: 900x1600`` + ``Override size: 1080x1920``），
        取第一个匹配会永远拿到**物理**尺寸——屏幕被 ``wm size`` 改过之后，
        坐标换算比例就恒等于 1.0，写死的坐标会按比例全偏，而账本上只表现成
        「设城市失败 / 页面认不出」，极难追（2026-11-03 实机验证时踩到）。
        """
        out = self._sh("shell", "wm", "size") or ""
        m = re.search(r"Override size:\s*(\d+)x(\d+)", out)
        if not m:
            m = re.search(r"Physical size:\s*(\d+)x(\d+)", out)
        if not m:
            m = re.search(r"(\d+)\s*x\s*(\d+)", out)
        return (int(m.group(1)), int(m.group(2))) if m else (0, 0)

    def root(self) -> bool:
        """切 adbd 为 root（MuMu 支持；失败也不致命）。"""
        self._sh("root", timeout=max(self.timeout, 30))
        time.sleep(1.5)
        out = self._sh("shell", "id") or ""
        return "uid=0" in out

    # ---------- 内部 ----------
    @staticmethod
    def _coord_ok(v) -> bool:
        try:
            return int(v) >= 0
        except (TypeError, ValueError):
            return False


DESIGN_BASIS = (900, 1600)


def _self_out(value):
    return value if value is not None else ""
