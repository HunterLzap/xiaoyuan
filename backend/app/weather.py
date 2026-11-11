"""Open-Meteo 天气客户端（免费、无需密钥）。

- 地理编码：城市名 -> 少量候选（含省/市/国家/时区/坐标），用于消歧。
- 天气查询：当前实况 + 可选未来每日预报（最高/最低温、天气、降雨概率、降水量），WMO 码转中文。
- 地理编码按城市名长期缓存；天气按坐标 + 查询范围 + 短 TTL 缓存，并保留数据时间。
- 数据来源需注明：Open-Meteo 气象模型数据，非附近气象站实测。
"""
from __future__ import annotations

import copy
import re
import time
from datetime import date, datetime, timedelta, timezone

import httpx

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ATTRIBUTION = "Open-Meteo（气象模型数据，非附近气象站实测）"
WEATHER_TTL_SECONDS = 600
MAX_FORECAST_DAYS = 16
_TIMEOUT = 5.0

_GEO_CACHE: dict[str, list[dict]] = {}
_WEATHER_CACHE: dict[str, tuple[float, dict]] = {}
_WEEK = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
# 与 prompt_context 一致：中国无夏令时，固定 UTC+8，不依赖 zoneinfo/tzdata。
_BEIJING = timezone(timedelta(hours=8))


class WeatherError(Exception):
    def __init__(self, code: str, message: str, status: int = 502):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


# WMO weather code -> 中文描述
_WMO = {
    0: "晴", 1: "晴间多云", 2: "多云", 3: "阴",
    45: "雾", 48: "雾凇",
    51: "毛毛雨", 53: "毛毛雨", 55: "毛毛雨", 56: "冻毛毛雨", 57: "冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨", 66: "冻雨", 67: "冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "阵雨", 81: "阵雨", 82: "强阵雨", 85: "阵雪", 86: "强阵雪",
    95: "雷阵雨", 96: "雷阵雨伴冰雹", 99: "强雷阵雨伴冰雹",
}


def wmo_cn(code) -> str:
    try:
        return _WMO.get(int(code), "未知天气")
    except (TypeError, ValueError):
        return "未知天气"


def _at(seq, index):
    if isinstance(seq, list) and 0 <= index < len(seq):
        return seq[index]
    return None


def _weekday(day_str) -> str:
    try:
        year, month, day = (int(part) for part in day_str.split("-"))
        return _WEEK[date(year, month, day).weekday()]
    except (ValueError, AttributeError):
        return ""


def _today() -> date:
    """用户在中国，问“今天/明天”按北京时间算，与全项目时间口径一致。"""
    return datetime.now(_BEIJING).date()


async def _get_json(client: httpx.AsyncClient, url: str, params: dict) -> dict:
    try:
        response = await client.get(url, params=params)
    except httpx.HTTPError:
        raise WeatherError("weather_unavailable", "天气服务连接失败，请稍后再试。") from None
    if response.status_code != 200:
        raise WeatherError("weather_upstream_error", f"天气服务返回 HTTP {response.status_code}。")
    try:
        data = response.json()
    except ValueError:
        raise WeatherError("weather_bad_response", "天气服务返回了无法识别的数据。") from None
    if not isinstance(data, dict):
        raise WeatherError("weather_bad_response", "天气服务返回了无法识别的数据。")
    return data


async def _geocode(client: httpx.AsyncClient, name: str) -> list[dict]:
    key = name.strip().lower()
    if key in _GEO_CACHE:
        return _GEO_CACHE[key]
    seen: dict[tuple, dict] = {}
    variants = _name_variants(name)
    for attempt in variants:
        data = await _get_json(client, GEOCODE_URL, {
            "name": attempt, "count": 5, "language": "zh", "format": "json",
        })
        for item in data.get("results") or []:
            if not isinstance(item, dict) or item.get("latitude") is None:
                continue
            marker = (round(float(item["latitude"]), 3), round(float(item["longitude"]), 3))
            if marker in seen:
                continue
            seen[marker] = {
                "name": item.get("name") or attempt,
                "admin1": item.get("admin1") or "",
                "admin2": item.get("admin2") or "",
                "country": item.get("country") or "",
                "latitude": item.get("latitude"),
                "longitude": item.get("longitude"),
                "timezone": item.get("timezone") or "",
                "population": item.get("population") or 0,
            }
        # 累加变体：一旦能唯一定位就停止，避免多余请求；仍歧义则继续补充候选
        if seen and _try_pick(list(seen.values()), name) is not None:
            break
    candidates = list(seen.values())
    _GEO_CACHE[key] = candidates
    return candidates


