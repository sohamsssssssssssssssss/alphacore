import { useMemo, useRef, useState } from 'react'

const TAB_FIX = 'FIX 4.4'
const TAB_WS = 'Binary WS'

const MSG_TYPE_LABEL = {
  1: 'ORDER_BOOK_SNAPSHOT',
  2: 'TRADE_SIGNAL',
  3: 'DETECTION_EVENT',
  4: 'HEARTBEAT',
  5: 'REGULATORY_ALERT',
}

function decodeFrame(buffer) {
  const view = new DataView(buffer)
  const magic = view.getUint16(0)
  const version = view.getUint8(2)
  const msgType = view.getUint8(3)
  const length = view.getUint32(4)
  const payloadBytes = new Uint8Array(buffer.slice(8, 8 + length))
  const text = new TextDecoder().decode(payloadBytes)
  return {
    magic,
    version,
    msgType,
    payload: text ? JSON.parse(text) : {},
  }
}

function createFrame(msgType, payload = {}) {
  const payloadBytes = new TextEncoder().encode(JSON.stringify(payload))
  const frame = new ArrayBuffer(8 + payloadBytes.length)
  const view = new DataView(frame)
  view.setUint16(0, 0xac01)
  view.setUint8(2, 1)
  view.setUint8(3, msgType)
  view.setUint32(4, payloadBytes.length)
  new Uint8Array(frame, 8).set(payloadBytes)
  return frame
}

