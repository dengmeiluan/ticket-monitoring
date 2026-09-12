# 安全策略

## 数据与凭据边界

- 你的全部凭据（钉钉 Webhook/加签密钥、ntfy 主题、阿里云 AccessKey）**只存本机 `config.yaml`**，该文件已被 `.gitignore` 拦截，永不入库。
- 采集的价格数据存本机 `data/prices.db`（SQLite），日志在 `logs/`。
- 控制台只监听 `127.0.0.1`，不暴露公网。
- 外发数据仅两类：推送消息发往你自己配置的钉钉/ntfy/阿里云通道；明细总表与走势图 PNG 上传至公共图床（freeimage.host）以获得钉钉可显示的直链——**图片内容为聚合票价，不含你的凭据**。如不接受，可在配置移除图床 provider（推送自动回退文字明细）。
- 演示模式 / 在线演示站均为合成数据，配置页不回读真实凭据。

## 报告漏洞

请勿公开 issue 披露可被利用的问题。通过 GitHub [Security Advisories](https://github.com/dengmeiluan/ticket-monitoring/security/advisories/new) 私密报告，或私信仓库所有者。预计 7 天内回应。

## 已知取舍

- 项目以「个人本机自托管」为威胁模型：控制台无鉴权（仅绑定回环地址）。请不要手动改绑 0.0.0.0 后暴露公网；如需远程访问，建议走 SSH 隧道或 Tailscale。
- 图床直链公开可访问，任何拿到 URL 的人可见该张票价图。
