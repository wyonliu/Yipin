"""Foot traffic monitoring engine.

Monitors pedestrian flow around target locations using Baidu Maps POI data.
Provides multi-category business density analysis as traffic proxy,
24-hour monitoring with time-based modeling, and daily summaries.

Data source: Baidu Maps Place Search API (POI density + category mix)
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime
from pathlib import Path

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)

# POI categories and their traffic weights
# Higher weight = stronger indicator of foot traffic
POI_CATEGORIES = {
    "餐饮": {"query": "餐厅", "weight": 1.0},
    "小吃奶茶": {"query": "奶茶", "weight": 1.0},
    "超市便利": {"query": "超市", "weight": 1.2},
    "商场": {"query": "商场", "weight": 1.2},
    "咖啡休闲": {"query": "咖啡", "weight": 0.8},
    "地铁公交": {"query": "地铁站", "weight": 1.5},
    "写字楼": {"query": "写字楼", "weight": 0.6},
    "银行": {"query": "银行", "weight": 0.5},
}

# Time-based traffic multipliers (hour → multiplier)
# Based on typical Chinese urban patterns
HOURLY_MULTIPLIERS = {
    0: 0.05, 1: 0.03, 2: 0.02, 3: 0.02, 4: 0.03, 5: 0.10,
    6: 0.25, 7: 0.55, 8: 0.80, 9: 0.70, 10: 0.65, 11: 0.85,
    12: 1.00, 13: 0.80, 14: 0.65, 15: 0.60, 16: 0.65, 17: 0.90,
    18: 1.00, 19: 0.95, 20: 0.80, 21: 0.60, 22: 0.35, 23: 0.15,
}

# Known locations
LOCATIONS = {
    "华星发展大厦": {
        "city": "杭州",
        "lat": 30.289209,
        "lng": 120.131394,
        "address": "杭州市西湖区文二路328号",
    },
}


def _get_baidu_ak() -> str:
    ak = getattr(settings, "baidu_map_ak", "") or ""
    return ak.strip()


async def _search_pois(
    ak: str, query: str, lat: float, lng: float, radius: int = 500
) -> list[dict]:
    """Search for POIs near a location."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://api.map.baidu.com/place/v2/search",
            params={
                "query": query,
                "location": f"{lat},{lng}",
                "radius": radius,
                "output": "json",
                "ak": ak,
                "page_size": 20,
            },
        )
        resp.raise_for_status()
        data = resp.json()
    if data.get("status") != 0:
        return []
    return data.get("results", [])


