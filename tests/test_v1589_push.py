# -*- coding: utf-8 -*-
"""推送审校收口钉：ServerChan 发送端截断留痕（发送端留痕家族律补齐
最后一通道）/ 钉钉截断尾注无链分支词面去重 / _cross_compare 头行
终档守卫 / _ops_fallbacks 地板档全角感知截 / GitHub 图库上传通路。

- GitHub 图库（ghimg）：pixhost 显示端大陆直连不可达（手机钉钉
  拉不到图实锤）、freeimage 上传端死亡（直连超时+代理被掐）、
  sm.ms 转维护模式——Contents API 传公开图库、显示走 jsDelivr
  （新文件首取即回源），上传直连失败按配置代理重试一次。
  上传端与显示端网络条件不同：验证显示端必须绕代理直连。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v1589_push.py -q
"""
import logging
import urllib.parse

import core.notifier as nm


def _dw(s):
    from core.alerter import _disp_dw
    return _disp_dw(s)


# ---- ServerChan：发送端截断留痕 ----

class _FakeUrlResp:
    def read(self):
        return b'{"code":0}'

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _sc_send(monkeypatch, tmp_path, desp):
    """捕获 ServerChan 实际发出的 desp（零网络）。"""
    cap = {}

    def fake_urlopen(req, timeout=None):
        cap["req"] = req
        return _FakeUrlResp()

    monkeypatch.chdir(tmp_path)   # push_history 落 CWD logs/
    monkeypatch.setattr(nm.urllib.request, "urlopen", fake_urlopen)
    n = nm.ServerChanNotifier("SCT_test", logging.getLogger("t"))
    n.send("t", desp)
    qs = urllib.parse.parse_qs(cap["req"].data.decode("utf-8"))
    return qs["desp"][0]


def test_serverchan_truncation_leaves_trace(monkeypatch, tmp_path):
    """>31800B 纯文本：产物 ≤31800B 且尾注在案（丢失面点明）——
    静默截断曾让尾部明细总表/对账段无声丢失。"""
    desp = "长" * 20000   # 60000B，纯 CJK 无 ![ 无 \n\n
    out = _sc_send(monkeypatch, tmp_path, desp)
    assert len(out.encode("utf-8")) <= 31800, \
        f"截断产物 {len(out.encode('utf-8'))}B 超 ServerChan 31800B 上限"
    assert "已截断" in out, "尾注丢失面说明未落位"
    assert "明细总表" in out, "丢失面语义（尾部明细总表）未点明"


def test_serverchan_truncation_keeps_intact_link(monkeypatch, tmp_path):
    """双图链长文：尾部图链被切点整体让位（不横切 URL 成死链），
    在位图链原样保留。"""
    link_a = "![走势](https://a.example.com/x.png)"
    link_b = "![总表](https://b.example.com/t.png)"
    desp = ("x" * 14000 + "\n\n" + link_a + "\n\n"
            + "y" * 14000 + "\n\n" + link_b + "\n\n" + "z" * 4000)
    out = _sc_send(monkeypatch, tmp_path, desp)
    assert len(out.encode("utf-8")) <= 31800
    assert link_a in out, "在位图链被误切"
    # 死链形态：](http 后被拦腰截断（无闭合括号）=横切实锤
    assert "](https://b" not in out, "尾部图链被横切成死链"


def test_serverchan_truncation_note_no_dup(monkeypatch, tmp_path):
    """无链分支尾注不与本体同义两现（钉钉病句同口关闭）：
    「见控制台」只出现一次。"""
    desp = "a" * 40000
    out = _sc_send(monkeypatch, tmp_path, desp)
    assert out.count("见控制台") == 1, out[-200:]


# ---- 钉钉：无链分支尾注词面去重 ----

class _FakeResp:
    def json(self):
        return {"errcode": 0, "errmsg": "ok"}


class _CapturePost:
    def __call__(self, url, **kw):
        self.payload = kw.get("json")
        return _FakeResp()


