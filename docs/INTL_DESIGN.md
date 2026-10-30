# 国际航班监控 · 统一设计

> 状态：**已落地**（核心契约 + 五渠道采集面全回填）。
> 本文档是「国际航班支持」的单源设计；实现以本文契约为准，
> 分渠道实证细节见调研报告（`_scratch/intl/report_*.md`）。

## 0. 目标与边界

社区需求：在只支持国内航班的监控平台上，**统一**支持国际航班监控。

- v1 范围：国际**单程**低价监控全链路（采集 → 明细 → 达标判定 → 推送 → 控制台）。
- **已实现（原 v1 非目标，2026-10-27 复核）**：往返（tripType）配对监控——`Route.ret_dates` 支持多返程日，采集按返程日逐对跑，`price` = 往返总价含税（详见本文 §2.6；渠道实现见 `crawlers/fliggy.py` 的 `tripType=1 + backDate`）。
- 仍挂账：多币种偏好、国际特价雷达接入。
- 铁律继承：自托管零外部服务依赖、宁缺勿错、跨端同带单源、行为变更必 TDD。

## 1. 统一核心契约（已定稿，实现即按此）

### 1.1 scope 判定：自动，零配置（`core/intl.py` 单源）

- `MAINLAND_CODES`：国内城市字典（core/citydata.CITY 289 城）值域**剔除「中国」前缀条目**
  （中国香港 HKG / 中国澳门 MFM / 中国台北 TPE 等——OTA 语境港澳门票走国际票体系，
  字典本身已自带标记，直接复用）。
- `_MAINLAND_AIRPORTS_EXTRA`（`core/intl.py` 的模块级私有集合）：城市字典是**城市码**口径，PEK / PKX 这类**机场码**不在其中；
  不补这一层，浦东以外的首都/大兴会被判成国际，整条国内航线走国际档（时长被时区修正、价格按含税总价）。
- `is_intl_city(code)`：合法 IATA3 且 ∉ MAINLAND_CODES → 国际。
- `is_intl_route(from,to)`：任一端是国际 → 整条航线国际。
- **用户零选档**：配置仍只填 `from/to` 三字码，scope 全自动判定。
  不引入 `scope:` 配置键（可判定的事不做配置，YAGNI）。
- 显示名：`INTL_CITY_NAME` 精选国际城市/机场中文名（热门目的地全量收录），
  未收录原样显示三字码（宁缺勿错，同 AIRPORT_NAME_CN 先例）。

### 1.2 明细元素契约：元素自描述，调用方零改动

国际分支产出的明细 dict 在国内形态之上**增量**落键（全部可选，国内行零污染）：

| 键 | 类型 | 语义 |
|----|------|------|
| `intl` | 1 | 国际行标记——flightnorm/推送/控制台凭它走国际档逻辑 |
| `tz_dep` / `tz_arr` | int（分钟） | 起飞/到达机场当地时区对 UTC 偏移（东正西负，含夏令时的由 zoneinfo 实时算出后落数） |
| `tax` | float | 税费额（渠道裸价+税分报时落；price 已含税则不落或为 0） |
| `arrDate` | str | 到达当地日期（结构化 API 给就透传，跨天 N 的日期源） |

- **价格口径**：`price` 恒为**含税总价 CNY**。渠道只给裸价+税时相加；
  外币报价必须换算 CNY 后落价（v1 渠道调研确认 CNY 报价为主，外币渠道列入挂账）。
- `FlightPrice.price` 语义不变（该航线本轮最低含税价）；`extra` 元素承载明细。
- 时长真值：`elapsed = N*1440 + arr_local − dep_local − (tz_arr − tz_dep)`
  （起降时刻是**双端本地时刻**，国内隐含同区所以从未显式；国际必须减时区差）。

### 1.3 价带分档（`core/models.py` 单源扩展）

- `PRICE_MIN=100` 不变；`PRICE_MAX=50000` 保留为**国内档**；
  新增 `PRICE_INTL_MAX=200000`（国际经济舱全档 + 高档舱低价窗）。
- 新单源帮手 `price_max_for(from_code, to_code)` 与 `price_band_ok(v, from, to)`：
  共享消费端（report/webui/alerter/main 的带过滤）一律改走它；
  爬虫内联守卫**只在新增国际分支**用国际带，存量国内分支一字节不动
  （国际行走国际分支，永不进国内守卫——分支隔离使窄带无害）。

### 1.4 flightnorm 国际档（元素 `intl` 在场时）

