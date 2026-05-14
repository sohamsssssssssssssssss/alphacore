import { useMemo } from 'react'
import { usePolling } from '../hooks/usePolling'

const TRACKED_SYMBOLS = ['RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'ICICIBANK']

function formatPrice(value) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return `₹${Number(value).toFixed(2)}`
}

function timeSince(isoTime) {
  if (!isoTime) return '—'
  const diffMs = Date.now() - new Date(isoTime).getTime()
  if (!Number.isFinite(diffMs) || diffMs < 0) return 'just now'
  const sec = Math.floor(diffMs / 1000)
  if (sec < 60) return `${sec}s ago`
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min}m ago`
  const hrs = Math.floor(min / 60)
  return `${hrs}h ago`
}

function SignalCard({ signal }) {
  const direction = signal?.direction || 'NEUTRAL'
  const directionColor =
    direction === 'BUY' ? 'var(--green)' : direction === 'SELL' ? 'var(--red)' : 'var(--text-secondary)'
  const directionBg =
    direction === 'BUY' ? 'var(--green-dim)' : direction === 'SELL' ? 'var(--red-dim)' : 'var(--bg-hover)'
  const confidence = Math.max(0, Math.min(100, Number(signal?.confidence || 0)))

  return (
    <div
      style={{
        border: '1px solid var(--border)',
        borderRadius: 8,
        padding: 12,
        background: 'var(--bg-card)',
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ fontSize: 19, fontWeight: 700, letterSpacing: '0.04em' }}>{signal?.symbol || '—'}</div>
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            letterSpacing: '0.1em',
            padding: '4px 8px',
            borderRadius: 999,
            background: directionBg,
            color: directionColor,
            border: `1px solid ${directionColor}`,
          }}
        >
          {direction}
        </span>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
          gap: 8,
          fontFamily: 'var(--font-mono)',
          fontSize: 12,
        }}
      >
        <div>Entry: <span style={{ color: 'var(--text-primary)' }}>{formatPrice(signal?.entry_price)}</span></div>
        <div>SL: <span style={{ color: 'var(--red)' }}>{formatPrice(signal?.stop_loss)}</span></div>
        <div>Target: <span style={{ color: 'var(--green)' }}>{formatPrice(signal?.target_price)}</span></div>
      </div>

      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text-secondary)', marginBottom: 4 }}>
          <span>CONFIDENCE</span>
          <span style={{ fontFamily: 'var(--font-mono)' }}>{confidence}%</span>
        </div>
        <div style={{ height: 8, borderRadius: 999, background: 'rgba(255,255,255,0.06)', overflow: 'hidden' }}>
          <div
            style={{
              width: `${confidence}%`,
              height: '100%',
              background: direction === 'SELL' ? 'var(--red)' : direction === 'BUY' ? 'var(--green)' : 'var(--text-secondary)',
            }}
          />
        </div>
      </div>

      <ul style={{ margin: 0, paddingLeft: 18, color: 'var(--text-secondary)', fontSize: 12 }}>
        {(signal?.reasons?.length ? signal.reasons : ['No active signal']).map((reason, idx) => (
          <li key={`${signal?.symbol || 'neutral'}-${idx}`}>{reason}</li>
        ))}
      </ul>

      <div style={{ color: 'var(--text-muted)', fontSize: 11 }}>Updated {timeSince(signal?.generated_at)}</div>
    </div>
  )
}

export default function SignalPanel() {
  const { data } = usePolling('/api/signals/latest', 5000)

  const signals = useMemo(() => {
    const latestBySymbol = data && typeof data === 'object' ? data : {}
    return TRACKED_SYMBOLS.map((symbol) => {
      const signal = latestBySymbol[symbol]
      if (signal) return signal
      return {
        symbol,
        direction: 'NEUTRAL',
        reasons: ['No active signal'],
      }
    })
  }, [data])

  return (
    <section style={{ height: '100%', padding: 12, overflow: 'auto' }}>
      <div style={{ fontSize: 11, letterSpacing: '0.14em', color: 'var(--blue)', marginBottom: 10 }}>
        ALPHA SIGNALS
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 10 }}>
        {signals.map((signal) => (
          <SignalCard key={signal.symbol} signal={signal} />
        ))}
      </div>
    </section>
  )
}
