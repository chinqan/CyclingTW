"""GPX 產出：gpx-save / gpx-waypoints / gpx-split-plan / gpx-append / gpx-merge。"""
from __future__ import annotations

import re
import sys

from .helpers import ROOT, day_dir, plan_dir, read_json, write_json, die, info, haversine_km


def cmd_gpx_save(args):
    """從 stdin 接收 GPX 文字，儲存為 dayN_route.gpx。"""
    n = args.day
    raw = sys.stdin.read()
    if "<gpx" not in raw:
        die("stdin 不像 GPX 內容（找不到 <gpx 標籤）")
    start = raw.find("<?xml")
    if start == -1:
        start = raw.find("<gpx")
    gpx = raw[start:]
    out = day_dir(n) / f"day{n}_route.gpx"
    out.write_text(gpx, encoding="utf-8")
    info(f"已寫入 {out.relative_to(ROOT)}（{len(gpx)} chars）")


def cmd_gpx_waypoints(args):
    """備案：依 places.json 座標產出純航點 GPX。"""
    n = args.day
    data = read_json(plan_dir(n) / "places.json")
    places = data["places"]
    lats = [p["location"]["lat"] for p in places]
    lons = [p["location"]["lng"] for p in places]
    gpx = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1" creator="CyclingTW">',
        f'  <metadata><name>Day {n} {data.get("route_name", "")}</name>',
        f'    <bounds minlat="{min(lats)}" minlon="{min(lons)}" maxlat="{max(lats)}" maxlon="{max(lons)}"/></metadata>',
    ]
    for i, p in enumerate(places, 1):
        sym = "Flag, Green" if i == 1 else "Flag, Red" if i == len(places) else "Waypoint"
        gpx.append(f'  <wpt lat="{p["location"]["lat"]}" lon="{p["location"]["lng"]}">')
        gpx.append(f'    <name>{p["name_zh"]}</name><sym>{sym}</sym></wpt>')
    gpx.append(f'  <trk><name>Day {n}</name><trkseg>')
    for p in places:
        gpx.append(f'    <trkpt lat="{p["location"]["lat"]}" lon="{p["location"]["lng"]}"/>')
    gpx.append("  </trkseg></trk></gpx>")
    out = day_dir(n) / f"day{n}_route.gpx"
    out.write_text("\n".join(gpx), encoding="utf-8")
    info(f"已寫入備案 waypoint GPX：{out.relative_to(ROOT)}")