- `cross_days`：日期差上限 0–3 → 国际档 0–7（长衔接国际行程 +2/+3 天合法）。
- 时长重算：有 `tz_dep/tz_arr` → 按 §1.2 公式修正后参与 ±15 分钟覆盖窗；
  **无时区键 → 绝不用本地时刻朴素重算覆盖渠道时长**（无时区的朴素重算对
  国际行系统性错 ±小时级，宁信渠道结构化时长，宁缺勿错）。
- 到达窗 `_arrival_ok`：凭 `crossDayN/arrDate` 泛化（到达「次日 HH:MM 前」
  语义按到达当地日推 N 天，约束语义不变）。

### 1.5 存储与聚合

- `flight_prices` 表结构零变更（extra JSON 已是明细载体；platform+route 键
  天然容纳国际航线）；`price_daily` 直/中转分桶键 `transCity` truthy 语义
  对国际同样成立。半年走势/日报按航线键自然隔离。

### 1.6 达标判定与毒价守卫

- `_qual_price`：国际行 price 已含税 → **直接返回原价**（`if f.get("intl"): return p`）；
  国内飞猪走 `FLIGGY_TAX_PAD` 垫税分支，但该常量**当前为 0**（2026-10-27 核 `core/alerter.py`），
  即两条路现在都不加税。历史原因：垫税是为飞猪国内**裸价**列表设的补偿，归零重标定后（12,303 对中位比 1.000）不再需要；
  国际含税口径本来就对齐，重复加税=判定虚高。
- 跨渠道毒价守卫（XCHAN_PHANTOM_RATIO 比率线）与渠道内 0.5x 锚：
  全部按比率工作，**对价格量纲不敏感，国际直接复用**（绝对价格假设仅在
  带过滤处，已按 §1.3 收口）。

## 2. 分渠道采集面（调研实证回填）

> 完整证据链在 `_scratch/intl/report_*.md`（端点/风控三态/样本响应）。

### 2.1 携程 ctrip —— B 级 · 已落地（fetch 参数分流）

国际与国内**共用 taro H5 壳 + soa2/14488 flightListSearchForH5 同一条
通路**：`from=outer` 即国际壳，请求体 `dccode/accode` IATA3 直通
（dcid/acid 传 undefined 即可），同 XHR 键同解析器。风控同一面
（whaleguard 只认 profile 信任度，同新鲜 profile 国内同样 430）——
生产 persistent profile 通用。落地：`URL_TPL_INTL` + `_entry_url` 单源
分流，解析器/预热零改动，价带 `_band_ok` 宽带档，元素 tz 戳解析期
自门落键。**待生产 profile 首采定谳**：国际 200 响应的税费/币种键
（国内结构无此键，观察哨已挂设计）。

### 2.2 去哪儿 qunar —— B 级 · 已落地（浏览器单路径）

`touchInterList`（与国内 touchInnerList 同族命名），参数=**中文城市名**
（INTL_CITY_SHORT 城市级短名回退链）。未登录=1999 硬拒（国内软空
列表），生产 .qunar.com 主域登录 cookie 同域生效。价格三键渲染实证：
**minPrice=含税 / nakedPrice=裸价 / taxPrice=税费**，CNY。风控状态机
（Judge 源码）：code 7=滑块/8=跳登录/9=强刷/10004=点选——只记录
退避不绕过，8/1999 置 login_suspect。PC 国际面已 404 断供（单腿渠道，
须接受无回退）。落地：`page.route` 拦响应体（on_response.text() 丢体
时序规避）+ 三级解码（明文→t1000 分片重组→dump 拒落价）。

### 2.3 同程 tongcheng —— A- 级日历 · 已落地（H5 明细可探针；桌面 API 挂二期）

