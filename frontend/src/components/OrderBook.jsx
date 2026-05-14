function formatNumber(value, digits = 0) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return new Intl.NumberFormat('en-IN', {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  }).format(Number(value))
}

function formatPrice(value) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return `₹${formatNumber(value, 2)}`
}

function Row({ side, level, maxVolume }) {
  const width = maxVolume > 0 ? `${(level.volume / maxVolume) * 100}%` : '0%'
  const isBid = side === 'bid'

  return (
    <div
      style={{
        position: 'relative',
        display: 'grid',
        gridTemplateColumns: isBid ? '90px minmax(0, 1fr)' : 'minmax(0, 1fr) 90px',
        alignItems: 'center',
        minHeight: 28,
        padding: '0 8px',
        overflow: 'hidden',
        borderBottom: '1px solid rgba(255,255,255,0.03)',
      }}
    >
      <div
        style={{
          position: 'absolute',
          top: 4,
          bottom: 4,
          [isBid ? 'right' : 'left']: 8,
          width,
          background: isBid ? 'var(--green-dim)' : 'var(--red-dim)',
          borderRadius: 4,
        }}
      />
      {isBid ? (
        <>
          <div
            style={{
              position: 'relative',
              zIndex: 1,
              textAlign: 'right',
              color: 'var(--green)',
              fontFamily: 'var(--font-mono)',
              fontSize: 12,
            }}
          >
            {formatPrice(level.price)}
          </div>
          <div
            style={{
              position: 'relative',
              zIndex: 1,
              textAlign: 'left',
              color: 'var(--text-primary)',
              fontFamily: 'var(--font-mono)',
              fontSize: 12,
              paddingLeft: 12,
            }}
          >
            {formatNumber(level.volume)}
          </div>
        </>
      ) : (
        <>
          <div
            style={{
              position: 'relative',
              zIndex: 1,
              color: 'var(--text-primary)',
              fontFamily: 'var(--font-mono)',
              fontSize: 12,
              paddingRight: 12,
              textAlign: 'right',
            }}
          >
            {formatNumber(level.volume)}
          </div>
          <div
            style={{
              position: 'relative',
              zIndex: 1,
              textAlign: 'left',
              color: 'var(--red)',
              fontFamily: 'var(--font-mono)',
              fontSize: 12,
            }}
          >
            {formatPrice(level.price)}
          </div>
        </>
      )}
    </div>
  )
}

export default function OrderBook({ data }) {
  if (!data) {
    return (
      <section
        style={{
          height: '100%',
          display: 'grid',
          placeItems: 'center',
          color: 'var(--text-muted)',
          letterSpacing: '0.12em',
          padding: 12,
        }}
      >
        AWAITING DATA...
      </section>
    )
  }

  const bids = data.bids?.slice(0, 5) ?? []
  const asks = data.asks?.slice(0, 5) ?? []
  const maxBidVolume = Math.max(...bids.map((level) => level.volume), 0)
  const maxAskVolume = Math.max(...asks.map((level) => level.volume), 0)
  const bidShare = Math.max(0, Math.min(1, (Number(data.bid_ask_imbalance ?? 0) + 1) / 2))
  const askShare = 1 - bidShare

  return (
    <section
      style={{
        height: '100%',
        padding: 12,
        display: 'flex',
        flexDirection: 'column',
        position: 'relative',
      }}
    >
      {data.stale ? (
        <div
          style={{
            position: 'absolute',
            top: 12,
            right: 12,
            padding: '3px 7px',
            borderRadius: 999,
            background: 'var(--yellow-dim)',
            color: 'var(--yellow)',
            fontSize: 10,
            letterSpacing: '0.12em',
          }}
        >
          MOCK DATA
        </div>
      ) : null}

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 84px 1fr',
          gap: 10,
          flex: 1,
          minHeight: 0,
        }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          <div
            style={{
              textAlign: 'right',
              color: 'var(--green)',
              fontSize: 11,
              letterSpacing: '0.14em',
              marginBottom: 8,
            }}
          >
            BIDS
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {bids.map((level, index) => (
              <Row key={`bid-${index}`} side="bid" level={level} maxVolume={maxBidVolume} />
            ))}
          </div>
        </div>

        <div
          style={{
            borderLeft: '1px solid var(--border)',
            borderRight: '1px solid var(--border)',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 14,
            padding: '0 8px',
          }}
        >
          <div
            style={{
              color: 'var(--text-secondary)',
              fontSize: 11,
              letterSpacing: '0.12em',
              textAlign: 'center',
            }}
          >
            SPREAD {formatPrice(data.spread)}
          </div>
          <div
            style={{
              width: '100%',
              height: 8,
              background: 'rgba(255,255,255,0.05)',
              borderRadius: 999,
              overflow: 'hidden',
              display: 'flex',
            }}
          >
            <div style={{ width: `${bidShare * 100}%`, background: 'var(--green)' }} />
            <div style={{ width: `${askShare * 100}%`, background: 'var(--red)' }} />
          </div>
          <div
            style={{
              color: 'var(--text-muted)',
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
            }}
          >
            {formatNumber(data.bid_ask_imbalance, 2)}
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          <div
            style={{
              textAlign: 'left',
              color: 'var(--red)',
              fontSize: 11,
              letterSpacing: '0.14em',
              marginBottom: 8,
            }}
          >
            ASKS
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {asks.map((level, index) => (
              <Row key={`ask-${index}`} side="ask" level={level} maxVolume={maxAskVolume} />
            ))}
          </div>
        </div>
      </div>

      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          marginTop: 12,
          paddingTop: 10,
          borderTop: '1px solid var(--border)',
          fontFamily: 'var(--font-mono)',
          fontSize: 12,
        }}
      >
        <div style={{ color: 'var(--green)' }}>BID VOL: {formatNumber(data.total_bid_volume)}</div>
        <div style={{ color: 'var(--red)' }}>ASK VOL: {formatNumber(data.total_ask_volume)}</div>
      </div>
    </section>
  )
}
