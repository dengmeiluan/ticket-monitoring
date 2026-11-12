"""上线抽查（r1063 T100）：`python -m core.live_check`

为什么要它：`webui.py` 是 4.9MB 单文件、多人并行编辑的热点。**代码里有**不等于
**线上有**——本会话就发生过两次：并行会话整段重写后，我加的面板接线在工作树里
静默消失（代码看着还在 HEAD，实例跑的却是被覆盖的版本）。

所以给一条"点一下就知道线上对不对"的命令，检查**运行中实例**的关键能力：

```
python -m core.live_check            # 抽查本机 8765
python -m core.live_check --port 8000 --json
```

判据（任何一条不满足就退出码 1）：
1. 版本与源码一致（跑旧发行版会被点名）；
2. 登录槽位 = 9 格，且 PC 槽不指向移动域；
3. `/api/pacing` 渠道对象带 `session`（可用窗口）；
4. 通路读数带 `why`（失败原因原文）；
5. 降级账本可读（哪怕为空，字段要在）。
"""
from __future__ import annotations

import json
import urllib.request

DEFAULT_PORTS = (8765, 8000, 5000)


def _get(base: str, path: str, timeout: float = 20.0) -> dict:
    with urllib.request.urlopen(base + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


def source_version() -> str:
    try:
        import io
        import os
        import re
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        txt = io.open(os.path.join(root, "main.py"), encoding="utf-8").read()
        m = re.search(r'__version__\s*=\s*"([^"]+)"', txt)
        return m.group(1) if m else ""
    except Exception:
        return ""


def check(port: int = 0) -> dict:
    """抽查一台实例。返回 {ok, port, version, problems[], detail{}}。"""
    src = source_version()
    ports = [port] if port else list(DEFAULT_PORTS)
    last_err = ""
    for p in ports:
        base = "http://127.0.0.1:%d" % p
        try:
            st = _get(base, "/api/state", timeout=4)
        except Exception as e:
            last_err = "%s: %s" % (type(e).__name__, str(e)[:60])
            continue
        out = {"ok": True, "port": p, "version": st.get("version"),
               "source_version": src, "problems": [], "detail": {}}
        if src and str(st.get("version")) != src:
            out["problems"].append(
                "版本不一致：线上 %s / 源码 %s（改进未生效）"
                % (st.get("version"), src))
        # ① 槽位
        try:
            ls = _get(base, "/api/login-state")
            slots = ls.get("slots") or {}
            out["detail"]["slots"] = len(slots)
            if len(slots) != 9:
                out["problems"].append("登录槽位 %d 格（应为 9）" % len(slots))
            for key, s in slots.items():
                url = str((s or {}).get("login_url") or "")
                if (s or {}).get("surface_label") == "PC" and "://m." in url:
                    out["problems"].append("%s 是 PC 槽却指向移动域：%s"
                                           % (key, url[:40]))
        except Exception as e:
            out["problems"].append("登录槽位读取失败：%s" % type(e).__name__)
        # ② pacing 字段
        try:
            pc = _get(base, "/api/pacing")
            ch = pc.get("channels") or {}
            with_session = [k for k, v in ch.items()
                            if isinstance(v, dict) and "session" in v]
            why = sum(1 for v in ch.values() if isinstance(v, dict)
                      for pv in ((v.get("paths") or {})).values()
                      if isinstance(pv, dict) and pv.get("why"))
            out["detail"]["channels"] = len(ch)
            out["detail"]["with_session"] = len(with_session)
            out["detail"]["why_rows"] = why
            out["detail"]["degraded"] = list((pc.get("degraded") or {}).keys())
            if ch and not with_session:
                out["problems"].append(
                    "渠道对象没有 session 字段（可用窗口接线被覆盖了？）")
            if ch and not why:
                out["problems"].append(
                    "通路读数没有 why 字段（原因接线被覆盖了？）")
        except Exception as e:
            out["problems"].append("pacing 读取失败：%s" % type(e).__name__)
        out["ok"] = not out["problems"]
        return out
    return {"ok": False, "port": 0, "problems": ["连不上实例：" + last_err],
            "detail": {}}


def _main(argv=None):                          # pragma: no cover - CLI
    import sys

    argv = list(sys.argv[1:] if argv is None else argv)
    port = 0
    for i, a in enumerate(argv):
        if a == "--port" and i + 1 < len(argv):
            port = int(argv[i + 1])
    rep = check(port)
    if "--json" in argv:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        if not rep.get("port"):
            print("✗", rep["problems"][0] if rep.get("problems") else "连不上")
            return 1
        print("实例 : 127.0.0.1:%s（版本 %s，源码 %s）"
              % (rep["port"], rep.get("version"), rep.get("source_version")))
        d = rep.get("detail") or {}
        print("槽位 : %s 格 | 渠道 %s 个 | 带 session %s 个 | 带 why %s 条"
              % (d.get("slots"), d.get("channels"), d.get("with_session"),
                 d.get("why_rows")))
        print("降级 : %s" % (", ".join(d.get("degraded") or []) or "（空）"))
        if rep["ok"]:
            print("结论 : ✓ 线上能力齐全")
        else:
            print("结论 : ✗ 有问题")
            for p in rep["problems"]:
                print("   -", p)
    return 0 if rep.get("ok") else 1


if __name__ == "__main__":                     # pragma: no cover
    raise SystemExit(_main())
