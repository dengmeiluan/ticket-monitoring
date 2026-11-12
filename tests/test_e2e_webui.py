# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r235_webui_axis.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import os
import pytest
import socket
import subprocess
import sys
import time
import urllib.request


# ---- merged from tests/test_r235_webui_axis.py ----

pytest.importorskip("playwright",
                    reason="行为钉依赖 playwright（缺库 SKIP 不 ERROR）")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 现取空闲端口：固定 8797 在并发全量下会被别模块的 legacy 清理误杀
PORT = None
BASE = None


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_up():
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(40):
        try:
            op.open(BASE + "/api/state", timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False






# 样本：直飞 3 点（窗头→窗中→窗尾），中转 2 点仅在窗尾。
# 时刻并集 5 个：中转首点 '10-02 04:00' 的轴位 = 3/4（右带），
# 索引式旧码会把它画在 i=0/(N-1)=0（左缘）。
_SPARSE = ("const cr=curRoute();cr.range='48h';cr.r.history="
           "{direct:[['10-01 08:00',1000,0],['10-01 20:00',1010,0],"
           "['10-02 08:00',1020,0]],"
           "transfer:[['10-02 04:00',900,0],['10-02 08:00',950,0]]};"
           "cr.r.th={direct:800,transfer:800};")












def test_tset_sort_consumes_axtkey():
    """消费点锁（变异验证补钉）：直调钉只证排序键函数正确，
    tset 排序必须真实消费 axTKey——还原字典序变异时本钉红。"""
    import os as _os
    import pathlib as _pl
    src = webui_full_src()
    assert "axTKey(a,Date.now())" in src and "axTKey(b,Date.now())" in src,         "tset 排序未消费跨年感知排序键"




