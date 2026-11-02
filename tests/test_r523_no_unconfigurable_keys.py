# -*- coding: utf-8 -*-
"""r523：配置页不允许存在「无法配置」的项。

用户明确要求：**配置页面不允许存在任何无法配置的项**；需要重启的走重启
生效，能热更新的就热更新。

审计方法：把 `config.example.yaml` 的叶子键与「配置页控件能写的 GLB 键 +
后端回读键」做差集。修前有 9 个键既无控件也无展示：

    crawler.session_max_days      会话到期强制续期（采集端真读）
    crawler.max_concurrency       并发上限（pacing 真读）
    crawler.mobile_user_agent     H5/移动入口 UA
    crawler.tls_impersonate       飞猪等 curl_cffi 指纹
    crawler.debug_dir             失败现场快照落盘位置
    crawler.login_desktop         登录窗是否可见
    crawler.breaker.login_cooldown_s  登录墙固定冷却
    crawler.cadence.<5 渠道>      单渠道节奏倍率（TTL 下限）
    schedule.near_days            邻近日期比价窗口

（`breaker.enabled`/`warmup.*` 等经键名映射在页面上本来就有，不算缺口。）

现在这些键都有编辑控件，且**保存路径真的把它们写回 config.yaml**——
只有控件没有写入等于没配上。
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_KEYS = ("session_max_days", "max_concurrency", "mobile_user_agent",
         "tls_impersonate", "debug_dir", "login_desktop",
         "login_cooldown_s", "near_days", "cadence")


def _w():
    return io.open(os.path.join(ROOT, "webui.py"), encoding="utf-8",
                   newline="").read()


def test_every_key_has_an_editable_control():
    """控件必须真的**渲染**（`glcell(` 调用在场），而不只是有赋值表达式。

    负控踩过：把 `glcell('会话最长可用天数','glbSessMax'…)` 删掉后，
    `GLB.session_max_days=…` 这段 onchange 代码仍在源码里，只查赋值会全绿。
    """
    w = _w()
    # 1) 每个键都要有赋值表达式（onchange 的写回）
    handled = set(re.findall(r"GLB\.([a-zA-Z0-9_]+)\s*=", w))
    for k in _KEYS:
        assert k in handled, "配置页没有 %s 的写回表达式" % k
    # 2) 每个键都必须被某个 glcell 真正渲染出来——按**控件 id** 判定。
    #    负控踩过两次：删掉 glcell 后 ①`GLB.k=` 仍在 onchange 里、
    #    ②宽泛的正则还能匹配到别的 glcell，两次都假绿。控件 id 是唯一不变量。
    _ID = {"session_max_days": "glbSessMax", "max_concurrency": "glbMaxConc",
           "mobile_user_agent": "glbMua", "tls_impersonate": "glbTls",
           "debug_dir": "glbDbgDir", "login_desktop": "glbLgd",
           "login_cooldown_s": "glbLcd", "near_days": "glbNearD"}
    for k, cid in _ID.items():
        assert "'%s'" % cid in w, \
            "%s 没有渲染控件（找不到 id=%s）" % (k, cid)
    assert "'glbCad_'+p" in w or "glbCad_" in w, "cadence 控件缺失"


def test_config_page_no_longer_declares_any_key_readonly():
    """r521 的「仅可在 config.yaml 中修改」只读块必须撤掉。"""
    w = _w()
    assert "glnote('仅可在 config.yaml 中修改" not in w, \
        "仍有一块「只能改文件」的说明——按新要求这些项必须可配"


def test_every_key_is_actually_persisted():
    """控件只是前端；POST 必须真的写进 cfg 并落盘。"""
    w = _w()
    i = w.index('if self.path == "/api/config":')
    seg = w[i:i + 14000]
    # 逐个键确认出现在写入块里（含 cadence 的 dict 分发）
    for k in _KEYS:
        assert '"%s"' % k in seg, "保存路径没有写入 %s（改了存不进去）" % k


def test_every_key_is_read_back():
    """回读：保存后重开配置页要能看到自己设的值。"""
    w = _w()
    i = w.index('elif self.path == "/api/config":')
    seg = w[i:i + 13000]
    keys = set(re.findall(r'"([a-z_]+)":', seg))
    for k in _KEYS:
        assert k in keys, "/api/config 没有回读 %s" % k


def test_written_keys_are_hot_effective_not_startup_level():
    """这几项都不是启动级（启动级只有路径/host/run_on_start）。"""
    w = _w()
    i = w.index("def _startup_vals(")
    seg = w[i:i + 2600]
    for k in _KEYS:
        assert k not in seg, \
            "%s 被当成启动级却没有进重启中心（会静默不生效）" % k


def test_cadence_control_matches_backend_semantics():
    """cadence 的语义是「该渠道单独的最小采集间隔（分钟）」，整数。

    前端若按「倍率/小数」写，用户填 1.5 会被后端 `int()` 截成 1，
    控件与实际生效值对不上。两侧必须同口径：整数分钟、0..10080。
    """
    w = _w()
    i = w.index("GLB.cadence=Object.assign")
    seg = w[max(0, i - 260):i + 260]
    assert "parseInt(this.value)" in w[i:i + 260], \
        "cadence 控件没有按整数解析"
    assert "10080" in w[i:i + 260], "上限与后端不一致（后端 max 10080）"
    assert "parseFloat" not in w[i:i + 260], \
        "cadence 控件按小数解析，但后端 int() 会截断"
    assert "最小间隔" in seg, "标签没写清语义（应说明是「最小间隔 分钟」）"


def test_cadence_write_uses_the_same_clamp():
    w = _w()
    i = w.index('if isinstance(glb.get("cadence"), dict):')
    # 取整段写入逻辑到缩进回落到同级为止。原先钉 700 字符窗口，r630 给
    # 白名单补了 App 渠道（try/import 多出 6 行）后把 close 语句挤出窗口，
    # 变成「代码还在、断言够不着」的假红（门禁守意图，不守源码长度）。
    j = w.index("win_toast 缺省即开启", i)
    seg = w[i:j]
    assert "int(_cv)" in seg, "写入时没有按整数解析（与解析端 int() 不一致）"
    assert "10080" in seg, "写入上限与 core/pacing.py 不一致"
