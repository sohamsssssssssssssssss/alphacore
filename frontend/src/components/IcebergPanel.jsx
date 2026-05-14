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

function confidenceTone(confidence) {
  if (confidence >= 70) return { bg: 'var(--green-dim)', color: 'var(--green)' }
  if (confidence >= 40) return { bg: 'var(--yellow-dim)', color: 'var(--yellow)' }
  return { bg: 'rgba(255,255,255,0.04)', color: 'var(--text-secondary)' }
}

export default function IcebergPanel({ data }) {
  const items = Array.isArray(data) ? data : []

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
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 12,
        }}
      >
        <div style={{ color: 'var(--text-secondary)', fontSize: 11, letterSpacing: '0.14em' }}>
          ICEBERG DETECTIONS
        </div>
        <div
          style={{
            minWidth: 24,
            textAlign: 'center',
            padding: '2px 8px',
            borderRadius: 999,
            background: 'var(--blue-dim)',
            color: 'var(--blue)',
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
          }}
        >
          {items.length}
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
          No icebergs detected this session
        </div>
      ) : (
        <div style={{ flex: 1, overflowY: 'auto', paddingRight: 2 }}>
          {items.map((item) => {
            const side = (item.side || item.direction || '').toLowerCase()
            const confidence = Number(item.confidence ?? item.confidence_score ?? 0)
            const tone = confidenceTone(confidence)
            return (
              <div
                key={item.id}
                style={{
                  background: 'var(--bg-card)',
                  borderLeft: `3px solid ${side === 'buy' ? 'var(--green)' : 'var(--red)'}`,
                  padding: '10px 12px',
                  marginBottom: 6,
                  borderRadius: 4,
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
                      background: side === 'buy' ? 'var(--green-dim)' : 'var(--red-dim)',
                      color: side === 'buy' ? 'var(--green)' : 'var(--red)',
                      fontSize: 10,
                      letterSpacing: '0.1em',
                    }}
                  >
                    {side.toUpperCase()}
                  </span>
                  <span
                    style={{
                      padding: '2px 7px',
                      borderRadius: 999,
                      background: tone.bg,
                      color: tone.color,
                      fontSize: 10,
                      letterSpacing: '0.1em',
                    }}
                  >
                    CONF: {confidence}%
                  </span>
                </div>
                <div
                  style={{
                    marginTop: 8,
                    display: 'flex',
                    justifyContent: 'space-between',
                    gap: 12,
                    color: 'var(--text-primary)',
                    fontSize: 12,
                  }}
                >
                  <span style={{ fontFamily: 'var(--font-mono)' }}>
                    @ ₹{formatNumber(item.price ?? item.price_level, 2)}
                  </span>
                  <span>EST. HIDDEN: {formatNumber(item.estimated_hidden_volume)}</span>
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
                  <span>REFILLS: {formatNumber(item.refill_count)}</span>
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
