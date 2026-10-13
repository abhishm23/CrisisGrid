"""
CrisisGrid — Infrastructure Disaster Routing Engine
====================================================
Dynamically recalculates critical transit corridors across a regional
transportation graph when live seismic hazard zones disrupt network
nodes and bridge crossings.

Powered by:
  • USGS Earthquake Hazards Program real-time GeoJSON feed
  • Haversine great-circle spatial impact analysis
  • Dijkstra shortest-path rerouting with exponential penalty mutation
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any

import networkx as nx
import requests
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.requests import Request

# ─── Configuration ───────────────────────────────────────────────────────────

USGS_FEED = (
    "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson"
)
R_EARTH: float = 6_371.0        # Earth mean radius in km
DAMAGE_FACTOR: float = 25.0     # impact radius = magnitude × 25 km
PENALTY: float = 50.0           # edge-weight multiplier for disrupted links
CACHE_TTL: int = 60             # seconds to cache USGS responses

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-12s  %(levelname)-8s  %(message)s",
)
log = logging.getLogger("crisisgrid")

# ─── Transportation Graph Topology ──────────────────────────────────────────
# 10 logistical transit hubs / depots / bridge junctions across the
# seismically active Western United States corridor.

NODES: dict[str, dict[str, Any]] = {
    "SEA": {"name": "Seattle Distribution Center",  "lat": 47.6062, "lon": -122.3321, "type": "hub"},
    "PDX": {"name": "Portland Regional Depot",      "lat": 45.5152, "lon": -122.6784, "type": "depot"},
    "BOI": {"name": "Boise Supply Depot",            "lat": 43.6150, "lon": -116.2023, "type": "depot"},
    "RNO": {"name": "Reno Bridge Junction",          "lat": 39.5296, "lon": -119.8138, "type": "bridge"},
    "SAC": {"name": "Sacramento Bridge Junction",    "lat": 38.5816, "lon": -121.4944, "type": "bridge"},
    "SFO": {"name": "San Francisco Logistics Hub",   "lat": 37.7749, "lon": -122.4194, "type": "hub"},
    "SLC": {"name": "Salt Lake City Hub",            "lat": 40.7608, "lon": -111.8910, "type": "hub"},
    "LAS": {"name": "Las Vegas Transit Hub",         "lat": 36.1699, "lon": -115.1398, "type": "hub"},
    "LAX": {"name": "Los Angeles Relief Depot",      "lat": 34.0522, "lon": -118.2437, "type": "depot"},
    "PHX": {"name": "Phoenix Regional Depot",        "lat": 33.4484, "lon": -112.0740, "type": "depot"},
}

# (source, target, approximate road distance in km)
EDGES: list[tuple[str, str, float]] = [
    ("SEA", "PDX", 280),   ("SEA", "BOI", 740),
    ("PDX", "BOI", 690),   ("PDX", "RNO", 700),   ("PDX", "SAC", 960),
    ("SAC", "SFO", 140),   ("SAC", "RNO", 220),
    ("SFO", "RNO", 350),   ("SFO", "LAX", 620),
    ("LAX", "LAS", 440),   ("LAX", "PHX", 600),
    ("LAS", "PHX", 480),   ("LAS", "SLC", 670),   ("LAS", "RNO", 710),
    ("SLC", "BOI", 490),   ("SLC", "RNO", 830),
    ("PHX", "SLC", 970),   ("RNO", "BOI", 430),
]


# ─── Haversine Distance ─────────────────────────────────────────────────────

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance (km) between two WGS-84 points.

    d = 2R·arcsin( √[ sin²(Δφ/2) + cos(φ₁)·cos(φ₂)·sin²(Δλ/2) ] )
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
    )
    return 2 * R_EARTH * math.asin(math.sqrt(a))


# ─── Graph Builder ───────────────────────────────────────────────────────────

def _build_graph() -> nx.Graph:
    """Construct the base transportation network (undirected weighted graph)."""
    G = nx.Graph()
    for nid, attrs in NODES.items():
        G.add_node(nid, **attrs)
    for u, v, d in EDGES:
        G.add_edge(u, v, weight=d, base_weight=d)
    return G


# ─── USGS Earthquake Feed (with TTL cache) ──────────────────────────────────

_eq_cache: dict[str, Any] = {"data": None, "ts": None}


def _fetch_quakes() -> list[dict]:
    """Return M2.5+ earthquakes from the last 24 h (cached)."""
    now = datetime.now(timezone.utc)
    if (
        _eq_cache["data"] is not None
        and _eq_cache["ts"] is not None
        and (now - _eq_cache["ts"]).total_seconds() < CACHE_TTL
    ):
        return _eq_cache["data"]

    try:
        r = requests.get(USGS_FEED, timeout=10)
        r.raise_for_status()
        features = r.json().get("features", [])
        out: list[dict] = []
        for f in features:
            p = f.get("properties", {})
            c = f.get("geometry", {}).get("coordinates", [])
            mag = p.get("mag")
            if len(c) >= 2 and mag:
                out.append(
                    {
                        "id": f.get("id", "?"),
                        "mag": mag,
                        "place": p.get("place", ""),
                        "time": p.get("time", 0),
                        "lat": c[1],
                        "lon": c[0],
                        "depth": c[2] if len(c) > 2 else 0,
                        "impact_radius": mag * DAMAGE_FACTOR,
                    }
                )
        _eq_cache.update(data=out, ts=now)
        log.info("USGS feed: %d seismic events ingested", len(out))
        return out
    except Exception as exc:
        log.warning("USGS fetch failed: %s", exc)
        return _eq_cache.get("data") or []


# ─── Spatial Impact Assessment ───────────────────────────────────────────────

def _assess_damage(quakes: list[dict]) -> dict[str, list[dict]]:
    """Identify nodes within earthquake damage radii via Haversine check."""
    damaged: dict[str, list[dict]] = {}
    for nid, node in NODES.items():
        hits: list[dict] = []
        for q in quakes:
            dist = haversine(node["lat"], node["lon"], q["lat"], q["lon"])
            if dist <= q["impact_radius"]:
                hits.append(
                    {
                        "eq_id": q["id"],
                        "mag": q["mag"],
                        "dist_km": round(dist, 1),
                        "radius": q["impact_radius"],
                    }
                )
        if hits:
            damaged[nid] = hits
    return damaged


# ─── Edge Penalty Mutation ───────────────────────────────────────────────────

def _penalise(G: nx.Graph, bad: set[str]) -> nx.Graph:
    """Apply 50× exponential penalty to edges touching disrupted nodes."""
    Gc = G.copy()
    for u, v, d in Gc.edges(data=True):
        d["penalized"] = u in bad or v in bad
        if d["penalized"]:
            d["weight"] = d["base_weight"] * PENALTY
    return Gc


# ─── Dijkstra Shortest-Path Routing ─────────────────────────────────────────

def _route(G: nx.Graph, src: str, dst: str) -> dict | None:
    """Compute the minimum-cost path via Dijkstra's algorithm."""
    try:
        path = nx.shortest_path(G, src, dst, weight="weight")
        cost = nx.shortest_path_length(G, src, dst, weight="weight")
        segs = []
        for i in range(len(path) - 1):
            ed = G[path[i]][path[i + 1]]
            segs.append(
                {
                    "from": path[i],
                    "to": path[i + 1],
                    "weight": ed["weight"],
                    "base": ed["base_weight"],
                    "penalized": ed.get("penalized", False),
                }
            )
        return {"path": path, "cost": round(cost, 1), "segments": segs, "hops": len(segs)}
    except nx.NetworkXNoPath:
        return None


