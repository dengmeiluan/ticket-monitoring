# -*- coding: utf-8 -*-
"""伴生本地控制台（多租户版）：纯标准库 HTTP 服务（127.0.0.1），随监控常驻

页面能力：每用户状态卡与仪表 / 多航线可切走势图（canvas 自绘+悬停十字线）/
航班明细表（日期列·筛选·排序·同班跨渠道比价展开）/ 下轮倒计时 /
智能刷新（响应不变不重渲染，页面隐藏暂停）/ 一键立即扫描一轮、一键推送走势报告。
"""
import gzip
import hashlib
import json
import logging
import os
import re
import sqlite3
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from core.alerter import (Alerter, _qual_price, FLIGGY_TAX_PAD,
                          xchan_phantom_idx, NEAR_RATIO)
from report import _rounds, recent_platform_flights, _daily_minima

# 仓库根锚定（CWD 漂移免疫家族，与 main._SENT_PATH 同族收口）：
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
   图表擦除）在此同样直取终值 */
const RM=window.matchMedia&&window.matchMedia('(prefers-reduced-motion:reduce)').matches;
/* 主题预置（与 NOTIFY 轻页同款）：渲染前落 data-theme 防暗色首屏白闪——
   主题落位脚本不得放 body 末尾，否则暗色用户每次打开先闪一屏白 */
(function(){var t='auto';try{t=localStorage.getItem('jptheme')||'auto'}catch(e){}
 var dark=t==='dark'||(t!=='light'&&window.matchMedia
   &&window.matchMedia('(prefers-color-scheme:dark)').matches);
 document.documentElement.dataset.theme=dark?'dark':'light';})();
</script>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ctext y='0.9em' font-size='90'%3E%E2%9C%88%EF%B8%8F%3C/text%3E%3C/svg%3E">
<title>机票监控台</title>
<style>
 /* ===== 「签派控制台」设计语言：数字即主角（mono）、hairline 分区、扁平精密仪表 ===== */
 :root{--blue:#0b62d6;--orange:#c96a10;--red:#c22a2e;
       --green:#0e8345;     /* 与推送图达标绿 C_QUAL 同值（跨端同色同义），改必双端同步（report.py） */
       --okrgb:14,131,69;   /* 绿档通道令牌：rgba(var(--okrgb),α) 消费（描边/底/晕全谱），暗色随 #43c072 换谱 */
       --bg:#eceff4;--card:#ffffff;--tx:#141f2b;--mut:#5a6c7d;--tx2:#3d4e5f;
       --line:#dde3ea;--line2:#cbd4de;--grid:#b8c2cf;--headbg:#eef2f7;--hover:#e8edf3;--rowalt:#f5f8fb;
       --tgbar:#6f8090;       /* r258 U1：改期微图普通日数据柱专档（原借 --line2 边框令牌对行底 1.41:1 <3:1 非文字图形档）→ 对 rowalt 3.8:1；.tgb.cheap/.lo 绿档与 .cur 蓝描边语义态不随此令牌 */
       --ctlbd:#7d8fa0;       /* r259 U1：交互控件边界专档（表单件边框/开关 off 轨/描边钮原借 --line/--line2 容器 hairline 对衬底 1.08-1.66 双主题 <3:1 非文字图形档）→ 亮对 rowalt 3.1/card 3.3（WCAG 精算）；hover/focus 提档链不随此令牌（.fbar 等表单件 hover --mut 更强、.tg hover --blue、描边钮 hover 换底）；容器分区/装饰 hairline 不随此令牌（--line/--line2 语义保留） */
       --stl:#a84c15;--okbg:#e9f4ec;--warn:#8a6c00;--okzone:rgba(var(--okrgb),.14);
       /* --stl 消费点唯一（.stl.lay 衔接警示小字），与推送图 LAY_SHORT 同值
          （跨端同色同义，report.py，改必双端同步）；对 card/rowalt 双主题过 AA */
       --ok-txt:#0b6e39;      /* P2-3：okbg 底绿词面加深（--green 对 okbg 4.28:1 欠 AA）→ 5.63:1；消费 .pill.ok/.hbadge.ok/.upill.ok 小字 */
       --orange-txt:#a45508;  /* r230 P2-2：文字级橙令牌（--orange 对白卡 3.78 全站正文级最低）→ 5.41:1；消费 .kpi.t .num 主数字（12px 小字已收 --ok-txt 族，主角同律） */
       --warn-deep:#6f5600;   /* P2-3：琥珀小标（.chip .bd.mid）加深（--warn 对 headbg 4.42:1 欠 AA）→ 6.21:1；仍琥珀=擦边语义不换谱 */
       --maint:#9b7ede;--maint-soft:rgba(155,126,222,.35);  /* P2-7：维护纹紫令牌（.hc.maint/.hlh 两处消费防改一漏一） */
       --chip-on-warn:#ffe9b8;--chip-on-red:#ffe0e1;--chip-on-mut:#dfe8f2;  /* P2-8 设令牌 / P2-2 提亮：.bd 基线 opacity .9 税曾把选中底拉到 3.28~3.98（10px 需 4.5）——warn 4.72/4.69、red 4.56/4.53、mut 4.55/4.52（双主题删税后全过） */
       --at-bg:#ffd24d;--at-fg:#7a4b00;   /* @手机高亮双令牌（.md-at 消费）：硬编码曾暗色不换谱 */
       --warn-rgb:138,108,0;   /* 琥珀 RGB 令牌（随 C_NEAR 加深过 AA）：rgba(var(--warn-rgb),α) 消费，暗色随 #d9b34a 换谱 */
       --warnbd:rgba(var(--warn-rgb),.45);--warnbg:rgba(var(--warn-rgb),.10);--xzone:rgba(var(--warn-rgb),.13);
       --redbd:rgba(194,42,46,.32);--redbdh:rgba(194,42,46,.55);--redbg:rgba(194,42,46,.08);
       --thline:#8a6d1f;   /* 中转达标虚线：与 --orange 曲线异色可分（图例同源） */
       --cal-best-stroke:rgba(255,255,255,.8);   /* 日历「近期最低」描边在真达标绿底格上的配色（同绿=零对比隐形）；暗色随块换深墨 */
       --fill:#0b62d6;--fill2:#1d6fd8;          /* 实心选中底：暗色换深蓝保白字对比；P2-1 顶带收深（#2f83ea 渐变顶带白字 4.25 欠 → #1d6fd8 全带 ≥4.86） */
       --fill-t:#b05a00;                        /* 实心选中底·橙系（中转 tag）：白字 11px 需 ≥4.5:1 */
       --blue-rgb:11,98,214;   /* 蓝 RGB 令牌：rgba(var(--blue-rgb),α) 消费（ring/glow/cdt.run/cfgflash/glcell focus），暗色随 #63a4f8 换谱 */
       --ring:rgba(var(--blue-rgb),.14);--glow:rgba(var(--blue-rgb),.45);
       --c-qunar:#2f7fe0;--c-fliggy:#c2661a;--c-ctrip:#0f8f8f;
       --c-tongcheng:#8250df;--c-tuniu:#a87b16;   /* 渠道识别色：全组件同谱；亮色飞猪/途牛加深至非文字 3:1+（r235 P2-2，暗色 7.8+ 本过不动） */
       --sh1:0 1px 2px rgba(20,31,43,.05);
       --sh2:0 6px 18px -6px rgba(20,31,43,.12);
       --sh3:0 16px 40px -12px rgba(20,31,43,.22);
       --sh-knob:0 1px 2px rgba(0,0,0,.25);   /* 开关圆点浮起微阴影（不随主题，浮起阴影通用）；r239 P3-2 裸值收口 */
       --sh-pop:0 18px 50px rgba(16,24,40,.35);   /* 弹层卡重阴影（遮罩语境单值，暗色底上同形自然）；r239 P3-2 裸值收口 */
       --r:14px;--r2:11px;--r3:9px;--r10:10px;--pill:999px;   /* 全胶囊家族单源（P2-C：.tag/.switch/.hbadge/.upill/.mchip/CTA 六处 20/18/999px 三写法并轨）；--r10=容器瓦片档（.tw/.fbar/.cdt/mtab/savebar/pldesp/notify 框，与 --r3 交互件档分立） */
       --r-xs:2px;--r-sm:5px;   /* 微件圆角两档（r239 P3-1 收口：色票/健康格/脉冲柱/键帽/滚动条 thumb/TG 柱顶）；1px 毛发档与 4/6/8px 特意值不入族（并入即改外观） */
       --ls1:1px;--ls2:2px;--ls05:.5px;   /* 微型标签字距三档单源：--ls1=正文级微签（11px 系），--ls2=装饰英文签（.seclab .en/.grouplab .en），--ls05=11-14px 胶囊/代码的半像素档（.seclab .zh/.tag/.pseclab/.rtcode）；15px 展示性大字距与品牌 h1、mono 数字负字距不入族 */
       --kpiw:min(1168px,100%);   /* KPI/脉冲区限宽单源：流式封顶 1168
                                     （原 992 固定值在 1366/1280
                                     主流本留 ~150px 右空腔，100% 流式
                                     后卡内跟随容器宽、多档免维护） */
       --num:"Cascadia Mono","Consolas","SF Mono","Menlo",monospace}
 *{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
 /* 原生控件（time/checkbox/滚动条）跟随页面主题，不随系统深浅漂移 */
 html{color-scheme:light}
 html[data-theme="dark"]{
  color-scheme:dark;
  --bg:#0a0f16;--card:#101823;--tx:#dbe4ee;--mut:#7f92a6;--tx2:#a9b9ca;
  /* dark 专用件色令牌（r239 P3-3：游离 hex 收口防漂移）——
     --danger-solid=暗色警示红实底（arming 按钮/筛选角标，#ef5350 白字
     欠 AA 的深档替身）；--demo-*/--ver-*=演示条/版本横幅暗色三件套 */
  --danger-solid:#b3393c;
  --demo-bg:#2b2413;--demo-tx:#e8c96a;--demo-bd:#4d4021;
  --ver-bg:#33191a;--ver-tx:#ffb4b4;--ver-bd:#5c2d2d;
  --line:#1e2a3a;--line2:#2a3a50;--grid:#35465f;--headbg:#141d2a;--hover:#182430;--rowalt:#0f1722;
  --tgbar:#58768f;       /* 普通日柱暗谱（对暗 rowalt 3.7:1） */
  --ctlbd:#56718c;       /* 交互控件边界暗谱（对暗 card 3.5 WCAG 精算）；hover/focus 提档链 --mut 暗 #7f92a6 更强 */
  --blue:#63a4f8;--orange:#e6922e;--red:#ef5350;--green:#43c072;--stl:#e08555;--okbg:#12241a;
  --ok-txt:#43c072;--warn-deep:#d9b34a;--orange-txt:#e6922e;   /* 成对换谱（P2-3）：暗底原值已过 AA，外观不变；--orange-txt 同律=暗 --orange 本值 */
  --maint:#9b7ede;--maint-soft:rgba(155,126,222,.35);  /* 维护纹紫暗色同值（紫纹本就双主题通读） */
  --at-bg:rgba(255,210,77,.16);--at-fg:#ffd24d;   /* @手机高亮暗谱：降饱和暗底+原亮字 */
  --okrgb:67,192,114;   /* 同谱 #43c072：与 tr.qual 暗色覆写 rgba(67,192,114,…) 同源 */
  --okzone:rgba(67,192,114,.16);   /* 走势图例色票/canvas 区间填充：暗底提一档可辨 */
  --warn:#d9b34a;--thline:#d4b75c;
  --warn-rgb:217,179,74;   /* 同谱 #d9b34a：与亮色 --warn-rgb 成对换谱 */
  --cal-best-stroke:rgba(10,15,22,.55);   /* 日历 best×qhit 叠加态描边暗色换深墨（白描边对暗色浅绿底弱对比） */
  --warnbd:rgba(var(--warn-rgb),.50);--warnbg:rgba(var(--warn-rgb),.12);--xzone:rgba(var(--warn-rgb),.10);
  --redbd:rgba(239,83,80,.38);--redbdh:rgba(239,83,80,.62);--redbg:rgba(239,83,80,.10);
  --fill:#2c67ba;--fill2:#3771c4;   /* 暗色实心底用深蓝：白字对比 ≥4.5:1（--blue 太浅）；P2-1 顶带收深（#3f82d8 顶带 4.32 欠 → #3771c4 4.86） */
  --fill-t:#8a5f10;                 /* 暗色橙系实心底：#e6922e 白字仅 2.47:1 不达标 */
  --blue-rgb:99,164,248;   /* 同谱 #63a4f8：与亮色 --blue-rgb 成对换谱 */
  --ring:rgba(var(--blue-rgb),.2);--glow:rgba(var(--blue-rgb),.32);
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
 html{scroll-padding-top:72px;scrollbar-gutter:stable}   /* 72px 为全带宽被置尾分带块接替的基础兜底（≤540/≤760/761+ 各带末块按源码序覆盖，任何视口不可达）——补偿值改动在各带块做，勿改此处 */
 /* scrollbar-gutter:stable：viewport 滚动条槽常驻——弹层锁滚
    （body overflow:hidden）摘滚动条时内容不再横移 ~17px（健康格/
    推送预览弹层「开合闪烁」的机械根因）；老内核不识别该属性，
    由 _openPvMask 的 JS 宽度补偿兜底 */
 header{background:var(--card);border-bottom:1px solid var(--line2);color:var(--tx);
        padding:9px 18px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;
        position:sticky;top:0;z-index:50;box-shadow:var(--sh2);
        margin:0 -18px 4px}
 /* 用户实报:header 右区两行堆叠(pill 行+meta 行)参差臃肿——
    单行同轴:按钮组+pill+倒计时+更新时间一条水平轴;≤540 物理宽度下限
    meta 才独占行(右对齐),541-900 同行装得下,header 恒两行 */
 .hdx{display:flex;align-items:center;gap:10px;min-width:0}
 .hdmeta{display:inline-flex;align-items:center;gap:8px;font-size:12px;
         color:var(--mut);white-space:nowrap;min-width:0}
 @media(max-width:900px){
  .hdx{flex-wrap:wrap;justify-content:flex-end;row-gap:4px}}
 /* ≤540 的 hdmeta 独占行声明在源码后部 ≤540 断点块内（断点块置尾
    纪律：同断点声明集中于其后，避免拆散多个 max-width:540 块） */
 header h1{margin:0;font-size:14px;font-weight:700;letter-spacing:1.2px;
           display:flex;align-items:center;gap:10px;text-transform:uppercase}
 .logo{width:30px;height:30px;border-radius:var(--r3);flex:none;
       background:var(--tx);color:var(--card);
       display:inline-flex;align-items:center;justify-content:center;font-size:15px}
 .pill{font-size:13px;font-weight:700;background:var(--headbg);color:var(--tx2);
       padding:6px 14px;border-radius:var(--r3);border:1px solid var(--line);
       display:inline-flex;align-items:center;gap:8px;font-variant-numeric:tabular-nums;
       cursor:pointer}
 /* 状态 pill 可点（jumpQual 直达「仅达标」明细），hover 提亮 affordance；
    静态线索（审计 P2-6）：尾 ▸ 微箭头——仅 hover 提亮与不可点状态
    pill 视觉同形，常态给静态可点线索 */
 .pill:hover{filter:brightness(1.07)}
 .pill::after{content:'▸';font-size:10px;opacity:.55;line-height:1}
 /* 灰点随 --mut 中性令牌（原亮暗同值硬编码灰最后残留一枚） */
 .pill::before{content:'';width:7px;height:7px;border-radius:50%;background:var(--mut);flex:none}
 .pill.ok{background:var(--okbg);color:var(--ok-txt);border-color:rgba(var(--okrgb),.35)}
 .pill.ok::before{background:var(--green);animation:pulse 1.8s ease-in-out infinite}
 @keyframes pulse{0%,100%{box-shadow:0 0 0 0 rgba(var(--okrgb),.45);opacity:1}
                  50%{box-shadow:0 0 0 4px rgba(var(--okrgb),0);opacity:.55}}
 .muted{color:var(--mut);font-size:12px;font-weight:500}
 /* 分区标签：编号 + 中文 + 英文小签（签派台分区语言）；
     P2-6：margin/border-bottom/padding-bottom 死声明删除——
    全站 8 处消费全为 .inline（167 全量覆写），基础态无生产点 */
 .seclab{display:flex;align-items:baseline;gap:9px}
 .seclab .no{font-family:var(--num);font-size:11px;color:var(--mut);letter-spacing:var(--ls1)}
 .seclab .zh{font-size:14px;font-weight:700;letter-spacing:var(--ls05)}
 .seclab .en{font-size:10px;letter-spacing:var(--ls2);color:var(--mut);text-transform:uppercase}
 /* 卡内嵌用：脱掉分区条的边距与底线（曾 7 处复制内联，收编于此） */
 .seclab.inline{margin:0;border:none;padding:0}
 .ucard{background:var(--card);border:1px solid var(--line);border-radius:var(--r);
        padding:15px 18px;margin:0 0 12px;box-shadow:none;transition:border-color .2s}
 .ucard:hover{border-color:var(--line2)}
 .kpi{transition:transform .15s,border-color .2s,background .2s;border:1px solid var(--line);
      border-radius:var(--r2);padding:13px 16px;position:relative;overflow:hidden;background:var(--card)}
 /* 整卡可点：有行情链接（numlink）的卡加 clk 类整卡打开同目标，
    卡内数字链接保留（点击锚点不重复开窗）；无链接卡不显 pointer。
    卡带 role="link"+tabindex="0"+Enter 键开（注释修正：旧注
    「role 已删」失实，link 语义与键盘可达已并存，见 kpi 渲染处） */
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
 .uname{font-size:15px;font-weight:700;letter-spacing:.3px}  /* 人名字距独立档：15px 展示性大字距不入 --ls05 族（同 h1 品牌对语义） */
 .udot{width:9px;height:9px;border-radius:50%;display:inline-block;margin-right:7px;
   background:var(--line2);vertical-align:1px}
 .udot.hit{background:var(--green);animation:hitpulse 1.6s ease-in-out infinite}
 .uroutes{color:var(--mut);font-size:12px}
 .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));
       gap:12px;margin-top:10px}
 /* 1fr 轨道填满容器：KPI 双卡左缘与卡内下方 statline/mchips 全宽贴边
    对齐；460px 上限+居中曾让概览恒 2 卡整体内缩错位 */
 .kpi .lab{font-size:11px;color:var(--mut);letter-spacing:var(--ls1)}
 /* fb 行统一 19px 地板：徽章（bagtag/stoptag inline-block）行高 19、
    纯文本行 16，跨日期组两卡曾差 3px 节奏——min-height 归一 */
 .kpi .fb{color:var(--tx2);font-size:12px;margin-top:2px;min-height:19px}
 /* fb 行词组粒度防断词：CJK 无断词边界逐字折行，「经郑州」曾折成
    「经郑/州」孤字（P1-1，768 档两组中转卡必现）——
    中转城市段整词 nowrap，空间不足时整段掉行不断字 */
 .nw{white-space:nowrap}   /* 词组粒度 nowrap 全局工具类（r246 自容器限定放宽：stl 机场段/航向+走势入口、ssub 用时段、pvfoot 末段新消费点同律——容器限定版曾是局部约定，全站消费点全为显式标注的语义词组，无误伤面） */
 .xrow td{background:var(--xzone);color:var(--tx2);font-size:12px;white-space:normal}
 .erow td{padding:34px 16px;text-align:center;color:var(--mut);font-size:13px;letter-spacing:.02em}
 .bagtag{display:inline-block;margin-left:6px;padding:1px 7px;border-radius:var(--r3);
   border:1px solid var(--green);color:var(--ok-txt);font-size:11px;font-weight:600;
   vertical-align:1px}   /* 字面 --ok-txt：qual tint 底上 --green 4.28 欠 AA，描边非文字走 --green */
 .stoptag{display:inline-block;margin-left:6px;padding:1px 7px;border-radius:var(--r3);
   border:1px solid var(--mut);color:var(--mut);font-size:11px;font-weight:600;
   vertical-align:1px}
 .xind{display:inline-block;margin-right:5px;color:var(--tx2);font-size:12px;line-height:1;vertical-align:1px}
 .xind::before{content:'▸';display:inline-block;transition:transform .15s ease-out,color .15s ease-out}
 tr[aria-expanded="true"] .xind::before{transform:rotate(90deg);color:var(--blue)}
 .stl.lay.ok{color:var(--ok-txt)}   /* 衔接达标小字：qual tint 底 --green 4.34 欠 AA，同 --ok-txt 族收编 */
 /* 衔接「停X」小字：下限已配置且未达=警示色，达标 .ok 覆写为绿；
    下限未配置（=0）无警示语义，渲染式不落 .lay（走 .stl 基类中性灰） */
 .stl.lay{color:var(--stl)}
 .kpi .num{font-family:var(--num);font-size:clamp(24px,2.4vw,31px);font-weight:600;margin:3px 0 1px;
           letter-spacing:-1px;font-variant-numeric:tabular-nums}
 .kpi.d .num{color:var(--blue)}.kpi.t .num{color:var(--orange-txt)}
 /* 达标卡数字随语义转绿（绿卡上蓝/橙大数字信号混杂）；文字级令牌
    同律（r230 P2-2：--green 对白卡 4.28 与 12px 小字档位不齐） */
 .kpi.hit .num{color:var(--ok-txt)}
 /* 空日期卡占位破折号弱化（r256 P3-4）：40% 透明大号「—」与相邻
    31px 大数字不再对比突兀，空卡不显残缺；说明行语义不变 */
 .kpi .num.em{opacity:.4}
 .bar{height:6px;border-radius:4px;background:var(--line);overflow:hidden;margin-top:6px}
 .bar i{display:block;height:100%;border-radius:4px}/* width transition 已死：innerHTML 整卡重建，过渡从不触发 */
 .kpi.d .bar i{background:var(--blue)}
 .kpi.t .bar i{background:var(--orange)}
 .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:4px}
 button,input,select,textarea{font-family:inherit}   /* 表单件落 UA 默认字体族（Arial）与全站体系断裂 */
 button{background:linear-gradient(180deg,var(--fill2),var(--fill));color:#fff;border:none;
        border-radius:var(--r3);padding:9px 17px;font-size:13px;font-weight:600;cursor:pointer;
        transition:.15s;box-shadow:0 1px 3px var(--glow)}
 button:hover{filter:brightness(1.1);box-shadow:0 3px 10px var(--glow)}
 button:active{box-shadow:none}
 button.warn{background:var(--card);color:var(--blue);border:none;
        box-shadow:inset 0 0 0 1px var(--ctlbd),var(--sh1);font-weight:600}
 button.warn:hover{background:var(--headbg);filter:none;
        box-shadow:inset 0 0 0 1px var(--ctlbd),var(--sh2)}
 canvas{width:100%;height:clamp(240px,max(38vh,28vw),360px);display:block}   /* 高度取大（r236 P1-1 重落）：r235 旧式的取小语义对名目标带零实效——1024-1919 宽短带 28vw 恒大于 38vh、取小恒落在 38vh（1440×700 仍 1246×266=4.68:1），且窄高窗反向变矮（760×900 342→240）。取大语义：宽短带真正抬升到 360 上限、窄高窗复原 38vh、横短屏由 clamp 下限 240 承载（竖屏手机 38vh 主导）；≥1920 仍走 42vh 专带 */
 #chart{cursor:pointer}   /* C-1：画布可点=看该轮明细（cursor affordance） */
 .legend{display:flex;gap:16px;font-size:12px;color:var(--mut);margin-top:6px;flex-wrap:wrap}
 /* 图例分组缝（r256 美感1）：lgDirect/lgTrans=数据系列、lgZone 起=
    阈值参考组，「行情 vs 阈值」扫读分组（16px 基础 gap+14px=30px 缝） */
 .legend #lgZone{margin-left:14px}
 .legend b{display:inline-block;width:18px;height:4px;border-radius:var(--r-xs);vertical-align:middle;margin-right:5px;box-shadow:inset 0 0 0 1px var(--line)}
 .tabs{display:flex;gap:6px;margin:10px 0;align-items:center;flex-wrap:wrap}
 .tabs span{padding:6px 14px;border-radius:var(--r3);cursor:pointer;font-size:12px;
   background:var(--headbg);color:var(--mut);border:1px solid var(--line);
   font-weight:600;transition:.15s;user-select:none}
 .tabs span:hover{color:var(--tx2);background:var(--hover)}
 .tabs span.on{background:var(--fill);color:#fff;border-color:transparent;
   box-shadow:0 2px 8px -2px var(--glow)}
 /* 用户切换 chip（审计 P2-1）：montabs 吸顶条右端深滚自救位——
    视觉随 .tabs span 全局，此处只加右推+长名截断（溢出省略，
    防「超长用户名把 4 个 tab 挤出横滚视野」） */
 .tabs .uchip{margin-left:auto;flex:0 0 auto;max-width:44vw;overflow:hidden;
   text-overflow:ellipsis;white-space:nowrap}
 .tw{overflow:auto;max-height:clamp(430px,52vh,780px);border-radius:var(--r10);border:1px solid var(--line);position:relative}
 /* 明细表内横滚提示（审计 P2-2）：390/768 档右侧时长/中转/渠道列
    不可见且触屏滚动条自动隐藏，截断文本是唯一线索——右缘渐变与
    xhint 机制同轨（#montabs/#montab-details .tabs 先例），可滚才点亮 */
 .tw::after{content:'';position:absolute;top:0;right:0;bottom:0;width:12px;
  pointer-events:none;opacity:0;background:linear-gradient(90deg,transparent,var(--card));
  transition:opacity .15s}
 .tw.xhint::after{opacity:1}
 table{border-collapse:collapse;width:100%;font-size:13px;background:var(--card)}
 th{position:sticky;top:0;background:var(--headbg);color:var(--tx2);font-weight:600;
    font-size:11px;letter-spacing:var(--ls1);z-index:3}
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
 tr.qual td.price{color:var(--ok-txt);font-weight:800}   /* --green 对绿 tint 底 4.19~4.35:1 欠 AA（13px/800 非大字）→ --ok-txt 5.18~6.36 全过；P2-3 同族收编 */
 html[data-theme="dark"] tr.qual{background:rgba(67,192,114,.13)}
 /* qual 行内 .stl 子行（--mut）对绿 tint 底 4.48 擦线差 0.02：暗色单点
    提亮（不动全局 --mut 影响面；亮色 4.7 全过不动）；.stoptag 同底同
    词色同病成对收编（P2-1，4.48:1 差 0.02） */
 html[data-theme="dark"] tr.qual .stl,
 html[data-theme="dark"] tr.qual .stoptag{color:#8ba0b4}
 /* 衔接达标小字是 .ok 语义绿档非中性子行，豁免上一条提亮灰（与
    推送 PNG 达标行停时绿同语言）；特异度 (0,4,0) 压 (0,3,2) */
 html[data-theme="dark"] tr.qual .stl.lay.ok{color:var(--ok-txt)}
 /* .mdat 日期副字同族漏收补齐（r239 WebUI 审计 P2-1）：其基础规则
    #ftable .mdat 带 ID 特异性 (1,1,0)，恒压类选择器组 (0,3,2)——
    覆写须同带 ID（LESSONS 十四§4 同族判例）；规则本体在窄屏媒体块，
    仅移动卡可见面有对比度暴露 */
 html[data-theme="dark"] #ftable tr.qual .mdat{color:#8ba0b4}
 html[data-theme="dark"] tr.qual:hover{background:rgba(67,192,114,.2)}
 .tag{border-radius:var(--pill);padding:3px 10px;font-size:11px;color:#fff;font-weight:600;
   letter-spacing:var(--ls05)}
 .pdot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;
   vertical-align:1px;background:var(--mut)}
 .pdot.qunar{background:var(--c-qunar)}.pdot.fliggy{background:var(--c-fliggy)}
 .pdot.ctrip{background:var(--c-ctrip)}.pdot.tongcheng{background:var(--c-tongcheng)}
 .pdot.tuniu{background:var(--c-tuniu)}
 .t-d{background:var(--fill)}.t-t{background:var(--fill-t)}   /* 直飞蓝/中转橙色相语义不变，实心底换高对比对：tag 白字 11px 暗/亮两主题 ≥4.5:1（--blue/--orange 直用曾暗色 2.5:1） */
 .price{font-weight:800;font-family:var(--num);letter-spacing:-.3px}
 .price .fire{display:inline-block;width:19px;text-align:left;white-space:nowrap}   /* 达标🔥定宽占位：qual 行与非 qual 行￥共起点（首扫读列数位共线） */
 /* 时刻/日期/时长/中转列数字即主角（补中转列 8：
    「停1h20m 二段 14:05」数字混排，mono 对表扫读更整齐） */
 #ftable tbody td:nth-child(3),#ftable tbody td:nth-child(5),
 #ftable tbody td:nth-child(6),#ftable tbody td:nth-child(7),
 #ftable tbody td:nth-child(8){
  font-family:var(--num);letter-spacing:-.2px}
 nav{display:inline-flex;gap:4px;background:var(--card);border:1px solid var(--line);
     border-radius:var(--r10);padding:4px;box-shadow:var(--sh1);margin:14px 0}   /* 容器瓦片档统一 10px（P2-6：12px 双轨并轨，同 .tw/.fbar/.demoBar/.verbar/.pldesp） */
 nav span{padding:7px 20px;border-radius:var(--r3);cursor:pointer;font-size:13px;
          color:var(--mut);font-weight:600;transition:.15s;user-select:none}
 nav span:hover{color:var(--tx)}
 nav span.on{background:var(--fill);color:#fff;
          box-shadow:0 2px 8px -2px var(--glow)}
 .subsec{font-size:11px;letter-spacing:var(--ls1);color:var(--mut);margin:13px 0 7px;
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
    「白色方块内一个灰圆」的畸形（用户实锤：开关分散零散） */
 .srow .sctl input:not(.switch){height:34px;padding:0 12px;border:1px solid var(--ctlbd);
   border-radius:var(--r3);background:var(--card);color:var(--tx);font-size:13px;
   box-sizing:border-box;transition:border-color .15s,box-shadow .15s}
 .srow .sctl input:not(.switch):hover{border-color:var(--mut)}
 .srow .sctl input:not(.switch):focus{outline:none;border-color:var(--blue);
   box-shadow:0 0 0 3px var(--ring);transition:box-shadow 0s}   /* 环即时呈现（th.srt r221 P2-6 同族）：基座 .15s 淡入让 Tab 巡航滞后 */
 .srow .sctl input[type=number]{width:96px;text-align:right;
   font-family:var(--num);font-variant-numeric:tabular-nums}
 .srow .sctl input[type=time],.srow .sctl input:not([type]){width:118px}
 .srow .sctl input[type=time]{text-align:center;padding:0 8px}
 .srow .sctl .btn2{height:34px}
 .sunit{color:var(--mut);font-size:11px;font-family:var(--num)}
 .switch{appearance:none;-webkit-appearance:none;width:36px;height:20px;
   border-radius:var(--pill);background:var(--ctlbd);position:relative;cursor:pointer;
   transition:background .18s;flex:none;margin:0;vertical-align:middle;
   color:inherit;border:none} /* UA 纯黑 color/border 残留收口（appearance:none
   后均无笔画消费，零视觉影响——语义色只从 var 取纪律的记录项归零） */
 .switch:checked{background:var(--green)}
 .switch:hover{filter:brightness(1.07)}
 .switch::after{content:'';position:absolute;left:3px;top:3px;width:14px;height:14px;
   border-radius:50%;background:#fff;transition:transform .18s;
   box-shadow:var(--sh-knob)}
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
 .rbadge{color:var(--warn);font-weight:700;font-size:11px;white-space:nowrap}
 .danger{color:var(--red);cursor:pointer;font-size:12px;font-weight:600;
        border:1px solid var(--redbd);background:transparent;border-radius:var(--r3);
        padding:5px 12px;transition:.15s}
 .danger:hover{background:var(--redbg);border-color:var(--redbdh)}
 .btn2{background:var(--card);color:var(--blue);border:1px solid var(--ctlbd);border-radius:var(--r3);
       padding:6px 14px;font-size:12px;font-weight:600;cursor:pointer;
       box-shadow:var(--sh1);margin-right:6px;transition:.15s}
 .btn2:hover{background:var(--headbg);box-shadow:var(--sh2)}
 .btn2:active{transform:scale(.97)}
 button.busy{opacity:.6;pointer-events:none}
 /* busy 转圈替代 ⏳ emoji（与 mono 精密仪表语言一致；RM 下全局
    animation:none 自动降级为静止环） */
 button.busy::after{content:'';width:11px;height:11px;margin-left:6px;
  border:2px solid var(--mut);border-top-color:transparent;border-radius:50%;
  display:inline-block;vertical-align:-2px;animation:spin .8s linear infinite}
 @keyframes spin{to{transform:rotate(360deg)}}
 .fbar{margin:8px 0;padding:10px 12px;background:var(--rowalt);border-radius:var(--r10)}
 .frow{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
 .frow+.frow{margin-top:8px}
 #chartRoutes{margin:6px 0}
 /* 空筛选行不再吃间距（单航线/单日期下 datechips/routechips 空置） */
 .frow:empty{display:none}
 #chartRoutes:empty{display:none}
 .chiplab{font-size:12px;color:var(--mut)}
 /* 「⇅日期」排序 chip（≤760 显示，桌面有表头入口）：箭头由
    data-dir 属性驱动 content——排序点击只 setAttribute 零 childList
    变更（扩展 MutationObserver 免疫预置律，LESSONS 十二§3） */
 .srtchip{display:none}
 .srtchip .arr::after{content:"\200B"}
 .srtchip[data-dir="asc"] .arr::after{content:"↑"}
 .srtchip[data-dir="desc"] .arr::after{content:"↓"}
 /* 筛选行开关标签：与 srow 开关同款 .switch（禁用裸 checkbox 形态脱队） */
 .flab{display:inline-flex;gap:8px;align-items:center;font-size:12px;
   color:var(--tx2);cursor:pointer;user-select:none}
 /* 时段挡位分组：标签与挡位绑死不可拆行（窄屏 flex-wrap 曾把「到达时段：」
    标签留在上行末尾、挡位掉到下一行=视觉断裂，用户截图实锤） */
 .wingrp{display:inline-flex;align-items:center;gap:6px;white-space:nowrap;
   flex:none}
 .winsel{display:inline-flex;gap:5px}
 /* 概览多日期分组：日期小标 + 该日期直飞/中转两卡（10-5/10-6 并排可对比） */
 .dgroup{margin-bottom:10px}
 .dgroup:last-child{margin-bottom:0}
 .dlab{font-size:11px;font-weight:700;letter-spacing:var(--ls1);color:var(--mut);
   margin:2px 0 6px;font-family:var(--num)}
 .chip{padding:4px 12px;border-radius:var(--r3);cursor:pointer;font-size:12px;
   background:var(--headbg);color:var(--mut);border:1px solid var(--line);
   user-select:none;font-weight:600;transition:.15s}
 .chip:hover{background:var(--hover);color:var(--tx2)}
 .chip.on{background:var(--fill);color:#fff;border-color:transparent;
   box-shadow:0 2px 8px -2px var(--glow)}
 .chip .pdot{margin-right:5px;vertical-align:0}
 .chip.on .pdot{background:#fff;opacity:.9}
 .chip .bd{font-style:normal;font-size:10px;margin-left:4px}   /* P2-2：删 opacity:.9 税（选中底含税 3.28~3.98 欠 AA，10px 需 4.5；未选中族同步升档全过） */
 /* 出发日期 chips：✕ 悬停显形（常态半隐不抢视觉，删除是低频操作） */
 .dchip .dx{font-style:normal;margin-left:6px;opacity:.45;cursor:pointer;
   font-size:11px;transition:.15s}
 .dchip .dx:hover{opacity:1;color:#fff}
 /* 隐藏真 date 控件：仅供 📅 按钮唤原生日历（showPicker），不占视觉 */
 .dreal{position:absolute;width:0;height:0;opacity:0;pointer-events:none;
   border:0;padding:0}
 /* 时段快捷挡：srow 内小号 chip（复用 chip 视觉语言，尺寸贴 time 输入） */
 .schip{padding:4px 9px;border-radius:var(--r3);font-size:11px}
 .chip .bd.mid{color:var(--warn-deep)}.chip .bd.old{color:var(--red)}
 .chip .bd.non{color:var(--mut)}
 .chip.on .bd.mid{color:var(--chip-on-warn)}.chip.on .bd.old{color:var(--chip-on-red)}
 .chip.on .bd.non{color:var(--chip-on-mut)}
 .fbar label{font-size:12px;color:var(--tx2);display:flex;align-items:center;gap:5px;white-space:nowrap}
 .fbar select,.fbar input[type=text],.fbar input[type=time]{
   height:30px;padding:0 9px;border:1px solid var(--ctlbd);border-radius:var(--r3);
   font-size:12px;background:var(--card);color:var(--tx);
   transition:border-color .15s,box-shadow .15s}
 .fbar select:hover,.fbar input:hover{border-color:var(--mut)}
 .fbar select:focus,.fbar input:focus:not(.switch){outline:none;border-color:var(--blue);
   box-shadow:0 0 0 3px var(--ring);transition:box-shadow 0s}   /* :not(.switch) 豁免——开关 UA 焦点环被剥离后 box-shadow 14% 微晕不可辨（.srow 299 同律）；0s=环即时呈现（r221 P2-6 同族） */
 th.srt{cursor:pointer;user-select:none}
 th.srt:hover{background:var(--hover)}
 th.srt.on{color:var(--blue)}
 /* 次行小字（舱位·准点·餐食/二段时刻）：中性灰——曾挂 --stl 衔接警示
    色，--stl 改暗橙红后误伤（次行小字非警示语义，收口） */
 .stl{color:var(--mut);font-size:11px;font-weight:400}
 /* 航班列 .stl 子行（舱位·准点·餐食）允许换行：td 的 nowrap 会被继承
    把子行挤出列宽；只放开子行，主行保持 nowrap。
    词组段豁免（.stl.nw 0,2,1 压本条 0,1,1）：机场名段/航向+走势入口
    整词包 nw——放开换行的容器里仍守词组粒度不断字 */
 td .stl{white-space:normal}
 td .stl.nw{white-space:nowrap}
 /* 数字等宽：价格/时刻列对齐，扫读不跳 */
 table,.kpi .num,.mchip b{font-variant-numeric:tabular-nums}
 /* 达标态：进度条转绿 + 文案 */
 .bar i.ok{background:linear-gradient(90deg,var(--green),rgba(var(--okrgb),.55))!important}
 .bar i.near{background:linear-gradient(90deg,var(--warn),rgba(var(--warn-rgb),.55))!important}   /* 擦边琥珀：与明细 near 描边/推送 🟨 同语言 */
 .okTxt{color:var(--ok-txt);font-weight:600}   /* 唯一消费点在 .kpi.hit okbg 底（12px），--ok-strong 3.80:1 欠 AA → --ok-txt 亮 5.63/暗 6.98 双过 */
 /* 较上轮涨跌：降=绿 涨=红 持平=灰 */
 .dn{color:var(--ok-txt);font-weight:600}   /* --ok-strong 白卡 4.21/okbg 3.73 欠 AA → --ok-txt（亮 6.36/okbg 5.63，暗 10.0），同族最后一枚 */
 .up{color:var(--red);font-weight:600}
 html[data-theme="dark"] .up{color:#ff8a8c}
 /* 明细行：直达链接 + 擦边琥珀 */
 a.vw{color:var(--blue);text-decoration:none;font-weight:400;margin-left:5px;
      font-size:12px;border:1px solid var(--line);border-radius:var(--r3);padding:0 3px}
 a.vw:hover{background:var(--hover)}
 /* 明细行→走势页内跳转（结构性建议：跳转图谱唯一缺口，
   行尾 📈 与 ↗ 外链成对；触控热区同 vw 家族） */
 .tj{color:var(--blue);font-size:12px;margin-left:4px;border:1px solid var(--line);
     border-radius:var(--r3);padding:0 3px;cursor:pointer;user-select:none}
 .tj:hover{background:var(--hover)}
 /* 擦边琥珀：--warn=#8a6c00 与推送图 C_NEAR 同值（跨端同色同义；
    曾挂 --stl，其改暗橙红后擦边色跨端失配，收口；
     随 C_NEAR 加深过一次；再次随 C_NEAR 加深
    （白卡 4.97:1/斑马行 4.65:1 过 AA），暗色 --warn 不动） */
 td.price.near{color:var(--warn);font-weight:800}
 /* 行情破线第四档（与总表图 🟩 同语言）：实绿回退；支持描边时空心绿 */
 .price.brk{color:var(--green)}
 @supports (-webkit-text-stroke:1px #000){.price.brk{color:transparent;
  -webkit-text-stroke:1.1px var(--green)}
  /* 斑马行描边提档：--green 空心绿对斑马底 4.526:1 余量 0.026 擦线
     （字体/内核渲染漂移即翻车）——斑马域单点提文字档 --ok-txt
     （对斑马 5.4，hover 回白卡底用同色只是更稳，无视觉断层） */
  #ftable tbody tr.zebra:not(:hover) .price.brk{-webkit-text-stroke-color:var(--ok-txt)}
  /* 角标描边豁免：transparent+描边作用到整格（stroke 为继承属性），
     格内全部 span 角标（税前/黑卡价/⚠资格价/⚠孤低价/🔥/退改费等）
     统一撤描边——按格内子 span 通配而非逐类枚举，防后续新徽标同病
     复发；.pretax 无自身 color 规则的透明继承另补灰字（内联 warn 色
     与 emoji 不受扰） */
  #ftable td.price.brk span{-webkit-text-stroke:0}
  #ftable td.price.brk .pretax{color:var(--mut)}}
 /* 表格斑马纹（长表扫读不串行；xrow 展开行不参与）——
    行间夹隐藏 xrow 使 nth-child(even) 永落空，改按数据行序号显式 .zebra */
 #ftable tbody tr.zebra:not(:hover){background:var(--rowalt)}
 /* KPI 价格可点（直达去哪儿） */
 a.numlink{color:inherit;text-decoration:none;position:relative}
 a.numlink:hover{text-decoration:underline}
 /* 触控热区外扩（家族同律）：28px 字高+垂直外扩 8px=36px 触控地板 */
 a.numlink::after{content:'';position:absolute;inset:-4px -4px}
 #ftable tbody tr:focus-visible{box-shadow:inset 0 0 0 2px var(--blue);outline:none}
 /* 配置页航线摘要头：单行制——截图中「中转≤￥1700 被挤折行+基线参差」
    根治：nowrap 不折行 + align-items:center 统一控件中线；右侧操作组
    （折叠箭/开关/复制/删除）margin-left:auto 永远贴右；摘要溢出省略号 */
 .rhead{display:flex;gap:10px;align-items:center;flex-wrap:nowrap;margin-bottom:4px}
 .rhead .muted{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
 .rhead .rop{display:flex;gap:8px;align-items:center;margin-left:auto;flex:none}
 .ropbtn{background:var(--card);color:var(--blue);border:1px solid var(--ctlbd);
        border-radius:var(--r3);padding:5px 10px;font-size:12px;font-weight:600;
        cursor:pointer;transition:.15s;white-space:nowrap;flex:none;
        box-shadow:var(--sh1)}
 .ropbtn:hover{background:var(--headbg);box-shadow:var(--sh2)}
 /* 渠道最低价 chips（替代长串文本） */
 .mchip{display:inline-block;padding:4px 11px;border-radius:var(--pill);background:var(--headbg);
        color:var(--mut);font-size:12px;user-select:none;border:1px solid var(--line);
        transition:border-color .15s,transform .15s}
 .mchip:hover{border-color:var(--mut);transform:translateY(-1px)}
 .mchip b{font-weight:700;margin-left:2px;font-family:var(--num)}
 .mchip.best{background:var(--fill);color:#fff;border-color:transparent;
        box-shadow:0 2px 8px -2px var(--glow)}   /* -2px spread 与 .chip.on/.tabs .on 同态（P2-6 补齐） */
 .mchip.best .pdot{background:#fff;opacity:.9}
 /* 可点渠道胶囊：真实 affordance（hover 上浮必须可点，上浮却不可点=虚假 affordance） */
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
      color:var(--mut);border-radius:var(--r10);padding:2px 10px;font-size:11px;
      font-family:var(--num);font-variant-numeric:tabular-nums}
 .cdt.run{background:rgba(var(--blue-rgb),.12);color:var(--blue);border-color:transparent}
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
 /* CTA 块级化独立成行（空态 hero）：inline 排曾吊在 ol 右侧半高处，
    块级居中与 390 档自然换行形制对齐 */
 .hero button{display:block;margin:14px auto 0}
 footer{margin:22px 0 10px;text-align:center;font-size:12px}
 footer a{color:var(--blue)}
 /* 键盘可达性（统一 2px 蓝环；[role="button"] 一揽子覆盖 mkact 收编元素）。
    环走 box-shadow：真实内核键盘 Tab 下站点 outline 环会被 UA 焦点环
    系统性接管（主按钮白字蓝底 3px 白环≈隐形焦点），box-shadow 不在
    接管范围；focus 环替换常态投影是可接受视觉代价（环主导） */
 button:focus-visible,.chip:focus-visible,nav span:focus-visible,.tabs span:focus-visible,
 .cnav:focus-visible,.rngchip:focus-visible,.hbtn:focus-visible,[role="button"]:focus-visible,
 a.vw:focus-visible,a.numlink:focus-visible,.kpisum a:focus-visible,#foot a:focus-visible,
 .demoBar a:focus-visible,.verbar a:focus-visible,.pvbody a:focus-visible,
 #chart:focus-visible,.kpi.clk:focus-visible{   /* clk 整卡可点带 tabindex（收编全站蓝环） */
  box-shadow:0 0 0 2px var(--blue);outline:none;
  transition:box-shadow 0s}   /* 环即时呈现（审计 P2-6）：基座 .15s transition 曾把焦点环拖成淡入，Tab 巡航滞后 ~150ms */
 th.srt:focus-visible{box-shadow:inset 0 0 0 2px var(--blue);outline:none}/* 表头排序：inset 环贴格不外溢 */
 /* 开关焦点环显式接管：.switch 族 checkbox（appearance:none 剥了 UA
    环的绘制基础）曾退回 UA 默认环与全站 2px 蓝环双轨——box-shadow
    对本件微晕不可辨是既有豁免理由，outline 形态不受 appearance 影响 */
 .switch:focus-visible{outline:2px solid var(--blue);outline-offset:2px}
 /* 推送通道健康行（renderPushChannels）：小节签/状态词/计量小字 */
 .pseclab{margin:14px 0 4px;font-size:11px;font-weight:600;color:var(--tx2);letter-spacing:var(--ls05)}
 .pst{font-size:12px;font-weight:600;flex:none}
 .pst.bad{color:var(--red)}.pst.ok{color:var(--green)}
 .pmeta{font-size:12px;color:var(--mut);flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
 /* ===== 渠道健康时间线 ===== */
 .hrow{display:flex;align-items:center;gap:10px;margin:7px 0}
 /* 失败渠道行辉光（审计 P2-2 带态落地）：gotoPulseHealth 落地时
    临时点亮（class 切换零 childList 变更），reduced-motion 下全局
    animation 禁令使其自然退化为仅横滚定位 */
 .hrow.hflash{animation:hflash 1.8s ease-out 1}
 @keyframes hflash{0%,55%{box-shadow:0 0 0 2px var(--red),0 0 14px var(--red)}100%{box-shadow:0 0 0 0 transparent}}
 .hlab{width:64px;flex:none;font-size:12px;color:var(--tx2);font-weight:600}
 .hcells{display:flex;gap:2px;flex:1;overflow-x:auto;overflow-y:hidden;padding:11px 0;margin:-9px 0;pointer-events:none}   /* y 轴必须显式 hidden：只写 overflow-x:auto 会把 overflow-y 计算值强制成 auto（双轴滚动容器），hover 时 .hc 的 scaleY 连 ::after 一起放大 → 纵滚条闪现 → 弹性档全行重排（抖动根因）；纵向裁剪框随 padding 外衬扩到 37px，.hc::after 热区恰铺满不被裁；margin 负值回收布局行高；容器事件穿透防衬垫吞点击 */
 /* 390 档可滚暗示：右缘渐隐提示有裁格（renderHealth 判 scrollWidth
    才挂类，防恰好放下时误裁尾格） */
 .hcells.xhint{-webkit-mask-image:linear-gradient(90deg,#000 calc(100% - 12px),transparent);mask-image:linear-gradient(90deg,#000 calc(100% - 12px),transparent)}
 .hcells .hc{pointer-events:auto}   /* 容器穿透后格本体恢复命中 */
 .hc{width:6px;height:15px;border-radius:var(--r-xs);flex:none;cursor:pointer;
   transition:transform .12s ease}/* hover 放大平滑过渡（RM 全局禁动兜底）；pointer=：点击开日志弹层，help 与真实点击动作失配 */
 .hc.ok{background:var(--green)}.hc.part{background:var(--orange)}.hc.fail{background:var(--red)}
 .hc.maint{background:repeating-linear-gradient(45deg,var(--maint) 0 2px,var(--maint-soft) 2px 4px)}
 .hc.none{background:var(--line)}
 .hc:hover{transform:scaleY(1.35)}
 .hbadge{flex:none;font-size:11px;font-weight:700;min-width:52px;text-align:center;font-family:var(--num);
   padding:2px 8px;border-radius:var(--pill);border:1px solid var(--line);
   background:var(--card);color:var(--tx2);font-variant-numeric:tabular-nums}
 .hbadge.ok{color:var(--ok-txt);border-color:rgba(var(--okrgb),.35);background:var(--okbg)}
 .hbadge.mid{color:var(--warn-deep);border-color:var(--warnbd);background:var(--warnbg)}   /* 11.5px 小字亮色 4.36:1 欠 AA → --warn-deep 6.55:1；暗色两令牌同值外观不变 */
 .hbadge.bad{color:var(--red);border-color:var(--redbd);background:var(--redbg)}
 .hlh{background:repeating-linear-gradient(45deg,var(--maint) 0 2px,var(--maint-soft) 2px 4px)}
 /* ===== 运行脉冲：概览 statline + 轮次堆叠柱 =====
    分隔线缝隙法：1px 缝透出容器底线色，每格自带 card 底——auto-fit
    任意列数（1-4 列换行皆可）分隔线恒正确。旧 border-right 方案在中间
    列数档竖线错乱，≤760 强制单列+border-bottom 补线是妥协（已删） */
 .statline{display:grid;grid-template-columns:repeat(auto-fit,minmax(158px,1fr));
  gap:1px;background:var(--line);
  border:1px solid var(--line);border-radius:var(--r2);overflow:hidden;
  margin-top:10px}
 .stat{padding:11px 16px;background:var(--card);min-width:0}
 .stat .slab{font-size:11px;letter-spacing:var(--ls1);color:var(--mut);
  text-transform:uppercase;display:flex;align-items:center;gap:6px;white-space:nowrap}
 .stat .sval{font-family:var(--num);font-size:22px;font-weight:600;margin-top:3px;
  font-variant-numeric:tabular-nums;letter-spacing:-.5px;white-space:nowrap}
 .stat .sval.ok{color:var(--green)}.stat .sval.bad{color:var(--red)}
 .stat .ssub{font-size:11px;color:var(--mut);margin-top:1px;white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis}
 .pulsewrap{display:flex;align-items:flex-end;gap:3px;height:72px;margin-top:12px;
   justify-content:center;max-width:var(--kpiw)}/* 少轮次贴左曾让宽屏右侧大片空白；限宽随 --kpiw，柱间仍居中 */
 #pulseLegend{max-width:var(--kpiw)}
 .pbar{flex:1;min-width:4px;max-width:16px;height:100%;display:flex;flex-direction:column;
  justify-content:flex-end;cursor:pointer;border-radius:var(--r-xs);position:relative;
  transition:filter .12s ease}/* pointer=：点击柱跳渠道健康；hover 过渡与 .hc 家族同律 */
 .pbar:hover{filter:brightness(1.15)}
 .pbar .seg{width:100%}
 .pbar .cap{width:100%;height:3px;background:var(--red);margin-bottom:1px;border-radius:1px}
 .pbar.zero{display:flex;justify-content:center}
 .pbar.zero i{width:100%;max-width:8px;height:3px;border-radius:1px;background:var(--red)}
 .pseg-qunar{background:var(--c-qunar)}.pseg-fliggy{background:var(--c-fliggy)}
 .pseg-tongcheng{background:var(--c-tongcheng)}.pseg-tuniu{background:var(--c-tuniu)}
 .pseg-ctrip{background:var(--c-ctrip)}
 .kbd{font-family:var(--num);font-size:11px;border:1px solid var(--line2);
  border-bottom-width:2px;border-radius:var(--r-sm);padding:1px 6px;color:var(--tx2);
  background:var(--headbg);margin:0 2px;white-space:nowrap}
 /* ===== 推送预览弹层（钉钉近似渲染） ===== */
 /* 推送预览弹层：display 恒 flex，显隐走 opacity+visibility 过渡而非突现；
    visibility 一并过渡让关闭时淡出播完才移出命中测试 */
 .pvmask{position:fixed;inset:0;background:rgba(16,24,40,.45);z-index:200;display:flex;
        align-items:flex-start;justify-content:center;padding:5vh 12px;
        opacity:0;visibility:hidden;transition:opacity .18s,visibility .18s}
 .pvmask.on{opacity:1;visibility:visible}
 .pvcard{background:var(--card);border-radius:var(--r);max-width:560px;width:100%;max-height:88vh;
        display:flex;flex-direction:column;box-shadow:var(--sh-pop);
        transform:translateY(10px);transition:transform .18s}
 .pvmask.on .pvcard{transform:translateY(0)}
 .pvhead{display:flex;justify-content:space-between;align-items:center;gap:10px;
        padding:12px 16px;border-bottom:1px solid var(--line);font-weight:700;font-size:14px}
 .pvx{cursor:pointer;color:var(--mut);font-size:16px;padding:2px 8px;border-radius:6px;user-select:none;transition:background .12s ease}
 .pvx:hover{background:var(--hover)}
 .pvbody{padding:14px 16px;overflow-y:auto;font-size:13px;line-height:1.75;color:var(--tx)}   /* 水平 16 与 pvhead/pvfoot 三段同内衬（P2-5：曾 18px 凸出 2px 肉眼可辨） */
 .pvbody .md-h1{font-size:17px;font-weight:800;margin:8px 0 10px}
 .pvbody .md-h2{font-size:15px;font-weight:800;margin:14px 0 8px;color:var(--blue)}
 .pvbody .md-h3{font-size:13px;font-weight:700;margin:10px 0 6px}
 .pvbody .md-q{border-left:3px solid var(--blue);background:var(--rowalt);border-radius:0 8px 8px 0;
        padding:6px 12px;margin:6px 0;color:var(--tx2)}
 .pvbody .md-hr{border:none;border-top:1px solid var(--line);margin:10px 0}
 .pvbody .md-p{margin:6px 0}
 .pvbody .md-li{margin:6px 0;padding-left:16px;color:var(--tx)}
 .pvbody .md-g{font-size:15px;letter-spacing:var(--ls2)}
 .pvbody img{max-width:100%;border-radius:8px;border:1px solid var(--line);display:block;margin:6px 0}
 .pvbody a{color:var(--blue);text-decoration:none}
 .pvbody a:hover{text-decoration:underline}   /* 真实可点链接悬停零反馈，与 .toast:hover/a.vw:hover 同律 */
 .pvbody .md-at{background:var(--at-bg);color:var(--at-fg);border-radius:4px;padding:0 5px;font-weight:700}
 .pvfoot{padding:10px 16px;border-top:1px solid var(--line);font-size:11px}
 /* ===== 演示横幅 ===== */
 .demoBar{margin:12px 0 0;background:#fff7e0;color:#7a4b00;border:1px solid #f0d98c;
        border-radius:var(--r10);padding:9px 14px;font-size:13px;text-align:center}
 .demoBar a{color:#9a6200;font-weight:700;padding:5px 0;white-space:nowrap}   /* 纵向外衬补触控基准（文字行裸高 34）；词组粒度 nowrap——CJK 窄带逐字折行曾断成「下载源/码或发行包」 */
 html[data-theme="dark"] .demoBar a{color:#ffd97a}
 /* 页脚/演示条/版本横幅链接触控热区外扩（.dchip .dx 家族纪律：纯命中
    区，视觉零变化）——页脚 GitHub 裸高 16px、demoBar 下载链 27px、
    verbar 刷新链裸高 19px 曾是全站最小可点件，手机难点中 */
 #foot a,.demoBar a,.verbar a{position:relative}
 #foot a::after,.demoBar a::after,.verbar a::after{content:'';position:absolute;inset:-10px -4px}
 html[data-theme="dark"] .demoBar{background:var(--demo-bg);color:var(--demo-tx);border-color:var(--demo-bd)}
 /* 版本失配横幅：no-cache 只管「下次导航」，救不了重启窗口期
    一直开着的旧标签页——10s 轮询发现服务端版本与页面代际不一致即亮此条 */
 .verbar{margin:12px 0 0;background:#ffe4e4;color:#8a1f1f;border:1px solid #f2b8b8;
         border-radius:var(--r10);padding:9px 14px;font-size:13px;text-align:center}
 .verbar a{color:#8a1f1f;font-weight:700;text-decoration:none}
 .verbar a:hover{text-decoration:underline}   /* 紧急刷新链悬停零反馈，与 .pvbody a:hover 同律 */
 html[data-theme="dark"] .verbar a{color:var(--ver-tx)}
 html[data-theme="dark"] .verbar{background:var(--ver-bg);color:var(--ver-tx);border-color:var(--ver-bd)}
 /* ===== 价格日历热力卡 ===== */
 .calgrid{display:flex;gap:5px;flex-wrap:wrap;margin-top:8px}
 /* 日历统计条分层：指标胶囊（mono 数字加重）与图例小字分体，
    决策信息与解码信息不再混排一行 */
 .cs-i{display:inline-block;background:var(--rowalt);border:1px solid var(--line);
  border-radius:var(--r3);padding:1px 8px;margin:2px 6px 2px 0;font-size:12px;color:var(--tx2)}
 .cs-i b{font-family:var(--num);color:var(--tx)}
 .cs-lg{font-size:11px;color:var(--mut)}
 .calcell{flex:1 1 74px;max-width:112px;border-radius:var(--r3);padding:6px 4px;text-align:center;
        border:1px solid var(--line)}
 /* hover 视觉暗示（r256 美感3）：title 悬停可读但格面无反馈——描边
    升 --line2 一档（与 ucard hover 同语言）；不加 pointer 光标，
    维持「非可点」语义诚实 */
 .calcell:hover{border-color:var(--line2)}
 .calcell .cd{font-size:11px;font-weight:600}
 .calcell .cp{font-size:13px;font-weight:800;margin-top:2px;
  font-family:var(--num);font-variant-numeric:tabular-nums}
 .calcell .cx{font-size:11px;margin-top:1px;font-variant-numeric:tabular-nums}
 .calcell.best{outline:2px solid var(--green);outline-offset:-2px}
 .calcell.best.qhit{outline-color:var(--cal-best-stroke)}   /* best×真达标绿底叠加态：绿描边压绿底零对比隐形（双主题实锤），换专色令牌 */
 .calcell.best .cx{font-weight:800}
 /* 删日历格 none 死规则——renderCal 格类只产 calcell/best/qhit，
    无数据格走内联 bg，none 类无生产点 */
 /* ===== 日志原文弹层 ===== */
 .logpre{font-family:var(--num);font-size:11px;line-height:1.6;
        white-space:pre-wrap;overflow-wrap:anywhere;background:var(--rowalt);
        border-radius:8px;padding:10px 12px;margin:0;max-height:60vh;overflow:auto}
 /* ===== 通知开关 ===== */
 /* ===== 走势范围 chips（与 tabs/chip 同一视觉语言） ===== */
 /* .mdgrp 模式/范围组容器：组内 nowrap 恒整、组间由 uhead 外层 flex
    wrap 承担——四 chip 平铺同层时窄档折行后模式档与时间窗档混排
    （「K线 48h」同行，组间语义断裂）。不复用 .wingrp：其窄档媒体块
    放宽为可折行（时段筛选组语义），组界会再断 */
 .mdgrp{display:inline-flex;align-items:center;white-space:nowrap}
 .rngchip{padding:5px 14px;border-radius:var(--r3);cursor:pointer;font-size:12px;
   background:var(--headbg);color:var(--mut);border:1px solid var(--line);
   user-select:none;font-weight:600;transition:.15s}
 .rngchip:hover{border-color:var(--mut);color:var(--tx2)}
 .rngchip.on{background:var(--fill);color:#fff;border-color:transparent;
   box-shadow:0 2px 8px -2px var(--glow)}
 /* 选中态键盘焦点环：.rngchip.on 的辉光与环块同属性（box-shadow）
    且 :focus-visible 伪类加一档特异性恒胜——环语义由高特异性
    覆写显式 reclaim，不依赖声明序（LESSONS 廿一§1 层叠序的
    特异性档变体） */
 .rngchip.on:focus-visible{box-shadow:0 0 0 2px var(--blue)}
 /* ===== toast 通知（右下角堆叠，非阻断；替代原生 alert） ===== */
 #toasts{position:fixed;bottom:78px;right:18px;z-index:300;display:flex;
        flex-direction:column;gap:8px;align-items:flex-end}
 .toast{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--blue);
        border-radius:var(--r3);padding:10px 16px;font-size:13px;color:var(--tx);
        box-shadow:var(--sh3);animation:tin .25s ease;cursor:pointer;
        max-width:min(340px,calc(100vw - 28px));word-break:break-all}
 .toast.ok{border-left-color:var(--green)}
 .toast.err{border-left-color:var(--red)}
 .toast:hover{background:var(--hover)}   /* 可点击关闭的 hover 反馈，与 .pvx 同语言（P2-E） */
 .toast.out{opacity:0;transform:translateX(20px);transition:.3s}
 @keyframes tin{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
 /* 危险操作二次确认态（按钮内联确认，替代原生 confirm） */
 button.arming{background:var(--red)!important;border-color:var(--red)!important;color:#fff!important}
 /* 暗色确认态底收深：--red(#ef5350) 作填充底白字仅 3.49（亮色 #c22a2e 5.73 不受累；
    --red 令牌本身不动——作文字色 5.12 仍正确，P2-3 只修作底两处） */
 html[data-theme="dark"] button.arming{background:var(--danger-solid)!important;border-color:var(--danger-solid)!important}
 /* 明细行入场（stagger 渐显；reduced-motion 全局已禁用动画） */
 @keyframes rowin{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
 /* 延迟由数据行 --i 变量驱动（JS clamp 至 7=210ms 封顶）：nth-child 计数
    会被行间隐藏 xrow 打乱，折叠展开/筛选后序号错位 */
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
 /* ===== 配置页双栏骨架 ===== */
 .cfglayout{display:grid;grid-template-columns:180px minmax(0,1fr);gap:16px;align-items:start}
 /* sticky top 贴 header 实高底 +4px 呼吸缝（--hdh 动态单源，与监控页
    吸顶家族同源；fallback 58=54+4 为 JS 失效等效值），max-height 同步
    联动（吸顶态底缘恒距视口 12px） */
 .cfgnav{position:sticky;top:calc(var(--hdh,54px) + 4px);display:flex;flex-direction:column;gap:4px;
  align-self:start;max-height:calc(100vh - var(--hdh,54px) - 16px);overflow:auto}
 /* 底部字段不被浮存条(savebar)遮挡：savebar 实高动态单源 --sbh
    （ResizeObserver 跟随折行/文本缩放实时写；fallback 40+48=88
    为 JS 失效等效值=旧单行校准） */
 #cfgview{padding-bottom:calc(var(--sbh,40px) + 48px)}
 /* 搜索框独立瓦片样式（曾 .cfgnav>span 通配——特异性 (0,1,1) 恒压
    .cnav 的 (0,1,0)，其 padding/radius/background 全部死代码，且 760px
    触控增强 .cnav{padding:10px 14px} 从未生效（收口）：
    瓦片样式合并进 .cnav 本体，观感不变、特异性归位） */
 .cfgnav .cfgsearch{background:var(--card);
   border:1px solid var(--ctlbd);border-radius:var(--r);padding:10px 12px}
 .cfgnav-t{font-size:10px;letter-spacing:var(--ls1);color:var(--mut);padding:2px 8px 6px;
   text-transform:uppercase}
 .cnav{background:var(--card);border:1px solid var(--line);
   border-radius:var(--r);padding:8px 12px;cursor:pointer;font-size:13px;
   color:var(--tx2);font-weight:600;transition:.15s;user-select:none}
 .cnav:hover{background:var(--hover)}
 .cnav.on{background:var(--fill);color:#fff}
 @media(max-width:900px){.cfglayout{grid-template-columns:minmax(0,1fr)}
   .cfgnav{position:static;flex-direction:row;flex-wrap:wrap;
     max-height:none;overflow:visible}
   .cfgnav-t{display:none}}
 .grouplab{display:flex;align-items:center;gap:9px;margin:16px 2px 10px;
   border:1px solid var(--line);border-radius:var(--r3);padding:9px 12px;font-size:13px;
   font-weight:700;color:var(--tx);background:var(--headbg);
   transition:border-color .15s,background .15s}
 .grouplab[data-sec]:hover{border-color:var(--blue);background:var(--hover)}
 .grouplab .gsum{font-weight:400;font-size:11px;color:var(--mut);
   overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}
 .grouplab .chev{font-size:14px}
 .grouplab .no{font-family:var(--num);color:var(--mut);font-size:11px;letter-spacing:var(--ls1);
   background:var(--headbg);border:1px solid var(--line);border-radius:6px;
   padding:2px 8px;align-self:center}
 .grouplab .en{font-size:10px;letter-spacing:var(--ls2);color:var(--mut);
   text-transform:uppercase;font-weight:600}
 .grouplab::after{content:'';flex:1;border-top:1px solid var(--line)}
 /* ===== 配置页质感：登录卡 / 参数格 / 通道卡 / 用户卡头 ===== */
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
 .lgcard .lgname{font-size:13px;font-weight:700;display:flex;align-items:center;gap:8px}
 .lgcard .lgsub{font-size:11px;color:var(--mut)}
 .lgcard .btn2{margin-top:auto}
 .glgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
 .glcell{border:1px solid var(--line);border-radius:var(--r2);padding:12px 14px;
   background:var(--card);transition:border-color .2s}   /* 12px 14px 与 .lgcard/.chcard 同档（P2-B：11px 垂直档系全卡唯一游离值） */
 .glcell:hover{border-color:var(--line2)}
 .glcell .glab{font-size:11px;letter-spacing:var(--ls1);color:var(--mut);
   text-transform:uppercase;white-space:nowrap}
 .glcell input:not(.switch){margin-top:6px;font-family:var(--num);font-size:17px;font-weight:600;
   width:100%;border:none;background:transparent;color:var(--tx);padding:2px 0 0;
   border-bottom:1px dashed var(--ctlbd);border-radius:0}
 .glcell input:not(.switch):hover{border-bottom-color:var(--mut)}
 .glcell input:not(.switch):focus{outline:none;border-bottom:1px solid var(--blue);
   box-shadow:0 1px 0 0 rgba(var(--blue-rgb),.25)}
 /* P1-1：hover/focus 豁免 .switch（原 outline:none 吞掉三枚开关键盘
    焦点环，srow/fbar 对照均有 UA 环；数字/文本输入样式零变化） */
 .glcell .gsub{font-size:11px;color:var(--mut);margin-top:5px}
 .chgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(272px,1fr));
   gap:10px;margin-top:8px}
 .chcard.expanded{grid-column:1/-1}/* 展开的通道卡跨全宽，不留半列空白 */
 .chcard.ih-free .ih-token{display:none!important}/* freeimage 下藏 Token 行——!important 压过 applyFolds 展开时的 inline 清空 */
 .chcard{border:1px solid var(--line);border-radius:var(--r2);padding:12px 14px;
   background:var(--card);display:flex;flex-direction:column;gap:9px;
   transition:border-color .2s}
 .chcard.on{border-color:rgba(var(--okrgb),.4)}
 .chhead{display:flex;align-items:center;gap:8px;font-size:13px;font-weight:700}
 .chhead .muted{font-weight:500;margin-left:auto;white-space:nowrap}
 .hint{font-size:11px;color:var(--mut);line-height:1.55;margin-top:5px}
 .uhead2{cursor:pointer;display:flex;align-items:center;gap:12px;flex-wrap:wrap;padding:13px 16px;
   background:var(--headbg);transition:background .15s;user-select:none}
 .uhead2:hover{background:var(--hover)}
 /* min-width 保底：flex:1（basis:0）会让标题被同行 nowrap 胶囊压到
    min-content=一字一行竖排（审计 P1）；flex-wrap 让胶囊
    放不下时换行而不是挤压标题 */
 .uhead2{flex-wrap:wrap}
 .uhead2 b{flex:1;min-width:8em;font-size:14px}
 .uava{width:30px;height:30px;border-radius:var(--r3);flex:none;display:inline-flex;
   align-items:center;justify-content:center;font-size:13px;font-weight:700;color:#fff;
   background:linear-gradient(135deg,var(--fill2),var(--blue))}
 /* 暗色头像渐变第二站收深：--blue(#63a4f8) 端白字墨迹
    带 2.56~3.96 全欠 → --fill(#2c67ba) 全带过；亮色两端已深不受累 */
 html[data-theme="dark"] .uava{background:linear-gradient(135deg,var(--fill2),var(--fill))}
 .upill{font-size:11px;padding:3px 9px;border-radius:var(--pill);border:1px solid var(--line);
   background:var(--card);color:var(--mut);white-space:nowrap;line-height:1;
   font-family:var(--num);font-variant-numeric:tabular-nums}
 .upill.ok{color:var(--ok-txt);border-color:rgba(var(--okrgb),.35);background:var(--okbg)}
 .upill.warn{color:var(--warn-deep);border-color:var(--warnbd);background:var(--warnbg)}   /* 「● 未保存」11px 亮色 3.9:1 欠 AA → --warn-deep 6.21:1；暗色 --warn≡--warn-deep 同值（#d9b34a）零外观变化 */
 .udirty{display:none}
 .chev{transition:transform .2s;color:var(--mut);font-size:12px;flex:none}
 .chev.open{transform:rotate(180deg)}
 .grouplab[data-sec],.rhead[role="button"],.chhead[role="button"]{cursor:pointer;user-select:none}
 .grouplab[data-sec]:hover .zh,.chhead[role="button"]:hover{color:var(--blue)}
 .rhead[role="button"]:hover .rtcode{border-color:var(--blue)}
 .grouplab .chev{margin-left:auto}
 .ucard.flash,.rline.flash{animation:cfgflash 1.4s ease-out}
 @keyframes cfgflash{0%{box-shadow:0 0 0 3px rgba(var(--blue-rgb),.5)}
  100%{box-shadow:0 0 0 3px rgba(var(--blue-rgb),0)}}
 .rtcode{font-family:var(--num);font-size:14px;font-weight:600;color:var(--blue);
   letter-spacing:var(--ls05)}
 /* 未保存修改浮出保存条：display 恒 flex，显隐走 translateY+opacity 滑入
    （.on 由 JS 巡检 toggle，隐藏态平移出视口不吃点击）。
     补 visibility 双态（与 .pvmask 同范式）：仅 transform 隐藏时
    按钮仍在焦点树内，键盘 Tab 会命中不可见按钮静默保存/回滚配置 */
 .savebar{position:fixed;right:18px;bottom:18px;z-index:120;display:flex;gap:10px;
   align-items:center;background:var(--card);border:1px solid var(--line2);
   border-radius:var(--r10);padding:10px 14px;box-shadow:var(--sh2);font-size:13px;font-weight:600;
   transform:translateY(140%);opacity:0;visibility:hidden;
   transition:transform .22s,opacity .22s,visibility .22s}
 .savebar.on{transform:translateY(0);opacity:1;visibility:visible}
 .savebar .dot{width:8px;height:8px;border-radius:50%;background:var(--warn);
   animation:pulse 1.4s ease-in-out infinite}
 /* ===== 推送记录列表（状态色条卡片：绿=成功 红=失败） ===== */
 .plitem{padding:9px 12px;border-radius:var(--r3);cursor:pointer;font-size:13px;
        margin:6px 0 2px;background:var(--rowalt);border:1px solid var(--line);
        border-left:3px solid var(--green);display:flex;gap:8px;
        align-items:center;transition:background .15s,border-color .15s}
 .plitem:hover{background:var(--hover)}
 .plitem.bad{border-left-color:var(--red)}
 .plts{color:var(--mut);font-size:11px;white-space:nowrap;font-variant-numeric:tabular-nums}
 .plch{font-size:10px;color:var(--mut);border:1px solid var(--line);border-radius:var(--pill);padding:0 6px;line-height:16px;white-space:nowrap}
 .pldesp{border:1px solid var(--line);border-radius:0 var(--r10) var(--r10) var(--r10);
        background:var(--headbg);padding:4px 14px;margin:0 0 10px}
 /* ===== 细滚动条（主题化；Firefox 走 scrollbar-*） ===== */
 ::-webkit-scrollbar{width:9px;height:9px}
 ::-webkit-scrollbar-thumb{background:var(--line);border-radius:var(--r-sm)}
 ::-webkit-scrollbar-thumb:hover{background:var(--mut)}
 ::-webkit-scrollbar-track{background:transparent}
 *{scrollbar-width:thin;scrollbar-color:var(--line) transparent}
 /* ===== 视图/图表切换过渡（丝滑不跳变） ===== */
 .viewin{animation:vin .18s ease}
 @keyframes vin{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
 /* ===== 配置页：搜索框 + 命中计数 ===== */
 .cfgsearch{width:100%;padding:7px 11px;border:1px solid var(--ctlbd);border-radius:var(--r3);
  font-size:12px;background:var(--card);color:var(--tx);margin:8px 0 10px;
  transition:border-color .15s,box-shadow .15s}
 .cfgsearch:hover{border-color:var(--mut)}
 .cfgsearch:focus{outline:none;border-color:var(--blue);box-shadow:0 0 0 3px var(--ring);transition:box-shadow 0s}   /* 环即时呈现（r221 P2-6 同族） */
 .cfghit{font-size:11px;color:var(--mut);margin:-4px 0 8px;min-height:14px}
 /* ===== 追加规则一律置末尾（同特异性后者胜，防被前文同名规则覆盖） ===== */
 .stat .sval{overflow:hidden;text-overflow:ellipsis}
 @media(min-width:1440px){.wrap{max-width:min(1320px,92vw)}}
 /* ===== KPI 宽度单源令牌 --kpiw：min(1168px,100%) 流式（收口
    1366/1280 空腔；1800+ 不再加宽——KPI 过扁失比） ===== */
 /* KPI 宽屏限宽 → 令牌化：.grid 为 KPI 专用（唯一消费点），
    auto-fit 在 1180-1439 恒出 2 轨 ~566px 宽扁失比（1280/1366 主流本
    正落在区间内）；限宽下探到 600px 生效——<600px 维持 auto-fit
    minmax(280px,1fr) 单列不破手机端；轨道 1fr×2 宽随 --kpiw 容器定，
    statline 同宽左缘成线 */
 @media(min-width:600px){
  /* statline 与 KPI 同宽左缘成线维持 600 起；.grid 双卡断点上移
     660（审计 P2-2）：600-659 带双卡 minmax(0,1fr) 无地板曾压破
     280px 设计下限（卡宽 252-282、599→601 密度反转 496→252），
     该带回落基础 auto-fit minmax(280px,1fr) 地板档 */
  .statline{max-width:var(--kpiw)}}
 @media(min-width:660px){
  /* 1920 档右侧空腔收敛（审计复核翻案）：每组恒 2 卡（直飞/中转）
     纪律保留（放开 3 轨出空轨、auto-fit 折叠反成 ~815px 宽扁），
     但 1168 限宽在 wrap 1716 下空腔 474px 被 ≥1920 块放宽 1440
     消减（互指见 1920 块）；660-1919 维持 --kpiw 纪律，左缘对齐 */
  .grid{grid-template-columns:repeat(2,minmax(0,1fr));max-width:var(--kpiw);
   justify-content:flex-start}}
 .kpisum{max-width:var(--kpiw)}   /* 用户卡「全线最低」行与 KPI 行同宽 */
 /* 行内明细/走势链接触控外扩（#foot a::after 同款族
    收编：实测 h=16 全站最小可点件之一，纯命中区视觉零变化，
    与相邻「｜」分隔 ~20px 不吃邻命中） */
 .kpisum a{position:relative;padding:12px 4px;margin:0 -4px;text-decoration:none}   /* r219 P1-1：内联链触控热区实体扩张（inline 垂直 padding 纯扩命中区不占布局；12px 地板=本地 16px 与 CI Linux ~14px 字体行高双环境均 ≥36 触控基准） */
 .kpisum a::after{content:'';position:absolute;inset:-10px -4px}
 .kpisum a:hover{text-decoration:underline}   /* 与 .pvbody a:hover 同律 */
 /* 断点缝收敛：wrap 跨断点一次性 +140px 而 statline/pulsewrap
    仍锁 --kpiw=1168，1440-1919 全带卡内右缘 ~115px 空腔、同屏 trend 卡
    全宽=跨卡右缘双轨 ~78px（实测不可感维持；≥1920 档空腔 474px 被
    放宽 1440 消减，见 1920 块）。解锁块必须位于上方 600px 块之后
    （同特异性后者胜：放 1440 wrap 块内会被 600 块的 --kpiw 覆盖，
    uitest 全量实抓） */
 @media(min-width:1440px){.statline,#pulseLegend,.pulsewrap{max-width:none}}
 /* ↑与 ≥1920 块内同选择器同值声明互指：1440 扩带后该行恒 no-op
    （两块间无再限宽规则），保留作 1920 块自洽注记——勿据此误判
    两档不同值，也勿单侧删除（两块间若回插再限宽规则，1920 档
    需自有声明才不被回插值锁死） */
 /* ===== 密度两挡：cozy（默认）/compact（紧凑），html[data-density] 覆写 ===== */
 html[data-density="compact"] .ucard{padding:14px}
 html[data-density="compact"] .srow{padding:8px 10px;min-height:38px}
 html[data-density="compact"] th,html[data-density="compact"] td{padding:6px 8px}
 html[data-density="compact"] .kpi .num{font-size:27px}
 html[data-density="compact"] .chcard{padding:8px 10px}
 /* compact 同步收窄航线卡/通道卡内衬（基础 padding 约 -30%）：srow 行高
    收了而外层卡不收，折叠体内留白比例反而变大 */
 html[data-density="compact"] .rline{padding:7px 10px}
 /* ===== 首列吸附全宽度生效：吸附成本恒定，超长航线名在 >1024 也可能
    触发横滚——价格列在任何宽度都不许滚出视野（原只在 ≤1024 生效）。
    斑马/hover/qual 补偿底随 .zebra 显式类同步 ===== */
 .tw th:first-child,.tw td:first-child{position:sticky;left:0;z-index:2;
  background:var(--card);box-shadow:2px 0 0 var(--line)}
 .tw th:first-child{background:var(--headbg);z-index:4}
 /* 首列表头兼默认排序列（.srt.on 同体）：上方 th.srt:hover 与本吸附
    打底同特异性 (0,2,1)、源码序在前被压制——9 列唯一 hover 死区恰在
    最高频排序入口，置尾复声明的反馈（sticky 打底/z-index 不动） */
 .tw th.srt:first-child:hover{background:var(--hover)}
 /* 首列表头键盘焦点环：吸附投影 (0,2,1) 源码序在后压制 th.srt:
    focus-visible 的 inset 环（同特异性后者胜），最高频排序入口聚焦
    蓝环缺失——置尾复声明双影叠加（环+投影共存，单写环会吃掉投影） */
 .tw th.srt:first-child:focus-visible{box-shadow:inset 0 0 0 2px var(--blue),2px 0 0 var(--line);outline:none}
 .tw tbody tr.zebra td:first-child{background:var(--rowalt)}
 .tw tbody tr:hover td:first-child{background:var(--hover)}
 /* 吸附格底=不透明 --card 打底 + 同值 tint 单层：rgba 重涂曾叠在
    行身同值 rgba 上成双层绿底（首格 #daebe2 vs 行身 #ecf5f0 色带），且半透明格在横滚时
    被下层列透视；gradient 打底后与行身逐像素同值、横滚不透 */
 .tw tbody tr.qual td:first-child{background:linear-gradient(rgba(var(--okrgb),.08),rgba(var(--okrgb),.08)),var(--card)}
 .tw tbody tr.qual:hover td:first-child{background:linear-gradient(rgba(var(--okrgb),.14),rgba(var(--okrgb),.14)),var(--card)}
 .tw tbody tr.qual.zebra td:first-child{background:linear-gradient(rgba(var(--okrgb),.12),rgba(var(--okrgb),.12)),var(--card)}
 html[data-theme="dark"] .tw tbody tr.qual td:first-child{background:linear-gradient(rgba(67,192,114,.13),rgba(67,192,114,.13)),var(--card)}
 html[data-theme="dark"] .tw tbody tr.qual:hover td:first-child{background:linear-gradient(rgba(67,192,114,.2),rgba(67,192,114,.2)),var(--card)}
 /* 空态/加载行（erow）：行身透明+悬停透明（上方 #ftable tr.erow:hover 规则），sticky 首格若被
    通用 hover 规则染成 --hover 会与行身断裂——钉回 card 底（含 hover 态） */
 #ftable tbody tr.erow td:first-child{background:var(--card)}
 #ftable tbody tr.erow:hover td:first-child{background:var(--card)}
 /* 明细行键盘焦点环左缘段：tr:focus-visible 的 inset 环画在 tr 装饰层，
    被首列吸附格不透明底（--card/斑马/qual tint，td 背景绘制恒在 tr 装饰
    之上）盖住左缘 2px——环落 td 自身才在吸附列之上（tr 层修法无效）。
    与吸附分隔投影双影并存（表头首列环同语言），ID 特异度恒压 (0,2,1) 打底块 */
 #ftable tbody tr:focus-visible td:first-child{box-shadow:inset 2px 0 0 var(--blue),2px 0 0 var(--line);outline:none}
 /* ===== 触控热区扩展：可点小控件以 ::after 外扩命中区（视觉尺寸不变） ===== */
 .dchip .dx,.pvx,a.vw,.hc,.tj{position:relative}
 .pvx::after,a.vw::after{content:'';position:absolute;inset:-11px -8px}   /* 纵向 -11px 达 36 触控基准：a.vw 是纯 inline 盒，::after 包含块取行内片段 content-box，-9px 实测只兑现 34px；横向 -8px 已富余 */
 /* .dx 字面仅 ~11px：热区外扩到 -13px≈37px 达触控基准；外缘仍落在自身
    chip 12px 内衬+片间距内，不侵入相邻日期片命中区 */
 .dchip .dx::after{content:'';position:absolute;inset:-13px}
 /* .hc 热区：纵向扩展保触控高度；横向只补缝隙（6px 格距 8px，曾
    ±10px 全向扩展——相邻 5 格热区互相覆盖，点 A 格响应 B 格） */
 .hc::after{content:'';position:absolute;inset:-11px -1px}   /* 纵向 -11px 达 36 触控基准（35 差 1px），横向 -1px 防串格纪律不动 */
 .hc.none{cursor:default}   /* 未扫描格无点击动作：光标语言跟动作语言（假手型清除） */
 /* .pbar 热区同语言：4px 细柱难点中；横向只 ±1px 防串柱（缝 3px） */
 .pbar::after{content:'';position:absolute;inset:-10px -1px}
 /* .tj（明细行 📈 跳走势，新件）同族收编：纵向 -11px 达 36 触控基准
    （inline 盒包含块律同 a.vw，-9px 只兑现 34px）；横向只 -4px 同 .tg
    先例——右侧紧邻 ↗ vw 链接，防吃相邻命中 */
 .tj::after{content:'';position:absolute;inset:-11px -4px}
 /* .chhead（配置页通道卡折叠头，role=button 点击 foldCh 收展）同族
    收编：本体仅 13.5px 字号行高 ≈19px，三处触控基准缺口；纵向 -9px
    补到触控基准，横向 -8px——chcard 间距 10px 内衬不吃相邻卡命中 */
 .chhead[role=button]{position:relative}
 .chhead[role=button]::after{content:'';position:absolute;inset:-9px -8px}
 /* .pvbody a（弹层正文链接，三入口共用）：inline 锚盒高随环境字体
    浮动（Windows 17px / CI Linux 15px），按最差环境取值 -11px 补到
    CI 37px/Win 39px 触控基准（-10px 在 CI 差 1px 实锤）；
    NOTIFY 轻页 .md a::after 同制先例；横向 -4px 同轻页先例
    （行内邻链接防互叠误触） */
 #pvMask .pvbody a{position:relative}
 #pvMask .pvbody a::after{content:'';position:absolute;inset:-11px -4px}
 .savebar{flex-wrap:wrap}
 /* ===== xrow（同班比价展开行）退出首列吸附：colspan 行恰是 td:first-child，
    被 全宽度吸附规则上了不透明卡底+投影，琥珀高亮底被整体吃掉 ===== */
 .tw tbody tr.xrow td:first-child{position:static;
  background:var(--xzone);box-shadow:none}
 /* ===== 暗色清扫第三批：JS 内联硬编码随令牌 ===== */
 /* .lgdot 离线灰点暗色下接近在线绿点（语义变糊），随 --line2 退后 */
 /* ===== 触屏平板（≤900px 且 pointer:coarse）：iPad 768/810/820
    落在 760 断点真空，触控目标拿不到 ≥36px 基准（本块补此缺口）。规则自上方 ≤760 触控
    块逐字复制（声明同值，手机 coarse 下双块叠加零视觉差）；置于全部
    基础规则之后（.cnav/.cfgsearch 基础声明更后，写前面会被同特异性
    后者覆盖=整块失效，见上方两次实锤注释）。fbar 开关热区外扩必须覆盖
    （含 #fnostale），::before 命中区一并补齐 ===== */
 @media(max-width:900px) and (pointer:coarse){
  .tabs .mtab{padding:9px 14px}
  .tabs .uchip{padding:9px 14px}   /* 用户切换 chip 触控地板（本块无 .tabs span 通配） */
  #tabs span{padding:9px 14px}
  .chip{padding:9px 14px;font-size:13px}
  .chip+.chip{margin-left:6px}
  .mchip{padding:9px 14px;font-size:13px}
  .fbar input:not(.switch),.fbar select{padding:9px 10px}
  th.srt{padding:11px 8px}
  .cnav{padding:10px 14px}
  .rngchip{padding:9px 14px;font-size:13px}
  nav span{padding:9px 18px}
  nav span{min-height:36px;display:inline-flex;align-items:center}
  .hbtn{min-height:36px;min-width:36px}
  .ropbtn,.danger{min-height:36px}
  .fbar input:not(.switch),.fbar select{height:38px}
  .fbar input[type=text]{height:38px}
  .fbar .btn2{height:38px;margin-right:0}
  .btn2{min-height:36px}
  button{min-height:36px}
  .pill{min-height:36px}
  .srow .sctl .switch::before{content:'';position:absolute;inset:-8px}
  .fbar .switch::before{content:'';position:absolute;inset:-8px}
  .glcell .switch::before{content:'';position:absolute;inset:-8px}
  .rop .switch::before{content:'';position:absolute;inset:-8px}
  /* flab 开关（#fnostale）同族补齐（外扩家族 .srow/.fbar/.glcell/.rop
     作用域漏收槽位）。a.vw/.tj 热区 base 已有 ::after 外扩
     （-11px -8px / -11px -4px，纵向 36 达标、横向 33/32 在案备案豁免
     ——此块不再覆写，覆写收窄曾把触屏横向热区压到 ~20px） */
  .flab .switch::before{content:'';position:absolute;inset:-8px}
  /* flab label 文字区同律补热区（开关本体 above 达标、文字部分命中
     高度仅 20px<36px 基准；纵向 -8px 吃满 frow 行距、横向 -4px 同
     a.vw 先例防吃邻件） */
  .flab{position:relative}
  .flab::after{content:'';position:absolute;inset:-8px -4px}
  .srow input[type=text],.srow input[type=number],.srow input[type=time],
  .srow input[type=url],.srow input[type=tel],.srow input[type=password],
  .srow input:not([type]),.fbar input[type=text],.cfgsearch,
  .fbar label input{font-size:16px}
  /* srow 行内输入触控高度对齐 fbar 38（基础 34px 低于 36 基准；
     srow min-height 容得下） */
  .srow .sctl input:not(.switch){height:38px}
  /* .srow 16px 守卫走与上行同形的高特异形态（(0,3,1) 置尾胜基础
     13px；清单形态 (0,2,1) 曾被压制=层叠败北，iOS 聚焦爆版） */
  .srow .sctl input:not(.switch){font-size:16px}
  /* 三处 16px 清单互指（审计）：本块=≤900 粗指针（iPad 竖屏
     820 带）、≤760 任意指针、901+ 粗指针（iPad Pro 横屏）——
     条件语义各异勿合并，改动须三处同步 */
  .glcell input[type=text]{font-size:16px!important}}
  /* P2-C：glcell 文本输入内联 13px 锁定，!important 压内联
     （iOS 聚焦自动放大且不回位；仅本媒体内生效，桌面 13px 观感不变） */
 /* ===== 暗色漏网：硬编码深琥珀在暗底对比不足，随令牌 ===== */
 html[data-theme="dark"] .rbadge{color:var(--warn)}
 /* .upill.warn 暗色覆写已删：基类改 --warn-deep 后
    暗色 --warn≡--warn-deep（#d9b34a）自动成对，覆写纯冗余 */
 /* ===== 日历擦边档（q=-1）：格价琥珀，与走势图「擦边」同语言 ===== */
 .calcell .cp.near{color:var(--warn-deep)}   /* 擦边价字 --warn-deep：亮色对琥珀 tint 4.66/暗色 4.72 双过 AA（--warn 亮色 3.31 欠，；暗色 --warn≡--warn-deep 成对） */
 /* 飞猪明细行「税前」小标（推送侧同标注：税前价≠到手价，扫读可辨） */
 .pretax{font-size:10px;color:var(--mut);font-weight:500;margin-left:4px;
   vertical-align:1px}
 /* ===== 2K 宽屏（≥1920px）：全站统一 1680 内容宽（wrap 1716=1680+36 padding）
    —— 骨架收口：旧「宽窄组」设计（走势/明细 1680、概览/健康 1284，
    逐块负 margin 突破+宽窄组总闸）在用户实拍三连图里暴露为每次切标签
    整页横移 198px、标题头右缘跳 180px=「页面抖动」实感。统一后任何视图/
    标签切换零位移；/55/56/57/59 的 breakout 机制整体退役 */
 @media(min-width:1920px){
  .wrap{max-width:1716px}
  /* P1-2：KPI 空腔收敛——1680 卡内腔 1642px 只放开非比例
     敏感件（statline 是 auto-fit 4 格统计条、脉冲柱本体 max-width:16
     内部居中、legend 单行短文本，跟卡全宽不失比）；
     .grid/.kpisum 放宽 1440（见下），1440-1919 带仍锁 --kpiw 1168 */
  .statline,#pulseLegend,.pulsewrap{max-width:none}
  /* ↑与下方 1440 解锁块同选择器同值（互指注在该块）：1440 扩带后
     本行恒 no-op，保留作块内自洽；删改任一侧前先核两块间有无
     再限宽规则回插 */
  /* KPI 行 ≥1920 放宽 1440（每卡 ~703px 仍在可读带，815px 才入
     宽扁区）：--kpiw 1168 在 wrap 1716 下卡内右侧 474px 空腔被放大
     （1440-1919 带同病灶 ~115px 不可感）——空腔收敛至 ~239、左缘
     对齐纪律不变；1440-1919 带 ~115px 不可感维持限宽（该档取舍
     保留域；两数为 demo 实测口径，随卡内胶囊数浮动）。层叠：须晚于
     600 块 .grid 限宽声明 */
  .grid,.kpisum{max-width:min(1440px,100%)}
  /* header 原生 -18px 出血是 1284 档视觉语言；统一 1680 后与卡同缘。
     摘出血后 h1（卡内文字轴）与 #mainnav（裸排胶囊卡，盒轴线）相
     差 18px——窄带的 h1≡nav 同线是出血恰抵消 padding 的巧合，非设
     计语言；本带对齐语言=「盒轴通线」：nav 与下方全部卡盒同线一柱
     贯底，h1 内缩是 header 卡内呼吸空间。消台阶的两修法（nav 缩进
     18px 破通线 / header padding 左 0 伤对称）害均大于台阶本身，备案不修 */
  header{margin-left:0;margin-right:0}}
 /* ===== 大屏触控设备（>900px 且 pointer:coarse）：iPad Pro 横屏 1366 等
    落在 ≤900 触控补丁盲区，控件回落 <36px 触控基准；声明与上方触控块
    同值补档（历史纪律：媒体增强块置于文件尾部） ===== */
 @media(pointer:coarse) and (min-width:901px){
  .chip,.mchip,.rngchip{padding:9px 14px;font-size:13px}
  nav span,.tabs span{padding:9px 14px}
  /* nav span 触控 36 地板（仅 padding 增强时视高 ~35 差 1px）；
     inline 元素 min-height 不生效，flex 化垂直居中（三触控块同律） */
  nav span{min-height:36px;display:inline-flex;align-items:center}
  .tabs .mtab{padding:9px 14px}
  #tabs span{padding:9px 14px}
  .chip+.chip{margin-left:6px}
  .cnav{padding:10px 14px}
  .hbtn{min-height:36px;min-width:36px}
  .fbar input:not(.switch),.fbar select{padding:9px 10px}
  .fbar input:not(.switch),.fbar select{height:38px}
  .fbar input[type=text]{height:38px}
  .fbar .btn2{height:38px;margin-right:0}
  .btn2,.ropbtn,.danger{min-height:36px}
  button{min-height:36px}
  .pill{min-height:36px}
  th.srt{padding:11px 8px}
  .srow .sctl .switch::before{content:'';position:absolute;inset:-8px}
  .fbar .switch::before{content:'';position:absolute;inset:-8px}
  .glcell .switch::before{content:'';position:absolute;inset:-8px}
  .rop .switch::before{content:'';position:absolute;inset:-8px}
  /* flab 开关（#fnostale）同族补齐（外扩家族 .srow/.fbar/.glcell/.rop
     作用域漏收槽位）。a.vw/.tj 热区 base 已有 ::after 外扩
     （-11px -8px / -11px -4px，纵向 36 达标、横向 33/32 在案备案豁免
     ——此块不再覆写，覆写收窄曾把触屏横向热区压到 ~20px） */
  .flab .switch::before{content:'';position:absolute;inset:-8px}
  /* flab label 文字区同律补热区（开关本体 above 达标、文字部分命中
     高度仅 20px<36px 基准；纵向 -8px 吃满 frow 行距、横向 -4px 同
     a.vw 先例防吃邻件） */
  .flab{position:relative}
  .flab::after{content:'';position:absolute;inset:-8px -4px}
  .srow input[type=text],.srow input[type=number],.srow input[type=time],
  .srow input[type=url],.srow input[type=tel],.srow input[type=password],
  .srow input:not([type]),.fbar input[type=text],.cfgsearch,
  .fbar label input{font-size:16px}
  .srow .sctl input:not(.switch){height:38px}
  .srow .sctl input:not(.switch){font-size:16px}
  .glcell input[type=text]{font-size:16px!important}
  /* 三处触控清单互指（审计）：本块=901+ 粗指针（iPad Pro 横屏）、
     姊妹块=≤900 粗指针（iPad 竖屏带）与 ≤760 任意指针——条件
     语义各异勿合并，触控清单改动三处同步 */}
 /* ===== 改期窗口胶囊+15 点展开微图（tgrow 兼 xrow 类，首格底色须
    压过上方 吸附规则——同短写法特异性不够会被吃掉） ===== */
 /* 改期胶囊触控热区外扩（本体 11px 字+4px 内衬 ≈19px 高低于
    36px 触控基准；::after 同 .dx/.hc/.pbar 先例全宽生效，透明无视觉差）。
    纵向 -9px 外扩到 ~37px；横向只 -4px——外扩过多会吃同行「↗」vw 链接
    与行间隙的点击，且热区命中仍算 .tg 自身（stopPropagation 在元素上），
    不再误触整行 togRow 开出同班比价异功能面板 */
 .tg{display:inline-flex;gap:4px;align-items:center;margin-top:4px;padding:2px 8px;border:1px solid var(--ctlbd);border-radius:var(--r3);font-size:11px;color:var(--tx2);cursor:pointer;transition:border-color .15s;position:relative}
 .tg:hover{border-color:var(--blue);color:var(--blue)}
 .tg::after{content:'';position:absolute;inset:-9px -4px}
 .tg b{font-family:var(--num)}
 .tgrow>td{background:var(--rowalt)}
 .tw tbody tr.tgrow>td:first-child{position:static;background:var(--rowalt);box-shadow:none}
 /* 柱与轴共用同宽容器：柱 flex 填满、轴 space-between 三标——首标/中心
    (出发日恒 15 点正中)/尾标与柱两端及中心柱精确对齐（曾柱区左聚
    ~230px 轴拉满 560px，尾标悬空在柱区外）。display:block 必须显式
    声明：span 内联元素不吃 max-width（曾漏 → 15 柱拉伸成
    整表宽，2K 档柱宽 ~106px 失比） */
 .tgbox{display:block;max-width:460px}
 .tgwrap{display:flex;align-items:flex-end;gap:3px;height:46px;margin:2px 0 4px;width:100%}
 .tgb{flex:1 1 0;min-width:6px;background:var(--tgbar);border-radius:var(--r-xs) var(--r-xs) 0 0}
 .tgb.cheap{background:var(--green)}
 .tgb.lo{background:var(--green)}
 .tgb.cur{box-shadow:inset 0 0 0 1.5px var(--blue)}
 .tgaxis{display:flex;justify-content:space-between;width:100%;font-family:var(--num);font-size:10px;color:var(--mut)}
 .tgleg{display:block;margin-top:3px;font-size:10px;color:var(--mut)}
 /* ===== 2K 宽屏 canvas 高度档（追加规则置末尾）：宽屏画布
    随负 margin 拉宽到 1680 后仍 38vh 高——宽高比失真把曲线拉扁（曾
    4.7:1）；抬档 42vh 并放宽 clamp 上下限（resize 重绘钩子已有）；
     断点随卡宽突破档同步 1800→1920（两块必须联动） ===== */
 @media(min-width:1920px){
  canvas{height:clamp(280px,42vh,460px)}}
 /* 盲文区（#nextrun 状态迁移播报）：clip 法视觉隐身、读屏可达 */
 .vh{position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;
  clip:rect(0 0 0 0);clip-path:inset(50%);white-space:nowrap;border:0}
 /* ===== 移动端（≤760px）合并块（原 5 处分散 @760 块并 1 置尾——760 案维护债；媒体增强块置尾纪律由整个尾区承担，≤390 是 ≤760 的再增强必须声明在后（header padding 同特异性后者胜）） ===== */
 #fltBtn{display:none}
 @media(max-width:760px){

  header{padding:12px 18px}
  header h1{font-size:17px}
  .pill{font-size:14px;padding:5px 12px;min-height:36px}
  #fltBtn{display:inline-block}
  #fltBtn b{background:var(--red);color:#fff;border-radius:var(--r3);padding:0 6px;font-size:11px;margin-left:3px}   /* 暗色覆写见置尾 P2-3（#b3393c） */
  .fbar{display:none}
  .fbar.open{display:block;animation:vin .18s ease}/* 抽屉淡入（复用 vin），免突现 */
  .fbar label,.fbar select,.fbar input{font-size:13px}
  button{padding:11px 16px}
  .hc{width:5px}
 }
 /* ===== 移动端触控目标增强（基础规则之后声明，防同特异性覆盖） ===== */
 @media(max-width:760px){
  .tabs .mtab{padding:9px 14px}
  .tabs .uchip{padding:9px 14px}   /* 用户切换 chip 触控地板（同上族补档） */
  #tabs span{padding:9px 14px}
  nav span{min-height:36px;display:inline-flex;align-items:center}
  .chip{padding:9px 14px;font-size:13px}/* 触控目标 ~36px，间距防误触 */
  .chip+.chip{margin-left:6px}
  .mchip{padding:9px 14px;font-size:13px}/* 与 chip 同触控基准（原 26px 偏小） */
  .fbar input:not(.switch),.fbar select{padding:9px 10px}
  /* 触控基准最后两个漏点：表头排序/配置左导航原 ~34px */
  th.srt{padding:11px 8px}
  .cnav{padding:10px 14px}
 }
 /* 触控增强必须声明在基础规则之后（同特异性后者胜——曾写在前面整块失效） */
 @media(max-width:760px){.rngchip{padding:9px 14px;font-size:13px}
   nav span{padding:9px 18px}
   .hbtn{min-height:36px;min-width:36px}
   .ropbtn,.danger{min-height:36px}
   /* 抽屉触控 ≥38px + 时段挡位允许换行——必须位于全部基础规则之后
      （.fbar input[type=text] (0,2,1) / .wingrp 基础规则声明更后，
      移动规则写在前面会被同特异性后者覆盖=整块失效，两次实锤） */
   .fbar input:not(.switch),.fbar select{height:38px}
   .fbar input[type=text]{height:38px}/* 对齐基础 (0,2,1) 的 height:30px */
   .srow .sctl input:not(.switch){height:38px}
   .fbar .btn2{height:38px;margin-right:0}
   /* 触控热区补账：配置页大量 .btn2（📅/➕/测试）在基础
      规则下 ≈31px 低于 36px 基准；srow 裸 .switch 20px 高——::before
      外扩隐形命中区（::after 已是旋钮本体不可复用；inset 全向外扩）。
       补 .glcell 内开关（启动即扫/无头/调试日志，同 20px 高）。
       开关外扩成员三处与姊妹触控块（≤900coarse/901+coarse）对齐：
       srow/fbar/glcell 一员不缺（同值补档全族清点，防新增开关位
       时只改部分块的家族漂移） */
   .btn2{min-height:36px}
   .srow .sctl .switch::before{content:'';position:absolute;inset:-8px}
   .fbar .switch::before{content:'';position:absolute;inset:-8px}
   .glcell .switch::before{content:'';position:absolute;inset:-8px}
   .rop .switch::before{content:'';position:absolute;inset:-8px}
   /* flab label 文字区热区（开关本体由上方 fbar 开关热区行覆盖，
      label 漏收；与两 coarse 块同值补档，家族计数钉=3） */
   .flab{position:relative}
   .flab::after{content:'';position:absolute;inset:-8px -4px}
   .wingrp{flex-wrap:wrap;white-space:normal;max-width:100%}
   .winsel{flex-wrap:wrap}/* 内层 chips 行也允许折行，否则组仍 390px 溢出 */}
 /* 窄屏航线卡头允许换行（nowrap 摘要在 390px 曾把整页撑出横向滚动） */
 @media(max-width:760px){.rhead{flex-wrap:wrap}
   .rhead .muted{white-space:normal}}
 /* ===== iOS Safari 聚焦不放大：输入字号 <16px 会触发自动缩放 ===== */
 @media(max-width:760px){
  .srow input[type=text],.srow input[type=number],.srow input[type=time],
  .srow input[type=url],.srow input[type=tel],.srow input[type=password],
  .srow input:not([type]),.fbar input[type=text],.cfgsearch,
  .fbar label input{font-size:16px}
  .srow .sctl input:not(.switch){font-size:16px}
  .glcell input[type=text]{font-size:16px!important}}
  /* P2-C：glcell 文本输入内联 13px 锁定，!important 压内联
     （iOS 聚焦自动放大且不回位；仅本媒体内生效，桌面 13px 观感不变） */
 /* ===== savebar 小屏（≤760）防溢出+toast 抬升（从 ≤390 提档：391-760 档 savebar 同样可折双行，toast z-index 300 曾盖住按钮点错格） ===== */
 @media(max-width:760px){
  .savebar{left:12px;right:12px;max-width:calc(100vw - 24px);justify-content:flex-end}
  /* 垫底与 toast 抬升同挂 --sbh 动态单源（双行实高随内容漂移，
     固定 132/148 校准退役；fallback 84+48=132、112+36=148 为
     JS 失效等效值=旧双行校准） */
  #cfgview{padding-bottom:calc(var(--sbh,84px) + 48px)}
  #toasts{bottom:96px;right:12px}
  /* toast 底与 savebar 首行恒差呼吸缝（与视口高度无关）——
     savebar 在场时 toast 整体抬到其上方（实高+bottom+呼吸） */
  body:has(.savebar.on) #toasts{bottom:calc(var(--sbh,112px) + 36px)}}
 /* ===== ≤390px 小屏档（手机竖排末端）：卡距/header 再收一档；声明在 ≤760 合并块之后（header padding 同特异性后者胜） ===== */
 @media(max-width:390px){
  .kpi{padding:10px 12px}
  .grid{gap:8px}
  .ucard{padding:12px 12px}
  header{padding:10px 10px}
  header h1{font-size:15px;letter-spacing:.6px}
  .wrap{padding:0 10px 14px}
  header{margin:0 -10px 4px}
 }
 /* ===== P2-8：.tgbox 460px 上限在 ≤480 视口把明细表顶出横向
    滚动（展开改期胶囊微图时 td ≥460，触屏首行被推出视口外）——≤760 档
    放宽 100%，15 柱在 358px 下每柱 ~18px 仍可读（min-width:6 兜底）。
    追加断点块置尾纪律 ===== */
 @media(max-width:760px){.tgbox{max-width:100%}}
 /* P2-4：健康时间线 ≥1440 拉伸空洞——96 格×8px 左聚、徽标钉死
    右缘，1920 实测 ~740px 空白横在卡片正中。容器保 flex:1 占满、格改
    弹性均分（1920 档 ~13.7px/格、1440 档 ~9.6px，时间轴等距语义不变）。
    审计原建议「容器 flex:0 1 auto 收缩+格 max-width 12px」在 Chrome
    实测格宽归零（收缩容器的 content-size 测量不给可伸缩子项发宽度，
    flex-basis 6px 被无视）——弃用；hover 放大/热区/xhint 不受影响。
     P2-B：弹性门槛 1440→1024——1180/1280/1366 主流本带（wrap 1180
    封顶）恒 214px 左聚空腔（P2-4 同病灶半幅残留）；1024 视口容器
    实测 814px ≥ 格带本宽 768px 不溢出；<1024 保固定 6px + xhint 横滚暗示
    （底部档 flex 收缩会让 390 横滚失效，门槛必须保住） */
 @media(min-width:1024px){
  /* 弹性档格带恒等于容器宽（格 flex 均分铺满），却因 .hc::after
     横向外扩 1px 使 scrollWidth=clientWidth+1 → 横滚条恒在；再叠 hover
     放大出的纵滚条 → 滚动条一进一出，74+ 弹性格全行收缩重排 = 鼠标扫过
     时逐格「呼吸」抖动（真机 1280 实测 sw/cw=971/970、hover sh 37→43）。
     用非滚动容器（clip 优先，老内核回退 hidden）→ 滚动条与可滚区同时
     消失，热点外扩/hover 放大都不再改变几何；裁剪框仍是 37px 衬垫框，
     纵向 -11px 热区与 hover 放大观感均不受影响。 */
  .hcells{overflow:hidden;overflow:clip}
  .hc{width:auto;flex:1 1 6px}
 }
 /* P2-3：暗色筛选角标填充底收深（#ef5350 白字 3.49 欠 → #b3393c
    5.89；与 button.arming 暗色覆写同案，--red 令牌不动） */
 @media(max-width:760px){
  html[data-theme="dark"] #fltBtn b{background:var(--danger-solid)}
 }
 /* 审计 P1：窄带 statline 强制 2 列——auto-fit 在容器
    474-632px 带（视口 ~547-745）折 3 轨，4 格变 3+1，第二行空轨露
    容器 --line 灰底（缝隙法容器底外露）。2 列 4 格整除零空腔；纯
    CSS 零量纲（幽灵格方案在 display:none 容器 grid 列数解析全零）。
    置尾：媒体块覆写须在基础规则之后（LESSONS 二十一.1） */
 @media(max-width:760px){
  .statline{grid-template-columns:repeat(2,1fr)}
 }
 /* P1-1：图床「测试上传」结果行——span 块化（零 div 平衡增量，
    chcard flex 列内与 .hint 同观感）；折展 _setFold 复位 inline 后仍
    回落类上 display:block */
 .ihtest{display:block;font-size:11px;color:var(--mut);margin:-2px 0 4px;
  line-height:1.55;word-break:break-all}
 /* 桌面档 savebar×toast 抬升（≤760 同族先例）：桌面 savebar 高
    59+bottom 18=顶缘 77px，与 toast 基础 78px 仅 1px 巧合缝——文本
    缩放令 savebar 增高即重叠盖住保存按钮。抬到 --sbh+56（fallback
    96=旧校准值，JS 失效等效）；媒体条件与 ≤760 档 calc 抬升互斥，
    不参与层叠竞争 */
 @media(min-width:761px){body:has(.savebar.on) #toasts{bottom:calc(var(--sbh,40px) + 56px)}}
 /* P2-5：教学行左距挪基础 CSS（内联 style 曾在 ≤760 独立成行后
    残留右偏——媒体块 margin 简写可覆写本值，内联则压不过）。
    触屏隐藏的 coarse 块置样式区尾（同选择器 ≤760 块的层叠序） */
 .kbdtips{margin-left:14px}
 /* 审计 P1-1：≥1440 解锁后 statline 通栏/柱区居中/图例左贴边三轴
    分裂——图例与 .pulsewrap 的 center 同轴。柱区 center 全宽域生效
    （L552 无媒体壳），同轴条件必须同域：去 761 媒体壳改无条件
    （窄档少轮次柱簇居中/图例左贴边 Δ125px 双轴残留） */
 #pulseLegend{justify-content:center}
 /* 审计 P2-4：≤390 四片 3+1 折行后「渠道健康」孤片成行——两列网格
    均分两行（内联 display:none 的隐藏态不受影响：内联优先级恒高于
    样式表，JS 显示置 style.display='' 时回落本规则） */
 @media(min-width:541px) and (max-width:760px){
  /* --mtabsh 随消费带补齐：本带切换器吸顶（下方 sticky）而变量只在
     ≤540 定义——scroll-padding 消费裸 var 整条 calc 塌 0（声明
     invalid 落 auto），锚点落点被 header+吸顶条遮挡实测 102px。
     52px 与 ≤540 同值（宁多勿遮既定取舍）；切换器同款吃
     height:var(--mtabsh)（吸顶双条贴合无透缝，与 ≤540 同构） */
  :root{--mtabsh:52px}
  #montabs{display:flex;gap:6px;height:var(--mtabsh);align-items:center;
  position:sticky;top:var(--hdh,76px);z-index:6;background:var(--card);
  border-bottom:1px solid var(--line);flex-wrap:nowrap;overflow-x:auto;
  scrollbar-width:none}
  #montabs::-webkit-scrollbar{display:none}
  /* 明细筛选条同款吸顶（≤540 同构：数百行明细深滚后筛选/日期排序
     入口随时可达；top 过切换器让位防双条重叠；单行化——类别片
     nowrap 横滚、图例隐藏语义并入 fltBtn title，该档 .tabs 恒为
     吸顶条无非吸顶位） */
  #montab-details .tabs{position:sticky;
    top:calc(var(--hdh,76px) + var(--mtabsh));z-index:6;
    background:var(--card);margin:0 -12px;padding:8px 12px 2px;
    border-bottom:1px solid var(--line);
    flex-wrap:nowrap;overflow-x:auto;scrollbar-width:none}
  #montab-details .tabs::-webkit-scrollbar{display:none}
  #montab-details .tabs span{flex:0 0 auto;white-space:nowrap}
  #montab-details .tabs>b.muted{display:none}
  /* 明细跟页滚（吸顶可达的结构前提，与 ≤540 处方同构）：.tw 内滚
     max-height 把页面总高限死时吸顶触发点永超最大滚动=声明死代码；
     放开后 montabs 精确生效，切片续载/End 跳底/重建滚动位三条路径
     的宽度门随族同步 540→760（脚本区 window.scroll 门）。
     已知代价（r265 审计备案）：thead sticky 宿主仍是 .tw（横滚容器
     强制竖向滚动语境），本带页滚深处列头不可达=结构性死档——列语义
     由首列吸附（价格列恒可见）+montabs 承担，9 列表拖回最左即可重
     校准；强行修=恢复内滚杀 montabs 吸顶或列裁剪撤决策信息，两害
     皆大于列头记忆负担，不再回头 */
  .tw{max-height:none}}
 /* 审计 P2-7：窄窗（fine pointer）页脚快捷键教学随上行折行突兀——
    独立成行（真实手机 coarse 由样式区尾 coarse 块隐藏，本块只影响
    桌面窄窗） */
 @media(max-width:760px){.kbdtips{display:block;margin:6px 0 0;margin-left:0}}
 /* 审计 P2-2：「用时」尾段省略截断带 391-509 与 761-900 同病灶——
    ssub 换行放行门 ≤900 档（复合信息换行无害） */
 @media(max-width:900px){.stat .ssub{white-space:normal}}
 /* 审计 P2-3：生产态 hdmeta（下轮倒计时在场）窄机临界溢出——折行放行 */
 @media(max-width:900px){.hdmeta{flex-wrap:wrap}}
 /* 审计 P2-1：761-900 带 header 折行，scroll-padding 补偿须过
    header 实高（行为钉守护，历史单行 72px 形制的 118px 档已被
    761+ 块 88px 与带内覆写 106px 按源码序接替） */
 @media(max-width:900px){html{scroll-padding-top:calc(var(--hdh,54px) + 34px)}}
 /* 审计 P2-7：390 档吸附价格列被行内退改徽标撑到可见表宽 53%
    （td nowrap+行内 .pretax 单行不折）——退改词面折到价格第二行
    （信息不丢，首列回落） */
 @media(max-width:760px){#ftable td.price .pretax{display:block;font-size:10px}}
 /* 桌面档价格列 ≥2 枚徽标同折第二行（审计 P2-5）：⚠资格专享/退改
    等多徽标行曾把 96px 节奏锚撑到 ~270px 挤占航班列配额；:has 计数
    单徽标行维持行内（税前独挂形态最常见，不折） */
 @media(min-width:761px){#ftable td.price:has(.pretax ~ .pretax) .pretax{display:block;margin-top:2px}}
 /* 触屏设备无物理键盘：页脚快捷键教学段纯视觉噪音，coarse 指针
    一律隐藏。本块必须位于上面 ≤760「独立成行」块之后——同选择器
    同特异性媒体块源码序后者胜（coarse+窄屏双命中时隐藏是最终语；
    曾置 L1153 邻位被置尾追加的 760 块反杀，触屏手机 display:block
    复活成误导文案） */
 @media(pointer:coarse){.kbdtips{display:none}}
 /* ===== 媒体增强块置尾纪律——
    同选择器覆写块必须在全部早前声明之后 ===== */
 /* P2-3：≤760 类别/日期独立列收进航班格 mmeta——390 首屏吸附价格
    列+类别+日期三列挤占后航班列仅剩 ~109px 窄条（核心识别信息被切，
    须横滚才见全名）。类别 tag 与日期小字预置进航班格（桌面
    display:none 零视觉差），窄屏隐藏独立列，信息零删减；列 DOM 序
    不变（display:none 仍在文档流），sortCol 按 data-k 排序、CSV 独立
    生成、xrow colspan=9 均不受扰。预置律：每行常驻一个 mmeta 容器，
    交互路径零 childList 变更（扩展免疫同款） */
 #ftable .mmeta{display:none}
 @media(max-width:760px){
  #ftable th.catt,#ftable td.catt,#ftable th.datd,#ftable td.datd{display:none}
  /* 日期列隐藏的对称补偿：表头排序入口消失，「⇅日期」chip 顶上
     （buildDateChips 行尾，与 sortCol 单源同状态机） */
  .srtchip{display:inline-block}
  #ftable .mmeta{display:flex;gap:6px;align-items:center;margin-top:3px}
  #ftable .mdat{font-size:10px;color:var(--mut)}
  /* P2-4：xrow 同班比价链 ≤760 折行——th,td nowrap 作用于 colspan
     行，五渠道链单行延伸把结论句「（可省 ￥N）」藏到两屏外；tgrow
     改期微图（xrow tgrow 双类）已有自身宽度放宽，:not 排除不受扰 */
  #ftable tr.xrow:not(.tgrow) td{white-space:normal;line-height:2}
  /* 比价链锚本体不内折：td 折行放开后断点可落在锚内部（价与 ↗
     被拆两行、「↗」独行实测）；锚整体 nowrap，断点退到「＜」分隔符
     处（链整体仍可折）——源码钉 tests/test_v15109_fields；行为面
     playwright 探针验证（Range.getClientRects 锚单段） */
  #ftable tr.xrow td a.vw{white-space:nowrap}
  /* P2-5：深滚动跳转落点补偿 136px——118px 档行内 📈/日历格跳转
     落点顶部被 sticky header 盖 16px；实测 header 随内核/仿真口径
     105~134 波动，补偿宁多勿遮（余量=落点上方留白，不产生遮挡）；
     768 档 header 109 由 ≤900 块 118px 服务，本块仅 ≤760 不越界。
     --tabsh=明细吸顶筛选条实高（ResizeObserver 动态单源，非明细
     视图条隐藏=0 自动降档，JS 失效 0px 兜底回落原值）——补偿过
     「吸顶三件」防落点藏条后（≤760 两带同公式，390 实测 ≤540
     同族遮挡一并收口） */
  html{scroll-padding-top:calc(var(--hdh,134px) + var(--mtabsh) + var(--tabsh,0px) + 4px)}}
 /* ≤540 档明细 tabs 行 sticky 吸顶——筛选/分类入口原在首屏
    折叠线下 ~150-180px（390 档 fltBtn top≈994 / vh 844），数百行
    明细滚动中随时可筛也是高频路径。top 对齐 ≤760 档 sticky header
    134px；负 margin 外扩横贯卡片+padding 回补（sticky 条卡片底色
    衬底防透行）；z 低于 header(50)、高于表内 sticky 件 */
 @media(max-width:540px){
  /* 头部 meta（倒计时+更新时刻）独占行右对齐：390 物理宽度下限
     （h1 行+hdx 行+meta 行三行是窄带内容宽度必然；541-900 hdmeta
     并入 hdx 单行，header 两行制） */
  .hdmeta{flex-basis:100%;justify-content:flex-end}
  /* 视图切换器同款吸顶（与筛选条能力对称：深滚切视图不再回滚
     ~830px）：单行横滚锁高 --mtabsh，明细筛选条 top 以 calc 联动
     让位（吸顶双条不重叠，高度改动一处变量全联动）；锚点补偿
     同步过吸顶双条总高 */
  :root{--mtabsh:52px}
  /* top 动态贴 header 实高（--hdh 单源）：固定 134px 按无倒计时态
     校准，生产 ⏱ 倒计时 chip 折行使实高 105~134 漂移——固定值与
     header 间透缝 18-29px 且随文案漂移（内容从缝中滚过） */
  #montabs{position:sticky;top:var(--hdh,134px);z-index:6;display:flex;gap:6px;
    height:var(--mtabsh);box-sizing:border-box;align-items:center;
    background:var(--card);margin:0 -12px;padding:0 12px;
    border-bottom:1px solid var(--line);overflow-x:auto;
    flex-wrap:nowrap;scrollbar-width:none}
  #montabs::-webkit-scrollbar{display:none}
  #montabs .mtab{flex:1 0 auto;text-align:center;white-space:nowrap;
    padding:9px 10px;
    /* 竖向 9px=触控 36px 地板：本条 ID 特异性 (1,1,0) 恒压
       .tabs .mtab 触控增强块 (0,2,0)，7px 曾把触控高压到 32px */}
  #montab-details .tabs{position:sticky;
    top:calc(var(--hdh,134px) + var(--mtabsh));z-index:6;
    background:var(--card);margin:0 -12px;padding:8px 12px 2px;
    border-bottom:1px solid var(--line);
    /* 吸顶条单行化（旧吸顶态 3 行高 131px，叠 header 后固定占屏
       ~31%）：类别片 nowrap 横滚、图例 ≤760 全带隐藏（541-760
       同律见 1313 块；语义并入 fltBtn title——两带 .tabs 恒为
       吸顶条无非吸顶位） */
    flex-wrap:nowrap;overflow-x:auto;scrollbar-width:none}
  #montab-details .tabs::-webkit-scrollbar{display:none}
  #montab-details .tabs span{flex:0 0 auto;white-space:nowrap}
  #montab-details .tabs>b.muted{display:none}
  /* 明细跟页滚（吸顶可达的结构前提）：.tw 内滚 max-height 把页面
     总高限死，吸顶触发点（滚动 ~821px）永超页面最大滚动（~756，
     差口 65-156px 结构性），sticky 是死代码；放开后 tabs 以下内容
     随页增长，吸顶精确生效。切片续载/End 跳底/重建滚动位三条内滚
     路径同轮重接线页面滚动（脚本区 window.scroll 门）。
     scroll-padding 与 ≤760 块同公式（含 --tabsh 过吸顶三件） */
  .tw{max-height:none}
  html{scroll-padding-top:calc(var(--hdh,134px) + var(--mtabsh) + var(--tabsh,0px) + 4px)}}
 /* 390 档 wrap padding 收窄 10px 后吸顶条负 margin 联动（追加块置尾
    纪律：≤540 块在源码更后，同特异性覆写必须在其后再声明） */
 @media(max-width:390px){#montabs{margin:0 -10px;padding:0 10px}
 /* 五件恒超容器 3px（gap 6×4+件宽）：mtab 横向收 2px 消隐藏溢出
    （低于 xhint 阈值 +4 的提示盲区）；须用 ID 特异性覆写——基础块
    #montabs .mtab (1,1,0) 恒压类选择器 (0,2,0)，声明序在后同特异性
    胜出 */
 #montabs .mtab{padding:9px 8px}}
 /* 桌面视图切换器吸顶：深滚切视图不回滚 ~830px（≤540 同款能力；
    top 贴 header 底，背景衬底防透行、底边线与 ≤540 形制一致；
    锚点补偿同步过 header+吸顶条总高）。追加块置尾纪律：与 ≤540/
    ≤390 同选择器块的命中域不相交（761+ 桌面档），源码序即生效序 */
 @media(min-width:761px){
  #montabs{position:sticky;top:var(--hdh,54px);z-index:6;background:var(--card);
   border-bottom:1px solid var(--line)}
  html{scroll-padding-top:calc(var(--hdh,54px) + 34px)}}
 /* 761-900 带固定校准块（吸顶 76px/补偿 106px 的带内覆写）随 --hdh
    动态化退役：该块按「折行实高 ~72px」单值校准，生产倒计时文案使
    实高 72→109 浮动后固定值反而盖住切换器 33px（WD P1-1 实测）——
    变量贴实高自动跟随，fallback 54px 与该带 JS 失效旧态等效 */
 /* 全直飞视图整列「—」零信息：中转列条件隐藏（table() 按当前筛选
    结果集切 no-transfer 类；xrow colspan=9 不受扰——display:none 列
    零宽，colspan 多余一格无视觉影响，行为钉验横贯） */
 #ftable.no-transfer th:nth-child(8),#ftable.no-transfer td:nth-child(8){display:none}
 /* 明细价格主判据字号阶梯：cozy 档 15px 与次要字段拉开主次
    （compact 档保持基础字号——密度档语义优先）；1440 零横滚为
    前提钉守护（uitest EN-7 三钉） */
 :root:not([data-density=compact]) #ftable td.price{font-size:15px}
 /* 配置即时校验：输入越界标红边+行内提示（与 saveCfg 共用
    GLB_RANGES 单源表，防两处漂移） */
 .glcell input.invalid{border-bottom-color:var(--red)!important}
 .glcell .verr{display:none;color:var(--red);font-size:11px;margin-top:4px}
 /* 明细吸顶条+视图切换器横滚暗示（P1-W1）：::after 装饰层渐隐
    挂 xhint 点亮——非容器 mask（mask 会把 sticky 的 fltBtn 一起淡
    出）；fltBtn sticky 钉可视右缘，筛选抽屉 ≤760 唯一入口不依赖
    滚动可达（fine pointer 窄窗滚轮在横滚条上零位移实测）。媒体门
    与横滚形制同域（≤760：≤540 与 541-760 两带吸顶条均为单行横滚
    形制；wide 档 .tabs 折行无溢出，本组规则惰性）。追加置尾：
    同选择器早前块命中域按源码序以本块为准 */
 @media(max-width:760px){
 #montab-details .tabs::after{content:'';position:absolute;top:0;
  right:0;bottom:0;width:12px;pointer-events:none;opacity:0;
  background:linear-gradient(90deg,transparent,var(--card));
  transition:opacity .15s}
 #montab-details .tabs.xhint::after{opacity:1}
 #montabs::after{content:'';position:absolute;top:0;
  right:0;bottom:0;width:12px;pointer-events:none;opacity:0;
  background:linear-gradient(90deg,transparent,var(--card));
  transition:opacity .15s}
 #montabs.xhint::after{opacity:1}
 #montab-details .tabs>#fltBtn{position:sticky;right:0;z-index:1;
  box-shadow:0 0 0 4px var(--card)}}
 /* 页脚/演示条链接 hover 反馈（NOTIFY 轻页同位对齐：
    真实可点链接悬停零反馈属缺陷）；基态去 UA 恒下划线与
    .numlink/a.vw 同语言（悬停才显形） */
 #foot a,.demoBar a{text-decoration:none}
 #foot a:hover,.demoBar a:hover{text-decoration:underline}
 /* 1000-1439 中带日历恒单行（P1-2）：flex-wrap 下 shrink
    不跨折行线——1280 档首行 14 格后第 15 格必折行（1106 容器
    14×74+13×5=1101 恰满），末行孤悬「★最低」绿格扎眼。改 grid
    auto-fit 等分：格数多少恒单行、等宽填满（69px@1280/63px@1024，
    均高于内容下限）；<1000 维持折行（768/390 多格折行是设计形制）、
    ≥1440 本就单行不动（flex 基础规则保留零回归面）。追加置尾 */
 @media(min-width:1000px) and (max-width:1439px){
 .calgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(0,1fr))}
 .calcell{max-width:none;flex:none}}
 /* ≤999 带跨行等宽（r246 P3-1）：flex-wrap 行内 grow 使折行
    两行格宽漂移（768 实测首行 81/次行 93 列边界错位）——grid 按最小
    74px 自动列数，折行后跨行同列恒等宽（十七§7 grid 等分族；auto-fit
    恒单行形制在此带会把 15 格压到 48px/格破内容下限，勿改用）。
    r247 扩带收编：541-999 修后 ≤540 带同族残留实锤（390 档末行
    3 格 108 vs 上行 80 差 28px）——flex grow 错位不分级带，窄带
    同病同修；360 档 grid 后 4 列 4 行（列宽 ~79 > 内容下限 74） */
 @media(max-width:999px){
 .calgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(74px,1fr))}
 .calcell{max-width:none;flex:none}}
 /* 选中态悬停反馈（r230 P2-3）：.on 族悬停零反馈与 .pill:hover
    brightness 先例不一致，选中 chip 恰是「再点=取消」高频目标。
    置尾追加（层叠序：同特异性后者胜，LESSONS 二十一§1；filter
    无既有声明零冲突面）。行为钉 uitest「选中态悬停反馈」 */
 .tabs span.on:hover,nav span.on:hover,.chip.on:hover,
 .rngchip.on:hover,.cnav.on:hover{filter:brightness(1.07)}
 /* 明细 tabs 档位图例 761-860 带孤行（r235 P2-4，十七§7 flex 孤格
    族）：图例 margin-left:auto 右对齐独占第二行时左贴行首（跟 tabs
    起缘读）；541-760 吸顶单行横滚不受扰、≤540 已隐藏、≥861 同行 */
 @media(min-width:761px) and (max-width:860px){
 #tabs b.muted{margin-left:0!important;flex-basis:100%}}
 /* r244 P2-1：opscard 四钮包 .opsbtns（桌面=原 .row 折行形制零行为差，
    供移动档单行化取件）。提示行内联样式挪基础规则（内联优先级压过
    媒体覆写=移动隐藏失效，P2-5 同款判例）。移动首屏数据上移：四个
    日频级操作钮+提示行曾在 ≤760 档折行竖排占首屏 ~60% 高（390 实测），
    KPI/明细被推出首屏——按钮行收编单行横滚（nowrap+overflow-x，触控
    36px 基准与间距防误触保留）、提示行隐藏（桌面档不动）。媒体覆写
    置尾（LESSONS 二十一§1）；#opscard 限定作用域防同类名误伤 */
 .opsbtns{display:flex;gap:10px;flex-wrap:wrap;align-items:center;flex:1 1 100%}
 #opscard .row>.muted{display:block;width:100%;margin-top:4px;font-size:11px}
 @media(max-width:760px){
  #opscard .opsbtns{flex-wrap:nowrap;overflow-x:auto;scrollbar-width:none}
  #opscard .opsbtns::-webkit-scrollbar{display:none}
  #opscard .opsbtns>button{flex:0 0 auto;white-space:nowrap;min-height:36px}
  /* 横滚暗示（r247 W1）：「预览推送」被裁切、「推送记录」不可见
     且滚动条隐藏=零暗示。mask 渐隐挂 xhint 点亮——::after 形态只
     适用 sticky 吸顶件（absolute 层随内容滚走），本容器是普通横滚
     无 sticky 子件，用 .hcells 同构 mask；桌面档折行无溢出，类恒
     不挂=惰性。同批挂点：健康渲染/showMonTab/resize 三判定批次 */
  #opscard .opsbtns.xhint{-webkit-mask-image:linear-gradient(90deg,#000 calc(100% - 12px),transparent);mask-image:linear-gradient(90deg,#000 calc(100% - 12px),transparent)}
  #opscard .row>.muted{display:none}}
 /* 矮窗 canvas 比例档（审计 P3-6）：r236 取大语义下宽短窗由 28vw
    主导（1280×540 半屏 → 358px，占视口 66%），基础档 240px 下限同
    样超出矮窗预算——首屏操作区（模式/范围 chips、航线 chips）被推
    出一滚。矮窗带（视口高 <600 的桌面窗）收一档 clamp(200px,34vh,
    280px)；min-width:761px 限定桌面（移动竖屏 38vh 形制不受扰）。
    媒体覆写置尾（LESSONS 二十一§1）=层叠序胜过基础档与 ≥1920 档，
    矮窗优先级正确；uitest 视口高全 ≥844 不触发 */
 @media(max-height:600px) and (min-width:761px){
  canvas{height:clamp(200px,34vh,280px)}}
 /* ≤760 档筛选钮键盘焦点环（audit P1-1）：吸顶 sticky 衬底 halo 规则
    （特异度 (1,1,0)）整条覆盖焦点环族（(0,2,x)，ID 恒压 class）——
    亮色白 halo 落白条、暗色深 halo 落深条均近零对比，筛选抽屉唯一
    入口键盘无可见焦点。置尾复声明双影叠加（首列表头 th.srt 先例）：
    inset 环落按钮自身底色（headbg 对 --blue 充足），外层 halo 原样
    保留（其本职=压住横滚 chips 防透色），两个职能并存 */
 @media(max-width:760px){
  #montab-details .tabs>#fltBtn:focus-visible{box-shadow:inset 0 0 0 2px var(--blue),0 0 0 4px var(--card);outline:none}}
</style></head><body><div class="wrap">
<header id="hdcard"><h1><span class="logo">✈️</span>机票监控台</h1>
 <div class="hdx"><span id="ntBtn" class="hbtn" role="button" tabindex="0" aria-label="达标浏览器通知开关" onclick="togNotify()" title="达标时浏览器通知+提示音">🔕</span><span id="themeBtn" class="hbtn" role="button" tabindex="0" aria-label="切换亮暗主题" onclick="cycleTheme()" title="亮/暗/自动">🌗</span><span id="denBtn" class="hbtn" role="button" tabindex="0" aria-label="切换界面密度" onclick="cycleDensity()" title="密度">≡</span><span class="pill" id="pill" title="数据通道状态：加载中" onclick="jumpQual()">加载中…</span>
  <span class="hdmeta"><span id="nextrun" class="cdt" role="timer" aria-label="距下一轮扫描倒计时" style="display:none"></span><span id="nrLive" class="vh" aria-live="polite"></span><span id="updated" style="font-family:var(--num)"></span></span></div></header>

<datalist id="citydl"></datalist>
<div class="demoBar" id="demoBar" role="status" style="display:none">🎪 演示模式：数据为本地合成，仅作功能预览 · <a href="https://github.com/dengmeiluan/ticket-monitoring" target="_blank" rel="noopener">下载源码或发行包</a>即可监控真实票价</div>
<div class="verbar" id="verbar" role="alert" style="display:none">🔄 服务端已升级 <b id="verTxt"></b>，本页面是旧版、功能可能异常 —— <a href="#" onclick="location.reload();return false">点此刷新</a></div>
<nav id="mainnav"><span id="navMon" class="on" onclick="switchView('mon')">📊 监控</span>
 <span id="navCfg" onclick="switchView('cfg')">⚙️ 配置<i id="navDirty" style="display:none;color:var(--warn-deep);font-style:normal;margin-left:2px" title="配置有未保存修改">●</i></span></nav>
<div id="monview">
<div class="ucard" id="opscard"><div class="row">
 <div class="opsbtns">
 <button onclick="api('run','立即扫描全部航线？将触发采集与各用户钉钉推送',this)">🔄 立即扫描一轮</button>
 <button class="warn" onclick="api('push','向所有已配置用户推送走势报告？',this)">📈 推送走势报告</button>
 <button class="warn" id="pvBtn" onclick="previewPush()">👁 预览推送</button>
 <button class="warn" onclick="pushLog()">📨 推送记录</button>
 </div>
 <div class="frow" id="userPills" style="display:none;width:100%;margin-top:2px"></div>
 <span class="muted" id="opsHint">数据变化才刷新（悬停/展开不打断）· 页面隐藏时暂停轮询</span></div></div>

<div class="tabs" id="montabs" style="display:none" onkeydown="_roving(event,this);_rovingV(event,this)">
 <span class="mtab on" data-t="overview" data-rv tabindex="0" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();showMonTab(this.dataset.t)}">🎯 概览<i id="ovAlert" role="img" aria-label="采集或推送通道有异常，详情见渠道健康" title="采集失败或推送连败——详情见「渠道健康」" style="display:none;width:7px;height:7px;border-radius:50%;background:var(--red);margin-left:5px;vertical-align:2px"></i></span>
 <span class="mtab" data-t="trend" data-rv tabindex="0" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();showMonTab(this.dataset.t)}">📈 走势 · 日历</span>
 <span class="mtab" data-t="details" data-rv tabindex="0" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();showMonTab(this.dataset.t)}">📋 航班明细</span>
 <span class="mtab" data-t="health" data-rv tabindex="0" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();showMonTab(this.dataset.t)}">🏥 渠道健康</span>
 <span class="uchip" id="mtabUser" style="display:none" data-rv tabindex="0" role="button" aria-label="切换用户" onclick="mtabUserNext()" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();mtabUserNext()}"></span></div>

<div id="montab-overview" role="tabpanel">
<div id="users"><div class="ucard"><div class="grid">
 <div class="kpi d"><div class="sk" style="height:12px;width:45%"></div><div class="sk" style="height:30px;width:52%;margin:8px 0"></div><div class="sk" style="height:10px;width:68%"></div></div>
 <div class="kpi t"><div class="sk" style="height:12px;width:45%"></div><div class="sk" style="height:30px;width:52%;margin:8px 0"></div><div class="sk" style="height:10px;width:68%"></div></div>
</div><div class="sk" style="height:12px;width:58%;margin-top:14px"></div></div></div>

<div class="ucard" id="pulsecard" style="display:none"><div class="uhead">
  <span style="display:flex;align-items:center;gap:9px;flex-wrap:wrap"><span class="seclab inline"><span class="no">01</span><span class="zh">运行脉冲</span><span class="en">PULSE</span></span></span>
  <span class="muted">每根柱 = 一轮扫描 · 高度 = 采集行数 · 红帽 = 有渠道失败 · 悬停看明细 · 点击柱跳渠道健康</span></div>
 <div class="statline" id="statline"></div>
 <div class="pulsewrap" id="pulsebars" onkeydown="_roving(event,this)"></div>
 <div class="legend" id="pulseLegend" style="margin-top:8px"></div></div>
</div><!-- /montab-overview -->

<div id="montab-trend" role="tabpanel" style="display:none">
<div class="ucard" id="chartcard"><div class="uhead"><span style="display:flex;align-items:center;gap:9px;flex-wrap:wrap"><span class="seclab inline"><span class="no">02</span><span class="zh">价格走势</span><span class="en">TREND</span></span><span id="chartTitle" style="font-weight:700;font-size:14px"></span></span>
 <span style="display:inline-flex;align-items:center;gap:8px;flex-wrap:wrap"><span class="mdgrp"><span class="rngchip on" id="mdLine" onclick="setMode('line')">折线</span>
 <span class="rngchip" id="mdK" onclick="setMode('kline')">K线</span></span>
 <span class="mdgrp"><span class="rngchip on" id="rng48" onclick="setRange('48h')">48h</span>
 <span class="rngchip" id="rng7d" onclick="setRange('7d')">7 天</span></span></span></div>
 <div class="frow" id="chartRoutes"></div>
 <div class="chartwrap"><canvas id="chart" tabindex="0" role="img" aria-label="价格走势图：聚焦后按左右方向键逐点读数，Home/End 跳首尾，Enter 看该轮明细"></canvas>
  <div class="chart-empty" id="chartEmpty" style="display:flex">数据加载中…</div></div>
 <div class="legend"><span id="lgDirect"><b style="background:var(--blue)"></b>直飞最低</span>
  <span id="lgTrans"><b style="background:var(--orange)"></b>中转最低</span>
  <span id="lgZone" title="行情价低于达标线的区间；未必可出手（达标以环标为准）"><b style="background:var(--okzone)"></b>线内区间</span><span id="lgThD"><b style="background:var(--red)"></b>直飞达标线</span><span id="lgThT"><b style="background:var(--thline)"></b>中转达标线</span>
  <div class="muted" id="ringNote" style="flex-basis:100%;font-size:11px;margin-top:2px"></div></div></div>

<div class="ucard" id="calcard" style="display:none"><div class="uhead"><span style="display:flex;align-items:center;gap:9px;flex-wrap:wrap"><span class="seclab inline"><span class="no">03</span><span class="zh">价格日历</span><span class="en">CALENDAR</span></span><span id="calTitle" style="font-weight:700;font-size:14px"></span></span>
 <span class="muted" id="calStats"></span></div>
 <div class="calgrid" id="calgrid"></div></div>
</div><!-- /montab-trend -->

<div id="montab-details" role="tabpanel" style="display:none">
<div class="ucard" id="tablecard"><div class="uhead"><span style="display:flex;align-items:center;gap:9px;flex-wrap:wrap"><span class="seclab inline"><span class="no">04</span><span class="zh">航班明细</span><span class="en">DETAILS</span></span></span>
 <span class="muted" id="fcnt" style="font-family:var(--num)"></span></div><div class="tabs" id="tabs">
  <span data-f="all" class="on">全部</span><span data-f="d">✈️ 直飞</span>
  <span data-f="tq">🔁 中转·达标</span><span data-f="t">🔁 中转·全部</span>
  <span data-f="q">🔥 仅达标</span>
  <span data-f="bag">🧳 直挂</span>
  <span id="fltBtn" aria-expanded="false" aria-controls="fltwrap" onclick="togFlt()" title="筛选；档位图例：深绿=真达标 · 描绿=行情破线（行情价低于达标线但未达标，未必可出手，达标以🔥/环标为准） · 琥珀=擦边">🎛 筛选<b id="fltN" style="display:none"></b></span>
  <!-- 档位图例常驻（触屏读不到 price 格 title 的补位）：b 元素避开 .tabs span 胶囊底；「未必可出手」语义收进 title 悬停防行尾溢出；≤540 全档隐藏、语义并入 fltBtn title（吸顶条单行化），宽档常驻不受扰 -->
  <b class="muted" style="margin-left:auto;font-size:11px" title="描绿=行情破线：行情价低于达标线但未达标，未必可出手（达标以🔥/环标为准）">深绿=真达标 · 描绿=行情破线 · 琥珀=擦边</b></div>
 <div class="fbar" id="fltwrap"><div class="frow" id="datechips"></div>
  <div class="frow" id="routechips"></div>
  <div class="frow" id="platchips"></div>
  <div class="frow" style="align-items:center">
   <span class="wingrp"><span class="chiplab">出发时段：</span><span id="wdep" class="winsel"></span></span>
   <span class="wingrp"><span class="chiplab">到达时段：</span><span id="warr" class="winsel"></span></span>
   <label>价格 ￥<input type="text" id="fpmin" aria-label="价格下限" style="width:72px" placeholder="不限" oninput="applyFltD()"> –
    <input type="text" id="fpmax" aria-label="价格上限" style="width:72px" placeholder="不限" oninput="applyFltD()"></label>
   <label>搜索 <input type="text" id="fq" style="flex:1 1 120px;max-width:180px;width:auto" placeholder="航班号/航司/中转" oninput="applyFltD()"></label>
   <label class="flab"><input type="checkbox" class="switch" id="fnostale" onchange="applyFlt()"> 隐藏补位数据（·Nh前）</label>
   <button class="btn2" onclick="resetFltUI()">重置筛选与排序</button>
   <button class="btn2" onclick="expCsv()">⬇ 导出CSV</button>
   <span class="muted">点击表头可排序（再点切换升降序）</span>
  </div></div>
 <div class="tw"><table id="ftable"><tr class="erow"><td colspan="9">加载中…</td></tr></table></div></div>
</div><!-- /montab-details -->

<!-- 审计 P2-5：display 翻转架构下键盘 Tab 序按 DOM 序——明细(04)
     原在健康(05)之后，与视觉 tab 序相反；纯文本搬移零逻辑影响 -->
<div id="montab-health" role="tabpanel" style="display:none">
<div class="muted" id="healthEmpty" style="display:none;padding:34px 0;text-align:center">
 暂无扫描记录——完成一轮采集后，这里会出现 24h 渠道健康时间线</div>
<div class="ucard" id="healthcard" style="display:none"><div class="uhead"><span style="display:flex;align-items:center;gap:9px;flex-wrap:wrap"><span class="seclab inline"><span class="no">05</span><span class="zh">渠道健康</span><span class="en">HEALTH</span></span><span class="muted">近 24h · 每格一轮扫描 · 点击格子看该轮日志</span></span>
 <span class="muted"><span id="hroundcnt"></span><span id="hsrcNote">解析自 monitor.log</span></span></div>
 <div id="hbody"></div>
 <div id="pushhl"></div>
 <div class="legend">
  <span><b style="background:var(--green)"></b>成功</span>
  <span><b style="background:var(--orange)"></b>部分/降级</span>
  <span><b style="background:var(--red)"></b>失败</span>
  <span><b class="hlh"></b>维护</span>
  <span><b style="background:var(--line)"></b>未扫描</span></div></div>
</div><!-- /montab-health -->
</div><!-- /monview -->

 <div id="cfgview" style="display:none">
 <div class="cfglayout">
 <aside class="cfgnav" id="cfgnav">
  <div class="cfgnav-t">配置分区</div>
  <input id="cfgSearch" class="cfgsearch" aria-label="搜索配置项" placeholder="🔍 搜索配置项"
   oninput="CFGQ=this.value;cfgFilterD()">
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
  <button class="btn2" onclick="loadLogin(this)">🔄 刷新状态</button>
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
<div id="savebar" class="savebar" role="status">
 <span class="dot"></span><span id="saveTxt">有未保存的修改</span>
 <button onclick="saveCfg()">💾 保存并生效</button>
 <button class="warn" onclick="discardCfg()">放弃更改</button>
</div>
<div id="pvMask" class="pvmask" onclick="if(event.target===this)closePv()">
 <div class="pvcard" role="dialog" aria-modal="true" aria-label="钉钉推送预览">
  <div class="pvhead"><span id="pvTitle">预览</span><span class="pvx" id="pvClose" role="button" tabindex="0" aria-label="关闭预览" onclick="closePv()" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();closePv()}" title="关闭（Esc）">✕</span></div>
  <div class="pvbody" id="pvBody"></div>
  <div class="pvfoot muted" id="pvFoot">本地近似渲染（标题/段落/加粗/链接/引用/进度条）· 明细总表图仅真实推送携带 · <span class="nw">以钉钉客户端实际效果为准</span></div>
 </div>
</div>
<footer id="foot" class="muted"></footer>
</div>
<script>
let S=null,F='all',U=0,SORT={k:'price',dir:1},FLT={plats:new Set(),routes:new Set(),dates:new Set(),dep:null,arr:null,pmin:0,pmax:0,no:false,q:'',_platsInit:false};
let LASTTXT='',NEXTRUN=null,TICKED=false,CHR={};
const $=id=>document.getElementById(id);
/* 主题变量读取（走势绘制与悬停共用；drawHover 不得误引 chart 局部
   同名常量——折线悬停十字线会每次 mousemove 抛 ReferenceError 整体失效） */
const cssv=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
/* 智能刷新：响应逐字不变则跳过重渲染（悬停/展开/滚动不被打断）；
   页面不可见时不轮询，切回立即拉一次；上一笔未回不叠发
   （服务端重建期间叠发会触发并发重建，越等越慢） */
let LOADN=false;
function _markStale(svc){/* fetch 失败时五处静态「加载中…」骨架同步置错误态：
   pill 已明说服务异常/未启动而表体/配置区/概览骨架仍「加载中…」=永不到达
   的假等待；svc=服务在线的失败形态传「服务异常」（500 错误体与 pill 同轨），
   缺省=服务未启动（网络不可达）；ftable/loginRows/users 恢复轮重写自愈，
   cfgglobals 仅 loadCfg 首载重写（不承诺自动刷新，文案如实）；chartEmpty
   只在空态/加载态在场时翻新（已绘制图表 display:none 不动，保陈旧真数据） */
  const msg=(svc||'服务未启动')+'，恢复后自动刷新';
  const msgCfg=(svc||'服务未启动')+'，恢复后刷新页面';
  _ROWS=null;_CHUNKS=[];_NDRAW=0;   /* 失败骨架上滚动续载只出陈旧行 */
  $('ftable').innerHTML='<tr class="erow"><td colspan="9">'+msg+'</td></tr>';
  const lr=$('loginRows');if(lr)lr.innerHTML='<span class="muted">'+msg+'</span>';
  const cg=$('cfgglobals');if(cg)cg.innerHTML='<span class="muted">'+msgCfg+'</span>';
  const us=$('users');if(us)us.innerHTML='<div class="ucard"><span class="muted">'+msg+'</span></div>';
  const ce=$('chartEmpty');if(ce&&ce.style.display!=='none')ce.innerHTML=msg;
}
async function load(){if(document.hidden||LOADN)return;
 /* 弹层开着整拍跳过（LASTTXT 不吞）：预览/日志弹层是半透明遮罩，
    背后全量重渲在点击/阅读间隙闪一帧且抢主线程——关弹层后下一拍
    自然补上，数据陈旧窗口≈10s 与常规轮询间隔同量级 */
 if($('pvMask').classList.contains('on'))return;LOADN=true;
 try{const r=await fetch('/api/state');const t=await r.text();
  let j=null,_pj=true;try{j=JSON.parse(t)}catch(_p){_pj=false}
  if(!_pj){/* 非 JSON 响应体（502 错误页/网关截断体）：服务应答了——
     词面归「服务异常」档（与 500 JSON 错误体同轨）。旧逻辑
     JSON.parse 抛错落外层 catch 被当网络不可达，冷启动误报
     「服务未启动」而服务实际在线（r244 P3-2）。失败体不入签名：
     恢复轮同文本也必被处理，否则「服务异常」词面驻留到下轮数据
     变化才退场 */
   LASTTXT='';
   pillState('服务异常','pill','数据通道状态：服务异常');
   if(S){$('updated').textContent='（数据刷新失败：保留上次结果）';}
   else{$('updated').textContent='';_markStale('服务异常');}}
  else if(t!==LASTTXT){LASTTXT=t;
   if(j&&j.users){S=j;
    try{render();}
    catch(e){console.error('render:',e);
     $('updated').textContent='（渲染异常：'+e.message+'）';}}
   else{/* 错误体分支：HTTP 500 的 {"err":...} 走过成功解析路径，
      服务在线——两个终点各有落点：有旧数据→保旧不 clobber（交互
      不失效，pill 落中性「服务异常」+updated 如实标注）；冷启动
      无旧数据→落错误态（词面同轨「服务异常」） */
    pillState('服务异常','pill','数据通道状态：服务异常');
    if(S){$('updated').textContent='（数据刷新失败：保留上次结果）';}
    else{$('updated').textContent='';_markStale('服务异常');}}}}
 catch(e){LASTTXT='';/* 失败体不入签名：恢复轮同文本也必被处理，
    否则「服务异常」词面驻留到下轮数据变化才退场 */
  if(S){pillState('服务异常','pill','数据通道状态：服务异常');
   $('updated').textContent='（连接失败：保留上次结果）';}
  else{pillState('服务未启动','pill','数据通道状态：服务未启动');
   $('updated').textContent='';_markStale();}}
 finally{LOADN=false;}
 /* health/pulse 自带文本签名（HL/PU 变更才重渲），脱离 state 签名门
    每拍调用——否则 state 文本不变时健康/脉冲永不刷新，失败词面驻留 */
 health();pulse();}
function pct(p,t){if(!t||!p)return 0;return Math.min(100,Math.max(2,(p/t-1)/0.5*100));}
/* pill 三态赋值单源：异常/未配置态的 title 换「数据通道状态」词面
   （常态词面「跳转达标明细」在不可跳转态是假 affordance，点击安全由
   jumpQual 空态守卫兜底，词面如实即可）；恢复常态回跳转词面 */
function pillState(txt,cls,title){const p=$('pill');p.textContent=txt;p.className=cls;p.title=title;}
function durTxt(s){if(!s)return'';const m=String(s).match(/^(\d+)h(\d+)m$/);return m?m[1]+'时'+m[2]+'分':s;}/* 时长词面展示端归一（r260 P3-3）：totalDuration 值域中文为主但渠道「25h40m」英文形态真实在场（值域实测约 5%），多渠道同屏混排；排序键后端 _dur_min 不动，CSV 导出原词保真不动 */
function diffTxt(p,t){if(!t)return'';
 const d=Math.round(p-t);
   return d<=0?`<span class="okTxt">✅ 已低于线 ￥${-d}，可出手</span>`
            :`差￥${d}（${pctTxt((p-t)*100/t)}%）`;}/* 「差￥N」与推送 KPI 单源同形。
飞猪 pad 同步律：FLIGGY_TAX_PAD>0 时 qual/推送用含税 eff 价，此处用 raw 价——KPI 卡面「税前」标注在位，口径差可读 */
/* 距线百分数词面单源：≤0.5 出「不足1」（与 Python banker 舍整
   精确同语言——JS Math.round 半点向上，恰 0.5 须显式含边界）；
   Math.round(0.21)=0 曾出「差￥4（0%）」「擦边0%」与档位词字面
   自相矛盾（推送 _near_txt 同律同轮）；词面不用「<1」——尖括号是
   钉钉 markdown 全禁字符（首例不入口） */
function pctTxt(np){return np<=0.5?'不足1':Math.round(np);}
function deltaTxt(d){if(d==null||isNaN(d))return'';
 if(d===0)return'较上轮持平';
 return d<0?`<span class="dn">较上轮 ↓￥${-d}</span>`
           :`<span class="up">较上轮 ↑￥${d}</span>`;}
function render(){const s=S;
 if(!s||!s.users){pillState('服务未启动','pill','数据通道状态：服务未启动');return;}/* 瞬时错误体不级联 */
 // 用户索引钳制：localStorage 存的 U 越尾（删用户/配置回退）时
 // s.users[U] 为 undefined → u.flights 抛错 → 页面永远停在骨架屏
 // 且单用户时切换 pills 隐藏无自救入口（实锤渲染死锁路径）
 if(!(U>=0)||U>=s.users.length)U=0;
 setNext(s.next_run);
 $('demoBar').style.display=s.demo?'':'none';
 /* 数据来源词面过 demo 分支（r236 P3-1，十六§7）：demo 为合成数据，
    「解析自 monitor.log」对演示用户失实 */
 const _hn=$('hsrcNote');if(_hn)_hn.textContent=s.demo?'演示合成数据':'解析自 monitor.log';
 /* 快捷键教学提为全局页脚：曾只活在概览 pulseLegend——
    无数据/非概览时整个界面零快捷键线索 */
 $('foot').innerHTML=((s.version&&s.version!=='demo')?'v'+s.version+' · ':'')
  +'<a href="https://github.com/dengmeiluan/ticket-monitoring" target="_blank" rel="noopener">GitHub</a> · '
  +(s.demo?'演示模式 · 合成数据':(s.svc?'本地服务 '+he(s.svc):'本地服务'))
  +'<span class="kbdtips"><span class="kbd">1</span>/<span class="kbd">2</span> 视图 <span class="kbd">3-6</span> 分栏 <span class="kbd">/</span> 搜索 <span class="kbd">R</span> 立即扫描</span>';
 $('updated').textContent=s.updated?'更新于 '+s.updated:'';
 /* 版本失配刷新横幅：PGVER 为空（极端注入失败）时静默，
    不误报；demo/烘焙站代际同为 demo 形态恒一致 */
 if(s.version&&PGVER&&s.version!==PGVER){const vb=$('verbar');
  if(vb){vb.style.display='';$('verTxt').textContent='v'+s.version;}}
 if(!s.users||!s.users.length){
  /* 空态自愈：hero 教学卡在概览 pane 内，非概览子栏停留时删光用户
     曾被埋葬成空白死区（jpmontab 持久化使刷新也不自救、navMon 点击
     switchView 不切子栏无法回位）；silent 形态防入场动画与 hash 写
     副作用，持久化槽同步落 overview——刷新自愈 */
  if(MONTAB!=='overview')showMonTab('overview',true);
  /* 空态二分：suspended 在场=全停用（呈现停用清单与启用入口，词面
     与「从未配置」严格分开——回归用户找心理线配置不被「还没有任务」
     误导）；产物是配置自由文本，渲染一律 he() 消毒 */
  const sup=(s.suspended&&s.suspended.length)?s.suspended:[];
  if(sup.length){
   pillState('已全停用','pill','数据通道状态：航线已全部停用（切「⚙️ 配置」可启用）');
   $('users').innerHTML=`<div class="ucard hero"><div class="hicon">⏸️</div>
   <h2>航线已全部停用</h2>
   <p>`+sup.map(x=>`<b>${he(x.name)}</b>（${x.n} 条）：${he(x.routesTxt).split('、').map(s=>'<span class="nw">'+s+'</span>').join('、')}`).join('<br>')+`</p>
   <p class="muted">停用保留全部配置（心理线/日期），采集与推送已暂停，启用立即恢复。</p>
   <button onclick="switchView('cfg')">前往配置启用 →</button></div>`;
  }else{
   pillState('未配置','pill','数据通道状态：未配置（切「⚙️ 配置」添加航线）');
   $('users').innerHTML=`<div class="ucard hero"><div class="hicon">✈️</div>
   <h2>还没有监控任务</h2><p>三步开始追踪机票价格：</p>
   <ol><li>切到「⚙️ 配置」添加第一条航线（城市 + 日期 + 心理价）</li>
   <li>填入钉钉机器人 Webhook，点<span class="nw">「🔔 测试推送」</span>验证通路</li>
   <li>保存即生效——达标时推送 @你，重要警报可来电</li></ol>
   <button onclick="switchView('cfg')">前往配置 →</button></div>`;
  }
  $('chartcard').style.display='none';$('tablecard').style.display='none';
  $('montabs').style.display='none';
  /* 操作卡回收（P3-2）：立即扫描对零启用航线无作用面且易误触，恢复
     启用随数据态路径回显（下方恢复点，空态↔数据态双向自愈） */
  $('opscard').style.display='none';
  /* P2-4：残留态回收——renderPulse/renderHealth 与 userPills
     亮过即保持 display:''，删光用户保存后 hero 上方挂着上一轮脉冲卡 */
  $('pulsecard').style.display='none';$('userPills').style.display='none';return;}
 $('opscard').style.display='';
 $('chartcard').style.display='';$('tablecard').style.display='';
 $('montabs').style.display='';
 const u=s.users[U];
 // 达标以每用户逐行真实判定（后端按各自航线阈值）；
 // 无旗标不标档：缺 hit 的旧数据不再回退裸价判达标（反转）
 const hit=s.users.some(x=>x.hit===true);
 pillState(hit?'有人已达标':'未达标',
           'pill'+(hit?' ok':''),'跳转达标明细（仅达标档，将重置现有筛选）');
 document.title=(hit?'🚨 达标｜':'')+'机票监控台';
 /* 多用户切换 pills：明细/走势/日历跟随所选用户（单用户隐藏不占位） */
 const up=$('userPills');
 if((s.users||[]).length>1){up.style.display='';
  chipsRefocus('userPills',()=>{
  up.innerHTML='<span class="chiplab">用户：</span>'+(s.users||[]).map((x,i)=>
   `<span class="chip${i===U?' on':''}" onclick="pickUser(${i})">${he(x.name)}</span>`).join('')
   +'<span class="muted">明细 / 走势 / 日历跟随所选用户</span>';});}
 else up.style.display='none';
 mtabUserSync();   /* 吸顶 chip 同拍（审计 P2-1）：与 userPills 同数据源同显隐 */
 maybeNotify(s);
 let h='';
 (s.users||[]).forEach((x,i)=>{
  const xd=x.best.direct,xt=x.best.transfer;
  // KPI 阈值随最优航班所属航线（xd.th）：跨航线混用 routes[0] 的线=虚报
  const td=xd?(xd.th||x.th.direct):x.th.direct;
  const tt=xt?(xt.th||x.th.transfer):x.th.transfer;
  /* 卡头圆点与 KPI 绿卡/顶部 pill 同语言：qual（全口径）真值才亮；
     无旗标不标档，旧数据缺 qual 不再回退裸价（反转）；
     补位 stale 不亮（与 KPI 卡/后端 hit 同口径，补齐——
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
    `<span class="mchip mchip-link${k===0?' best':''}" title="渠道全线报价最低（含未过约束班次，未必可出手）· 点击只看该渠道明细（将重置现有筛选与排序）" onclick="pickUser(${i});showMonTab('details');resetFlt();FLT.plats=new Set(['${m[0]}']);buildChips();buildRouteChips();buildDateChips();table();toast('已重置现有筛选，仅看 ${m[0]} 明细')"><span class="pdot ${PKEY[m[0]]||''}"></span>${m[0]} <b>￥${m[1]}</b></span>`).join('')
   :(x.minsTxt||'<span class="muted">本轮暂无报价</span>');   /* 空态不悬挂「全线最低：｜」分隔符 */
  /* 多日期航线按日期分组 KPI（用户原话「我想看 10-5 和 10-6 的」）：
     全池 min 只露一个日期；分组后每日期直飞/中转各一卡可对比。
     kpi 卡结构与单日期路径同构（label/num/bar/muted/fb 五行）。 */
  const kpiCard=(kind,brief,th,lab,delta,dk)=>{
   /* dk=日期维度：多日期航线的 count-up PREV 键若不含日期，3 个日期的
      直飞卡共用 "0d" 互相串值当动画起点（数字乱滚） */
   /* 达标绿卡与推送 🎯 同口径：用 brief.qual（价格+中转全约束）判定；
      无旗标不标档，旧数据无 qual 不再回退价格口径（反转）。
      行情最低未必能出手（非直挂/衔接不足）；
      补位 stale 行不亮绿（展示价非当轮实时价，与后端 hit/推送链同口径） */
   const hit=brief&&!brief.stale&&brief.qual===true;
   const near=!!brief&&!hit&&th&&brief.price>th&&(brief.price-th)/th<=NEAR_PCT/100;   /* 擦边带宽：与推送 kpi_tier_txt 同一词（单源口径 core.alerter）；brief 守卫在前（hit 同款，均在 !brief return 之前求值） */
   const platCn=brief?(PLATCN[brief.view_plat||brief.plat]||brief.plat||'去哪儿'):'去哪儿';/* 名随链接落点（view_plat） */
   if(!brief)return `<div class="kpi ${kind}"><div class="lab">${lab}${th?`（线 ￥${th}）`:''}</div>
    <div class="num em">—</div>
    <div class="muted">${(dk&&_exp.has(dk))?'<span class="stoptag" title="监控日期已过期：过期航班无购买意义，扫描已跳过（渠道对过期查询会滚动返回其他日期航班）——不会有下轮">已过期·停采</span>':'该日期本轮未采到航班，下轮自动补上'}</div></div>`;
   /* 整卡可点：有行情链接时整卡加 clk 类打开同目标（卡内 numlink 保留，
      点击锚点处不重复开窗）；无链接卡不可点 */
   return `<div class="kpi ${kind}${hit?' hit':''}${brief.view?' clk':''}"${brief.view?` data-href="${he(brief.view)}" tabindex="0" role="link" aria-label="打开行情页（${platCn}）" onclick="if(event.target.closest('a'))return;window.open(this.dataset.href,'_blank','noopener')" onkeydown="if(event.key==='Enter'&&event.target===this){window.open(this.dataset.href,'_blank','noopener')}"`:''}><div class="lab">${lab}${th?`（线 ￥${th}）`:''}</div>
    <div class="num">${brief?(brief.view?`<a class="numlink" data-k="${i}${kind}${dk||''}" data-v="${brief.price}" href="${he(brief.view)}" target="_blank" rel="noopener" title="去${platCn}查看该航线">￥${brief.price}</a>`:'￥'+brief.price):'-'}${brief&&brief.plat==='fliggy'?'<span class="pretax" style="cursor:help" title="飞猪列表价为不含机建燃油的裸价，出行总成本需另加此项">税前</span>':''}</div>
    <div class="bar"${brief?` title="${hit?'已达标：价格在达标线内（满条=可出手）':'条长=超出达标线幅度（最高 +50% 封顶）'}"`:''}><i class="${hit?'ok':(near?'near':'')}" style="width:${hit?100:(brief?pct(brief.price,th):0)}%"></i></div>
    <div class="muted">${brief?(brief.qual===false&&th&&brief.price<=th
      ?'<span title="价格为行情价：非直挂/衔接不足/税前，未必能按此价出手">行情破线 · 约束未满足 ⚠</span>'
      :(near?`<span title="距达标线 ${NEAR_PCT}% 带宽内，未达标">擦边${pctTxt((brief.price-th)*100/th)}% · 未达标</span>`:diffTxt(brief.price,th)))
      +(brief.stale?' · <span title="该渠道当轮无数据，展示的是近期补位价">'+brief.stale+'h前补位</span>':'')
      +(delta!=null?' · '+deltaTxt(delta):''):''}</div>
    <div class="muted fb">${brief?`${brief.route?'<span class="nw">'+he(brief.route)+'</span> · ':''}<span class="nw">${he(brief.name)}</span> <span class="nw">${he(brief.depTime)}-${he(brief.arrTime)}${brief.cross?' '+he(brief.cross):''}</span>${brief.trans?' <span class="nw">经'+he(brief.trans)+'</span>':''}${brief.stop?` <span class="stoptag">经停${he(brief.stopCity||'')}${brief.stopTimeT?` 停${he(brief.stopTimeT)}`:''}${brief.stopWin?`(${he(brief.stopWin)})`:''}</span>`:''}${brief.bag?' <span class="bagtag">直挂</span>':((brief.bagState==='recheck')?' <span class="stoptag" title="渠道标注行李需重新托运（中转不直挂）">需转运</span>':'')}`:''}</div></div>`;};
  const bbd=x.best_by_date||{};
  const bdates=bbd.dates||[];
  const _exp=new Set(x.expiredDates||[]);
  let kpis='';
  if(bdates.length>1){
   /* 多日期「较上轮」按日期拆分（delta_by_date 载荷，后端按日期精确
      匹配 routes_arr 序列）：demo/旧快照无此字段时 undefined 安全退化
      为不显示涨跌 */
   const dDl=(x.delta_by_date||{}).direct||{},dTl=(x.delta_by_date||{}).transfer||{};
   for(const d of bdates){
    const dd=(bbd.direct||{})[d],tp=(bbd.transfer||{})[d];
    const dth=dd?(dd.th||x.th.direct):x.th.direct;
    const tth=tp?(tp.th||x.th.transfer):x.th.transfer;
    kpis+=`<div class="dgroup"><div class="dlab">${dSlash(d)}${_exp.has(d)?' <span class="stoptag" title="监控日期已过期：过期航班无购买意义，扫描已跳过（渠道对过期查询会滚动返回其他日期航班，照常采集会把别的日期的价挂进过期日期）——曲线定格在最后真实数据">已过期·停采</span>':''}</div><div class="grid">`
     +kpiCard('d',dd,dth,'直飞最低',dDl[d],d)+kpiCard('t',tp,tth,'中转最低·次日'+((tp&&tp.tam)||'02:00')+'前到达',dTl[d],d)
     +`</div></div>`;}
  }else{
   /* 单日期过期航线同款徽标（多日期分支对齐）：跳采后该日期
      永无下轮，空态「下轮自动补上」与事实矛盾 */
   const _sd=bdates[0]||'';
   kpis=(_exp.has(_sd)?`<div class="dlab">${dSlash(_sd)} <span class="stoptag" title="监控日期已过期：过期航班无购买意义，扫描已跳过（渠道对过期查询会滚动返回其他日期航班，照常采集会把别的日期的价挂进过期日期）——曲线定格在最后真实数据">已过期·停采</span></div>`:'')
    +`<div class="grid">`
    +kpiCard('d',xd,td,'直飞最低',x.delta?x.delta.direct:null,_sd)
    +kpiCard('t',xt,tt,'中转最低·次日'+((xt&&xt.tam)||'02:00')+'前到达',x.delta?x.delta.transfer:null,_sd)
    +`</div>`;
  }
  /* 卡头 name/routesTxt 过 he()，与上方用户 pills 转义纪律对齐 */
  h+=`<div class="ucard"><div class="uhead">
   <span class="uname"><span class="udot${xh?' hit':''}" title="${xh?'已达标':'未达标'}"></span>${he(x.name)}</span>
   <span class="uroutes">${String(x.routesTxt||'').split('、').map(s=>'<span class="nw">'+he(s)+'</span>').join('、')}</span></div>
   ${kpis}
   <div class="muted kpisum" style="margin-top:8px">全线最低：${mHtml}<span style="white-space:nowrap"> ｜ <a href="#" onclick="pickUser(${i});showMonTab('details');return false" style="color:var(--blue);white-space:nowrap">查看明细 ▾</a> ｜ <a href="#" onclick="pickUser(${i});jumpRowTrend('');return false" style="color:var(--blue);white-space:nowrap">走势 ▾</a></span></div>
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
function pickUser(i){U=i;saveUI();render();
 /* URL 深链同步（用户维度，与 showMonTab 的 tab 维度并存：
    #details/u1 形态可分享/收藏——曾只有 tab 级，航线选择不可分享） */
 try{history.replaceState(null,'','#'+MONTAB+'/u'+i)}catch(e){}}
/* 吸顶条右端用户切换 chip（审计 P2-1）：多用户入口只驻留页顶
   opscard，深滚明细/走势后切换须长滚回顶——第二级吸顶右端给深滚
   自救位；与 userPills 同拍同步（render 同段调用），单用户隐藏不占位 */
function mtabUserSync(){const el=$('mtabUser');if(!el)return;
 const us=(S&&S.users)||[];
 if(us.length<2){el.style.display='none';return;}
 el.style.display='';
 el.textContent='👤 '+(((us[U]||{}).name||'').slice(0,6)||'用户')+' ▸';
 el.title='切换用户 · 当前：'+((us[U]||{}).name||'')+'（点击循环切换）';
 /* audit P3-3：读屏名随拍带当前用户（themeBtn「态入名」家族）——
    aria 静态「切换用户」在多用户下与视觉 chip 信息不同步 */
 el.setAttribute('aria-label','切换用户 · 当前：'+((us[U]||{}).name||''));}
function mtabUserNext(){const us=(S&&S.users)||[];
 if(us.length<2)return;pickUser((U+1)%us.length);}
/* ===== 主页子视图工作台：一屏一会话（概览/走势·日历/明细/健康）；
   display 切换零 DOM 插拔（扩展免疫）；canvas 容器切回时须重绘 ===== */
let MONTAB='overview';
/* 页面代际（服务端把 __PAGEVER__ 替换成运行版本）：load() 轮询比对
   state.version，失配亮刷新横幅——跨重启的旧标签页不再无声跑旧代码 */
const PGVER='__PAGEVER__';
function showMonTab(t,silent){
 /* 空态收敛：明细/走势/健康在 users 空时无渲染面（render 空态已藏
    三卡），键盘数字/深链切过去只会落空白 pane——前置收敛回 overview
    （S 未到的启动深链不受影响，该守卫只在数据已载且为空态时触发） */
 if(S&&S.users&&!S.users.length&&t!=='overview')t='overview';
 MONTAB=t;
 document.querySelectorAll('#montabs .mtab').forEach(x=>
  x.classList.toggle('on',x.dataset.t===t));
 tabAria();
 ['overview','trend','details','health'].forEach(k=>{
  const el=$('montab-'+k);if(el)el.style.display=(k===t)?'':'none';});
 if(!silent){const el=$('montab-'+t);
  if(el){el.classList.remove('viewin');void el.offsetWidth;el.classList.add('viewin');}}
 if(t==='trend'&&!silent)chart();
 if(t==='details'&&!silent)table();   /* render 在非明细视图跳过了重建，切回补一拍（S 未到时自身有守卫） */
 if(t==='health')document.querySelectorAll('.hcells,#montab-details .tabs,#montabs,#opscard .opsbtns').forEach(x=>x.classList.toggle('xhint',x.scrollWidth>x.clientWidth+4));   /* 首渲发生在隐藏容器 sw=0 恒误判不可滚，切回补一拍（≥1024 弹性档放得下恒 false 不误挂）；选择器含明细吸顶条（P1-W1 同判定）与操作钮行（r247 W1） */
 if(t==='details')document.querySelectorAll('#montab-details .tabs,.tw').forEach(x=>x.classList.toggle('xhint',x.scrollWidth>x.clientWidth+4));   /* 明细吸顶条同律：首渲在隐藏容器 sw=0，切回补一拍；.tw 表内横滚提示同批（审计 P2-2，滚动发生在表容器自身） */
 try{localStorage.setItem('jpmontab',t);}catch(e){}
 if(!silent){try{history.replaceState(null,'','#'+t+'/u'+U)}catch(e){}}}   /* URL 深链同步（带 /uN 用户段：pickUser 落下的用户维度不被 tab 切换覆写；silent 档不写——启动恢复唯一 silent 调用点在 restoreUI 之前，此时 U 尚未恢复，写入会污染深链用户段） */
document.querySelectorAll('#montabs .mtab').forEach(x=>{
 x.onclick=()=>showMonTab(x.dataset.t);});
/* 启动恢复：URL 深链优先于 localStorage（tab 名过白名单校验，防任意
   hash 注入 DOM）；#cfg 不属 tab 名，留给下方 switchView 初始化处理。
   #tab/uN 双段解析（tab 段跟深链）。hash 对齐只在「hash 本身无合法
   tab」（localStorage 回退档）时补写裸 tab——有合法 tab（含双段深
   链）保持原 hash：本块在 restoreUI 之前跑，U 未恢复，任何带 /uN
   的写入都会用 0 污染深链用户段（回访者静默丢人） */
try{const _h=location.hash.slice(1);
 const _us=_h.indexOf('/u'),_ht=_us>0?_h.slice(0,_us):_h;
 /* localStorage 回退段与 hash 段同律过白名单：非法 tab 名（版本升级
    改名残留/手改）直通 showMonTab 会令四 pane 全隐=空白死区，且下方
    脏值写 hash 后两槽互喂刷新也不自救 */
 const _mt=(_ht==='cfg')?'':(['overview','trend','details','health'].indexOf(_ht)>=0?_ht
  :(['overview','trend','details','health'].indexOf(localStorage.getItem('jpmontab'))>=0?localStorage.getItem('jpmontab'):''));
 if(_mt&&_mt!=='overview'){showMonTab(_mt,true);
  if(['overview','trend','details','health'].indexOf(_ht)<0)
   try{history.replaceState(null,'','#'+_mt)}catch(e){}}}catch(e){}
/* hashchange 消费：深链曾只在加载时读一次，活页
   上手动改 hash/浏览器后退不切视图——此处复用同一白名单解析（tab 名
   防任意 hash 注入 DOM），replaceState 写入的历史记录由此可后退消费。
   showMonTab/switchView 写 hash 走 replaceState 不触发本事件，无回环；
   闭包运行期引用 VIEW/MONTAB（脚本已全量求值，无 TDZ） */
window.addEventListener('hashchange',()=>{
 const _h=location.hash.slice(1);
 /* 用户段解析（#tab/uN）：活页后退/前进/手动改 hash 时跟随切换；
    越界忽略（手输错误 hash 不乱切，钳 0 是启动自愈口径非交互口径） */
 const _s=_h.indexOf('/u');
 const _un=_s>0?parseInt(_h.slice(_s+2),10):NaN;
 const _tab=_s>0?_h.slice(0,_s):_h;
 if(!isNaN(_un)&&_un!==U&&S&&S.users&&_un>=0&&_un<S.users.length)pickUser(_un);
 if(_tab==='cfg'){if(VIEW!=='cfg')switchView('cfg');return;}
 if(_tab==='mon'){if(VIEW!=='mon')switchView('mon');return;}
 if(['overview','trend','details','health'].indexOf(_tab)>=0){
  if(VIEW!=='mon')switchView('mon');
  if(MONTAB!==_tab)showMonTab(_tab);
  /* 深链段回写：switchView('mon') 内部无条件 replaceState('#mon')
     覆写入站 hash，回退到离开时同一页签场景（MONTAB 已等，不再
     走 showMonTab 补写）深链段永久丢失——带 /uN 段入站原样回写
     （'#details/u0' 分享/刷新语义恢复）；裸 tab 入站对齐 showMonTab
     写点补用户段（裸回写会把刚写的 '#trend/u2' 洗回 '#trend'）；
     replaceState 不触发本事件，无回环 */
  try{history.replaceState(null,'',(_s>0?'#'+_h:'#'+_tab+'/u'+U))}catch(e){}
  return;}
 /* 白名单外/空 hash（手输或历史导航落入）：视图保持当前，URL 清洗成
    与视图一致——曾停「URL=#bogus_tab 而视图停 cfg」不一致态，继续
    后退/前进出现 mon/details 配 #bogus_tab 的并存。replaceState 不触发本事件，无回环 */
 try{history.replaceState(null,'',VIEW==='cfg'?'#cfg':'#mon')}catch(e){}});
/* onclick-only span 的键盘可达：tabindex+role=button，Enter/Space 转发 click
   （焦点环复用既有 ：focus-visible 规则；dataset.kbd 防 innerHTML 重建后重复绑定） */
function mkact(el){if(!el||el.dataset.kbd)return;el.dataset.kbd='1';
 /* 模板自带 tabindex 的元素（健康格/脉冲柱 roving 初态 0/-1、
    dreal 隐藏件 -1）不改写——无条件赋 0 曾在内联 onkeydown 早退
    之前把 roving -1 族全打穿（族内逐格 Tab 穿越回归） */
 if(!el.hasAttribute('tabindex'))el.tabIndex=0;el.setAttribute('role','button');
 /* 模板自带内联 onkeydown 的元素（健康格 .hc/脉冲柱 .pbar/
    预览关闭 #pvClose）不再叠加监听——内联+mkact 双通道曾让一次 Enter
    连发两个相同 /api/logtail（dataset.kbd 只防重复绑定不防双通道） */
 if(el.getAttribute('onkeydown'))return;
 el.addEventListener('keydown',e=>{
  if(e.key==='Enter'||e.key===' '){e.preventDefault();el.click();}});}
function mkactAll(){document.querySelectorAll('[role="button"],span[onclick],.mtab,#tabs span[data-f],.cnav,.plitem,.dx,.tg').forEach(mkact);tabAria();}
/* 审计 P2-2：mkact 的 button 降级形态不携带选中态——.mtab 走
   aria-pressed 动态回写（挂 mkactAll 尾随渲染补拍，showMonTab 切换
   点再补一拍，与「量纲型 affordance 在可见性切换点重跑」同律）。
   #tabs/#cfgnav 混有图例/搜索等非 tab 子元素，#montabs 后来也混入
   多租户切换 chip（role=button 非 tab 子件）——ARIA tablist 须纯
   tab 子集，三处统一 button 形态（读屏按按钮播报，功能无缺；
   方向键 roving 挂容器 onkeydown 与形制无关，键盘切换不回归；
   tabIndex roving 随 tablist 形制退役，button 下全员可 Tab） */
function tabAria(){
 /* audit P3-1：面板侧回指可访问名——读屏聚焦 tabpanel 只播「tabpanel」，
    回写面板名（data-t→中文名映射，不取 .mtab textContent 防概览角标
    <i> 词面混入） */
 const PNAME={overview:'概览',trend:'走势·日历',details:'航班明细',health:'渠道健康'};
 Object.keys(PNAME).forEach(k=>{const p=$('montab-'+k);
  if(p)p.setAttribute('aria-label',PNAME[k]);});
 document.querySelectorAll('.mtab').forEach(x=>
  x.setAttribute('aria-pressed',x.classList.contains('on')?'true':'false'));
 /* 审计 P2-4：#tabs/#cfgnav 选中态只有 .on 类视觉呈现——button
    形态按 aria-pressed 播报（mkact 已赋予 role=button），切换点各补
    一拍，本函数随 mkactAll 尾随渲染兜初始态 */
 document.querySelectorAll('#tabs span[data-f]').forEach(x=>
  x.setAttribute('aria-pressed',x.classList.contains('on')?'true':'false'));
 document.querySelectorAll('#cfgnav .cnav').forEach(x=>
  x.setAttribute('aria-pressed',x.classList.contains('on')?'true':'false'));
 /* 审计 P2：#mainnav 顶栏视图切换器同律补播报（switchView 切换点
    各补一拍，此处兜初始态） */
 document.querySelectorAll('#mainnav span[id]').forEach(x=>
  x.setAttribute('aria-pressed',x.classList.contains('on')?'true':'false'));
 /* r257 P3-2：走势模式/范围 chips（折线/K线/48h/7天）同族补播报
    （setMode/setRange 切换点各补一拍，此处兜初始态） */
 document.querySelectorAll('.rngchip').forEach(x=>
  x.setAttribute('aria-pressed',x.classList.contains('on')?'true':'false'));}
 /* 选择器说明：[role="button"] 覆盖配置折叠头（grouplab/uhead2/rhead/chhead，
    模板已写 role 但缺 tabindex）；.plitem/.dx/.tg 为 div/i/span 标签补
    tabindex+回车转发；KPI 卡是整卡 div 不在此列——卡内数字本身是
    <a class="numlink"> 天然可 Tab，不双绑 */
/* ===== 明细表：筛选 + 排序 ===== */
/* 日期 chips：多日期航线（日期片）的明细必须按日分看、不得混排——
   与 routechips 同一套多选模式（空选=全部）；单日期隐藏 */
function buildDateChips(){if(!S||!S.users.length)return;const u=S.users[U];
 const ds=[...new Set(u.flights.map(f=>f.date).filter(Boolean))].sort();
 const box=$('datechips');
 if(ds.length<2){box.innerHTML='';FLT.dates=new Set();return;}   /* 单日期清残留：跨用户切换时旧 dates 会让明细过滤全灭（L1692 消费点） */
 const keep=[...FLT.dates].filter(d=>ds.includes(d));
 FLT.dates=new Set(keep.length?keep:new Set());   /* 初始空集=全部：全亮默认稀释选中语义，plats 同律 */
 chipsRefocus('datechips',()=>{
 box.innerHTML='<span class="chiplab">日期：</span>'+ds.map(d=>
  `<span class="chip${FLT.dates.has(d)?' on':''}" onclick="togDate(this,'${d}')">${dSlash(d)}</span>`).join('')
  /* ≤760 日期列隐藏后表头排序入口随之消失——行尾补
     「⇅日期」排序 chip 与表头 sortCol 单源（SORT/aria-sort/箭头
     同一状态机）；箭头走 data-dir 属性驱动 CSS content，点击路径
     零 childList 变更（扩展 MutationObserver 免疫预置律） */
  +`<span class="chip srtchip" role="button" tabindex="0" aria-pressed="${srtChipState()[0]}" aria-label="${srtChipState()[1]}" data-dir="${srtChipState()[2]}" title="按出发日期排序：点一次升序、再点降序（与桌面表头同一状态机；恢复价格排序点「价格」表头）" onclick="dateSortChip(this)" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();dateSortChip(this)}">⇅日期<i class="arr" aria-hidden="true"></i></span>`;});}
/* 「⇅日期」排序 chip 态三件套单源（r247 W2）：aria-pressed/词面/
   箭头档全部与 SORT 状态机同源——渲染（上串内联）与同步（下函数）
   共用，防多路径手抄词面漂移 */
function srtChipState(){const on=SORT.k==='date';
 return [on?'true':'false',
         '按出发日期排序'+(on?(SORT.dir>0?'（当前升序）':'（当前降序）'):'（未启用）'),
         on?(SORT.dir>0?'asc':'desc'):''];}
/* chip 不随 table() 重建：SORT 变化的全部路径尾补一拍就地同步
   （r247 W2：点表头排序/重置筛选后 chip 曾滞留旧态至下轮渲染） */
function srtChipSync(){const el=document.querySelector('.srtchip');if(!el)return;
 const s=srtChipState(),on=SORT.k==='date';
 el.classList.toggle('on',on);
 el.dataset.dir=s[2];
 el.setAttribute('aria-pressed',s[0]);
 el.setAttribute('aria-label',s[1]);}
function dateSortChip(el){sortCol('date');srtChipSync();}
function togDate(el,d){if(FLT.dates.has(d))FLT.dates.delete(d);else FLT.dates.add(d);
 el.classList.toggle('on');saveUI();table();}
function buildRouteChips(){if(!S||!S.users.length)return;const u=S.users[U];
 const rs=[...new Set(u.flights.map(f=>f.route).filter(Boolean))].sort();
 const box=$('routechips');
 if(rs.length<2){box.innerHTML='';FLT.routes=new Set();return;}   // 单航线无角标数据，隐藏并清残留（同 buildDateChips P2-B：跨用户切换旧 routes 会让明细过滤全灭）
 const keep=[...FLT.routes].filter(p=>rs.includes(p));
 FLT.routes=new Set(keep.length?keep:new Set());   /* 初始空集=全部：全亮默认稀释选中语义，plats 同律 */
 chipsRefocus('routechips',()=>{
 box.innerHTML='<span class="chiplab">航线：</span>'+rs.map(p=>
  `<span class="chip${FLT.routes.has(p)?' on':''}" data-r="${he(p)}" onclick="togRoute(this)">${he(p)}</span>`).join('');});}
function togRoute(el){const p=el.dataset.r;if(FLT.routes.has(p))FLT.routes.delete(p);else FLT.routes.add(p);
 el.classList.toggle('on');saveUI();table();}
function buildChips(){if(!S||!S.users.length)return;const u=S.users[U];
 const age=u.platAge||{};
 const ps=[...new Set(u.flights.map(f=>f.plat).concat(Object.keys(age)))].sort();
 const keep=[...FLT.plats].filter(p=>ps.includes(p));
 /* 仅未初始化才回填全选——用户逐一取消到最后一片（空集=全部，
    筛选语义）曾被下次 10s 轮询 buildChips 判「未初始化」回填成全亮 */
 if(keep.length||FLT._platsInit){FLT.plats=new Set(keep);FLT._platsInit=true;}
 else{FLT.plats=new Set();FLT._platsInit=true;}   /* 初始空集=全部（过滤消费点空集语义在案）：全亮默认稀释选中语义 */
 const badge=p=>{const a=age[p];
  if(a==null)return'<i class="bd non">无数据</i>';
  if(a<0.5)return'';   /* 数据新鲜是常态，全员「新」无信息量（用户反馈移除） */
  const h=Math.max(1,Math.round(a));
  return a<6?`<i class="bd mid">${h}h前</i>`:`<i class="bd old">${h}h前</i>`;};
 const PK={'去哪儿':'qunar','飞猪':'fliggy','同程':'tongcheng','途牛':'tuniu','携程':'ctrip'};
 chipsRefocus('platchips',()=>{
 $('platchips').innerHTML='<span class="chiplab">渠道：</span>'+ps.map(p=>{
  const b=badge(p);
  return `<span class="chip${FLT.plats.has(p)?' on':''}" onclick="togChip(this,'${p}')"><span class="pdot ${PK[p]||''}"></span>${p}${b?' '+b:''}</span>`;}).join('');});}
function togChip(el,p){if(FLT.plats.has(p))FLT.plats.delete(p);else FLT.plats.add(p);
 el.classList.toggle('on');saveUI();table();}
/* ===== 筛选/排序状态持久化（刷新不丢） ===== */
function saveUI(){try{localStorage.setItem('jpui',JSON.stringify(
 {F:F,U:U,sk:SORT.k,sd:SORT.dir,plats:[...FLT.plats],routes:[...FLT.routes],dates:[...FLT.dates],dep:FLT.dep,arr:FLT.arr,no:FLT.no,q:FLT.q,chr:CHR,exp:EXP,tg:TGOPEN}));}catch(e){}}
function restoreUI(){try{const j=JSON.parse(localStorage.getItem('jpui')||'{}');
 if(j.F)F=j.F;if(j.sk)SORT={k:j.sk,dir:j.sd||1};
 if(Array.isArray(j.plats)&&j.plats.length){FLT.plats=new Set(j.plats);FLT._platsInit=true;}
 if(Array.isArray(j.dates)&&j.dates.length)FLT.dates=new Set(j.dates);
 if(Array.isArray(j.dep)&&j.dep.length===2)FLT.dep=j.dep;
 if(Array.isArray(j.arr)&&j.arr.length===2)FLT.arr=j.arr;
 if(Array.isArray(j.routes))FLT.routes=new Set(j.routes);
 if(j.chr)CHR=j.chr;
 /* 行展开态持久化：刷新/次日回访不再全部收起
    ——展开内容由 table() 现渲随数据同源刷新，无陈旧读面；字符串
    类型守卫防旧存档脏值进键比较 */
 if(typeof j.exp==='string')EXP=j.exp;
 if(typeof j.tg==='string')TGOPEN=j.tg;
 if(j.no){FLT.no=true;$('fnostale').checked=true;}
 if(j.q){FLT.q=j.q;const el=$('fq');if(el)el.value=j.q;}
 U=Math.min(j.U||0,99);
 document.querySelectorAll('#tabs span').forEach(s=>
  s.classList.toggle('on',s.dataset.f===F));}catch(e){}}
function hm(t){const m=(t||'').match(/^(\d{1,2}):(\d{2})/);return m?(+m[1])*60+(+m[2]):null;}
/* 出发/到达时段挡位 chips：原生 time 输入整套替换为与配置页
   同语言的挡位单选——再次点选中挡=取消回「全部」；FLT.dep/arr 存 [起,终]
   分钟对（null=不限），table() 过滤与旧 t1/t2 语义一致 */
const WINS=[['全部',''],['凌晨','00:00|06:00'],['上午','06:00|12:00'],
            ['下午','12:00|18:00'],['晚间','18:00|23:59']];
function buildWinSel(){
 for(const [key,id] of [['dep','wdep'],['arr','warr']]){
  const cur=FLT[key];
  const box=$(id);
  const want=WINS.map(([,w])=>w);
  const have=[...box.querySelectorAll('.schip')].map(c=>c.dataset.w);
  /* WINS 恒定，子节点齐时原位翻 on 类不重建——table() 每拍
     整组 innerHTML 重建曾把刚点按/回车的 .schip 连节点换掉，键盘焦点
     每切一挡丢回 body */
  if(have.length!==want.length||want.some((w,i)=>have[i]!==w)){
   box.innerHTML=WINS.map(([n,w])=>{
    const on=(cur?(cur[0]+'|'+cur[1]):'')===w;
    return `<span class="chip schip${on?' on':''}" data-w="${w}" onclick="togWin(this,'${key}')">${n}</span>`;}).join('');
   continue;}
  const cw=cur?(cur[0]+'|'+cur[1]):'';
  box.querySelectorAll('.schip').forEach(c=>c.classList.toggle('on',c.dataset.w===cw));
 }}
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
/* 文本筛选实时防抖：价格/搜索框曾只 onchange（失焦/回车才
   过滤），边打字边出结果更直观；250ms 防抖避免每键全表重建 */
let _fltT=0;
function applyFltD(){clearTimeout(_fltT);_fltT=setTimeout(applyFlt,250);}
/* 配置搜索防抖（r235 P2-8，applyFltD 同款）：cfgFilter 每键全 DOM
   重排+computed style 强制 layout，多用户配置打字卡顿；重建重放
   路径（buildForm 后 cfgFilter 直调）不经此，即时性不受扰 */
let _cfgT=0;
function cfgFilterD(){clearTimeout(_cfgT);_cfgT=setTimeout(()=>cfgFilter(CFGQ),250);}
function applyWins(){/* 由挡位 chips 状态推导分钟窗（无独立输入框可读） */
 for(const key of ['dep','arr']){
  const on=$(('w'+key)).querySelector('.schip.on');
  FLT[key]=on&&on.dataset.w?on.dataset.w.split('|'):null;}}
/* 类别挡回「全部」并同步 tabs 高亮（resetFlt/mchip 联动共用） */
function setCatAll(){F='all';
 document.querySelectorAll('#tabs span').forEach(s=>
  s.classList.toggle('on',s.dataset.f===F));}
/* 显式重置入口（筛选区按钮）：排序曾非默认时补告知——跳转类
   调用方（jumpCalDate/jumpQual/mchip）自带 toast，经 resetFlt
   直调不重复播报 */
function resetFltUI(){const had=SORT.k!=='price'||SORT.dir!==1;
 resetFlt();if(had)toast('已恢复默认排序');}
function resetFlt(){if(SORT.k!=='price'||SORT.dir!==1){SORT={k:'price',dir:1};}
 /* 排序曾驻留：唯一复位路径=再点「价格」表头（不可发现）——重置筛选
    时附带恢复默认排序；告知只在显式重置入口 resetFltUI（跳转类调用
    方自带 toast，双条堆叠=冗余播报） */
 FLT.routes=new Set();FLT.dates=new Set();FLT.dep=null;FLT.arr=null;
 /* 重置=回到「空集=全部」语义（buildChips 对空集不回填选中片，
    过滤守卫 size&&!has 恒放行全部），选中片不亮 */
 FLT.plats=new Set();FLT._platsInit=false;FLT.pmin=0;FLT.pmax=0;FLT.no=false;FLT.q='';setCatAll();
 buildWinSel();
 $('fpmin').value='';$('fpmax').value='';$('fnostale').checked=false;$('fq').value='';
 saveUI();buildChips();table();srtChipSync();}
const HEADS=[['price','价格'],['cat','类别'],['date','日期'],['name','航班'],['dep','出发'],
 ['arr','到达'],['dur','时长'],['trans','中转'],['plat','渠道']];
function tmin(t){const m=(t||'').match(/(\d{1,2}):(\d{2})/);return m?(+m[1])*60+(+m[2]):null;}
function sval(f,k){switch(k){case 'price':return f.price;case 'cat':return f.transfer?1:0;
 case 'date':return f.date||'';
 case 'name':return f.name;case 'dep':return tmin(f.depTime)??99999;
 case 'arr':return tmin(f.arrTime)??99999;case 'dur':return f.durM||99999;
 case 'trans':return f.trans||'';case 'plat':return f.plat;default:return 0;}}
function sortCol(k){if(SORT.k===k)SORT.dir*=-1;else SORT={k:k,dir:1};saveUI();table();srtChipSync();}
/* ===== 同班跨渠道比价：点击行展开（指纹含日期/经停——多日期航线同班次、
   直挂与经停报价不混串；经停对应后端 out 的 stop=bool(stopover)） ===== */
let EXP=null;
/* 指纹构造点去引号/尖括号——trans/cross 是渠道自由文本，裸插
   data-k 属性与 togRow('${k}') JS 串可被断串；he() 在单引号 JS 上下文
   会因实体解码还原引号反而无效，故在源头统一清洗（fp(x)===k 两侧同源，
   比较一致性不受影响） */
const fp=f=>((f.date||'')+'|'+f.depTime+'|'+f.arrTime+'|'+f.trans+'|'+f.cross+'|'+(f.stop?1:0)).replace(/["'<>&]/g,'_');
/* 展开行渲染期预置为隐藏行，点击只切 display——表格零 childList 变更。
   （禁用"插/删一个 tr"的外科手术方案：翻译/比价类扩展监听 DOM 插入会
   全页重扫，用户实测每点一行卡数秒；隐藏行只是 attribute 变更，不触发） */
function xrowHtml(u,k,open,grp){
 /* grp=纯 fp 分组键（比价聚合用）；k=行实例键（展开态）。两者必须
    分传——grp 缺省回退 k 会让比价组退化为单行（链静默丢失），故
    不设兜底 */
 const same=u.flights.filter(x=>fp(x)===grp)
  .sort((a,b)=>a.price-b.price);
 const save=same.length>1?same[same.length-1].price-same[0].price:0;
 /* 离群警示（口径单源后端下发=钉钉/推送图同一 Alerter._outlier：最高>2×最低
    或跨舱位大类，收口——前端本地曾只判 2×，跨舱位 ≤2× 时此处显示
    「可省」而推送显示「差」）：「可省」是假优惠——如实改「差」并标 ⚠️+最高价舱位 */
 const outlier=same.length>1&&!!same[same.length-1].outlier;
 const hiCn=(he((same[same.length-1].cabinT||'')).split(' · ')[0]);
 const chain=same.map(x=>`${he(x.plat)}${x.stale?'·'+x.stale+'h前':''} `
  +(x.view?`<a class="vw" href="${he(x.view)}" target="_blank" rel="noopener" title="去${he(x.plat||'去哪儿')}查看该航线">￥${x.price} ↗</a>`
  :'￥'+x.price)).join(' ＜ ');
 /* 结论句前置：colspan td 宽=全表宽，white-space:normal 只在链长超全表
    宽时才折行——短链单行放得下，链尾结论句曾仍藏视口外须横滚；前置后
    恒贴链头（xrow 已退出首列吸附，链头=滚动零位），移动端首屏即见 */
 return `<tr class="xrow"${open?'':' style="display:none"'}><td colspan="9">⚖️ 同班比价`+
    (save?(outlier?`<span style="white-space:nowrap">（差 ￥${save} · ${hiCn?hiCn+' · ':''}渠道报价口径差异 ⚠️）</span>`
                  :`<span style="white-space:nowrap">（可省 ￥${save}）</span>`)
         :'<span style="white-space:nowrap">（仅一渠道报价）</span>')+`：${chain}</td></tr>`;}
function _hideXrows(){document.querySelectorAll('#ftable tr.xrow').forEach(
 x=>{x.style.display='none';});}
/* 展开切换：目标行的紧邻隐藏行 display 翻转，无任何节点插拔/全表重建 */
function _ariaOff(){const p=document.querySelector('#ftable tr[aria-expanded="true"]');
 if(p)p.setAttribute('aria-expanded','false');
 /* r257 P3-3：改期胶囊互斥收口同源（开比价收改期/开改期收比价的
    另一侧，.tg 状态随行收合一并复位） */
 const g=document.querySelector('.tg[aria-expanded="true"]');
 if(g)g.setAttribute('aria-expanded','false');}
function togRow(k,row){
 const nx=row&&row.nextElementSibling;
 /* 改期窗口行（tgrow）夹在数据行与比价行之间：跳过它找真 xrow */
 const cur=nx&&nx.classList.contains('tgrow')?nx.nextElementSibling:nx;
 if(EXP===k){EXP=null;if(cur)cur.style.display='none';_ariaOff();saveUI();return;}
 if(TGOPEN)TGOPEN=null;   /* 互斥：开比价先收改期（tgrow 兼 xrow 类，下行同收） */
 _ariaOff();
 EXP=k;
 saveUI();   /* 展开态持久化（restoreUI 回填，刷新/次日回访不丢；收支路对称落盘——收起不落盘则刷新复开） */
 _hideXrows();
 if(cur){cur.style.display='';row.setAttribute('aria-expanded','true');}
 else table();}
/* ===== 改期窗口（trendGo 跨渠道协议：qunar goFTrend / tongcheng pc[]
   15 点=±7 天、fliggy 日历条 7 格=±3 天，窗口与点数随渠道；仅挂当轮
   最低价行）：[[MM-DD,价],…] 语义=「换个日子飞多少钱」非「现在买 vs
   再等等」。胶囊挂摘要，点击展开点集柱状微图；与同班比价 xrow 互斥
   （tgrow 兼 xrow 类，_hideXrows 同收两族） ===== */
let TGOPEN=null;
function tgCap(f,k){
 const tg=(f.trendGo||[]).filter(p=>p&&p[1]>0);
 if(!tg.length)return '';
 const lo=tg.reduce((a,b)=>b[1]<a[1]?b:a);
 const pct=Math.round((f.price-lo[1])/f.price*100);
 const dn=lo[0]===(f.date||'').slice(5)?'当前日期即最低'
  :(pct>0?'<span class="dn">↓'+pct+'%</span>'
   :(pct===0?'暂无更低':'改期更贵'));/* 钳制防负 ↓%；持平≠更贵（边界） */
 return `<span class="tg" role="button" tabindex="0" aria-expanded="${TGOPEN===k?'true':'false'}" onclick="event.stopPropagation();togGo('${k}',this)" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();event.stopPropagation();togGo('${k}',this)}" title="改期窗口：邻近出发日期同航线每日最低价（换个日子飞多少钱；共${tg.length}个日期点，窗口随渠道）">改期 最低￥${lo[1]} ${he(dSlash(lo[0]))} ${dn}</span>`;}
/* 点集微图：高度归一 (v-min)/(max-min) → 12%~100%（全同值统一 60%）；
   档类 lo=全窗最低（绿实心）/cheap=比行价便宜（浅绿）/cur=等于行
   depDate（蓝描边 inset），lo 压 cheap，cur 描边可叠加 */
function tgrowHtml(f,k,open){
 const tg=(f.trendGo||[]).filter(p=>p&&p[1]>0);
 if(!tg.length)return '';
 const lo=tg.reduce((a,b)=>b[1]<a[1]?b:a);
 let mn=tg[0][1],mx=tg[0][1];
 for(const p of tg){if(p[1]<mn)mn=p[1];if(p[1]>mx)mx=p[1];}
 const cur=(f.date||'').slice(5);
 /* 节假日标注（tongcheng trendHoliday 同点协议）：按日期配对进柱
    title——「哪天便宜为什么便宜」的解释变量（节假日/会员日） */
 const hol={};(f.trendHoliday||[]).forEach(p=>{if(p&&p[0])hol[p[0]]=p[1];});
 /* 高档舱同点注（tongcheng trendBiz 同点协议）：柱 title 附「公务￥X」
    ——「改期那天想飞公务多少钱」参考变量，与经济舱主轴同 title 分层 */
 const biz={};(f.trendBiz||[]).forEach(p=>{if(p&&p[0])biz[p[0]]=p[1];});
 const bars=tg.map(p=>{
  const h=mx>mn?12+Math.round((p[1]-mn)/(mx-mn)*88):60;
  const cls='tgb'+(p===lo?' lo':(p[1]<f.price?' cheap':''))+(p[0]===cur?' cur':'');
  return `<i class="${cls}" style="height:${h}%" title="${he(dSlash(p[0]))} ￥${p[1]}${biz[p[0]]?' · 公务￥'+biz[p[0]]:''}${hol[p[0]]?' · '+he(hol[p[0]]):''}"></i>`;}).join('');
 return `<tr class="xrow tgrow"${open?'':' style="display:none"'}><td colspan="9">`+
  `<span class="tgbox"><span class="tgwrap">${bars}</span>`+
  `<span class="tgaxis"><span>${he(dSlash(tg[0][0]))}</span><span>${he(dSlash(cur))}(出发)</span><span>${he(dSlash(tg[tg.length-1][0]))}</span></span>`+
  `<span class="tgleg">绿=窗口最低 · 浅绿=比当前票价便宜 · 蓝框=出发日（颜色与达标线无关）</span></span></td></tr>`;}
/* 展开切换：tgrow 渲染在数据行与 xrow 之间（nextElementSibling 语义）；
   开改期先收比价（EXP=null+_hideXrows，tgrow 兼 xrow 类一并收） */
function togGo(k,el){
 const row=el&&el.closest?el.closest('tr'):null;
 let tg=row&&row.nextElementSibling;
 if(tg&&!tg.classList.contains('tgrow'))tg=null;
 if(TGOPEN===k){TGOPEN=null;if(tg)tg.style.display='none';el.setAttribute('aria-expanded','false');saveUI();return;}
 TGOPEN=k;_ariaOff();EXP=null;
 saveUI();   /* 展开态持久化（与 togRow 同律） */
 _hideXrows();
 if(tg){tg.style.display='';el.setAttribute('aria-expanded','true');}
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
   const hay=(f.name+' '+(f.code||'')+' '+(f.trans||'')+' '+f.plat+' '+(f.depAirportCode||'')+' '+(f.arrAirportCode||'')+' '+(f.airlineCode||'')).toLowerCase();
   if(!hay.includes(q))return false;}
  return true;});
 rows.sort((a,b)=>{const x=sval(a,SORT.k),y=sval(b,SORT.k);
  return (x<y?-1:x>y?1:0)*SORT.dir;});
 return rows;}
function _rc_txt(f){if(f.returnFee==null&&f.changeFee==null)return'';
 const one=(v,lbl)=>v==null?'':(v===-1?'不可'+lbl:(lbl+'￥'+v));
 if(f.returnFee===0&&f.changeFee===0)return'免费退改';
 return[one(f.returnFee,'退'),one(f.changeFee,'改')].filter(Boolean).join('·');}
function _ad_txt(v){if(v==null||!v)return'';
 return v<0?'早到'+(-v)+'分':'延'+v+'分';}
function _nb_txt(f){/* 周边城市特价词面单源（title 与 CSV 同一产出，
   he() 由调用点按出口施加）：[日期,码,名,价,折扣,km,锚] 元组按
   在场段拼接，空段跳过；无有效行返回空串。
   备案（r268 Soldier 观察-4）：a[0] 日期/a[1] 目的码采集不渲染——
   日期=行自身日期上下文恒同日（模块 data-depdate=查询日期）冗余；
   码=中文名已辨识零增量；若渠道未来出现跨日期推荐形态再启用 */
 const nb=(f.nearby||[]).filter(a=>a&&a[2]&&a[3]>0);
 if(!nb.length)return'';
 return'周边特价：'+nb.map(a=>a[2]+'￥'+a[3]
  +(a[4]?'·'+a[4]:'')
  +((a[6]&&a[5]>0)?'·距'+a[6]+a[5]+'km':'')).join('｜');}
function _rt_txt(f){/* 往返程推荐词面单源（title 与 CSV 同一产出，
   he() 由调用点按出口施加）：[去日期,返日期,价,去码,返码] 元组按
   在场段拼接；无有效行返回空串。
   备案：a[3]/a[4] 城市码采集不渲染（往返模块城市对=行自身航线对
   上下文冗余；渠道未来出现跨航线推荐形态再启用） */
 const rt=(f.trendRound||[]).filter(a=>a&&a[0]&&a[1]&&a[2]>0);
 if(!rt.length)return'';
 return'往返推荐：'+rt.map(a=>'去'+a[0].slice(5)+'返'+a[1].slice(5)
  +'￥'+a[2]).join('｜');}
function _roving(e,box){/* 同族相邻件 ←/→ 移动焦点族尾回绕：
   脉冲柱/健康格曾全量 tabindex=0，400+ 拍逐格 Tab 穿越负担 */
 if(e.key!=='ArrowRight'&&e.key!=='ArrowLeft')return;
 const els=Array.prototype.slice.call((box||e.target.parentElement).querySelectorAll('[data-rv]'));
 const i=els.indexOf(e.target);if(i<0)return;e.preventDefault();
 els[(i+(e.key==='ArrowRight'?1:els.length-1))%els.length].focus();}
function _rovingV(e,box){/* ↑↓ 网格形制族移动（541-760 档 montabs
   折两行，←/→ 到行尾不换行）：按几何行分组+列左缘最近邻对位，
   单行/首行↑/末行↓ 自然 no-op，不改变单行族（脉冲柱等）行为面 */
 if(e.key!=='ArrowDown'&&e.key!=='ArrowUp')return;
 const els=Array.prototype.slice.call(box.querySelectorAll('[data-rv]'));
 const i=els.indexOf(e.target);if(i<0)return;e.preventDefault();
 const self=e.target.getBoundingClientRect();
 const rows=[];els.forEach(el=>{const t=el.getBoundingClientRect().top;
  let row=rows.find(r=>Math.abs(r.top-t)<4);
  if(!row){row={top:t,els:[]};rows.push(row);}row.els.push(el);});
 rows.sort((a,b)=>a.top-b.top);
 const ri=rows.findIndex(r=>Math.abs(r.top-self.top)<4);
 const ni=ri+(e.key==='ArrowDown'?1:-1);
 if(ri<0||ni<0||ni>=rows.length)return;
 let best=null,bd=1e9;rows[ni].els.forEach(el=>{
  const d=Math.abs(el.getBoundingClientRect().left-self.left);
  if(d<bd){bd=d;best=el;}});
 if(best)best.focus();}
function _rowRoving(e,el){/* 明细行 ↑/↓ 族内移动（审计 P2-6：
   行 tabindex 改首行 0 余 -1 后，数百行 Tab 穿越改方向键族移动；
   隐藏 xrow/tgrow 无 data-k 天然排除，切片未渲染侧到底即停，
   深跳转由 End 显式补全路径承担） */
 const els=Array.prototype.slice.call(
  el.closest('tbody').querySelectorAll('tr[data-k]'));
 const i=els.indexOf(el);if(i<0)return;
 const j=e.key==='ArrowDown'?i+1:i-1;
 if(j>=0&&j<els.length)els[j].focus();}
function heFriendly(e){/* 服务端 500 的原始异常串不直出中文界面：
   截断 + 指路服务日志（有更友好映射的场景由调用点自行给词） */
 e=String(e==null?'':e).trim();if(!e)return'';
 return e.length>80?Array.from(e).slice(0,80).join('')+'…（详见服务日志）':e;}
function expCsv(){if(!S||!S.users.length){toast('数据加载中，请稍候再导出');return;}
 const rows=filteredRows();
 if(!rows.length){toast('当前筛选无数据，先调整筛选条件');return;}
 const e2=v=>'"'+String(v==null?'':v).replace(/"/g,'""')+'"';
 const head=['价格','类别','日期','航班','航班号','出发','到达','机场/航站楼','跨天','时长','均延','准点率','取消率','中转','衔接','直挂','托运额','手提额','经停','舱位','舱位码','座椅倾斜','机型体量','廊桥率','机建燃油','高档舱','退改','廉航','权益标签','标签说明','中转服务','航司中转','渠道','数据时效','状态','孤低价','改期最低','改期公务','儿童/婴儿','航程','航司码','公布运价','实际承运','周边特价','往返推荐'];
 const lines=[head.map(e2).join(',')];
 for(const f of rows)lines.push([
  f.price,f.transfer?'中转':'直飞',f.date||'',f.name,f.code||'',f.depTime,f.arrTime,
  ((_ttc(f.depAirport,f.depTerminal,f.depAirportCode))&&(_ttc(f.arrAirport,f.arrTerminal,f.arrAirportCode))&&_ttc(f.arrAirport,f.arrTerminal,f.arrAirportCode)!==_ttc(f.depAirport,f.depTerminal,f.depAirportCode))?(_ttc(f.depAirport,f.depTerminal,f.depAirportCode)+'→'+_ttc(f.arrAirport,f.arrTerminal,f.arrAirportCode)):(_ttc(f.arrAirport,f.arrTerminal,f.arrAirportCode)||_ttc(f.depAirport,f.depTerminal,f.depAirportCode)||''),
  f.cross||'',f.dur||'',_ad_txt(f.avgDelay),(f.prate?f.prate+'%':''),(f.cancelRate!=null?f.cancelRate+'%':''),f.trans||'',
  (f.layoverT||'')+(f.layMin?(f.layoverM>=f.layMin?'✓':(f.layoverM?'⚠':'')):''),
  (f.bagState==='direct'?'是':(f.bagState==='recheck'?'需转运':'')),f.baggage||'',f.carryon||'',f.stop?('是'+(f.stopWin?'('+f.stopWin+')':'')):'',(f.cabinT||'').replace(/<[^>]*>/g,''),f.cabinCode||'',(f.seatTilt!=null?f.seatTilt+'°':''),f.planeSize||'',(f.bridgeRate!=null?f.bridgeRate+'%':''),(f.transferTax!=null?f.transferTax:''),(f.bizPrice!=null?((f.price!=null&&f.bizPrice>f.price)?'+￥'+(f.bizPrice-f.price):(f.bizCabin||'公务')+'￥'+f.bizPrice):''),_rc_txt(f),(f.lcc?'是':''),f.labels||'',f.labelNote||'',f.transferService||'',f.airlineTransfer||'',f.plat,
  f.stale?('补位·'+f.stale+'h前'):'实时',
  f.qual?'真达标':(f.brk?'行情破线':(f.near?'擦边':'')),
  f.xphan?'是':'',
  (()=>{const tg=(f.trendGo||[]).filter(p=>p&&p[1]>0);return tg.length?Math.min(...tg.map(p=>p[1])):'';})(),
  (()=>{const tb=(f.trendBiz||[]).filter(p=>p&&p[1]>0);return tb.length?Math.min(...tb.map(p=>p[1])):'';})(),
  (f.childPrice!=null?f.childPrice:'')+(f.childPrice!=null&&f.infantPrice!=null?'/':'')+(f.infantPrice!=null?f.infantPrice:''),
  (f.distance!=null?f.distance:''),(f.airlineCode||''),(f.stdFare!=null?f.stdFare:''),(f.shareCarrier?(f.shareAirline?f.shareAirline+f.shareCarrier:f.shareCarrier):(f.shareAirline||'')),_nb_txt(f),_rt_txt(f)].map(e2).join(','));
 const blob=new Blob([String.fromCharCode(65279)+lines.join(String.fromCharCode(13,10))],{type:'text/csv;charset=utf-8'});
 const a=document.createElement('a');
 a.href=URL.createObjectURL(blob);
 const _p=n=>String(n).padStart(2,'0');const _d=new Date();
 a.download='flights_'+_d.getFullYear()+_p(_d.getMonth()+1)+_p(_d.getDate())+'_'+_p(_d.getHours())+_p(_d.getMinutes())+'.csv';
 a.click();URL.revokeObjectURL(a.href);
 /* 导出成功反馈（exportCfg/importCfg 同律：静默成功=「点了没反应」） */
 toast('📤 已导出 '+rows.length+' 行 CSV','ok');}
/* ===== 明细表切片渲染：首拍只渲首屏切片，滚动近底按需续载 =====
   全量 innerHTML 重建实测 549 班 ~214ms（布局 122ms+解析 40ms+拼串
   ~50ms）——排序/筛选/chip/每拍刷新的每次点击都是 200ms 长任务
   （「点击卡顿」根因）。切片后交互路径只建 ~120 行；旧「已显示前
   300 班」截断提示退役（滚动即达全量，CSV 导出本就全量不受影响） */
let _ROWS=null,_CHUNKS=[],_NDRAW=0;
const _CHUNK=120;
function _chunkHtml(ci){if(_CHUNKS[ci]!=null)return _CHUNKS[ci];
 const u=S.users[U];
 const from=ci*_CHUNK,to=Math.min(from+_CHUNK,_ROWS.length);let h='';
 for(let i=from;i<to;i++){const f=_ROWS[i];const noanim=ci>0?';animation:none':'';
  /* 行实例键=分组键+渠道：同物理班跨渠道两行（同 fp）各有胶囊/
     比价行，展开态（TGOPEN/EXP）必须按行实例存取——按分组键存取
     会让同组第二颗胶囊首点走进 close 分支永开不成。比价聚合仍用
     纯 fp（xrowHtml grp 参），分组键本身勿加维度（打断跨渠道配对） */
  const k=fp(f)+'|'+(f.plat||'');
  /* 斑马纹按数据行序号显式加类：行间夹着隐藏 xrow，nth-child(even)
     永远落在 xrow 上被 ：not(.xrow) 排除——斑马纹从未生效过。
     达标行不加斑马：#ftable tr.zebra 带 ID 特异性恒压
     tr.qual，「仅达标」筛选下绿色语义曾呈奇灰偶绿条纹抖动 */
  const zb=i%2===1;
  const zebra=(!f.qual&&zb)?' zebra':'';
  h+=`<tr class="${f.qual?'qual':''}${zebra}" style="cursor:pointer;--i:${Math.min(i,7)}${noanim}" data-k="${k}" tabindex="${i===0?0:-1}" aria-expanded="${EXP===k?'true':'false'}" title="${he(f.date||'')} ${he(f.code||'')}｜点击或回车展开同班各渠道比价" onclick="togRow('${k}',this)" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();togRow('${k}',this)}else if(event.key==='End'){event.preventDefault();_jumpTableBottom()}else if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();_rowRoving(event,this)}">`+
  `<td class="price${f.brk?' brk':(f.near?' near':'')}"${f.brk?' title="行情破线未达标：因非直挂/衔接不足/税前等原因暂不可出手"':(f.near?` title="擦边：距达标线 ≤${NEAR_PCT}%，未达标"`:'')}>${'<span class="fire">'+(f.qual?'🔥':'')+'</span>'}￥${f.price}${f.xphan?' <span class="stl" style="color:var(--warn);cursor:help" title="跨渠道孤低价：显著低于其他渠道同航班报价，疑似页面污染/错误价——不参与达标判定与行情最优">⚠</span>':''}${f.platKey==='fliggy'?'<span class="pretax" style="cursor:help" title="飞猪列表价为不含机建燃油的裸价，出行总成本需另加此项">税前</span>':''}${f.blackCard?'<span class="pretax" style="cursor:help" title="黑卡价：渠道黑卡商品价，实付以渠道页为准">黑卡价</span>':''}${f.agePolicy?`<span class="pretax" style="color:var(--warn);cursor:help" title="资格受限专享价：仅符合限定条件（年龄/航司或平台会员资格/指定卡类型/航司协议/成团人数）的旅客可购，误购无法出行">⚠${f.agePolicy}价</span>`:''}${f.riskPolicy?`<span class="pretax" style="color:var(--warn);cursor:help" title="渠道标注的高风险政策价：出票/退款类购买风险以渠道页说明为准，下单前请核实政策详情">⚠${f.riskPolicy}</span>`:''}${f.ticketRisk?`<span class="pretax" style="color:var(--warn);cursor:help" title="值机时效风险（渠道弹层警示）：航班临近起飞，购票前请先到值机柜台确认出票后仍有时间值机；出票失败自动取消全额退款；已出票退改损失需自行承担">⚠值机</span>`:''}${f.lurePrice?`<span class="pretax" style="color:var(--warn);cursor:help" title="渠道列表页展示价￥${f.lurePrice}已被渠道过滤（不可购）：点进渠道预订将按本行可购价成交，请勿以该展示价比价">⚠页面价￥${f.lurePrice}不可购</span>`:''}${(f.returnFee!=null||f.changeFee!=null)?`<span class="pretax" style="cursor:help" title="该价位退改规则（渠道标注，当前档位费率、起飞前分档变动）：退票/改签手续费，不可=渠道标注不可办理">${_rc_txt(f)}</span>`:''}</td>`+
  `<td class="catt"><span class="tag ${f.transfer?'t-t':'t-d'}"${(f.transfer&&f.transferService)?` title="中转服务：${he(f.transferService)}"`:''}>${f.transfer?'中转':'直飞'}</span></td>`+
  `<td class="datd">${f.date?dSlash(f.date):'—'}</td>`+
  `<td${((f.labels||f.labelNote||f.baggage||f.carryon||f.bizPrice!=null)||(f.childPrice!=null||f.infantPrice!=null)||f.distance!=null||(f.nearby&&f.nearby.length)||(f.trendRound&&f.trendRound.length))?` title="${he((f.labels||'').split('·').join(' · '))+(f.labels&&f.labelNote?'｜':'')+he(f.labelNote||'')+((f.labels||f.labelNote)&&f.baggage?'｜':'')+(f.baggage?he(f.baggage):'')+((f.labels||f.labelNote||f.baggage)&&f.carryon?'｜':'')+(f.carryon?he(f.carryon):'')+((f.labels||f.labelNote||f.baggage||f.carryon)&&f.bizPrice!=null?'｜':'')+(f.bizPrice!=null?he(f.bizCabin||'公务')+'￥'+he(String(f.bizPrice)):'')+((f.childPrice!=null||f.infantPrice!=null)?(((f.labels||f.labelNote||f.bizPrice!=null||f.baggage||f.carryon)?'｜':'')+(f.childPrice!=null?'儿童价￥'+he(String(f.childPrice)):'')+((f.childPrice!=null&&f.infantPrice!=null)?'｜':'')+(f.infantPrice!=null?'婴儿价￥'+he(String(f.infantPrice)):'')):'')+(f.distance!=null?((f.labels||f.labelNote||f.baggage||f.carryon||f.bizPrice!=null||f.childPrice!=null||f.infantPrice!=null)?'｜':'')+'航程'+he(String(f.distance))+'km':'')+(f.nearby&&f.nearby.length?((f.labels||f.labelNote||f.baggage||f.carryon||f.bizPrice!=null||f.childPrice!=null||f.infantPrice!=null||f.distance!=null)?'｜':'')+he(_nb_txt(f)):'')+(f.trendRound&&f.trendRound.length?((f.labels||f.labelNote||f.baggage||f.carryon||f.bizPrice!=null||f.childPrice!=null||f.infantPrice!=null||f.distance!=null||(f.nearby&&f.nearby.length))?'｜':'')+he(_rt_txt(f)):'')}"`:''}><div class="mmeta"><span class="tag ${f.transfer?'t-t':'t-d'}"${(f.transfer&&f.transferService)?` title="中转服务：${he(f.transferService)}"`:''}>${f.transfer?'中转':'直飞'}</span><span class="mdat">${f.date?dSlash(f.date):'—'}</span></div><span class="xind" aria-hidden="true"></span>${he(f.name)}${f.stop?`<span class="stoptag">经停${he(f.stopCity||'')}${f.stopTimeT?` 停${he(f.stopTimeT)}`:''}${f.stopWin?`(${he(f.stopWin)})`:''}</span>`:''}${f.bagState==='direct'?'<span class="bagtag">直挂</span>':(f.bagState==='recheck'?'<span class="stoptag" title="渠道标注行李需重新托运（中转不直挂）">需转运</span>':'')}${f.lcc?'<span class="stoptag" title="廉价航空：中转常需重新值机、行李托运受限">廉航</span>':''}${(f.cabinT||f.prate||f.meal||f.shareCarrier||f.fewTicket||f.depTerminal||f.arrTerminal||f.depAirport||f.arrAirport||f.planeSize||f.ptripNote||f.airlineTransfer||f.avgDelay!=null||f.transTerminal||f.transDepTerminal||f.transferTax!=null||(f.leftTickets>0&&f.leftTickets<10))?`<div class="stl" style="margin-top:3px">${[f.cabinT?he(f.cabinT):'',f.cabinCode?'<span title="舱位代码'+(f.seatTilt!=null?'｜座椅倾斜'+f.seatTilt+'°':'')+'">'+he(f.cabinCode)+'</span>':'',f.prate?'准点'+he(String(f.prate))+'%'+(f.cancelRate!=null?'·取消'+he(String(f.cancelRate))+'%':''):'',f.meal?he(f.meal):'',f.planeSize?'<span title="数据源：渠道连廊率/机龄">'+he(f.planeSize)+(f.bridgeRate!=null?'·廊桥'+he(String(f.bridgeRate))+'%':'')+(f.planeAge?'·机龄'+he(String(f.planeAge))+'年':'')+'</span>':'',f.shareCarrier?'共享·'+he(f.shareAirline?f.shareAirline+f.shareCarrier:f.shareCarrier):(f.shareAirline?'承运·'+he(f.shareAirline):''),f.fewTicket?he(f.fewTicket):'',(f.leftTickets>0&&f.leftTickets<10)?'余'+he(String(f.leftTickets))+'张':'',(f.depTerminal||f.arrTerminal||f.depAirport||f.arrAirport)?'<span class="nw">'+he(((_ttc(f.depAirport,f.depTerminal,f.depAirportCode))&&(_ttc(f.arrAirport,f.arrTerminal,f.arrAirportCode))&&_ttc(f.arrAirport,f.arrTerminal,f.arrAirportCode)!==_ttc(f.depAirport,f.depTerminal,f.depAirportCode))?(_ttc(f.depAirport,f.depTerminal,f.depAirportCode)+'→'+_ttc(f.arrAirport,f.arrTerminal,f.arrAirportCode)):(_ttc(f.arrAirport,f.arrTerminal,f.arrAirportCode)||_ttc(f.depAirport,f.depTerminal,f.depAirportCode)))+'</span>':'',f.transTerminal?'换乘·'+he(f.transTerminal)+(f.transDepTerminal?'（'+he((f.transDepTerminal.match(/T\d+/)||[''])[0])+'出）':''):'',f.transferTax!=null?'<span title="飞猪列表价为不含机建燃油的裸价，出行总成本需另加此项">+机建燃油￥'+he(String(f.transferTax))+'</span>':'',f.ptripNote?he(f.ptripNote):'',_ad_txt(f.avgDelay),f.airlineTransfer?he(f.airlineTransfer):''].filter(Boolean).join(' ｜ ')}</div>`:''}${tgCap(f,k)}${f.view?`<a class="vw" href="${he(f.view)}" target="_blank" rel="noopener" onclick="event.stopPropagation()" title="去${he(f.plat||'去哪儿')}查看该航线">↗</a>`:''}${f.route?`<span class="stl nw"> <span style="display:inline-block">${he(f.route)}</span><span class="tj" role="button" tabindex="0" title="查看该航线价格走势" data-r="${he(f.route)}" data-d="${he(f.date||'')}" onclick="event.stopPropagation();jumpRowTrend(this.dataset.r,this.dataset.d)" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();event.stopPropagation();jumpRowTrend(this.dataset.r,this.dataset.d)}">📈</span></span>`:''}</td><td>${f.depTime}</td>`+
  `<td>${f.arrTime}${f.cross?`<span class="stl"> ${he(f.cross)}</span>`:''}</td>`+
  `<td>${durTxt(f.dur)||'—'}</td><td>${f.trans?he(f.trans):'—'}${(f.lay2dep||f.transGoDate)?`<div class="stl">二段 ${[f.transGoDate&&dSlash(f.transGoDate),f.lay2dep].filter(Boolean).join(' ')} 起飞</div>`:''}${f.layoverT?`<div class="${f.layMin>0?('stl lay'+((+f.layoverM||0)>=f.layMin?' ok':'')):'stl'}"${f.layMin>0?' title="航线衔接下限 '+f.layMin+' 分钟"':''}>停${f.layoverT}</div>`:''}</td>`+
  `<td><span class="pdot ${f.platKey||''}"></span>${f.plat}${f.stale?`<span class="stl">·${f.stale}h前</span>`:''}</td></tr>`+
  tgrowHtml(f,k,TGOPEN===k)+xrowHtml(u,k,EXP===k,fp(f));
 }
 return _CHUNKS[ci]=h;}
function _tblAppend(){if(!_ROWS||_NDRAW*_CHUNK>=_ROWS.length)return false;
 const h=_chunkHtml(_NDRAW);_NDRAW++;
 $('ftable').tBodies[0].insertAdjacentHTML('beforeend',h);return true;}
/* End 键显式跳底：补片会推远底边并打断平滑滚动（滚动监听的
   「距底<600」接力条件被自身补片失效），键盘路径必须一次性补
   全量再滚到底并交接末行焦点——不依赖滚动事件接力 */
function _jumpTableBottom(){
 const tw=document.querySelector('#tablecard .tw');if(!tw)return;
 while(_ROWS&&_NDRAW*_CHUNK<_ROWS.length){if(!_tblAppend())break;}
 /* ≤760 档明细跟页滚（.tw 无纵向内滚，scrollTop 是 no-op）：跳页面底 */
 if(window.innerWidth<=760){window.scrollTo(0,document.documentElement.scrollHeight);}
 else tw.scrollTop=tw.scrollHeight;
 const rows=tw.querySelectorAll('tbody tr[data-k]');
 if(rows.length)rows[rows.length-1].focus();}
 function table(){if(!S||!S.users.length)return;/* 状态未到不渲染（render 会重调）；length 门对空数组收紧（[] 真值放行曾致 curRoute 读 undefined 抛错） */
  const u=S.users[U];
  /* 全量重建保滚动：滚动容器是表格外层 .tw（overflow:auto），重建前存
     scrollTop 写回——智能刷新 10s 一拍，明细长表滚动位曾每拍弹回顶部 */
  const tw=document.querySelector('#tablecard .tw');const st=tw?tw.scrollTop:0;
  /* ≤760 档明细跟页滚：重建前存页面滚动位（内容高塌缩会先被浏览器
     钳位，innerHTML 后必须先补齐切片至原落点再 scrollTo 回设） */
  const wy=window.scrollY;
  buildWinSel();
  const rows=filteredRows();
  _ROWS=rows;_CHUNKS=[];_NDRAW=0;   /* 切片缓存随筛选/排序/换用户整体失效 */
  $('ftable').classList.toggle('big',rows.length>150);
  /* 全直飞结果集整列「—」零信息：中转列条件隐藏（按当前筛选结果集
     判定，非全库；空结果集不隐藏——空态行 colspan 铺满更完整） */
  $('ftable').classList.toggle('no-transfer',
   rows.length>0&&rows.every(f=>!f.transfer));
 let h='<thead><tr>'+HEADS.map(([k,n])=>
  `<th class="srt${SORT.k===k?' on':''}${k==='cat'?' catt':(k==='date'?' datd':'')}" data-k="${k}" scope="col" tabindex="0" aria-sort="${SORT.k===k?(SORT.dir>0?'ascending':'descending'):'none'}" onclick="sortCol('${k}')" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();sortCol('${k}')}">${n}${SORT.k===k?(SORT.dir>0?' ▲':' ▼'):''}</th>`).join('')+'</tr></thead><tbody>';
 if(rows.length){h+=_chunkHtml(0);_NDRAW=1;}
 if(!rows.length) h+='<tr class="erow"><td colspan="9">'+(u.flights.length?'没有符合条件的航班——'+(window.innerWidth<=760?/* ≤760「重置筛选」在默认收起的筛选抽屉内：宽屏词面给移动用户指不可见按钮（断头路），给抽屉语境版 */'点右上「🎛 筛选」展开抽屉后「重置筛选」恢复全部 ':'试试清空上方时段/价格筛选，或点「重置筛选」恢复全部 ')+u.flights.length+' 班':'本轮尚无采集数据——完成一轮扫描后，这里会出现航班明细（可先到「配置」核对航线与日期）')+'</td></tr>';
 /* 同 render()：重建前快照 data-k（th=排序键 / tr=fp 行键），重建后回焦 */
  const fae=document.activeElement,fk=fae&&fae.getAttribute?fae.getAttribute('data-k'):null;
  $('ftable').innerHTML=h+'</tbody>';
 /* 表内横滚提示随行渲染重判（筛选/排序/切片续载都会改 scrollWidth；
    showMonTab/resize 批只覆盖切换与几何变化点） */
 document.querySelectorAll('.tw').forEach(x=>
  x.classList.toggle('xhint',x.scrollWidth>x.clientWidth+4));
  if(tw){/* 滚动位深于首屏切片：同步补齐切片再回设（深位轮询刷新不弹顶不丢位） */
   while(st>0&&tw.scrollHeight<st+tw.clientHeight&&_tblAppend()){}
   tw.scrollTop=st;}
  if(window.innerWidth<=760&&wy>0){
   while(document.documentElement.scrollHeight<wy+window.innerHeight&&_tblAppend()){}
   window.scrollTo(0,wy);}
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
function setRange(r){if(!S||!S.users.length)return;/* 状态未到不记状态（render 重调） */
 const u=S.users[U];let st=CHR[u.name];
 if(typeof st==='number')st={i:st};st=st||{i:0};st.r=r;CHR[u.name]=st;saveUI();
 $('rng48').className='rngchip'+(r==='48h'?' on':'');
 $('rng7d').className='rngchip'+(r==='7d'?' on':'');
 tabAria();   /* 切换点同步 aria-pressed（r257 P3-2 读屏播报选中态） */
 chart();renderCal();}
function setMode(m){if(!S||!S.users.length)return;
 const u=S.users[U];let st=CHR[u.name];
 if(typeof st==='number')st={i:st};st=st||{i:0};st.m=m;CHR[u.name]=st;saveUI();
 $('mdLine').className='rngchip'+(m==='line'?' on':'');
 $('mdK').className='rngchip'+(m==='kline'?' on':'');
 tabAria();   /* 切换点同步 aria-pressed（r257 P3-2 读屏播报选中态） */
 chart();}
/* 跨年感知排序键（r235 P1-1）：走势时刻串「MM-DD HH:MM」无年份，
   字典序在跨年窗（12-31→01-01）把新年排前=整轴时间流向反转。历史
   回看窗（48h/7d）内全部时刻 ≤now：MM-DD 晚于 now 的 MM-DD 判属
   去年，其余今年——窗内同 MM-DD 至多一次（回看窗 < 一年），无歧义。
   nowMs 参数注入（钉面直调免环境 mock）；返回拼年份串，字符串比较
   即时间序。 */
function axTKey(t,nowMs){
 t=String(t||'');const mm=+t.slice(0,2),dd=+t.slice(3,5);
 if(!mm||!dd)return t;
 const d=new Date(nowMs),nm=d.getMonth()+1,nd=d.getDate();
 const y=(mm>nm||(mm===nm&&dd>nd))?d.getFullYear()-1:d.getFullYear();
 return y+'-'+t;}
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
  /* t0=桶起点时刻（非桶内首点时刻）：直/中转两系列各自聚合，渠道错峰
     使同桶首点相差可达数分钟——t0 取首点时同桶双簇在共享时间轴上分裂
     两个轴位、hover 读数错桶；取桶起点后两系列恒对齐 */
  const b0=new Date(k*bucketMin*60000),p2=n=>String(n).padStart(2,'0');
  const b0s=p2(b0.getMonth()+1)+'-'+p2(b0.getDate())+' '+p2(b0.getHours())+':'+p2(b0.getMinutes());
  /* f=桶档位：桶内含真达标轮（q=2）则整桶标真达标——曾取「桶内最低价
     那轮」档位，真达标轮被更低的行情轮掩盖整桶消失（列表🔥图上无环，
     与明细不同义）；否则与「低」标注同指桶最低价档 */
  const hit2=g.find(x=>x[2]===2);
  const lo=hit2||g.reduce((a,b)=>b[1]<a[1]?b:a);
  return {t0:b0s,o:vs[0],c:vs[vs.length-1],
   h:Math.max.apply(null,vs),l:Math.min.apply(null,vs),f:lo[2],
   /* hp=真达标轮自身价：桶最低价可能属于另一轮「行情破线
      但 _transfer_ok 不满足」的点——●环曾落在明细不标 🔥 的价上 */
   hp:hit2?hit2[1]:null}});}
function buildChartChips(){if(!S||!S.users.length)return;
 const u=S.users[U];const box=$('chartRoutes');
 const arr=u.routesArr&&u.routesArr.length?u.routesArr:null;
 const CR=curRoute();
 $('rng48').className='rngchip'+(CR.range==='48h'?' on':'');
 $('rng7d').className='rngchip'+(CR.range==='7d'?' on':'');
 $('mdLine').className='rngchip'+(CR.mode==='line'?' on':'');
 $('mdK').className='rngchip'+(CR.mode==='kline'?' on':'');
 /* 类重写无条件同拍 aria（跨用户态/恢复路径不经 setMode/setRange，
    早退路径曾跳过 mkactAll/tabAria 让 aria 停在上一态）；幂等 */
 tabAria();
 if(!arr||arr.length<2){box.innerHTML='';return;}
 const idx=CR.idx;
 chipsRefocus('chartRoutes',()=>{
 box.innerHTML='<span class="chiplab">航线：</span>'+arr.map((r,i)=>
  `<span class="chip${i===idx?' on':''}" onclick="togChart(${i})">${he(r.label)}</span>`).join('');});mkactAll();}
function togChart(i){if(!S||!S.users.length)return;
 const nm=S.users[U].name;let st=CHR[nm];
 if(typeof st==='number')st={i:st};st=st||{r:'48h'};st.i=i;CHR[nm]=st;
 saveUI();buildChartChips();CHART_ANIM=1;
 const w=document.querySelector('.chartwrap');
 if(w){w.classList.remove('viewin');void w.offsetWidth;w.classList.add('viewin');}
 chart();renderCal();}
 function chart(){if(!S||!S.users.length)return;/* 状态未到不画（render 会重调）；length 门对空数组收紧同 table */
 const RUN=++CHART_RUN;/* 新 chart 接管：旧入场动画帧作废 */
 const u=S.users[U];const CR=curRoute();
 /* 三档判定（折线点/K线桶共用，环标语言与明细🔥/推送🎯一致）：
    2=真达标（后端旗标） 1=行情破线未达标 -1=擦边（距达标线 ≤10%） 0=线外。
    折线前点状态曾手写条件序颠倒（pv[1]<=tv 先于旗标判断恒真）——
    破线段逐点串珠、○→●真达标入场环被吞 */
 /* 无旗标不标档，裸价回退=虚画真达标（反转） */
 /* TIER 值域 {2,1,-1,0}（2=真达标 1=行情破线 -1=擦边 0=线外）：
    q===0 ∧ v≤tv 落 2 的分支与服务端 _tier_of(qual=False,v≤th)=1 语义分叉，
    现三重不可达（服务端 flag=0 ⟹ ¬(th∧v≤th) 正向蕴含精确成立，反向
    须并 ¬q 才闭合；该组合 v≤tv 恒假；PRICE_MIN 下界排除 v≤0；
    环标/fl 消费点另有 tv>0/tv&& 守卫）——
    纯防御性冗余；后端旗标协议若变（flag=0 且 v≤tv 同时出现）此处必须改出 1 */
 /* 擦边带宽 ×1.1 与 core.alerter NEAR_RATIO=0.10 同值，改一处必两处同步（单源律；单源定义在 core/alerter.py，report.py 亦是 import 方）；擦边N% 词面与推送 _near_txt 同契约：≤0.5 出「不足1」、>0.5 半点向上（Math.round 本态），pctTxt 输入式须与 near 判定同式 (p-th)*100/t——先除后减的浮点在 x.5 中点系统性向下偏致两端一档分叉 */
 const TIER=(q,v,tv)=>q===2?2:(q===1?1:(q==null?0:(v<=tv?2:(v<=tv*NEAR?-1:0))));
 $('chartTitle').textContent=u.name+(CR.r.label?' · '+CR.r.label:'')
  +(CR.range==='7d'?' · 7天':'');
 const c=$('chart'),ctx=c.getContext('2d');
 /* 容器隐藏（非走势子视图）时跳过绘制：offsetWidth=0 画了也白画；
    切回走势子视图时 showMonTab 会重绘 */
 if(!c.offsetWidth)return;
 /* 高度单源：CSS clamp(240px,max(38vh,28vw),360px) 弹性（r236 取大
    语义），dpr 尺寸按 clientHeight 实测换算（resize 监听重调 chart
    即随视口重读） */
 const dpr=window.devicePixelRatio||1,H=c.clientHeight;
 /* 尺寸未变不重设：width/height 赋值即清空画布+重分配位图，hover 合帧
    后每次移动仍会进 chart()，无守卫时等于白重绘 */
 if(c.width!==Math.round(c.offsetWidth*dpr)||c.height!==Math.round(H*dpr)){
  c.width=Math.round(c.offsetWidth*dpr);c.height=Math.round(H*dpr);}
 ctx.setTransform(dpr,0,0,dpr,0,0);
 const W=c.offsetWidth,L=64,R=14,T=14,B=52;
 const H0=CR.range==='7d'?(CR.r.history7||CR.r.history):CR.r.history;
 const hd=H0.direct,ht=H0.transfer;
 /* 主题感知配色：暗色下网格/坐标轴用主题变量，不再硬编码浅色；
    网格线走 --grid 专用令牌（比 --line 提半档至 ~1.8:1 装饰豁免档，
    骨架感立现不与数据线竞争） */
 const GRID=cssv('--grid')||'#b8c2cf',AXIS=cssv('--mut')||'#5a6c7d';
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
 /* 环标图例随模式切换（折线=点环；K线=桶环）——K线曾零环而图例
    照念折线文案（图与例不一致）；「擦边」词面与推送 PNG 环标小注
    逐字同语言（收口）。环标锚点：●真达标锚桶内真达标轮自身价
    （hp），仅 ○ 锚桶最低价。赋值在 CD/CT 声明之后（K线簇位句按
    双簇在场条件化需读桶系列，r235 P2-1；本块原在 chart() 顶部，
    数据条件化后随声明序后移，空态门会整段清空 ringNote 语义不变）
    环词表随心理价缺省退场：th=0（UI 新建默认 alert=0）时 zone/dash/
    档位环对 0 全 no-op，环词表对空=装饰信号领先数据（二十三§6；
    判定式与 calStats 档位图例门同式防两处漂移）。段序重组成 join：
    th>0 时输出与拼接式逐字节等，th=0 时无悬挂分隔符 */
 const thD=(CR.r.th&&CR.r.th.direct)>0,thT=(CR.r.th&&CR.r.th.transfer)>0;
 const _rw=(thD||thT)?'环标：<span style="color:var(--green)">●</span>真达标（与明细🔥同口径）· <span style="color:var(--green)">○</span>行情破线未达标 · <span style="color:var(--warn)">○</span>擦边 · <span style="color:var(--red)">▼</span>达标回落':'';
 $('ringNote').innerHTML=CR.mode==='kline'
  ?((thD||thT)?'环标：●标在真达标轮自身价 · ○标在桶最低价；<span style="color:var(--green)">●</span>真达标（与明细🔥同口径）· <span style="color:var(--green)">○</span>行情破线未达标 · <span style="color:var(--warn)">○</span>擦边 · <span style="color:var(--red)">▼</span>达标回落<br>':'')
   +'K线=轮最低价分桶（开/收=桶内首末轮）'
   +(CD.length&&CT.length?'；左簇=直飞 · 右簇=中转':'')
   +'；<span style="color:var(--green)">绿桶</span>=桶内回落（与达标绿无关）'
  :[_rw,(hd.length&&ht.length)?'两线均为行情池最低 · 中转不限直挂':'',
     (hd.length>0&&hd.length<3)?'直飞样本少仅列点不成线':'',
     (ht.length>0&&ht.length<3)?'中转样本少仅列点不成线':''
    ].filter(Boolean).join('；');
 /* 系列色票随模式切换（r230 P2-1）+ 系列数据维度（r235 P2-1）：
    K线蜡烛只有红/绿、系列靠左右簇区分（语义入 ringNote 簇位句），
    「直飞■蓝/中转■橙」无所指即隐藏；空系列（该系列 0 点）色票
    同样隐藏——图例-数据一致性，装饰信号不领先数据；恢复条件=
    chart() 每次重算无条件重写本属性；达标虚线/线内区间双模式保留。
    达标三色票随心理价在位显示（K 线模式 zone/dash 照画故门不含
    模式项，只看对应侧 th>0） */
 $('lgDirect').style.display=(CR.mode==='kline'||!hd.length)?'none':'';
 $('lgTrans').style.display=(CR.mode==='kline'||!ht.length)?'none':'';
 $('lgZone').style.display=(thD||thT)?'':'none';
 /* 分组缝条件化（r257 P3-1）：缝的语义是「数据系列组 vs 阈值组」
    之间——K线/空数据系列档 lgDirect/lgTrans 隐藏后 lgZone 成首项，
    CSS 缺省 14px 左距变成行首悬挂缩进（inline '0' 压过 CSS；任一
    系列色票在场才保留缝）。与上两行 display 切换同函数同拍，防
    「display 翻了 margin 没翻」半同步态 */
 $('lgZone').style.marginLeft=(CR.mode!=='kline'&&(hd.length||ht.length))?'':'0';
 $('lgThD').style.display=thD?'':'none';
 $('lgThT').style.display=thT?'':'none';
 let vals=K?CD.concat(CT).map(c=>[c.h,c.l]).reduce((a,b)=>a.concat(b),[])
            .concat([CR.r.th.direct,CR.r.th.transfer]).filter(x=>x>0)
           :hd.concat(ht).map(x=>x[1]).concat([CR.r.th.direct,CR.r.th.transfer]).filter(x=>x>0);
 /* 幽灵坐标轴守卫：阈值线并入量纲源后 vals 恒非空——已配置未
    扫描航线（history 空）会画出只有达标虚线的空坐标系零解释，
    首轮扫描前打开走势必现。真实数据点为零即走空态：阈值只作
    量纲参考，不构成画图理由 */
 if(!vals.length||!(K?CD.length+CT.length:hd.length+ht.length)){
  ctx.clearRect(0,0,W,H);HPTS=null;$('ringNote').innerHTML='';
  $('lgZone').style.display='none';$('lgThD').style.display='none';$('lgThT').style.display='none';
  $('chartEmpty').innerHTML='暂无走势数据<span>完成第一轮扫描后，这里会出现近 48h 的最低价曲线</span>';
  $('chartEmpty').style.display='flex';return;}
 $('chartEmpty').style.display='none';
 const lo=Math.min(...vals)-30,hi=Math.max(...vals)+30;
 /* nice-step 整价锚（与 report.py _nice_ticks 同律）：刻度曾
    lo+(hi-lo)k/4 浮点直出（￥2031/￥1926 类尾数价）——数据点几乎永不落线，扫读对齐
    形同虚设。阶梯 (1,2,5,10)：标签永远 ×00/×50 收尾。门槛 ≥raw*0.5
    （同律同改）：≥raw 档在 raw∈(100,200] 带步长突翻倍、48h 窗常态
    仅 2 条网格线（悬崖带实证 lo=1630/hi=2060） */
 const _raw=(hi-lo)/4;let _mag=1;while(_mag*10<=_raw)_mag*=10;
 const _nice=[1,2,5,10].find(m=>m*_mag>=_raw*0.5)*_mag;
 const _k0=Math.ceil(lo/_nice-1e-9),_k1=Math.floor(hi/_nice+1e-9);
 /* 共享时间轴（r235 P1）：双系列点数不齐时索引式 X 把稀疏系列压到
    左缘（某系列仅窗尾 2 点时整条线挤在 x=L 附近，低点标注/档位环/
    回落▼全错位），hover/键盘按同索引取两系列还会跨时刻错配读数
    （十字在窗尾读出窗头价）——按双系列全部时刻排序去重建轴，每点
    按自身时刻落位；X 的索引语义统一为「轴刻度索引」，系列内索引
    经 axd/axt 换算 */
 const tset=(K?[...new Set(CD.concat(CT).map(c=>String(c.t0||'')))]
             :[...new Set(hd.concat(ht).map(p=>String(p[0]||'')))])
   .sort((a,b)=>{const ka=axTKey(a,Date.now()),kb=axTKey(b,Date.now());
    return ka<kb?-1:ka>kb?1:0;});
 const TIDX={};tset.forEach((t,i)=>{TIDX[t]=i;});
 const NT=tset.length;
 const AXT=t=>TIDX[String(t||'')]||0;
 const axd=K?(i=>AXT(CD[i].t0)):(i=>AXT(hd[i][0]));
 const axt=K?(i=>AXT(CT[i].t0)):(i=>AXT(ht[i][0]));
 const X=i=>L+(W-L-R)*(NT>1?i/(NT-1):0.5),Y=v=>T+(H-T-B)*(1-(v-lo)/(hi-lo));
 /* 承诺句条件在场（NT>0 有点可点 + CR.r.date 有处可跳）：空态死承诺
    防线（jumpCalDate 条件化同律）；chart() 顶部已重写 ringNote，
    此处追加幂等 */
 if(NT>0&&CR.r.date)$('ringNote').insertAdjacentHTML('beforeend',
  '<span class="cs-lg"> · 点击看该航线当日明细</span>');
 const chartDraw=()=>{
 ctx.clearRect(0,0,W,H);ctx.font='11px '+(cssv('--num')||'sans-serif');
 for(let k=_k0;k<=_k1;k++){const v=_nice*k;
  ctx.strokeStyle=GRID;ctx.setLineDash([2,4]);
  ctx.beginPath();ctx.moveTo(L,Y(v));ctx.lineTo(W-R,Y(v));ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle=AXIS;ctx.fillText('￥'+Math.round(v),6,Y(v)+4);}
 /* X 轴双行刻度：HH:MM 行(H-22) + 跨天日期行(H-8)；按实测宽度避让，
    相邻标签绝不互撞。日期标签挂在分隔竖线底部（画图内顶部会被
    折线/散点压住不可读）。折线/K线统一遍历共享时间轴 tset（轴刻度
    索引=X 语义，稀疏系列不再产生错位刻度） */
 const tickT=i=>tset[i]||'';
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
    /* 时间参考线中性化（--line2 线条档/日期标签 --mut 文字档）：
       曾取 --stl 警示色与中转达标琥珀虚线语义竞争；运行时取值+
       兜底仅防 var 缺失，值随 :root 亮谱令牌对齐（兜底漂移=改令牌
       必漏面） */
    ctx.globalAlpha=.45;ctx.strokeStyle=cssv('--line2')||'#cbd4de';
    ctx.lineWidth=1;
    ctx.beginPath();ctx.moveTo(gx,T);ctx.lineTo(gx,H-B);ctx.stroke();
    ctx.globalAlpha=1;
    ctx.lineWidth=3;ctx.strokeStyle=halo;
    ctx.strokeText(day,dx,H-8);
    ctx.fillStyle=cssv('--mut')||'#5a6c7d';ctx.fillText(day,dx,H-8);
    prevDay=day;}}}
 const zone=(v)=>{if(!v||v<lo||v>hi)return;ctx.fillStyle=cssv('--okzone')||'rgba(14,131,69,.14)';ctx.fillRect(L,Y(v),W-L-R,H-B-Y(v));};
 zone(CR.r.th.direct);zone(CR.r.th.transfer);
 const dash=(v,col)=>{if(!v||v<lo||v>hi)return;ctx.strokeStyle=col;ctx.setLineDash([6,5]);
  ctx.beginPath();ctx.moveTo(L,Y(v));ctx.lineTo(W-R,Y(v));ctx.stroke();ctx.setLineDash([]);};
 dash(CR.r.th.direct,cssv('--red')||'#c22a2e');dash(CR.r.th.transfer,cssv('--thline')||'#8a6d1f');
 if(K){
  /* K线：涨红空心 跌绿实心（A股习惯）；直飞左偏 中转右偏。
     窄画布触底保中心距：cw 触底 4px 时 ±0.62cw=±2.5px 偏移
     让两系列中心距 5px<目视分辨并成单列（390 档实测），下限
     4px 保中心距 8px——仍 <pitch 桶序不交错、环标互叠缓解 */
  const cw=Math.max(4,Math.min(15,(W-L-R)/Math.max(NT,1)*0.30));
  const drawK=(cs,off,xf)=>{cs.forEach((c,i)=>{
   /* 首末桶钳位（审计 P3-1）：蜡烛以桶中心定位，首桶 cx=L 时左半
      越过绘图区压 Y 轴标签带（7 天窗首桶红蜡烛半裁实测）——双端
      钳进 [L+cw/2, W-R-cw/2]，首末桶对称不单侧 */
   const cx=Math.max(L+cw/2,Math.min(W-R-cw/2,X(xf(i))+off)),up=c.c>=c.o,col=up?(cssv('--red')||'#c22a2e'):(cssv('--green')||'#0e8345');
   ctx.strokeStyle=col;ctx.lineWidth=1.2;
   ctx.beginPath();ctx.moveTo(cx,Y(c.h));ctx.lineTo(cx,Y(c.l));ctx.stroke();
   const yT=Y(Math.max(c.o,c.c)),yB=Y(Math.min(c.o,c.c));
   /* doji 桶（开=收）实体高下限 3px：1.5px 短横成排后与达标红虚线
      同色同形，远看是第二条阈值线（读图歧义）——3px 矮棒可辨 */
   if(up)ctx.strokeRect(cx-cw/2,yT,cw,Math.max(3,yB-yT));
   else{ctx.fillStyle=col;ctx.fillRect(cx-cw/2,yT,cw,Math.max(3,yB-yT));}});};
  const koff=Math.max(cw*0.62,4);drawK(CD,-koff,axd);drawK(CT,koff,axt);
  /* K线档位环（与折线三档同语言）：●粗绿=真达标（锚桶内真达标轮自身
     价） ○细绿=行情破线 ○琥珀=擦边（两 ○ 锚桶最低价=影线低点，
     与「低」标注同所指）；仍按状态入场+末桶防串珠（桶数 48h≤24/7d≤28，
     密度无忧） */
  const ringK=(cs,off,tv,xf)=>{if(!tv)return;
   const stOf=c=>TIER(c.f,c.l,tv);
   cs.forEach((c,i)=>{const st=stOf(c);
    const pv=i>0?cs[i-1]:null;
    const pst=pv?stOf(pv):0;
    /* 环标中心与烛体同款双端钳位（r273 P3-1：烛体钳位当年只护了
       蜡烛，末桶环心 X+koff 越过 W-R、半径再外扩半截环贴 canvas
       右缘——同式钳进绘图区，左右对称） */
    const cx=Math.max(L+cw/2,Math.min(W-R-cw/2,X(xf(i))+off));
    if(pst===2&&st!==2)fallMark(cx,Y(c.l));/* ▼红=达标回落 */
    if(!st)return;
    if(!pst||pst!==st||i===cs.length-1){
     /* ●=真达标环锚 hp（桶内真达标轮自身价，与明细 🔥 同所指——
         终局：曾锚桶最低价，行情最低轮≠达标轮时环画在非达标
        价上）；○环仍锚桶最低价（行情档语义） */
     const rp=(st===2&&c.hp!=null)?c.hp:c.l;
     const grn=cssv('--green')||'#0e8345';
     if(st===2){/* ●实心=真达标（与折线/图例同语言） */
      ctx.beginPath();ctx.arc(cx,Y(rp),5,0,7);
      ctx.fillStyle=grn;ctx.fill();
      ctx.lineWidth=1.5;ctx.strokeStyle=cssv('--card')||'#fff';ctx.stroke();
     }else{
      const ring=st===-1?[5,2,cssv('--warn')||'#8a6c00']
       :[5,1,grn];
      ctx.beginPath();ctx.arc(cx,Y(rp),ring[0],0,7);
      ctx.fillStyle=cssv('--card')||'#fff';ctx.fill();
      ctx.lineWidth=ring[1];ctx.strokeStyle=ring[2];ctx.stroke();}}});};
  ringK(CD,-koff,CR.r.th.direct,axd);ringK(CT,koff,CR.r.th.transfer,axt);
  HPTS={kline:true,
   cd:CD.map(c=>Object.assign({},c,{_ax:AXT(c.t0)})),
   ct:CT.map(c=>Object.assign({},c,{_ax:AXT(c.t0)})),
   cw:cw,L:L,Rx:W-R,T:T,B:H-B,N:NT,
   thd:CR.r.th.direct,tht:CR.r.th.transfer};
  /* K线最低影线标注（同样带完整时刻）；候选位按盒内影线命中数取最少 */
  let best=null;CD.forEach((c,i)=>{if(!best||c.l<best.c.l)best={c,i,s:'d'};});
  CT.forEach((c,i)=>{if(!best||c.l<best.c.l)best={c,i,s:'t'};});
   if(best&&best.i!==(best.s==='d'?CD:CT).length-1){
    const bx=X((best.s==='d'?axd:axt)(best.i))+(best.s==='d'?-koff:koff);
    ctx.font='bold 11px '+(cssv('--num')||'sans-serif');
    const ktag='低 ￥'+Math.round(best.c.l)+' '+String(best.c.t0||'').slice(0,11);
    const kw=ctx.measureText(ktag).width;
    const hitN=(cx,cy)=>{let n=0;
     for(let s=0;s<2;s++){const xf=s?axt:axd,off=s?koff:-koff;
      const arr=s?CT:CD;
      for(let i=0;i<arr.length;i++){
       const cxx=X(xf(i))+off;
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
     const cy=Math.min(Math.max(c[1],T+12),H-B-6);
     const n=hitN(cx,cy)+(placedBoxes.some(b=>
      !(cx+kw+3<b[0]||b[2]<cx-3||cy+4<b[1]||b[3]<cy-12))?99:0);
     if(n<bn){bn=n;kx=cx;ky=cy;}
     if(!bn)break;}
    tagBox(kx,ky,kw);
    /* 「低」标签随所属系列色（直飞蓝/中转橙），不再与达标线红同色混淆；
       文字消费文字档令牌（图形档 --orange 对白 halo 3.78 欠 AA） */
    ctx.fillStyle=best.s==='d'?(cssv('--blue')||'#0b62d6'):(cssv('--orange-txt')||'#a45508');
    ctx.fillText(ktag,kx,ky);
    placedBoxes.push([kx-3,ky-12,kx+kw+3,ky+4]);
    ctx.font='11px sans-serif';}
  }else{
  const series=(pts,color,tv,xf)=>{if(!pts.length)return;
   if(pts.length>=3){
    ctx.beginPath();ctx.moveTo(X(xf(0)),Y(pts[0][1]));
    /* 平滑曲线：水平控制点三次贝塞尔（monotone 不过冲）+ 渐变面积填充
       （X/Y 接收轴索引——曾误传时间标签致整条曲线 NaN 消失，仅剩散点） */
    for(let i=1;i<pts.length;i++){
     const x0=X(xf(i-1)),y0=Y(pts[i-1][1]),x1=X(xf(i)),y1=Y(pts[i][1]);
     ctx.bezierCurveTo((x0+x1)/2,y0,(x0+x1)/2,y1,x1,y1);}
    ctx.strokeStyle=color;ctx.lineWidth=2.2;ctx.stroke();
    ctx.lineTo(X(xf(pts.length-1)),H-B);ctx.lineTo(X(xf(0)),H-B);
    ctx.closePath();
    const g=ctx.createLinearGradient(0,T,0,H-B);
    g.addColorStop(0,color+'44');g.addColorStop(1,color+'08');
    ctx.fillStyle=g;ctx.fill();}
   /* 稀疏系列（n<3，直挂航线中转全程仅 2 点的真实形态）只画点不
      连线：两点间平滑曲线+面积在窗尾画成陡坡，读感「暴跌」误判
      （r244 P3-1）；稀疏注随 ringNote 声明（图例-数据一致） */
   const RPT=pts.length>240?1.4:(pts.length>120?2:2.6);/* 7 天窗≈672 点/系：1.8px 间距实心点连成珠链淹没低点，>240 点降半径（report 侧 同思想） */
   pts.forEach((p,i)=>{ctx.fillStyle=color;ctx.beginPath();
    ctx.arc(X(xf(i)),Y(p[1]),RPT,0,7);ctx.fill();});
   /* audit P3-4：入场点环在密集窗互叠成串——7 天窗 390 档 672 点/系
      挤 334px，价格在达标线附近震荡时状态转换密，相邻「已绘环」X
      间距 <8px（环径 10px）即视觉粘连。绘制层按上一枚已绘环去重
      （末点豁免恒在位）；数据点/状态判定/悬停键盘读数全不动，仅防
      串珠。lastRX 挂 series 闭包（每系列独立），K线侧桶数少不动 */
   let lastRX=-1e9;
   if(tv>0)/* 分档点环（与推送图/明细同语义）：●粗绿=真达标（后端旗标，
      与明细🔥/推送🎯同口径）；○细绿=行情破线但未达标（非直挂/
      衔接不足/税前）；○琥珀=擦边（距达标线 ≤10%，未必达标）。仍只画状态入场点
      与最新点，长期同状态段不逐点密铺成串（7 天窗口实测） */
    pts.forEach((p,i)=>{const q=p[2],v=p[1];
     const st=TIER(q,v,tv);
     const pv=i>0?pts[i-1]:null;
     const pst=pv?TIER(pv[2],pv[1],tv):0;
     if(pst===2&&st!==2)fallMark(X(xf(i)),Y(v));/* ▼红=达标回落 */
    if(st&&(!pst||pst!==st||i===pts.length-1)){
     const rx=X(xf(i));
     if(!(i===pts.length-1)&&rx-lastRX<8)return;
     lastRX=rx;
     const grn=cssv('--green')||'#0e8345';
     if(st===2){/* ●实心=真达标（与图例字面成立；亮描边防曲线穿心）
        ——曾两种档只差 1px 线宽，●/○ 视觉不可分 */
      ctx.beginPath();ctx.arc(X(xf(i)),Y(v),5,0,7);
      ctx.fillStyle=grn;ctx.fill();
      ctx.lineWidth=1.5;ctx.strokeStyle=cssv('--card')||'#fff';ctx.stroke();
     }else{
      const ring=st===-1?[5,2,cssv('--warn')||'#8a6c00']
       :[5,1,grn];
      ctx.beginPath();ctx.arc(X(xf(i)),Y(v),ring[0],0,7);
      ctx.fillStyle=cssv('--card')||'#fff';ctx.fill();
      ctx.lineWidth=ring[1];ctx.strokeStyle=ring[2];ctx.stroke();
      /* 环心补系列色小点（审计 P2-3）：环内 card 不透明填充曾把
         同圆心系列点完全盖住——稀疏中转系列（n<3 只列点不成线）
         图上只见环不见点，图例「中转最低」色票无所指，图例-数据
         一致律在稀疏场景破功 */
      ctx.beginPath();ctx.arc(X(xf(i)),Y(v),1.4,0,7);
      ctx.fillStyle=color;ctx.fill();}}});};
  series(hd,cssv('--blue')||'#0b62d6',CR.r.th.direct,axd);
  series(ht,cssv('--orange')||'#c96a10',CR.r.th.transfer,axt);
  HPTS={d:hd.map((p,i)=>[X(axd(i)),Y(p[1]),p[1],p[0],p[2],axd(i)]),
   t:ht.map((p,i)=>[X(axt(i)),Y(p[1]),p[1],p[0],p[2],axt(i)]),
   L:L,Rx:W-R,T:T,B:H-B,N:NT,thd:CR.r.th.direct,tht:CR.r.th.transfer};
  /* 最低点标注：带完整日期时刻（只显 HH:MM 会被误读为"刚刚暴跌"）。
     候选位按「标签盒内压到多少数据点」取最少——密集 7 天窗固定偏移
     曾直接盖在线上（小屏/密集场景图文互遮挡实锤），全撞才落首选 */
  const markMin=(pts,color,bandY)=>{if(!pts||pts.length<3)return;
   let mi=0;pts.forEach((p,i)=>{if(p[2]<pts[mi][2])mi=i;});
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
   for(const dy of [-10,16,42])
    for(const dx of [6,6+tagW*.55,6-tagW*.55,6+tagW*1.1,6-tagW*1.1])
     cands.push([x+dx,y+dy]);
   /* 顶部专属带（bandY 双系列异带恒异行）：审计 P1-1——共享
      顶带候选时双系列最低点常水平邻近，同带 0 分位让后绘盒贴邻先绘
      盒盖住「低」前缀（评分制逃生档实证不够）；专属带按系列确定性
      分行，同带贴邻类整类根除 */
   for(const dx of [6,6+tagW*1.05,6-tagW*1.05,6+tagW*2.1,6-tagW*2.1])
    cands.push([x+dx,bandY]);
   let bx=x+6,by=y-10,bn=1e9;
   for(const c of cands){
    const cx=Math.min(Math.max(c[0],L),W-tagW-6);
    /* 钳位下界=绘图区底(H-B)-标签高：B 是底边距(52)非底坐标——
       旧 B-6 在高画布(454px)把全部候选钳进 y∈[26,46] 顶部窄带，
       近点候选永不可达、双系列标注注定同带互叠（审计 P1-1 真根因，
       专属带/逃生档均被此钳位吞没） */
    const cy=Math.min(Math.max(c[1],T+12),H-B-6);
    /* 标签互叠罚 999+纵向错距梯度：互叠绝对劣于压数据（白底块保可
       读，叠字不可读）；横向判定外扩 6px 兼收「同带贴邻」（审计
       P1-1：宽画布双系列最低点常水平邻近，先绘盒右缘曾压住后绘标注
       的「低」前缀）；常数罚下全候选必撞时按错距梯度换行——近点三行
       +顶部两行给全叠情形错行出口 */
    const n=hitN(cx,cy)+placedBoxes.reduce((a,b)=>
     !(cx+tagW+6<b[0]||b[2]<cx-6||cy+4<b[1]||b[3]<cy-12)
      ?Math.max(a,999+Math.max(0,16-Math.abs(cy-b[1]))):a,0);
    if(n<bn){bn=n;bx=cx;by=cy;}
    if(!bn)break;}
   tagBox(bx,by,tagW);
   ctx.fillStyle=color;ctx.fillText(tag,bx,by);
   placedBoxes.push([bx-3,by-12,bx+tagW+3,by+4]);
   ctx.font='11px sans-serif';};
  markMin(HPTS.d,cssv('--blue')||'#0b62d6',T+12);markMin(HPTS.t,cssv('--orange-txt')||'#a45508',T+44);
 }
 };  /* /chartDraw */
 /* 入场动画：左→右擦除重现（数据刷新/切航线触发，hover 重绘不触发）；
    RM（prefers-reduced-motion）时直取终值——CSS 全禁了 JS 动画仍跑。
    动画轮跳过首绘：先全量画满终帧再逐帧 clip 重绘同内容=零视觉产出
    （中段右区恒等于终帧），跳过后才从旧图/空布左→右揭示 */
 const _anim=CHART_ANIM&&!RM;
 if(!_anim)chartDraw();
 if(_anim){CHART_ANIM=0;const t0=performance.now();
  const step=t=>{if(RUN!==CHART_RUN)return;/* 已被新 chart 接管：旧帧作废 */
   const p=Math.max(0,Math.min(1,(t-t0)/700)),e=1-Math.pow(1-p,3);
   ctx.save();ctx.beginPath();ctx.rect(0,0,L-2+(W-L+2)*e,H);ctx.clip();
   chartDraw();ctx.restore();
   if(p<1)requestAnimationFrame(step);};
  requestAnimationFrame(step);}
 else if(CHART_ANIM)CHART_ANIM=0;
}
/* 悬停提示：十字线 + 数值浮框（折线读价 / K线读 OHLC） */
let HPTS=null,CHART_ANIM=0,CHART_RUN=0;
function drawHover(x){const c=$('chart'),ctx=c.getContext('2d');
 if(!HPTS)return;
 /* 档位后缀（与环标图例逐字同形）：flag 2=●真达标、1=○行情破线 */
 const fl=(q,v,tv)=>q===2?' ●真达标':(q===1?' ○行情破线':(tv&&v<=tv*NEAR?' ○擦边':(tv?' ·差￥'+(v-tv):'')));   /* 读数后缀与环标图例逐字同形（●实心=真达标/○空心=行情破线·擦边——真达标曾用 🎯 与图例 ● 同档三字面漂移）；NEAR 同步律见 TIER；线外点补差额读数免目测虚线（词面与推送 KPI「差￥N」同形） */
 let ax,txt,parts=[];
 if(HPTS.kline){
  const {cd,ct,L,Rx}=HPTS;
  const N=HPTS.N||Math.max(cd.length,ct.length);if(N<1)return;
  /* 轴位反查（共享时间轴）：十字线锚「轴刻度索引」，桶按自身 t0
     的轴位命中——稀疏系列缺位轴不误配邻桶 */
  let i=Math.round((x-L)/(Rx-L)*(N-1));i=Math.max(0,Math.min(N-1,i));
  const kd=cd.find(c=>c._ax===i),kt=ct.find(c=>c._ax===i);
  if(!kd&&!kt)return;
  ax=L+(Rx-L)*(N>1?i/(N-1):0.5);
  parts=[];
  if(kd)parts.push('直飞(轮最低) 低￥'+kd.l+fl(kd.f,kd.l,HPTS.thd)+' 开￥'+kd.o+' 收￥'+kd.c+' 高￥'+kd.h);
  if(kt)parts.push('中转(轮最低) 低￥'+kt.l+fl(kt.f,kt.l,HPTS.tht)+' 开￥'+kt.o+' 收￥'+kt.c+' 高￥'+kt.h);
  txt=((kd||kt).t0||'')+'　'+parts.join('　');
 }else{
  const {d,t,L,Rx,T,B}=HPTS;
  const N=HPTS.N||Math.max(d.length,t.length);if(N<1)return;
  let i=Math.round((x-L)/(Rx-L)*(N-1));i=Math.max(0,Math.min(N-1,i));
  /* 轴位反查（共享时间轴）：点带 _ax 轴索引，两系列各按自身时刻
     命中——同索引配对曾在稀疏系列把窗尾十字读成窗头价 */
  const pd=d.find(q=>q[5]===i),pt=t.find(q=>q[5]===i);
  if(!pd&&!pt)return;
  ax=(pd||pt)[0];
  parts=[];
  if(pd){ctx.fillStyle=cssv('--blue')||'#0b62d6';ctx.beginPath();ctx.arc(pd[0],pd[1],4.5,0,7);ctx.fill();
   parts.push('直飞最低 ￥'+pd[2]+fl(pd[4],pd[2],HPTS.thd));}
  if(pt){ctx.fillStyle=cssv('--orange')||'#c96a10';ctx.beginPath();ctx.arc(pt[0],pt[1],4.5,0,7);ctx.fill();
   parts.push('中转最低 ￥'+pt[2]+fl(pt[4],pt[2],HPTS.tht));}
  txt=((pd||pt)[3]||'')+'　'+parts.join('　');
 }
 ctx.strokeStyle=getComputedStyle(document.documentElement).getPropertyValue('--mut').trim()||'#5a6c7d';
 ctx.setLineDash([4,4]);
 ctx.beginPath();ctx.moveTo(ax,HPTS.T);ctx.lineTo(ax,HPTS.B);ctx.stroke();ctx.setLineDash([]);
 /* 行预算：窄画布一行装不下（K线双系列 OHLC 读数 ~600px，390px 手机
    画布 ~370px，offsetWidth-w-4 为负曾把 tooltip 半截裁出画布）→
    按「　」部件拆行；单部件仍超宽时 K线降级只留 低/收 决策数字 */
 ctx.font='12px '+(cssv('--num')||'sans-serif');   /* 读数与图内刻度同 mono（数字扫读不跳） */
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
/* hover 合帧：每事件全量 chart() 曾在宽屏 dpr=2 下逐移动
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
/* 键盘步进十字线（打磨池）：走势读数键盘可达——聚焦画布后
   ←/→ 逐点、Home/End 跳首尾，读数走 drawHover 同一管线（含档位后缀
   与 K线降级），索引钳制到 HPTS 点数；CHART_RUN 纪律天然满足（与
   mousemove 同走 chart()，入场动画旧帧自动作废）；blur 清十字线对齐
   onmouseleave */
let KB_IDX=null;
function _kbN(){if(!HPTS)return 0;
 return HPTS.N||Math.max(HPTS.kline?HPTS.cd.length:HPTS.d.length,
                         HPTS.kline?HPTS.ct.length:HPTS.t.length);}
$('chart').addEventListener('keydown',e=>{if(!HPTS)return;
 const N=_kbN();if(N<1)return;
 /* 首按方向即落点：→ 从最老点开始、← 从最新点开始（m1 审查收口：
    曾统一初值 N-1 使首按 → 停末点且再按无位移，观感似失灵） */
 let i;
 if(e.key==='ArrowRight')i=KB_IDX===null?0:Math.min(N-1,KB_IDX+1);
 else if(e.key==='ArrowLeft')i=KB_IDX===null?N-1:Math.max(0,KB_IDX-1);
 else if(e.key==='Home')i=0;
 else if(e.key==='End')i=N-1;
 else if(e.key==='Enter'||e.key===' '){e.preventDefault();jumpTrendDetail();return;}
 else return;
 e.preventDefault();
 KB_IDX=i;
 const x=HPTS.L+(HPTS.Rx-HPTS.L)*(N>1?i/(N-1):0.5);
 chart();drawHover(x);});
$('chart').addEventListener('blur',()=>{if(KB_IDX===null)return;
 KB_IDX=null;if(HPTS)chart();});
/* C-1 走势点→该轮明细：点击画布任意点=看该系列（航线+出发日）明细，
   目标与点位无关（一系列一日）；触屏滑动防误触——位移 >8px 的 touch
   视为滚动手势不触发 click 跳转；右键/中键不跳。
   触屏双拍：触屏首 tap=读数（touchstart 已映射 hover 十字线，
   不再 touchend 即清），同点二次 tap 才跳明细，异点 tap=换点重读——
   旧形态轻 tap 直接离场，移动端既读不到数值也无法「点一下看看」而不
   换页；鼠标路径不经过 _tPin，行为不变 */
let _tTap=null;
let _tPin=null;   /* 触屏读数锚：首 tap 记点保留十字线，同点二次 tap 放行跳转 */
let _tGo=false;   /* touchend 判定「同点二次 tap」→ click 放行（click 在 touchend 后合成，时序上锚已就位） */
let _tTouch=false;   /* 本轮 click 来自触屏（tap 必先 touchstart；消费即清） */
$('chart').addEventListener('touchstart',e=>{const t=e.touches&&e.touches[0];
 _tTouch=true;_tTap=t?[t.clientX,t.clientY]:null;},{passive:true});
/* touchend 后拍一拍清残坐标：tap 自身的 click 同步先发仍能读到 _tTap
   做位移判定，此后混合设备的鼠标点击不再被残坐标误吞（P2-3）。
   tap（位移 ≤8px）：首 tap 记锚 _tPin 保留十字线读数；同点二次 tap
   置 _tGo 放行 click 跳明细；异点 tap=换锚重读。滚动触摸全清 */
$('chart').addEventListener('touchend',
 e=>{const t=e.changedTouches&&e.changedTouches[0];
  if(t&&_tTap){const dx=t.clientX-_tTap[0],dy=t.clientY-_tTap[1];
   if(dx*dx+dy*dy<=64){
    if(_tPin){const px=t.clientX-_tPin[0],py=t.clientY-_tPin[1];
     if(px*px+py*py<900){_tGo=true;
      setTimeout(()=>{_tTap=null;},0);return;}}
    _tPin=[t.clientX,t.clientY];
    setTimeout(()=>{_tTap=null;},0);return;}}
  _tPin=null;_tGo=false;_tTap=null;
  _hovX=null;if(_hovRaf){cancelAnimationFrame(_hovRaf);_hovRaf=0;}
  if(HPTS)chart();},{passive:true});
$('chart').addEventListener('click',e=>{if(e.button!==0)return;
 if(_tTap){const dx=e.clientX-_tTap[0],dy=e.clientY-_tTap[1];
  if(dx*dx+dy*dy>64){_tTap=null;return;}}
 _tTap=null;
 if(!_tTouch){if(HPTS&&S&&S.users)jumpTrendDetail();return;}   /* 鼠标路径原行为 */
 _tTouch=false;
 if(_tGo){_tGo=false;_tPin=null;
  if(HPTS&&S&&S.users)jumpTrendDetail();}
  /* 首 tap：锚已记、读数已显（touchstart hover 管线），click 吞掉不跳 */});
/* ===== 触屏横向热区近邻映射：脉冲柱/健康格横向仅 4-9px，缝死区+
   邻格 ::after 吃缝的 off-by-one（指尖点格 N 右缘修正带系统性开到
   N+1 日志）低于指尖分辨率。coarse 指针下容器捕获阶段截获点击，
   按「点击点到动作格本体矩形的 Chebyshev 距离」最近邻重判（等距
   取先遍历=左格；距离必须含 Y 维——健康区多行同列，纯 X 维会让
   跨行直击 d=0 平手塌向 DOM 序首行）；桌面鼠标路径不经 coarse
   分支零变化。无动作格/none 格不入候选；委托挂恒存容器（hbody/
   pulsebars），render 重建子树不丢监听；best.onclick 直调不走事件
   传播，无递归。行内标签/徽标（hlab/hbadge）无自身动作，点击落
   最近动作格=行级命中放大语义，定界接受 ===== */
const _nearHit=(wrapId,sel)=>{const w=$(wrapId);if(!w||w._near)return;
 w._near=1;
 w.addEventListener('click',e=>{
  if(!(window.matchMedia&&matchMedia('(pointer:coarse)').matches))return;
  let best=null,bd=Infinity;
  for(const x of w.querySelectorAll(sel)){
   if(!x.onclick||x.classList.contains('none'))continue;
   const r=x.getBoundingClientRect();
   const dx=e.clientX<r.left?r.left-e.clientX
           :(e.clientX>r.right?e.clientX-r.right:0);
   const dy=e.clientY<r.top?r.top-e.clientY
           :(e.clientY>r.bottom?e.clientY-r.bottom:0);
   const d=Math.max(dx,dy);
   if(d<bd){bd=d;best=x;}}
  if(!best)return;
  e.preventDefault();e.stopPropagation();
  if(typeof best.onclick==='function')best.onclick.call(best,e);},true);};
_nearHit('hbody','.hc');_nearHit('pulsebars','.pbar');
/* ===== toast（替代 alert）与按钮内联二次确认（替代 confirm） ===== */
function toast(msg,kind){let box=$('toasts');
 if(!box){box=document.createElement('div');box.id='toasts';
  box.setAttribute('role','status');box.setAttribute('aria-live','polite');   /* 读屏播报新 toast */
  document.body.appendChild(box);}
 const t=document.createElement('div');t.className='toast '+(kind||'');
 t.textContent=msg;t.tabIndex=0;t.setAttribute('role','button');
 t.setAttribute('aria-label','通知（回车关闭）');box.appendChild(t);
 t.onclick=()=>{if(t.parentNode)t.remove();};   /* 点击即关（错误类驻留更长） */
 t.onkeydown=(e)=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();
  if(t.parentNode)t.remove();}};   /* 可点件必有键盘路径：Esc 只关最新一条，逐条 Enter/Space 补齐 */
 setTimeout(()=>{t.classList.add('out');
  setTimeout(()=>{if(t.parentNode)t.remove();},350);},kind==='err'?5000:2600);}
function _evtT(){/* window.event 守卫：废弃全局在
   非点击路径/非 Chromium 内核为 undefined——确认态按钮找不到锚时静默
   降级，不再抛 ReferenceError。仅作无参调用兜底：危险动作件一律显式
   传 this（window.event 是 Chromium 专属，Firefox/Safari 恒 undefined
   曾让内联动作件全哑——空锚静默=交互断头路） */
 return (typeof event!=='undefined'&&event&&event.target)||null;}
async function api(act,msg,b){b=b||_evtT();if(!b)return;   /* 空锚静默 */
 if(b.classList.contains('busy'))return;   /* busy 守卫：pointer-events 只挡指针，键盘 Enter 合成 click 照发（同族九件同款首行守卫）——双发=双轮扫描/双份钉钉推送 */
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
function armConfirm(el,fn){if(!el)return;   /* _evtT 空锚静默 */
 if(!el.dataset.arming){
 el.dataset.arming='1';el.dataset.label=el.textContent;
 el.style.minWidth=el.offsetWidth+'px';   /* 确认文案更短，锁首态宽防同排控件位移（api 同族） */
 el.textContent='⚠ 确认';el.classList.add('arming');
 setTimeout(()=>{if(el.dataset.arming){delete el.dataset.arming;
  el.textContent=el.dataset.label;el.classList.remove('arming');el.style.minWidth='';}},3000);return;}
 delete el.dataset.arming;el.textContent=el.dataset.label;
 el.classList.remove('arming');el.style.minWidth='';fn();}
/* ===== 渠道健康时间线：/api/health（monitor.log 解析，与状态同拍刷新） ===== */
let HL=null;
async function health(){try{const r=await fetch('/api/health');
 const t=await r.text();if(t===HL)return;HL=t;renderHealth(JSON.parse(t));}
 catch(e){/* 错误态落点（_markStale 家族）：健康 tab 整区纯空白=零
   引导；healthcard 可见=已有真实时间线，保陈旧不闪错，恢复轮重写自愈 */
  const _he=$('healthEmpty');
  if(_he&&$('healthcard').style.display==='none'){_he.style.display='';
   _he.innerHTML='⚠ 健康数据读取失败（详见服务日志）';}}}
function renderHealth(j){
 /* 已有时间线时错误体保陈旧（与 catch 分支「healthcard 可见=保陈旧不
    闪错」政策对齐）：瞬态 500 曾把整条格带掀成错误文案，下一轮询才自愈 */
 if(j&&j.err&&!j.rounds&&$('healthcard').style.display!=='none')return;
 const _he=$('healthEmpty');
 if(!j||!j.rounds||!j.rounds.length){
  if(_he){_he.style.display='';
   _he.innerHTML=(j&&j.err)?'⚠ 健康数据读取失败（详见服务日志）'
    :'暂无扫描记录——完成一轮采集后，这里会出现 24h 渠道健康时间线';}
  $('healthcard').style.display='none';   // 空态/错误态回收旧卡：500 错误体曾点亮空态文案而旧 96 轮格带同屏并存
  /* 推送连败源随健康数据一并清零（红帽双源合成，Soldier Minor-1）：
     账本空窗后 _ovPushStreak 残留旧值会让红帽常亮而健康页推送通道
     区已随 healthcard 回收，「详情见渠道健康」指引落空 */
  renderPushChannels({channels:{}});
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
  /* roving 首格锚该渠道首个可交互格（首轮缺扫/maint 时 ri=0 是
     .hc none 无 tabindex——按轮位锚会让该渠道族零 Tab 停靠点） */
  const firstIdx=j.rounds.findIndex(r=>(r.plats||{})[p]);
   const cells=j.rounds.map((r,ri)=>{const c=(r.plats||{})[p];
   if(!c)return `<i class="hc none" title="${r.ts} 未扫描"></i>`;
   const det=c.s==='ok'?`成功 ${c.ok}/${c.tot}`:(c.note||SM[c.s]);
   return `<i class="hc ${c.s}" style="cursor:pointer" data-rv tabindex="${ri===firstIdx?0:-1}" role="button" aria-label="${r.ts} ${he(det)}" onclick="showLog('${p}','${r.ts}')" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();showLog('${p}','${r.ts}')}" title="${r.ts}｜${he(det)}（点击查看日志）"></i>`;}).join('');
  const cls=rate===null?'':(rate>=95?'ok':(rate>=80?'mid':'bad'));
  h+=`<div class="hrow"><span class="hlab"><span class="pdot ${p}"></span>${CN[p]||p}</span>`
   +`<span class="hcells" onkeydown="_roving(event,this)">${cells}</span>`
   +`<span class="hbadge ${cls}" title="近24h成功率 ${st.ok}/${att}${st.maint?'（维护 '+st.maint+' 轮）':''}">${rate===null?'—':rate+'%'}</span></div>`;}
 const rc=$('hroundcnt');
 if(rc)rc.textContent='近 24h 共 ' + j.rounds.length + ' 轮 · ';
 $('hbody').innerHTML=h;
 /* 滚动暗示：可滚才挂右缘渐隐类——静态渐隐会在
    恰好放下时不诚实裁切尾格；选择器含明细吸顶条（P1-W1） */
 document.querySelectorAll('.hcells,#montab-details .tabs,#montabs,#opscard .opsbtns,.tw').forEach(x=>
  x.classList.toggle('xhint',x.scrollWidth>x.clientWidth+4));
 renderPushChannels(j.push);}
/* 推送通道名映射（全局单源）：健康面板与推送记录小标同源消费；
   通道落账新 ch 名时此处补中文名（缺名兜底显英文 raw key） */
const CH_CN={'dingtalk':'钉钉','serverchan':'ServerChan','email':'邮件','urgent':'强提醒'};
/* 推送通道健康（j.push）：采集渠道之外的第二张脸——钉钉 -1 幽灵期
   邮件通道全绿时主推送面静默降级，逐条 ⚠️ 只在推送记录弹窗可见；
   通道级成功率/连败/最近成功时刻补齐这块盲区 */
function renderPushChannels(pj){
 const el=$('pushhl');if(!el)return;
 const keys=Object.keys((pj&&pj.channels)||{});
 /* 概览红帽第二点亮源：推送通道连败（红帽双源合成，见
    renderPulseAlert）——每轮全量重算，空通道列表自然清零 */
 let _streak=0;
 for(const k of keys)_streak=Math.max(_streak,((pj.channels[k]||{}).fail_streak||0));
 window._ovPushStreak=_streak;
 const _al=$('ovAlert');
 if(_al)_al.style.display=(_streak>0||(window._ovCollectFails||0)>0)?'':'none';
 if(!keys.length){el.innerHTML='<div class="muted" style="margin-top:10px">近 24h 无推送记录</div>';return;}
 el.innerHTML='<div class="pseclab">推送通道 · 近 24h</div>'+keys.map(k=>{const c=pj.channels[k];const att=c.ok+c.fail;
  const rate=att?Math.round(c.ok*100/att):null;
  const cls=rate===null?'':(rate>=95?'ok':(rate>=80?'mid':'bad'));
  return '<div class="hrow"><span class="hlab">'+(CH_CN[k]||he(k))+'</span>'
   +'<span class="pst '+(c.fail_streak>0?'bad':'ok')+'">'+(c.fail_streak>0?'连败 '+c.fail_streak:'正常')+'</span>'
   +'<span class="pmeta">成功 '+c.ok+'/'+att+' · 最近 '+he(c.last)+'</span>'
   +'<span class="hbadge '+cls+'" title="近24h推送成功率 '+c.ok+'/'+att+(c.last_ok?' · 最近成功 '+c.last_ok:'')+'">'+(rate===null?'—':rate+'%')+'</span></div>';}).join('');}
function he(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');}
/* 日期短标词面单源（MM-DD→MM/DD）：入参兼容 YYYY-MM-DD 与协议 MM-DD
   双形态——裸内联换装写法已全部收口进本函数（同簇双格式是词面漂移
   温床；新增日期短标消费点一律走 dSlash） */
function dSlash(d){const s=String(d==null?'':d);return s.length>=10?s.slice(5).replace('-','/'):s.replace('-','/');}
function chipsRefocus(id,build){
 /* 数据重建时键盘焦点恢复：重建前焦点在本容器子项上→重建后同序号
    子项回焦（表格行/表头走 data-k 先例，chips 是最后一处缺口——
    10s 轮询整组重建让停在 chip 上的键盘用户坠 body、Tab 从头再来）。
    重建后的新子项不带 tabindex（mkactAll 在本函数之后才补），
    span 不可聚焦 → focus() 静默 no-op——恢复前先 mkact 化当前子项
    （tabIndex=0+role=button，与 mkact 同形）再聚焦。
    容器隐藏/子项数变短时自然落空（焦点坠 body，与现状同）。 */
 const el=$(id);
 const idx=el?[...el.children].indexOf(document.activeElement):-1;
 build();
 const c=idx>=0?el.children[idx]:null;
 if(c){ if(!c.hasAttribute('tabindex')){
   c.tabIndex=0;c.setAttribute('role','button');}
   if(c.focus)c.focus();}}
/* 机场名+楼号展示（六批字段）：机场名剥「国际机场/机场」后缀
   （「虹桥国际机场」→「虹桥」，三字码 URC 无后缀原样），与楼号拼
   「虹桥T2」——楼号单独歧义（同城多场），全名太长 */
function _apt(s){s=String(s||'');return s.endsWith('国际机场')?s.slice(0,-4):(s.endsWith('机场')?s.slice(0,-2):s);}
function _tt(a,t){a=_apt(a);t=String(t||'');return (a&&t)?a+t:(a||t);}
/* 机场名+楼号+IATA 码旁注（depAirportCode/arrAirportCode 三源）：
   「虹桥T2 (SHA)」形。仅机场名含中文才注——qunar PC 源 depAirport 现状
   即三字码（城市码 SHA 与机场名双义冲突在案），名无中文或码与名义相同
   时不重复注（防「SHA (SHA)」） */
const _HAN=/[\u4e00-\u9fff]/;
function _ttc(a,t,c){const b=_tt(a,t);
 return (b&&c&&/^[A-Z]{3}$/.test(c)&&_HAN.test(a)&&c!==_apt(a))?b+' ('+c+')':b;}
/* ===== 健康格子点击：该轮该渠道日志原文（复用预览弹层） ===== */
/* 弹层在途取消与换代：_PV_SEQ 令牌统一两语义——Esc 取消与「立刻
   重新触发」都使旧请求令牌失配，迟到响应不得开层/覆盖新响应（单布
   尔取消标志会被新请求重置，被取消请求的迟到响应照样弹出；
   previewPush 生产构建 ~27s 是主要暴露面） */
let _PV_PENDING=false,_PV_SEQ=0;
async function showLog(p,ts){const _sq=++_PV_SEQ;_PV_PENDING=true;try{
 const r=await fetch('/api/logtail?plat='+p+'&ts='+encodeURIComponent(ts));
 if(_sq!==_PV_SEQ)return;
 const j=await r.json();if(!j.ok){toast(heFriendly(j.err)||'读取失败','err');return;}
 $('pvTitle').textContent='📄 '+( {'qunar':'去哪儿','fliggy':'飞猪','ctrip':'携程','tongcheng':'同程','tuniu':'途牛'}[p]||p )+'｜'+ts+' 轮日志';
 document.querySelector('#pvMask .pvcard').setAttribute('aria-label','渠道轮日志');
 $('pvFoot').textContent=(S&&S.demo)?'演示模式 · 合成轮日志回放':'轮日志为原文直读（非渲染预览）· 仅尾部 2MB 读取范围 · 完整日志见 logs/monitor.log';
 const lines=j.lines||[];
 $('pvBody').innerHTML=lines.length
  ?'<pre class="logpre">'+he(lines.join(String.fromCharCode(10)))+'</pre>'
  :'<div class="muted">该时间窗无日志（或已滚动出日志尾部 2MB 读取范围）</div>';
 _openPvMask();}catch(e){if(_sq===_PV_SEQ)toast('请求失败','err');}finally{if(_sq===_PV_SEQ)_PV_PENDING=false;}}
/* ===== 运行脉冲：/api/pulse（每轮每渠道行数/耗时，签派台脉搏） ===== */
let PU=null;
const PCN={'qunar':'去哪儿','fliggy':'飞猪','ctrip':'携程','tongcheng':'同程','tuniu':'途牛'};
async function pulse(){try{const r=await fetch('/api/pulse');
 const t=await r.text();if(t===PU)return;PU=t;renderPulse(JSON.parse(t));}catch(e){}}
/* pulse 失败静默论证：脉冲区属「有则显示」性质——
   失败时保持 display:none 即「无脉冲数据」的正确落点，非假等待；
   LESSONS 二十三要求每个异步终点显式论证落点，此处即论证 */
/* 红帽徽标：双源合成点亮（概览 tab 红点）——采集失败（pulse 轮
   写 _ovCollectFails）与推送通道连败（health 轮写 _ovPushStreak，
   钉钉 -1 幽灵期采集面全绿而达标推送静默丢失，红帽只挂采集失败时
   该故障零主动暴露）各写各的缓存、任一非零即亮：两轮询独立刷新
   互不覆盖，一方清零不得熄灭另一方的非零源 */
function renderPulseAlert(fails){window._ovCollectFails=fails||0;
 const el=$('ovAlert');
 if(el)el.style.display=((fails||0)>0||(window._ovPushStreak||0)>0)?'':'none';}
function renderPulse(j){if(!(S&&S.users&&S.users.length))return;/* 空配置守卫：删光用户后 10s 轮询不得复明 pulsecard（P2-4 回收的另一半——render 分支只封一拍，轮询每拍都会再点亮） */
 const rs=(j&&j.rounds)||[];
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
  cell('本轮采集',last.rows+' 条',he(last.ts)+' · <span class="nw">用时 '+last.dur+'s</span>')
 +cell('渠道成功率',rate==null?'—':rate+'%',
   '近 '+rs.length+' 轮 · '+failRounds+' 轮有失败',rate==null?'':(rate>=95?'ok':(rate>=80?'':'bad')))
 +cell('渠道均耗',avgLat==null?'—':avgLat+'s','单渠道平均抓取耗时')
 +cell('服务在线',up||'—',j.since?'自 '+j.since:'');
 /* 轮次堆叠柱：段=渠道，高=行数占比，红帽=该轮有渠道失败 */
 const maxRows=Math.max.apply(null,rs.map(r=>r.rows).concat([1]));
 $('pulsebars').innerHTML=rs.map((r,i)=>{
  const tip=he(r.ts)+' · '+r.rows+' 条 · '+r.dur+'s'
   +(r.fails?' · '+r.fails+' 渠道失败':'')
   +String.fromCharCode(10)+Object.keys(r.chans||{}).map(p=>{
    const c=r.chans[p];return (PCN[p]||p)+' '+(c.ok?c.rows+' 条':'无数据')+' · '+c.lat+'s';}).join(' · ');
  const rv=`data-rv tabindex="${i===0?0:-1}" aria-label="${he(r.ts)} 轮次，${r.rows} 条"`;
  const bad=Object.keys(r.chans||{}).filter(p=>!((r.chans[p]||{}).ok)).join(',');
  if(!r.rows)return `<div class="pbar zero" title="${tip}" role="button" ${rv} onclick="gotoPulseHealth('${r.ts}','${bad}')" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();gotoPulseHealth('${r.ts}','${bad}')}"><i></i></div>`;
  const segs=Object.keys(r.chans||{}).map(p=>{const c=r.chans[p];
   if(!c.rows)return'';
   return '<i class="seg pseg-'+p+'" style="height:'
    +Math.max(3,Math.round(c.rows/maxRows*100))+'%"></i>';}).join('');
  return `<div class="pbar" title="${tip}" role="button" ${rv} onclick="gotoPulseHealth('${r.ts}','${bad}')" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();gotoPulseHealth('${r.ts}','${bad}')}">${r.fails?'<i class="cap"></i>':''}${segs}</div>`;}).join('');
 $('pulseLegend').innerHTML=Object.keys(chans).map(p=>
  '<span><i class="pseg-'+p+'" style="width:12px;height:8px;border-radius:var(--r-xs);display:inline-block;vertical-align:middle;margin-right:5px"></i>'+(PCN[p]||p)+'</span>').join('')
 /* 审计 P2-5：红帽色票与渠道色票同规格（12×8 inline 方块），两种
    形制同排精细度参差 */
 +'<span><i style="background:var(--red);width:12px;height:8px;border-radius:var(--r-xs);display:inline-block;vertical-align:middle;margin-right:5px"></i>红帽 = 该轮有渠道失败</span>';
 renderPulseAlert(last.fails||0);}/* kbd 提示已常驻页脚，不再双份 */
/* ===== 价格日历热力卡：跟随当前走势航线 ===== */
function renderCal(){if(!S||!S.users.length)return;/* 状态未到不画 */
 const u=S.users[U];
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
  /* 指标胶囊 + 图例小字分层：曾 7 项混排一行 12px muted，决策指标与
     解码图例主次不分 */
  $('calStats').innerHTML='<span class="cs-i">近7天最低 <b>￥'+mn+'</b></span>'
   +'<span class="cs-i">日均 <b>￥'+avg+'</b></span>'
   +'<span class="cs-i">降价 <b>'+drops+'</b> 天</span>'
   +'<span class="cs-i">'+(cur<=mn?'当前即最低':'比最低高 <b>'+Math.round((cur/mn-1)*100)+'%</b>')+'</span>'
   /* 档位图例仅 th>0 拼接（r235 P2-1）：未设心理价永无档位色，
      图例空挂=装饰信号领先数据（二十三§6 族） */
   +((CR.r.th&&CR.r.th.direct)>0?'<span class="cs-lg">深绿=真达标 浅绿=行情破线 琥珀=擦边 <span style="white-space:nowrap">红=超线（格底）</span></span>':'');}
 else if((CR.r.th&&CR.r.th.direct)>0)$('calStats').innerHTML='<span class="cs-lg">深绿=真达标 浅绿=行情破线 琥珀=擦边 <span style="white-space:nowrap">红=超线（格底）</span></span>';
 else $('calStats').innerHTML='';
 if(!cal.length){$('calcard').style.display='none';return;}
 $('calcard').style.display='';
 const th=(CR.r.th&&CR.r.th.direct)||0;
 let mn=Infinity;for(const p of cal)if(p[1]>0&&p[1]<mn)mn=p[1];
 let h='';
 /* 档位底色运行时取语义变量（暗色随动）：曾硬编码亮色值——擦边旧琥珀
    (176,137,0)、超线旧红 (214,45,48) 均落后 加深后的
    --warn/--red，暗色下更深；达标绿也随主题换亮色 */
 const _rgbv=n=>{const m=/^#([0-9a-f]{6})$/i.exec(cssv(n)||'');
  return m?[parseInt(m[1].slice(0,2),16),parseInt(m[1].slice(2,4),16),parseInt(m[1].slice(4,6),16)]:null;};
 const CG=_rgbv('--green')||[14,131,69],CW=_rgbv('--warn')||[138,108,0],CRD=_rgbv('--red')||[194,42,46];
 /* 暗色 --green(#43c072) 高 alpha 浅底上白字仅 ~2.9:1（AA 需 4.5）：
    高 alpha 档改深字（--bg 同源），低 alpha 深底仍浅字；applyTheme
    重渲日历，DK 随主题刷新 */
 const DK=document.documentElement.dataset.theme==='dark',FGDK=cssv('--bg')||'#0a0f16';
 for(const cell of cal){const d=he(cell[0]),v=cell[1],q=cell[2];
  let bg='var(--rowalt)',fg='var(--mut)';
  if(v>0&&th>0){
   if(q===2){bg=DK?'rgba('+CG+',.88)':'rgb('+CG+')';fg=DK?FGDK:'#fff';}       /* 真达标（旗标）；bg 运行时实色（活变量曾让直接翻主题不重渲时白字衬亮绿 2.33 欠 AA），亮色实色底保白字 4.83:1 */
   else if(q===1){const r=v/th;                              /* 行情破线未达标（无旗标不标档，裸价回退已除） */
    const a=0.25+Math.min(0.28,(1-r)*2.2);                   /* alpha 上限 0.53（案结 + 修正：合成底真实衬底是 #calcard 的 --card(#101823) 非 --bg——a=0.56 时 --tx 仅 4.280、.cd/.cx 3.563 双欠，4.5 交点 a=0.5373 → 0.53 留余量恒达标；小字全档无税基线恒过 AA；FGDK 分支同期删除与超线档同构） */
    /* 底色同走 --green 变量（曾硬编码 46,164,79 亮色快照——
       三绿并存病灶残留，暗色不随动；与 CG 同源） */
    bg='rgba('+CG+','+a.toFixed(2)+')';
    fg='var(--tx)';}                                          /* 亮暗恒 --tx 与超线档同构（FGDK 分支删除） */
   else if(q===-1){                                          /* 擦边：最低价距达标线 ≤10% 未达标（价格数字琥珀高亮 .cp.near） */
    bg='rgba('+CW+',.30)';fg='var(--tx)';}
   else{const r=v/th;
    const a=0.16+Math.min(0.40,(r-1)*2.2);                   /* alpha 上限 0.56（0.60 时暗色最深格白字 4.39 欠 AA；0.76 时亮色白字最低 2.41） */
    /* 亮暗统一深/浅正文色 var(--tx)：暗色 FGDK 对暗红合成底 2.42~2.62
       曾倒退（实锤——0.60 档 alpha 的 FGDK 阈值只对绿底实色成立，
       红系 tint 全程不过线）；--tx 亮 5.22+/暗 5.70~6.97 双主题全过 */
    bg='rgba('+CRD+','+a.toFixed(2)+')';fg='var(--tx)';}}
  const best=v>0&&v===mn;
  const near=q===-1;
  const ds=dSlash(d);   /* 悬停词面与格面同源（格面已斜杠而 tip 仍裸横杠=同簇双格式） */
  const tip=v>0?(th>0?(q===2?ds+' 直飞最低 ￥'+v+' · 真达标（可出手）✅'
    :(v<=th?ds+' 直飞最低 ￥'+v+' · 行情破线，未必可出手 ⚠'
    :(q===-1?ds+' 直飞最低 ￥'+v+' · 擦边（距达标线 ≤'+NEAR_PCT+'%，未达标）'
    :ds+' 直飞最低 ￥'+v+' · 超线 '+Math.round((v/th-1)*100)+'%')))
   :ds+' 直飞最低 ￥'+v)+(best?' · 近期最低':''):(ds+' 无数据');
  h+='<div class="calcell'+(best?' best':'')+(q===2?' qhit':'')+'" style="background:'+bg+';color:'+fg+'" title="'+tip+'">'
   +'<div class="cd">'+dSlash(d)+'</div><div class="cp'+(near?' near':'')+'">'+(v>0?'￥'+v:'—')+'</div>'
   +'<div class="cx">'+(v>0?(best?'★ 最低':(mn<Infinity?'+￥'+(v-mn):'')):'')+'</div></div>';}
 $('calgrid').innerHTML=h;mkactAll();}
/* 日历格保持纯展示：格键=扫描观察日域（近 14 天窗），FLT.dates 过滤
   域=明细行出发日（未来出发窗）——两域一后向一前向恒不相交，格级
   点击跳明细恒为空过滤死通道（接线经真机证伪后维持收口；去该轮明细
   的活通道是走势 canvas 点击 jumpTrendDetail，其点键=完整出发日域，
   语义自洽）。无动作元素不加 role=button——假 affordance 比无
   affordance 更伤可达性预期 */
function jumpCalDate(d){if(!S||!S.users.length)return;/* 空态守卫纪律对齐 setRange/togChart 族 */
 showMonTab('details');
 resetFlt();FLT.dates=new Set([d]);/* 先 reset 再锁日期：dates 不被清 */
 const CR=curRoute();/* 多航线：卡 label 带 " MM/DD" 后缀，截掉再入 Set */
 if(S.users[U].routesArr&&S.users[U].routesArr.length>1)
  FLT.routes=new Set([CR.r.label.replace(/\s+\d{2}[/]\d{2}\s*$/,'')]);
 saveUI();buildChips();buildRouteChips();buildDateChips();table();
 /* 重置筛选显式告知（jumpQual/mchip 同族：resetFlt 清用户日期/
    渠道筛选是副作用，静默=「我点的日期怎么别的筛选没了」） */
 toast('已重置现有筛选，仅看该日期明细');
 /* 焦点交接：原视图隐藏后日历格/走势 canvas 的焦点坠 body，键盘用户
    失位（审计 P2-1）——落到明细 tab 钮上衔接 Tab 行进 */
 const el=document.querySelector('.mtab[data-t="details"]');
 if(el)el.focus();}
/* ===== 达标浏览器通知 + 提示音（开关持久化；按 航线+类别+价格 去重） ===== */
function jumpRowTrend(rt,d){if(!S||!S.users.length)return;/* 空态守卫纪律对齐 jumpCalDate 族 */
 const u=S.users[U];let st=CHR[u.name];
 if(typeof st==='number')st={i:st};st=st||{i:0};
 /* 明细行 route 无日期后缀、routesArr label 带 " MM/DD"——日期拼 full
    精确锚定（多航线多日期时首中即首个日期），失配回落前缀匹配；
    单航线（route 空）不设 i，跳过去即当前视图 */
 if(rt&&u.routesArr&&u.routesArr.length){
  const short=dSlash(d);
  const full=short?rt+' '+short:rt;
  let ix=u.routesArr.findIndex(r=>r.label===full);
  if(ix<0)ix=u.routesArr.findIndex(r=>r.label===rt||r.label.startsWith(rt+' '));
  if(ix>=0)st.i=ix;}
 CHR[u.name]=st;saveUI();gotoMonTab('trend');buildChartChips();
 /* 焦点交接（jumpCalDate 同律）：明细视图隐藏后
    行内 📈 的焦点坠 body——落到走势 tab 钮上衔接 Tab 行进 */
 const el=document.querySelector('.mtab[data-t="trend"]');
 if(el)el.focus();}
 /* chip 高亮须显式重建跟跳（togChart 1787 同律）：只 chart() 不重建时
    选中片停留旧路由 */
/* 走势数据点 → 该轮明细：系列=航线+出发日（点=扫描轮），跳明细锁出发日
   +多航线锁路由——jumpCalDate 同款联动路径，直接复用勿抄第二份；
   兜底系列（routesArr 缺席）无 date，静默不跳（承诺句也不会在场） */
function jumpTrendDetail(){if(!S||!S.users.length)return;/* 空态守卫纪律对齐 jumpCalDate 族 */
 const d=curRoute().r.date;
 if(d)jumpCalDate(d);}
/* 存储被禁（隐私模式等）时裸访问 localStorage 抛异常会中止整段脚本——
   降级默认值（通知关），页面其余功能不受累 */
let NT={on:false,ctx:null};
try{NT.on=localStorage.getItem('jpnotify')==='1';}catch(e){}
function ntIcon(){const b=$('ntBtn');if(!b)return;
 b.textContent=NT.on?'🔔':'🔕';
 b.title=NT.on?'达标浏览器通知已开启（点击关闭）':'达标时浏览器通知+提示音（点击开启）';
 b.setAttribute('aria-pressed',NT.on?'true':'false');}   /* 读屏播态：图标变而 aria 静默曾漏 */
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
    行情破线但约束不满足的班次不再误响（与钉钉侧 修复同因） */
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
async function previewPush(){const b=$('pvBtn');
 if(b.classList.contains('busy'))return;   /* busy 守卫：pointer-events 只挡指针，键盘 Enter 合成 click 照发（七件同族） */
 /* 锁宽须盖 busy 终态：min-width 是下限，busy 文案比首态宽时同排仍被
    挤一拍（r242 Soldier Minor-1）；量测必须在 add('busy') 之前——
    busy::after spinner 会撑大 offsetWidth 量值（+17px=11px 轮+6px 边距） */
 const _bw=b.style.minWidth;
 const _cs=getComputedStyle(b);
 const _m=document.createElement('span');
 _m.style.cssText='position:absolute;visibility:hidden;white-space:nowrap;font:'+_cs.font;
 _m.textContent='构建中 · 约需半分钟…';document.body.appendChild(_m);
 b.style.minWidth=Math.max(b.offsetWidth,_m.offsetWidth
   +parseFloat(_cs.paddingLeft)+parseFloat(_cs.paddingRight)+17)+'px';
 _m.remove();
 b.classList.add('busy');
 const _bl=b.textContent;b.textContent='构建中 · 约需半分钟…';   /* 慢路径时长预期：生产数据量 /api/preview ~27s，只挂 11px spinner 无文案，用户唯一合理反应就是认为坏了；文案随 busy 恢复（成功/失败同） */
 const _sq=++_PV_SEQ;_PV_PENDING=true;
 try{const r=await fetch('/api/preview',{method:'POST',
   headers:{'Content-Type':'application/json'},body:JSON.stringify({user:U})});
  if(_sq!==_PV_SEQ)return;   /* Esc 取消或已换代：构建完了也不开（busy 摘除走 finally） */
  const j=await r.json();
  if(!j.ok){toast(heFriendly(j.err)||'预览失败','err');return;}
  $('pvTitle').textContent=j.title;
  $('pvBody').innerHTML=renderDesp(j.desp);
  document.querySelector('#pvMask .pvcard').setAttribute('aria-label','钉钉推送预览');   /* 三入口全显式回设：showLog/pushLog 先开过会把静态值留在上一入口（P2-2）；底注同律三入口各回设 */
  $('pvFoot').innerHTML='本地近似渲染（标题/段落/加粗/链接/引用/进度条）· 明细总表图仅真实推送携带 · <span class="nw">以钉钉客户端实际效果为准</span>';
  _openPvMask();}
 catch(e){if(_sq===_PV_SEQ)toast('预览请求失败','err');}
 finally{if(_sq===_PV_SEQ)_PV_PENDING=false;b.classList.remove('busy');b.style.minWidth=_bw;b.textContent=_bl;}}   /* finally 兜底：!j.ok 提前 return 曾跳过 busy 摘除（按钮 pointer-events:none 卡死），本批随文案/锁宽还原一并收口 */
function closePv(){$('pvMask').classList.remove('on');
 /* 弹层开着背景曾可滚动/Tab 逃逸（无焦点管理）；锁滚+aria 轻量收口 */
 document.body.style.overflow='';
 document.body.style.paddingRight='';   /* 开层时滚动条宽度补偿同撤（gutter:stable 生效的浏览器该值为空串本就无操作） */
 /* 焦点归还开启者：Tab 曾继续在背景游走 */
 const ret=_PV_RETURN;_PV_RETURN=null;
 if(ret&&ret.focus)try{ret.focus();}catch(e){}}
let _PV_RETURN=null;
function _openPvMask(){_PV_RETURN=document.activeElement;
 /* 滚动条宽度补偿（老内核兜底）：锁滚摘视口滚动条会让内容整体横移
    （弹层开/关各跳一次=「点击闪烁不丝滑」的机械根因）。
    实测矩阵：无 gutter 锁滚 +5px 位移；scrollbar-gutter:stable 零位移；
    stable+补偿反而 -5px（补偿画蛇添足）——故支持 gutter 的现代内核
    走 CSS 零位移，仅老内核（不识别该属性）落 JS 垫宽补偿 */
 const _sw=(window.CSS&&CSS.supports&&CSS.supports('scrollbar-gutter','stable'))
  ?0:(window.innerWidth-document.documentElement.clientWidth);
 if(_sw>0)document.body.style.paddingRight=_sw+'px';
 const _m=$('pvMask');_m.classList.add('on');
 /* aria-modal 随 role="dialog" 静态挂 .pvcard（原挂在遮罩上，
    读屏按 role 定位 dialog 时拿不到语义） */
 document.body.style.overflow='hidden';
 /* 焦点进弹层关闭钮：键盘/读屏用户不再滞留背景。
     rAF 双帧赌「过渡起点已提交」不可靠——demo 秒开路径通过，
    但生产 /api/preview 真实慢路径（~27s 构建）双帧时刻 computed
    visibility 仍 hidden（maskVis:hidden maskOp:0），focus() 静默
    失败。须轮询 computed
    visibility/opacity 至弹层真正可见再移交：rAF 帧合保留（快路径
    1-2 帧即过，不回退 行为），3s 上限防长任务饿死轮询，
    弹层中途关闭（类摘除）即弃权不再 focus */
 const _t0=Date.now();
 const _fv=()=>{if(!_m.classList.contains('on'))return;
  const cs=getComputedStyle(_m);
  if(cs.visibility==='visible'&&parseFloat(cs.opacity||'0')>0){
   const x=$('pvClose');if(x)try{x.focus();}catch(e){}return;}
  if(Date.now()-_t0<3000)requestAnimationFrame(_fv);};
 requestAnimationFrame(_fv);}
/* ===== 推送记录：钉钉发送存档回看（点条目展开全文；display 切换零插拔） ===== */
async function pushLog(){const _sq=++_PV_SEQ;_PV_PENDING=true;try{
 const r=await fetch('/api/pushlog');
 if(_sq!==_PV_SEQ)return;
 const j=await r.json();
 if(!j.ok){toast(heFriendly(j.err)||'读取失败','err');return;}
 const items=j.items||[];
 $('pvTitle').textContent=items.length?('📨 推送记录（最近 '+items.length+' 条）'):'📨 暂无推送记录';
 document.querySelector('#pvMask .pvcard').setAttribute('aria-label','推送记录');
 $('pvFoot').textContent=(S&&S.demo)?'演示模式 · 合成推送记录回放':'推送历史本地存档回放 · 明细总表图以当时图床链接呈现（可能已过期）';
  $('pvBody').innerHTML=items.length?items.map(p=>
  `<div class="plitem${p.ok?'':' bad'}" onclick="const d=this.nextElementSibling;d.style.display=d.style.display==='none'?'':'none'">`+
  `<span>${p.ok?'✅':'⚠️'}</span><span style="flex:1">${he(p.title||'')}</span>`+
  `${p.ch?`<span class="plch">${he(CH_CN[p.ch]||p.ch)}</span>`:''}`+
  `${(!p.ok&&p.errcode!=null)?`<span class="plch" style="color:var(--warn)" title="通道错误码：-1=系统繁忙（幽灵送达——报错但消息可能已入群，勿据此判定未送达）；-2=未收到响应（网络异常轮也落账，便于发现断网）；其他码见通道文档">${he(String(p.errcode))}</span>`:''}`+
  `<span class="plts">${p.img?`<span title="部分推送图内嵌失败，邮件端该图保留外链（可能加载慢）" style="color:var(--warn)">${he(p.img)}</span> · `:''}${he(p.ts||'')}</span></div>`+
  `<div class="pldesp" style="display:none">${renderDesp(p.desp||'')}</div>`).join('')
  :'<div class="muted" style="padding:14px">还没有推送存档——每次发送自动记录在这里</div>';
 mkactAll();
 _openPvMask();}
 catch(e){if(_sq===_PV_SEQ)toast('请求失败','err');}
 finally{if(_sq===_PV_SEQ)_PV_PENDING=false;}}
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
     曾退化成裸段落「1. 🔥…」 */
  else if(/^- /.test(first)||/^\d+[.)] /.test(first))
   h+=`<div class="md-li">${bl.map(x=>mdInline(x)).join('<br>')}</div>`;
  else h+=`<div class="md-p">${bl.map(mdInline).join('<br>')}</div>`;}
 return h;}
/* ===== 移动端筛选抽屉 ===== */
function setFltOpen(open){/* 抽屉开合唯一入口：类切换+aria-expanded
   回写单源（审计 P2-2：Esc 关抽屉与 `/` 开抽屉两条旁路曾直改
   .open 类绕过状态同步点，读屏播报的展开态与真实状态相反） */
 const f=document.querySelector('.fbar');if(f)f.classList.toggle('open',open);
 const b=$('fltBtn');if(b)b.setAttribute('aria-expanded',open?'true':'false');
 /* ≤760 吸顶筛选条的抽屉在文档流原位展开（.fbar.open 在流形制
    全带同域）：深滚动位置点开时面板落在视口上方，且浏览器滚动
    锚定把展开撑高的内容位移抵消——用户视角=按钮无响应。开方向
    把面板顶拉到吸顶筛选条下缘（类切换后取实时几何，关方向不动）；
    宽档抽屉就在点按位旁，不干预 */
 if(open&&window.innerWidth<=760&&f&&f.classList.contains('open')){
  const tb=document.querySelector('#montab-details .tabs');
  const stick=tb?tb.getBoundingClientRect().bottom:0;
  /* vin 入场动画首帧 translateY 会让 getBoundingClientRect 虚高同值、
     scrollBy 少滚同值（抽屉顶缘压进吸顶条下缘、恒欠数 px）——量测前
     剔除 computed transform 的 ty 分量，量的是布局位真值 */
  const _tf=getComputedStyle(f).transform;
  let _dy=0;
  if(_tf&&_tf!=='none'){const _m=_tf.match(/matrix\(([^)]+)\)/);
   if(_m)_dy=parseFloat(_m[1].split(',')[5])||0;}
  const ftop=f.getBoundingClientRect().top-_dy;
  if(ftop<stick)window.scrollBy(0,ftop-stick);}}
function togFlt(){const f=document.querySelector('.fbar');
 setFltOpen(!(f&&f.classList.contains('open')));}
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
  if(FLT.routes.size&&FLT.routes.size<rs.length)n++;
  const ds=[...new Set(u.flights.map(f=>f.date).filter(Boolean))];
  if(FLT.dates.size&&FLT.dates.size<ds.length)n++;}catch(e){}   /* dates 全选=无筛选不计（与 plats/routes 守卫同构） */
 el.style.display=n?'':'none';el.textContent=n||'';}
$('tabs').onclick=e=>{if(e.target.dataset.f){
 document.querySelectorAll('#tabs span').forEach(s=>s.classList.remove('on'));
 e.target.classList.add('on');F=e.target.dataset.f;saveUI();table();tabAria();}};
/* ===== 下轮倒计时：到点自动拉一次新数据 ===== */
function setNext(t){NEXTRUN=t?new Date(String(t).replace(/-/g,'/')):null;TICKED=false;tick();}
/* #nextrun 状态迁移播报：timer 角色隐式 live=off（每秒静默
   是正确的，秒级播报是灾难）；读屏用户的事件感由 vh 盲文区在三个迁移点
   各播一次——首次可见/进入最后一分钟/切「扫描中」 */
let NR_STAGE='';
function nrSay(t){const el=$('nrLive');if(el&&el.textContent!==t)el.textContent=t;}
function tick(){const el=$('nextrun');if(!el)return;
 if(!NEXTRUN){el.style.display='none';NR_STAGE='';nrSay('');return;}
 const d=(NEXTRUN-new Date())/1000;
 el.style.display='';
 if(d<=0){const rt='🔄 扫描中…';if(el.textContent!==rt)el.textContent=rt;   /* 同值跳过（nrSay 律）：每秒重写=扫描窗内每秒一次 childList 脉冲 */
  el.classList.add('run');
  if(NR_STAGE!=='run'){NR_STAGE='run';nrSay('扫描进行中');}
  if(!TICKED){TICKED=true;setTimeout(load,4000);}return;}
 el.classList.remove('run');
 const m=Math.floor(d/60),s2=Math.floor(d%60);
 el.textContent='⏱ 下轮 '+NEXTRUN.toTimeString().slice(0,5)
  +'（'+(m>0?m+' 分 '+s2+' 秒':s2+' 秒')+'后）';
 if(NR_STAGE!=='last'&&NR_STAGE!=='run'){
  nrSay('距下一轮扫描 '+m+' 分 '+s2+' 秒');NR_STAGE='last';}
 else if(NR_STAGE==='last'&&m===0&&s2<=5){nrSay('即将开始扫描');NR_STAGE='fin';}}
restoreUI();mkactAll();
/* header 实高单源 --hdh：吸顶偏移原是固定像素（按 demo 无倒计时态
   校准），生产 ⏱ 倒计时 chip 折行使实高 72~134 漂移——固定值全带
   错位（768 实测吸顶条被盖 33px）。ResizeObserver 跟随折行/显隐
   变化实时写 CSS 变量，吸顶块与锚点补偿消费 var(--hdh)；JS 失效时
   CSS fallback 保现值零退化 */
(function(){const hd=document.getElementById('hdcard');
 if(!hd||!window.ResizeObserver)return;
 const set=()=>document.documentElement.style
  .setProperty('--hdh',hd.offsetHeight+'px');
 set();new ResizeObserver(set).observe(hd);})();
/* 明细吸顶筛选条实高单源 --tabsh：锚点补偿过「吸顶三件」
   （header+切换器+筛选条；非明细视图条隐藏 offsetHeight=0，
   补偿自动降档；JS 失效 CSS fallback 0px 回落原值零退化） */
(function(){const tb=document.querySelector('#montab-details .tabs');
 if(!tb||!window.ResizeObserver)return;
 const set=()=>document.documentElement.style
  .setProperty('--tabsh',tb.offsetHeight+'px');
 set();new ResizeObserver(set).observe(tb);})();
/* savebar 实高单源 --sbh：配置页垫底与 toast 抬升原按「单行 40/
   双行 112」两个校准态手分固定像素（文本缩放 150% 双行可破 112，
   全带错位）。savebar 恒在 DOM（display:flex 显隐走 translateY），
   ResizeObserver 跟随折行实时写变量；JS 失效各带 CSS fallback
   保旧校准值零退化 */
(function(){const sb=document.querySelector('.savebar');
 if(!sb||!window.ResizeObserver)return;
 const set=()=>document.documentElement.style
  .setProperty('--sbh',sb.offsetHeight+'px');
 set();new ResizeObserver(set).observe(sb);})();
/* 深链用户段恢复（restoreUI 之后——否则 localStorage U 覆盖 hash）：
   #tab/uN 形态，越界由 render 的 U 钳制自愈为 0（同 restoreUI 口径） */
try{const _h=location.hash.slice(1),_s=_h.indexOf('/u');
 if(_s>0){const _un=parseInt(_h.slice(_s+2),10);
  if(!isNaN(_un)&&_un>=0)U=Math.min(_un,99);}}catch(e){}
load();setInterval(load,10000);setInterval(tick,1000);
/* 明细表滚动续载：近底 600px 预取下一切片（passive 不阻塞滚动合成）。
   循环补齐至落点可见：End 键跳底/拖滚动条快滚只来一次事件，单片
   补法落点距真底数千 px（549 班实测 ~9100）需多按收敛；上限 4 片
   防超长表单帧长任务回潮，余量由后续惯性滚动事件接力。
   两容器互斥门（≤760 档 .tw 放开内滚、明细跟页滚）：.tw 侧桌面档
   独占——无纵向内滚时 scrollHeight==clientHeight，水平滚动的 scroll
   事件会伪真触发近底条件补片；页面侧窄档独占，动态查询放 handler 内
   （旋转跨档即时生效） */
document.querySelector('#tablecard .tw').addEventListener('scroll',function(){
 if(window.innerWidth<=760)return;
 if(!_ROWS||_NDRAW*_CHUNK>=_ROWS.length)return;
 let n=0;
 while(n<4&&_NDRAW*_CHUNK<_ROWS.length&&
    this.scrollTop+this.clientHeight>this.scrollHeight-600){
  _tblAppend();n++;}
},{passive:true});
window.addEventListener('scroll',function(){
 if(window.innerWidth>760)return;
 if(!_ROWS||_NDRAW*_CHUNK>=_ROWS.length)return;
 if(!(window.innerHeight+window.scrollY>document.documentElement.scrollHeight-600))return;
 let n=0;
 while(n<4&&_NDRAW*_CHUNK<_ROWS.length&&_tblAppend()){n++;}
},{passive:true});
document.addEventListener('visibilitychange',()=>{if(!document.hidden)load();});
/* Esc 收起展开的同班比价行/改期窗口行 / 关闭推送预览弹层 */
document.addEventListener('keydown',e=>{if(e.key!=='Escape')return;
 if($('pvMask').classList.contains('on')){closePv();return;}
 /* 弹层在途（响应未回）：令牌递增取消之——用户已改主意，弹层可见
    前按 Esc 曾被无视、响应回来照样弹出（previewPush ~27s 构建期
    主要暴露面）；取消后立刻重触发的场景由 _PV_SEQ 换代语义一并覆盖 */
 if(_PV_PENDING){++_PV_SEQ;_PV_PENDING=false;return;}
 /* 移动筛选抽屉同收（Esc 须弹层、比价行、抽屉一并管，抽屉开着不得掉队） */
 const fb=document.querySelector('.fbar.open');
 if(fb){setFltOpen(false);return;}
 if(EXP){EXP=null;_hideXrows();_ariaOff();saveUI();}
 if(TGOPEN){TGOPEN=null;_hideXrows();_ariaOff();saveUI();}   /* Esc 收改期同律回写 .tg aria（_ariaOff 单源） */
 /* toast 通知条同收：关最新一条（err 驻留 5s，逐条点 ✕ 曾不跟手）。
    序在展开行之后：toast 只读即点即关，驻留期不得挡内容态回收
    （序在展开行前时 toast 分支 return，展开行要等 toast 自然消散） */
 const ts=document.querySelectorAll('#toasts .toast');if(ts.length){ts[ts.length-1].remove();}});
/* 弹层 Tab 焦点圈封口：pvBody 内 renderDesp 生成真实 <a>，
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
/* 快捷键：1/2 切视图 · R 立即扫描（两段确认，防手滑） · / 聚焦搜索
   输入类控件聚焦时不劫持按键 */
let RUNARM=0;
function keyRun(){const now=Date.now();
 if(now-RUNARM>3000){RUNARM=now;toast('⚠ 再按一次 R 确认立即扫描全部航线','');return;}
 RUNARM=0;
 fetch('/api/run',{method:'POST'}).then(r=>r.json()).then(j=>{
  toast(j.ok?'✅ 已触发，页面自动刷新':'❌ 失败: '+(j.err||''),j.ok?'ok':'err');load();})
  .catch(()=>toast('❌ 请求失败','err'));}
/* 分栏跳转收口：先切监控视图再选子栏——3/4/6 曾直调
   showMonTab，在配置视图按快捷键只翻转 #monview（display:none）内的
   子容器，页面毫无反应（快捷键 3-6 分栏的承诺未兑现） */
function gotoMonTab(t){if(VIEW!=='mon')switchView('mon');showMonTab(t);}
/* 脉冲柱带状态落地（审计 P2-2）：原「跳到区域」让 96 格窗口里的目标
   轮靠视觉二次扫描——失败渠道行辉光（class 切换零 childList 变更，
   扩展免疫同律；1.9s 自灭）+ 该轮时间片横滚居中。同步执行不包 rAF：
   showMonTab 的 display 切换同步生效（offsetLeft 读取自带 reflow），
   rAF 包装在后台标签页被节流暂停、回调永不执行（真机实锤）；
   轮次按 ts 前缀对齐（pulse 与健康卡 rounds 数量可不同，时刻是唯一
   稳定键）；bad 传失败渠道键列表，无失败轮仅定位不辉光 */
function gotoPulseHealth(ts,bad){
 gotoMonTab('health');
 let cell=null;
 document.querySelectorAll('#hbody .hrow').forEach(row=>{
  let hit=null;
  row.querySelectorAll('.hc').forEach(c=>{
   if(!hit&&(c.getAttribute('title')||'').indexOf(ts)===0)hit=c;});
  if(hit&&!cell)cell=hit;
  if(bad){bad.split(',').some(b=>{if(b&&row.querySelector('.pdot.'+b)){
   row.classList.remove('hflash');void row.offsetWidth;
   row.classList.add('hflash');
   setTimeout(()=>row.classList.remove('hflash'),1900);
   return true;}return false;});}});
 if(cell){const wrap=cell.parentElement;
  if(wrap&&wrap.scrollWidth>wrap.clientWidth+4)
   wrap.scrollLeft=Math.max(0,cell.offsetLeft-wrap.clientWidth/2);}}
/* 桌面窄窗 .hcells 横滚滚轮通道（审计 P3-3）：overflow-x:auto 容器
   纵向滚轮默认不动横滚、Shift+滚轮无可发现性——容器级 deltaY→
   scrollLeft 转写（仅当容器真横向可滚；宽屏放得下恒不抢滚轮）。
   委托挂恒存 document，innerHTML 重建子树不丢监听 */
document.addEventListener('wheel',function(ev){
 if(!ev.deltaY)return;
 const t=ev.target;
 if(!(t&&t.closest))return;
 const wrap=t.closest('.hcells');
 if(!wrap||wrap.scrollWidth<=wrap.clientWidth+4)return;
 ev.preventDefault();
 wrap.scrollLeft+=ev.deltaY;
},{passive:false});
/* 状态 pill 直达「仅达标」明细：看到达标→看谁达标的高频路径一步收口
   （resetFlt 先回全选清残留筛选，再切 🔥 档；高亮同步与 tabs onclick 同式） */
function jumpQual(){if(!S){toast('数据加载中，请稍候');return;}
 /* 空态守卫：pill 在顶栏恒可见（空态也渲染），users 空时无明细可跳
    （真值门放行曾致下游 buildChips 读 undefined 抛未捕获 TypeError）——
    按二分词面引到配置页 */
 if(!S.users||!S.users.length){
  toast(S.suspended&&S.suspended.length?'航线已全部停用，前往配置启用':'尚未配置航线，前往配置添加');
  switchView('cfg');return;}
 gotoMonTab('details');resetFlt();F='q';
 document.querySelectorAll('#tabs span').forEach(s=>s.classList.toggle('on',s.dataset.f===F));
 saveUI();table();
 /* 审计 P2-1：resetFlt 会静默清用户日期/渠道筛选——落地 toast 显式
    告知（title 同步声明副作用，两入口同律） */
 toast('已重置现有筛选，切至「仅达标」明细');
 /* 焦点交接（jumpCalDate 同律）：顶栏 pill 跳明细后
    原件隐藏，焦点落明细 tab 衔接 Tab 行进 */
 const el=document.querySelector('.mtab[data-t="details"]');
 if(el)el.focus();}
document.addEventListener('keydown',e=>{
 /* Ctrl/Cmd+S：配置页保存（原生拦截，非输入态也可用） */
 if((e.ctrlKey||e.metaKey)&&(e.key==='s'||e.key==='S')){
  if(VIEW!=='cfg')return;e.preventDefault();saveCfg();return;}
 /* P2-5：弹层开着按键打背景页——1/2/3-6/R// 全拦；R 两段
    确认=后台真触发全量扫描，必须挡（Esc/Tab 各有专属 handler 不经此） */
 if($('pvMask').classList.contains('on'))return;
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
   if(fb&&getComputedStyle(fb).display==='none')setFltOpen(true);
   const q=$('fq');if(q){q.focus();q.select();}},0);
  e.preventDefault();}
 else if(e.key==='r'||e.key==='R')keyRun();});
/* 配置未保存守卫：dirty 徽标 + 关闭/刷新页面前确认（防手滑丢配置；全局项同守） */
function cfgIsDirty(){return CFG&&(JSON.stringify(CFG)!==CFG_CLEAN
 ||JSON.stringify(GLB)!==GLB_CLEAN);}
 setInterval(()=>{
  const dirty=cfgIsDirty();   /* 监控页也算：navCfg 红点全局可见（切走仅一次性 toast 曾让脏态不可见） */
  const nb=$('navDirty');if(nb)nb.style.display=(dirty&&VIEW!=='cfg')?'':'none';
  const n=dirty?cfgDirtyCount():0;
  const sb=$('savebar');
  if(sb){sb.classList.toggle('on',dirty&&VIEW==='cfg');   /* 显隐走 .on 过渡类（display 恒 flex）。toggle 必须在视图早退之前——cfg 弄脏后切监控，浮条不回收就永久浮在监控页右下 */
   const st=$('saveTxt');if(st){const t=n+' 处未保存的修改';
    if(st.textContent!==t)st.textContent=t;}   /* 同值跳过：textContent 无条件重写=每 800ms 删+插文本节点的常驻 childList 脉冲（MutationObserver 扩展被持续唤醒，nrSay 同律） */}
  if(VIEW!=='cfg')return;   /* 监控页跳过 cfgDirty/用户卡 DOM 巡检 */
  const el=$('cfgDirty');if(el){el.style.display=dirty?'':'none';
   const ct='● '+n+' 处未保存的修改';
   if(el.textContent!==ct)el.textContent=ct;}
  /* 用户卡头各自的未保存标记（对比干净快照里的对应用户） */
  let cleanArr=null;
  try{cleanArr=JSON.parse(CFG_CLEAN||'[]');}catch(e){}
  if(!CFG)return;  /* loadCfg 异步窗口期：配置未到本轮跳过（竞态炸 forEach，uitest 实锤） */
  CFG.forEach((u,i)=>{const el=$('udirty-'+i);if(!el)return;
   const d=dirty&&(!cleanArr||!cleanArr[i]
    ||JSON.stringify(u)!==JSON.stringify(cleanArr[i]));
   /* 复位值必须显式 inline-block——空串回落样式表仍被
      .udirty{display:none} 压死，徽标自引入从未亮过（inline/inline-block
      在 .uhead2 flex 容器内同为块化，渲染无差） */
   el.style.display=d?'inline-block':'none';});
 },800);
function discardCfg(){loadCfg();toast('已放弃未保存的更改','ok')}
/* 配置面板化：左侧导航=视图切换器（同屏只显一个分区，告别长滚动）；
   display 切换零 DOM 插拔；搜索态临时展示全部分区（只含命中字段） */
let CFGPANEL='login';
function showCfgPanel(id,silent){CFGPANEL=id;
 /* 搜索态点导航=离开搜索模式：命中行残留隐藏 + cfgHits 陈旧文案
    曾让新面板大面积空白（面板化与搜索两条 display 控制线打架——
    十四§4 叠加面在导航路径漏了复位拍）。cfgFilter('') 的清空分支
    亦走此单源，防双份清单漂移 */
 if(CFGQ){cfgSearchClear();applyFolds();}
 document.querySelectorAll('#cfgnav .cnav').forEach(c=>
  {c.classList.toggle('on',c.dataset.p===id);
   c.setAttribute('aria-pressed',c.dataset.p===id?'true':'false');});
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
 clearTimeout(_rsT);_rsT=setTimeout(()=>{
  if(S&&S.users&&S.users.length)chart();
  /* P2-4：跨 1024 断点几何变化点重判健康格滚动暗示（showMonTab
     同式——量纲 affordance 挂「变得可见」与「几何变化」两类切换点）；
     明细吸顶条同批重判（P1-W1） */
  document.querySelectorAll('.hcells,#montab-details .tabs,#montabs,#opscard .opsbtns,.tw').forEach(x=>
   x.classList.toggle('xhint',x.scrollWidth>x.clientWidth+4));},200);});
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
 const b=$('themeBtn');if(b){b.textContent=THEMES[i][1];
  /* 三态件布尔 pressed 语义错：aria-label 带当前态名播报 */
  b.setAttribute('aria-label','界面主题（当前：'
   +(t==='auto'?'跟随系统':t==='light'?'亮色':'暗色')+'）');}
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
 const b=$('denBtn');if(b){b.title=d==='compact'?'密度：紧凑（点击切回舒适）':'密度：舒适（点击切换紧凑）';
  b.setAttribute('aria-pressed',d==='compact'?'true':'false');}}
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
 tabAria();   /* 切换点同步 aria-pressed（读屏播报选中视图） */
 const el=$(v==='mon'?'monview':'cfgview');
 el.classList.remove('viewin');void el.offsetWidth;el.classList.add('viewin');
 $('monview').style.display=v==='mon'?'':'none';
 $('cfgview').style.display=v==='cfg'?'':'none';
 try{history.replaceState(null,'',v==='mon'?'#mon':'#cfg')}catch(e){}   /* URL 深链同步 */
  if(v==='cfg'&&!CFG)loadCfg();
  if(v==='cfg')loadLogin();
  if(v==='mon'&&_from==='cfg'){
   /* cfg 停留期间数据变更：回程补一拍——chart() 对隐藏容器早退
      （offsetWidth=0），switchView 回程不补则走势陈旧到下一轮数据
      变化；hcells 同律（<1024 右缘渐隐提示失真，健康() 每拍重判
      兜底，此处消窗口期）；明细吸顶条同批（P1-W1） */
   if(MONTAB==='trend')chart();
   document.querySelectorAll('.hcells,#montab-details .tabs,#montabs,#opscard .opsbtns').forEach(x=>
    x.classList.toggle('xhint',x.scrollWidth>x.clientWidth+4));}
  if(_from!==v)window.scrollTo({top:0});}/* 大视图互切回顶；子栏切换不重置 */
/* URL 深链恢复视图：#cfg 直达配置（mon 为默认无需恢复；须置于 VIEW 声明
   之后——上方 tab 初始化块处 let 尚在 TDZ 不可调 switchView） */
try{if(location.hash.slice(1)==='cfg')switchView('cfg');}catch(e){}
/* ===== 渠道登录：弹窗登录 + 会话保存（免命令行） ===== */
const LOGIN_CN = {qunar:'去哪儿', ctrip:'携程', tongcheng:'同程',
 tuniu:'途牛', fliggy:'飞猪'};
const LOGIN_NEED = {qunar:'必须', ctrip:'必须', tongcheng:'建议',
 tuniu:'建议', fliggy:'无需'};
async function loadLogin(b){if(b&&b.classList.contains('busy'))return;
 if(b)b.classList.add('busy');   /* busy 即 pointer-events:none 物理挡双击 */
 const box=$('loginRows');if(!box){if(b)b.classList.remove('busy');return;}
 try{const r=await fetch('/api/login-state');const j=await r.json();
  if(!j.ok){box.innerHTML='<span class="muted">读取失败</span>';
   if(b)b.classList.remove('busy');return;}
  box.innerHTML='<div class="lggrid">'+Object.keys(j.plats).map(p=>{
   const s=j.plats[p];
   const btn=s.active
    ?`<button class="btn2" style="border-color:var(--green);color:var(--green)" onclick="loginFinish('${p}',this)">✅ 我已登录完成</button>`
    :`<button class="btn2" onclick="loginStart('${p}',this)">🔐 弹窗登录</button>`;
   return `<div class="lgcard${s.saved?' saved':''}${s.active?' active':''}">`
    +`<div class="lgname"><span class="lgdot${s.saved?' on':''}"></span>${LOGIN_CN[p]||p}</div>`
    +`<div class="lgsub">${LOGIN_NEED[p]||''}登录 · ${s.saved?'已有登录态':(s.active?'登录中…':'未登录')}</div>${btn}</div>`;
  }).join('')+'</div>';
 }catch(e){box.innerHTML='<span class="muted">读取失败</span>';}
 if(b)b.classList.remove('busy');}
async function loginStart(p,b){
 if(b&&b.classList.contains('busy'))return;   /* busy 守卫（同步双调曾 2 次 POST） */
 b.classList.add('busy');
 try{const r=await fetch('/api/login',{method:'POST',
  headers:{'Content-Type':'application/json'},
  body:JSON.stringify({platform:p})});
  const j=await r.json();
  if(j.ok)toast('🔐 '+(LOGIN_CN[p]||p)+' 登录窗口已弹出——请在窗口完成登录，回这里点「我已登录完成」','ok');   /* 渠道名走中文映射（登录卡同源，全站唯一英文裸键漏网口 r242 审计收口） */
  else toast(heFriendly(j.err)||'启动失败','err');
 }catch(e){toast('请求失败','err');}
 b.classList.remove('busy');setTimeout(loadLogin,400);}
async function loginFinish(p,b){if(b&&b.classList.contains('busy'))return;
 if(b)b.classList.add('busy');   /* busy 期第二击直接忽略（连点曾发
  两次 finish，第二击落「没有进行中的登录」错误 toast） */
 try{const r=await fetch('/api/login-finish',{method:'POST',
  headers:{'Content-Type':'application/json'},
  body:JSON.stringify({platform:p})});
  const j=await r.json();
  toast(j.ok?'✅ 会话已保存，下轮采集自动生效（无需重启）'
   :'⚠ '+(j.err||'操作失败'),j.ok?'ok':'err');
 }catch(e){toast('请求失败','err');}
 if(b)b.classList.remove('busy');
 loadLogin();}
let GLB={interval_minutes:30},GLB_CLEAN='';
async function loadCfg(){try{
 const r=await fetch('/api/config');const j=await r.json();
 if(!j||!Array.isArray(j.users))throw new Error('配置接口响应异常');   // 500 错误体当数据曾静默渲染「0 用户+出厂全局参数」假界面（importCfg 同律守卫）
 CFG=j.users||[];CITY=j.city||{};GLB=j.globals||{interval_minutes:30};
 CFG_CLEAN=JSON.stringify(CFG);GLB_CLEAN=JSON.stringify(GLB);
 $('citydl').innerHTML=Object.keys(CITY).map(c=>`<option value="${c}">`).join('');
 buildForm();
 /* 输入程序化命名：srow/glcell 行的标题 b 与输入
    无 for/id 包裹（模板串多处，逐行加 id 维护成本高）——渲染后统一
    aria-label 关联，一处后处理覆盖配置页全部行 */
 try{document.querySelectorAll('.srow,.glcell').forEach(r=>{
  const b=r.querySelector('.slab b,.slab2 b,.glab');if(!b)return;
  /* 双控件行（往返城市/心理价直中/免打扰两端/时段窗/阿里云 ID+Secret）
     第二枚曾对读屏无名（一行一输入假设，审计 P2-3）——全量
     挂行标题，多控件序号后缀区分 */
  const inps=r.querySelectorAll('input,select');
  inps.forEach((inp,i)=>{
   if(inp.getAttribute('aria-label'))return;
   inp.setAttribute('aria-label',b.textContent.trim()
    +(inps.length>1?' '+(i+1):''));});});}catch(e){}}catch(e){cfgErr('配置读取失败: '+e);
 const _cg=$('cfgglobals');if(_cg)_cg.innerHTML='<span class="muted">加载失败——服务未启动或请求异常，恢复后刷新页面</span>';}}   // cfgErr 双通道（cfgmsg+toast）：cfgmsg 挂 users 面板，非 users 页签下也必达；cfgglobals 错误态落点（r236 P2-1）：静态「加载中…」是首次成功前的占位，失败分支不写即永不到达（二十三§1）
/* P2-1：& 最先（防把后续实体再转一次）+ < >（配置值含尖括号
   曾吞标签破排版；数据源是本机 config/自导入文件，硬收自伤面） */
function esc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;')}
let OPEN_USER=0;
try{const _ou=JSON.parse(localStorage.getItem('jpcfguseropen'));
 if(typeof _ou==='number')OPEN_USER=_ou;}catch(e){}
function setOpenUser(v){OPEN_USER=v;
 try{localStorage.setItem('jpcfguseropen',JSON.stringify(v))}catch(e){}}
function buildForm(){if(!CFG)return;let h='',gh='';
 if(OPEN_USER>=CFG.length)OPEN_USER=CFG.length-1;   /* 槽值恢复越界钳回有效域（删用户/换配置后） */
 const _fae=document.activeElement,_fkid=(_fae&&_fae.id)?_fae.id:null;   /* 重建不丢键盘焦点：回车加日期等承诺通道连续录入不坠 body（render/table data-k 先例的 id 版） */
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
     +'<input'+((type==='text'||type==='ro')?' type="text"':' type="number"')+' id="'+id+'" value="'+val+'"'
     +(type==='ro'?' readonly style="color:var(--mut);font-size:14px"':'')
     +(type==='text'?' style="font-size:13px;font-weight:500"':'')
     +(unit?' style="width:100%;padding-right:40px"':'')
     +((type!=='text'&&type!=='ro')?' oninput="glbCheck(this)"':'')
     +' onchange="'+onch+'">'
     +(unit?'<span style="position:absolute;right:10px;top:50%;transform:translateY(-50%);'
       +'color:var(--mut);font-size:11px;pointer-events:none">'+unit+'</span>':'')
     +'</div><div class="gsub">'+sub+'</div>'
     +((type!=='text'&&type!=='ro')?'<div class="verr" id="'+id+'Err"></div>':''))
  +'</div>';
 const glsec=t=>'<div class="subsec">'+t+'</div>';   /* P2-A：与 .subsec 归一（字面样式同源，原内联缺 hairline 且 margin ±1px） */
 gh+=glsec('⏱ 调度 · 🔥 保存即热生效')
  +'<div class="glgrid">'
  +glcell('扫描周期','glbIv','GLB.interval_minutes=Math.max(5,parseInt(this.value)||30)',esc(GLB.interval_minutes),'5–720 · 改动即重排下一轮',null,'分钟')
  +glcell('随机扰动','glbJt','GLB.jitter_minutes=Math.max(0,parseInt(this.value)||0)',esc(GLB.jitter_minutes||0),'错峰防规律抓取',null,'分钟')
  +glcell('控制台端口','glbPort','GLB.port=Math.max(1024,parseInt(this.value)||8765)',esc(GLB.port||8765),'1024–65535 · 原地热切换')
  +glcell('监听地址','glbHost','GLB.host=this.value',esc(GLB.host||'127.0.0.1'),'127.0.0.1=仅本机；0.0.0.0=局域网可达（手机开推送详情）· ♻ 重启生效','text')
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
 h+='<div class="rline" style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">'
  +'<b style="flex:1;min-width:8em">👥 用户与航线配置<span style="white-space:nowrap">（'+CFG.length+' 个用户）</span></b>'
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
  const ih=u.notifier&&u.notifier.image_host||{};
  const nR=(u.routes||[]).length;
  const open=(OPEN_USER===i);
  h+='<div class="ucard" style="margin:10px 0;padding:0;overflow:hidden">'
   +'<div class="uhead2" role="button" data-u="'+i+'" aria-expanded="'+(open?'true':'false')+'" onclick="toggleUser(this)">'
   +'<span class="uava">'+esc((u.name||'?').slice(0,1))+'</span>'
   +'<b>'+esc(u.name)+'</b>'
   +'<span class="upill">'+nR+' 航线</span>'
   +'<span class="upill'+((u.notifier||{}).win_toast!==false?' ok':'')+'">🔔弹窗'+((u.notifier||{}).win_toast!==false?'开':'关')+'</span>'
   +'<span class="upill'+(dt.enabled?' ok':'')+'">'+(dt.enabled?'推送已启用':'推送未启用')+'</span>'
   +'<span class="upill warn udirty" id="udirty-'+i+'">● 未保存</span>'
   +'<span class="chev'+(open?' open':'')+'">▾</span></div>'
   +'<div style="'+(open?'padding:4px 16px 14px':'display:none')+'">';   /* 单标签三元——原双分支各写一份开标签，源码 div 开闭差虚高 1 */
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
   `+glab('B','监控渠道','PLATFORMS',(u.platforms||[]).length+' / 5 渠道')+`
   <div class="srow"><div class="slab"><b>监控渠道</b><div class="shint">点击切换采集渠道；携程需本机已建立登录态，其余开箱即用</div></div><div class="sctl" style="flex-wrap:wrap;justify-content:flex-end;max-width:60%">`+
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
    +`<button class="danger" onclick="delRoute(${i},${j},this)">✕ 删除</button></span></div>
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
    +`</span><input type="text" id="dpick-${i}-${j}" placeholder="如 2026-10-08" style="width:128px" onkeydown="if(event.key==='Enter')addDate(${i},${j})"><button class="btn2" title="日历选择" onclick="pickDate(${i},${j})">📅</button><input type="date" id="dreal-${i}-${j}" class="dreal" tabindex="-1"><button class="btn2" style="margin-right:0" onclick="addDate(${i},${j})">➕ 加日期</button></div></div>
   </div>`;});
   h+=`<button class="btn2 addrbtn" onclick="addRoute(${i})">➕ 添加航线</button>
   `+glab('D','通知渠道','CHANNELS',[
      dt.enabled?'钉钉✓':'钉钉×',
      ((u.notifier||{}).ntfy||{}).enabled?'ntfy✓':null,
      ((u.notifier||{}).aliyun||{}).enabled?'电话✓':null,
      ((u.notifier||{}).serverchan||{}).enabled?'微信✓':null,
      (ems(i).filter(e=>e.enabled).length?'邮件✓×'+ems(i).filter(e=>e.enabled).length:null)
     ].filter(Boolean).join(' · ')||'未配置任何渠道')+`
   <div class="chgrid">
   <div class="chcard${dt.enabled?' on':''}" data-ch="dingtalk"><div class="chhead" role="button" onclick="foldCh(this)"><span class="lgdot${dt.enabled?' on':''}"></span>钉钉机器人<span class="muted">${dt.enabled?'已启用':'未启用'}</span><span class="chev open" style="margin-left:auto">▾</span></div>
    <div class="srow"><div class="slab"><b>启用钉钉推送</b><div class="shint">关闭后该用户不再向此群推送</div></div><div class="sctl"><input type="checkbox" class="switch" ${dt.enabled?'checked':''} onchange="setDt(${i},'enabled',this.checked);chSync(this,${i},'dingtalk')"></div></div>
    <div class="srow"><div class="slab"><b>Webhook</b><div class="shint">群设置 → 智能群助手 → 自定义机器人获取</div></div><div class="sctl" style="flex:1;min-width:0"><input type="url" placeholder="https://oapi.dingtalk.com/robot/send?access_token=..." style="width:100%;text-align:left" value="${esc(dt.webhook||'')}" onchange="setDt(${i},'webhook',this.value)"></div></div>
    <div class="srow"><div class="slab"><b>加签密钥 SEC…</b><div class="shint">机器人安全设置选「加签」后获得</div></div><div class="sctl" style="flex:1;min-width:0"><input autocomplete="off" placeholder="SEC 开头的加签密钥" style="width:100%;text-align:left" value="${esc(dt.secret||'')}" onchange="setDt(${i},'secret',this.value)"></div></div>
    <div class="srow"><div class="slab"><b>达标 @ 手机号</b><div class="shint">达标推送时 @ 这个号码</div></div><div class="sctl"><input type="tel" placeholder="13800000000" style="width:140px" value="${esc(dt.at_mobile||'')}" onchange="setDt(${i},'at_mobile',this.value)"></div></div>
    <div class="srow"><div class="slab"><b>通路验证</b><div class="shint">发一条测试消息到群里，验证 Webhook 可用；凭据仅存本机 config.yaml</div></div><div class="sctl"><button class="btn2" onclick="testPush(${i},this)">🔔 测试推送（用表单当前值）</button></div></div>
   </div><!-- 此闭合标签必须保留：ntfy/aliyun/serverchan 三卡嵌进钉钉卡内部，foldCh 按 parentElement 取 ch 键——缺行会折一连藏三 -->
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
   ${ems(i).map((em,k)=>`
   <div class="chcard${em.enabled?' on':''}" data-ch="email${k}"><div class="chhead" role="button" onclick="foldCh(this)"><span class="lgdot${em.enabled?' on':''}"></span>邮件·${esc(em.user||'邮箱通道'+(k+1))}<span class="muted">${em.enabled?'已启用':'未启用'}</span><span class="chev open" style="margin-left:auto">▾</span></div>
    <div class="srow"><div class="slab"><b>启用此邮件通道</b><div class="shint">与钉钉/其他邮件通道并联（都发）；163/QQ 各配各的，自发自收互不依赖</div></div><div class="sctl"><input type="checkbox" class="switch" ${em.enabled?'checked':''} onchange="setEm(${i},${k},'enabled',this.checked);chSync(this,${i},'email${k}')"></div></div>
    <div class="srow"><div class="slab"><b>SMTP 服务器</b><div class="shint">163：网页版设置→POP3/SMTP→开启服务→获授权码；QQ 同理</div></div><div class="sctl" style="flex:1;min-width:0;flex-wrap:wrap;gap:6px"><span class="chip schip emhchip${(em.host||'smtp.163.com')!=='smtp.qq.com'?' on':''}" onclick="emHost(this,'smtp.163.com',${i},${k})">163</span><span class="chip schip emhchip${em.host==='smtp.qq.com'?' on':''}" onclick="emHost(this,'smtp.qq.com',${i},${k})">QQ</span><input class="emhost" placeholder="smtp.163.com" style="width:150px;text-align:left" value="${esc(em.host||'')}" onchange="setEm(${i},${k},'host',this.value)"></div></div>
    <div class="srow"><div class="slab"><b>端口（SSL）</b><div class="shint">465 = SMTP_SSL；host 留空默认 smtp.163.com</div></div><div class="sctl"><input type="number" style="width:80px" value="${esc(em.port||465)}" onchange="setEm(${i},${k},'port',parseInt(this.value)||465)"></div></div>
    <div class="srow"><div class="slab"><b>发件账号</b><div class="shint">完整邮箱地址；须与授权码同属一账号；填自己=自发自收，一个账号即可</div></div><div class="sctl" style="flex:1;min-width:0"><input placeholder="you@163.com" style="width:100%;text-align:left" value="${esc(em.user||'')}" onchange="setEm(${i},${k},'user',this.value);chSync(this,${i},'email${k}')"></div></div>
    <div class="srow"><div class="slab"><b>SMTP 授权码</b><div class="shint">非登录密码！邮箱设置开启 SMTP 后生成；凭据仅存本机 config.yaml</div></div><div class="sctl" style="flex:1;min-width:0"><input type="password" autocomplete="off" placeholder="16 位授权码" style="width:100%;text-align:left" value="${esc(em.password||'')}" onchange="setEm(${i},${k},'password',this.value)"></div></div>
    <div class="srow"><div class="slab"><b>收件邮箱</b><div class="shint">多个逗号分隔；填发件账号自己=自发自收；加家人邮箱即可同收</div></div><div class="sctl" style="flex:1;min-width:0"><input placeholder="you@163.com 或多个" style="width:100%;text-align:left" value="${esc(em.to||'')}" onchange="setEm(${i},${k},'to',this.value)"></div></div>
    <div class="srow"><div class="slab"><b>通路验证</b><div class="shint">真实发一封测试邮件（正文=控制台整页截图，与正式推送同形态），授权码对错一试便知</div></div><div class="sctl"><button class="btn2" onclick="testEm(${i},${k},this)">📩 测试邮件（用表单当前值）</button><button class="danger" style="margin-left:6px" onclick="delEm(${i},${k},this)">✕ 删除</button></div></div>
    <div class="hint">免费方案：163/QQ 邮箱网页版设置开启 SMTP 拿「授权码」即可。邮件正文=控制台整页截图直嵌（与网页 100% 同视觉），渲染失败自动降级纯文字。可添加多个邮箱通道并联发送。</div></div>`).join('')}
   <button class="btn2" onclick="addEm(${i})">➕ 添加邮箱通道</button>
   <div class="chcard ih-${ih.provider==='smms'?'smms':'free'}" data-ch="imghost"><div class="chhead" role="button" onclick="foldCh(this)"><span class="lgdot on"></span>推送图床<span class="muted">${ih.provider==='smms'?'sm.ms':'freeimage'}</span><span class="chev open" style="margin-left:auto">▾</span></div>
    <div class="srow"><div class="slab"><b>图床服务</b><div class="shint">推送图文里图片的存放处；钉钉图空白/裂图 = 当前图床拉不到，切这里换床</div></div><div class="sctl"><span class="chip schip ihchip${(ih.provider||'freeimage')!=='smms'?' on':''}" data-p="freeimage" onclick="setIh(${i},'provider','freeimage',this)">freeimage</span><span class="chip schip ihchip${ih.provider==='smms'?' on':''}" data-p="smms" onclick="setIh(${i},'provider','smms',this)">sm.ms</span></div></div>
    <div class="srow ih-token"><div class="slab"><b>sm.ms API Token</b><div class="shint">选 sm.ms 时必填；凭据仅存本机 config.yaml</div></div><div class="sctl" style="flex:1;min-width:0"><input type="password" autocomplete="off" placeholder="粘贴 sm.ms 的 API Token" style="width:100%;text-align:left" value="${esc(ih.token||'')}" onchange="setIh(${i},'token',this.value,this)"></div></div>
    <span class="srow"><span class="slab"><b>通路验证</b><span class="shint" style="display:block">传一张 1px 测试图，验证当前所选图床真实可上传（不走降级链，失败即如实报错）</span></span><span class="sctl"><button class="btn2" onclick="testImghost(${i},this)">🔍 测试上传（用表单当前值）</button></span></span>
    <span class="ihtest" id="ihtest-${i}" style="display:none"></span>
    <div class="hint">推送图片空白？免费注册 <a href="https://sm.ms" target="_blank" rel="noopener" style="color:var(--blue)">sm.ms</a>（邮箱验证）→ <a href="https://sm.ms/home/apitoken" target="_blank" rel="noopener" style="color:var(--blue)">直达 API Token 页</a> 复制 → 上面粘贴 → 保存即热生效（免重启）。freeimage 恢复后可随时切回。</div></div>
   </div>
   <button class="danger" onclick="delUser(${i},this)">✕ 删除用户 ${esc(u.name)}</button></div></div>`;});
 $('cfgform').innerHTML=h;
 $('cfgglobals').innerHTML=gh;
 applyFolds();mkactAll();   /* 折叠头（role=button）/日期片 ✕ 补键盘可达 */
 if(CFGQ)cfgFilter(CFGQ);
 if(_fkid){const _fe=document.getElementById(_fkid);if(_fe)_fe.focus({preventScroll:true});}}
/* ===== 子卡折叠：分区(A-D)/航线卡/通道卡 点击标题行收展。
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
 /* r257 P3-3：折叠头开合状态语义（grouplab/rhead/chhead 三类全走
    本单源，开合路径收敛于此一处） */
 h.setAttribute('aria-expanded',String(!hide));
 /* 折叠区键盘卫生：收起后内部可聚焦件退出 Tab 序（焦点不再回落
    BODY 形成连续空步）。原态以 data-tdx 记录（''=原生无属性态），
    展开时按原态恢复。 */
 body.forEach(b=>b.querySelectorAll('a[href],button,input,select,textarea,[tabindex]').forEach(el=>{
  if(hide){if(el.getAttribute('data-tdx')==null)
    el.setAttribute('data-tdx',el.hasAttribute('tabindex')?el.getAttribute('tabindex'):'');
   el.setAttribute('tabindex','-1');}
  else{const t=el.getAttribute('data-tdx');
   if(t!=null){if(t==='')el.removeAttribute('tabindex');else el.setAttribute('tabindex',t);
    el.removeAttribute('data-tdx');}}}));
 const c=h.querySelector('.chev');if(c)c.classList.toggle('open',!hide);}
function _isFolded(h){return _foldSibs(h).every(b=>b.style.display==='none');}
function foldSec(g){const body=_foldSibs(g);
 const hide=!_isFolded(g);
 _setFold(g,body,hide);
 FOLD.sec[g.dataset.sec]=hide;saveFold();}
function foldRoute(rh){const _t=_evtT();if(_t&&_t.closest('.danger,.rop'))return;
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
function expandFolds(){/* 搜索态临时全开，清空后 cfgSearchClear 还原。
   用户卡头也纳入：容器壳扫会按命中可见性强展折叠卡 body，头若不
   随动即「头报收起、内容却显示」的状态分裂——aria/chev 由 _setFold
   单源同步；显式单 body（手风琴卡结构，_foldSibs 会越过 ucard 边界）*/
 document.querySelectorAll('#cfgform .grouplab[data-sec],'
  +'#cfgform .rline .rhead,#cfgform .chcard .chhead').forEach(
  h=>_setFold(h,_foldSibs(h),false));
 document.querySelectorAll('#cfgform .uhead2').forEach(h=>{
  const b=h.nextElementSibling;if(b)_setFold(h,[b],false);});}
function toggleUser(h){/* 用户卡收展：纯 display 翻转，不重建表单（不跳滚动位） */
 const u=+h.dataset.u,body=h.nextElementSibling;
 const willOpen=(body.style.display==='none');
 if(willOpen&&OPEN_USER!==u&&OPEN_USER>=0){/* 手风琴：收起上一张展开卡 */
  const prev=document.querySelectorAll('#cfgform .ucard')[OPEN_USER];
  if(prev){const ph=prev.querySelector('.uhead2');
   if(ph&&ph.nextElementSibling)_setFold(ph,[ph.nextElementSibling],true);}}
 _setFold(h,[body],!willOpen);
 setOpenUser(willOpen?u:-1);}
function setN(i,k,v){CFG[i].notifier=CFG[i].notifier||{};CFG[i].notifier[k]=v;}
/* 无头开关文字联动 / 通道卡状态灯随启用联动 */
function glbHlChk(el){GLB.headless=el.checked;
 const t=$('glbHlTxt');if(t)t.textContent=el.checked?'后台静默采集':'弹窗可见调试';}
function chSync(el,i,key){const c=el.closest('.chcard');if(!c)return;
 /* 邮件卡真值在 notifier.emails[k]（多通道数组）：key 形如 email0，
    按单对象键直查恒 miss——勾选「启用此邮件通道」后卡片灯当场熄灭
   （配置值正确、推送正常、刷新恢复） */
 const en=key.indexOf('email')===0
  ? !!((((CFG[i].notifier||{}).emails)||[])[+key.slice(5)]||{}).enabled
  : !!(((CFG[i].notifier||{})[key]||{}).enabled);
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
/* 邮件通道多实例：emails 数组（每项=发件账号+收件人们，
   163/QQ 各配各的自发自收）；旧单对象 email 首次编辑时迁移进数组。
   enabled 由显式开关控制（暂停不丢配置——产品操作完整性定律） */
function ems(i){const n=(CFG[i].notifier=CFG[i].notifier||{});
 if(n.emails)return n.emails;
 return (n.email&&Object.keys(n.email).length)?[n.email]:[];}
function emMig(i){const n=(CFG[i].notifier=CFG[i].notifier||{});
 if(!n.emails){n.emails=(n.email&&Object.keys(n.email).length)?
  [n.email]:[];delete n.email;}
 return n.emails;}
function setEm(i,k,f,v){emMig(i)[k][f]=v;}
function addEm(i){emMig(i).push({enabled:false,host:'smtp.163.com',
 port:465,user:'',password:'',to:''});buildForm();}
function delEm(i,k,b){armConfirm(b||_evtT(),()=>{emMig(i).splice(k,1);buildForm();
 toast('已删除邮箱通道（保存后生效）','ok');});}
/* 快捷填值 chip（163/QQ）：填入本卡 host 输入框并同步存值 */
function emHost(b,v,i,k){const c=b.closest('.chcard');
 const inp=c.querySelector('.emhost');
 if(inp){inp.value=v;}
 setEm(i,k,'host',v);
 c.querySelectorAll('.emhchip').forEach(x=>x.classList.remove('on'));
 b.classList.add('on');}
async function testEm(i,k,b){if(b&&b.classList.contains('busy'))return;
 const em=ems(i)[k]||{};
 if(!(em.user||'').trim()||!(em.password||'').trim()){toast('❌ 请先填写发件账号和授权码','err');return;}
 if(!(em.to||'').trim()){toast('❌ 请先填写收件邮箱','err');return;}
 b.classList.add('busy');
 try{const r=await fetch('/api/test-email',{method:'POST',
  headers:{'Content-Type':'application/json'},
  body:JSON.stringify({host:em.host||'',port:em.port||465,user:em.user,
   password:em.password,to:em.to})});
  const j=await r.json();
  toast(j.ok?'📩 测试邮件已发出，请查收（注意垃圾箱）'
   :'❌ '+(j.err||'发送失败'),j.ok?'ok':'err');}
 catch(e){toast('❌ '+(/abort|timeout/i.test(String(e))
   ?'请求超时，请重试':'网络异常，请检查服务是否在运行'),'err');}
 b.classList.remove('busy');}
async function testToast(b){if(b&&b.classList.contains('busy'))return;
 b.classList.add('busy');
 try{const r=await fetch('/api/test-toast',{method:'POST'});
  const j=await r.json();
  toast(j.ok?'🔔 测试弹窗已发出——收到后点它验证直达详情':'❌ '+(j.err||'失败'),j.ok?'ok':'err');}
 catch(e){toast('❌ '+(/abort|timeout/i.test(String(e))
   ?'请求超时，请重试':'网络异常，请检查服务是否在运行'),'err');}
 b.classList.remove('busy');}
async function testNtfy(i,b){if(b&&b.classList.contains('busy'))return;
 const nt=(CFG[i].notifier||{}).ntfy||{};
 if(!(nt.topic||'').trim()){toast('❌ 请先填写 ntfy 主题','err');return;}
 b.classList.add('busy');
 try{const r=await fetch('/api/test-ntfy',{method:'POST',
  headers:{'Content-Type':'application/json'},
  body:JSON.stringify({topic:nt.topic,priority:nt.priority||5})});
  const j=await r.json();
  toast(j.ok?'🔔 测试已发到手机 ntfy，请查收':'❌ '+(j.err||'失败'),j.ok?'ok':'err');}
 catch(e){toast('❌ '+(/abort|timeout/i.test(String(e))
   ?'请求超时，请重试':'网络异常，请检查服务是否在运行'),'err');}
 b.classList.remove('busy');}
/* P1-1：图床通路测试——后端直调所选床上传函数（不走
   upload_chart 降级链，失败如实报错）；成功结果行出可点直链+toast */
async function testImghost(i,b){if(b&&b.classList.contains('busy'))return;
 const _ih=(CFG[i].notifier||{}).image_host||{};
 const p=(_ih.provider||'freeimage')==='smms'?'smms':'freeimage';
 if(p==='smms'&&!(_ih.token||'').trim()){toast('❌ 请先填写 sm.ms Token','err');return;}
 const res=$('ihtest-'+i);
 b.classList.add('busy');
 try{const r=await fetch('/api/test-imghost',{method:'POST',
  headers:{'Content-Type':'application/json'},
  body:JSON.stringify({provider:p,token:(_ih.token||'').trim()})});
  const j=await r.json();
  if(j.ok&&j.url){if(res){res.style.display='block';
   res.innerHTML='✅ 测试图已上传，直链：<a href="'+he(j.url)+'" target="_blank" rel="noopener" style="color:var(--blue)">'+he(j.url)+'</a>';}
   toast('✅ 图床通路正常，测试图直链见通道卡','ok');}
  else{if(res){res.style.display='block';
   res.innerHTML='<span style="color:var(--red)">❌ '+he(j.err||'上传失败')+'</span>';}
   toast('❌ '+(j.err||'上传失败'),'err');}}
 catch(e){toast('❌ '+(/abort|timeout/i.test(String(e))
   ?'请求超时，请重试':'网络异常，请检查服务是否在运行'),'err');}
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
/* 出发日期 chips：多日期是产品能力不是配置技巧（裸文本逗号分隔不可用——
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
function setIh(i,k,v,el){CFG[i].notifier=CFG[i].notifier||{};const ih=CFG[i].notifier.image_host=CFG[i].notifier.image_host||{};ih[k]=(''+v).trim();
 if(k!=='provider'&&el&&el.value!==ih[k])el.value=ih[k];   /* trim 回写：落盘已清洗，输入框不留尾随空格残影 */
 if(k==='provider'&&el){const c=el.closest('.chcard');if(c){
  c.classList.toggle('ih-free',ih.provider!=='smms');c.classList.toggle('ih-smms',ih.provider==='smms');
  c.querySelectorAll('.ihchip').forEach(x=>x.classList.toggle('on',x.dataset.p===ih.provider));
  const m=c.querySelector('.chhead .muted');if(m)m.textContent=ih.provider==='smms'?'sm.ms':'freeimage';}}}
async function testPush(i,b){b=b||_evtT();
 if(!b||b.classList.contains('busy'))return;
 const dt=CFG[i].notifier&&CFG[i].notifier.dingtalk||{};
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
function addUser(){setOpenUser(CFG.length);CFG.push({name:'新用户',routes:[{from:'SHA',from_name:'上海',to:'SYX',to_name:'三亚',dates:[defDate()],alert_direct:0,alert_transfer:0,transfer_arrival_max:'02:00'}],platforms:['qunar','fliggy','tongcheng','tuniu'],notifier:{digest:true,storm_repeat:3,win_toast:true,dingtalk:{enabled:false,webhook:'',secret:'',at_mobile:''}}});buildForm();
 flashEl(document.querySelectorAll('#cfgform .ucard')[CFG.length-1]);}
function delUser(i,b){armConfirm(b||_evtT(),()=>{CFG.splice(i,1);
 /* 展开态索引跟随前移：展开用户 2 时删用户 0，原 2 落索引 1——
    不调整则重建后错位卡片自动展开（展开的是没点过的用户） */
 if(OPEN_USER===i)setOpenUser(-1);else if(OPEN_USER>i)setOpenUser(OPEN_USER-1);
 buildForm();
 toast('已删除用户（保存后生效）','ok');});}
function addRoute(i){CFG[i].routes.push({from:'SHA',from_name:'上海',to:'HAK',to_name:'海口',dates:[defDate()],alert_direct:0,alert_transfer:0,transfer_arrival_max:'02:00'});
 FOLD.route[i+':'+(CFG[i].routes.length-1)]=false;/* 新航线自动展开 */
 buildForm();
 flashEl(document.querySelector('#cfgform .rline[data-rk="'+i+':'+(CFG[i].routes.length-1)+'"]'));}
function flashEl(el){if(!el)return;
 el.scrollIntoView({block:'start',behavior:'smooth'});
 el.classList.add('flash');setTimeout(()=>el.classList.remove('flash'),1500);}
function delRoute(i,j,b){armConfirm(b||_evtT(),()=>{
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
/* 配置即时校验单源表：glcell 数字项输入即校验（glbCheck），saveCfg
   复用同一张表——校验规则两处漂移曾是「保存才首错即停」的根因 */
const GLB_RANGES=[
 {id:'glbIv',min:5,max:720,label:'扫描周期须为 5-720 的整数分钟'},
 {id:'glbPort',min:1024,max:65535,label:'控制台端口须为 1024-65535'},
 {id:'glbTo',min:10,max:600,label:'采集超时须为 10-600 秒'},
 {id:'glbDn',min:0,max:120,label:'错峰延迟须为 0-120 秒',
  chk:()=>{const dn=parseInt($('glbDn').value),dx=parseInt($('glbDx').value);
   return (!isNaN(dn)&&!isNaN(dx)&&dn>dx)?'错峰延迟「自」须 ≤「至」':null;}},
 {id:'glbDx',min:0,max:120,label:'错峰延迟须为 0-120 秒',
  chk:()=>{const dn=parseInt($('glbDn').value),dx=parseInt($('glbDx').value);
   return (!isNaN(dn)&&!isNaN(dx)&&dn>dx)?'错峰延迟「自」须 ≤「至」':null;}}];
/* 输入即校验：越界标红边+行内提示（verr），改对即清；returnMsg=true
   返回错误消息供 saveCfg 复用（不打 UI）。空串不标红——onchange 的
   钳位兜底接管；错峰「自/至」互为联动键，一方改对时姊妹键同步重判 */
function glbCheck(el,returnMsg){const r=GLB_RANGES.find(x=>x.id===el.id);
 if(!r)return null;
 const errDiv=$(el.id+'Err');const v=el.value.trim();let m=null;
 if(v!==''){const n=parseInt(v);
  if(isNaN(n)||n<r.min||n>r.max)m=r.label;
  else if(r.chk)m=r.chk(el);}
 if(!returnMsg&&m==null){
  const twin=$(el.id==='glbDn'?'glbDx':'glbDn');
  if(twin&&twin.classList.contains('invalid'))glbCheck(twin);}
 if(errDiv){errDiv.textContent=m?'⚠ '+m:'';
  errDiv.style.display=m?'block':'none';}
 el.classList.toggle('invalid',!!m);
 return m;}
async function saveCfg(){
 if(!CFG){cfgErr('❌ 配置尚未载入，请稍候再保存');return;}
 // ：全局参数先校验（周期/端口），再逐用户校验
 // 全局参数校验走 GLB_RANGES 单源表（与输入即时校验同源）——校验
 // 输入框原始值，onch 钳位静默改值的越界输入同样拦下
 for(const r of GLB_RANGES){const el=$(r.id);
  const _m=el?glbCheck(el,true):null;
  if(_m){cfgErr('❌ '+_m);return;}}
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
   for(const k of ['alert_direct','alert_transfer']){
    const v=Number(r[k]);
    if(r[k]!==''&&r[k]!=null&&(isNaN(v)||v<0||v>99999)){
     cfgErr('❌ 阈值须为 0-99999 的数字');return;}}
   if(!/^\d{2}:\d{2}$/.test(r.transfer_arrival_max||'02:00')){
    $('cfgmsg').textContent='❌ 到达时刻应为 HH:MM：'+r.transfer_arrival_max;return;}}
  const dt=(u.notifier||{}).dingtalk||{};
  const _ih=(u.notifier||{}).image_host||{};
  if((_ih.provider||'')==='smms'&&!(_ih.token||'').trim()){
   cfgErr('❌ 图床选了 sm.ms 但 Token 为空——填入 Token 或切回 freeimage');return;}
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
/* ===== 配置搜索：字段级过滤（srow/rline 容器按可见子块收敛；
   buildForm 重建后按 CFGQ 重放，搜索状态不丢 ===== */
function cfgSearchClear(){/* 搜索态复位单源：CFGQ/输入框/命中计数/
   被过滤元素 display 全量还原（cfgFilter('') 清空分支与 showCfgPanel
   导航复位共享，清单两处手抄曾漂移风险收口） */
 CFGQ='';
 const si=$('cfgSearch');if(si)si.value='';
 const hi=$('cfgHits');if(hi)hi.textContent='';
 document.querySelectorAll(''
  +'#cfgview .glgrid>div,#cfgview .srow,#cfgview .rline,#cfgview .chcard,'
  +'#cfgview .frow,#cfgview .row,#cfgview .lgcard,'
  +'#cfgview .chgrid>button,#cfgview .ucard button.danger,'
  +'#cfgview .addrbtn,#cfgview .grouplab,#cfgview .uhead2,#cfgview .uhead,#cfgview .subsec,'
  +'#cfgview .cfpanel>.ucard,#cfgview #cfgform>.ucard,#cfgview #cfgform>.ucard>div')
  .forEach(el=>{el.style.display='';el.style.boxShadow='';});
 /* 用户卡手风琴态按 OPEN_USER 单源重写：容器族复位把折叠卡的
    body 包裹层一并 display=''，清空后须还原进搜索前的手风琴态——
    回写源不能是 aria-expanded：搜索态 expandFolds 已把全部卡头
    aria 改 true（按它回写=清空后全卡展开），OPEN_USER 是搜索态
    不触碰的开合权威；aria/chev/tabindex 由 _setFold 单源同步 */
 document.querySelectorAll('#cfgform .ucard').forEach((c,i)=>{
  const h=c.querySelector('.uhead2');if(!h)return;
  const b=h.nextElementSibling;if(!b)return;
  _setFold(h,[b],i!==OPEN_USER);});}
function cfgFilter(qraw){const q=(qraw||'').trim().toLowerCase();
 const hits=$('cfgHits');if(!q){cfgSearchClear();
  showCfgPanel(CFGPANEL,true);applyFolds();return;}
 /* 搜索态：全部分区临时可见（子卡临时全开），只留命中字段 */
 document.querySelectorAll('#cfgmain .cfpanel').forEach(p=>{p.style.display='';});
 expandFolds();
 let n=0;
 document.querySelectorAll(''
  +'#cfgview .glgrid>div,#cfgview .srow,#cfgview .lgcard,'
  +'#cfgview .chgrid>button,#cfgview .ucard button.danger,'
  +'#cfgview .addrbtn').forEach(d=>{
  /* 登录卡（.lgcard）并入字段级过滤——搜索态
     非命中登录卡整版滞留会把真命中顶出首屏（清空复位清单同步加）；
      动作件并入——受过滤收编，不得悬在空分区里（删除用户钮实际
     DOM 多包一层 div，旧版子代选择器恒不命中=死选择器，后代选择器
     收编——同时覆盖航线/邮箱通道的删除钮，同为删除类动作件语义
     一致；「添加航线」钮在折叠包裹层内同理，按专类收编） */
  const inputs=[...d.querySelectorAll('input')].map(i=>i.value).join(' ');
  const m=((d.textContent||'')+' '+inputs).toLowerCase().includes(q);
  /* 被 !important 藏住的行（图床 ih-free Token 行）命中也
     不计——inline display='' 压不过 !important，行仍隐形；计入会出
     「✓ 1 项匹配」却无高亮行的假命中（audit160 P2-1）。
     先清上一轮自己写入的 inline 再判：守卫无法区分 !important 隐藏
     与本函数上轮写下的普通 inline none——命中判定在前时，前轮被藏
     的行本轮即使命中也在复位前被 return，顺序查询第二轮起假零
     （清空路径全量复位才复活）。复位后仍 none=真 !important 档 */
  d.style.display='';
  if(m&&getComputedStyle(d).display==='none')return;
  d.style.display=m?'':'none';
  d.style.boxShadow=m?'0 0 0 2px '+cssv('--glow'):'';   /* 主题随动（曾钉亮色蓝，暗色下与 --glow 脱节） */
  if(m)n++;});
 document.querySelectorAll('#cfgview .frow,#cfgview .row').forEach(el=>{
  if(el.closest('.rline'))return;
  const m=(el.textContent||'').toLowerCase().includes(q);
  el.style.display=m?'':'none';if(m)n++;});
 document.querySelectorAll('#cfgview .rline,#cfgview .chcard').forEach(rl=>{
  /* 容器可见性随命中字段行（.srow，起的统一行类）——
     此处曾查早已不存在的 .tog，命中也整卡隐藏，搜索对用户航线分区失效。
      同律改 computed：!important 隐形行（图床 Token 行）不算可见。
      P2-7：.rhead 摘要行（三字码/日期）并入索引面——rhead 独命中
     整卡显示但不高亮行，boxShadow 打在 rline 上，计数进 cfgHits */
  const vis=Array.from(rl.querySelectorAll('.srow'))
   .some(d=>getComputedStyle(d).display!=='none');
  const rhm=!vis&&rl.classList.contains('rline')
   &&((rl.querySelector('.rhead')||{}).textContent||'').toLowerCase().includes(q);
  rl.style.display=(vis||rhm)?'':'none';
  /* 非空搜索间切换时清上一轮 rhm 光晕（旧值
     残留曾与新高亮并存现双圈；空查询路径本就有整体复位） */
  if(rhm){n++;rl.style.boxShadow='0 0 0 2px '+cssv('--glow');}
  else if(!vis)rl.style.boxShadow='';});
 /* 孤儿头隐藏：结构头（分区/用户卡/静态卡头/全局 subsec）随「其后
    最近的本分区可见内容行」显隐——命中集中于单面板时其余面板的头
    悬空=可点件漂浮的孤儿头（只随全页命中数 n 判定只覆盖 n=0 档）；
    沿 nextElementSibling 扫描至下一个结构头为止，遇任一可见内容行
    即在位。清空路径走 cfgSearchClear 同清单还原 */
 document.querySelectorAll('#cfgview .grouplab,#cfgview .uhead2,#cfgview .uhead,#cfgview .subsec').forEach(g=>{
  const ROWS='.srow,.glgrid>div,.frow,.row,.lgcard,.rline,.chcard';
  let keep=false,sib=g.nextElementSibling;
  while(sib&&!keep){
   if(/\b(grouplab|uhead2|uhead|subsec)\b/.test(sib.className||''))break;
   const rows=sib.matches(ROWS)?[sib]
    :Array.from(sib.querySelectorAll? sib.querySelectorAll(ROWS):[]);
   keep=rows.some(d=>getComputedStyle(d).display!=='none');
   sib=sib.nextElementSibling;}
  g.style.display=keep?'':'none';});
 /* 孤儿容器壳收尾扫（头级扫的下层）：结构头隐藏后，宿主容器链
    （面板卡壳/用户卡/用户卡 body 包裹层）子件全隐时 padding 独存
    成空白残影条——按「容器内是否存在可见内容」隐藏容器本体
    （头类与动作件计入 ROWS：头级 inline 已由孤儿头扫写对，动作件
    命中时其宿主容器不得被误隐）；命中面板恒有可见行不受扰；无内
    容结构的卡（空态引导）不参与防误杀。清空路径 cfgSearchClear
    同清单对称复位 */
 document.querySelectorAll('#cfgview .cfpanel>.ucard,#cfgview #cfgform>.ucard,#cfgview #cfgform>.ucard>div').forEach(c=>{
  const ROWS='.srow,.glgrid>div,.frow,.row,.lgcard,.rline,.chcard,.grouplab,.uhead2,.uhead,.subsec,.chgrid>button,.ucard button.danger,.addrbtn';
  const rows=Array.from(c.querySelectorAll(ROWS));
  if(!rows.length)return;
  c.style.display=rows.some(d=>getComputedStyle(d).display!=='none')?'':'none';});
 hits.textContent=n?('✓ '+n+' 项匹配'):'无匹配项';

}
/* ===== 配置导入/导出：本地 JSON 直拷（含钉钉等凭据，本机自管） ===== */
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
  CFG=j.users;GLB=j.globals||GLB;setOpenUser(0);
  /* P2-1：导入文件是不归一路径——dates 过 addDate 同款
     _normDate 归一（10-08 补年/斜杠换谱），非法项丢弃 */
  CFG.forEach(u=>(u.routes||[]).forEach(r=>{r.dates=(r.dates||[]).map(_normDate).filter(Boolean);}));
  buildForm();
  toast('📥 已导入 '+CFG.length+' 个用户——检查无误后点「保存并生效」','ok');}
  catch(e){toast('❌ 导入失败：'+e.message,'err');}
  inp.value='';};
 rd.readAsText(f,'utf-8');}
/* ===== 脏计数：叶子级 diff，savebar/徽标显示 N 处修改 ===== */
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


NOTIFY_PAGE = r"""<!DOCTYPE html>
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
 :root{--bg:#eceff4;--card:#ffffff;--tx:#141f2b;--mut:#5a6c7d;--line:#dde3ea;
       --line2:#cbd4de;--blue:#0b62d6;--green:#0e8345;--okbg:#e9f4ec;
       --ok-txt:#0b6e39;
       --at-bg:#ffd24d;--at-fg:#7a4b00;   /* @手机高亮双令牌（.md-at 消费）：与主站令牌区同值成对 */
       --okrgb:14,131,69; /* 绿档通道令牌（hitbar/hitpulse 消费）；暗色两块覆写随主站 #43c072 换谱 */
       --blue-rgb:11,98,214; /* 蓝 RGB 令牌：pillbd/pillbg/pillbh/pillbd2 消费，暗色随主站 #63a4f8 换谱 */
       --pillbd:rgba(var(--blue-rgb),.32);--pillbg:rgba(var(--blue-rgb),.07);
       --pillbh:rgba(var(--blue-rgb),.14);--pillbd2:rgba(var(--blue-rgb),.55);
       --num:"Cascadia Mono","Consolas","SF Mono","Menlo",monospace;--r:14px;
       --r3:9px;
       --r10:10px;--ls1:1px;--ls2:2px;
       --pill:999px} /* notify 独立页自带 :root 令牌区，--pill 须随 .md a 消费同步在册（P2-C 漏补则 CTA 圆角塌 0）；--mut/--r3 系 P2-D 在册对齐主站；--r10/--ls1/--ls2 随主站令牌区同步在册 */
 *{box-sizing:border-box}
 html{color-scheme:light}
 :root[data-theme="dark"]{color-scheme:dark;--bg:#0a0f16;--card:#101823;--tx:#dbe4ee;
   --mut:#7f92a6;--line:#1e2a3a;--line2:#2a3a50;--okbg:#12241a;--blue:#63a4f8;
   --green:#43c072;--ok-txt:#43c072;--okrgb:67,192,114;--blue-rgb:99,164,248;
   --pillbd:rgba(var(--blue-rgb),.5);--pillbg:rgba(var(--blue-rgb),.12);
   --pillbh:rgba(var(--blue-rgb),.22);--pillbd2:rgba(var(--blue-rgb),.75);
   --at-bg:rgba(255,210,77,.16);--at-fg:#ffd24d}   /* @手机高亮暗谱：降饱和暗底+原亮字（主站同值成对） */
 @media(prefers-color-scheme:dark){:root:not([data-theme=light]){color-scheme:dark;
   --bg:#0a0f16;--card:#101823;--tx:#dbe4ee;
   --mut:#7f92a6;--line:#1e2a3a;--line2:#2a3a50;--okbg:#12241a;--blue:#63a4f8;
   --green:#43c072;--ok-txt:#43c072;--okrgb:67,192,114;--blue-rgb:99,164,248;
   --pillbd:rgba(var(--blue-rgb),.5);--pillbg:rgba(var(--blue-rgb),.12);
   --pillbh:rgba(var(--blue-rgb),.22);--pillbd2:rgba(var(--blue-rgb),.75);
   --at-bg:rgba(255,210,77,.16);--at-fg:#ffd24d}}   /* @手机高亮暗谱：与上块同值成对 */
 body{font-family:"Segoe UI Variable Text","Segoe UI","Microsoft YaHei","PingFang SC",sans-serif;
      margin:0;background:var(--bg);color:var(--tx)}
 .top{display:flex;align-items:center;gap:10px;padding:12px 18px;background:var(--card);
      border-bottom:1px solid var(--line2);position:sticky;top:0;z-index:5}
 .logo{width:26px;height:26px;border-radius:var(--r3);background:var(--tx);color:var(--bg);
       display:inline-flex;align-items:center;justify-content:center;font-size:13px}
 .top b{font-size:12px;letter-spacing:var(--ls1);text-transform:uppercase}
 .wrap{max-width:680px;margin:0 auto;padding:22px 18px}
 .hitbar{display:flex;align-items:center;gap:10px;background:var(--okbg);
      border:1px solid rgba(var(--okrgb),.35);border-radius:var(--r10);padding:12px 16px;margin-bottom:16px}
      /* 圆角对齐主站 10px 容器瓦片档（12px 出圈档） */
 .hitbar b{color:var(--ok-txt);font-size:14px}   /* 绿字对绿底：--green 4.28:1 欠 AA → --ok-txt 亮 5.63/暗 6.98（主控台 P2-3 同案孪生页同步） */
 .hitbar.ok b::before{content:"";display:inline-block;width:8px;height:8px;border-radius:50%;
      background:var(--green);margin-right:8px;vertical-align:1px;
      animation:hitpulse 1.6s ease-in-out infinite}
 @keyframes hitpulse{0%,100%{box-shadow:0 0 0 0 rgba(var(--okrgb),.4)}
      50%{box-shadow:0 0 0 5px rgba(var(--okrgb),0)}}
 .card{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:18px 22px}
 .md h1{font-size:19px;margin:6px 0 14px;line-height:1.5}
 .md .h2{font-size:15px;color:var(--blue);margin:16px 0 8px;font-weight:700}
 .md .h3{font-size:13px;margin:12px 0 6px;font-weight:700}
 .md p{margin:7px 0;line-height:1.85;font-size:14px}
 .md .md-at{background:var(--at-bg);color:var(--at-fg);border-radius:4px;padding:0 5px;font-weight:700}   /* 与主站 .pvbody .md-at 同谱（双主题令牌消费） */
 /* CTA 胶囊：落地页里所有链接都是动作（去下单/看详情），胶囊化提质感 */
 .md a{display:inline-block;color:var(--blue);text-decoration:none;font-weight:600;
      padding:5px 14px;margin:2px 6px 2px 0;border-radius:var(--pill);
      border:1px solid var(--pillbd);background:var(--pillbg);
      transition:background .15s,border-color .15s}
 .md a:hover{background:var(--pillbh);border-color:var(--pillbd2)}
 /* 触控地板：主站同位件（#foot a::after/.kpisum a）已外扩，轻页
    CTA/页脚链同族清点补齐（36px 基准——CTA 实高 29/页脚 17 均欠）。
    竖向外扩为主横向收敛（-4px < CTA 右距 6px，不互叠邻链接误触） */
 .md a,.foot a{position:relative}
 .md a::after,.foot a::after{content:'';position:absolute;inset:-10px -4px}
 /* --- 分隔线：渐隐 hairline（默认裸 hr 极廉价） */
 .md hr{border:none;height:1px;margin:14px 0;
       background:linear-gradient(90deg,transparent,var(--line2) 18%,var(--line2) 82%,transparent)}
 .md .g{letter-spacing:var(--ls2);font-size:15px}
 .md b{font-variant-numeric:tabular-nums}
 .md img{max-width:100%;border-radius:var(--r10);border:1px solid var(--line);display:block;margin:10px 0}
 .foot{margin-top:16px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px}
 .foot a{display:inline;color:var(--blue);font-size:13px;font-weight:400;
        padding:0;margin:0;border:none;background:none;text-decoration:none}
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
function esc(s){return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;")}
function inline(s){let t=esc(s)
 .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>')
 .replace(/@(\d[\d*]+)/g,'<span class="md-at">@$1</span>')
 const parts=t.split("**");let o=""
 for(let i=0;i<parts.length;i++)o+=(i%2)?"<b>"+parts[i]+"</b>":parts[i]
 return o}
const NL=String.fromCharCode(10)
const md=document.getElementById("md")
String(N.desp||"").split(NL).forEach(ln=>{
 const t=ln.trim()
 if(!t){return}
 if(t.indexOf("![")===0){const m=t.match(/\((https?:[^)]+)\)/)
  if(m){const im=document.createElement("img");im.src=m[1];md.appendChild(im)}return}
 if(t.indexOf("#### ")===0){const d=document.createElement("div");d.className="h3";d.innerHTML=inline(t.slice(5));md.appendChild(d);return}
 if(t.indexOf("### ")===0){const d=document.createElement("div");d.className="h3";d.innerHTML=inline(t.slice(4));md.appendChild(d);return}
 if(t.indexOf("## ")===0){const d=document.createElement("div");d.className="h2";d.innerHTML=inline(t.slice(3));md.appendChild(d);return}
 if(t.indexOf("# ")===0){const d=document.createElement("h1");d.innerHTML=inline(t.slice(2));md.appendChild(d);return}
 if(/^-{3,}$/.test(t)){const d=document.createElement("hr");md.appendChild(d);return}
 if(t.indexOf("> ")===0){const d=document.createElement("p");d.style.cssText="border-left:3px solid var(--blue);padding:4px 12px;margin:6px 0;color:var(--mut)";d.innerHTML=inline(t.slice(2));md.appendChild(d);return}
 if(/^[🟦🟩🟨⬜🟥]+$/.test(t.replace(/\s/g,""))){const d=document.createElement("div");d.className="g";d.textContent=t;md.appendChild(d);return}
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


def _test_email_launch() -> str:
    """测试邮件 launch：按配置 base_url 公网判定。
    独立模块级函数=执行级可测（曾内联三元表达式
    中变量名写错 NameError，被端点 except 吞成「发送失败」，源钉
    grep 抓不到执行错误）。"""
    from core.notifier import launch_is_public
    bu = str(((_State.cfg or {}).get("web") or {})
             .get("base_url", "") or "").strip()
    return bu if launch_is_public(bu) else ""


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


def _cluster_round_rows(rows, gap_s: int = 420):
    """按时间断口聚"轮"：倒序相邻行距 >gap_s 秒视为轮边界。

    一轮内多查询错峰完成跨 2-3 分钟、轮间隔 ~15 分钟——原"最新 1 分钟片"
    会切掉前几查询的明细。纯函数便于单测。
     收口 420s（观测收口：原 600s 曾把生产实测 483-503s 的相邻
    轮并桶——曲线桶取窗口内 min、列表 dedupe 取最新行，313 桶 6 桶
    口径分歧 1.9%（幅度 ≤￥253）；420 < 483 实测最小轮间隔，同轮改
    report._rounds 桶界（两套阈值曾 300/600 并存致「图有列无」——
    历史教训：两端必须同值）。轮内错峰跨 2-3 分钟仍同轮不受影响。
    语义刻意保持：曲线合并桶取窗口内最低价、列表 dedupe 只留最新行
    （最新快照语义）。"""
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


def _suspended_users(runtime_users, cfg_users):
    """停用态用户轻标记（停用态空态二分）：运行时 routes 空且配置
    同名用户名下航线全部 enabled=False 的用户。/api/state 用它区分
    「从未配置」（教学卡）与「已停用」（暂停卡+启用入口）两种空态——
    全停用用户在 states 过滤处被剔出（routes 空），不补此标记前端
    只能呈现教学卡，回归用户找心理线配置被误导。原始 routes 只从
    st.cfg 单一事实源取（热载安全，LESSONS 十二§1）；采集豁免层
    （main.build_routes）不动。"""
    cfg_by_name = {}
    for cu in cfg_users or []:
        if isinstance(cu, dict) and cu.get("name"):
            cfg_by_name[cu["name"]] = cu
    out = []
    for u in runtime_users or []:
        if not isinstance(u, dict) or u.get("routes"):
            continue
        cu = cfg_by_name.get(u.get("name") or "")
        if not cu:
            continue
        raw = [r for r in (cu.get("routes") or []) if isinstance(r, dict)]
        if not raw or any(r.get("enabled") is not False for r in raw):
            continue
        segs = []
        for r in raw:
            seg = (f"{r.get('from_name') or r.get('from', '')}"
                   f"→{r.get('to_name') or r.get('to', '')}")
            ds = [d for d in (r.get("dates") or []) if d]
            if ds:
                seg += f" {ds[0]}"
            segs.append(seg)
        out.append({
            "name": cu.get("name") or "",
            "n": len(raw),
            "routesTxt": "、".join(segs),
        })
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
    # 停用航线不进 routesArr/日历（日报 _chart_routes
    # 已滤对齐）：生产 cfg 路线是 dict（enabled:false 滤）、demo 是
    # Route 对象（无 enabled 字段，getattr 兜底不误杀）
    def _enabled(r):
        if isinstance(r, dict):
            return r.get("enabled") is not False
        return getattr(r, "enabled", True) is not False
    routes = [_route_view(r) for r in (u.get("routes") or [])
              if _enabled(r)]
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

    from core.models import PRICE_MIN, PRICE_MAX

    def _price_in_band(v):
        """列表端价格带兜底（与曲线 _rounds 同带单源 core.models
        PRICE_MIN/MAX）：曲线端有 _rounds 带过滤而列表端曾零防线——
        纵深不对称，爬虫端把关一旦回归即「列表可见、图上不可见」
        反向复演。两处 flights 收集点（当轮展开+近 6h 补位）同挂；
        非数值=False 宁缺勿错。"""
        try:
            return PRICE_MIN <= float(v) <= PRICE_MAX
        except (TypeError, ValueError):
            return False

    # 该用户关注的航线集合（明细/全线最低都只看自己航线）
    my_pairs = {(r["from"], r["to"]) for r in routes}
    rows = _cluster_round_rows(rows)
    # 跨渠道孤低价守卫·行级：FlightPrice 行=渠道最低价，幻影
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
                if isinstance(f, dict) and "price" in f and _price_in_band(f.get("price")):
                    g = dict(f)
                    g["_platform"] = r["platform"]
                    g["_pair"] = (r["from_city"], r["to_city"])
                    _fnorm(g, r["depart_date"] or "")
                    if g.get("_dep_mismatch"):
                        continue   # 渠道滚动行不入列表池（与推送/曲线同滤）
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
    from core.flightnorm import dep_mismatch as _dmm
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
                if isinstance(f, dict) and "price" in f and _price_in_band(f.get("price")):
                    if not Alerter._stale_sane(f):
                        continue
                    g = dict(f)
                    g["_platform"] = p
                    g["_stale_h"] = round(age, 1)
                    g["_pair"] = _k3
                    g["depDate"] = g.get("depDate") or _d0
                    if _dmm(g, _d0):
                        continue   # 渠道滚动行不入列表池（与推送/曲线同滤）
                    if _keep(g):
                        flights.append(g)
    except Exception:
        pass
    # 先全量归一化，再做同指纹衔接补全（qunar 列表页不渲染停留时长，
    # 同班次在携程测得的真实停留补到缺行——与聚合池同口径）
    from core.flightnorm import normalize as _fnorm_all, prate_txt
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
    # 跨渠道孤低价守卫·明细级（与告警池/走势池同一判定）：
    # 按 航线×日期×直/中 分组打 _xphan——明细行保留显示（原始保真）但
    # 永不判达标、不进行情最优/KPI（前端价格挂 ⚠ 角标）
    _fgrp = {}
    for f in flights:
        _fgrp.setdefault((f.get("_pair"), f.get("depDate", ""),
                          bool(f.get("transCity"))), []).append(f)
    for _g in _fgrp.values():
        Alerter._mark_xchan(_g)
    def _int_or_none(v):
        """int 协议键统一转写：渠道缺省空串/None/脏值
        → None（前端 !=null 门才干净）；非整数值（840.0 浮型）取整。"""
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    def _num_or_none(v):
        """float 协议键转写（_int_or_none 同型）：儿童票半价可出现
        X.5，int 取整会丢 5 角——数值即透传，脏值→None 不占位。"""
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

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
        # 多航线或多日期才带航线标签+📈 走势入口：单启用航线×多日期
        # （最常见形态）len(routes)>1 恒假曾让全表 route 为空、走势
        # 入口整表消失——多日期同样产生跳转歧义（跳哪天的图）
        rt_label = (f"{rr.get('from_name','')}→{rr.get('to_name','')}"
                    if len(routes) > 1
                    or len(rr.get("dates") or []) > 1 else "")
        thv = float(rr.get("alert_transfer" if transfer else "alert_direct", 0) or 0)
        # 明细行链接保持该行自身渠道（行价=该渠道报价，落点价=文案价）；
        # 同价跨渠道优选只做在概览 KPI 卡与推送链接（_pref_platform）
        view = _view_url(rr, f.get("depDate", ""),
                         f.get("_platform") or "")
        # 空/未知平台 _view_url 返回 ""（宁缺勿错，不出去哪儿挂羊头链）
        # 擦边：未达标但距线 10% 以内（表格琥珀提示，扫读一眼看出快到了）
        # 擦边带宽 NEAR_RATIO 已收口 core.alerter 单源
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
            "prate": prate_txt(f.get("prate")),
            "meal": str(f.get("meal") or "").strip(),
            # 托运额词面（「免费托运20KG」/「无免费托运」）：ctrip pid
            # 数字额与 qunar/tongcheng 既有 baggage 同键透传——全渠道
            # 行李词面在 WebUI 一并对等
            "baggage": (f.get("baggage") or "").strip(),
            # 手提额词面（「手提7KG·1件」，ctrip pid 孪生家族同门）
            "carryon": (f.get("carryon") or "").strip(),
            "shareCarrier": (f.get("shareCarrier") or "").strip(),
            # 共享承运航司名（qunar mainCarrierShortName，与 shareCarrier
            # 同门）：前端渲染门「共享·名+号」组合消费，CSV「实际承运」列
            "shareAirline": (f.get("shareAirline") or "").strip(),
            # 航司二字码（qunar shortCarrier/tuniu airlineIataCode 跨渠道
            # 统一出口，iata2 守卫在爬虫端）：CSV「航司码」列 + 搜索 hay
            "airlineCode": (f.get("airlineCode") or "").strip().upper(),
            # 航程公里（qunar distance，int 协议）：CSV「航程」列 +
            # 航班名格 title 注记（中转绕行程度参考）
            "distance": _int_or_none(f.get("distance")),
            # 舱位公布运价（tuniu bcTaxExclusiveFare，与所选价同
            # breakdown 配对）：CSV「公布运价」列（报销/里程累积口径）
            "stdFare": _num_or_none(f.get("stdFare")),
            "fewTicket": (f.get("fewTicket") or "").strip(),
            "depTerminal": (f.get("depTerminal") or "").strip(),
            "arrTerminal": (f.get("arrTerminal") or "").strip(),
            # 渠道字段三批透传（tongcheng 转机服务/航司中转文案，ctrip·qunar
            # 权益标签；trendGo=[[MM-DD,价],…] 仅挂 qunar/tongcheng/fliggy 当轮最低
            # 价行，点数与窗口随渠道——原样透传不做整形，前端空值不占位）。
            # 核实：qunar PC
            # 新采 transferService 与 tongcheng/ctrip 既有同名键同语义（中转
            # 服务权益文本），行到这里自动并入既有渲染位（中转 tag title）
            # 与 CSV「中转服务」列，零新增键
            "trendGo": f.get("trendGo"),
            # 改期日历节假日标注（tongcheng pc[].holidayName·tag，与
            # trendGo 同点同源同挂当轮最低价行）：[[MM-DD,词],…] 原样
            # 透传，改期窗口柱图 title 消费（「哪天便宜为什么便宜」
            # 解释变量）；其他渠道无源不落键
            "trendHoliday": f.get("trendHoliday"),
            # 高档舱改期日历价（tongcheng pc[].hlp，trendGo 同槽兄弟键
            # r254 翻案采入）：[[MM-DD,价],…] 同协议同挂当轮最低价行，
            # 柱图 title「公务￥X」附注 + CSV「改期公务」列；其他渠道
            # 无源不落键
            "trendBiz": f.get("trendBiz"),
            # 渠道字段十二批透传：fliggy 周边城市特价（J_Nearby 模块，
            # 两代 dump 在场）——[[日期,目的码,目的名,价,折扣词,公里数,
            # 锚城市],…] 已过爬虫端 _parse_nearby 逐点守卫（日期形/
            # iata3/价带/折扣词形），挂当轮 fliggy 最低价行（trendGo
            # 同槽同律，无值不落键）。消费端=航班名格 title 注记 + CSV
            # 「周边特价」列（明细次行段容量红线 14 已满不加段元素，
            # title/CSV 零布局风险——seatTilt 先例）；推送侧零改动
            "nearby": f.get("nearby"),
            # 渠道字段十三批透传：fliggy 往返程推荐（J_RoundRecommend
            # 模块，三代 dump 在场）——[[去程日期,返程日期,价,去程码,
            # 返程码],…] 已过爬虫端 _parse_round 逐点守卫（日期形/
            # iata3/价带/返程不早于去程），挂当轮 fliggy 最低价行
            # （trendGo/nearby 同槽第三兄弟，无值不落键）。消费端=
            # 航班名格 title 注记 + CSV「往返推荐」列（_nb_txt 零布局
            # 风险先例）；推送侧零改动
            "trendRound": f.get("trendRound"),
            # 中转二段出发日期（qunar transGoDate，跨天中转「二段哪天
            # 起飞」决策辨识信息——lay2dep 只有 HH:MM）：明细「二段 X
            # 起飞」渲染位拼 MM-DD 前缀，空串不占位同批内纪律
            "transGoDate": (f.get("transGoDate") or "").strip(),
            "transferService": (f.get("transferService") or "").strip(),
            "airlineTransfer": (f.get("airlineTransfer") or "").strip(),
            "labels": (f.get("labels") or "").strip(),
            # 渠道字段九批透传：qunar PC labels 适用条件说明
            # （「享受退改保护…」形，解释决策标签何时生效）——渲染挂
            # labels 既有 title 通道（'｜' 分隔同现状惯例），CSV +1 列
            # 「标签说明」；空串不占位同批内纪律
            "labelNote": (f.get("labelNote") or "").strip(),
            # 渠道字段四批透传：中转航站楼（qunar transInfo/
            # ctrip mutilstn，「咸阳T3」形）/ctrip 最低价政策余票数
            # int 1-10（None=无值不占位）。 核实：fliggy 新产
            # transTerminal、tongcheng 新采 leftTickets 与既有键同键同
            # 协议，白名单与渲染门渠道无关（明细次行「换乘·X」/「余N张」
            # 词面照常出），行到这里自动生效零改动
            "transTerminal": (f.get("transTerminal") or "").strip(),
            "leftTickets": f.get("leftTickets"),
            "avgDelay": avg_delay,
            # 渠道字段六批透传：中转出发楼（qunar secondDep
            # Info「正定T2」形，与 transTerminal 配对成换乘路径）+ 机场
            # 名（tuniu/tongcheng/fliggy 中文名、ctrip/qunar PC 三字码）
            # + 机型体量（「大型机/中型机/小型机」四渠道）+ 舱位代码
            # （tuniu 单舱位守卫后）
            "transDepTerminal": (f.get("transDepTerminal") or "").strip(),
            "depAirport": (f.get("depAirport") or "").strip(),
            "arrAirport": (f.get("arrAirport") or "").strip(),
            # 渠道字段十一批透传：机场 IATA 码（qunar H5 binfo
            # depAirportId 系/tuniu dPortIataCode/ctrip 原码三源，iata3
            # 守卫）——恒 3 大写字母 strip+upper 直通不做 int 转写，空串
            # 不占位同邻键；消费端 _ttc 机场中文旁注 + CSV「机场/航站楼」
            # 列并入（不加新列）+ 搜索 hay
            "depAirportCode": (f.get("depAirportCode") or "").strip().upper(),
            "arrAirportCode": (f.get("arrAirportCode") or "").strip().upper(),
            "planeSize": (f.get("planeSize") or "").strip(),
            "cabinCode": (f.get("cabinCode") or "").strip(),
            # 座椅倾斜角度（ctrip classinfor.seattilt，100~180°，
            # 0=未报爬虫端不落）：int 协议转写（七批先例）；渲染门=
            # cabinCode 悬停 title 注记 + CSV 列（明细次行段容量
            # 红线 14 已满不加段元素，title/CSV 零布局风险）
            "seatTilt": _int_or_none(f.get("seatTilt")),
            # 途牛儿童/婴儿价（渠道调研移交：爬虫已采、消费端补齐）：
            # float 协议（半价 X.5 不截断），渲染=航班名格 title 注记
            # + CSV「儿童/婴儿」列（次行段红线 14 已满不加段元素，
            # title/CSV 零布局风险——seatTilt 先例）
            "childPrice": _num_or_none(f.get("childPrice")),
            "infantPrice": _num_or_none(f.get("infantPrice")),
            # 渠道字段七批透传：廊桥率/取消率/公务舱价（int
            # 协议）、机龄 planeAge（str）、廉航旗标 lcc（normalize 派生
            # bool）—— ：爬虫缺省产出是空串非缺键（tongcheng
            # sts/ctrip extendinfos 未命中行），空串过 JS !=null 会渲染
            # 「·取消%」脏词面——复用 avgDelay 的 int→None 转写（
            # 先例），非数字一律 None 前端不占位
            "bridgeRate": _int_or_none(f.get("bridgeRate")),
            "cancelRate": _int_or_none(f.get("cancelRate")),
            "bizPrice": _int_or_none(f.get("bizPrice")),
            # 高档舱舱别词面（公务/头等，随 bizPrice 同源落键）——
            # CSV/title 词面随源，缺省由前端回退「公务」兼容存量行
            "bizCabin": f.get("bizCabin") or None,
            # 渠道字段八批透传：fliggy 中转行机建燃油合计
            # （int 协议 None 不占位，同上三键转写）——飞猪列表价裸价
            # 口径的补税提示，渲染位明细次行；只采+展示不接达标口径
            # （FLIGGY_TAX_PAD 归零定标，无配对样本证据不动比价）
            "transferTax": _int_or_none(f.get("transferTax")),
            "planeAge": f.get("planeAge") or None,
            "lcc": bool(f.get("lcc")),
            # tuniu 黑卡价透明标记（渠道调研 B）：选中价来自黑卡政策时
            # 爬虫落 blackCard=True，此处透传渲染门标「黑卡价」；不改
            # 选价口径（报文零文字性会员门标注，口径取证留 WATCH）
            "blackCard": bool(f.get("blackCard")),
            # qunar 退改费结构化双键（价位级决策字段）：int 协议
            # （_int_or_none 转写，-1「不可办理」如实保留非数字缺失
            # 归 None）；渲染=价格格徽标 + CSV「退改」列，词面单源
            # _rc_txt。推送 PNG 明细次行段容量红线 14 已满，推送侧
            # 零改动（退改从未进推送文本，不触「图≥文本」律）
            "returnFee": _int_or_none(f.get("returnFee")),
            "changeFee": _int_or_none(f.get("changeFee")),
            # ctrip 年龄限制专享价：最低价政策带 nt=20
            # 资格限制词面「限青年/限老年/限年龄/限学生/限携程会员/
            # 限航司会员」（并存「·」拼接）——该价非资格旅客误购无法
            # 出行，价格格 ⚠ 徽标（⚠+warn 与孤低价警告同语义族）
            "agePolicy": (f.get("agePolicy") or "").strip(),
            # ctrip 高风险政策透明标记：nt=104 报价条目与最低价同价
            # 条目 limitTag=HighRiskPolicy（价门精确到分+仅直飞）——
            # 渠道级购买风险提示，价格格 ⚠ 徽标（与 agePolicy 同
            # warn 语义族；词面不加「价」尾：它是政策风险标记不是
            # 资格价语义）
            "riskPolicy": (f.get("riskPolicy") or "").strip(),
            # qunar 值机时效风险警示（listPopView 弹层，双词面守卫在
            # 爬虫端）：「临近起飞需确认值机」固定词面，价格格 ⚠ 徽标
            # （agePolicy/riskPolicy 同 warn 语义族）——载体行 fewTicket/
            # labels/refundChange 全空时的行级唯一购买风险出口
            "ticketRisk": (f.get("ticketRisk") or "").strip(),
            # ctrip 诱饵价透明标记（nt=105 展示价 ∈ nt=104 渠道过滤
            # 清单=页面展示价不可购，点进必涨价；爬虫端已守卫 FP 互证
            # +背离 ≤5% 双门）——价格格 ⚠ 徽标（agePolicy/riskPolicy
            # 同 warn 语义族），防用户以渠道列表展示价比价后预期落空
            "lurePrice": _int_or_none(f.get("lurePrice")),
            "bagState": (f.get("transferBaggage") or "").strip(),
            # qunar PC 特惠产品权益（「航变免费改、20Kg免费行李」，稀疏；
            # 门不下发即孤儿键，PC 复活当日会静默丢失）
            "ptripNote": (f.get("ptripNote") or "").strip(),
            "layoverM": f.get("layoverM", 0),
            "layMin": int(rr.get("transfer_layover_min", 0) or 0),
            "lay2dep": (f.get("lay2dep") or ""),
            # 载荷卫生：飞行行 tam 曾为 56 键白名单
            # 唯一无消费键（前端 f.tam 零读取、CSV 无此列；「次日 HH:MM
            # 前到达」的 tam 消费全在 KPI best brief 的同名字段，见
            # _best_brief）——行级删键，brief 载体保留
            "bag": f.get("transferBaggage") == "direct",
            "stop": bool(f.get("stopover")),
            "stopCity": (f.get("stopCity") or "").strip(),
            "stopTimeT": (f.get("stopTimeT") or "").strip(),
            # 经停窗口绝对时刻（tuniu stopPoints 段时刻，词面直传）
            "stopWin": (f.get("stopWin") or "").strip(),
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
    # 同班比价离群旗标下发：与钉钉/总表图同一 Alerter._outlier
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
                "bagState": (f.get("transferBaggage") or "").strip(),
                "stop": bool(f.get("stopover")),
                "stopCity": (f.get("stopCity") or "").strip(),
                "stopTimeT": (f.get("stopTimeT") or "").strip(),
                "stopWin": (f.get("stopWin") or "").strip(),
                "plat": f.get("_platform", ""),
                "view_plat": view_plat,
                # 真实达标语义（与明细 qual 同源）：行情最低班未必能出手
                # （非直挂/衔接不足时 qual=False，KPI 卡不亮绿）
                "qual": _qual_of(f, bool(f.get("transCity")),
                                 round(float(f["price"]))),
                "stale": round(f["_stale_h"], 1) if f.get("_stale_h") else 0,
                "route": label, "view": view, "th": th_v,
                "tam": (rr.get("transfer_arrival_max", "02:00") or "02:00"),
                # 所属日期（delta 按日期精确匹配 routes_arr 用——单航线
                # 多日期时 route 为空串，label 匹配会错配首日期序列）
                "date": (f.get("depDate") or "")}

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
        1 行情破线但未达标、0 其余。组装不得丢弃 _rounds 的达标旗标，
        否则前端退化成「裸价≤线」画达标环——飞猪税前价/非直挂中转在图上虚画
        达标，与列表含义不一致（曲线口径收口）。"""
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
    # 多航线走势：每 (航线,日期) 一条序列，前端图上切着看（必须画全部，不许只画第一条）
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
                "date": d0,
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
    bbd_d = _best_by_date(directs)
    bbd_t = _best_by_date(oks)

    def _delta_vs_prev(brief, key, date=None):
        """较上轮涨跌：取最优航班所属航线的走势序列，倒数两点之差。
        序列末点即当前轮，倒数第二点为上轮（与推送的「较上轮」同源语义）。
        date 给定时按日期精确匹配 routes_arr 条目（多日期分组 KPI 用；
        label 匹配在单航线多日期时 route 为空串会错配到首日期序列）。"""
        if not brief:
            return None
        ser = None
        if date is not None:
            ser = next((r["history"][key] for r in routes_arr
                        if r.get("date") == date), None)
        if ser is None and brief.get("route"):
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
            "direct": bbd_d,
            "transfer": bbd_t,
        },
        # 过期监控日期（全部 dates < today）：sweep 已跳过期查询（渠道
        # 对过期查询滚动返回其他日期航班，照常落库=把别的日期的价挂进
        # 过期桶）——概览对过期日期渲染「已过期·停采」徽标，让「为何
        # 没数据」可自解释
        "expiredDates": [d for d in _dates_all
                         if d and d < datetime.now().strftime("%Y-%m-%d")],
        # 多日期分组 KPI 的「较上轮」按日期拆分：
        # dgroup 分支 delta 恒 null 曾让多日期航线概览无任何涨跌信息）；
        # 按日期精确匹配 routes_arr 条目，与单日期 delta 同源同语义
        "delta_by_date": {
            "direct": {d: _delta_vs_prev(b, "direct", d)
                       for d, b in bbd_d.items()},
            "transfer": {d: _delta_vs_prev(b, "transfer", d)
                         for d, b in bbd_t.items()},
        },
        "delta": {"direct": _delta_vs_prev(bd_brief, "direct",
                                           (bd_brief or {}).get("date")),
                  "transfer": _delta_vs_prev(xt_brief, "transfer",
                                             (xt_brief or {}).get("date"))},
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
_STATE_LOCK = threading.RLock()   # 可重入——同锁快照读取嵌套调 _latest_state
_STATE_BUILDING = {"on": False}

# ---- /api/state SWR 快照的磁盘副本 ----
# 冷启动首建分支是**同步**等待（见 _latest_state）：真机全量重算即便
# 从 222s 收到 ~26s，服务刚起时首个控制台请求仍要干等。把上一轮已
# 发布的快照落盘、首个请求时恢复，用户首屏立即拿到上次数据，后台再
# 按现行签名重建换新——stale-while-revalidate 的磁盘版，语义与内存
# 态一字不差（sig 对不上就自然落到既有 SWR 路径）。
_STATE_DISK_ONCE = {"on": False}      # 恢复只在首个请求做一次
_STATE_CACHE_TTL = 48 * 3600          # 超过则丢弃（不展示数天前价格）
_STATE_CACHE_MAGIC = b"TKMSTATE1\n"


def _state_cache_path():
    """快照文件路径（与库同目录、随库隔离）。不可解析返回 None。

    与 DB 同名加后缀：demo 模式的临时库天然落到系统临时目录，不污染
    仓库（跨次复用由版本/签名双守卫兜住，陈旧快照不会误展示）。"""
    try:
        db = _anchored((_State.cfg.get("output") or {}).get("db_path"),
                       "data/prices.db")
        d = os.path.dirname(os.path.abspath(db))
        return os.path.join(d, os.path.basename(db) + ".statecache")
    except Exception:
        return None


def _state_persist(sig, body, etag, gz):
    """发布快照后落盘（best-effort，任何异常静默）。

    单文件布局 `MAGIC + 4B(meta 长度) + meta + gz`，一次 os.replace
    原子换入。拆成 meta/body 两份文件会在中途崩溃时撕裂——body 已
    换新而 meta 仍旧，恢复出 body/etag 不配对的响应（轮询按新 etag
    落陈旧缓存被 304 粘死）。"""
    base = _state_cache_path()
    if not base or gz is None:
        return
    try:
        meta = json.dumps(
            {"sig": (list(sig) if sig is not None else None),
             "etag": etag or "", "ts": time.time(),
             # payload 结构随程序版本演进：跨版本快照一律不认（升版后
             # 首次请求慢一次，之后照旧毫秒级）——比前端拿旧结构渲染
             # 出空列安全
             "ver": str(_State.version or "")},
            ensure_ascii=False).encode("utf-8")
        tmp = base + ".tmp"
        with open(tmp, "wb") as f:
            f.write(_STATE_CACHE_MAGIC)
            f.write(len(meta).to_bytes(4, "big"))
            f.write(meta)
            f.write(gz)
        os.replace(tmp, base)
    except Exception:
        pass


def _state_restore():
    """从磁盘恢复上一轮快照（best-effort，坏文件一律静默丢弃）。

    恢复出的 sig 是**上一轮**的签名——与当前库不符时 _latest_state
    自然走既有的 SWR 路径（回旧值 + 后台重建），不需要任何新分支。"""
    base = _state_cache_path()
    if not base:
        return
    try:
        with open(base, "rb") as f:
            if f.read(len(_STATE_CACHE_MAGIC)) != _STATE_CACHE_MAGIC:
                return
            n = int.from_bytes(f.read(4), "big")
            meta = json.loads(f.read(n).decode("utf-8"))
            gz = f.read()
        if not gz:
            return
        if time.time() - float(meta.get("ts") or 0) > _STATE_CACHE_TTL:
            return
        if str(meta.get("ver") or "") != str(_State.version or ""):
            return          # 跨版本快照结构可能已变，不认
        body = gzip.decompress(gz)
        payload = json.loads(body.decode("utf-8"))
        sig = meta.get("sig")
        with _STATE_LOCK:
            if _STATE_CACHE["payload"] is not None:
                return          # 本进程已构建，活缓存优先
            _STATE_CACHE["payload"] = payload
            _STATE_CACHE["body"] = body
            _STATE_CACHE["etag"] = meta.get("etag") or ""
            _STATE_CACHE["gz"] = gz
            _STATE_CACHE["sig"] = tuple(sig) if sig else None
    except Exception:
        pass


def _state_restore_once():
    """首个 /api/state 请求前尝试恢复一次（热路径零重复 IO）。"""
    if _STATE_DISK_ONCE["on"]:
        return
    _STATE_DISK_ONCE["on"] = True
    _state_restore()


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
    """全量重建并写入缓存（payload/body/etag/gz 同批落位，永不出现半新半旧）。

    ：重活（全历史 extra JSON 逐条解析——现库体量实测 ~145s，
     时代的「11~14s」注释已过时）移到锁外做——异步重建线程若
    持锁构建，SWR 回旧值的请求会整体钉死在锁上（每轮扫描后控制台
    /api/state 假死 ~2.4 分钟的根因）；发布段收成同锁一次赋值，body/
    etag/gz 原子成对（撕裂修复语义不变）。并发双构建无害：
    单飞旗标已挡重入，即便穿透也是先完成者先发布、后完成者整体覆盖。"""
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
           "suspended": _suspended_users(users, st.cfg.get("users") or []),
           "next_run": _next_run(), "version": st.version,
           "demo": bool(DEMO["on"]),
           # 页脚「本地服务」实际监听地址（热切换/自定义 host 下页脚
           # 口径随实况；服务未起时留空）
           "svc": (("%s:%d" % _State.srv.server_address)
                   if getattr(_State, "srv", None) else "")}
    body = (json.dumps(out, ensure_ascii=False).encode("utf-8")
            if sig is not None else None)
    # ETag 随响应体一并缓存：轮询 304 路径零 hash 开销
    etag = ('"%s"' % hashlib.md5(body).hexdigest() if body else None)
    gz = (gzip.compress(body, 6) if body else None)
    with _STATE_LOCK:
        _STATE_CACHE["payload"] = out
        _STATE_CACHE["body"] = body
        _STATE_CACHE["etag"] = etag
        _STATE_CACHE["gz"] = gz
        _STATE_CACHE["sig"] = sig
    # 发布即落盘：下次进程重启时首个控制台请求能立刻命中（见
    # _state_persist/_state_restore）。异步重建路径在此锁外；同步
    # 兜底路径（_latest_state 直调）随外层 RLock 可重入无死锁
    _state_persist(sig, body, etag, gz)


def _state_rebuild_async():
    """后台单飞重建：构建中再多的请求/轮询也只触发一次重建。"""
    if _STATE_BUILDING["on"]:
        return
    _STATE_BUILDING["on"] = True

    def _run():
        try:
            # 构建移出锁外（见 _build_state docstring）——持锁
            # 构建曾把 SWR 回旧值的取锁路径一并钉死
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

    控制台每 10s 轮询本端点——轮间 DB 不变时不得全量重算
    （extra JSON 逐条解析 + 每航线×日期 走势/日历多查询）。配置摘要取
    users 的 JSON 哈希（Route 对象经 default=str 进 repr，阈值改动即换签），
    不用对象 id（CPython id 复用会让热重载后撞上旧签名返回脏缓存）。

    签名失效时分两路：有旧 payload → 立即回陈旧值 + 后台单飞重建
    （stale-while-revalidate，用户零等待，下一个轮询拿到新值）；进程后
    首建（无旧值可回）→ 触发同一单飞后台构建并轮询等待（构建
    在锁外做后，等锁改等旗标——持锁构建时代首请求会钉死全部并发请求）。"""
    _state_restore_once()   # 上一轮快照先顶上（先于签名比对：同签名连建都省）
    sig = _state_signature()
    if sig is not None and _STATE_CACHE["sig"] == sig:
        return _STATE_CACHE["payload"]
    if _STATE_CACHE["payload"] is not None:
        _state_rebuild_async()
        return _STATE_CACHE["payload"]
    # 冷启动首建：单飞后台构建 + 锁外轮询等待。等待绝不可发生在锁内：
    # 构建线程的发布段需要这把锁，持锁等待=互等死锁（CI uitest
    # 实锤：demo 首请求永挂）。此处已在无锁区（snap 端两段式，见下）
    _state_rebuild_async()
    deadline = time.time() + 300
    while _STATE_BUILDING["on"] and time.time() < deadline:
        time.sleep(0.2)
        if sig is not None and _STATE_CACHE["sig"] == sig:
            return _STATE_CACHE["payload"]
    with _STATE_LOCK:
        if sig is not None and _STATE_CACHE["sig"] == sig:
            return _STATE_CACHE["payload"]
        if _STATE_CACHE["payload"] is None:
            _build_state(sig)   # 后台线程异常兜底：缓存仍空则同步补建
        return _STATE_CACHE["payload"]


def _latest_state_snap():
    """/api/state 响应三元组 (body, etag, gz)：同锁内成对读取。

     两段式：先无锁调 _latest_state()（触发/等待重建——等待段
    绝不可持锁，否则与构建线程发布段互等死锁），再同锁一拍读取三元组。
    签名命中时连 json.dumps 都省掉（370KB 级载荷每次 dumps 要十几毫秒，
    轮询路径零序列化）。 的撕裂不变量保持：body/etag/gz 三元组
    仍在一个锁区内读齐——重建线程发布段同锁一次落位，读侧不会拿到旧
    body 配新 etag 下发 200（客户端按新 etag 落陈旧缓存被 304 粘死）。"""
    _latest_state()
    with _STATE_LOCK:
        body = _STATE_CACHE["body"]
        if body is None:
            body = json.dumps(_STATE_CACHE["payload"],
                              ensure_ascii=False).encode("utf-8")
        return (body, _STATE_CACHE.get("etag") or "",
                _STATE_CACHE.get("gz"))


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
        return {"ok": False, "err": "暂无本轮数据，先「立即扫描一轮」跑一轮"}
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
        # 逐日期独立成 entry（与生产 main.py 按查询日期逐条喂条的
        # 形状对齐）：曾把多日期价格并进一条产出单节「MM/DD-MM/DD」
        # +次日期 📍 mini 折行——预览≠实发的结构性差异（实发恒为
        # 逐日期独立全节），构建参考失真
        for d in rv["dates"]:
            prices = [FlightPrice(
                platform=row["platform"], from_city=row["from_city"],
                to_city=row["to_city"], depart_date=row["depart_date"],
                price=row["price"], extra=row["extra"],
                fetched_at=row["fetched_at"])
                for row in by_key.get((rv["from"], rv["to"], d), [])]
            if prices:
                secs = a._build_sections(route, prices)
                if secs:
                    built.append((route, secs))
    if not built:
        return {"ok": False, "err": "本轮数据为空"}
    # with_charts=False：预览无本轮走势图 URL，整段跳过走势块——
    # 缺图分支曾恒出假警告误导用户（词面已中性化「缺失」）；
    # with_tables=False 同理在 desp 尾补占位注——预览≠实发的结构性
    # 差异不标注，构建参考读者会误以为实发也无表
    p = a._digest_payload(built, fresh=True, with_tables=False,
                          with_charts=False)
    return {"ok": True, "title": p["title"],
            "desp": p["desp"] + "> （预览态无明细总表图，实发附整表PNG）\n\n",
            "hits": len(p["hits"]), "user": u.get("name", "")}


_HEALTH_CACHE = {"sig": None, "payload": None}


def _health_state(hours: int = 24) -> dict:
    """渠道健康时间线：解析 monitor.log（尾部 2MB 封顶，防长日志拖慢）。

    按 (monitor.log, push_history.jsonl) 双文件 (路径, mtime_ns, size)
    签名缓存——控制台每 10s 轮询，轮间双账本不变时不再重复解析；
    推送账本参与签名（推送轮更新不依赖 monitor.log，只锚日志会让
    通道健康滞后到下一扫描轮才刷新）。"""
    from core.health import parse_health
    logp = _anchored(((_State.cfg or {}).get("output") or {}).get(
        "log_path"), "logs/monitor.log")
    php = os.environ.get("PUSH_HISTORY_FILE") or os.path.join(
        "logs", "push_history.jsonl")
    parts = []
    for p in (logp, php):
        try:
            st = os.stat(p)
            parts.extend([p, st.st_mtime_ns, st.st_size])
        except OSError:
            pass
    sig = (tuple(parts), hours) if parts else None
    if sig is not None and _HEALTH_CACHE["sig"] == sig:
        return _HEALTH_CACHE["payload"]
    out = parse_health(_read_log_tail(), hours=hours)
    out["push"] = _push_channel_state(hours=hours)
    _HEALTH_CACHE["sig"], _HEALTH_CACHE["payload"] = sig, out
    return out


def _push_channel_state(hours: int = 24, tail_bytes: int = 262_144) -> dict:
    """推送通道健康：读推送账本尾部按通道聚合（只读消费，发送链路
    零触碰）。钉钉 -1 幽灵期邮件通道全绿时，主推送面在健康页不可见
    （逐条 ⚠️ 仅推送记录弹窗）——通道级 ok 率/连败补齐盲区。
    账本路径与写入面同源（PUSH_HISTORY_FILE 重定向同轨）；fail_streak
    =最后一条成功之后的连续失败数（升序尾长）。"""
    import json as _json
    from datetime import datetime as _dt, timedelta as _td
    path = os.environ.get("PUSH_HISTORY_FILE") or os.path.join(
        "logs", "push_history.jsonl")
    empty = {"channels": {}}
    try:
        with open(path, "rb") as f:
            size = f.seek(0, 2)
            f.seek(max(0, size - tail_bytes))
            raw = f.read().decode("utf-8", errors="ignore")
    except OSError:
        return empty
    lines = raw.splitlines()
    if lines and not lines[0].lstrip().startswith("{"):
        lines = lines[1:]   # 尾读切断的首半行丢弃
    chans: dict = {}
    t0 = _dt.now() - _td(hours=hours)
    for ln in lines:
        try:
            rec = _json.loads(ln)
        except ValueError:
            continue
        ch = rec.get("ch")
        if not ch:
            continue   # 旧账无通道字段，不入聚合
        try:
            ts = _dt.strptime(rec.get("ts", ""), "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            continue
        if ts < t0:
            continue
        c = chans.setdefault(ch, {"ok": 0, "fail": 0, "fail_streak": 0,
                                  "last": "", "last_ok": ""})
        ok = bool(rec.get("ok"))
        hm = ts.strftime("%m-%d %H:%M")
        c["ok" if ok else "fail"] += 1
        c["last"] = hm   # 升序遍历尾现=最近一条
        if ok:
            c["last_ok"] = hm   # 尾现=最近一次成功
            c["fail_streak"] = 0
        else:
            c["fail_streak"] += 1
    return {"channels": chans, "window_hours": hours}


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

    def handle_error(self, request, client_address):
        # 客户端中途断开（刷新/提前关闭/探针超时）会让写回炸
        # ConnectionReset/ConnectionAborted/BrokenPipe——socketserver
        # 默认逐条打 traceback 到 stderr，err 文件随使用刷屏（逐条
        # 定性全为断连噪音）。断连族静默；其余异常维持默认输出。
        if isinstance(sys.exc_info()[1], ConnectionError):
            return
        super().handle_error(request, client_address)


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
            body = _page_html(_State.version).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            # no-cache=每次导航必回源校验：升级重启后浏览器绝不拿旧
            # 页 JS（页面 本地秒回，无带宽顾虑；没有它启发式缓存会吐陈旧页面）
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
                    # desp 内「真达标/破线/擦边」为图例词面手抄样例——
                    # 与 alerter._legend_line/_TIER_TABLE 同源词面，改版
                    # 日须同轮同步（同步律；投影化因 desp 是静态演示
                    # 文本、不引 Python 侧依赖）
                    data = {"nid": "NDEMO",
                            "title": "🚨 达标 上海→乌鲁木齐 09/25",
                            "desp": "#### 🚨 已达标——可出手\n\n"
                                    "> ⏱09:00 🎯真达标 🟩破线 🟨擦边 超线\n\n"
                                    "[**🎯 直飞 ￥1468**](https://flight.qunar.com/site/oneway_list.htm?searchDepartureAirport=%E4%B8%8A%E6%B5%B7&searchArrivalAirport=%E4%B9%8C%E9%B2%81%E6%9C%A8%E9%BD%90&searchDepartureTime=2026-09-25&nextNDays=0&startSearch=true&fromCode=SHA&toCode=URC&from=flight_dom_search)"
                                    "　线￥1600　低￥132\n\n"
                                    "国航CA1295 21:10-02:35(+1天)\n\n"
                                    "> 经济舱 · 经停乌鲁木齐\n\n"
                                    "乌鲁木齐→上海 10/06 · 国航CA1295 21:10-02:35 +1天",
                            "ts": "（演示数据）"}
                elif nid:
                    p = _os.path.join(_ROOT, "data", "notify", nid + ".json")
                    if _os.path.isfile(p):
                        with open(p, encoding="utf-8") as _nf:
                            data = _j.load(_nf)
                else:
                    if _os.path.isdir(d):
                        for f in sorted(_os.listdir(d), reverse=True):
                            if f.endswith(".json"):
                                with open(_os.path.join(d, f),
                                          encoding="utf-8") as _nf:
                                    data = _j.load(_nf)
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
                # body/etag/gz 同锁快照一次取齐，304 判定不再撕裂
                body, etag, gz = _latest_state_snap()
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
                if "gzip" in (self.headers.get("Accept-Encoding") or "") and gz:
                    body = gz
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
                    # 样例与现役推送格式同步（#### 标题/四档图例「真达标」/
                    # 🎯-低-差口径、撤超线仪表条后行1=差价百分比）；旧
                    # 🟦超线 图例样例曾误导预览（随仪
                    # 表条撤除一并下架）
                    self._json({"ok": True, "items": [
                        {"ts": "2026-09-10 09:00:02", "ok": True,
                         "ch": "dingtalk",
                         "title": "🚨 达标！乌→上 10/04 直飞￥1580｜另监控 乌→上 10/05",
                         "desp": "#### 🚨 已达标——可出手\n\n"
                                 "> ⏱09:00 🎯真达标 🟩破线 🟨擦边 超线\n\n"
                                 "#### ✈️ 上海→乌鲁木齐 10/04\n\n"
                                 "[**🎯 直飞 ￥1580**](https://example.com)"
                                 "　线￥1600　低￥20·1%\n\n"
                                 "国航CA1295 21:10-02:35(+1天)\n\n"
                                 "> 经济舱 · 行李直挂\n\n"
                                 "> 💡 直飞 真达标 低￥20，建议出手\n\n"
                                 "> 📉 近7天 直飞 ↓3%"},
                        {"ts": "2026-09-10 08:45:03", "ok": True,
                         "ch": "email",
                         "title": "❌ 全部未达标｜最近 上→乌 09/25 直飞差￥570｜另监控 上→乌 09/26",
                         "desp": "#### ❌ 1 条航线 2 个日期全部未达标\n\n"
                                 "直飞 ￥2470　线￥1900　差￥570（30%）\n\n"},
                        {"ts": "2026-09-10 08:30:00", "ok": False,
                         "ch": "dingtalk",
                         "errcode": -1,
                         "title": "❌ 全部未达标｜上→乌 09/25",
                         "desp": "#### ❌ 1 条航线全部未达标\n\n"},
                        {"ts": "2026-09-10 08:15:00", "ok": False,
                         "ch": "dingtalk",
                         "errcode": -2,
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
                    # 演示模式不回读真实 config.yaml（webhook/secret 不落页面）。
                    # 航线/日期复用演示数据单源（core.demo.demo_routes 滚动
                    # 日期）——日期硬编码曾与演示数据脱节，配置页航线摘要
                    # 与监控/走势/明细各视图互相矛盾且随时间越来越旧；
                    # globals.port 随实际 --port（_State.cfg 由 demo_cfg 写入）
                    from core.demo import demo_routes as _demo_routes
                    self._json({
                        "users": [{
                            "name": "演示用户",
                            "routes": [
                                {"from": r["from"],
                                 "from_name": r["from_name"],
                                 "to": r["to"], "to_name": r["to_name"],
                                 "dates": r["dates"],
                                 "alert_direct": r["alert_direct"],
                                 "alert_transfer": r["alert_transfer"]}
                                for r in _demo_routes()],
                            "notifier": {"dingtalk": {"enabled": False},
                                         "win_toast": True},
                            "platforms": ["qunar", "ctrip", "fliggy",
                                          "tongcheng", "tuniu"],
                        }],
                        "city": {}, "demo": True,
                        "globals": {"interval_minutes": 15,
                                    "jitter_minutes": 5,
                                    "port": int((( _State.cfg or {})
                                                 .get("web") or {})
                                                .get("port", 8765) or 8765),
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
                with open(_State.config_path, encoding="utf-8") as _yf:
                    cfg = _y.safe_load(_yf)
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
                with open(st.config_path, encoding="utf-8") as _yf:
                    cfg = _y.safe_load(_yf) or {}
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
                # 采集参数：rt["cfg"] 单一事实源，保存热生效（起）
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
                # 签名缓存作废：签名五元组只含运行时 users 形态，cfg 派生
                # 键（suspended 等）在「只改停用航线配置」场景下 users 序列
                # 化逐字节不变，不作废则卡片文本陈旧到进程重启
                _STATE_CACHE["sig"] = None
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
                    # #### 纪律（# 级大标题喧宾夺主）+ 正文行 ≤40 半角
                    # （22 全角行手机窄屏折行断点不受控）
                    "#### ✅ 测试推送成功\n\n该钉钉机器人配置可用。\n\n"
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
        elif self.path == "/api/test-email":
            # 邮件通路测试：直调 EmailNotifier 用表单当前值
            # 真实发信——SMTP 授权码对错只有真发才知道（同图床/ntfy
            # 「测试必须如实报告通路死活」纪律）；正文即 HTML 正式形态
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                if not ((body.get("user") or "").strip()
                        and (body.get("password") or "").strip()):
                    self._json({"ok": False,
                                "err": "请先填写发件账号和授权码"})
                    return
                if not (body.get("to") or "").strip():
                    self._json({"ok": False, "err": "请先填写收件邮箱"})
                    return
                from core.notifier import EmailNotifier
                now = __import__('datetime').datetime.now().strftime(
                    '%H:%M:%S')
                ver = str(getattr(__import__("__main__"),
                                 "__version__", "") or "")
                # 测试邮件 = 正式形态（整套快照）：snapshot_base
                # 指向本控制台，渲染失败自动降级轻壳（通路优先于形态）
                host = self.headers.get("Host") or "127.0.0.1:8765"
                n = EmailNotifier(
                    host=str(body.get("host") or ""),
                    port=int(body.get("port") or 465),
                    user=str(body.get("user") or ""),
                    password=str(body.get("password") or ""),
                    to=str(body.get("to") or ""),
                    logger=st.logger,
                    snapshot_base="http://%s/" % host)
                desp = ("#### 📸 测试邮件——通路正常（控制台整页截图）\n\n"
                        "正文即正式推送形态：控制台整页截图直嵌，KPI/走势/"
                        "明细与网页 100% 同视觉。\n\n"
                        "> 版本 v%s ｜ ⏰ %s\n\n"
                        "- 截图渲染失败自动降级纯文字轻壳，通路不受影响"
                        % (ver or "?", now))
                ok = n.send("✅ 机票监控｜邮件通路测试", desp,
                            # launch 与主路径同律（回环
                            # base_url 异机必死链，按钮/页脚指引两态联动）；
                            # snapshot_base 回环合法（快照服务端本机渲染）
                            launch=_test_email_launch())
                self._json({"ok": bool(ok),
                            "err": (getattr(n, "last_err", "")
                                    or "发送失败（详见监控日志）")})
            except Exception as e:
                self._json({"ok": False, "err": str(e)}, 500)
        elif self.path == "/api/test-imghost":
            # 图床通路测试（P1-1）：直调所选床上传函数，绕开
            # upload_chart 的 provider 路由——freeimage 连败记忆会静默
            # 跳档，走 upload_chart 测试会假绿；测试必须如实报告所选床
            # 死活（死亡/退避期返回 None 如实报败）
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                provider = (body.get("provider") or "").strip().lower()
                token = (body.get("token") or "").strip()
                if provider not in ("freeimage", "smms"):
                    self._json({"ok": False, "err": "未知图床服务"})
                    return
                if provider == "smms" and not token:
                    self._json({"ok": False, "err": "请先填写 sm.ms Token"})
                    return
                import base64 as _b64
                import tempfile as _tf
                from report import upload_freeimage, upload_smms
                _png = _tf.NamedTemporaryFile(suffix=".png", delete=False)
                try:
                    # 1×1 透明 PNG 内存图：测通路不产图
                    _png.write(_b64.b64decode(
                        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
                        "AAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="))
                    _png.close()
                    # 独立捕获 logger：不碰服务主 logger，失败时捞出图床
                    # 响应摘要随 err 回显（upload_smms 失败只回 None）
                    tlog = logging.getLogger("webui.imghost-test")
                    tlog.propagate = False
                    tlog.setLevel(logging.WARNING)
                    _buf = []

                    class _Cap(logging.Handler):
                        def emit(self, record):
                            _buf.append(record.getMessage())

                    _h = _Cap()
                    tlog.addHandler(_h)
                    try:
                        if provider == "freeimage":
                            # 连败退避跳档/端点死亡均返回 None：端点
                            # 拿不到 URL 即报败（日志经 _Cap 随附）
                            url = upload_freeimage(_png.name, tlog)
                        else:
                            url = upload_smms(_png.name, token, tlog)
                    finally:
                        tlog.removeHandler(_h)
                    if url:
                        self._json({"ok": True, "url": url})
                    else:
                        _detail = _buf[-1] if _buf else "上传失败（详见服务日志）"
                        self._json({"ok": False, "err": _detail[:120]})
                finally:
                    try:
                        os.remove(_png.name)
                    except OSError:
                        pass
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


def _page_html(version):
    """PAGE 注入页面代际（__PAGEVER__ → 运行版本）：页面 load() 轮询
    比对 state.version，失配亮「刷新」横幅——Cache-Control: no-cache
    管不住重启窗口期一直开着的旧标签页（今日「布局抖动/点击不通」
    实报=陈旧标签页跑着中间代际代码，12 档窗宽矩阵证实现行代码零振荡）。
    demo/烘焙站传 demo 代际同律，令牌必须替换勿泄漏。"""
    return PAGE.replace("__PAGEVER__", version or "")


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
    # 依赖局域网可达——服务只绑回环时 base_url 配了也连不上，host 必须可配
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
            # state 缓存签名不含端口：只作废签名让下个请求走 SWR
            # （先回旧值、后台按新端口重建）——连 payload 一起清会让
            # 首个 /api/state 落入冷启动首建全量重算，换绑后分钟级假死
            with _STATE_LOCK:
                _STATE_CACHE["sig"] = None
        except Exception as e:
            _State.logger.warning("[控制台] 端口 %s 切换失败: %s", port, e)

    threading.Timer(0.4, _do).start()
    return True


def _demo_main():
    """`python webui.py --demo`：零配置演示控制台（开源访客一键体验）。

    生成确定性合成库（系统临时目录，不污染仓库），渲染链路与真机完全一致。"""
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
