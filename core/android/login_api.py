# -*- coding: utf-8 -*-
"""App 登录的 HTTP 处理逻辑（与服务器解耦，便于单测）。

webui.py 只需在路由里调用 `handle(handler, method, path, body_json)`，
返回 dict 或 (bytes, content_type)；本模块不 import webui，避免循环。

安全约定（对齐既有 /api/login 的边界）：
  * 只服务已注册会话的 plat，未知 plat 一律 400；
  * 点击坐标必须是整数且非负；
  * 文本长度上限 200（验证码/手机号远小于此），防误贴长文本；
  * 不落任何账号内容到日志。
"""
from __future__ import annotations

import json
from typing import Optional, Tuple

from .login_session import ST_ERROR, ST_PENDING, ST_SAVING

MAX_TEXT = 200


def _err(msg: str, code: int = 400):
    return {"ok": False, "err": str(msg)[:200]}, code


def handle_create(registry, plat: str, packages: dict, runtime_factory,
                  logger=None) -> Tuple[dict, int]:
    """POST /api/app-login  {plat} -> 起 App、登记会话。"""
    pkg = (packages or {}).get(plat)
    if not pkg:
        return _err(f"未知渠道 {plat!r}")
    existing = registry.get(plat)
    if existing is not None and existing.alive():
        return {"ok": True, "already": True, "session": existing.view()}, 200

    rt = runtime_factory()
    if rt is None:
        return _err("Android 通道未启用", 409)
    ok, why = rt.ensure_ready()
    if not ok:
        return _err(f"Android 运行时未就绪：{why}", 409)

    dev = rt.device()
    if dev is None or not dev.app_start(pkg):
        return _err("App 启动失败", 502)

    from .login_session import AppLoginSession
    sess = AppLoginSession(plat, rt, pkg, logger=logger)
    try:
        registry.put(sess)
    except ValueError as e:
        return _err(str(e), 409)
    return {"ok": True, "session": sess.view()}, 200


def handle_frame(registry, plat: str) -> Tuple[bytes, int, dict]:
    """GET /api/app-login/frame?plat=x -> (png, http_code, headers)。

    画面未变返回 304，前端复用上一帧——实测每秒 4 帧时这能省掉
    绝大多数带宽（同一屏停留时几乎全是未变）。
    """
    sess = registry.get(plat)
    if sess is None:
        return b"", 404, {"Content-Type": "text/plain"}
    if sess.status not in (ST_PENDING, ST_SAVING):
        return b"", 409, {"Content-Type": "text/plain"}
    png, changed = sess.frame()
    if not png and not changed:
        return b"", 304, {"Cache-Control": "no-store"}
    return png, 200, {"Content-Type": "image/png",
                      "Cache-Control": "no-store"}


def handle_tap(registry, plat: str, body: dict) -> Tuple[dict, int]:
    """POST /api/app-login/tap {plat,x,y}"""
    sess = registry.get(plat)
    if sess is None:
        return _err("没有进行中的登录会话", 409)
    try:
        x = int(body.get("x"))
        y = int(body.get("y"))
    except (TypeError, ValueError):
        return _err("坐标必须是整数")
    if not sess.tap(x, y):
        return {"ok": False, "err": sess.detail or "点击失败"}, 409
    return {"ok": True, "taps": sess.taps}, 200


def handle_input(registry, plat: str, body: dict) -> Tuple[dict, int]:
    """POST /api/app-login/input {plat,text}"""
    sess = registry.get(plat)
    if sess is None:
        return _err("没有进行中的登录会话", 409)
    text = body.get("text")
    if not isinstance(text, str):
        return _err("text 必须是字符串")
    if len(text) > MAX_TEXT:
        return _err(f"文本过长（上限 {MAX_TEXT}）")
    if not sess.input_text(text):
        return {"ok": False, "err": "输入失败"}, 409
    return {"ok": True}, 200


def handle_key(registry, plat: str, body: dict) -> Tuple[dict, int]:
    """POST /api/app-login/key {plat,key}  —— 返回键/删除键等。"""
    sess = registry.get(plat)
    if sess is None:
        return _err("没有进行中的登录会话", 409)
    key = str(body.get("key") or "").strip()
    if not key or len(key) > 40:
        return _err("key 非法")
    if not sess.keyevent(key):
        return {"ok": False, "err": "按键失败"}, 409
    return {"ok": True}, 200


