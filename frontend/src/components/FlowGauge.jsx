function formatNumber(value, digits = 0) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return new Intl.NumberFormat('en-IN', {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  }).format(Number(value))
}

function polarToCartesian(cx, cy, radius, angle) {
  const radians = ((angle - 90) * Math.PI) / 180
  return {
    x: cx + radius * Math.cos(radians),
    y: cy + radius * Math.sin(radians),
  }
}

function describeArc(cx, cy, radius, startAngle, endAngle) {
  const start = polarToCartesian(cx, cy, radius, endAngle)
  const end = polarToCartesian(cx, cy, radius, startAngle)
  const largeArcFlag = endAngle - startAngle <= 180 ? '0' : '1'
  return `M ${start.x} ${start.y} A ${radius} ${radius} 0 ${largeArcFlag} 0 ${end.x} ${end.y}`
}

export default function FlowGauge({ data }) {
  const score = Number(data?.imbalance_score ?? 0)
  const hasData = Boolean(data)
  const clamped = Math.max(-1, Math.min(1, score))
  const rotation = clamped * 90
  const tone = !hasData
    ? 'var(--text-muted)'
    : clamped >= 0
      ? 'var(--green)'
      : 'var(--red)'

  return (
    <section
      style={{
        height: '100%',
        padding: 12,
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <div
        style={{
          color: 'var(--text-secondary)',
          fontSize: 11,
          letterSpacing: '0.14em',
          marginBottom: 12,
        }}
      >
        ORDER FLOW
      </div>

      <div style={{ flex: 1, display: 'grid', placeItems: 'center' }}>
        <div style={{ position: 'relative', width: 220, height: 180 }}>
          <svg width="220" height="180" viewBox="0 0 220 180">
            <defs>
              <linearGradient id="flowArc" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stopColor="var(--red)" />
                <stop offset="50%" stopColor="var(--text-muted)" />
                <stop offset="100%" stopColor="var(--green)" />
              </linearGradient>
            </defs>
            <path
              d={describeArc(110, 128, 74, -90, 90)}
              fill="none"
              stroke="rgba(255,255,255,0.06)"
              strokeWidth="16"
              strokeLinecap="round"
            />
            <path
              d={describeArc(110, 128, 74, -90, 90)}
              fill="none"
              stroke={hasData ? 'url(#flowArc)' : 'rgba(255,255,255,0.12)'}
              strokeWidth="10"
              strokeLinecap="round"
            />
            <g transform={`rotate(${rotation}, 110, 128)`}>
              <line
                x1="110"
                y1="128"
                x2="110"
                y2="52"
                stroke={tone}
                strokeWidth="3"
                strokeLinecap="round"
              />
              <circle cx="110" cy="128" r="6" fill={tone} />
            </g>
          </svg>

          <div
            style={{
              position: 'absolute',
              inset: 0,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 4,
              transform: 'translateY(12px)',
            }}
          >
            <div
              style={{
                color: tone,
                fontFamily: 'var(--font-mono)',
                fontSize: 30,
                fontWeight: 700,
              }}
            >
              {hasData ? formatNumber(clamped, 2) : '—'}
            </div>
            <div
              style={{
                color: 'var(--text-muted)',
                fontSize: 11,
                letterSpacing: '0.14em',
              }}
            >
              FLOW IMBALANCE
            </div>
          </div>
        </div>
      </div>

      <div
        style={{
          display: 'grid',
          gap: 8,
          borderTop: '1px solid var(--border)',
          paddingTop: 12,
          fontFamily: 'var(--font-mono)',
          fontSize: 12,
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--green)' }}>
          <span>BUY VOL</span>
          <span>{formatNumber(data?.aggressive_buys ?? data?.buy_volume)}</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--red)' }}>
          <span>SELL VOL</span>
          <span>{formatNumber(data?.aggressive_sells ?? data?.sell_volume)}</span>
        </div>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            color: 'var(--text-secondary)',
          }}
        >
          <span>WINDOW</span>
          <span>
            {data?.window_seconds
              ? `${data.window_seconds}s`
              : data?.window_minutes
                ? `${data.window_minutes * 60}s`
                : '—'}
          </span>
        </div>
      </div>
    </section>
  )
}
