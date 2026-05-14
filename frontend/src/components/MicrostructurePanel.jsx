import { useEffect, useMemo, useState } from 'react'

const SYMBOLS = ['RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'ICICIBANK']

function fmt(v, d = 2) {
  if (v == null || Number.isNaN(Number(v))) return '—'
  return Number(v).toFixed(d)
}

function Sparkline({ values }) {
  if (!values?.length) return <span style={{ color: 'var(--text-muted)' }}>—</span>
  const w = 120
  const h = 28
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const pts = values.map((v, i) => `${(i / Math.max(values.length - 1, 1)) * w},${h - ((v - min) / span) * h}`).join(' ')
  return <svg width={w} height={h}><polyline points={pts} fill="none" stroke="var(--blue)" strokeWidth="1.5" /></svg>
}

function ImpactCurve({ curve }) {
  if (!curve?.length) return null
  const w = 320
  const h = 120
  const maxX = Math.max(...curve.map((x) => x.qty_pct)) || 1
  const maxY = Math.max(...curve.map((x) => x.total_bps)) || 1
  const pts = curve.map((p) => `${(p.qty_pct / maxX) * w},${h - (p.total_bps / maxY) * h}`).join(' ')
  return <svg width={w} height={h} style={{ border: '1px solid var(--border)' }}><polyline points={pts} fill="none" stroke="var(--yellow)" strokeWidth="2" /></svg>
}

export default function MicrostructurePanel() {
  const [vwapRows, setVwapRows] = useState([])
  const [spreadRows, setSpreadRows] = useState([])
  const [liquidityRows, setLiquidityRows] = useState([])
  const [impactSymbol, setImpactSymbol] = useState('RELIANCE')
  const [impactQty, setImpactQty] = useState('50000')
  const [impact, setImpact] = useState(null)

  const load = async () => {
    const [vwapData, spreadData, liquidityData] = await Promise.all([
      Promise.all(SYMBOLS.map(async (s) => (await fetch(`/api/microstructure/vwap/${s}`)).json())),
      Promise.all(SYMBOLS.map(async (s) => (await fetch(`/api/microstructure/spread/${s}`)).json())),
      (await fetch('/api/microstructure/liquidity')).json(),
    ])
    setVwapRows(vwapData)
    setSpreadRows(spreadData)
    setLiquidityRows(Array.isArray(liquidityData) ? liquidityData : [])
  }

  useEffect(() => {
    load().catch(() => {})
    const id = setInterval(() => load().catch(() => {}), 8000)
    return () => clearInterval(id)
  }, [])

  const calcImpact = async () => {
    const r = await fetch('/api/microstructure/impact', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: impactSymbol, qty: Number(impactQty), side: 'BUY' }),
    })
    const d = await r.json()
    setImpact(d)
  }

  const liqBySymbol = useMemo(() => {
    const m = {}
    for (const r of liquidityRows) m[r.symbol] = r
    return m
  }, [liquidityRows])

  return (
    <section style={{ height: '100%', overflow: 'auto', padding: 12, display: 'grid', gap: 10 }}>
      <div style={{ fontSize: 11, letterSpacing: '0.14em', color: 'var(--green)', marginBottom: 4 }}>MICROSTRUCTURE ANALYTICS</div>

      <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 10, background: 'var(--bg-card)' }}>
        <div style={{ color: 'var(--text-secondary)', marginBottom: 6 }}>VWAP</div>
        <table style={{ width: '100%', fontSize: 12 }}><thead><tr><th>Symbol</th><th>1m</th><th>5m</th><th>15m</th><th>Deviation (bps)</th></tr></thead><tbody>
          {vwapRows.map((r) => <tr key={r.symbol}><td>{r.symbol}</td><td>{fmt(r.vwap_1min)}</td><td>{fmt(r.vwap_5min)}</td><td>{fmt(r.vwap_15min)}</td><td style={{ color: Number(r.current_deviation_bps) > 0 ? 'var(--red)' : 'var(--green)' }}>{fmt(r.current_deviation_bps)}</td></tr>)}
        </tbody></table>
      </div>

      <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 10, background: 'var(--bg-card)' }}>
        <div style={{ color: 'var(--text-secondary)', marginBottom: 6 }}>Spread</div>
        <table style={{ width: '100%', fontSize: 12 }}><thead><tr><th>Symbol</th><th>Bid</th><th>Ask</th><th>Spread bps</th><th>Avg bps</th><th>Trend</th></tr></thead><tbody>
          {spreadRows.map((r) => <tr key={r.symbol}><td>{r.symbol}</td><td>{fmt(r.bid)}</td><td>{fmt(r.ask)}</td><td>{fmt(r.spread_bps)}</td><td>{fmt(r.avg_spread_bps)}</td><td><Sparkline values={(r.history || []).slice(-30).map((x) => Number(x.relative || 0))} /></td></tr>)}
        </tbody></table>
      </div>

      <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 10, background: 'var(--bg-card)' }}>
        <div style={{ color: 'var(--text-secondary)', marginBottom: 6 }}>Liquidity Scores</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(220px,1fr))', gap: 8 }}>
          {SYMBOLS.map((s) => {
            const row = liqBySymbol[s] || { total: 0, grade: 'F', components: { spread: 0, depth: 0, otr: 0, volatility: 0 } }
            const color = row.grade === 'A' ? 'var(--green)' : row.grade === 'B' ? '#9acd32' : row.grade === 'C' ? 'var(--yellow)' : row.grade === 'D' ? '#ff8c00' : 'var(--red)'
            return <div key={s} style={{ border: '1px solid var(--border)', borderRadius: 6, padding: 8 }}><div style={{ display: 'flex', justifyContent: 'space-between' }}><strong>{s}</strong><span style={{ color }}>{row.grade} • {fmt(row.total, 1)}</span></div><div style={{ marginTop: 6, fontSize: 11, color: 'var(--text-secondary)' }}>S {fmt(row.components?.spread,0)} | D {fmt(row.components?.depth,0)} | O {fmt(row.components?.otr,0)} | V {fmt(row.components?.volatility,0)}</div></div>
          })}
        </div>
      </div>

      <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 10, background: 'var(--bg-card)' }}>
        <div style={{ color: 'var(--text-secondary)', marginBottom: 6 }}>Market Impact</div>
        <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
          <select value={impactSymbol} onChange={(e) => setImpactSymbol(e.target.value)}>{SYMBOLS.map((s) => <option key={s}>{s}</option>)}</select>
          <input value={impactQty} onChange={(e) => setImpactQty(e.target.value)} type="number" />
          <button onClick={calcImpact}>Calculate</button>
        </div>
        {impact && <div style={{ display: 'grid', gap: 8 }}><div style={{ fontSize: 12 }}>Temporary {fmt(impact.temporary_bps)} bps | Permanent {fmt(impact.permanent_bps)} bps | Total {fmt(impact.total_bps)} bps | Cost ₹{fmt(impact.cost_rupees, 0)}</div><ImpactCurve curve={impact.impact_curve} /></div>}
      </div>
    </section>
  )
}