export default function ProtocolPanel() {
  const [tab, setTab] = useState(TAB_FIX)
  const [fixRaw, setFixRaw] = useState('8=FIX.4.4|9=12|35=W|49=ALPHACORE|56=EXCHANGE|10=000|')
  const [fixParsed, setFixParsed] = useState(null)
  const [fixOrderResp, setFixOrderResp] = useState(null)
  const [sessionState, setSessionState] = useState('DISCONNECTED')

  const [wsConnected, setWsConnected] = useState(false)
  const [frames, setFrames] = useState([])
  const [frameCount, setFrameCount] = useState(0)
  const [lastHeartbeat, setLastHeartbeat] = useState(null)
  const wsRef = useRef(null)

  const sortedFields = useMemo(() => {
    if (!fixParsed?.fields) return []
    return Object.entries(fixParsed.fields).sort((a, b) => Number(a[0]) - Number(b[0]))
  }, [fixParsed])

  const refreshSession = async () => {
    const r = await fetch('/api/fix/session')
    if (!r.ok) return
    const d = await r.json()
    setSessionState(d.state)
  }

  const parseFix = async () => {
    const r = await fetch('/api/fix/parse', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ raw: fixRaw }),
    })
    const d = await r.json()
    setFixParsed(d)
    refreshSession()
  }

  const sendTestOrder = async () => {
    const r = await fetch('/api/fix/order', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: 'RELIANCE', side: 'BUY', qty: 100, price: 2500.0 }),
    })
    const d = await r.json()
    setFixOrderResp(d)
    refreshSession()
  }

  const connectBinary = () => {
    if (wsRef.current) return
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${window.location.host}/ws/binary`)
    ws.binaryType = 'arraybuffer'
    ws.onopen = () => setWsConnected(true)
    ws.onclose = () => {
      setWsConnected(false)
      wsRef.current = null
    }
    ws.onmessage = (evt) => {
      if (!(evt.data instanceof ArrayBuffer)) return
      const decoded = decodeFrame(evt.data)
      if (decoded.msgType === 4) setLastHeartbeat(new Date().toISOString())
      setFrameCount((n) => n + 1)
      setFrames((prev) => [{ ...decoded, receivedAt: new Date().toISOString() }, ...prev].slice(0, 25))
    }
    wsRef.current = ws
  }

  const disconnectBinary = () => {
    if (wsRef.current) wsRef.current.close()
    wsRef.current = null
    setWsConnected(false)
  }

  const requestSnapshot = (msgType) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return
    wsRef.current.send(createFrame(msgType, { symbol: 'RELIANCE' }))
  }

  return (
    <section style={{ height: '100%', overflow: 'auto', padding: 12 }}>
      <div style={{ fontSize: 11, letterSpacing: '0.14em', color: 'var(--purple)', marginBottom: 10 }}>
        PROTOCOL DEPTH
      </div>

      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        {[TAB_FIX, TAB_WS].map((name) => (
          <button
            key={name}
            onClick={() => setTab(name)}
            style={{
              border: '1px solid var(--border-bright)',
              background: tab === name ? 'var(--blue-dim)' : 'var(--bg-card)',
              color: 'var(--text-primary)',
              borderRadius: 6,
              padding: '6px 10px',
              fontFamily: 'var(--font-mono)',
              cursor: 'pointer',
            }}
          >
            {name}
          </button>
        ))}
      </div>

      {tab === TAB_FIX ? (
        <div style={{ display: 'grid', gap: 10 }}>
          <div style={{ color: 'var(--text-secondary)' }}>
            Session: <span style={{ color: sessionState === 'ACTIVE' ? 'var(--green)' : 'var(--red)' }}>{sessionState}</span>
          </div>
          <textarea
            value={fixRaw}
            onChange={(e) => setFixRaw(e.target.value)}
            style={{ minHeight: 92, background: 'var(--bg-card)', border: '1px solid var(--border)', color: 'var(--text-primary)', padding: 8, fontFamily: 'var(--font-mono)' }}
          />
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={parseFix} style={{ border: '1px solid var(--border-bright)', background: 'var(--bg-card)', color: 'var(--text-primary)', borderRadius: 6, padding: '6px 10px', cursor: 'pointer' }}>Parse</button>
            <button onClick={sendTestOrder} style={{ border: '1px solid var(--border-bright)', background: 'var(--bg-card)', color: 'var(--text-primary)', borderRadius: 6, padding: '6px 10px', cursor: 'pointer' }}>Send Test Order</button>
            <button onClick={refreshSession} style={{ border: '1px solid var(--border-bright)', background: 'var(--bg-card)', color: 'var(--text-primary)', borderRadius: 6, padding: '6px 10px', cursor: 'pointer' }}>Refresh Session</button>
          </div>

          {sortedFields.length > 0 && (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead><tr style={{ textAlign: 'left', color: 'var(--text-secondary)' }}><th>Tag</th><th>Value</th></tr></thead>
              <tbody>
                {sortedFields.map(([tag, value]) => (
                  <tr key={tag}><td>{tag}</td><td>{String(value)}</td></tr>
                ))}
              </tbody>
            </table>
          )}

          {fixOrderResp && (
            <pre style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 6, padding: 8, overflow: 'auto' }}>{JSON.stringify(fixOrderResp, null, 2)}</pre>
          )}
        </div>
      ) : (
        <div style={{ display: 'grid', gap: 10 }}>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={connectBinary} style={{ border: '1px solid var(--border-bright)', background: 'var(--bg-card)', color: 'var(--text-primary)', borderRadius: 6, padding: '6px 10px', cursor: 'pointer' }}>Connect</button>
            <button onClick={disconnectBinary} style={{ border: '1px solid var(--border-bright)', background: 'var(--bg-card)', color: 'var(--text-primary)', borderRadius: 6, padding: '6px 10px', cursor: 'pointer' }}>Disconnect</button>
            <button onClick={() => requestSnapshot(1)} style={{ border: '1px solid var(--border-bright)', background: 'var(--bg-card)', color: 'var(--text-primary)', borderRadius: 6, padding: '6px 10px', cursor: 'pointer' }}>Request OB</button>
            <button onClick={() => requestSnapshot(2)} style={{ border: '1px solid var(--border-bright)', background: 'var(--bg-card)', color: 'var(--text-primary)', borderRadius: 6, padding: '6px 10px', cursor: 'pointer' }}>Request Signals</button>
            <button onClick={() => requestSnapshot(3)} style={{ border: '1px solid var(--border-bright)', background: 'var(--bg-card)', color: 'var(--text-primary)', borderRadius: 6, padding: '6px 10px', cursor: 'pointer' }}>Request Detections</button>
          </div>
          <div style={{ color: wsConnected ? 'var(--green)' : 'var(--red)' }}>
            {wsConnected ? 'Connected' : 'Disconnected'} | Frames: {frameCount} | Last heartbeat: {lastHeartbeat || '—'}
          </div>
          <div style={{ display: 'grid', gap: 6 }}>
            {frames.map((f, idx) => (
              <div key={`${f.receivedAt}-${idx}`} style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 6, padding: 8 }}>
                <div style={{ color: 'var(--text-secondary)', marginBottom: 4 }}>{MSG_TYPE_LABEL[f.msgType] || `TYPE_${f.msgType}`} • {f.receivedAt}</div>
                <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{JSON.stringify(f.payload, null, 2)}</pre>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}
