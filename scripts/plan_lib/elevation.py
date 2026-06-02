"""Google Elevation API 呼叫 — 從 GPX 軌跡點計算精確爬升/下降。

用法：
  python3 scripts/plan.py elevation N

從 dayN_route.gpx 讀軌跡點，抽樣送 Google Elevation API，
本地平滑後計算累計爬升/下降，寫回 places.json。

費用：Elevation Essentials tier，前 10,000 次/月免費。
每天路線約 3 次請求（512 點/次），10 天 = 30 次，完全免費。
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

from .helpers import ROOT, day_dir, plan_dir, read_json, write_json, info, die

ELEVATION_API_URL = "https://maps.googleapis.com/maps/api/elevation/json"
MAX_LOCATIONS_PER_REQUEST = 512
SMOOTHING_THRESHOLD_M = 3  # 忽略 < 3m 的起伏（降噪）


def _get_api_key() -> str:
    key = os.environ.get("GOOGLE_PLACES_API_KEY", "")
    if not key:
        die(
            "缺少 GOOGLE_PLACES_API_KEY 環境變數。\n"
            "Google Elevation API 與 Places API 共用同一個 key。"
        )
    return key


def _parse_gpx_trackpoints(gpx_path: Path) -> list[tuple[float, float]]:
    """從 GPX 讀取所有 rtept/trkpt 的 lat/lng。"""
    content = gpx_path.read_text(encoding="utf-8")
    # 匹配 <rtept lat="..." lon="..."> 和 <trkpt lat="..." lon="...">
    pattern = re.compile(r'<(?:rtept|trkpt)\s+lat="([^"]+)"\s+lon="([^"]+)"')
    points = []
    for m in pattern.finditer(content):
        lat = float(m.group(1))
        lng = float(m.group(2))
        points.append((lat, lng))
    return points


def _sample_points(points: list[tuple[float, float]], max_total: int = 300) -> list[tuple[float, float]]:
    """等距抽樣，確保首尾都包含。"""
    n = len(points)
    if n <= max_total:
        return points
    step = (n - 1) / (max_total - 1)
    sampled = []
    for i in range(max_total):
        idx = round(i * step)
        sampled.append(points[idx])
    return sampled


def _fetch_elevations(points: list[tuple[float, float]], api_key: str) -> list[float]:
    """呼叫 Google Elevation API，回傳每個點的海拔（公尺）。"""
    all_elevations = []

    for i in range(0, len(points), MAX_LOCATIONS_PER_REQUEST):
        batch = points[i:i + MAX_LOCATIONS_PER_REQUEST]
        locations_str = "|".join(f"{lat},{lng}" for lat, lng in batch)

        url = f"{ELEVATION_API_URL}?locations={locations_str}&key={api_key}"

        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            die(f"Elevation API HTTP {e.code}:\n{error_body}")
        except urllib.error.URLError as e:
            die(f"Elevation API 網路錯誤：{e.reason}")

        status = body.get("status", "")
        if status != "OK":
            die(f"Elevation API 回傳 status={status}: {body.get('error_message', '')}")

        for result in body["results"]:
            all_elevations.append(result["elevation"])

    return all_elevations


def _calculate_ascent_descent(elevations: list[float], threshold: float = SMOOTHING_THRESHOLD_M) -> tuple[int, int]:
    """用 threshold 平滑法計算累計爬升/下降。

    只在高度變化超過 threshold 時才累計，忽略小於 threshold 的雜訊起伏。
    """
    if len(elevations) < 2:
        return 0, 0

    total_ascent = 0.0
    total_descent = 0.0
    last_significant = elevations[0]

    for elev in elevations[1:]:
        diff = elev - last_significant
        if diff >= threshold:
            total_ascent += diff
            last_significant = elev
        elif diff <= -threshold:
            total_descent += abs(diff)
            last_significant = elev

    return round(total_ascent), round(total_descent)


def compute_from_points(points: list[tuple[float, float]], api_key: str) -> tuple[int, int]:
    """從 [(lat, lng), …] 軌跡折線抽樣 → Elevation API → 平滑算累計爬升/下降。

    供 cmd_elevation（讀 GPX）與 cmd_route（直接用記憶體裡的真實路線折線）共用，
    讓 route 能在「寫 places.json 距離」的同一次寫入順手帶上爬升欄位，
    不額外多一次 places.json 寫入而破壞 render-md 自癒的 mtime 不變式。
    """
    if len(points) < 2:
        die(f"軌跡點不足（{len(points)} 個）")
    sampled = _sample_points(points, max_total=300)
    info(f"抽樣：{len(sampled)} 個點 → {math.ceil(len(sampled) / MAX_LOCATIONS_PER_REQUEST)} 次 Elevation API 請求")
    elevations = _fetch_elevations(sampled, api_key)
    info(f"取得 {len(elevations)} 個海拔值（範圍 {min(elevations):.0f}m – {max(elevations):.0f}m）")
    ascent, descent = _calculate_ascent_descent(elevations, threshold=SMOOTHING_THRESHOLD_M)
    info(f"計算結果：↑ {ascent} m ／ ↓ {descent} m（threshold={SMOOTHING_THRESHOLD_M}m）")
    return ascent, descent


def cmd_elevation(args):
    """從 GPX 軌跡點 + Google Elevation API 計算精確爬升/下降。"""
    n = args.day
    api_key = _get_api_key()

    gpx_path = day_dir(n) / f"day{n}_route.gpx"
    if not gpx_path.exists():
        die(f"找不到 {gpx_path.relative_to(ROOT)}，請先執行 route {n}")

    places_path = plan_dir(n) / "places.json"
    if not places_path.exists():
        die(f"找不到 {places_path.relative_to(ROOT)}")

    # 讀取 GPX 軌跡點 → 共用計算
    all_points = _parse_gpx_trackpoints(gpx_path)
    info(f"GPX 軌跡點：{len(all_points)} 個")
    ascent, descent = compute_from_points(all_points, api_key)

    # 寫回 places.json
    data = read_json(places_path)
    data["elevation_ascent_m"] = ascent
    data["elevation_descent_m"] = descent
    write_json(places_path, data)
    info(f"已寫入 places.json（elevation_ascent_m={ascent}, elevation_descent_m={descent}）")
