"""Local-First Geospatial Awareness, Public Feeds & Search-and-Rescue (SAR) Planning (Phase 8).

Capabilities:
- Offline geodesy: Haversine great-circle distance, initial bearing, bounding boxes,
  and deterministic Search-and-Rescue (SAR) parallel-track search grid generator.
- Official public awareness feed catalog (USGS Earthquakes, NASA EONET Wildfires,
  NWS Weather, OpenSky Public Flights, CelesTrak Public Satellites) — strictly fail-closed
  behind Internet ON, Lockdown OFF, and net.read_public_page() TLS 1.2+ public-IP pinning.
- Zero private device tracking or unauthorized surveillance.
"""
import json
import math
import re
import time

from . import net, secure

EARTH_RADIUS_KM = 6371.0088

PUBLIC_GEOSPATIAL_FEEDS = {
    "usgs_earthquakes": {
        "label": "USGS Earthquakes (Past Day, M2.5+)",
        "url": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson",
        "content_type": "application/json",
        "category": "earthquake",
        "data_class": "live",
        "attribution": "U.S. Geological Survey (Public Domain)",
        "freshness": "Updated ~every 1-5 minutes",
        "coverage": "Global M2.5+ seismic network",
    },
    "nasa_eonet_wildfires": {
        "label": "NASA EONET Open Wildfires",
        "url": "https://eonet.gsfc.nasa.gov/api/v3/events?category=wildfires&status=open&limit=25",
        "content_type": "application/json",
        "category": "wildfire",
        "data_class": "delayed",
        "attribution": "NASA Earth Observatory Natural Event Tracker (Public Domain)",
        "freshness": "Curated hourly/daily thermal anomalies",
        "coverage": "Global satellite-detected wildfire events",
    },
    "opensky_public_flights": {
        "label": "OpenSky Network Public ADS-B States",
        "url": "https://opensky-network.org/api/states/all",
        "content_type": "application/json",
        "category": "aviation",
        "data_class": "delayed",
        "attribution": "The OpenSky Network (CC-BY / Research)",
        "freshness": "10-second public snapshot (rate-limited anonymous)",
        "coverage": "Community ADS-B receivers (strongest in North America & Europe)",
    },
    "celestrak_stations": {
        "label": "CelesTrak Active Space Stations (GP/TLE)",
        "url": "https://celestrak.org/NORAD/elements/gp.php?GROUP=stations&FORMAT=json",
        "content_type": "application/json",
        "category": "satellite",
        "data_class": "estimated",
        "attribution": "CelesTrak / 18th Space Defense Squadron Public GP Catalog",
        "freshness": "Orbital elements updated ~2x daily; positions propagated mathematically",
        "coverage": "Global LEO space stations (ISS, Tiangong, etc.)",
    },
    "noaa_maritime_buoys": {
        "label": "NOAA NDBC Public Maritime Buoy Observations",
        "url": "https://www.ndbc.noaa.gov/data/latest_obs/latest_obs.txt",
        "content_type": "text/plain",
        "category": "maritime",
        "data_class": "delayed",
        "attribution": "NOAA National Data Buoy Center (Public Domain)",
        "freshness": "Updated every 10-60 minutes",
        "coverage": "US coastal, Pacific, Atlantic & Gulf stations",
    },
    "nws_weather_alerts": {
        "label": "NOAA NWS Active Severe Weather & Flood Alerts",
        "url": "https://api.weather.gov/alerts/active?limit=25",
        "content_type": "application/geo+json",
        "category": "weather",
        "data_class": "live",
        "attribution": "NOAA National Weather Service (Public Domain)",
        "freshness": "Real-time CAP alerts",
        "coverage": "United States & territories",
    },
}

KNOWN_PLACES = {
    "new york": (40.7128, -74.0060),
    "london": (51.5074, -0.1278),
    "tokyo": (35.6762, 139.6503),
    "san francisco": (37.7749, -122.4194),
    "sydney": (-33.8688, 151.2093),
    "paris": (48.8566, 2.3522),
    "denver": (39.7392, -104.9903),
    "singapore": (1.3521, 103.8198),
}


