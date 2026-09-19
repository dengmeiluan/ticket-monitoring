"""消息推送：钉钉群机器人（加签） / Server酱（sct.ftqq.com）/ Windows 系统弹窗"""
import base64
import hashlib
import hmac
import json
import logging
import os
import re as _re
import time
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Optional

import httpx


class _HeartbeatBackoff:
    """未达标心跳退避（v1.5.50，HANDOFF §9.3 收口）：钉钉 -1「系统繁忙」
    占 push_history 失败大头（实测 90%），每 15 分钟重推同语义心跳自身
    就是限流放大器。连败 ≥HB_BACKOFF_AFTER 轮后心跳跳过、每
    HB_PROBE_EVERY 轮放行一次探测（≈ 每小时 1 探）。

    跳过轮必须计入连败：否则退避期不再调 send、streak 冻在阈值，
    连败弹窗（≥8 每 8 轮升级）永远到不了——「故障必须被看见」断档。

    入闸范围由调用方（alerter._heartbeat_gate）结构性保证：达标轮与
    回落出线轮不入闸（必达不可吞）；状态存进程内存不持久化——重启后
    首轮心跳本身就是合法探测，陈旧退避态反而会吞掉已自愈通道的心跳。
    """

    HB_BACKOFF_AFTER = 6   # 连败 6 轮（15min/轮 ≈ 1.5h）起退避
    HB_PROBE_EVERY = 4     # 退避中每 4 个心跳轮放行 1 次探测

    def heartbeat_allow(self) -> bool:
        streak = getattr(self, "_fail_streak", 0)
        if streak < self.HB_BACKOFF_AFTER:
            self._hb_skip = 0
            return True
        self._hb_skip = getattr(self, "_hb_skip", 0) + 1
        if self._hb_skip % self.HB_PROBE_EVERY == 0:
            return True
        self._fail_streak = streak + 1
        return False


def _append_push_history(title: str, desp: str, ok: bool) -> None:
    """推送历史存档（JSONL 追加，与钉钉通道 logs/push_history.jsonl 同
    文件同格式）：ServerChan 曾成功/失败都不落盘，控制台「推送记录」
    对本通道失明（v1.5.50 补齐）。"""
    try:
        os.makedirs("logs", exist_ok=True)
        with open("logs/push_history.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(
                {"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 "ok": ok, "ch": "serverchan", "title": title, "desp": desp},
                ensure_ascii=False) + "\n")
    except Exception:
        pass


