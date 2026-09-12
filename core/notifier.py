"""消息推送：钉钉群机器人（加签） / Server酱（sct.ftqq.com）/ Windows 系统弹窗"""
import base64
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Optional

import httpx


class ServerChanNotifier:
    """Server 酱·Turbo 版：https://sct.ftqq.com/

    免费额度：每日 5 条；超出付费。
    """

    ENDPOINT_TPL = "https://sctapi.ftqq.com/{key}.send"

    def __init__(self, send_key: str, logger: logging.Logger,
                 channel: Optional[str] = None):
        self.send_key = send_key.strip()
        self.logger = logger
        self.channel = channel  # 可指定推送通道，不填默认

    def send(self, title: str, desp: str = "") -> bool:
        if not self.send_key:
            self.logger.debug("Server酱 SendKey 未配置，跳过推送")
            return False
        url = self.ENDPOINT_TPL.format(key=self.send_key)
        payload = {
            # 限60字符
            "title": title[:60],
            # 支持 markdown
            "desp": desp[:32000],
        }
        if self.channel:
            payload["channel"] = self.channel

        data = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode("utf-8", "ignore")
                obj = json.loads(body)
                code = obj.get("code", -1)
                if code == 0:
                    self.logger.info("Server酱 推送成功: %s", title)
                    return True
                self.logger.warning("Server酱 推送失败 code=%s body=%s",
                                    code, body[:200])
                return False
        except Exception as e:
            self.logger.warning("Server酱 推送异常: %s", e)
            return False


class DingTalkNotifier:
    """钉钉群自定义机器人：Webhook + 加签（HMAC-SHA256）。

    文档：https://open.dingtalk.com/document/robots/custom-robot-access
    markdown 消息有 18000 字节限制。
    """

    def __init__(self, webhook: str, logger: logging.Logger,
                 secret: str = ""):
        self.webhook = webhook.strip()
        self.secret = (secret or "").strip()
        self.logger = logger

    def _signed_url(self) -> str:
        url = self.webhook
        if self.secret:
            ts = str(round(time.time() * 1000))
            string_to_sign = f"{ts}\n{self.secret}"
            sign = urllib.parse.quote_plus(base64.b64encode(
                hmac.new(self.secret.encode("utf-8"),
                         string_to_sign.encode("utf-8"),
                         digestmod=hashlib.sha256).digest()))
            url = f"{url}&timestamp={ts}&sign={sign}"
        return url

    def send(self, title: str, desp: str = "",
             at_mobiles: list = None, is_at_all: bool = False) -> bool:
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": (title or "机票监控")[:60],
                "text": (desp or title or "")[:18000],
            },
        }
        at = {}
        if at_mobiles:
            at["atMobiles"] = [str(m).strip() for m in at_mobiles if str(m).strip()]
        if is_at_all:
            at["isAtAll"] = True
        if at:
            payload["at"] = at
        # 严格单发，永无重试（用户明确要求杜绝重发）：钉钉 -1 存在
        # 幽灵送达（报错但消息已入群），任何第二次发送都可能造成重复。
        # -1 即放弃本轮，15 分钟后下轮心跳自然补；达标场景电话/ntfy
        # 通道完全独立于钉钉，关键警报不依赖本通道。
        try:
            import os
            os.makedirs("debug", exist_ok=True)
            with open("debug/last_push.md", "w", encoding="utf-8") as f:
                f.write("<!-- title: %s %s -->\n%s" % (
                    title, datetime.now().strftime("%H:%M:%S"), desp))
        except Exception:
            pass
        try:
            r = httpx.post(self._signed_url(), json=payload,
                           timeout=10, trust_env=False)
            body = r.text
            obj = r.json()
        except Exception as e:
            self.logger.warning("钉钉推送异常: %s", e)
            return False
        ok = obj.get("errcode") == 0
        # 推送历史存档（JSONL 追加）：控制台"推送记录"随时回看群里收到过什么
        try:
            import os
            os.makedirs("logs", exist_ok=True)
            with open("logs/push_history.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(
                    {"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                     "ok": ok, "title": title, "desp": desp},
                    ensure_ascii=False) + "\n")
        except Exception:
            pass
        if ok:
            self.logger.info("钉钉推送成功: %s", title)
            return True
        self.logger.warning(
            "钉钉推送失败 code=%s（单发不重试，下轮自然补）: %s",
            obj.get("errcode"), body[:200])
        return False