def _validate_coords(lat: float, lon: float) -> tuple[float, float]:
    la, lo = float(lat), float(lon)
    if not (-90.0 <= la <= 90.0 and -180.0 <= lo <= 180.0):
        raise ValueError("Latitude must be in [-90, 90] and longitude in [-180, 180].")
    return la, lo


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute great-circle distance in kilometers between two WGS84 points."""
    la1, lo1 = _validate_coords(lat1, lon1)
    la2, lo2 = _validate_coords(lat2, lon2)
    phi1, phi2 = math.radians(la1), math.radians(la2)
    dphi = math.radians(la2 - la1)
    dlam = math.radians(lo2 - lo1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
    return round(2.0 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a))), 3)


def initial_bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    la1, lo1 = _validate_coords(lat1, lon1)
    la2, lo2 = _validate_coords(lat2, lon2)
    phi1, phi2 = math.radians(la1), math.radians(la2)
    dlam = math.radians(lo2 - lo1)
    y = math.sin(dlam) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlam)
    return round((math.degrees(math.atan2(y, x)) + 360.0) % 360.0, 1)


def sar_search_grid(center_lat: float, center_lon: float, *, radius_km: float = 5.0, spacing_km: float = 1.0) -> dict:
    """Generate a deterministic parallel-track Search-and-Rescue (SAR) waypoint grid (offline)."""
    clat, clon = _validate_coords(center_lat, center_lon)
    rad = float(radius_km)
    spc = float(spacing_km)
    if not (0.2 <= rad <= 100.0) or not (0.1 <= spc <= rad):
        raise ValueError("Radius must be 0.2-100 km and spacing must be 0.1 km up to radius.")
    deg_lat_per_km = 1.0 / 111.32
    cos_lat = max(0.1, math.cos(math.radians(clat)))
    deg_lon_per_km = 1.0 / (111.32 * cos_lat)

    tracks = min(25, max(2, int((2.0 * rad) / spc) + 1))
    waypoints = []
    for i in range(tracks):
        offset_km = -rad + (2.0 * rad) * (i / max(1, tracks - 1))
        lat = round(max(-89.9, min(89.9, clat + offset_km * deg_lat_per_km)), 6)
        west = round(clon - rad * deg_lon_per_km, 6)
        east = round(clon + rad * deg_lon_per_km, 6)
        # Serpentine pattern minimizes transit distance between parallel sweeps
        if i % 2 == 0:
            waypoints.append({"track": i + 1, "leg": "start", "lat": lat, "lon": west})
            waypoints.append({"track": i + 1, "leg": "end", "lat": lat, "lon": east})
        else:
            waypoints.append({"track": i + 1, "leg": "start", "lat": lat, "lon": east})
            waypoints.append({"track": i + 1, "leg": "end", "lat": lat, "lon": west})

    total_track_km = round(tracks * (2.0 * rad) + (tracks - 1) * spc, 2)
    area_km2 = round((2.0 * rad) ** 2, 2)
    return {
        "center": {"lat": clat, "lon": clon},
        "radius_km": rad,
        "spacing_km": spc,
        "tracks": tracks,
        "area_km2": area_km2,
        "estimated_sweep_km": total_track_km,
        "waypoints": waypoints,
        "operational_limitations": (
            "Planning and simulation aid only. Assumes flat local tangent projection over short radii; "
            "does not account for terrain elevation, airspace restrictions, weather minimums, or certified SAR command."
        ),
    }


def extract_feed_markers(feed_id: str, raw_text: str, *, limit: int = 50) -> tuple[int, list[dict]]:
    """Parse bounded lat/lon markers from supported public geospatial feeds (never raises on missing fields)."""
    markers: list[dict] = []
    if feed_id == "noaa_maritime_buoys":
        lines = [ln.strip() for ln in (raw_text or "").splitlines() if ln.strip() and not ln.startswith("#")]
        for ln in lines[:200]:
            parts = ln.split()
            if len(parts) >= 3:
                try:
                    la, lo = _validate_coords(float(parts[1]), float(parts[2]))
                    markers.append({"lat": la, "lon": lo, "label": f"Buoy {parts[0]}"})
                    if len(markers) >= limit:
                        break
                except (ValueError, TypeError):
                    continue
        return len(lines), markers

    data = json.loads(raw_text)
    if feed_id == "usgs_earthquakes":
        feats = data.get("features") or []
        for f in feats[:limit]:
            coords = (f.get("geometry") or {}).get("coordinates") or []
            if len(coords) >= 2:
                try:
                    la, lo = _validate_coords(coords[1], coords[0])
                    props = f.get("properties") or {}
                    markers.append({"lat": la, "lon": lo, "label": str(props.get("title") or "Earthquake")[:80]})
                except (ValueError, TypeError):
                    pass
        return len(feats), markers
    if feed_id == "nasa_eonet_wildfires":
        events = data.get("events") or []
        for ev in events[:limit]:
            geom = (ev.get("geometry") or [{}])[-1]
            coords = geom.get("coordinates") or []
            if len(coords) >= 2:
                try:
                    la, lo = _validate_coords(coords[1], coords[0])
                    markers.append({"lat": la, "lon": lo, "label": str(ev.get("title") or "Wildfire")[:80]})
                except (ValueError, TypeError):
                    pass
        return len(events), markers
    if feed_id == "opensky_public_flights":
        states = data.get("states") or []
        for st in states[:limit]:
            if isinstance(st, list) and len(st) >= 7 and st[5] is not None and st[6] is not None:
                try:
                    la, lo = _validate_coords(st[6], st[5])
                    markers.append({"lat": la, "lon": lo, "label": str(st[1] or st[0] or "Flight").strip()[:40]})
                except (ValueError, TypeError):
                    pass
        return len(states), markers
    items = data if isinstance(data, list) else (data.get("features") or data.get("events") or data.get("states") or [])
    return len(items), markers


def fetch_public_feed(cfg: dict, feed_id: str) -> dict:
    """Fetch an approved public geospatial feed over pinned TLS 1.2+ HTTPS (fail-closed)."""
    if feed_id not in PUBLIC_GEOSPATIAL_FEEDS:
        raise ValueError(f"Unknown public feed '{feed_id}'.")
    spec = PUBLIC_GEOSPATIAL_FEEDS[feed_id]
    text, _ctype = net.read_public_page(spec["url"], cfg, content_types=(spec["content_type"], "application/geo+json", "application/json"))
    count, markers = extract_feed_markers(feed_id, text)
    secure.audit("geospatial_feed_read", {"feed": feed_id, "markers": len(markers)})
    return {
        "feed": feed_id,
        "label": spec["label"],
        "category": spec["category"],
        "data_class": spec.get("data_class", "delayed"),
        "attribution": spec.get("attribution", ""),
        "freshness": spec.get("freshness", ""),
        "coverage": spec.get("coverage", ""),
        "fetched_at": round(time.time(), 2),
        "item_count": count,
        "markers": markers,
    }


def estimate_orbital_track(
    name: str = "ISS (Estimated)",
    *,
    inclination_deg: float = 51.64,
    period_min: float = 92.9,
    start_lon: float = -80.0,
    steps: int = 36,
) -> dict:
    """Compute a deterministic ground-track estimation for educational/globe visualization (explicitly marked 'estimated')."""
    inc = max(0.0, min(98.0, float(inclination_deg)))
    n = max(8, min(int(steps), 72))
    points = []
    for i in range(n):
        frac = i / float(n)
        angle = 2.0 * math.pi * frac
        lat = round(inc * math.sin(angle), 4)
        lon = ((start_lon + 360.0 * frac - (period_min / 1440.0) * 360.0 * frac + 180.0) % 360.0) - 180.0
        points.append({"step": i, "lat": lat, "lon": round(lon, 4), "alt_km": 420.0})
    return {
        "name": str(name)[:60],
        "data_class": "estimated",
        "note": "Simplified circular Keplerian ground-track estimation; use live CelesTrak GP/SGP4 for precise passes.",
        "points": points,
    }


def parse_voice_navigation(command: str) -> dict:
    """Parse voice-controlled map navigation commands (e.g. 'fly to Tokyo', 'zoom to 37.7, -122.4', 'show earthquakes')."""
    text = str(command or "").strip().lower()
    coord_m = re.search(r"(-?\d{1,2}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)", text)
    if coord_m:
        la, lo = _validate_coords(float(coord_m.group(1)), float(coord_m.group(2)))
        return {"action": "fly_to", "lat": la, "lon": lo, "label": f"{la:.2f}, {lo:.2f}"}
    for place, (la, lo) in KNOWN_PLACES.items():
        if place in text:
            return {"action": "fly_to", "lat": la, "lon": lo, "label": place.title()}
    for fid, spec in PUBLIC_GEOSPATIAL_FEEDS.items():
        if spec["category"] in text or fid in text:
            return {"action": "toggle_layer", "feed": fid, "category": spec["category"]}
    if "sar" in text or "search" in text:
        return {"action": "open_sar", "label": "SAR Planning Grid"}
    return {"action": "noop", "message": "Say 'fly to London', coordinates '39.7, -105.0', or 'show earthquakes'."}


def _init_annotations_db(mem) -> None:
    with mem._lock:
        mem.db.execute(
            """CREATE TABLE IF NOT EXISTS geo_annotations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                category TEXT NOT NULL DEFAULT 'note',
                notes TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL
            )"""
        )
        mem.db.commit()


def add_annotation(mem, label: str, lat: float, lon: float, *, category: str = "note", notes: str = "") -> dict:
    la, lo = _validate_coords(lat, lon)
    clean_label = str(label or "Waypoint").strip()[:80]
    _init_annotations_db(mem)
    now = time.time()
    with mem._lock:
        cur = mem.db.execute(
            "INSERT INTO geo_annotations (label, lat, lon, category, notes, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (clean_label, la, lo, str(category or "note")[:30], str(notes or "")[:240], now),
        )
        mem.db.commit()
        aid = cur.lastrowid
    return {"id": aid, "label": clean_label, "lat": la, "lon": lo, "category": category, "notes": notes, "data_class": "user_annotation"}


def list_annotations(mem) -> list[dict]:
    _init_annotations_db(mem)
    with mem._lock:
        rows = mem.db.execute(
            "SELECT id, label, lat, lon, category, notes, created_at FROM geo_annotations ORDER BY id DESC LIMIT 100"
        ).fetchall()
    return [
        {"id": r[0], "label": r[1], "lat": r[2], "lon": r[3], "category": r[4], "notes": r[5], "created_at": r[6], "data_class": "user_annotation"}
        for r in rows
    ]


def delete_annotation(mem, annotation_id: int) -> dict:
    _init_annotations_db(mem)
    with mem._lock:
        mem.db.execute("DELETE FROM geo_annotations WHERE id=?", (int(annotation_id),))
        mem.db.commit()
    return {"ok": True, "deleted": int(annotation_id)}


def workspace_status(cfg: dict, mem=None) -> dict:
    return {
        "internet_enabled": bool(cfg.get("allow_internet_tools")),
        "lockdown": bool(cfg.get("lockdown")),
        "feeds": [
            {
                "id": fid, "label": spec["label"], "category": spec["category"], "url": spec["url"],
                "data_class": spec.get("data_class", "delayed"),
                "attribution": spec.get("attribution", ""),
                "freshness": spec.get("freshness", ""),
                "coverage": spec.get("coverage", ""),
            }
            for fid, spec in PUBLIC_GEOSPATIAL_FEEDS.items()
        ],
        "annotations": list_annotations(mem) if mem is not None else [],
        "sample_orbital_track": estimate_orbital_track(),
        "ethics_policy": "Public feeds & user annotations only. Covert surveillance and private individual tracking are prohibited.",
    }