class ServerChanNotifier(_HeartbeatBackoff):
    """Server 酱·Turbo 版：https://sct.ftqq.com/

    免费额度：每日 5 条；超出付费。
    """

    ENDPOINT_TPL = "https://sctapi.ftqq.com/{key}.send"

    def __init__(self, send_key: str, logger: logging.Logger,
                 channel: Optional[str] = None):
        self.send_key = send_key.strip()
        self.logger = logger
        self.channel = channel  # 可指定推送通道，不填默认
        self._fail_streak = 0   # 连败自监控（v1.5.49 与钉钉通道同权）

    def send(self, title: str, desp: str = "", at_mobiles=None,
             is_at_all: bool = False, launch: str = "") -> bool:
        # at_mobiles/is_at_all/launch 收下即忽略：与钉钉/ntfy 通道签名
        # 对齐（alerter 统一按 send(title, desp, at_mobiles=…) 调用），
        # Server 酱无 @/@all 能力——此前缺形参，选中本通道即整轮
        # TypeError 断推
        if not self.send_key:
            self.logger.debug("Server酱 SendKey 未配置，跳过推送")
            return False
        url = self.ENDPOINT_TPL.format(key=self.send_key)
        # desp 按 utf-8 字节截断（与钉钉 18000 同法）：上限按字符切曾让
        # 中文长文超服务端字节限被整体拒绝（v1.5.41 与钉钉侧对齐）
        desp_b = desp.encode("utf-8")[:31800].decode("utf-8", "ignore")
        payload = {
            # 限60字符
            "title": title[:60],
            # 支持 markdown
            "desp": desp_b,
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
                    if self._fail_streak:
                        self.logger.info(
                            "Server酱 推送恢复（此前连续失败 %d 轮）",
                            self._fail_streak)
                    self._fail_streak = 0
                    self.logger.info("Server酱 推送成功: %s", title)
                    _append_push_history(title, desp, True)
                    return True
                self.logger.warning("Server酱 推送失败 code=%s body=%s",
                                    code, body[:200])
                self._fail_streak += 1
                _append_push_history(title, desp, False)
                self._maybe_streak_toast(code)
                return False
        except Exception as e:
            self.logger.warning("Server酱 推送异常: %s", e)
            self._fail_streak += 1
            _append_push_history(title, desp, False)
            self._maybe_streak_toast("EXC")
            return False

    def _maybe_streak_toast(self, code) -> None:
        """连败达阈值经本机弹窗浮出（v1.5.49 与钉钉同款）：build_notifier
        里 Server酱与钉钉二选一为主通道，钉钉有连败弹窗而本通道曾只有
        日志——key 失效/欠费真断推时「告警系统自身的故障」无人看见。"""
        if self._fail_streak >= 8 and self._fail_streak % 8 == 0:
            _channel_streak_toast(
                self.logger, "Server酱",
                f"Server酱文本推送已连续 {self._fail_streak} 轮失败"
                f"（code={code}）。若微信同样收不到，请检查 SendKey/"
                "付费额度/通道设置。")


class DingTalkNotifier(_HeartbeatBackoff):
    """钉钉群自定义机器人：Webhook + 加签（HMAC-SHA256）。

    文档：https://open.dingtalk.com/document/robots/custom-robot-access
    markdown 消息有 18000 字节限制。
    """

    def __init__(self, webhook: str, logger: logging.Logger,
                 secret: str = ""):
        self.webhook = webhook.strip()
        self.secret = (secret or "").strip()
        self.logger = logger
        # 最近一次响应的钉钉 errcode（-1=幽灵送达信号，上层防重发用；
        # 网络异常时置 None 防陈旧值误判）
        self.last_errcode = None
        # 连续失败轮数（连败自监控用，成功即清零）
        self._fail_streak = 0

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
        text = desp or title or ""
        # 钉钉 18000 上限按 UTF-8 字节计（中文 3 字节/字，按字符数判
        # 会漏判：近万字中文 desp 实际已近 3 万字节，原样发出被网关拒收）
        if len(text.encode("utf-8")) > 18000:
            # 截断回退：优先落在最后一个完整段落边界；若边界太靠前，
            # 再回退到最后一个图链起点之前——![走势](url) 是纯 ASCII，
            # 恰在 18000 处硬切会产出语法完整却指向不存在资源的死链
            # （比坏 markdown 更隐蔽）。截断必须留痕：丢的尾段可能含
            # 对账行/达标命中，静默丢失曾无从排查；v1.5.40 起消息内
            # 也留痕（⚠️ 已截断尾注），且链接全被切掉时补控制台指引
            # ——用户侧「这期没链接」曾无从解释
            raw_b = len(text.encode("utf-8"))
            cut_b = text.encode("utf-8")[:17900]
            img = cut_b.rfind(b"![")
            edge = cut_b.rfind(b"\n\n")
            if img > 6000:
                cut_b = cut_b[:img]
            elif edge > 12000:
                cut_b = cut_b[:edge]
            note = "\n\n⚠️ 内容超长已截断"
            if b"](http" not in cut_b:
                note += "，完整详情见控制台"
            cut_b += note.encode("utf-8")
            self.logger.warning(
                "钉钉 desp 超上限截断 %d→%d 字节（尾段丢弃）",
                raw_b, len(cut_b))
            text = cut_b.decode("utf-8", "ignore")
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": (title or "机票监控")[:60],
                "text": text,
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
                f.write("<!-- title: %s -->\n<!-- saved: %s -->\n%s" % (
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
            # 网络异常未收到 errcode，必须清掉上轮残留（如 -1）：日报落账
            # 据 last_errcode==-1 判「幽灵送达按已推」——本轮根本没发出去，
            # 残留 -1 会把当日日报静默吞掉且不再重试
            self.last_errcode = None
            # 网络异常同样计入连败：持续断网时只有本 WARNING 无弹窗，
            # 「故障必须被看见」在主通道上不留死角
            self._fail_streak += 1
            return False
        ok = obj.get("errcode") == 0
        # 留痕 errcode：钉钉 -1「系统繁忙」是幽灵送达（报错但消息已入群），
        # 上层（日报落账等）据此决定不重发——内容固定的消息重试=重复轰炸
        self.last_errcode = obj.get("errcode")
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
            if self._fail_streak:
                self.logger.info("钉钉推送恢复（此前连续失败 %d 轮）",
                                 self._fail_streak)
            self._fail_streak = 0
            self.logger.info("钉钉推送成功: %s", title)
            return True
        self._fail_streak += 1
        self.logger.warning(
            "钉钉推送失败 code=%s（单发不重试，下轮自然补）: %s",
            obj.get("errcode"), body[:200])
        # 连败自监控（v1.5.43）：-1 历史多为幽灵送达，但若真断推，
        # 钉钉是唯一文本通道且服务端无法区分两种形态——连败达阈值经
        # 本机弹窗浮出（告警系统自身的故障必须被看见，v1.5.7 原则
        # 补齐主通道缺口）。每 8 轮（15 分钟轮约 2 小时）提醒一次
        if self._fail_streak >= 8 and self._fail_streak % 8 == 0:
            self._streak_toast(self._fail_streak, obj.get("errcode"))
        return False

    def _streak_toast(self, streak: int, code) -> None:
        """连败本机弹窗（v1.5.49 抽共用 _channel_streak_toast）：
        用户见弹窗即可对照群聊分辨「幽灵送达」与「真断推」。"""
        _channel_streak_toast(
            self.logger, "钉钉",
            f"钉钉文本推送已连续 {streak} 轮失败（code={code}）。"
            "若群里同样收不到消息，请检查机器人 webhook/加签/限流设置。")


def _channel_streak_toast(logger: logging.Logger, channel: str, body: str):
    """文本通道连败本机弹窗（v1.5.49 单源，钉钉/Server酱共用）：WinToast
    同法零依赖。失败静默——告警系统自身不得再炸。"""
    try:
        import base64 as _b64
        import subprocess
        script = WindowsToastNotifier._script(f"{channel}推送通道异常", body, "")
        enc = _b64.b64encode(script.encode("utf-16-le")).decode()
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-EncodedCommand", enc],
            timeout=20, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, check=False)
    except Exception as e:
        logger.warning("[连败自监控] 弹窗失败: %s", e)


def _is_legend_line(ln: str) -> bool:
    """图例行兜底识别（v1.5.48 emoji 计数式）：剥引用块 `>` 后档位
    emoji（🎯🟩🟨）计数 ≥2 即判图例——正文任何行至多 1 个档位点
    （KPI 行点前置 1 个、hits 行用 🔥 不入计、建议行无点、仪表条行
    另有独立过滤）。旧双词识别（「破线+超线」「破线+达标」）锚死
    现役措辞，图例降级丢段/未来改词即静默漏进电话/弹窗。"""
    t = ln.lstrip("> ").strip()
    return sum(t.count(e) for e in "🎯🟩🟨") >= 2


def _alert_body(desp: str) -> str:
    """强提醒通道（弹窗/电话短信）的正文瘦身：弹窗一闪而过，
    主通道专用的「图例/时刻」说明行在弹窗里是噪音——现行聚合头行
    「> ⏱ 22:38 🎯达标 🟩破线 🟨擦边 无标超线」（引用块行首是 `>`，
    startswith("⏱") 恒不中）与纯仪表条行「🟩🟩🟩🟩🟩」一律滤除，
    旧措辞（距达标/进度条 =/数据截至）兼容保留，首屏只留航线价格
    与操作建议。"""
    def _skip(ln: str) -> bool:
        # 结构化前缀判定先剥引用块 `>`（旧 lstrip 不剥 `>`，头行
        # 「> ⏱ …」恒漏网，靠措辞子串兜底——图例超宽降级丢「 无标超线」
        # 时子串双词识别失效、图例直进电话/弹窗）；⏳ 空窗/⚠️ 运维
        # 对账行同属弹窗噪音（v1.5.43 收口）
        t = ln.lstrip("> ").strip()
        if t.startswith(("⏱", "⏳", "⚠️", "⚠")):
            return True
        if ("距达标" in ln or "进度条 =" in ln or "数据截至" in ln):
            return True
        # 图例行兜底（v1.5.48 emoji 计数式）：图例措辞再变/降级丢段
        # 均可识别（≥2 档位点=图例），不再耦合「破线+超线」字面
        if _is_legend_line(ln):
            return True
        # 纯仪表条行（只由五格方块/分隔符组成）：电话播报读不出颜色
        if any(c in t for c in "🟩🟨🟦⬜🟥") and not _re.sub(
                r"[🟩🟨🟦⬜🟥\s|]", "", t):
            return True
        return False

    lines = [ln for ln in (desp or "").splitlines() if not _skip(ln)]
    return chr(10).join(lines)


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
             at_mobiles: list = None, is_at_all: bool = False,
             launch: str = "") -> bool:
        if not self.topic:
            return False
        body = _alert_body(desp or title)
        body = _re.sub(r"!\[[^\]]*\]\([^)]*\)", "[图]", body)
        # markdown 链接还原「文字: url」：ntfy 自动链接化裸 URL，剥壳后
        # 手机通知栏不再残留 [文字](url) 原始记号
        body = _re.sub(r"\[([^\]]*)\]\(([^)]*)\)", r"\1: \2", body)
        body = _re.sub(r"[#>*`]", "", body).strip()
        # 截断避让 URL（v1.5.46）：600 字符硬截曾落在 URL 中段——通知栏
        # 链接可点但必死的半截链。在完整文本上判定截点是否落入 URL 内，
        # 是则回退到链接前
        _full = body
        _cut = body[:600]
        for _m in _re.finditer(r"https?://\S+", body):
            if _m.start() >= len(_cut):
                break
            if len(_cut) < _m.end():
                _cut = body[:_m.start()].rstrip()
                break
        body = _cut or title
        # 截断留痕（v1.5.47 与钉钉「⚠️ 已截断」纪律对齐）：回退后其后
        # 整段（含后续命中行的渠道链接）曾静默丢弃，读者以为只有这些
        if len(body) < len(_full):
            _tail = "…（已截断"
            _n = _full.count("🔥")
            if _n:
                _tail += f"，共{_n}条命中"
            body += _tail + "，完整内容见钉钉/详情页）"
        try:
            # JSON body 模式：标题含中文/emoji（HTTP header 仅 latin-1 会炸）
            # click：通知级点击跳转（此前手机点 ntfy 通知无任何反应）
            r = httpx.post(
                self.server,
                json={
                    "topic": self.topic,
                    "title": (title or "机票监控")[:120],
                    "message": body,
                    "priority": self.priority,
                    "tags": ["rotating_light", "bell"],
                    **({"click": launch} if launch else {}),
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
            if _re.fullmatch(r"[🟦⬜🟩🟥🟨\s|]+", ln):
                continue                       # 仪表条/纯符号行（🟨 曾漏剥直进弹窗）
            if ln.startswith(("⏱", "⏳", "⚠")):
                continue                       # 时间戳/空窗/运维对账行（弹窗噪音）
            if ("进度条 =" in ln or "去哪儿查看" in ln
                    or "查看详情" in ln or "完整详情" in ln
                    or "查现价" in ln or "查价" in ln):
                continue                       # 图例/跳转行（弹窗本身就是提醒）
            # 四档图例行（🎯达标 🟩破线 🟨擦边 无标超线）：emoji 计数
            # 式识别（≥2 档位点=图例，v1.5.48）——曾按「破线+达标」双词
            # 同现，耦合措辞长度的教训（超宽降级丢段即整行漏进弹窗）
            if _is_legend_line(ln):
                continue
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
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive",
                 "-EncodedCommand", enc],
                timeout=20, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, check=False)
            # 退出码非 0 = PS 脚本失败（AUMID 未注册等）：如实报 False，
            # 此前无条件 return True 把哑弹报成功，失败通道无法浮出水面
            if proc.returncode != 0:
                self.logger.warning("[WinToast] 弹窗脚本退出码 %s: %s",
                                    proc.returncode, title[:50])
                return False
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
        body_txt = _alert_body(desp or title)
        body_txt = _re.sub(r"!\[[^\]]*\]\([^)]*\)", "[图]", body_txt)
        # 剥链接保文字（v1.5.46 对齐 WinToast _plain 策略）：裸 URL 曾
        # 原文进短信——长 OTA 链接白占 900 字符额度且不可点
        body_txt = _re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", body_txt)
        body_txt = _re.sub(r"https?://\S+", "", body_txt)
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
