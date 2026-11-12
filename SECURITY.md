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


## 不可信输入：别人给的压缩包（zip slip / 符号链接穿透）

> 一句话：**凡是别人给的 zip，只能走 `core/safezip.safe_extract()`**，不许直接
> `ZipFile.extractall()`。`tests/test_r1903_safezip_matrix.py` 扫全仓把这个钉死。

### 为什么要有这份策略

2026-11-14 社区安全报告（PR #17，作者 Shengcun-Scanner）指出：`core/update.py`
的 `apply()` 用 `z.extractall(tmp)` 解开**从 release 下载的升级包**，而成员名由发布方
决定。他的结论是 `../x` 或 `/x` 能写到缓存目录之外。

我们按"先量再改"的规矩实测（Python 3.11，Windows）：

| 成员名 | 落盘位置 | 结论 |
|---|---|---|
| `../escaped.txt` | `cache/escaped.txt` | **没逃逸**：CPython 的 `_extract_member` 会去掉 `..` 分量 |
| `/abs.txt` | `cache/abs.txt` | 没逃逸：前导分隔符被去掉 |
| `C:/evil.txt` | `cache/evil.txt` | 没逃逸：盘符被去掉 |
| `link -> /outside` + `link/pwned.txt` | 视平台 | **真向量**：`extractall` 不管软链，POSIX 上 `os.symlink` 无需特权 |

也就是说：报告的方向对、`../` 这条在 CPython ≥3.6 上已不可利用，**而符号链接才是能
真正逃出目标目录的那条路**——本项目正好发行 Linux/macOS 包，必须在 POSIX 上堵死。

### 判据（`core/safezip.py`）

1. **先全量校验、再落盘**：任一成员不安全 → 抛 `UnsafeArchiveError`，目标目录
   **一个字节都不写**（不会出现"写了一半才失败"的中间态）；
2. 拒绝：空名、绝对路径、Windows 盘符（`C:`）、UNC（`//host/share`）、
   **任何 `..` 分量**、解析后落在目标之外的路径；
3. 拒绝**符号链接**成员；fifo/字符设备/块设备/socket 等特殊成员同样拒绝
   （只看文件类型位 `mode & 0o170000`，只有权限位、没有类型位的普通成员照常放行）；
4. 目标位置**已存在软链**时也不顺着写；
5. 成员数上限 `max_entries`（默认 20 万）；解压后总字节上限 `max_total_bytes`
   默认**不限制**（避免误伤正常的大升级包），需要时显式传。

### 用到的地方

| 调用点 | 用途 |
|---|---|
| `core/update.py::apply()` | 升级包解压（经薄别名 `_safe_extract` 转发，保留历史调用名） |

新增"解压别人给的 zip"的地方，请直接用：

```python
import zipfile
from core.safezip import safe_extract

with zipfile.ZipFile(path) as z:
    written = safe_extract(z, dest)     # 失败抛 UnsafeArchiveError(RuntimeError)
```

压缩包**炸弹**（高压缩比、超大解压体积）不在默认拦截范围：需要时传
`max_total_bytes=`，或在下载阶段就核对体积与 SHA256。

### 与升级流程的关系

升级包的完整性仍以 **SHA256 校验 + 备份回滚**为准（`core/update.py`）；
解压防护只是"万一包本身是恶意的"这条兜底。两者都要，不能互相替代。

## 已知取舍

- 项目以「个人本机自托管」为威胁模型：控制台无鉴权（仅绑定回环地址）。请不要手动改绑 0.0.0.0 后暴露公网；如需远程访问，建议走 SSH 隧道或 Tailscale。
- 图床直链公开可访问，任何拿到 URL 的人可见该张票价图。
