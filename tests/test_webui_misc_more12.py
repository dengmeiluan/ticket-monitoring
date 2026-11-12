# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r282_webui.py
- tests/test_r317_webui_inject.py
- tests/test_r338_webui_p3.py
- tests/test_r675_container_bind_host.py
- tests/test_r794_capbar_names_gaps.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import json
import os
import pytest
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

from urllib.parse import urlsplit


# ---- merged from tests/test_r282_webui.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src():
    import webui
    return webui_full_src()


def _fn_body(src, name):
    """函数声明起到下一个顶层 function 为止的切片（块级语义，非字符窗）。"""
    m = re.search(r"function %s\(" % name, src)
    assert m, "function %s 不在场" % name
    nxt = re.search(r"\nfunction ", src[m.end():])
    end = m.end() + nxt.start() if nxt else len(src)
    return src[m.start():end]


def test_expand_folds_covers_user_head():
    body = _fn_body(_src(), "expandFolds")
    # 实效档：用户卡头纳入搜索态临时全开（显式单 body 形态）
    assert "#cfgform .uhead2" in body
    assert "_setFold(h,[b],false)" in body


def test_search_clear_rewrites_by_open_user_not_aria():
    src = _src()
    body = _fn_body(src, "cfgSearchClear")
    # 实效档：手风琴还原按 OPEN_USER 权威逐卡回写（b 缺守卫在位）
    assert "i!==OPEN_USER" in body
    assert "_setFold(h,[b],i!==OPEN_USER)" in body
    # 禁复活：旧形态（按已被搜索态污染的 aria 回写）在清空路径零残留
    assert "getAttribute('aria-expanded')==='true'?'':'none'" not in body


def test_open_user_writes_routed_through_single_setter():
    src = _src()
    # 直接赋值形态仅存四处合法点：let 声明 / 启动读槽恢复 /
    # setOpenUser 函数体 / buildForm 越界钳回——其余写点必须走
    # setOpenUser（localStorage 槽随写点同步）。负向先行排除
    # OPEN_USER=== 比较形态（其子串含 "OPEN_USER="）
    assert len(re.findall(r"OPEN_USER=(?!=)", src)) == 4
    for caller in ("setOpenUser(willOpen?u:-1)",
                   "setOpenUser(CFG.length)",
                   "setOpenUser(-1)", "setOpenUser(0)"):
        assert caller in src, caller
    # 持久化槽与折叠态槽同惯例（try/catch 收口）
    assert "jpcfguseropen" in src


def test_build_form_clamps_restored_slot():
    body = _fn_body(_src(), "buildForm")
    # 槽值恢复越界钳回（删用户/导入后 OPEN_USER 越界=全收假象）
    assert "if(OPEN_USER>=CFG.length)OPEN_USER=CFG.length-1;" in body


# ---- merged from tests/test_r317_webui_inject.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _page_src():
    import webui
    return webui.PAGE


# ---------- 源码钉（轻量，防回退） ----------

def test_citydl_datalist_escapes_keys():
    """P3-1 城市键转义律（r320 随迁移改写）：native datalist 已退役
    （289 城自定义面板替代）——旧填充点禁复活；面板城市项经 esc()
    入 data-n（转义语义保留：`data-n="${esc(n)}"`）。"""
    src = _page_src()
    assert "citydl" not in src, "native datalist 复活（r320 已退役）"
    i = src.find('data-n="${esc(n)}"')
    assert i > 0, "面板城市项 esc 转义点不在场"
    assert src.count('data-n="${esc(n)}"') >= 1


