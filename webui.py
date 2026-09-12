# -*- coding: utf-8 -*-
"""伴生本地控制台（多租户版）：纯标准库 HTTP 服务（127.0.0.1），随监控常驻

页面能力：每用户状态卡与仪表 / 多航线可切走势图（canvas 自绘+悬停十字线）/
航班明细表（日期列·筛选·排序·同班跨渠道比价展开）/ 下轮倒计时 /
智能刷新（响应不变不重渲染，页面隐藏暂停）/ 一键立即抓取、一键推送走势报告。
"""
import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from core.alerter import Alerter
from report import _rounds, recent_platform_flights, _daily_minima

# 演示模式（python webui.py --demo）：/api/* 走合成数据，POST 全部只读拦截
DEMO = {"on": False}


def _dur_min(txt) -> int:
    """'5时25分'/'5小时25分'/'5h25m' → 分钟数；解析不出返回 0。"""
    m = re.match(r"\s*(\d+)\s*(?:小时|[时hH])\s*(?:(\d+)\s*分?m?)?", str(txt or ""))
    if not m:
        return 0
    return int(m.group(1)) * 60 + int(m.group(2) or 0)

PAGE = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="description" content="自托管多渠道机票价格监控：五渠道明细、达标强提醒、配置全热加载">
<meta name="theme-color" content="#1a73e8">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ctext y='0.9em' font-size='90'%3E%E2%9C%88%EF%B8%8F%3C/text%3E%3C/svg%3E">
<title>机票监控台</title>
<style>
 /* ===== V15「签派控制台」设计语言：数字即主角（mono）、hairline 分区、扁平精密仪表 ===== */
 :root{--blue:#0b62d6;--blue2:#3d8af0;--orange:#c96a10;--red:#c22a2e;--green:#0e8345;
       --bg:#eceff4;--card:#ffffff;--tx:#141f2b;--mut:#66788a;--tx2:#3d4e5f;
       --line:#dde3ea;--line2:#cbd4de;--headbg:#eef2f7;--hover:#e8edf3;--rowalt:#f5f8fb;
       --stl:#a07400;--okbg:#e9f4ec;
       --sh1:0 1px 2px rgba(20,31,43,.05);
       --sh2:0 6px 18px -6px rgba(20,31,43,.12);
       --sh3:0 16px 40px -12px rgba(20,31,43,.22);
       --r:14px;--r2:11px;--r3:8px;
       --num:"Cascadia Mono","Consolas","SF Mono","Menlo",monospace;
       --glass:#ffffff}
 *{box-sizing:border-box}
 /* 原生控件（time/checkbox/滚动条）跟随页面主题，不随系统深浅漂移 */
 html{color-scheme:light}
 html[data-theme="dark"]{
  color-scheme:dark;
  --bg:#0a0f16;--card:#101823;--tx:#dbe4ee;--mut:#7f92a6;--tx2:#a9b9ca;
  --line:#1e2a3a;--line2:#2a3a50;--headbg:#141d2a;--hover:#182430;--rowalt:#0f1722;
  --blue:#63a4f8;--orange:#e6922e;--red:#ef5350;--green:#43c072;--stl:#d9b34a;--okbg:#12241a;
  --sh1:0 1px 2px rgba(0,0,0,.35);
  --sh2:0 6px 18px -6px rgba(0,0,0,.5);
  --sh3:0 16px 40px -12px rgba(0,0,0,.65);
  --glass:#101823;
  body{background:var(--bg)}
  canvas{filter:brightness(.97)}
 }
 body{font-family:"Segoe UI Variable Text","Segoe UI","Microsoft YaHei","PingFang SC",sans-serif;
      margin:0;color:var(--tx);background:var(--bg);transition:background .3s}
 .wrap{max-width:1180px;margin:0 auto;padding:0 18px 18px}
 /* header：通栏扁平仪表条（hairline 底边，sticky）。
    scroll-padding 让聚焦/锚点滚动不被 header 盖住；投影让"内容从栏下滑过"有层次 */
 html{scroll-padding-top:72px}
 header{background:var(--card);border-bottom:1px solid var(--line2);color:var(--tx);
        padding:11px 18px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;
        position:sticky;top:0;z-index:50;box-shadow:0 6px 18px rgba(16,24,40,.08);
        margin:0 -18px 4px;
        padding-left:max(18px,calc(50% - 562px));padding-right:max(18px,calc(50% - 562px))}
 header h1{margin:0;font-size:14px;font-weight:700;letter-spacing:1.2px;
           display:flex;align-items:center;gap:10px;text-transform:uppercase}
 .logo{width:30px;height:30px;border-radius:8px;flex:none;
       background:var(--tx);color:var(--card);
       display:inline-flex;align-items:center;justify-content:center;font-size:15px}
 .pill{font-size:13px;font-weight:700;background:var(--headbg);color:var(--tx2);
       padding:6px 14px;border-radius:8px;border:1px solid var(--line);
       display:inline-flex;align-items:center;gap:8px;font-variant-numeric:tabular-nums}
 .pill::before{content:'';width:7px;height:7px;border-radius:50%;background:#93a3b4;flex:none}
 .pill.ok{background:var(--okbg);color:var(--green);border-color:rgba(14,131,69,.35)}
 .pill.ok::before{background:var(--green);animation:pulse 1.8s ease-in-out infinite}
 @keyframes pulse{0%,100%{box-shadow:0 0 0 0 rgba(14,131,69,.45);opacity:1}
                  50%{box-shadow:0 0 0 4px rgba(14,131,69,0);opacity:.55}}
 .muted{color:var(--mut);font-size:12px;font-weight:500}
 /* 分区标签：编号 + 中文 + 英文小签（签派台分区语言） */
 .seclab{display:flex;align-items:baseline;gap:9px;margin:22px 2px 9px;
         border-bottom:1px solid var(--line);padding-bottom:7px}
 .seclab .no{font-family:var(--num);font-size:11px;color:var(--mut);letter-spacing:1px}
 .seclab .zh{font-size:14px;font-weight:700;letter-spacing:.5px}
 .seclab .en{font-size:10px;letter-spacing:2px;color:var(--mut);text-transform:uppercase}
 /* 卡头内联变体：不带尾线（尾线由 ucard 边界承担） */
 .seclab.inline::after{display:none}
 .ucard{background:var(--card);border:1px solid var(--line);border-radius:var(--r);
        padding:15px 18px;margin:0 0 12px;box-shadow:none;transition:border-color .2s}
 .ucard:hover{border-color:var(--line2)}
 .kpi{transition:transform .15s,border-color .2s,background .2s;border:1px solid var(--line);
      border-radius:var(--r2);padding:13px 16px;position:relative;overflow:hidden;background:var(--card)}
 .kpi:hover{transform:translateY(-2px)}
 /* 达标态：okbg 底 + 绿实线包边（签派台的"可出手"灯） */
 .kpi.hit{background:var(--okbg);border-color:rgba(14,131,69,.45);
      box-shadow:0 2px 14px rgba(14,131,69,.12)}
 .kpi.hit::before{content:'';position:absolute;left:0;top:0;bottom:0;width:3px;
      background:linear-gradient(180deg,var(--green),rgba(14,131,69,.25))}
 .kpi .big{font-variant-numeric:tabular-nums;text-shadow:0 1px 0 rgba(255,255,255,.25)}
 button:active{transform:scale(.96)}
 .rngchip:hover{background:var(--hover)}
 .uhead{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px}
 .uname{font-size:15px;font-weight:700;letter-spacing:.3px}
 .uroutes{color:var(--mut);font-size:12px}
 .grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:10px}
 @media(max-width:760px){.grid{grid-template-columns:1fr}}
 .kpi .lab{font-size:11px;color:var(--mut);letter-spacing:.8px}
 .kpi .fb{color:var(--tx2);font-size:12px;margin-top:2px}
 .xrow td{background:rgba(255,208,74,.15);color:var(--stl);font-size:12px;white-space:normal}
 .kpi .num{font-family:var(--num);font-size:31px;font-weight:600;margin:3px 0 1px;
           letter-spacing:-1px;font-variant-numeric:tabular-nums}
 .kpi.d .num{color:var(--blue)}.kpi.t .num{color:var(--orange)}
 .bar{height:6px;border-radius:4px;background:var(--line);overflow:hidden;margin-top:6px}
 .bar i{display:block;height:100%;border-radius:4px;transition:width .6s}
 .kpi.d .bar i{background:var(--blue)}
 .kpi.t .bar i{background:var(--orange)}
 .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:4px}
 button{background:linear-gradient(180deg,#2f83ea,var(--blue));color:#fff;border:none;
        border-radius:9px;padding:9px 17px;font-size:13px;font-weight:600;cursor:pointer;
        transition:.15s;box-shadow:0 1px 3px rgba(26,115,232,.35)}
 button:hover{filter:brightness(1.1);box-shadow:0 3px 10px rgba(26,115,232,.4)}
 button:active{box-shadow:none}
 button.warn{background:var(--card);color:var(--blue);border:1px solid var(--line2);
        box-shadow:var(--sh1);font-weight:600}
 button.warn:hover{background:var(--headbg);filter:none;box-shadow:var(--sh2)}
 canvas{width:100%;height:280px;display:block}
 .legend{display:flex;gap:16px;font-size:12px;color:var(--mut);margin-top:6px;flex-wrap:wrap}
 .legend b{display:inline-block;width:18px;height:4px;border-radius:2px;vertical-align:middle;margin-right:5px}
 .tabs{display:flex;gap:6px;margin:10px 0;align-items:center;flex-wrap:wrap}
 .tabs span{padding:6px 14px;border-radius:9px;cursor:pointer;font-size:12.5px;
   background:var(--headbg);color:var(--mut);border:1px solid var(--line);
   font-weight:600;transition:.15s;user-select:none}
 .tabs span:hover{color:var(--tx2)}
 .tabs span.on{background:var(--blue);color:#fff;border-color:transparent;
   box-shadow:0 2px 8px -2px rgba(26,115,232,.45)}
 .tw{overflow:auto;max-height:430px;border-radius:10px;border:1px solid var(--line)}
 table{border-collapse:collapse;width:100%;font-size:13px;background:var(--card)}
 th{position:sticky;top:0;background:var(--headbg);color:var(--mut);font-weight:600;
    font-size:11px;letter-spacing:.8px;z-index:3}
 th,td{padding:9px 10px;text-align:left;white-space:nowrap;border-bottom:1px solid var(--line)}
 tbody tr{transition:background .12s}
 tbody tr:hover{background:var(--hover)}
 tr.qual td{color:var(--red);font-weight:700}
 .tag{border-radius:20px;padding:3px 10px;font-size:11px;color:#fff;font-weight:600;
   letter-spacing:.5px}
 .pdot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;
   vertical-align:1px;background:var(--mut)}
 .pdot.qunar{background:#1a73e8}.pdot.fliggy{background:#e67e22}
 .pdot.ctrip{background:#2ea44f}.pdot.tongcheng{background:#8250df}
 .pdot.tuniu{background:#d29922}
 .t-d{background:#2f7fe0}.t-t{background:#e07f2a}
 .tag{font-weight:600}
 .price{font-weight:800;font-family:var(--num);letter-spacing:-.3px}
 nav{display:inline-flex;gap:4px;background:var(--card);border:1px solid var(--line);
     border-radius:12px;padding:4px;box-shadow:var(--sh1);margin:14px 0}
 nav span{padding:7px 20px;border-radius:9px;cursor:pointer;font-size:13.5px;
          color:var(--mut);font-weight:600;transition:.15s;user-select:none}
 nav span:hover{color:var(--tx)}
 nav span.on{background:var(--blue);color:#fff;
          box-shadow:0 2px 8px -2px rgba(26,115,232,.5)}
 .fgrid{display:grid;grid-template-columns:1fr 1fr;gap:12px 14px;margin:6px 0}
 @media(max-width:760px){.fgrid{grid-template-columns:1fr}}
 .fgrid label{font-size:12px;color:var(--tx2);font-weight:600;letter-spacing:.2px;
              display:block;margin-bottom:3px;white-space:nowrap}
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
 .srow .sctl input{height:34px;padding:0 12px;border:1px solid var(--line2);
   border-radius:9px;background:var(--card);color:var(--tx);font-size:13px;
   box-sizing:border-box;transition:border-color .15s,box-shadow .15s}
 .srow .sctl input:hover{border-color:var(--mut)}
 .srow .sctl input:focus{outline:none;border-color:var(--blue);
   box-shadow:0 0 0 3px rgba(26,115,232,.14)}
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
 .fgrid input{width:100%;padding:8px 10px;border:1px solid var(--line2);border-radius:9px;
              font-size:13px;box-sizing:border-box;background:var(--card);color:var(--tx);
              transition:border-color .15s,box-shadow .15s}
 .fgrid input:hover{border-color:var(--mut)}
 .fgrid input:focus{outline:none;border-color:var(--blue);
              box-shadow:0 0 0 3px rgba(26,115,232,.14)}
 .fgrid input[type=checkbox]{width:15px;height:15px;accent-color:var(--blue)}
 input[type=checkbox]{accent-color:var(--blue)}
 /* number 输入去原生 spinner（黑块破坏质感；步进用键盘方向键仍可用） */
 input[type=number]{-moz-appearance:textfield;appearance:textfield}
 input[type=number]::-webkit-outer-spin-button,
 input[type=number]::-webkit-inner-spin-button{-webkit-appearance:none;margin:0}
 /* 全局卡迷你输入框 */
 .mini{width:64px;text-align:center;padding:6px 8px;border:1px solid var(--line2);
       border-radius:9px;font-size:13px;background:var(--card);color:var(--tx);
       transition:border-color .15s,box-shadow .15s}
 .mini:focus{outline:none;border-color:var(--blue);box-shadow:0 0 0 3px rgba(26,115,232,.14)}
 /* 免打扰三列（窄屏说明换行堆叠）；label/input 与 .fgrid 同规格 */
 .qgrid{display:grid;grid-template-columns:1fr 1fr 1.8fr;gap:8px 14px;margin:8px 0}
 .qgrid label{font-size:12px;color:var(--mut);display:block;margin-bottom:2px;
              white-space:nowrap}
 .qgrid input{width:100%;padding:7px 10px;border:1px solid var(--line2);border-radius:9px;
              font-size:13px;box-sizing:border-box;background:var(--card);color:var(--tx);
              transition:border-color .15s,box-shadow .15s}
 .qgrid input:hover{border-color:var(--mut)}
 .qgrid input:focus{outline:none;border-color:var(--blue);
              box-shadow:0 0 0 3px rgba(26,115,232,.14)}
 @media(max-width:760px){.qgrid{grid-template-columns:1fr 1fr}
   .qgrid div:last-child{grid-column:1/-1}}
 .rline{background:var(--rowalt);border:1px solid var(--line);border-radius:var(--r2);
        padding:10px 14px;margin:8px 0;min-width:0;max-width:100%;
        box-sizing:border-box;overflow:hidden}
 .danger{color:var(--red);cursor:pointer;font-size:12px;font-weight:600;
        border:1px solid rgba(214,45,48,.30);background:transparent;border-radius:8px;
        padding:5px 12px;transition:.15s}
 .danger:hover{background:rgba(214,45,48,.08);border-color:rgba(214,45,48,.55)}
 .btn2{background:var(--card);color:var(--blue);border:1px solid var(--line2);border-radius:9px;
       padding:6px 14px;font-size:12.5px;font-weight:600;cursor:pointer;
       box-shadow:var(--sh1);margin-right:6px;transition:.15s}
 .btn2:hover{background:var(--headbg);box-shadow:var(--sh2)}
 .btn2:active{transform:scale(.97)}
 button.busy{opacity:.6;pointer-events:none}
 button.busy::after{content:' ⏳'}
 .fgrid input{width:100%;padding:7px 9px;border:1px solid var(--line);border-radius:7px;
              font-size:13px;box-sizing:border-box;background:var(--card);color:var(--tx)}
 .fbar{margin:8px 0;padding:10px 12px;background:var(--rowalt);border-radius:10px}
 .frow{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
 .frow+.frow{margin-top:8px}
 .chiplab{font-size:12px;color:var(--mut)}
 .chip{padding:4px 12px;border-radius:9px;cursor:pointer;font-size:12px;
   background:var(--headbg);color:var(--mut);border:1px solid var(--line);
   user-select:none;font-weight:600;transition:.15s}
 .chip:hover{background:var(--hover);color:var(--tx2)}
 .chip.on{background:var(--blue);color:#fff;border-color:transparent;
   box-shadow:0 2px 8px -2px rgba(26,115,232,.45)}
 .chip .bd{font-style:normal;font-size:10px;margin-left:4px;opacity:.9}
 .chip .bd.ok{color:#1e8e3e}.chip .bd.mid{color:#b08900}.chip .bd.old{color:#d62d30}
 .chip .bd.non{color:#9aa8b6}
 .chip.on .bd.ok{color:#b7f0c9}.chip.on .bd.mid{color:#ffe3a3}.chip.on .bd.old{color:#ffc4c5}
 .chip.on .bd.non{color:#dfe8f2}
 .fbar label{font-size:12px;color:var(--tx2);display:flex;align-items:center;gap:5px;white-space:nowrap}
 .fbar select,.fbar input[type=text],.fbar input[type=time]{
   height:30px;padding:0 9px;border:1px solid var(--line);border-radius:8px;
   font-size:12px;background:var(--card);color:var(--tx);
   transition:border-color .15s,box-shadow .15s}
 .fbar select:hover,.fbar input:hover{border-color:var(--mut)}
 .fbar select:focus,.fbar input:focus{outline:none;border-color:var(--blue);
   box-shadow:0 0 0 3px rgba(26,115,232,.14)}
 th.srt{cursor:pointer;user-select:none}
 th.srt:hover{background:var(--hover)}
 th.srt.on{color:var(--blue)}
 .stl{color:var(--stl);font-size:11px;font-weight:400}
 /* 数字等宽：价格/时刻列对齐，扫读不跳 */
 table,.kpi .num,.mchip b{font-variant-numeric:tabular-nums}
 /* 达标态：进度条转绿 + 文案 */
 .bar i.ok{background:linear-gradient(90deg,#57cf7a,#2ea44f)!important}
 .okTxt{color:#1e8e3e;font-weight:600}
 html[data-theme="dark"] .okTxt{color:#6fd693}
 /* 较上轮涨跌：降=绿 涨=红 持平=灰 */
 .dn{color:#1e8e3e;font-weight:600}
 .up{color:#d62d30;font-weight:600}
 html[data-theme="dark"] .dn{color:#6fd693}
 html[data-theme="dark"] .up{color:#ff8a8c}
 /* 明细行：直达链接 + 近达标琥珀 */
 a.vw{color:var(--blue);text-decoration:none;font-weight:400;margin-left:5px;
      font-size:12px;border:1px solid var(--line);border-radius:4px;padding:0 3px}
 a.vw:hover{background:var(--hover)}
 td.price.near{color:var(--stl);font-weight:800}
 /* 表格斑马纹（长表扫读不串行；xrow 展开行不参与） */
 #ftable tbody tr:nth-child(even):not(.xrow):not(:hover){background:var(--rowalt)}
 /* KPI 价格可点（直达去哪儿） */
 a.numlink{color:inherit;text-decoration:none}
 a.numlink:hover{text-decoration:underline}
 #ftable tbody tr:focus-visible{outline:2px solid var(--blue);outline-offset:-2px}
 /* 配置页航线摘要头 */
 .rhead{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;margin-bottom:4px}
 /* 渠道最低价 chips（替代长串文本） */
 .mchip{display:inline-block;padding:4px 11px;border-radius:18px;background:var(--headbg);
        color:var(--mut);font-size:12px;user-select:none;border:1px solid var(--line);
        transition:border-color .15s,transform .15s}
 .mchip:hover{border-color:var(--mut);transform:translateY(-1px)}
 .mchip b{font-weight:700;margin-left:2px;font-family:var(--num)}
 .mchip.best{background:var(--blue);color:#fff;border-color:transparent;
        box-shadow:0 2px 8px rgba(26,115,232,.3)}
 .mchip.best .pdot{background:#fff;opacity:.9}
 /* ===== header 图标按钮（玻璃拟态配套） ===== */
 .hbtn{cursor:pointer;font-size:17px;line-height:1;background:var(--headbg);
       border:1px solid var(--line);border-radius:10px;padding:8px 11px;
       user-select:none;transition:.15s;color:var(--tx2)}
 .hbtn:hover{background:var(--hover);transform:translateY(-1px)}
 .hbtn:active{transform:scale(.95)}
 /* 下轮倒计时 chip */
 .cdt{display:inline-block;background:var(--headbg);border:1px solid var(--line);
      color:var(--mut);border-radius:12px;padding:2px 10px;margin-right:8px;font-size:11px}
 .cdt.run{background:rgba(26,115,232,.12);color:var(--blue);border-color:transparent}
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
 /* 键盘可达性 */
 button:focus-visible,.chip:focus-visible,nav span:focus-visible,.tabs span:focus-visible{
  outline:2px solid var(--blue);outline-offset:2px}
 /* ===== 渠道健康时间线 ===== */
 .hrow{display:flex;align-items:center;gap:10px;margin:7px 0}
 .hlab{width:64px;flex:none;font-size:12px;color:var(--tx2);font-weight:600}
 .hcells{display:flex;gap:2px;flex:1;overflow-x:auto;padding:2px 0}
 .hc{width:6px;height:15px;border-radius:2px;flex:none;cursor:help}
 .hc.ok{background:#2ea44f}.hc.part{background:#e6a23c}.hc.fail{background:#d62d30}
 .hc.maint{background:repeating-linear-gradient(45deg,#9b7ede 0 2px,rgba(155,126,222,.35) 2px 4px)}
 .hc.none{background:var(--line)}
 .hc:hover{transform:scaleY(1.35)}
 .hbadge{flex:none;font-size:11.5px;font-weight:700;min-width:52px;text-align:center;
   padding:2px 8px;border-radius:20px;border:1px solid var(--line);
   background:var(--card);color:var(--tx2);font-variant-numeric:tabular-nums}
 .hbadge.ok{color:#1e8e3e;border-color:rgba(14,131,69,.35);background:var(--okbg)}
 .hbadge.mid{color:#b08900;border-color:rgba(230,162,60,.4);background:rgba(230,162,60,.1)}
 .hbadge.bad{color:#d62d30;border-color:rgba(214,45,48,.35);background:rgba(214,45,48,.08)}
 .hlb{display:inline-block;width:12px;height:6px;border-radius:2px;vertical-align:middle;margin-right:4px}
 .hlh{background:repeating-linear-gradient(45deg,#9b7ede 0 2px,rgba(155,126,222,.35) 2px 4px)}
 /* ===== V50 运行脉冲：概览 statline + 轮次堆叠柱 ===== */
 .statline{display:grid;grid-template-columns:repeat(auto-fit,minmax(158px,1fr));
  border:1px solid var(--line);border-radius:var(--r2);overflow:hidden;
  background:var(--card);margin-top:10px}
 .stat{padding:11px 16px;border-right:1px solid var(--line);min-width:0}
 .stat:last-child{border-right:none}
 .stat .slab{font-size:10.5px;letter-spacing:1.5px;color:var(--mut);
  text-transform:uppercase;display:flex;align-items:center;gap:6px;white-space:nowrap}
 .stat .sval{font-family:var(--num);font-size:22px;font-weight:600;margin-top:3px;
  font-variant-numeric:tabular-nums;letter-spacing:-.5px;white-space:nowrap}
 .stat .sval.ok{color:var(--green)}.stat .sval.bad{color:var(--red)}
 .stat .ssub{font-size:11px;color:var(--mut);margin-top:1px;white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis}
 .pulsewrap{display:flex;align-items:flex-end;gap:3px;height:72px;margin-top:12px}
 .pbar{flex:1;min-width:4px;max-width:16px;height:100%;display:flex;flex-direction:column;
  justify-content:flex-end;cursor:help;border-radius:2px}
 .pbar:hover{filter:brightness(1.15)}
 .pbar .seg{width:100%}
 .pbar .cap{width:100%;height:3px;background:var(--red);margin-bottom:1px;border-radius:1px}
 .pbar.zero{display:flex;justify-content:center}
 .pbar.zero i{width:100%;max-width:8px;height:3px;border-radius:1px;background:var(--red)}
 .pseg-qunar{background:#2f7fe0}.pseg-fliggy{background:#e07f2a}
 .pseg-tongcheng{background:#0e8345}.pseg-tuniu{background:#8a63d2}
 .pseg-ctrip{background:#0f8f8f}
 html[data-theme="dark"] .pseg-qunar{background:#5b9cf0}
 html[data-theme="dark"] .pseg-fliggy{background:#e89a4d}
 html[data-theme="dark"] .pseg-tongcheng{background:#43c072}
 html[data-theme="dark"] .pseg-tuniu{background:#a988e0}
 html[data-theme="dark"] .pseg-ctrip{background:#3ab0b0}
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
 .pvbody .md-p{margin:6px 0}
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
  header{padding:12px 14px}
  header .muted{display:none}/* 窄屏收窄 header 高度：内容别整行藏进栏底 */
  header h1{font-size:17px}
  .pill{font-size:14px;padding:5px 12px}
  #fltBtn{display:inline-block}
  #fltBtn b{background:var(--red);color:#fff;border-radius:9px;padding:0 6px;font-size:11px;margin-left:3px}
  .fbar{display:none}
  .fbar.open{display:block}
  .fbar label,.fbar select,.fbar input{font-size:13px}
  button{padding:11px 16px}
  .chip{padding:6px 12px}
  .hc{width:5px}
  .tw th:first-child,.tw td:first-child{position:sticky;left:0;z-index:2;
   background:var(--card);box-shadow:2px 0 0 var(--line)}
  .tw th:first-child{background:var(--headbg);z-index:4}
  .tw tbody tr:nth-child(even):not(.xrow) td:first-child{background:var(--rowalt)}
  .tw tbody tr:hover td:first-child{background:var(--hover)}
 }
 /* ===== 价格日历热力卡 ===== */
 .calgrid{display:flex;gap:5px;flex-wrap:wrap;margin-top:8px}
 .calcell{flex:0 0 auto;width:74px;border-radius:9px;padding:6px 4px;text-align:center;
        cursor:help;border:1px solid var(--line);transition:transform .12s}
 .calcell:hover{transform:translateY(-2px)}
 .calcell .cd{font-size:11px;font-weight:600;opacity:.85}
 .calcell .cp{font-size:13px;font-weight:800;margin-top:2px;font-variant-numeric:tabular-nums}
 .calcell.none{background:var(--rowalt);color:var(--mut)}
 /* ===== 日志原文弹层 ===== */
 .logpre{font-family:Consolas,Menlo,monospace;font-size:11.5px;line-height:1.6;
        white-space:pre-wrap;word-break:break-all;background:var(--rowalt);
        border-radius:8px;padding:10px 12px;margin:0;max-height:60vh;overflow:auto}
 /* ===== 通知开关 ===== */
 /* ===== 走势范围 chips（与 tabs/chip 同一视觉语言） ===== */
 .rngchip{padding:5px 14px;border-radius:18px;cursor:pointer;font-size:12px;
   background:var(--headbg);color:var(--mut);border:1px solid var(--line);
   user-select:none;font-weight:600;transition:.15s}
 .rngchip:hover{border-color:var(--mut);color:var(--tx2)}
 .rngchip.on{background:var(--blue);color:#fff;border-color:transparent;
   box-shadow:0 2px 8px -2px rgba(26,115,232,.45)}
 /* ===== toast 通知（右上角堆叠，非阻断；替代原生 alert） ===== */
 #toasts{position:fixed;top:70px;right:14px;z-index:300;display:flex;
        flex-direction:column;gap:8px;align-items:flex-end}
 .toast{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--blue);
        border-radius:10px;padding:10px 16px;font-size:13px;color:var(--tx);
        box-shadow:0 8px 24px rgba(16,24,40,.14);animation:tin .25s ease;
        max-width:340px;word-break:break-all}
 .toast.ok{border-left-color:#2ea44f}
 .toast.err{border-left-color:#d62d30}
 .toast.out{opacity:0;transform:translateX(20px);transition:.3s}
 @keyframes tin{from{opacity:0;transform:translateX(20px)}to{opacity:1;transform:none}}
 /* 危险操作二次确认态（按钮内联确认，替代原生 confirm） */
 button.arming{background:var(--red)!important;border-color:var(--red)!important;color:#fff!important}
 /* 明细行入场（stagger 渐显；reduced-motion 全局已禁用动画） */
 @keyframes rowin{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
 #ftable tbody tr{animation:rowin .22s ease backwards}
 /* 大表免动画：数百行同时入场动画只增加合成开销（重建本身已 <15ms） */
 #ftable.big tbody tr{animation:none}
 #ftable tbody tr:nth-child(2){animation-delay:.03s}
 #ftable tbody tr:nth-child(3){animation-delay:.06s}
 #ftable tbody tr:nth-child(4){animation-delay:.09s}
 #ftable tbody tr:nth-child(5){animation-delay:.12s}
 #ftable tbody tr:nth-child(6){animation-delay:.15s}
 #ftable tbody tr:nth-child(7){animation-delay:.18s}
 #ftable tbody tr:nth-child(n+8){animation-delay:.21s}
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
 .cfgnav{position:sticky;top:64px;display:flex;flex-direction:column;gap:4px;
  align-self:start;max-height:calc(100vh - 76px);overflow:auto}
 #cfgview{padding-bottom:88px}/* 底部字段不被浮存条(savebar)遮挡 */
 .cfgnav>span,.cfgnav .cfgsearch{background:var(--card);
   border:1px solid var(--line);border-radius:var(--r);padding:10px 12px}
 .cfgnav-t{font-size:10px;letter-spacing:1.5px;color:var(--mut);padding:2px 8px 6px;
   text-transform:uppercase}
 .cnav{padding:8px 12px;border-radius:9px;cursor:pointer;font-size:13px;color:var(--tx2);
   font-weight:600;transition:.15s;user-select:none}
 .cnav:hover{background:var(--hover)}
 .cnav.on{background:var(--blue);color:#fff}
 @media(max-width:900px){.cfglayout{grid-template-columns:1fr}
   .cfgnav{position:static;flex-direction:row;flex-wrap:wrap}
   .cfgnav-t{display:none}}
 .grouplab{display:flex;align-items:center;gap:9px;margin:16px 2px 10px;
   border:1px solid var(--line);border-radius:9px;padding:9px 12px;font-size:13px;
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
 .lgdot{width:8px;height:8px;border-radius:50%;background:#b9c4d0;flex:none;
   display:inline-block}
 .lgdot.on{background:var(--green);box-shadow:0 0 0 3px rgba(14,131,69,.15)}
 .lggrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(148px,1fr));gap:10px}
 .lgcard{border:1px solid var(--line);border-radius:var(--r2);padding:12px 14px;
   background:var(--card);display:flex;flex-direction:column;gap:7px;
   transition:border-color .2s,transform .15s}
 .lgcard:hover{border-color:var(--line2);transform:translateY(-2px)}
 .lgcard.saved{border-color:rgba(14,131,69,.35)}
 .lgcard.active{border-color:rgba(230,162,60,.6)}
 .lgcard .lgname{font-size:13.5px;font-weight:700;display:flex;align-items:center;gap:8px}
 .lgcard .lgsub{font-size:11.5px;color:var(--mut)}
 .lgcard .btn2{margin-top:auto}
 .glgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
 .glcell{border:1px solid var(--line);border-radius:var(--r2);padding:11px 14px;
   background:var(--card);transition:border-color .2s}
 .glcell:hover{border-color:var(--line2)}
 .glcell .glab{font-size:10.5px;letter-spacing:1.2px;color:var(--mut);
   text-transform:uppercase;white-space:nowrap}
 .glcell input{margin-top:6px;font-family:var(--num);font-size:17px;font-weight:600;
   width:100%;border:none;background:transparent;color:var(--tx);padding:2px 0 0;
   border-bottom:1px dashed var(--line2);border-radius:0}
 .glcell input:hover{border-bottom-color:var(--mut)}
 .glcell input:focus{outline:none;border-bottom:1px solid var(--blue);
   box-shadow:0 1px 0 0 rgba(26,115,232,.25)}
 .glcell .gsub{font-size:11px;color:var(--mut);margin-top:5px}
 .chgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(272px,1fr));
   gap:10px;margin-top:8px}
 .chcard.expanded{grid-column:1/-1}/* 展开的通道卡跨全宽，不留半列空白 */
 .chcard{border:1px solid var(--line);border-radius:var(--r2);padding:12px 14px;
   background:var(--card);display:flex;flex-direction:column;gap:9px;
   transition:border-color .2s}
 .chcard.on{border-color:rgba(14,131,69,.4)}
 .chhead{display:flex;align-items:center;gap:8px;font-size:13.5px;font-weight:700}
 .chhead .muted{font-weight:500;margin-left:auto;white-space:nowrap}
 .hint{font-size:10.5px;color:var(--mut);line-height:1.55;margin-top:5px;opacity:.92}
 .uhead2{cursor:pointer;display:flex;align-items:center;gap:12px;padding:13px 16px;
   background:var(--headbg);transition:background .15s;user-select:none}
 .uhead2:hover{background:var(--hover)}
 .uhead2 b{flex:1;font-size:14px}
 .uhead2 .stat2{font-family:var(--num);font-size:11.5px;color:var(--mut)}
 .uava{width:30px;height:30px;border-radius:9px;flex:none;display:inline-flex;
   align-items:center;justify-content:center;font-size:13px;font-weight:700;color:#fff;
   background:linear-gradient(135deg,#1a73e8,#6c47ff)}
 .upill{font-size:11px;padding:3px 9px;border-radius:20px;border:1px solid var(--line);
   background:var(--card);color:var(--mut);white-space:nowrap;
   font-family:var(--num);font-variant-numeric:tabular-nums}
 .upill.ok{color:var(--green);border-color:rgba(14,131,69,.35);background:var(--okbg)}
 .upill.warn{color:#b45309;border-color:rgba(240,180,41,.45);background:rgba(240,180,41,.12)}
 .udirty{display:none}
 .chev{transition:transform .2s;color:var(--mut);font-size:12px;flex:none}
 .chev.open{transform:rotate(180deg)}
 .grouplab[data-sec],.rhead[role="button"],.chhead[role="button"]{cursor:pointer;user-select:none}
 .grouplab[data-sec]:hover .zh,.chhead[role="button"]:hover{color:var(--blue)}
 .rhead[role="button"]:hover .rtcode{border-color:var(--blue)}
 .grouplab .chev{margin-left:auto}
 .ucard.flash,.rline.flash{animation:cfgflash 1.4s ease-out}
 @keyframes cfgflash{0%{box-shadow:0 0 0 3px rgba(26,115,232,.5)}
  100%{box-shadow:0 0 0 3px rgba(26,115,232,0)}}
 .rtcode{font-family:var(--num);font-size:14.5px;font-weight:600;color:var(--blue);
   letter-spacing:.5px}
 /* 未保存修改浮出保存条 */
 .savebar{position:fixed;right:18px;bottom:18px;z-index:120;display:none;gap:10px;
   align-items:center;background:var(--card);border:1px solid var(--line2);
   border-radius:12px;padding:10px 14px;box-shadow:var(--sh2);font-size:13px;font-weight:600}
 .savebar .dot{width:8px;height:8px;border-radius:50%;background:var(--orange);
   animation:pulse 1.4s ease-in-out infinite}
 /* ===== 推送记录列表 ===== */
 .plitem{padding:8px 10px;border-radius:8px;cursor:pointer;font-size:13px;
        margin:4px 0 2px;background:var(--rowalt);display:flex;gap:8px;align-items:baseline}
 .plitem:hover{background:var(--hover)}
 .plts{color:var(--mut);font-size:11.5px;white-space:nowrap;font-variant-numeric:tabular-nums}
 .pldesp{border:1px solid var(--line);border-radius:8px;padding:4px 14px;margin:2px 0 10px}
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
 .cfgsearch{width:100%;padding:7px 11px;border:1px solid var(--line2);border-radius:9px;
  font-size:12.5px;background:var(--card);color:var(--tx);margin:8px 0 10px;
  transition:border-color .15s,box-shadow .15s}
 .cfgsearch:hover{border-color:var(--mut)}
 .cfgsearch:focus{outline:none;border-color:var(--blue);box-shadow:0 0 0 3px rgba(26,115,232,.14)}
 .cfghit{font-size:11px;color:var(--mut);margin:-4px 0 8px;min-height:14px}
</style></head><body><div class="wrap">
<header><h1><span class="logo">✈️</span>机票监控台</h1>
 <div style="display:flex;align-items:center;gap:10px"><span id="ntBtn" class="hbtn" onclick="togNotify()" title="达标时浏览器通知+提示音">🔕</span><span id="themeBtn" class="hbtn" onclick="cycleTheme()" title="亮/暗/自动">🌗</span><div><span class="pill" id="pill">加载中…</span>
  <div class="muted" style="margin-top:6px;text-align:right"><span id="nextrun" class="cdt" style="display:none"></span><span id="updated"></span></div></div></div></header>

<datalist id="citydl"></datalist>
<div class="demoBar" id="demoBar" style="display:none">🎪 演示模式：数据为本地合成，仅作功能预览 · <a href="https://github.com/dengmeiluan/ticket-monitoring" target="_blank">下载源码或发行包</a>即可监控真实票价</div>
<nav><span id="navMon" class="on" onclick="switchView('mon')">📊 监控</span>
 <span id="navCfg" onclick="switchView('cfg')">⚙️ 配置</span></nav>
<div id="monview">
<div class="ucard"><div class="row">
 <button onclick="api('run','立即扫描全部航线？将触发采集与各用户钉钉推送')">🔄 立即扫描一轮</button>
 <button class="warn" onclick="api('push','向所有已配置用户推送走势报告？')">📈 推送走势报告</button>
 <button class="warn" id="pvBtn" onclick="previewPush()">👁 预览推送</button>
 <button class="warn" onclick="pushLog()">📨 推送记录</button>
 <span class="muted">数据变化才刷新（悬停/展开不打断）· 页面隐藏时暂停轮询</span>
 <div class="frow" id="userPills" style="display:none;width:100%;margin-top:2px"></div></div></div>

<div class="ucard" id="pulsecard" style="display:none"><div class="uhead">
  <span style="display:flex;align-items:center;gap:9px;flex-wrap:wrap"><span class="seclab inline" style="margin:0;border:none;padding:0"><span class="no">01</span><span class="zh">运行脉冲</span><span class="en">PULSE</span></span></span>
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
<div class="ucard" id="chartcard"><div class="uhead"><span style="display:flex;align-items:center;gap:9px;flex-wrap:wrap"><span class="seclab inline" style="margin:0;border:none;padding:0"><span class="no">02</span><span class="zh">价格走势</span><span class="en">TREND</span></span><span id="chartTitle" style="font-weight:700"></span></span>
 <span><span class="rngchip on" id="mdLine" onclick="setMode('line')">折线</span>
 <span class="rngchip" id="mdK" onclick="setMode('kline')">K线</span>
 <span style="display:inline-block;width:8px"></span>
 <span class="rngchip on" id="rng48" onclick="setRange('48h')">48h</span>
 <span class="rngchip" id="rng7d" onclick="setRange('7d')">7 天</span></span></div>
 <div class="frow" id="chartRoutes" style="margin:6px 0"></div>
 <div class="chartwrap"><canvas id="chart"></canvas>
  <div class="chart-empty" id="chartEmpty" style="display:none">暂无走势数据<span>完成第一轮扫描后，这里会出现近 48 小时的最低价曲线</span></div></div>
 <div class="legend"><span><b style="background:#1a73e8"></b>直飞最低</span>
  <span><b style="background:#e67e22"></b>达标中转最低</span>
  <span><b style="background:#2ea44f;opacity:.35"></b>可出手区</span><span><b style="background:#d62d30"></b>达标线（直飞/中转）</span></div></div>

<div class="ucard" id="calcard" style="display:none"><div class="uhead"><span style="display:flex;align-items:center;gap:9px;flex-wrap:wrap"><span class="seclab inline" style="margin:0;border:none;padding:0"><span class="no">03</span><span class="zh">价格日历</span><span class="en">CALENDAR</span></span><span id="calTitle" style="font-weight:700"></span></span>
 <span class="muted" id="calStats"></span></div>
 <div class="calgrid" id="calgrid"></div></div>
</div><!-- /montab-trend -->

<div id="montab-health" style="display:none">
<div class="ucard" id="healthcard" style="display:none"><div class="uhead"><span style="display:flex;align-items:center;gap:9px;flex-wrap:wrap"><span class="seclab inline" style="margin:0;border:none;padding:0"><span class="no">04</span><span class="zh">渠道健康</span><span class="en">HEALTH</span></span><span class="muted">近 24 小时 · 每格一轮扫描 · 点击格子看该轮日志</span></span>
 <span class="muted">解析自 monitor.log</span></div>
 <div id="hbody"></div>
 <div class="legend">
  <span><b class="hlb" style="background:#2ea44f"></b>成功</span>
  <span><b class="hlb" style="background:#e6a23c"></b>部分/降级</span>
  <span><b class="hlb" style="background:#d62d30"></b>失败</span>
  <span><b class="hlb hlh"></b>维护</span>
  <span><b class="hlb" style="background:var(--line)"></b>未扫描</span></div></div>
</div><!-- /montab-health -->

<div id="montab-details" style="display:none">
<div class="ucard" id="tablecard"><div class="seclab"><span class="no">05</span><span class="zh">航班明细</span><span class="en">DETAILS</span></div><div class="tabs" id="tabs">
  <span data-f="all" class="on">全部</span><span data-f="d">✈️ 直飞</span>
  <span data-f="tq">🔁 中转·达标</span><span data-f="t">🔁 中转·全部</span>
  <span data-f="q">🔥 仅达标</span>
  <span id="fltBtn" onclick="togFlt()">🎛 筛选<b id="fltN" style="display:none"></b></span>
  <span class="muted" style="margin-left:auto" id="fcnt"></span></div>
 <div class="fbar"><div class="frow" id="routechips"></div>
  <div class="frow" id="platchips"></div>
  <div class="frow" style="align-items:center">
   <label>出发时段 <select id="fdep" onchange="fdepChange()">
    <option value="">全部</option><option value="0">凌晨 00–06</option>
    <option value="6">上午 06–12</option><option value="12">下午 12–18</option>
    <option value="18">晚间 18–24</option><option value="c">自定义↓</option></select></label>
   <label>自 <input type="time" id="fdep1" style="width:92px" onchange="applyFlt()">
    至 <input type="time" id="fdep2" style="width:92px" onchange="applyFlt()"></label>
   <label>到达 自 <input type="time" id="farr1" style="width:92px" onchange="applyFlt()">
    至 <input type="time" id="farr2" style="width:92px" onchange="applyFlt()"></label>
   <label>价格 ￥<input type="text" id="fpmin" style="width:60px" placeholder="不限" onchange="applyFlt()"> –
    <input type="text" id="fpmax" style="width:60px" placeholder="不限" onchange="applyFlt()"></label>
   <label>搜索 <input type="text" id="fq" style="width:120px" placeholder="航班号/航司/中转" onchange="applyFlt()"></label>
   <label><input type="checkbox" id="fnostale" onchange="applyFlt()"> 隐藏补位数据（·Nh前）</label>
   <button class="btn2" onclick="resetFlt()">重置筛选</button>
   <button class="btn2" onclick="expCsv()">⬇ 导出CSV</button>
   <span class="muted">点击表头可排序（再点切换升降序）</span>
  </div></div>
 <div class="tw"><table id="ftable"></table></div></div>
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
 <div class="ucard" id="sec-login"><div class="uhead"><span class="seclab inline" style="margin:0;border:none;padding:0"><span class="no">01</span><span class="zh">渠道登录</span><span class="en">LOGIN</span></span>
  <span class="muted">弹出浏览器完成登录，点「我已登录完成」即保存并生效（无需重启）</span></div>
 <div id="loginRows"><span class="muted">加载中…</span></div>
 <div class="row" style="margin-top:6px">
  <button class="btn2" onclick="loadLogin()">🔄 刷新状态</button>
  <span class="muted">携程必须登录 · 去哪儿/同程/途牛建议 · 飞猪无需 · 采集进行中时窗口可能被占用，稍后再试</span></div></div>
 </div><!-- /panel-login -->
 <div class="cfpanel" id="panel-users" style="display:none">
 <div class="ucard" id="sec-users"><div class="uhead"><span class="seclab inline" style="margin:0;border:none;padding:0"><span class="no">02</span><span class="zh">用户与航线</span><span class="en">USERS</span></span>
  <span class="muted">保存后立即热重载生效（无需重启）；仅数据库/日志路径等启动级项需改 config.yaml 后重启</span></div>
 <div id="cfgform"></div>
 <div class="row" style="margin-top:10px">
  <button onclick="addUser()">➕ 添加用户</button>
  <button class="warn" onclick="saveCfg()">💾 保存并生效</button>
  <button class="btn2" onclick="exportCfg()" title="下载本机配置 JSON（含钉钉等本地凭据，注意保管）">📤 导出配置</button>
  <button class="btn2" onclick="$('cfgImport').click()" title="从导出的 JSON 恢复配置（导入后需保存生效）">📥 导入配置</button>
  <input type="file" id="cfgImport" accept=".json,application/json" style="display:none" onchange="importCfg(this)">
  <span class="muted" id="cfgmsg"></span>
  <span class="muted" id="cfgDirty" style="display:none;color:#b45309;font-weight:600">● 有未保存的修改</span></div></div>
 </div><!-- /panel-users -->
 <div class="cfpanel" id="panel-globals" style="display:none">
 <div class="ucard" id="sec-globals-card"><div class="uhead"><span class="seclab inline" style="margin:0;border:none;padding:0"><span class="no">03</span><span class="zh">全局参数</span><span class="en">GLOBAL</span></span>
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
  <div class="pvhead"><span id="pvTitle">预览</span><span class="pvx" onclick="closePv()" title="关闭（Esc）">✕</span></div>
  <div class="pvbody" id="pvBody"></div>
  <div class="pvfoot muted">本地近似渲染（标题/段落/加粗/链接/引用/进度条）· 明细总表图仅真实推送携带 · 以钉钉客户端实际效果为准</div>
 </div>
</div>
<footer id="foot" class="muted"></footer>
</div>
<script>
let S=null,F='all',U=0,SORT={k:'price',dir:1},FLT={plats:new Set(),routes:new Set(),t1:null,t2:null,a1:null,a2:null,pmin:0,pmax:0,no:false,q:''};
let LASTTXT='',NEXTRUN=null,TICKED=false,CHR={};
/* 渠道维护标记（无数据时角标）：如 {'飞猪':'维护中'}；渠道恢复后清空 */
const MAINT={};
const $=id=>document.getElementById(id);
/* 智能刷新：响应逐字不变则跳过重渲染（悬停/展开/滚动不被打断）；
   页面不可见时不轮询，切回立即拉一次 */
async function load(){if(document.hidden)return;
 try{const r=await fetch('/api/state');const t=await r.text();
  if(t===LASTTXT)return;LASTTXT=t;S=JSON.parse(t);}
 catch(e){$('updated').textContent='（服务未启动）';return;}
 try{render();health();pulse();}
 catch(e){console.error('render:',e);
  $('updated').textContent='（渲染异常：'+e.message+'）';}}
function pct(p,t){if(!t||!p)return 0;return Math.min(100,Math.max(2,(p/t-1)/0.5*100));}
function diffTxt(p,t){if(!t)return'';
 const d=Math.round(p-t);
 return d<=0?`<span class="okTxt">✅ 已低于线 ￥${-d}，可出手</span>`
            :`距线 ￥${d}（${Math.round((p/t-1)*100)}%）`;}
function deltaTxt(d){if(d==null||isNaN(d))return'';
 if(d===0)return'较上轮持平';
 return d<0?`<span class="dn">较上轮 ↓￥${-d}</span>`
           :`<span class="up">较上轮 ↑￥${d}</span>`;}
function render(){const s=S;if(!s)return;
 setNext(s.next_run);
 $('demoBar').style.display=s.demo?'':'none';
 $('foot').innerHTML=(s.version?'v'+s.version+' · ':'')
  +'<a href="https://github.com/dengmeiluan/ticket-monitoring" target="_blank">GitHub</a> · 本地服务 127.0.0.1:8765';
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
 // 达标以每用户逐行真实判定（后端按各自航线阈值）；旧字段回退
 const hit=s.users.some(x=>x.hit!==undefined?x.hit:
  ((x.best.direct&&x.best.direct.price<=x.th.direct)
   ||(x.best.transfer&&x.best.transfer.price<=x.th.transfer)));
 const pill=$('pill');pill.textContent=(hit?'🚨':'❌')+' '+(hit?'有人已达标':'未达标');
 pill.className='pill'+(hit?' ok':'');
 document.title=(hit?'🚨 达标｜':'')+'机票监控台';
 /* 多用户切换 pills：明细/走势/日历跟随所选用户（单用户隐藏不占位） */
 const up=$('userPills');
 if(s.users.length>1){up.style.display='';
  up.innerHTML='<span class="chiplab">用户：</span>'+s.users.map((x,i)=>
   `<span class="chip${i===U?' on':''}" onclick="pickUser(${i})">${he(x.name)}</span>`).join('')
   +'<span class="muted">明细 / 走势 / 日历跟随所选用户</span>';}
 else up.style.display='none';
 maybeNotify(s);
 let h='';
 s.users.forEach((x,i)=>{
  const xd=x.best.direct,xt=x.best.transfer;
  // KPI 阈值随最优航班所属航线（xd.th）：跨航线混用 routes[0] 的线=虚报
  const td=xd?(xd.th||x.th.direct):x.th.direct;
  const tt=xt?(xt.th||x.th.transfer):x.th.transfer;
  const xh=(xd&&td&&xd.price<=td)||(xt&&tt&&xt.price<=tt);
  const mins=x.minsArr||[];
  const PKEY={'去哪儿':'qunar','飞猪':'fliggy','携程':'ctrip','同程':'tongcheng','途牛':'tuniu'};
  const mHtml=mins.length?mins.map((m,k)=>
   `<span class="mchip${k===0?' best':''}"><span class="pdot ${PKEY[m[0]]||''}"></span>${m[0]} <b>￥${m[1]}</b></span>`).join('')
   :x.minsTxt;
  h+=`<div class="ucard"><div class="uhead">
   <span class="uname">${xh?'🚨':'❌'} ${x.name}</span>
   <span class="uroutes">${x.routesTxt}</span></div>
   <div class="grid">
    <div class="kpi d${xd&&td&&xd.price<=td?' hit':''}"><div class="lab">直飞最低（线 ￥${td}）</div>
     <div class="num">${xd?(xd.view?`<a class="numlink" data-k="${i}d" data-v="${xd.price}" href="${xd.view}" target="_blank" title="去哪儿查看该航线">￥${xd.price}</a>`:'￥'+xd.price):'-'}</div>
     <div class="bar"><i class="${xd&&td&&xd.price<=td?'ok':''}" style="width:${xd?pct(xd.price,td):0}%"></i></div>
     <div class="muted">${xd?diffTxt(xd.price,td)+(x.delta&&x.delta.direct!=null?' · '+deltaTxt(x.delta.direct):''):''}</div>
     <div class="muted fb">${xd?`${xd.route?xd.route+' · ':''}${xd.name} ${xd.depTime}-${xd.arrTime}${xd.cross?' '+xd.cross:''}`:''}</div></div>
    <div class="kpi t${xt&&tt&&xt.price<=tt?' hit':''}"><div class="lab">中转最低·达标班次（线 ￥${tt}）</div>
     <div class="num">${xt?(xt.view?`<a class="numlink" data-k="${i}t" data-v="${xt.price}" href="${xt.view}" target="_blank" title="去哪儿查看该航线">￥${xt.price}</a>`:'￥'+xt.price):'-'}</div>
     <div class="bar"><i class="${xt&&tt&&xt.price<=tt?'ok':''}" style="width:${xt?pct(xt.price,tt):0}%"></i></div>
     <div class="muted">${xt?diffTxt(xt.price,tt)+(x.delta&&x.delta.transfer!=null?' · '+deltaTxt(x.delta.transfer):''):''}</div>
     <div class="muted fb">${xt?`${xt.route?xt.route+' · ':''}${xt.name} ${xt.depTime}-${xt.arrTime}${xt.cross?' '+xt.cross:''}${xt.trans?' 经'+xt.trans:''}`:''}</div></div>
   </div>
   <div class="muted" style="margin-top:8px">全线最低：${mHtml} ｜ <a href="#" onclick="pickUser(${i});return false" style="color:var(--blue)">查看明细 ▾</a></div>
  </div>`;});
 $('users').innerHTML=h;
 countUps();
 CHART_ANIM=1;
 buildRouteChips();buildChips();buildChartChips();table();chart();renderCal();}
/* KPI 数字 count-up：数据刷新时从旧值滚动到新值（600ms smoothstep） */
const PREV={};
function countUps(){document.querySelectorAll('a.numlink').forEach(el=>{
 const k=el.dataset.k,to=parseFloat(el.dataset.v);
 if(!k||isNaN(to))return;
 const from=PREV[k];PREV[k]=to;
 if(from==null||from===to)return;
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
 if(t==='trend'&&!silent)chart();
 try{localStorage.setItem('jpmontab',t);}catch(e){}}
document.querySelectorAll('#montabs .mtab').forEach(x=>{
 x.onclick=()=>showMonTab(x.dataset.t);});
try{const _mt=localStorage.getItem('jpmontab');
 if(_mt&&_mt!=='overview')showMonTab(_mt,true);}catch(e){}
/* ===== 明细表：筛选 + 排序 ===== */
function buildRouteChips(){const u=S.users[U];
 const rs=[...new Set(u.flights.map(f=>f.route).filter(Boolean))].sort();
 const box=$('routechips');
 if(rs.length<2){box.innerHTML='';return;}   // 单航线无角标数据，隐藏
 const keep=[...FLT.routes].filter(p=>rs.includes(p));
 FLT.routes=new Set(keep.length?keep:rs);
 box.innerHTML='<span class="chiplab">航线：</span>'+rs.map(p=>
  `<span class="chip${FLT.routes.has(p)?' on':''}" onclick="togRoute(this,'${p}')">${p}</span>`).join('');}
function togRoute(el,p){if(FLT.routes.has(p))FLT.routes.delete(p);else FLT.routes.add(p);
 el.classList.toggle('on');saveUI();table();}
function buildChips(){const u=S.users[U];
 const age=u.platAge||{};
 const ps=[...new Set(u.flights.map(f=>f.plat).concat(Object.keys(age)))].sort();
 const keep=[...FLT.plats].filter(p=>ps.includes(p));
 FLT.plats=new Set(keep.length?keep:ps);
 const badge=p=>{const a=age[p];
  if(MAINT[p]&&a==null)return'<i class="bd mid">'+MAINT[p]+'</i>';
  if(a==null)return'<i class="bd non">无数据</i>';
  if(a<0.5)return'<i class="bd ok">新</i>';
  const h=Math.max(1,Math.round(a));
  return a<6?`<i class="bd mid">${h}h前</i>`:`<i class="bd old">${h}h前</i>`;};
 $('platchips').innerHTML='<span class="chiplab">渠道：</span>'+ps.map(p=>
  `<span class="chip${FLT.plats.has(p)?' on':''}" onclick="togChip(this,'${p}')">${p} ${badge(p)}</span>`).join('');}
function togChip(el,p){if(FLT.plats.has(p))FLT.plats.delete(p);else FLT.plats.add(p);
 el.classList.toggle('on');saveUI();table();}
/* ===== 筛选/排序状态持久化（刷新不丢） ===== */
function saveUI(){try{localStorage.setItem('jpui',JSON.stringify(
 {F:F,U:U,sk:SORT.k,sd:SORT.dir,plats:[...FLT.plats],routes:[...FLT.routes],no:FLT.no,q:FLT.q,chr:CHR}));}catch(e){}}
function restoreUI(){try{const j=JSON.parse(localStorage.getItem('jpui')||'{}');
 if(j.F)F=j.F;if(j.sk)SORT={k:j.sk,dir:j.sd||1};
 if(Array.isArray(j.plats)&&j.plats.length)FLT.plats=new Set(j.plats);
 if(Array.isArray(j.routes))FLT.routes=new Set(j.routes);
 if(j.chr)CHR=j.chr;
 if(j.no){FLT.no=true;$('fnostale').checked=true;}
 if(j.q){FLT.q=j.q;const el=$('fq');if(el)el.value=j.q;}
 U=Math.min(j.U||0,99);
 document.querySelectorAll('#tabs span').forEach(s=>
  s.classList.toggle('on',s.dataset.f===F));}catch(e){}}
function hm(t){const m=(t||'').match(/^(\d{1,2}):(\d{2})/);return m?(+m[1])*60+(+m[2]):null;}
function fdepChange(){const v=$('fdep').value;
 const map={0:['00:00','06:00'],6:['06:00','12:00'],12:['12:00','18:00'],18:['18:00','23:59']};
 if(map[v]){$('fdep1').value=map[v][0];$('fdep2').value=map[v][1];}
 else if(v===''){$('fdep1').value='';$('fdep2').value='';}
 applyFlt();}
function applyFlt(){FLT.t1=hm($('fdep1').value);FLT.t2=hm($('fdep2').value);
 FLT.a1=hm($('farr1').value);FLT.a2=hm($('farr2').value);
 FLT.pmin=parseFloat($('fpmin').value)||0;FLT.pmax=parseFloat($('fpmax').value)||0;
 FLT.no=$('fnostale').checked;
 FLT.q=($('fq').value||'').trim();saveUI();table();}
function resetFlt(){FLT.routes=new Set();FLT.t1=null;FLT.t2=null;FLT.a1=null;FLT.a2=null;
 FLT.pmin=0;FLT.pmax=0;FLT.no=false;FLT.q='';
 $('fdep').value='';$('fdep1').value='';$('fdep2').value='';
 $('farr1').value='';$('farr2').value='';
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
/* ===== 同班跨渠道比价：点击行展开（指纹含日期——多日期航线同班次不混串） ===== */
let EXP=null;
const fp=f=>(f.date||'')+'|'+f.depTime+'|'+f.arrTime+'|'+f.trans+'|'+f.cross;
/* 展开行渲染期预置为隐藏行，点击只切 display——表格零 childList 变更。
   （曾用"插/删一个 tr"的外科手术方案，但翻译/比价类扩展监听 DOM 插入会
   全页重扫，用户实测每点一行卡数秒；隐藏行只是 attribute 变更，不触发） */
function xrowHtml(u,k,open){
 const same=u.flights.filter(x=>fp(x)===k)
  .sort((a,b)=>a.price-b.price);
 const save=same.length>1?same[same.length-1].price-same[0].price:0;
 const chain=same.map(x=>`${x.plat}${x.stale?'·'+x.stale+'h前':''} ￥${x.price}`).join(' ＜ ');
 return `<tr class="xrow"${open?'':' style="display:none"'}><td colspan="9">⚖️ 同班比价：${chain}`+
    (save?`（可省 ￥${save}）`:'（仅一渠道报价）')+`</td></tr>`;}
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
  if(FLT.plats.size&&!FLT.plats.has(f.plat))return false;
  if(FLT.routes.size&&f.route&&!FLT.routes.has(f.route))return false;
  if(FLT.t1!==null||FLT.t2!==null){const m=tmin(f.depTime);
   if(m===null)return false;
   if(FLT.t1!==null&&m<FLT.t1)return false;
   if(FLT.t2!==null&&m>FLT.t2)return false;}
  if(FLT.a1!==null||FLT.a2!==null){const m=tmin(f.arrTime);
   if(m===null)return false;
   if(FLT.a1!==null&&m<FLT.a1)return false;
   if(FLT.a2!==null&&m>FLT.a2)return false;}
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
function expCsv(){const rows=filteredRows();
 if(!rows.length){toast('当前筛选无数据','err');return;}
 const e2=v=>'"'+String(v==null?'':v).replace(/"/g,'""')+'"';
 const head=['价格','类别','日期','航班','航班号','出发','到达','跨天','时长','中转','渠道','数据时效','状态'];
 const lines=[head.map(e2).join(',')];
 for(const f of rows)lines.push([
  f.price,f.transfer?'中转':'直飞',f.date||'',f.name,f.code||'',f.depTime,f.arrTime,
  f.cross||'',f.dur||'',f.trans||'',f.plat,
  f.stale?('补位·'+f.stale+'h前'):'实时',
  f.qual?'达标':(f.near?'近达标':'')].map(e2).join(','));
 const blob=new Blob([String.fromCharCode(65279)+lines.join(String.fromCharCode(13,10))],{type:'text/csv;charset=utf-8'});
 const a=document.createElement('a');
 a.href=URL.createObjectURL(blob);
 a.download='flights_'+new Date().toISOString().slice(0,16).replace(/[-:T]/g,'')+'.csv';
 a.click();URL.revokeObjectURL(a.href);}
 function table(){
  const u=S.users[U];
  const rows=filteredRows();
  $('ftable').classList.toggle('big',rows.length>150);
 let h='<thead><tr>'+HEADS.map(([k,n])=>
  `<th class="srt${SORT.k===k?' on':''}" onclick="sortCol('${k}')">${n}${SORT.k===k?(SORT.dir>0?' ▲':' ▼'):''}</th>`).join('')+'</tr></thead><tbody>';
 for(const f of rows){
  const k=fp(f);
  h+=`<tr class="${f.qual?'qual':''}" style="cursor:pointer" tabindex="0" title="${f.date||''} ${f.code||''}｜点击或回车展开同班各渠道比价" onclick="togRow('${k}',this)" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();togRow('${k}',this)}">`+
  `<td class="price${f.near?' near':''}"${f.near?' title="距线 10% 以内，接近达标"':''}>${f.qual?'🔥 ':''}￥${f.price}</td>`+
  `<td><span class="tag ${f.transfer?'t-t':'t-d'}">${f.transfer?'中转':'直飞'}</span></td>`+
  `<td>${f.date?f.date.slice(5).replace('-','/'):'—'}</td>`+
  `<td>${f.name}${f.cabinT?`<div class="stl" style="margin-top:3px">${f.cabinT}</div>`:''}${f.view?`<a class="vw" href="${f.view}" target="_blank" onclick="event.stopPropagation()" title="去哪儿查看该航线">↗</a>`:''}${f.route?`<span class="stl"> ${f.route}</span>`:''}</td><td>${f.depTime}</td>`+
  `<td>${f.arrTime}${f.cross?`<span class="stl"> ${f.cross}</span>`:''}</td>`+
  `<td>${f.dur||'—'}</td><td>${f.trans||'—'}${f.layoverT?`<div class="stl">停${f.layoverT}</div>`:''}</td>`+
  `<td><span class="pdot ${f.platKey||''}"></span>${f.plat}${f.stale?`<span class="stl">·${f.stale}h前</span>`:''}</td></tr>`+
  xrowHtml(u,k,EXP===k);
 }
 $('ftable').innerHTML=h+'</tbody>';
 $('fcnt').textContent=u.name+'：'+rows.length+' / '+u.flights.length+' 班';
 updFltN();}
/* ===== 走势图：多航线可切（routesArr），单航线回落旧行为；48h/7d 范围 ===== */
function curRoute(){const u=S.users[U];
 const arr=(u.routesArr&&u.routesArr.length)?u.routesArr
  :[{label:u.routesTxt||u.name,th:u.th,history:u.history}];
 let st=CHR[u.name];if(typeof st==='number')st={i:st};
 st=st||{i:0,r:'48h',m:'line'};CHR[u.name]=st;
 let idx=st.i||0;if(idx>=arr.length)idx=0;
 return {arr,idx,r:arr[idx],range:st.r||'48h',mode:st.m||'line'};}
function setRange(r){const u=S.users[U];let st=CHR[u.name];
 if(typeof st==='number')st={i:st};st=st||{i:0};st.r=r;CHR[u.name]=st;saveUI();
 $('rng48').className='rngchip'+(r==='48h'?' on':'');
 $('rng7d').className='rngchip'+(r==='7d'?' on':'');
 chart();renderCal();}
function setMode(m){const u=S.users[U];let st=CHR[u.name];
 if(typeof st==='number')st={i:st};st=st||{i:0};st.m=m;CHR[u.name]=st;saveUI();
 $('mdLine').className='rngchip'+(m==='line'?' on':'');
 $('mdK').className='rngchip'+(m==='kline'?' on':'');
 chart();}
/* K线聚合：[[MM-DD HH:MM,价],...] → 桶 OHLC（48h=2h 桶，7d=6h 桶） */
function toCandles(pts,bucketMin){const map={};
 const Y=new Date().getFullYear();
 for(const p of pts){
  const t=new Date(Y+'-'+p[0].replace(' ','T')).getTime();
  if(isNaN(t))continue;
  const k=Math.floor(t/(bucketMin*60000));
  (map[k]=map[k]||[]).push(p);}
 return Object.keys(map).map(Number).sort((a,b)=>a-b).map(k=>{
  const g=map[k];const vs=g.map(x=>x[1]);
  return {t0:g[0][0],o:vs[0],c:vs[vs.length-1],
   h:Math.max.apply(null,vs),l:Math.min.apply(null,vs)}});}
function buildChartChips(){const u=S.users[U];const box=$('chartRoutes');
 const arr=u.routesArr&&u.routesArr.length?u.routesArr:null;
 const CR=curRoute();
 $('rng48').className='rngchip'+(CR.range==='48h'?' on':'');
 $('rng7d').className='rngchip'+(CR.range==='7d'?' on':'');
 $('mdLine').className='rngchip'+(CR.mode==='line'?' on':'');
 $('mdK').className='rngchip'+(CR.mode==='kline'?' on':'');
 if(!arr||arr.length<2){box.innerHTML='';return;}
 const idx=CR.idx;
 box.innerHTML='<span class="chiplab">航线：</span>'+arr.map((r,i)=>
  `<span class="chip${i===idx?' on':''}" onclick="togChart(${i})">${r.label}</span>`).join('');}
function togChart(i){const nm=S.users[U].name;let st=CHR[nm];
 if(typeof st==='number')st={i:st};st=st||{r:'48h'};st.i=i;CHR[nm]=st;
 saveUI();buildChartChips();CHART_ANIM=1;
 const w=document.querySelector('.chartwrap');
 if(w){w.classList.remove('viewin');void w.offsetWidth;w.classList.add('viewin');}
 chart();renderCal();}
function chart(){const u=S.users[U];const CR=curRoute();
 $('chartTitle').textContent=u.name+(CR.r.label?' · '+CR.r.label:'')
  +(CR.range==='7d'?' · 7天':'');
 const c=$('chart'),ctx=c.getContext('2d');
 /* 容器隐藏（非走势子视图）时跳过绘制：offsetWidth=0 画了也白画；
    切回走势子视图时 showMonTab 会重绘 */
 if(!c.offsetWidth)return;
 const dpr=window.devicePixelRatio||1;c.width=c.offsetWidth*dpr;c.height=280*dpr;
 ctx.setTransform(dpr,0,0,dpr,0,0);
 const W=c.offsetWidth,H=280,L=64,R=14,T=14,B=44;
 const H0=CR.range==='7d'?(CR.r.history7||CR.r.history):CR.r.history;
 const hd=H0.direct,ht=H0.transfer;
 /* 主题感知配色：暗色下网格/坐标轴用主题变量，不再硬编码浅色 */
 const cssv=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
 const GRID=cssv('--line')||'#eef2f7',AXIS=cssv('--mut')||'#9aa8b6';
 const K=CR.mode==='kline';
 /* 标注 halo 底色随主题（K线/折线两分支共用；块级作用域须在此声明） */
 const halo=cssv('--card')||'#fff';
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
 ctx.clearRect(0,0,W,H);ctx.font='11px sans-serif';
 for(let k=0;k<=4;k++){const v=lo+(hi-lo)*k/4;
  ctx.strokeStyle=GRID;ctx.setLineDash([2,4]);
  ctx.beginPath();ctx.moveTo(L,Y(v));ctx.lineTo(W-R,Y(v));ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle=AXIS;ctx.fillText('￥'+Math.round(v),6,Y(v)+4);}
 /* X 轴时间刻度 + 跨天分隔线（数据点自带 MM-DD HH:MM，v110 可视化对齐推送图） */
 if(hd.length&&typeof hd[0][0]==='string'){
  ctx.font='11px sans-serif';ctx.fillStyle=AXIS;
  const stepN=Math.max(1,Math.ceil(hd.length/5));
  for(let i=0;i<hd.length;i+=stepN){
   ctx.fillText((hd[i][0]||'').slice(-5),Math.min(X(i)-14,W-46),H-8);}
  let prevDay=(hd[0][0]||'').slice(0,5);
  for(let i=1;i<hd.length;i++){
   const day=(hd[i][0]||'').slice(0,5);
   if(day!==prevDay){
    const gx=X(i);
    ctx.strokeStyle='rgba(214,150,60,.45)';ctx.lineWidth=1;
    ctx.beginPath();ctx.moveTo(gx,T);ctx.lineTo(gx,H-B);ctx.stroke();
    ctx.fillStyle='#9a7b30';ctx.fillText(day,gx+4,T+10);
    prevDay=day;}}
  ctx.font='11px sans-serif';}
 const zone=(v)=>{if(!v||v<lo||v>hi)return;ctx.fillStyle='rgba(46,164,79,.14)';ctx.fillRect(L,Y(v),W-L-R,H-B-Y(v));};
 zone(CR.r.th.direct);zone(CR.r.th.transfer);
 const dash=(v)=>{if(!v||v<lo||v>hi)return;ctx.strokeStyle='#d62d30';ctx.setLineDash([6,5]);
  ctx.beginPath();ctx.moveTo(L,Y(v));ctx.lineTo(W-R,Y(v));ctx.stroke();ctx.setLineDash([]);};
 dash(CR.r.th.direct);dash(CR.r.th.transfer);
 if(K){
  /* K线：涨红空心 跌绿实心（A股习惯）；直飞左偏 中转右偏 */
  const cw=Math.max(4,Math.min(15,(W-L-R)/Math.max(N,1)*0.30));
  const drawK=(cs,off)=>{cs.forEach((c,i)=>{
   const cx=X(i)+off,up=c.c>=c.o,col=up?'#d62d30':'#2ea44f';
   ctx.strokeStyle=col;ctx.lineWidth=1.2;
   ctx.beginPath();ctx.moveTo(cx,Y(c.h));ctx.lineTo(cx,Y(c.l));ctx.stroke();
   const yT=Y(Math.max(c.o,c.c)),yB=Y(Math.min(c.o,c.c));
   if(up)ctx.strokeRect(cx-cw/2,yT,cw,Math.max(1.5,yB-yT));
   else{ctx.fillStyle=col;ctx.fillRect(cx-cw/2,yT,cw,Math.max(1.5,yB-yT));}});};
  drawK(CD,-cw*0.62);drawK(CT,cw*0.62);
  HPTS={kline:true,cd:CD,ct:CT,cw:cw,L:L,Rx:W-R,T:T,B:B};
  /* K线最低影线标注（同样带完整时刻 + halo 防压线） */
  let best=null;CD.forEach((c,i)=>{if(!best||c.l<best.c.l)best={c,i,s:'d'};});
  CT.forEach((c,i)=>{if(!best||c.l<best.c.l)best={c,i,s:'t'};});
  if(best&&best.i!==(best.s==='d'?CD:CT).length-1){
   const bx=X(best.i)+(best.s==='d'?-cw*0.62:cw*0.62);
   ctx.font='bold 11px sans-serif';ctx.lineWidth=3;ctx.strokeStyle=halo;
   const ktag='低 ￥'+Math.round(best.c.l)+' '+String(best.c.t0||'').slice(0,11);
   ctx.strokeText(ktag,Math.min(bx+6,W-150),Math.max(Y(best.c.h)-8,T+12));
   ctx.fillStyle='#d62d30';
   ctx.fillText(ktag,Math.min(bx+6,W-150),Math.max(Y(best.c.h)-8,T+12));
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
   pts.forEach((p,i)=>{ctx.fillStyle=color;ctx.beginPath();
    ctx.arc(X(i),Y(p[1]),2.6,0,7);ctx.fill();});
   if(tv>0)/* 达标数据点：白心绿环旗标（达标时刻图上直接可见） */
    pts.forEach((p,i)=>{if(p[1]<=tv){
     ctx.beginPath();ctx.arc(X(i),Y(p[1]),5.5,0,7);
     ctx.fillStyle='#fff';ctx.fill();
     ctx.lineWidth=2;ctx.strokeStyle='#1e8e3e';ctx.stroke();}});};
  series(hd,'#1a73e8',CR.r.th.direct);series(ht,'#e67e22',CR.r.th.transfer);
  HPTS={d:hd.map((p,i)=>[X(i),Y(p[1]),p[1],p[0]]),
   t:ht.map((p,i)=>[X(i),Y(p[1]),p[1],p[0]]),
   L:L,Rx:W-R,T:T,B:B};
  /* 最低点标注：带完整日期时刻（只显 HH:MM 会被误读为"刚刚暴跌"），
     halo 描边防止文字压线不可读 */
  const markMin=(pts,color)=>{if(!pts||pts.length<3)return;
   let mi=0;pts.forEach((p,i)=>{if(p[1]<pts[mi][1])mi=i;});
   if(mi===pts.length-1)return;
   const [x,y,v,t]=pts[mi];
   ctx.font='bold 11px sans-serif';ctx.lineWidth=3;ctx.strokeStyle=halo;
   const tag=('低 ￥'+Math.round(v)+' '+String(t||'').slice(0,11));
   ctx.strokeText(tag,Math.min(x+6,W-150),Math.max(y-10,T+12));
   ctx.fillStyle=color;ctx.fillText(tag,Math.min(x+6,W-150),Math.max(y-10,T+12));
   ctx.font='11px sans-serif';};
  markMin(HPTS.d,'#1a73e8');markMin(HPTS.t,'#e67e22');
 }
 ctx.fillStyle=AXIS;
 [0,Math.floor((N-1)/2),N-1].slice(0,N===1?1:3).forEach((i)=>{
  const src=K?(CD[i]||CT[i]):(hd[i]||ht[i]);
  if(src)ctx.fillText(K?src.t0:src[0],X(i)-18,H-12);});
 };  /* /chartDraw */
 chartDraw();
 /* 入场动画：左→右擦除重现（数据刷新/切航线触发，hover 重绘不触发） */
 if(CHART_ANIM){CHART_ANIM=0;const t0=performance.now();
  const step=t=>{const p=Math.min(1,(t-t0)/700),e=1-Math.pow(1-p,3);
   ctx.save();ctx.beginPath();ctx.rect(L-2,0,(W-L-R+4)*e,H);ctx.clip();
   chartDraw();ctx.restore();
   if(p<1)requestAnimationFrame(step);};
  requestAnimationFrame(step);}
}
/* 悬停提示：十字线 + 数值浮框（折线读价 / K线读 OHLC） */
let HPTS=null,CHART_ANIM=0;
function drawHover(x){const c=$('chart'),ctx=c.getContext('2d');
 if(!HPTS)return;
 let ax,txt;
 if(HPTS.kline){
  const {cd,ct,L,Rx}=HPTS;
  const N=Math.max(cd.length,ct.length);if(N<1)return;
  let i=Math.round((x-L)/(Rx-L)*(N-1));i=Math.max(0,Math.min(N-1,i));
  const kd=cd[i],kt=ct[i];if(!kd&&!kt)return;
  ax=L+(Rx-L)*(N>1?i/(N-1):0.5);
  const parts=[];
  if(kd)parts.push('直飞 开'+kd.o+' 收'+kd.c+' 高'+kd.h+' 低'+kd.l);
  if(kt)parts.push('中转 开'+kt.o+' 收'+kt.c+' 高'+kt.h+' 低'+kt.l);
  txt=((kd||kt).t0||'')+'　'+parts.join('　');
 }else{
  const {d,t,L,Rx,T,B}=HPTS;
  const N=Math.max(d.length,t.length);if(N<1)return;
  let i=Math.round((x-L)/(Rx-L)*(N-1));i=Math.max(0,Math.min(N-1,i));
  const pd=d[i],pt=t[i];
  if(!pd&&!pt)return;
  ax=(pd||pt)[0];
  const parts=[];
  if(pd){ctx.fillStyle='#1a73e8';ctx.beginPath();ctx.arc(pd[0],pd[1],4.5,0,7);ctx.fill();
   parts.push(['直飞 ￥'+pd[2],'#1874cd']);}
  if(pt){ctx.fillStyle='#e67e22';ctx.beginPath();ctx.arc(pt[0],pt[1],4.5,0,7);ctx.fill();
   parts.push(['达标中转 ￥'+pt[2],'#e67e22']);}
  txt=((pd||pt)[3]||'')+'　'+parts.map(p=>p[0]).join('　');
 }
 ctx.strokeStyle=getComputedStyle(document.documentElement).getPropertyValue('--mut').trim()||'#9aa8b6';
 ctx.setLineDash([4,4]);
 ctx.beginPath();ctx.moveTo(ax,HPTS.T);ctx.lineTo(ax,HPTS.B);ctx.stroke();ctx.setLineDash([]);
 ctx.font='12px sans-serif';
 const w=ctx.measureText(txt).width+18;
 let bx=Math.min(Math.max(ax-w/2,4),c.offsetWidth-w-4);
 ctx.fillStyle='rgba(44,62,80,.93)';
 if(ctx.roundRect){ctx.beginPath();ctx.roundRect(bx,4,w,24,6);ctx.fill();}
 else ctx.fillRect(bx,4,w,24);
 ctx.fillStyle='#fff';ctx.fillText(txt,bx+9,20);}
$('chart').onmousemove=e=>{if(!HPTS)return;chart();
 const r=$('chart').getBoundingClientRect();drawHover(e.clientX-r.left);};
$('chart').onmouseleave=()=>{chart();};
/* ===== toast（替代 alert）与按钮内联二次确认（替代 confirm） ===== */
function toast(msg,kind){let box=$('toasts');
 if(!box){box=document.createElement('div');box.id='toasts';
  document.body.appendChild(box);}
 const t=document.createElement('div');t.className='toast '+(kind||'');
 t.textContent=msg;box.appendChild(t);
 setTimeout(()=>{t.classList.add('out');
  setTimeout(()=>{if(t.parentNode)t.remove();},350);},2600);}
async function api(act,msg){const b=event.target;
 if(!b.dataset.arming){                 /* 第一次点击：进入确认态 3s */
  b.dataset.arming='1';b.dataset.label=b.textContent;
  b.textContent='⚠ 再点一次确认';b.title=msg;b.classList.add('arming');
  setTimeout(()=>{if(b.dataset.arming){delete b.dataset.arming;
   b.textContent=b.dataset.label;b.classList.remove('arming');}},3000);
  return;}
 delete b.dataset.arming;b.textContent=b.dataset.label;b.title='';
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
function renderHealth(j){if(!j||!j.rounds||!j.rounds.length)return;
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
   return `<i class="hc ${c.s}" style="cursor:pointer" onclick="showLog('${p}','${r.ts}')" title="${r.ts}｜${he(det)}（点击查看日志）"></i>`;}).join('');
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
 $('pvMask').classList.add('on');}catch(e){toast('请求失败','err');}}
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
  if(!r.rows)return '<div class="pbar zero" title="'+tip+'"><i></i></div>';
  const segs=Object.keys(r.chans||{}).map(p=>{const c=r.chans[p];
   if(!c.rows)return'';
   return '<i class="seg pseg-'+p+'" style="height:'
    +Math.max(3,Math.round(c.rows/maxRows*100))+'%"></i>';}).join('');
  return '<div class="pbar" title="'+tip+'">'+(r.fails?'<i class="cap"></i>':'')+segs+'</div>';}).join('');
 $('pulseLegend').innerHTML=Object.keys(chans).map(p=>
  '<span><i class="pseg-'+p+'" style="width:12px;height:8px;border-radius:2px;display:inline-block;vertical-align:middle;margin-right:5px"></i>'+(PCN[p]||p)+'</span>').join('')
 +'<span><b style="background:var(--red)"></b>红帽 = 该轮有渠道失败</span>'
 +'<span style="margin-left:auto"><span class="kbd">R</span> 立即扫描 <span class="kbd">1</span>/<span class="kbd">2</span> 切视图 <span class="kbd">/</span> 搜索</span>';}
/* ===== 价格日历热力卡：跟随当前走势航线 ===== */
function renderCal(){const u=S.users[U];if(!u)return;
 const CR=curRoute();const cal=CR.r.cal||[];
 $('calTitle').textContent=CR.r.label||'';
 /* 7 天洞察统计：最低/均价/降价天数/当前距最低（数据源同走势与日历，零后端开销） */
 const h7=((CR.r.history7||{}).direct||[]).map(p=>p[1]).filter(v=>v>0);
 const d7=cal.slice(-7).map(c=>c[1]).filter(v=>v>0);
 if(h7.length){const mn=Math.min.apply(null,h7);
  const avg=d7.length?Math.round(d7.reduce((a,b)=>a+b,0)/d7.length)
            :Math.round(h7.reduce((a,b)=>a+b,0)/h7.length);
  let drops=0;for(let i=1;i<d7.length;i++)if(d7[i]<d7[i-1])drops++;
  const cur=h7[h7.length-1];
  $('calStats').textContent='近7天 最低 ￥'+mn+' · 日均 ￥'+avg
   +' · 降价 '+drops+' 天 · '+(cur<=mn?'当前即最低':'当前比最低高 '
   +Math.round((cur/mn-1)*100)+'%')+' · 绿=达标 红=超线';}
 else $('calStats').textContent='绿=达标 红=超线 · 悬停看明细';
 if(!cal.length){$('calcard').style.display='none';return;}
 $('calcard').style.display='';
 const th=(CR.r.th&&CR.r.th.direct)||0;
 let h='';
 for(const pair of cal){const d=pair[0],v=pair[1];
  let bg='var(--rowalt)',fg='var(--mut)';
  if(v>0&&th>0){const r=v/th;
   if(r<=1){const a=0.25+Math.min(0.6,(1-r)*2.2);
    bg='rgba(46,164,79,'+a.toFixed(2)+')';fg=a>0.55?'#fff':'var(--tx)';}
   else{const a=0.16+Math.min(0.6,(r-1)*2.2);
    bg='rgba(214,45,48,'+a.toFixed(2)+')';fg=a>0.5?'#fff':'var(--tx)';}}
  const tip=v>0?(th>0?(v<=th?d+' 直飞最低 ￥'+v+' · 已达标 ✅':d+' 直飞最低 ￥'+v+' · 超线 '+Math.round((v/th-1)*100)+'%'):d+' 直飞最低 ￥'+v):(d+' 无数据');
  h+='<div class="calcell" style="background:'+bg+';color:'+fg+'" title="'+tip+'">'
   +'<div class="cd">'+d+'</div><div class="cp">'+(v>0?'￥'+v:'—')+'</div></div>';}
 $('calgrid').innerHTML=h;}
/* ===== 达标浏览器通知 + 提示音（开关持久化；按 航线+类别+价格 去重） ===== */
let NT={on:localStorage.getItem('jpnotify')==='1',ctx:null};
function ntIcon(){const b=$('ntBtn');if(!b)return;
 b.textContent=NT.on?'🔔':'🔕';
 b.title=NT.on?'达标浏览器通知已开启（点击关闭）':'达标时浏览器通知+提示音（点击开启）';}
function togNotify(){NT.on=!NT.on;localStorage.setItem('jpnotify',NT.on?'1':'0');
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
 for(const x of s.users){
  const xd=x.best.direct,xt=x.best.transfer;
  if(xd&&x.th.direct&&xd.price<=x.th.direct&&(!kind||xd.price<price)){
   kind='直飞';price=xd.price;route=xd.route||x.routesTxt;}
  if(xt&&x.th.transfer&&xt.price<=x.th.transfer&&(!kind||xt.price<price)){
   kind='中转';price=xt.price;route=xt.route||x.routesTxt;}}
 if(!kind)return;
 const sig=route+'|'+kind+'|'+price;
 if(sig===localStorage.getItem('jpnlast'))return;
 localStorage.setItem('jpnlast',sig);
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
  $('pvMask').classList.add('on');}
 catch(e){toast('预览请求失败','err');}
 b.classList.remove('busy');}
function closePv(){$('pvMask').classList.remove('on');}
/* ===== 推送记录：钉钉发送存档回看（点条目展开全文；display 切换零插拔） ===== */
async function pushLog(){try{
 const r=await fetch('/api/pushlog');const j=await r.json();
 if(!j.ok){toast(j.err||'读取失败','err');return;}
 const items=j.items||[];
 $('pvTitle').textContent='📨 推送记录（最近 '+items.length+' 条）';
 $('pvBody').innerHTML=items.length?items.map(p=>
  `<div class="plitem" onclick="const d=this.nextElementSibling;d.style.display=d.style.display==='none'?'':'none'">`+
  `<span class="plts">${he(p.ts||'')}</span><span>${p.ok?'✅':'⚠️'}</span>`+
  `<span style="flex:1">${he(p.title||'')}</span></div>`+
  `<div class="pldesp" style="display:none">${renderDesp(p.desp||'')}</div>`).join('')
  :'<div class="muted" style="padding:14px">还没有推送存档——v3.0 起每次发送自动记录在这里</div>';
 $('pvMask').classList.add('on');}
 catch(e){toast('请求失败','err');}}
function mdInline(s){/* 先链接（[**粗体**](url) 链接可包粗体），再 **粗体**，@手机 高亮 */
 let t=he(String(s||''))
  .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g,'<a href="$2" target="_blank">$1</a>')
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
  else if(first.indexOf('### ')===0)h+=`<div class="md-h3">${mdInline(first.slice(4))}</div>`;
  else if(first.indexOf('## ')===0)h+=`<div class="md-h2">${mdInline(first.slice(3))}</div>`;
  else if(first.indexOf('# ')===0)h+=`<div class="md-h1">${mdInline(first.slice(2))}</div>`;
  else if(/^-{3,}$/.test(first.trim()))h+=`<hr class="md-hr">`;
  else if(first.indexOf('> ')===0)
   h+=`<div class="md-q">${bl.map(x=>mdInline(x.replace(/^>\s?/,''))).join('<br>')}</div>`;
  else if(/^[🟦🟩🟨⬜🟥]+$/.test(first.replace(/\s/g,'')))
   h+=`<div class="md-g">${he(first)}</div>`;
  else h+=`<div class="md-p">${bl.map(mdInline).join('<br>')}</div>`;}
 return h;}
/* ===== 移动端筛选抽屉 ===== */
function togFlt(){const f=document.querySelector('.fbar');if(f)f.classList.toggle('open');}
function updFltN(){const el=$('fltN');if(!el)return;
 let n=0;
 if(FLT.t1!=null||FLT.t2!=null)n++;
 if(FLT.a1!=null||FLT.a2!=null)n++;
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
restoreUI();load();setInterval(load,10000);setInterval(tick,1000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)load();});
/* Esc 收起展开的同班比价行 / 关闭推送预览弹层 */
document.addEventListener('keydown',e=>{if(e.key!=='Escape')return;
 if($('pvMask').classList.contains('on')){closePv();return;}
 if(EXP){EXP=null;_hideXrows();}});
/* V50 快捷键：1/2 切视图 · R 立即扫描（两段确认，防手滑） · / 聚焦搜索
   输入类控件聚焦时不劫持按键 */
let RUNARM=0;
function keyRun(){const now=Date.now();
 if(now-RUNARM>3000){RUNARM=now;toast('⚠ 再按一次 R 确认立即扫描全部航线','');return;}
 RUNARM=0;
 fetch('/api/run',{method:'POST'}).then(r=>r.json()).then(j=>{
  toast(j.ok?'✅ 已触发，页面自动刷新':'❌ 失败: '+(j.err||''),j.ok?'ok':'err');load();})
  .catch(()=>toast('❌ 请求失败','err'));}
document.addEventListener('keydown',e=>{
 /* Ctrl/Cmd+S：配置页保存（原生拦截，非输入态也可用） */
 if((e.ctrlKey||e.metaKey)&&(e.key==='s'||e.key==='S')){
  if(VIEW!=='cfg')return;e.preventDefault();saveCfg();return;}
 if(e.ctrlKey||e.altKey||e.metaKey)return;
 const t=e.target,tag=((t&&t.tagName)||'').toLowerCase();
 if(tag==='input'||tag==='select'||tag==='textarea'||(t&&t.isContentEditable))return;
 if(e.key==='1')switchView('mon');
 else if(e.key==='2')switchView('cfg');
 else if(e.key==='/'){if(VIEW!=='mon')switchView('mon');
  setTimeout(()=>{const q=$('fq');if(q){q.focus();q.select();}},0);
  e.preventDefault();}
 else if(e.key==='r'||e.key==='R')keyRun();});
/* 配置未保存守卫：dirty 徽标 + 关闭/刷新页面前确认（防手滑丢配置；全局项同守） */
function cfgIsDirty(){return CFG&&(JSON.stringify(CFG)!==CFG_CLEAN
 ||JSON.stringify(GLB)!==GLB_CLEAN);}
 setInterval(()=>{if(VIEW!=='cfg')return;   /* 监控页不空转 stringify 配置 */
  const dirty=cfgIsDirty();
  const n=dirty?cfgDirtyCount():0;
  const el=$('cfgDirty');if(el){el.style.display=dirty?'':'none';
   el.textContent='● '+n+' 处未保存的修改';}
  const sb=$('savebar');
  if(sb){sb.style.display=dirty?'flex':'none';
   const st=$('saveTxt');if(st)st.textContent=n+' 处未保存的修改';}
  /* 用户卡头各自的未保存标记（对比干净快照里的对应用户） */
  let cleanArr=null;
  try{cleanArr=JSON.parse(CFG_CLEAN||'[]');}catch(e){}
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
function applyTheme(){const t=localStorage.getItem('jptheme')||'auto';
 let dark=(t==='dark');
 if(t==='auto'){dark=window.matchMedia&&window.matchMedia('(prefers-color-scheme:dark)').matches;}
 document.documentElement.dataset.theme=dark?'dark':'light';
 const i=THEMES.findIndex(x=>x[0]===t);
 const b=$('themeBtn');if(b)b.textContent=THEMES[i][1];
 try{if(S&&S.users&&S.users.length)chart();}catch(e){}}
function cycleTheme(){const cur=localStorage.getItem('jptheme')||'auto';
 const i=THEMES.findIndex(x=>x[0]===cur);
 localStorage.setItem('jptheme',THEMES[(i+1)%3][0]);applyTheme();}
if(window.matchMedia)window.matchMedia('(prefers-color-scheme:dark)').addEventListener('change',applyTheme);
applyTheme();

/* ===== 配置视图 ===== */
let CFG=null,CITY={},VIEW='mon',CFG_CLEAN='',CFGQ='';
function switchView(v){VIEW=v;
 $('navMon').className=v==='mon'?'on':'';$('navCfg').className=v==='cfg'?'on':'';
 const el=$(v==='mon'?'monview':'cfgview');
 el.classList.remove('viewin');void el.offsetWidth;el.classList.add('viewin');
 $('monview').style.display=v==='mon'?'':'none';
 $('cfgview').style.display=v==='cfg'?'':'none';
 if(v==='cfg'&&!CFG)loadCfg();
 if(v==='cfg')loadLogin();}
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
    ?`<button class="btn2" style="border-color:#2ea44f;color:#1e8e3e" onclick="loginFinish('${p}')">✅ 我已登录完成</button>`
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
    ?'<label style="display:flex;align-items:center;gap:8px;margin-top:10px;font-size:13px;user-select:none;cursor:pointer">'
     +'<input type="checkbox" class="switch" id="'+id+'"'+(val?' checked':'')+' onchange="'+onch+'">'
     +'<span class="gsub" style="margin:0" id="'+id+'Txt">'+sub+'</span></label>'
    :'<div style="position:relative">'
     +'<input'+((type==='text'||type==='ro')?'':' type="number"')+' id="'+id+'" value="'+val+'"'
     +(type==='ro'?' readonly style="color:var(--mut);font-size:14px"':'')
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
  +'<button class="btn2" style="border-color:#f0b429;color:#b45309" onclick="saveCfg()">💾 保存全部并生效</button>'
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
  h+=glab('C','航线','ROUTES',(u.routes||[]).length+' 条航线监控中');
  (u.routes||[]).forEach((r,j)=>{
   h+=`<div class="rline" data-rk="${i}:${j}">
    <div class="rhead" role="button" onclick="foldRoute(this)"><span class="rtcode">${esc(r.from||'')}→${esc(r.to||'')}</span>
     <b>${esc(r.from_name)} → ${esc(r.to_name)}</b>
     <span class="muted">${esc((r.dates||[]).join('、'))}`
    +`${r.alert_direct>0?' · 直飞≤￥'+esc(r.alert_direct):''}`
    +`${r.alert_transfer>0?' · 中转≤￥'+esc(r.alert_transfer):''}`
    +`${(r.dep_time_min||r.dep_time_max)?' · '+(r.dep_time_min||'00:00')+'–'+(r.dep_time_max||'24:00')+' 出发':''}`
    +`</span><span class="chev open" style="margin-left:auto">▾</span><button class="danger" onclick="delRoute(${i},${j})">✕ 删除</button></div>
    <div class="srow"><div class="slab"><b>出发 → 到达城市</b><div class="shint">直接输中文城市名，支持 50 城联想</div></div><div class="sctl"><input list="citydl" style="width:108px" value="${esc(r.from_name)}" onchange="setRoute(${i},${j},'from_name',this.value)"><span class="sunit">→</span><input list="citydl" style="width:108px" value="${esc(r.to_name)}" onchange="setRoute(${i},${j},'to_name',this.value)"></div></div>
    <div class="srow"><div class="slab"><b>心理价 · 直飞 / 中转</b><div class="shint">低于此价即触发 🚨 强提醒（0=关）；中转还须满足到达约束</div></div><div class="sctl"><span class="sunit">￥</span><input type="number" min="0" step="10" style="width:88px" value="${esc(r.alert_direct||0)}" onchange="setRoute(${i},${j},'alert_direct',this.value)"><span class="sunit">/</span><span class="sunit">￥</span><input type="number" min="0" step="10" style="width:88px" value="${esc(r.alert_transfer||0)}" onchange="setRoute(${i},${j},'alert_transfer',this.value)"></div></div>
    <div class="srow"><div class="slab"><b>中转最晚到达</b><div class="shint">次日该时刻前到达的中转才算达标</div></div><div class="sctl"><input type="time" value="${esc(r.transfer_arrival_max||'02:00')}" onchange="setRoute(${i},${j},'transfer_arrival_max',this.value)"></div></div>
    <div class="srow"><div class="slab"><b>出发时段窗口</b><div class="shint">只关注该窗口内起飞的航班，两端留空 = 不限</div></div><div class="sctl"><input type="time" value="${esc(r.dep_time_min||'')}" onchange="setRoute(${i},${j},'dep_time_min',this.value)"><span class="sunit">→</span><input type="time" value="${esc(r.dep_time_max||'')}" onchange="setRoute(${i},${j},'dep_time_max',this.value)"></div></div>
    <div class="srow"><div class="slab"><b>出发日期</b><div class="shint">逗号分隔；多个日期各自独立监控与推送</div></div><div class="sctl" style="flex:1;min-width:0"><input placeholder="2026-10-01,2026-10-05" style="width:100%;text-align:left" value="${esc((r.dates||[]).join(','))}" onchange="setDates(${i},${j},this.value)"></div></div>
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
    <div class="hint"><a href="https://ntfy.sh" target="_blank" style="color:var(--blue)">ntfy.sh</a> 免费无需注册，手机装 App 订阅同名主题即收。</div></div>
   <div class="chcard${((u.notifier||{}).aliyun||{}).enabled?' on':''}" data-ch="aliyun"><div class="chhead" role="button" onclick="foldCh(this)"><span class="lgdot${((u.notifier||{}).aliyun||{}).enabled?' on':''}"></span>阿里云电话/短信<span class="muted">${((u.notifier||{}).aliyun||{}).enabled?'已启用':'未启用'}</span><span class="chev open" style="margin-left:auto">▾</span></div>
    <div class="srow"><div class="slab"><b>云监控事件回调 URL</b><div class="shint">留空关闭；云监控 CRITICAL 事件触发电话/短信</div></div><div class="sctl" style="flex:1;min-width:0"><input style="width:100%;text-align:left" value="${esc(((u.notifier||{}).aliyun||{}).url||'')}" onchange="setAy(${i},'url',this.value);chSync(this,${i},'aliyun')"></div></div>
    <div class="srow"><div class="slab"><b>AccessKey ID / Secret</b><div class="shint">建议只授云监控只读权限，仅存本机 config.yaml</div></div><div class="sctl"><input autocomplete="off" placeholder="ID" style="width:110px" value="${esc(((u.notifier||{}).aliyun||{}).user||'')}" onchange="setAy(${i},'user',this.value)"><input autocomplete="off" type="password" placeholder="Secret" style="width:110px" value="${esc(((u.notifier||{}).aliyun||{}).password||'')}" onchange="setAy(${i},'password',this.value)"></div></div>
    <div class="hint">达标时拨打一次，风暴不重复。</div></div>
   <div class="chcard${((u.notifier||{}).serverchan||{}).enabled?' on':''}" data-ch="serverchan"><div class="chhead" role="button" onclick="foldCh(this)"><span class="lgdot${((u.notifier||{}).serverchan||{}).enabled?' on':''}"></span>Server酱·微信<span class="muted">${((u.notifier||{}).serverchan||{}).enabled?'已启用':'未启用'}</span><span class="chev open" style="margin-left:auto">▾</span></div>
    <div class="srow"><div class="slab"><b>SendKey</b><div class="shint">微信扫码获取；留空关闭</div></div><div class="sctl" style="flex:1;min-width:0"><input type="password" autocomplete="off" placeholder="sct.ftqq.com 微信扫码获取" style="width:100%;text-align:left" value="${esc(((u.notifier||{}).serverchan||{}).send_key||'')}" onchange="setSc(${i},'send_key',this.value);chSync(this,${i},'serverchan')"></div></div>
    <div class="srow"><div class="slab"><b>通道</b><div class="shint">留空 = 默认通道</div></div><div class="sctl"><input style="width:140px" value="${esc(((u.notifier||{}).serverchan||{}).channel||'')}" onchange="setSc(${i},'channel',this.value)"></div></div>
    <div class="hint">钉钉之外的微信触达备份：Server酱·Turbo 免费每日 5 条，
    <a href="https://sct.ftqq.com" target="_blank" style="color:var(--blue)">sct.ftqq.com</a> 扫码即得 SendKey。凭据仅存本机。</div></div>
   </div>
   <button class="danger" onclick="delUser(${i})">✕ 删除用户 ${esc(u.name)}</button></div></div>`;});
 $('cfgform').innerHTML=h;
 $('cfgglobals').innerHTML=gh;
 applyFolds();
 if(CFGQ)cfgFilter(CFGQ);}
/* ===== V100 子卡折叠：分区(A-D)/航线卡/通道卡 点击标题行收展。
   display 切换零 DOM 插拔（翻译/比价扩展免疫）；状态 localStorage 记忆。
   默认态：分区展开、航线卡与通道卡收起（标题行已含关键摘要） ===== */
let FOLD={sec:{},route:{},ch:{}};
try{const _f=JSON.parse(localStorage.getItem('jpcfgfold'));if(_f)FOLD=_f;}catch(e){}
FOLD.sec=FOLD.sec||{};FOLD.route=FOLD.route||{};FOLD.ch=FOLD.ch||{};
function saveFold(){localStorage.setItem('jpcfgfold',JSON.stringify(FOLD));}
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
function foldRoute(rh){if(event.target.closest('.danger'))return;
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
function setDates(i,j,v){CFG[i].routes[j].dates=v.split(/[,，]/).map(s=>s.trim()).filter(Boolean);}
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
function defDate(){const d=new Date(Date.now()+14*864e5);
 return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');}
function cfgErr(m){/* 校验失败提示必达：页面顶部 cfgmsg + 右下 toast 双通道 */
 $('cfgmsg').textContent=m;toast(m,'err');}
async function saveCfg(){
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
/* ===== V50 配置搜索：字段级过滤（fgrid/qgrid 直接子块），容器按可见子块收敛；
   buildForm 重建后按 CFGQ 重放，搜索状态不丢 ===== */
function cfgFilter(qraw){const q=(qraw||'').trim().toLowerCase();
 const hits=$('cfgHits');if(!q){hits.textContent='';
  document.querySelectorAll('#cfgview .fgrid>div,#cfgview .qgrid>div,'
   +'#cfgview .glgrid>div,#cfgview .tog,#cfgview .rline,#cfgview .chcard,'
   +'#cfgview .srow,#cfgview .frow,#cfgview .row,#cfgview .grouplab')
   .forEach(el=>{el.style.display='';el.style.boxShadow='';});
  showCfgPanel(CFGPANEL,true);applyFolds();return;}
 /* 搜索态：全部分区临时可见（子卡临时全开），只留命中字段 */
 document.querySelectorAll('#cfgmain .cfpanel').forEach(p=>{p.style.display='';});
 expandFolds();
 let n=0;
 document.querySelectorAll('#cfgview .fgrid>div,#cfgview .qgrid>div,'
  +'#cfgview .glgrid>div,#cfgview .tog,#cfgview .srow').forEach(d=>{
  const m=(d.textContent||'').toLowerCase().includes(q);
  d.style.display=m?'':'none';
  d.style.boxShadow=m?'0 0 0 2px rgba(26,115,232,.4)':'';
  if(m)n++;});
 document.querySelectorAll('#cfgview .frow,#cfgview .row').forEach(el=>{
  if(el.closest('.rline'))return;
  const m=(el.textContent||'').toLowerCase().includes(q);
  el.style.display=m?'':'none';if(m)n++;});
 document.querySelectorAll('#cfgview .rline,#cfgview .chcard').forEach(rl=>{
  const vis=Array.from(rl.querySelectorAll('.fgrid>div,.qgrid>div,.tog'))
   .some(d=>d.style.display!=='none');
  rl.style.display=vis?'':'none';});
 document.querySelectorAll('#cfgview .grouplab').forEach(g=>{g.style.display='';});
 hits.textContent=n?('✓ '+n+' 项匹配'):'无匹配项';}
/* ===== V50 配置导入/导出：本地 JSON 直拷（含钉钉等凭据，本机自管） ===== */
function exportCfg(){
 try{const blob=new Blob([JSON.stringify({users:CFG,globals:GLB},null,2)],
  {type:'application/json'});
  const a=document.createElement('a');
  a.href=URL.createObjectURL(blob);
  a.download='ticket-monitoring-config-'
   +new Date().toISOString().slice(0,10)+'.json';
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
<style>
 :root{--bg:#eceff4;--card:#ffffff;--tx:#141f2b;--mut:#66788a;--line:#dde3ea;
       --line2:#cbd4de;--blue:#0b62d6;--green:#0e8345;--okbg:#e9f4ec;
       --num:"Cascadia Mono","Consolas","SF Mono","Menlo",monospace;--r:14px}
 *{box-sizing:border-box}
 html{color-scheme:light}
 @media(prefers-color-scheme:dark){:root{--bg:#0a0f16;--card:#101823;--tx:#dbe4ee;
   --mut:#7f92a6;--line:#1e2a3a;--line2:#2a3a50;--okbg:#12241a}}
 body{font-family:"Segoe UI Variable Text","Segoe UI","Microsoft YaHei","PingFang SC",sans-serif;
      margin:0;background:var(--bg);color:var(--tx)}
 .top{display:flex;align-items:center;gap:10px;padding:12px 18px;background:var(--card);
      border-bottom:1px solid var(--line2);position:sticky;top:0;z-index:5}
 .logo{width:26px;height:26px;border-radius:7px;background:var(--tx);color:var(--bg);
       display:inline-flex;align-items:center;justify-content:center;font-size:13px}
 .top b{font-size:12px;letter-spacing:1.2px;text-transform:uppercase}
 .wrap{max-width:680px;margin:0 auto;padding:22px 18px}
 .hitbar{display:flex;align-items:center;gap:10px;background:var(--okbg);
      border:1px solid rgba(14,131,69,.35);border-radius:12px;padding:12px 16px;margin-bottom:16px}
 .hitbar b{color:var(--green);font-size:14px}
 .card{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:18px 22px}
 .md h1{font-size:19px;margin:6px 0 14px;line-height:1.5}
 .md .h2{font-size:15px;color:var(--blue);margin:16px 0 8px;font-weight:700}
 .md .h3{font-size:13.5px;margin:12px 0 6px;font-weight:700}
 .md p{margin:7px 0;line-height:1.85;font-size:14px}
 .md a{color:var(--blue)}
 .md .g{letter-spacing:2px;font-size:15px}
 .md b{font-variant-numeric:tabular-nums}
 .md img{max-width:100%;border-radius:10px;border:1px solid var(--line);display:block;margin:10px 0}
 .foot{margin-top:16px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px}
 .foot a{color:var(--blue);font-size:13px}
 .ts{color:var(--mut);font-size:12px;font-variant-numeric:tabular-nums}
</style></head><body>
<div class="top"><span class="logo">✈️</span><b>机票监控 · 达标通知</b></div>
<div class="wrap">
 <div class="hitbar"><b>🚨 已达标——可出手</b><span id="ts" class="ts" style="margin-left:auto"></span></div>
 <div class="card md" id="md"></div>
 <div class="foot">
  <a id="console" href="/">打开完整控制台 →</a>
  <span class="ts">点系统弹窗直达本页 · 数据仅存本机</span>
 </div>
</div>
<script>
const N=__PAYLOAD__;
document.getElementById("ts").textContent=N.ts||"";
document.title=(N.title||"达标通知")+" · 机票监控";
/* 横幅随内容如实变化：非达标通知（如"通知不存在"）不冒充达标 */
(function(){const hb=document.querySelector(".hitbar"),hbB=hb.querySelector("b");
 if((N.title||"").indexOf("达标")>=0){hbB.textContent="🚨 已达标——可出手";return;}
 hbB.textContent=N.title||"通知";
 hb.style.background="var(--card)";hb.style.borderColor="var(--line)";
 hbB.style.color="var(--tx2)";})();
function esc(s){return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;")}
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
 if(t.indexOf("### ")===0){const d=document.createElement("div");d.className="h3";d.innerHTML=inline(t.slice(4));md.appendChild(d);return}
 if(t.indexOf("## ")===0){const d=document.createElement("div");d.className="h2";d.innerHTML=inline(t.slice(3));md.appendChild(d);return}
 if(t.indexOf("# ")===0){const d=document.createElement("h1");d.innerHTML=inline(t.slice(2));md.appendChild(d);return}
 if(/^-{3,}$/.test(t)){const d=document.createElement("hr");md.appendChild(d);return}
 if(t.indexOf("> ")===0){const d=document.createElement("p");d.style.cssText="border-left:3px solid var(--blue);padding:4px 12px;margin:6px 0;color:var(--mut)";d.innerHTML=inline(t.slice(2));md.appendChild(d);return}
 if(/^[🟦🟩🟨⬜🟥]+$/.test(t.replace(/\\s/g,""))){const d=document.createElement("div");d.className="g";d.textContent=t;md.appendChild(d);return}
 const p=document.createElement("p");p.innerHTML=inline(t);md.appendChild(p)})
document.getElementById("console").href=location.origin+"/"
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
    已验证主路径同源（链接必须点开有数据；qunar 为 PC 页非 touch H5）。"""
    try:
        from types import SimpleNamespace
        from core.alerter import Alerter
        ns = SimpleNamespace(from_code=(rr or {}).get("from", ""),
                             from_name=(rr or {}).get("from_name", ""),
                             to_code=(rr or {}).get("to", ""),
                             to_name=(rr or {}).get("to_name", ""))
        return Alerter._build_view_url(None, ns, date or "",
                                       plat or "qunar")
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
        "dep_time_min": d.get("dep_time_min", "") or "",
        "dep_time_max": d.get("dep_time_max", "") or "",
    }


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
    db = (st.cfg.get("output") or {}).get("db_path", "data/prices.db")
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
    for r in rows:
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
    # 近期明细补位：当轮缺明细的平台用近 6h 成功明细
    try:
        recent = recent_platform_flights(
            db, route.get("from", ""), route.get("to", ""),
            (route.get("dates") or [""])[0], hours=6)
        have = {f.get("_platform") for f in flights}
        for p, (age, fl) in recent.items():
            if p in have:
                continue
            for f in fl:
                if isinstance(f, dict) and "price" in f:
                    if not Alerter._stale_sane(f):
                        continue
                    g = dict(f)
                    g["_platform"] = p
                    g["_stale_h"] = round(age, 1)
                    g["_pair"] = (route.get("from", ""), route.get("to", ""))
                    if _keep(g):
                        flights.append(g)
    except Exception:
        pass
    out = []
    for f in flights:
        transfer = bool(f.get("transCity"))
        try:
            price = round(float(f["price"]))
        except (TypeError, ValueError):
            price = f["price"]
        # 多航线：每行明细按其所属航线的阈值判达标
        rr = _rr_of(f)
        qd = float(rr.get("alert_direct", 0) or 0)
        qt = float(rr.get("alert_transfer", 0) or 0)
        qam = rr.get("transfer_arrival_max", "02:00") or "02:00"
        qual = (not transfer and qd and price <= qd) or (
            transfer and qt and price <= qt
            and Alerter._arrival_ok(f, qam))
        rt_label = (f"{rr.get('from_name','')}→{rr.get('to_name','')}"
                    if len(routes) > 1 else "")
        thv = qt if transfer else qd
        view = _view_url(rr, f.get("depDate", ""),
                         f.get("_platform") or "qunar")
        # 近达标：未达标但距线 10% 以内（表格琥珀提示，扫读一眼看出快到了）
        near = (not qual and thv > 0 and 0 < (price - thv) / thv <= 0.10)
        from core.flightnorm import cabin_text as _ct, normalize as _fnorm
        _fnorm(f, f.get("depDate", ""))  # 幂等兜底：demo 等未过汇聚点的路径
        out.append({
            "price": price, "transfer": transfer, "name": f.get("name", ""),
            "code": f.get("code", ""),
            "cabinT": _ct(f), "layoverT": f.get("layoverT", ""),
            "depTime": f.get("depTime", ""), "arrTime": f.get("arrTime", ""),
            "date": f.get("depDate", ""),
            "trans": f.get("transCity", ""), "cross": f.get("crossDayDesc", ""),
            "route": rt_label,
            "dur": f.get("totalDuration") or "",
            "durM": _dur_min(f.get("totalDuration")),
            "plat": Alerter.PLATFORM_CN.get(f.get("_platform", ""), ""),
            "platKey": f.get("_platform", ""),
            "stale": round(f["_stale_h"]) if f.get("_stale_h") else 0,
            "qual": qual, "near": near, "view": view,
        })
    directs = [f for f in flights if not f.get("transCity")]
    # 中转到达约束按各自航线（原实现拿 routes[0] 的 am 一刀切——多航线混串）
    def _am_of(f):
        rr = _rr_of(f)
        return rr.get("transfer_arrival_max", "02:00") or "02:00"

    oks = [f for f in flights if f.get("transCity")
           and Alerter._arrival_ok(f, _am_of(f))]

    def _best_brief(f):
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
        view = _view_url(rr, f.get("depDate", ""),
                         f.get("_platform") or "qunar")
        return {"price": f["price"], "name": f.get("name", ""),
                "depTime": f.get("depTime", ""), "arrTime": f.get("arrTime", ""),
                "trans": f.get("transCity", ""),
                "cross": f.get("crossDayDesc", ""),
                "route": label, "view": view, "th": th_v}

    hist = _rounds(db, route.get("from", ""), route.get("to", ""),
                   (route.get("dates") or [""])[0], am)
    h_d = [[t.strftime("%m-%d %H:%M"), d] for t, d, _ in hist if d]
    h_t = [[t.strftime("%m-%d %H:%M"), x] for t, _, x in hist if x]
    # 多航线走势：每 (航线,日期) 一条序列，前端图上切着看（原来只画第一条）
    routes_arr, seen_rd = [], set()
    for r in routes:
        am_r = r.get("transfer_arrival_max", "02:00") or "02:00"
        for d0 in r.get("dates") or [""]:
            if (r["from"], r["to"], d0) in seen_rd:
                continue
            seen_rd.add((r["from"], r["to"], d0))
            try:
                hist_r = _rounds(db, r["from"], r["to"], d0, am_r)
            except Exception:
                hist_r = []
            rd = [[t.strftime("%m-%d %H:%M"), v] for t, v, _ in hist_r if v]
            rt_ = [[t.strftime("%m-%d %H:%M"), v] for t, _, v in hist_r if v]
            # 7 天序列（范围切换）+ 14 天价格日历（热力卡）
            try:
                hist7 = _rounds(db, r["from"], r["to"], d0, am_r, hours=168)
            except Exception:
                hist7 = []
            r7d = [[t.strftime("%m-%d %H:%M"), v] for t, v, _ in hist7 if v]
            r7t = [[t.strftime("%m-%d %H:%M"), v] for t, _, v in hist7 if v]
            try:
                cal = _daily_minima(db, r["from"], r["to"], d0, am_r, days=14)
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
                           if directs else None)
    xt_brief = _best_brief(min(oks, key=lambda f: f["price"])
                           if oks else None)

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
        # 不再拿全局最低价配 routes[0] 的线（跨航线虚报）
        "hit": any(f["qual"] for f in out),
    }


_STATE_CACHE = {"sig": None, "payload": None}


def _latest_state():
    """全量状态；按 (DB 文件, mtime_ns, size, 用户配置摘要, 版本) 签名缓存。

    控制台每 10s 轮询本端点——轮间 DB 不变时此前每次都全量重算
    （extra JSON 逐条解析 + 每航线×日期 走势/日历多查询）。配置摘要取
    users 的 JSON 哈希（Route 对象经 default=str 进 repr，阈值改动即换签），
    不用对象 id（CPython id 复用会让热重载后撞上旧签名返回脏缓存）。"""
    st = _State
    db = (st.cfg.get("output") or {}).get("db_path", "data/prices.db")
    sig = None
    try:
        sst = os.stat(db)
        users = st.users or []
        sig = (db, sst.st_mtime_ns, sst.st_size,
               hash(json.dumps(users, default=str, ensure_ascii=False)),
               st.version)
    except OSError:
        pass
    if sig is not None and _STATE_CACHE["sig"] == sig:
        return _STATE_CACHE["payload"]
    users = st.users or [{"name": "default", "routes": st.cfg.get("routes") or []}]
    states = [_user_state(u) for u in users if u.get("routes")]
    # 更新时间取 DB 最新一条
    import sqlite3 as sq
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
    _STATE_CACHE["sig"] = sig
    return out


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
    db = (st.cfg.get("output") or {}).get("db_path", "data/prices.db")
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
    p = a._digest_payload(built, fresh=True, with_tables=False)
    return {"ok": True, "title": p["title"], "desp": p["desp"],
            "hits": len(p["hits"]), "user": u.get("name", "")}


_HEALTH_CACHE = {"sig": None, "payload": None}


def _health_state(hours: int = 24) -> dict:
    """渠道健康时间线：解析 monitor.log（尾部 2MB 封顶，防长日志拖慢）。

    按日志 (路径, mtime_ns, size) 签名缓存——控制台每 10s 轮询，
    轮间日志不变时不再重复解析 2MB 日志。"""
    from core.health import parse_health
    logp = ((_State.cfg or {}).get("output") or {}).get(
        "log_path", "logs/monitor.log")
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
    logp = ((_State.cfg or {}).get("output") or {}).get(
        "log_path", "logs/monitor.log")
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
        elif self.path.startswith("/notify/"):
            # Windows 弹窗点击直达：单条达标详情（轻页，非控制台）
            try:
                import json as _j
                import os as _os
                import re as _re2
                nid = _re2.sub(r"[^A-Z0-9]", "",
                               self.path[len("/notify/"):].split("?")[0])
                data = None
                d = "data/notify"
                if DEMO["on"]:
                    data = {"nid": "NDEMO",
                            "title": "🚨 达标 上海→乌鲁木齐 09/25",
                            "desp": "# 🚨 已达标——可出手\n\n"
                                    "## ✈️ 上海→乌鲁木齐 2026-09-25\n\n"
                                    "[**直飞 ￥1468**](https://flight.qunar.com/site/oneway_list.htm?searchDepartureAirport=%E4%B8%8A%E6%B5%B7&searchArrivalAirport=%E4%B9%8C%E9%B2%81%E6%9C%A8%E9%BD%90&searchDepartureTime=2026-09-25&nextNDays=0&startSearch=true&fromCode=SHA&toCode=URC&from=flight_dom_search)"
                                    " ｜ 线 1600 ｜ 已低于线 ￥132\n\n"
                                    "🟦⬜⬜⬜⬜\n\n"
                                    "乌鲁木齐→上海 10/06 · 国航CA1295 21:10-02:35 +1天",
                            "ts": "（演示数据）"}
                elif nid:
                    p = _os.path.join("data/notify", nid + ".json")
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
                self.send_header("Content-Length", str(len(body)))
                self.send_header("ETag", etag)
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
                    self._json({"ok": True, "items": [
                        {"ts": "2026-09-10 09:00:02", "ok": True,
                         "title": "🚨 达标！乌→上 10/04 直飞￥1580｜乌→上 10/04",
                         "desp": "# 🚨 已达标——可出手\n\n"
                                 "## ✈️ 乌鲁木齐→上海 2026-10-04（17:00后出发）\n\n"
                                 "[**直飞 ￥1580**](https://example.com)\n\n"
                                 "线 1600 ｜ 差 -20 (-1%)\n\n"
                                 "🟦🟦⬜⬜⬜\n\n> 💡 ✅ 直飞已破线 ￥20，建议立即出手"},
                        {"ts": "2026-09-10 08:45:03", "ok": True,
                         "title": "❌ 全部未达标｜最近 上→乌 09/25 直飞差￥130｜上→乌 09/25",
                         "desp": "# ❌ 3 条航线全部未达标\n\n"},
                        {"ts": "2026-09-10 08:30:00", "ok": False,
                         "title": "❌ 全部未达标｜上→乌 09/25",
                         "desp": "# ❌ 3 条航线全部未达标\n\n"},
                    ]})
                    return
                import os as _os
                items = []
                p = "logs/push_history.jsonl"
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
    try:
        srv = _Srv(("127.0.0.1", port), _Handler)
        _State.srv = srv
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        _State.logger.info("[控制台] http://127.0.0.1:%d （随监控常驻）", port)
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
            srv = _Srv(("127.0.0.1", int(port)), _Handler)
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
    ap.add_argument("--port", type=int, default=8765)
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
