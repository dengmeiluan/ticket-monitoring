"""App 登录态对账：`python -m core.app_check [--fix]`（r1063 T187）

问题（用户实测）：智行/携程 App **界面已经是登录态**（有「会员 / 积分 /
我的订单」），但面板与采集闸门仍按**过期的登录墙记忆**判「需登录」——
因为墙记忆是 24 小时窗口，而"用户后来登录了"这件事没人告诉它。

本模块只做一件事：**用设备实况对账**——
1. 逐个 App dump 当前界面；
2. 按"已登录标记 vs 登录页标记"判定；
3. `--fix` 时把**确属已登录**的渠道的 `login_wall` 记忆清掉（不动任何账号、不下单、不点广告）。

判定口径（都取真实界面文字，不猜）：
* 已登录：`我的订单 / 全部订单 / 退出登录 / 会员 / 积分 / 我的行程 / 钱包`
* 登录页：`立即登录 / 手机号登录 / 账号登录 / 输入手机号 / 注册`
* 两样都有（首页带"登录"入口是常态）→ 以**已登录标记**优先，但要求登录页标记
  不出现"输入手机号/密码"这类硬证据。

只读判定 + 可选清理记忆；**绝不导出快照**（快照需要 App 内会话，属登录流程）。
"""
from __future__ import annotations

import re

IN_HINTS = ("我的订单", "全部订单", "退出登录", "会员", "积分", "我的行程",
            "钱包", "优惠券", "个人中心", "我的收藏")
LOGIN_HINTS = ("立即登录", "手机号登录", "账号登录", "输入手机号", "密码登录",
               "一键登录", "注册/登录", "登录/注册")
HARD_LOGIN = ("输入手机号", "密码登录", "获取验证码")


def classify(xml: str) -> dict:
    """按界面文字判 App 登录态（只读）。"""
    texts = re.findall(r'text="([^"]{1,60})"', xml or "")
    joined = " | ".join(t for t in texts if t.strip())
    have_in = [k for k in IN_HINTS if k in joined]
    have_login = [k for k in LOGIN_HINTS if k in joined]
    hard = [k for k in HARD_LOGIN if k in joined]
    if not joined:
        state = "empty"
    elif hard:
        state = "login_page"
    elif have_in:
        state = "logged_in"
    elif have_login:
        state = "login_page"
    else:
        state = "unknown"
    return {"state": state, "in_markers": have_in,
            "login_markers": have_login, "hard": hard,
            "len": len(xml or ""), "head": joined[:90]}


def check(dev, pkg: str, wait_s: float = 8.0) -> dict:
    """启动该 App 并 dump 一次，返回分类结果。"""
    import time
    try:
        if hasattr(dev, "app_stop"):
            dev.app_stop(pkg)
    except Exception:
        pass
    time.sleep(1)
    try:
        dev.app_start(pkg)
    except Exception as e:
        return {"state": "error", "err": "%s" % type(e).__name__}
    time.sleep(wait_s)
    try:
        xml = dev.dump() or ""
    except Exception as e:
        return {"state": "error", "err": "%s" % type(e).__name__}
    return classify(xml)


def fix_wall(root: str, plat: str) -> bool:
    """清掉该渠道的登录墙记忆（文件 + service_state）。返回是否清到东西。"""
    import os
    cleared = False
    f = os.path.join(str(root), plat, "login_wall.json")
    try:
        if os.path.isfile(f):
            os.remove(f)
            cleared = True
    except Exception:
        pass
    try:
        from core import service_state as ss
        if ss.until(str(root), plat, "login_wall") > 0:
            ss.clear(str(root), plat, "login_wall")
            cleared = True
    except Exception:
        pass
    return cleared


def main(argv=None):                                     # pragma: no cover
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import yaml
    from core.android import emulator as _emu

    argv = list(sys.argv[1:] if argv is None else argv)
    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8")) or {}
    root = ((cfg.get("crawler") or {}).get("user_data_dir") or "user_data")
    pkgs = {"app_zhixing": "cn.suanya.zhixing", "app_qunar": "com.Qunar",
            "app_fliggy": "com.taobao.trip", "app_ctrip": "ctrip.android.view"}
    dev = _emu.device(cfg)
    if dev is None:
        print("✗ 设备不可用")
        return 1
    print("%-12s %-11s %-28s %s" % ("渠道", "判定", "已登录标记", "登录页标记"))
    fixed = []
    for plat, pkg in pkgs.items():
        r = check(dev, pkg)
        print("%-12s %-11s %-28s %s"
              % (plat, r.get("state", "?"),
                 "、".join(r.get("in_markers") or []) or "-",
                 "、".join(r.get("login_markers") or []) or "-"))
        if "--fix" in argv and r.get("state") == "logged_in":
            if fix_wall(root, plat):
                fixed.append(plat)
    if "--fix" in argv:
        print("\n已清过期登录墙记忆：%s" % ("、".join(fixed) or "（无需清理）"))
    return 0


if __name__ == "__main__":                               # pragma: no cover
    raise SystemExit(main())
