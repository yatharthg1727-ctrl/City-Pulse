# CityPulse — Live Civic Intelligence (Demo / Synthetic Data)
Fuses six synthetic civic feeds (weather, traffic, complaints, transit, air quality, utilities) into one `CivicEvent` model,
detects anomalies vs. per-zone baselines, flags *possible* cross-feed relationships (never causation), computes a configurable
CityPulse Composite Indicator (not an official rating), and explains it in grounded plain language (rule-based, no API key needed).

## Run
Backend: `cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload` → http://localhost:8000/docs
Frontend: `cd frontend && npm install && npm run dev` → http://localhost:5173 (proxies /api and /ws to :8000)
Tests: `cd backend && python -m pytest -q`
Demo: click **Run full civic scenario**; use **Simulate failure** on a feed card to see graceful degradation.

## Layout
`backend/app/config.py` (all thresholds/weights/zones) · `engine.py` (normalize, anomalies, correlations, score, summary) · `main.py` (REST + `/ws/citypulse` + simulation)
Env vars: see `backend/.env.example` (all optional for the demo).
