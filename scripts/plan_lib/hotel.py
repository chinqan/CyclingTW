"""住宿選點 hotel-*：薄殼，邏輯見 poi_pool（晚餐 / 住宿共用）。

hotel-search / hotel-status / hotel-pool / hotel-review / hotel-render。
本地鏡像 DB：dayN/hotel_map/。人工微調直接編 dayN/hotel_map/<place_id>.json。
"""
from __future__ import annotations

from . import poi_pool

# Google Places primary_type 住宿類白名單；searchText 即便指定 includedType=lodging
# 仍會混入餐廳/運動場/景點，必須在 client 端嚴格過濾。
LODGING_PRIMARY_TYPES = {
    "lodging",
    "hotel",
    "motel",
    "resort_hotel",
    "extended_stay_hotel",
    "inn",
    "bed_and_breakfast",
    "private_guest_room",
    "guest_house",
    "hostel",
    "campground",
    "cottage",
    "farmstay",
    "japanese_inn",
}


def _keep(pt: str | None) -> bool:
    # None 放行（無 type）；有 type 則必須屬於住宿白名單
    return (not pt) or (pt in LODGING_PRIMARY_TYPES)


SPEC = poi_pool.POISpec(
    kind="hotel",
    noun="住宿",
    included_type="lodging",
    search_text_queries=("飯店", "民宿", "旅館", "Hotel"),
    type_keep=_keep,
    type_reject_label="非住宿類",
    array_key="hotels",
    select_emoji="🏨",
    title_emoji="🏨",
    include_type_label=False,
    default_note_from_label=False,
)


def cmd_hotel_search(args):
    return poi_pool.cmd_search(args, SPEC)


def cmd_hotel_status(args):
    return poi_pool.cmd_status(args, SPEC)


def cmd_hotel_pool(args):
    return poi_pool.cmd_pool(args, SPEC)


def cmd_hotel_review(args):
    return poi_pool.cmd_review(args, SPEC)


def cmd_hotel_render(args):
    return poi_pool.cmd_render(args, SPEC)