def _name_variants(name: str) -> list[str]:
    """把“辽宁省朝阳市”这类全称回退成可检索的城市名；裸城市名补“市”再试。"""
    variants: list[str] = []

    def add(value: str):
        value = value.strip()
        if value and value not in variants:
            variants.append(value)

    name = (name or "").strip()
    add(name)
    add(name.replace(" ", ""))
    if name and name[-1] not in "省市县区州盟旗":
        add(name + "市")
    for sep in ("自治区", "省", "市", "盟"):
        if sep in name:
            add(name.split(sep)[-1])
    for token in reversed(re.findall(r"[\u4e00-\u9fff]{2,10}?(?:市|县|区|州|旗|盟)", name)):
        add(token)
        add(token[:-1])
    # 口语“辽宁朝阳”“山西朝阳”这类省+城：回退到末尾城市名再查（如“朝阳”），
    # 再由 _pick 按用户明确省份匹配，避免整串查不到。
    if re.fullmatch(r"[\u4e00-\u9fff]+", name) and len(name) > 2:
        for length in (2, 3):
            if length < len(name):
                add(name[-length:])
                add(name[-length:] + "市")
    return variants


def _pick(candidates: list[dict], name: str) -> dict:
    """在候选里选出唯一地点；真正拿不准就回 location_ambiguous，绝不默认挑一个。"""
    if not candidates:
        raise WeatherError("location_not_found", f"没找到城市“{name}”，请换个更具体的城市名。", 422)
    norm = (name or "").strip()
    norm_compact = norm.replace(" ", "")
    unique: dict[tuple, dict] = {}
    for candidate in candidates:
        marker = (round(float(candidate["latitude"]), 3), round(float(candidate["longitude"]), 3))
        unique.setdefault(marker, candidate)
    items = list(unique.values())
    if len(items) == 1:
        return items[0]

    def region_match(candidate: dict) -> bool:
        # 只认用户话里明确出现的省份/国家，避免拿候选自身市名反推
        for region in (candidate.get("admin1"), candidate.get("country")):
            if not region or region == "中国":
                continue
            if region in norm_compact or norm_compact in region:
                return True
        return False

    matched = [candidate for candidate in items if region_match(candidate)]
    pool = matched or items
    ordered = sorted(pool, key=lambda candidate: candidate.get("population") or 0, reverse=True)
    top = ordered[0]
    if len(ordered) == 1:
        return top
    second = ordered[1]
    if (top.get("name"), top.get("admin1"), top.get("admin2")) == (
            second.get("name"), second.get("admin1"), second.get("admin2")):
        return top
    top_pop = top.get("population") or 0
    second_pop = second.get("population") or 0
    # 明确的大城市（>= 50 万人，且领先次选 10 倍或次选无人口）才直接采用
    if top_pop >= 500000 and (second_pop == 0 or top_pop >= second_pop * 10):
        return top
    label = "、".join(f"{c.get('admin1') or ''}{c.get('name') or ''}".strip() for c in ordered[:4])
    raise WeatherError("location_ambiguous",
                       f"“{name}”有多个同名地点：{label}。请告诉我具体是哪个省市。", 422)


def _try_pick(candidates: list[dict], name: str):
    try:
        return _pick(candidates, name)
    except WeatherError:
        return None


def _parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        raise WeatherError("weather_bad_date", f"{field} 格式应为 YYYY-MM-DD。", 422) from None


def _request_scope(days, start_date: str, end_date: str):
    """解析范围参数，返回 (kind, payload)。

    - ("current", None)        只查当前实况
    - ("days", n)              从今天起 n 天，交给接口按地点时区锚定
    - ("range", (start, end))  明确日期区间（date 对象）
    """
    start_text = (start_date or "").strip()
    end_text = (end_date or "").strip()
    if start_text or end_text:
        today = _today()
        start = _parse_date(start_text, "start_date") if start_text else today
        end = _parse_date(end_text, "end_date") if end_text else start
        if end < start:
            raise WeatherError("weather_bad_range", "结束日期不能早于开始日期。", 422)
        latest = today + timedelta(days=MAX_FORECAST_DAYS - 1)
        if start < today:
            raise WeatherError("weather_date_out_of_range",
                               f"只能查询 {today.isoformat()} 及以后的天气（不翻查过去）。", 422)
        if end > latest:
            raise WeatherError("weather_date_out_of_range",
                               f"最多只能预报到 {latest.isoformat()}（未来 {MAX_FORECAST_DAYS} 天）。", 422)
        return "range", (start, end)
    if days not in (None, ""):
        try:
            count = int(days)
        except (TypeError, ValueError):
            raise WeatherError("weather_bad_range", "days 必须是整数。", 422) from None
        if count < 1:
            raise WeatherError("weather_bad_range", "days 至少为 1。", 422)
        return "days", min(count, MAX_FORECAST_DAYS)
    return "current", None


