import { useEffect, useRef, useState } from 'react'
import * as d3 from 'd3'

function formatNumber(value, digits = 0) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return new Intl.NumberFormat('en-IN', {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  }).format(Number(value))
}

function labelForTimestamp(timestamp) {
  const date = new Date(timestamp)
  return date.toLocaleTimeString('en-IN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function buildHeatmapGrid(data) {
  if (Array.isArray(data?.matrix) && Array.isArray(data?.price_levels) && Array.isArray(data?.time_labels)) {
    return {
      priceLevels: data.price_levels.map((price) => Number(price)),
      timeLabels: data.time_labels,
      matrix: data.matrix,
      maxVolume: Number(data.max_volume ?? 0),
    }
  }

  const cells = Array.isArray(data?.cells) ? data.cells : []
  if (cells.length === 0) return null

  const timestamps = [...new Set(cells.map((cell) => cell.timestamp))].sort()
  const prices = [...new Set(cells.map((cell) => Number(cell.price_level)))].sort((a, b) => b - a)
  const lookup = new Map(
    cells.map((cell) => [`${Number(cell.price_level)}|${cell.timestamp}`, cell.total_volume]),
  )
  const matrix = prices.map((price) =>
    timestamps.map((timestamp) => lookup.get(`${price}|${timestamp}`) ?? 0),
  )

  return {
    priceLevels: prices,
    timeLabels: timestamps.map(labelForTimestamp),
    matrix,
    maxVolume: Math.max(...matrix.flat(), 0),
  }
}

export default function LiquidityHeatmap({ data, symbol }) {
  const ref = useRef(null)
  const [range, setRange] = useState('15m')
  const [tooltip, setTooltip] = useState(null)

  useEffect(() => {
    const host = ref.current
    if (!host) return

    const width = host.clientWidth || 640
    const height = host.clientHeight || 300
    const margin = { top: 16, right: 20, bottom: 30, left: 76 }

    d3.select(host).selectAll('*').remove()

    const svg = d3
      .select(host)
      .append('svg')
      .attr('width', width)
      .attr('height', height)

    const grid = buildHeatmapGrid(data)

    if (!grid) {
      const cols = 12
      const rows = 8
      const cellWidth = (width - margin.left - margin.right) / cols
      const cellHeight = (height - margin.top - margin.bottom) / rows
      const seeded = d3.randomLcg(symbol.length * 0.137 + 0.42)
      const placeholder = d3.range(rows * cols).map((index) => ({
        col: index % cols,
        row: Math.floor(index / cols),
        opacity: 0.05 + seeded() * 0.25,
      }))

      svg
        .append('g')
        .attr('transform', `translate(${margin.left},${margin.top})`)
        .selectAll('rect')
        .data(placeholder)
        .join('rect')
        .attr('x', (d) => d.col * cellWidth)
        .attr('y', (d) => d.row * cellHeight)
        .attr('width', cellWidth - 4)
        .attr('height', cellHeight - 4)
        .attr('rx', 3)
        .attr('fill', 'rgba(61, 124, 245, 1)')
        .attr('opacity', (d) => d.opacity)

      svg
        .append('text')
        .attr('x', width / 2)
        .attr('y', height / 2)
        .attr('text-anchor', 'middle')
        .attr('fill', 'var(--text-secondary)')
        .attr('font-size', 13)
        .attr('letter-spacing', '0.18em')
        .text('ACCUMULATING DATA...')

      return
    }

    const rows = grid.priceLevels.length
    const cols = grid.timeLabels.length
    const chartWidth = width - margin.left - margin.right
    const chartHeight = height - margin.top - margin.bottom
    const cellWidth = chartWidth / Math.max(cols, 1)
    const cellHeight = chartHeight / Math.max(rows, 1)
    const color = d3
      .scaleLinear()
      .domain([0, grid.maxVolume || 1])
      .range(['#1a1d27', '#3d7cf5'])

    const chart = svg
      .append('g')
      .attr('transform', `translate(${margin.left},${margin.top})`)

    const points = []
    grid.matrix.forEach((row, rowIndex) => {
      row.forEach((value, colIndex) => {
        points.push({
          value,
          rowIndex,
          colIndex,
          price: grid.priceLevels[rowIndex],
          label: grid.timeLabels[colIndex],
        })
      })
    })

    chart
      .selectAll('rect')
      .data(points)
      .join('rect')
      .attr('x', (d) => d.colIndex * cellWidth)
      .attr('y', (d) => d.rowIndex * cellHeight)
      .attr('width', Math.max(cellWidth - 2, 1))
      .attr('height', Math.max(cellHeight - 2, 1))
      .attr('rx', 2)
      .attr('fill', (d) => color(d.value))
      .attr('stroke', 'rgba(255,255,255,0.03)')
      .on('mousemove', (event, d) => {
        const bounds = host.getBoundingClientRect()
        setTooltip({
          x: event.clientX - bounds.left + 10,
          y: event.clientY - bounds.top - 10,
          price: d.price,
          time: d.label,
          volume: d.value,
        })
      })
      .on('mouseleave', () => setTooltip(null))

    const currentPrice = grid.priceLevels[Math.floor(grid.priceLevels.length / 2)] ?? null

    svg
      .append('g')
      .selectAll('text.y')
      .data(grid.priceLevels)
      .join('text')
      .attr('x', margin.left - 10)
      .attr('y', (_, index) => margin.top + index * cellHeight + cellHeight / 2 + 4)
      .attr('text-anchor', 'end')
      .attr('fill', (price) => (price === currentPrice ? 'var(--yellow)' : 'var(--text-secondary)'))
      .attr('font-size', 11)
      .attr('font-family', 'var(--font-mono)')
      .text((price) => `₹${formatNumber(price, 2)}`)

    svg
      .append('g')
      .selectAll('text.x')
      .data(grid.timeLabels)
      .join('text')
      .attr('x', (_, index) => margin.left + index * cellWidth + cellWidth / 2)
      .attr('y', height - 8)
      .attr('text-anchor', 'middle')
      .attr('fill', 'var(--text-muted)')
      .attr('font-size', 10)
      .text((label, index) => (index % Math.ceil(cols / 6) === 0 ? label.slice(0, 5) : ''))
  }, [data, symbol])

  const ranges = ['5m', '15m', '1h']

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
          LIQUIDITY HEATMAP
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          {ranges.map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => setRange(value)}
              style={{
                border: value === range ? '1px solid var(--blue)' : '1px solid var(--border)',
                background: value === range ? 'var(--blue-dim)' : 'transparent',
                color: value === range ? 'var(--text-primary)' : 'var(--text-secondary)',
                borderRadius: 4,
                padding: '4px 8px',
                fontSize: 11,
                cursor: 'pointer',
                fontFamily: 'var(--font-mono)',
              }}
            >
              {value}
            </button>
          ))}
        </div>
      </div>

      <div
        style={{
          position: 'relative',
          flex: 1,
          minHeight: 200,
          border: '1px solid rgba(255,255,255,0.04)',
          borderRadius: 6,
          background:
            'radial-gradient(circle at top, rgba(61,124,245,0.14), transparent 45%), var(--bg-card)',
          overflow: 'hidden',
        }}
      >
        <div ref={ref} style={{ width: '100%', height: '100%' }} />
        {tooltip ? (
          <div
            style={{
              position: 'absolute',
              left: tooltip.x,
              top: tooltip.y,
              pointerEvents: 'none',
              background: 'rgba(13,15,20,0.94)',
              border: '1px solid var(--border-bright)',
              borderRadius: 4,
              padding: '6px 8px',
              fontSize: 11,
              color: 'var(--text-primary)',
              boxShadow: '0 8px 20px rgba(0,0,0,0.35)',
            }}
          >
            <div>₹{formatNumber(tooltip.price, 2)}</div>
            <div>{tooltip.time}</div>
            <div>VOL {formatNumber(tooltip.volume)}</div>
          </div>
        ) : null}
      </div>
    </section>
  )
}
