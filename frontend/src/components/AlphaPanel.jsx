import { useEffect, useMemo, useState } from 'react'

const SYMBOLS = ['RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'ICICIBANK']

function fmt(v, d = 2) {
  if (v == null || Number.isNaN(Number(v))) return '—'
  return Number(v).toFixed(d)
}

export default function AlphaPanel() {
  const [leaderboard, setLeaderboard] = useState([])
  const [selected, setSelected] = useState('RELIANCE')
  const [signals, setSignals] = useState(null)
  const [alphaOne, setAlphaOne] = useState(null)
  const [allAlpha, setAllAlpha] = useState([])

  const load = async () => {
    const [lb, all] = await Promise.all([
      (await fetch('/api/alpha/leaderboard')).json(),
      (await fetch('/api/alpha')).json(),
    ])
    setLeaderboard(Array.isArray(lb) ? lb : [])
    setAllAlpha(Array.isArray(all) ? all : [])
  }

  const loadSymbol = async (sym) => {
    const [s, a] = await Promise.all([
      (await fetch(`/api/alpha/signals/${sym}`)).json(),
      (await fetch(`/api/alpha/${sym}`)).json(),
    ])
    setSignals(s)
    setAlphaOne(a)
  }

  useEffect(() => {
    load().catch(() => {})
    loadSymbol(selected).catch(() => {})
    const id = setInterval(() => {
      load().catch(() => {})
      loadSymbol(selected).catch(() => {})
    }, 5000)
    return () => clearInterval(id)
  }, [selected])

  const weightsRows = useMemo(() => allAlpha.map((r) => ({ symbol: r.symbol, ...(r.combined?.weights_used || {}) })), [allAlpha])

  const dirColor = (d) => (d === 'LONG' ? 'var(--green)' : d === 'SHORT' ? 'var(--red)' : 'var(--text-secondary)')

  return (
    <section style={{ height: '100%', overflow: 'auto', padding: 12, display: 'grid', gap: 10 }}>
      <div style={{ fontSize: 11, letterSpacing: '0.14em', color: 'var(--blue)', marginBottom: 4 }}>ALPHA SIGNAL ENGINE</div>

      <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 10, background: 'var(--bg-card)' }}>
        <div style={{ color: 'var(--text-secondary)', marginBottom: 6 }}>Alpha Leaderboard</div>
        <table style={{ width: '100%', fontSize: 12 }}><thead><tr><th>Rank</th><th>Symbol</th><th>Direction</th><th>Alpha</th><th>Confidence</th><th>Grade</th></tr></thead><tbody>
          {leaderboard.map((r, i) => <tr key={r.symbol}><td>{i + 1}</td><td>{r.symbol}</td><td style={{ color: dirColor(r.direction) }}>{r.direction}</td><td><div style={{ display: 'flex', alignItems: 'center', gap: 8 }}><div style={{ width: 120, height: 8, background: 'var(--border)', borderRadius: 6, overflow: 'hidden' }}><div style={{ width: `${Math.max(0, Math.min(100, r.alpha_score || 50))}%`, height: '100%', background: 'var(--blue)' }} /></div><span>{fmt(r.alpha_score, 1)}</span></div></td><td>{fmt(r.confidence, 2)}</td><td>{r.liquidity_grade}</td></tr>)}
        </tbody></table>
      </div>

      <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 10, background: 'var(--bg-card)' }}>
        <div style={{ color: 'var(--text-secondary)', marginBottom: 6 }}>Signal Breakdown</div>
        <div style={{ marginBottom: 8 }}><select value={selected} onChange={(e) => setSelected(e.target.value)}>{SYMBOLS.map((s) => <option key={s}>{s}</option>)}</select></div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,minmax(0,1fr))', gap: 8 }}>
          <div style={{ border: '1px solid var(--border)', borderRadius: 6, padding: 8 }}><div>Momentum</div><div style={{ color: dirColor(signals?.momentum?.direction) }}>{signals?.momentum?.direction || '—'}</div><div>Sig: {fmt(signals?.momentum?.signal)}</div><div>1m {fmt(signals?.momentum?.mom_1min)} | 5m {fmt(signals?.momentum?.mom_5min)} | 15m {fmt(signals?.momentum?.mom_15min)}</div></div>
          <div style={{ border: '1px solid var(--border)', borderRadius: 6, padding: 8 }}><div>Mean Reversion</div><div style={{ color: dirColor(signals?.mean_reversion?.direction) }}>{signals?.mean_reversion?.direction || '—'}</div><div>Z: {fmt(signals?.mean_reversion?.z_score)}</div><div>Half-life: {fmt(signals?.mean_reversion?.half_life)}</div></div>
          <div style={{ border: '1px solid var(--border)', borderRadius: 6, padding: 8 }}><div>Order Flow</div><div style={{ color: dirColor(signals?.order_flow?.direction) }}>{signals?.order_flow?.direction || '—'}</div><div>OFI: {fmt(signals?.order_flow?.ofi, 3)}</div><div>BidP {fmt(signals?.order_flow?.bid_pressure)} | AskP {fmt(signals?.order_flow?.ask_pressure)}</div></div>
          <div style={{ border: '1px solid var(--border)', borderRadius: 6, padding: 8 }}><div>Combined</div><div style={{ color: dirColor(alphaOne?.combined?.combined_direction) }}>{alphaOne?.combined?.combined_direction || '—'}</div><div>Alpha: {fmt(alphaOne?.combined?.alpha_score, 1)}</div><div>Conf: {fmt(alphaOne?.combined?.confidence, 2)}</div></div>
        </div>
      </div>

      <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 10, background: 'var(--bg-card)' }}>
        <div style={{ color: 'var(--text-secondary)', marginBottom: 6 }}>Signal Weights</div>
        <table style={{ width: '100%', fontSize: 12 }}><thead><tr><th>Symbol</th><th>Momentum</th><th>MeanRev</th><th>OrderFlow</th></tr></thead><tbody>
          {weightsRows.map((r) => <tr key={r.symbol}><td>{r.symbol}</td><td>{fmt(r.momentum, 3)}</td><td>{fmt(r.mean_reversion, 3)}</td><td>{fmt(r.order_flow, 3)}</td></tr>)}
        </tbody></table>
      </div>
    </section>
  )
}
