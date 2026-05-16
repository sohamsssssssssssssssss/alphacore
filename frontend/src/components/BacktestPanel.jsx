import { useMemo, useState } from 'react'

const SYMBOLS = ['RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'ICICIBANK']
const STRATEGIES = ['momentum', 'mean_reversion', 'ofi', 'combined']

function inr(v) {
  const n = Number(v || 0)
  return `Rs. ${n.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
}

function pct(v, d = 2) {
  return `${(Number(v || 0) * 100).toFixed(d)}%`
}

function num(v, d = 3) {
  return Number(v || 0).toFixed(d)
}

function Spinner() {
  return <span className='inline-block w-4 h-4 border-2 border-slate-400 border-t-transparent rounded-full animate-spin' />
}

function EquitySvg({ curve, initial }) {
  const width = 900
  const height = 200
  if (!curve || curve.length < 2) return <div className='text-slate-400'>Run a backtest to see equity curve.</div>

  const minV = Math.min(...curve)
  const maxV = Math.max(...curve)
  const pad = Math.max((maxV - minV) * 0.05, 1)
  const yMin = minV - pad
  const yMax = maxV + pad

  const x = (i) => (i / (curve.length - 1)) * width
  const y = (v) => height - ((v - yMin) / (yMax - yMin)) * height

  const pts = curve.map((v, i) => `${x(i)},${y(v)}`).join(' ')
  const baseY = y(initial)

  return (
    <svg width='100%' viewBox={`0 0 ${width} ${height}`}>
      <line x1='0' y1={baseY} x2={width} y2={baseY} stroke='#4b5563' strokeDasharray='6 4' />
      <polyline points={pts} fill='none' stroke='#00ff88' strokeWidth='2' />
    </svg>
  )
}

function PnlSvg({ series }) {
  const data = (series || []).slice(-50)
  const width = 900
  const height = 120
  if (!data.length) return <div className='text-slate-400'>No closed trades yet.</div>

  const maxAbs = Math.max(1, ...data.map((v) => Math.abs(v)))
  const mid = height / 2
  const barW = width / data.length

  return (
    <svg width='100%' viewBox={`0 0 ${width} ${height}`}>
      <line x1='0' y1={mid} x2={width} y2={mid} stroke='#334155' />
      {data.map((v, i) => {
        const h = (Math.abs(v) / maxAbs) * (height / 2 - 4)
        const y = v >= 0 ? mid - h : mid
        return (
          <rect
            key={i}
            x={i * barW + 1}
            y={y}
            width={Math.max(1, barW - 2)}
            height={h}
            fill={v >= 0 ? '#00ff88' : '#ff4d4d'}
          />
        )
      })}
    </svg>
  )
}

function CompareBars({ rows }) {
  if (!rows?.length) return <div className='text-slate-400'>Run Compare All to see ranking.</div>
  const sorted = [...rows].sort((a, b) => b.sharpe - a.sharpe)
  const maxAbs = Math.max(1, ...sorted.map((r) => Math.abs(r.sharpe)))
  return (
    <div className='space-y-2'>
      {sorted.map((r) => {
        const pctW = (Math.abs(r.sharpe) / maxAbs) * 100
        return (
          <div key={r.strategy} className='grid grid-cols-[180px_1fr_100px] gap-3 items-center'>
            <div className='uppercase text-slate-200'>{r.strategy}</div>
            <div className='h-3 bg-slate-800 border border-slate-700'>
              <div className='h-full bg-cyan-400' style={{ width: `${pctW}%` }} />
            </div>
            <div className='text-right font-mono'>{num(r.sharpe)}</div>
          </div>
        )
      })}
    </div>
  )
}

export default function BacktestPanel() {
  const [tab, setTab] = useState('results')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const [cfg, setCfg] = useState({
    symbol: 'RELIANCE',
    strategy: 'combined',
    n_snapshots: 500,
    hold_periods: 10,
    stop_loss_pct: 0.5,
    position_size_pct: 10,
  })

  const [result, setResult] = useState(null)
  const [compare, setCompare] = useState(null)

  const [sortBy, setSortBy] = useState('entry_period')
  const [sortDir, setSortDir] = useState('asc')

  const runBacktest = async () => {
    setLoading(true)
    setError('')
    try {
      const payload = {
        symbol: cfg.symbol,
        strategy: cfg.strategy,
        n_snapshots: Number(cfg.n_snapshots),
        hold_periods: Number(cfg.hold_periods),
        stop_loss_pct: Number(cfg.stop_loss_pct) / 100,
        position_size_pct: Number(cfg.position_size_pct) / 100,
      }
      const res = await fetch('/api/backtest/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!res.ok) throw new Error(`Backtest failed (${res.status})`)
      setResult(await res.json())
      setTab('results')
    } catch (e) {
      setError(e.message || 'Backtest failed')
    } finally {
      setLoading(false)
    }
  }

  const compareAll = async () => {
    setLoading(true)
    setError('')
    try {
      const payload = {
        symbol: cfg.symbol,
        n_snapshots: Number(cfg.n_snapshots),
        hold_periods: Number(cfg.hold_periods),
        stop_loss_pct: Number(cfg.stop_loss_pct) / 100,
        position_size_pct: Number(cfg.position_size_pct) / 100,
      }
      const res = await fetch('/api/backtest/compare', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!res.ok) throw new Error(`Compare failed (${res.status})`)
      setCompare(await res.json())
      setTab('compare')
    } catch (e) {
      setError(e.message || 'Compare failed')
    } finally {
      setLoading(false)
    }
  }

  const metrics = result?.metrics || null
  const trades = result?.trades || []

  const sortedTrades = useMemo(() => {
    const copy = [...trades]
    copy.sort((a, b) => {
      const av = a[sortBy]
      const bv = b[sortBy]
      if (av === bv) return 0
      if (sortDir === 'asc') return av > bv ? 1 : -1
      return av < bv ? 1 : -1
    })
    return copy
  }, [trades, sortBy, sortDir])

  const toggleSort = (col) => {
    if (sortBy === col) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortBy(col)
      setSortDir('asc')
    }
  }

  return (
    <section className='h-full overflow-auto p-3 grid gap-3 text-slate-200'>
      <div className='text-xs tracking-[0.2em] text-cyan-300'>BACKTESTING ENGINE</div>

      <div className='border border-slate-700 bg-slate-900 p-3 grid gap-3'>
        <div className='grid grid-cols-2 md:grid-cols-7 gap-2 text-xs'>
          <label className='grid gap-1'>
            <span>Symbol</span>
            <select className='bg-slate-950 border border-slate-700 p-1' value={cfg.symbol} onChange={(e) => setCfg((p) => ({ ...p, symbol: e.target.value }))}>
              {SYMBOLS.map((s) => <option key={s}>{s}</option>)}
            </select>
          </label>
          <label className='grid gap-1'>
            <span>Strategy</span>
            <select className='bg-slate-950 border border-slate-700 p-1' value={cfg.strategy} onChange={(e) => setCfg((p) => ({ ...p, strategy: e.target.value }))}>
              {STRATEGIES.map((s) => <option key={s}>{s}</option>)}
            </select>
          </label>
          <label className='grid gap-1'><span>n_snapshots</span><input className='bg-slate-950 border border-slate-700 p-1 font-mono' type='number' min='100' max='2000' value={cfg.n_snapshots} onChange={(e) => setCfg((p) => ({ ...p, n_snapshots: e.target.value }))} /></label>
          <label className='grid gap-1'><span>hold_periods</span><input className='bg-slate-950 border border-slate-700 p-1 font-mono' type='number' min='1' max='50' value={cfg.hold_periods} onChange={(e) => setCfg((p) => ({ ...p, hold_periods: e.target.value }))} /></label>
          <label className='grid gap-1'><span>Stop Loss %</span><input className='bg-slate-950 border border-slate-700 p-1 font-mono' type='number' step='0.1' value={cfg.stop_loss_pct} onChange={(e) => setCfg((p) => ({ ...p, stop_loss_pct: e.target.value }))} /></label>
          <label className='grid gap-1'><span>Position %</span><input className='bg-slate-950 border border-slate-700 p-1 font-mono' type='number' step='1' value={cfg.position_size_pct} onChange={(e) => setCfg((p) => ({ ...p, position_size_pct: e.target.value }))} /></label>
          <div className='flex items-end gap-2'>
            <button className='border border-slate-600 px-2 py-1 hover:bg-slate-800' onClick={runBacktest} disabled={loading}>Run Backtest</button>
            <button className='border border-slate-600 px-2 py-1 hover:bg-slate-800' onClick={compareAll} disabled={loading}>Compare All</button>
            {loading && <Spinner />}
          </div>
        </div>

        <div className='flex gap-2 text-xs'>
          {['results', 'trades', 'compare'].map((t) => (
            <button key={t} className={`px-2 py-1 border ${tab === t ? 'border-cyan-400 text-cyan-300' : 'border-slate-700 text-slate-300'}`} onClick={() => setTab(t)}>
              {t === 'results' ? 'Results' : t === 'trades' ? 'Trade Log' : 'Compare'}
            </button>
          ))}
        </div>
        {error && <div className='text-red-400 text-sm'>{error}</div>}
      </div>

      {!result && tab !== 'compare' && <div className='text-slate-400 text-sm'>Run your first backtest to populate this panel.</div>}

      {tab === 'results' && metrics && (
        <div className='grid gap-3'>
          <div className='grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-2 text-xs'>
            {[
              ['Total PnL', inr(metrics.total_pnl), metrics.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'],
              ['Sharpe Ratio', num(metrics.sharpe), 'text-slate-100'],
              ['Max Drawdown', pct(metrics.max_drawdown), 'text-slate-100'],
              ['Win Rate', pct(metrics.win_rate), 'text-slate-100'],
              ['Final Equity', inr(metrics.final_equity), 'text-slate-100'],
              ['Calmar Ratio', num(metrics.calmar), 'text-slate-100'],
              ['Profit Factor', num(metrics.profit_factor), 'text-slate-100'],
              ['Total Trades', String(metrics.total_trades), 'text-slate-100'],
            ].map(([k, v, cls]) => (
              <div key={k} className='border border-slate-700 bg-slate-900 p-2'>
                <div className='text-slate-400'>{k}</div>
                <div className={`font-mono text-sm ${cls}`}>{v}</div>
              </div>
            ))}
          </div>

          <div className='border border-slate-700 bg-slate-900 p-2'>
            <div className='text-xs text-slate-400 mb-2'>Equity Curve</div>
            <EquitySvg curve={metrics.equity_curve} initial={result.config.initial_capital} />
          </div>

          <div className='border border-slate-700 bg-slate-900 p-2'>
            <div className='text-xs text-slate-400 mb-2'>Per-Trade PnL (Last 50)</div>
            <PnlSvg series={metrics.pnl_series} />
          </div>
        </div>
      )}

      {tab === 'trades' && (
        <div className='border border-slate-700 bg-slate-900 p-2 overflow-auto'>
          <table className='w-full text-xs'>
            <thead>
              <tr className='text-slate-400'>
                {[['#', 'entry_period'], ['Direction', 'direction'], ['Entry Price', 'entry_price'], ['Exit Price', 'exit_price'], ['Qty', 'quantity'], ['PnL (Rs.)', 'pnl'], ['Return %', 'return_pct'], ['Hold', 'hold_periods'], ['Exit Reason', 'exit_reason']].map(([label, key]) => (
                  <th key={key} className='text-left p-1 cursor-pointer' onClick={() => toggleSort(key)}>{label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sortedTrades.map((t, i) => (
                <tr key={`${t.entry_period}-${t.exit_period}-${i}`} className='border-t border-slate-800'>
                  <td className='p-1 font-mono'>{i + 1}</td>
                  <td className={`p-1 font-semibold ${t.direction === 'LONG' ? 'text-blue-400' : 'text-orange-400'}`}>{t.direction}</td>
                  <td className='p-1 font-mono'>{num(t.entry_price, 2)}</td>
                  <td className='p-1 font-mono'>{num(t.exit_price, 2)}</td>
                  <td className='p-1 font-mono'>{num(t.quantity, 2)}</td>
                  <td className={`p-1 font-mono ${t.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>{inr(t.pnl)}</td>
                  <td className='p-1 font-mono'>{num(t.return_pct, 3)}%</td>
                  <td className='p-1 font-mono'>{t.hold_periods}</td>
                  <td className='p-1'>{t.exit_reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === 'compare' && (
        <div className='grid gap-3'>
          <div className='border border-slate-700 bg-slate-900 p-2'>
            <div className='text-xs text-slate-400 mb-2'>Sharpe Ranking</div>
            <CompareBars rows={compare?.leaderboard || []} />
          </div>

          <div className='border border-slate-700 bg-slate-900 p-2 overflow-auto'>
            <table className='w-full text-xs'>
              <thead>
                <tr className='text-slate-400'>
                  <th className='text-left p-1'>Strategy</th>
                  <th className='text-left p-1'>Sharpe</th>
                  <th className='text-left p-1'>Total PnL</th>
                  <th className='text-left p-1'>Win Rate</th>
                  <th className='text-left p-1'>Max DD</th>
                  <th className='text-left p-1'>Trades</th>
                  <th className='text-left p-1'>Calmar</th>
                </tr>
              </thead>
              <tbody>
                {(compare?.leaderboard || []).map((r, idx) => (
                  <tr key={r.strategy} className={`border-t border-slate-800 ${idx === 0 ? 'bg-cyan-950/30' : ''}`}>
                    <td className='p-1 uppercase'>{r.strategy}</td>
                    <td className='p-1 font-mono'>{num(r.sharpe)}</td>
                    <td className={`p-1 font-mono ${r.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>{inr(r.total_pnl)}</td>
                    <td className='p-1 font-mono'>{pct(r.win_rate)}</td>
                    <td className='p-1 font-mono'>{pct(r.max_drawdown)}</td>
                    <td className='p-1 font-mono'>{r.total_trades}</td>
                    <td className='p-1 font-mono'>{num(r.calmar)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  )
}
