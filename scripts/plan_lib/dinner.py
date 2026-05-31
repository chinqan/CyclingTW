"""晚餐選點 dinner-*：薄殼，邏輯見 poi_pool（晚餐 / 住宿共用）。

dinner-search / dinner-status / dinner-pool / dinner-review / dinner-render。
本地鏡像 DB：dayN/dinner_map/。人工微調直接編 dayN/dinner_map/<place_id>.json。
"""
from __future__ import annotations

from . import poi_pool

# 餐廳類 primary_type 白名單：含 "restaurant" 的子類一律放行，再加上幾個
# 無 restaurant 字根但屬正餐的類型。
DINNER_EXTRA_TYPES = {
    "food", "cafe", "meal_takeaway", "meal_delivery",
    "bakery", "diner", "deli", "sandwich_shop",
    "steak_house", "ice_cream_shop", "donut_shop",
    "fast_food_restaurant",
}


def _keep(pt: str | None) -> bool:
    if not pt:
        return True  # 無 type 暫且放行（Bayesian 後人工再檢查）
    if "restaurant" in pt:
        return True
    return pt in DINNER_EXTRA_TYPES


SPEC = poi_pool.POISpec(
    kind="dinner",
    noun="晚餐",
    included_type="restaurant",
    search_text_queries=("餐廳", "美食", "小吃", "食堂"),
    type_keep=_keep,
    type_reject_label="非餐廳類",
    array_key="restaurants",
    select_emoji="🏆",
    title_emoji="🍽️",
    include_type_label=True,
    default_note_from_label=True,
)


def cmd_dinner_search(args):
    return poi_pool.cmd_search(args, SPEC)


def cmd_dinner_status(args):
    return poi_pool.cmd_status(args, SPEC)


def cmd_dinner_pool(args):
    return poi_pool.cmd_pool(args, SPEC)


def cmd_dinner_review(args):
    return poi_pool.cmd_review(args, SPEC)


def cmd_dinner_render(args):
    return poi_pool.cmd_render(args, SPEC)