def handle_state(registry, plat: str, snapshot_info=None) -> Tuple[dict, int]:
    """GET /api/app-login/state?plat=x

    没有进行中的会话时也要报出「是否已保存过快照」：否则用户登录完、
    会话结束后，配置页会一直显示「未保存会话」——他刚登好却看到没存上。
    """
    sess = registry.get(plat)
    saved, snap_at = False, 0.0
    if snapshot_info is not None:
        try:
            info = snapshot_info(plat) or {}
            saved = bool(info.get("exists"))
            snap_at = float(info.get("mtime") or 0)
        except Exception:
            saved, snap_at = False, 0.0
    if sess is None:
        return {"ok": True, "session": None,
                "saved": saved, "saved_at": snap_at}, 200
    view = dict(sess.view())
    # 会话内 saved 只在 finish 之后为真；快照文件才是跨进程的事实。
    view["saved"] = bool(view.get("saved")) or saved
    view["saved_at"] = snap_at
    return {"ok": True, "session": view}, 200


def handle_finish(registry, plat: str, verify=None,
                  snapshot=None) -> Tuple[dict, int]:
    """POST /api/app-login/finish {plat}

    verify: 可选回调 (plat) -> (ok, detail)，用于 dump 首页判断是否真的
            登录成功。各渠道的登录墙形态不同（去哪儿是手机号表单、智行是
            「立即登录」文案），回调需要知道自己在校验哪个渠道。
    snapshot: 可选回调 (plat) -> (ok, detail)，导出该渠道的登录态。
              **必须按 plat 存**：把包名/文件名写死在回调里，登录去哪儿
              也会存成智行快照（实测：下次采集报「快照已失效」，而界面
              显示过「已保存」）。老签名 `snapshot()` 仍兼容。
    """
    sess = registry.get(plat)
    if sess is None:
        return _err("没有进行中的登录会话", 409)
    if sess.status != ST_PENDING:
        return {"ok": False, "err": f"会话状态为 {sess.status}"}, 409

    detail = []
    if verify is not None:
        try:
            vok, vdetail = verify(plat)
        except TypeError:
            # 兼容老签名 verify()：没有 plat 参数的回调
            try:
                vok, vdetail = verify()
            except Exception as e:                   # 校验本身失败不等于没登录
                vok, vdetail = True, f"校验异常：{type(e).__name__}"
        except Exception as e:                       # 校验本身失败不等于没登录
            vok, vdetail = True, f"校验异常：{type(e).__name__}"
        detail.append(vdetail)
        if not vok:
            sess.finish(False, vdetail)
            registry.drop(plat)
            return {"ok": False, "err": vdetail}, 409

    if snapshot is not None:
        try:
            try:
                sok, sdetail = snapshot(plat)
            except TypeError:
                sok, sdetail = snapshot()      # 兼容老签名
            detail.append(sdetail)
        except Exception as e:
            detail.append(f"快照失败：{type(e).__name__}")

    msg = "；".join(d for d in detail if d) or "登录完成"
    sess.finish(True, msg)
    registry.drop(plat)
    return {"ok": True, "detail": msg}, 200


def dispatch(registry, method: str, path: str, query: dict,
             body: Optional[dict], ctx: dict):
    """统一入口，供 webui 路由处一行接入。"""
    plat = (query.get("plat") or [""])[0] if query else ""
    if not plat and isinstance(body, dict):
        plat = str(body.get("plat") or "")
    sub = path.replace("/api/app-login", "").strip("/")

    if method == "GET":
        if sub == "frame":
            return handle_frame(registry, plat)
        if sub == "state":
            return handle_state(registry, plat, ctx.get("snapshot_info"))
        return _err("未知子路径", 404)

    if method == "POST":
        body = body if isinstance(body, dict) else {}
        if sub == "":
            return handle_create(registry, plat, ctx.get("packages") or {},
                                 ctx.get("runtime_factory"))
        if sub == "tap":
            return handle_tap(registry, plat, body)
        if sub == "input":
            return handle_input(registry, plat, body)
        if sub == "key":
            return handle_key(registry, plat, body)
        if sub == "finish":
            return handle_finish(registry, plat, ctx.get("verify"),
                                 ctx.get("snapshot"))
        return _err("未知子路径", 404)

    return _err("不支持的方法", 405)


def parse_body(raw: bytes) -> dict:
    """限制 32KB，与既有 POST 端点同一边界。"""
    if not raw:
        return {}
    if len(raw) > 32768:
        raise ValueError("body too large")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}