def cmd_gpx_split_plan(args):
    """切割長路線為 N 段。"""
    n = args.day
    max_wp = args.max_waypoints
    data = read_json(plan_dir(n) / "places.json")
    coords = [(p["location"]["lng"], p["location"]["lat"], p["name_zh"]) for p in data["places"]]
    if len(coords) < 2:
        die("places.json 至少需要 2 個點位")

    # ── 座標品質驗證 ──
    TAIWAN_BOUNDS = {"lat_min": 21.8, "lat_max": 25.4, "lng_min": 119.2, "lng_max": 122.1}
    MAX_ADJACENT_KM = 40  # 相鄰兩點最大合理距離（單車一日 ≤ 120km，分段後不應超過 40）

    errors = []
    for i, (lng, lat, name) in enumerate(coords):
        # 台灣 bounding box 檢查
        if not (TAIWAN_BOUNDS["lat_min"] <= lat <= TAIWAN_BOUNDS["lat_max"]):
            errors.append(f"  [{i+1}] {name}: lat={lat} 超出台灣範圍 ({TAIWAN_BOUNDS['lat_min']}–{TAIWAN_BOUNDS['lat_max']})")
        if not (TAIWAN_BOUNDS["lng_min"] <= lng <= TAIWAN_BOUNDS["lng_max"]):
            errors.append(f"  [{i+1}] {name}: lng={lng} 超出台灣範圍 ({TAIWAN_BOUNDS['lng_min']}–{TAIWAN_BOUNDS['lng_max']})")

    for i in range(len(coords) - 1):
        lng1, lat1, name1 = coords[i]
        lng2, lat2, name2 = coords[i + 1]
        dist = haversine_km(lat1, lng1, lat2, lng2)
        if dist > MAX_ADJACENT_KM:
            errors.append(f"  [{i+1}→{i+2}] {name1} → {name2}: 直線距離 {dist:.1f} km（上限 {MAX_ADJACENT_KM} km），座標可能有誤")

    # 偏離檢查：中間點離前後兩點連線太遠（繞路超過 5km 且倍率 > 1.5x）
    for i in range(1, len(coords) - 1):
        lng_prev, lat_prev, _ = coords[i - 1]
        lng_cur, lat_cur, name_cur = coords[i]
        lng_next, lat_next, _ = coords[i + 1]
        direct = haversine_km(lat_prev, lng_prev, lat_next, lng_next)
        detour = (haversine_km(lat_prev, lng_prev, lat_cur, lng_cur) +
                  haversine_km(lat_cur, lng_cur, lat_next, lng_next))
        excess = detour - direct
        if excess > 5.0 and direct > 0 and detour / direct > 1.5:
            errors.append(f"  [{i+1}] {name_cur}: 繞路 {excess:.1f} km（前後直線 {direct:.1f}，經此點 {detour:.1f}），座標疑似不在路線上")

    # 累計距離 vs 起終點直線距離的合理性
    total_step_km = sum(
        haversine_km(coords[i][1], coords[i][0], coords[i+1][1], coords[i+1][0])
        for i in range(len(coords) - 1)
    )
    straight_km = haversine_km(coords[0][1], coords[0][0], coords[-1][1], coords[-1][0])
    if straight_km > 0 and total_step_km > straight_km * 3:
        errors.append(f"  路線累計直線距離 {total_step_km:.1f} km 是起終點直線 {straight_km:.1f} km 的 {total_step_km/straight_km:.1f} 倍，"
                      f"可能有座標跳躍異常")

    if errors:
        die("⚠️  座標品質驗證失敗，請先修正再重跑：\n" + "\n".join(errors) +
            "\n\n💡 便利商店座標務必用 Google Maps search_places 取得精確值，不要手動估算。")
    # ── 驗證通過 ──
    # ── 驗證通過 ──

    chunk = max_wp + 2
    legs = []
    i = 0
    while i < len(coords) - 1:
        end = min(i + chunk, len(coords))
        seg = coords[i:end]
        legs.append({
            "leg": len(legs) + 1,
            "from_name": seg[0][2],
            "to_name": seg[-1][2],
            "from_coordinates": [seg[0][0], seg[0][1]],
            "to_coordinates": [seg[-1][0], seg[-1][1]],
            "waypoints": [[c[0], c[1]] for c in seg[1:-1]],
        })
        i = end - 1

    plan_file = plan_dir(n) / "gpx_split.json"
    write_json(plan_file, {"legs": legs})

    # 清理舊 leg 檔：leg 編號 > 新計畫的最大 leg 一律刪除（避免被 gpx-merge 誤併）
    new_max = len(legs)
    stale = []
    for f in plan_dir(n).glob("gpx_leg_*.gpx"):
        match = re.search(r"leg_(\d+)\.gpx$", f.name)
        if match and int(match.group(1)) > new_max:
            stale.append(f)
    for f in stale:
        f.unlink()
    if stale:
        info(f"清除舊 leg 檔（超出新計畫 {new_max} 段）：{', '.join(s.name for s in stale)}")

    # 提醒既有 in-range leg 檔若 places.json 已變更需要重抓
    existing = sorted(plan_dir(n).glob("gpx_leg_*.gpx"),
                      key=lambda p: int(re.search(r"leg_(\d+)", p.name).group(1)))
    if existing:
        info(f"⚠️  既有 {len(existing)} 個 leg 檔仍保留：{', '.join(e.name for e in existing)}；"
             f"若 places.json 已改動請重抓對應 leg")

    print(f"切成 {len(legs)} 段（每段 ≤ {max_wp} 個中間 waypoints）：\n")
    for L in legs:
        print(f"  Leg {L['leg']}: {L['from_name']} → {L['to_name']}  ({len(L['waypoints'])} waypoints)")
    print(f"\nClaude 操作：")
    print(f"  1. 對每段呼叫 mcp__openroute-mcp__create_route_from_to")
    print(f"     (參數從 {plan_file.relative_to(ROOT)} 取出對應 leg)")
    print(f"  2. 將 MCP 結果 pipe 給 'plan.py gpx-append {n} --leg <i>'")
    print(f"  3. 最後 'plan.py gpx-merge {n}' 合併所有 leg")