一期走 **A- 级 `miflightapi/ts/calendar`**（无登录、结构化、三航线
实测）：LP/TP 裸含税双列 + RD[] 未来日点位，price←RD[].TP 含税口径
（与国内 atp 一致），tax=TP−P，transfer←ext.segments。**纯 httpx 全
444「非法链接」（会话层校验）——唯一实证通路 = Playwright 环境**：
iflight 入口页养会话（as-sdk 初始化+cookie 下发）后页内
credentials fetch（探针 p7 实证）；headless 下页内 async fetch 有被
GC 的形态，主路径以 `ctx.request.get` 兜底（共享会话 cookie，无页内
promise）。国际入口是 PC 页——移动 UA 下会话面错位，采集临时切桌面档。
通路具**时段性**：同时段同手法可整域软拒（小体「非法链接」），生产按
分支三档降级链自愈并观测恢复窗。国际面用同程城市码（值面=IATA
城市码）：airport_city_code 映射归并（PEK→BJS/PVG→SHA/NRT→TYO）。
日历面无航班明细（行名「日历最低价」诚实留空同 fliggy 律）；日历价
疑中转/拼接成分（ML 标记）——source=ts_calendar 随行落库分层。
**列表明细已有通路（2026-10-27 核）**：桌面 `book1` 会跳到 H5
`m.ly.com/tiflight/book1.html`，原站服务端直出航班卡片（SHA→OSA 实测 52 条，
含航班号/起降时刻/机场/机型/余票/含税总价），代码以 H5 DOM 为主路径
（`crawlers/tongcheng.py` 的 `INTL_H5_BOOK` + `_intl_h5_url`）；无痕上下文会跳 passport，
须复用已保存会话的可见窗口，因此**只在用户主动探针时使用**。
**仍挂二期的是桌面 API 那条**（`ts/list/iflightbff`：双端强制登录 + as-sdk wasm 签名，
需 `--login` 会话反推轮询协议）。不要把两者混为一谈写成「同程国际明细没有」。

### 2.4 途牛 tuniu —— B（能出极少数行）· 已落地（httpx 直连）

国际整条产品线跑 **m2015 老应用**（seajs/zepto），与国内 SPA 分家：
`GET m.tuniu.com/api/intlFlight/intelProduct/queryFlight`（systemId 63 /
错误族 710000）——**国内 710114 登录墙不连坐**（受理面实测）。token 门
（非登录）已还原并实测：列表页 `#token` GUID → Σ(charCode×(i+1))
过程中 >80 则 -=80。请求面字段 `dCityCode/aCityCode`（实证定谳：
误用响应回显字段 `dCityIataCode` 服务端忽略→回显 null）。
**2026-10-27 复核（推翻「受理不出数」）**：调研期那次 30+ 拍空确有据，但**不是永久软墙**。
当日真实落库已是：SHA→LHR 286 行（5 个航班号）/ SHA→BKK 277（7 个）/ SHA→NRT 251（3 个）/ SHA→SIN 205（3 个），
行均带航班号、时刻与机场（`flight_no` 空值 0/1159），价格区间合理（LHR ￥2108–3217）。
> **行数会随轮次增长**（2026-10-28 复核：+LHR 285 / BKK 274 / NRT 249 / SIN 204，`flight_no` 空值仍为 0/1012，
> LHR 价位仍是 ￥2108–3217）。上段写的是当日快照；判据不是这些绝对行数，
> 而是**「行数 ≈ 不同 `fetched_at` 数」**——它证明每轮只落极少量条目，见下。
**形态要点**：每轮批次只落 1 行（286 行 = 286 个不同 `fetched_at`），说明 `needQueryMore` 轮询虽然能拿到
非空 `productList`，但**聚合长期只吐极少量条目**——这是"能出、但出得少"，不是"不出数"。
（2026-10-28 实测这条判据仍成立：四条航线均 `COUNT(*) == COUNT(DISTINCT fetched_at)`，
即 285/285、274/274、249/249、204/204——**新增代码后若一轮落多行，这个等式就会破，说明采集口径变了**。）
因此：**不要把途牛国际写成"软墙/不出数"**（旧结论已过期），也不要按"全渠道明细齐全"宣传；
正确说法是「可出极少飞行条目」。needLogin 观察哨仍保留：翻 true 即停采；独立连败计数（国内墙不拖累国际降载节奏）。

### 2.5 飞猪 fliggy —— A 级日历 · 已落地（明细级挂二期）

一期走 **A 级 `r.fliggy.com/cheapestCalendar/pc`**（零 cookie 直连
JSONP，三航线实证）：日维度最低价，票面/税费分列（税费 340~1272
占比大），price=bare+tax 含税入库，日历无航班明细（airline/时刻诚实
留空，行名「日历最低价」，extra 元素数组带全日历上下文 days）。**国际
按城市码收**（机场码被拒「城市基础数据缺失」）——`airport_city_code`
映射层（NRT→TYO…）。0 价=无报价日静默信号须滤。日历请求须带搜索
结果页 Referer（缺被 WAF 拒）；短窗连打触发软拒空壳小体（频控门），
生产 1 请求/航线/轮在安全面内。明细级 poller.do
是 B 级（匿名 headless 必触发 baxia 滑块，登录态免滑未验证）挂二期。
往返（backDate 参数）日历端点已支持，挂账接入。

