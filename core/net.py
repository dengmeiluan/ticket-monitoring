# -*- coding: utf-8 -*-
"""HTTP 出口选择：优先 curl_cffi（Chrome 的 TLS/JA3 指纹），缺依赖退回 httpx。

为什么值得多这一层：HTTPS 握手里的 TLS 指纹（JA3/JA4）与 HTTP/2 帧序，
是比 UA 更难伪装的一层。Python 的 ssl 栈有固定特征，直接 POST 接口时
一眼就能和浏览器区分开。curl_cffi 用的是真 libcurl + Chrome 指纹配置，
在不改业务代码的前提下把这层对齐。

依赖可选：没装 curl_cffi 就自动走 httpx，行为与之前完全一致。
"""
IMPERSONATE_DEFAULT = "chrome"


def post(url, *, headers=None, payload=b"", cookies=None, timeout=25,
         impersonate=None):
    """POST 一次。返回对象需具备 status_code/text/headers（两者都满足）。"""
    imp = (IMPERSONATE_DEFAULT if impersonate is None
           else str(impersonate or "").strip())
    if imp:
        try:
            from curl_cffi import requests as _cffi
        except ImportError:
            _cffi = None
        if _cffi is not None:
            return _cffi.post(
                url, headers=headers or {}, data=payload,
                cookies=cookies or {}, timeout=timeout,
                impersonate=imp)
    import httpx
    return httpx.post(url, headers=headers or {}, content=payload,
                      cookies=cookies or {}, timeout=timeout)


def new_client(impersonate="chrome", **kwargs):
    """`httpx.Client` 的等价替换（本项目实际用到的子集）。

    按 httpx 的习惯传参（`follow_redirects` / `proxy` / `trust_env`），内部映射
    成 curl_cffi 的 `Session(impersonate=...)`；没装 curl_cffi 或显式传
    `impersonate=""` 时原样退回 `httpx.Client`，行为与改造前一致。

    支持到：`get/post(url, params=, headers=, cookies=, timeout=, data=, json=)`、
    `cookies.get/set(name, value, domain=, path=)`、`close()`、`with` 上下文。
    """
    imp = (IMPERSONATE_DEFAULT if impersonate is None
           else str(impersonate or "").strip())
    if imp:
        try:
            from curl_cffi import requests as _c
        except ImportError:
            _c = None
        if _c is not None:
            kw = dict(kwargs)
            if "follow_redirects" in kw:
                kw["allow_redirects"] = kw.pop("follow_redirects")
            kw.pop("http2", None)
            if "trust_env" in kw:
                # curl 默认不读系统代理环境变量，与 trust_env=False 同义
                kw.pop("trust_env")
            _p = kw.pop("proxy", None)
            if _p:
                kw["proxies"] = {"http": _p, "https": _p}
            try:
                return _c.Session(impersonate=imp, **kw)
            except TypeError:
                # 个别版本不认识某个参数：丢掉非必要项，保证还能用
                for _k in ("allow_redirects", "proxies", "verify"):
                    kw.pop(_k, None)
                return _c.Session(impersonate=imp)
    import httpx
    return httpx.Client(**kwargs)


def get(url, *, headers=None, cookies=None, timeout=20, impersonate=None):
    imp = (IMPERSONATE_DEFAULT if impersonate is None
           else str(impersonate or "").strip())
    if imp:
        try:
            from curl_cffi import requests as _cffi
        except ImportError:
            _cffi = None
        if _cffi is not None:
            return _cffi.get(url, headers=headers or {},
                             cookies=cookies or {}, timeout=timeout,
                             impersonate=imp)
    import httpx
    return httpx.get(url, headers=headers or {}, cookies=cookies or {},
                     timeout=timeout)
