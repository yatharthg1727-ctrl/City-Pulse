import asyncio, random
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from . import config as C
from .engine import Store, now

import os
app = FastAPI(title="CityPulse API (Demo / Synthetic Data)")
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
                   allow_methods=["*"], allow_headers=["*"])
store = Store(); clients: set[WebSocket] = set(); tasks: set[asyncio.Task] = set()
sim = {"running": False, "paused": False, "label": "idle"}
TRIGGERS = {"weather": ("weather", 5), "traffic": ("traffic", 3.3), "complaints": ("complaints", 3.2), "transit": ("transit", 2.2)}
ZONE_A = "Central District"

@app.exception_handler(Exception)
async def safe_errors(_, __): return JSONResponse({"error": "Internal error"}, status_code=500)

async def bcast(kind: str, data):
    for ws in list(clients):
        try: await ws.send_json({"type": kind, "data": data})
        except Exception: clients.discard(ws)

def snapshot() -> dict:
    return {"score": store.score, "status": store.status, "label": "CityPulse Composite Indicator (not an official rating)",
            "components": store.comp, "history": store.history[-60:], "feeds": store.feeds(), "anomalies": list(store.anoms.values()),
            "correlations": store.corrs, "alerts": store.alerts, "summary": store.summary(), "simulation": sim,
            "debug": store.counts, "synthetic": True}

async def process(events):
    for e in events[:5]: await bcast("event", e.model_dump(mode="json"))
    res = store.analyze()
    for k, t in (("anomalies", "anomaly"), ("correlations", "correlation"), ("alerts", "alert")):
        for x in res[k]: await bcast(t, x)
    await bcast("citypulse", {"score": store.score, "status": store.status})

def spawn(coro):
    t = asyncio.create_task(coro); tasks.add(t); t.add_done_callback(tasks.discard)

async def ambient():
    while sim["running"]:
        await asyncio.sleep(3)
        if not sim["paused"]:
            src, z = random.choice(list(C.SOURCES)), random.choice(list(C.ZONES))
            await process(store.inject(src, z, random.uniform(.85, 1.15), 1))

async def scenario(zone: str):
    await reset_all(); sim.update(running=True, paused=False)
    steps = [("T+10 Heavy rainfall begins", "weather"), ("T+20 Traffic incidents increase", "traffic"),
             ("T+30 Flooding complaints increase", "complaints"), ("T+40 Transit delays increase", "transit")]
    for label, k in steps:
        while sim["paused"]: await asyncio.sleep(.3)
        sim["label"] = label; await bcast("simulation", sim)
        src, m = TRIGGERS[k]; await process(store.inject(src, zone, m)); await asyncio.sleep(2.5)
    sim.update(label="T+90 Scenario complete: summary generated", running=False); await bcast("simulation", sim)
    await bcast("citypulse", {"score": store.score, "status": store.status})

async def reset_all():
    for t in list(tasks):
        if t is not asyncio.current_task(): t.cancel()
    store.reset(); sim.update(running=False, paused=False, label="idle")
    await bcast("simulation", sim); await bcast("citypulse", {"score": store.score, "status": store.status})

def _events(source=None, zone=None, severity=None, limit=200):
    ev = sorted((e for e in store.events if (not source or e.source == source) and (not zone or e.zone == zone)
                 and (not severity or e.severity == severity)), key=lambda e: e.timestamp, reverse=True)
    return [e.model_dump(mode="json") for e in ev[:limit]]

@app.get("/api/health")
def health(): return {"status": "ok", "time": now().isoformat(), "sources": store.health}
@app.get("/api/events")
def events(source: str | None = None, zone: str | None = None, severity: str | None = None, limit: int = Query(200, le=1000)):
    if source and source not in C.SOURCES: raise HTTPException(400, "Unknown source")
    return _events(source, zone, severity, limit)
@app.get("/api/events/{eid}")
def event(eid: str):
    for e in store.events:
        if e.id == eid: return e.model_dump(mode="json")
    raise HTTPException(404, "Event not found")
for _path, _src in [("weather", "weather"), ("traffic", "traffic"), ("complaints", "complaints"), ("transit", "transit"),
                    ("air-quality", "air_quality"), ("utilities", "utilities")]:
    app.add_api_route(f"/api/{_path}", (lambda s: lambda limit: _events(s, limit=limit))(_src), methods=["GET"])
@app.get("/api/feeds")
def feeds(): return store.feeds()
@app.get("/api/anomalies")
def anomalies(): return list(store.anoms.values())
@app.get("/api/correlations")
def correlations(): return store.corrs
@app.get("/api/alerts")
def alerts(): return store.alerts
@app.get("/api/summary")
def summary(): return store.summary()
@app.get("/api/citypulse")
def citypulse(): return snapshot()
@app.get("/api/zones")
def zones(): return [{"name": n, "latitude": la, "longitude": lo, "anomalies": sum(a["zone"] == n for a in store.anoms.values())}
                     for n, (la, lo) in C.ZONES.items()]

@app.post("/api/alerts/{aid}/{action}")
async def alert_action(aid: str, action: str):
    if action not in ("read", "dismiss"): raise HTTPException(400, "Unknown action")
    for a in store.alerts:
        if a["id"] == aid: a["status"] = "read" if action == "read" else "dismissed"; await bcast("alert", a); return a
    raise HTTPException(404, "Alert not found")

@app.post("/api/simulation/start")
async def start():
    if not sim["running"]: sim["running"] = True; spawn(ambient())
    sim.update(paused=False, label="ambient simulation running"); await bcast("simulation", sim); return sim
@app.post("/api/simulation/pause")
async def pause(): sim["paused"] = not sim["paused"]; await bcast("simulation", sim); return sim
@app.post("/api/simulation/reset")
async def reset(): await reset_all(); return sim
@app.post("/api/simulation/full-scenario")
async def full(zone: str = ZONE_A):
    if zone not in C.ZONES: raise HTTPException(400, "Unknown zone")
    spawn(scenario(zone)); return {"started": True}
@app.post("/api/simulation/trigger/{kind}")
async def trigger(kind: str, zone: str = ZONE_A):
    if kind not in TRIGGERS or zone not in C.ZONES: raise HTTPException(404, "Unknown trigger or zone")
    src, m = TRIGGERS[kind]; new = store.inject(src, zone, m); await process(new)
    return {"injected": len(new), "score": store.score, "status": store.status}
@app.post("/api/simulation/fail/{source}")
async def fail(source: str, offline: bool = True):
    if source not in store.health: raise HTTPException(404, "Unknown source")
    store.health[source]["status"] = "OFFLINE" if offline else "HEALTHY"; await bcast("citypulse", snapshot()); return store.health[source]

@app.websocket("/ws/citypulse")
async def ws(sock: WebSocket):
    await sock.accept(); clients.add(sock)
    try:
        await sock.send_json({"type": "citypulse", "data": {"score": store.score, "status": store.status}})
        while True: await sock.receive_text()
    except WebSocketDisconnect: pass
    finally: clients.discard(sock)
