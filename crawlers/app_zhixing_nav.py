# -*- coding: utf-8 -*-
"""智行首页操作：设置起降城市与日期，然后发起查询。

**只用文案锚点 + 结构相邻定位，不写死坐标**——坐标在不同分辨率/版本
下必变，而"机票查询按钮在首页下半部、城市在第二行"这类结构关系稳定。

流程（实测依据见 docs/APP_CHANNELS.md）：
  1. 回首页（app_stop + app_start，避免停在上次的列表页）
  2. 点出发城市 → 城市选择页 → 输入三字码/城市名 → 选第一项
  3. 点到达城市 → 同上
  4. 点日期 → 日历页 → 选目标日期
  5. 点「机票查询」

每一步都返回 (ok, detail)，调用方据此记 path_note，不猜。
"""
from __future__ import annotations

import re
import time

_NODE_RE = re.compile(
    r'text="([^"]*)"[^>]*(?:content-desc="([^"]*)")?[^>]*'
    r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')


class Node:
    __slots__ = ("text", "desc", "x1", "y1", "x2", "y2")

    def __init__(self, text, desc, x1, y1, x2, y2):
        self.text, self.desc = text, desc
        self.x1, self.y1, self.x2, self.y2 = x1, y1, x2, y2

    @property
    def cx(self):
        return (self.x1 + self.x2) // 2

    @property
    def cy(self):
        return (self.y1 + self.y2) // 2

    def __repr__(self):
        return f"Node({self.text!r},{self.cx},{self.cy})"


def nodes(xml: str):
    out = []
    for m in _NODE_RE.finditer(xml or ""):
        text = (m.group(1) or "").strip()
        desc = (m.group(2) or "").strip()
        if not text and not desc:
            continue
        out.append(Node(text, desc, int(m.group(3)), int(m.group(4)),
                        int(m.group(5)), int(m.group(6))))
    return out


def find(nodes_list, *cands, exact=True):
    """按文案找第一个节点；exact=False 时为包含匹配。"""
    for want in cands:
        for n in nodes_list:
            if exact and n.text == want:
                return n
            if not exact and want in n.text:
                return n
    return None


_NODE_TAG_RE = re.compile(r"<node\b[^>]*>")
_BOUNDS_RE = re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')


def edit_box(xml: str):
    """城市页的搜索输入框（页面上唯一的 EditText）。

    不能按文案找：实测 `find(ns, "搜索", "请输入城市", exact=False)` 命中
    的是页面上的「常去/历史搜索」标题（y=554），点它之后 input text 全部
    丢弃。国内热门城市恰好还列在下方，所以这条路一直"碰巧成功"，缺陷
    藏了很久——直到设国际城市（列表里没有）才暴露成「城市列表里找不到」。
    EditText 是结构事实，按 class 取，不猜文案。
    """
    for m in _NODE_TAG_RE.finditer(xml or ""):
        s = m.group(0)
        if "android.widget.EditText" not in s:
            continue
        b = _BOUNDS_RE.search(s)
        if b:
            return Node("", "", *[int(x) for x in b.groups()])
    return None


def city_result(xml: str, name: str, below: int = 0):
    """搜索结果区里第一个「城市名」行（在搜索框下沿 `below` 之下）。

    必须排除搜索框自身：输入后 EditText 的 text 就是 `name`，按文案
    `find()` 会先命中它——点它等于继续打字，「选完城市页面毫无变化」。
    """
    cands = [n for n in nodes(xml) if n.text == name and n.y1 >= below]
    if not cands:
        return None
    cands.sort(key=lambda n: n.y1)
    return cands[0]


# 国际单程表单的稳定标记（实测首页国内档没有这一行，国际档有）。
_INTL_FORM_MARK = "经济/超级经济舱"


def is_intl_form(xml: str) -> bool:
    return _INTL_FORM_MARK in (xml or "")


_HOME_MARK = "机票查询"


def _await_home(dev, timeout_s: float = 30.0, frames: int = 10) -> tuple:
    """等到一帧能看见首页表单（「机票查询」在）的页面。返回 (xml, ready)。

    冷启动实测：`app_start` 之后头几帧 `dump()` 全是空串（uiautomator
    服务还没起好），随后才出现首页。**空帧不等于"页面不是这样"**，
    所有按「某标记在不在」下结论的判据都必须先过这一关，否则会把
    「没取到页面」读成「功能不存在」——实测把档位判成了「已是国内档」，
    接着在还没渲染的首页上找城市行，整轮记成「找不到城市行」。

    同时也排除「停在别页」：城市选择页/日历弹层里也没有「机票查询」，
    拿它们判档位同样会得到「没有国际档标记」的假结论。

    **按帧数预算**（与 `set_flight_route` 同一策略，2026-11-04）：
    纯秒数在"整机被 5 个浏览器渠道拖住"时一帧要 ~20s，30s 只够 1–2 帧，
    会判「dump 连续为空」——看着像 uiautomator 挂了，其实只是慢。
    """
    deadline = time.time() + max(5.0, float(timeout_s))
    for _ in range(max(2, int(frames))):
        xml = dev.dump() or ""
        if _HOME_MARK in xml and "Search_Calendar_Dialog_Title" not in xml:
            return xml, True
        if time.time() > deadline:
            break
        time.sleep(2.0)
    return "", False


def select_mode(dev, intl: bool, log=None) -> tuple:
    """切到国际/国内档。

    智行首页「国内/国际」是两个不同的查询表单（国际档多出「返程日期」
    与「经济/超级经济舱」舱位行），城市选择页也随档位不同。不切档直接
    设国际城市，本渠道此前根本没有国际能力——而矩阵里这一格是空的
    （未验证），空着就说明没人跑过。

    已是目标档就直接返回，避免多点一次把表单重置。

    **空 dump 不能当"国内档"**：`is_intl_form("")` 是 False，而冷启动
    头 4 帧 dump 实测全是空串（uiautomator 还没起来）。按空串判「已是
    国内档」会直接跳过切档，接着去首页找城市行——而此时首页还没渲染，
    整轮就记成「设出发地失败：找不到城市行」，把「没取到页面」说成了
    「控件不存在」。所以先要求拿到首页，再判档位。
    """
    tag = "国际" if intl else "国内"
    xml, ready = _await_home(dev)
    if not ready:
        return False, "没取到首页（dump 连续为空），无法判断当前档位"
    if is_intl_form(xml) == bool(intl):
        return True, f"已是{tag}档"
    node = find(nodes(xml), tag)
    if node is None:
        return False, f"找不到「{tag}」标签"
    if not dev.tap(node.cx, node.cy):
        return False, f"点击「{tag}」标签失败"
    deadline = time.time() + 10
    while time.time() < deadline:
        time.sleep(1.5)
        page = dev.dump() or ""
        if not page:
            continue
        if is_intl_form(page) == bool(intl):
            return True, f"已切到{tag}档"
    return False, f"切到{tag}档后表单未切换（{_INTL_FORM_MARK} 未出现/未消失）"


def open_date_dialog(dev, log=None) -> tuple:
    """打开「选择日期」弹层（长窗口日历）。

    为什么要主动打开：首页日历条只覆盖约 8 天，而弹层是跨两个月的
    完整日历、每天明码标价（resource-id 里内嵌 ISO 日期）。对远期
    配置来说这是唯一能拿到价的入口。

    返回 (ok, detail)。失败不算致命——调用方可以退回首页日历条。

    刻意每次自己 dump：调用方手上的页面可能是"设航线之前"的旧帧，
    拿它定位日期入口会点到错的地方（省 5s 不如不错）。
    """
    xml = dev.dump()
    if not xml:
        return False, "未取到页面"
    if "Search_Calendar_Dialog_Title" in xml:
        return True, "已打开"

    trigger = None
    # 日期入口的文案有**两种格式**（2026-11-04 实测 fixtures）：
    #   中文：`11月16日`（首页日期行，更像"入口"）
    #   横线：`10-29` / `11-16`（日历条格子，fixture 里全是这种）
    # 原来只认中文格式，于是国际档首页只显示 `11-16` 时判「找不到日期入口」，
    # 长窗口日历打不开 → `明细页解析不出带价航班` → 整条国际航线没明细。
    # 优先取中文格式（它是"打开日历"的那一行）；没有才用横线格子。
    dash = None
    for n in nodes(xml):
        t = (n.text or "").strip()
        if re.fullmatch(r"\d{1,2}月\d{1,2}日", t):
            trigger = n
            break
        if dash is None and re.fullmatch(r"\d{1,2}-\d{1,2}", t):
            dash = n
    if trigger is None:
        trigger = dash
    if trigger is None:
        return False, "找不到日期入口（无 `N月N日` / `N-N` 文案）"
    if not dev.tap(trigger.cx, trigger.cy):
        return False, "点击日期失败"

    # 轮询代替固定 sleep(3)+单次 dump：弹层通常在 1–2s 出现，
    # 固定等 3s 只是保底；轮询能在出现后立刻继续，失败时也不早退。
    deadline = time.time() + 12
    while time.time() < deadline:
        time.sleep(0.8)
        xml = dev.dump()
        if "Search_Calendar_Dialog_Title" in xml:
            if log:
                try:
                    log.info("[nav] 已打开长窗口日历")
                except Exception:
                    pass
            return True, "已打开"
    return False, "日期弹层未出现"


def close_date_dialog(dev) -> bool:
    """关闭日历弹层（点右上角关闭按钮）。"""
    for m in re.finditer(r'<node[^>]*resource-id="Search_Calendar_Dialog_Close"'
                         r'[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
                         dev.dump() or ""):
        x = (int(m.group(1)) + int(m.group(3))) // 2
        y = (int(m.group(2)) + int(m.group(4))) // 2
        return bool(dev.tap(x, y))
    return False


def set_flight_route(dev, from_name: str, to_name: str, date_ymd: str,
                     log=None, stop_before_search: bool = False,
                     intl: bool = False) -> tuple:
    """设好起降与日期；stop_before_search=True 时停在首页不点查询。

    停在首页是为了先读「选择日期」长窗口日历——一旦点了「机票查询」
    进到列表页，日历入口就没了（实测列表页只有 8 天日期条）。
    """
    """在智行首页设置航线与日期并发起查询。返回 (ok, detail)。"""

    def say(msg):
        if log:
            try:
                log.info(msg)
            except Exception:
                pass

    dev.app_stop("cn.suanya.zhixing")
    time.sleep(1.5)
    if not dev.app_start("cn.suanya.zhixing"):
        return False, "启动 App 失败"

    # 轮询等首页，而不是固定 sleep。实测三个坑：
    #   ① 冷启动到首页可交互在 10–20s 波动（固定 8s 必失败）；
    #   ② 启动后**第一帧是上次残留的弹层**（124KB 日历层），
    #      第二帧才回到首页（63KB）——所以必须连续两帧都是首页
    #      才算稳定，否则会把残留弹层当成首页继续操作。
    #   ③ **整机被浏览器渠道拖慢时单帧 dump 能到 ~20s**（2026-11-03 实测：
    #      `app_qunar`/`app_zhixing` 同秒起跑，6 条航线并行，5 个浏览器
    #      渠道同时占 CPU）。60s 只够 3 帧，而"连续两帧首页"最少要 6 帧 →
    #      必然判失败。日志里 14 次「首页未就绪」全是这个形态。
    #
    # 所以预算改成**按帧数 + 自适应放宽**（与 qunar 城市页同一套办法）：
    # 最少 12 帧；若首帧耗时 >6s（说明整机很慢），总时长放宽到 150s。
    xml = ""
    deadline = time.time() + 90
    frames = 0
    _t_first = time.time()
    stable = 0
    while time.time() < deadline and frames < 14:
        frames += 1
        time.sleep(2.5)
        xml = dev.dump()
        if frames == 1 and (time.time() - _t_first) > 6:
            deadline = time.time() + 150      # 整机被拖慢：放宽总时长
        if "机票查询" in xml and "Search_Calendar_Dialog_Title" not in xml:
            stable += 1
            if stable >= 2:
                break
        else:
            stable = 0
    if stable < 2:
        # App 会恢复到上次停留的弹层/子页（实测：卡在「选择日期」透明
        # Activity）。按返回键退出去比反复重启有效——实测一次返回即可。
        # 退到 6 级：重载弹层可能是两层（日历 + 城市），4 级会差一步。
        for _ in range(6):
            dev.keyevent("KEYCODE_BACK")
            time.sleep(2)
            xml = dev.dump()
            if "机票查询" in xml:
                break
        else:
            return False, ("首页未就绪（等 %d 帧 / 约 %ds 并回退 6 级仍找不到"
                           "「机票查询」）" % (frames, int(time.time() - _t_first)))

    # 国际/国内是两个不同的表单：不切档就设国际城市，输入框里搜得到但
    # 首页城市位与结果页仍是国内那套，整轮白跑。切档放在设城市之前。
    ok, detail = select_mode(dev, intl, log=say)
    if not ok:
        return False, f"切换{'国际' if intl else '国内'}档失败：{detail}"
    say(f"[nav] {detail}")
    # 切档之后要重新读页面：空帧不能让 `_pick_city` 得出「找不到城市行」
    xml, ready = _await_home(dev, timeout_s=20)
    if not ready:
        return False, "设出发地失败：切档后没取到首页（dump 连续为空）"
    ns = nodes(xml)

    ok, detail = _pick_city(dev, ns, from_name, side="from", log=say)
    if not ok:
        return False, f"设出发地失败：{detail}"
    xml, ready = _await_home(dev, timeout_s=20)
    if not ready:
        return False, "设目的地失败：选完出发地后没取到首页（dump 连续为空）"
    ns = nodes(xml)
    ok, detail = _pick_city(dev, ns, to_name, side="to", log=say)
    if not ok:
        return False, f"设目的地失败：{detail}"

    xml, ready = _await_home(dev, timeout_s=20)
    if not ready:
        # 日期设不上不算致命，但没有页面就没法继续，如实报出来
        return False, "设日期失败：选完目的地后没取到首页（dump 连续为空）"
    ns = nodes(xml)
    ok, detail = _pick_date(dev, ns, date_ymd, log=say)
    if not ok:
        # 日期设不上不算致命：日历条覆盖范围有限，仍可用当前日期查询
        say(f"[warn] {detail}")

    if stop_before_search:
        # 关掉日期弹层（_pick_date 可能会打开它），留在首页
        close_date_dialog(dev)
        time.sleep(1)
        return True, "已设好航线（停在首页）"

    xml, ready = _await_home(dev, timeout_s=20)
    if not ready:
        return False, "查找「机票查询」失败：没取到首页（dump 连续为空）"
    ns = nodes(xml)
    btn = find(ns, "机票查询")
    if not btn:
        # 设城市/日期过程中可能进了子页没退回来（实测：日期选择会打开
        # 一个透明 Activity）。退一级再找，仍没有才判失败。
        dev.keyevent("KEYCODE_BACK")
        time.sleep(2)
        xml, ready = _await_home(dev, timeout_s=20)
        if not ready:
            return False, "查找「机票查询」失败：返回后仍没取到页面"
        ns = nodes(xml)
        btn = find(ns, "机票查询")
    if not btn:
        _dbg = [n.text for n in ns][:14]
        return False, f"找不到「机票查询」按钮（当前页文本：{_dbg}）"
    if not dev.tap(btn.cx, btn.cy):
        return False, "点击「机票查询」失败"
    time.sleep(12)
    return True, "已发起查询"


def _city_row(ns, side: str):
    """城市行：首页第二行左右两端各一个城市。

    实测首页布局：'上海'[74,472] 与 '北京'[826,472] 同一 y。判据是
    **同一 y 上有两个中文名**——按固定 y 带取最左/最右曾被国际档打过：
    国际表单多出的「返程日期」也在那条带里（cx=798，比窄城市名更靠右），
    目的地会选中「返程日期」。改成先找"同行有两个候选"的 y 再取两端。
    """
    cands = [n for n in ns
             if 2 <= len(n.text) <= 4
             and all("\u4e00" <= c <= "\u9fff" for c in n.text)]
    rows = {}
    for n in cands:
        rows.setdefault(n.cy, []).append(n)
    # 同一 y（±12px 容差）至少两个候选，才算城市行
    for y in sorted(rows, key=lambda v: (v < 380, v)):
        if not (380 <= y <= 620):
            continue
        same = sorted(rows[y], key=lambda n: n.cx)
        if len(same) >= 2:
            return same[0] if side == "from" else same[-1]
    return None


def _pick_city(dev, ns, name: str, side: str, log=None) -> tuple:
    if not name:
        return False, "城市名为空"
    # 已一致就不点（避免多余跳转与失败面）
    cur = _city_row(ns, side)
    if cur and cur.text == name:
        return True, "已就位"

    # 只点"城市行"里的那个节点。**不要退化成点当前城市节点**：
    # 实测踩过——找不到明确入口时退而点 cur，结果点到了日期行，
    # 打开「选择日期」日历弹层，整条流程卡在透明 Activity 上。
    if cur is None:
        return False, "找不到城市行"
    target = cur
    if not dev.tap(target.cx, target.cy):
        return False, "点击城市失败"
    time.sleep(3)

    xml = dev.dump()
    ns2 = nodes(xml)
    # 进入城市选择页的判据：出现搜索输入框，否则说明没跳转，直接失败
    box = edit_box(xml)
    if box is None:
        return False, "未进入城市选择页（没有搜索输入框）"
    dev.tap(box.cx, box.cy)
    time.sleep(1)
    # 用中文输入；App 城市页支持中文搜索
    dev.input_text(name)
    time.sleep(3)
    xml = dev.dump()
    hit = city_result(xml, name, below=box.y2)
    if hit is None:
        time.sleep(3)
        xml = dev.dump()
        hit = city_result(xml, name, below=box.y2)
    if hit is None:
        return False, f"城市列表里找不到 {name}"
    dev.tap(hit.cx, hit.cy)
    time.sleep(3)
    return True, "已选"


def _pick_date(dev, ns, ymd: str, log=None, xml: str = "") -> tuple:
    """日期选择：首页有日期行（'10月30日'），点开日历后选目标日。

    首页日历条只覆盖约 8 天；更远的日期必须到「选择日期」长窗口里点。
    那里按 **resource-id 里的 ISO 日期**定位，不按文案匹配——文案是
    「11月5日」（不补零），跨月后还会重复，按文案找会点错或找不到
    （实测 11-05 就这样被判成「日历里找不到」而放弃）。

    弹层**已经开着**时（xml 里带 Search_Calendar_Dialog）必须直接点格子：
    此时弹层盖住了首页日期行，再去找「日期入口」只会得到「找不到」。
    """
    if not ymd or len(ymd) < 10:
        return False, "日期格式非法"
    mm = int(ymd[5:7])
    dd = int(ymd[8:10])
    want = f"{mm}月{dd}日"

    if "Search_Calendar_Dialog" in (xml or ""):
        return _tap_calendar_cell(dev, xml, ymd)

    # 首页直接显示目标日期则无需点开日历
    home_hit = find(ns, want)
    if home_hit:
        return True, "首页已显示目标日期"

    trigger = None
    for n in ns:
        if re.fullmatch(r"\d{1,2}月\d{1,2}日", n.text or ""):
            trigger = n
            break
    if trigger is None:
        return False, "找不到日期入口"
    if not dev.tap(trigger.cx, trigger.cy):
        return False, "点击日期失败"
    time.sleep(3)

    xml2 = dev.dump() or ""
    if "Search_Calendar_Dialog" in xml2:
        return _tap_calendar_cell(dev, xml2, ymd)

    # 兜底：目标日就在当前可见的普通日历页里（文案匹配）
    hit = find(nodes(xml2), want)
    if hit is None:
        return False, f"日历里找不到 {want}"
    dev.tap(hit.cx, hit.cy)
    time.sleep(2)
    return True, "已选日期"


def _cell_month_scroll_hint(xml: str, ymd: str):
    """目标格卷到哪个方向去了：'down'（看更早日期）/ 'up'（看更晚）。

    必须按**可见格子**的日期算范围：卷出屏幕的格子在 XML 里仍在（bounds
    退化），把它们算进来会让范围永远覆盖目标日，滚动方向判不出来——
    实测就是这样：屏幕显示 12 月起，XML 里却还挂着 11-08 起的一堆格子。
    """
    vis = sorted(m.group(1) for m in re.finditer(
        r'resource-id="flight_calendar_date_cell-(\d{4}-\d{2}-\d{2})"'
        r'[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml or "")
        if int(m.group(5)) > int(m.group(3)))
    if not vis:
        return None
    if ymd < vis[0]:
        return "down"
    if ymd > vis[-1]:
        return "up"
    return None


def _needs_earlier(xml: str, ymd: str) -> bool:
    """目标日是否位于当前可见区间之前（→ 需要往下拉看更早）。"""
    vis = [m.group(1) for m in re.finditer(
        r'resource-id="flight_calendar_date_cell-(\d{4}-\d{2}-\d{2})"'
        r'[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml or "")
        if int(m.group(5)) > int(m.group(3))]
    return bool(vis) and ymd < max(vis)


def _scroll_calendar(dev, direction: str) -> bool:
    """在日历弹层里滚动一屏。direction: 'down'=看更早日期，'up'=看更晚。"""
    # 手指从日历中段划到另一端；区间取 500→1300（避开头部标题与底部按钮）
    if direction == "down":
        return bool(dev.swipe(450, 500, 450, 1300, 400))
    return bool(dev.swipe(450, 1300, 450, 500, 400))


def _tap_calendar_cell(dev, xml: str, ymd: str) -> tuple:
    """在已打开的长窗口日历里点目标日；成功后弹层会自己关掉。

    目标日可能被卷出视口（91 格分三个月，屏幕只放得下其中一段）。那种
    情况下格子仍在 XML 里，但 bounds 退化、点不到——必须先把日期滚回
    可视区。最多滚动 4 屏；仍找不到才认「不在窗口内」（那是能力边界，
    与「点了没反应」是两回事）。
    """
    for attempt in range(5):
        cell = _calendar_cell(xml, ymd)
        if cell is None:
            hint = _cell_month_scroll_hint(xml, ymd)
            if hint is None:
                # 日期在可见区间内却拿不到坐标：只可能是夹在两段可见区
                # 之间的缝隙（被裁掉的半行）。按目标相对首格的方向推一屏。
                if attempt > 1:
                    break
                hint = "down" if _needs_earlier(xml, ymd) else "up"
            if not _scroll_calendar(dev, hint):
                break
            time.sleep(1.5)
            xml = dev.dump() or ""
            continue
        if not dev.tap(*cell):
            return False, f"点击日历格失败 {ymd}"
        time.sleep(2)
        left = dev.dump() or ""
        if "Search_Calendar_Dialog" in left:
            # **弹层没关是可恢复的**（2026-11-03~04 实测 15 次）：
            # 落点偶尔偏到弹层头部，日历不关；原代码直接判失败放弃，
            # 于是「明细页没解析出带价航班」整条航线白跑。
            #
            # 关键：BACK **把弹层关掉了**，所以重试不能就地找格子
            # （2026-11-04 实测报「重试时找不到格子」——弹层都没了当然找不到）。
            # 重试必须**重新打开弹层**，再走一遍滚动查找 + 点击。
            try:
                from .app_base import dismiss_until_gone
                gone, _ = dismiss_until_gone(
                    dev, "Search_Calendar_Dialog", tries=1)
            except Exception:
                gone = "Search_Calendar_Dialog" not in (dev.dump() or "")
            if not gone:
                return False, "点了日期但弹层没关"
            if attempt >= 4:
                return False, "点了日期但弹层没关"
            # 重新打开弹层，再递归地走一次本函数（次数由 attempt 上限兜住）
            reopened, why = open_date_dialog(dev)
            if not reopened:
                return False, "点了日期但弹层没关（重开弹层失败：%s）" % why
            return _tap_calendar_cell(dev, dev.dump() or "", ymd)
        # 点完必须核对首页日期行真的换了：没换时点「机票查询」会重查上一日，
        # 结果被打上目标日期——价格错配而看不出任何异常。
        shown = home_date_text(left)
        if shown and shown != _want_md(ymd):
            return False, f"点完日期仍是 {shown}（期望 {_want_md(ymd)}）"
        return True, "已在长窗口选中日期"
    return False, f"日历里没有 {ymd} 这一格（不在弹层覆盖范围内或不在可视区）"


def _want_md(ymd: str) -> str:
    """2026-11-05 -> '11月5日'（App 的日期行不补零）。"""
    return f"{int(ymd[5:7])}月{int(ymd[8:10])}日"


def home_date_text(xml: str) -> str:
    """首页日期行当前显示的目标日；找不到返回空串。"""
    for n in nodes(xml):
        t = (n.text or "").strip()
        if re.fullmatch(r"\d{1,2}月\d{1,2}日", t):
            return t
    return ""


def _calendar_cell(xml: str, ymd: str):
    """长窗口日历里某天的可点坐标；找不到或**不在视口内**返回 None。

    bounds 必须校验 y2 > y1：弹层是滚动容器，卷出屏幕的行在 XML 里仍在，
    但 bounds 退化成 `[11,327][90,30]`（y2 < y1，可见高度 0）。按中心点
    算出的坐标会落到弹层头部，点完弹层不关——报「点了日期但弹层没关」，
    看着像点击失败，实际是**那一格根本没显示**（实测 11 月全月如此）。
    """
    m = re.search(
        r'resource-id="flight_calendar_date_cell-%s"[^>]*'
        r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"' % re.escape(ymd), xml or "")
    if not m:
        return None
    x1, y1, x2, y2 = (int(m.group(i)) for i in range(1, 5))
    if y2 <= y1 or x2 <= x1:
        return None
    return (x1 + x2) // 2, (y1 + y2) // 2