def _save_leg_gpx(n: int, leg_i: int, raw: str) -> None:
    """共用：清理 GPX 內容、修補截斷、寫入 gpx_leg_{i}.gpx、驗證終點。"""
    start = raw.find("<?xml")
    if start == -1:
        start = raw.find("<gpx")
    if start == -1:
        die("輸入不含 GPX 內容")
    gpx = raw[start:]

    before_strip = len(gpx)
    gpx = re.sub(r"<extensions>.*?</extensions>", "", gpx, flags=re.DOTALL)
    saved = before_strip - len(gpx)
    if saved > 0:
        info(f"剝除 <extensions> 區塊，省下 {saved} bytes（{saved * 100 // before_strip}%）")

    if "</gpx>" not in gpx:
        last_rtept = gpx.rfind("</rtept>")
        if last_rtept > 0:
            gpx = gpx[:last_rtept + len("</rtept>")] + "\n  </rte>\n</gpx>"
            info("⚠️  GPX 被截斷，已自動補上閉合標籤")
        else:
            die("GPX 既無 </gpx> 也無任何完整 </rtept>，無法修補")

    out = plan_dir(n) / f"gpx_leg_{leg_i}.gpx"
    out.write_text(gpx, encoding="utf-8")
    rtept_count = len(re.findall(r"<rtept", gpx))
    info(f"已儲存 leg {leg_i} → {out.relative_to(ROOT)}（{rtept_count} 個 rtept, {len(gpx)} bytes）")

    split_file = plan_dir(n) / "gpx_split.json"
    if split_file.exists():
        plan = read_json(split_file)
        matching = next((L for L in plan.get("legs", []) if L.get("leg") == leg_i), None)
        if matching:
            planned_to = matching["to_coordinates"]
            pts = re.findall(r'<rtept\s+lat="([\d.\-]+)"\s+lon="([\d.\-]+)"', gpx)
            if pts:
                last_lat, last_lon = float(pts[-1][0]), float(pts[-1][1])
                dist_km = haversine_km(last_lat, last_lon, planned_to[1], planned_to[0])
                if dist_km > 2.0:
                    die(f"⚠️  Leg {leg_i} 實際終點 ({last_lat:.4f}, {last_lon:.4f}) "
                        f"距計畫終點 {matching['to_name']} ({planned_to[1]:.4f}, {planned_to[0]:.4f}) "
                        f"{dist_km:.2f} km，疑似 MCP envelope 截斷。\n"
                        f"建議：重跑 gpx-split-plan {n} --max-waypoints 2（或更小）後重抓所有 leg。")
                else:
                    info(f"終點驗證通過：距計畫 {matching['to_name']} {dist_km * 1000:.0f} m")


def cmd_gpx_append(args):
    """[stdin] 儲存單段 openroute MCP GPX。"""
    _save_leg_gpx(args.day, args.leg, sys.stdin.read())


