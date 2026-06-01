"""共用工具函式：路徑、JSON I/O、haversine、console 輸出。"""
from __future__ import annotations

import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def _load_dotenv():
    """從專案根目錄 .env 載入環境變數（不覆蓋已設定的值）。"""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'\"")
        if key not in os.environ:
            os.environ[key] = val


_load_dotenv()


# ── 必經景點（index.md must_visit_landmarks）正規化與配對 ──────────────────
# index.md 的「景點」欄位混有 markdown 裝飾（**極西：國聖燈塔**）、區域名（墾丁、
# 八里、東北角）與騎乘敘述（可視體力先騎…、回蘆洲完騎）。以下三個 helper 共用於
# parse-index（清理）、render-md gate（覆蓋檢查）、route 繞路豁免，確保三處對「必經
# 景點是什麼、是否已涵蓋」判斷一致。
_NOTE_WORDS = re.compile(r"完騎|可視|體力|住宿|建議|視情況|沿途|可先|再回到?|若")


def normalize_landmark(s: str) -> str:
    """清掉必經景點名的裝飾：markdown 粗體 *、極東西南北：前綴、前後空白。"""
    s = (s or "").replace("*", "").strip()
    s = re.sub(r"^極[東西南北][：:]\s*", "", s)
    return s.strip()


def is_note_landmark(s: str) -> bool:
    """判斷是否為敘述/備註而非真正的景點名（過長或含騎乘指示用語）。"""
    lm = normalize_landmark(s)
    return len(lm) > 8 or bool(_NOTE_WORDS.search(lm))


def landmark_matches_name(landmark: str, name: str) -> bool:
    """必經景點名是否對應某航點名（雙向含括，或字元重疊 ≥ 0.5）。"""
    lm = normalize_landmark(landmark)
    if not lm or not name:
        return False
    lset = set(lm)
    return lm in name or name in lm or len(lset & set(name)) / len(lset) >= 0.5


def landmark_covered(landmark: str, names: list[str], context_text: str = "") -> bool:
    """必經景點是否已被涵蓋。

    涵蓋條件（任一）：(1) 對應某航點名（landmark_matches_name）；(2) 區域名出現在
    當天 origin/dest/route 文字（context_text，子字串或字元重疊 ≥ 0.5）。空字串與
    敘述型（is_note_landmark）一律視為已涵蓋（不擋）。直接處理尚未經 parse-index
    清理的 dirty config：複合項（如「淡水 / 八里」）任一子項涵蓋即算涵蓋。
    """
    lm = normalize_landmark(landmark)
    if not lm or is_note_landmark(landmark):
        return True
    for part in re.split(r"[/／]", lm):
        part = part.strip()
        if not part:
            continue
        if any(landmark_matches_name(part, nm) for nm in names):
            return True
        pset = set(part)
        if context_text and (part in context_text
                             or len(pset & set(context_text)) / len(pset) >= 0.5):
            return True
    return False


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


def hotel_map_dir(n: int) -> Path:
    p = day_dir(n) / "hotel_map"
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


def load_protagonist() -> tuple[str, str]:
    """從 ROOT/主角.md 解析角色提示詞與負面限制。回傳 (prompt, negative)。"""
    import re
    path = ROOT / "主角.md"
    if not path.exists():
        die(f"找不到 {path}，請確認專案根目錄有 主角.md")
    text = path.read_text(encoding="utf-8")
    m_prompt = re.search(
        r"##\s*可直接放入產圖 Prompt 的版本\s*\n+([\s\S]+?)(?=\n##|\Z)", text
    )
    m_neg = re.search(
        r"##\s*負面限制\s*\n+([\s\S]+?)(?=\n##|\Z)", text
    )
    protagonist_prompt = m_prompt.group(1).strip() if m_prompt else ""
    protagonist_negative = m_neg.group(1).strip() if m_neg else ""
    if not protagonist_prompt:
        die("主角.md 中找不到「可直接放入產圖 Prompt 的版本」段落")
    if not protagonist_negative:
        die("主角.md 中找不到「負面限制」段落")
    return protagonist_prompt, protagonist_negative


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """兩點地表距離（公里），用於 GPX leg 終點驗證。"""
    R = 6371
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def downsample(points: list, max_pts: int = 512) -> list:
    """等間隔抽稀折線點，避免 4000+ 點的 encoded polyline 過長。保留頭尾。"""
    n = len(points)
    if n <= max_pts:
        return list(points)
    step = n / max_pts
    out = [points[int(i * step)] for i in range(max_pts)]
    if out[-1] != points[-1]:
        out[-1] = points[-1]
    return out


def encode_polyline(points: list) -> str:
    """把 [lat, lng] 點列編成 Google encoded polyline（演算法 precision 5）。

    供 Google Places API (New) searchAlongRouteParameters 使用。無外部相依。
    """
    def _enc(value: int) -> str:
        value = ~(value << 1) if value < 0 else (value << 1)
        chunks = []
        while value >= 0x20:
            chunks.append(chr((0x20 | (value & 0x1F)) + 63))
            value >>= 5
        chunks.append(chr(value + 63))
        return "".join(chunks)

    out = []
    prev_lat = prev_lng = 0
    for lat, lng in points:
        ilat = round(lat * 1e5)
        ilng = round(lng * 1e5)
        out.append(_enc(ilat - prev_lat))
        out.append(_enc(ilng - prev_lng))
        prev_lat, prev_lng = ilat, ilng
    return "".join(out)
