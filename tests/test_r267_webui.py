# -*- coding: utf-8 -*-
"""r267 WebUI 落地案（调研 _scratch/r267_webui.md + 主修档案 r267_lead_findings.md）：

P2-1 停用态空态二分：全停用配置曾被呈现为「还没有监控任务」（回归
用户找心理线配置被误导）——后端 /api/state 产 suspended 轻标记
（纯函数 _suspended_users：运行时 routes 空但 cfg 同名用户航线全部
enabled=False），前端空态分支按二分词面呈现 + pill 同步。
P2-2 空态交互死角：users:[] 时 `!S.users` 真值门全族放行（JS 空数组
真值），pill 点击 jumpQual→buildChips 读 S.users[0].platAge 抛未捕获
TypeError（pageerror 实锤）——门卫族统一收紧 length 门（users 非空时
行为等价，纯收紧零回归）+ showMonTab 空态收敛 overview。
P3-1 空 hero CTA 桌面档吊位 → 块级化独立成行。
P3-2 空态 opscard 回收（立即扫描对零启用航线无作用面）。
P3-3 折行徽标行视觉密度紧凑化（.pretax 折行规则已盖权益徽标——
审计原判「无同律」为误读，缺的只是折行态行距）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_r267_webui.py -q
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webui  # noqa: E402  模块级无副作用（test_v1559 先例）


def _src():
    return open("webui.py", encoding="utf-8").read()


# ---------- P2-1 后端：suspended 轻标记纯函数 ----------

def test_suspended_users_pure_function():
    fn = getattr(webui, "_suspended_users", None)
    assert fn is not None, "_suspended_users 纯函数缺失（P2-1 后端协议未落地）"
    # 全停用用户 → suspended 条目（name/n/routesTxt/dates 四键）
    runtime = [{"name": "张三", "routes": []}]
    cfg = [{"name": "张三", "routes": [
        {"from": "SHA", "from_name": "上海", "to": "URC", "to_name": "乌鲁木齐",
         "dates": ["2026-10-14"], "enabled": False},
        {"from": "URC", "from_name": "乌鲁木齐", "to": "SHA", "to_name": "上海",
         "dates": ["2026-10-15"], "enabled": False},
    ]}]
    got = fn(runtime, cfg)
    # 无 dates 键：前端零消费的死重（routesTxt 已含日期摘要，全量在配置页）
    assert got == [{"name": "张三", "n": 2,
                    "routesTxt": "上海→乌鲁木齐 2026-10-14、乌鲁木齐→上海 2026-10-15"}], got


def test_suspended_users_mixed_and_absent():
    fn = webui._suspended_users
    # 混合态：有启用航线的用户不进 suspended（runtime routes 非空）
    runtime = [{"name": "李四", "routes": [{"from_code": "SHA"}]}]
    cfg = [{"name": "李四", "routes": [
        {"from": "SHA", "from_name": "上海", "to": "SYX", "to_name": "三亚",
         "dates": ["2026-10-20"], "enabled": True},
        {"from": "SYX", "from_name": "三亚", "to": "SHA", "to_name": "上海",
         "dates": ["2026-10-21"], "enabled": False},
    ]}]
    assert fn(runtime, cfg) == [], "有启用航线的用户不得进 suspended"
    # cfg 无同名用户（demo 合成态）→ 恒 []
    assert fn([{"name": "demo用户", "routes": []}],
              [{"name": "张三", "routes": [{"enabled": False}]}]) == []
    # cfg 用户 raw routes 全空（真·从未配置）→ 不进
    assert fn([{"name": "张三", "routes": []}],
              [{"name": "张三", "routes": []}]) == []
    # 启用态矛盾（cfg 有启用但 runtime routes 空=热载窗口）→ 宁缺勿错不进
    assert fn([{"name": "张三", "routes": []}],
              [{"name": "张三", "routes": [
                  {"from": "SHA", "from_name": "上海", "to": "SYX",
                   "to_name": "三亚", "dates": ["2026-10-20"]}]}]) == []
    # 空入参形态
    assert fn([], []) == []
    assert fn(None, None) == []


def test_state_payload_carries_suspended():
    src = _src()
    # _build_state 输出面挂 suspended（键在 out 构造处）
    assert re.search(r'"suspended":\s*_suspended_users\(', src), \
        "/api/state 输出未挂 suspended 键"
    # st.cfg 单一事实源取原始 routes（热载安全——LESSONS 十二§1）
    assert re.search(r'_suspended_users\(\s*users\s*,\s*st\.cfg\.get\("users"\)', src), \
        "suspended 取数未走 st.cfg 单一事实源"


def test_state_cache_invalidated_on_cfg_save():
    """suspended 是 cfg 派生键（签名五元组只含运行时 users 形态，全停
    态下改停用航线配置 users 序列化逐字节不变）——保存端点热重载后
    必须作废签名缓存，否则卡片 routesTxt/dates 陈旧到进程重启。"""
    src = _src()
    assert re.search(
        r'n = st\.reload_cb\(\) if st\.reload_cb else 0\n'
        r'(?:\s*#[^\n]*\n)*\s*_STATE_CACHE\["sig"\] = None', src), \
        "保存端点热重载后未作废 /api/state 签名缓存（cfg 派生键变更不可见）"


# ---------- P2-1 前端：空态二分词面 ----------

def test_empty_state_split_wording():
    src = _src()
    # 停用卡词面（二分新分支）
    assert "航线已全部停用" in src, "停用态空态词面缺失"
    assert "前往配置启用" in src, "停用态 CTA 词面缺失"
    # pill 词面二分
    assert "已全停用" in src, "pill 停用态词面缺失"
    # 教学卡（从未配置档）词面保留
    assert "还没有监控任务" in src, "从未配置教学卡被误删"
    assert "前往配置 →" in src, "教学卡 CTA 被误删"
    # suspended 渲染走 he() 消毒（name/routesTxt 是配置自由文本）——
    # 窗口锁停用卡字面之后的新段（全文件 he(x.name) 有既有消费点，
    # 全局形态匹配会被既有代码满足成半恒真）
    i = src.index("航线已全部停用")
    seg = src[i:i + 900]
    assert re.search(r"he\([a-z]\.name\)", seg) and re.search(r"he\([a-z]\.routesTxt\)", seg), \
        "suspended 渲染段未过 he() 消毒"


# ---------- P2-2：真值门全族收紧 length ----------

def test_gate_family_length_pins():
    src = _src()
    # 12 处真值门收紧后零残留（精确串：users 后紧跟右括号=无 length）
    assert src.count("if(!S||!S.users)") == 0, \
        "真值门残留（JS 空数组真值放行→S.users[U] 读 undefined）：见 r267 P2-2"
    # length 门计数：12 处收紧 + table/chart 既有 2 处
    assert src.count("if(!S||!S.users.length)") == 14, \
        "length 门计数漂移：门族清单见 test 文档头"
    # jumpQual 空态守卫（pill 点击链首）
    jq = src[src.index("function jumpQual(){"):]
    jq = jq[:jq.index("gotoMonTab('details')")]
    assert "!S.users.length" in jq, "jumpQual 空态守卫缺失"
    assert "switchView('cfg')" in jq, "jumpQual 空态应引到配置页"
    # showMonTab 空态收敛 overview（键盘 5/深链瞬态空白 pane 前置收敛）
    smt = src[src.index("function showMonTab("):]
    smt = smt[:smt.index("MONTAB=t;")]
    assert re.search(r"!S\.users\.length&&t!=='overview'", smt), \
        "showMonTab 空态收敛守卫缺失"


def test_buildchips_empty_no_throw_by_node():
    """行为钉：users=[] 时 buildChips 早退不抛（修复前 u.platAge
    TypeError）。抽函数段 node 实执行（test_v1559 先例形态）。"""
    if shutil.which("node") is None:
        sys.exit("node 不在 PATH：无法完成门卫实执行自验")
    src = _src()
    a = src.index("function buildChips(){")
    b = src.index("function togChip(el,p){", a)  # buildChips 之后最近的函数锚
    js = src[a:b]
    assert "function buildChips(){" in js
    probe = js + """
