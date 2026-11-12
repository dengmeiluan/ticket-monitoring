# 基线快照（2026-11-09）

> 用途：任何改动前后用同一口径复测对比。数据来自本机 `data/prices.db` 与 `http://127.0.0.1:8765`，不估算。

## 一、今日各渠道出数（只算真出数 ok/calendar）

| 渠道 | 次数 | 行数 | 行/次 |
|---|---|---|---|
| fliggy | 48 | 3746 | 78.0 |
| ctrip | 49 | 3338 | 68.1 |
| tuniu | 37 | 1386 | 37.5 |
| tongcheng | 81 | 188 | 2.3 |
| app_zhixing | 10 | 10 | 1.0 |
| app_qunar | 7 | 7 | 1.0 |

## 二、各通路效率 + **通路分工**（近 12 小时，按行/次降序）

| 渠道 | 通路 | 次数 | 行数 | 行/次 | 独立日期数 |
|---|---|---|---|---|---|
| ctrip | PC | 18 | 2148 | 119.3 | 1 |
| fliggy | PC | 54 | 4339 | 80.4 | 4 |
| tuniu | PC·国际 | 16 | 703 | 43.9 | 1 |
| ctrip | H5 | 34 | 1306 | 38.4 | 3 |
| tuniu | H5/API | 24 | 755 | 31.5 | 4 |
| tongcheng | PC | 28 | 143 | 5.1 | 3 |
| app_qunar | 航班明细 | 7 | 7 | 1.0 | 4 |
| app_zhixing | 日历 | 5 | 5 | 1.0 | 1 |
| app_zhixing | 航班明细 | 5 | 5 | 1.0 | 1 |
| fliggy | 日历 | 1 | 1 | 1.0 | 1 |
| tongcheng | 窗历 | 59 | 59 | 1.0 | 1 |

> **读这一节的前提**：`行/次` 只在『分工相同』时可比。新增/调整通路后，有的通路会先吃掉好采的日期，其余通路只剩缺口——比值下降不等于变差。判断办法：看 `独立日期数`（分工变了，这个数也会变），并对照第三节**失败面构成**。

## 三、失败面构成（近 12 小时，前 12 项）

| 渠道 | 通路 | 状态 | 次数 |
|---|---|---|---|
| app_fliggy | app-login | login | 59 |
| app_ctrip | 航班明细 | login | 33 |
| app_zhixing | app-date | unsupported | 31 |
| app_ctrip | app-date | unsupported | 27 |
| app_fliggy | app-date | unsupported | 23 |
| tuniu | PC | unsupported | 23 |
| app_ctrip | app-date | timeout | 22 |
| app_ctrip | app-login | login | 15 |
| app_qunar | app-login | login | 8 |
| app_qunar | 航班明细 | login | 8 |
| app_fliggy | app-login | timeout | 4 |
| app_fliggy | app-form | timeout | 3 |

## 四、登录槽位（各端独立 profile）

| 槽位 | 端 | 状态 | 需登录 |
|---|---|---|---|
| ctrip | PC | available | 否 |
| ctrip_h5 | H5 | saved | 否 |
| fliggy | PC | available | 否 |
| fliggy_h5 | H5 | page_ok | 否 |
| qunar | 全端·已停服 | saved | 否 |
| tongcheng | PC | available | 否 |
| tongcheng_h5 | H5 | saved | 否 |
| tuniu | PC | available | 否 |
| tuniu_h5 | H5 | saved | 否 |

## 五、降级项

| 项 | 次数 | 最近原因 |
|---|---|---|
| device_env | 7 | 1 处矛盾（ro.product.cpu.abilist：现 arm64-v8a,armeabi-v7a,ar / 应 只有 ARM（arm |
| app_layout | 28 | 连续 8 轮 0 行且认不出页面（末次路径 空）——疑似改版，该渠道的认屏/解析规则可能要更新 |
| app_risk_blocked | 75 | 登录墙短路：还需等 115 分钟（去「渠道登录」登一次） |

## 六、最近一轮计时

| 项 | 值 |
|---|---|
| n | 14 |
| wall | 360.9 |
| work | 900.2 |
| idle_ratio | 0.0 |
| gate_ratio | 0.113 |
| timed_out | 0 |

## 复测方法

```bash
python -m core.baseline --out /tmp/after.md
python -m core.channel_matrix
python -m core.channel_matrix --trend --hours 6
python -m core.advise
```

**对比看 `行/次`（产出效率）与失败面构成**，不要只看总行数（总行数受轮次与日期影响）。
