import { useState } from 'react'
import TopBar from './components/TopBar'
import OrderBook from './components/OrderBook'
import FlowGauge from './components/FlowGauge'
import IcebergPanel from './components/IcebergPanel'
import SpoofAlert from './components/SpoofAlert'
import LiquidityHeatmap from './components/LiquidityHeatmap'
import NarrativeBanner from './components/NarrativeBanner'
import SignalPanel from './components/SignalPanel'
import RegulatoryPanel from './components/RegulatoryPanel'
import ProtocolPanel from './components/ProtocolPanel'
import { useWebSocket } from './hooks/useWebSocket'
import { usePolling } from './hooks/usePolling'

function toOrderBookSnapshot(payload) {
  if (!payload) return null
  if (payload.symbol && payload.bids && payload.asks) {
    return {
      ...payload,
      stale: payload.stale ?? false,
    }
  }
  return null
}

export default function App() {
  const [activeSymbol, setActiveSymbol] = useState('RELIANCE')

  const { data: wsPayload, connected, lastUpdate: wsLastUpdate } = useWebSocket(activeSymbol)
  const { data: polledOrderBook, lastUpdate: pollLastUpdate } = usePolling(
    `/api/orderbook/${activeSymbol}`,
    2000,
  )
  const { data: flowData } = usePolling(`/api/flow/${activeSymbol}`, 3000)
  const { data: icebergData } = usePolling('/api/detections/icebergs', 5000)
  const { data: spoofData } = usePolling('/api/detections/spoof', 5000)
  const { data: narrativeData } = usePolling('/api/narrative/current', 10000)
  const { data: heatmapData } = usePolling(`/api/heatmap/${activeSymbol}`, 10000)

  const websocketOrderBook = toOrderBookSnapshot(wsPayload)
  const effectiveOrderBook = websocketOrderBook || polledOrderBook
  const lastUpdate = wsLastUpdate || pollLastUpdate

  return (
    <div
      style={{
        minHeight: '100vh',
        background:
          'radial-gradient(circle at top left, rgba(0,211,149,0.08), transparent 22%), radial-gradient(circle at top right, rgba(61,124,245,0.12), transparent 28%), var(--bg-base)',
      }}
    >
      <TopBar
        activeSymbol={activeSymbol}
        onSymbolChange={setActiveSymbol}
        wsConnected={connected}
        lastUpdate={lastUpdate}
        narrative={narrativeData?.narrative}
      />

      <main
        style={{
          height: 'calc(100vh - 52px - 44px)',
          marginTop: 52,
          marginBottom: 44,
          display: 'grid',
          gridTemplateColumns: '320px 1fr 280px',
          gridTemplateRows: '1fr 1fr minmax(200px, 28vh) minmax(220px, 28vh) minmax(240px, 34vh)',
          gridTemplateAreas: `
            "orderbook heatmap flow"
            "icebergs heatmap spoof"
            "signals signals signals"
            "regulatory regulatory regulatory"
            "protocol protocol protocol"
          `,
          gap: 1,
          background: 'var(--border)',
        }}
      >
        <div style={{ gridArea: 'orderbook', background: 'var(--bg-panel)', minHeight: 0 }}>
          <OrderBook data={effectiveOrderBook} />
        </div>
        <div style={{ gridArea: 'heatmap', background: 'var(--bg-panel)', minHeight: 0 }}>
          <LiquidityHeatmap data={heatmapData} symbol={activeSymbol} />
        </div>
        <div style={{ gridArea: 'flow', background: 'var(--bg-panel)', minHeight: 0 }}>
          <FlowGauge data={flowData} />
        </div>
        <div style={{ gridArea: 'icebergs', background: 'var(--bg-panel)', minHeight: 0 }}>
          <IcebergPanel data={icebergData} />
        </div>
        <div style={{ gridArea: 'spoof', background: 'var(--bg-panel)', minHeight: 0 }}>
          <SpoofAlert data={spoofData} />
        </div>
        <div style={{ gridArea: 'signals', background: 'var(--bg-panel)', minHeight: 0 }}>
          <SignalPanel />
        </div>
        <div style={{ gridArea: 'regulatory', background: 'var(--bg-panel)', minHeight: 0 }}>
          <RegulatoryPanel />
        </div>
        <div style={{ gridArea: 'protocol', background: 'var(--bg-panel)', minHeight: 0 }}>
          <ProtocolPanel />
        </div>
      </main>

      <div style={{ position: 'fixed', left: 0, right: 0, bottom: 0, zIndex: 20 }}>
        <NarrativeBanner data={narrativeData} />
      </div>
    </div>
  )
}
