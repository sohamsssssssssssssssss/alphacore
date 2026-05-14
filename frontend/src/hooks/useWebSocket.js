import { useState, useEffect, useRef } from 'react'

export function useWebSocket(symbol) {
  const [data, setData] = useState(null)
  const [connected, setConnected] = useState(false)
  const [lastUpdate, setLastUpdate] = useState(null)
  const ws = useRef(null)

  useEffect(() => {
    if (!symbol) return
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const url =
      window.location.port === '5173'
        ? `${protocol}://localhost:8000/ws/orderbook/${symbol}`
        : `${protocol}://${window.location.host}/ws/orderbook/${symbol}`

    ws.current = new WebSocket(url)
    ws.current.onopen = () => setConnected(true)
    ws.current.onclose = () => setConnected(false)
    ws.current.onerror = () => setConnected(false)
    ws.current.onmessage = (e) => {
      try {
        setData(JSON.parse(e.data))
        setLastUpdate(Date.now())
      } catch {
        // Ignore malformed frames.
      }
    }
    return () => ws.current?.close()
  }, [symbol])

  return { data, connected, lastUpdate }
}