const S={users:[]},U=0,FLT={plats:new Set(),_platsInit:false},
 chipsRefocus=()=>{},$=()=>({innerHTML:''});
buildChips();
console.log('OK no-throw, platsInit='+FLT._platsInit);"""
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as f:
        f.write(probe)
        path = f.name
    try:
        r = subprocess.run(["node", path], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60)
        assert r.returncode == 0, "users=[] 时 buildChips 抛错：\n" + (r.stderr or "")[:400]
        assert "OK no-throw" in (r.stdout or ""), r.stdout
    finally:
        os.unlink(path)


# ---------- P3-1/P3-2/P3-3 ----------

def test_hero_cta_block_level():
    src = _src()
    assert re.search(r"\.hero button\{display:block", src), \
        "空 hero CTA 块级化规则缺失（桌面档吊位）"


def test_opsccard_reclaimed_in_empty_state():
    src = _src()
    # 空态分支回收（立即扫描对零启用航线无作用面）
    assert "$('opscard').style.display='none'" in src, \
        "空态 opscard 回收缺失"
    # 数据态路径恢复（render 每拍重写，空态↔数据态双向自愈）
    assert "$('opscard').style.display=''" in src, \
        "数据态 opscard 恢复点缺失"


def test_pretax_wrapped_stack_compact():
    src = _src()
    # 折行徽标行紧凑化（折行规则已盖全部徽标——补的只是折行态行距）
    assert ":has(.pretax ~ .pretax) .pretax{display:block;margin-top:2px}}" in src, \
        "折行徽标紧凑化规则缺失或形态漂移"
