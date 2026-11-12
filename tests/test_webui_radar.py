# -*- coding: utf-8 -*-
"""由轮号钉归并生成的模块（tests/ 归并工程，映射见 _scratch/w2a_mapping.json）。

本文件按主题收拢下列源文件，测试函数名与原实现逐字保留：
- tests/test_r425_radar_smoothness.py
- tests/test_r850_radar_canvas_scale.py
- tests/test_v295_radar_auto.py
- tests/test_v295_radar_config.py

合并约定：import 区去重合并；每个源文件的模块级语句、辅助函数、
fixture 以 `# ---- merged from ... ----` 分段原样保留；
`if __name__ == "__main__"` 块移至文件尾。
"""
from support_webui_src import webui_full_src

import inspect
import json
import os
import pytest
import socket
import subprocess
import sys
import time
import urllib.request
import webui

from core.storage import PriceStorage
from main import build_users


# ---- merged from tests/test_r425_radar_smoothness.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src():
    import webui
    return webui.PAGE


def test_radar_canvas_can_exceed_viewport():
    """r373 曾把画布宽度锁成可视宽：拖动指令还在、光标还是 grab，
    但 scrollWidth==clientWidth，拖了完全不动 —— 用户读作「滑动卡顿」。
    画布宽必须是「可视宽」与「点数 × 最小间距」取大（带上限）。"""
    src = _src()
    # r850：注释变长后 700 字符窗口会漏掉公式，改为直接全文定位公式。
    seg = src
    # r850：上限系数不再钉死（原 baseW*2.4 会压缩密集采样），
    # 只守「取大(可视宽, 点数×间距, 上限)」的结构。
    assert "const W=Math.max(baseW,Math.min(units*MINPX," in seg, seg
    assert "c.style.width=W+'px';" in seg, seg
    # 溢出时必须真的能横滚
    assert ".spmon-chartwrap{overflow-x:auto;overflow-y:hidden" in src


def test_radar_bitmap_not_reallocated_per_frame():
    """每帧重设 canvas.width/height 等于清空 + 重分配位图，悬停/节流时整幅闪
    一下，读作「不丝滑」。只在尺寸真的变了才重设。"""
    src = _src()
    i = src.index("const _bw=Math.max(1,Math.round(W*dpr))")
    seg = src[i:i + 260]
    assert "if(c.width!==_bw|c.height!==_bh){c.width=_bw;c.height=_bh;}" in seg, seg


def test_radar_gap_is_segmented_not_bridged():
    """「走势一定不可以断档」不是「必须连起来」——真实没数据的时间窗必须
    留空，且两端点要各自可见（否则走势断在看不见的地方）。
    判据：缺口阈值 4 小时，且面积/折线都按缺口分段。"""
    src = _src()
    assert "const _gapMin=4*3600*1000;" in src
    # 主系列面积填充带 gapMin（分段）
    i = src.index("if(low||sel)PCHART.area(ctx,g,x.pts.map")
    seg = src[i:i + 220]
    assert "gapMin:_gapMin" in seg, seg
    # 折线同样分段
    assert src.count("gapMin:_gapMin") >= 2, "折线与面积都应分段"


def test_radar_no_opaque_overlay_above_canvas():
    """用户实报「白白的折叠遮挡短点」。画布所在的 .spmon-chartwrap 里
    除 canvas 外只允许 .spmonChartNote（透明、且在画布外）——
    不得再塞不透明面板/遮罩进去。"""
    src = _src()
    i = src.index('<div class="spmon-chartwrap">')
    seg = src[i:src.index("</div>", src.index("spMonChartNote", i))]
    assert seg.count("<canvas") == 1, seg
    # 允许的覆盖层只有 tip（悬停才显示）、cross（发丝线，无底色）、note（透明）
    for tag in ("spMonTip", "spMonCross", "spMonChartNote", "spMonTable"):
        assert tag in seg, tag
    assert "spmon-fold" not in seg and "spmon-mask" not in seg, seg


