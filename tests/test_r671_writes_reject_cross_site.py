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
    # 强制绑回环：测试进程只该监听本机。这个替换**必须**在夹具退出时还原——
    # 直接赋值会永久改掉模块属性，后续 test_r675 的「TM_WEB_HOST 生效」断言
    # 会读到这个替身而恒得 127.0.0.1（实测全量到该文件必红 4 条）。
    old_bind = webui._bind_host
    webui._bind_host = lambda c: "127.0.0.1"
    try:
        webui.start_web(cfg={"web": {"port": port, "host": "127.0.0.1"}},
                        job=None, report_push=None, config_path=cfg)
    except Exception:
        webui._bind_host = old_bind
        raise
    return port, tmp, old_bind


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
    port, tmp, old_bind = _server()
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
    global_webui = sys.modules.get("webui")
    if global_webui is not None:
        global_webui._bind_host = old_bind
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
    # 新增会话重置/写分支会把 /api/config 推后；只钉相对顺序。
    j_demo = src.index('DEMO["on"]', i)
    j_guard = src.index("跨站请求已拒绝", i)
    j_cfg = src.index('"/api/config"', i)
    assert j_demo < j_guard < j_cfg, (
        "跨站闸门必须在演示短路之后、所有写分支之前")


def test_bodyless_post_is_never_rejected_by_content_type():
    """r672b：无 body 的 POST 不得因 Content-Type 被判 415（结构级兜底）。

    真实缺陷：`/api/app-login*`（5 个）、`/api/challenge/*`（3 个）、
    `/api/login`、`/api/login-finish`、`/api/login-verify`、
    `/api/channel/{probe,verify,warmup}`、`/api/pacing/reset`、
    `/api/special-radar`、`/api/srx/watch`、`/api/probe/start` 共 13 个
    端点各自重复写了一模一样的一段「不是 application/json 就 415」。
    `fetch(path,{method:'POST'})` 不带 body 时浏览器自动补
    `text/plain`——这些按钮全部被打哑，而 r672 的端点普查此前被
    `/api/restart` 的 `os._exit` 杀掉，一直没跑到（表是绿的）。

    判据：除统一 helper 外，正文里不得再出现逐分支的
    「Content-Type 必须为 application/json」+415 组合；且所有 415 出口
    都必须先看 Content-Length > 0。负控=把 helper 改回无条件 415 即红
    （r672 运行时普查同时红）。
    """
    import io
    src = io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                  newline="").read()
    # 只允许两处：_json_body_ok 单源，以及 _post_json 里为了让「鸭子类型
    # 替身」能独立单测而内联的同一判据。逐分支再抄一份（13 个端点那种）
    # 就是缺陷回潮。
    occ = src.count('"Content-Type 必须为 application/json"')
    assert occ == 2, (
        "JSON Content-Type 判据应只有 _json_body_ok 与 _post_json 两处"
        "（现 %d 处）——逐分支重复写会把「无 body 同源请求」打成 415" % occ)
    i = src.index("def _json_body_ok(self):")
    seg = src[i:src.index("def _post_json(", i)]
    # helper 必须「先看有没有 body」：Content-Length 的**读取**要出现在
    # 返回 415 的自绘调用之前（注释里也提到 Content-Length，故锚定代码本身）
    j_len = seg.index('get("Content-Length"')
    j_415 = seg.index("self._json(")
    assert j_len < j_415, "helper 必须先判 Content-Length 再谈 415"
    assert "application/json" in seg
    # _post_json 里的内联份同样必须先读 Content-Length
    j = src.index("def _post_json(self")
    seg2 = src[j:src.index("def _json_response", j)
              if "def _json_response" in src[j:] else j + 3000]
    assert seg2.index('get("Content-Length"') < seg2.index("415")
