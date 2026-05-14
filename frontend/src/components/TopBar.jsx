const SYMBOLS = ['RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'ICICIBANK']

function secondsAgo(lastUpdate) {
  if (!lastUpdate) return '—'
  const parsed = typeof lastUpdate === 'number' ? lastUpdate : Date.parse(lastUpdate)
  if (Number.isNaN(parsed)) return '—'
  return Math.max(0, Math.floor((Date.now() - parsed) / 1000))
}

function Pill({ children, tone = 'default' }) {
  const styles = {
    default: {
      background: 'rgba(255,255,255,0.03)',
      borderColor: 'var(--border)',
      color: 'var(--text-secondary)',
    },
    green: {
      background: 'var(--green-dim)',
      borderColor: 'rgba(0, 211, 149, 0.24)',
      color: 'var(--text-primary)',
    },
    red: {
      background: 'var(--red-dim)',
      borderColor: 'rgba(255, 71, 87, 0.24)',
      color: 'var(--text-primary)',
    },
  }

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '6px 10px',
        borderRadius: 999,
        border: `1px solid ${styles[tone].borderColor}`,
        background: styles[tone].background,
        color: styles[tone].color,
        fontSize: 11,
        letterSpacing: '0.08em',
        textTransform: 'uppercase',
        whiteSpace: 'nowrap',
      }}
    >
      {children}
    </div>
  )
}

export default function TopBar({
  activeSymbol,
  onSymbolChange,
  wsConnected,
  lastUpdate,
  narrative,
}) {
  const elapsed = secondsAgo(lastUpdate)

  return (
    <header
      style={{
        height: 52,
        background: 'var(--bg-panel)',
        borderBottom: '1px solid var(--border)',
        padding: '0 20px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        zIndex: 20,
        gap: 16,
      }}
    >
      <div style={{ minWidth: 220 }}>
        <div
          style={{
            fontFamily: 'var(--font-mono)',
            fontWeight: 700,
            fontSize: 18,
            letterSpacing: '0.16em',
            color: 'var(--green)',
          }}
        >
          ALPHACORE
        </div>
        <div
          style={{
            color: 'var(--text-muted)',
            fontSize: 10,
            letterSpacing: '0.14em',
          }}
        >
          ORDER BOOK INTELLIGENCE
        </div>
      </div>

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          justifyContent: 'center',
          flexWrap: 'wrap',
        }}
      >
        {SYMBOLS.map((symbol) => {
          const active = activeSymbol === symbol
          return (
            <button
              key={symbol}
              type="button"
              onClick={() => onSymbolChange(symbol)}
              style={{
                padding: '4px 10px',
                borderRadius: 4,
                border: active
                  ? '1px solid var(--blue)'
                  : '1px solid transparent',
                background: active ? 'var(--blue-dim)' : 'transparent',
                color: active ? 'var(--text-primary)' : 'var(--text-secondary)',
                fontFamily: 'var(--font-mono)',
                cursor: 'pointer',
                letterSpacing: '0.06em',
              }}
            >
              {symbol}
            </button>
          )
        })}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 320 }}>
        <Pill tone={wsConnected ? 'green' : 'red'}>
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: '50%',
              background: wsConnected ? 'var(--green)' : 'var(--red)',
              boxShadow: `0 0 10px ${wsConnected ? 'var(--green-dim)' : 'var(--red-dim)'}`,
            }}
          />
          <span>WS: {wsConnected ? 'LIVE' : 'OFF'}</span>
        </Pill>
        <Pill>UPDATED: {elapsed === '—' ? '—' : `${elapsed}s ago`}</Pill>
        <Pill>REGIME: {narrative || 'NO SIGNAL'}</Pill>
      </div>
    </header>
  )
}
