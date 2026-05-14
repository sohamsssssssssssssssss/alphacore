import { useMemo } from 'react'
import { usePolling } from '../hooks/usePolling'

function formatTime(ts) {
  if (!ts) return '—'
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ts
  return d.toLocaleTimeString()
}

export default function RegulatoryPanel() {
  const { data: breakers } = usePolling('/api/regulatory/circuit-breakers', 10000)
  const { data: killSwitch } = usePolling('/api/regulatory/kill-switch', 5000)
  const { data: otr } = usePolling('/api/regulatory/otr', 10000)

  const breakerRows = useMemo(() => Object.entries(breakers || {}), [breakers])
  const otrRows = useMemo(() => Object.entries(otr || {}), [otr])

  const toggleKillSwitch = async () => {
    if (killSwitch?.active) {
      await fetch('/api/regulatory/kill-switch/deactivate', { method: 'POST' })
      return
    }
    await fetch('/api/regulatory/kill-switch/activate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: 'Triggered from dashboard' }),
    })
  }

  const resetBreaker = async (symbol) => {
    await fetch(`/api/regulatory/circuit-breakers/${symbol}/reset`, { method: 'POST' })
  }

  return (
    <section style={{ height: '100%', overflow: 'auto', padding: 12 }}>
      <div style={{ fontSize: 11, letterSpacing: '0.14em', color: 'var(--yellow)', marginBottom: 10 }}>
        REGULATORY CONTROLS
      </div>

      <div
        style={{
          marginBottom: 12,
          padding: 12,
          border: '1px solid var(--border)',
          borderRadius: 8,
          background: killSwitch?.active ? 'var(--red-dim)' : 'var(--green-dim)',
          color: killSwitch?.active ? 'var(--red)' : 'var(--green)',
          fontFamily: 'var(--font-mono)',
          fontWeight: 700,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <span>{killSwitch?.active ? 'KILL SWITCH ACTIVE' : 'Systems Normal'}</span>
        <button
          onClick={toggleKillSwitch}
          style={{
            background: 'var(--bg-card)',
            color: 'var(--text-primary)',
            border: '1px solid var(--border-bright)',
            borderRadius: 6,
            padding: '6px 10px',
            cursor: 'pointer',
            fontFamily: 'var(--font-mono)',
          }}
        >
          {killSwitch?.active ? 'Deactivate' : 'Activate'}
        </button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
        <div style={{ border: '1px solid var(--border)', borderRadius: 8, background: 'var(--bg-card)', padding: 10 }}>
          <div style={{ marginBottom: 8, color: 'var(--text-secondary)', fontSize: 12 }}>Circuit Breakers</div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ color: 'var(--text-secondary)', textAlign: 'left' }}>
                <th>Symbol</th><th>Reason</th><th>Halted</th><th></th>
              </tr>
            </thead>
            <tbody>
              {breakerRows.length === 0 && (
                <tr><td colSpan={4} style={{ color: 'var(--text-muted)', paddingTop: 8 }}>No halted symbols</td></tr>
              )}
              {breakerRows.map(([symbol, value]) => (
                <tr key={symbol}>
                  <td>{symbol}</td>
                  <td style={{ color: 'var(--text-secondary)' }}>{value.reason}</td>
                  <td style={{ color: 'var(--text-secondary)' }}>{formatTime(value.halted_at)}</td>
                  <td>
                    <button
                      onClick={() => resetBreaker(symbol)}
                      style={{
                        background: 'transparent',
                        color: 'var(--blue)',
                        border: '1px solid var(--border-bright)',
                        borderRadius: 6,
                        padding: '4px 8px',
                        cursor: 'pointer',
                      }}
                    >
                      Reset
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div style={{ border: '1px solid var(--border)', borderRadius: 8, background: 'var(--bg-card)', padding: 10 }}>
          <div style={{ marginBottom: 8, color: 'var(--text-secondary)', fontSize: 12 }}>OTR Monitor</div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ color: 'var(--text-secondary)', textAlign: 'left' }}>
                <th>Symbol</th><th>Orders</th><th>Trades</th><th>Ratio</th><th>Status</th>
              </tr>
            </thead>
            <tbody>
              {otrRows.length === 0 && (
                <tr><td colSpan={5} style={{ color: 'var(--text-muted)', paddingTop: 8 }}>No OTR data</td></tr>
              )}
              {otrRows.map(([symbol, value]) => (
                <tr key={symbol}>
                  <td>{symbol}</td>
                  <td>{value.orders}</td>
                  <td>{value.trades}</td>
                  <td>{Number(value.otr || 0).toFixed(2)}</td>
                  <td>
                    {value.breached ? (
                      <span style={{ color: 'var(--yellow)', border: '1px solid var(--yellow)', borderRadius: 999, padding: '2px 6px' }}>BREACH</span>
                    ) : (
                      <span style={{ color: 'var(--green)' }}>OK</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  )
}
