# -*- coding: utf-8 -*-
"""携程 App 登录助手：填手机号 → 你给短信码 → 自动过拼图 → 完成登录。

为什么需要它（2026-11-04 实测背景）
----------------------------------
携程 App 的登录流程是：

    手机号 → 获取验证码（**短信能正常下发**）→ 填码 → 弹「请完成拼图验证」
    → 拖对了才登录成功

其中只有**短信码**需要人（在手机上），其它步骤都可以自动化。所以本脚本
的设计是"人只给一个码，剩下全自动"：

    python scripts/ctrip_login.py --phone 19989828573 --code 123456

它做的事：

1. 启动 App → 进「我的」→「登录/注册」；
2. 填手机号、点「获取验证码」（如尚未发送）；
3. 点「同意并登录」；
4. 若出现「请完成拼图验证」→ **自动算缺口 + 拟人轨迹拖动**；
5. 核对是否登录成功（离开登录页且「我的」不再显示"登录携程"）。

拼图这一关的可靠性：

* 分级：`请完成拼图验证` 现在判成 **simple**（可解），`geetest/天御/极验`
  仍是 **strong**（一律不碰）——边界没破；
* 缺口：`slider.find_gap` 已校准（排除拼图块自身），实测携程真实截图
  两种独立方法都指向 x≈304；
* 拖动：`slider.trajectory` 生成 S 曲线 + 回拉 + 落点修正的拟人增量。

用法：
    python scripts/ctrip_login.py --code 123456
    python scripts/ctrip_login.py --code 123456 --phone 19989828573
    python scripts/ctrip_login.py --send-only      # 只发码，不填（先拿码）
    python scripts/ctrip_login.py --check          # 只看当前登录态
"""
from __future__ import annotations

import argparse
import os
import random
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PKG = "ctrip.android.view"
_ADB_CANDIDATES = (
    r"D:\Program Files\Netease\MuMu\nx_main\adb.exe",
    r"D:\Program Files\Netease\MuMu\emulator\nemu\adb.exe",
    "adb",
)


def _adb() -> str:
    env = os.environ.get("TM_ADB")
    if env:
        return env
    for p in _ADB_CANDIDATES:
        if p == "adb" or os.path.isfile(p):
            return p
    return "adb"


def _dev():
    from core.android.device import AdbDevice
    return AdbDevice(_adb(), os.environ.get("TM_SERIAL", "127.0.0.1:16384"))


def _nodes(xml: str):
    """[(text, rid, cls, x1, y1, x2, y2)]——够用即可，不引第三方。"""
    out = []
    for m in re.finditer(r"<node[^>]*>", xml or ""):
        tag = m.group(0)
        t = re.search(r'text="([^"]*)"', tag)
        rid = re.search(r'resource-id="([^"]*)"', tag)
        c = re.search(r'class="([^"]*)"', tag)
        b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
        if not b:
            continue
        out.append(((t.group(1) if t else "").strip(),
                    (rid.group(1) if rid else ""),
                    (c.group(1) if c else ""),
                    int(b.group(1)), int(b.group(2)),
                    int(b.group(3)), int(b.group(4))))
    return out


