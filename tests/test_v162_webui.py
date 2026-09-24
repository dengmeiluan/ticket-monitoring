# -*- coding: utf-8 -*-
"""webui 回归（源码级钉 + /api/test-imghost 真请求）。

 图床卡「测试上传」（前端按钮 + JS + 后端直调所选床上传函数，绕开
upload_chart 降级链防假绿）； ≥1920 档 statline/pulsewrap/pulseLegend
放开 --kpiw；P2 批：①esc 补 &<> + importCfg dates 归一 ②末用户删除
残留回收 ③弹层开启快捷键守卫 ④AA 对比度（--ok-txt/--warn-deep）⑤NEAR
注释锚归 core.alerter ⑥open 改 with ⑦搜索索引 rhead ⑧.tgbox ≤760 放宽。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v162_webui.py -q
"""
import json
import os
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestWebuiV162Pins:
    """webui.py 源码级钉死（同 test_v1558_webui.py 模式）。"""

    @staticmethod
    def _src():
        import webui as _w
        with open(_w.__file__, encoding="utf-8") as f:
            return f.read()

    # ---- 图床「测试上传」 ----------

    def test_imghost_test_upload_frontend(self):
        src = self._src()
        assert "function testImghost(" in src          # 仿 testNtfy guard+busy+toast
        assert "testImghost(${i},this)" in src         # 卡内按钮（用表单当前值）
        assert "/api/test-imghost" in src              # POST 端点
        assert "请先填写 sm.ms Token" in src           # 对齐 saveCfg 同款拦截词面

    def test_imghost_test_upload_backend_direct_call(self):
        src = self._src()
        assert '"/api/test-imghost"' in src
        # 直调所选床：不走 upload_chart——freeimage 连败记忆会静默降级
        # pixhost，走降级链 = 测试假绿（备案 核心约束）
        assert "from report import upload_freeimage, upload_smms" in src
        assert "upload_chart(" not in src
        # freeimage 死时 upload_freeimage 内部降级 pixhost：URL 含 pixhost
        # = 主床不可用，测试端必须如实报败
        assert '"pixhost" in url' in src
        assert "iVBORw0KGgo" in src                    # 1×1 PNG 内存图常量

    # ---- kpiw 空腔收敛 ----------

    def test_kpiw_1920_release_non_proportional_parts(self):
        src = self._src()
        assert ".statline,#pulseLegend,.pulsewrap{max-width:none}" in src
        # .grid/.kpisum 保持 1168 纪律（KPI 价卡过扁失比，取舍成立）
        assert ".kpisum{max-width:var(--kpiw)}" in src

    # ---- esc 补转义 + importCfg 归一 ----------

    def test_esc_escapes_ampersand_angle_brackets(self):
        src = self._src()
        # & 必须最先转义（防把后续产生的实体再转一次）
        assert (".replace(/&/g,'&amp;').replace(/</g,'&lt;')"
                ".replace(/>/g,'&gt;')") in src
        # 引号转义保留（delDate 等 JS 单引号上下文调用面依赖）
        assert ".replace(/\"/g,'&quot;').replace(/'/g,'&#39;')" in src

    def test_import_cfg_dates_normalized(self):
        # 导入文件是不归一路径：dates 过 addDate 同款 _normDate，丢非法项
        assert "(r.dates||[]).map(_normDate).filter(Boolean)" in self._src()

    # ---- 末用户删除残留回收 ----------

    def test_empty_users_hides_pulsecard_userpills(self):
        src = self._src()
        assert "$('pulsecard').style.display='none'" in src
        assert "$('userPills').style.display='none'" in src

    # ---- 弹层开启快捷键守卫 ----------

    def test_hotkey_guard_when_modal_open(self):
        src = self._src()
        # Ctrl+S 分支之后、数字键/R// 分发之前：R 两段确认=后台真触发
        # 全量扫描，弹层开着必须挡
        assert "if($('pvMask').classList.contains('on'))return;" in src

    # ---- AA 对比度 ----------

    def test_aa_ok_text_and_warn_deep_tokens(self):
        src = self._src()
        assert "--ok-txt:#0b6e39" in src               # 对 --okbg 5.63:1（原 4.28 欠 AA）
        assert "--warn-deep:#6f5600" in src            # 对 --headbg 6.21:1（原 4.42 欠 AA）
        assert ".pill.ok{background:var(--okbg);color:var(--ok-txt)" in src
        assert ".hbadge.ok{color:var(--ok-txt)" in src
        assert ".upill.ok{color:var(--ok-txt)" in src
        assert ".chip .bd.mid{color:var(--warn-deep)}" in src
        # 暗色成对换谱（暗底原值已过 AA，外观不变）
        assert "--ok-txt:#43c072" in src
        assert "--warn-deep:#d9b34a" in src

    # ---- NEAR 注释锚 ----------

    def test_near_comment_anchor_single_source(self):
        src = self._src()
        assert "report.py NEAR_RATIO" not in src       # 旧锚清零（单源已迁 core.alerter）
        assert "core.alerter NEAR_RATIO=0.10" in src

    # ---- open 改 with ----------

    def test_read_open_uses_with(self):
        src = self._src()
        assert "_j.load(open(" not in src              # /notify 两处
        assert "_y.safe_load(open(" not in src         # GET/POST /api/config 两处

    # ---- 搜索索引 rhead ----------

    def test_cfg_search_indexes_rhead(self):
        src = self._src()
        assert "rl.querySelector('.rhead')" in src     # rhead 摘要并入索引面
        # rhead 独命中计入 cfgHits（防空卡配「无匹配项」假阴性）
        assert "if(rhm){n++;" in src

    # ---- tgbox 窄屏 ----------

    def test_tgbox_narrow_viewport_release(self):
        src = self._src()
        assert ".tgbox{display:block;max-width:460px}" in src   # 基础档保留
        # ≤760 档放宽（≤480 视口 460px 上限把明细表顶出横向滚动）
        assert "@media(max-width:760px){.tgbox{max-width:100%}}" in src


class TestTestImghostEndpoint:
    """/api/test-imghost 真请求（守卫分支，不触外网）。"""

    @staticmethod
    def _post(payload):
        import webui as _w
        srv = ThreadingHTTPServer(("127.0.0.1", 0), _w._Handler)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:%d/api/test-imghost" % srv.server_address[1],
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        finally:
            srv.shutdown()
            srv.server_close()

    def test_unknown_provider_rejected(self):
        st, j = self._post({"provider": "pixhost", "token": ""})
        assert st == 200 and j["ok"] is False and "未知图床" in j["err"]

    def test_smms_without_token_rejected(self):
        st, j = self._post({"provider": "smms", "token": "  "})
        assert st == 200 and j["ok"] is False and "Token" in j["err"]

    def test_demo_mode_blocked(self):
        import webui as _w
        saved = _w.DEMO["on"]
        _w.DEMO["on"] = True
        try:
            try:
                st, j = self._post({"provider": "freeimage", "token": ""})
            except urllib.error.HTTPError as e:
                st = e.code
                j = json.loads(e.read().decode("utf-8"))
            assert st == 403 and j.get("demo") is True
        finally:
            _w.DEMO["on"] = saved
