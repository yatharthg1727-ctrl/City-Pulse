import { useCallback, useEffect, useRef, useState } from 'react'
import { MapContainer, TileLayer, Circle, CircleMarker, Popup, useMap } from 'react-leaflet'

type J = Record<string, any>
const api = (p: string, m = 'GET') => fetch(p, { method: m }).then(r => { if (!r.ok) throw new Error(String(r.status)); return r.json() })
const ICON: Record<string, string> = { NORMAL: '●', HEALTHY: '●', LOW: '▲', MEDIUM: '▲', WATCH: '▲', WARNING: '▲', INFO: 'ℹ', HIGH: '◆', ELEVATED: '◆', CRITICAL: '■', OFFLINE: '○' }
const Tag = ({ v }: { v: string }) => <span className={`tag ${v}`}>{ICON[v] ?? ''} {v}</span>
const COLORS: Record<string, string> = { weather: '#1f4fbf', traffic: '#e67e22', complaints: '#8e44ad', transit: '#16a085', air_quality: '#7f8c8d', utilities: '#c0392b' }
const time = (t?: string) => (t ? new Date(t).toLocaleTimeString() : '—')

function Fly({ to }: { to: [number, number] | null }) { const m = useMap(); useEffect(() => { if (to) m.flyTo(to, 14) }, [to]); return null }