def test_demo_health_rows_show_no_fake_rates():
    """用户实报「现在有很多都是补位数据，感觉有点奇怪，确认下真实性和解析
    的正确性」。`--demo` 的分通路账是按合成轮次迭代算的，`查询 97% ·
    明细 x / 日历 y · n 次` 与真实实测读数长得一模一样，会被当成实测引用。
    演示态该半栏只说明「合成样本」，真实实例照常给百分比与次数。

    r466 起判据从 `_demoAll` 收紧为 `_maskSynth = _demoAll && _pthDemo`：
    只看 advice 会把「演示 advice + 真库账本」也遮掉，导致同一页健康卡
    11% 与节流面板「不参与成功率」两数打架。纯演示下两者等价。"""
    src = _src()
    i = src.index("const pathTxt=")
    seg = src[i:i + 400]
    assert "_maskSynth?'':" in seg, "演示态仍在通路串里给百分比"
    # 判据必须同时要求「advice 是演示」与「账本也是合成」
    k = src.index("const _maskSynth=")
    assert "_demoAll&&_pthDemo" in src[k:k + 60], "遮蔽条件丢了账本来源判断"
    j = src.index("const _qbit=_maskSynth")
    q = src[j:j + 420]
    assert "'合成样本 · 不参与成功率'" in q, q
    assert "'查询 <b>'+_rate(_qr)+'</b> · 明细 '" in q, "真实实例的次数口径被误删"
    # _demoAll / _pthDemo 都必须早于这两处定义（TDZ）
    assert src.index("const _demoAll=Object.keys(ch)") < i
    assert src.index("_pthDemo=!!_pj.demo") < i


# ---- merged from tests/test_r850_radar_canvas_scale.py ----

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


PORT = _free_port()
BASE = "http://127.0.0.1:%d" % PORT

JS = r"""() => {
  const pad=n=>String(n).padStart(2,'0');
  const fm=t=>{const d=new Date(t);return d.getFullYear()+'-'+pad(d.getMonth()+1)
    +'-'+pad(d.getDate())+' '+pad(d.getHours())+':'+pad(d.getMinutes());};
  const t0=Date.now()-2*86400e3;
  const mk=(n,stepH,gapAt)=>{
    const out=[];
    for(let i=0;i<n;i++){
      if(gapAt!=null && i>gapAt && i<=gapAt+3) continue;   // 挖掉 3 个采样
      const t=t0+i*stepH*3600e3;
      out.push({at:fm(t), price:1400+Math.round(Math.sin(i/3)*70)+((i*17)%29),
                channel:'ctrip', basis:'tax_included'});
    }
    return out;
  };
  const dense=mk(60,2,null);
  spMonDraw([{date:'11-01', points:dense}], '11-01', '');
  const c=document.getElementById('spMonChart'), g1=SPMON.geo;
  const wrap=c.parentElement;
  const W1=g1.W, scrollW=wrap.scrollWidth, clientW=wrap.clientWidth;

  // 顶点不得被纯白覆盖（「白白的折叠遮挡短点」）
  const ctx=c.getContext('2d'), dpr=window.devicePixelRatio||1;
  let occluded=0;
  g1.series[0].pts.forEach(p=>{
    const x=Math.round(g1.X(p.t)*dpr), y=Math.round(g1.Y(p.p)*dpr);
    const px=ctx.getImageData(Math.max(0,x-3),Math.max(0,y-3),6,6).data;
    let hasInk=false, onlyWhite=false;
    for(let i=0;i<px.length;i+=4){
      if(px[i+3]<10) continue;
      if(px[i]>245&&px[i+1]>245&&px[i+2]>245) onlyWhite=true; else hasInk=true;
    }
    if(onlyWhite && !hasInk) occluded++;
  });
  const im=ctx.getImageData(0,0,c.width,c.height).data;
  let white=0,total=0;
  for(let i=0;i<im.length;i+=4){ total++; if(im[i]>245&&im[i+1]>245&&im[i+2]>245&&im[i+3]>10) white++; }

  // 缺口：挖掉 3 个 2h 采样 = 8h 空窗，中点应几乎无墨
  const gapPts=mk(20,2,10);
  spMonDraw([{date:'11-02', points:gapPts}], '11-02', '');
  const g2=SPMON.geo, c2=document.getElementById('spMonChart'), ctx2=c2.getContext('2d');
  const tA=t0+10*2*3600e3, tB=t0+14*2*3600e3;
  const xa=g2.X(tA), xb=g2.X(tB), xm=(xa+xb)/2;
  const ys=g2.series[0].pts.map(p=>g2.Y(p.p));
  const y0=Math.max(0,Math.floor(Math.min(...ys))-10);
  const y1=Math.min(c2.height-1, Math.ceil(Math.max(...ys))+10);
  const ink=(x)=>{const w=5,xx=Math.max(0,Math.round(x-w/2));
    const d=ctx2.getImageData(xx,y0,w,Math.max(1,y1-y0)).data;
    let k=0; for(let i=3;i<d.length;i+=4) if(d[i]>8) k++; return k;};
  const gapMidInk=ink(xm), atPointInk=ink(xa);

  return {W1, scrollW, clientW, whitePct:+(white/total*100).toFixed(3),
          occluded, ptsN:g1.series[0].pts.length,
          gapMidInk, atPointInk, gapPx:+(xb-xa).toFixed(1)};
}"""




    # pan-x 光标由 spMonPanState() 在 rAF 里打，两次 draw 连跑时第二轮
    # 可能还没轮到；「可滚性」本身就是判据，光标只是它的视觉反映。
    # 单独一条用例在 rAF 落定后核对（见 test_grab_cursor_marks_scrollable）。