def test_dingtalk_note_no_link_branch_distinct(monkeypatch, tmp_path):
    """19000B 无链文本（push_history 实录形态）：尾注不再产出
    「完整明细见控制台），完整详情见控制台」同义两现；无链提示改
    独立语义。"""
    monkeypatch.chdir(tmp_path)
    cap = _CapturePost()
    monkeypatch.setattr(nm.httpx, "post", cap)
    n = nm.DingTalkNotifier.__new__(nm.DingTalkNotifier)
    n.logger = logging.getLogger("t")
    n.last_errcode = None
    n._fail_streak = 0
    n._signed_url = lambda: "http://127.0.0.1/fake-webhook"
    n.send("t", "a" * 19000)
    txt = cap.payload["markdown"]["text"]
    assert len(txt.encode("utf-8")) <= 18000
    assert txt.count("见控制台") == 1, txt[-200:]
    assert "本条已无跳转链接" in txt, "无链分支应给独立指引"


def test_dingtalk_note_with_link_branch_unchanged(monkeypatch, tmp_path):
    """有链分支：尾注维持本体词面（不误加无链提示）。"""
    monkeypatch.chdir(tmp_path)
    cap = _CapturePost()
    monkeypatch.setattr(nm.httpx, "post", cap)
    n = nm.DingTalkNotifier.__new__(nm.DingTalkNotifier)
    n.logger = logging.getLogger("t")
    n.last_errcode = None
    n._fail_streak = 0
    n._signed_url = lambda: "http://127.0.0.1/fake-webhook"
    desp = ("x" * 8000 + "\n\n![走势](https://a.com/x.png)\n\n"
            + "y" * 8000 + "\n\n![总表](https://b.com/t.png)\n\n"
            + "z" * 2500)
    n.send("t", desp)
    txt = cap.payload["markdown"]["text"]
    assert len(txt.encode("utf-8")) <= 18000
    assert "本条已无跳转链接" not in txt, "有链分支误挂无链提示"
    assert txt.count("见控制台") == 1, txt[-200:]


# ---- _cross_compare：头行终档守卫 ----

def test_cross_compare_head_long_name_fits_40():
    """双航司长名+日期+结论（45 半角实发形态）：头行逐行 ≤40 半角，
    航班号与结论保留（地板档=航班号+价格结论，核心判据最小集）。"""
    from core.alerter import Alerter as _A
    base = {"code": "HU7849", "depTime": "08:15", "arrTime": "12:40",
            "depDate": "2026-10-05", "arrDate": "2026-10-05",
            "transCity": "", "crossDayDesc": ""}
    secs = [{"date": "2026-10-05", "pool": [
        dict(base, name="新海航｜海南航空HU7849", price=2546,
             _platform="qunar"),
        dict(base, name="新海航｜海南航空HU7849", price=2746,
             _platform="ctrip")]}]
    secs.append({"date": "2026-10-06", "pool": [
        dict(base, depDate="2026-10-06", name="新海航｜海南航空HU7849",
             price=2688, _platform="qunar"),
        dict(base, depDate="2026-10-06", name="新海航｜海南航空HU7849",
             price=2888, _platform="ctrip")]})
    txt = _A._cross_compare(secs)
    assert txt
    for ln in txt.splitlines():
        assert _dw(ln) <= 40, f"头行超宽 {ln!r} ({_dw(ln)} 半角)"
    head_ln = next(ln for ln in txt.splitlines() if "💰" in ln)
    assert "HU7849" in head_ln, "地板档丢航班号"


# ---- _ops_fallbacks：地板档全角感知截 ----

def test_ops_fallbacks_floor_cjk_width_safe():
    """全 CJK 长注（无冒号形态）：末档地板按 _disp_dw 预算截，
    恒 ≤40 半角（字符数截曾 47 半角超宽）。"""
    from core.alerter import _ops_fallbacks
    tiers = _ops_fallbacks("航变免费退改与直挂标注缺失" * 4)
    assert tiers
    assert _dw(tiers[-1]) <= 40, \
        f"地板档超宽 {tiers[-1]!r} ({_dw(tiers[-1])} 半角)"


def test_ops_fallbacks_floor_colon_head_width_safe():
    """冒号形态：地板保前缀——前缀本身超长时按宽截，恒 ≤40。"""
    from core.alerter import _ops_fallbacks
    n = "超长事由前缀不需要这么长但是为了测试宽度守卫必须写满：" + "内容" * 30
    tiers = _ops_fallbacks(n)
    assert tiers
    assert _dw(tiers[-1]) <= 40, \
        f"地板档超宽 {tiers[-1]!r} ({_dw(tiers[-1])} 半角)"