def test_health_pulse_clicks_use_dataset_not_jsstring():
    """P3-2：健康格 showLog 与脉冲柱 gotoPulseHealth 的 onclick 不再
    拼 JS 串实参（'${p}'/'${r.ts}' 断属性族），改 data-* + this。"""
    src = _page_src()
    assert "showLog('${p}','${r.ts}')" not in src
    assert "gotoPulseHealth('${r.ts}','${bad}')" not in src
    # r1140：24 颗小格收敛为 6 个 4h 整段按钮；段按钮只带 this，
    # 段内取 data-ts 的最后一格（showLog 读 dataset，不拼 JS 串）。
    assert 'onclick="hcSegLog(this)"' in src
    assert "showLog(cs[cs.length-1])" in src
    assert 'data-ts="' in src
    assert "gotoPulseHealth(this)" in src


def test_main_landmark_and_table_caption_source_pin():
    """P3-5：main 地标与明细表 caption（视觉隐藏）在源码在场。"""
    src = _page_src()
    assert "<main" in src or 'role="main"' in src
    assert "ftable'）" in src or "ftable'" in src  # 表 id 既有
    i = src.find("<table id=\"ftable\"")
    if i < 0:
        i = src.find("id=\"ftable\"")
    assert i > 0, "#ftable 表标签不在场"
    seg = src[i:i + 400]
    assert "<caption" in seg, seg[:200]


# ---------- 行为钉（demo 实例） ----------



_POISON = '<img src=x onerror="window.__XSS_{f}=1">'
_FIELDS = ("depTime", "arrTime", "dur", "agePolicy", "riskPolicy",
           "plat", "date", "layoverT", "lay2dep", "transGoDate")


def _injected_state(base):
    """取真实 demo state，首航班 10 字段落毒值（探针同构 C1 报告）。"""
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    raw = op.open(base + "/api/state", timeout=5).read().decode("utf-8")
    st = json.loads(raw)
    f0 = st["users"][0]["flights"][0]
    for fld in _FIELDS:
        f0[fld] = _POISON.format(f=fld)
    return st












# ---- merged from tests/test_r338_webui_p3.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src():
    import webui
    return webui_full_src()


def test_p3_1_header_padding_matches_bleed_function():
    """P3-1：header 左右 padding 与出血 margin 同一 clamp 函数（全带）。"""
    src = _src()
    # 实效档：基础块 header 水平 padding=clamp(12px,3vw,18px)——与
    # margin:0 calc(-1*clamp(12px,3vw,18px)) 同函数，391-599 带内
    # 内容缘逐点==卡轴（出血相抵后 header 左缘=视口缘，padding 落
    # 3vw==wrap 内容缘）；≥600 cap 18px 桌面语言不变
    assert "padding:9px clamp(12px,3vw,18px)" in src
    # 置尾覆写块同函数（≤760 移动端合并块声明序在基础块后，同特异性
    # 恒压——漏改它则 391-760 全带被压回恒 18px，探针实锤）：上下
    # 12px 移动档保留，左右随出血函数。
    # r808 起页头选择器带作用域（`#hdcard`）——裸 `header{}` 会同时命中
    # 8 个组件卡头（白横带 + 分割线），由 test_r808_header_selector_scope
    # 守死；本钉跟到同一选择器，守的仍是「padding 与出血同函数」。
    assert "#hdcard{padding:12px clamp(12px,3vw,18px)}" in src
    # 禁复活：恒 18px 旧形态（基础块 391-599 带偏 6px / ≤760 块压回恒值）
    assert "padding:9px 18px;display:flex" not in src
    assert "#hdcard{padding:12px 18px}" not in src


def test_p3_2_transfer_terminal_word_nowrap():
    """P3-2：换乘词段整词 nowrap（同数组机场段/机型段同构）。"""
    src = _src()
    # 实效档：换乘段包 <span class="nw">——「换乘·X（Y出）」是含
    # 语义的中文词组+航站楼码，裸排在 td .stl（white-space:normal）
    # 容器里宽屏折行出孤字
    assert '<span class="nw">换乘·' in src
    # 禁复活：裸排形态零命中（同数组其余 nw 段不受此断言约束）
    assert "f.transTerminal?'换乘·'+he(" not in src