class NtfyNotifier:
    """ntfy.sh 强提醒通道（达标专用）：手机装 ntfy App 订阅同名 topic，
    即可获得系统级弹窗 + 铃声 + 免打扰穿透（priority=max）——
    自定义钉钉机器人无法打电话/发 DING，这是 webhook 体系内最接近的强提醒。"""

    def __init__(self, topic: str, logger: logging.Logger,
                 server: str = "https://ntfy.sh", priority: int = 5):
        self.topic = (topic or "").strip()
        self.server = (server or "https://ntfy.sh").rstrip("/")
        self.priority = max(1, min(5, int(priority or 5)))
        self.logger = logger

    def send(self, title: str, desp: str = "",
             at_mobiles: list = None, is_at_all: bool = False) -> bool:
        if not self.topic:
            return False
        import re as _re
        body = _re.sub(r"!\[[^\]]*\]\([^)]*\)", "[图]", desp or title)
        body = _re.sub(r"[#>*`]", "", body).strip()[:600] or title
        try:
            # JSON body 模式：标题含中文/emoji（HTTP header 仅 latin-1 会炸）
            r = httpx.post(
                self.server,
                json={
                    "topic": self.topic,
                    "title": (title or "机票监控")[:120],
                    "message": body,
                    "priority": self.priority,
                    "tags": ["rotating_light", "bell"],
                }, timeout=15, trust_env=False)
            ok = 200 <= r.status_code < 300
            if ok:
                self.logger.info("ntfy 强提醒已发送: %s", title)
            else:
                self.logger.warning("ntfy 发送失败 %s: %s",
                                    r.status_code, r.text[:120])
            return ok
        except Exception as e:
            self.logger.warning("ntfy 发送异常: %s", e)
            return False


class WindowsToastNotifier:
    """Windows 10+ 系统右下角 Toast 通知（零依赖：经系统自带 PowerShell 调 WinRT）。

    达标强提醒的本机触达通道：无需联网、无需任何账号，人在电脑前即见即点。
    脚本经 -EncodedCommand（UTF-16LE Base64）传输——中文零乱码、引号零转义风险。
    任何失败静默降级（记日志），绝不影响主推送链路。"""

    # PowerShell 的已注册 AUMID（自定义 AppId 在未注册系统上会抛异常）
    APPID = ("{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}"
             "\\WindowsPowerShell\\v1.0\\powershell.exe")

    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.available = (os.name == "nt")

    @staticmethod
    def _ps_str(s: str) -> str:
        """PS 单引号字面量：内部单引号翻倍转义。"""
        return "'" + str(s).replace("'", "''") + "'"

    @classmethod
    def _script(cls, title: str, body: str, launch: str = "") -> str:
        launch_attr = ""
        if launch:
            # 点击通知 → 浏览器打开单条详情页（protocol 激活）
            launch_attr = (f"$x.DocumentElement.SetAttribute('activationType',"
                           f"'protocol')\n"
                           f"$x.DocumentElement.SetAttribute('launch',"
                           f"{cls._ps_str(launch)})\n")
        return (
            "[Windows.UI.Notifications.ToastNotificationManager, "
            "Windows.UI.Notifications, ContentType = WindowsRuntime] > $null\n"
            "$x=[Windows.UI.Notifications.ToastNotificationManager]"
            "::GetTemplateContent("
            "[Windows.UI.Notifications.ToastTemplateType]::ToastText04)\n"
            f"{launch_attr}"
            "$x.GetElementsByTagName('text').Item(0).AppendChild("
            f"$x.CreateTextNode({cls._ps_str(title)})) > $null\n"
            "$x.GetElementsByTagName('text').Item(1).AppendChild("
            f"$x.CreateTextNode({cls._ps_str(body)})) > $null\n"
            f"$app={cls._ps_str(cls.APPID)}\n"
            "$t=[Windows.UI.Notifications.ToastNotification]::new($x)\n"
            "[Windows.UI.Notifications.ToastNotificationManager]"
            "::CreateToastNotifier($app).Show($t)\n")

    @staticmethod
    def _plain(text: str, limit: int) -> str:
        """去 markdown 取纯文本：链接留文字（钉钉 KPI 行是 [**直飞 ￥x**](url)，
        原样进弹窗会带一长串 URL）、加粗/图片/仪表条/图例行剔除，
        行间以「；」相连。弹窗第二行可见高度有限，信息密度优先。"""
        import re as _re
        t = _re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text or "")
        t = _re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
        lines = []
        for ln in t.splitlines():
            ln = _re.sub(r"^[#>\-*\s]+", "", ln).strip().replace("**", "")
            if not ln:
                continue
            if _re.fullmatch(r"[🟦⬜🟩🟥\s|]+", ln):
                continue                       # 仪表条/纯符号行
            if ("进度条 =" in ln or "去哪儿查看" in ln
                    or "完整详情" in ln):
                continue                       # 图例/跳转行（弹窗本身就是提醒）
            lines.append(ln)
        return "；".join(lines)[:limit]

    def send(self, title: str, desp: str = "",
             at_mobiles: list = None, is_at_all: bool = False,
             launch: str = "") -> bool:
        """launch 非空时：点击通知经浏览器打开该链接（如单条达标详情页）。"""
        if not self.available:
            return False
        try:
            import subprocess
            body = self._plain(desp, 180) or self._plain(title, 120)
            script = self._script(title[:120], body, launch)
            enc = base64.b64encode(
                script.encode("utf-16-le")).decode()
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive",
                 "-EncodedCommand", enc],
                timeout=20, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, check=False)
            self.logger.info("[WinToast] 右下角通知已弹出: %s", title[:50])
            return True
        except Exception as e:
            self.logger.warning("[WinToast] 弹窗失败: %s", e)
            return False


