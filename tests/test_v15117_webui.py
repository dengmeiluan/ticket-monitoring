"""WebUI 精细化：verbar 链接三缺失 / kpisum hover / 表单字体族
/ 焦点环 box-shadow 迁移。

背景（WebUI 审计）：
- `.verbar a`（版本失配横幅「点此刷新」）无焦点环收录/无 hover/无触控
  外扩——触发场景恰是用户必须点它的紧急时刻（demoBar 同族漏网）；
- `.kpisum a`「查看明细/走势」无 hover 反馈（.pvbody a:hover 同律）；
- 表单件 button/input/select/textarea 落 UA 默认字体族（Arial），
  与全站 Segoe UI/雅黑体系断裂；
- 真实内核（msedge 复证）键盘 Tab 下站点 outline 环被 UA 环系统性
  接管——主按钮白字蓝底 3px 白环≈隐形焦点；焦点环迁移 box-shadow
  （不在 UA 接管范围；站点已有 .cfgsearch box-shadow ring 先例）。"""

import inspect

import webui

_SRC = None


def src():
    global _SRC
    if _SRC is None:
        _SRC = inspect.getsource(webui)
    return _SRC


# ---------------- verbar a 三缺失 ----------------

def test_verbar_link_focus_ring():
    assert ".verbar a:focus-visible" in src(), "焦点环清单缺 .verbar a"


def test_verbar_link_touch_expand():
    # 触控热区外扩（#foot a/.demoBar a::after 家族纪律：纯命中区）
    s = src()
    assert "#foot a,.demoBar a,.verbar a{position:relative}" in s
    assert "#foot a::after,.demoBar a::after,.verbar a::after" in s


def test_verbar_link_hover():
    assert ".verbar a:hover{text-decoration:underline}" in src()


# ---------------- kpisum a hover ----------------

def test_kpisum_link_hover():
    assert ".kpisum a:hover{text-decoration:underline}" in src()


# ---------------- 表单字体族 ----------------

def test_form_font_family_inherit():
    assert "button,input,select,textarea{font-family:inherit}" in src()


# ---------------- 焦点环 box-shadow 迁移 ----------------

def test_focus_ring_box_shadow_migration():
    s = src()
    # 全站清单：box-shadow 环 + outline 关闭（UA 接管 outline 通道，
    # box-shadow 不受接管；th.srt 负 offset 等效 inset 环）
    assert "box-shadow:0 0 0 2px var(--blue);outline:none" in s
    assert "th.srt:focus-visible{box-shadow:inset 0 0 0 2px var(--blue);outline:none" in s
    # 行级焦点（明细 tr）同迁移：inset 贴格
    assert "#ftable tbody tr:focus-visible{box-shadow:inset 0 0 0 2px var(--blue);outline:none}" in s


# ---------------- 推送通道健康可见性 ----------------

def _ts(hours_ago):
    """样本时刻动态生成（相对 24h 窗留足余量）——硬编码日历样本会随
    系统时间滑出窗口（时间敏感测试日历自爆律）。"""
    from datetime import datetime, timedelta
    return (datetime.now() - timedelta(hours=hours_ago)).strftime(
        "%Y-%m-%d %H:%M:%S")


def test_push_channel_state_aggregation(tmp_path, monkeypatch):
    # 账本按通道聚合：ok/fail 计数、连败=最后一条 ok 之后的连续 fail、
    # last/last_ok 取窗口内首现（逐条升序）；旧账无 ch 字段不入聚合；
    # 路径与写入面同源（PUSH_HISTORY_FILE 重定向同轨）
    import json
    f = tmp_path / "push_history.jsonl"
    recs = [
        {"ts": _ts(6), "ok": True, "ch": "dingtalk",
         "title": "t", "desp": "d"},
        {"ts": _ts(5), "ok": False, "ch": "dingtalk",
         "title": "t", "desp": "d"},
        {"ts": _ts(4), "ok": False, "ch": "dingtalk",
         "title": "t", "desp": "d"},
        {"ts": _ts(3.5), "ok": True, "ch": "email",
         "title": "t", "desp": "d"},
        {"ts": "2021-01-01 00:00:00", "ok": False, "ch": "dingtalk",
         "title": "t", "desp": "d"},   # 窗口外（>24h 前）不入
        {"ts": _ts(2), "ok": False, "title": "t",
         "desp": "d"},                 # 无 ch 字段不入
    ]
    f.write_text("\n".join(json.dumps(r, ensure_ascii=False)
                           for r in recs) + "\n", encoding="utf-8")
    monkeypatch.setenv("PUSH_HISTORY_FILE", str(f))
    import webui
    out = webui._push_channel_state(hours=24)
    dt = out["channels"]["dingtalk"]
    assert dt["ok"] == 1 and dt["fail"] == 2
    assert dt["fail_streak"] == 2
    # 升序账本尾现=最近：期望值从落账记录串派生（独立再取 now 在
    # 分钟边界有几十 ms 非确定性窗口）
    assert dt["last"] == recs[2]["ts"][5:16]
    assert dt["last_ok"] == recs[0]["ts"][5:16]
    em = out["channels"]["email"]
    assert em["ok"] == 1 and em["fail"] == 0 and em["fail_streak"] == 0
    assert set(out["channels"].keys()) == {"dingtalk", "email"}


def test_push_channel_state_missing_file(tmp_path, monkeypatch):
    monkeypatch.setenv("PUSH_HISTORY_FILE",
                       str(tmp_path / "nope.jsonl"))
    import webui
    assert webui._push_channel_state() == {"channels": {}}


def test_api_health_carries_push_channels():
    # /api/health 载荷挂 push 通道聚合（采集渠道之外的第二张脸）
    s = src()
    assert 'out["push"] = _push_channel_state(hours=hours)' in s
    # 前端消费：容器 + renderHealth 尾部调用渲染
    assert 'id="pushhl"' in s
    assert "renderPushChannels(j.push);" in s
    assert "function renderPushChannels(pj){" in s


def test_demo_health_push_channels_shape():
    # demo 分支同形（凡功能都过 demo 分支）：合成钉钉连败+邮件全绿
    from core.demo import demo_health
    j = demo_health(hours=24)
    ch = j["push"]["channels"]
    assert ch["dingtalk"]["fail_streak"] > 0 and ch["email"]["fail"] == 0
    for c in ch.values():
        assert set(c) == {"ok", "fail", "fail_streak", "last", "last_ok"}