def cmd_gpx_fetch(args):
    """自動拾取最新 cycling-regular-*.gpx 並存為指定 leg。

    掃描兩個位置（向前/向後相容 openroute-mcp 的 --data-folder 設定）：
      - 專案根目錄 ROOT/
      - ROOT/data/generated_routes/
    取 mtime 最新者，成功後刪除來源檔。
    """
    n = args.day
    leg_i = args.leg
    search_dirs = [ROOT, ROOT / "data" / "generated_routes"]
    candidates: list = []
    for d in search_dirs:
        if d.exists():
            candidates.extend(d.glob("cycling-regular-*.gpx"))
    if not candidates:
        searched = "、".join(str(d.relative_to(ROOT)) if d != ROOT else "(cwd)" for d in search_dirs)
        die(f"找不到 cycling-regular-*.gpx（已掃描：{searched}），請先呼叫 openroute MCP")
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    src = candidates[0]
    loc = src.parent.relative_to(ROOT) if src.parent != ROOT else "(cwd)"
    info(f"使用 {loc}/{src.name}（mtime {src.stat().st_mtime:.0f}）")
    _save_leg_gpx(n, leg_i, src.read_text(encoding="utf-8"))
    src.unlink()
    info(f"已刪除來源檔 {src.name}")


def cmd_gpx_merge(args):
    """合併 gpx_leg_*.gpx 為最終 dayN_route.gpx。"""
    n = args.day
    leg_files = sorted(
        plan_dir(n).glob("gpx_leg_*.gpx"),
        key=lambda p: int(re.search(r"leg_(\d+)", p.name).group(1))
    )
    if not leg_files:
        die(f"找不到 {plan_dir(n).relative_to(ROOT)}/gpx_leg_*.gpx")

    # 與 gpx_split.json 比對一致性：避免舊 leg 檔被誤併
    split_file = plan_dir(n) / "gpx_split.json"
    if split_file.exists():
        plan = read_json(split_file)
        expected = {L["leg"] for L in plan.get("legs", [])}
        actual = {int(re.search(r"leg_(\d+)", f.name).group(1)) for f in leg_files}
        missing = expected - actual
        extra = actual - expected
        if missing or extra:
            msgs = []
            if missing:
                msgs.append(f"缺少 leg {sorted(missing)}（需重抓 openroute）")
            if extra:
                msgs.append(f"多餘 leg {sorted(extra)}（不在 gpx_split.json 計畫內，請刪除或重跑 gpx-split-plan）")
            die("⚠️  leg 檔與 gpx_split.json 不一致：\n  " + "\n  ".join(msgs))

    rtept_pattern = re.compile(r'<rtept\s+lat="([\d.\-]+)"\s+lon="([\d.\-]+)"', re.MULTILINE)
    all_pts = []
    for f in leg_files:
        pts = rtept_pattern.findall(f.read_text(encoding="utf-8"))
        all_pts.extend(pts)
        info(f"  leg {f.name}: {len(pts)} 個 rtept")
    if not all_pts:
        die("各 leg 檔案皆無 rtept 點位")

    lats = [float(p[0]) for p in all_pts]
    lons = [float(p[1]) for p in all_pts]

    data = read_json(plan_dir(n) / "places.json")
    places = data["places"]

    out_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1" creator="CyclingTW merged">',
        '  <metadata>',
        f'    <name>Day {n} {data.get("route_name", "")}</name>',
        f'    <bounds minlat="{min(lats)}" minlon="{min(lons)}" maxlat="{max(lats)}" maxlon="{max(lons)}"/>',
        '  </metadata>',
    ]
    for i, p in enumerate(places, 1):
        sym = "Flag, Green" if i == 1 else "Flag, Red" if i == len(places) else "Waypoint"
        out_lines.append(
            f'  <wpt lat="{p["location"]["lat"]}" lon="{p["location"]["lng"]}">'
            f'<name>{p["name_zh"]}</name><sym>{sym}</sym></wpt>'
        )
    out_lines.append(f'  <trk><name>Day {n} 完整軌跡</name><trkseg>')
    for lat, lon in all_pts:
        out_lines.append(f'    <trkpt lat="{lat}" lon="{lon}"/>')
    out_lines.append('  </trkseg></trk>')
    out_lines.append('</gpx>')

    out_path = day_dir(n) / f"day{n}_route.gpx"
    out_path.write_text("\n".join(out_lines), encoding="utf-8")
    info(f"合併 {len(leg_files)} 段 / {len(all_pts)} 軌跡點 → {out_path.relative_to(ROOT)}")