def build_urgent_notifier(cfg: dict, logger: logging.Logger):
    """达标专用强提醒通道列表（与普通推送分开，心跳不会吵）：
    ntfy（系统级弹窗+铃声）与 aliyun（云监控事件→电话/短信）可并联。"""
    outs = []
    wt = (cfg or {}).get("win_toast", True)   # 缺省开启（Windows 本机弹窗）
    if isinstance(wt, dict):
        wt = wt.get("enabled", True)
    if wt and os.name == "nt":
        outs.append(WindowsToastNotifier(logger))
    nt = (cfg or {}).get("ntfy") or {}
    if nt.get("enabled") and (nt.get("topic") or "").strip():
        outs.append(NtfyNotifier(
            topic=nt["topic"], logger=logger,
            server=nt.get("server") or "https://ntfy.sh",
            priority=nt.get("priority", 5)))
    ay = (cfg or {}).get("aliyun") or {}
    if ay.get("enabled") and (ay.get("url") or "").strip() and ay.get("user"):
        outs.append(AliyunAlertNotifier(
            url=ay["url"], user=ay["user"], password=ay.get("password", ""),
            logger=logger, rule_name=ay.get("rule_name") or "机票监控"))
    return outs or None


class AliyunAlertNotifier:
    """阿里云云监控事件通知通道（达标专用）：CRITICAL 级事件经联系人组
    触达电话/短信——电话 DING 的免费替代（同事提供的告警通道）。
    仅达标即时触发一次（风暴连推不重复拨打）。"""

    def __init__(self, url: str, user: str, password: str,
                 logger: logging.Logger, rule_name: str = "机票监控"):
        self.url = url.strip()
        self.user = (user or "").strip()
        self.password = (password or "").strip()
        self.rule_name = rule_name
        self.logger = logger

    def send(self, title: str, desp: str = "",
             at_mobiles: list = None, is_at_all: bool = False) -> bool:
        import re as _re
        body_txt = _re.sub(r"!\[[^\]]*\]\([^)]*\)", "[图]", desp or title)
        body_txt = _re.sub(r"[#>*`\[\]]", "", body_txt).strip()[:900] or title
        try:
            # 中文全部 ASCII 转义传输（ensure_ascii），网关不可能解错编码；
            # JSON 解析后自动还原中文，短信不再乱码
            r = httpx.post(
                self.url,
                auth=(self.user, self.password),
                content=json.dumps(
                    {"ruleName": self.rule_name,
                     "title": (title or "机票监控达标")[:80],
                     "message": body_txt},
                    ensure_ascii=True).encode("ascii"),
                headers={"Content-Type": "application/json; charset=utf-8"},
                timeout=15, trust_env=False)
            ok = r.status_code == 200
            if ok:
                self.logger.info("阿里云电话/短信告警已受理: %s", title[:50])
            else:
                self.logger.warning("阿里云告警失败 %s: %s",
                                    r.status_code, r.text[:120])
            return ok
        except Exception as e:
            self.logger.warning("阿里云告警异常: %s", e)
            return False


def build_notifier(cfg: dict, logger: logging.Logger):
    """根据 notifier 配置块构造推送器；未配置则返回 None。钉钉优先。"""
    if not cfg:
        return None
    dt = (cfg.get("dingtalk") or {})
    if dt.get("enabled") and dt.get("webhook"):
        return DingTalkNotifier(
            webhook=dt["webhook"],
            logger=logger,
            secret=dt.get("secret", ""),
        )
    sc = (cfg.get("serverchan") or {})
    if sc.get("enabled") and sc.get("send_key"):
        return ServerChanNotifier(
            send_key=sc["send_key"],
            channel=sc.get("channel"),
        )
    return None