def test_canvas_width_is_capped_for_dense_series():
    """r861：真实库一条线可有 500+ 采样点，不能按 30px/点无限展开。

    实测（真实库 URC→SHA，537/611/47 点）：旧公式给 16110~28230px，
    是视口的 12.6~22 倍——一屏只放得下 28 个点，图上大段空白、横轴只剩
    一个刻度，读作「图坏了」。定案：上限按点数给，画布最多约 3 个视口宽；
    点少时仍按 MINPX 展开（上一条用例守）。修后 537 点 ⇒ 3849px（3 倍），
    绘制 0 白像素、1195 顶点无遮挡、拖动 60 帧 p50 17ms 无长任务。
    """
    import re
    import webui
    src = webui.PAGE
    m = re.search(r"const _capW=([^;]+);", src)
    assert m, "找不到画布宽度上限 _capW"
    expr = m.group(1)
    assert "baseW" in expr, "_capW 未按视口宽计算：%s" % expr
    assert re.search(r"const W=Math\.max\(baseW,Math\.min\(units\*MINPX,_capW", src), (
        "公式没有把 _capW 纳入 min()，密集采样会再次拉成细带")


# ---- merged from tests/test_v295_radar_auto.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class _Notifier:
    def __init__(self):
        self.sent = []

    def send(self, title, desp="", **kw):
        self.sent.append((title, desp))
        return True


class _Alerter:
    user = "u"

    def __init__(self):
        self.notifier = _Notifier()

    def _in_quiet(self):
        return False


def _res(price, status="ok"):
    return {
        "dates": [{"date": "2026-11-01", "by_channel": {"ctrip": {
            "price": price, "to": "BJS", "basis": "bare",
            "kind": "calendar", "link": ""}}}],
        "channels": {"ctrip": {"status": status}},
        "query": {"user": "u", "from": "SHA", "to": "BJS",
                  "nationwide": False, "start": "2026-11-01",
                  "end": "2026-11-07", "channels": ["ctrip"]},
    }


