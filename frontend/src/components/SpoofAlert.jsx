function formatNumber(value, digits = 0) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return new Intl.NumberFormat('en-IN', {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  }).format(Number(value))
}

function timeAgo(timestamp) {
  if (!timestamp) return '—'
  const diff = Math.max(0, Math.floor((Date.now() - Date.parse(timestamp)) / 1000))
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  return `${Math.floor(diff / 3600)}h ago`
}

function severityMeta(severity) {
  const normalized = (severity || '').toUpperCase()
  if (normalized === 'HIGH') {
    return {
      label: '⚠ HIGH',
      background: 'rgba(255, 71, 87, 0.18)',
      color: 'var(--red)',
      border: '1px solid var(--red)',
      shadow: '0 0 8px var(--red-dim)',
    }
  }
  if (normalized === 'MEDIUM') {
    return {
      label: '◆ MEDIUM',
      background: 'rgba(255, 165, 2, 0.18)',
      color: 'var(--yellow)',
      border: '1px solid rgba(255, 165, 2, 0.24)',
      shadow: 'none',
    }
  }
  return {
    label: '○ LOW',
    background: 'rgba(255,255,255,0.05)',
    color: 'var(--text-secondary)',
    border: '1px solid var(--border)',
    shadow: 'none',
  }
}

export default function SpoofAlert({ data }) {
  const items = Array.isArray(data) ? data : []
  const high = items.filter((item) => item.severity === 'HIGH').length
  const medium = items.filter((item) => item.severity === 'MEDIUM').length
  const low = items.filter((item) => item.severity === 'LOW').length

  return (
    <section
      style={{
        height: '100%',
        padding: 12,
        display: 'flex',
        flexDirection: 'column',
        minHeight: 0,
      }}
    >
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'auto auto',
          alignItems: 'center',
          gap: 8,
          marginBottom: 12,
        }}
      >
        <div style={{ color: 'var(--text-secondary)', fontSize: 11, letterSpacing: '0.14em' }}>
          SPOOF ALERTS
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, justifySelf: 'end' }}>
          <div
            style={{
              padding: '2px 8px',
              borderRadius: 999,
              background: 'rgba(255,255,255,0.05)',
              color: 'var(--text-secondary)',
              fontSize: 10,
              letterSpacing: '0.08em',
            }}
          >
            {high} HIGH&nbsp;&nbsp;{medium} MED&nbsp;&nbsp;{low} LOW
          </div>
          <div
            style={{
              minWidth: 24,
              textAlign: 'center',
              padding: '2px 8px',
              borderRadius: 999,
              background: high > 0 ? 'var(--red-dim)' : 'var(--blue-dim)',
              color: high > 0 ? 'var(--red)' : 'var(--blue)',
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
            }}
          >
            {items.length}
          </div>
        </div>
      </div>

      {items.length === 0 ? (
        <div
          style={{
            flex: 1,
            display: 'grid',
            placeItems: 'center',
            color: 'var(--text-muted)',
          }}
        >
          No spoofing detected this session
        </div>
      ) : (
        <div style={{ flex: 1, overflowY: 'auto', paddingRight: 2 }}>
          {items.map((item) => {
            const meta = severityMeta(item.confidence_level || item.severity)
            return (
              <div
                key={item.id}
                style={{
                  background: 'var(--bg-card)',
                  padding: '10px 12px',
                  marginBottom: 6,
                  borderRadius: 4,
                  border: meta.border,
                  boxShadow: meta.shadow,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                  <span
                    style={{
                      padding: '2px 7px',
                      borderRadius: 999,
                      background: 'var(--blue-dim)',
                      color: 'var(--blue)',
                      fontSize: 10,
                      letterSpacing: '0.1em',
                    }}
                  >
                    {item.symbol}
                  </span>
                  <span
                    style={{
                      padding: '2px 7px',
                      borderRadius: 999,
                      background: meta.background,
                      color: meta.color,
                      fontSize: 10,
                      letterSpacing: '0.1em',
                    }}
                  >
                    {meta.label}
                  </span>
                  <span
                    style={{
                      color: 'var(--text-secondary)',
                      fontFamily: 'var(--font-mono)',
                      fontSize: 11,
                    }}
                  >
                    SCORE: {formatNumber(item.spoof_score)}/100
                  </span>
                </div>
                <div
                  style={{
                    marginTop: 8,
                    display: 'flex',
                    justifyContent: 'space-between',
                    gap: 12,
                    fontSize: 12,
                  }}
                >
                  <span>SIZE: {formatNumber(item.order_size)}</span>
                  <span style={{ fontFamily: 'var(--font-mono)' }}>
                    @ ₹{formatNumber(item.price ?? item.order_price, 2)}
                  </span>
                </div>
                <div
                  style={{
                    marginTop: 6,
                    display: 'flex',
                    justifyContent: 'space-between',
                    color: 'var(--text-secondary)',
                    fontSize: 11,
                  }}
                >
                  <span>ACTIVE: {formatNumber(item.time_active_seconds)}s</span>
                  <span>{timeAgo(item.detected_at)}</span>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}
