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
) -> tuple[list[dict], int]:
    """Search for POIs near a location. Returns (examples, total_count)."""
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
        return [], 0
    results = data.get("results", [])
    # Use API-reported total, fall back to len(results)
    total = data.get("total", len(results))
    return results, total


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

    # Resolve location — if lat/lng provided, use them directly
    if lat is not None and lng is not None:
        pass  # use provided coordinates
    elif location_name and location_name in LOCATIONS:
        loc = LOCATIONS[location_name]
        lat, lng = loc["lat"], loc["lng"]
        city = loc["city"]
    elif location_name:
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
        examples, total = await _search_pois(ak, cat_info["query"], lat, lng, radius_m)
        weighted = total * cat_info["weight"]
        total_weighted_score += weighted
        category_results[cat_name] = {
            "count": total,
            "weighted": round(weighted, 1),
            "examples": [p.get("name", "") for p in examples],
        }

    # Normalize to 0-100 score
    # Calibration: 400 weighted POIs in 500m ≈ score 100 (very busy commercial district)
    traffic_score = min(100, round(total_weighted_score * 100 / 400))

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


async def generate_store_recommendation(analysis_data: dict) -> dict:
    """Call DeepSeek V3 via OpenRouter to generate expert store opening recommendations.

    Args:
        analysis_data: Output from analyze_location_traffic().

    Returns:
        Dict with recommended_types, avoid_types, key_insights, warnings, etc.
    """
    location = analysis_data.get("location", "未知")
    address = analysis_data.get("address", "未知")
    city = analysis_data.get("city", "未知")
    traffic_score = analysis_data.get("traffic_score", 0)
    traffic_level = analysis_data.get("traffic_level", "未知")
    traffic_desc = analysis_data.get("traffic_desc", "")
    category_breakdown = analysis_data.get("category_breakdown", {})
    hourly_estimate = analysis_data.get("hourly_estimate", {})
    peak_hours = analysis_data.get("peak_hours", [])
    total_weighted_pois = analysis_data.get("total_weighted_pois", 0)

    # Build category detail text
    category_lines = []
    for cat_name, cat_data in category_breakdown.items():
        examples_str = "、".join(cat_data.get("examples", [])) or "无"
        category_lines.append(
            f"  - {cat_name}: {cat_data.get('count', 0)}家 "
            f"(加权分: {cat_data.get('weighted', 0)}), 代表: {examples_str}"
        )
    category_text = "\n".join(category_lines)

    # Build hourly estimate text
    hourly_lines = []
    for hour in sorted(hourly_estimate.keys(), key=lambda h: int(h)):
        hourly_lines.append(f"  {hour}时: {hourly_estimate[hour]}")
    hourly_text = "\n".join(hourly_lines)

    peak_hours_str = "、".join(str(h) for h in peak_hours) if peak_hours else "无数据"

    user_prompt = f"""请根据以下商圈数据，给出专业的开店建议。

【位置信息】
- 地点名称: {location}
- 详细地址: {address}
- 城市: {city}

【人流评估】
- 人流评分: {traffic_score}/100
- 人流等级: {traffic_level} ({traffic_desc})
- 加权POI总分: {total_weighted_pois}

【商业业态分布】
{category_text}

【每小时人流估算】
{hourly_text}

【高峰时段】
{peak_hours_str}时

请基于以上数据，返回一个JSON对象，包含以下字段：
- recommended_types: 推荐开设的店铺类型列表，每项包含 type(店铺类型), reason(推荐理由), confidence(推荐信心0-100), monthly_rent_estimate(月租金估算范围)
- avoid_types: 不建议开设的店铺类型列表，每项包含 type(不建议类型), reason(原因)
- key_insights: 关键洞察列表（字符串数组）
- warnings: 注意事项列表（字符串数组）
- best_opening_hours: 建议营业时段
- target_customers: 目标客群描述
- competition_analysis: 竞争分析
- overall_rating: 总体评级(A/B/C/D)
- overall_comment: 总体评价

只返回JSON，不要有其他文字。"""

    system_prompt = (
        "你是中国顶级商业选址顾问，拥有20年连锁餐饮和零售选址经验。"
        "你擅长通过商圈数据分析给出精准的开店建议。请用专业但易懂的中文回答。"
    )

    api_url = settings.openrouter_base_url.strip().rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key.strip()}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.openrouter_model.strip(),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.7,
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(api_url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        content = data["choices"][0]["message"]["content"]
        recommendation = json.loads(content)
        return recommendation

    except (httpx.HTTPStatusError, httpx.RequestError) as e:
        logger.error(f"OpenRouter API call failed: {e}")
        return {
            "error": f"AI API call failed: {type(e).__name__}: {e}",
            "recommended_types": [],
            "avoid_types": [],
            "key_insights": [],
            "warnings": ["AI推荐服务暂时不可用，请稍后重试"],
            "best_opening_hours": "",
            "target_customers": "",
            "competition_analysis": "",
            "overall_rating": "",
            "overall_comment": "AI推荐服务暂时不可用",
        }
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.error(f"Failed to parse AI response: {e}")
        return {
            "error": f"AI response parse failed: {type(e).__name__}: {e}",
            "recommended_types": [],
            "avoid_types": [],
            "key_insights": [],
            "warnings": ["AI返回数据格式异常，请稍后重试"],
            "best_opening_hours": "",
            "target_customers": "",
            "competition_analysis": "",
            "overall_rating": "",
            "overall_comment": "AI返回数据格式异常",
        }


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
