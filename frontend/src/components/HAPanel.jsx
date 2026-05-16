import React from 'react'
import { usePolling } from '../hooks/usePolling'

export default function HAPanel() {
  const { data: status } = usePolling('/api/ha/status', 5000)
  const { data: journal } = usePolling('/api/ha/journal?limit=20', 3000)

  return (
    <div className="panel ha-panel">
      <div className="panel-header">
        <div className="panel-title">
          <span className="icon">🛡️</span>
          HIGH AVAILABILITY & JOURNAL
        </div>
        {status && (
          <div className="status-tag success">
            SEQ: {status.sequence_numbers?.last_spoof_seq} | EVENTS: {status.journal_events}
          </div>
        )}
      </div>

      <div className="panel-body" style={{ display: 'grid', gridTemplateColumns: '300px 1fr', gap: '1rem', height: '100%' }}>
        <div className="ha-status-col" style={{ borderRight: '1px solid var(--border)', paddingRight: '1rem' }}>
          <div className="metric-group">
            <div className="metric-label">RECOVERY STATUS</div>
            <div className={`metric-value ${status?.recovery_summary?.recovered ? 'text-success' : 'text-warning'}`}>
              {status?.recovery_summary?.recovered ? 'FULLY RECOVERED' : 'INITIALIZING...'}
            </div>
          </div>
          <div className="metric-group" style={{ marginTop: '1rem' }}>
            <div className="metric-label">LAST EVENT AT</div>
            <div className="metric-value small">{status?.last_event_at || 'N/A'}</div>
          </div>
          <div className="metric-group" style={{ marginTop: '1rem' }}>
            <div className="metric-label">SEQUENCE NUMBERS</div>
            <div className="mini-stats">
              <div>SPOOF: {status?.sequence_numbers?.last_spoof_seq}</div>
              <div>ICEBERG: {status?.sequence_numbers?.last_iceberg_seq}</div>
              <div>SIGNAL: {status?.sequence_numbers?.last_signal_seq}</div>
            </div>
          </div>
        </div>

        <div className="journal-col" style={{ overflowY: 'auto', maxHeight: '200px' }}>
          <div className="metric-label" style={{ marginBottom: '0.5rem', position: 'sticky', top: 0, background: 'var(--bg-panel)' }}>
            EVENT JOURNAL (LAST 20)
          </div>
          <div className="journal-feed">
            {journal?.map((entry, i) => (
              <div key={entry.seq || i} className="journal-entry" style={{ 
                fontSize: '0.75rem', 
                padding: '4px 0', 
                borderBottom: '1px solid var(--bg-base)',
                display: 'flex',
                gap: '8px'
              }}>
                <span style={{ color: 'var(--text-dim)', width: '30px' }}>#{entry.seq}</span>
                <span style={{ color: 'var(--primary)', width: '80px' }}>[{entry.type.toUpperCase()}]</span>
                <span style={{ color: 'var(--text-main)', flex: 1 }}>{entry.symbol}: {JSON.stringify(entry.data)}</span>
              </div>
            ))}
            {(!journal || journal.length === 0) && (
              <div className="text-dim small">No journal entries available.</div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