def test_p3_3_flab_hover_feedback():
    """P3-3：.flab hover 有视觉反馈（color 提亮档）。"""
    src = _src()
    assert ".flab:hover{color:var(--tx)}" in src


# ---- merged from tests/test_r675_container_bind_host.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_bind_host_priority(monkeypatch):
    import webui
    monkeypatch.delenv("TM_WEB_HOST", raising=False)
    assert webui._bind_host({}) == "127.0.0.1"
    monkeypatch.setenv("TM_WEB_HOST", "0.0.0.0")
    assert webui._bind_host({}) == "0.0.0.0"
    assert webui._bind_host({"web": {}}) == "0.0.0.0"
    # 显式值优先——用户主动指定 0.0.0.0 时不能被环境变量覆盖
    monkeypatch.setenv("TM_WEB_HOST", "127.0.0.1")
    assert webui._bind_host({"web": {"host": "0.0.0.0"}}) == "0.0.0.0"


def test_startup_vals_reports_effective_host(monkeypatch):
    import webui
    monkeypatch.setenv("TM_WEB_HOST", "0.0.0.0")
    out = webui._startup_vals({"web": {"port": 8765}})
    assert out["host"] == "0.0.0.0", (
        "重启中心拿文件缺省值比较，容器里会造出永远差一项的假待重启")


@pytest.fixture(scope="module")
def live():
    import webui
    port = _free_port()
    tmp = tempfile.mkdtemp(prefix="r675_")
    cfg_path = os.path.join(tmp, "c.yaml")
    # 只读样例副本：绝不让探针写仓库里的 config.example.yaml
    shutil.copyfile(os.path.join(ROOT, "config.example.yaml"), cfg_path)
    old_bind = webui._bind_host
    old_env = os.environ.get("TM_WEB_HOST")
    os.environ["TM_WEB_HOST"] = "0.0.0.0"
    webui.start_web(cfg={"web": {"port": port}}, job=None,
                    report_push=None, config_path=cfg_path)
    base = "http://127.0.0.1:%d" % port
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(120):
        try:
            op.open(base + "/api/state", timeout=1)
            break
        except Exception:
            time.sleep(0.25)
    yield base, cfg_path, op
    if old_env is None:
        os.environ.pop("TM_WEB_HOST", None)
    else:
        os.environ["TM_WEB_HOST"] = old_env
    webui._bind_host = old_bind


def _get(base, path, op):
    with op.open(base + path, timeout=6) as r:
        return json.loads(r.read().decode("utf-8"))


def _post(base, path, body, op):
    req = urllib.request.Request(
        base + path, method="POST",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with op.open(req, timeout=8) as r:
        return json.loads(r.read().decode("utf-8"))


def test_config_page_reports_effective_host(live):
    base, _cfg, op = live
    j = _get(base, "/api/config", op)
    assert j["globals"]["host"] == "0.0.0.0", (
        "容器里页面显示 127.0.0.1，服务实际绑 0.0.0.0——状态说谎")


def test_save_does_not_pin_loopback_into_yaml(live):
    import yaml
    base, cfg, op = live
    j = _get(base, "/api/config", op)
    glb = j["globals"]
    # 模拟用户在网页里改了一个热更新项后保存（原样回传页面拿到的 globals）
    glb["interval_minutes"] = 20
    out = _post(base, "/api/config", {"users": j.get("users") or [],
                                      "globals": glb}, op)
    assert out.get("ok"), out
    with open(cfg, encoding="utf-8") as f:
        saved = yaml.safe_load(f)
    host = ((saved.get("web") or {}).get("host") or "")
    assert host == "0.0.0.0", (
        "保存一次配置就把 host=%r 写进 yaml；容器重启后将只绑回环，"
        "端口映射不可达（issue #8 同类的「容器在跑但打不开」）" % host)


# ---- merged from tests/test_r794_capbar_names_gaps.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port










