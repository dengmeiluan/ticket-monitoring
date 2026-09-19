# -*- coding: utf-8 -*-
"""伴生本地控制台（多租户版）：纯标准库 HTTP 服务（127.0.0.1），随监控常驻

页面能力：每用户状态卡与仪表 / 多航线可切走势图（canvas 自绘+悬停十字线）/
航班明细表（日期列·筛选·排序·同班跨渠道比价展开）/ 下轮倒计时 /
智能刷新（响应不变不重渲染，页面隐藏暂停）/ 一键立即抓取、一键推送走势报告。
"""
import gzip
import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from core.alerter import (Alerter, _qual_price, FLIGGY_TAX_PAD,
                          xchan_phantom_idx, NEAR_RATIO)
from report import _rounds, recent_platform_flights, _daily_minima

# 仓库根锚定（v1.5.49 CWD 漂移免疫家族，与 main._SENT_PATH 同族收口）：
# 与 main 同进程但 db/log/notify 读取曾按 CWD 解析——main 锚定后单向
# 分叉，CWD 漂移时 sqlite3.connect 会在错误路径静默新建空库（写副作用）
_ROOT = os.path.dirname(os.path.abspath(__file__))


def _anchored(p, default):
    """相对路径锚定仓库根（绝对路径原样）。"""
    p = (str(p) if p else "").strip() or default
    return p if os.path.isabs(p) else os.path.join(_ROOT, p)


# 演示模式（python webui.py --demo）：/api/* 走合成数据，POST 全部只读拦截
DEMO = {"on": False}


def _dur_min(txt) -> int:
    """'5时25分'/'5小时25分'/'5h25m' → 分钟数；解析不出返回 0。"""
    m = re.match(r"\s*(\d+)\s*(?:小时|[时hH])\s*(?:(\d+)\s*分?m?)?", str(txt or ""))
    if not m:
        return 0
    return int(m.group(1)) * 60 + int(m.group(2) or 0)

PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="description" content="自托管多渠道机票价格监控：五渠道明细、达标强提醒、配置全热加载">
<meta name="theme-color" content="#0b62d6">
<script>
/* reduced-motion 全局开关：CSS 动画已由 @media 全禁，JS 动画（count-up/
   图表擦除）在此同样直取终值（v1.5.41） */
const RM=window.matchMedia&&window.matchMedia('(prefers-reduced-motion:reduce)').matches;
/* 主题预置（与 NOTIFY 轻页同款）：渲染前落 data-theme 防暗色首屏白闪——
   此前主题落位脚本在 body 末尾，暗色用户每次打开先闪一屏白 */
(function(){var t='auto';try{t=localStorage.getItem('jptheme')||'auto'}catch(e){}
 var dark=t==='dark'||(t!=='light'&&window.matchMedia
   &&window.matchMedia('(prefers-color-scheme:dark)').matches);
 document.documentElement.dataset.theme=dark?'dark':'light';})();
