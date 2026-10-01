# -*- coding: utf-8 -*-
"""首次运行配置向导：中文问答生成 config.yaml

用法:
    python main.py --setup     # 重跑向导（或 exe --setup）
    配置文件不存在时：main.py 会写入空骨架并引导用网页配置页
    （http://127.0.0.1:8765）——问答向导需显式 --setup 进入
"""
import os
import re
import shutil
import sys
from datetime import date, timedelta

# 支持的城市（中文名 -> 三字码），与采集器 CITY_NAME 保持一致
CITY = {
    "北京": "BJS", "上海": "SHA", "广州": "CAN", "深圳": "SZX",
    "成都": "CTU", "重庆": "CKG", "杭州": "HGH", "西安": "SIA",
    "南京": "NKG", "武汉": "WUH", "长沙": "CSX", "厦门": "XMN",
    "三亚": "SYX", "海口": "HAK", "昆明": "KMG", "丽江": "LJG",
    "大理": "DLU", "西双版纳": "JHG", "香格里拉": "DIG", "腾冲": "TCZ",
    "乌鲁木齐": "URC", "青岛": "TAO", "天津": "TSN", "郑州": "CGO",
    "济南": "TNA", "福州": "FOC", "温州": "WNZ", "宁波": "NGB",
    "合肥": "HFE", "贵阳": "KWE", "南宁": "NNG", "桂林": "KWL",
    "兰州": "LHW", "西宁": "XNN", "银川": "INC", "呼和浩特": "HET",
    "太原": "TYN", "石家庄": "SJW", "哈尔滨": "HRB", "长春": "CGQ",
    "沈阳": "SHE", "大连": "DLC", "珠海": "ZUH", "汕头": "SWA",
    "泉州": "JJN", "无锡": "WUX", "烟台": "YNT", "威海": "WEH",
    "敦煌": "DNH", "张家界": "DYG",
}


def _input(prompt):
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        # Ctrl+C 曾裸栈退出（docstring 承诺「Ctrl+C 退出」，实际抛
        # KeyboardInterrupt traceback）
        print("\n[向导退出，未生成配置]")
        sys.exit(1)


def _ask(prompt, default=""):
    tip = f"{prompt}（回车={default}）: " if default != "" else f"{prompt}: "
    v = _input(tip)
    return v or default


def _ask_city(prompt):
    while True:
        v = _ask(prompt)
        # 「支持城市」以「市」结尾会被剥成「支持城」→ 零命中死循环
        # （横幅承诺了该指令却从未实现）
        if v in ("支持城市", "支持城", "城市"):
            print("  支持城市：" + "、".join(sorted(CITY)))
            continue
        probe = v[:-1] if v.endswith("市") else v  # 「上海市」→「上海」
        if v in CITY:
            return v, CITY[v]
        if probe in CITY:
            return probe, CITY[probe]
        hits = [c for c in sorted(CITY) if c.startswith(probe)] if probe else []
        if len(hits) == 1:
            return hits[0], CITY[hits[0]]
        if hits:
            print(f"  没有「{v}」。是不是：{'、'.join(hits[:6])}？")
        else:
            print(f"  暂不支持「{v}」。输入「支持城市」查看全部 {len(CITY)} 城")


def _ask_dates():
    default = (date.today() + timedelta(days=14)).strftime("%Y-%m-%d")
    while True:
        raw = _ask("出发日期 YYYY-MM-DD（多个用逗号分隔）", default)
        dates = [d.strip() for d in raw.replace("，", ",").split(",") if d.strip()]
        ok = dates and all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) for d in dates)
        if ok:
            # 正则只验形状：2026-13-99 这类假日期会全渠道零数据且难排查
            try:
                parsed = [date.fromisoformat(d) for d in dates]
            except ValueError:
                print("  日期不存在，检查月份/日期（例：2026-10-01）")
                continue
            if min(parsed) < date.today():
                print(f"  {'、'.join(d for d, p in zip(dates, parsed) if p < date.today())}"
                      " 已是过去日期，出发日期请 ≥ 今天")
                continue
            return dates
        print("  日期格式不对，示例：2026-10-01 或 2026-10-01,2026-10-02")


def _ask_hhmm(prompt, default):
    while True:
        v = _ask(prompt, default)
        if re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
            return v
        print("  格式应为 HH:MM（24h 制），示例：02:00")


def _ask_int(prompt, default, lo):
    while True:
        v = _ask(prompt, str(default))
        if v.isdigit() and int(v) >= lo:
            return int(v)
        print(f"  请输入 ≥{lo} 的整数")


def _ask_price(prompt):
    while True:
        v = _ask(prompt, "0")
        if v == "0":
            return 0
        if v.isdigit() and int(v) >= 100:
            return int(v)
        print("  请输入 ≥100 的整数，或 0 表示不启用")