async def get_weather(city: str, default_city: str = "", days=None,
                      start_date: str = "", end_date: str = "") -> dict:
    """查询天气。

    - 只给 city（不给 days/日期）时：返回当前实况（保持旧 city-only 调用不变）。
    - 给 days 或 start_date/end_date 时：在实况之外附上每日预报。
    - 城市缺失时用 default_city，仍无则抛 location_required。
    """
    city = (city or "").strip() or (default_city or "").strip()
    if not city:
        raise WeatherError("location_required", "需要先告诉我城市（例如“北京”），我才能查天气。", 422)
    async with httpx.AsyncClient(trust_env=False, timeout=_TIMEOUT) as client:
        place = _pick(await _geocode(client, city), city)
        lat, lon = float(place["latitude"]), float(place["longitude"])
        tz_name = place.get("timezone") or ""
        scope_kind, scope_value = _request_scope(days, start_date, end_date)
        if scope_kind == "range":
            cache_key = f"{lat:.3f},{lon:.3f}|{scope_value[0].isoformat()}|{scope_value[1].isoformat()}"
        elif scope_kind == "days":
            cache_key = f"{lat:.3f},{lon:.3f}|days={scope_value}"
        else:
            cache_key = f"{lat:.3f},{lon:.3f}|current"
        now = time.monotonic()
        cached = _WEATHER_CACHE.get(cache_key)
        if cached and now - cached[0] < WEATHER_TTL_SECONDS:
            return copy.deepcopy(cached[1])
        params = {
            "latitude": lat, "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,precipitation,weather_code,wind_speed_10m",
            "timezone": "auto",
        }
        if scope_kind != "current":
            params["daily"] = ("temperature_2m_max,temperature_2m_min,weather_code,"
                               "precipitation_probability_max,precipitation_sum")
            if scope_kind == "range":
                params["start_date"] = scope_value[0].isoformat()
                params["end_date"] = scope_value[1].isoformat()
            else:
                params["forecast_days"] = scope_value
        data = await _get_json(client, FORECAST_URL, params)
        current = data.get("current") or {}
        if "temperature_2m" not in current:
            raise WeatherError("weather_invalid", "天气服务未返回当前天气数据。")
        location = f"{place['admin1']}{place['name']}".strip() or place["name"]
        tz_suffix = f" {tz_name}" if tz_name else ""
        report = {
            "地点": location,
            "数据时间": str(current.get("time") or "") + tz_suffix,
            "天气": wmo_cn(current.get("weather_code")),
            "温度℃": current.get("temperature_2m"),
            "湿度": current.get("relative_humidity_2m"),
            "降水mm": current.get("precipitation"),
            "风速": f"{current.get('wind_speed_10m')}km/h",
        }
        if scope_kind != "current":
            daily = data.get("daily") or {}
            times = daily.get("time") or []
            forecast = []
            for index, day_str in enumerate(times):
                high = _at(daily.get("temperature_2m_max"), index)
                low = _at(daily.get("temperature_2m_min"), index)
                if high is None and low is None:
                    continue  # 接口在预报末端可能给空温度，跳过避免“未知天气/空值”
                forecast.append({
                    "日期": day_str,
                    "星期": _weekday(day_str),
                    "天气": wmo_cn(_at(daily.get("weather_code"), index)),
                    "最高℃": high,
                    "最低℃": low,
                    "降水概率%": _at(daily.get("precipitation_probability_max"), index),
                    "降水量mm": _at(daily.get("precipitation_sum"), index),
                })
            if not forecast:
                raise WeatherError("weather_invalid", "天气服务未返回每日预报数据。")
            report["覆盖日期"] = f"{forecast[0]['日期']} 至 {forecast[-1]['日期']}（每日预报）"
            report["预报"] = forecast
        report["source"] = ATTRIBUTION
        _WEATHER_CACHE[cache_key] = (now, copy.deepcopy(report))
        return report
