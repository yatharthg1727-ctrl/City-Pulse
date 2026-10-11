import pytest
from app.engine import Store, normalize
Z = "Central District"

def test_seed_normal():
    s = Store(); assert len(s.events) >= 560 and s.status == "NORMAL" and s.score <= 25

def test_normalize_rejects_bad_records():
    ok = {"id": 1, "timestamp": "2026-01-01T00:00:00Z", "latitude": 26.9, "longitude": 75.8, "zone": Z, "incident_count": 3}
    assert normalize("traffic", ok) is not None
    assert normalize("traffic", {**ok, "timestamp": "bad"}) is None
    assert normalize("traffic", {**ok, "latitude": 999}) is None
    assert normalize("traffic", {k: v for k, v in ok.items() if k != "incident_count"}) is None

def test_scenario_detects_anomaly_correlation_and_score():
    s = Store()
    for src, m in [("weather", 5), ("traffic", 3.3), ("complaints", 3.2), ("transit", 2.2)]: s.inject(src, Z, m)
    s.analyze()
    assert s.anoms and s.corrs and s.corrs[0]["zone"] == Z and s.score > 50
    assert s.corrs[0]["disclaimer"] and "caused" not in s.summary()["text"]
    s.reset(); assert s.status == "NORMAL" and not s.corrs

def test_failed_feed_survives():
    s = Store(); s.health["traffic"]["status"] = "OFFLINE"
    assert s.inject("traffic", Z, 3) == [] and s.health["traffic"]["errors"] > 0 and s.feeds()

def test_api_and_simulation():
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    assert c.get("/api/health").status_code == 200 and len(c.get("/api/weather?limit=10").json()) == 10
    with c.websocket_connect("/ws/citypulse") as w:
        assert w.receive_json()["type"] == "citypulse"
        assert c.post("/api/simulation/trigger/weather").status_code == 200
    assert c.post("/api/simulation/trigger/bogus").status_code == 404
    assert c.post("/api/simulation/reset").status_code == 200 and c.get("/api/citypulse").json()["status"] == "NORMAL"