export default function App() {
  const [snap, setSnap] = useState<J | null>(null)
  const [events, setEvents] = useState<J[]>([])
  const [err, setErr] = useState('')
  const [live, setLive] = useState(false)
  const [filter, setFilter] = useState('all')
  const [focus, setFocus] = useState<[number, number] | null>(null)
  const timer = useRef<any>(null)

  const load = useCallback(() => Promise.all([api('/api/citypulse'), api('/api/events?limit=200')])
    .then(([s, e]) => { setSnap(s); setEvents(e); setErr('') }).catch(() => setErr('Backend unavailable. Showing last known data.')), [])
  const debounced = useCallback(() => { clearTimeout(timer.current); timer.current = setTimeout(load, 300) }, [load])

  useEffect(() => {
    load(); let ws: WebSocket, retry: any, dead = false
    const connect = () => {
      ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/citypulse`)
      ws.onopen = () => setLive(true); ws.onmessage = debounced
      ws.onclose = () => { setLive(false); if (!dead) retry = setTimeout(connect, 2000) }
    }
    connect(); return () => { dead = true; clearTimeout(retry); ws?.close() }
  }, [])

  const act = (p: string) => api(p, 'POST').then(load).catch(() => setErr('Action failed.'))
  if (!snap) return <p style={{ padding: 20 }}>{err || 'Loading CityPulse…'}</p>
  const shown = events.filter(e => filter === 'all' || e.source === filter).slice(0, 150)
  const sim = snap.simulation

  return (<>
    <header>
      <div><h1>CITYPULSE <span className="muted">Live Civic Intelligence</span></h1>
        <span className="muted">Demo / Synthetic Data</span></div>
      <div className="row" role="status"><span className={live ? 'HEALTHY' : 'OFFLINE'}>{live ? '● LIVE' : '○ OFFLINE'}</span>
        <span className="muted">{sim.label}</span></div>
    </header>
    {err && <p role="alert" style={{ margin: 16, color: '#c62828' }}>{err}</p>}
    <main>
      <div style={{ display: 'grid', gap: 16 }}>
        <section aria-label="City status"><h2>City status</h2>
          <div className="row" style={{ alignItems: 'baseline' }}><span className={`big ${snap.status}`}>{snap.status}</span>
            <span className="big">{snap.score} / 100</span></div>
          <div className="muted">CityPulse Composite Indicator — not an official government rating.</div></section>
        <section aria-label="Demo controls"><h2>Demo control center</h2><div className="row">
          <button className="p" onClick={() => act('/api/simulation/full-scenario')}>Run full civic scenario</button>
          <button onClick={() => act('/api/simulation/start')}>Start simulation</button>
          <button onClick={() => act('/api/simulation/pause')}>{sim.paused ? 'Resume' : 'Pause'}</button>
          <button onClick={() => act('/api/simulation/reset')}>Reset</button>
          {['weather', 'traffic', 'complaints', 'transit'].map(k => <button key={k} onClick={() => act(`/api/simulation/trigger/${k}`)}>Trigger {k}</button>)}
        </div></section>
        <section aria-label="Live map"><h2>Live city map</h2>
          <label className="row">Filter: <select value={filter} onChange={e => setFilter(e.target.value)}>
            <option value="all">All</option>{Object.keys(COLORS).map(k => <option key={k}>{k}</option>)}</select></label>
          <div className="map"><MapContainer center={[26.9124, 75.7873]} zoom={12} style={{ height: '100%' }}>
            <TileLayer attribution="© OpenStreetMap contributors" url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" />
            <Fly to={focus} />
            {snap.anomalies.map((a: J) => <Circle key={a.id} center={[a.latitude, a.longitude]} radius={1800} pathOptions={{ color: '#c62828' }} />)}
            {shown.map(e => <CircleMarker key={e.id} center={[e.latitude, e.longitude]} radius={5} pathOptions={{ color: COLORS[e.source] }}>
              <Popup><b>{e.event_type}</b><br />{e.source} · {e.zone}<br />{time(e.timestamp)} · {e.severity}<br />value {e.value}</Popup></CircleMarker>)}
          </MapContainer></div>
          <p className="muted">{shown.length} events shown. Red circles are detected anomalies.</p></section>
        <section aria-label="Feeds"><h2>Feeds</h2><div className="grid">
          {snap.feeds.map((f: J) => <div className="card" key={f.source}><b>{f.source.toUpperCase()}</b> <Tag v={f.severity} />
            <div className="big" style={{ fontSize: 22 }}>{f.current ?? '—'}</div>
            <div className="muted">baseline {f.baseline} · {f.pct_change == null ? '—' : `${f.pct_change > 0 ? '+' : ''}${f.pct_change}%`}</div>
            <div className="muted">{time(f.updated)} · <span className={f.health.status}>{f.health.status}</span></div>
            <button onClick={() => act(`/api/simulation/fail/${f.source}?offline=${f.health.status !== 'OFFLINE'}`)}>
              {f.health.status === 'OFFLINE' ? 'Restore feed' : 'Simulate failure'}</button></div>)}
        </div></section>
      </div>
      <div style={{ display: 'grid', gap: 16, alignContent: 'start' }}>
        <section aria-label="What's happening"><h2>What's happening?</h2><p>{snap.summary.text}</p>
          {snap.summary.observations.length > 0 && <p className="muted"><b>Observations:</b> {snap.summary.observations.join('; ')}</p>}
          {snap.summary.inference && <p className="muted"><b>Inference (not confirmed):</b> {snap.summary.inference}</p>}
          <p className="muted">{snap.summary.disclaimer}</p></section>
        <section aria-label="Anomalies"><h2>Anomalies</h2>
          {snap.anomalies.length === 0 && <p className="muted">No anomalies detected in the current window.</p>}
          {snap.anomalies.map((a: J) => <div className="card" key={a.id}><Tag v={a.severity} /> <b>{a.zone}</b> — {a.source} {a.pct_change > 0 ? '+' : ''}{a.pct_change}% vs baseline
            <ul className="muted">{a.evidence.map((x: string) => <li key={x}>{x}</li>)}</ul>
            <span className="muted">Detected {time(a.detected_at)}</span> <button onClick={() => setFocus([a.latitude, a.longitude])}>View on map</button></div>)}</section>
        <section aria-label="Possible relationships"><h2>Possible relationships</h2>
          {snap.correlations.length === 0 && <p className="muted">No cross-feed relationships detected.</p>}
          {snap.correlations.map((c: J) => <div className="card" key={c.id}><b>{c.zone}</b>: {c.sources.join(' + ')}<br />
            Confidence {Math.round(c.confidence * 100)}% · window {c.time_window_min} min · {c.geographic_overlap} · {c.independent_signals} signals
            <ul className="muted">{c.evidence.map((x: string) => <li key={x}>{x}</li>)}</ul>
            <div className="muted">{c.disclaimer}</div> <button onClick={() => setFocus([c.latitude, c.longitude])}>View on map</button></div>)}</section>
        <section aria-label="Alerts"><h2>Alerts</h2>
          {snap.alerts.filter((a: J) => a.status !== 'dismissed').length === 0 && <p className="muted">No active alerts.</p>}
          {snap.alerts.filter((a: J) => a.status !== 'dismissed').map((a: J) => <div className="card" key={a.id} style={{ opacity: a.status === 'read' ? .65 : 1 }}>
            <Tag v={a.severity} /> <b>{a.title}</b><div className="muted">{a.zone} · {time(a.timestamp)} · {a.status}</div><p>{a.description}</p>
            <div className="row"><button onClick={() => act(`/api/alerts/${a.id}/read`)}>Mark read</button>
              <button onClick={() => act(`/api/alerts/${a.id}/dismiss`)}>Dismiss</button></div></div>)}</section>
        <section aria-label="Debug"><h2>Debug</h2><p className="muted">events {snap.debug.events} · anomalies {snap.debug.anomalies} · correlations {snap.debug.correlations} · alerts {snap.debug.alerts} · WebSocket {live ? 'connected' : 'disconnected'}</p></section>
      </div>
    </main></>)
}
