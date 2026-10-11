"""Ingestion -> validation -> normalization -> CivicEvent -> anomaly + correlation -> score -> summary."""
import random, uuid
from datetime import datetime, timedelta, timezone
from statistics import mean, pstdev
from typing import Any
from pydantic import BaseModel
from . import config as C

RANK = {"NORMAL": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
ALERT_SEV = {"LOW": "INFO", "MEDIUM": "WARNING", "HIGH": "HIGH", "CRITICAL": "CRITICAL"}
PHRASE = {"weather": "rainfall", "traffic": "traffic incidents", "complaints": "citizen reports",
          "transit": "transit delays", "air_quality": "air quality index", "utilities": "outage-affected customers"}
DISCLAIMER = "Correlation does not establish causation."

def now() -> datetime: return datetime.now(timezone.utc)
def sev_for(pct: float) -> str: return next((n for n, t in C.THRESHOLDS if pct >= t), "NORMAL")

class CivicEvent(BaseModel):
    id: str; source: str; event_type: str; timestamp: datetime
    latitude: float; longitude: float; zone: str; severity: str
    value: float; status: str = "active"; metadata: dict[str, Any] = {}

def make_raw(source: str, zone: str, ts: datetime, value: float) -> dict:
    lat, lon = C.ZONES[zone]; u = random.uniform
    r = {"id": uuid.uuid4().hex[:10], "timestamp": ts.isoformat(), "latitude": lat + u(-.01, .01),
         "longitude": lon + u(-.01, .01), "zone": zone, C.SOURCES[source][1]: value}
    if source == "complaints":  # anonymous, category-level only
        r["category"] = "flooding" if value > 16 else random.choice(["garbage", "road_damage", "streetlight"])
    return r

def normalize(source: str, raw: dict, base: float | None = None) -> CivicEvent | None:
    """Validate + map a raw feed record to CivicEvent. Returns None for invalid records."""
    try:
        et, field, mu = C.SOURCES[source]
        lat, lon = float(raw["latitude"]), float(raw["longitude"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180): return None
        ts = datetime.fromisoformat(str(raw["timestamp"]).replace("Z", "+00:00"))
        if ts.tzinfo is None: ts = ts.replace(tzinfo=timezone.utc)
        if raw.get(field) is None or raw["zone"] not in C.ZONES: return None
        v = float(raw[field]); b = base or mu
        skip = {"id", "timestamp", "latitude", "longitude", "zone", field, "category"}
        return CivicEvent(id=str(raw["id"]), source=source, event_type=raw.get("category", et), timestamp=ts,
                          latitude=lat, longitude=lon, zone=raw["zone"], severity=sev_for((v - b) / b * 100),
                          value=round(v, 2), metadata={k: x for k, x in raw.items() if k not in skip})
    except (KeyError, ValueError, TypeError):
        return None

class Store:
    def __init__(self): self.reset()

    def reset(self):
        self.events: list[CivicEvent] = []; self.base = {}; self.sd = {}; self.anoms = {}; self.corrs = []
        self.alerts = []; self.first = {}; self.alerted = set(); self.score = 0; self.status = "NORMAL"
        self.comp = {}; self.history = []
        self.counts = {"events": 0, "anomalies": 0, "correlations": 0, "alerts": 0}
        self.health = {k: {"status": "HEALTHY", "records": 0, "errors": 0, "last_update": None} for k in C.SOURCES}
        self._seed(); self.analyze()

    def _seed(self):
        t = now(); zs = list(C.ZONES)
        for src, (_, _, mu) in C.SOURCES.items():
            raws = [make_raw(src, zs[i % len(zs)], t - timedelta(minutes=random.uniform(C.WINDOW_MIN + 5, 1440)),
                             round(mu * random.uniform(.6, 1.4), 2)) for i in range(C.COUNTS[src])]
            for z in zs:
                vals = [r[C.SOURCES[src][1]] for r in raws if r["zone"] == z]
                self.base[(src, z)] = mean(vals); self.sd[(src, z)] = pstdev(vals)
            self.ingest(src, raws)
            self.ingest(src, [make_raw(src, z, t - timedelta(minutes=random.uniform(1, 10)),
                                       round(self.base[(src, z)] * random.uniform(.85, 1.15), 2)) for z in zs])

    def ingest(self, src: str, raws: list) -> list[CivicEvent]:
        h = self.health[src]
        if h["status"] == "OFFLINE": h["errors"] += len(raws); return []  # failed feed: skip, keep serving cached data
        out = []
        for r in raws:
            e = normalize(src, r, self.base.get((src, r.get("zone")))) if isinstance(r, dict) else None
            if e: out.append(e)
            else: h["errors"] += 1
        self.events += out; h["records"] += len(out); self.counts["events"] += len(out)
        if out: h["last_update"] = now().isoformat()
        return out

    def inject(self, src: str, zone: str, mult: float, n: int = 4) -> list[CivicEvent]:
        b, t = self.base[(src, zone)], now()
        return self.ingest(src, [make_raw(src, zone, t - timedelta(seconds=i), round(b * mult * random.uniform(.9, 1.1), 2))
                                 for i in range(n)])

    def _alert(self, new, key, sev, zone, title, desc, related):
        if key in self.alerted: return
        self.alerted.add(key)
        a = {"id": uuid.uuid4().hex[:8], "timestamp": now().isoformat(), "zone": zone, "severity": sev, "title": title,
             "description": desc, "related_events": related, "status": "active"}
        self.alerts.insert(0, a); new["alerts"].append(a); self.counts["alerts"] += 1

    def analyze(self) -> dict:
        cut = now() - timedelta(minutes=C.WINDOW_MIN); cur = {}
        for e in self.events:
            if e.timestamp >= cut: cur.setdefault((e.source, e.zone), []).append(e)
        new = {"anomalies": [], "correlations": [], "alerts": []}
        comp = {k: 0.0 for k in C.SOURCES}; found = {}; latest = {}
        for (src, z), evs in cur.items():
            b = self.base[(src, z)]; c = mean(e.value for e in evs); p = (c - b) / b * 100
            comp[src] = max(comp[src], p); sv = sev_for(p)
            if sv == "NORMAL": continue
            aid = f"{src}:{z}"; latest[aid] = max(e.timestamp for e in evs)
            det = self.first.setdefault(aid, now().isoformat())
            a = {"id": aid, "source": src, "zone": z, "severity": sv, "current": round(c, 2), "baseline": round(b, 2),
                 "pct_change": round(p, 1), "deviation": round((c - b) / max(self.sd[(src, z)], 1e-6), 1),
                 "latitude": C.ZONES[z][0], "longitude": C.ZONES[z][1], "detected_at": det,
                 "evidence": [f"{len(evs)} {src} records in the last {C.WINDOW_MIN} min",
                              f"current {c:.1f} vs baseline {b:.1f} ({p:+.0f}%)"]}
            found[aid] = a
            if aid not in self.anoms: new["anomalies"].append(a); self.counts["anomalies"] += 1
            if RANK[sv] >= 2:
                self._alert(new, (aid, sv), ALERT_SEV[sv], z, f"{PHRASE[src].capitalize()} abnormal in {z}",
                            f"{PHRASE[src].capitalize()} are {p:+.0f}% relative to baseline (observation, not a confirmed cause).", [aid])
        self.anoms = found
        by = {}
        for a in found.values(): by.setdefault(a["zone"], []).append(a)
        old = {c["id"]: len(c["sources"]) for c in self.corrs}; corrs = []
        for z, lst in by.items():
            if len(lst) < 2: continue
            lst.sort(key=lambda a: list(C.SOURCES).index(a["source"]))
            ts = [latest[a["id"]] for a in lst]; spread = (max(ts) - min(ts)).total_seconds() / 60
            conf = round(min(.95, .4 + .12 * len(lst) + .1 * max(0, 1 - spread / C.WINDOW_MIN)), 2)
            cid = f"corr:{z}"; names = [PHRASE[a["source"]] for a in lst]
            c = {"id": cid, "zone": z, "sources": [a["source"] for a in lst], "latitude": C.ZONES[z][0],
                 "longitude": C.ZONES[z][1], "confidence": conf, "time_window_min": C.WINDOW_MIN,
                 "spread_min": round(spread, 1), "geographic_overlap": "Same zone", "related_events": [a["id"] for a in lst],
                 "evidence": [f"{PHRASE[a['source']]}: {a['pct_change']:+.0f}% vs baseline ({a['current']} vs {a['baseline']})" for a in lst],
                 "independent_signals": len(lst), "detected_at": self.first.setdefault(cid, now().isoformat()),
                 "explanation": f"Possible relationship detected in {z}: {', '.join(names)} are all abnormal in the same zone and time window.",
                 "disclaimer": DISCLAIMER}
            corrs.append(c)
            if old.get(cid) != len(lst):
                new["correlations"].append(c); self.counts["correlations"] += 1
                self._alert(new, (cid, len(lst)), "HIGH" if len(lst) >= 3 else "WARNING", z, f"Possible relationship in {z}",
                            c["explanation"] + " " + DISCLAIMER, c["related_events"])
        self.corrs = corrs
        self.score = round(sum(C.WEIGHTS[k] * min(100, max(0, v) / C.SCORE_FULL_PCT * 100) for k, v in comp.items()))
        self.status = next(n for lim, n in C.BANDS if self.score <= lim); self.comp = comp
        if RANK.get(self.status, 0) >= 0 and self.status in ("ELEVATED", "CRITICAL"):
            self._alert(new, ("status", self.status), "HIGH" if self.status == "ELEVATED" else "CRITICAL", "City-wide",
                        f"CityPulse status {self.status}", f"CityPulse Composite Indicator reached {self.score}/100.", [])
        self.history = (self.history + [{"t": now().isoformat(), "score": self.score}])[-200:]
        return new

    def feeds(self) -> list[dict]:
        cut = now() - timedelta(minutes=C.WINDOW_MIN); out = []
        for src, (_, field, _) in C.SOURCES.items():
            evs = sorted((e for e in self.events if e.source == src), key=lambda e: e.timestamp)
            w = [e.value for e in evs if e.timestamp >= cut]; cur = mean(w) if w else None
            b = mean(v for (k, _), v in self.base.items() if k == src)
            p = None if cur is None else round((cur - b) / b * 100, 1)
            worst = max((a["severity"] for a in self.anoms.values() if a["source"] == src), key=RANK.get, default="NORMAL")
            out.append({"source": src, "unit": field, "current": None if cur is None else round(cur, 2), "baseline": round(b, 2),
                        "pct_change": p, "severity": worst, "updated": evs[-1].timestamp.isoformat() if evs else None,
                        "spark": [e.value for e in evs[-12:]], "health": self.health[src]})
        return out

    def summary(self) -> dict:
        facts = [f"{PHRASE[a['source']]} in {a['zone']}: {a['current']} (baseline {a['baseline']})" for a in self.anoms.values()]
        if self.corrs:
            c = max(self.corrs, key=lambda c: c["confidence"])
            parts = [f"{PHRASE[a['source']]} ({a['pct_change']:+.0f}%)" for a in self.anoms.values() if a["zone"] == c["zone"]]
            text = (f"Unusual activity is being observed in {c['zone']}: {', '.join(parts)} are above their usual levels at the "
                    f"same time. These signals overlap in the same area and time period, so a possible relationship is flagged.")
            inference = c["explanation"]
        elif self.anoms:
            a = max(self.anoms.values(), key=lambda a: a["pct_change"])
            text = f"{PHRASE[a['source']].capitalize()} in {a['zone']} are {a['pct_change']:+.0f}% relative to baseline. No other feed is abnormal there yet."
            inference = None
        else:
            text = "No unusual activity detected. All monitored feeds are within normal ranges."; inference = None
        return {"text": text, "facts": facts, "observations": [f"{k}: {v:+.0f}% vs baseline" for k, v in self.comp.items() if v >= 50],
                "inference": inference, "disclaimer": DISCLAIMER, "provider": "rule-based"}
