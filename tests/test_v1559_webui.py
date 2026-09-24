# -*- coding: utf-8 -*-
"""webui 回归（源码级钉死 + _ttc node 实执行）：审计 P2 六项 +
机场 IATA 码（depAirportCode/arrAirportCode）webui 端。

 .glcell 内开关触控热区、 updFltN 补日期维计数、 aria-modal
随 role=dialog 挂 .pvcard、 brief 孤儿键 date 删行（行级同名键合法
保留）、 MAINT 死分支清退、 死 CSS .stat2 清退；新字段：白名单
透传（strip+upper 邻位插键）、_ttc 机场中文旁注渲染门（名含中文才注/
码与名义相同不重注）、CSV 并入「机场/航站楼」列不漂移（32 列锚）、
搜索 hay 两码可检索。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v1559_webui.py -q
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestWebuiV1559Pins:
    """webui.py 源码级钉死（同 test_v1558_webui.py 模式）。"""

    @staticmethod
    def _src():
        import webui as _w
        with open(_w.__file__, encoding="utf-8") as f:
            return f.read()

    @staticmethod
    def _page():
        import webui as _w
        return _w.PAGE

    # ---- .glcell 开关触控热区 ----------

    def test_glcell_switch_hotzone(self):
        """全局参数页 .glcell 内开关（启动即扫/无头/调试日志）本体
        36×20px 低于触控基准——coarse≤900 与 ≤760 两块触控补账各补
::before inset:-8px（.switch 基类自带 position:relative）。"""
        src = self._src()
        rule = ".glcell .switch::before{content:'';position:absolute;inset:-8px}"
        assert src.count(rule) == 3          # 三块触控媒体各一（≤760/≤900/901+），漏一即触控档撕裂
        base = ".srow .sctl .switch::before{content:'';position:absolute;inset:-8px}"
        assert src.count(base) == 3          # 既有 srow 补账不被挪用

    # ---- updFltN 漏计日期维 ----------

    def test_updfltn_counts_dates(self):
        """日历格跳转锁 FLT.dates 后移动端 #fltN 徽标须计数——
         插入位意图为 arr 与 pmin 之间， 起计数主体移入
        try 数据段且形态改全选豁免守卫（FLT.dates==日期全集=零筛选
        不计，与 plats/routes 同构， P2-B）。"""
        src = self._src()
        assert ("if(FLT.arr!=null)n++;\n"
                " if(FLT.pmin||FLT.pmax)n++;") in src
        assert "if(FLT.dates.size&&FLT.dates.size<ds.length)n++;" in src

    # ---- aria-modal 挂 dialog 元素 ----------

    def test_aria_modal_on_pvcard(self):
        """aria-modal 语义须与 role="dialog" 同元素（读屏按 role 定位
        dialog 取语义）——原挂 #pvMask 遮罩上读屏拿不到。静态随 .pvcard
        落 HTML，运行时 setAttribute 入口清零。"""
        page = self._page()
        assert 'role="dialog" aria-modal="true"' in page
        assert page.count('aria-modal="true"') == 1
        assert "_m.setAttribute('aria-modal'" not in self._src()

    # ---- brief 级孤儿键 date ----------

    def test_brief_orphan_date_removed(self):
        """_best_brief 的 "date" 前端零消费（KPI 日期标签全取自
        best_by_date 的 dgroup dlab）——删行。行级白名单同名键合法
        保留（f.date 被筛选/CSV/行 title 多处消费），故只钉 brief 函数体。"""
        src = self._src()
        m = re.search(r"def _best_brief\(f, pool=None\):(.*?)\n\n", src, re.S)
        assert m, "_best_brief 锚点丢失"
        assert '"date"' not in m.group(1)
        assert '"stopTimeT": (f.get("stopTimeT") or "").strip(),\n                "plat":' in src

    # ---- MAINT 死分支清退 ----------

    def test_maint_dead_branch_removed(self):
        """const MAINT={} 恒空无写入方，badge 首个 if 恒假——常量、
        注释与分支三处一并清退（渠道维护信号接入时再按需回补）。"""
        assert "MAINT" not in self._src()

    # ---- 死 CSS .stat2 ----------

    def test_stat2_dead_css_removed(self):
        """.uhead2 .stat2 零消费点（upill 才是现行徽标）——整条规则清退。"""
        assert "stat2" not in self._src()

    # ---- 新字段：白名单透传 ----------

    def test_whitelist_passthrough_codes(self):
        """depAirportCode/arrAirportCode 邻位插在 depAirport/arrAirport
        之后：IATA 恒 3 大写字母，strip+upper 直通不做 int 转写，空串
        不占位同邻键口径。"""
        src = self._src()
        for k in ("depAirportCode", "arrAirportCode"):
            assert f'"{k}": (f.get("{k}") or "").strip().upper(),' in src
        # 邻位：紧随 arrAirport、先于 planeSize
        assert (src.index('"arrAirport": (f.get("arrAirport") or "").strip(),')
                < src.index('"depAirportCode":')
                < src.index('"arrAirportCode":')
                < src.index('"planeSize":'))

    # ---- 新字段：_ttc 渲染门（node 实执行） ----------

    def test_ttc_gate_by_node_exec(self):
        """机场中文旁注：名含中文才注（qunar PC 源 depAirport 现状即
        三字码，城市码 SHA 与机场名双义冲突在案）、码与名义相同不重复
        注（防「SHA (SHA)」）、脏码/空码不注。抽 _apt/_tt/_HAN/_ttc 四段
        用 node 实执行（node --check 先例的执行版）。"""
        if shutil.which("node") is None:
            sys.exit("node 不在 PATH：无法完成 _ttc 实执行自验")
        page = self._page()
        a = page.index("function _apt(s)")
        b = page.index(":b;}") + len(":b;}")
        js = page[a:b]
        for frag in ("function _apt(s)", "function _tt(a,t)",
                     "const _HAN=", "function _ttc(a,t,c)"):
            assert frag in js, frag
        probe = js + """
