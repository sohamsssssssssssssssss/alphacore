import { useMemo, useState } from 'react'

const SYMBOLS = ['RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'ICICIBANK']

function num(v, d = 3) {
  return Number(v || 0).toFixed(d)
}

function pct(v) {
  return `${(Number(v || 0) * 100).toFixed(1)}%`
}

function FeatureBars({ importance = {} }) {
  const items = Object.entries(importance).sort((a, b) => b[1] - a[1]).slice(0, 10)
  if (!items.length) return <div style={{ color: 'var(--text-muted)' }}>No feature importance available</div>
  const max = Math.max(...items.map((x) => x[1]), 1e-9)
  return (
    <svg width='100%' viewBox={`0 0 720 ${items.length * 24}`}>
      {items.map(([k, v], i) => {
        const y = i * 24
        const w = (v / max) * 420
        return (
          <g key={k} transform={`translate(0,${y})`}>
            <text x='0' y='15' fill='var(--text-secondary)' fontSize='11'>{k}</text>
            <rect x='260' y='6' width={w} height='10' fill='var(--blue)' />
            <text x='690' y='15' fill='var(--text-primary)' fontSize='11' textAnchor='end'>{num(v, 4)}</text>
          </g>
        )
      })}
    </svg>
  )
}

function FoldBars({ folds = [] }) {
  if (!folds.length) return <div style={{ color: 'var(--text-muted)' }}>Run backtest to view fold accuracies</div>
  const w = 560
  const h = 120
  const barW = w / folds.length
  return (
    <svg width='100%' viewBox={`0 0 ${w} ${h}`}>
      {folds.map((f, i) => {
        const bh = Math.max(2, f * (h - 20))
        return <rect key={i} x={i * barW + 3} y={h - bh} width={barW - 6} height={bh} fill='var(--green)' />
      })}
    </svg>
  )
}

export default function MLPanel() {
  const [tab, setTab] = useState('signals')
  const [symbol, setSymbol] = useState('RELIANCE')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const [single, setSingle] = useState(null)
  const [allSignals, setAllSignals] = useState([])
  const [metrics, setMetrics] = useState(null)
  const [backtest, setBacktest] = useState(null)

  const getSignal = async () => {
    setLoading(true)
    setError('')
    try {
      const res = await fetch(`/api/ml/signal/${symbol}`)
      if (!res.ok) throw new Error(`Signal request failed (${res.status})`)
      setSingle(await res.json())
    } catch (e) {
      setError(e.message || 'Signal fetch failed')
    } finally {
      setLoading(false)
    }
  }

  const getAll = async () => {
    setLoading(true)
    setError('')
    try {
      const res = await fetch('/api/ml/signal')
      if (!res.ok) throw new Error(`Signal list failed (${res.status})`)
      setAllSignals(await res.json())
    } catch (e) {
      setError(e.message || 'Signal list fetch failed')
    } finally {
      setLoading(false)
    }
  }

  const retrain = async () => {
    setLoading(true)
    setError('')
    try {
      const res = await fetch(`/api/ml/retrain/${symbol}`, { method: 'POST' })
      if (!res.ok) throw new Error(`Retrain failed (${res.status})`)
      setMetrics(await res.json())
      setTab('model')
    } catch (e) {
      setError(e.message || 'Retrain failed')
    } finally {
      setLoading(false)
    }
  }

  const loadMetrics = async () => {
    setLoading(true)
    setError('')
    try {
      const res = await fetch(`/api/ml/metrics/${symbol}`)
      if (!res.ok) throw new Error(`Metrics failed (${res.status})`)
      setMetrics(await res.json())
      setTab('model')
    } catch (e) {
      setError(e.message || 'Metrics fetch failed')
    } finally {
      setLoading(false)
    }
  }

  const runBacktest = async () => {
    setLoading(true)
    setError('')
    try {
      const res = await fetch(`/api/ml/backtest/${symbol}`)
      if (!res.ok) throw new Error(`Backtest failed (${res.status})`)
      setBacktest(await res.json())
      setTab('model')
    } catch (e) {
      setError(e.message || 'Backtest failed')
    } finally {
      setLoading(false)
    }
  }

  const cards = useMemo(() => {
    if (allSignals?.length) return allSignals
    return single ? [single] : []
  }, [single, allSignals])

  return (
    <section style={{ height: '100%', overflow: 'auto', padding: 12, display: 'grid', gap: 10 }}>
      <div style={{ fontSize: 11, letterSpacing: '0.14em', color: 'var(--green)', marginBottom: 4 }}>ML SIGNAL ENGINE</div>

      <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 10, background: 'var(--bg-card)' }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
          <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>{SYMBOLS.map((s) => <option key={s}>{s}</option>)}</select>
          <button onClick={getSignal} disabled={loading}>Get Signal</button>
          <button onClick={getAll} disabled={loading}>Get All</button>
          <button onClick={retrain} disabled={loading}>{loading ? 'Retraining...' : 'Retrain'}</button>
          <button onClick={loadMetrics} disabled={loading}>Model Metrics</button>
          <button onClick={runBacktest} disabled={loading}>Run Backtest</button>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
            <button onClick={() => setTab('signals')}>Signals</button>
            <button onClick={() => setTab('model')}>Model Info</button>
          </div>
        </div>
        {error && <div style={{ color: 'var(--red)' }}>{error}</div>}
      </div>

      {tab === 'signals' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5,minmax(0,1fr))', gap: 8 }}>
          {cards.map((s) => (
            <div key={s.symbol} style={{ border: '1px solid var(--border)', borderRadius: 8, background: 'var(--bg-card)', padding: 8 }}>
              <div style={{ color: 'var(--text-secondary)' }}>{s.symbol}</div>
              <div style={{ color: s.direction === 'UP' ? 'var(--green)' : 'var(--red)', fontWeight: 700 }}>{s.direction}</div>
              <div style={{ marginTop: 6 }}>
                <div style={{ height: 8, background: 'var(--border)', borderRadius: 6, overflow: 'hidden' }}>
                  <div style={{ width: `${Math.max(0, Math.min(100, (s.confidence || 0) * 100))}%`, height: '100%', background: 'var(--blue)' }} />
                </div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>Confidence: {pct(s.confidence)}</div>
              </div>
              <div style={{ marginTop: 6, fontSize: 11 }}>
                <div>UP: {pct(s.probability_up)}</div>
                <div>DOWN: {pct(s.probability_down)}</div>
              </div>
            </div>
          ))}
          {!cards.length && <div style={{ color: 'var(--text-muted)' }}>No signals yet.</div>}
        </div>
      )}

      {tab === 'model' && (
        <div style={{ display: 'grid', gap: 8 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,minmax(0,1fr))', gap: 8 }}>
            <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 8, background: 'var(--bg-card)' }}>Accuracy: <b>{pct(metrics?.accuracy)}</b></div>
            <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 8, background: 'var(--bg-card)' }}>F1: <b>{num(metrics?.f1)}</b></div>
            <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 8, background: 'var(--bg-card)' }}>Train: <b>{metrics?.n_train ?? 0}</b></div>
            <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 8, background: 'var(--bg-card)' }}>Test: <b>{metrics?.n_test ?? 0}</b></div>
          </div>

          <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 8, background: 'var(--bg-card)' }}>
            <div style={{ color: 'var(--text-secondary)', marginBottom: 4 }}>Top Feature Importance</div>
            <FeatureBars importance={metrics?.feature_importance || {}} />
          </div>

          <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 8, background: 'var(--bg-card)' }}>
            <div style={{ color: 'var(--text-secondary)', marginBottom: 4 }}>Walk-forward Accuracy</div>
            <FoldBars folds={backtest?.fold_accuracies || []} />
            {backtest && (
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                Mean: {pct(backtest.mean_accuracy)} | Beats random: {String(backtest.beats_random)}
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  )
}
