# -*- coding: utf-8 -*-
r"""r671：写接口必须挡住跨站请求，否则「手机也能用」=「同网段谁都能改」。

背景：README 教用户为了手机访问把 `web.host` 改成 `0.0.0.0`。那一刻控制台
绑到全网卡，而 POST 处理**没有任何来源校验**——实测带
`Origin: http://evil.example` 的 `POST /api/config` 回 200 并真的落盘，
`POST /api/restart` 回 200 并真的重启进程。原先只有 `/api/app-login`
做了 Origin 同源校验，其余写接口裸奔。

判据（真起服务，只打到不写盘的分支）：
① 跨站 Origin → 403；
② 同源 Origin → 通过（不是把所有人的浏览器都挡掉）；
③ 无 Origin（命令行 curl/脚本，本机运维常用）→ 通过；
④ 非 JSON 的 Content-Type → 415；
⑤ `/api/restart` 同样受保护（这条最危险：能重启进程）。

负控：去掉 `_do_POST` 开头的闸门 → ①②⑤ 红。
"""
import json
import os
import shutil
import socket
import sys
import tempfile
import time
import urllib.error
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 只打这些：要么本身是只读语义的写接口，要么失败分支不会落盘
SAFE_PATHS = ("/api/app-login/state", "/api/restart")


def _server():
    import webui
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    tmp = tempfile.mkdtemp(prefix="r671_")
    cfg = os.path.join(tmp, "c.yaml")
    # 用一份**临时**配置，绝不动仓库里的 config.example.yaml
    shutil.copyfile(os.path.join(ROOT, "config.example.yaml"), cfg)
    webui._bind_host = lambda c: "127.0.0.1"
    webui.start_web(cfg={"web": {"port": port, "host": "127.0.0.1"}},
                    job=None, report_push=None, config_path=cfg)
    return port, tmp


def _post(base, path, headers, body=b"{}"):
    req = urllib.request.Request(base + path, method="POST", data=body,
                                 headers=headers)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        r = op.open(req, timeout=6)
        return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:
        return "ERR:%s" % type(e).__name__


@pytest.fixture(scope="module")
def live():
    port, tmp = _server()
    base = "http://127.0.0.1:%d" % port
    host = "127.0.0.1:%d" % port
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    up = False
    for _ in range(160):
        try:
            op.open(base + "/api/state", timeout=1)
            up = True
            break
        except Exception:
            time.sleep(0.25)
    if not up:
        shutil.rmtree(tmp, ignore_errors=True)
        pytest.skip("控制台未在期限内起来")
    yield base, host
    shutil.rmtree(tmp, ignore_errors=True)


def test_cross_site_write_is_rejected(live):
    base, host = live
    for p in SAFE_PATHS:
        code = _post(base, p, {"Content-Type": "application/json",
                               "Origin": "http://evil.example",
                               "Host": host})
        assert code == 403, "%s 接受了跨站请求（%s）" % (p, code)


def test_same_origin_still_works(live):
    base, host = live
    code = _post(base, "/api/app-login/state",
                 {"Content-Type": "application/json",
                  "Origin": "http://" + host, "Host": host})
    assert code != 403, "同源请求被误挡（%s）" % code


def test_cli_without_origin_still_works(live):
    base, host = live
    code = _post(base, "/api/app-login/state",
                 {"Content-Type": "application/json", "Host": host})
    assert code != 403, "无 Origin 的脚本调用被误挡（%s）" % code


def test_non_json_body_is_rejected(live):
    base, host = live
    code = _post(base, "/api/app-login/state",
                 {"Content-Type": "text/plain", "Host": host}, body=b"x=1")
    assert code == 415, "非 JSON 请求体没被挡（%s）" % code


@pytest.mark.parametrize("path", ["/api/open-folder", "/api/test-toast"])
def test_bodyless_post_is_not_over_blocked(live, path):
    """无 body 的 POST 不能被 415 误伤（r671b 真实回归）。

    `fetch(path, {method:'POST'})` 不带 body 时，浏览器会自动补
    `Content-Type: text/plain`——按「非 JSON 一律 415」会把「打开文件夹 /
    测试弹窗 / 立即扫描 / 重启」这些无参按钮全部打哑。实测同源调用直接 415。
    无 body 本就没有可解析载荷，CSRF 拿它也只能触发幂等动作。
    """
    base, host = live
    same = _post(base, path,
                 {"Content-Type": "text/plain;charset=UTF-8",
                  "Origin": "http://" + host, "Host": host}, body=b"")
    assert same != 415, "%s 的无 body 同源请求被误判成非 JSON（%s）" % (path, same)
    cross = _post(base, path,
                  {"Content-Type": "text/plain;charset=UTF-8",
                   "Origin": "http://evil.example", "Host": host}, body=b"")
    assert cross == 403, "%s 的无 body 跨站请求没被挡（%s）" % (path, cross)


def test_restart_is_guarded(live):
    """最危险的一条：跨站能重启进程。"""
    base, host = live
    code = _post(base, "/api/restart",
                 {"Content-Type": "application/json",
                  "Origin": "http://evil.example", "Host": host})
    assert code == 403, "跨站请求能重启进程（%s）" % code


def test_guard_covers_every_write_endpoint_structurally():
    """闸门放在 _do_POST 开头：新增写接口自动继承，不靠逐个记得加。"""
    import io
    src = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                  newline="").read()
    i = src.index("def _do_POST(self):")
    seg = src[i:i + 2200]
    j_demo = seg.index('DEMO["on"]')
    j_guard = seg.index("跨站请求已拒绝")
    j_cfg = seg.index('if self.path == "/api/config":')
    assert j_demo < j_guard < j_cfg, (
        "跨站闸门必须在演示短路之后、所有写分支之前")