def run_wizard(config_path="config.yaml") -> bool:
    print("=" * 56)
    print("  机票价格监控 - 配置向导")
    print("  全程回车可用默认值；Ctrl+C 退出")
    print("=" * 56)

    routes = []
    while True:
        print(f"\n--- 第 {len(routes) + 1} 条航线 ---")
        from_name, from_code = _ask_city("出发城市（中文）")
        to_name, to_code = _ask_city("到达城市（中文）")
        dates = _ask_dates()
        print(f"  提醒规则（0 = 不启用该类提醒）")
        alert_direct = _ask_price("  直飞心理价位 ￥")
        alert_transfer = _ask_price("  中转心理价位 ￥")
        arrival_max = _ask_hhmm("  中转最晚到达（次日几点前，24h制）", "02:00")
        layover_min = _ask_int("  中转最短衔接分钟（需托运建议 90，0=不限）", 90, 0)
        bag = _ask("  仅认两段含免费托运的直挂班次？(y/N)", "n").lower() == "y"
        routes.append({
            "from_code": from_code, "from_name": from_name,
            "to_code": to_code, "to_name": to_name,
            "dates": dates, "alert_direct": alert_direct,
            "alert_transfer": alert_transfer, "arrival_max": arrival_max,
            "layover_min": layover_min, "bag": "direct" if bag else "",
        })
        if _ask("还要监控其他航线吗？(y/N)", "n").lower() != "y":
            break

    print("\n--- 监控平台 ---")
    print("  去哪儿+飞猪（默认，免登录开箱即用）")
    print("  可追加: ctrip携程(需登录) / tongcheng同程 / tuniu途牛")
    extra = _ask("追加平台（逗号分隔，回车=不追加）", "")
    platforms = ["qunar", "fliggy"]
    alias = {"ctrip": "ctrip", "携程": "ctrip", "tongcheng": "tongcheng",
             "同程": "tongcheng", "tuniu": "tuniu", "途牛": "tuniu"}
    for x in [x.strip() for x in extra.replace("，", ",").split(",") if x.strip()]:
        p = alias.get(x.lower(), alias.get(x))
        if p and p not in platforms:
            platforms.append(p)
    if "ctrip" in platforms:
        print("  ⚠ 携程在部分公司网络会被风控拦截，如失效请运行: --login ctrip")

    interval = _ask_int("轮询间隔（分钟，建议 ≥5）", 30, 5)

    print("\n--- 钉钉推送（可跳过；跳过则只在窗口看日志）---")
    webhook = _ask("机器人 Webhook（https://oapi.dingtalk.com/robot/send?...）", "")
    secret = _ask("加签密钥 SEC...（安全设置未选加签则回车）", "") if webhook else ""
    at_mobile = _ask("达标时 @ 的手机号", "") if webhook else ""

    # 备份旧配置
    if os.path.exists(config_path):
        bak = config_path + ".bak"
        shutil.copyfile(config_path, bak)
        print(f"\n旧配置已备份到 {bak}")

    route_blocks = []
    for r in routes:
        dates_yaml = "\n".join(f'      - "{d}"' for d in r["dates"])
        route_blocks.append(
            f'''  - from: {r['from_code']}
    from_name: {r['from_name']}
    to: {r['to_code']}
    to_name: {r['to_name']}
    dates:
{dates_yaml}
    alert_threshold: 0
    alert_direct: {r['alert_direct']}          # 直飞心理价位（0 不启用）
    alert_transfer: {r['alert_transfer']}      # 中转心理价位（0 不启用）
    transfer_arrival_max: "{r['arrival_max']}"  # 中转最晚到达
    transfer_layover_min: {r['layover_min']}    # 中转最短衔接分钟（0 不限制）
    transfer_baggage: "{r['bag']}"              # direct=仅认两段含免费托运的直挂班次'''
        )
    routes_yaml = "\n".join(route_blocks)
    platforms_yaml = "\n".join(f"  - {p}" for p in platforms)

    # users 包裹格式（与网页配置页同一结构）：旧顶层 routes 格式曾被
    # 网页首次保存无条件改写为 users:[] ——向导生成的航线静默全失效
    content = f'''# 由配置向导生成，可手工编辑；重跑向导: --setup
users:
- name: 我的监控
  routes:
{routes_yaml}

  platforms:
{platforms_yaml}
  notifier:
    digest: true               # 每轮推送运行状态；达标时警报式推送
    report_hour: 9             # 每日该时刻推送图文价格走势（删掉此行=关闭；
                               # 需 digest: true 同时成立）
    image_host:
      provider: freeimage      # 走势图图床（免注册；sm.ms 需填 token）
    push_drop_min: 30
    push_rise_min: 50
    dingtalk:
      enabled: {'true' if webhook else 'false'}
      webhook: "{webhook}"
      secret: "{secret}"
      at_mobile: "{at_mobile}"  # 达标强提醒 @ 的手机号
    serverchan:
      enabled: false
      send_key: ""
      channel: ""

schedule:
  interval_minutes: {interval}
  jitter_minutes: 5
  run_on_start: true

crawler:
  headless: true
  timeout_seconds: 45
  delay_min: 5
  delay_max: 15
  user_agent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
  mobile_user_agent: ""
  debug: true
  debug_dir: debug
  user_data_dir: user_data

output:
  db_path: data/prices.db
  log_path: logs/monitor.log

web:
  port: 8765
'''
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"\n✅ 配置已写入 {os.path.abspath(config_path)}")
    return True


if __name__ == "__main__":
    run_wizard()
