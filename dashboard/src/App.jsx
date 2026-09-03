import { useState, useEffect, useRef } from 'react'
import './App.css'

const ORCH_API = 'http://127.0.0.1:8002'
const ORCH_WS = 'ws://127.0.0.1:8002'
const GATEWAY_API = 'http://127.0.0.1:8001'
const TARGET_SYS_API = 'http://127.0.0.1:8003'

function App() {
  const [incidents, setIncidents] = useState([])
  const [selectedId, setSelectedId] = useState('')
  const [incidentState, setIncidentState] = useState(null)
  const [auditLogs, setAuditLogs] = useState([])
  
  const [wsConnected, setWsConnected] = useState(false)
  const [globalWsConnected, setGlobalWsConnected] = useState(false)
  const [reconnecting, setReconnecting] = useState(false)

  // Trigger form state
  const [triggerId, setTriggerId] = useState(`inc-p5-${Math.floor(Math.random() * 8999 + 1000)}`)
  const [faultType, setFaultType] = useState('memory_pressure')
  const [triggerDesc, setTriggerDesc] = useState('Critical memory leak on checkout service causing high memory pressure')
  const [triggerAction, setTriggerAction] = useState('restart_service')
  const [isSubmitting, setIsSubmitting] = useState(false)

  const terminalRef = useRef(null)

  // Auto-scroll terminal log
  useEffect(() => {
    if (terminalRef.current) {
      terminalRef.current.scrollTop = terminalRef.current.scrollHeight
    }
  }, [incidentState?.event_log])

  // 1. Initial REST fetch for incident list
  const fetchIncidents = async () => {
    try {
      const res = await fetch(`${ORCH_API}/incidents`)
      if (res.ok) {
        const data = await res.json()
        setIncidents(data)
        if (data.length > 0 && !selectedId) {
          setSelectedId(data[data.length - 1].incident_id)
        }
      }
    } catch (e) {
      console.warn('Failed to fetch incident list:', e)
    }
  }

  useEffect(() => {
    fetchIncidents()
  }, [])

  // 2. Global WebSocket connection for live incident list updates (/ws/incidents)
  useEffect(() => {
    let ws = null
    let timer = null

    const connectGlobal = () => {
      ws = new WebSocket(`${ORCH_WS}/ws/incidents`)

      ws.onopen = () => {
        setGlobalWsConnected(true)
        setReconnecting(false)
      }

      ws.onmessage = (evt) => {
        try {
          const msg = JSON.parse(evt.data)
          if (msg.event_type === 'init') {
            setIncidents(msg.incidents || [])
            if ((msg.incidents || []).length > 0 && !selectedId) {
              setSelectedId(msg.incidents[msg.incidents.length - 1].incident_id)
            }
          } else if (msg.event_type === 'incident_updated') {
            setIncidents((prev) => {
              const idx = prev.findIndex((i) => i.incident_id === msg.incident_id)
              if (idx >= 0) {
                const updated = [...prev]
                updated[idx] = { ...updated[idx], status: msg.status, updated_at: msg.updated_at }
                return updated
              } else {
                return [...prev, { incident_id: msg.incident_id, description: msg.description, status: msg.status }]
              }
            })
          }
        } catch (e) {
          console.error('Failed to parse global WS msg:', e)
        }
      }

      ws.onclose = () => {
        setGlobalWsConnected(false)
        setReconnecting(true)
        timer = setTimeout(connectGlobal, 2000)
      }

      ws.onerror = () => {
        setGlobalWsConnected(false)
        setReconnecting(true)
      }
    }

    connectGlobal()
    return () => {
      if (ws) ws.close()
      if (timer) clearTimeout(timer)
    }
  }, [])

  // 3. Single Incident WebSocket connection (/ws/incidents/{incident_id})
  useEffect(() => {
    if (!selectedId) {
      setIncidentState(null)
      return
    }

    let ws = null
    let timer = null

    // Fetch initial full state via REST
    const fetchSingleState = async () => {
      try {
        const res = await fetch(`${ORCH_API}/incidents/${selectedId}`)
        if (res.ok) {
          const data = await res.json()
          setIncidentState(data)
        }
      } catch (e) {
        console.warn('Single incident fetch failed:', e)
      }
    }
    fetchSingleState()

    const connectIncidentWs = () => {
      ws = new WebSocket(`${ORCH_WS}/ws/incidents/${selectedId}`)

      ws.onopen = () => {
        setWsConnected(true)
        setReconnecting(false)
      }

      ws.onmessage = (evt) => {
        try {
          const msg = JSON.parse(evt.data)
          if (msg.event_type === 'init' || msg.event_type === 'log_entry') {
            if (msg.state) {
              setIncidentState(msg.state)
            }
          }
        } catch (e) {
          console.error('Failed to parse single incident WS msg:', e)
        }
      }

      ws.onclose = () => {
        setWsConnected(false)
        setReconnecting(true)
        timer = setTimeout(connectIncidentWs, 2000)
      }

      ws.onerror = () => {
        setWsConnected(false)
        setReconnecting(true)
      }
    }

    connectIncidentWs()
    return () => {
      if (ws) ws.close()
      if (timer) clearTimeout(timer)
    }
  }, [selectedId])

  // 4. Polling Policy Gateway Audit Log (/audit-log?limit=50)
  useEffect(() => {
    const fetchAuditLog = async () => {
      try {
        const res = await fetch(`${GATEWAY_API}/audit-log?limit=50`)
        if (res.ok) {
          const data = await res.json()
          setAuditLogs(data)
        }
      } catch (e) {
        console.warn('Audit log fetch failed:', e)
      }
    }

    fetchAuditLog()
    const interval = setInterval(fetchAuditLog, 3000)
    return () => clearInterval(interval)
  }, [])

  // Handler: Trigger new incident
  const handleTriggerIncident = async (e) => {
    e.preventDefault()
    if (!triggerId || !triggerDesc || isSubmitting) return

    setIsSubmitting(true)
    try {
      // 1. Inject fault into target system API (port 8003)
      try {
        await fetch(`${TARGET_SYS_API}/faults/${faultType}?incident_id=${triggerId}`, {
          method: 'POST'
        })
      } catch (fErr) {
        console.warn('Target system fault injection API call warning:', fErr)
      }

      // 2. Trigger incident pipeline via Orchestrator API (port 8002)
      const res = await fetch(`${ORCH_API}/incidents`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          incident_id: triggerId,
          description: triggerDesc,
          desired_action_type: triggerAction
        })
      })

      if (res.ok) {
        const data = await res.json()
        setSelectedId(data.incident_id)
        setIncidentState(data)
        setTriggerId(`inc-p5-${Math.floor(Math.random() * 8999 + 1000)}`)
      } else {
        const err = await res.json()
        alert(`Error triggering incident: ${err.detail || 'Failed'}`)
      }
    } catch (err) {
      alert(`Network error triggering incident: ${err.message}`)
    } finally {
      setIsSubmitting(false)
    }
  }

  // Handler: Approve Action via POST /incidents/{incident_id}/confirm
  const handleConfirmApproval = async () => {
    if (!selectedId || !incidentState || incidentState.status !== 'awaiting_approval') return

    try {
      const res = await fetch(`${ORCH_API}/incidents/${selectedId}/confirm`, {
        method: 'POST'
      })

      if (res.ok) {
        const data = await res.json()
        setIncidentState(data)
      } else {
        const err = await res.json()
        alert(`Approval confirmation failed: ${err.detail || 'Error'}`)
      }
    } catch (e) {
      alert(`Network error on approval: ${e.message}`)
    }
  }

  // Helper computations
  const status = incidentState?.status || 'idle'
  const logs = incidentState?.event_log || []

  // Fast-Path Detection
  const isFastPath = logs.some((l) => l.includes('[FAST PATH TRIGGERED]'))
  const isFullPath = logs.some((l) => l.includes('[FULL REASONING PATH]'))

  // Agent States derived 100% from backend state
  const getAgentState = (agentName) => {
    if (!incidentState) return 'idle'

    if (agentName === 'Orchestrator') {
      if (['detecting', 'remediating', 'verifying', 'communicating'].includes(status)) return 'active'
      if (status === 'awaiting_approval') return 'awaiting'
      if (status === 'done') return 'done'
      if (status === 'failed') return 'failed'
      return 'idle'
    }

    if (agentName === 'Detective') {
      if (isFastPath) return 'skipped'
      if (status === 'detecting') return 'active'
      if (incidentState.diagnosis) return 'done'
      return 'idle'
    }

    if (agentName === 'Remediator') {
      if (isFastPath) return 'skipped'
      if (status === 'remediating' && !incidentState.proposed_action) return 'active'
      if (incidentState.proposed_action) return 'done'
      return 'idle'
    }

    if (agentName === 'Verifier') {
      if (status === 'verifying') return 'active'
      if (['communicating', 'done'].includes(status)) return 'done'
      if (status === 'failed' && incidentState.proposed_action) return 'failed'
      return 'idle'
    }

    if (agentName === 'Communicator') {
      if (status === 'communicating') return 'active'
      if (incidentState.postmortem) return 'done'
      return 'idle'
    }

    return 'idle'
  }

  return (
    <div className="dashboard-container">
      {/* Header */}
      <header className="header">
        <div className="header-title">
          <h1>AEGIS // MISSION CONTROL</h1>
          <span className="badge-tag">PHASE 5 LIVE COCKPIT</span>
        </div>
        <div className="status-indicators">
          <div className="status-item">
            <div className={`dot ${globalWsConnected && wsConnected ? 'connected' : 'disconnected'}`}></div>
            <span>WebSocket: {globalWsConnected && wsConnected ? 'LIVE CONNECTED' : 'RECONNECTING...'}</span>
          </div>
          <div className="status-item">
            <div className="dot connected"></div>
            <span>Policy Gateway: ONLINE</span>
          </div>
        </div>
      </header>

      {/* Reconnection Alert Banner */}
      {reconnecting && (
        <div className="reconnect-banner">
          ⚠️ WebSocket connection lost. Reconnecting to Aegis Orchestrator real-time stream...
        </div>
      )}

      {/* Control & Trigger Bar */}
      <div className="control-bar">
        {/* Trigger Panel */}
        <div className="card">
          <div className="card-title">⚡ Trigger New Incident</div>
          <form className="trigger-form" onSubmit={handleTriggerIncident}>
            <div className="input-group">
              <label>Incident ID</label>
              <input
                type="text"
                value={triggerId}
                onChange={(e) => setTriggerId(e.target.value)}
                required
              />
            </div>
            <div className="input-group">
              <label>Fault Type Preset</label>
              <select
                value={faultType}
                onChange={(e) => {
                  const val = e.target.value
                  setFaultType(val)
                  if (val === 'memory_pressure') setTriggerDesc('Critical memory leak on checkout service causing high memory pressure')
                  else if (val === 'cpu_pressure') setTriggerDesc('CPU exhaustion and elevated response latency on worker node')
                  else if (val === 'latency_injection') setTriggerDesc('High response time latency injection on payment gateway')
                  else if (val === 'packet_loss') setTriggerDesc('Network packet loss causing high drop rate and connectivity failure')
                  else if (val === 'pod_failure') setTriggerDesc('Instance registered in service mesh but not serving traffic')
                }}
              >
                <option value="memory_pressure">Memory Pressure (Heap leak / 95% memory)</option>
                <option value="cpu_pressure">CPU Pressure (Compute exhaustion / 90%+ CPU)</option>
                <option value="latency_injection">Latency Injection (1000-3000ms response delay)</option>
                <option value="packet_loss">Packet Loss (Network partition / high error rate)</option>
                <option value="pod_failure">Pod Failure (Registered but not serving traffic)</option>
              </select>
            </div>
            <div className="input-group">
              <label>Fault Description</label>
              <input
                type="text"
                value={triggerDesc}
                onChange={(e) => setTriggerDesc(e.target.value)}
                required
              />
            </div>
            <div className="input-group">
              <label>Desired Action Type</label>
              <select value={triggerAction} onChange={(e) => setTriggerAction(e.target.value)}>
                <option value="restart_service">restart_service (Risky / Approval Needed)</option>
                <option value="throttle_process">throttle_process (Risky / Approval Needed)</option>
                <option value="trigger_circuit_breaker">trigger_circuit_breaker (Risky / Approval Needed)</option>
                <option value="reroute_traffic">reroute_traffic (Risky / Approval Needed)</option>
                <option value="replace_instance">replace_instance (Risky / Approval Needed)</option>
                <option value="rollback_deploy">rollback_deploy (Risky / Approval Needed)</option>
                <option value="read_metrics">read_metrics (Auto-Approved Readonly)</option>
                <option value="read_logs">read_logs (Auto-Approved Readonly)</option>
              </select>
            </div>
            <button type="submit" className="btn-primary" disabled={isSubmitting}>
              {isSubmitting ? 'Dispatching...' : '⚡ Trigger Incident'}
            </button>
          </form>
        </div>

        {/* Incident List Switcher */}
        <div className="card">
          <div className="card-title">
            <span>📋 Active Incidents ({incidents.length})</span>
            <span style={{ fontSize: '0.8rem', color: '#9ca3af' }}>Select to inspect live trace</span>
          </div>
          <div className="incident-list-container">
            {incidents.length === 0 ? (
              <div style={{ color: '#9ca3af', fontSize: '0.85rem', padding: '10px' }}>
                No incidents recorded yet. Trigger one above!
              </div>
            ) : (
              incidents.map((inc) => (
                <div
                  key={inc.incident_id}
                  className={`incident-item ${selectedId === inc.incident_id ? 'selected' : ''}`}
                  onClick={() => setSelectedId(inc.incident_id)}
                >
                  <div className="incident-item-info">
                    <span className="incident-id">{inc.incident_id}</span>
                    <span className="incident-desc">{inc.description}</span>
                  </div>
                  <span className={`status-pill ${inc.status}`}>{inc.status}</span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* Selected Incident Detail Area */}
      {selectedId && (
        <div className="card" style={{ border: '1px solid #374151' }}>
          <div className="card-title" style={{ borderBottom: '1px solid #1f2937', pb: '10px' }}>
            <div>
              <span>Incident Focus: </span>
              <span style={{ color: '#60a5fa', fontFamily: 'monospace' }}>{selectedId}</span>
            </div>
            {isFastPath && (
              <div className="path-badge fast-path">⚡ Memory Recall Fast Path</div>
            )}
            {isFullPath && (
              <div className="path-badge full-path">🧠 Full Reasoning Path</div>
            )}
          </div>

          <div className="main-grid" style={{ marginTop: '16px' }}>
            {/* Left Column: Agent State Visualizer & Approval Card */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div className="agents-panel">
                {/* Orchestrator Node */}
                <div className={`agent-card ${getAgentState('Orchestrator')}`}>
                  <div className="agent-header">
                    <span className="agent-name">⚙️ Orchestrator</span>
                    <span className={`status-pill ${status}`}>{status}</span>
                  </div>
                  <div className="agent-role">Pipeline Coordinator & Memory Recaller</div>
                </div>

                {/* Detective Agent Node */}
                <div className={`agent-card ${getAgentState('Detective')}`}>
                  <div className="agent-header">
                    <span className="agent-name">🔍 Detective Agent</span>
                    <span className={`status-pill ${getAgentState('Detective')}`}>{getAgentState('Detective')}</span>
                  </div>
                  <div className="agent-role">Telemetry Analyzer & Root Cause Diagnoser</div>
                  {incidentState?.diagnosis && (
                    <div className="agent-detail">
                      Root Cause: {incidentState.diagnosis.root_cause} (Conf: {incidentState.diagnosis.confidence})
                    </div>
                  )}
                  {isFastPath && (
                    <div className="agent-detail" style={{ color: '#c084fc' }}>
                      ⚡ SKIPPED — Experience memory recalled from vector DB
                    </div>
                  )}
                </div>

                {/* Remediator Agent Node */}
                <div className={`agent-card ${getAgentState('Remediator')}`}>
                  <div className="agent-header">
                    <span className="agent-name">🛠️ Remediator Agent</span>
                    <span className={`status-pill ${getAgentState('Remediator')}`}>{getAgentState('Remediator')}</span>
                  </div>
                  <div className="agent-role">Remediation Action Planner</div>
                  {incidentState?.proposed_action && (
                    <div className="agent-detail">
                      Proposed: {incidentState.proposed_action.action_type} → {incidentState.proposed_action.target}
                    </div>
                  )}
                  {isFastPath && (
                    <div className="agent-detail" style={{ color: '#c084fc' }}>
                      ⚡ SKIPPED — Experience memory recalled from vector DB
                    </div>
                  )}
                </div>

                {/* Verifier Agent Node */}
                <div className={`agent-card ${getAgentState('Verifier')}`}>
                  <div className="agent-header">
                    <span className="agent-name">🧪 Verifier Agent</span>
                    <span className={`status-pill ${getAgentState('Verifier')}`}>{getAgentState('Verifier')}</span>
                  </div>
                  <div className="agent-role">Telemetry Delta & Local Sanity Checker</div>
                </div>

                {/* Communicator Agent Node */}
                <div className={`agent-card ${getAgentState('Communicator')}`}>
                  <div className="agent-header">
                    <span className="agent-name">📝 Communicator Agent</span>
                    <span className={`status-pill ${getAgentState('Communicator')}`}>{getAgentState('Communicator')}</span>
                  </div>
                  <div className="agent-role">Postmortem Report Generator</div>
                </div>
              </div>

              {/* Approval Card (Shown when awaiting_approval) */}
              {status === 'awaiting_approval' && (
                <div className="approval-card">
                  <div className="approval-header">
                    ⚠️ ACTION REQUIRES HUMAN APPROVAL
                  </div>
                  <div className="approval-body">
                    <div className="approval-item">
                      <span className="approval-label">Action Type:</span>
                      <span className="approval-val">{incidentState?.proposed_action?.action_type}</span>
                    </div>
                    <div className="approval-item">
                      <span className="approval-label">Target Service:</span>
                      <span className="approval-val">{incidentState?.proposed_action?.target}</span>
                    </div>
                    <div className="approval-item">
                      <span className="approval-label">Policy Rule:</span>
                      <span className="approval-val">{incidentState?.policy_verdict?.deciding_rule}</span>
                    </div>
                    <div className="approval-item">
                      <span className="approval-label">Approval Token:</span>
                      <span className="approval-val">{incidentState?.approval_token}</span>
                    </div>
                  </div>
                  <button className="btn-approve" onClick={handleConfirmApproval}>
                    ✅ APPROVE & EXECUTE REMEDIATION
                  </button>
                </div>
              )}
            </div>

            {/* Right Column: Live Reasoning Trace & Postmortem */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div className="card-title">📡 Live WebSocket Reasoning Trace</div>
              <div className="terminal-container" ref={terminalRef}>
                {logs.length === 0 ? (
                  <div style={{ color: '#64748b' }}>Waiting for reasoning trace logs...</div>
                ) : (
                  logs.map((log, idx) => {
                    let className = 'terminal-line'
                    if (log.includes('[FAST PATH]')) className += ' fast-path-log'
                    else if (log.includes('requires human approval') || log.includes('awaiting_approval')) className += ' approval-log'
                    else if (log.includes('successfully resolved') || log.includes('exit_code=0')) className += ' success-log'
                    else if (log.includes('failed') || log.includes('error')) className += ' error-log'

                    return (
                      <div key={idx} className={className}>
                        {log}
                      </div>
                    )
                  })
                )}
              </div>

              {/* Postmortem Report */}
              {incidentState?.postmortem && (
                <div>
                  <div className="card-title" style={{ color: '#34d399' }}>📄 Incident Postmortem Report</div>
                  <div className="postmortem-container">
                    {incidentState.postmortem}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Audit Log Panel */}
      <div className="card">
        <div className="card-title">
          <span>🛡️ Policy Gateway Audit Log (GET /audit-log)</span>
          <span style={{ fontSize: '0.8rem', color: '#9ca3af' }}>Polling every 3s</span>
        </div>
        <div className="audit-table-wrapper">
          <table className="audit-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Timestamp</th>
                <th>Action Type</th>
                <th>Verdict</th>
                <th>Deciding Rule</th>
                <th>Token</th>
              </tr>
            </thead>
            <tbody>
              {auditLogs.length === 0 ? (
                <tr>
                  <td colSpan="6" style={{ textAlign: 'center', color: '#9ca3af' }}>No audit log entries found</td>
                </tr>
              ) : (
                auditLogs.map((row) => (
                  <tr key={row.id}>
                    <td>#{row.id}</td>
                    <td>{row.timestamp}</td>
                    <td style={{ color: '#60a5fa', fontWeight: 'bold' }}>{row.action_type}</td>
                    <td>
                      <span className={`verdict-tag ${row.verdict}`}>
                        {row.verdict}
                      </span>
                    </td>
                    <td>{row.deciding_rule}</td>
                    <td style={{ fontSize: '0.75rem', color: '#9ca3af' }}>{row.token || '-'}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

export default App