async def analyze_location_traffic(
    location_name: str | None = None,
    lat: float | None = None,
    lng: float | None = None,
    radius_m: int = 500,
    city: str = "杭州",
) -> dict:
    """Comprehensive foot traffic analysis using multi-category POI density.

    Returns a traffic score (0-100), category breakdown, and estimated
    hourly traffic pattern.
    """
    ak = _get_baidu_ak()
    if not ak:
        return {"error": "baidu_map_ak not configured"}

    # Resolve location
    if location_name and location_name in LOCATIONS:
        loc = LOCATIONS[location_name]
        lat, lng = loc["lat"], loc["lng"]
        city = loc["city"]
    elif lat is None or lng is None:
        # Try searching by name
        if location_name:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    "https://api.map.baidu.com/place/v2/search",
                    params={
                        "query": location_name,
                        "region": city,
                        "output": "json",
                        "ak": ak,
                    },
                )
                resp.raise_for_status()
                result = resp.json()
            pois = result.get("results", [])
            if not pois:
                return {"error": f"Location '{location_name}' not found"}
            target = pois[0]
            loc_data = target.get("location", {})
            lat, lng = loc_data.get("lat"), loc_data.get("lng")
            location_name = target.get("name", location_name)
        else:
            return {"error": "Must provide location_name or lat/lng"}

    # Search each POI category
    category_results = {}
    total_weighted_score = 0.0

    for cat_name, cat_info in POI_CATEGORIES.items():
        pois = await _search_pois(ak, cat_info["query"], lat, lng, radius_m)
        count = len(pois)
        weighted = count * cat_info["weight"]
        total_weighted_score += weighted
        category_results[cat_name] = {
            "count": count,
            "weighted": round(weighted, 1),
            "examples": [p.get("name", "") for p in pois[:3]],
        }

    # Normalize to 0-100 score
    # Calibration: 50 weighted POIs in 500m = score 50 (moderate traffic)
    traffic_score = min(100, round(total_weighted_score * 100 / 100))

    # Generate 24-hour traffic estimate
    now_hour = datetime.now().hour
    current_multiplier = HOURLY_MULTIPLIERS.get(now_hour, 0.5)
    base_traffic = total_weighted_score / current_multiplier if current_multiplier > 0 else total_weighted_score

    hourly_estimate = {}
    for hour, mult in HOURLY_MULTIPLIERS.items():
        hourly_estimate[hour] = round(base_traffic * mult)

    # Traffic level
    if traffic_score >= 70:
        level = "高"
        level_desc = "商业密集区，人流量大"
    elif traffic_score >= 40:
        level = "中"
        level_desc = "商业活跃区，人流量适中"
    elif traffic_score >= 15:
        level = "低"
        level_desc = "商业稀疏区，人流量较小"
    else:
        level = "极低"
        level_desc = "偏僻区域，几乎无商业活动"

    return {
        "location": location_name or f"{lat},{lng}",
        "address": LOCATIONS.get(location_name, {}).get("address", ""),
        "city": city,
        "lat": lat,
        "lng": lng,
        "radius_m": radius_m,
        "traffic_score": traffic_score,
        "traffic_level": level,
        "traffic_desc": level_desc,
        "category_breakdown": category_results,
        "total_weighted_pois": round(total_weighted_score, 1),
        "hourly_estimate": hourly_estimate,
        "current_hour": now_hour,
        "current_estimate": hourly_estimate.get(now_hour, 0),
        "peak_hours": [h for h, m in HOURLY_MULTIPLIERS.items() if m >= 0.9],
        "timestamp": datetime.now().isoformat(),
        "data_source": "baidu_maps_poi",
    }


async def fetch_poi_traffic(location_name: str, city: str = "杭州") -> dict:
    """Quick traffic check using POI density (lightweight version)."""
    return await analyze_location_traffic(
        location_name=location_name, city=city
    )


async def monitor_24h(
    location_name: str = "华星发展大厦",
    city: str = "杭州",
) -> dict:
    """Run a single monitoring snapshot (call hourly for 24h monitoring)."""
    result = await analyze_location_traffic(
        location_name=location_name, city=city
    )

    snapshot = {
        "location": location_name,
        "city": city,
        "hour": datetime.now().hour,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "data": result,
    }

    # Save snapshot to disk
    output_dir = Path(__file__).parent / "static" / "traffic"
    output_dir.mkdir(parents=True, exist_ok=True)

    snapshots_file = output_dir / f"snapshots_{datetime.now().strftime('%Y%m%d')}.json"
    existing = []
    if snapshots_file.exists():
        existing = json.loads(snapshots_file.read_text(encoding="utf-8"))
    existing.append(snapshot)
    snapshots_file.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return snapshot


def generate_daily_summary(date_str: str | None = None) -> dict:
    """Generate a daily foot traffic summary from saved snapshots."""
    if not date_str:
        date_str = datetime.now().strftime("%Y%m%d")

    snapshots_file = (
        Path(__file__).parent / "static" / "traffic"
        / f"snapshots_{date_str}.json"
    )

    if not snapshots_file.exists():
        return {"error": f"No data for date {date_str}"}

    snapshots = json.loads(snapshots_file.read_text(encoding="utf-8"))

    hourly_data = {}
    for s in snapshots:
        hour = s.get("hour", 0)
        data = s.get("data", {})
        score = data.get("traffic_score") or data.get("nearby_businesses") or 0
        hourly_data[hour] = score

    peak_hour = max(hourly_data, key=hourly_data.get) if hourly_data else 0
    avg_score = sum(hourly_data.values()) / len(hourly_data) if hourly_data else 0

    return {
        "date": date_str,
        "location": snapshots[0].get("location", "") if snapshots else "",
        "snapshots_count": len(snapshots),
        "hourly_data": hourly_data,
        "peak_hour": peak_hour,
        "peak_score": hourly_data.get(peak_hour, 0),
        "average_score": round(avg_score, 1),
        "data_source": "baidu_maps_poi",
    }