## 2.6 往返（tripType）监控 · 已落地（2026-10-27 核对）

> 本节原标「二期统一设计」。现状：`core/models.py` 有 `ret_date`（单值）与 `ret_dates`（多返程日），
> `main.py` 按 `ret_dates` 逐对跑采集，`core/specials.py` 侧往返价与推送文案（`ret_price`、
> 「往返含返程」）均已接线；界面有「🔁 往返」开关与返程日多选。**尚未接入的是特价雷达**（`core/special_radar.py`
> 没有 backDate/tripType）。引用本节时按这个现状理解。

> 真报文实证（`_scratch/intl/r13_fliggy_rt.json`：SHA→TYO 往返
> 日历 7 日点全有价，**¥771+税 1550=含税 2321**——往返税费占比
> 远超单程，含税总价口径 §1.2 的价值实证）。

### 契约决策

- **配置面**：`Route` 增可选单键 `ret_date`（YYYY-MM-DD；缺省=单程，
  存量配置零兼容负担）。**不做** dates×ret_date 笛卡尔积（往返按
  「去程日+固定回程日」一对一定价，与单程多日独立监控语义分开）。
- **数据面**：`FlightPrice` 契约不变（`depart_date`=去程日）；
  元素增量落 `backDate` / `tripType:"RT"`，`price`=**往返总价含税**
  （渠道直出总价口径，勿拆两程）。达标判定：往返总价对
  `alert_threshold`（直飞阈值语义复用；中转阈值对国际往返暂不启用，
  挂账）。曲线/日桶：桶键 `depart_date` 自然承载（回程日随元素
  backDate 透传，不参桶键）。
- **渠道参数映射**（全部已受理实证或产品面确认）：

| 渠道 | 请求形态 | 实证 |
|------|----------|------|
| 飞猪 | 日历 `tripType=1&backDate=`；元素增 `backDate` 键 | **R13 真报文** |
| 同程 | 日历 `TT=RT&AD=回程日`；RD[].RD=返程日 | 调研 §5 实测受理 |
| 去哪儿 | 列表 body 增 `backDate`；响应 `isOneway`/行 go-back 分组 | 调研 §5 实测 body |
| 途牛 | `route=A-B\|B-A` + `date=d1\|d2`；`isPackage=2` | 调研 §5 实测受理 |
| 携程 | URL `tripType=ROUND_TRIP&rdate=`；14488 searchitem 双段 | 页面 200/形态待登录取数 |

- **UI 面**：行头「往返」徽标（route.ret_date 在场即亮，徽标族
  同 `.rintl` 形态）；日期片成对呈现；明细行「往返」tag（复用
  .tag 族）。
- **分期落地（2026-10-27 复核）**：飞猪/同程日历通道已按日历价口径接线（`source` 分层）；
  去哪儿/携程随账号可达性推进；**途牛国际已能出极少数行（见 §2.4），不是软墙**；**特价雷达 RT 仍未接入**（末位）。

## 3. 控制台交互（高级便捷）

- **行头**：国际航线自动「国际」徽标（scope 自动判定，行头 chips 族复用）。
- **城市面板**：新增「国际」页签——热门目的地（东亚/东南亚/欧洲/北美/大洋洲）
  中文名/拼音/三字码三路搜索，点选即填码；输入框直接认任意合法 IATA3。
- **明细**：国际行带「国际」标记 + 税费拆分小字（含税总价口径下展示
  「裸价+税」构成，渠道给全才显示）；跨天/时长/准点率等 chips 全复用。
- **筛选**：直飞/中转、航司、舱位、时段族对国际行同构生效，零新增维度。
- **推送**：达标行标「含税」；日报/心跳行文按航线 scope 自然兼容（slim
  链与明细总表图零结构性改动）。

## 4. 实施切面

| 层 | 文件 | 动作 |
|----|------|------|
| 契约 | core/intl.py（新） | scope/字典/时区，TDD |
| 契约 | core/models.py | 价带分档帮手，TDD |
| 归一 | core/flightnorm.py | 国际档时长/跨天，TDD |
| 采集 | crawlers/*.py ×5 | fetch 分流 _fetch_intl，按 §2 分级落地 |
| 消费 | alerter/report/webui/main | 带过滤走 price_band_ok 单源 |
| 界面 | webui.py | 徽标/页签/税费词面 |
| 门禁 | tests/test_intl_*.py | 元素契约+归一+界面+回放 |

- 存量国内行为零变更（分支隔离 + 元素自描述键缺省缺席）。
- 全量 pytest 回归绿为唯一落地门。
