# 安全策略

## 数据与凭据边界

- 你的全部凭据（钉钉 Webhook/加签密钥、ntfy 主题、阿里云 AccessKey）**只存本机 `config.yaml`**，该文件已被 `.gitignore` 拦截，永不入库。
- 采集的价格数据存本机 `data/prices.db`（SQLite），日志在 `logs/`。
- 控制台**默认只监听 `127.0.0.1`**（`web.host` 缺省值，`webui.py:457`），不暴露公网；但你可以在配置里改绑 `0.0.0.0` 让局域网可达（手机看推送详情页的前提）——**改绑后无鉴权即等于对局域网开放**，见下方「已知取舍」。
- 外发数据仅两类：推送消息发往你自己配置的钉钉/ntfy/阿里云通道；明细总表与走势图 PNG 上传至**你选择的**公共图床以获得钉钉可显示的直链——**图片内容为聚合票价，不含你的凭据**。
  - 可选 provider（`report.py`）：`ghimg`（GitHub 图库，需仓库 + Token，**当前推荐**）、`smms`、`freeimage`（freeimage.host，**端点已被对方封禁**：全量 400/111，代码内置连败 ≥3 自动熔断并每 10 次重探，仅作历史兼容保留）。凭据同样只存本机 `config.yaml`，已由 `.gitignore` 拦截。
    - `smms`：代码注释定性为「官方停止活跃更新，不推荐」（`report.py::upload_chart` docstring），仍可用但非推荐路径。
    - `ghimg` 自身也有熔断：连续失败后 `_GH_FAIL_COOLDOWN_S = 600`（10 分钟）内直接跳过、交文本兜底，成功即清零（`report.py:2081`）。
  - 三个 provider 的直链都是**公开可访问**的；如不接受，可在配置移除图床 provider（推送自动回退文字明细）。
- 演示模式 / 在线演示站均为合成数据，配置页不回读真实凭据。

## 报告漏洞

请勿公开 issue 披露可被利用的问题。通过 GitHub [Security Advisories](https://github.com/dengmeiluan/ticket-monitoring/security/advisories/new) 私密报告，或私信仓库所有者。预计 7 天内回应。

## 已知取舍

- 项目以「个人本机自托管」为威胁模型：控制台无鉴权（仅绑定回环地址）。请不要手动改绑 0.0.0.0 后暴露公网；如需远程访问，建议走 SSH 隧道或 Tailscale。
- 图床直链公开可访问，任何拿到 URL 的人可见该张票价图。
