# ticket-monitoring 1.5.279 · 2026-10-22

> 自托管的多渠道机票价格监控：五平台明细采集 → 钉钉图文推送 → 达标四层强提醒。
> 国内航线与国际航线（五洲目的地）同一套采集-判定-推送链路。
> 数据留在本机，配置全在网页，开源免费。

## 去哪儿 PC 断供切换 H5（2026-10-10 渠道变更）

- **爬虫主路径改为 H5 先行**：`https://m.flight.qunar.com/ncs/page/flightlist` 作为去哪儿国内列表主入口；PC `flight.qunar.com/site/oneway_list.htm` 自 2026-10-10 起 302 回官网促销聚合，仅保留「复活探测」兜底，避免每轮把时间耗在死入口。
- **token 直连同源**：httpx 兜底 Referer 同步改为 m.flight H5；浏览器拦截到的 `touchInnerList` token 仍用于分片还原完整明细。
- **用户侧「打开原页」改指 H5**：L2 推送、检索镜像、关注台与演示样本中的去哪儿深链全部改为 m.flight H5 列表页，与爬虫同参（城市名/日期/child/baby/cabinType），不再把用户送到断供的 PC 页。
- **实测**：2026-10-22 对 SHA→CAN 2026-10-23 实际抓取，H5 浏览器路径 4.0s 返回 **181 条明细**（直飞 159 / 中转 22），最低价 ¥620；PC 入口确认 302 到 `www.qunar.com`。
- **携程国际的口径说清**：Ctrip 国际列表/日历对匿名会话弹「手机登录/注册」，14488 列表端点对国际查询业务性拒答（既有设计走 15380 日历）。本轮补上页面级「需登录」识别并写入 health/告警，不再把「没登录」表现成「没数据」；重登后日历价继续采，航班明细仍以携程国际页面实际供给为准。
- **门禁**：新增 H5 先行顺序、PC 死链禁回归、Ctrip 国际登录识别测试；用户链接与爬虫模板逐参相等测试同步到 H5。

## 登录入口与「来源接入」看板（2026-10-22）

- **统一登录页**：PC 登录入口随 `/site/` 停服，qunar 登录窗改落 `user.qunar.com/passport/login.jsp`（手机号验证码/扫码），Cookie 落 `.qunar.com` 主域，与 H5 取数共用；登录卡改为「必须登录」并标注 `H5`。
- **来源接入卡**：渠道健康顶部新增「PC 网页已停服 → H5 机票仍可取数 → 登录态」路径，登录态实时读 `/api/login-state`（20s 节流）；DEMO 静态站明确标 DEMO，不伪造已登录。卡片同时声明 App 专属价与自动下单不在采集范围。
- **实测**：2026-10-22 H5 先行 SHA→HAK 2027-01-29 **4.4s / 68 条明细 / 最低 ¥1650**；同一 URL 匿名返回 0 条，确认登录门。App 抓包在 Windows 模拟器 + mitmproxy 上理论可行，但证书固定/设备指纹/签名与风控、升级维护成本高，且 H5 与 App 库存同源，不列为主方案。

## 验证

- pytest 全量 **3286 passed / 0 failed**
- 浏览器自测 **570/570**，零 JS console/pageerror
- 实时检索门禁 **43/43**
- 在线演示：https://dengmeiluan.github.io/ticket-monitoring/site/
- 源码与说明：https://github.com/dengmeiluan/ticket-monitoring

## 发行资产

四个平台 zip + `SHA256SUMS.txt`，zip 根为可执行文件与 `_internal/`；`config.yaml`、`data/`、`user_data/` 在升级时保留。