const r=['上海虹桥|T2|SHA','乌鲁木齐国际机场|T3|URC','SHA||SHA','上海虹桥||SHA',
 '|T2|SHA','上海虹桥|T2|URCS','上海虹桥|T2|','上海虹桥|T2|sha'].map( s=>{const [a,t,c]=s.split('|');return _ttc(a,t,c);});
console.log(JSON.stringify(r));"""
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                         encoding="utf-8") as f:
            f.write(probe)
            path = f.name
        try:
            r = subprocess.run(["node", path], capture_output=True, text=True,
                               encoding="utf-8", timeout=60)
            assert r.returncode == 0, r.stderr[:400]
            got = json.loads(r.stdout)
        finally:
            os.unlink(path)
        assert got == ["上海虹桥T2 (SHA)",    # 中文名+楼号+码旁注（_apt 只剥「机场」后缀，虹桥不在剥除列）
                       "乌鲁木齐T3 (URC)",     # 「国际机场」后缀先剥再注
                       "SHA",                # 码与名义相同：不注（无中文名）
                       "上海虹桥 (SHA)",       # 无楼号只注码
                       "T2",                 # 机场名空：不注
                       "上海虹桥T2",           # 脏码（超 iata3）不注
                       "上海虹桥T2",           # 空码不注
                       "上海虹桥T2"]          # 小写码不注

    # ---- 新字段：CSV 并列不漂移 ----------

    def test_csv_airport_col_merged_not_new(self):
        """两码并入既有第 8 列「机场/航站楼」（_ttc 直出「虹桥T2 (SHA)→
        浦东T2 (PVG)」形），不加新列——列数锚随「退改」列增为 33
        （D-1 有意 +1）；「座椅倾斜」列再 +1 为 34（ctrip seattilt
        舱位物理参数，贴舱位码）；「儿童/婴儿」再 +1 为 35（tuniu
        child/infant 消费端补齐，表尾追加）；裸 _tt 机场槽消费点清零
        （全部换 _ttc）。"""
        page = self._page()
        m = re.search(r"const head=\[(.*?)\];", page, re.S)
        assert m, "CSV 列头锚点丢失"
        assert m.group(1).count(",") + 1 == 35          # 列数锚
        assert "'机场/航站楼'" in m.group(1)             # 列名原位
        assert "_ttc(f.depAirport,f.depTerminal,f.depAirportCode)" in page
        assert "_ttc(f.arrAirport,f.arrTerminal,f.arrAirportCode)" in page
        assert "_tt(f.depAirport,f.depTerminal)" not in page   # 旧裸 _tt 清零

    # ---- 新字段：搜索 hay ----------

    def test_search_hay_includes_codes(self):
        """filteredRows 搜索 hay 追加两码：搜索框可按「PVG/SHA」检索。"""
        page = self._page()
        assert ("' '+f.plat+' '+(f.depAirportCode||'')+' '"
                "+(f.arrAirportCode||'')") in page


# ----------：状态重建不持锁（SWR 不被钉死） ----------

class TestRebuildNoLockFreeze:
    """_build_state 重活（全历史 JSON 解析，生产实测 ~145s）移出锁外：
    异步重建进行中 _STATE_LOCK 必须可即时取得——持锁构建曾把 SWR 回旧值
    的请求整体钉死（每轮扫描后 /api/state 假死 ~2.4 分钟的根因）；
    发布段仍同锁原子落位（body/etag/gz 成对， 撕裂修复语义不变）。"""

    def setup_method(self):
        import webui as _wm
        self.w = _wm
        self._cache = dict(self.w._STATE_CACHE)
        self._building = dict(self.w._STATE_BUILDING)
        self.w._STATE_CACHE.update({"sig": None, "payload": None,
                                    "body": None, "etag": None, "gz": None})

    def teardown_method(self):
        self.w._STATE_CACHE.clear()
        self.w._STATE_CACHE.update(self._cache)
        self.w._STATE_BUILDING.clear()
        self.w._STATE_BUILDING.update(self._building)

    def test_async_build_does_not_hold_lock(self):
        """重建进行中（慢构建窗口）持锁读即时可入；完成后缓存整体换新。"""
        import time as _t
        w = self.w
        w._STATE_CACHE["sig"] = "old"
        w._STATE_CACHE["payload"] = {"v": "stale"}
        real_build = w._build_state

        def slow_build(sig):
            _t.sleep(0.8)               # 模拟 145s 级重活
            real_build(sig)

        orig_sig, orig_us = w._state_signature, w._user_state
        w._state_signature = lambda: "new"
        w._build_state = slow_build
        w._user_state = lambda u: {"k": "fresh"}
        st = w._State
        users_bak, cfg_bak = st.users, st.cfg
        st.users = [{"name": "u", "routes": [{"a": 1}]}]
        st.cfg = {"output": {"db_path": "data/nonexistent-probe.db"}}
        try:
            w._state_rebuild_async()
            _t.sleep(0.25)              # 进入构建中窗口
            t0 = _t.time()
            got = w._STATE_LOCK.acquire(timeout=1.5)
            held = _t.time() - t0
            if got:
                w._STATE_LOCK.release()
            assert got, "重建进行中锁被长期持有（SWR 钉死回归）"
            assert held < 1.2
            deadline = _t.time() + 8
            while _t.time() < deadline:
                if w._STATE_CACHE.get("sig") == "new":
                    break
                _t.sleep(0.1)
            assert w._STATE_CACHE.get("sig") == "new", "重建未完成"
            assert w._STATE_CACHE["payload"]["users"][0]["k"] == "fresh"
        finally:
            st.users, st.cfg = users_bak, cfg_bak
            w._state_signature = orig_sig
            w._user_state = orig_us
            w._build_state = real_build

    def test_swr_returns_stale_immediately(self):
        """有旧值时签名失效：请求即刻回旧值并触发后台重建（零等待）。"""
        import time as _t
        w = self.w
        w._STATE_CACHE["sig"] = "old"
        w._STATE_CACHE["payload"] = {"v": "stale"}
        orig_sig = w._state_signature
        w._state_signature = lambda: "new"
        try:
            t0 = _t.time()
            out = w._latest_state()
            assert _t.time() - t0 < 0.5, "SWR 路径被重建阻塞"
            assert out == {"v": "stale"}
        finally:
            w._state_signature = orig_sig


class TestColdStartNoDeadlock:
    """冷启动（缓存全空）时 /api/state 必须能在构建完成后返回——首版
     修复把冷路径等待写在 _latest_state_snap 的锁区内，与构建
    线程发布段互等死锁（CI uitest 实锤：demo 首请求永挂）。"""

    def setup_method(self):
        import webui as _wm
        self.w = _wm
        self._cache = dict(self.w._STATE_CACHE)
        self._building = dict(self.w._STATE_BUILDING)
        self.w._STATE_CACHE.update({"sig": None, "payload": None,
                                    "body": None, "etag": None, "gz": None})
        self.w._STATE_BUILDING["on"] = False

    def teardown_method(self):
        self.w._STATE_CACHE.clear()
        self.w._STATE_CACHE.update(self._cache)
        self.w._STATE_BUILDING.clear()
        self.w._STATE_BUILDING.update(self._building)

    def test_cold_snap_returns_after_build(self):
        import time as _t
        import threading as _th
        w = self.w
        real_build = w._build_state

        def slow_build(sig):
            _t.sleep(0.5)
            real_build(sig)

        orig_sig, orig_us = w._state_signature, w._user_state
        w._state_signature = lambda: "cold-sig"
        w._build_state = slow_build
        w._user_state = lambda u: {"k": "cold"}
        st = w._State
        users_bak, cfg_bak = st.users, st.cfg
        st.users = [{"name": "u", "routes": [{"a": 1}]}]
        st.cfg = {"output": {"db_path": "data/nonexistent-probe.db"}}
        try:
            done = {}

            def ask():
                body, etag, gz = w._latest_state_snap()
                done["ok"] = body is not None

            th = _th.Thread(target=ask, daemon=True)
            th.start()
            th.join(timeout=15)
            assert done.get("ok"), "冷启动 /api/state 死锁（15s 未返回）"
        finally:
            st.users, st.cfg = users_bak, cfg_bak
            w._state_signature = orig_sig
            w._user_state = orig_us
            w._build_state = real_build
