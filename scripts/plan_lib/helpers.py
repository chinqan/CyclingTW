"""共用工具函式：路徑、JSON I/O、haversine、console 輸出。"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def day_dir(n: int) -> Path:
    return ROOT / f"day{n}"


def plan_dir(n: int) -> Path:
    p = day_dir(n) / "_plan"
    p.mkdir(parents=True, exist_ok=True)
    return p


def map_dir(n: int) -> Path:
    p = day_dir(n) / "map"
    p.mkdir(parents=True, exist_ok=True)
    return p


def dinner_map_dir(n: int) -> Path:
    p = day_dir(n) / "dinner_map"
    p.mkdir(parents=True, exist_ok=True)
    return p


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    """寫 JSON；若內容與既有檔案完全一致則跳過實際寫入但 touch 更新 mtime
    （為避免 write_text 的 I/O；mtime 必須前進，否則 Phase 0-3 預檢會認定下游檔過舊）。"""
    new_text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if path.exists():
        try:
            if path.read_text(encoding="utf-8") == new_text:
                import os, time
                now = time.time()
                os.utime(path, (now, now))
                return
        except OSError:
            pass
    path.write_text(new_text, encoding="utf-8")


def read_stdin_json() -> Any:
    raw = sys.stdin.read()
    if not raw.strip():
        die("stdin 為空，請 pipe JSON 資料進來")
    return json.loads(raw)


def die(msg: str, code: int = 1) -> None:
    print(f"[error] {msg}", file=sys.stderr)
    sys.exit(code)


def info(msg: str) -> None:
    print(f"[info] {msg}", file=sys.stderr)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """兩點地表距離（公里），用於 GPX leg 終點驗證。"""
    R = 6371
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))
