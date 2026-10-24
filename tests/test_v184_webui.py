# -*- coding: utf-8 -*-
"""v1.5.84 webui 回归（行为级：控制台服务器断连噪音静默）。

观测报表卫生案：浏览器刷新/提前关闭/探针超时会触发 wfile 写回
ConnectionReset/ConnectionAborted/BrokenPipe（10054/10053），socketserver
默认 handle_error 逐条打 traceback 到 stderr——monitor.out.log.err 随使用
刷屏（实测单日 8 处，逐条定性全部为断连噪音、非监控主流程缺陷）。
_Srv.handle_error 覆写契约：断连族静默；其余异常维持默认 traceback
（真缺陷必须可见）。

运行：PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_v184_webui.py -q
"""

import io
import socket
import threading
import time
import urllib.request
from contextlib import redirect_stderr


class TestSrvHandleError:
    """_Srv.handle_error 断连族静默契约。"""

    @staticmethod
    def _srv():
        import webui as _w
        return _w._Srv(("127.0.0.1", 0), _w._Handler)

    def test_client_disconnect_is_silent(self):
        srv = self._srv()
        try:
            err = io.StringIO()
            with redirect_stderr(err):
                try:
                    raise ConnectionResetError(10054, "远程主机强迫关闭了一个现有的连接")
                except ConnectionResetError:
                    srv.handle_error(None, ("127.0.0.1", 51000))
            assert "Traceback" not in err.getvalue(), \
                "断连族仍打 traceback（err 文件刷屏病面未收口）"
        finally:
            srv.server_close()

    def test_real_defect_stays_visible(self):
        srv = self._srv()
        try:
            err = io.StringIO()
            with redirect_stderr(err):
                try:
                    raise ValueError("真缺陷哨兵")
                except ValueError:
                    srv.handle_error(None, ("127.0.0.1", 51000))
            out = err.getvalue()
            assert "Traceback" in out and "真缺陷哨兵" in out, \
                "非断连异常被静默（真缺陷必须可见的契约被破坏）"
        finally:
            srv.server_close()

    def test_server_survives_abrupt_client(self):
        srv = self._srv()
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            # 连上即断（不发请求）：handler 读侧得空串走正常关闭路径
            c = socket.create_connection(("127.0.0.1", port), timeout=5)
            c.close()
            time.sleep(0.2)
            # 服务器必须存活并继续服务后续请求（空代理直连回环）
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(f"http://127.0.0.1:{port}/api/pulse", timeout=10) as r:
                assert r.status == 200
        finally:
            srv.shutdown()
            srv.server_close()


class TestAuditV184Fixes:
    """audit_v184 P1-1/P2-1 源码钉。"""

    @staticmethod
    def _src():
        import webui as _w
        with open(_w.__file__, encoding="utf-8") as f:
            return f.read()

    def test_trend_markmin_price_domain(self):
        src = self._src()
        i0 = src.index("const markMin=")
        seg = src[i0:i0 + 200]
        # 走势「低」标注按价域（p[2]）取 argmin——y 像素域（p[1]）
        # 因 canvas y 向下会反向锚到窗口最高价（决策语义反转）
        assert "p[2]<pts[mi][2]" in seg, "markMin 未按价域取最低"
        assert "p[1]<pts[mi][1]" not in seg, "markMin 仍在 y 像素域比较"

    def test_cal_best_qhit_outline_token(self):
        src = self._src()
        assert ".calcell.best.qhit{outline-color:var(--cal-best-stroke)}" in src, \
            "best×qhit 叠加态缺描边配色分支（绿描边压绿底隐形）"
        # 双主题令牌成对
        assert "--cal-best-stroke:rgba(255,255,255,.8)" in src, "亮色描边令牌缺"
        assert "--cal-best-stroke:rgba(10,15,22,.55)" in src, "暗色描边令牌缺"