def test_auto_seed_then_new_low_alerts_once(tmp_path):
    old_cfg, old_alerters = webui._State.cfg, webui._State.alerters
    old_demo = webui.DEMO["on"]
    webui.DEMO["on"] = False
    al = _Alerter()
    webui._State.cfg = {"output": {"db_path": str(tmp_path / "a.db")}}
    webui._State.alerters = [al]
    PriceStorage(str(tmp_path / "a.db")).set_radar_alert_config(
        "u", {"enabled": True, "drop_min": 50, "threshold": 0,
              "cooldown_h": 12})
    try:
        webui._radar_save_result(_res(500), source="auto")
        assert al.notifier.sent == []
        webui._radar_save_result(_res(450), source="auto")
        assert len(al.notifier.sent) == 1
        st = PriceStorage(str(tmp_path / "a.db"))
        assert len(st.radar_alerts("u")) == 1
        assert st.radar_alerts("u")[0]["kind"] == "new_low"
    finally:
        webui._State.cfg, webui._State.alerters = old_cfg, old_alerters
        webui.DEMO["on"] = old_demo


def test_manual_and_cache_runs_never_alert(tmp_path):
    old_cfg, old_alerters = webui._State.cfg, webui._State.alerters
    old_demo = webui.DEMO["on"]
    webui.DEMO["on"] = False
    al = _Alerter()
    webui._State.cfg = {"output": {"db_path": str(tmp_path / "b.db")}}
    webui._State.alerters = [al]
    try:
        webui._radar_save_result(_res(500), source="manual")
        webui._radar_save_result(_res(400, status="cache_hit"), source="auto")
        assert al.notifier.sent == []       # cached run must not seed/alert
    finally:
        webui._State.cfg, webui._State.alerters = old_cfg, old_alerters
        webui.DEMO["on"] = old_demo


def test_auto_uses_eligible_channels_only(tmp_path):
    old_cfg, old_alerters = webui._State.cfg, webui._State.alerters
    old_demo = webui.DEMO["on"]
    webui.DEMO["on"] = False
    al = _Alerter()
    webui._State.cfg = {"output": {"db_path": str(tmp_path / "c.db")}}
    webui._State.alerters = [al]
    try:
        hit = _res(500)
        hit["channels"]["ctrip"]["cache_hit"] = True
        webui._radar_save_result(hit, source="auto")
        st = PriceStorage(str(tmp_path / "c.db"))
        assert st.radar_alerts("u") == []
        assert st.radar_history("u")["last_run"]["status"] == "cache_hit"
    finally:
        webui._State.cfg, webui._State.alerters = old_cfg, old_alerters
        webui.DEMO["on"] = old_demo


def test_alert_api_and_ui_source_pins():
    src = webui_full_src()
    for s in ("/api/radar/alert-config", "/api/radar/alerts",
              "spRadarAlertOn", "spAlertSave", "提醒：",
              "_radar_eval_alerts", "no_notifier"):
        assert s in src, s


# ---- merged from tests/test_v295_radar_config.py ----

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_build_users_keeps_special_radar_without_routes():
    cfg = {"users": [{"name": "u", "special_radar": {
        "enabled": True, "from": "SHA", "start": "2026-11-01",
        "end": "2026-11-07", "channels": ["ctrip"]}}]}
    users = build_users(cfg)
    assert users and users[0]["special_radar"]["from"] == "SHA"


def test_build_users_legacy_single_user_keeps_special_radar():
    cfg = {"special_radar": {"enabled": True, "from": "SHA",
                             "start": "2026-11-01", "end": "2026-11-07"}}
    users = build_users(cfg)
    assert users and users[0]["special_radar"]["from"] == "SHA"


def test_start_web_exposes_alerters():
    assert "alerters" in inspect.signature(webui.start_web).parameters
    assert hasattr(webui._State, "alerters")