</script>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ctext y='0.9em' font-size='90'%3E%E2%9C%88%EF%B8%8F%3C/text%3E%3C/svg%3E">
<title>机票监控台</title>
<style>
 /* ===== V15「签派控制台」设计语言：数字即主角（mono）、hairline 分区、扁平精密仪表 ===== */
 :root{--blue:#0b62d6;--orange:#c96a10;--red:#c22a2e;--green:#0e8345;
       --okrgb:14,131,69;   /* 绿档通道令牌：rgba(var(--okrgb),α) 消费（描边/底/晕全谱），暗色随 #43c072 换谱 */
       --bg:#eceff4;--card:#ffffff;--tx:#141f2b;--mut:#617384;--tx2:#3d4e5f;
       --line:#dde3ea;--line2:#cbd4de;--headbg:#eef2f7;--hover:#e8edf3;--rowalt:#f5f8fb;
       --stl:#c0561a;--okbg:#e9f4ec;--warn:#9a7800;--ok-strong:#1e8e3e;--okzone:rgba(var(--okrgb),.14);
       --warnbd:rgba(154,120,0,.45);--warnbg:rgba(154,120,0,.10);--xzone:rgba(154,120,0,.13);
       --redbd:rgba(194,42,46,.32);--redbdh:rgba(194,42,46,.55);--redbg:rgba(194,42,46,.08);
       --thline:#8a6d1f;   /* 中转达标虚线：与 --orange 曲线异色可分（图例同源） */
       --fill:#0b62d6;--fill2:#2f83ea;          /* 实心选中底：暗色换深蓝保白字对比 */
       --fill-t:#b05a00;                        /* 实心选中底·橙系（中转 tag）：白字 11px 需 ≥4.5:1 */
       --ring:rgba(11,98,214,.14);--glow:rgba(11,98,214,.45);
       --c-qunar:#2f7fe0;--c-fliggy:#e07f2a;--c-ctrip:#0f8f8f;
       --c-tongcheng:#8250df;--c-tuniu:#d29922;   /* 渠道识别色：全组件同谱 */
       --sh1:0 1px 2px rgba(20,31,43,.05);
       --sh2:0 6px 18px -6px rgba(20,31,43,.12);
       --sh3:0 16px 40px -12px rgba(20,31,43,.22);
       --r:14px;--r2:11px;--r3:9px;
       --kpiw:992px;   /* KPI/脉冲区限宽单源：1440/1600 档在下方 media 覆写 */
       --num:"Cascadia Mono","Consolas","SF Mono","Menlo",monospace}
 *{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
 /* 原生控件（time/checkbox/滚动条）跟随页面主题，不随系统深浅漂移 */
 html{color-scheme:light}
 html[data-theme="dark"]{
  color-scheme:dark;
  --bg:#0a0f16;--card:#101823;--tx:#dbe4ee;--mut:#7f92a6;--tx2:#a9b9ca;
  --line:#1e2a3a;--line2:#2a3a50;--headbg:#141d2a;--hover:#182430;--rowalt:#0f1722;
  --blue:#63a4f8;--orange:#e6922e;--red:#ef5350;--green:#43c072;--stl:#e08555;--okbg:#12241a;--ok-strong:#6fd693;
  --okrgb:67,192,114;   /* 同谱 #43c072：与 tr.qual 暗色覆写 rgba(67,192,114,…) 同源 */
  --okzone:rgba(67,192,114,.16);   /* 走势图例色票/canvas 区间填充：暗底提一档可辨 */
  --warn:#d9b34a;--thline:#d4b75c;
  --warnbd:rgba(217,179,74,.50);--warnbg:rgba(217,179,74,.12);--xzone:rgba(217,179,74,.10);
  --redbd:rgba(239,83,80,.38);--redbdh:rgba(239,83,80,.62);--redbg:rgba(239,83,80,.10);
  --fill:#2c67ba;--fill2:#3f82d8;   /* 暗色实心底用深蓝：白字对比 ≥4.5:1（--blue 太浅） */
  --fill-t:#8a5f10;                 /* 暗色橙系实心底：#e6922e 白字仅 2.47:1 不达标 */
  --ring:rgba(99,164,248,.2);--glow:rgba(99,164,248,.32);
  --c-qunar:#5b9cf0;--c-fliggy:#e89a4d;--c-ctrip:#3ab0b0;
  --c-tongcheng:#a988e0;--c-tuniu:#e0b04d;
  --sh1:0 1px 2px rgba(0,0,0,.35);
  --sh2:0 6px 18px -6px rgba(0,0,0,.5);
  --sh3:0 16px 40px -12px rgba(0,0,0,.65)
 }
 /* 嵌套写法（html[data-theme]{body{...}}）依赖 Chrome 112+ CSS Nesting，
    提出为平级选择器（放原规则之后，特异性 (0,1,2) 恒压通用 body/canvas） */
 html[data-theme="dark"] body{background:var(--bg)}
 html[data-theme="dark"] canvas{filter:brightness(.97)}
 body{font-family:"Segoe UI Variable Text","Segoe UI","Microsoft YaHei","PingFang SC",sans-serif;
      margin:0;color:var(--tx);background:var(--bg);transition:background .3s}
 .wrap{max-width:1180px;margin:0 auto;padding:0 18px 18px}
 /* header：通栏扁平仪表条（hairline 底边，sticky）。
    scroll-padding 让聚焦/锚点滚动不被 header 盖住；投影让"内容从栏下滑过"有层次 */
 html{scroll-padding-top:72px}
 header{background:var(--card);border-bottom:1px solid var(--line2);color:var(--tx);
        padding:11px 18px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;
        position:sticky;top:0;z-index:50;box-shadow:var(--sh2);
        margin:0 -18px 4px}
 header h1{margin:0;font-size:14px;font-weight:700;letter-spacing:1.2px;
           display:flex;align-items:center;gap:10px;text-transform:uppercase}
 .logo{width:30px;height:30px;border-radius:var(--r3);flex:none;
       background:var(--tx);color:var(--card);
       display:inline-flex;align-items:center;justify-content:center;font-size:15px}
 .pill{font-size:13px;font-weight:700;background:var(--headbg);color:var(--tx2);
       padding:6px 14px;border-radius:var(--r3);border:1px solid var(--line);
       display:inline-flex;align-items:center;gap:8px;font-variant-numeric:tabular-nums}
 .pill::before{content:'';width:7px;height:7px;border-radius:50%;background:#93a3b4;flex:none}
 .pill.ok{background:var(--okbg);color:var(--green);border-color:rgba(var(--okrgb),.35)}
 .pill.ok::before{background:var(--green);animation:pulse 1.8s ease-in-out infinite}
 @keyframes pulse{0%,100%{box-shadow:0 0 0 0 rgba(var(--okrgb),.45);opacity:1}
                  50%{box-shadow:0 0 0 4px rgba(var(--okrgb),0);opacity:.55}}
 .muted{color:var(--mut);font-size:12px;font-weight:500}
 /* 分区标签：编号 + 中文 + 英文小签（签派台分区语言） */
 .seclab{display:flex;align-items:baseline;gap:9px;margin:22px 2px 9px;
         border-bottom:1px solid var(--line);padding-bottom:7px}
 .seclab .no{font-family:var(--num);font-size:11px;color:var(--mut);letter-spacing:1px}
 .seclab .zh{font-size:14px;font-weight:700;letter-spacing:.5px}
 .seclab .en{font-size:10px;letter-spacing:2px;color:var(--mut);text-transform:uppercase}
 /* 卡内嵌用：脱掉分区条的边距与底线（曾 7 处复制内联，收编于此） */
 .seclab.inline{margin:0;border:none;padding:0}
 .ucard{background:var(--card);border:1px solid var(--line);border-radius:var(--r);
        padding:15px 18px;margin:0 0 12px;box-shadow:none;transition:border-color .2s}
 .ucard:hover{border-color:var(--line2)}
 .kpi{transition:transform .15s,border-color .2s,background .2s;border:1px solid var(--line);
      border-radius:var(--r2);padding:13px 16px;position:relative;overflow:hidden;background:var(--card)}
 /* 整卡可点：有行情链接（numlink）的卡加 clk 类整卡打开同目标，
    卡内数字链接保留（点击锚点不重复开窗）；无链接卡不显 pointer。
    role="link" 已删——div 不可聚焦，link 语义与键盘现实矛盾 */
 .kpi.clk{cursor:pointer}
 .kpi.clk:hover{transform:translateY(-2px);box-shadow:var(--sh2)}
 /* 达标态：okbg 底 + 绿实线包边（签派台的"可出手"灯） */
 .kpi.hit{background:var(--okbg);border-color:rgba(var(--okrgb),.45);
      box-shadow:0 2px 14px rgba(var(--okrgb),.12)}
 .kpi.hit::before{content:'';position:absolute;left:0;top:0;bottom:0;width:3px;
      background:linear-gradient(180deg,var(--green),rgba(var(--okrgb),.25))}
 button:active{transform:scale(.96)}
 .rngchip:hover{background:var(--hover)}
 .uhead{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px}
 .uname{font-size:15px;font-weight:700;letter-spacing:.3px}
 .udot{width:9px;height:9px;border-radius:50%;display:inline-block;margin-right:7px;
   background:var(--line2);vertical-align:1px}
 .udot.hit{background:var(--green);animation:hitpulse 1.6s ease-in-out infinite}
 .uroutes{color:var(--mut);font-size:12px}
 .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));
       gap:12px;margin-top:10px}
 /* 1fr 轨道填满容器：KPI 双卡左缘与卡内下方 statline/mchips 全宽贴边
    对齐（v1.5.39）；460px 上限+居中曾让概览恒 2 卡整体内缩错位 */
 .kpi .lab{font-size:11px;color:var(--mut);letter-spacing:.8px}
 .kpi .fb{color:var(--tx2);font-size:12px;margin-top:2px}
 .xrow td{background:var(--xzone);color:var(--tx2);font-size:12px;white-space:normal}
 .erow td{padding:34px 16px;text-align:center;color:var(--mut);font-size:13px;letter-spacing:.02em}
 .bagtag{display:inline-block;margin-left:6px;padding:1px 7px;border-radius:var(--r3);
   border:1px solid var(--green);color:var(--green);font-size:10.5px;font-weight:600;
   vertical-align:1px}
 .stoptag{display:inline-block;margin-left:6px;padding:1px 7px;border-radius:var(--r3);
   border:1px solid var(--mut);color:var(--mut);font-size:10.5px;font-weight:600;
   vertical-align:1px}
 .stl.lay.ok{color:var(--green)}
 /* 衔接「停X」小字默认走 --stl 警示色（未达下限）：.stl 基类改中性灰
    后衔接警示语义在此保留（.ok 覆写为绿） */
 .stl.lay{color:var(--stl)}
 .kpi .num{font-family:var(--num);font-size:clamp(24px,2.4vw,31px);font-weight:600;margin:3px 0 1px;
           letter-spacing:-1px;font-variant-numeric:tabular-nums}
 .kpi.d .num{color:var(--blue)}.kpi.t .num{color:var(--orange)}
 /* 达标卡数字随语义转绿（旧版绿卡上蓝/橙大数字信号混杂） */
 .kpi.hit .num{color:var(--green)}
 .bar{height:6px;border-radius:4px;background:var(--line);overflow:hidden;margin-top:6px}
 .bar i{display:block;height:100%;border-radius:4px}/* width transition 已死：innerHTML 整卡重建，过渡从不触发 */
 .kpi.d .bar i{background:var(--blue)}
 .kpi.t .bar i{background:var(--orange)}
 .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:4px}
 button{background:linear-gradient(180deg,var(--fill2),var(--fill));color:#fff;border:none;
        border-radius:var(--r3);padding:9px 17px;font-size:13px;font-weight:600;cursor:pointer;
        transition:.15s;box-shadow:0 1px 3px var(--glow)}
 button:hover{filter:brightness(1.1);box-shadow:0 3px 10px var(--glow)}
 button:active{box-shadow:none}
 button.warn{background:var(--card);color:var(--blue);border:1px solid var(--line2);
        box-shadow:var(--sh1);font-weight:600}
 button.warn:hover{background:var(--headbg);filter:none;box-shadow:var(--sh2)}
 canvas{width:100%;height:clamp(240px,38vh,360px);display:block}
 .legend{display:flex;gap:16px;font-size:12px;color:var(--mut);margin-top:6px;flex-wrap:wrap}
 .legend b{display:inline-block;width:18px;height:4px;border-radius:2px;vertical-align:middle;margin-right:5px}
 .tabs{display:flex;gap:6px;margin:10px 0;align-items:center;flex-wrap:wrap}
 .tabs span{padding:6px 14px;border-radius:var(--r3);cursor:pointer;font-size:12.5px;
   background:var(--headbg);color:var(--mut);border:1px solid var(--line);
   font-weight:600;transition:.15s;user-select:none}
 .tabs span:hover{color:var(--tx2)}
 .tabs span.on{background:var(--fill);color:#fff;border-color:transparent;
   box-shadow:0 2px 8px -2px var(--glow)}
 .tw{overflow:auto;max-height:clamp(430px,52vh,780px);border-radius:10px;border:1px solid var(--line)}
 table{border-collapse:collapse;width:100%;font-size:13px;background:var(--card)}
 th{position:sticky;top:0;background:var(--headbg);color:var(--tx2);font-weight:600;
    font-size:11px;letter-spacing:.8px;z-index:3}
 th,td{padding:9px 10px;text-align:left;white-space:nowrap;border-bottom:1px solid var(--line)}
 /* 列宽节奏锚点：富余宽度给航班/中转列，防「类别虚胖、航班独大」
    （1512px 实测航班列曾 321px/29% 而类别列 93px 只装 46px 内容） */
 #ftable th:nth-child(1),#ftable td:nth-child(1){width:96px}
 #ftable th:nth-child(2),#ftable td:nth-child(2){width:64px}
 #ftable th:nth-child(4),#ftable td:nth-child(4){width:24%}
 tbody tr{transition:background .12s}
 tbody tr:hover{background:var(--hover)}
 /* 空态行不吃 hover 高亮（整行提示文字，非可点数据行） */
 #ftable tbody tr.erow:hover{background:transparent}
 /* 达标行=可出手语义（与推送图同语言）：浅绿底+左绿条，价格绿色加粗 */
 tr.qual{background:rgba(var(--okrgb),.08);box-shadow:inset 3px 0 0 var(--green)}
 tr.qual:hover{background:rgba(var(--okrgb),.14)}
 tr.qual td{color:var(--tx)}
 tr.qual td.price{color:var(--green);font-weight:800}
 html[data-theme="dark"] tr.qual{background:rgba(67,192,114,.13)}
 html[data-theme="dark"] tr.qual:hover{background:rgba(67,192,114,.2)}
 .tag{border-radius:20px;padding:3px 10px;font-size:11px;color:#fff;font-weight:600;
   letter-spacing:.5px}
 .pdot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;
   vertical-align:1px;background:var(--mut)}
 .pdot.qunar{background:var(--c-qunar)}.pdot.fliggy{background:var(--c-fliggy)}
 .pdot.ctrip{background:var(--c-ctrip)}.pdot.tongcheng{background:var(--c-tongcheng)}
 .pdot.tuniu{background:var(--c-tuniu)}
 .t-d{background:var(--fill)}.t-t{background:var(--fill-t)}   /* 直飞蓝/中转橙色相语义不变，实心底换高对比对：tag 白字 11px 暗/亮两主题 ≥4.5:1（--blue/--orange 直用曾暗色 2.5:1） */
 .price{font-weight:800;font-family:var(--num);letter-spacing:-.3px}
 /* 时刻/日期/时长列数字即主角（v1.5.44）：纯数字曾用正文字体，
    mono 对表扫读更整齐（与 .price 同 --num 族） */
 #ftable tbody td:nth-child(3),#ftable tbody td:nth-child(5),
 #ftable tbody td:nth-child(6),#ftable tbody td:nth-child(7){
  font-family:var(--num);letter-spacing:-.2px}
 nav{display:inline-flex;gap:4px;background:var(--card);border:1px solid var(--line);
     border-radius:12px;padding:4px;box-shadow:var(--sh1);margin:14px 0}
 nav span{padding:7px 20px;border-radius:var(--r3);cursor:pointer;font-size:13.5px;
          color:var(--mut);font-weight:600;transition:.15s;user-select:none}
 nav span:hover{color:var(--tx)}
 nav span.on{background:var(--fill);color:#fff;
          box-shadow:0 2px 8px -2px var(--glow)}
 .subsec{font-size:10.5px;letter-spacing:1.2px;color:var(--mut);margin:13px 0 7px;
   display:flex;align-items:center;gap:8px;text-transform:uppercase}
 .subsec::after{content:'';flex:1;height:1px;background:var(--line)}
 /* ===== 设置行范式（settings list）：说明居左、窄控件居右、hairline 分行 ===== */
 .srow{display:flex;align-items:center;gap:14px;padding:9px 2px;
   border-bottom:1px solid var(--line);min-height:46px;min-width:0;
   box-sizing:border-box}
 .srow:last-child{border-bottom:none}
 .srow .slab{flex:1;min-width:120px;overflow:hidden}
 .srow .slab b{overflow:hidden;text-overflow:ellipsis}
 .srow .slab b{font-size:13px;color:var(--tx);font-weight:600;display:block}
 .srow .shint{font-size:11px;color:var(--mut);margin-top:2px;line-height:1.5}
 .srow .sctl{flex:none;display:flex;align-items:center;gap:8px;max-width:72%;flex-wrap:wrap}
 .srow .sctl[style*="flex:1"]{flex:1;max-width:none}
 .srow .sctl input{max-width:100%}
 /* :not(.switch) 必须保留——通用输入样式（白底/边框/34px 高）特异性
    (0,2,1) 压过 .switch (0,1,0)，曾把 srow 内全部开关覆盖成
    「白色方块内一个灰圆」的畸形（v1.5.11 用户实锤：开关分散零散） */
 .srow .sctl input:not(.switch){height:34px;padding:0 12px;border:1px solid var(--line2);
   border-radius:var(--r3);background:var(--card);color:var(--tx);font-size:13px;
   box-sizing:border-box;transition:border-color .15s,box-shadow .15s}
 .srow .sctl input:not(.switch):hover{border-color:var(--mut)}
 .srow .sctl input:not(.switch):focus{outline:none;border-color:var(--blue);
   box-shadow:0 0 0 3px var(--ring)}
 .srow .sctl input[type=number]{width:96px;text-align:right;
   font-family:var(--num);font-variant-numeric:tabular-nums}
 .srow .sctl input[type=time],.srow .sctl input:not([type]){width:118px}
 .srow .sctl input[type=time]{text-align:center;padding:0 8px}
 .srow .sctl .btn2{height:34px}
 .sunit{color:var(--mut);font-size:11.5px;font-family:var(--num)}
 .switch{appearance:none;-webkit-appearance:none;width:36px;height:20px;
   border-radius:20px;background:var(--line2);position:relative;cursor:pointer;
   transition:background .18s;flex:none;margin:0;vertical-align:middle}
 .switch:checked{background:var(--green)}
 .switch::after{content:'';position:absolute;left:3px;top:3px;width:14px;height:14px;
   border-radius:50%;background:#fff;transition:transform .18s;
   box-shadow:0 1px 2px rgba(0,0,0,.25)}
 .switch:checked::after{transform:translateX(16px)}
 /* 原生日历/时钟图标全局弱化：各主题下不抢视觉（站点自带 focus 态已够醒目） */
 input[type=time]::-webkit-calendar-picker-indicator,
 input[type=date]::-webkit-calendar-picker-indicator{opacity:.5;cursor:pointer;
   transition:opacity .15s}
 input[type=time]::-webkit-calendar-picker-indicator:hover,
 input[type=date]::-webkit-calendar-picker-indicator:hover{opacity:.9}
 input[type=checkbox]{accent-color:var(--blue)}
 /* number 输入去原生 spinner（黑块破坏质感；步进用键盘方向键仍可用） */
 input[type=number]{-moz-appearance:textfield;appearance:textfield}
 input[type=number]::-webkit-outer-spin-button,
 input[type=number]::-webkit-inner-spin-button{-webkit-appearance:none;margin:0}
 .rline{background:var(--rowalt);border:1px solid var(--line);border-radius:var(--r2);
        padding:10px 14px;margin:8px 0;min-width:0;max-width:100%;
        box-sizing:border-box;overflow:hidden}
 /* 停用态：整卡降不透明度 + 城市对去色；徽标提示「已停用」 */
 .rline.off{opacity:.62}
 .rline.off .rtcode,.rline.off .rhead b{filter:grayscale(1)}
 .rbadge{color:var(--warn);font-weight:700;font-size:11.5px;white-space:nowrap}
 .danger{color:var(--red);cursor:pointer;font-size:12px;font-weight:600;
        border:1px solid var(--redbd);background:transparent;border-radius:var(--r3);
        padding:5px 12px;transition:.15s}
 .danger:hover{background:var(--redbg);border-color:var(--redbdh)}
 .btn2{background:var(--card);color:var(--blue);border:1px solid var(--line2);border-radius:var(--r3);
       padding:6px 14px;font-size:12.5px;font-weight:600;cursor:pointer;
       box-shadow:var(--sh1);margin-right:6px;transition:.15s}
 .btn2:hover{background:var(--headbg);box-shadow:var(--sh2)}
 .btn2:active{transform:scale(.97)}
 button.busy{opacity:.6;pointer-events:none}
 /* busy 转圈替代 ⏳ emoji（与 V15 mono 精密仪表语言一致；RM 下全局
    animation:none 自动降级为静止环） */
 button.busy::after{content:'';width:11px;height:11px;margin-left:6px;
  border:2px solid var(--mut);border-top-color:transparent;border-radius:50%;
  display:inline-block;vertical-align:-2px;animation:spin .8s linear infinite}
 @keyframes spin{to{transform:rotate(360deg)}}
 .fbar{margin:8px 0;padding:10px 12px;background:var(--rowalt);border-radius:10px}
 .frow{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
 .frow+.frow{margin-top:8px}
 #chartRoutes{margin:6px 0}
 /* 空筛选行不再吃间距（单航线/单日期下 datechips/routechips 空置） */
 .frow:empty{display:none}
 #chartRoutes:empty{display:none}
 .chiplab{font-size:12px;color:var(--mut)}
 /* 筛选行开关标签：与 srow 开关同款 .switch（此前是裸 checkbox 形态脱队） */
 .flab{display:inline-flex;gap:8px;align-items:center;font-size:12.5px;
   color:var(--tx2);cursor:pointer;user-select:none}
 /* 时段挡位分组：标签与挡位绑死不可拆行（窄屏 flex-wrap 曾把「到达时段：」
    标签留在上行末尾、挡位掉到下一行=视觉断裂，用户截图实锤） */
 .wingrp{display:inline-flex;align-items:center;gap:6px;white-space:nowrap;
   flex:none}
 .winsel{display:inline-flex;gap:5px}
 /* 概览多日期分组：日期小标 + 该日期直飞/中转两卡（10-5/10-6 并排可对比） */
 .dgroup{margin-bottom:10px}
 .dgroup:last-child{margin-bottom:0}
 .dlab{font-size:11px;font-weight:700;letter-spacing:1px;color:var(--mut);
   margin:2px 0 6px;font-family:var(--num)}
 .chip{padding:4px 12px;border-radius:var(--r3);cursor:pointer;font-size:12px;
   background:var(--headbg);color:var(--mut);border:1px solid var(--line);
   user-select:none;font-weight:600;transition:.15s}
 .chip:hover{background:var(--hover);color:var(--tx2)}
 .chip.on{background:var(--fill);color:#fff;border-color:transparent;
   box-shadow:0 2px 8px -2px var(--glow)}
 .chip .pdot{margin-right:5px;vertical-align:0}
 .chip.on .pdot{background:#fff;opacity:.9}
 .chip .bd{font-style:normal;font-size:10px;margin-left:4px;opacity:.9}
 /* 出发日期 chips：✕ 悬停显形（常态半隐不抢视觉，删除是低频操作） */
 .dchip .dx{font-style:normal;margin-left:6px;opacity:.45;cursor:pointer;
   font-size:11px;transition:.15s}
 .dchip .dx:hover{opacity:1;color:#fff}
 /* 隐藏真 date 控件：仅供 📅 按钮唤原生日历（showPicker），不占视觉 */
 .dreal{position:absolute;width:0;height:0;opacity:0;pointer-events:none;
   border:0;padding:0}
 /* 时段快捷挡：srow 内小号 chip（复用 chip 视觉语言，尺寸贴 time 输入） */
 .schip{padding:4px 9px;border-radius:var(--r3);font-size:11px}
 .chip .bd.mid{color:var(--warn)}.chip .bd.old{color:var(--red)}
 .chip .bd.non{color:var(--mut)}
 .chip.on .bd.mid{color:#ffe3a3}.chip.on .bd.old{color:#ffc4c5}
 .chip.on .bd.non{color:#dfe8f2}
 .fbar label{font-size:12px;color:var(--tx2);display:flex;align-items:center;gap:5px;white-space:nowrap}
 .fbar select,.fbar input[type=text],.fbar input[type=time]{
   height:30px;padding:0 9px;border:1px solid var(--line);border-radius:var(--r3);
   font-size:12px;background:var(--card);color:var(--tx);
   transition:border-color .15s,box-shadow .15s}
 .fbar select:hover,.fbar input:hover{border-color:var(--mut)}
 .fbar select:focus,.fbar input:focus{outline:none;border-color:var(--blue);
   box-shadow:0 0 0 3px var(--ring)}
 th.srt{cursor:pointer;user-select:none}
 th.srt:hover{background:var(--hover)}
 th.srt.on{color:var(--blue)}
 /* 次行小字（舱位·准点·餐食/二段时刻）：中性灰——曾挂 --stl 衔接警示
    色，--stl 改暗橙红后误伤（次行小字非警示语义，Soldier 审查收口） */
 .stl{color:var(--mut);font-size:11px;font-weight:400}
 /* 航班列 .stl 子行（舱位·准点·餐食）允许换行：td 的 nowrap 会被继承
    把子行挤出列宽；只放开子行，主行保持 nowrap */
 td .stl{white-space:normal}
 /* 数字等宽：价格/时刻列对齐，扫读不跳 */
 table,.kpi .num,.mchip b{font-variant-numeric:tabular-nums}
 /* 达标态：进度条转绿 + 文案 */
 .bar i.ok{background:linear-gradient(90deg,var(--green),rgba(var(--okrgb),.55))!important}
 .bar i.near{background:linear-gradient(90deg,var(--warn),rgba(154,120,0,.55))!important}   /* 擦边琥珀：与明细 near 描边/推送 🟨 同语言 */
 .okTxt{color:var(--ok-strong);font-weight:600}
 /* 较上轮涨跌：降=绿 涨=红 持平=灰 */
 .dn{color:var(--ok-strong);font-weight:600}
 .up{color:var(--red);font-weight:600}
 html[data-theme="dark"] .up{color:#ff8a8c}
 /* 明细行：直达链接 + 擦边琥珀 */
 a.vw{color:var(--blue);text-decoration:none;font-weight:400;margin-left:5px;
      font-size:12px;border:1px solid var(--line);border-radius:var(--r3);padding:0 3px}
 a.vw:hover{background:var(--hover)}
 /* 擦边琥珀：--warn=#9a7800 与推送图 C_NEAR 同值（跨端同色同义；
    曾挂 --stl，其改暗橙红后擦边色跨端失配，Soldier 审查收口；
    v1.5.44 随 C_NEAR 加深对比度同步 #b08900→#9a7800，暗色 --warn 不动） */
 td.price.near{color:var(--warn);font-weight:800}
 /* 行情破线第四档（与总表图 🟩 同语言）：实绿回退；支持描边时空心绿 */
 .price.brk{color:var(--green)}
 @supports (-webkit-text-stroke:1px #000){.price.brk{color:transparent;
  -webkit-text-stroke:1.1px var(--green)}}
 /* 表格斑马纹（长表扫读不串行；xrow 展开行不参与）——
    行间夹隐藏 xrow 使 nth-child(even) 永落空，改按数据行序号显式 .zebra */
 #ftable tbody tr.zebra:not(:hover){background:var(--rowalt)}
 /* KPI 价格可点（直达去哪儿） */
 a.numlink{color:inherit;text-decoration:none}
 a.numlink:hover{text-decoration:underline}
 #ftable tbody tr:focus-visible{outline:2px solid var(--blue);outline-offset:-2px}
 /* 配置页航线摘要头：单行制——截图中「中转≤￥1700 被挤折行+基线参差」
    根治：nowrap 不折行 + align-items:center 统一控件中线；右侧操作组
    （折叠箭/开关/复制/删除）margin-left:auto 永远贴右；摘要溢出省略号 */
 .rhead{display:flex;gap:10px;align-items:center;flex-wrap:nowrap;margin-bottom:4px}
 .rhead .muted{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
 .rhead .rop{display:flex;gap:8px;align-items:center;margin-left:auto;flex:none}
 .ropbtn{background:var(--card);color:var(--blue);border:1px solid var(--line2);
        border-radius:var(--r3);padding:5px 10px;font-size:12px;font-weight:600;
        cursor:pointer;transition:.15s;white-space:nowrap;flex:none;
        box-shadow:var(--sh1)}
 .ropbtn:hover{background:var(--headbg);box-shadow:var(--sh2)}
 /* 渠道最低价 chips（替代长串文本） */
 .mchip{display:inline-block;padding:4px 11px;border-radius:18px;background:var(--headbg);
        color:var(--mut);font-size:12px;user-select:none;border:1px solid var(--line);
        transition:border-color .15s,transform .15s}
 .mchip:hover{border-color:var(--mut);transform:translateY(-1px)}
 .mchip b{font-weight:700;margin-left:2px;font-family:var(--num)}
 .mchip.best{background:var(--fill);color:#fff;border-color:transparent;
        box-shadow:0 2px 8px var(--glow)}
 .mchip.best .pdot{background:#fff;opacity:.9}
 /* 可点渠道胶囊：真实 affordance（此前 hover 上浮却不可点=虚假 affordance） */
 .mchip-link{cursor:pointer}
 .mchip-link:hover{border-color:var(--blue);color:var(--tx)}
 /* ===== header 图标按钮（玻璃拟态配套） ===== */
 .hbtn{cursor:pointer;font-size:17px;line-height:1;background:var(--headbg);
       border:1px solid var(--line);border-radius:var(--r3);padding:8px 11px;
       user-select:none;transition:.15s;color:var(--tx2)}
 .hbtn:hover{background:var(--hover);transform:translateY(-1px)}
 .hbtn:active{transform:scale(.95)}
 /* 下轮倒计时 chip */
 .cdt{display:inline-block;background:var(--headbg);border:1px solid var(--line);
      color:var(--mut);border-radius:12px;padding:2px 10px;margin-right:8px;font-size:11px;
      font-variant-numeric:tabular-nums}
 .cdt.run{background:rgba(11,98,214,.12);color:var(--blue);border-color:transparent}
 /* 图表容器 + 空状态 */
 .chartwrap{position:relative}
 .chart-empty{position:absolute;inset:0;display:flex;flex-direction:column;gap:6px;
        align-items:center;justify-content:center;color:var(--mut);font-size:14px;text-align:center}
 .chart-empty span{font-size:12px}
 /* 无用户引导（空状态即教学） */
 .hero{text-align:center;padding:44px 20px}
 .hero .hicon{font-size:44px}
 .hero h2{margin:10px 0 6px;font-size:19px}
 .hero p{color:var(--mut);margin:4px 0}
 .hero ol{text-align:left;display:inline-block;margin:12px 0 16px;color:var(--tx2);
        font-size:14px;line-height:2}
 footer{margin:22px 0 10px;text-align:center;font-size:12px}
 footer a{color:var(--blue)}
 /* 键盘可达性（统一 2px 蓝环；[role="button"] 一揽子覆盖 mkact 收编元素） */
 button:focus-visible,.chip:focus-visible,nav span:focus-visible,.tabs span:focus-visible,
 .cnav:focus-visible,.rngchip:focus-visible,.hbtn:focus-visible,[role="button"]:focus-visible{
  outline:2px solid var(--blue);outline-offset:2px}
 th.srt:focus-visible{outline:2px solid var(--blue);outline-offset:-2px}/* 表头排序：负 offset 贴格不外溢 */
 /* ===== 渠道健康时间线 ===== */
 .hrow{display:flex;align-items:center;gap:10px;margin:7px 0}
 .hlab{width:64px;flex:none;font-size:12px;color:var(--tx2);font-weight:600}
 .hcells{display:flex;gap:2px;flex:1;overflow-x:auto;padding:2px 0}
 .hc{width:6px;height:15px;border-radius:2px;flex:none;cursor:help}
 .hc.ok{background:var(--green)}.hc.part{background:var(--orange)}.hc.fail{background:var(--red)}
 .hc.maint{background:repeating-linear-gradient(45deg,#9b7ede 0 2px,rgba(155,126,222,.35) 2px 4px)}
 .hc.none{background:var(--line)}
 .hc:hover{transform:scaleY(1.35)}
 .hbadge{flex:none;font-size:11.5px;font-weight:700;min-width:52px;text-align:center;font-family:var(--num);
   padding:2px 8px;border-radius:20px;border:1px solid var(--line);
   background:var(--card);color:var(--tx2);font-variant-numeric:tabular-nums}
 .hbadge.ok{color:var(--green);border-color:rgba(var(--okrgb),.35);background:var(--okbg)}
 .hbadge.mid{color:var(--warn);border-color:var(--warnbd);background:var(--warnbg)}
 .hbadge.bad{color:var(--red);border-color:var(--redbd);background:var(--redbg)}
 .hlb{display:inline-block;width:12px;height:6px;border-radius:2px;vertical-align:middle;margin-right:4px}
 .hlh{background:repeating-linear-gradient(45deg,#9b7ede 0 2px,rgba(155,126,222,.35) 2px 4px)}
 /* ===== V50 运行脉冲：概览 statline + 轮次堆叠柱 =====
    分隔线缝隙法：1px 缝透出容器底线色，每格自带 card 底——auto-fit
    任意列数（1-4 列换行皆可）分隔线恒正确。旧 border-right 方案在中间
    列数档竖线错乱，≤760 强制单列+border-bottom 补线是妥协（已删） */
 .statline{display:grid;grid-template-columns:repeat(auto-fit,minmax(158px,1fr));
  gap:1px;background:var(--line);
  border:1px solid var(--line);border-radius:var(--r2);overflow:hidden;
  margin-top:10px}
 .stat{padding:11px 16px;background:var(--card);min-width:0}
 .stat .slab{font-size:11.5px;letter-spacing:1.2px;color:var(--mut);
  text-transform:uppercase;display:flex;align-items:center;gap:6px;white-space:nowrap}
 .stat .sval{font-family:var(--num);font-size:22px;font-weight:600;margin-top:3px;
  font-variant-numeric:tabular-nums;letter-spacing:-.5px;white-space:nowrap}
 .stat .sval.ok{color:var(--green)}.stat .sval.bad{color:var(--red)}
 .stat .ssub{font-size:11px;color:var(--mut);margin-top:1px;white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis}
 .pulsewrap{display:flex;align-items:flex-end;gap:3px;height:72px;margin-top:12px;
   justify-content:center;max-width:var(--kpiw)}/* 少轮次贴左曾让宽屏右侧大片空白（v1.5.41）；限宽随 --kpiw，柱间仍居中 */
 #pulseLegend{max-width:var(--kpiw)}
 .pbar{flex:1;min-width:4px;max-width:16px;height:100%;display:flex;flex-direction:column;
  justify-content:flex-end;cursor:help;border-radius:2px;position:relative}
 .pbar:hover{filter:brightness(1.15)}
 .pbar .seg{width:100%}
 .pbar .cap{width:100%;height:3px;background:var(--red);margin-bottom:1px;border-radius:1px}
 .pbar.zero{display:flex;justify-content:center}
 .pbar.zero i{width:100%;max-width:8px;height:3px;border-radius:1px;background:var(--red)}
 .pseg-qunar{background:var(--c-qunar)}.pseg-fliggy{background:var(--c-fliggy)}
 .pseg-tongcheng{background:var(--c-tongcheng)}.pseg-tuniu{background:var(--c-tuniu)}
 .pseg-ctrip{background:var(--c-ctrip)}
 .kbd{font-family:var(--num);font-size:10.5px;border:1px solid var(--line2);
  border-bottom-width:2px;border-radius:5px;padding:1px 6px;color:var(--tx2);
  background:var(--headbg);margin:0 2px;white-space:nowrap}
 /* ===== 推送预览弹层（钉钉近似渲染） ===== */
 .pvmask{position:fixed;inset:0;background:rgba(16,24,40,.45);z-index:200;display:none;
        align-items:flex-start;justify-content:center;padding:5vh 12px}
 .pvmask.on{display:flex}
 .pvcard{background:var(--card);border-radius:14px;max-width:560px;width:100%;max-height:88vh;
        display:flex;flex-direction:column;box-shadow:0 18px 50px rgba(16,24,40,.35)}
 .pvhead{display:flex;justify-content:space-between;align-items:center;gap:10px;
        padding:12px 16px;border-bottom:1px solid var(--line);font-weight:700;font-size:14px}
 .pvx{cursor:pointer;color:var(--mut);font-size:16px;padding:2px 8px;border-radius:6px;user-select:none}
 .pvx:hover{background:var(--hover)}
 .pvbody{padding:14px 18px;overflow-y:auto;font-size:13.5px;line-height:1.75;color:var(--tx)}
 .pvbody .md-h1{font-size:17px;font-weight:800;margin:8px 0 10px}
 .pvbody .md-h2{font-size:15px;font-weight:800;margin:14px 0 8px;color:var(--blue)}
 .pvbody .md-h3{font-size:13.5px;font-weight:700;margin:10px 0 6px}
 .pvbody .md-q{border-left:3px solid var(--blue);background:var(--rowalt);border-radius:0 8px 8px 0;
        padding:6px 12px;margin:6px 0;color:var(--tx2)}
 .pvbody .md-hr{border:none;border-top:1px solid var(--line);margin:10px 0}
 .pvbody .md-p{margin:6px 0}
 .pvbody .md-li{margin:6px 0;padding-left:16px;color:var(--tx)}
 .pvbody .md-g{font-size:15px;letter-spacing:2px}
 .pvbody img{max-width:100%;border-radius:8px;border:1px solid var(--line);display:block;margin:6px 0}
 .pvbody a{color:var(--blue);text-decoration:none}
 .pvbody .md-at{background:#ffd24d;color:#7a4b00;border-radius:4px;padding:0 5px;font-weight:700}
 .pvfoot{padding:10px 16px;border-top:1px solid var(--line);font-size:11.5px}
 /* ===== 演示横幅 ===== */
 .demoBar{margin:12px 0 0;background:#fff7e0;color:#7a4b00;border:1px solid #f0d98c;
        border-radius:10px;padding:9px 14px;font-size:13px;text-align:center}
 .demoBar a{color:#9a6200;font-weight:700}
 html[data-theme="dark"] .demoBar{background:#2b2413;color:#e8c96a;border-color:#4d4021}
 html[data-theme="dark"] .demoBar a{color:#ffd97a}
 /* ===== 移动端（≤760px）：筛选抽屉 + 首列吸附 + 触控加大 ===== */
 #fltBtn{display:none}
 @media(max-width:760px){
  html{scroll-padding-top:118px}
  header{padding:12px 18px}
  header .muted{display:block}/* 倒计时/更新时间是手机核心信息，不再整行隐藏 */
  header h1{font-size:17px}
  .pill{font-size:14px;padding:5px 12px}
  #fltBtn{display:inline-block}
  #fltBtn b{background:var(--red);color:#fff;border-radius:var(--r3);padding:0 6px;font-size:11px;margin-left:3px}
  .fbar{display:none}
  .fbar.open{display:block;animation:vin .18s ease}/* 抽屉淡入（复用 vin），免突现 */
  .fbar label,.fbar select,.fbar input{font-size:13px}
  button{padding:11px 16px}
  .hc{width:5px}
 }
 /* ===== 价格日历热力卡 ===== */
 .calgrid{display:flex;gap:5px;flex-wrap:wrap;margin-top:8px}
 /* 日历统计条分层（v1.5.45）：指标胶囊（mono 数字加重）与图例小字分体，
    决策信息与解码信息不再混排一行 */
 .cs-i{display:inline-block;background:var(--rowalt);border:1px solid var(--line);
  border-radius:var(--r3);padding:1px 8px;margin:2px 6px 2px 0;font-size:12px;color:var(--tx2)}
 .cs-i b{font-family:var(--num);color:var(--tx)}
 .cs-lg{font-size:11px;color:var(--mut)}
 .calcell{flex:1 1 74px;max-width:112px;border-radius:var(--r3);padding:6px 4px;text-align:center;
        border:1px solid var(--line);transition:transform .12s}
 .calcell.link{cursor:pointer}
 .calcell.link:hover{transform:translateY(-2px)}
 .calcell .cd{font-size:11px;font-weight:600;opacity:.85}
 .calcell .cp{font-size:13px;font-weight:800;margin-top:2px;
  font-family:var(--num);font-variant-numeric:tabular-nums}
 .calcell .cx{font-size:10.5px;margin-top:1px;font-variant-numeric:tabular-nums;opacity:.85}
 /* ===== 移动端触控目标增强（基础规则之后声明，防同特异性覆盖） ===== */
 @media(max-width:760px){
  .tabs .mtab{padding:9px 14px}
  #tabs span{padding:9px 14px}
  .chip{padding:9px 14px;font-size:13px}/* 触控目标 ~36px，间距防误触 */
  .chip+.chip{margin-left:6px}
  .mchip{padding:9px 14px;font-size:13px}/* 与 chip 同触控基准（原 26px 偏小） */
  .fbar input:not(.switch),.fbar select{padding:9px 10px}
  /* 触控基准最后两个漏点（v1.5.41）：表头排序/配置左导航原 ~34px */
  th.srt{padding:11px 8px}
  .cnav{padding:10px 14px}
 }
 .calcell.best{outline:2px solid var(--green);outline-offset:-2px}
 .calcell.link:hover{border-color:var(--blue)}
 .calcell.best .cx{font-weight:800;opacity:1}
 .calcell.none{background:var(--rowalt);color:var(--mut)}
 /* ===== 日志原文弹层 ===== */
 .logpre{font-family:var(--num);font-size:11.5px;line-height:1.6;
        white-space:pre-wrap;word-break:break-all;background:var(--rowalt);
        border-radius:8px;padding:10px 12px;margin:0;max-height:60vh;overflow:auto}
 /* ===== 通知开关 ===== */
 /* ===== 走势范围 chips（与 tabs/chip 同一视觉语言） ===== */
 .rngchip{padding:5px 14px;border-radius:var(--r3);cursor:pointer;font-size:12px;
   background:var(--headbg);color:var(--mut);border:1px solid var(--line);
   user-select:none;font-weight:600;transition:.15s}
 .rngchip:hover{border-color:var(--mut);color:var(--tx2)}
 .rngchip.on{background:var(--fill);color:#fff;border-color:transparent;
   box-shadow:0 2px 8px -2px var(--glow)}
 /* 触控增强必须声明在基础规则之后（同特异性后者胜——曾写在前面整块失效） */
 @media(max-width:760px){.rngchip{padding:9px 14px}
   nav span{padding:9px 18px}
   .hbtn{min-height:36px;min-width:36px}
   .ropbtn,.danger{min-height:36px}
   /* 抽屉触控 ≥38px + 时段挡位允许换行——必须位于全部基础规则之后
      （.fbar input[type=text] (0,2,1) / .wingrp 基础规则声明更后，
      移动规则写在前面会被同特异性后者覆盖=整块失效，两次实锤） */
   .fbar input:not(.switch),.fbar select{height:38px}
   .fbar input[type=text]{height:38px}/* 对齐基础 (0,2,1) 的 height:30px */
   .fbar .btn2{height:38px;margin-right:0}
   /* 触控热区补账（v1.5.38）：配置页大量 .btn2（📅/➕/测试）在基础
      规则下 ≈31px 低于 36px 基准；srow 裸 .switch 20px 高——::before
      外扩隐形命中区（::after 已是旋钮本体不可复用；inset 全向外扩） */
   .btn2{min-height:36px}
   .srow .sctl .switch::before{content:'';position:absolute;inset:-8px}
   .wingrp{flex-wrap:wrap;white-space:normal;max-width:100%}
   .winsel{flex-wrap:wrap}/* 内层 chips 行也允许折行，否则组仍 390px 溢出 */}
 /* ===== toast 通知（右下角堆叠，非阻断；替代原生 alert） ===== */
 #toasts{position:fixed;bottom:78px;right:18px;z-index:300;display:flex;
        flex-direction:column;gap:8px;align-items:flex-end}
 .toast{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--blue);
        border-radius:var(--r3);padding:10px 16px;font-size:13px;color:var(--tx);
        box-shadow:var(--sh3);animation:tin .25s ease;cursor:pointer;
        max-width:min(340px,calc(100vw - 28px));word-break:break-all}
 .toast.ok{border-left-color:var(--green)}
 .toast.err{border-left-color:var(--red)}
 .toast.out{opacity:0;transform:translateX(20px);transition:.3s}
 @keyframes tin{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
 /* 危险操作二次确认态（按钮内联确认，替代原生 confirm） */
 button.arming{background:var(--red)!important;border-color:var(--red)!important;color:#fff!important}
 /* 明细行入场（stagger 渐显；reduced-motion 全局已禁用动画） */
 @keyframes rowin{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
 /* 延迟由数据行 --i 变量驱动（JS clamp 至 7=210ms 封顶）：nth-child 计数
    会被行间隐藏 xrow 打乱，折叠展开/筛选后序号错位（v1.5.39） */
 #ftable tbody tr{animation:rowin .22s ease backwards;animation-delay:calc(var(--i,0)*30ms)}
 /* 大表免动画：数百行同时入场动画只增加合成开销（重建本身已 <15ms） */
 #ftable.big tbody tr{animation:none}
 @media(prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
 /* ===== 骨架屏（首屏加载占位，shimmer 扫光） ===== */
 .sk{position:relative;overflow:hidden;background:var(--line);border-radius:8px}
 .sk::after{content:'';position:absolute;inset:0;transform:translateX(-100%);
   background:linear-gradient(90deg,transparent,rgba(255,255,255,.4),transparent);
   animation:skm 1.3s infinite}
 html[data-theme="dark"] .sk::after{background:linear-gradient(90deg,transparent,rgba(255,255,255,.07),transparent)}
 @keyframes skm{to{transform:translateX(100%)}}
 /* ===== V20 配置页双栏骨架 ===== */
 .cfglayout{display:grid;grid-template-columns:180px minmax(0,1fr);gap:16px;align-items:start}
 /* sticky top 与真实 header 高对齐（header≈74px，64 曾让导航条顶边被盖 10px） */
 .cfgnav{position:sticky;top:76px;display:flex;flex-direction:column;gap:4px;
  align-self:start;max-height:calc(100vh - 88px);overflow:auto}
 #cfgview{padding-bottom:88px}/* 底部字段不被浮存条(savebar)遮挡 */
 /* 搜索框独立瓦片样式（曾 .cfgnav>span 通配——特异性 (0,1,1) 恒压
    .cnav 的 (0,1,0)，其 padding/radius/background 全部死代码，且 760px
    触控增强 .cnav{padding:10px 14px} 从未生效（v1.5.46 收口）：
    瓦片样式合并进 .cnav 本体，观感不变、特异性归位） */
 .cfgnav .cfgsearch{background:var(--card);
   border:1px solid var(--line);border-radius:var(--r);padding:10px 12px}
 .cfgnav-t{font-size:10px;letter-spacing:1.5px;color:var(--mut);padding:2px 8px 6px;
   text-transform:uppercase}
 .cnav{background:var(--card);border:1px solid var(--line);
   border-radius:var(--r);padding:8px 12px;cursor:pointer;font-size:13px;
   color:var(--tx2);font-weight:600;transition:.15s;user-select:none}
 .cnav:hover{background:var(--hover)}
 .cnav.on{background:var(--fill);color:#fff}
 @media(max-width:900px){.cfglayout{grid-template-columns:minmax(0,1fr)}
   .cfgnav{position:static;flex-direction:row;flex-wrap:wrap}
   .cfgnav-t{display:none}}
 /* 窄屏航线卡头允许换行（nowrap 摘要在 390px 曾把整页撑出横向滚动） */
 @media(max-width:760px){.rhead{flex-wrap:wrap}
   .rhead .muted{white-space:normal}}
 .grouplab{display:flex;align-items:center;gap:9px;margin:16px 2px 10px;
   border:1px solid var(--line);border-radius:var(--r3);padding:9px 12px;font-size:13px;
   font-weight:700;color:var(--tx);background:var(--headbg);
   transition:border-color .15s,background .15s}
 .grouplab[data-sec]:hover{border-color:var(--blue);background:var(--hover)}
 .grouplab .gsum{font-weight:400;font-size:11.5px;color:var(--mut);
   overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}
 .grouplab .chev{font-size:14px}
 .grouplab .no{font-family:var(--num);color:var(--blue);font-size:11px;letter-spacing:1px;
   background:var(--headbg);border:1px solid var(--line);border-radius:6px;
   padding:2px 8px;align-self:center}
 .grouplab .en{font-size:10px;letter-spacing:2px;color:var(--mut);
   text-transform:uppercase;font-weight:600}
 .grouplab::after{content:'';flex:1;border-top:1px solid var(--line)}
 /* ===== V50 配置页质感：登录卡 / 参数格 / 通道卡 / 用户卡头 ===== */
 .lgdot{width:8px;height:8px;border-radius:50%;background:var(--line2);flex:none;
   display:inline-block}
 .lgdot.on{background:var(--green);box-shadow:0 0 0 3px rgba(var(--okrgb),.15)}
 .lggrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(148px,1fr));gap:10px}
 .lgcard{border:1px solid var(--line);border-radius:var(--r2);padding:12px 14px;
   background:var(--card);display:flex;flex-direction:column;gap:7px;
   transition:border-color .2s,transform .15s}
 .lgcard:hover{border-color:var(--line2);transform:translateY(-2px)}
 .lgcard.saved{border-color:rgba(var(--okrgb),.35)}
 .lgcard.active{border-color:var(--warnbd)}
 .lgcard .lgname{font-size:13.5px;font-weight:700;display:flex;align-items:center;gap:8px}
 .lgcard .lgsub{font-size:11.5px;color:var(--mut)}
 .lgcard .btn2{margin-top:auto}
 .glgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
 .glcell{border:1px solid var(--line);border-radius:var(--r2);padding:11px 14px;
   background:var(--card);transition:border-color .2s}
 .glcell:hover{border-color:var(--line2)}
 .glcell .glab{font-size:11.5px;letter-spacing:1px;color:var(--mut);
   text-transform:uppercase;white-space:nowrap}
 .glcell input:not(.switch){margin-top:6px;font-family:var(--num);font-size:17px;font-weight:600;
   width:100%;border:none;background:transparent;color:var(--tx);padding:2px 0 0;
   border-bottom:1px dashed var(--line2);border-radius:0}
 .glcell input:hover{border-bottom-color:var(--mut)}
 .glcell input:focus{outline:none;border-bottom:1px solid var(--blue);
   box-shadow:0 1px 0 0 rgba(11,98,214,.25)}
 .glcell .gsub{font-size:11px;color:var(--mut);margin-top:5px}
 .chgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(272px,1fr));
   gap:10px;margin-top:8px}
 .chcard.expanded{grid-column:1/-1}/* 展开的通道卡跨全宽，不留半列空白 */
 .chcard{border:1px solid var(--line);border-radius:var(--r2);padding:12px 14px;
   background:var(--card);display:flex;flex-direction:column;gap:9px;
   transition:border-color .2s}
 .chcard.on{border-color:rgba(var(--okrgb),.4)}
 .chhead{display:flex;align-items:center;gap:8px;font-size:13.5px;font-weight:700}
 .chhead .muted{font-weight:500;margin-left:auto;white-space:nowrap}
 .hint{font-size:11.5px;color:var(--mut);line-height:1.55;margin-top:5px;opacity:.92}
 .uhead2{cursor:pointer;display:flex;align-items:center;gap:12px;flex-wrap:wrap;padding:13px 16px;
   background:var(--headbg);transition:background .15s;user-select:none}
 .uhead2:hover{background:var(--hover)}
 .uhead2 b{flex:1;font-size:14px}
 .uhead2 .stat2{font-family:var(--num);font-size:11.5px;color:var(--mut)}
 .uava{width:30px;height:30px;border-radius:var(--r3);flex:none;display:inline-flex;
   align-items:center;justify-content:center;font-size:13px;font-weight:700;color:#fff;
   background:linear-gradient(135deg,var(--fill2),var(--blue))}
 .upill{font-size:11px;padding:3px 9px;border-radius:20px;border:1px solid var(--line);
   background:var(--card);color:var(--mut);white-space:nowrap;
   font-family:var(--num);font-variant-numeric:tabular-nums}
 .upill.ok{color:var(--green);border-color:rgba(var(--okrgb),.35);background:var(--okbg)}
 .upill.warn{color:var(--warn);border-color:var(--warnbd);background:var(--warnbg)}
 .udirty{display:none}
 .chev{transition:transform .2s;color:var(--mut);font-size:12px;flex:none}
 .chev.open{transform:rotate(180deg)}
 .grouplab[data-sec],.rhead[role="button"],.chhead[role="button"]{cursor:pointer;user-select:none}
 .grouplab[data-sec]:hover .zh,.chhead[role="button"]:hover{color:var(--blue)}
 .rhead[role="button"]:hover .rtcode{border-color:var(--blue)}
 .grouplab .chev{margin-left:auto}
 .ucard.flash,.rline.flash{animation:cfgflash 1.4s ease-out}
 @keyframes cfgflash{0%{box-shadow:0 0 0 3px rgba(11,98,214,.5)}
  100%{box-shadow:0 0 0 3px rgba(11,98,214,0)}}
 .rtcode{font-family:var(--num);font-size:14.5px;font-weight:600;color:var(--blue);
   letter-spacing:.5px}
 /* 未保存修改浮出保存条 */
 .savebar{position:fixed;right:18px;bottom:18px;z-index:120;display:none;gap:10px;
   align-items:center;background:var(--card);border:1px solid var(--line2);
   border-radius:12px;padding:10px 14px;box-shadow:var(--sh2);font-size:13px;font-weight:600}
 .savebar .dot{width:8px;height:8px;border-radius:50%;background:var(--orange);
   animation:pulse 1.4s ease-in-out infinite}
 /* ===== 推送记录列表（状态色条卡片：绿=成功 红=失败） ===== */
 .plitem{padding:9px 12px;border-radius:var(--r3);cursor:pointer;font-size:13px;
        margin:6px 0 2px;background:var(--rowalt);border:1px solid var(--line);
        border-left:3px solid var(--green);display:flex;gap:8px;
        align-items:center;transition:background .15s,border-color .15s}
 .plitem:hover{background:var(--hover)}
 .plitem.bad{border-left-color:var(--red)}
 .plts{color:var(--mut);font-size:11.5px;white-space:nowrap;font-variant-numeric:tabular-nums}
 .pldesp{border:1px solid var(--line);border-radius:0 10px 10px 10px;
        background:var(--headbg);padding:4px 14px;margin:0 0 10px}
 /* ===== 细滚动条（主题化；Firefox 走 scrollbar-*） ===== */
 ::-webkit-scrollbar{width:9px;height:9px}
 ::-webkit-scrollbar-thumb{background:var(--line);border-radius:5px}
 ::-webkit-scrollbar-thumb:hover{background:var(--mut)}
 ::-webkit-scrollbar-track{background:transparent}
 *{scrollbar-width:thin;scrollbar-color:var(--line) transparent}
 /* ===== 视图/图表切换过渡（丝滑不跳变） ===== */
 .viewin{animation:vin .18s ease}
 @keyframes vin{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
 /* ===== V50 配置页：搜索框 + 命中计数 ===== */
 .cfgsearch{width:100%;padding:7px 11px;border:1px solid var(--line2);border-radius:var(--r3);
  font-size:12.5px;background:var(--card);color:var(--tx);margin:8px 0 10px;
  transition:border-color .15s,box-shadow .15s}
 .cfgsearch:hover{border-color:var(--mut)}
 .cfgsearch:focus{outline:none;border-color:var(--blue);box-shadow:0 0 0 3px var(--ring)}
 .cfghit{font-size:11px;color:var(--mut);margin:-4px 0 8px;min-height:14px}
 /* ===== 追加规则一律置末尾（同特异性后者胜，防被前文同名规则覆盖） ===== */
 .stat .sval{overflow:hidden;text-overflow:ellipsis}
 @media(min-width:1440px){.wrap{max-width:min(1320px,92vw)}}
 /* ===== KPI 宽度单源令牌 --kpiw：默认 992；1440-1599 补此前被跳过的
    档 1132（该档恒 992 时用户卡内右侧空腔 ~290px）；1600+ 1172
    （560→580/格与明细卡左缘成线）；1800+ 不再加宽——KPI 过扁失比 ===== */
 @media(min-width:1440px){:root{--kpiw:1132px}}
 @media(min-width:1600px){:root{--kpiw:1172px}}
 /* v1.5.43 KPI 宽屏限宽 → 令牌化：.grid 为 KPI 专用（唯一消费点），
    auto-fit 在 1180-1439 恒出 2 轨 ~566px 宽扁失比（1280/1366 主流本
    正落在区间内）；限宽下探到 600px 生效——<600px 维持 auto-fit
    minmax(280px,1fr) 单列不破手机端；轨道 1fr×2 宽随 --kpiw 容器定，
    statline 同宽左缘成线 */
 @media(min-width:600px){
  .grid{grid-template-columns:repeat(2,minmax(0,1fr));max-width:var(--kpiw);
   justify-content:flex-start}
  .statline{max-width:var(--kpiw)}}
 .kpisum{max-width:var(--kpiw)}   /* 用户卡「全线最低」行与 KPI 行同宽 */
 /* ===== 密度两挡：cozy（默认）/compact（紧凑），html[data-density] 覆写 ===== */
 html[data-density="compact"] .ucard{padding:14px}
 html[data-density="compact"] .srow{padding:8px 10px;min-height:38px}
 html[data-density="compact"] th,html[data-density="compact"] td{padding:6px 8px}
 html[data-density="compact"] .kpi .num{font-size:27px}
 /* compact 同步收窄航线卡/通道卡内衬（基础 padding 约 -30%）：srow 行高
    收了而外层卡不收，折叠体内留白比例反而变大（v1.5.39） */
 html[data-density="compact"] .rline{padding:7px 10px}
 html[data-density="compact"] .chcard{padding:8px 10px}
 /* ===== ≤390px 小屏档（手机竖排末端）：卡距/header 再收一档 ===== */
 @media(max-width:390px){
  .kpi{padding:10px 12px}
  .grid{gap:8px}
  .ucard{padding:12px 12px}
  header{padding:10px 12px}
  header h1{font-size:15px;letter-spacing:.6px}
  .wrap{padding:0 10px 14px}
  header{margin:0 -10px 4px}
 }
 /* ===== 首列吸附全宽度生效：吸附成本恒定，超长航线名在 >1024 也可能
    触发横滚——价格列在任何宽度都不许滚出视野（原只在 ≤1024 生效）。
    斑马/hover/qual 补偿底随 .zebra 显式类同步（v1.5.33） ===== */
 .tw th:first-child,.tw td:first-child{position:sticky;left:0;z-index:2;
  background:var(--card);box-shadow:2px 0 0 var(--line)}
 .tw th:first-child{background:var(--headbg);z-index:4}
 .tw tbody tr.zebra td:first-child{background:var(--rowalt)}
 .tw tbody tr:hover td:first-child{background:var(--hover)}
 /* 吸附不透明底会盖掉达标行绿底（斑马/hover 已补偿，qual 曾漏） */
 .tw tbody tr.qual td:first-child{background:rgba(var(--okrgb),.08)}
 .tw tbody tr.qual:hover td:first-child{background:rgba(var(--okrgb),.14)}
 .tw tbody tr.qual.zebra td:first-child{background:rgba(var(--okrgb),.12)}
 html[data-theme="dark"] .tw tbody tr.qual td:first-child{background:rgba(67,192,114,.13)}
 html[data-theme="dark"] .tw tbody tr.qual:hover td:first-child{background:rgba(67,192,114,.2)}
 /* 空态/加载行（erow）：行身透明+悬停透明（上方 #ftable tr.erow:hover 规则），sticky 首格若被
    通用 hover 规则染成 --hover 会与行身断裂——钉回 card 底（含 hover 态） */
 #ftable tbody tr.erow td:first-child{background:var(--card)}
 #ftable tbody tr.erow:hover td:first-child{background:var(--card)}
 /* ===== 触控热区扩展：可点小控件以 ::after 外扩命中区（视觉尺寸不变） ===== */
 .dchip .dx,.pvx,a.vw,.hc{position:relative}
 .pvx::after,a.vw::after{content:'';position:absolute;inset:-8px}
 /* .dx 字面仅 ~11px：热区外扩到 -13px≈37px 达触控基准；外缘仍落在自身
    chip 12px 内衬+片间距内，不侵入相邻日期片命中区 */
 .dchip .dx::after{content:'';position:absolute;inset:-13px}
 /* .hc 热区：纵向扩展保触控高度；横向只补缝隙（6px 格距 8px，曾
    ±10px 全向扩展——相邻 5 格热区互相覆盖，点 A 格响应 B 格） */
 .hc::after{content:'';position:absolute;inset:-10px -1px}
 /* .pbar 热区同语言：4px 细柱难点中；横向只 ±1px 防串柱（缝 3px） */
 .pbar::after{content:'';position:absolute;inset:-10px -1px}
 /* ===== savebar 小屏防溢出（≤390 视口左缘曾被裁）——只在小屏生效，
    桌面保持右下紧凑浮条（无媒体查询时曾拉成全宽大横条） ===== */
 @media(max-width:390px){
  .savebar{left:12px;right:12px;max-width:calc(100vw - 24px);justify-content:flex-end}
  /* savebar 小屏折双行可近 80px：toast 底距同步抬升防叠压 */
  #toasts{bottom:96px}}
 .savebar{flex-wrap:wrap}
 /* ===== xrow（同班比价展开行）退出首列吸附：colspan 行恰是 td:first-child，
    被 v1.5.33 全宽度吸附规则上了不透明卡底+投影，琥珀高亮底被整体吃掉 ===== */
 .tw tbody tr.xrow td:first-child{position:static;
  background:var(--xzone);box-shadow:none}
 /* ===== 暗色清扫第三批：JS 内联硬编码随令牌 ===== */
 /* .lgdot 离线灰点暗色下接近在线绿点（语义变糊），随 --line2 退后 */
 /* ===== iOS Safari 聚焦不放大：输入字号 <16px 会触发自动缩放 ===== */
 @media(max-width:760px){
  .srow input[type=text],.srow input[type=number],.srow input[type=time],
  .srow input[type=url],.srow input[type=tel],.srow input[type=password],
  .srow input:not([type]),.fbar input[type=text],.cfgsearch,
  .fbar label input{font-size:16px}}
 /* ===== 触屏平板（≤900px 且 pointer:coarse）：iPad 768/810/820 此前
    落在 760 断点真空，触控目标拿不到 ≥36px 基准。规则自上方 ≤760 触控
    块逐字复制（声明同值，手机 coarse 下双块叠加零视觉差）；置于全部
    基础规则之后（.cnav/.cfgsearch 基础声明更后，写前面会被同特异性
    后者覆盖=整块失效，见上方两次实锤注释）。fbar 开关此前无热区外扩
    （含 #fnostale），一并补 ::before 命中区 ===== */
 @media(max-width:900px) and (pointer:coarse){
  .tabs .mtab{padding:9px 14px}
  #tabs span{padding:9px 14px}
  .chip{padding:9px 14px;font-size:13px}
  .chip+.chip{margin-left:6px}
  .mchip{padding:9px 14px;font-size:13px}
  .fbar input:not(.switch),.fbar select{padding:9px 10px}
  th.srt{padding:11px 8px}
  .cnav{padding:10px 14px}
  .rngchip{padding:9px 14px}
  nav span{padding:9px 18px}
  .hbtn{min-height:36px;min-width:36px}
  .ropbtn,.danger{min-height:36px}
  .fbar input:not(.switch),.fbar select{height:38px}
  .fbar input[type=text]{height:38px}
  .fbar .btn2{height:38px;margin-right:0}
  .btn2{min-height:36px}
  .srow .sctl .switch::before{content:'';position:absolute;inset:-8px}
  .fbar .switch::before{content:'';position:absolute;inset:-8px}
  .srow input[type=text],.srow input[type=number],.srow input[type=time],
  .srow input[type=url],.srow input[type=tel],.srow input[type=password],
  .srow input:not([type]),.fbar input[type=text],.cfgsearch,
  .fbar label input{font-size:16px}}
 /* ===== 暗色漏网：硬编码深琥珀在暗底对比不足，随令牌 ===== */
 html[data-theme="dark"] .rbadge{color:var(--warn)}
 html[data-theme="dark"] .upill.warn{color:var(--warn)}
 /* ===== 日历擦边档（q=-1）：格价琥珀，与走势图「擦边」同语言 ===== */
 .calcell .cp.near{color:var(--warn)}
 /* 飞猪明细行「税前」小标（推送侧同标注：税前价≠到手价，扫读可辨） */
 .pretax{font-size:10px;color:var(--mut);font-weight:500;margin-left:4px;
   vertical-align:1px}
 /* ===== 2K 宽屏（≥1800px）：明细表放宽一档看全列，其余卡维持 1320 密度 =====
    负 margin 突破 .wrap 内容宽（min(1320,92vw)-36=1284px）：(1680-1284)/2=198；
    视口 ≥1800 时两侧屏内余量 ≥60px 不溢出。
    v1.5.44 补 #calcard：与 chartcard 同在 trend 子视图上下排布，曾只破
    明细/走势两卡——2K 下上图 1680 / 下卡 1284 左右缘双双错位 198px；
    日历格 flex-wrap 放宽后多容纳一列，信息密度反受益 */
 @media(min-width:1800px){
  #tablecard,#chartcard,#calcard{max-width:1680px;margin-left:-198px;margin-right:-198px}}
 /* ===== 大屏触控设备（>900px 且 pointer:coarse）：iPad Pro 横屏 1366 等
    落在 ≤900 触控补丁盲区，控件回落 <36px 触控基准；声明与上方触控块
    同值补档（历史纪律：媒体增强块置于文件尾部） ===== */
 @media(pointer:coarse) and (min-width:901px){
  .chip,.mchip,.rngchip{padding:9px 14px}
  nav span,.tabs span{padding:9px 14px}
  th.srt{padding:11px 8px}
  .btn2,.ropbtn,.danger{min-height:36px}}
</style></head><body><div class="wrap">
<header><h1><span class="logo">✈️</span>机票监控台</h1>
 <div style="display:flex;align-items:center;gap:10px"><span id="ntBtn" class="hbtn" onclick="togNotify()" title="达标时浏览器通知+提示音">🔕</span><span id="themeBtn" class="hbtn" onclick="cycleTheme()" title="亮/暗/自动">🌗</span><span id="denBtn" class="hbtn" onclick="cycleDensity()" title="密度">≡</span><div><span class="pill" id="pill">加载中…</span>
  <div class="muted" style="margin-top:6px;text-align:right"><span id="nextrun" class="cdt" style="display:none"></span><span id="updated"></span></div></div></div></header>

<datalist id="citydl"></datalist>
<div class="demoBar" id="demoBar" style="display:none">🎪 演示模式：数据为本地合成，仅作功能预览 · <a href="https://github.com/dengmeiluan/ticket-monitoring" target="_blank" rel="noopener">下载源码或发行包</a>即可监控真实票价</div>
<nav><span id="navMon" class="on" onclick="switchView('mon')">📊 监控</span>
 <span id="navCfg" onclick="switchView('cfg')">⚙️ 配置<i id="navDirty" style="display:none;color:var(--red);font-style:normal;margin-left:2px" title="配置有未保存修改">●</i></span></nav>
<div id="monview">
<div class="ucard"><div class="row">
 <button onclick="api('run','立即扫描全部航线？将触发采集与各用户钉钉推送')">🔄 立即扫描一轮</button>
 <button class="warn" onclick="api('push','向所有已配置用户推送走势报告？')">📈 推送走势报告</button>
 <button class="warn" id="pvBtn" onclick="previewPush()">👁 预览推送</button>
 <button class="warn" onclick="pushLog()">📨 推送记录</button>
 <span class="muted">数据变化才刷新（悬停/展开不打断）· 页面隐藏时暂停轮询</span>
 <div class="frow" id="userPills" style="display:none;width:100%;margin-top:2px"></div></div></div>

<div class="ucard" id="pulsecard" style="display:none"><div class="uhead">
  <span style="display:flex;align-items:center;gap:9px;flex-wrap:wrap"><span class="seclab inline"><span class="no">01</span><span class="zh">运行脉冲</span><span class="en">PULSE</span></span></span>
  <span class="muted">每根柱 = 一轮扫描 · 高度 = 采集行数 · 红帽 = 有渠道失败 · 悬停看明细</span></div>
 <div class="statline" id="statline"></div>
 <div class="pulsewrap" id="pulsebars"></div>
 <div class="legend" id="pulseLegend" style="margin-top:8px"></div></div>

<div class="tabs" id="montabs" style="display:none">
 <span class="mtab on" data-t="overview">🎯 概览</span>
 <span class="mtab" data-t="trend">📈 走势 · 日历</span>
 <span class="mtab" data-t="details">📋 航班明细</span>
 <span class="mtab" data-t="health">🏥 渠道健康</span></div>

<div id="montab-overview">
<div id="users"><div class="ucard"><div class="grid">
 <div class="kpi d"><div class="sk" style="height:12px;width:45%"></div><div class="sk" style="height:30px;width:52%;margin:8px 0"></div><div class="sk" style="height:10px;width:68%"></div></div>
 <div class="kpi t"><div class="sk" style="height:12px;width:45%"></div><div class="sk" style="height:30px;width:52%;margin:8px 0"></div><div class="sk" style="height:10px;width:68%"></div></div>
</div><div class="sk" style="height:12px;width:58%;margin-top:14px"></div></div></div>
</div><!-- /montab-overview -->

<div id="montab-trend" style="display:none">
<div class="ucard" id="chartcard"><div class="uhead"><span style="display:flex;align-items:center;gap:9px;flex-wrap:wrap"><span class="seclab inline"><span class="no">02</span><span class="zh">价格走势</span><span class="en">TREND</span></span><span id="chartTitle" style="font-weight:700"></span></span>
 <span><span class="rngchip on" id="mdLine" onclick="setMode('line')">折线</span>
 <span class="rngchip" id="mdK" onclick="setMode('kline')">K线</span>
 <span style="display:inline-block;width:8px"></span>
 <span class="rngchip on" id="rng48" onclick="setRange('48h')">48h</span>
 <span class="rngchip" id="rng7d" onclick="setRange('7d')">7 天</span></span></div>
 <div class="frow" id="chartRoutes"></div>
 <div class="chartwrap"><canvas id="chart"></canvas>
  <div class="chart-empty" id="chartEmpty" style="display:none">暂无走势数据<span>完成第一轮扫描后，这里会出现近 48 小时的最低价曲线</span></div></div>
 <div class="legend"><span><b style="background:var(--blue)"></b>直飞最低</span>
  <span><b style="background:var(--orange)"></b>中转最低</span>
  <span title="行情价低于达标线的区间；未必可出手（达标以环标为准）"><b style="background:var(--okzone)"></b>线内区间</span><span><b style="background:var(--red)"></b>直飞达标线</span><span><b style="background:var(--thline)"></b>中转达标线</span>
  <div class="muted" id="ringNote" style="flex-basis:100%;font-size:11px;margin-top:2px"></div></div></div>

<div class="ucard" id="calcard" style="display:none"><div class="uhead"><span style="display:flex;align-items:center;gap:9px;flex-wrap:wrap"><span class="seclab inline"><span class="no">03</span><span class="zh">价格日历</span><span class="en">CALENDAR</span></span><span id="calTitle" style="font-weight:700"></span></span>
 <span class="muted" id="calStats"></span></div>
 <div class="calgrid" id="calgrid"></div></div>
</div><!-- /montab-trend -->

<div id="montab-health" style="display:none">
<div class="muted" id="healthEmpty" style="display:none;padding:34px 0;text-align:center">
 暂无扫描记录——完成一轮采集后，这里会出现 24 小时渠道健康时间线</div>
<div class="ucard" id="healthcard" style="display:none"><div class="uhead"><span style="display:flex;align-items:center;gap:9px;flex-wrap:wrap"><span class="seclab inline"><span class="no">04</span><span class="zh">渠道健康</span><span class="en">HEALTH</span></span><span class="muted">近 24 小时 · 每格一轮扫描 · 点击格子看该轮日志</span></span>
 <span class="muted">解析自 monitor.log</span></div>
 <div id="hbody"></div>
 <div class="legend">
  <span><b class="hlb" style="background:var(--green)"></b>成功</span>
  <span><b class="hlb" style="background:var(--orange)"></b>部分/降级</span>
  <span><b class="hlb" style="background:var(--red)"></b>失败</span>
  <span><b class="hlb hlh"></b>维护</span>
  <span><b class="hlb" style="background:var(--line)"></b>未扫描</span></div></div>
</div><!-- /montab-health -->

<div id="montab-details" style="display:none">
<div class="ucard" id="tablecard"><div class="uhead"><span style="display:flex;align-items:center;gap:9px;flex-wrap:wrap"><span class="seclab inline"><span class="no">05</span><span class="zh">航班明细</span><span class="en">DETAILS</span></span></span>
 <span class="muted" id="fcnt"></span></div><div class="tabs" id="tabs">
  <span data-f="all" class="on">全部</span><span data-f="d">✈️ 直飞</span>
  <span data-f="tq">🔁 中转·达标</span><span data-f="t">🔁 中转·全部</span>
  <span data-f="q">🔥 仅达标</span>
  <span data-f="bag">🧳 直挂</span>
  <span id="fltBtn" onclick="togFlt()">🎛 筛选<b id="fltN" style="display:none"></b></span></div>
 <div class="fbar"><div class="frow" id="datechips"></div>
  <div class="frow" id="routechips"></div>
  <div class="frow" id="platchips"></div>
  <div class="frow" style="align-items:center">
   <span class="wingrp"><span class="chiplab">出发时段：</span><span id="wdep" class="winsel"></span></span>
   <span class="wingrp"><span class="chiplab">到达时段：</span><span id="warr" class="winsel"></span></span>
   <label>价格 ￥<input type="text" id="fpmin" style="width:72px" placeholder="不限" oninput="applyFltD()"> –
    <input type="text" id="fpmax" style="width:72px" placeholder="不限" oninput="applyFltD()"></label>
   <label>搜索 <input type="text" id="fq" style="flex:1 1 120px;max-width:180px;width:auto" placeholder="航班号/航司/中转" oninput="applyFltD()"></label>
   <label class="flab"><input type="checkbox" class="switch" id="fnostale" onchange="applyFlt()"> 隐藏补位数据（·Nh前）</label>
   <button class="btn2" onclick="resetFlt()">重置筛选</button>
   <button class="btn2" onclick="expCsv()">⬇ 导出CSV</button>
   <span class="muted">点击表头可排序（再点切换升降序）</span>
  </div></div>
 <div class="tw"><table id="ftable"><tr class="erow"><td colspan="9">加载中…</td></tr></table></div></div>
</div><!-- /montab-details -->
</div><!-- /monview -->

 <div id="cfgview" style="display:none">
 <div class="cfglayout">
 <aside class="cfgnav" id="cfgnav">
  <div class="cfgnav-t">配置分区</div>
  <input id="cfgSearch" class="cfgsearch" placeholder="🔍 搜索配置项"
   oninput="CFGQ=this.value;cfgFilter(CFGQ)">
  <div class="cfghit" id="cfgHits"></div>
  <span class="cnav on" data-p="login">🔐 渠道登录</span>
  <span class="cnav" data-p="users">👥 用户与航线</span>
  <span class="cnav" data-p="globals">🎛 全局参数</span>
 </aside>
 <div class="cfgmain" id="cfgmain">
 <div class="cfpanel" id="panel-login">
 <div class="ucard" id="sec-login"><div class="uhead"><span class="seclab inline"><span class="no">01</span><span class="zh">渠道登录</span><span class="en">LOGIN</span></span>
  <span class="muted">弹出浏览器完成登录，点「我已登录完成」即保存并生效（无需重启）</span></div>
 <div id="loginRows"><span class="muted">加载中…</span></div>
 <div class="row" style="margin-top:6px">
  <button class="btn2" onclick="loadLogin()">🔄 刷新状态</button>
  <span class="muted">携程必须登录 · 去哪儿/同程/途牛建议 · 飞猪无需 · 采集进行中时窗口可能被占用，稍后再试</span></div></div>
 </div><!-- /panel-login -->
 <div class="cfpanel" id="panel-users" style="display:none">
 <div class="ucard" id="sec-users"><div class="uhead"><span class="seclab inline"><span class="no">02</span><span class="zh">用户与航线</span><span class="en">USERS</span></span>
  <span class="muted">保存后立即热重载生效（无需重启）；仅数据库/日志路径等启动级项需改 config.yaml 后重启</span></div>
 <div id="cfgform"></div>
 <div class="row" style="margin-top:10px">
  <button onclick="addUser()">➕ 添加用户</button>
  <button class="warn" onclick="saveCfg()">💾 保存并生效</button>
  <button class="btn2" onclick="exportCfg()" title="下载本机配置 JSON（含钉钉等本地凭据，注意保管）">📤 导出配置</button>
  <button class="btn2" onclick="$('cfgImport').click()" title="从导出的 JSON 恢复配置（导入后需保存生效）">📥 导入配置</button>
  <input type="file" id="cfgImport" accept=".json,application/json" style="display:none" onchange="importCfg(this)">
  <span class="muted" id="cfgmsg"></span>
  <span class="muted" id="cfgDirty" style="display:none;color:var(--warn);font-weight:600">● 有未保存的修改</span></div></div>
 </div><!-- /panel-users -->
 <div class="cfpanel" id="panel-globals" style="display:none">
 <div class="ucard" id="sec-globals-card"><div class="uhead"><span class="seclab inline"><span class="no">03</span><span class="zh">全局参数</span><span class="en">GLOBAL</span></span>
  <span class="muted">全部保存即热生效（端口原地切换，零重启）；仅数据库/日志路径需重启</span></div>
 <div id="cfgglobals"><span class="muted">加载中…</span></div></div>
 </div><!-- /panel-globals -->
 </div><!-- /cfgmain -->
 </div><!-- /cfglayout -->
</div><!-- /cfgview -->
<div id="savebar" class="savebar">
 <span class="dot"></span><span id="saveTxt">有未保存的修改</span>
 <button onclick="saveCfg()">💾 保存并生效</button>
 <button class="warn" onclick="discardCfg()">放弃更改</button>
</div>
<div id="pvMask" class="pvmask" onclick="if(event.target===this)closePv()">
 <div class="pvcard" role="dialog" aria-label="钉钉推送预览">
  <div class="pvhead"><span id="pvTitle">预览</span><span class="pvx" id="pvClose" role="button" tabindex="0" onclick="closePv()" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();closePv()}" title="关闭（Esc）">✕</span></div>
  <div class="pvbody" id="pvBody"></div>
  <div class="pvfoot muted">本地近似渲染（标题/段落/加粗/链接/引用/进度条）· 明细总表图仅真实推送携带 · 以钉钉客户端实际效果为准</div>
 </div>
</div>
<footer id="foot" class="muted"></footer>
</div>
<script>
let S=null,F='all',U=0,SORT={k:'price',dir:1},FLT={plats:new Set(),routes:new Set(),dates:new Set(),dep:null,arr:null,pmin:0,pmax:0,no:false,q:''};
let LASTTXT='',NEXTRUN=null,TICKED=false,CHR={};
/* 渠道维护标记（无数据时角标）：如 {'飞猪':'维护中'}；渠道恢复后清空 */
const MAINT={};
const $=id=>document.getElementById(id);
/* 主题变量读取（走势绘制与悬停共用；此前 drawHover 误引 chart 局部
   同名常量，折线悬停十字线每次 mousemove 抛 ReferenceError 整体失效） */
const cssv=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
/* 智能刷新：响应逐字不变则跳过重渲染（悬停/展开/滚动不被打断）；
   页面不可见时不轮询，切回立即拉一次；上一笔未回不叠发
   （服务端重建期间叠发会触发并发重建，越等越慢） */
let LOADN=false;
async function load(){if(document.hidden||LOADN)return;LOADN=true;
 try{const r=await fetch('/api/state');const t=await r.text();
  if(t!==LASTTXT){LASTTXT=t;S=JSON.parse(t);
   try{render();health();pulse();}
   catch(e){console.error('render:',e);
    $('updated').textContent='（渲染异常：'+e.message+'）';}}}
 catch(e){$('updated').textContent='（服务未启动）';
  $('pill').textContent='⚪ 服务未启动';$('pill').className='pill';}
 finally{LOADN=false;}}
function pct(p,t){if(!t||!p)return 0;return Math.min(100,Math.max(2,(p/t-1)/0.5*100));}
function diffTxt(p,t){if(!t)return'';
 const d=Math.round(p-t);
   return d<=0?`<span class="okTxt">✅ 已低于线 ￥${-d}，可出手</span>`
            :`差 ￥${d}（${Math.round((p/t-1)*100)}%）`;}/* 「差」与推送 KPI 同词 */
function deltaTxt(d){if(d==null||isNaN(d))return'';
 if(d===0)return'较上轮持平';
 return d<0?`<span class="dn">较上轮 ↓￥${-d}</span>`
           :`<span class="up">较上轮 ↑￥${d}</span>`;}
function render(){const s=S;
 if(!s||!s.users){$('pill').textContent='⚪ 服务未启动';$('pill').className='pill';return;}/* 瞬时错误体不级联 */
 // 用户索引钳制：localStorage 存的 U 越尾（删用户/配置回退）时
 // s.users[U] 为 undefined → u.flights 抛错 → 页面永远停在骨架屏
 // 且单用户时切换 pills 隐藏无自救入口（实锤渲染死锁路径）
 if(!(U>=0)||U>=s.users.length)U=0;
 setNext(s.next_run);
 $('demoBar').style.display=s.demo?'':'none';
 /* 快捷键教学提为全局页脚（v1.5.44）：曾只活在概览 pulseLegend——
    无数据/非概览时整个界面零快捷键线索 */
 $('foot').innerHTML=(s.version?'v'+s.version+' · ':'')
  +'<a href="https://github.com/dengmeiluan/ticket-monitoring" target="_blank" rel="noopener">GitHub</a> · '
  +(s.demo?'在线演示 · 静态合成数据':'本地服务 127.0.0.1:8765')
  +'<span style="margin-left:14px"><span class="kbd">1</span>/<span class="kbd">2</span> 视图 <span class="kbd">3-6</span> 分栏 <span class="kbd">/</span> 搜索 <span class="kbd">R</span> 立即扫描</span>';
 $('updated').textContent=s.updated?'更新于 '+s.updated:'';
 if(!s.users||!s.users.length){
  $('pill').textContent='⚪ 未配置';$('pill').className='pill';
  $('users').innerHTML=`<div class="ucard hero"><div class="hicon">✈️</div>
   <h2>还没有监控任务</h2><p>三步开始追踪机票价格：</p>
   <ol><li>切到「⚙️ 配置」添加第一条航线（城市 + 日期 + 心理价）</li>
   <li>填入钉钉机器人 Webhook，点「🔔 测试推送」验证通路</li>
   <li>保存即生效——达标时推送 @你，重要警报可来电</li></ol>
   <button onclick="switchView('cfg')">前往配置 →</button></div>`;
  $('chartcard').style.display='none';$('tablecard').style.display='none';
  $('montabs').style.display='none';return;}
 $('chartcard').style.display='';$('tablecard').style.display='';
 $('montabs').style.display='';
 const u=s.users[U];
 // 达标以每用户逐行真实判定（后端按各自航线阈值）；
 // 无旗标不标档：缺 hit 的旧数据不再回退裸价判达标（v1.5.37 反转）
 const hit=s.users.some(x=>x.hit===true);
 const pill=$('pill');pill.textContent=(hit?'🚨':'❌')+' '+(hit?'有人已达标':'未达标');
 pill.className='pill'+(hit?' ok':'');
 document.title=(hit?'🚨 达标｜':'')+'机票监控台';
 /* 多用户切换 pills：明细/走势/日历跟随所选用户（单用户隐藏不占位） */
 const up=$('userPills');
 if((s.users||[]).length>1){up.style.display='';
  up.innerHTML='<span class="chiplab">用户：</span>'+(s.users||[]).map((x,i)=>
   `<span class="chip${i===U?' on':''}" onclick="pickUser(${i})">${he(x.name)}</span>`).join('')
   +'<span class="muted">明细 / 走势 / 日历跟随所选用户</span>';}
 else up.style.display='none';
 maybeNotify(s);
 let h='';
 (s.users||[]).forEach((x,i)=>{
  const xd=x.best.direct,xt=x.best.transfer;
  // KPI 阈值随最优航班所属航线（xd.th）：跨航线混用 routes[0] 的线=虚报
  const td=xd?(xd.th||x.th.direct):x.th.direct;
  const tt=xt?(xt.th||x.th.transfer):x.th.transfer;
  /* 卡头圆点与 KPI 绿卡/顶部 pill 同语言：qual（全口径）真值才亮；
     无旗标不标档，旧数据缺 qual 不再回退裸价（v1.5.37 反转）；
     补位 stale 不亮（与 KPI 卡/后端 hit 同口径，v1.5.38 补齐——
     曾三处两种结论：pill ❌ 而 udot 绿） */
  const _qq=b=>!!b&&b.qual===true&&!b.stale;
  const xh=_qq(xd)||_qq(xt);
  const mins=x.minsArr||[];
  const PKEY={'去哪儿':'qunar','飞猪':'fliggy','携程':'ctrip','同程':'tongcheng','途牛':'tuniu'};
  const PLATCN={qunar:'去哪儿',fliggy:'飞猪',ctrip:'携程',tongcheng:'同程',tuniu:'途牛'};
  const mHtml=mins.length?mins.map((m,k)=>
   /* FLT.plats 与 f.plat 同为中文渠道名（英文键只有 pdot 类在用）：
      曾塞 PKEY 英文键 → buildChips keep 恒空静默重置全渠道，
      「点击只看该渠道明细」从未生效 */
   `<span class="mchip mchip-link${k===0?' best':''}" title="渠道全线报价最低（含未过约束班次，未必可出手）· 点击只看该渠道明细" onclick="pickUser(${i});showMonTab('details');resetFlt();FLT.plats=new Set(['${m[0]}']);buildChips();buildRouteChips();buildDateChips();table()"><span class="pdot ${PKEY[m[0]]||''}"></span>${m[0]} <b>￥${m[1]}</b></span>`).join('')
   :(x.minsTxt||'<span class="muted">本轮暂无报价</span>');   /* 空态不悬挂「全线最低：｜」分隔符 */
  /* 多日期航线按日期分组 KPI（用户原话「我想看 10-5 和 10-6 的」）：
     全池 min 只露一个日期；分组后每日期直飞/中转各一卡可对比。
     kpi 卡结构与单日期路径同构（label/num/bar/muted/fb 五行）。 */
  const kpiCard=(kind,brief,th,lab,delta,dk)=>{
   /* dk=日期维度：多日期航线的 count-up PREV 键若不含日期，3 个日期的
      直飞卡共用 "0d" 互相串值当动画起点（数字乱滚） */
   /* 达标绿卡与推送 🎯 同口径：用 brief.qual（价格+中转全约束）判定；
      无旗标不标档，旧数据无 qual 不再回退价格口径（v1.5.37 反转）。
      行情最低未必能出手（非直挂/衔接不足）；
      补位 stale 行不亮绿（展示价非当轮实时价，与后端 hit/推送链同口径） */
   const hit=brief&&!brief.stale&&brief.qual===true;
   const near=!!brief&&!hit&&th&&brief.price>th&&(brief.price-th)/th<=NEAR_PCT/100;   /* 擦边带宽：与推送 kpi_tier_txt 同一词（单源口径 core.alerter）；brief 守卫在前（hit 同款，均在 !brief return 之前求值） */
   const platCn=brief?(PLATCN[brief.view_plat||brief.plat]||brief.plat||'去哪儿'):'去哪儿';/* 名随链接落点（view_plat） */
   if(!brief)return `<div class="kpi ${kind}"><div class="lab">${lab}${th?`（线 ￥${th}）`:''}</div>
    <div class="num">-</div>
    <div class="muted">该日期本轮未采到航班，下轮自动补上</div></div>`;
   /* 整卡可点：有行情链接时整卡加 clk 类打开同目标（卡内 numlink 保留，
      点击锚点处不重复开窗）；无链接卡不可点 */
   return `<div class="kpi ${kind}${hit?' hit':''}${brief.view?' clk':''}"${brief.view?` onclick="if(event.target.closest('a'))return;window.open('${brief.view}','_blank','noopener')"`:''}><div class="lab">${lab}${th?`（线 ￥${th}）`:''}</div>
    <div class="num">${brief?(brief.view?`<a class="numlink" data-k="${i}${kind}${dk||''}" data-v="${brief.price}" href="${brief.view}" target="_blank" rel="noopener" title="去${platCn}查看该航线">￥${brief.price}</a>`:'￥'+brief.price):'-'}</div>
    <div class="bar"><i class="${hit?'ok':(near?'near':'')}" style="width:${brief?pct(brief.price,th):0}%"></i></div>
    <div class="muted">${brief?(brief.qual===false&&th&&brief.price<=th
      ?'<span title="价格为行情价：非直挂/衔接不足/税前，未必能按此价出手">行情破线 · 约束未满足 ⚠</span>'
      :(near?`<span title="距达标线 ${NEAR_PCT}% 带宽内，未达标">擦边${Math.round((brief.price/th-1)*100)}% · 未达标</span>`:diffTxt(brief.price,th)))
      +(brief.stale?' · <span title="该渠道当轮无数据，展示的是近期补位价">'+brief.stale+'h前补位</span>':'')
      +(delta!=null?' · '+deltaTxt(delta):''):''}</div>
    <div class="muted fb">${brief?`${brief.route?brief.route+' · ':''}${brief.name} ${brief.depTime}-${brief.arrTime}${brief.cross?' '+brief.cross:''}${brief.trans?' 经'+brief.trans:''}${brief.stop?` <span class="stoptag">经停${brief.stopCity||''}${brief.stopTimeT?` 停${brief.stopTimeT}`:''}</span>`:''}${brief.bag?' <span class="bagtag">直挂</span>':''}`:''}</div></div>`;};
  const bbd=x.best_by_date||{};
  const bdates=bbd.dates||[];
  let kpis='';
  if(bdates.length>1){
   for(const d of bdates){
    const dd=(bbd.direct||{})[d],tp=(bbd.transfer||{})[d];
    const dth=dd?(dd.th||x.th.direct):x.th.direct;
    const tth=tp?(tp.th||x.th.transfer):x.th.transfer;
    kpis+=`<div class="dgroup"><div class="dlab">${d.slice(5).replace('-','/')}</div><div class="grid">`
     +kpiCard('d',dd,dth,'直飞最低',null,d)+kpiCard('t',tp,tth,'中转最低·次日'+((tp&&tp.tam)||'02:00')+'前到达',null,d)
     +`</div></div>`;}
  }else{
   kpis=`<div class="grid">`
    +kpiCard('d',xd,td,'直飞最低',x.delta?x.delta.direct:null)
    +kpiCard('t',xt,tt,'中转最低·次日'+((xt&&xt.tam)||'02:00')+'前到达',x.delta?x.delta.transfer:null)
    +`</div>`;
  }
  h+=`<div class="ucard"><div class="uhead">
   <span class="uname"><span class="udot${xh?' hit':''}" title="${xh?'已达标':'未达标'}"></span>${x.name}</span>
   <span class="uroutes">${x.routesTxt}</span></div>
   ${kpis}
   <div class="muted kpisum" style="margin-top:8px">全线最低：${mHtml} ｜ <a href="#" onclick="pickUser(${i});showMonTab('details');return false" style="color:var(--blue)">查看明细 ▾</a></div>
  </div>`;});
 /* 重建不丢键盘焦点：快照 activeElement 的 data-k 键值（numlink 等），
    重建后按键回焦（preventScroll 防跳动）；无键元素不救（CSS :hover
    无法程序恢复，同不救） */
 const fae=document.activeElement,fk=fae&&fae.getAttribute?fae.getAttribute('data-k'):null;
 $('users').innerHTML=h;
 if(fk){const fe=document.querySelector('[data-k="'+fk+'"]');if(fe)fe.focus({preventScroll:true});}
 countUps();
 CHART_ANIM=1;
 buildRouteChips();buildDateChips();buildChips();buildChartChips();
 if(MONTAB==='details')table();   /* 非明细视图跳过重建：#ftable 不可见画了也白画，切回时 showMonTab 补调 */
 chart();renderCal();mkactAll();}   /* render 尾无条件补键盘可达：概览/单航线路径下 chips 不再依赖子视图里的调用点（mkact 自身 dataset.kbd 幂等） */
/* KPI 数字 count-up：数据刷新时从旧值滚动到新值（600ms smoothstep） */
const PREV={};
function countUps(){document.querySelectorAll('a.numlink').forEach(el=>{
 const k=el.dataset.k,to=parseFloat(el.dataset.v);
 if(!k||isNaN(to))return;
 const from=PREV[k];PREV[k]=to;
 if(from==null||from===to)return;
 if(RM){el.textContent='￥'+Math.round(to);return;}/* reduced-motion 直取终值 */
 const t0=performance.now();
 const step=t=>{const p=Math.min(1,(t-t0)/600),e=p*p*(3-2*p);
  el.textContent='￥'+Math.round(from+(to-from)*e);
  if(p<1)requestAnimationFrame(step);};
 requestAnimationFrame(step);});}
function pickUser(i){U=i;saveUI();render();}
/* ===== V50 主页子视图工作台：一屏一会话（概览/走势·日历/明细/健康）；
   display 切换零 DOM 插拔（扩展免疫）；canvas 容器切回时须重绘 ===== */
let MONTAB='overview';
function showMonTab(t,silent){MONTAB=t;
 document.querySelectorAll('#montabs .mtab').forEach(x=>
  x.classList.toggle('on',x.dataset.t===t));
 ['overview','trend','details','health'].forEach(k=>{
  const el=$('montab-'+k);if(el)el.style.display=(k===t)?'':'none';});
 if(!silent){const el=$('montab-'+t);
  if(el){el.classList.remove('viewin');void el.offsetWidth;el.classList.add('viewin');}}
 if(t==='trend'&&!silent)chart();
 if(t==='details'&&!silent)table();   /* render 在非明细视图跳过了重建，切回补一拍（S 未到时自身有守卫） */
 try{localStorage.setItem('jpmontab',t);}catch(e){}}
document.querySelectorAll('#montabs .mtab').forEach(x=>{
 x.onclick=()=>showMonTab(x.dataset.t);});
try{const _mt=localStorage.getItem('jpmontab');
 if(_mt&&_mt!=='overview')showMonTab(_mt,true);}catch(e){}
/* onclick-only span 的键盘可达：tabindex+role=button，Enter/Space 转发 click
   （焦点环复用既有 ：focus-visible 规则；dataset.kbd 防 innerHTML 重建后重复绑定） */
function mkact(el){if(!el||el.dataset.kbd)return;el.dataset.kbd='1';
 el.tabIndex=0;el.setAttribute('role','button');
 el.addEventListener('keydown',e=>{
  if(e.key==='Enter'||e.key===' '){e.preventDefault();el.click();}});}
function mkactAll(){document.querySelectorAll('[role="button"],span[onclick],.mtab,#tabs span[data-f],.cnav,.calcell.link,.plitem,.dx').forEach(mkact);}
 /* 选择器说明：[role="button"] 覆盖配置折叠头（grouplab/uhead2/rhead/chhead，
    模板已写 role 但缺 tabindex）；.calcell/.plitem/.dx 为 div/i 标签补
    tabindex+回车转发；KPI 卡是整卡 div 不在此列——卡内数字本身是
    <a class="numlink"> 天然可 Tab，不双绑 */
/* ===== 明细表：筛选 + 排序 ===== */
/* 日期 chips：多日期航线（日期片）的明细此前混排无法按日分看——
   与 routechips 同一套多选模式（空选=全部）；单日期隐藏 */
function buildDateChips(){if(!S||!S.users)return;const u=S.users[U];
 const ds=[...new Set(u.flights.map(f=>f.date).filter(Boolean))].sort();
 const box=$('datechips');
 if(ds.length<2){box.innerHTML='';return;}
 const keep=[...FLT.dates].filter(d=>ds.includes(d));
 FLT.dates=new Set(keep.length?keep:ds);
 box.innerHTML='<span class="chiplab">日期：</span>'+ds.map(d=>
  `<span class="chip${FLT.dates.has(d)?' on':''}" onclick="togDate(this,'${d}')">${d.slice(5).replace('-','/')}</span>`).join('');}
function togDate(el,d){if(FLT.dates.has(d))FLT.dates.delete(d);else FLT.dates.add(d);
 el.classList.toggle('on');saveUI();table();}
function buildRouteChips(){if(!S||!S.users)return;const u=S.users[U];
 const rs=[...new Set(u.flights.map(f=>f.route).filter(Boolean))].sort();
 const box=$('routechips');
 if(rs.length<2){box.innerHTML='';return;}   // 单航线无角标数据，隐藏
 const keep=[...FLT.routes].filter(p=>rs.includes(p));
 FLT.routes=new Set(keep.length?keep:rs);
 box.innerHTML='<span class="chiplab">航线：</span>'+rs.map(p=>
  `<span class="chip${FLT.routes.has(p)?' on':''}" onclick="togRoute(this,'${p}')">${p}</span>`).join('');}
function togRoute(el,p){if(FLT.routes.has(p))FLT.routes.delete(p);else FLT.routes.add(p);
 el.classList.toggle('on');saveUI();table();}
function buildChips(){if(!S||!S.users)return;const u=S.users[U];
 const age=u.platAge||{};
 const ps=[...new Set(u.flights.map(f=>f.plat).concat(Object.keys(age)))].sort();
 const keep=[...FLT.plats].filter(p=>ps.includes(p));
 FLT.plats=new Set(keep.length?keep:ps);
 const badge=p=>{const a=age[p];
  if(MAINT[p]&&a==null)return'<i class="bd mid">'+MAINT[p]+'</i>';
  if(a==null)return'<i class="bd non">无数据</i>';
  if(a<0.5)return'';   /* 数据新鲜是常态，全员「新」无信息量（用户反馈移除） */
  const h=Math.max(1,Math.round(a));
  return a<6?`<i class="bd mid">${h}h前</i>`:`<i class="bd old">${h}h前</i>`;};
 const PK={'去哪儿':'qunar','飞猪':'fliggy','同程':'tongcheng','途牛':'tuniu','携程':'ctrip'};
 $('platchips').innerHTML='<span class="chiplab">渠道：</span>'+ps.map(p=>{
  const b=badge(p);
  return `<span class="chip${FLT.plats.has(p)?' on':''}" onclick="togChip(this,'${p}')"><span class="pdot ${PK[p]||''}"></span>${p}${b?' '+b:''}</span>`;}).join('');}
function togChip(el,p){if(FLT.plats.has(p))FLT.plats.delete(p);else FLT.plats.add(p);
 el.classList.toggle('on');saveUI();table();}
/* ===== 筛选/排序状态持久化（刷新不丢） ===== */
function saveUI(){try{localStorage.setItem('jpui',JSON.stringify(
 {F:F,U:U,sk:SORT.k,sd:SORT.dir,plats:[...FLT.plats],routes:[...FLT.routes],dates:[...FLT.dates],dep:FLT.dep,arr:FLT.arr,no:FLT.no,q:FLT.q,chr:CHR}));}catch(e){}}
function restoreUI(){try{const j=JSON.parse(localStorage.getItem('jpui')||'{}');
 if(j.F)F=j.F;if(j.sk)SORT={k:j.sk,dir:j.sd||1};
 if(Array.isArray(j.plats)&&j.plats.length)FLT.plats=new Set(j.plats);
 if(Array.isArray(j.dates)&&j.dates.length)FLT.dates=new Set(j.dates);
 if(Array.isArray(j.dep)&&j.dep.length===2)FLT.dep=j.dep;
 if(Array.isArray(j.arr)&&j.arr.length===2)FLT.arr=j.arr;
 if(Array.isArray(j.routes))FLT.routes=new Set(j.routes);
 if(j.chr)CHR=j.chr;
 if(j.no){FLT.no=true;$('fnostale').checked=true;}
 if(j.q){FLT.q=j.q;const el=$('fq');if(el)el.value=j.q;}
 U=Math.min(j.U||0,99);
 document.querySelectorAll('#tabs span').forEach(s=>
  s.classList.toggle('on',s.dataset.f===F));}catch(e){}}
function hm(t){const m=(t||'').match(/^(\d{1,2}):(\d{2})/);return m?(+m[1])*60+(+m[2]):null;}
/* 出发/到达时段挡位 chips（v1.5.12）：原生 time 输入整套替换为与配置页
   同语言的挡位单选——再次点选中挡=取消回「全部」；FLT.dep/arr 存 [起,终]
   分钟对（null=不限），table() 过滤与旧 t1/t2 语义一致 */
const WINS=[['全部',''],['凌晨','00:00|06:00'],['上午','06:00|12:00'],
            ['下午','12:00|18:00'],['晚间','18:00|23:59']];
function buildWinSel(){
 for(const [key,id] of [['dep','wdep'],['arr','warr']]){
  const cur=FLT[key];
  $(id).innerHTML=WINS.map(([n,w])=>{
   const on=(cur?(cur[0]+'|'+cur[1]):'')===w;
   return `<span class="chip schip${on?' on':''}" data-w="${w}" onclick="togWin(this,'${key}')">${n}</span>`;}).join('');}}
function togWin(el,key){
 const w=el.dataset.w, was=el.classList.contains('on');
 if(!el.parentElement)return;
 el.parentElement.querySelectorAll('.schip').forEach(c=>c.classList.remove('on'));
 if(was||!w){FLT[key]=null;}
 else{el.classList.add('on');FLT[key]=w.split('|');}
 saveUI();table();}
function applyFlt(){applyWins();
 FLT.pmin=parseFloat($('fpmin').value)||0;FLT.pmax=parseFloat($('fpmax').value)||0;
 FLT.no=$('fnostale').checked;
 FLT.q=($('fq').value||'').trim();saveUI();table();}
/* 文本筛选实时防抖（v1.5.41）：价格/搜索框曾只 onchange（失焦/回车才
   过滤），边打字边出结果更直观；250ms 防抖避免每键全表重建 */
let _fltT=0;
function applyFltD(){clearTimeout(_fltT);_fltT=setTimeout(applyFlt,250);}
function applyWins(){/* 由挡位 chips 状态推导分钟窗（无独立输入框可读） */
 for(const key of ['dep','arr']){
  const on=$(('w'+key)).querySelector('.schip.on');
  FLT[key]=on&&on.dataset.w?on.dataset.w.split('|'):null;}}
/* 类别挡回「全部」并同步 tabs 高亮（resetFlt/mchip 联动共用） */
function setCatAll(){F='all';
 document.querySelectorAll('#tabs span').forEach(s=>
  s.classList.toggle('on',s.dataset.f===F));}
function resetFlt(){FLT.routes=new Set();FLT.dates=new Set();FLT.dep=null;FLT.arr=null;
 FLT.plats=new Set();FLT.pmin=0;FLT.pmax=0;FLT.no=false;FLT.q='';setCatAll();
 buildWinSel();
 $('fpmin').value='';$('fpmax').value='';$('fnostale').checked=false;$('fq').value='';
 saveUI();buildChips();table();}
const HEADS=[['price','价格'],['cat','类别'],['date','日期'],['name','航班'],['dep','出发'],
 ['arr','到达'],['dur','时长'],['trans','中转'],['plat','渠道']];
function tmin(t){const m=(t||'').match(/(\d{1,2}):(\d{2})/);return m?(+m[1])*60+(+m[2]):null;}
function sval(f,k){switch(k){case 'price':return f.price;case 'cat':return f.transfer?1:0;
 case 'date':return f.date||'';
 case 'name':return f.name;case 'dep':return tmin(f.depTime)??99999;
 case 'arr':return tmin(f.arrTime)??99999;case 'dur':return f.durM||99999;
 case 'trans':return f.trans||'';case 'plat':return f.plat;default:return 0;}}
function sortCol(k){if(SORT.k===k)SORT.dir*=-1;else SORT={k:k,dir:1};saveUI();table();}
/* ===== 同班跨渠道比价：点击行展开（指纹含日期/经停——多日期航线同班次、
   直挂与经停报价不混串；经停对应后端 out 的 stop=bool(stopover)） ===== */
let EXP=null;
const fp=f=>(f.date||'')+'|'+f.depTime+'|'+f.arrTime+'|'+f.trans+'|'+f.cross+'|'+(f.stop?1:0);
/* 展开行渲染期预置为隐藏行，点击只切 display——表格零 childList 变更。
   （曾用"插/删一个 tr"的外科手术方案，但翻译/比价类扩展监听 DOM 插入会
   全页重扫，用户实测每点一行卡数秒；隐藏行只是 attribute 变更，不触发） */
function xrowHtml(u,k,open){
 const same=u.flights.filter(x=>fp(x)===k)
  .sort((a,b)=>a.price-b.price);
 const save=same.length>1?same[same.length-1].price-same[0].price:0;
 /* 离群警示（口径单源后端下发=钉钉/推送图同一 Alerter._outlier：最高>2×最低
    或跨舱位大类，v1.5.46 收口——前端本地曾只判 2×，跨舱位 ≤2× 时此处显示
    「可省」而推送显示「差」）：「可省」是假优惠——如实改「差」并标 ⚠️+最高价舱位 */
 const outlier=same.length>1&&!!same[same.length-1].outlier;
 const hiCn=(he((same[same.length-1].cabinT||'')).split(' · ')[0]);
 const chain=same.map(x=>`${he(x.plat)}${x.stale?'·'+x.stale+'h前':''} `
  +(x.view?`<a class="vw" href="${x.view}" target="_blank" rel="noopener" title="去${he(x.plat||'去哪儿')}查看该航线">￥${x.price} ↗</a>`
  :'￥'+x.price)).join(' ＜ ');
 return `<tr class="xrow"${open?'':' style="display:none"'}><td colspan="9">⚖️ 同班比价：${chain}`+
    (save?(outlier?`（差 ￥${save} · ${hiCn?hiCn+' · ':''}渠道报价口径差异 ⚠️）`
                  :`（可省 ￥${save}）`)
         :'（仅一渠道报价）')+`</td></tr>`;}
function _hideXrows(){document.querySelectorAll('#ftable tr.xrow').forEach(
 x=>{x.style.display='none';});}
/* 展开切换：目标行的紧邻隐藏行 display 翻转，无任何节点插拔/全表重建 */
function togRow(k,row){
 const cur=row&&row.nextElementSibling;
 if(EXP===k){EXP=null;if(cur)cur.style.display='none';return;}
 EXP=k;
 _hideXrows();
 if(cur)cur.style.display='';
 else table();}
/* 筛选+排序统一出口：表格渲染与 CSV 导出共用同一结果集 */
function filteredRows(){const u=S.users[U];
 const rows=u.flights.filter(f=>{
  if(F==='d'&&f.transfer)return false;
  if(F==='t'&&!f.transfer)return false;
  if(F==='tq'&&!(f.transfer&&f.qual))return false;
  if(F==='q'&&!f.qual)return false;
  if(F==='bag'&&!(f.transfer&&f.bag))return false;
  if(FLT.plats.size&&!FLT.plats.has(f.plat))return false;
  if(FLT.routes.size&&f.route&&!FLT.routes.has(f.route))return false;
  if(FLT.dates.size&&!FLT.dates.has(f.date))return false;
  if(FLT.dep){const m=tmin(f.depTime);
   if(m===null)return false;
   if(m<hm(FLT.dep[0])||m>hm(FLT.dep[1]))return false;}
  if(FLT.arr){const m=tmin(f.arrTime);
   if(m===null)return false;
   if(m<hm(FLT.arr[0])||m>hm(FLT.arr[1]))return false;}
  if(FLT.pmin&&f.price<FLT.pmin)return false;
  if(FLT.pmax&&f.price>FLT.pmax)return false;
  if(FLT.no&&f.stale)return false;
  if(FLT.q){const q=FLT.q.toLowerCase();
   const hay=(f.name+' '+(f.code||'')+' '+(f.trans||'')+' '+f.plat).toLowerCase();
   if(!hay.includes(q))return false;}
  return true;});
 rows.sort((a,b)=>{const x=sval(a,SORT.k),y=sval(b,SORT.k);
  return (x<y?-1:x>y?1:0)*SORT.dir;});
 return rows;}
function expCsv(){if(!S||!S.users){toast('数据加载中','err');return;}
 const rows=filteredRows();
 if(!rows.length){toast('当前筛选无数据','err');return;}
 const e2=v=>'"'+String(v==null?'':v).replace(/"/g,'""')+'"';
 const head=['价格','类别','日期','航班','航班号','出发','到达','航站楼','跨天','时长','均延','中转','衔接','直挂','经停','舱位','渠道','数据时效','状态'];
 const lines=[head.map(e2).join(',')];
 for(const f of rows)lines.push([
  f.price,f.transfer?'中转':'直飞',f.date||'',f.name,f.code||'',f.depTime,f.arrTime,
  (f.depTerminal&&f.arrTerminal&&f.depTerminal!==f.arrTerminal)?(f.depTerminal+'→'+f.arrTerminal):(f.arrTerminal||f.depTerminal||''),
  f.cross||'',f.dur||'',(f.avgDelay!=null?f.avgDelay+'分':''),f.trans||'',
  (f.layoverT||'')+(f.layMin?(f.layoverM>=f.layMin?'✓':(f.layoverM?'⚠':'')):''),
  f.bag?'是':'',f.stop?'是':'',(f.cabinT||'').replace(/<[^>]*>/g,''),f.plat,
  f.stale?('补位·'+f.stale+'h前'):'实时',
  f.qual?'真达标':(f.brk?'行情破线':(f.near?'擦边':''))].map(e2).join(','));
 const blob=new Blob([String.fromCharCode(65279)+lines.join(String.fromCharCode(13,10))],{type:'text/csv;charset=utf-8'});
 const a=document.createElement('a');
 a.href=URL.createObjectURL(blob);
 const _p=n=>String(n).padStart(2,'0');const _d=new Date();
 a.download='flights_'+_d.getFullYear()+_p(_d.getMonth()+1)+_p(_d.getDate())+'_'+_p(_d.getHours())+_p(_d.getMinutes())+'.csv';
 a.click();URL.revokeObjectURL(a.href);}
 function table(){if(!S||!S.users)return;/* 状态未到不渲染（render 会重调） */
  const u=S.users[U];
  /* 全量重建保滚动：滚动容器是表格外层 .tw（overflow:auto），重建前存
     scrollTop 写回——智能刷新 10s 一拍，明细长表滚动位曾每拍弹回顶部 */
  const tw=document.querySelector('#tablecard .tw');const st=tw?tw.scrollTop:0;
  buildWinSel();
  const rows=filteredRows();
  $('ftable').classList.toggle('big',rows.length>150);
 let h='<thead><tr>'+HEADS.map(([k,n])=>
  `<th class="srt${SORT.k===k?' on':''}" data-k="${k}" tabindex="0" onclick="sortCol('${k}')" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();sortCol('${k}')}">${n}${SORT.k===k?(SORT.dir>0?' ▲':' ▼'):''}</th>`).join('')+'</tr></thead><tbody>';
 let ri=0;
 for(const f of rows){
  const k=fp(f);
  /* 斑马纹按数据行序号显式加类：行间夹着隐藏 xrow，nth-child(even)
     永远落在 xrow 上被 ：not(.xrow) 排除——斑马纹从未生效过。
     达标行不加斑马（v1.5.44）：#ftable tr.zebra 带 ID 特异性恒压
     tr.qual，「仅达标」筛选下绿色语义曾呈奇灰偶绿条纹抖动 */
  const zb=ri++%2===1;
  const zebra=(!f.qual&&zb)?' zebra':'';
  h+=`<tr class="${f.qual?'qual':''}${zebra}" style="cursor:pointer;--i:${Math.min(ri-1,7)}" data-k="${k}" tabindex="0" title="${he(f.date||'')} ${he(f.code||'')}｜点击或回车展开同班各渠道比价" onclick="togRow('${k}',this)" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();togRow('${k}',this)}">`+
  `<td class="price${f.brk?' brk':(f.near?' near':'')}"${f.brk?' title="行情破线未达标：因非直挂/衔接不足/税前等原因暂不可出手"':(f.near?` title="擦边：距达标线 ≤${NEAR_PCT}%，未达标"`:'')}>${f.qual?'🔥 ':''}￥${f.price}${f.xphan?' <span class="stl" style="color:var(--warn);cursor:help" title="跨渠道孤低价：显著低于其他渠道同航班报价，疑似页面污染/错误价——不参与达标判定与行情最优">⚠</span>':''}${f.platKey==='fliggy'?'<span class="pretax">税前</span>':''}</td>`+
  `<td><span class="tag ${f.transfer?'t-t':'t-d'}">${f.transfer?'中转':'直飞'}</span></td>`+
  `<td>${f.date?f.date.slice(5).replace('-','/'):'—'}</td>`+
  `<td>${he(f.name)}${f.stop?`<span class="stoptag">经停${he(f.stopCity||'')}${f.stopTimeT?` 停${he(f.stopTimeT)}`:''}</span>`:''}${f.bag?'<span class="bagtag">直挂</span>':''}${(f.cabinT||f.prate||f.meal||f.shareCarrier||f.fewTicket||f.depTerminal||f.avgDelay!=null)?`<div class="stl" style="margin-top:3px">${[f.cabinT?he(f.cabinT):'',f.prate?'准点'+he(String(f.prate))+'%':'',f.meal?he(f.meal):'',f.shareCarrier?'共享·'+he(f.shareCarrier):'',f.fewTicket?he(f.fewTicket):'',f.depTerminal||f.arrTerminal?he((f.depTerminal&&f.arrTerminal&&f.arrTerminal!==f.depTerminal)?(f.depTerminal+'→'+f.arrTerminal):(f.arrTerminal||f.depTerminal)):'',f.avgDelay!=null?'延'+he(String(f.avgDelay))+'分':''].filter(Boolean).join(' · ')}</div>`:''}${f.view?`<a class="vw" href="${f.view}" target="_blank" rel="noopener" onclick="event.stopPropagation()" title="去${he(f.plat||'去哪儿')}查看该航线">↗</a>`:''}${f.route?`<span class="stl"> ${he(f.route)}</span>`:''}</td><td>${f.depTime}</td>`+
  `<td>${f.arrTime}${f.cross?`<span class="stl"> ${he(f.cross)}</span>`:''}</td>`+
  `<td>${f.dur||'—'}</td><td>${f.trans?he(f.trans):'—'}${f.lay2dep?`<div class="stl">二段 ${f.lay2dep} 起飞</div>`:''}${f.layoverT?`<div class="stl lay${(f.layMin>0&&(+f.layoverM||0)>=f.layMin)?' ok':''}"${f.layMin>0?' title="航线衔接下限 '+f.layMin+' 分钟"':''}>停${f.layoverT}</div>`:''}</td>`+
  `<td><span class="pdot ${f.platKey||''}"></span>${f.plat}${f.stale?`<span class="stl">·${f.stale}h前</span>`:''}</td></tr>`+
  xrowHtml(u,k,EXP===k);
 }
 if(!rows.length) h+='<tr class="erow"><td colspan="9">没有符合条件的航班——试试清空上方时段/价格筛选，或点「重置筛选」恢复全部 '+u.flights.length+' 班</td></tr>';
 /* 同 render()：重建前快照 data-k（th=排序键 / tr=fp 行键），重建后回焦 */
  const fae=document.activeElement,fk=fae&&fae.getAttribute?fae.getAttribute('data-k'):null;
  $('ftable').innerHTML=h+'</tbody>';
  if(tw)tw.scrollTop=st;
  if(fk){const fe=document.querySelector('[data-k="'+fk+'"]');if(fe)fe.focus({preventScroll:true});}
 $('fcnt').textContent=u.name+'：'+rows.length+' / '+u.flights.length+' 班';
 updFltN();mkactAll();}
 /* ===== 走势图：多航线可切（routesArr），单航线回落旧行为；48h/7d 范围 ===== */
 /* 擦边带宽单源（脚本顶层，chart() 的 TIER 与 drawHover() 的 fl 两处消费）：
    与 core.alerter NEAR_RATIO 同步律（前端无法 import），改必两处同步 */
 const NEAR=1.1;
 const NEAR_PCT=Math.round((NEAR-1)*100);   /* 带宽百分数派生单点：UI 文案禁再写「≤10%」字面量（改带宽只动 NEAR） */
function curRoute(){const u=S.users[U];
 const arr=(u.routesArr&&u.routesArr.length)?u.routesArr
  :[{label:u.routesTxt||u.name,th:u.th,history:u.history}];
 let st=CHR[u.name];if(typeof st==='number')st={i:st};
 st=st||{i:0,r:'48h',m:'line'};CHR[u.name]=st;
 let idx=st.i||0;if(idx>=arr.length)idx=0;
 return {arr,idx,r:arr[idx],range:st.r||'48h',mode:st.m||'line'};}
function setRange(r){if(!S||!S.users)return;/* 状态未到不记状态（render 重调） */
 const u=S.users[U];let st=CHR[u.name];
 if(typeof st==='number')st={i:st};st=st||{i:0};st.r=r;CHR[u.name]=st;saveUI();
 $('rng48').className='rngchip'+(r==='48h'?' on':'');
 $('rng7d').className='rngchip'+(r==='7d'?' on':'');
 chart();renderCal();}
function setMode(m){if(!S||!S.users)return;
 const u=S.users[U];let st=CHR[u.name];
 if(typeof st==='number')st={i:st};st=st||{i:0};st.m=m;CHR[u.name]=st;saveUI();
 $('mdLine').className='rngchip'+(m==='line'?' on':'');
 $('mdK').className='rngchip'+(m==='kline'?' on':'');
 chart();}
/* K线聚合：[[MM-DD HH:MM,价],...] → 桶 OHLC（48h=2h 桶，7d=6h 桶） */
function toCandles(pts,bucketMin){const map={};
 let Y=new Date().getFullYear(),prevM=0;
 for(const p of pts){
  /* 跨年递推：时序月份回落（12→01）即年份进一；首点若拼出未来时刻
     （开年回看上月数据）整体回退一年——恒用当前年曾致跨年桶序颠倒 */
  const mm=+(p[0]||'').slice(0,2);
  if(prevM&&mm<prevM)Y+=1;
  prevM=mm;
  let t=new Date(Y+'-'+p[0].replace(' ','T')).getTime();
  if(t>Date.now()+6e4){Y-=1;t=new Date(Y+'-'+p[0].replace(' ','T')).getTime();}
  if(isNaN(t))continue;
  const k=Math.floor(t/(bucketMin*60000));
  (map[k]=map[k]||[]).push(p);}
 return Object.keys(map).map(Number).sort((a,b)=>a-b).map(k=>{
  const g=map[k];const vs=g.map(x=>x[1]);
  /* f=桶档位：桶内含真达标轮（q=2）则整桶标真达标——曾取「桶内最低价
     那轮」档位，真达标轮被更低的行情轮掩盖整桶消失（列表🔥图上无环，
     与明细不同义，v1.5.38）；否则与「低」标注同指桶最低价档 */
  const hit2=g.find(x=>x[2]===2);
  const lo=hit2||g.reduce((a,b)=>b[1]<a[1]?b:a);
  return {t0:g[0][0],o:vs[0],c:vs[vs.length-1],
   h:Math.max.apply(null,vs),l:Math.min.apply(null,vs),f:lo[2],
   /* hp=真达标轮自身价（v1.5.44）：桶最低价可能属于另一轮「行情破线
      但 _transfer_ok 不满足」的点——●环曾落在明细不标 🔥 的价上 */
   hp:hit2?hit2[1]:null}});}
function buildChartChips(){if(!S||!S.users)return;
 const u=S.users[U];const box=$('chartRoutes');
 const arr=u.routesArr&&u.routesArr.length?u.routesArr:null;
 const CR=curRoute();
 $('rng48').className='rngchip'+(CR.range==='48h'?' on':'');
 $('rng7d').className='rngchip'+(CR.range==='7d'?' on':'');
 $('mdLine').className='rngchip'+(CR.mode==='line'?' on':'');
 $('mdK').className='rngchip'+(CR.mode==='kline'?' on':'');
 if(!arr||arr.length<2){box.innerHTML='';return;}
 const idx=CR.idx;
 box.innerHTML='<span class="chiplab">航线：</span>'+arr.map((r,i)=>
  `<span class="chip${i===idx?' on':''}" onclick="togChart(${i})">${he(r.label)}</span>`).join('');mkactAll();}
function togChart(i){if(!S||!S.users)return;
 const nm=S.users[U].name;let st=CHR[nm];
 if(typeof st==='number')st={i:st};st=st||{r:'48h'};st.i=i;CHR[nm]=st;
 saveUI();buildChartChips();CHART_ANIM=1;
 const w=document.querySelector('.chartwrap');
 if(w){w.classList.remove('viewin');void w.offsetWidth;w.classList.add('viewin');}
 chart();renderCal();}
 function chart(){if(!S||!S.users)return;/* 状态未到不画（render 会重调） */
 const RUN=++CHART_RUN;/* 新 chart 接管：旧入场动画帧作废 */
 const u=S.users[U];const CR=curRoute();
 /* 三档判定（折线点/K线桶共用，环标语言与明细🔥/推送🎯一致）：
    2=真达标（后端旗标） 1=行情破线未达标 -1=擦边（距达标线 ≤10%） 0=线外。
    折线前点状态曾手写条件序颠倒（pv[1]<=tv 先于旗标判断恒真）——
    破线段逐点串珠、○→●真达标入场环被吞 */
 /* 无旗标不标档，裸价回退=虚画真达标（v1.5.37 反转） */
 /* 擦边带宽 ×1.1 与 report.py NEAR_RATIO=0.10 同值，改一处必两处同步（v1.5.44 单源律） */
 const TIER=(q,v,tv)=>q===2?2:(q===1?1:(q==null?0:(v<=tv?2:(v<=tv*NEAR?-1:0))));
 $('chartTitle').textContent=u.name+(CR.r.label?' · '+CR.r.label:'')
  +(CR.range==='7d'?' · 7天':'');
 /* 环标图例随模式切换（折线=点环；K线=桶最低价环）——K线曾零环
    而图例照念折线文案（图与例不一致）；「擦边」词面与推送 PNG
    环标小注逐字同语言（v1.5.47 收口） */
 $('ringNote').innerHTML=CR.mode==='kline'
  ?'环标（标在桶最低价）：<span style="color:var(--green)">●</span>真达标（与明细🔥同口径）· <span style="color:var(--green)">○</span>行情破线未达标 · <span style="color:var(--warn)">○</span>擦边 · <span style="color:var(--red)">▼</span>达标回落；K线=轮最低价分桶（开/收=桶内首末轮）；绿桶=桶内回落（与达标绿无关）'
  :'环标：<span style="color:var(--green)">●</span>真达标（与明细🔥同口径）· <span style="color:var(--green)">○</span>行情破线未达标 · <span style="color:var(--warn)">○</span>擦边 · <span style="color:var(--red)">▼</span>达标回落；两线均为行情池最低 · 中转不限直挂';
 const c=$('chart'),ctx=c.getContext('2d');
 /* 容器隐藏（非走势子视图）时跳过绘制：offsetWidth=0 画了也白画；
    切回走势子视图时 showMonTab 会重绘 */
 if(!c.offsetWidth)return;
 /* 高度单源：CSS clamp(240px,38vh,360px) 弹性，dpr 尺寸按 clientHeight
    实测换算（resize 监听重调 chart 即随视口重读） */
 const dpr=window.devicePixelRatio||1,H=c.clientHeight;
 /* 尺寸未变不重设：width/height 赋值即清空画布+重分配位图，hover 合帧
    后每次移动仍会进 chart()，无守卫时等于白重绘（v1.5.41） */
 if(c.width!==Math.round(c.offsetWidth*dpr)||c.height!==Math.round(H*dpr)){
  c.width=Math.round(c.offsetWidth*dpr);c.height=Math.round(H*dpr);}
 ctx.setTransform(dpr,0,0,dpr,0,0);
 const W=c.offsetWidth,L=64,R=14,T=14,B=52;
 const H0=CR.range==='7d'?(CR.r.history7||CR.r.history):CR.r.history;
 const hd=H0.direct,ht=H0.transfer;
 /* 主题感知配色：暗色下网格/坐标轴用主题变量，不再硬编码浅色 */
 const GRID=cssv('--line')||'#eef2f7',AXIS=cssv('--mut')||'#9aa8b6';
 const K=CR.mode==='kline';
 /* 标注 halo 底色随主题（K线/折线两分支共用；块级作用域须在此声明） */
 const halo=cssv('--card')||'#fff';
 /* 标注白底块：密集折线区 3px 柔边 halo 仍花，底块+细描边彻底隔开背景 */
 const HALOBG=cssv('--card')||'#fff',HALOBD=cssv('--line2')||'#e5e9f0';
 /* 已放置标注盒（[x0,y0,x1,y1]）：候选位互避——低点标签间曾互相叠字 */
 const placedBoxes=[];
 const tagBox=(tx,ty,tw)=>{ctx.beginPath();
  if(ctx.roundRect)ctx.roundRect(tx-4,ty-11,tw+8,15,4);
  else ctx.rect(tx-4,ty-11,tw+8,15);
  ctx.fillStyle=HALOBG;ctx.fill();
  ctx.lineWidth=1;ctx.strokeStyle=HALOBD;ctx.stroke();};
 /* ▼红=达标回落标记（与推送图同语言）：锚离开真达标态的第一点，
    画在该点上方，宽 8px 与现环标（r5）协调 */
 const fallMark=(x,y)=>{ctx.fillStyle=cssv('--red')||'#c22a2e';
  ctx.beginPath();ctx.moveTo(x-4,y-12);ctx.lineTo(x+4,y-12);
  ctx.lineTo(x,y-6);ctx.closePath();ctx.fill();};
 const BUCKET=CR.range==='7d'?360:120;   // K线桶：48h→2h，7d→6h
 const CD=K?toCandles(hd,BUCKET):null,CT=K?toCandles(ht,BUCKET):null;
 let vals=K?CD.concat(CT).map(c=>[c.h,c.l]).reduce((a,b)=>a.concat(b),[])
            .concat([CR.r.th.direct,CR.r.th.transfer]).filter(x=>x>0)
           :hd.concat(ht).map(x=>x[1]).concat([CR.r.th.direct,CR.r.th.transfer]).filter(x=>x>0);
 if(!vals.length){ctx.clearRect(0,0,W,H);HPTS=null;
  $('chartEmpty').style.display='flex';return;}
 $('chartEmpty').style.display='none';
 const lo=Math.min(...vals)-30,hi=Math.max(...vals)+30;
 const N=K?Math.max(CD.length,CT.length,1):Math.max(hd.length,ht.length,1);
 const X=i=>L+(W-L-R)*(N>1?i/(N-1):0.5),Y=v=>T+(H-T-B)*(1-(v-lo)/(hi-lo));
 const chartDraw=()=>{
 ctx.clearRect(0,0,W,H);ctx.font='11px '+(cssv('--num')||'sans-serif');
 for(let k=0;k<=4;k++){const v=lo+(hi-lo)*k/4;
  ctx.strokeStyle=GRID;ctx.setLineDash([2,4]);
  ctx.beginPath();ctx.moveTo(L,Y(v));ctx.lineTo(W-R,Y(v));ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle=AXIS;ctx.fillText('￥'+Math.round(v),6,Y(v)+4);}
 /* X 轴双行刻度：HH:MM 行(H-22) + 跨天日期行(H-8)；按实测宽度避让，
    相邻标签绝不互撞。日期标签挂在分隔竖线底部（旧版画图内顶部，
    被折线/散点压住不可读）。折线取数据点时刻，K线取桶起始 t0；
    旧「首/中/尾全时刻」刻度循环已删——两套刻度叠加双重绘制互撞 */
 const tickT=K?(i=>((CD[i]||CT[i]||{}).t0||'')):(i=>((hd[i]||ht[i]||[''])[0]));
 const NT=K?Math.max(CD.length,CT.length,1):Math.max(hd.length,ht.length);
 if(NT&&tickT(0)){
  ctx.font='11px '+(cssv('--num')||'sans-serif');
  const stepN=Math.max(1,Math.ceil(NT/5));
  let lastR=-1e9;
  for(let i=0;i<NT;i+=stepN){
   const s=tickT(i);if(!s)continue;
   const lb=s.slice(-5),lw=ctx.measureText(lb).width;
   const lx=Math.min(Math.max(X(i)-lw/2,L-46),W-R-lw);
   if(lx<lastR+10)continue;
   ctx.fillStyle=AXIS;ctx.fillText(lb,lx,H-22);lastR=lx+lw;}
  let prevDay=tickT(0).slice(0,5);
  for(let i=1;i<NT;i++){
   const s=tickT(i);if(!s)continue;
   const day=s.slice(0,5);
   if(day!==prevDay){
    const gx=X(i),dw=ctx.measureText(day).width;
    const dx=Math.min(Math.max(gx-dw/2,L-46),W-R-dw);
    /* --stl 运行时取值+alpha 分离（v1.5.46：曾 rgba(192,86,26,.45)
       亮色快照，暗色 --stl=#e08555 不随动；fallback 同步现行值） */
    ctx.globalAlpha=.45;ctx.strokeStyle=cssv('--stl')||'#c0561a';
    ctx.lineWidth=1;
    ctx.beginPath();ctx.moveTo(gx,T);ctx.lineTo(gx,H-B);ctx.stroke();
    ctx.globalAlpha=1;
    ctx.lineWidth=3;ctx.strokeStyle=halo;
    ctx.strokeText(day,dx,H-8);
    ctx.fillStyle=cssv('--stl')||'#c0561a';ctx.fillText(day,dx,H-8);
    prevDay=day;}}}
 const zone=(v)=>{if(!v||v<lo||v>hi)return;ctx.fillStyle=cssv('--okzone')||'rgba(67,192,114,.14)';ctx.fillRect(L,Y(v),W-L-R,H-B-Y(v));};
 zone(CR.r.th.direct);zone(CR.r.th.transfer);
 const dash=(v,col)=>{if(!v||v<lo||v>hi)return;ctx.strokeStyle=col;ctx.setLineDash([6,5]);
  ctx.beginPath();ctx.moveTo(L,Y(v));ctx.lineTo(W-R,Y(v));ctx.stroke();ctx.setLineDash([]);};
 dash(CR.r.th.direct,cssv('--red')||'#c22a2e');dash(CR.r.th.transfer,cssv('--thline')||'#8a6d1f');
 if(K){
  /* K线：涨红空心 跌绿实心（A股习惯）；直飞左偏 中转右偏 */
  const cw=Math.max(4,Math.min(15,(W-L-R)/Math.max(N,1)*0.30));
  const drawK=(cs,off)=>{cs.forEach((c,i)=>{
   const cx=X(i)+off,up=c.c>=c.o,col=up?(cssv('--red')||'#c22a2e'):(cssv('--green')||'#0e8345');
   ctx.strokeStyle=col;ctx.lineWidth=1.2;
   ctx.beginPath();ctx.moveTo(cx,Y(c.h));ctx.lineTo(cx,Y(c.l));ctx.stroke();
   const yT=Y(Math.max(c.o,c.c)),yB=Y(Math.min(c.o,c.c));
   if(up)ctx.strokeRect(cx-cw/2,yT,cw,Math.max(1.5,yB-yT));
   else{ctx.fillStyle=col;ctx.fillRect(cx-cw/2,yT,cw,Math.max(1.5,yB-yT));}});};
  drawK(CD,-cw*0.62);drawK(CT,cw*0.62);
  /* K线档位环（与折线三档同语言）：●粗绿=真达标（锚桶内真达标轮自身
     价） ○细绿=行情破线 ○琥珀=擦边（两 ○ 锚桶最低价=影线低点，
     与「低」标注同所指）；仍按状态入场+末桶防串珠（桶数 48h≤24/7d≤28，
     密度无忧） */
  const ringK=(cs,off,tv)=>{if(!tv)return;
   const stOf=c=>TIER(c.f,c.l,tv);
   cs.forEach((c,i)=>{const st=stOf(c);
    const pv=i>0?cs[i-1]:null;
    const pst=pv?stOf(pv):0;
    if(pst===2&&st!==2)fallMark(X(i)+off,Y(c.l));/* ▼红=达标回落 */
    if(!st)return;
    if(!pst||pst!==st||i===cs.length-1){
     /* ●=真达标环锚 hp（桶内真达标轮自身价，与明细 🔥 同所指——
        v1.5.44 终局：曾锚桶最低价，行情最低轮≠达标轮时环画在非达标
        价上）；○环仍锚桶最低价（行情档语义） */
     const rp=(st===2&&c.hp!=null)?c.hp:c.l;
     const grn=cssv('--green')||'#0e8345';
     if(st===2){/* ●实心=真达标（与折线/图例同语言，v1.5.38） */
      ctx.beginPath();ctx.arc(X(i)+off,Y(rp),5,0,7);
      ctx.fillStyle=grn;ctx.fill();
      ctx.lineWidth=1.5;ctx.strokeStyle=cssv('--card')||'#fff';ctx.stroke();
     }else{
      const ring=st===-1?[5,2,cssv('--warn')||'#9a7800']
       :[5.5,1,grn];
      ctx.beginPath();ctx.arc(X(i)+off,Y(rp),ring[0],0,7);
      ctx.fillStyle=cssv('--card')||'#fff';ctx.fill();
      ctx.lineWidth=ring[1];ctx.strokeStyle=ring[2];ctx.stroke();}}});};
  ringK(CD,-cw*0.62,CR.r.th.direct);ringK(CT,cw*0.62,CR.r.th.transfer);
  HPTS={kline:true,cd:CD,ct:CT,cw:cw,L:L,Rx:W-R,T:T,B:B,
   thd:CR.r.th.direct,tht:CR.r.th.transfer};
  /* K线最低影线标注（同样带完整时刻）；候选位按盒内影线命中数取最少 */
  let best=null;CD.forEach((c,i)=>{if(!best||c.l<best.c.l)best={c,i,s:'d'};});
  CT.forEach((c,i)=>{if(!best||c.l<best.c.l)best={c,i,s:'t'};});
   if(best&&best.i!==(best.s==='d'?CD:CT).length-1){
    const bx=X(best.i)+(best.s==='d'?-cw*0.62:cw*0.62);
    ctx.font='bold 11px '+(cssv('--num')||'sans-serif');
    const ktag='低 ￥'+Math.round(best.c.l)+' '+String(best.c.t0||'').slice(0,11);
    const kw=ctx.measureText(ktag).width;
    const hitN=(cx,cy)=>{let n=0;
     for(let s=0;s<2;s++){const arr=s?CT:CD,off=s?cw*0.62:-cw*0.62;
      for(let i=0;i<arr.length;i++){
       const cxx=X(i)+off;
       if(cxx>=cx-3&&cxx<=cx+kw+3){
        const yh=Y(arr[i].h),yl=Y(arr[i].l);
        if(yl>=cy-12&&yh<=cy+4)n++;}}}
     return n;};
    const yh0=Y(best.c.h),yl0=Y(best.c.l);
    const cands=[[bx+6,yh0-8],[bx+6,yl0+16],[bx-kw-6,yh0-8],
     [bx-kw-6,yl0+16],[bx+6,T+12],[bx-kw-6,T+12]];
    let kx=bx+6,ky=yh0-8,bn=1e9;
    for(const c of cands){
     const cx=Math.min(Math.max(c[0],L),W-kw-6);
     const cy=Math.min(Math.max(c[1],T+12),B-6);
     const n=hitN(cx,cy)+(placedBoxes.some(b=>
      !(cx+kw+3<b[0]||b[2]<cx-3||cy+4<b[1]||b[3]<cy-12))?99:0);
     if(n<bn){bn=n;kx=cx;ky=cy;}
     if(!bn)break;}
    tagBox(kx,ky,kw);
    /* 「低」标签随所属系列色（直飞蓝/中转橙），不再与达标线红同色混淆 */
    ctx.fillStyle=best.s==='d'?(cssv('--blue')||'#0b62d6'):(cssv('--orange')||'#c96a10');
    ctx.fillText(ktag,kx,ky);
    placedBoxes.push([kx-3,ky-12,kx+kw+3,ky+4]);
    ctx.font='11px sans-serif';}
  }else{
  const series=(pts,color,tv)=>{if(!pts.length)return;
   ctx.beginPath();ctx.moveTo(X(0),Y(pts[0][1]));
   /* 平滑曲线：水平控制点三次贝塞尔（monotone 不过冲）+ 渐变面积填充
      （X/Y 接收索引——曾误传时间标签致整条曲线 NaN 消失，仅剩散点） */
   for(let i=1;i<pts.length;i++){
    const x0=X(i-1),y0=Y(pts[i-1][1]),x1=X(i),y1=Y(pts[i][1]);
    ctx.bezierCurveTo((x0+x1)/2,y0,(x0+x1)/2,y1,x1,y1);}
   ctx.strokeStyle=color;ctx.lineWidth=2.2;ctx.stroke();
   ctx.lineTo(X(pts.length-1),H-B);ctx.lineTo(X(0),H-B);
   ctx.closePath();
   const g=ctx.createLinearGradient(0,T,0,H-B);
   g.addColorStop(0,color+'44');g.addColorStop(1,color+'08');
   ctx.fillStyle=g;ctx.fill();
   const RPT=pts.length>240?1.4:(pts.length>120?2:2.6);/* 7 天窗≈672 点/系：1.8px 间距实心点连成珠链淹没低点，>240 点降半径（report 侧 v1.5.43 同思想） */
   pts.forEach((p,i)=>{ctx.fillStyle=color;ctx.beginPath();
    ctx.arc(X(i),Y(p[1]),RPT,0,7);ctx.fill();});
   if(tv>0)/* 分档点环（与推送图/明细同语义）：●粗绿=真达标（后端旗标，
      与明细🔥/推送🎯同口径）；○细绿=行情破线但未达标（非直挂/
      衔接不足/税前）；○琥珀=擦边（距达标线 ≤10%，未必达标）。仍只画状态入场点
      与最新点，长期同状态段不逐点密铺成串（7 天窗口实测） */
    pts.forEach((p,i)=>{const q=p[2],v=p[1];
     const st=TIER(q,v,tv);
     const pv=i>0?pts[i-1]:null;
     const pst=pv?TIER(pv[2],pv[1],tv):0;
     if(pst===2&&st!==2)fallMark(X(i),Y(v));/* ▼红=达标回落 */
    if(st&&(!pst||pst!==st||i===pts.length-1)){
     const grn=cssv('--green')||'#1e8e3e';
     if(st===2){/* ●实心=真达标（与图例字面成立；亮描边防曲线穿心）
        ——曾两种档只差 1px 线宽，●/○ 视觉不可分 */
      ctx.beginPath();ctx.arc(X(i),Y(v),5,0,7);
      ctx.fillStyle=grn;ctx.fill();
      ctx.lineWidth=1.5;ctx.strokeStyle=cssv('--card')||'#fff';ctx.stroke();
     }else{
      const ring=st===-1?[5,2,cssv('--warn')||'#9a7800']
       :[5.5,1,grn];
      ctx.beginPath();ctx.arc(X(i),Y(v),ring[0],0,7);
      ctx.fillStyle=cssv('--card')||'#fff';ctx.fill();
      ctx.lineWidth=ring[1];ctx.strokeStyle=ring[2];ctx.stroke();}}});};
  series(hd,cssv('--blue')||'#0b62d6',CR.r.th.direct);series(ht,cssv('--orange')||'#c96a10',CR.r.th.transfer);
  HPTS={d:hd.map((p,i)=>[X(i),Y(p[1]),p[1],p[0],p[2]]),
   t:ht.map((p,i)=>[X(i),Y(p[1]),p[1],p[0],p[2]]),
   L:L,Rx:W-R,T:T,B:B,thd:CR.r.th.direct,tht:CR.r.th.transfer};
  /* 最低点标注：带完整日期时刻（只显 HH:MM 会被误读为"刚刚暴跌"）。
     候选位按「标签盒内压到多少数据点」取最少——密集 7 天窗固定偏移
     曾直接盖在线上（小屏/密集场景图文互遮挡实锤），全撞才落首选 */
  const markMin=(pts,color)=>{if(!pts||pts.length<3)return;
   let mi=0;pts.forEach((p,i)=>{if(p[1]<pts[mi][1])mi=i;});
   if(mi===pts.length-1)return;
   const [x,y,v,t]=pts[mi];
   ctx.font='bold 11px '+(cssv('--num')||'sans-serif');
   const tag=('低 ￥'+Math.round(v)+' '+String(t||'').slice(0,11));
   const tagW=ctx.measureText(tag).width;
   const all=HPTS.d.concat(HPTS.t);
   const hitN=(cx,cy)=>{let n=0;
    for(const q of all)
     if(q[0]>=cx-3&&q[0]<=cx+tagW+3&&q[1]>=cy-12&&q[1]<=cy+4)n++;
    return n;};
   const cands=[];
   for(const dy of [-10,16])
    for(const dx of [6,6+tagW*.55,6-tagW*.55,6+tagW*1.1,6-tagW*1.1])
     cands.push([x+dx,y+dy]);
   for(const dx of [6,6+tagW*1.05,6-tagW*1.05,6+tagW*2.1,6-tagW*2.1])
    cands.push([x+dx,T+12]);
   let bx=x+6,by=y-10,bn=1e9;
   for(const c of cands){
    const cx=Math.min(Math.max(c[0],L),W-tagW-6);
    const cy=Math.min(Math.max(c[1],T+12),B-6);
    /* 标签互叠罚 999：互叠绝对劣于压数据（白底块保可读，叠字不可读） */
    const n=hitN(cx,cy)+(placedBoxes.some(b=>
     !(cx+tagW+3<b[0]||b[2]<cx-3||cy+4<b[1]||b[3]<cy-12))?999:0);
    if(n<bn){bn=n;bx=cx;by=cy;}
    if(!bn)break;}
   tagBox(bx,by,tagW);
   ctx.fillStyle=color;ctx.fillText(tag,bx,by);
   placedBoxes.push([bx-3,by-12,bx+tagW+3,by+4]);
   ctx.font='11px sans-serif';};
  markMin(HPTS.d,cssv('--blue')||'#0b62d6');markMin(HPTS.t,cssv('--orange')||'#c96a10');
 }
 };  /* /chartDraw */
 chartDraw();
 /* 入场动画：左→右擦除重现（数据刷新/切航线触发，hover 重绘不触发）；
    RM（prefers-reduced-motion）时直取终值——CSS 全禁了 JS 动画仍跑 */
 if(CHART_ANIM&&!RM){CHART_ANIM=0;const t0=performance.now();
  const step=t=>{if(RUN!==CHART_RUN)return;/* 已被新 chart 接管：旧帧作废 */
   const p=Math.min(1,(t-t0)/700),e=1-Math.pow(1-p,3);
   ctx.save();ctx.beginPath();ctx.rect(L-2,0,(W-L-R+4)*e,H);ctx.clip();
   chartDraw();ctx.restore();
   if(p<1)requestAnimationFrame(step);};
  requestAnimationFrame(step);}
 else if(CHART_ANIM)CHART_ANIM=0;
}
/* 悬停提示：十字线 + 数值浮框（折线读价 / K线读 OHLC） */
let HPTS=null,CHART_ANIM=0,CHART_RUN=0;
function drawHover(x){const c=$('chart'),ctx=c.getContext('2d');
 if(!HPTS)return;
 /* 档位后缀（与环标/明细🔥同语言）：flag 2=真达标 🎯、1=行情破线 ○ */
 const fl=(q,v,tv)=>q===2?' 🎯':(q===1?' ○行情破线':(tv&&v<=tv*NEAR?' ○擦边':(tv?' ·距线￥'+(v-tv):'')));   /* ● 实心=真达标专属；NEAR 同步律见 TIER；线外点补距线读数免目测虚线 */
 let ax,txt,parts=[];
 if(HPTS.kline){
  const {cd,ct,L,Rx}=HPTS;
  const N=Math.max(cd.length,ct.length);if(N<1)return;
  let i=Math.round((x-L)/(Rx-L)*(N-1));i=Math.max(0,Math.min(N-1,i));
  const kd=cd[i],kt=ct[i];if(!kd&&!kt)return;
  ax=L+(Rx-L)*(N>1?i/(N-1):0.5);
  parts=[];
  if(kd)parts.push('直飞(轮最低) 低￥'+kd.l+fl(kd.f,kd.l,HPTS.thd)+' 开￥'+kd.o+' 收￥'+kd.c+' 高￥'+kd.h);
  if(kt)parts.push('中转(轮最低) 低￥'+kt.l+fl(kt.f,kt.l,HPTS.tht)+' 开￥'+kt.o+' 收￥'+kt.c+' 高￥'+kt.h);
  txt=((kd||kt).t0||'')+'　'+parts.join('　');
 }else{
  const {d,t,L,Rx,T,B}=HPTS;
  const N=Math.max(d.length,t.length);if(N<1)return;
  let i=Math.round((x-L)/(Rx-L)*(N-1));i=Math.max(0,Math.min(N-1,i));
  const pd=d[i],pt=t[i];
  if(!pd&&!pt)return;
  ax=(pd||pt)[0];
  parts=[];
  if(pd){ctx.fillStyle=cssv('--blue')||'#0b62d6';ctx.beginPath();ctx.arc(pd[0],pd[1],4.5,0,7);ctx.fill();
   parts.push('直飞最低 ￥'+pd[2]+fl(pd[4],pd[2],HPTS.thd));}
  if(pt){ctx.fillStyle=cssv('--orange')||'#c96a10';ctx.beginPath();ctx.arc(pt[0],pt[1],4.5,0,7);ctx.fill();
   parts.push('中转最低 ￥'+pt[2]+fl(pt[4],pt[2],HPTS.tht));}
  txt=((pd||pt)[3]||'')+'　'+parts.join('　');
 }
 ctx.strokeStyle=getComputedStyle(document.documentElement).getPropertyValue('--mut').trim()||'#9aa8b6';
 ctx.setLineDash([4,4]);
 ctx.beginPath();ctx.moveTo(ax,HPTS.T);ctx.lineTo(ax,HPTS.B);ctx.stroke();ctx.setLineDash([]);
 /* 行预算：窄画布一行装不下（K线双系列 OHLC 读数 ~600px，390px 手机
    画布 ~370px，offsetWidth-w-4 为负曾把 tooltip 半截裁出画布）→
    按「　」部件拆行；单部件仍超宽时 K线降级只留 低/收 决策数字 */
 ctx.font='12px sans-serif';
 const avail=Math.max(c.offsetWidth-8,80);
 let lines=[txt];
 if(ctx.measureText(txt).width+18>avail&&parts.length)lines=parts.slice();
 let w=Math.max(...lines.map(s=>ctx.measureText(s).width))+18;
 if(w>avail&&HPTS.kline){
  lines=lines.map(s=>s.replace(/ 开￥\d+/,'').replace(/ 高￥\d+/,'').replace(/  +/g,' '));
  w=Math.max(...lines.map(s=>ctx.measureText(s).width))+18;}
 w=Math.min(w,avail);
 let bx=Math.min(Math.max(ax-w/2,4),c.offsetWidth-w-4);
 const bh=24+(lines.length-1)*16;
 ctx.fillStyle='rgba(44,62,80,.93)';   /* 有意深底白字：两主题皆可读的 tooltip 惯例，勿随主题反转 */
 if(ctx.roundRect){ctx.beginPath();ctx.roundRect(bx,4,w,bh,6);ctx.fill();}
 else ctx.fillRect(bx,4,w,bh);
 ctx.fillStyle='#fff';
 lines.forEach((s,ix)=>ctx.fillText(s,bx+9,20+ix*16));}
/* hover 合帧（v1.5.41）：每事件全量 chart() 曾在宽屏 dpr=2 下逐移动
   重分配画布+全量重绘，密集段可感卡顿——rAF 合帧一拍一绘；画布尺寸
   未变时不再重设 width/height（重设即清空+重分配，见 chart 内守卫） */
let _hovX=null,_hovRaf=0;
const _hovPaint=()=>{_hovRaf=0;if(_hovX===null)return;
 const r=$('chart').getBoundingClientRect();drawHover(_hovX-(r.left));};
$('chart').onmousemove=e=>{if(!HPTS)return;
 _hovX=e.clientX;if(!_hovRaf)_hovRaf=requestAnimationFrame(()=>{chart();_hovPaint();});};
$('chart').onmouseleave=()=>{_hovX=null;if(_hovRaf){cancelAnimationFrame(_hovRaf);_hovRaf=0;}
 if(HPTS)chart();};
/* 触屏 hover：touchstart/move 映射 mousemove 同一 hover 路径，touchend
   清十字线（passive 不阻塞滚动；复用 drawHover 与清理路径，不另写逻辑） */
const _tchHover=e=>{if(!HPTS)return;
 const t=e.touches&&e.touches[0];if(!t)return;
 _hovX=t.clientX;if(!_hovRaf)_hovRaf=requestAnimationFrame(()=>{chart();_hovPaint();});};
$('chart').addEventListener('touchstart',_tchHover,{passive:true});
$('chart').addEventListener('touchmove',_tchHover,{passive:true});
$('chart').addEventListener('touchend',()=>{_hovX=null;
 if(_hovRaf){cancelAnimationFrame(_hovRaf);_hovRaf=0;}
 if(HPTS)chart();},{passive:true});
/* ===== toast（替代 alert）与按钮内联二次确认（替代 confirm） ===== */
function toast(msg,kind){let box=$('toasts');
 if(!box){box=document.createElement('div');box.id='toasts';
  document.body.appendChild(box);}
 const t=document.createElement('div');t.className='toast '+(kind||'');
 t.textContent=msg;box.appendChild(t);
 t.onclick=()=>{if(t.parentNode)t.remove();};   /* 点击即关（错误类驻留更长） */
 setTimeout(()=>{t.classList.add('out');
  setTimeout(()=>{if(t.parentNode)t.remove();},350);},kind==='err'?5000:2600);}
async function api(act,msg){const b=event.target;
 if(!b.dataset.arming){                 /* 第一次点击：进入确认态 3s */
  b.dataset.arming='1';b.dataset.label=b.textContent;
  b.style.minWidth=b.offsetWidth+'px';  /* 确认文案更宽，锁首态宽防同排按钮被挤右移 */
  b.textContent='⚠ 再点一次确认';b.title=msg;b.classList.add('arming');
  setTimeout(()=>{if(b.dataset.arming){delete b.dataset.arming;
   b.textContent=b.dataset.label;b.classList.remove('arming');b.style.minWidth='';}},3000);
  return;}
 delete b.dataset.arming;b.textContent=b.dataset.label;b.title='';
 b.style.minWidth='';
 b.classList.remove('arming');b.classList.add('busy');
 try{const r=await fetch('/api/'+act,{method:'POST'});const j=await r.json();
  toast(j.ok?'✅ 已触发，页面自动刷新':'❌ 失败: '+(j.err||''),
   j.ok?'ok':'err');load();}
 catch(e){toast('❌ 请求失败','err');}
 b.classList.remove('busy');}
/* 通用内联二次确认（删除类小按钮） */
function armConfirm(el,fn){if(!el.dataset.arming){
 el.dataset.arming='1';el.dataset.label=el.textContent;
 el.textContent='⚠ 确认';el.classList.add('arming');
 setTimeout(()=>{if(el.dataset.arming){delete el.dataset.arming;
  el.textContent=el.dataset.label;el.classList.remove('arming');}},3000);return;}
 delete el.dataset.arming;el.textContent=el.dataset.label;
 el.classList.remove('arming');fn();}
/* ===== 渠道健康时间线：/api/health（monitor.log 解析，与状态同拍刷新） ===== */
let HL=null;
async function health(){try{const r=await fetch('/api/health');
 const t=await r.text();if(t===HL)return;HL=t;renderHealth(JSON.parse(t));}catch(e){}}
function renderHealth(j){
 const _he=$('healthEmpty');
 if(!j||!j.rounds||!j.rounds.length){
  if(_he)_he.style.display='';           // 空态：别整片空白（v1.5.38）
  return;}
 if(_he)_he.style.display='none';
 $('healthcard').style.display='';
 const CN={'qunar':'去哪儿','fliggy':'飞猪','ctrip':'携程','tongcheng':'同程','tuniu':'途牛'};
 const SM={'ok':'成功','part':'部分成功','fail':'失败','maint':'维护模式'};
 let h='';
 const plats=Object.keys(j.stats||{}).sort();
 for(const p of plats){const st=j.stats[p];
  const att=st.ok+st.part+st.fail;
  const rate=att?Math.round(st.rate*100):null;
  const cells=j.rounds.map(r=>{const c=(r.plats||{})[p];
   if(!c)return `<i class="hc none" title="${r.ts} 未扫描"></i>`;
   const det=c.s==='ok'?`成功 ${c.ok}/${c.tot}`:(c.note||SM[c.s]);
   return `<i class="hc ${c.s}" style="cursor:pointer" tabindex="0" role="button" onclick="showLog('${p}','${r.ts}')" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();showLog('${p}','${r.ts}')}" title="${r.ts}｜${he(det)}（点击查看日志）"></i>`;}).join('');
  const cls=rate===null?'':(rate>=95?'ok':(rate>=80?'mid':'bad'));
  h+=`<div class="hrow"><span class="hlab"><span class="pdot ${p}"></span>${CN[p]||p}</span>`
   +`<span class="hcells">${cells}</span>`
   +`<span class="hbadge ${cls}" title="近24h成功率 ${st.ok}/${att}${st.maint?'（维护 '+st.maint+' 轮）':''}">${rate===null?'—':rate+'%'}</span></div>`;}
 $('hbody').innerHTML=h;}
function he(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;');}
/* ===== 健康格子点击：该轮该渠道日志原文（复用预览弹层） ===== */
async function showLog(p,ts){try{
 const r=await fetch('/api/logtail?plat='+p+'&ts='+encodeURIComponent(ts));
 const j=await r.json();if(!j.ok){toast(j.err||'读取失败','err');return;}
 $('pvTitle').textContent='📄 '+( {'qunar':'去哪儿','fliggy':'飞猪','ctrip':'携程','tongcheng':'同程','tuniu':'途牛'}[p]||p )+'｜'+ts+' 轮日志';
 const lines=j.lines||[];
 $('pvBody').innerHTML=lines.length
  ?'<pre class="logpre">'+he(lines.join(String.fromCharCode(10)))+'</pre>'
  :'<div class="muted">该时间窗无日志（或已滚动出日志尾部 2MB 读取范围）</div>';
 _openPvMask();}catch(e){toast('请求失败','err');}}
/* ===== V50 运行脉冲：/api/pulse（每轮每渠道行数/耗时，签派台脉搏） ===== */
let PU=null;
const PCN={'qunar':'去哪儿','fliggy':'飞猪','ctrip':'携程','tongcheng':'同程','tuniu':'途牛'};
async function pulse(){try{const r=await fetch('/api/pulse');
 const t=await r.text();if(t===PU)return;PU=t;renderPulse(JSON.parse(t));}catch(e){}}
function renderPulse(j){const rs=(j&&j.rounds)||[];
 if(!rs.length)return;
 $('pulsecard').style.display='';
 const last=rs[rs.length-1];
 const chans={};let runs=0,oks=0,latSum=0,latN=0,failRounds=0;
 for(const r of rs){if(r.fails>0)failRounds++;
  for(const p in (r.chans||{})){const c=r.chans[p];
   chans[p]=chans[p]||{n:0};
   chans[p].n++;runs++;if(c.ok)oks++;latSum+=c.lat;latN++;}}
 const rate=runs?Math.round(oks/runs*100):null;
 const avgLat=latN?(latSum/latN).toFixed(1):null;
 let up='';
 try{if(j.since){const h=(Date.now()-new Date(j.since.replace(/-/g,'/')).getTime())/36e5;
  if(h>=0)up=h>=1?(h>=10?Math.round(h):h.toFixed(1))+' 小时':Math.round(h*60)+' 分钟';}}catch(e){}
 const cell=(lab,val,sub,cls)=>'<div class="stat"><div class="slab">'+lab+'</div>'
  +'<div class="sval '+(cls||'')+'">'+val+'</div><div class="ssub">'+sub+'</div></div>';
 $('statline').innerHTML=
  cell('本轮采集',last.rows+' 条',he(last.ts)+' · 用时 '+last.dur+'s')
 +cell('渠道成功率',rate==null?'—':rate+'%',
   '近 '+rs.length+' 轮 · '+failRounds+' 轮有失败',rate==null?'':(rate>=95?'ok':(rate>=80?'':'bad')))
 +cell('渠道均耗',avgLat==null?'—':avgLat+'s','单渠道平均抓取耗时')
 +cell('服务在线',up||'—',j.since?'自 '+j.since:'');
 /* 轮次堆叠柱：段=渠道，高=行数占比，红帽=该轮有渠道失败 */
 const maxRows=Math.max.apply(null,rs.map(r=>r.rows).concat([1]));
 $('pulsebars').innerHTML=rs.map(r=>{
  const tip=he(r.ts)+' · '+r.rows+' 条 · '+r.dur+'s'
   +(r.fails?' · '+r.fails+' 渠道失败':'')
   +String.fromCharCode(10)+Object.keys(r.chans||{}).map(p=>{
    const c=r.chans[p];return (PCN[p]||p)+' '+(c.ok?c.rows+' 条':'无数据')+' · '+c.lat+'s';}).join(' · ');
  if(!r.rows)return `<div class="pbar zero" title="${tip}" role="button" tabindex="0" onclick="gotoMonTab('health')" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();gotoMonTab('health')}"><i></i></div>`;
  const segs=Object.keys(r.chans||{}).map(p=>{const c=r.chans[p];
   if(!c.rows)return'';
   return '<i class="seg pseg-'+p+'" style="height:'
    +Math.max(3,Math.round(c.rows/maxRows*100))+'%"></i>';}).join('');
  return `<div class="pbar" title="${tip}" role="button" tabindex="0" onclick="gotoMonTab('health')" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();gotoMonTab('health')}">${r.fails?'<i class="cap"></i>':''}${segs}</div>`;}).join('');
 $('pulseLegend').innerHTML=Object.keys(chans).map(p=>
  '<span><i class="pseg-'+p+'" style="width:12px;height:8px;border-radius:2px;display:inline-block;vertical-align:middle;margin-right:5px"></i>'+(PCN[p]||p)+'</span>').join('')
 +'<span><b style="background:var(--red)"></b>红帽 = 该轮有渠道失败</span>';}/* kbd 提示已常驻页脚，不再双份 */
/* ===== 价格日历热力卡：跟随当前走势航线 ===== */
function renderCal(){if(!S||!S.users)return;/* 状态未到不画 */
 const u=S.users[U];
 const CR=curRoute();const cal=CR.r.cal||[];
 $('calTitle').textContent=CR.r.label||'';
 /* MM-DD → 完整日期映射：日历格点击跳明细按该日期筛选（明细 dates 是完整格式） */
 const dfull={};(u.flights||[]).forEach(f=>{if(f.date)dfull[f.date.slice(5)]=f.date;});
 /* 7 天洞察统计：最低/均价/降价天数/当前距最低（数据源同走势与日历，零后端开销） */
 const h7=((CR.r.history7||{}).direct||[]).map(p=>p[1]).filter(v=>v>0);
 const d7=cal.slice(-7).map(c=>c[1]).filter(v=>v>0);
  if(h7.length){const mn=Math.min.apply(null,h7);
  const avg=d7.length?Math.round(d7.reduce((a,b)=>a+b,0)/d7.length)
            :Math.round(h7.reduce((a,b)=>a+b,0)/h7.length);
  let drops=0;for(let i=1;i<d7.length;i++)if(d7[i]<d7[i-1])drops++;
  const cur=h7[h7.length-1];
  /* 指标胶囊 + 图例小字分层：曾 7 项混排一行 12px muted，决策指标与
     解码图例主次不分 */
  $('calStats').innerHTML='<span class="cs-i">近7天最低 <b>￥'+mn+'</b></span>'
   +'<span class="cs-i">日均 <b>￥'+avg+'</b></span>'
   +'<span class="cs-i">降价 <b>'+drops+'</b> 天</span>'
   +'<span class="cs-i">'+(cur<=mn?'当前即最低':'比最低高 <b>'+Math.round((cur/mn-1)*100)+'%</b>')+'</span>'
   +'<span class="cs-lg">深绿=真达标 浅绿=行情破线 琥珀=擦边 红=超线（直飞）</span>';}
 else $('calStats').innerHTML='<span class="cs-lg">深绿=真达标 浅绿=行情破线 琥珀=擦边 红=超线（直飞） · 点击格看该日明细</span>';
 if(!cal.length){$('calcard').style.display='none';return;}
 $('calcard').style.display='';
 const th=(CR.r.th&&CR.r.th.direct)||0;
 let mn=Infinity;for(const p of cal)if(p[1]>0&&p[1]<mn)mn=p[1];
 let h='';
 /* 档位底色运行时取语义变量（暗色随动）：曾硬编码亮色值——擦边旧琥珀
    (176,137,0)、超线旧红 (214,45,48) 均落后 v1.5.44 加深后的
    --warn/--red，暗色下更深；达标绿也随主题换亮色 */
 const _rgbv=n=>{const m=/^#([0-9a-f]{6})$/i.exec(cssv(n)||'');
  return m?[parseInt(m[1].slice(0,2),16),parseInt(m[1].slice(2,4),16),parseInt(m[1].slice(4,6),16)]:null;};
 const CG=_rgbv('--green')||[14,131,69],CW=_rgbv('--warn')||[154,120,0],CRD=_rgbv('--red')||[194,42,46];
 for(const cell of cal){const d=cell[0],v=cell[1],q=cell[2];
  let bg='var(--rowalt)',fg='var(--mut)';
  if(v>0&&th>0){
   if(q===2){bg='rgba('+CG+',.88)';fg='#fff';}               /* 真达标（旗标） */
   else if(q===1){const r=v/th;                              /* 行情破线未达标（无旗标不标档，裸价回退已除 v1.5.37） */
    const a=0.25+Math.min(0.5,(1-r)*2.2);
    /* 底色同走 --green 变量（v1.5.46：曾硬编码 46,164,79 亮色快照——
       三绿并存病灶残留，暗色不随动；与 CG 同源） */
    bg='rgba('+CG+','+a.toFixed(2)+')';fg=a>0.55?'#fff':'var(--tx)';}
   else if(q===-1){                                          /* 擦边：最低价距达标线 ≤10% 未达标（价格数字琥珀高亮 .cp.near） */
    bg='rgba('+CW+',.30)';fg='var(--tx)';}
   else{const r=v/th;
    const a=0.16+Math.min(0.6,(r-1)*2.2);
    bg='rgba('+CRD+','+a.toFixed(2)+')';fg=a>0.5?'#fff':'var(--tx)';}}
  const best=v>0&&v===mn;
  const near=q===-1;
  const tip=v>0?(th>0?(q===2?d+' 直飞最低 ￥'+v+' · 真达标（可出手）✅'
    :(v<=th?d+' 直飞最低 ￥'+v+' · 行情破线，未必可出手 ⚠'
    :(q===-1?d+' 直飞最低 ￥'+v+' · 擦边（距达标线 ≤'+NEAR_PCT+'%，未达标）'
    :d+' 直飞最低 ￥'+v+' · 超线 '+Math.round((v/th-1)*100)+'%')))
   :d+' 直飞最低 ￥'+v)+(best?' · 近期最低':''):(d+' 无数据');
  const jump=dfull[d]?` onclick="jumpCalDate('${dfull[d]}')"`:'';
  h+='<div class="calcell'+(best?' best':'')+(jump?' link':'')+'" style="background:'+bg+';color:'+fg+'" title="'+tip+(jump?' · 点击看该日明细':'')+'"'+jump+'>'
   +'<div class="cd">'+d+'</div><div class="cp'+(near?' near':'')+'">'+(v>0?'￥'+v:'—')+'</div>'
   +'<div class="cx">'+(v>0?(best?'★ 最低':(mn<Infinity?'+￥'+(v-mn):'')):'')+'</div></div>';}
 $('calgrid').innerHTML=h;mkactAll();}
/* 日历格点击 → 明细子视图并锁定该日期（与全线最低 chip 同款联动路径） */
function jumpCalDate(d){showMonTab('details');
 resetFlt();FLT.dates=new Set([d]);/* 先 reset 再锁日期：dates 不被清 */
 const CR=curRoute();/* 多航线：卡 label 带 " MM/DD" 后缀，截掉再入 Set */
 if(S.users[U].routesArr&&S.users[U].routesArr.length>1)
  FLT.routes=new Set([CR.r.label.replace(/\s+\d{2}[/]\d{2}\s*$/,'')]);
 saveUI();buildChips();buildRouteChips();buildDateChips();table();}
/* ===== 达标浏览器通知 + 提示音（开关持久化；按 航线+类别+价格 去重） ===== */
/* 存储被禁（隐私模式等）时裸访问 localStorage 抛异常会中止整段脚本——
   降级默认值（通知关），页面其余功能不受累 */
let NT={on:false,ctx:null};
try{NT.on=localStorage.getItem('jpnotify')==='1';}catch(e){}
function ntIcon(){const b=$('ntBtn');if(!b)return;
 b.textContent=NT.on?'🔔':'🔕';
 b.title=NT.on?'达标浏览器通知已开启（点击关闭）':'达标时浏览器通知+提示音（点击开启）';}
function togNotify(){NT.on=!NT.on;try{localStorage.setItem('jpnotify',NT.on?'1':'0')}catch(e){}/* 存储禁用（隐私模式）不中断交互 */;
 if(NT.on&&'Notification' in window&&Notification.permission==='default')
  Notification.requestPermission();
 if(NT.on&&!NT.ctx){try{NT.ctx=new (window.AudioContext||window.webkitAudioContext)();}catch(e){}}
 ntIcon();}
function chime(){if(!NT.ctx)return;const c=NT.ctx;
 [[880,0],[1320,0.16]].forEach(function(ft){const o=c.createOscillator(),g=c.createGain();
  o.frequency.value=ft[0];o.type='sine';o.connect(g);g.connect(c.destination);
  const t0=c.currentTime+ft[1];
  g.gain.setValueAtTime(0.0001,t0);
  g.gain.exponentialRampToValueAtTime(0.22,t0+0.02);
  g.gain.exponentialRampToValueAtTime(0.0001,t0+0.15);
  o.start(t0);o.stop(t0+0.16);});}
function maybeNotify(s){if(!NT.on||!s.users||!s.users.length)return;
 let kind='',price=0,route='';
 /* 与推送 🎯 同口径：仅 qual 行（价格+中转到达/衔接/直挂全约束）触发通知。
    行情破线但约束不满足的班次不再误响（与钉钉侧 v1.5.30 修复同因） */
 for(const x of s.users){
  for(const f of (x.flights||[])){
   if(!f.qual||f.stale)continue;   /* 补位价不响铃（与推送链同口径） */
   if(!kind||f.price<price){
    kind=f.transfer?'中转':'直飞';price=f.price;
    route=(f.route?f.route+' ':'')+x.routesTxt;}}}
 if(!kind)return;
 const sig=route+'|'+kind+'|'+price;
 try{if(sig===localStorage.getItem('jpnlast'))return;
  localStorage.setItem('jpnlast',sig);}catch(e){}/* 存储被禁：去重跳过，通知照发 */
 if('Notification' in window&&Notification.permission==='granted'){
  try{new Notification('🚨 机票达标 ￥'+price,
   {body:route+' '+kind+' 已低于心理线，回控制台查看明细'});}catch(e){}}
 chime();}
ntIcon();
/* ===== 钉钉推送预览：markdown 近似渲染（分段→块级→行内） ===== */
async function previewPush(){const b=$('pvBtn');b.classList.add('busy');
 try{const r=await fetch('/api/preview',{method:'POST',
   headers:{'Content-Type':'application/json'},body:JSON.stringify({user:U})});
  const j=await r.json();
  if(!j.ok){toast(j.err||'预览失败','err');return;}
  $('pvTitle').textContent=j.title;
  $('pvBody').innerHTML=renderDesp(j.desp);
  _openPvMask();}
 catch(e){toast('预览请求失败','err');}
 b.classList.remove('busy');}
function closePv(){$('pvMask').classList.remove('on');
 /* 弹层开着背景曾可滚动/Tab 逃逸（无焦点管理）；锁滚+aria 轻量收口 */
 document.body.style.overflow='';
 /* 焦点归还开启者（v1.5.44）：Tab 曾继续在背景游走 */
 const ret=_PV_RETURN;_PV_RETURN=null;
 if(ret&&ret.focus)try{ret.focus();}catch(e){}}
let _PV_RETURN=null;
function _openPvMask(){_PV_RETURN=document.activeElement;
 $('pvMask').classList.add('on');
 $('pvMask').setAttribute('aria-modal','true');
 document.body.style.overflow='hidden';
 /* 焦点进弹层关闭钮（v1.5.44）：键盘/读屏用户不再滞留背景 */
 setTimeout(()=>{const x=$('pvClose');if(x)x.focus();},0);}
/* ===== 推送记录：钉钉发送存档回看（点条目展开全文；display 切换零插拔） ===== */
async function pushLog(){try{
 const r=await fetch('/api/pushlog');const j=await r.json();
 if(!j.ok){toast(j.err||'读取失败','err');return;}
 const items=j.items||[];
 $('pvTitle').textContent='📨 推送记录（最近 '+items.length+' 条）';
  $('pvBody').innerHTML=items.length?items.map(p=>
  `<div class="plitem${p.ok?'':' bad'}" onclick="const d=this.nextElementSibling;d.style.display=d.style.display==='none'?'':'none'">`+
  `<span>${p.ok?'✅':'⚠️'}</span><span style="flex:1">${he(p.title||'')}</span>`+
  `<span class="plts">${he(p.ts||'')}</span></div>`+
  `<div class="pldesp" style="display:none">${renderDesp(p.desp||'')}</div>`).join('')
  :'<div class="muted" style="padding:14px">还没有推送存档——v3.0 起每次发送自动记录在这里</div>';
 mkactAll();
 _openPvMask();}
 catch(e){toast('请求失败','err');}}
function mdInline(s){/* 先链接（[**粗体**](url) 链接可包粗体），再 **粗体**，@手机 高亮 */
 let t=he(String(s||''))
  .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>')
  .replace(/@(\d[\d*]+)/g,'<span class="md-at">@$1</span>');
 const parts=t.split('**');let out='';
 for(let i=0;i<parts.length;i++)out+=(i%2)?'<b>'+parts[i]+'</b>':parts[i];
 return out;}
function renderDesp(s){const NL=String.fromCharCode(10);
 const lines=String(s||'').split(NL);const blocks=[];let cur=[];
 for(const ln of lines){if(ln.trim()===''){if(cur.length){blocks.push(cur);cur=[];}}
  else cur.push(ln);}
 if(cur.length)blocks.push(cur);
 let h='';
 for(const bl of blocks){const first=bl[0];
  if(first.indexOf('![')===0){const m=first.match(/!\[([^\]]*)\]\((https?:[^)\s]+)\)/);
   h+=m?`<img src="${m[2]}" alt="${he(m[1])}" loading="lazy">`
       :`<div class="md-p muted">[图片]</div>`;}
  else if(first.indexOf('#### ')===0)h+=`<div class="md-h3">${mdInline(first.slice(5))}</div>`;
  else if(first.indexOf('### ')===0)h+=`<div class="md-h3">${mdInline(first.slice(4))}</div>`;
  else if(first.indexOf('## ')===0)h+=`<div class="md-h2">${mdInline(first.slice(3))}</div>`;
  else if(first.indexOf('# ')===0)h+=`<div class="md-h1">${mdInline(first.slice(2))}</div>`;
  else if(/^-{3,}$/.test(first.trim()))h+=`<hr class="md-hr">`;
  else if(first.indexOf('> ')===0)
   h+=`<div class="md-q">${bl.map(x=>mdInline(x.replace(/^>\s?/,''))).join('<br>')}</div>`;
  else if(/^[🟦🟩🟨⬜🟥]+$/.test(first.replace(/\s/g,'')))
   h+=`<div class="md-g">${he(first)}</div>`;
  /* 列表项（单路由达标 TOP3 等）：钉钉渲染为缩进列表，预览/回放
     曾退化成裸段落「1. 🔥…」（v1.5.38） */
  else if(/^- /.test(first)||/^\d+[.)] /.test(first))
   h+=`<div class="md-li">${bl.map(x=>mdInline(x)).join('<br>')}</div>`;
  else h+=`<div class="md-p">${bl.map(mdInline).join('<br>')}</div>`;}
 return h;}
/* ===== 移动端筛选抽屉 ===== */
function togFlt(){const f=document.querySelector('.fbar');if(f)f.classList.toggle('open');}
function updFltN(){const el=$('fltN');if(!el)return;
 let n=0;
 if(FLT.dep!=null)n++;
 if(FLT.arr!=null)n++;
 if(FLT.pmin||FLT.pmax)n++;
 if(FLT.q)n++;
 if(FLT.no)n++;
 try{const u=S.users[U];const ps=[...new Set(u.flights.map(f=>f.plat))];
  if(FLT.plats.size&&FLT.plats.size<ps.length)n++;
  const rs=[...new Set(u.flights.map(f=>f.route).filter(Boolean))];
  if(FLT.routes.size&&FLT.routes.size<rs.length)n++;}catch(e){}
 el.style.display=n?'':'none';el.textContent=n||'';}
$('tabs').onclick=e=>{if(e.target.dataset.f){
 document.querySelectorAll('#tabs span').forEach(s=>s.classList.remove('on'));
 e.target.classList.add('on');F=e.target.dataset.f;saveUI();table();}};
/* ===== 下轮倒计时：到点自动拉一次新数据 ===== */
function setNext(t){NEXTRUN=t?new Date(String(t).replace(/-/g,'/')):null;TICKED=false;tick();}
function tick(){const el=$('nextrun');if(!el)return;
 if(!NEXTRUN){el.style.display='none';return;}
 const d=(NEXTRUN-new Date())/1000;
 el.style.display='';
 if(d<=0){el.textContent='🔄 扫描中…';el.classList.add('run');
  if(!TICKED){TICKED=true;setTimeout(load,4000);}return;}
 el.classList.remove('run');
 const m=Math.floor(d/60),s2=Math.floor(d%60);
 el.textContent='⏱ 下轮 '+NEXTRUN.toTimeString().slice(0,5)
  +'（'+(m>0?m+' 分 '+s2+' 秒':s2+' 秒')+'后）';}
restoreUI();mkactAll();load();setInterval(load,10000);setInterval(tick,1000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)load();});
/* Esc 收起展开的同班比价行 / 关闭推送预览弹层 */
document.addEventListener('keydown',e=>{if(e.key!=='Escape')return;
 if($('pvMask').classList.contains('on')){closePv();return;}
 /* 移动筛选抽屉同收（此前 Esc 只管弹层与比价行，抽屉开着不跟手） */
 const fb=document.querySelector('.fbar.open');
 if(fb){fb.classList.remove('open');return;}
 if(EXP){EXP=null;_hideXrows();}});
/* 弹层 Tab 焦点圈封口（v1.5.46）：pvBody 内 renderDesp 生成真实 <a>，
   Tab 走到最后一个链接曾逃逸到背景页（背景仅锁滚未 inert）——
   pvcard 内 focusable 首尾回绕；previewPush/pushLog/showLog 三入口
   共用同一 mask，一处修全收益 */
document.addEventListener('keydown',e=>{
 if(e.key!=='Tab'||!$('pvMask').classList.contains('on'))return;
 const f=[...document.querySelectorAll('#pvMask a[href],#pvMask button,#pvMask [tabindex="0"]')]
  .filter(x=>x.offsetParent!==null);
 if(!f.length)return;
 const first=f[0],last=f[f.length-1];
 if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}
 else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}});
/* V50 快捷键：1/2 切视图 · R 立即扫描（两段确认，防手滑） · / 聚焦搜索
   输入类控件聚焦时不劫持按键 */
let RUNARM=0;
function keyRun(){const now=Date.now();
 if(now-RUNARM>3000){RUNARM=now;toast('⚠ 再按一次 R 确认立即扫描全部航线','');return;}
 RUNARM=0;
 fetch('/api/run',{method:'POST'}).then(r=>r.json()).then(j=>{
  toast(j.ok?'✅ 已触发，页面自动刷新':'❌ 失败: '+(j.err||''),j.ok?'ok':'err');load();})
  .catch(()=>toast('❌ 请求失败','err'));}
/* 分栏跳转收口（v1.5.44）：先切监控视图再选子栏——3/4/6 曾直调
   showMonTab，在配置视图按快捷键只翻转 #monview（display:none）内的
   子容器，页面毫无反应（快捷键 3-6 分栏的承诺未兑现） */
function gotoMonTab(t){if(VIEW!=='mon')switchView('mon');showMonTab(t);}
document.addEventListener('keydown',e=>{
 /* Ctrl/Cmd+S：配置页保存（原生拦截，非输入态也可用） */
 if((e.ctrlKey||e.metaKey)&&(e.key==='s'||e.key==='S')){
  if(VIEW!=='cfg')return;e.preventDefault();saveCfg();return;}
 if(e.ctrlKey||e.altKey||e.metaKey)return;
 const t=e.target,tag=((t&&t.tagName)||'').toLowerCase();
 if(tag==='input'||tag==='select'||tag==='textarea'||(t&&t.isContentEditable))return;
 if(e.key==='1')switchView('mon');
 else if(e.key==='2')switchView('cfg');
 else if(e.key==='3')gotoMonTab('overview');
 else if(e.key==='4')gotoMonTab('trend');
 else if(e.key==='5')gotoMonTab('details');
 else if(e.key==='6')gotoMonTab('health');
 else if(e.key==='/'){if(VIEW==='cfg'){const c=$('cfgSearch');
   if(c){c.focus();c.select();}e.preventDefault();return;}
  /* 明细子视图未激活时 #fq 在 display:none 容器里，focus 是 no-op
     （按 / 曾无任何反应）——先切到明细再聚焦 */
  gotoMonTab('details');
  /* ≤760px .fbar 是 display:none 抽屉：不先展开则聚焦仍是 no-op */
  setTimeout(()=>{const fb=document.querySelector('.fbar');
   if(fb&&getComputedStyle(fb).display==='none')fb.classList.add('open');
   const q=$('fq');if(q){q.focus();q.select();}},0);
  e.preventDefault();}
 else if(e.key==='r'||e.key==='R')keyRun();});
/* 配置未保存守卫：dirty 徽标 + 关闭/刷新页面前确认（防手滑丢配置；全局项同守） */
function cfgIsDirty(){return CFG&&(JSON.stringify(CFG)!==CFG_CLEAN
 ||JSON.stringify(GLB)!==GLB_CLEAN);}
 setInterval(()=>{
  const dirty=cfgIsDirty();   /* 监控页也算：navCfg 红点全局可见（v1.5.44，
                              切走仅一次性 toast 曾让脏态不可见） */
  const nb=$('navDirty');if(nb)nb.style.display=(dirty&&VIEW!=='cfg')?'':'none';
  if(VIEW!=='cfg')return;   /* 监控页跳过 savebar/用户卡 DOM 巡检 */
  const n=dirty?cfgDirtyCount():0;
  const el=$('cfgDirty');if(el){el.style.display=dirty?'':'none';
   el.textContent='● '+n+' 处未保存的修改';}
  const sb=$('savebar');
  if(sb){sb.style.display=(dirty&&VIEW==='cfg')?'flex':'none';
   const st=$('saveTxt');if(st)st.textContent=n+' 处未保存的修改';}
  /* 用户卡头各自的未保存标记（对比干净快照里的对应用户） */
  let cleanArr=null;
  try{cleanArr=JSON.parse(CFG_CLEAN||'[]');}catch(e){}
  if(!CFG)return;  /* loadCfg 异步窗口期：配置未到本轮跳过（竞态炸 forEach，uitest 实锤） */
  CFG.forEach((u,i)=>{const el=$('udirty-'+i);if(!el)return;
   const d=dirty&&(!cleanArr||!cleanArr[i]
    ||JSON.stringify(u)!==JSON.stringify(cleanArr[i]));
   el.style.display=d?'':'none';});
 },800);
function discardCfg(){loadCfg();toast('已放弃未保存的更改','ok')}
/* V50 配置面板化：左侧导航=视图切换器（同屏只显一个分区，告别长滚动）；
   display 切换零 DOM 插拔；搜索态临时展示全部分区（只含命中字段） */
let CFGPANEL='login';
function showCfgPanel(id,silent){CFGPANEL=id;
 document.querySelectorAll('#cfgnav .cnav').forEach(c=>
  c.classList.toggle('on',c.dataset.p===id));
 document.querySelectorAll('#cfgmain .cfpanel').forEach(p=>
  p.style.display=(p.id==='panel-'+id)?'':'none');
 if(!silent){const t=$('panel-'+id);
  if(t){t.classList.remove('viewin');void t.offsetWidth;t.classList.add('viewin');}}
 try{localStorage.setItem('jpcfgpanel',id);}catch(e){}}
document.querySelectorAll('#cfgnav .cnav').forEach(c=>{
 c.onclick=()=>showCfgPanel(c.dataset.p);});
try{const _cp=localStorage.getItem('jpcfgpanel');
 if(_cp&&_cp!=='login')showCfgPanel(_cp,true);}catch(e){}
window.addEventListener('beforeunload',e=>{
 if(cfgIsDirty()){e.preventDefault();e.returnValue='';}});
let _rsT=null;window.addEventListener('resize',()=>{
 clearTimeout(_rsT);_rsT=setTimeout(()=>{if(S&&S.users&&S.users.length)chart();},200);});
/* ===== 主题三态：auto/light/dark（localStorage 持久，auto 跟随系统） ===== */
const THEMES=[['auto','🌗'],['light','☀️'],['dark','🌙']];
function applyTheme(){let t='auto';try{t=localStorage.getItem('jptheme')||'auto'}catch(e){}
 /* 裸读 localStorage 曾是 NT 守卫最后一漏网：存储禁用此处抛异常中断
    脚本，其后 let CFG/FOLD 进 TDZ——配置页/密度/折叠/保存全挂 */
 let dark=(t==='dark');
 if(t==='auto'){dark=window.matchMedia&&window.matchMedia('(prefers-color-scheme:dark)').matches;}
 document.documentElement.dataset.theme=dark?'dark':'light';
 /* 移动端浏览器工具栏随主题（meta theme-color 静态亮蓝曾暗色下发白） */
 const m=document.querySelector('meta[name="theme-color"]');
 if(m)m.content=dark?'#141d2a':'#0b62d6';
 const i=THEMES.findIndex(x=>x[0]===t);
 const b=$('themeBtn');if(b)b.textContent=THEMES[i][1];
 try{if(S&&S.users&&S.users.length){chart();renderCal();}}catch(e){}}
function cycleTheme(){let cur='auto';try{cur=localStorage.getItem('jptheme')||'auto'}catch(e){}
 const i=THEMES.findIndex(x=>x[0]===cur);
 try{localStorage.setItem('jptheme',THEMES[(i+1)%3][0])}catch(e){}applyTheme();}
if(window.matchMedia)window.matchMedia('(prefers-color-scheme:dark)').addEventListener('change',applyTheme);
applyTheme();
/* ===== 密度两挡：cozy（默认）/compact（localStorage jpdensity 持久） ===== */
function applyDensity(){let d='cozy';
 try{d=localStorage.getItem('jpdensity')||'cozy';}catch(e){}
 if(d!=='compact')d='cozy';
 document.documentElement.dataset.density=d;
 const b=$('denBtn');if(b)b.title=d==='compact'?'密度：紧凑（点击切回舒适）':'密度：舒适（点击切换紧凑）';}
function cycleDensity(){const nx=document.documentElement.dataset.density==='compact'?'cozy':'compact';
 try{localStorage.setItem('jpdensity',nx);}catch(e){}
 applyDensity();
 toast(nx==='compact'?'密度已切换：紧凑':'密度已切换：舒适','ok');}
applyDensity();

/* ===== 配置视图 ===== */
let CFG=null,CITY={},VIEW='mon',CFG_CLEAN='',CFGQ='';
function switchView(v){const _from=VIEW;VIEW=v;
 /* 离开配置页带脏改动时轻提醒（不拦截）：savebar 只在配置页显示，
    切走后未保存提示曾直接消失、回来一脸懵（beforeunload 只管关页） */
 if(_from==='cfg'&&v==='mon'&&cfgIsDirty())
  toast('配置有未保存修改，回配置页可继续编辑','');
 $('navMon').className=v==='mon'?'on':'';$('navCfg').className=v==='cfg'?'on':'';
 const el=$(v==='mon'?'monview':'cfgview');
 el.classList.remove('viewin');void el.offsetWidth;el.classList.add('viewin');
 $('monview').style.display=v==='mon'?'':'none';
 $('cfgview').style.display=v==='cfg'?'':'none';
 if(v==='cfg'&&!CFG)loadCfg();
 if(v==='cfg')loadLogin();
 if(_from!==v)window.scrollTo({top:0});}/* 大视图互切回顶；子栏切换不重置 */
/* ===== 渠道登录：弹窗登录 + 会话保存（免命令行） ===== */
const LOGIN_CN = {qunar:'去哪儿', ctrip:'携程', tongcheng:'同程',
 tuniu:'途牛', fliggy:'飞猪'};
const LOGIN_NEED = {qunar:'必须', ctrip:'必须', tongcheng:'建议',
 tuniu:'建议', fliggy:'无需'};
async function loadLogin(){const box=$('loginRows');if(!box)return;
 try{const r=await fetch('/api/login-state');const j=await r.json();
  if(!j.ok){box.innerHTML='<span class="muted">读取失败</span>';return;}
  box.innerHTML='<div class="lggrid">'+Object.keys(j.plats).map(p=>{
   const s=j.plats[p];
   const btn=s.active
    ?`<button class="btn2" style="border-color:var(--green);color:var(--green)" onclick="loginFinish('${p}')">✅ 我已登录完成</button>`
    :`<button class="btn2" onclick="loginStart('${p}',this)">🔐 弹窗登录</button>`;
   return `<div class="lgcard${s.saved?' saved':''}${s.active?' active':''}">`
    +`<div class="lgname"><span class="lgdot${s.saved?' on':''}"></span>${LOGIN_CN[p]||p}</div>`
    +`<div class="lgsub">${LOGIN_NEED[p]||''}登录 · ${s.saved?'已有登录态':(s.active?'登录中…':'未登录')}</div>${btn}</div>`;
  }).join('')+'</div>';
 }catch(e){box.innerHTML='<span class="muted">读取失败</span>';}}
async function loginStart(p,b){
 b.classList.add('busy');
 try{const r=await fetch('/api/login',{method:'POST',
  headers:{'Content-Type':'application/json'},
  body:JSON.stringify({platform:p})});
  const j=await r.json();
  if(j.ok)toast('🔐 '+p+' 登录窗口已弹出——请在窗口完成登录，回这里点「我已登录完成」','ok');
  else toast(j.err||'启动失败','err');
 }catch(e){toast('请求失败','err');}
 b.classList.remove('busy');setTimeout(loadLogin,400);}
async function loginFinish(p){
 try{const r=await fetch('/api/login-finish',{method:'POST',
  headers:{'Content-Type':'application/json'},
  body:JSON.stringify({platform:p})});
  const j=await r.json();
  toast(j.ok?'✅ 会话已保存，下轮采集自动生效（无需重启）'
   :'⚠ '+(j.err||'操作失败'),j.ok?'ok':'err');
 }catch(e){toast('请求失败','err');}
 loadLogin();}
let GLB={interval_minutes:30},GLB_CLEAN='';
async function loadCfg(){try{
 const r=await fetch('/api/config');const j=await r.json();
 CFG=j.users||[];CITY=j.city||{};GLB=j.globals||{interval_minutes:30};
 CFG_CLEAN=JSON.stringify(CFG);GLB_CLEAN=JSON.stringify(GLB);
 $('citydl').innerHTML=Object.keys(CITY).map(c=>`<option value="${c}">`).join('');
 buildForm();}catch(e){$('cfgmsg').textContent='配置读取失败: '+e;}}
function esc(s){return String(s==null?'':s).replace(/"/g,'&quot;')}
let OPEN_USER=0;
function buildForm(){if(!CFG)return;let h='',gh='';
 const glab=(no,zh,en,sum)=>'<div class="grouplab" data-sec="'+no+'" role="button" onclick="foldSec(this)" title="点击收起/展开该分区">'
  +'<span class="no">'+no+'</span>'
  +'<span class="zh">'+zh+'</span><span class="en">'+en+'</span>'
  +'<span class="gsum">'+(sum||'')+'</span><span class="chev open">▾</span></div>';
 const PLATS={qunar:'去哪儿',fliggy:'飞猪',tongcheng:'同程',tuniu:'途牛',ctrip:'携程'};
 const glcell=(lab,id,onch,val,sub,type,unit)=>'<div class="glcell"><div class="glab">'+lab+'</div>'
  +(type==='check'
    ?'<label style="display:block;margin-top:10px;font-size:13px;user-select:none;cursor:pointer">'
     +'<input type="checkbox" class="switch" id="'+id+'"'+(val?' checked':'')+' onchange="'+onch+'">'
     +'<span class="gsub" style="display:block" id="'+id+'Txt">'+sub+'</span></label>'
    :'<div style="position:relative">'
     +'<input'+((type==='text'||type==='ro')?'':' type="number"')+' id="'+id+'" value="'+val+'"'
     +(type==='ro'?' readonly style="color:var(--mut);font-size:14px"':'')
     +(type==='text'?' style="font-size:13px;font-weight:500"':'')
     +(unit?' style="width:100%;padding-right:40px"':'')
     +' onchange="'+onch+'">'
     +(unit?'<span style="position:absolute;right:10px;top:50%;transform:translateY(-50%);'
       +'color:var(--mut);font-size:11px;pointer-events:none">'+unit+'</span>':'')
     +'</div><div class="gsub">'+sub+'</div>')
  +'</div>';
 const glsec=t=>'<div style="font-size:10.5px;letter-spacing:1.2px;color:var(--mut);'
  +'margin:14px 0 8px;text-transform:uppercase">'+t+'</div>';
 gh+=glsec('⏱ 调度 · 🔥 保存即热生效')
  +'<div class="glgrid">'
  +glcell('扫描周期','glbIv','GLB.interval_minutes=Math.max(5,parseInt(this.value)||30)',esc(GLB.interval_minutes),'5–720 · 改动即重排下一轮',null,'分钟')
  +glcell('随机扰动','glbJt','GLB.jitter_minutes=Math.max(0,parseInt(this.value)||0)',esc(GLB.jitter_minutes||0),'错峰防规律抓取',null,'分钟')
  +glcell('控制台端口','glbPort','GLB.port=Math.max(1024,parseInt(this.value)||8765)',esc(GLB.port||8765),'1024–65535 · 原地热切换')
  +glcell('监听地址','glbHost','GLB.host=this.value',esc(GLB.host||'127.0.0.1'),'127.0.0.1=仅本机；0.0.0.0=局域网可达（手机开推送详情）· 重启生效','text')
  +glcell('详情基址 base_url','glbBu','GLB.base_url=this.value',esc(GLB.base_url||''),'钉钉「完整详情」的可达性取决于它；手机要看请配局域网地址（监听地址须非 127.0.0.1）','text')
  +glcell('启动即扫','glbRos','GLB.run_on_start=this.checked',GLB.run_on_start!==false,'进程启动时立即扫一轮（下次启动生效）','check')
  +'</div>'
  +glsec('🌐 采集 · 🔥 保存即热生效（下轮扫描即用新值）')
  +'<div class="glgrid">'
  +glcell('无头浏览器','glbHl','glbHlChk(this)',GLB.headless!==false,GLB.headless!==false?'后台静默采集':'弹窗可见调试','check')
  +glcell('采集超时','glbTo','GLB.timeout_seconds=Math.min(600,Math.max(10,parseInt(this.value)||45))',esc(GLB.timeout_seconds||45),'10–600 · 单渠道上限',null,'秒')
  +glcell('错峰延迟 自','glbDn','GLB.delay_min=Math.max(0,parseInt(this.value)||0)',esc(GLB.delay_min==null?5:GLB.delay_min),'页面动作间随机延迟',null,'秒')
  +glcell('错峰延迟 至','glbDx','GLB.delay_max=Math.max(0,parseInt(this.value)||0)',esc(GLB.delay_max==null?15:GLB.delay_max),'与「自」组成随机区间',null,'秒')
  +glcell('调试日志','glbDbg','GLB.debug=this.checked',!!GLB.debug,'接口现场存 debug/','check')
  +'</div>'
  +glsec('🅰 通用 · 🔥 保存即热生效')
  +'<div class="glgrid">'
  +glcell('浏览器 User-Agent（空=内置默认）','glbUa','GLB.user_agent=this.value',esc(GLB.user_agent||''),'全渠道共用的桌面 UA；风控策略变化时无需改码即可更换','text')
  +'</div>'
  +glsec('♻ 启动级配置 · 编辑 config.yaml 后重启进程生效')
  +'<div class="glgrid">'
  +glcell('数据库','glbDbp','',esc(GLB.db_path||'data/prices.db'),'SQLite 路径 · ♻ 只读','ro')
  +glcell('运行日志','glbLgp','',esc(GLB.log_path||'logs/monitor.log'),'日志文件 · ♻ 只读','ro')
  +glcell('浏览器资料目录','glbUdd','',esc(GLB.user_data_dir||'user_data'),'登录态存放 · ♻ 只读','ro')
  +'</div>';
 h+='<div class="rline" style="display:flex;align-items:center;gap:8px">'
  +'<b style="flex:1">👥 用户与航线配置（'+CFG.length+' 个用户）</b>'
  +'<button class="btn2" onclick="addUser()">➕ 添加用户</button>'
  +'<button class="btn2" style="border-color:var(--warn);color:var(--warn)" onclick="saveCfg()">💾 保存全部并生效</button>'
  +'</div>';
  if(!CFG.length){/* 空态引导：教新用户第一步怎么走 */
   h+='<div class="ucard" style="text-align:center;padding:46px 20px">'
    +'<div style="font-size:34px;margin-bottom:10px">🧭</div>'
    +'<b style="font-size:15px">还没有监控用户</b>'
    +'<div class="hint" style="margin:8px auto 16px;max-width:430px">每个用户是一套独立的航线与通知配置（给家人朋友各配一套互不打扰）。创建后填航线和心理价，保存即开始监控。</div>'
    +'<button class="btn2" onclick="addUser()">➕ 创建第一个用户</button></div>';
  }
  CFG.forEach((u,i)=>{
  const dt=u.notifier&&u.notifier.dingtalk||{};
  const nR=(u.routes||[]).length;
  const open=(OPEN_USER===i);
  h+='<div class="ucard" style="margin:10px 0;padding:0;overflow:hidden">'
   +'<div class="uhead2" role="button" data-u="'+i+'" onclick="toggleUser(this)">'
   +'<span class="uava">'+esc((u.name||'?').slice(0,1))+'</span>'
   +'<b>'+esc(u.name)+'</b>'
   +'<span class="upill">'+nR+' 航线</span>'
   +'<span class="upill'+((u.notifier||{}).win_toast!==false?' ok':'')+'">🔔弹窗'+((u.notifier||{}).win_toast!==false?'开':'关')+'</span>'
   +'<span class="upill'+(dt.enabled?' ok':'')+'">'+(dt.enabled?'推送已启用':'推送未启用')+'</span>'
   +'<span class="upill warn udirty" id="udirty-'+i+'">● 未保存</span>'
   +'<span class="chev'+(open?' open':'')+'">▾</span></div>'
   +(open?'<div style="padding:4px 16px 14px">':'<div style="display:none">');
  const _dtOn=dt.enabled?'已启用':'未启用';
  h+=glab('A','基础','BASICS','推送与提醒偏好 · 钉钉'+_dtOn+' · 弹窗'+((u.notifier||{}).win_toast!==false?'开':'关'));/* A 分区在卡内：折叠只收字段卡，卡头保留 */
  h+=`<div class="rline" style="background:var(--card)">
   <div class="srow"><div class="slab"><b>用户名</b><div class="shint">推送、达标与推送历史都以此名义区分</div></div><div class="sctl"><input value="${esc(u.name)}" style="width:170px" onchange="CFG[${i}].name=this.value"></div></div>
   <div class="subsec">📈 推送行为</div>
   <div class="srow"><div class="slab"><b>聚合推送</b><div class="shint">多航线合并推送：一轮合并为一条，关闭则逐条推</div></div><div class="sctl"><input type="checkbox" class="switch" ${!!(u.notifier||{}).digest?'checked':''} onchange="setN(${i},'digest',this.checked)"></div></div>
   <div class="srow"><div class="slab"><b>日报时刻</b><div class="shint">每天该点自动推一份走势日报（留空关闭）</div></div><div class="sctl"><input type="number" min="0" max="23" placeholder="如 9" style="width:90px" value="${esc((u.notifier||{}).report_hour||'')}" onchange="setN(${i},'report_hour',this.value)"></div></div>
   <div class="srow"><div class="slab"><b>风暴连推</b><div class="shint">新达标时连推多条，防被群聊淹没（1=关）</div></div><div class="sctl"><input type="number" min="1" max="5" style="width:90px" value="${esc((u.notifier||{}).storm_repeat||3)}" onchange="setN(${i},'storm_repeat',this.value)"></div></div>
   <div class="subsec">↕ 再推去抖 · 防刷屏</div>
   <div class="srow"><div class="slab"><b>降价再推阈值</b><div class="shint">较上次推送降幅 ≥ 此价才再次推送</div></div><div class="sctl"><span class="sunit">￥</span><input type="number" min="0" step="10" style="width:100px" value="${esc((u.notifier||{}).push_drop_min==null?30:(u.notifier||{}).push_drop_min)}" onchange="setN(${i},'push_drop_min',this.value)"></div></div>
   <div class="srow"><div class="slab"><b>涨价再推阈值</b><div class="shint">较上次推送涨幅 ≥ 此价才提醒</div></div><div class="sctl"><span class="sunit">￥</span><input type="number" min="0" step="10" style="width:100px" value="${esc((u.notifier||{}).push_rise_min==null?50:(u.notifier||{}).push_rise_min)}" onchange="setN(${i},'push_rise_min',this.value)"></div></div>
   <div class="subsec">🌙 免打扰时段</div>
   <div class="srow"><div class="slab"><b>免打扰 · 开始 → 结束</b><div class="shint">跨零点可用；时段内电话/风暴静默，达标主推照发；两端留空不启用</div></div><div class="sctl"><input type="time" value="${esc((u.notifier||{}).quiet_start||'')}" onchange="setN(${i},'quiet_start',this.value)"><span class="sunit">→</span><input type="time" value="${esc((u.notifier||{}).quiet_end||'')}" onchange="setN(${i},'quiet_end',this.value)"></div></div>
   <div class="srow"><div class="slab"><b>🔔 Windows 右下角弹窗</b><div class="shint">达标时系统弹窗+提示音，点击直达单条详情 · 默认开启 · 心跳不弹</div></div><div class="sctl"><input type="checkbox" class="switch" ${(u.notifier||{}).win_toast!==false?'checked':''} onchange="setN(${i},'win_toast',this.checked)"><button class="btn2" onclick="testToast(this)">🔔 发测试弹窗</button></div></div>
   </div>
   `+glab('B','监控平台','PLATFORMS',(u.platforms||[]).length+' / 5 渠道')+`
   <div class="srow"><div class="slab"><b>监控平台</b><div class="shint">点击切换采集渠道；携程需本机已建立登录态，其余开箱即用</div></div><div class="sctl" style="flex-wrap:wrap;justify-content:flex-end;max-width:60%">`+
   Object.keys(PLATS).map(p=>`<span class="chip${(u.platforms||[]).includes(p)?' on':''}" title="携程需本机已建立登录态" onclick="togPlat(${i},'${p}',this)">${PLATS[p]}</span>`).join('')+
   `</div></div>`;
  const _en=(u.routes||[]).filter(r=>r.enabled!==false).length,
        _dis=(u.routes||[]).length-_en;
  h+=glab('C','航线','ROUTES','<span id="csum-'+i+'">'+_en+' 条监控中'+(_dis?' · '+_dis+' 条已停用':'')+'</span>');
  (u.routes||[]).forEach((r,j)=>{
   h+=`<div class="rline${r.enabled===false?' off':''}" data-rk="${i}:${j}">
    <div class="rhead" role="button" onclick="foldRoute(this)"><span class="rtcode">${esc(r.from||'')}→${esc(r.to||'')}</span>
     <b>${esc(r.from_name)} → ${esc(r.to_name)}</b>
     <span class="rbadge">${r.enabled===false?'已停用':''}</span>
     <span class="muted">${esc((r.dates||[]).join('、'))}`
    +`${r.alert_direct>0?' · 直飞≤￥'+esc(r.alert_direct):''}`
    +`${r.alert_transfer>0?' · 中转≤￥'+esc(r.alert_transfer):''}`
    +`${(r.dep_time_min||r.dep_time_max)?' · '+(r.dep_time_min||'00:00')+'–'+(r.dep_time_max||'24:00')+' 出发':''}`
    +`</span><span class="chev open" style="margin-left:auto">▾</span>`
    +`<span class="rop" onclick="event.stopPropagation()">`
    +`<input type="checkbox" class="switch" title="启用/停用该航线：停用保留全部配置，调度跳过，随时可恢复" ${r.enabled===false?'':'checked'} onchange="setRouteEnabled(${i},${j},this.checked)">`
    +`<button class="ropbtn" title="复制该航线全部配置为新航线（改出发到达即可用）" onclick="copyRoute(${i},${j},this)">⧉ 复制</button>`
    +`<button class="danger" onclick="delRoute(${i},${j})">✕ 删除</button></span></div>
    <div class="srow"><div class="slab"><b>出发 → 到达城市</b><div class="shint">直接输中文城市名，支持 50 城联想</div></div><div class="sctl"><input list="citydl" style="width:108px" value="${esc(r.from_name)}" onchange="setRoute(${i},${j},'from_name',this.value)"><span class="sunit">→</span><input list="citydl" style="width:108px" value="${esc(r.to_name)}" onchange="setRoute(${i},${j},'to_name',this.value)"></div></div>
    <div class="srow"><div class="slab"><b>心理价 · 直飞 / 中转</b><div class="shint">低于此价即触发 🚨 强提醒（0=关）；中转还须满足到达约束</div></div><div class="sctl"><span class="sunit">￥</span><input type="number" min="0" step="10" style="width:88px" value="${esc(r.alert_direct||0)}" onchange="setRoute(${i},${j},'alert_direct',this.value)"><span class="sunit">/</span><span class="sunit">￥</span><input type="number" min="0" step="10" style="width:88px" value="${esc(r.alert_transfer||0)}" onchange="setRoute(${i},${j},'alert_transfer',this.value)"></div></div>
    <div class="srow"><div class="slab"><b>中转最晚到达</b><div class="shint">次日该时刻前到达的中转才算达标</div></div><div class="sctl"><input type="time" value="${esc(r.transfer_arrival_max||'02:00')}" onchange="setRoute(${i},${j},'transfer_arrival_max',this.value)"></div></div>
    <div class="srow"><div class="slab"><b>中转最短衔接</b><div class="shint">衔接不足该分钟数的中转不达标；需托运建议 ≥90（0=不限）</div></div><div class="sctl"><input type="number" min="0" step="10" style="width:88px" value="${esc(r.transfer_layover_min||0)}" onchange="setRoute(${i},${j},'transfer_layover_min',this.value)"><span class="sunit">分钟</span></div></div>
    <div class="srow"><div class="slab"><b>🧳 中转行李直挂</b><div class="shint">仅认渠道标注「中转行李免提」（两段含免费托运）的班次，未标注的视为不满足 · ⚠ 渠道直挂标注极少，开启后中转最优可能长期为空</div></div><div class="sctl"><input type="checkbox" class="switch" ${r.transfer_baggage==='direct'?'checked':''} onchange="setRoute(${i},${j},'transfer_baggage',this.checked?'direct':'')"></div></div>
    <div class="srow"><div class="slab"><b>出发时段窗口</b><div class="shint">快捷挡一点即填；也可手输精确时间（两端留空 = 不限）</div></div><div class="sctl" style="flex-wrap:wrap;justify-content:flex-end;gap:5px;max-width:62%">`
    +DEPWINS.map(([n,lo,hi])=>{
      const on=((r.dep_time_min||'')===(lo||''))&&((r.dep_time_max||'')===(hi||''));
      return `<span class="chip schip${on?' on':''}" title="${lo?lo+'–'+hi:'不限'}" onclick="quickDep(${i},${j},this,'${lo}','${hi}')">${n}</span>`;}).join('')
    +`<input type="time" value="${esc(r.dep_time_min||'')}" onchange="setRoute(${i},${j},'dep_time_min',this.value);customDepWin(this)"><span class="sunit">→</span><input type="time" value="${esc(r.dep_time_max||'')}" onchange="setRoute(${i},${j},'dep_time_max',this.value);customDepWin(this)"></div></div>
    <div class="srow"><div class="slab"><b>出发日期</b><div class="shint">可加多个，各日期独立监控与推送；点日期片 ✕ 删除；支持只输「10-08」自动补年</div></div><div class="sctl" style="flex-wrap:wrap;justify-content:flex-end;gap:6px;max-width:62%"><span class="dchips" id="dchips-${i}-${j}">`
    +(r.dates||[]).map(d=>`<span class="chip on dchip">${esc(d)}<i class="dx" title="删除该日期" onclick="delDate(${i},${j},'${esc(d)}')">✕</i></span>`).join('')
    +`</span><input type="text" id="dpick-${i}-${j}" placeholder="如 2026-10-08" style="width:128px" onkeydown="if(event.key==='Enter')addDate(${i},${j})"><button class="btn2 ical" title="日历选择" onclick="pickDate(${i},${j})">📅</button><input type="date" id="dreal-${i}-${j}" class="dreal" tabindex="-1"><button class="btn2" style="margin-right:0" onclick="addDate(${i},${j})">➕ 加日期</button></div></div>
   </div>`;});
   h+=`<button class="btn2" onclick="addRoute(${i})">➕ 添加航线</button>
   `+glab('D','通知渠道','CHANNELS',[
      dt.enabled?'钉钉✓':'钉钉×',
      ((u.notifier||{}).ntfy||{}).enabled?'ntfy✓':null,
      ((u.notifier||{}).aliyun||{}).enabled?'电话✓':null,
      ((u.notifier||{}).serverchan||{}).enabled?'微信✓':null
     ].filter(Boolean).join(' · ')||'未配置任何渠道')+`
   <div class="chgrid">
   <div class="chcard${dt.enabled?' on':''}" data-ch="dingtalk"><div class="chhead" role="button" onclick="foldCh(this)"><span class="lgdot${dt.enabled?' on':''}"></span>钉钉机器人<span class="muted">${dt.enabled?'已启用':'未启用'}</span><span class="chev open" style="margin-left:auto">▾</span></div>
    <div class="srow"><div class="slab"><b>启用钉钉推送</b><div class="shint">关闭后该用户不再向此群推送</div></div><div class="sctl"><input type="checkbox" class="switch" ${dt.enabled?'checked':''} onchange="setDt(${i},'enabled',this.checked);chSync(this,${i},'dingtalk')"></div></div>
    <div class="srow"><div class="slab"><b>Webhook</b><div class="shint">群设置 → 智能群助手 → 自定义机器人获取</div></div><div class="sctl" style="flex:1;min-width:0"><input type="url" placeholder="https://oapi.dingtalk.com/robot/send?access_token=..." style="width:100%;text-align:left" value="${esc(dt.webhook||'')}" onchange="setDt(${i},'webhook',this.value)"></div></div>
    <div class="srow"><div class="slab"><b>加签密钥 SEC…</b><div class="shint">机器人安全设置选「加签」后获得</div></div><div class="sctl" style="flex:1;min-width:0"><input autocomplete="off" placeholder="SEC 开头的加签密钥" style="width:100%;text-align:left" value="${esc(dt.secret||'')}" onchange="setDt(${i},'secret',this.value)"></div></div>
    <div class="srow"><div class="slab"><b>达标 @ 手机号</b><div class="shint">达标推送时 @ 这个号码</div></div><div class="sctl"><input type="tel" placeholder="13800000000" style="width:140px" value="${esc(dt.at_mobile||'')}" onchange="setDt(${i},'at_mobile',this.value)"></div></div>
    <div class="srow"><div class="slab"><b>通路验证</b><div class="shint">发一条测试消息到群里，验证 Webhook 可用；凭据仅存本机 config.yaml</div></div><div class="sctl"><button class="btn2" onclick="testPush(${i})">🔔 测试推送（用表单当前值）</button></div></div>
   <div class="chcard${((u.notifier||{}).ntfy||{}).enabled?' on':''}" data-ch="ntfy"><div class="chhead" role="button" onclick="foldCh(this)"><span class="lgdot${((u.notifier||{}).ntfy||{}).enabled?' on':''}"></span>ntfy 手机弹窗<span class="muted">${((u.notifier||{}).ntfy||{}).enabled?'已启用':'未启用'}</span><span class="chev open" style="margin-left:auto">▾</span></div>
    <div class="srow"><div class="slab"><b>主题</b><div class="shint">手机 ntfy App 订阅同名主题；留空关闭</div></div><div class="sctl" style="flex:1;min-width:0"><input placeholder="my-flight-alert" style="width:100%;text-align:left" value="${esc(((u.notifier||{}).ntfy||{}).topic||'')}" onchange="setNtfy(${i},'topic',this.value);chSync(this,${i},'ntfy')"></div></div>
    <div class="srow"><div class="slab"><b>优先级</b><div class="shint">5 = 最强（系统级弹窗+铃声+穿透免打扰，仅达标触发）</div></div><div class="sctl"><input type="number" min="1" max="5" style="width:70px" value="${esc(((u.notifier||{}).ntfy||{}).priority||5)}" onchange="setNtfy(${i},'priority',this.value)"></div></div>
    <div class="srow"><div class="slab"><b>通路验证</b><div class="shint">发一条测试到手机 ntfy，验证链路可用</div></div><div class="sctl"><button class="btn2" onclick="testNtfy(${i},this)">🔔 测试 ntfy（用表单当前值）</button></div></div>
    <div class="hint"><a href="https://ntfy.sh" target="_blank" rel="noopener" style="color:var(--blue)">ntfy.sh</a> 免费无需注册，手机装 App 订阅同名主题即收。</div></div>
   <div class="chcard${((u.notifier||{}).aliyun||{}).enabled?' on':''}" data-ch="aliyun"><div class="chhead" role="button" onclick="foldCh(this)"><span class="lgdot${((u.notifier||{}).aliyun||{}).enabled?' on':''}"></span>阿里云电话/短信<span class="muted">${((u.notifier||{}).aliyun||{}).enabled?'已启用':'未启用'}</span><span class="chev open" style="margin-left:auto">▾</span></div>
    <div class="srow"><div class="slab"><b>云监控事件回调 URL</b><div class="shint">留空关闭；云监控 CRITICAL 事件触发电话/短信</div></div><div class="sctl" style="flex:1;min-width:0"><input style="width:100%;text-align:left" value="${esc(((u.notifier||{}).aliyun||{}).url||'')}" onchange="setAy(${i},'url',this.value);chSync(this,${i},'aliyun')"></div></div>
    <div class="srow"><div class="slab"><b>AccessKey ID / Secret</b><div class="shint">建议只授云监控只读权限，仅存本机 config.yaml</div></div><div class="sctl"><input autocomplete="off" placeholder="ID" style="width:110px" value="${esc(((u.notifier||{}).aliyun||{}).user||'')}" onchange="setAy(${i},'user',this.value)"><input autocomplete="off" type="password" placeholder="Secret" style="width:110px" value="${esc(((u.notifier||{}).aliyun||{}).password||'')}" onchange="setAy(${i},'password',this.value)"></div></div>
    <div class="hint">达标时拨打一次，风暴不重复。</div></div>
   <div class="chcard${((u.notifier||{}).serverchan||{}).enabled?' on':''}" data-ch="serverchan"><div class="chhead" role="button" onclick="foldCh(this)"><span class="lgdot${((u.notifier||{}).serverchan||{}).enabled?' on':''}"></span>Server酱·微信<span class="muted">${((u.notifier||{}).serverchan||{}).enabled?'已启用':'未启用'}</span><span class="chev open" style="margin-left:auto">▾</span></div>
    <div class="srow"><div class="slab"><b>SendKey</b><div class="shint">微信扫码获取；留空关闭</div></div><div class="sctl" style="flex:1;min-width:0"><input type="password" autocomplete="off" placeholder="sct.ftqq.com 微信扫码获取" style="width:100%;text-align:left" value="${esc(((u.notifier||{}).serverchan||{}).send_key||'')}" onchange="setSc(${i},'send_key',this.value);chSync(this,${i},'serverchan')"></div></div>
    <div class="srow"><div class="slab"><b>通道</b><div class="shint">留空 = 默认通道</div></div><div class="sctl"><input style="width:140px" value="${esc(((u.notifier||{}).serverchan||{}).channel||'')}" onchange="setSc(${i},'channel',this.value)"></div></div>
    <div class="hint">钉钉之外的微信触达备份：Server酱·Turbo 免费每日 5 条，
    <a href="https://sct.ftqq.com" target="_blank" rel="noopener" style="color:var(--blue)">sct.ftqq.com</a> 扫码即得 SendKey。凭据仅存本机。</div></div>
   </div>
   <button class="danger" onclick="delUser(${i})">✕ 删除用户 ${esc(u.name)}</button></div></div>`;});
 $('cfgform').innerHTML=h;
 $('cfgglobals').innerHTML=gh;
 applyFolds();mkactAll();   /* 折叠头（role=button）/日期片 ✕ 补键盘可达 */
 if(CFGQ)cfgFilter(CFGQ);}
/* ===== V100 子卡折叠：分区(A-D)/航线卡/通道卡 点击标题行收展。
   display 切换零 DOM 插拔（翻译/比价扩展免疫）；状态 localStorage 记忆。
   默认态：分区展开、航线卡与通道卡收起（标题行已含关键摘要） ===== */
let FOLD={sec:{},route:{},ch:{}};
try{const _f=JSON.parse(localStorage.getItem('jpcfgfold'));if(_f)FOLD=_f;}catch(e){}
FOLD.sec=FOLD.sec||{};FOLD.route=FOLD.route||{};FOLD.ch=FOLD.ch||{};
function saveFold(){try{localStorage.setItem('jpcfgfold',JSON.stringify(FOLD))}catch(e){}}
function _foldSibs(h){const body=[];let n=h.nextElementSibling;
 while(n&&!n.classList.contains('grouplab')&&!n.classList.contains('danger')){
  body.push(n);n=n.nextElementSibling;}
 return body;}
function _setFold(h,body,hide){body.forEach(b=>b.style.display=hide?'none':'');
 const c=h.querySelector('.chev');if(c)c.classList.toggle('open',!hide);}
function _isFolded(h){return _foldSibs(h).every(b=>b.style.display==='none');}
function foldSec(g){const body=_foldSibs(g);
 const hide=!_isFolded(g);
 _setFold(g,body,hide);
 FOLD.sec[g.dataset.sec]=hide;saveFold();}
function foldRoute(rh){if(event.target.closest('.danger,.rop'))return;
 const hide=!_isFolded(rh);
 _setFold(rh,_foldSibs(rh),hide);
 FOLD.route[rh.parentElement.dataset.rk]=hide;saveFold();}
function foldCh(ch){const hide=!_isFolded(ch);
 _setFold(ch,_foldSibs(ch),hide);
 FOLD.ch[ch.parentElement.dataset.ch]=hide;saveFold();
 ch.parentElement.classList.toggle('expanded',!hide);}
function applyFolds(){
 document.querySelectorAll('#cfgform .grouplab[data-sec]').forEach(g=>
  _setFold(g,_foldSibs(g),!!FOLD.sec[g.dataset.sec]));
 document.querySelectorAll('#cfgform .rline[data-rk]').forEach(rl=>
  _setFold(rl.querySelector('.rhead'),_foldSibs(rl.querySelector('.rhead')),
   FOLD.route[rl.dataset.rk]!==false));
 document.querySelectorAll('#cfgform .chcard[data-ch]').forEach(c=>{
  const ch=c.querySelector('.chhead');
  const fold=FOLD.ch[c.dataset.ch]!==false;
  _setFold(ch,_foldSibs(ch),fold);
  c.classList.toggle('expanded',!fold);});}
function expandFolds(){/* 搜索态临时全开，清空后 applyFolds 还原 */
 document.querySelectorAll('#cfgform .grouplab[data-sec],'
  +'#cfgform .rline .rhead,#cfgform .chcard .chhead').forEach(
  h=>_setFold(h,_foldSibs(h),false));}
function toggleUser(h){/* 用户卡收展：纯 display 翻转，不重建表单（不跳滚动位） */
 const u=+h.dataset.u,body=h.nextElementSibling;
 const willOpen=(body.style.display==='none');
 if(willOpen&&OPEN_USER!==u&&OPEN_USER>=0){/* 手风琴：收起上一张展开卡 */
  const prev=document.querySelectorAll('#cfgform .ucard')[OPEN_USER];
  if(prev){const ph=prev.querySelector('.uhead2');
   if(ph&&ph.nextElementSibling)ph.nextElementSibling.style.display='none';
   const pc=ph&&ph.querySelector('.chev');if(pc)pc.classList.remove('open');}}
 body.style.display=willOpen?'':'none';
 const c=h.querySelector('.chev');if(c)c.classList.toggle('open',willOpen);
 OPEN_USER=willOpen?u:-1;}
function setN(i,k,v){CFG[i].notifier=CFG[i].notifier||{};CFG[i].notifier[k]=v;}
/* V50：无头开关文字联动 / 通道卡状态灯随启用联动 */
function glbHlChk(el){GLB.headless=el.checked;
 const t=$('glbHlTxt');if(t)t.textContent=el.checked?'后台静默采集':'弹窗可见调试';}
function chSync(el,i,key){const c=el.closest('.chcard');if(!c)return;
 const en=!!(((CFG[i].notifier||{})[key]||{}).enabled);
 c.classList.toggle('on',en);
 const d=c.querySelector('.lgdot');if(d)d.classList.toggle('on',en);
 const m=c.querySelector('.chhead .muted');if(m)m.textContent=en?'已启用':'未启用';}
function togPlat(i,p,el){CFG[i].platforms=CFG[i].platforms||[];
 const k=CFG[i].platforms.indexOf(p);
 if(k>=0)CFG[i].platforms.splice(k,1);else CFG[i].platforms.push(p);
 el.classList.toggle('on');}
function setAy(i,k,v){CFG[i].notifier=CFG[i].notifier||{};
 CFG[i].notifier.aliyun=CFG[i].notifier.aliyun||{};
 CFG[i].notifier.aliyun[k]=v;
 CFG[i].notifier.aliyun.enabled=!!(CFG[i].notifier.aliyun.url||'').trim();}
function setNtfy(i,k,v){CFG[i].notifier=CFG[i].notifier||{};
 CFG[i].notifier.ntfy=CFG[i].notifier.ntfy||{};
 CFG[i].notifier.ntfy[k]=v;
 CFG[i].notifier.ntfy.enabled=!!(CFG[i].notifier.ntfy.topic||'').trim();}
function setSc(i,k,v){CFG[i].notifier=CFG[i].notifier||{};
 CFG[i].notifier.serverchan=CFG[i].notifier.serverchan||{};
 CFG[i].notifier.serverchan[k]=v;
 if(k==='send_key')CFG[i].notifier.serverchan.enabled=!!(v||'').trim();}
async function testToast(b){b.classList.add('busy');
 try{const r=await fetch('/api/test-toast',{method:'POST'});
  const j=await r.json();
  toast(j.ok?'🔔 测试弹窗已发出——收到后点它验证直达详情':'❌ '+(j.err||'失败'),j.ok?'ok':'err');}
 catch(e){toast('❌ 请求失败: '+e,'err');}
 b.classList.remove('busy');}
async function testNtfy(i,b){const nt=(CFG[i].notifier||{}).ntfy||{};
 if(!(nt.topic||'').trim()){toast('❌ 请先填写 ntfy 主题','err');return;}
 b.classList.add('busy');
 try{const r=await fetch('/api/test-ntfy',{method:'POST',
  headers:{'Content-Type':'application/json'},
  body:JSON.stringify({topic:nt.topic,priority:nt.priority||5})});
  const j=await r.json();
  toast(j.ok?'🔔 测试已发到手机 ntfy，请查收':'❌ '+(j.err||'失败'),j.ok?'ok':'err');}
 catch(e){toast('❌ 请求失败: '+e,'err');}
 b.classList.remove('busy');}
function setRoute(i,j,k,v){CFG[i].routes[j][k]=v;}
function setRouteEnabled(i,j,on){
 /* 启用态删键：缺省即启用——config.yaml 不留 true 垃圾，快照比对不误脏 */
 if(on)delete CFG[i].routes[j].enabled;else CFG[i].routes[j].enabled=false;
 /* 外科更新：卡置灰/徽标/C 区摘要，不重建表单（零插拔、滚动不跳） */
 const rl=document.querySelector('.rline[data-rk="'+i+':'+j+'"]');
 if(rl){rl.classList.toggle('off',!on);
  const rb=rl.querySelector('.rbadge');if(rb)rb.textContent=on?'':'已停用';}
 const cs=$('csum-'+i);
 if(cs){const rs=CFG[i].routes||[],en=rs.filter(r=>r.enabled!==false).length,
  dis=rs.length-en;cs.textContent=en+' 条监控中'+(dis?' · '+dis+' 条已停用':'');}}
/* 出发日期 chips：多日期是产品能力不是配置技巧（此前裸文本逗号分隔，
   用户不知道也没法安心多选）。输入三通道等价：文本直输（10-08 自动补
   年、2026/10/8 归一化）/ 回车提交 / 📅 唤原生日历（showPicker）。
   原生 date 控件外观与站内不搭且必须开日历才看得见值——文本为主入口。 */
function _normDate(v){
 v=(v||'').trim().replace(/\//g,'-');
 let m=v.match(/^(\d{1,2})-(\d{1,2})$/);        /* 10-8 → 补年 */
 if(m){const y=new Date().getFullYear();
  v=y+'-'+m[1].padStart(2,'0')+'-'+m[2].padStart(2,'0');}
 else{m=v.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  if(m)v=m[1]+'-'+m[2].padStart(2,'0')+'-'+m[3].padStart(2,'0');}
 if(!/^\d{4}-\d{2}-\d{2}$/.test(v))return null;
 const d=new Date(v+'T00:00:00');
 return isNaN(d)?null:v;}
function addDate(i,j){
 const inp=document.getElementById('dpick-'+i+'-'+j);
 const v=_normDate(inp&&inp.value);
 if(!v){cfgErr('❌ 日期格式应为 YYYY-MM-DD（或 10-08）');return;}
 const rs=CFG[i].routes[j];
 if((rs.dates||[]).includes(v)){toast('该日期已在列表中','err');return;}
 rs.dates=[...(rs.dates||[]),v].sort();
 buildForm();toast('已加 '+v+'（保存后生效）','ok');}
function pickDate(i,j){
 const r=document.getElementById('dreal-'+i+'-'+j);
 r.onchange=()=>{if(r.value){document.getElementById('dpick-'+i+'-'+j).value=r.value;
  addDate(i,j);}};
 try{r.showPicker();}catch(e){r.click();}}
function delDate(i,j,d){const rs=CFG[i].routes[j];
 rs.dates=(rs.dates||[]).filter(x=>x!==d);buildForm();toast('已删 '+d+'（保存后生效）','ok');}
function setDt(i,k,v){CFG[i].notifier=CFG[i].notifier||{};CFG[i].notifier.dingtalk=CFG[i].notifier.dingtalk||{};CFG[i].notifier.dingtalk[k]=v;}
async function testPush(i){const dt=CFG[i].notifier&&CFG[i].notifier.dingtalk||{};
 const b=event.target;
 if(!dt.webhook){$('cfgmsg').textContent='❌ 请先填写 Webhook';return;}
 b.classList.add('busy');$('cfgmsg').textContent='🔔 测试推送中…';
 try{const r=await fetch('/api/test-push',{method:'POST',
  headers:{'Content-Type':'application/json'},
  body:JSON.stringify({webhook:dt.webhook,secret:dt.secret||''})});
  const j=await r.json();
  $('cfgmsg').textContent=j.ok?'✅ 测试消息已发送到钉钉群，请查收'
   :'❌ 推送失败：'+(j.err||'请检查 Webhook 与加签密钥');}
 catch(e){$('cfgmsg').textContent='❌ 请求失败: '+e;}
 b.classList.remove('busy');}
function addUser(){OPEN_USER=CFG.length;CFG.push({name:'新用户',routes:[{from:'SHA',from_name:'上海',to:'SYX',to_name:'三亚',dates:[defDate()],alert_direct:0,alert_transfer:0,transfer_arrival_max:'02:00'}],platforms:['qunar','fliggy','tongcheng','tuniu'],notifier:{digest:true,storm_repeat:3,win_toast:true,dingtalk:{enabled:false,webhook:'',secret:'',at_mobile:''}}});buildForm();
 flashEl(document.querySelectorAll('#cfgform .ucard')[CFG.length-1]);}
function delUser(i){armConfirm(event.target,()=>{CFG.splice(i,1);buildForm();
 toast('已删除用户（保存后生效）','ok');});}
function addRoute(i){CFG[i].routes.push({from:'SHA',from_name:'上海',to:'HAK',to_name:'海口',dates:[defDate()],alert_direct:0,alert_transfer:0,transfer_arrival_max:'02:00'});
 FOLD.route[i+':'+(CFG[i].routes.length-1)]=false;/* 新航线自动展开 */
 buildForm();
 flashEl(document.querySelector('#cfgform .rline[data-rk="'+i+':'+(CFG[i].routes.length-1)+'"]'));}
function flashEl(el){if(!el)return;
 el.scrollIntoView({block:'start',behavior:'smooth'});
 el.classList.add('flash');setTimeout(()=>el.classList.remove('flash'),1500);}
function delRoute(i,j){armConfirm(event.target,()=>{
 CFG[i].routes.splice(j,1);buildForm();});}
/* 快速复制：深拷贝该航线全部配置追加到列表尾，改城市对即可用
   （产品化：同规则多航线是常态，逐项重填 8 个字段太重）；
   复制出的新航线默认停用——先配好再启用，防止城市对没改就开扫。
   复制后新卡自动展开+滚动定位+flash 高亮（找得到刚复制的那条） */
function copyRoute(i,j,btn){
 const src=CFG[i].routes[j],cp=JSON.parse(JSON.stringify(src));
 cp.enabled=false;CFG[i].routes.push(cp);buildForm();
 const nrk=i+':'+(CFG[i].routes.length-1);
 FOLD.route[nrk]=false;saveFold();
 const el=document.querySelector('.rline[data-rk="'+nrk+'"]');
 if(el){const h=el.querySelector('.rhead');
  _setFold(h,_foldSibs(h),false);
  el.scrollIntoView({block:'center',behavior:'smooth'});
  el.classList.add('flash');setTimeout(()=>el.classList.remove('flash'),1600);}
 if(btn){btn.textContent='✓ 已复制';setTimeout(()=>{btn.textContent='⧉ 复制';},1500);}
 toast('已复制为新航线（默认停用）——改好城市对再启用','ok');}
/* 出发时段快捷挡：与明细表筛选同一套挡位语义（一点即填两个 time 输入，
   手输任意值即变自定义——挡位高亮让当前窗口一眼可读） */
const DEPWINS=[['不限','',''],['凌晨','00:00','06:00'],['上午','06:00','12:00'],
               ['下午','12:00','18:00'],['晚间','18:00','23:59']];
function quickDep(i,j,el,lo,hi){
 const rs=CFG[i].routes[j];rs.dep_time_min=lo;rs.dep_time_max=hi;
 const box=el.closest('.sctl'),t=box.querySelectorAll('input[type=time]');
 t[0].value=lo;t[1].value=hi;
 box.querySelectorAll('.schip').forEach(c=>c.classList.remove('on'));
 el.classList.add('on');
 toast(lo?'窗口已设 '+lo+'–'+hi+'（保存后生效）':'已改为不限（保存后生效）','ok');}
function customDepWin(el){/* 手输=自定义窗口：清挡位高亮 */
 el.closest('.sctl').querySelectorAll('.schip').forEach(c=>c.classList.remove('on'));}
function defDate(){const d=new Date(Date.now()+14*864e5);
 return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');}
function cfgErr(m){/* 校验失败提示必达：页面顶部 cfgmsg + 右下 toast 双通道 */
 $('cfgmsg').textContent=m;toast(m,'err');}
async function saveCfg(){
 if(!CFG){cfgErr('❌ 配置尚未载入，请稍候再保存');return;}
 // V50：全局参数先校验（周期/端口），再逐用户校验
 const iv=parseInt(GLB.interval_minutes);
 if(isNaN(iv)||iv<5||iv>720){cfgErr('❌ 扫描周期须为 5-720 的整数分钟');return;}
 const port=parseInt(GLB.port);
 if(isNaN(port)||port<1024||port>65535){cfgErr('❌ 控制台端口须为 1024-65535');return;}
 const to=parseInt(GLB.timeout_seconds);
 if(isNaN(to)||to<10||to>600){cfgErr('❌ 采集超时须为 10-600 秒');return;}
 const dn=parseInt(GLB.delay_min),dx=parseInt(GLB.delay_max);
 if(isNaN(dn)||dn<0||dn>120||isNaN(dx)||dx<0||dx>120||dn>dx){
  cfgErr('❌ 错峰延迟须为 0-120 秒且「自」≤「至」');return;}
 // 城市中文名 → 三字码；校验
 for(const u of CFG){
  const seenKey={};
  for(const r of (u.routes||[])){
   r.from=CITY[r.from_name]||r.from;r.to=CITY[r.to_name]||r.to;
   if(!CITY[r.from_name]&&!/^[A-Z]{3}$/.test(r.from||'')){
    $('cfgmsg').textContent='❌ 不支持的城市：'+r.from_name;return;}
   if(!r.dates||!r.dates.length){cfgErr('❌ 航线缺日期');return;}
   for(const d of r.dates){
    if(!/^\d{4}-\d{2}-\d{2}$/.test(d)){
     $('cfgmsg').textContent='❌ 日期格式应为 YYYY-MM-DD：'+d;return;}
    const dk=r.from_name+'→'+r.to_name+' '+d;
    if(seenKey[dk]){$('cfgmsg').textContent='❌ 重复航线：'+dk;return;}
    seenKey[dk]=1;}
   for(const k of ('alert_direct','alert_transfer')){
    const v=Number(r[k]);
    if(r[k]!==''&&r[k]!=null&&(isNaN(v)||v<0||v>99999)){
     cfgErr('❌ 阈值须为 0-99999 的数字');return;}}
   if(!/^\d{2}:\d{2}$/.test(r.transfer_arrival_max||'02:00')){
    $('cfgmsg').textContent='❌ 到达时刻应为 HH:MM：'+r.transfer_arrival_max;return;}}
  const dt=(u.notifier||{}).dingtalk||{};
  const rh=(u.notifier||{}).report_hour;
  if(rh!==''&&rh!=null&&(isNaN(Number(rh))||Number(rh)<0||Number(rh)>23)){
   cfgErr('❌ 日报时刻须为 0-23 的整数');return;}
  const _NL={'storm_repeat':'风暴连推','push_drop_min':'降价再推阈值',
   'push_rise_min':'涨价再推阈值','report_hour':'日报时刻'};
  for(const k of ['storm_repeat','push_drop_min','push_rise_min']){
   const v=(u.notifier||{})[k];
   if(v!==''&&v!=null&&(isNaN(Number(v))||Number(v)<0||Number(v)>99999)){
    $('cfgmsg').textContent='❌ '+(_NL[k]||k)+'须为 0-99999 的数字';return;}}
  if(dt.enabled&&dt.webhook&&!/^https:\/\/oapi\.dingtalk\.com\/robot\/send\?access_token=/.test(dt.webhook)){
   cfgErr('❌ 钉钉 Webhook 应以 https://oapi.dingtalk.com/robot/send?access_token= 开头');return;}}
 if(!CFG.length){cfgErr('❌ 至少一个用户');return;}
 $('cfgmsg').textContent='保存中…';
 try{const r=await fetch('/api/config',{method:'POST',
  headers:{'Content-Type':'application/json'},
  body:JSON.stringify({users:CFG,globals:GLB})});
  const j=await r.json();
  $('cfgmsg').textContent=j.ok?'✅ 已保存，'+j.users+' 个用户已热重载生效':'❌ '+(j.err||'失败');;
  if(!j.ok)toast('❌ 保存失败：'+(j.err||''),'err');
  if(j.ok){
   const oldPort=location.port;
   CFG_CLEAN=JSON.stringify(CFG);GLB_CLEAN=JSON.stringify(GLB);
   if(String(GLB.port||8765)!==oldPort){
    if(window.toast)toast('🎛 控制台端口已切换至 '+GLB.port+'，正在跳转…','ok');
    setTimeout(()=>{location.href=location.protocol+'//'+location.hostname
     +':'+GLB.port+location.pathname;},1600);
   }else{toast('💾 已保存，全部配置热生效','ok');
    setTimeout(()=>{load();},800);
    setTimeout(()=>{const m=$('cfgmsg');
     if(m&&m.textContent.charAt(0)==='✅')m.textContent='';},6000);}}
 }catch(e){cfgErr('❌ 请求失败: '+e);}}
/* ===== V50 配置搜索：字段级过滤（srow/rline 容器按可见子块收敛；
   buildForm 重建后按 CFGQ 重放，搜索状态不丢 ===== */
function cfgFilter(qraw){const q=(qraw||'').trim().toLowerCase();
 const hits=$('cfgHits');if(!q){hits.textContent='';
  document.querySelectorAll(''
   +'#cfgview .glgrid>div,#cfgview .srow,#cfgview .rline,#cfgview .chcard,'
   +'#cfgview .frow,#cfgview .row,#cfgview .grouplab')
   .forEach(el=>{el.style.display='';el.style.boxShadow='';});
  showCfgPanel(CFGPANEL,true);applyFolds();return;}
 /* 搜索态：全部分区临时可见（子卡临时全开），只留命中字段 */
 document.querySelectorAll('#cfgmain .cfpanel').forEach(p=>{p.style.display='';});
 expandFolds();
 let n=0;
 document.querySelectorAll(''
  +'#cfgview .glgrid>div,#cfgview .srow').forEach(d=>{
  const inputs=[...d.querySelectorAll('input')].map(i=>i.value).join(' ');
  const m=((d.textContent||'')+' '+inputs).toLowerCase().includes(q);
  d.style.display=m?'':'none';
  d.style.boxShadow=m?'0 0 0 2px '+cssv('--glow'):'';   /* 主题随动（曾钉亮色蓝，暗色下与 --glow 脱节） */
  if(m)n++;});
 document.querySelectorAll('#cfgview .frow,#cfgview .row').forEach(el=>{
  if(el.closest('.rline'))return;
  const m=(el.textContent||'').toLowerCase().includes(q);
  el.style.display=m?'':'none';if(m)n++;});
 document.querySelectorAll('#cfgview .rline,#cfgview .chcard').forEach(rl=>{
  /* 容器可见性随命中字段行（.srow，v100.6.0 起的统一行类）——
     此处曾查早已不存在的 .tog，命中也整卡隐藏，搜索对用户航线分区失效 */
  const vis=Array.from(rl.querySelectorAll('.srow'))
   .some(d=>d.style.display!=='none');
  rl.style.display=vis?'':'none';});
 document.querySelectorAll('#cfgview .grouplab').forEach(g=>{g.style.display='';});
 hits.textContent=n?('✓ '+n+' 项匹配'):'无匹配项';

}
/* ===== V50 配置导入/导出：本地 JSON 直拷（含钉钉等凭据，本机自管） ===== */
function exportCfg(){
 try{const blob=new Blob([JSON.stringify({users:CFG,globals:GLB},null,2)],
  {type:'application/json'});
  const a=document.createElement('a');
  a.href=URL.createObjectURL(blob);
  const _pd=new Date();
  a.download='ticket-monitoring-config-'+_pd.getFullYear()
   +(String(_pd.getMonth()+1).padStart(2,'0'))+(String(_pd.getDate()).padStart(2,'0'))+'.json';
  a.click();setTimeout(()=>URL.revokeObjectURL(a.href),3000);
  toast('📤 配置已导出（含钉钉等本地凭据，请妥善保管）','ok');}
 catch(e){toast('❌ 导出失败：'+e.message,'err');}}
function importCfg(inp){const f=inp.files&&inp.files[0];if(!f)return;
 const rd=new FileReader();
 rd.onload=()=>{try{
  const j=JSON.parse(rd.result);
  if(!Array.isArray(j.users)||!j.users.length)throw new Error('文件缺少 users 数组');
  CFG=j.users;GLB=j.globals||GLB;OPEN_USER=0;
  buildForm();
  toast('📥 已导入 '+CFG.length+' 个用户——检查无误后点「保存并生效」','ok');}
  catch(e){toast('❌ 导入失败：'+e.message,'err');}
  inp.value='';};
 rd.readAsText(f,'utf-8');}
/* ===== V50 脏计数：叶子级 diff，savebar/徽标显示 N 处修改 ===== */
function countDiff(a,b){
 if(a===b)return 0;
 if(typeof a!=='object'||typeof b!=='object'||!a||!b)return 1;
 if(Array.isArray(a)!==Array.isArray(b))return 1;
 let c=0;const seen={};
 Object.keys(a).concat(Object.keys(b)).forEach(k=>{
  if(seen[k])return;seen[k]=1;
  if(!(k in a)||!(k in b)){c++;return;}
  c+=countDiff(a[k],b[k]);});
 return c;}
function cfgDirtyCount(){
 try{return countDiff(JSON.parse(CFG_CLEAN||'[]'),CFG)
  +countDiff(JSON.parse(GLB_CLEAN||'{}'),GLB);}
 catch(e){return 0;}}
</script></body></html>"""


NOTIFY_PAGE = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>达标通知 · 机票监控</title>
<script>
/* 与主控制台同一主题体系（localStorage jptheme: auto/light/dark）——
   否则主站暗色、弹窗落地页亮色，主题体验断裂。渲染前落 data-theme 防闪白 */
(function(){var t='auto';try{t=localStorage.getItem('jptheme')||'auto'}catch(e){}
 var dark=t==='dark'||(t!=='light'&&window.matchMedia
   &&window.matchMedia('(prefers-color-scheme:dark)').matches);
 document.documentElement.dataset.theme=dark?'dark':'light';})();
</script>
<style>
 :root{--bg:#eceff4;--card:#ffffff;--tx:#141f2b;--mut:#617384;--line:#dde3ea;
       --line2:#cbd4de;--blue:#0b62d6;--green:#0e8345;--okbg:#e9f4ec;
       --okrgb:14,131,69;   /* 绿档通道令牌（hitbar/hitpulse 消费）；暗色两块覆写随主站 #43c072 换谱 */
       --pillbd:rgba(11,98,214,.32);--pillbg:rgba(11,98,214,.07);
       --pillbh:rgba(11,98,214,.14);--pillbd2:rgba(11,98,214,.55);
       --num:"Cascadia Mono","Consolas","SF Mono","Menlo",monospace;--r:14px}
 *{box-sizing:border-box}
 html{color-scheme:light}
 :root[data-theme="dark"]{color-scheme:dark;--bg:#0a0f16;--card:#101823;--tx:#dbe4ee;
   --mut:#7f92a6;--line:#1e2a3a;--line2:#2a3a50;--okbg:#12241a;--blue:#63a4f8;
   --green:#43c072;--okrgb:67,192,114;
   --pillbd:rgba(99,164,248,.5);--pillbg:rgba(99,164,248,.12);
   --pillbh:rgba(99,164,248,.22);--pillbd2:rgba(99,164,248,.75)}
 @media(prefers-color-scheme:dark){:root:not([data-theme=light]){color-scheme:dark;
   --bg:#0a0f16;--card:#101823;--tx:#dbe4ee;
   --mut:#7f92a6;--line:#1e2a3a;--line2:#2a3a50;--okbg:#12241a;--blue:#63a4f8;
   --green:#43c072;--okrgb:67,192,114;
   --pillbd:rgba(99,164,248,.5);--pillbg:rgba(99,164,248,.12);
   --pillbh:rgba(99,164,248,.22);--pillbd2:rgba(99,164,248,.75)}}
 body{font-family:"Segoe UI Variable Text","Segoe UI","Microsoft YaHei","PingFang SC",sans-serif;
      margin:0;background:var(--bg);color:var(--tx)}
 .top{display:flex;align-items:center;gap:10px;padding:12px 18px;background:var(--card);
      border-bottom:1px solid var(--line2);position:sticky;top:0;z-index:5}
 .logo{width:26px;height:26px;border-radius:7px;background:var(--tx);color:var(--bg);
       display:inline-flex;align-items:center;justify-content:center;font-size:13px}
 .top b{font-size:12px;letter-spacing:1.2px;text-transform:uppercase}
 .wrap{max-width:680px;margin:0 auto;padding:22px 18px}
 .hitbar{display:flex;align-items:center;gap:10px;background:var(--okbg);
      border:1px solid rgba(var(--okrgb),.35);border-radius:12px;padding:12px 16px;margin-bottom:16px}
 .hitbar b{color:var(--green);font-size:14px}
 .hitbar.ok b::before{content:"";display:inline-block;width:8px;height:8px;border-radius:50%;
      background:var(--green);margin-right:8px;vertical-align:1px;
      animation:hitpulse 1.6s ease-in-out infinite}
 @keyframes hitpulse{0%,100%{box-shadow:0 0 0 0 rgba(var(--okrgb),.4)}
      50%{box-shadow:0 0 0 5px rgba(var(--okrgb),0)}}
 .card{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:18px 22px}
 .md h1{font-size:19px;margin:6px 0 14px;line-height:1.5}
 .md .h2{font-size:15px;color:var(--blue);margin:16px 0 8px;font-weight:700}
 .md .h3{font-size:13.5px;margin:12px 0 6px;font-weight:700}
 .md p{margin:7px 0;line-height:1.85;font-size:14px}
 /* CTA 胶囊：落地页里所有链接都是动作（去下单/看详情），胶囊化提质感 */
 .md a{display:inline-block;color:var(--blue);text-decoration:none;font-weight:600;
      padding:5px 14px;margin:2px 6px 2px 0;border-radius:999px;
      border:1px solid var(--pillbd);background:var(--pillbg);
      transition:background .15s,border-color .15s}
 .md a:hover{background:var(--pillbh);border-color:var(--pillbd2)}
 /* --- 分隔线：渐隐 hairline（默认裸 hr 极廉价） */
 .md hr{border:none;height:1px;margin:14px 0;
       background:linear-gradient(90deg,transparent,var(--line2) 18%,var(--line2) 82%,transparent)}
 .md .g{letter-spacing:2px;font-size:15px}
 .md b{font-variant-numeric:tabular-nums}
 .md img{max-width:100%;border-radius:10px;border:1px solid var(--line);display:block;margin:10px 0}
 .foot{margin-top:16px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px}
 .foot a{display:inline;color:var(--blue);font-size:13px;font-weight:400;
        padding:0;margin:0;border:none;background:none}
 .foot a:hover{background:none;text-decoration:underline}
 .ts{color:var(--mut);font-size:12px;font-variant-numeric:tabular-nums}
</style></head><body>
<div class="top"><span class="logo">✈️</span><b>机票监控 · 达标通知</b></div>
<div class="wrap">
 <div class="hitbar"><b>🚨 已达标——可出手</b><span id="ts" class="ts" style="margin-left:auto"></span></div>
 <div class="card md" id="md"></div>
 <div class="foot">
  <a id="console" href="/#details">打开完整控制台 →</a>
  <span class="ts">点系统弹窗直达本页 · 数据仅存本机</span>
 </div>
</div>
<script>
const N=__PAYLOAD__;
document.getElementById("ts").textContent=N.ts||"";
document.title=(N.title||"达标通知")+" · 机票监控";
/* 横幅随内容如实变化：非达标通知（如"通知不存在"）不冒充达标 */
(function(){const hb=document.querySelector(".hitbar"),hbB=hb.querySelector("b");
 if((N.title||"").indexOf("达标")>=0){hb.classList.add("ok");
  hbB.textContent="🚨 已达标——可出手";return;}
 hbB.textContent=N.title||"通知";
 hb.style.background="var(--card)";hb.style.borderColor="var(--line)";
 hbB.style.color="var(--tx)";})();
function esc(s){return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/"/g,"&quot;")}
function inline(s){let t=esc(s)
 .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>')
 .replace(/@(\d[\d*]+)/g,'<span style="background:#ffd24d;color:#7a4b00;border-radius:4px;padding:0 5px">@$1</span>')
 const parts=t.split("**");let o=""
 for(let i=0;i<parts.length;i++)o+=(i%2)?"<b>"+parts[i]+"</b>":parts[i]
 return o}
const NL=String.fromCharCode(10)
const md=document.getElementById("md")
String(N.desp||"").split(NL).forEach(ln=>{
 const t=ln.trim()
 if(!t){return}
 if(t.indexOf("![")===0){const m=t.match(/\\((https?:[^)]+)\\)/)
  if(m){const im=document.createElement("img");im.src=m[1];md.appendChild(im)}return}
 if(t.indexOf("#### ")===0){const d=document.createElement("div");d.className="h3";d.innerHTML=inline(t.slice(5));md.appendChild(d);return}
 if(t.indexOf("### ")===0){const d=document.createElement("div");d.className="h3";d.innerHTML=inline(t.slice(4));md.appendChild(d);return}
 if(t.indexOf("## ")===0){const d=document.createElement("div");d.className="h2";d.innerHTML=inline(t.slice(3));md.appendChild(d);return}
 if(t.indexOf("# ")===0){const d=document.createElement("h1");d.innerHTML=inline(t.slice(2));md.appendChild(d);return}
 if(/^-{3,}$/.test(t)){const d=document.createElement("hr");md.appendChild(d);return}
 if(t.indexOf("> ")===0){const d=document.createElement("p");d.style.cssText="border-left:3px solid var(--blue);padding:4px 12px;margin:6px 0;color:var(--mut)";d.innerHTML=inline(t.slice(2));md.appendChild(d);return}
 if(/^[🟦🟩🟨⬜🟥]+$/.test(t.replace(/\\s/g,""))){const d=document.createElement("div");d.className="g";d.textContent=t;md.appendChild(d);return}
 const p=document.createElement("p");p.innerHTML=inline(t);md.appendChild(p)})
document.getElementById("console").href=location.origin+"/#details"
</script></body></html>"""


class _State:
    cfg = None
    users = None
    job = None
    report_push = None
    reload_cb = None
    config_path = "config.yaml"
    version = ""
    logger = logging.getLogger("ticket-monitor")
    lock = threading.Lock()
    login_sessions = {}   # plat -> {"evt": Event}（进行中的网页登录窗口）


_LOGIN_PLATS = ("qunar", "ctrip", "tongcheng", "tuniu", "fliggy")


def _login_state_view() -> dict:
    """各渠道登录态视图：user_data/<plat> 目录非空即视为已有会话。"""
    import os as _os
    root = ((_State.cfg or {}).get("crawler") or {}).get(
        "user_data_dir", "user_data")
    plats = {}
    for p in _LOGIN_PLATS:
        d = _os.path.join(root, p)
        try:
            saved = _os.path.isdir(d) and next(_os.scandir(d), None) is not None
        except OSError:
            saved = False
        plats[p] = {"saved": saved, "active": p in _State.login_sessions}
    return {"ok": True, "plats": plats}


def _start_login(plat: str) -> dict:
    """网页登录：弹出该渠道的有头浏览器窗口（与 --login 同机制），
    用户在窗口完成登录后点「我已登录完成」保存会话。"""
    from crawlers import REGISTRY
    if plat not in _LOGIN_PLATS or plat not in REGISTRY:
        return {"ok": False, "err": "未知渠道: %s" % plat}
    with _State.lock:
        if plat in _State.login_sessions:
            return {"ok": False,
                    "err": "该渠道登录窗口已打开——请在窗口完成登录后点「我已登录完成」"}
        evt = threading.Event()
        _State.login_sessions[plat] = {"evt": evt}
    cfg = ((_State.cfg or {}).get("crawler") or {})
    logger = _State.logger

    def _run():
        try:
            crawler = REGISTRY[plat](cfg, logger)
            crawler._login_window(evt, 0)
            _State.logger.info("[登录] %s 会话已保存（网页登录）", plat)
        except Exception as e:
            _State.logger.warning("[登录] %s 登录窗口异常: %s", plat, e)
        finally:
            _State.login_sessions.pop(plat, None)

    threading.Thread(target=_run, daemon=True).start()
    _State.logger.info("[登录] 已弹出 %s 登录窗口", plat)
    return {"ok": True, "plat": plat}


def _finish_login(plat: str) -> dict:
    sess = _State.login_sessions.get(plat)
    if not sess:
        return {"ok": False, "err": "该渠道没有进行中的登录窗口"}
    sess["evt"].set()
    return {"ok": True, "plat": plat}


def _next_run() -> str:
    """调度器下一轮时间（SCHED 未起/打包单跑时返回空串）。"""
    try:
        from core.scheduler import SCHED
        if SCHED:
            job = SCHED.get_job("price_monitor")
            if job and job.next_run_time:
                return job.next_run_time.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass
    return ""


def _view_url(rr: dict, date: str, plat: str) -> str:
    """明细行内 ↗ 跳转链接——复用 Alerter._build_view_url，与各渠道爬虫
    已验证主路径同源（链接必须点开有数据；qunar 为 PC 页非 touch H5）。
    空/未知平台返回 ""（宁缺勿错，与 alerter 同策略）——曾缺省回落
    "qunar"，控制台缺平台行会误出去哪儿链接（挂羊头风险）。"""
    try:
        from types import SimpleNamespace
        from core.alerter import Alerter
        ns = SimpleNamespace(from_code=(rr or {}).get("from", ""),
                             from_name=(rr or {}).get("from_name", ""),
                             to_code=(rr or {}).get("to", ""),
                             to_name=(rr or {}).get("to_name", ""))
        return Alerter._build_view_url(None, ns, date or "", plat or "")
    except Exception:
        return ""


def _route_view(r) -> dict:
    """归一化航线：兼容 dict 配置（from/to）与运行时 Route 对象（from_code/to_code）。"""
    if isinstance(r, dict):
        d = r
    else:
        try:
            from dataclasses import asdict as _asdict
            d = _asdict(r)
        except Exception:
            return {}
    return {
        "from": d.get("from_code", d.get("from", "")),
        "to": d.get("to_code", d.get("to", "")),
        "from_name": d.get("from_name") or d.get("from", ""),
        "to_name": d.get("to_name") or d.get("to", ""),
        "dates": d.get("dates") or [],
        "alert_direct": float(d.get("alert_direct", 0) or 0),
        "alert_transfer": float(d.get("alert_transfer", 0) or 0),
        "transfer_arrival_max": d.get("transfer_arrival_max", "02:00"),
        "transfer_layover_min": int(d.get("transfer_layover_min", 0) or 0),
        "transfer_baggage": d.get("transfer_baggage", "") or "",
        "dep_time_min": d.get("dep_time_min", "") or "",
        "dep_time_max": d.get("dep_time_max", "") or "",
    }


def _dep_win_of(r):
    """出发窗口元组（dict 路由配置 → (dmin,dmax)；未配置 None）——
    走势/日历取数与明细列表同窗（曲线与列表同口径）。"""
    dmin = (r.get("dep_time_min") or "").strip()
    dmax = (r.get("dep_time_max") or "").strip()
    return (dmin, dmax) if (dmin or dmax) else None


def _cluster_round_rows(rows, gap_s: int = 300):
    """按时间断口聚"轮"：倒序相邻行距 >gap_s 秒视为轮边界。

    一轮内多查询错峰完成跨 2-3 分钟、轮间隔 ~15 分钟——原"最新 1 分钟片"
    会切掉前几查询的明细。纯函数便于单测。"""
    from datetime import datetime as _dt

    def _ts(s):
        try:
            return _dt.strptime(str(s)[:19], "%Y-%m-%d %H:%M:%S")
        except Exception:
            return None

    out, prev_t = [], None
    for r in rows:
        t = _ts(r["fetched_at"])
        if prev_t is not None and t and (prev_t - t).total_seconds() > gap_s:
            break
        out.append(r)
        prev_t = t or prev_t
    return out


def _user_state(u):
    """单个用户的状态视图（最新轮明细 + 近期补位 + 走势历史）。"""
    st = _State
    db = _anchored((st.cfg.get("output") or {}).get("db_path"),
                   "data/prices.db")
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT platform, from_city, to_city, depart_date, price, extra, fetched_at "
        "FROM flight_prices "
        "WHERE extra != '' AND fetched_at >= "
        "datetime('now', 'localtime', '-40 minutes') "
        "ORDER BY id DESC").fetchall()
    conn.close()
    flights, latest, seen = [], "", set()
    plat_min = {}
    routes = [_route_view(r) for r in (u.get("routes") or [])]
    # 出发时段约束（与告警链路同一套窗口；按 航线+日期 粒度，
    # 同航线不同日期可有不同窗口，如返程 10-4 仅晚间 / 10-5 全天）
    win = {}
    for r in routes:
        if (r.get("dep_time_min") or "").strip() or (r.get("dep_time_max") or "").strip():
            for d in r.get("dates") or [""]:
                win[(r["from"], r["to"], d)] = (
                    r["dep_time_min"].strip(), r["dep_time_max"].strip())

    def _keep(f):
        pair = f.get("_pair")
        w = win.get((pair[0], pair[1], f.get("depDate", "")))
        if not w:
            return True
        return Alerter._dep_in_window(f.get("depTime", ""), w[0], w[1])
    # 该用户关注的航线集合（明细/全线最低都只看自己航线）
    my_pairs = {(r["from"], r["to"]) for r in routes}
    rows = _cluster_round_rows(rows)
    # 跨渠道孤低价守卫·行级（v1.5.45）：FlightPrice 行=渠道最低价，幻影
    # 渠道最低（< 其他渠道最低中位 ×0.5）不进 plat_min（概览 mchip 曾
    # 直出「￥700」）、不进明细池。Row 不可写 → 按下标集合标记
    _row_ph = set()
    _rgrp = {}
    for _ri, r in enumerate(rows):
        _rgrp.setdefault(
            (r["from_city"], r["to_city"], r["depart_date"]), []).append(_ri)
    for _idxs in _rgrp.values():
        _ent = [(rows[i]["price"]
                 + (FLIGGY_TAX_PAD if rows[i]["platform"] == "fliggy" else 0),
                 rows[i]["platform"]) for i in _idxs]
        for i in xchan_phantom_idx(_ent):
            _row_ph.add(_idxs[i])
    for ri, r in enumerate(rows):
        if ri in _row_ph:
            continue
        if my_pairs and (r["from_city"], r["to_city"]) not in my_pairs:
            continue
        plat_min[r["platform"]] = min(plat_min.get(r["platform"], 9e9), r["price"])
        seen_key = (r["platform"], r["from_city"], r["to_city"], r["depart_date"])
        if seen_key in seen:
            continue
        seen.add(seen_key)
        try:
            obj = json.loads(r["extra"])
        except Exception:
            continue
        if isinstance(obj, list):
            from core.flightnorm import normalize as _fnorm
            for f in obj:
                if isinstance(f, dict) and "price" in f:
                    g = dict(f)
                    g["_platform"] = r["platform"]
                    g["_pair"] = (r["from_city"], r["to_city"])
                    _fnorm(g, r["depart_date"] or "")
                    if _keep(g):
                        flights.append(g)
    route = routes[0] if routes else {}
    th_d = float(route.get("alert_direct", 0) or 0)
    th_t = float(route.get("alert_transfer", 0) or 0)
    am = route.get("transfer_arrival_max", "02:00") or "02:00"
    route_by_pair = {(r["from"], r["to"]): r for r in routes}
    # 同航线不同日期可有不同阈值/窗口（如乌→上 10/04 线 1600、10/05 线 1900）：
    # 按城市对索引会让后配置的日期覆盖前者——必须 (航线,日期) 精确匹配再回退航线
    route_by_fd = {}
    for _r in routes:
        for _d0 in _r.get("dates") or [""]:
            route_by_fd[(_r["from"], _r["to"], _d0)] = _r

    def _rr_of(f):
        _p = f.get("_pair") or ("", "")
        return (route_by_fd.get((_p[0], _p[1], f.get("depDate", "")))
                or route_by_pair.get(_p) or route)

    # 达标判定与推送同口径（Alerter._transfer_ok）：直飞仅比阈值；中转=
    # 到达约束 + 衔接下限 + 直挂约束；layoverM 缺失按不满足（宁漏不虚报）。
    # 每行按所属航线的阈值（同航线不同日期可有不同线）。概览 KPI/浏览器
    # 通知与明细行共用本函数——三个通道对「能不能出手」同一句话。
    def _qual_of(f, transfer, price):
        rq = _rr_of(f)
        # 孤低价行永不判达标（与推送/走势同一防线，控制台不留例外口子）
        if f.get("_xphan"):
            return False
        # 达标口径价：飞猪税前展示价加税垫（与推送 _collect_hits 同式）
        eff = _qual_price({"price": price,
                           "_platform": f.get("_platform")})
        if transfer:
            qt = float(rq.get("alert_transfer", 0) or 0)
            return bool(qt and eff <= qt and Alerter._transfer_ok(f, {
                "transfer_arrival_max": rq.get("transfer_arrival_max", "02:00") or "02:00",
                "transfer_layover_min": float(rq.get("transfer_layover_min", 0) or 0),
                "transfer_baggage": rq.get("transfer_baggage", "")}))
        qd = float(rq.get("alert_direct", 0) or 0)
        return bool(qd and eff <= qd)
    # 近期明细补位：当轮缺明细的平台用近 6h 成功明细——与推送链同款
    # 逐航线×日期补齐（曾只补 routes[0] 首日期：多日期/多航线时钉钉
    # 明细有该渠道补位价而控制台没有）
    try:
        have_pd = {(f.get("_platform"), f.get("depDate", "")) for f in flights}
        recent = {}
        for _r in routes:
            for _d0 in _r.get("dates") or [""]:
                _k3 = (_r.get("from", ""), _r.get("to", ""))
                for p, (age, fl) in recent_platform_flights(
                        db, _k3[0], _k3[1], _d0, hours=6).items():
                    if (p, _d0) in have_pd:
                        continue
                    _prev = recent.get((p, _d0))
                    if not _prev or age < _prev[0]:
                        recent[(p, _d0)] = (age, fl, _k3)
        for (p, _d0), (age, fl, _k3) in recent.items():
            for f in fl:
                if isinstance(f, dict) and "price" in f:
                    if not Alerter._stale_sane(f):
                        continue
                    g = dict(f)
                    g["_platform"] = p
                    g["_stale_h"] = round(age, 1)
                    g["_pair"] = _k3
                    g["depDate"] = g.get("depDate") or _d0
                    if _keep(g):
                        flights.append(g)
    except Exception:
        pass
    # 先全量归一化，再做同指纹衔接补全（qunar 列表页不渲染停留时长，
    # 同班次在携程测得的真实停留补到缺行——与聚合池同口径）
    from core.flightnorm import normalize as _fnorm_all
    import logging as _logging
    _lg_state = _logging.getLogger("ticket-monitor")
    for f in flights:
        try:
            _fnorm_all(f, f.get("depDate", ""))
        except Exception as e:
            # 归一化失败曾整行静默丢弃零留痕（访客审计会质疑吞异常）——
            # debug 级留痕，坏数据可回溯
            _lg_state.debug("state 归一化失败 %s: %s", f.get("name", "?"), e)
    Alerter._propagate_layover(flights)
    # 跨渠道孤低价守卫·明细级（v1.5.45，与告警池/走势池同一判定）：
    # 按 航线×日期×直/中 分组打 _xphan——明细行保留显示（原始保真）但
    # 永不判达标、不进行情最优/KPI（前端价格挂 ⚠ 角标）
    _fgrp = {}
    for f in flights:
        _fgrp.setdefault((f.get("_pair"), f.get("depDate", ""),
                          bool(f.get("transCity"))), []).append(f)
    for _g in _fgrp.values():
        Alerter._mark_xchan(_g)
    out = []
    for f in flights:
        transfer = bool(f.get("transCity"))
        try:
            price = round(float(f["price"]))
        except (TypeError, ValueError):
            price = f["price"]
        # 多航线：每行明细按其所属航线的阈值判达标
        qual = _qual_of(f, transfer, price)
        rr = _rr_of(f)
        rt_label = (f"{rr.get('from_name','')}→{rr.get('to_name','')}"
                    if len(routes) > 1 else "")
        thv = float(rr.get("alert_transfer" if transfer else "alert_direct", 0) or 0)
        # 明细行链接保持该行自身渠道（行价=该渠道报价，落点价=文案价）；
        # 同价跨渠道优选只做在概览 KPI 卡与推送链接（_pref_platform）
        view = _view_url(rr, f.get("depDate", ""),
                         f.get("_platform") or "")
        # 空/未知平台 _view_url 返回 ""（宁缺勿错，不出去哪儿挂羊头链）
        # 擦边：未达标但距线 10% 以内（表格琥珀提示，扫读一眼看出快到了）
        # 擦边带宽 NEAR_RATIO 已收口 core.alerter 单源（v1.5.46）
        near = (not qual and thv > 0
                and 0 < (price - thv) / thv <= NEAR_RATIO)
        # 行情破线未达标（第四档，前端描边绿）：价≤线但非直挂/衔接不足/
        # 税前等约束不满足；near 价>线与本档价≤线天然互斥（brk 低优先）
        brk = (not qual) and (thv > 0) and (price <= thv)
        from core.flightnorm import cabin_text as _ct, normalize as _fnorm
        _fnorm(f, f.get("depDate", ""))  # 幂等兜底：demo 等未过汇聚点的路径
        # 决策字段透传（爬虫端 normalize 落库，缺失=None → 前端空值不占位）：
        # 航站楼 depTerminal/arrTerminal（qunar/ctrip/tuniu）、历史平均延误 avgDelay（tuniu，分钟）
        try:
            avg_delay = int(f.get("avgDelay"))
        except (TypeError, ValueError):
            avg_delay = None
        out.append({
            "price": price, "transfer": transfer, "name": f.get("name", ""),
            "code": f.get("code", ""),
            "cabinT": _ct(f), "layoverT": f.get("layoverT", ""),
            "prate": str(f.get("prate") or "").strip(),
            "meal": str(f.get("meal") or "").strip(),
            "shareCarrier": (f.get("shareCarrier") or "").strip(),
            "fewTicket": (f.get("fewTicket") or "").strip(),
            "depTerminal": (f.get("depTerminal") or "").strip(),
            "arrTerminal": (f.get("arrTerminal") or "").strip(),
            "avgDelay": avg_delay,
            "layoverM": f.get("layoverM", 0),
            "layMin": int(rr.get("transfer_layover_min", 0) or 0),
            "lay2dep": (f.get("lay2dep") or ""),
            "tam": (rr.get("transfer_arrival_max", "02:00") or "02:00"),
            "bag": f.get("transferBaggage") == "direct",
            "stop": bool(f.get("stopover")),
            "stopCity": (f.get("stopCity") or "").strip(),
            "stopTimeT": (f.get("stopTimeT") or "").strip(),
            "depTime": f.get("depTime", ""), "arrTime": f.get("arrTime", ""),
            "date": f.get("depDate", ""),
            "trans": f.get("transCity", ""), "cross": f.get("crossDayDesc", ""),
            "route": rt_label,
            "dur": f.get("totalDuration") or "",
            "durM": _dur_min(f.get("totalDuration")),
            "plat": Alerter.PLATFORM_CN.get(f.get("_platform", ""), ""),
            "platKey": f.get("_platform", ""),
            "stale": round(f["_stale_h"]) if f.get("_stale_h") else 0,
            "xphan": bool(f.get("_xphan")),
            "qual": qual, "near": near, "brk": brk, "view": view,
        })
    # 同班比价离群旗标下发（v1.5.46）：与钉钉/总表图同一 Alerter._outlier
    # 口径（最高>2×最低 或 组内舱位大类>1）。前端本地曾只判 2×——跨舱位
    # ≤2× 时 webui 显示「可省」而推送显示「差」，同屏两语言。组级属性
    # 挂组内每行（指纹与前端 fp 同构：日期/时刻/中转/跨天/经停）
    _og = {}
    for _o in out:
        _k = (_o["date"], _o["depTime"], _o["arrTime"], _o["trans"],
              _o["cross"], _o["stop"])
        _byp = _og.setdefault(_k, {})
        _cur = _byp.get(_o["plat"])
        if _cur is None or _o["price"] < _cur["price"]:
            _byp[_o["plat"]] = _o
    for _byp in _og.values():
        if len(_byp) > 1:
            _ol = Alerter._outlier(
                sorted(_byp.values(), key=lambda x: x["price"]))
            for _o in _byp.values():
                _o["outlier"] = _ol
    directs = [f for f in flights
               if not f.get("transCity") and not f.get("_xphan")]
    # 中转到达约束按各自航线（原实现拿 routes[0] 的 am 一刀切——多航线混串）
    def _am_of(f):
        rr = _rr_of(f)
        return rr.get("transfer_arrival_max", "02:00") or "02:00"

    # 行情口径（与走势曲线 _rounds 一致）：到达约束 + 衔接下限（行李不参与）
    def _lay_ok(f):
        rr = _rr_of(f)
        lm = int(rr.get("transfer_layover_min", 0) or 0)
        m = f.get("layoverM")
        return lm <= 0 or (isinstance(m, int) and m >= lm)

    oks = [f for f in flights if f.get("transCity") and not f.get("_xphan")
           and Alerter._arrival_ok(f, _am_of(f)) and _lay_ok(f)]

    def _best_brief(f, pool=None):
        if not f:
            return None
        rr = _rr_of(f) or {}
        label = (f"{rr.get('from_name', '')}→{rr.get('to_name', '')}"
                 if rr and len(routes) > 1 else "")
        dshort = (f.get("depDate") or "")[5:].replace("-", "/")
        if label and len(dshort) == 5:
            label += f" {dshort}"
        # 阈值随航班所属航线：全局最低价配 routes[0] 的线 = 跨航线虚报达标
        th_v = float(rr.get("alert_transfer" if f.get("transCity")
                            else "alert_direct", 0) or 0)
        # 同价多渠道跳转优先去哪儿/携程（与推送链接同规则）；view_plat
        # 与链接同源下发（tooltip「去X查看」与落点一致，副行仍显原渠道）
        view_plat = Alerter._pref_platform(f, pool or [f])
        view = _view_url(rr, f.get("depDate", ""), view_plat)
        return {"price": f["price"], "name": f.get("name", ""),
                "depTime": f.get("depTime", ""), "arrTime": f.get("arrTime", ""),
                "trans": f.get("transCity", ""),
                "cross": f.get("crossDayDesc", ""),
                "bag": f.get("transferBaggage") == "direct",
                "stop": bool(f.get("stopover")),
                "stopCity": (f.get("stopCity") or "").strip(),
                "stopTimeT": (f.get("stopTimeT") or "").strip(),
                "date": f.get("depDate", ""),
                "plat": f.get("_platform", ""),
                "view_plat": view_plat,
                # 真实达标语义（与明细 qual 同源）：行情最低班未必能出手
                # （非直挂/衔接不足时 qual=False，KPI 卡不亮绿）
                "qual": _qual_of(f, bool(f.get("transCity")),
                                 round(float(f["price"]))),
                "stale": round(f["_stale_h"], 1) if f.get("_stale_h") else 0,
                "route": label, "view": view, "th": th_v,
                "tam": (rr.get("transfer_arrival_max", "02:00") or "02:00")}

    # 多日期航线概览按日期分看（用户原话「我想看 10-5 和 10-6 的」）：
    # 全池 min 只会露出一个日期的行情，另一日期不可见
    _dates_all = sorted({d for _r in routes for d in (_r.get("dates") or [])})
    def _best_by_date(pool):
        out = {}
        for d in _dates_all:
            c = [f for f in pool if (f.get("depDate") or "") == d]
            if c:
                best = min(c, key=lambda f: f["price"])
                out[d] = _best_brief(best, pool=c)
        return out

    hist = _rounds(db, route.get("from", ""), route.get("to", ""),
                   (route.get("dates") or [""])[0], am,
                   layover_min=int(route.get("transfer_layover_min", 0) or 0),
                   dep_win=_dep_win_of(route),
                   th_d=th_d, th_t=th_t, rc=route)

    def _pts(hist, key, th):
        """走势点 [时刻, 价, 档]：档=2 真达标（旗标，与明细🔥/推送🎯同口径）、
        1 行情破线但未达标、0 其余。此前组装时把 _rounds 的达标旗标丢弃，
        前端退化成「裸价≤线」画达标环——飞猪税前价/非直挂中转在图上虚画
        达标，与列表含义不一致（v1.5.33 曲线口径收口）。"""
        out = []
        for row in hist:
            v = row[key]
            if not v:
                continue
            q = row[key + 2] if len(row) >= key + 3 else None
            flag = 2 if q else (1 if (th and v <= th) else 0)
            out.append([row[0].strftime("%m-%d %H:%M"), v, flag])
        return out

    h_d = _pts(hist, 1, th_d)
    h_t = _pts(hist, 2, th_t)
    # 多航线走势：每 (航线,日期) 一条序列，前端图上切着看（原来只画第一条）
    routes_arr, seen_rd = [], set()
    for r in routes:
        am_r = r.get("transfer_arrival_max", "02:00") or "02:00"
        for d0 in r.get("dates") or [""]:
            if (r["from"], r["to"], d0) in seen_rd:
                continue
            seen_rd.add((r["from"], r["to"], d0))
            try:
                hist_r = _rounds(db, r["from"], r["to"], d0, am_r,
                                 layover_min=int(r.get("transfer_layover_min", 0) or 0),
                                 dep_win=_dep_win_of(r),
                                 th_d=float(r.get("alert_direct", 0) or 0),
                                 th_t=float(r.get("alert_transfer", 0) or 0),
                                 rc=r)
            except Exception:
                hist_r = []
            rd = _pts(hist_r, 1, float(r.get("alert_direct", 0) or 0))
            rt_ = _pts(hist_r, 2, float(r.get("alert_transfer", 0) or 0))
            # 7 天序列（范围切换）+ 14 天价格日历（热力卡）
            try:
                hist7 = _rounds(db, r["from"], r["to"], d0, am_r, hours=168,
                                layover_min=int(r.get("transfer_layover_min", 0) or 0),
                                dep_win=_dep_win_of(r),
                                th_d=float(r.get("alert_direct", 0) or 0),
                                th_t=float(r.get("alert_transfer", 0) or 0),
                                rc=r)
            except Exception:
                hist7 = []
            r7d = _pts(hist7, 1, float(r.get("alert_direct", 0) or 0))
            r7t = _pts(hist7, 2, float(r.get("alert_transfer", 0) or 0))
            try:
                cal = _daily_minima(db, r["from"], r["to"], d0, am_r, days=14,
                                    layover_min=int(r.get("transfer_layover_min", 0) or 0),
                                    dep_win=_dep_win_of(r),
                                    th_d=float(r.get("alert_direct", 0) or 0))
            except Exception:
                cal = []
            short = d0[5:].replace("-", "/") if len(d0) >= 10 else ""
            routes_arr.append({
                "label": f"{r['from_name']}→{r['to_name']}"
                         + (f" {short}" if short else ""),
                "th": {"direct": float(r.get("alert_direct", 0) or 0),
                       "transfer": float(r.get("alert_transfer", 0) or 0)},
                "history": {"direct": rd, "transfer": rt_},
                "history7": {"direct": r7d, "transfer": r7t},
                "cal": cal,
            })
    # 渠道数据新鲜度（每平台最新一条距今年小时；无=该渠道无任何数据）
    plat_age = {}
    try:
        conn = sqlite3.connect(db)
        for p, ts in conn.execute(
                "SELECT platform, MAX(fetched_at) FROM flight_prices "
                "GROUP BY platform"):
            try:
                t = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
                plat_age[Alerter.PLATFORM_CN.get(p, p)] = round(
                    (datetime.now() - t).total_seconds() / 3600, 1)
            except Exception:
                pass
        conn.close()
    except Exception:
        pass
    bd_brief = _best_brief(min(directs, key=lambda f: f["price"])
                           if directs else None, pool=directs)
    xt_brief = _best_brief(min(oks, key=lambda f: f["price"])
                           if oks else None, pool=oks)

    def _delta_vs_prev(brief, key):
        """较上轮涨跌：取最优航班所属航线的走势序列，倒数两点之差。
        序列末点即当前轮，倒数第二点为上轮（与推送的「较上轮」同源语义）。"""
        if not brief:
            return None
        ser = None
        if brief.get("route"):
            ser = next((r["history"][key] for r in routes_arr
                        if r["label"] == brief["route"]), None)
        if ser is None and routes_arr:
            ser = routes_arr[0]["history"][key]
        if ser and len(ser) >= 2:
            try:
                return round(float(ser[-1][1]) - float(ser[-2][1]))
            except Exception:
                pass
        return None

    return {
        "name": u.get("name", ""),
        "routesTxt": "、".join(
            f"{r['from_name']}→{r['to_name']}"
            for r in routes[:3]),
        "th": {"direct": th_d, "transfer": th_t},
        "best": {
            "direct": bd_brief,
            "transfer": xt_brief,
        },
        "best_by_date": {
            "dates": _dates_all,
            "direct": _best_by_date(directs),
            "transfer": _best_by_date(oks),
        },
        "delta": {"direct": _delta_vs_prev(bd_brief, "direct"),
                  "transfer": _delta_vs_prev(xt_brief, "transfer")},
        "minsTxt": " ｜ ".join(f"{Alerter.PLATFORM_CN.get(k, k)} ￥{v:.0f}"
                              for k, v in sorted(plat_min.items(), key=lambda kv: kv[1])),
        "minsArr": [[Alerter.PLATFORM_CN.get(k, k), round(v)]
                    for k, v in sorted(plat_min.items(), key=lambda kv: kv[1])],
        "flights": sorted(out, key=lambda x: x["price"]),
        "history": {"direct": h_d, "transfer": h_t},
        "routesArr": routes_arr,
        "platAge": plat_age,
        # 达标判定以"每行各自航线阈值"为准（与推送语义一致），
        # 不再拿全局最低价配 routes[0] 的线（跨航线虚报）。
        # 补位 stale 行不参与（与推送链「达标只认当轮实时数据」同口径，
        # alerter fresh_d/fresh_t 同式）——否则渠道限流时控制台 pill 🚨
        # 而钉钉不推，同问题两条链路结论相反
        "hit": any(f["qual"] and not f["stale"] for f in out),
    }


_STATE_CACHE = {"sig": None, "payload": None, "body": None,
                "etag": None, "gz": None}
_STATE_LOCK = threading.Lock()
_STATE_BUILDING = {"on": False}


def _state_signature():
    """当前 /api/state 缓存签名；DB 不可读时返回 None（禁用缓存路径）。"""
    st = _State
    db = _anchored((st.cfg.get("output") or {}).get("db_path"),
                   "data/prices.db")
    try:
        sst = os.stat(db)
        users = st.users or []
        return (db, sst.st_mtime_ns, sst.st_size,
                hash(json.dumps(users, default=str, ensure_ascii=False)),
                st.version)
    except OSError:
        return None


def _build_state(sig):
    """全量重建并写入缓存（payload/body/etag/gz 同批落位，永不出现半新半旧）。"""
    st = _State
    users = st.users or [{"name": "default", "routes": st.cfg.get("routes") or []}]
    states = [_user_state(u) for u in users if u.get("routes")]
    # 更新时间取 DB 最新一条
    import sqlite3 as sq
    db = _anchored((st.cfg.get("output") or {}).get("db_path"),
                   "data/prices.db")
    updated = ""
    try:
        conn = sq.connect(db)
        row = conn.execute(
            "SELECT MAX(fetched_at) FROM flight_prices").fetchone()
        conn.close()
        updated = row[0] if row and row[0] else ""
    except Exception:
        pass
    out = {"updated": updated, "users": states,
           "next_run": _next_run(), "version": st.version,
           "demo": bool(DEMO["on"])}
    _STATE_CACHE["payload"] = out
    body = (json.dumps(out, ensure_ascii=False).encode("utf-8")
            if sig is not None else None)
    _STATE_CACHE["body"] = body
    # ETag 随响应体一并缓存：轮询 304 路径零 hash 开销
    _STATE_CACHE["etag"] = ('"%s"' % hashlib.md5(body).hexdigest()
                            if body else None)
    _STATE_CACHE["gz"] = (gzip.compress(body, 6) if body else None)
    _STATE_CACHE["sig"] = sig


def _state_rebuild_async():
    """后台单飞重建：构建中再多的请求/轮询也只触发一次重建。"""
    if _STATE_BUILDING["on"]:
        return
    _STATE_BUILDING["on"] = True

    def _run():
        try:
            with _STATE_LOCK:
                sig = _state_signature()
                if sig is not None and _STATE_CACHE["sig"] == sig:
                    return  # 别的线程已建好
                _build_state(sig)
        except Exception as e:
            try:
                (_State.logger or print)("[控制台] 状态重建异常: %s" % e)
            except Exception:
                pass
        finally:
            _STATE_BUILDING["on"] = False

    threading.Thread(target=_run, daemon=True, name="state-rebuild").start()


def prewarm_state():
    """缓存预热：启动后/每轮扫描落库后后台调一次，用户打开控制台永远
    命中热缓存（全历史重算 11~14s 不再落在用户请求里）。"""
    _state_rebuild_async()


def _latest_state():
    """全量状态；按 (DB 文件, mtime_ns, size, 用户配置摘要, 版本) 签名缓存。

    控制台每 10s 轮询本端点——轮间 DB 不变时此前每次都全量重算
    （extra JSON 逐条解析 + 每航线×日期 走势/日历多查询）。配置摘要取
    users 的 JSON 哈希（Route 对象经 default=str 进 repr，阈值改动即换签），
    不用对象 id（CPython id 复用会让热重载后撞上旧签名返回脏缓存）。

    签名失效时分两路：有旧 payload → 立即回陈旧值 + 后台单飞重建
    （stale-while-revalidate，用户零等待，下一个轮询拿到新值）；进程后
    首建（无旧值可回）→ 加锁单飞同步构建，并发的首个请求合流等待。"""
    sig = _state_signature()
    if sig is not None and _STATE_CACHE["sig"] == sig:
        return _STATE_CACHE["payload"]
    if _STATE_CACHE["payload"] is not None:
        _state_rebuild_async()
        return _STATE_CACHE["payload"]
    with _STATE_LOCK:
        if sig is not None and _STATE_CACHE["sig"] == sig:
            return _STATE_CACHE["payload"]
        _build_state(sig)
        return _STATE_CACHE["payload"]


def _latest_state_body() -> bytes:
    """/api/state 响应体：签名命中时连 json.dumps 都省掉（370KB 级载荷
    每次 dumps 要十几毫秒，轮询路径零序列化）。"""
    _latest_state()
    body = _STATE_CACHE["body"]
    if body is None:
        body = json.dumps(_STATE_CACHE["payload"],
                          ensure_ascii=False).encode("utf-8")
    return body


def _preview_payload(user_idx: int) -> dict:
    """钉钉推送预览：从 DB 最新一轮还原 (route, sections)，
    调 _digest_payload 纯构建（不发送/不拨号/不传图床）。"""
    import types
    from core.models import FlightPrice, Route
    st = _State
    users = st.users or []
    if not users:
        return {"ok": False, "err": "尚未配置用户"}
    user_idx = max(0, min(int(user_idx or 0), len(users) - 1))
    u = users[user_idx]
    db = _anchored((st.cfg.get("output") or {}).get("db_path"),
                   "data/prices.db")
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT platform, from_city, to_city, depart_date, price, extra, "
        "fetched_at FROM flight_prices WHERE extra != '' AND fetched_at >= "
        "datetime('now', 'localtime', '-40 minutes') "
        "ORDER BY id DESC").fetchall()
    conn.close()
    rows = _cluster_round_rows(rows)
    if not rows:
        return {"ok": False, "err": "暂无本轮数据，先「▶ 立即抓取」跑一轮"}
    by_key = {}
    for r in rows:
        by_key.setdefault(
            (r["from_city"], r["to_city"], r["depart_date"]), []).append(r)
    a = Alerter(st.logger, notifier=None,
                storage=types.SimpleNamespace(db_path=db), digest=True,
                at_mobile=str(((u.get("notifier") or {}).get("dingtalk")
                               or {}).get("at_mobile", "")),
                user=u.get("name", ""),
                platforms=u.get("platforms") or None)
    built = []
    for r0 in (u.get("routes") or []):
        rv = _route_view(r0)
        if not rv.get("from"):
            continue
        route = Route(
            from_code=rv["from"], from_name=rv["from_name"],
            to_code=rv["to"], to_name=rv["to_name"], dates=rv["dates"],
            alert_direct=rv["alert_direct"],
            alert_transfer=rv["alert_transfer"],
            transfer_arrival_max=rv["transfer_arrival_max"],
            transfer_layover_min=rv["transfer_layover_min"],
            transfer_baggage=rv["transfer_baggage"],
            dep_time_min=rv["dep_time_min"], dep_time_max=rv["dep_time_max"])
        prices = []
        for d in rv["dates"]:
            for row in by_key.get((rv["from"], rv["to"], d), []):
                prices.append(FlightPrice(
                    platform=row["platform"], from_city=row["from_city"],
                    to_city=row["to_city"], depart_date=row["depart_date"],
                    price=row["price"], extra=row["extra"],
                    fetched_at=row["fetched_at"]))
        if prices:
            secs = a._build_sections(route, prices)
            if secs:
                built.append((route, secs))
    if not built:
        return {"ok": False, "err": "本轮数据为空"}
    # with_charts=False：预览无本轮走势图 URL，整段跳过走势块——
    # 缺图分支曾恒出「⚠️ 走势图上传失败」假警告误导用户
    p = a._digest_payload(built, fresh=True, with_tables=False,
                          with_charts=False)
    return {"ok": True, "title": p["title"], "desp": p["desp"],
            "hits": len(p["hits"]), "user": u.get("name", "")}


_HEALTH_CACHE = {"sig": None, "payload": None}


def _health_state(hours: int = 24) -> dict:
    """渠道健康时间线：解析 monitor.log（尾部 2MB 封顶，防长日志拖慢）。

    按日志 (路径, mtime_ns, size) 签名缓存——控制台每 10s 轮询，
    轮间日志不变时不再重复解析 2MB 日志。"""
    from core.health import parse_health
    logp = _anchored(((_State.cfg or {}).get("output") or {}).get(
        "log_path"), "logs/monitor.log")
    sig = None
    try:
        hst = os.stat(logp)
        sig = (logp, hst.st_mtime_ns, hst.st_size, hours)
    except OSError:
        pass
    if sig is not None and _HEALTH_CACHE["sig"] == sig:
        return _HEALTH_CACHE["payload"]
    out = parse_health(_read_log_tail(), hours=hours)
    _HEALTH_CACHE["sig"], _HEALTH_CACHE["payload"] = sig, out
    return out


def _read_log_tail(max_bytes: int = 2_000_000) -> str:
    import os
    logp = _anchored(((_State.cfg or {}).get("output") or {}).get(
        "log_path"), "logs/monitor.log")
    try:
        size = os.path.getsize(logp)
        with open(logp, "rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
            return f.read().decode("utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def _log_tail(plat: str, ts: str) -> dict:
    """某轮某渠道的日志原文：轮开始时间前 2 分钟至后 10 分钟窗口内，
    带该渠道标签的行 + 轮边界行（供健康格子点击查看）。"""
    import re
    from datetime import datetime as _dt, timedelta as _td
    if not re.match(r"^[\w-]+$", plat or ""):
        return {"ok": False, "err": "bad plat"}
    try:
        t0 = _dt.strptime(ts, "%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return {"ok": False, "err": "bad ts"}
    lo, hi = t0 - _td(minutes=2), t0 + _td(minutes=10)
    tag = "[" + plat + "]"
    line_re = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) ")
    lines = []
    for ln in _read_log_tail().splitlines():
        m = line_re.match(ln)
        if not m:
            continue
        try:
            t = _dt.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if lo <= t <= hi and (tag in ln or "=====" in ln):
            lines.append(ln)
    return {"ok": True, "lines": lines[-60:], "plat": plat, "ts": ts}


class _Srv(ThreadingHTTPServer):
    """禁用地址复用：Windows 上 SO_REUSEADDR 允许同端口双绑静默影身
    （僵尸控制台持端口、新实例起在同端口却收不到连接——LESSONS 十.4
    双实例坑的放大器）。绑定失败应当场报错，而不是假装启动成功。"""
    allow_reuse_address = False
    daemon_threads = True


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            # no-cache=每次导航必回源校验：升级重启后浏览器绝不拿旧页 JS
            # （页面 本地秒回，无带宽顾虑；没有它启发式缓存会吐旧版页面）
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/notify":
            self.send_response(302)
            self.send_header("Location", "/notify/latest")
            self.end_headers()
        elif self.path.startswith("/notify/"):
            # Windows 弹窗点击直达：单条达标详情（轻页，非控制台）
            try:
                import json as _j
                import os as _os
                import re as _re2
                nid = _re2.sub(r"[^A-Za-z0-9]", "",
                               self.path[len("/notify/"):].split("?")[0])
                if nid == "latest":
                    # 便捷入口回归语义：latest 走「最新存档」分支（曾按
                    # nid 处理找 latest.json——该文件恒不存在，入口恒死）
                    nid = ""
                data = None
                d = _anchored(None, "data/notify")
                if DEMO["on"]:
                    data = {"nid": "NDEMO",
                            "title": "🚨 达标 上海→乌鲁木齐 09/25",
                            "desp": "#### 🚨 已达标——可出手\n\n"
                                    "> ⏱ 09:00 🎯达标 🟩破线 🟨擦边 无标超线\n\n"
                                    "[**🎯 直飞 ￥1468**](https://flight.qunar.com/site/oneway_list.htm?searchDepartureAirport=%E4%B8%8A%E6%B5%B7&searchArrivalAirport=%E4%B9%8C%E9%B2%81%E6%9C%A8%E9%BD%90&searchDepartureTime=2026-09-25&nextNDays=0&startSearch=true&fromCode=SHA&toCode=URC&from=flight_dom_search)"
                                    "　线￥1600　低￥132\n\n"
                                    "国航CA1295 21:10-02:35(+1天)\n\n"
                                    "> 经济舱 · 经停乌鲁木齐\n\n"
                                    "乌鲁木齐→上海 10/06 · 国航CA1295 21:10-02:35 +1天",
                            "ts": "（演示数据）"}
                elif nid:
                    p = _os.path.join(_ROOT, "data", "notify", nid + ".json")
                    if _os.path.isfile(p):
                        data = _j.load(open(p, encoding="utf-8"))
                else:
                    if _os.path.isdir(d):
                        for f in sorted(_os.listdir(d), reverse=True):
                            if f.endswith(".json"):
                                data = _j.load(open(_os.path.join(d, f),
                                                    encoding="utf-8"))
                                break
                if data is None:
                    data = {"title": "通知不存在或已过期",
                            "desp": "详情仅保留最近 20 条，请从最新一条系统弹窗进入。",
                            "ts": ""}
                payload = _j.dumps(data, ensure_ascii=False).replace(
                    "</", "<\\/")
                body = NOTIFY_PAGE.replace(
                    "__PAYLOAD__", payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/state":
            try:
                body = _latest_state_body()
                etag = _STATE_CACHE.get("etag") or ""
                # 轮询 304：响应未变时浏览器连 370KB 的下载都省掉
                if (etag and etag == self.headers.get("If-None-Match", "").strip()):
                    self.send_response(304)
                    self.send_header("ETag", etag)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("ETag", etag)
                # gzip：462KB 级载荷压到 ~60KB（缓存内随 body 一次性压缩）
                if "gzip" in (self.headers.get("Accept-Encoding") or "") \
                        and _STATE_CACHE.get("gz"):
                    body = _STATE_CACHE["gz"]
                    self.send_header("Content-Encoding", "gzip")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as e:
                self._json({"err": str(e)}, 500)
        elif self.path == "/api/health":
            try:
                if DEMO["on"]:
                    from core.demo import demo_health
                    self._json(demo_health())
                else:
                    self._json(_health_state())
            except Exception as e:
                self._json({"err": str(e)}, 500)
        elif self.path == "/api/pulse":
            try:
                if DEMO["on"]:
                    from core.demo import demo_pulse
                    self._json(demo_pulse())
                else:
                    from core.pulse import PULSE
                    self._json(PULSE.view())
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/pushlog":
            try:
                if DEMO["on"]:
                    # 样例与现役推送格式同步（#### 标题/四档图例「无标超线」/
                    # 🎯-低-差口径）；旧 🟦超线 图例样例曾误导预览（v1.5.41）
                    self._json({"ok": True, "items": [
                        {"ts": "2026-09-10 09:00:02", "ok": True,
                         "title": "🚨 达标！乌→上 10/04 直飞￥1580｜乌→上 10/04",
                         "desp": "#### 🚨 已达标——可出手\n\n"
                                 "> ⏱ 09:00 🎯达标 🟩破线 🟨擦边 无标超线\n\n"
                                 "[**🎯 直飞 ￥1580**](https://example.com)"
                                 "　线￥1600　低￥20\n\n"
                                 "国航CA1295 21:10-02:35(+1天)\n\n"
                                 "> 经济舱 · 行李直挂\n\n"
                                 "> 💡 直飞已达标（低于线 ￥20），建议出手"},
                        {"ts": "2026-09-10 08:45:03", "ok": True,
                         "title": "❌ 全部未达标｜最近 上→乌 09/25 直飞差￥130｜上→乌 09/25",
                         "desp": "#### ❌ 1 条航线 2 个日期全部未达标\n\n"
                                 "🟦⬜⬜⬜⬜\n\n"},   # 超线仪表条样例：为 🟦 提供解码场景
                        {"ts": "2026-09-10 08:30:00", "ok": False,
                         "title": "❌ 全部未达标｜上→乌 09/25",
                         "desp": "#### ❌ 1 条航线全部未达标\n\n"},
                    ]})
                    return
                import os as _os
                items = []
                p = _anchored(None, "logs/push_history.jsonl")
                try:
                    size = _os.path.getsize(p)
                    with open(p, "rb") as f:
                        if size > 262144:
                            f.seek(size - 262144)
                        lines = f.read().decode(
                            "utf-8", errors="replace").splitlines()
                    if size > 262144 and len(lines) > 1:
                        lines = lines[1:]   # 首行可能被截半
                    for ln in reversed(lines):
                        try:
                            items.append(json.loads(ln))
                        except Exception:
                            continue
                        if len(items) >= 40:
                            break
                except FileNotFoundError:
                    pass
                self._json({"ok": True, "items": items})
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/login-state":
            try:
                if DEMO["on"]:
                    self._json({"ok": True, "demo": True, "plats": {
                        p: {"saved": p in ("ctrip", "tuniu"), "active": False}
                        for p in _LOGIN_PLATS}})
                else:
                    self._json(_login_state_view())
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path.startswith("/api/logtail"):
            try:
                from urllib.parse import urlparse, parse_qs
                q = parse_qs(urlparse(self.path).query)
                if DEMO["on"]:
                    self._json({"ok": True, "lines": [
                        "2026-09-09 14:00:00 [INFO] ticket-monitor: ===== 开始一轮扫描（1 用户 / 3 航线） =====",
                        "2026-09-09 14:00:17 [INFO] ticket-monitor: [qunar] 2026-09-25 最低价 ￥1850（航班明细 70 条：直飞 44 / 中转 26）",
                        "2026-09-09 14:00:45 [INFO] ticket-monitor: ===== 本轮扫描结束 =====",
                    ], "plat": q.get("plat", [""])[0],
                        "ts": q.get("ts", [""])[0], "demo": True})
                else:
                    self._json(_log_tail(q.get("plat", [""])[0],
                                         q.get("ts", [""])[0]))
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/config":
            try:
                if DEMO["on"]:
                    # 演示模式不回读真实 config.yaml（webhook/secret 不落页面）
                    self._json({
                        "users": [{
                            "name": "演示用户",
                            "routes": [{"from": "SHA", "from_name": "上海",
                                        "to": "URC", "to_name": "乌鲁木齐",
                                        "dates": ["2026-09-25"],
                                        "alert_direct": 1900,
                                        "alert_transfer": 1700}],
                            "notifier": {"dingtalk": {"enabled": False},
                                         "win_toast": True},
                            "platforms": ["qunar", "ctrip", "fliggy",
                                          "tongcheng", "tuniu"],
                        }],
                        "city": {}, "demo": True,
                        "globals": {"interval_minutes": 15,
                                    "jitter_minutes": 5, "port": 8765,
                                    "run_on_start": True,
                                    "headless": True,
                                    "timeout_seconds": 45,
                                    "delay_min": 5, "delay_max": 15,
                                    "user_agent": "",
                                    "debug": False,
                                    "db_path": "data/prices.db",
                                    "log_path": "logs/monitor.log",
                                    "user_data_dir": "user_data"}})
                    return
                import yaml as _y
                cfg = _y.safe_load(open(_State.config_path, encoding="utf-8"))
                # 物化生效值：win_toast 缺省即开启——补写显式布尔，让配置页
                # 勾选态与 config.yaml 都反映真实状态（所见即所存）
                for u0 in (cfg.get("users") or []):
                    n0 = u0.get("notifier") or {}
                    n0["win_toast"] = bool(n0.get("win_toast", True))
                    u0["notifier"] = n0
                from wizard import CITY
                self._json({"users": cfg.get("users") or [],
                            "city": CITY,
                            "globals": {
                                "interval_minutes": int(
                                    (cfg.get("schedule") or {}).get(
                                        "interval_minutes", 30) or 30),
                                "jitter_minutes": int(
                                    (cfg.get("schedule") or {}).get(
                                        "jitter_minutes", 0) or 0),
                                "run_on_start": bool(
                                    (cfg.get("schedule") or {}).get(
                                        "run_on_start", True)),
                                "port": int((cfg.get("web") or {}).get(
                                    "port", 8765) or 8765),
                                "base_url": str(
                                    (cfg.get("web") or {}).get(
                                        "base_url", "") or ""),
                                "host": str(
                                    (cfg.get("web") or {}).get(
                                        "host", "127.0.0.1") or "127.0.0.1"),
                                "headless": bool((cfg.get("crawler") or {}).get(
                                    "headless", True)),
                                "timeout_seconds": int(
                                    (cfg.get("crawler") or {}).get(
                                        "timeout_seconds", 45) or 45),
                                "delay_min": int(
                                    (cfg.get("crawler") or {}).get(
                                        "delay_min", 5) or 5),
                                "delay_max": int(
                                    (cfg.get("crawler") or {}).get(
                                        "delay_max", 15) or 15),
                                "user_agent": str(
                                    (cfg.get("crawler") or {}).get(
                                        "user_agent", "") or ""),
                                "debug": bool((cfg.get("crawler") or {}).get(
                                    "debug", False)),
                                # 启动级：只读展示（改 config.yaml 后重启生效）
                                "db_path": str(
                                    (cfg.get("output") or {}).get(
                                        "db_path", "data/prices.db")
                                    or "data/prices.db"),
                                "log_path": str(
                                    (cfg.get("output") or {}).get(
                                        "log_path", "logs/monitor.log")
                                    or "logs/monitor.log"),
                                "user_data_dir": str(
                                    (cfg.get("crawler") or {}).get(
                                        "user_data_dir", "user_data")
                                    or "user_data")}})
            except Exception as e:
                self._json({"err": str(e)}, 500)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        st = _State
        if DEMO["on"] and self.path != "/api/preview":
            self._json({"ok": False, "demo": True,
                        "err": "演示模式只读——下载源码或 zip 即可真跑"}, 403)
            return
        if self.path == "/api/config":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                import yaml as _y
                cfg = _y.safe_load(open(st.config_path, encoding="utf-8")) or {}
                cfg["users"] = body.get("users") or []
                glb = body.get("globals") or {}
                if glb.get("interval_minutes"):
                    cfg.setdefault("schedule", {})["interval_minutes"] = \
                        max(5, int(glb["interval_minutes"]))
                if glb.get("jitter_minutes") is not None:
                    cfg.setdefault("schedule", {})["jitter_minutes"] = \
                        max(0, int(glb["jitter_minutes"]))
                if glb.get("port"):
                    cfg.setdefault("web", {})["port"] = \
                        max(1024, int(glb["port"]))
                if glb.get("base_url") is not None:
                    cfg.setdefault("web", {})["base_url"] = \
                        str(glb["base_url"]).strip()[:300]
                if glb.get("host") is not None and str(glb["host"]).strip():
                    cfg.setdefault("web", {})["host"] = \
                        str(glb["host"]).strip()[:64]
                if glb.get("headless") is not None:
                    cfg.setdefault("crawler", {})["headless"] = \
                        bool(glb["headless"])
                if glb.get("run_on_start") is not None:
                    cfg.setdefault("schedule", {})["run_on_start"] = \
                        bool(glb["run_on_start"])
                # 采集参数：rt["cfg"] 单一事实源，保存热生效（v2.1.0 起）
                _crw = cfg.setdefault("crawler", {})
                if glb.get("timeout_seconds"):
                    _crw["timeout_seconds"] = min(
                        600, max(10, int(glb["timeout_seconds"])))
                if glb.get("delay_min") is not None:
                    _crw["delay_min"] = max(0, int(glb["delay_min"]))
                if glb.get("delay_max") is not None:
                    _crw["delay_max"] = max(0, int(glb["delay_max"]))
                if glb.get("user_agent") is not None:
                    _crw["user_agent"] = str(glb["user_agent"]).strip()[:600]
                if glb.get("debug") is not None:
                    _crw["debug"] = bool(glb["debug"])
                # win_toast 缺省即开启——保存时落显式布尔进 config.yaml
                for u0 in (cfg["users"] or []):
                    n0 = u0.get("notifier") or {}
                    n0["win_toast"] = bool(n0.get("win_toast", True))
                    u0["notifier"] = n0
                with open(st.config_path, "w", encoding="utf-8") as f:
                    _y.safe_dump(cfg, f, allow_unicode=True,
                                 sort_keys=False, width=100)
                n = st.reload_cb() if st.reload_cb else 0
                st.logger.info("[web配置] 已保存并热重载：%d 用户", n)
                self._json({"ok": True, "users": n})
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/test-push":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                from core.notifier import DingTalkNotifier
                n = DingTalkNotifier(
                    webhook=body.get("webhook", ""),
                    logger=st.logger,
                    secret=body.get("secret", ""))
                now = __import__('datetime').datetime.now().strftime('%H:%M:%S')
                # 带版本号：群里能直接核对当前运行版本（僵尸实例鉴别）
                ver = str(getattr(__import__("__main__"),
                                 "__version__", "") or "")
                extra = (f"\n\n当前运行版本 v{ver} ｜ ⏰ {now}" if ver
                         else f"\n\n⏰ {now}")
                ok = n.send(
                    "✅ 机票监控｜测试推送",
                    "# ✅ 测试推送成功\n\n该钉钉机器人配置可用，"
                    "监控警报将发送到此群。" + extra)
                self._json({"ok": bool(ok)})
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/test-toast":
            # Windows 本机弹窗通路测试（达标强提醒链路，点击可直达详情）
            try:
                from core.notifier import WindowsToastNotifier
                now = __import__('datetime').datetime.now().strftime('%H:%M:%S')
                ver = str(getattr(__import__("__main__"),
                                 "__version__", "") or "")
                host = self.headers.get("Host") or "127.0.0.1:8765"
                n = WindowsToastNotifier(st.logger)
                ok = n.send(
                    "🔔 弹窗测试——通路正常",
                    ("版本 v%s ｜ ⏰ %s\n收到即代表达标弹窗可用，"
                     "点击本弹窗验证直达" % (ver or "?", now)),
                    launch="http://%s/" % host)
                self._json({"ok": bool(ok),
                            "err": "" if ok else "本机不支持（需 Windows）"})
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/test-ntfy":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                topic = (body.get("topic") or "").strip()
                if not topic:
                    self._json({"ok": False, "err": "请先填写主题"})
                    return
                from core.notifier import NtfyNotifier
                now = __import__('datetime').datetime.now().strftime('%H:%M:%S')
                ver = str(getattr(__import__("__main__"),
                                 "__version__", "") or "")
                n = NtfyNotifier(topic=topic, logger=st.logger,
                                 priority=int(body.get("priority") or 5))
                ok = n.send("🔔 ntfy 测试——通路正常",
                            ("版本 v%s ｜ ⏰ %s\n收到即代表达标强提醒链路可用"
                             % (ver or "?", now)))
                self._json({"ok": bool(ok)})
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/login":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                self._json(_start_login(str(body.get("platform", ""))))
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/login-finish":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                self._json(_finish_login(str(body.get("platform", ""))))
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/run":
            if st.job is None:
                self._json({"ok": False, "err": "job 未挂接"}, 500)
                return
            if not st.lock.acquire(blocking=False):
                self._json({"ok": False, "err": "一轮扫描正在进行中"}, 409)
                return
            try:
                st.job()
                self._json({"ok": True})
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
            finally:
                st.lock.release()
        elif self.path == "/api/push":
            if st.report_push is None:
                self._json({"ok": False, "err": "report 未挂接"}, 500)
                return
            try:
                ok = st.report_push()
                self._json({"ok": bool(ok)})
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/preview":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                self._json(_preview_payload(int(body.get("user", 0) or 0)))
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        else:
            self.send_response(404)
            self.end_headers()


def start_web(cfg, job, report_push, logger=None, users=None,
              reload_cb=None, config_path="config.yaml", version=""):
    """在守护线程里启动本地控制台；失败只告警不中断监控。"""
    _State.cfg = cfg
    _State.users = users
    _State.job = job
    _State.report_push = report_push
    _State.reload_cb = reload_cb
    _State.config_path = config_path
    _State.version = version
    if logger:
        _State.logger = logger
    port = int((cfg.get("web") or {}).get("port", 8765))
    # 监听地址可配（web.host，默认 127.0.0.1）：手机端钉钉「完整详情」
    # 依赖局域网可达——此前服务只绑回环，base_url 配了也连不上
    host = (str((cfg.get("web") or {}).get("host", "127.0.0.1")
                or "127.0.0.1").strip() or "127.0.0.1")
    try:
        srv = _Srv((host, port), _Handler)
        _State.srv = srv
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        _State.logger.info("[控制台] http://%s:%d （随监控常驻）",
                           host if host != "0.0.0.0" else "0.0.0.0(全网卡)",
                           port)
        # 启动预热：后台先把 /api/state 全量建好，首个打开控制台的请求
        # 直接命中热缓存（全历史重算 11~14s 不落在用户首屏）
        def _warm():
            time.sleep(1.5)
            _state_rebuild_async()
        threading.Thread(target=_warm, daemon=True, name="state-warm").start()
        return srv
    except Exception as e:
        _State.logger.warning("[控制台] 启动失败: %s", e)
        return None


def rebind_web(port: int) -> bool:
    """控制台原地换绑端口：配置页改端口保存即生效，无需重启进程。

    旧 server 异步关闭（让当前响应先送回浏览器），随后新端口起监听。"""
    old = getattr(_State, "srv", None)

    def _do():
        try:
            if old:
                old.shutdown()
                old.server_close()
        except Exception:
            pass
        try:
            host = (str((_State.cfg.get("web") or {}).get(
                "host", "127.0.0.1") or "127.0.0.1").strip()
                or "127.0.0.1")
            srv = _Srv((host, int(port)), _Handler)
            _State.srv = srv
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            _State.logger.info("[控制台] 已热切换至 http://127.0.0.1:%d",
                               int(port))
        except Exception as e:
            _State.logger.warning("[控制台] 端口 %s 切换失败: %s", port, e)

    threading.Timer(0.4, _do).start()
    return True


def _demo_main():
    """`python webui.py --demo`：零配置演示控制台（开源访客一键体验）。

    生成确定性合成库（temp 目录，退出即弃），渲染链路与真机完全一致。"""
    import argparse
    import os
    import tempfile
    ap = argparse.ArgumentParser(description="机票监控控制台 · 演示模式")
    ap.add_argument("--demo", action="store_true", help="启动演示数据控制台")
    ap.add_argument("--port", type=int, default=8765,
                    help="控制台端口（演示模式配合截图脚本用 8799）")
    args = ap.parse_args()
    if not args.demo:
        print("控制台由 main.py 随监控启动；零配置体验请加 --demo")
        return
    from core.demo import build_demo_db, demo_cfg, demo_routes
    from core.models import Route
    db = os.path.join(tempfile.gettempdir(), "ticket_demo_prices.db")
    build_demo_db(db)
    DEMO["on"] = True
    _State.cfg = demo_cfg(db, port=args.port)
    _State.users = [{
        "name": "演示用户",
        "routes": [Route(
            from_code=r["from"], from_name=r["from_name"],
            to_code=r["to"], to_name=r["to_name"], dates=r["dates"],
            alert_direct=r["alert_direct"],
            alert_transfer=r["alert_transfer"],
            transfer_arrival_max=r["transfer_arrival_max"],
            # 衔接下限/行李直挂曾未映射——演示静默丢失这两个配置维度
            transfer_layover_min=r.get("transfer_layover_min", 0),
            transfer_baggage=r.get("transfer_baggage", ""),
            dep_time_min=r["dep_time_min"], dep_time_max=r["dep_time_max"])
            for r in demo_routes()],
        "platforms": ["qunar", "ctrip", "fliggy", "tongcheng", "tuniu"],
        "notifier": {"dingtalk": {"at_mobile": "138****1234"}},
        "schedule": {"interval_minutes": 15},
    }]
    _State.version = "demo"
    srv = _Srv(("127.0.0.1", args.port), _Handler)
    print(f"🎪 演示控制台: http://127.0.0.1:{args.port}  （数据为合成，Ctrl+C 退出）")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    _demo_main()
