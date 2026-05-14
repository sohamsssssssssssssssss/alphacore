function timeAgo(timestamp) {
  if (!timestamp) return '—'
  const diff = Math.max(0, Math.floor((Date.now() - Date.parse(timestamp)) / 1000))
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

function regimeIcon(regime) {
  switch (regime) {
    case 'recession_fear':
      return '📉'
    case 'rate_hike':
      return '⟰'
    case 'geopolitical':
      return '⚡'
    default:
      return '◎'
  }
}

function confidenceTone(confidence) {
  const normalized = (confidence || '').toUpperCase()
  if (normalized === 'HIGH') {
    return {
      color: 'var(--green)',
      background: 'linear-gradient(90deg, var(--bg-panel), var(--green-dim))',
      badge: 'var(--green-dim)',
    }
  }
  if (normalized === 'MEDIUM') {
    return {
      color: 'var(--yellow)',
      background: 'linear-gradient(90deg, var(--bg-panel), var(--yellow-dim))',
      badge: 'var(--yellow-dim)',
    }
  }
  return {
    color: 'var(--text-secondary)',
    background: 'var(--bg-panel)',
    badge: 'rgba(255,255,255,0.05)',
  }
}

export default function NarrativeBanner({ data }) {
  if (!data) {
    return (
      <section
        style={{
          height: 44,
          display: 'flex',
          alignItems: 'center',
          padding: '0 16px',
          background: 'var(--bg-panel)',
          color: 'var(--text-muted)',
          letterSpacing: '0.12em',
          fontSize: 11,
          borderTop: '1px solid var(--border)',
        }}
      >
        NO NARRATIVE SIGNAL — POST FROM NARRATIVEEDGE
      </section>
    )
  }

  const tone = confidenceTone(data.confidence)

  return (
    <section
      style={{
        height: 44,
        display: 'grid',
        gridTemplateColumns: '1.2fr 0.6fr 1fr',
        alignItems: 'center',
        padding: '0 16px',
        background: tone.background,
        borderTop: '1px solid var(--border)',
        gap: 12,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
        <span style={{ fontSize: 16 }}>{regimeIcon(data.regime)}</span>
        <span
          style={{
            fontWeight: 700,
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          {data.narrative}
        </span>
        <span
          style={{
            padding: '2px 7px',
            borderRadius: 999,
            background: 'rgba(255,255,255,0.06)',
            color: 'var(--text-secondary)',
            fontSize: 10,
            letterSpacing: '0.1em',
          }}
        >
          {data.strength || 'UNSPECIFIED'}
        </span>
      </div>

      <div style={{ justifySelf: 'center' }}>
        <span
          style={{
            padding: '3px 9px',
            borderRadius: 999,
            background: tone.badge,
            color: tone.color,
            fontSize: 11,
            letterSpacing: '0.12em',
          }}
        >
          {data.confidence}
        </span>
      </div>

      <div
        style={{
          justifySelf: 'end',
          color: 'var(--text-secondary)',
          fontSize: 11,
          display: 'flex',
          gap: 14,
          whiteSpace: 'nowrap',
        }}
      >
        <span>ACTIVE SINCE {data.started || '—'}</span>
        <span>UPDATED {timeAgo(data.received_at)}</span>
      </div>
    </section>
  )
}