def test_ops_fallbacks_normal_forms_unchanged():
    """现行四类 ops 注模板（34-40 半角恰安全）：降级链首档语义不回退。"""
    from core.alerter import _ops_fallbacks
    tiers = _ops_fallbacks("直挂标注缺失：qunar、ctrip、tongcheng")
    assert tiers, "正常形态应产出降级链"
    assert tiers[0].startswith("> ⚠️ 直挂标注缺失：qunar、ctrip")


# ---- GitHub 图库上传（ghimg） ----

class _CapturePut:
    """httpx.put 替身：按脚本逐次返回，捕获全部调用参数。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def __call__(self, url, **kw):
        self.calls.append({"url": url, **kw})
        return self.script.pop(0)


class _GhResp:
    def __init__(self, status, text=""):
        self.status_code = status
        self.text = text


def _ghimg(tmp_path):
    import os
    import report as rp
    p = os.path.join(tmp_path, "trend_urc_sha_2026-10-05.png")
    open(p, "wb").write(b"\x89PNG fake")
    return rp, p


def test_ghimg_upload_success_jsdelivr_url(monkeypatch, tmp_path):
    """上传成功：Contents API PUT → 显示 URL=jsDelivr（gh 库@main 路径），
    文件名带时分戳防 CDN 陈旧缓存。"""
    import os
    rp, p = _ghimg(tmp_path)
    cap = _CapturePut([_GhResp(201, '{"content":{"path":"charts/x.png"}}')])
    monkeypatch.setattr(rp.httpx, "put", cap)
    url = rp.upload_ghimg(
        p, {"repo": "dengmeiluan/ticket-img", "token": "t0k"},
        logging.getLogger("t"))
    assert url and url.startswith(
        "https://cdn.jsdelivr.net/gh/dengmeiluan/ticket-img@main/charts/"), url
    assert url.endswith(".png"), url
    body = cap.calls[0]
    assert body["url"].startswith(
        "https://api.github.com/repos/dengmeiluan/ticket-img/contents/charts/")
    assert body["headers"]["Authorization"] == "Bearer t0k"
    assert body["json"]["content"], "base64 内容缺失"


def test_ghimg_upload_retries_via_proxy(monkeypatch, tmp_path):
    """首连异常（api.github.com 直连不通形态）：按配置代理重试一次。"""
    rp, p = _ghimg(tmp_path)

    class _FailThenOk:
        def __init__(self):
            self.calls = []

        def __call__(self, url, **kw):
            self.calls.append(kw)
            if len(self.calls) == 1:
                raise rp.httpx.ConnectError("direct blocked")
            return _GhResp(201)

    fl = _FailThenOk()
    monkeypatch.setattr(rp.httpx, "put", fl)
    url = rp.upload_ghimg(
        p, {"repo": "dengmeiluan/ticket-img", "token": "t0k",
            "proxy": "http://127.0.0.1:7897"},
        logging.getLogger("t"))
    assert url, "代理重试后应成功"
    assert len(fl.calls) == 2
    assert fl.calls[0].get("proxy") is None, "首连应直连"
    assert fl.calls[1].get("proxy") == "http://127.0.0.1:7897"


def test_ghimg_upload_fail_returns_none(monkeypatch, tmp_path):
    """双连皆败：返回 None（upload_chart 降级 pixhost 兜底）。"""
    rp, p = _ghimg(tmp_path)

    class _AlwaysFail:
        def __call__(self, url, **kw):
            return _GhResp(401, '{"message":"Bad credentials"}')

    monkeypatch.setattr(rp.httpx, "put", _AlwaysFail())
    url = rp.upload_ghimg(
        p, {"repo": "dengmeiluan/ticket-img", "token": "bad"},
        logging.getLogger("t"))
    assert url is None


def test_upload_chart_ghimg_branch_wired():
    """upload_chart 装配 ghimg 分支（provider=ghimg 且 repo/token 齐
    才走，失败降级 pixhost 的词面在案）。"""
    import os
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(base, "report.py"), encoding="utf-8").read()
    assert 'provider == "ghimg"' in src, "upload_chart 缺 ghimg 分支"
    assert "GitHub 图库失败，降级 pixhost" in src
