# -*- coding: utf-8 -*-
"""静态在线演示站烘焙：把 --demo 控制台打成零后端单文件 index.html。

原理：core/demo 生成确定性合成库 → 走真实 _latest_state/_preview_payload
渲染链取数 → 内嵌为 window.__BAKED__ + fetch() 拦截 shim——
页面 JS 一行不改，离线双击 / GitHub Pages / 任意静态托管即完整可玩。

用法：python docs/demo_build.py        # 产出 docs/site/index.html
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webui  # noqa: E402
from core.demo import build_demo_db, demo_cfg, demo_health, demo_routes  # noqa: E402
from core.models import Route  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "site", "index.html")

SHIM = """
/* ===== 在线演示烘焙层：fetch 拦截 → 内嵌数据（真实控制台这些请求打到本地 API） ===== */
window.__BAKED__=%s;
(function(){const B=window.__BAKED__;
 const J=o=>new Response(JSON.stringify(o),{status:200,
  headers:{'Content-Type':'application/json; charset=utf-8'}});
 window.fetch=function(u,o){u=String(u);
  if(u.indexOf('/api/state')===0)return Promise.resolve(J(B.state));
  if(u.indexOf('/api/health')===0)return Promise.resolve(J(B.health));
  if(u.indexOf('/api/preview')===0)return Promise.resolve(J(B.preview));
  if(u.indexOf('/api/logtail')===0)return Promise.resolve(J(B.logtail));
  if(u.indexOf('/api/config')===0)return Promise.resolve(J(B.config));
  return Promise.resolve(J({ok:false,demo:true,
   err:'在线演示为静态烘焙页——此操作在真实控制台（本地运行）可用'}));
 };})();
"""


def build():
    db = os.path.join(tempfile.gettempdir(), "ticket_demo_bake.db")
    build_demo_db(db)
    webui._State.cfg = demo_cfg(db)
    webui._State.users = [{
        "name": "演示用户",
        "routes": [Route(
            from_code=r["from"], from_name=r["from_name"],
            to_code=r["to"], to_name=r["to_name"], dates=r["dates"],
            alert_direct=r["alert_direct"],
            alert_transfer=r["alert_transfer"],
            transfer_arrival_max=r["transfer_arrival_max"],
            dep_time_min=r["dep_time_min"], dep_time_max=r["dep_time_max"])
            for r in demo_routes()],
        "platforms": ["qunar", "ctrip", "fliggy", "tongcheng", "tuniu"],
        "notifier": {"dingtalk": {"at_mobile": "138****1234"}},
        "schedule": {"interval_minutes": 15},
    }]
    import main as _m
    webui._State.version = _m.__version__ + "-demo"
    state = webui._latest_state()
    state["demo"] = True
    baked = {
        "state": state,
        "health": demo_health(),
        "preview": webui._preview_payload(0),
        "logtail": {"ok": True, "demo": True, "lines": [
            "2026-09-09 14:00:00 [INFO] ticket-monitor: ===== 开始一轮扫描（1 用户 / 3 航线） =====",
            "2026-09-09 14:00:17 [INFO] ticket-monitor: [qunar] 2026-09-25 最低价 ￥1850（航班明细 70 条：直飞 44 / 中转 26）",
            "2026-09-09 14:00:45 [INFO] ticket-monitor: ===== 本轮扫描结束 =====",
        ], "plat": "qunar", "ts": "2026-09-09 14:00"},
        "config": {"users": [{
                       "name": "演示用户",
                       "routes": [{"from": "SHA", "from_name": "上海",
                                   "to": "URC", "to_name": "乌鲁木齐",
                                   "dates": ["2026-09-25"],
                                   "alert_direct": 1900,
                                   "alert_transfer": 1700}],
                       "notifier": {"dingtalk": {"enabled": False}},
                       "platforms": ["qunar", "ctrip", "fliggy",
                                     "tongcheng", "tuniu"]}],
                   "city": {}, "demo": True,
                   "globals": {"interval_minutes": 15, "jitter_minutes": 5,
                               "port": 8765, "headless": True}},
    }
    shim = SHIM % json.dumps(baked, ensure_ascii=False)
    page = webui.PAGE
    assert "<script>" in page, "PAGE 结构变化，找不到注入点"
    page = page.replace("<script>", "<script>" + shim, 1)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(page)
    print("baked:", OUT, "(%.0f KB)" % (os.path.getsize(OUT) / 1024))


if __name__ == "__main__":
    build()
