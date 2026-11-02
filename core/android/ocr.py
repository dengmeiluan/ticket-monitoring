# -*- coding: utf-8 -*-
"""Windows 自带 OCR（Windows.Media.Ocr）→ 词块列表。

用途：飞猪 App 的航班页是 Flutter 画布，uiautomator/u2 读不到文本；
截图后用系统 OCR 识别，再把词块交给 `crawlers.app_fliggy_parse` 解析。
不引入第三方模型/网络请求；只在 Windows 可用（MuMu App 渠道本就是
Windows-only），其他平台返回空列表，由调用方如实记 unsupported。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

# PowerShell 5.1 读无 BOM 的 UTF-8 会按 ANSI 解释；脚本保持纯 ASCII。
_PS = r"""
param([Parameter(Mandatory=$true)][string]$Path)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
$null = [Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
$null = [Windows.Globalization.Language,Windows.Globalization,ContentType=WindowsRuntime]
function Await($WinRtTask, $ResultType) {
  $m = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
  }
  $t = $m[0].MakeGenericMethod($ResultType).Invoke($null, @($WinRtTask))
  $t.Wait() | Out-Null
  $t.Result
}
$lang = New-Object Windows.Globalization.Language("zh-Hans-CN")
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
if ($engine -eq $null) { throw "no zh-Hans-CN OCR engine" }
$full = (Resolve-Path -LiteralPath $Path).Path
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($full)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
$lines = @()
foreach ($line in $result.Lines) {
  $words = @()
  foreach ($w in $line.Words) {
    $words += [PSCustomObject]@{
      t = $w.Text
      x = [int]$w.BoundingRect.X
      y = [int]$w.BoundingRect.Y
      w = [int]$w.BoundingRect.Width
      h = [int]$w.BoundingRect.Height
    }
  }
  $lines += [PSCustomObject]@{ text = $line.Text; words = $words }
}
$lines | ConvertTo-Json -Depth 5 -Compress
"""


def available() -> bool:
    return (sys.platform.startswith("win")
            and shutil.which("powershell") is not None)


def ocr_words(png: bytes, timeout: int = 90):
    """PNG 字节 → OCR 词块 `[{t,x,y,w,h}]`；不可用/失败返回 []。"""
    if not png or not available():
        return []
    tmp = tempfile.mkdtemp(prefix="tm_ocr_")
    try:
        img = os.path.join(tmp, "shot.png")
        ps1 = os.path.join(tmp, "ocr.ps1")
        with open(img, "wb") as f:
            f.write(png)
        with open(ps1, "w", encoding="ascii", newline="\n") as f:
            f.write(_PS)
        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", ps1, "-Path", img],
                capture_output=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            return []
        raw = proc.stdout or b""
        if not raw.strip():
            return []
        text = ""
        for enc in ("gbk", "utf-8-sig", "utf-8"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if not text:
            return []
        try:
            lines = json.loads(text)
        except ValueError:
            return []
        if isinstance(lines, dict):
            lines = [lines]
        out = []
        for line in lines or []:
            for w in (line or {}).get("words") or []:
                try:
                    out.append({"t": str(w.get("t") or "").strip(),
                                "x": int(w.get("x") or 0),
                                "y": int(w.get("y") or 0),
                                "w": int(w.get("w") or 0),
                                "h": int(w.get("h") or 0)})
                except (TypeError, ValueError):
                    continue
        return [w for w in out if w["t"]]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