def _tap_text(dev, xml, text, *, exact=True) -> bool:
    for t, _rid, _c, x1, y1, x2, y2 in _nodes(xml):
        if (t == text) if exact else (text in t):
            dev.tap((x1 + x2) // 2, (y1 + y2) // 2)
            return True
    return False


def _tap_edit(dev, xml) -> bool:
    """点第一个输入框（手机号/验证码共用）。"""
    for t, _rid, c, x1, y1, x2, y2 in _nodes(xml):
        if "EditText" in c:
            dev.tap((x1 + x2) // 2, (y1 + y2) // 2)
            return True
    return False


# 判据要三态，不能两态。
#
# 旧实现是 `-> bool`，最后一行等价于"没看到登录入口**并且**没看到
# 全部订单/我的钱包 ⇒ 未登录"。可这两种情况被压成了同一个答案：
#   ① 真的未登录；
#   ② **页面根本没认出来**——冷启动闪屏、开屏广告、还在加载、
#      风控页、或者压根没切到「我的」tab（`_tap_text("我的")` 时有时无）。
# 实测后果就是同一个未变化的设备状态，`--check` 一次报"已登录"、
# 连测三次报"未登录"：读数在跟**瞬时 UI** 走，而不是跟登录态走。
# 而"未登录"这个字会直接把人推去重登——**多余的重新登录恰恰是本项目
# 要减少的东西**，所以误报比无报更糟。
def _front_pkg(dev) -> str:
    """当前前台包名；读不到返回空串（**不把"读不到"当成"不是携程"**）。"""
    try:
        act = str(dev.current_activity() or "")
    except Exception:
        return ""
    return act.split("/")[0].strip()


def _ensure_front(dev, wait_s: float = 3.0) -> bool:
    """把携程切到前台；返回"前台确实是携程"。

    为什么必须有（2026-11-05 00:19 实测）：`--check` 原先直接 `dev.dump()`，
    于是它读的是**上一渠道留在前台的那个 App**（当次是智行，dump 里只有
    `智行 / 10` 两个文本节点），却照样给出"携程未登录"的结论。
    `pidof` 有进程 ≠ 在前台 —— 这两件事以前被混为一谈。
    同一台设备、登录态没变，连测却得到一次"已登录" + 三次"未登录"：
    **读数在跟瞬时前台走，不跟登录态走。**

    与 `crawlers/app_base._ensure_own_app`（2026-11-02 为解决
    "智行照着去哪儿首页解析"而加）同一手法：`current_activity()` 比对包名
    → 不对就 `app_start()` → 再校验。不另造第二套前台判据，否则迟早漂移。
    """
    if _front_pkg(dev) == PKG:
        return True
    try:
        dev.app_start(PKG)
    except Exception:
        return False
    time.sleep(max(1.0, wait_s))
    # 读不到包名时不谎报到位：宁可让调用方判 unknown
    return _front_pkg(dev) == PKG


_LOGGED_IN_MARKS = ("全部订单", "我的钱包", "订单", "优惠券", "会员")
_LOGGED_OUT_MARKS = ("登录携程", "登录/注册", "手机验证码登录", "立即登录")


def login_state(dev) -> str:
    """返回 ``"in" | "out" | "unknown"``。

    `unknown` 是**必须存在**的第三种答案：看不见 ≠ 没登录。
    判据顺序：先认"未登录"标志（登录入口是最强证据），再认"已登录"标志，
    两个都没命中就是 unknown，交给调用方决定重试还是问人。
    """
    # **先确认看的是携程**：切不到前台就绝不给结论。
    # 拿别的 App 的界面判携程登录态，比"不知道"危险得多——
    # "未登录"这个字会让人去做一次本不需要的重新登录。
    if not _ensure_front(dev):
        return "unknown"
    xml = dev.dump() or ""
    if _tap_text(dev, xml, "我的"):
        time.sleep(3)
        xml = dev.dump() or ""
    else:
        # 没点到「我的」也继续判：可能本来就在「我的」页
        pass
    if not xml.strip():
        return "unknown"          # dump 拿不到任何东西
    # 切完又跳走（弹窗抢焦点等）：不看内容，直接 unknown
    if _front_pkg(dev) not in ("", PKG):
        return "unknown"
    if any(m in xml for m in _LOGGED_OUT_MARKS):
        return "out"
    if any(m in xml for m in _LOGGED_IN_MARKS):
        return "in"
    return "unknown"


def is_logged_in(dev):
    """兼容旧调用：返回 True/False/**None(=判不出来)**。

    以前这里返回 False 表示"判不出来"，于是"判不出来"和"没登录"在
    调用处不可区分——正是误报重登的成因。返回 None 让调用方必须显式处理。
    """
    st = login_state(dev)
    return None if st == "unknown" else (st == "in")


def goto_login(dev) -> bool:
    """从首页走到登录页。"""
    xml = dev.dump() or ""
    if "手机验证码登录" in xml:
        return True
    _tap_text(dev, xml, "我的")
    time.sleep(3)
    xml = dev.dump() or ""
    if "手机验证码登录" in xml:
        return True
    if not _tap_text(dev, xml, "登录/注册", exact=False):
        return False
    time.sleep(4)
    return "手机验证码登录" in (dev.dump() or "")


def send_code(dev, phone: str) -> bool:
    """填手机号并点「获取验证码」。"""
    xml = dev.dump() or ""
    if "请输入手机号" in xml:
        if not _tap_edit(dev, xml):
            return False
        time.sleep(1)
        dev.input_text(phone)
        time.sleep(1.2)
        xml = dev.dump() or ""
    if not _tap_text(dev, xml, "获取验证码", exact=False):
        return False
    time.sleep(4)
    # 可能弹协议确认
    xml = dev.dump() or ""
    if "同意并登录" in xml:
        _tap_text(dev, xml, "同意并登录")
        time.sleep(4)
    return True


def solve_slider(dev, logger=None, tries: int = 3) -> dict:
    """过拼图滑块。返回 ``{"ok", "detail", "attempts"}``。

    只处理 **simple** 级（`请完成拼图验证` 已入该级）；`strong` 一律不碰。
    """
    from crawlers import slider as _sl
    rep = {"ok": False, "detail": "", "attempts": []}
    xml = dev.dump() or ""
    if "拼图验证" not in xml and "拖动滑块" not in xml:
        rep["ok"] = True
        rep["detail"] = "没有滑块（可能已过）"
        return rep
    tier = _sl.classify("", xml)
    if not tier.solvable:
        rep["detail"] = "分级=%s，不动手" % tier.name
        return rep

    rng = random.Random()
    for i in range(max(1, tries)):
        shot = dev.screencap() or b""
        best, cands = _sl.find_gap(shot)
        rep["attempts"].append({"round": i + 1, "best": best,
                                "cands": cands[:3]})
        if not best:
            rep["detail"] = "没找到缺口"
            return rep
        # 距离由 `attempt_device` 内部自己算（它拿 find_gap 的结果减起始偏移，
        # 并按 `single_shot` 决定试几个候选），这里不重复实现——两处各算一遍
        # 必然漂移。我们只负责"截一张新图、调一次、再看滑块在不在"。
        _sl.attempt_device(dev, "app_ctrip", {"slider": {"auto": "simple"}},
                           tier=tier, logger=logger, rng=rng)
        time.sleep(2.5)
        xml = dev.dump() or ""
        if "拼图验证" not in xml and "拖动滑块" not in xml:
            rep["ok"] = True
            rep["detail"] = "第 %d 次拖动后滑块消失" % (i + 1)
            return rep
    rep["detail"] = "试了 %d 次仍未过" % tries
    return rep


def submit_code(dev, code: str) -> bool:
    """填验证码并提交。"""
    xml = dev.dump() or ""
    if not _tap_edit(dev, xml):
        return False
    time.sleep(0.8)
    dev.input_text(str(code))
    time.sleep(1.2)
    xml = dev.dump() or ""
    # 有的版本要再点一次「登录」/「确定」
    for label in ("登录", "确定", "提交"):
        if _tap_text(dev, xml, label, exact=False):
            break
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="携程 App 登录助手（自动过拼图）")
    ap.add_argument("--phone", default="19989828573")
    ap.add_argument("--code", default="", help="短信验证码")
    ap.add_argument("--send-only", action="store_true", help="只发码")
    ap.add_argument("--check", action="store_true", help="只看登录态")
    args = ap.parse_args()

    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    log = logging.getLogger("ctrip_login")

    dev = _dev()
    try:
        dev.connect()
    except Exception:
        pass

    if args.check:
        st = login_state(dev)
        # 三态各自一句人话：`unknown` 绝不写成"未登录"，
        # 否则人会照着这句话去做一次本不需要的重新登录。
        print({"in": "已登录", "out": "未登录（看到登录入口）",
               "unknown": "无法判定（携程没切到前台，或页面没认出来："
                          "闪屏/广告/加载中）。稍后重试，"
                          "**不要据此重登**"}[st])
        return {"in": 0, "out": 1}.get(st, 2)

    # 1) 确保 App 在前台
    try:
        dev.app_stop(PKG)
    except Exception:
        pass
    time.sleep(2)
    try:
        dev.app_start(PKG)
    except Exception:
        pass
    time.sleep(12)

    # 2) 到登录页
    if not goto_login(dev):
        print("没能进入登录页")
        return 1

    # 3) 发码
    if args.send_only or not args.code:
        send_code(dev, args.phone)
        print("已请求验证码。收到后执行："
              "python scripts/ctrip_login.py --code <验证码>")
        return 0

    # 4) 填码 → 过拼图
    submit_code(dev, args.code)
    time.sleep(3)
    r = solve_slider(dev, logger=log)
    print("滑块:", r["detail"], "| 尝试:", r["attempts"])

    time.sleep(3)
    ok = is_logged_in(dev)
    print("登录结果:", "成功" if ok else "未成功")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
