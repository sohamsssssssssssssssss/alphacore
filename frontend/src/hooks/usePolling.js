import { useState, useEffect } from 'react'

export function usePolling(url, intervalMs = 5000) {
  const [data, setData] = useState(null)
  const [lastUpdate, setLastUpdate] = useState(null)

  useEffect(() => {
    if (!url) return
    let active = true
    const fetch_ = () =>
      fetch(url)
        .then((r) => {
          if (!r.ok) throw new Error(`Request failed: ${r.status}`)
          return r.json()
        })
        .then((d) => {
          if (!active) return
          setData(d)
          setLastUpdate(Date.now())
        })
        .catch(() => {})
    fetch_()
    const id = setInterval(fetch_, intervalMs)
    return () => {
      active = false
      clearInterval(id)
    }
  }, [url, intervalMs])

  return { data, lastUpdate }
}
