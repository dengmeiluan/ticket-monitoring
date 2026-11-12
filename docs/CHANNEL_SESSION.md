# 渠道会话与健康状态

配置登录卡、健康页的当前处理入口、来源接入和检索渠道条使用同一份 `/api/login-state` 快照。近 24 小时健康格、采集结果、字段可得率仍保留各自口径。

## 当前状态

| status | 含义 |
| --- | --- |
| active | 登录窗口已打开，等待用户确认 |
| saving | 已请求保存，后台尚未完成导出、关闭和落盘 |
| pending | 已确认保存，等待实际采集证据 |
| saved | 本地会话存在，尚无当前可用性结论 |
| available | 存在保存时间之后的近期航班明细证据；不等于所有航线有票，也不等于独立认证验证 |
| page_ok | 飞猪 H5 入口核验通过（页面未命中登录墙/验证）；只证明入口可达，不代表明细可用 |
| login_required | 当前范围有晚于保存及同范围明细证据的明确认证拒绝 |
| challenge | 账本（`fetch_paths`）里同入口最近一次尝试是滑块/人机验证，且之后没有成功或新会话；需打开该渠道窗口人工完成验证 |
| missing | 没有保存的本地会话资料 |
| save_error | 登录工作线程未能完成保存 |
| read_error | **前端派生**：`/api/login-state` 读取失败，界面保留上次资料并自动重试 |
| loading | **前端派生**：尚未拿到首份快照 |
| demo | **前端派生**：演示模式，会话未经验证（演示徽标同屏） |

> 前 10 个由后端产出；后 3 个是界面在前端按响应情况派生的状态（2026-11-01 核对 `webui.py::channelAuthView`）。看到 `read_error` 不代表账号失效，只代表这一次没读到。

`challenge` 的证据来自采集账本 `fetch_paths`（不是 monitor.log 的轮次）：同一入口最近一次是 `blocked`（滑块/验证码）或 `login`，且之后没有同入口成功、也没有更新的会话保存；看不懂的 `blocked` 原文不归入该状态。它与会话失效是两件事——滑块拦截时账号往往还在，动作是打开该渠道窗口完成验证。

接口另含 `saved_at`、`needs_login` 及按 `domestic/international/unknown` 划分的 `scopes`。当前动作使用 `status/needs_login`；兼容字段 `stale` 仅保留旧采集器标记，不作为新页面独立判断依据。状态接口读取失败时，前端显示读取失败并保留上次资料，不能改成未登录。

认证证据按渠道及业务范围取最新时间。国内明细不能清除国际认证拒绝；日历价不能证明明细或认证可用。过去失败仍保留在历史格中，重新保存的会话不继承保存前的拒绝。新的明确拒绝可以结束待验证状态，允许立即重新登录。

空结果、超时、普通 `444/非法链接/会话门拒` 不是账号失效证据。途牛国际聚合正常完成并明确返回空列表，可作为无航班结果，不能触发登录失败或整圈重试。

## 保存与采集

浏览器五渠道共用当前启动生效的绝对会话目录，每个渠道拥有独立 profile。App 渠道不用浏览器 profile，走「登录快照」（见 `docs/APP_CHANNELS.md`）。同一 profile 的网页登录和浏览器采集互斥，忙碌错误不归类为认证失败。修改会话目录后仍按既有启动级约定，在重启后统一生效。

### 「同一 profile」不等于「站点每个入口都认」

一个 profile 能同时装同一个账号的多套 cookie，所以槽位按渠道算、不按端面拆。
但站点的**入口页可能按面单独要登录**，这属于渠道的登录墙，不是我们的会话丢了：

| 渠道 | 实测（2026-11-01） | 采集侧 |
| --- | --- | --- |
| 飞猪 | PC（`.fliggy.com`）与 H5（`.m.taobao.com`）是两个域，**确实不共享** → 拆成 `fliggy` / `fliggy_h5` 两格 | 两套采集器各自用对应 profile |
| 同程 | `ly.com` 父域 cookie 覆盖 www/m/tiflight，国际 H5 显示「退出」 | 单 profile 即可 |
| 途牛 | 同一 profile 里有**两套 cookie 族**：www/passport 面 `tuniuuser_*`/`TDC_itoken`/`ssoUser`，m. 面 `muser`/`TUNIUmuser`/`isLogined`；用户现场「国内账号还在、切国际航线要求再登录」 | 单 profile 出数；国际通道遇到 `710114/needLogin` 会记 `H5/API login`（登录门），不当通道故障 |

因此登录卡上的「已保存 / 已核验」只说明**该槽位核验过**，不承诺站点的每个入口都放行。

“我已登录完成”只提交保存请求。后台完成 `storage_state` 导出、浏览器关闭和原子文件发布后，才进入待验证状态，并使相关采集器缓存失效。保存失败保留之前的快照，不显示虚假的保存成功。

`session-state.json` 位于对应渠道的本机会话目录，包含敏感会话资料，不应提交、打包、写入页面或导出证据。`saved_at` 仅在明确登录保存成功时更新。已有 profile 无快照时可以迁移已有会话，迁移不会制造新的登录时间或认证成功。

浏览器重开时补回快照中有效且 profile 缺失的会话 Cookie。途牛国内和国际 HTTP 请求读取当前快照，遵守域、路径、有效期、Secure 和 host-only 约束；追踪 Cookie 只补缺。去哪儿 HTTP 回退拒绝早于最新登录保存的 token 快照。

## 页面刷新

当前状态独立于报价 ETag 刷新；报价返回 304 时，健康和脉冲仍更新。可见页面每两秒检查当前认证状态，多个页面共用在途请求；强制刷新有请求序号保护，晚到旧响应不能覆盖新状态。

检索条分别显示当前查询的业务产物与共享会话状态，不从“没有航班”推出“请重新登录”。航线与出发日期限制业务产物范围，认证提示的适用范围及时间可从说明查看。

## 验证

针对性回归覆盖原子保存与失败、同 profile 互斥、旧 profile 迁移、Cookie 作用域、新保存后的缓存失效、认证证据时间及范围、304 独立刷新、跨页状态和请求乱序。测试使用临时 profile、离线 HTTP 替身及浏览器拦截，不能替代真实渠道认可当前会话的验证。

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONIOENCODING='utf-8'
python -m pytest tests/test_channel_session_bridge.py tests/test_channel_health_evidence.py tests/test_channel_status.py tests/test_channel_ui_status.py -q
```

> 认证分类的用例实际就在上列 `test_channel_status.py` / `test_channel_ui_status.py` 里；早期草案点名的 `tests/test_channel_auth_classification.py` **从未创建**（2026-10-27 核对），已从命令中移除。

国际路径的渠道能力不齐，**不要一概而论**（2026-10-27 核实）：
- **飞猪国际**：已有真实列表路径（`sjipiao.fliggy.com` PC 列表，`_parse_intl_items` 解析，账本记为「sjipiao.fliggy.com 国际列表」），日历仅作补充。
- **同程国际**：仍以低价日历为主（`miflightapi/ts/calendar`，城市级最低价）；列表明细双端强制登录 + as-sdk 签名，属挂账能力缺口。
认证判定纪律不变：日历成功不得包装成明细成功，也不得因缺明细而误报登录失效。