# ─── FastAPI Application ────────────────────────────────────────────────────

app = FastAPI(title="CrisisGrid", version="1.0.0",
              description="Infrastructure Disaster Routing Engine")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)
tpl = Jinja2Templates(directory="templates")


# ── Pydantic models for simulation ──────────────────────────────────────────

class SimQuake(BaseModel):
    lat: float
    lon: float
    mag: float


class SimRequest(BaseModel):
    source: str = "SEA"
    target: str = "PHX"
    simulated: list[SimQuake] = []


# ── Core response builder ──────────────────────────────────────────────────

def _build_response(src: str, dst: str, extra_quakes: list[dict] | None = None):
    """Assemble the full crisis-routing response payload."""
    if src not in NODES or dst not in NODES:
        return {"error": f"Unknown node(s): {src}, {dst}"}

    # 1. Build base graph
    G = _build_graph()

    # 2. Fetch live seismic data (+ optional simulated events)
    quakes = _fetch_quakes()
    if extra_quakes:
        quakes = quakes + extra_quakes

    # 3. Spatial impact assessment
    dmg = _assess_damage(quakes)
    bad = set(dmg)

    # 4. Penalty mutation
    Gc = _penalise(G, bad)

    # 5. Dijkstra routing (normal + crisis)
    normal = _route(G, src, dst)
    crisis = _route(Gc, src, dst)

    # 6. K-shortest alternative corridors
    alts: list[dict] = []
    try:
        for i, p in enumerate(
            nx.shortest_simple_paths(Gc, src, dst, weight="weight")
        ):
            if i == 0:
                continue  # skip primary (identical to crisis route)
            if i > 3:
                break
            c = sum(Gc[p[j]][p[j + 1]]["weight"] for j in range(len(p) - 1))
            alts.append({"path": p, "cost": round(c, 1)})
    except nx.NetworkXNoPath:
        pass

    # 7. Network resilience metrics
    total = len(NODES)
    ok = total - len(bad)

    # 8. Assemble node and edge payloads
    nodes_out = []
    for nid, a in NODES.items():
        nd: dict[str, Any] = {
            "id": nid, **a,
            "status": "damaged" if nid in bad else "operational",
        }
        if nid in dmg:
            nd["hits"] = dmg[nid]
        nodes_out.append(nd)

    edges_out = []
    for u, v, d in Gc.edges(data=True):
        edges_out.append(
            {
                "from": u,
                "to": v,
                "weight": d["weight"],
                "base": d["base_weight"],
                "penalized": d.get("penalized", False),
                "coords": [
                    [NODES[u]["lat"], NODES[u]["lon"]],
                    [NODES[v]["lat"], NODES[v]["lon"]],
                ],
            }
        )

    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "source": src,
        "target": dst,
        "nodes": nodes_out,
        "edges": edges_out,
        "earthquakes": quakes,
        "damage": {k: v for k, v in dmg.items()},
        "normal_route": normal,
        "crisis_route": crisis,
        "alt_routes": alts,
        "resilience": {
            "score": round(ok / total * 100, 1),
            "total": total,
            "ok": ok,
            "damaged": len(bad),
            "damaged_ids": list(bad),
        },
    }


# ── Endpoints ───────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Serve the single-page crisis map interface."""
    return tpl.TemplateResponse(request=request, name="index.html")


@app.get("/api/crisis-routes")
async def crisis_get(
    source: str = Query("SEA", description="Source node ID"),
    target: str = Query("PHX", description="Target node ID"),
):
    """Compute crisis-aware routing with live USGS seismic data."""
    return _build_response(source, target)


@app.post("/api/crisis-routes")
async def crisis_post(body: SimRequest):
    """Compute crisis-aware routing with optional simulated earthquakes."""
    extras = [
        {
            "id": f"SIM-{i}",
            "mag": s.mag,
            "place": "Simulated epicenter",
            "time": 0,
            "lat": s.lat,
            "lon": s.lon,
            "depth": 10,
            "impact_radius": s.mag * DAMAGE_FACTOR,
        }
        for i, s in enumerate(body.simulated)
    ]
    return _build_response(body.source, body.target, extras or None)


@app.get("/api/nodes")
async def nodes_list():
    """Return all network node definitions."""
    return [{"id": k, **v} for k, v in NODES.items()]


# ── Entrypoint ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
