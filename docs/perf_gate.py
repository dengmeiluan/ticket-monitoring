# -*- coding: utf-8 -*-
"""Reproducible search-filter latency gate (demo data, CDP 4x CPU).

Run: python docs/perf_gate.py
Outputs JSON + P50/P95/max. This is evidence, not a CI hard gate.
"""
import json
import os
import socket
import statistics
import subprocess
import sys
import time

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "_scratch", "perf_v295.json")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_http(url, timeout=30):
    import urllib.request
    end = time.time() + timeout
    while time.time() < end:
        try:
            if urllib.request.urlopen(url, timeout=2).status == 200:
                return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError("demo did not start")


def main():
    port = free_port()
    srv = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "webui.py"), "--demo",
         "--port", str(port)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_http("http://127.0.0.1:%d/" % port)
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1440, "height": 900})
            pg.goto("http://127.0.0.1:%d/" % port, wait_until="networkidle")
            pg.wait_for_function("typeof S!=='undefined'&&S&&S.users",
                                 timeout=20000)
            pg.evaluate("switchView('search')")
            pg.wait_for_timeout(1200)
            rows = pg.evaluate(
                "document.querySelectorAll('#srxRows .srx-row').length")

            def measure(page):
                cdp = page.context.new_cdp_session(page)
                cdp.send("Emulation.setCPUThrottlingRate", {"rate": 4})
                samples = []
                for i in range(25):
                    ms = page.evaluate("""()=>{
                      SRX.f.cal=!SRX.f.cal;
                      const t=performance.now();
                      srxApplyFilterChange();
                      document.body.offsetHeight;   // force layout
                      return performance.now()-t;
                    }""")
                    samples.append(round(float(ms), 1))
                    page.wait_for_timeout(120)
                cdp.send("Emulation.setCPUThrottlingRate", {"rate": 1})
                return samples

            def stats(samples, target):
                vals = sorted(samples)

                def pct(p):
                    return vals[min(len(vals) - 1, int(len(vals) * p))]

                return {"samples": samples,
                        "p50": round(statistics.median(vals), 1),
                        "p95": round(pct(0.95), 1),
                        "max": round(max(vals), 1),
                        "target_p95_ms": target}

            samples = measure(pg)
            pg2 = b.new_page(viewport={"width": 720, "height": 450},
                             device_scale_factor=2)
            pg2.goto("http://127.0.0.1:%d/" % port, wait_until="networkidle")
            pg2.wait_for_function("typeof S!=='undefined'&&S&&S.users",
                                  timeout=20000)
            pg2.evaluate("switchView('search')")
            pg2.wait_for_timeout(1200)
            rows200 = pg2.evaluate(
                "document.querySelectorAll('#srxRows .srx-row').length")
            out200 = stats(measure(pg2), 200)
            b.close()
        out = {"viewport": "1440x900", "cpu": 4, "rows": rows,
               "target_p95_ms": 300, **stats(samples, 300),
               "zoom200": {"viewport": "720x450@2x", "rows": rows200,
                           **out200}}
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print(json.dumps(out, ensure_ascii=False))
        ok = out["p95"] <= 300 and out["zoom200"]["p95"] <= 200
        print("PASS" if ok else "OVER TARGET")
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except Exception:
            srv.kill()


if __name__ == "__main__":
    main()
