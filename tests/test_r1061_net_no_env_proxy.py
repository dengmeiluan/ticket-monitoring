# -*- coding: utf-8 -*-
"""主采集路径不得隐式吃系统/环境代理（2026-11-06）。

两个实测后果：
1. **崩溃**：`NO_PROXY` 里出现带方括号的 IPv6（如 `[::1]`）时，httpx 0.28
   的 proxy_map 会抛 `InvalidURL: Invalid port ':1]'` —— 途牛渠道因此连续
   空转 45+ 次。
2. **风险**：httpx 默认 `trust_env=True` 会把系统代理（Clash）套到采集请求上，
   实测出现过同一域名一次走上海联通、一次走新加坡 AWS —— 国内站点 +
   境外出口是风控升档的典型特征。

项目自己在 `crawlers/special.py` / `core/notifier.py` 里早就写着
「系统代理一律不走」，主采集路径漏了这条纪律。
"""
import httpx

import core.net as net


def test_new_client_survives_broken_no_proxy(monkeypatch):
    """坏 NO_PROXY 下建客户端不能抛异常（这正是线上空转的现场）。"""
    monkeypatch.setenv('NO_PROXY', '[::1]')
    monkeypatch.setenv('no_proxy', '[::1]')
    c = net.new_client('', headers={'A': 'b'}, timeout=5)
    try:
        assert getattr(c, '_trust_env', False) is False
        assert not (getattr(c, '_mounts', None) or {}), (
            '不该套任何环境代理路由')
    finally:
        c.close()


def test_raw_httpx_still_breaks_on_that_env(monkeypatch):
    """反证：不经过 net.py 的裸 httpx 仍然会崩，说明问题确实来自环境代理。

    这条是负控——如果哪天 httpx 自己修好了，它会失败，提醒我们复评。
    """
    monkeypatch.setenv('NO_PROXY', '[::1]')
    monkeypatch.setenv('no_proxy', '[::1]')
    try:
        httpx.Client().close()
    except httpx.InvalidURL:
        return
    raise AssertionError('httpx 已不再受该环境变量影响，请复评本文件前提')


def test_get_and_post_pass_trust_env_false(monkeypatch):
    seen = {}

    def fake_get(url, **kw):
        seen['get'] = kw
        return 'GET'

    def fake_post(url, **kw):
        seen['post'] = kw
        return 'POST'

    # 强制走 httpx 兜底分支（impersonate=""）
    monkeypatch.setattr(httpx, 'get', fake_get)
    monkeypatch.setattr(httpx, 'post', fake_post)
    assert net.get('http://x', impersonate='') == 'GET'
    assert net.post('http://x', impersonate='') == 'POST'
    assert seen['get'].get('trust_env') is False
    assert seen['post'].get('trust_env') is False


def test_explicit_proxy_still_honoured(monkeypatch):
    """显式 proxy=（我们自己配的出口）必须仍然生效，不能被默认值覆盖。"""
    captured = {}

    import curl_cffi.requests as _cffi

    class FakeSession:
        def __init__(self, **kw):
            captured.update(kw)

        def close(self):
            pass

    monkeypatch.setattr(_cffi, 'Session', FakeSession)
    s = net.new_client('chrome', proxy='http://127.0.0.1:7897', timeout=5)
    s.close()
    assert captured.get('proxies') == {
        'http': 'http://127.0.0.1:7897',
        'https': 'http://127.0.0.1:7897'}
