# 用户内关注航班 + 特价雷达设计（2026-10-23）

## 目标

多租户下把「关注航班」「特价雷达」从全局概念收进用户：每个用户拥有自己的关注航班、特价查询条件与提醒；特价雷达支持“出发地 → 目的地 + 日期范围 → 五渠道低价日历/列表 → 最低价日期/航班 → 真实明细”。

## 信息架构

配置页每个用户卡内顺序：

1. 基础（A）
2. 监控渠道（B）
3. 关注航线（C）
4. 关注航班（D）：既有清单/筛选/添加表单**内联**展开在用户卡内（单实例 DOM 寄存后挂载），不弹层、不跳走
5. 特价雷达（E）：官方特价机票频道口径——任意出发/到达城市 + 日期范围 + 官方渠道（携程全国为独立选项），**不要求也不联动本用户关注航线**；卡内直接出低价日历/榜单价，并列出五家官方特价页直达入口，点日期进入真实明细探针
6. 通知渠道（F）

移除配置页左侧全局「关注航班」入口；监控页顶部吸顶 chip 始终显示「👤 <用户> · 用户视图」（单用户也显示；多用户另加用户 pills 行），tab 固定为「概览 / 特价雷达 / 关注航线走势 / 关注航班走势 / 关注航班明细 / 渠道健康」，全部跟随当前用户选择；关注航班明细页提供「只看关注」，按该用户关注清单过滤本轮真实明细。渠道选择统一使用官方渠道图标（与登录卡/监控台同源），不使用纯文字 chip。

## 数据模型

`users[].special_radar`（新增，按用户）：

```yaml
special_radar:
  enabled: true
  from: SHA
  to: BKK            # nationwide=true 时忽略/表示全国
  nationwide: false  # 仅携程支持“出发地→全国”
  start: 2026-10-24
  end: 2026-11-23
  channels: [ctrip, qunar, fliggy, tongcheng, tuniu]
  max_price: 0       # 0=不限
  alert: true        # 发现新低是否按用户通知
```

`special_deals` 增加 `user` 与 `channel` 列（迁移：`ALTER TABLE`，旧行 user=''）；`/api/specials?user=` 只返回该用户。关注航班沿用现有按用户 `/api/srx/watch`，不再新增存储。

## 特殊雷达数据契约

`POST /api/special-radar`：

```json
{
  "user": "邓美銮",
  "from": "SHA", "to": "BKK", "nationwide": false,
  "start": "2026-10-24", "end": "2026-11-23",
  "channels": ["ctrip", "fliggy", "qunar", "tongcheng", "tuniu"]
}
```

响应：

```json
{
  "ok": true,
  "query": {"from":"SHA","to":"BKK","start":"...","end":"..."},
  "dates": [
    {"date":"2026-10-24","best":{"channel":"ctrip","price":1355,
      "kind":"calendar","to":"BKK","to_name":"曼谷","link":"..."},
     "by_channel":{"ctrip":{"price":1355,"kind":"calendar"},
                   "fliggy":{"price":1461,"kind":"calendar"}}}
  ],
  "channels": {"ctrip":{"status":"ok","kind":"calendar"},
               "qunar":{"status":"login","reason":"..."},
               "fliggy":{"status":"ok"}, "tongcheng":{"status":"not_connected"},
               "tuniu":{"status":"unsupported","reason":"榜单出发地跟随出口 IP"}},
  "lowest": {"date":"2026-10-24","channel":"ctrip","price":1355},
  "generated_at": "..."
}
```

- `kind=calendar` 只能作为低价发现；不冒充航班明细。
- 每个渠道单独状态：`ok/empty/login/challenge/not_connected/unsupported/error`。
- 同日期同渠道去重，取最低；跨渠道 best 取最低，保留来源。
- 日期范围限制 1–90 天；渠道至少一个。

## 来源适配（Phase 1 + Phase 2）

| 渠道 | 真实来源 | 能力 |
| --- | --- | --- |
| 携程 | 15380 单航线低价日历；19728 出发地→全中国榜 | 指定航线 + 全国，日历价 |
| 飞猪 | `r.fliggy.com/cheapestCalendar/pc` 单航线日历（国内/国际同源，含税） | 指定航线；按 7 天窗口滚动，最多 5 窗（35 天），超窗如实标注覆盖终点 |
| 途牛 | 国内：`flight-api.tuniu.com/query/flight/v1/calendar`（官方 H5 同源，零登录/零签名，逐日裸价）；国际：`queryCheapTickets` 出发地榜单 | 国内任意城市对逐日价；国际仅榜单（跟随出口 IP），无国际日历 |
| 去哪儿 | 官方 H5 特价页 + `getFlightCalendar`（页面 JS 生成签名；使用已保存去哪儿会话） | 指定航线；加载官方深链读取真实日历，不逆向签名、不绕过验证码；风控失败时明确报错并冷却 10 分钟 |
| 同程 | H5 `queryCalendarLowestPrice`（免登录/免签名，channel=4） | 指定航线；一次返回 90 天（国际）/180 天（国内）窗口，按查询区间过滤 |

Phase 2 研究必须先捕获真实响应并落盘，再写解析；任何通用搜索页不得标成专属特价页。

## 最低价 → 明细

雷达日历只做发现。点击日期或“查看最低价明细”时：

1. 切到「检索」页；
2. 预填该用户航线/日期/勾选渠道；
3. 用户点击/自动发起现有真实探针（`/api/probe/start`）；
4. 任务面板展示真实明细、RAW、原页；失败/登录/验证按现有语义展示。

## 迁移与兼容

- `special_radar` 缺省时由旧 `specials[0]` 推导：`from`、`days` → `start/end`、`platforms`；`to` 空、`nationwide=false`；不删除旧字段。
- `special_deals` 迁移幂等；旧记录 user 为空，只在全局历史中展示。
- 关注航班面板不再有全局入口，但旧深链/配置仍可打开（兼容）。

## 验收

- 多用户 A/B：A 的关注/雷达条件不泄露到 B；切换用户后列表和查询条件同步。
- 携程指定航线日历、携程全国榜、飞猪榜返回真实日期价；状态标注来源。
- 去哪儿/同程/途牛未接入或 IP 不匹配时显示真实原因，不返回伪造行。
- 最低价日期可一键发起五渠道真实明细；明细失败/登录/验证可见。
- 1360/390 无横向溢出；日历/列表可键盘操作；空态区分未采/未接入/登录/无票。
- 全量 pytest、UI 门禁、live 浏览器验证。
