# App 日期视野：规划阶段就剔掉，别让 App 起来白跑

> 2026-11-12 起生效（`main._drop_far_app_channels`）。对应目标里的**效率**
> 与**口径**两件事：省掉注定做不到的 App 启动，也别让这些行污染成功率。

## 规则

App 渠道能查的日期有上下限（默认 **62 天**，可用
`crawler.app_date_horizon_days` 全局改、`crawler.app_date_horizon_days_map`
按渠道改）。超出视野的日期**不再派给 App 渠道**，只交浏览器通路。

浏览器渠道没有这个限制，所以覆盖不受影响。

## 为什么不是"让它跑，跑完记 unsupported"

`unsupported` 是能力边界、账本口径已经单列（不算失败、不算无票）。但**代价是真的**：
每派一次要启一次 App（十几秒起），走到地方才判「超窗」。实测账本：

```
unsupported  app-date   27 次 / 24h   平均 37146 ms      ← 白跑
ok           航班明细    23 次
```

27 次 × 一次启动 ≈ 十几分钟设备时间，全花在"注定做不到"的请求上。

## 实测证据（2026-11-12 09:08 那一轮）

规划日志：

```
[规划] app_ctrip     不采 2027-01-29：超出 App 视野 45 天（交浏览器通路）
[规划] app_fliggy    不采 2027-01-29：超出 App 视野 62 天（交浏览器通路）
[规划] app_qunar     不采 2027-01-29：超出 App 视野 62 天（交浏览器通路）
[规划] app_tongcheng 不采 2027-01-29：超出 App 视野 62 天（交浏览器通路）
[规划] app_zhixing   不采 2027-01-29：超出 App 视野 45 天（交浏览器通路）
```

**数据没少**——同一天浏览器通路照常接住：

```
ctrip      H5 ok / PC·周历 ok
fliggy     PC ok
tongcheng  PC ok
tuniu      PC·周历 ok
→ 该日期入库 5 条价（ctrip 2 / fliggy 1 / tongcheng 1 / tuniu 1）
```

并且这段时间 `app-date unsupported` **记录数 = 0**。

## 别把它当成"停用"

被剔的只是**这一次查询**。下一轮如果有个近日期，该 App 渠道照常参与。
真要停某个 App 渠道，用「停手」（见 `docs/CHANNEL_PARKED.md`）。
