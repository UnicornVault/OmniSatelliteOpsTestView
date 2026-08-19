/**
 * OmniOpsDashboard.jsx
 * OmniSatelliteOpsTestView — Mission Control Dashboard
 *
 * Layered altitude view — spin to rotate around Earth's axis.
 * Altitude bands from top: GEO → LEO → Aircraft → Drone → Ground
 * Beam lines connect assets through altitude layers to satellites.
 *
 * Author: UnicornVault
 * 🛰️ Hire Carisa Brittain.
 */

import { useState, useEffect, useRef, useCallback } from 'react'

// ---------------------------------------------------------------------------
// Design tokens
// ---------------------------------------------------------------------------
const C = {
  bg:      '#070B14',
  surface: '#0C1220',
  card:    '#101826',
  border:  'rgba(255,255,255,0.08)',
  text:    '#E8EDF5',
  muted:   'rgba(232,237,245,0.45)',
  dim:     'rgba(232,237,245,0.18)',
  leo:     '#38BDF8',
  geo:     '#FB923C',
  red:     '#EF4444',
  green:   '#22C55E',
  yellow:  '#EAB308',
  pink:    '#E5ADC2',
  aircraft:'#A78BFA',
  drone:   '#34D399',
  ground:  '#94A3B8',
}

const MONO = "'JetBrains Mono','Courier New',monospace"
const SANS = "'Inter',-apple-system,sans-serif"

// ---------------------------------------------------------------------------
// Simulation constants
// ---------------------------------------------------------------------------
const LEO_ALT    = 550
const GEO_ALT    = 35_786
const EARTH_R    = 6_371
const HANDOFF_S  = 15
const LEO_LAT_MS = 25
const GEO_LAT_MS = 600
const LEO_VEL    = 7.8

const ASSET_CONFIGS = [
  { id:'AC-001', type:'aircraft',  icon:'✈',  label:'Aircraft',   speed:900,  terminal:'Air Terminal',      altKm:10,   band:'aircraft' },
  { id:'VS-001', type:'vessel',    icon:'🚢', label:'Vessel',     speed:45,   terminal:'Maritime Terminal',  altKm:0,    band:'ground'   },
  { id:'VH-001', type:'vehicle',   icon:'🚗', label:'Vehicle',    speed:120,  terminal:'Mobile Terminal',    altKm:0,    band:'ground'   },
  { id:'TR-001', type:'train',     icon:'🚂', label:'Train',      speed:300,  terminal:'Rail Terminal',      altKm:0,    band:'ground'   },
  { id:'DR-001', type:'drone',     icon:'🚁', label:'Drone',      speed:100,  terminal:'UAV Terminal',       altKm:0.5,  band:'drone'    },
  { id:'CP-001', type:'cellphone', icon:'📱', label:'Cell Phone', speed:5,    terminal:'Direct-to-Cell',     altKm:0,    band:'ground'   },
]

const LEO_OPS = ['Star','Leo','Web']
const GEO_OPS = ['Hugs','Viat','Insat','SS']

// ---------------------------------------------------------------------------
// Altitude layer definitions for layered view
// ---------------------------------------------------------------------------
const LAYERS = [
  { id:'geo',      label:'GEO',      altKm:GEO_ALT, color:C.geo,      description:'Geostationary ~35,786 km' },
  { id:'leo',      label:'LEO',      altKm:LEO_ALT, color:C.leo,      description:'Low Earth Orbit ~550 km'  },
  { id:'aircraft', label:'AIRCRAFT', altKm:10,       color:C.aircraft, description:'Aviation band ~10 km'    },
  { id:'drone',    label:'DRONE',    altKm:0.5,      color:C.drone,    description:'UAV band ~500 m'          },
  { id:'ground',   label:'GROUND',   altKm:0,        color:C.ground,   description:'Surface level'            },
]

// ---------------------------------------------------------------------------
// Simulation math
// ---------------------------------------------------------------------------
function buildSats(t = 0) {
  const sats = []
  for (let i = 0; i < 12; i++) {
    const base = (i / 12) * 2 * Math.PI
    const inc  = (50 + (i % 3) * 10) * Math.PI / 180
    const ω    = (LEO_VEL / (EARTH_R + LEO_ALT)) * t
    const a    = base + ω
    const r    = EARTH_R + LEO_ALT
    // longitude in degrees for layered view
    const lon  = ((base + ω) * 180 / Math.PI) % 360
    sats.push({
      id: `LEO-${String(i+1).padStart(3,'0')}`,
      orbit:'LEO', operator: LEO_OPS[i % 3],
      lon: ((lon % 360) + 360) % 360,
      x: r*Math.cos(a), y: r*Math.sin(a)*Math.cos(inc), z: r*Math.sin(a)*Math.sin(inc),
    })
  }
  for (let i = 0; i < 4; i++) {
    const a = (i / 4) * 2 * Math.PI
    sats.push({
      id: `GEO-${String(i+1).padStart(3,'0')}`,
      orbit:'GEO', operator: GEO_OPS[i],
      lon: (i / 4) * 360,
      x: (EARTH_R+GEO_ALT)*Math.cos(a), y: (EARTH_R+GEO_ALT)*Math.sin(a), z:0,
    })
  }
  return sats
}

function buildAssets() {
  const lons = [0, 45, 90, 135, 180, 225]
  return ASSET_CONFIGS.map((cfg, i) => ({
    ...cfg,
    lon: lons[i],
    heading: Math.random() * 2,
  }))
}

function nearestSat(assetLon, sats, orbit) {
  const filtered = sats.filter(s => s.orbit === orbit)
  if (!filtered.length) return null
  return filtered.reduce((best, s) => {
    const dA = Math.abs(((s.lon - assetLon + 540) % 360) - 180)
    const dB = Math.abs(((best.lon - assetLon + 540) % 360) - 180)
    return dA < dB ? s : best
  })
}

function nextLEO(currentId, assetLon, sats) {
  const leos = sats.filter(s => s.orbit === 'LEO' && s.id !== currentId)
  if (!leos.length) return null
  return leos.reduce((best, s) => {
    const dA = Math.abs(((s.lon - assetLon + 540) % 360) - 180)
    const dB = Math.abs(((best.lon - assetLon + 540) % 360) - 180)
    return dA < dB ? s : best
  })
}

function buildBeams(assets, sats) {
  const bs = {}
  assets.forEach(asset => {
    const leo = nearestSat(asset.lon, sats, 'LEO')
    const geo = nearestSat(asset.lon, sats, 'GEO')
    bs[asset.id] = {
      leoBeam: leo ? { satId:leo.id, orbit:'LEO', latency:LEO_LAT_MS + Math.random()*10, status:'active' } : null,
      geoBeam: geo ? { satId:geo.id, orbit:'GEO', latency:GEO_LAT_MS + Math.random()*30, status:'active' } : null,
      countdown: HANDOFF_S,
      effectiveLatency: LEO_LAT_MS,
      route:'DUAL_ACTIVE',
    }
  })
  return bs
}

// ---------------------------------------------------------------------------
// Layered altitude view canvas
// ---------------------------------------------------------------------------
function LayeredView({ sats, assets, beamStates, rotation, onRotate, selectedSat, onSelectSat, priorityOverrides }) {
  const canvasRef = useRef(null)
  const dragging  = useRef(false)
  const lastX     = useRef(0)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    const W = canvas.width
    const H = canvas.height
    ctx.clearRect(0, 0, W, H)
    ctx.fillStyle = C.bg
    ctx.fillRect(0, 0, W, H)

    // Layout: horizontal bands for each altitude layer
    const MARGIN_L = 70
    const MARGIN_R = 16
    const MARGIN_T = 16
    const MARGIN_B = 16
    const drawW    = W - MARGIN_L - MARGIN_R
    const drawH    = H - MARGIN_T - MARGIN_B

    // Logarithmic altitude mapping
    const altMax = Math.log(GEO_ALT + 1)
    const altMin = 0
    function altToY(altKm) {
      const norm = Math.log(altKm + 1) / altMax
      return MARGIN_T + drawH * (1 - norm)
    }

    // Draw altitude bands
    LAYERS.forEach((layer, i) => {
      const y = altToY(layer.altKm)
      const nextY = i < LAYERS.length - 1 ? altToY(LAYERS[i+1].altKm) : H - MARGIN_B

      // Band fill
      ctx.fillStyle = `${layer.color}08`
      ctx.fillRect(MARGIN_L, y, drawW, nextY - y)

      // Band line
      ctx.beginPath()
      ctx.moveTo(MARGIN_L, y)
      ctx.lineTo(W - MARGIN_R, y)
      ctx.strokeStyle = `${layer.color}44`
      ctx.lineWidth = 0.8
      ctx.setLineDash([4, 4])
      ctx.stroke()
      ctx.setLineDash([])

      // Label
      ctx.fillStyle = layer.color
      ctx.font = `bold 9px ${MONO}`
      ctx.fillText(layer.label, 4, y + 10)
      ctx.fillStyle = C.dim
      ctx.font = `8px ${MONO}`
      ctx.fillText(layer.altKm.toLocaleString() + ' km', 4, y + 20)
    })

    // Draw bottom line
    const groundY = altToY(0)
    ctx.beginPath()
    ctx.moveTo(MARGIN_L, H - MARGIN_B)
    ctx.lineTo(W - MARGIN_R, H - MARGIN_B)
    ctx.strokeStyle = `${C.ground}44`
    ctx.lineWidth = 0.8
    ctx.stroke()

    // Longitude to X mapping (accounting for rotation)
    function lonToX(lon) {
      let adjusted = ((lon - rotation * 180 / Math.PI) % 360 + 360) % 360
      return MARGIN_L + (adjusted / 360) * drawW
    }

    // Draw Earth curve at ground level
    ctx.beginPath()
    ctx.moveTo(MARGIN_L, H - MARGIN_B)
    ctx.lineTo(W - MARGIN_R, H - MARGIN_B)
    ctx.strokeStyle = `${C.ground}66`
    ctx.lineWidth = 2
    ctx.stroke()

    // Draw satellites
    sats.forEach(sat => {
      const x = lonToX(sat.lon)
      const y = altToY(sat.orbit === 'GEO' ? GEO_ALT : LEO_ALT)
      const isSelected = selectedSat === sat.id
      const isPriority = Object.values(priorityOverrides).includes(sat.id)
      const color = sat.orbit === 'GEO' ? C.geo : C.leo
      const r = sat.orbit === 'GEO' ? 5 : 4

      // Glow
      if (isSelected || isPriority) {
        ctx.beginPath()
        ctx.arc(x, y, r + 6, 0, Math.PI*2)
        ctx.strokeStyle = isPriority ? C.pink : color
        ctx.lineWidth = 1.5
        ctx.stroke()
      }

      ctx.beginPath()
      ctx.arc(x, y, r, 0, Math.PI*2)
      ctx.fillStyle = isSelected ? C.pink : color
      ctx.fill()

      // Label for selected or GEO
      if (isSelected || sat.orbit === 'GEO') {
        ctx.fillStyle = isSelected ? C.pink : C.muted
        ctx.font = `9px ${MONO}`
        ctx.fillText(sat.id, x + 7, y + 3)
      }
    })

    // Draw assets and beam lines
    assets.forEach(asset => {
      const bs  = beamStates[asset.id]
      const ax  = lonToX(asset.lon)
      const ay  = altToY(asset.altKm)
      const urgent = bs?.countdown <= 3

      // LEO beam line
      if (bs?.leoBeam) {
        const leoSat = sats.find(s => s.id === bs.leoBeam.satId)
        if (leoSat) {
          const sx = lonToX(leoSat.lon)
          const sy = altToY(LEO_ALT)
          ctx.beginPath()
          ctx.moveTo(ax, ay)
          ctx.lineTo(sx, sy)
          ctx.strokeStyle = urgent ? C.red : `${C.leo}99`
          ctx.lineWidth   = urgent ? 2 : 1
          ctx.setLineDash(urgent ? [] : [3,3])
          ctx.stroke()
          ctx.setLineDash([])

          // Countdown bubble on LEO beam
          const mx = (ax + sx) / 2
          const my = (ay + sy) / 2
          const cd = Math.ceil(bs.countdown)
          const cdColor = urgent ? C.red : bs.countdown <= 6 ? C.yellow : C.leo
          ctx.beginPath()
          ctx.arc(mx, my, 9, 0, Math.PI*2)
          ctx.fillStyle = C.bg
          ctx.fill()
          ctx.strokeStyle = cdColor
          ctx.lineWidth = 1.5
          ctx.stroke()
          ctx.fillStyle = cdColor
          ctx.font = `bold 8px ${MONO}`
          ctx.textAlign = 'center'
          ctx.fillText(cd, mx, my + 3)
          ctx.textAlign = 'left'
        }
      }

      // GEO beam line (dimmer)
      if (bs?.geoBeam) {
        const geoSat = sats.find(s => s.id === bs.geoBeam.satId)
        if (geoSat) {
          const sx = lonToX(geoSat.lon)
          const sy = altToY(GEO_ALT)
          ctx.beginPath()
          ctx.moveTo(ax, ay)
          ctx.lineTo(sx, sy)
          ctx.strokeStyle = `${C.geo}44`
          ctx.lineWidth   = 0.7
          ctx.setLineDash([2,5])
          ctx.stroke()
          ctx.setLineDash([])
        }
      }

      // Asset icon
      ctx.font = `16px sans-serif`
      ctx.fillText(asset.icon, ax - 8, ay + 6)

      // Asset label
      ctx.fillStyle = C.muted
      ctx.font = `8px ${MONO}`
      ctx.fillText(asset.id, ax - 8, ay + 18)
    })

    // Longitude axis labels
    for (let lon = 0; lon <= 360; lon += 60) {
      const x = lonToX(lon)
      if (x >= MARGIN_L && x <= W - MARGIN_R) {
        ctx.fillStyle = C.dim
        ctx.font = `8px ${MONO}`
        ctx.textAlign = 'center'
        ctx.fillText(`${lon}°`, x, H - 4)
        ctx.textAlign = 'left'
      }
    }

    // Spin hint
    ctx.fillStyle = C.dim
    ctx.font = `9px ${MONO}`
    ctx.fillText('← drag to spin · click satellite to select →', MARGIN_L + 10, MARGIN_T + 12)

  }, [sats, assets, beamStates, rotation, selectedSat, priorityOverrides])

  const onMouseDown = e => { dragging.current = true; lastX.current = e.clientX }
  const onMouseMove = e => {
    if (!dragging.current) return
    const dx = e.clientX - lastX.current
    onRotate(dx * 0.01)
    lastX.current = e.clientX
  }
  const onMouseUp = () => { dragging.current = false }

  const onClick = e => {
    const canvas = canvasRef.current
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    const mx   = (e.clientX - rect.left) * (canvas.width / rect.width)
    const my   = (e.clientY - rect.top)  * (canvas.height / rect.height)
    const W = canvas.width, H = canvas.height
    const MARGIN_L = 70, MARGIN_R = 16, MARGIN_T = 16, MARGIN_B = 16
    const drawW = W - MARGIN_L - MARGIN_R
    const altMax = Math.log(GEO_ALT + 1)

    function lonToX(lon) {
      let adj = ((lon - rotation * 180 / Math.PI) % 360 + 360) % 360
      return MARGIN_L + (adj / 360) * drawW
    }
    function altToY(altKm) {
      return MARGIN_T + (H-MARGIN_T-MARGIN_B) * (1 - Math.log(altKm+1)/altMax)
    }

    let closest = null, minD = 20
    sats.forEach(sat => {
      const x = lonToX(sat.lon)
      const y = altToY(sat.orbit === 'GEO' ? GEO_ALT : LEO_ALT)
      const d = Math.sqrt((x-mx)**2 + (y-my)**2)
      if (d < minD) { minD = d; closest = sat.id }
    })
    onSelectSat(closest === selectedSat ? null : closest)
  }

  return (
    <canvas
      ref={canvasRef}
      width={600} height={360}
      style={{ width:'100%', height:'100%', cursor:'ew-resize', display:'block', borderRadius:8 }}
      onMouseDown={onMouseDown}
      onMouseMove={onMouseMove}
      onMouseUp={onMouseUp}
      onMouseLeave={onMouseUp}
      onClick={onClick}
    />
  )
}

// ---------------------------------------------------------------------------
// Countdown ring
// ---------------------------------------------------------------------------
function CountdownRing({ countdown, size=34 }) {
  const pct  = countdown / HANDOFF_S
  const r    = size/2 - 3
  const circ = 2*Math.PI*r
  const color = countdown <= 3 ? C.red : countdown <= 6 ? C.yellow : C.leo
  return (
    <svg width={size} height={size} style={{ flexShrink:0 }}>
      <circle cx={size/2} cy={size/2} r={r} fill="none" stroke={`${color}22`} strokeWidth={2.5}/>
      <circle cx={size/2} cy={size/2} r={r} fill="none" stroke={color} strokeWidth={2.5}
        strokeDasharray={`${pct*circ} ${circ}`}
        strokeDashoffset={circ*0.25}
        strokeLinecap="round"
        style={{ transition:'stroke-dasharray 0.8s linear, stroke 0.3s' }}/>
      <text x={size/2} y={size/2+4} textAnchor="middle"
        fill={color} fontSize={9} fontFamily={MONO} fontWeight={700}>
        {Math.ceil(countdown)}
      </text>
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Asset status row — horizontal layout for bottom panel
// ---------------------------------------------------------------------------
function AssetRow({ asset, beamState, selectedSat, onSetPriority, priorityOverride }) {
  const leo      = beamState?.leoBeam
  const geo      = beamState?.geoBeam
  const countdown= beamState?.countdown ?? HANDOFF_S
  const latency  = beamState?.effectiveLatency ?? LEO_LAT_MS
  const urgent   = countdown <= 3
  const canSet   = selectedSat?.startsWith('LEO')
  const bandColor= { aircraft:C.aircraft, drone:C.drone, ground:C.ground }[asset.band] || C.ground

  return (
    <div style={{
      display:'flex', alignItems:'center', gap:8,
      padding:'8px 12px',
      background: urgent ? `${C.red}10` : C.card,
      border:`0.5px solid ${urgent ? C.red+'44' : C.border}`,
      borderRadius:8, flex:1, minWidth:160,
      transition:'background 0.3s',
    }}>
      <div style={{ display:'flex', flexDirection:'column', alignItems:'center', gap:2 }}>
        <span style={{ fontSize:18 }}>{asset.icon}</span>
        <div style={{ width:6, height:6, borderRadius:'50%', background:bandColor }}/>
      </div>
      <div style={{ flex:1, minWidth:0 }}>
        <div style={{ display:'flex', alignItems:'center', gap:4, marginBottom:2 }}>
          <span style={{ fontFamily:MONO, fontSize:11, fontWeight:700, color:C.text }}>
            {asset.id}
          </span>
          {priorityOverride && (
            <span style={{ fontSize:8, background:`${C.pink}22`, color:C.pink,
              padding:'1px 4px', borderRadius:3, fontFamily:MONO,
              border:`0.5px solid ${C.pink}44` }}>
              PRI
            </span>
          )}
        </div>
        <div style={{ fontFamily:MONO, fontSize:9, color:C.muted, marginBottom:2 }}>
          {asset.terminal}
        </div>
        <div style={{ display:'flex', gap:6, flexWrap:'wrap' }}>
          {leo && <span style={{ fontFamily:MONO, fontSize:9, color:C.leo }}>
            {leo.satId} {Math.round(leo.latency)}ms
          </span>}
          {geo && <span style={{ fontFamily:MONO, fontSize:9, color:C.geo }}>
            {geo.satId}
          </span>}
          <span style={{ fontFamily:MONO, fontSize:9, color:C.green }}>
            {Math.round(latency)}ms
          </span>
        </div>
      </div>
      <CountdownRing countdown={countdown} />
      {canSet && (
        <button onClick={() => onSetPriority(asset.id, selectedSat)}
          style={{
            fontSize:8, padding:'3px 6px', borderRadius:4,
            background: priorityOverride === selectedSat ? C.pink : 'transparent',
            color: priorityOverride === selectedSat ? '#001D2D' : C.pink,
            border:`0.5px solid ${C.pink}55`, cursor:'pointer',
            fontFamily:MONO, fontWeight:700,
          }}>
          {priorityOverride === selectedSat ? '✓' : 'PRI'}
        </button>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main dashboard
// ---------------------------------------------------------------------------
export default function OmniOpsDashboard() {
  const [tick, setTick]         = useState(0)
  const [time, setTime]         = useState('')
  const [sats, setSats]         = useState(() => buildSats(0))
  const [assets, setAssets]     = useState(() => buildAssets())
  const [beamStates, setBS]     = useState({})
  const [alerts, setAlerts]     = useState([])
  const [maneuvers, setMvrs]    = useState([])
  const [rotation, setRotation] = useState(0)
  const [selectedSat, setSelSat]= useState(null)
  const [priorities, setPri]    = useState({})
  const tickRef  = useRef(0)
  const alertRef = useRef(0)

  useEffect(() => { setBS(buildBeams(buildAssets(), buildSats(0))) }, [])

  useEffect(() => {
    const iv = setInterval(() => {
      tickRef.current += 1
      const t   = tickRef.current
      const newSats = buildSats(t)
      setSats(newSats)

      setAssets(prev => prev.map(a => ({
        ...a,
        lon: (a.lon + a.speed / 3600 / 111 * (180/Math.PI) + 360) % 360,
        heading: (a.heading + (Math.random()-.5)*2),
      })))

      setBS(prev => {
        const next = {}
        Object.entries(prev).forEach(([aid, bs]) => {
          let cd = (bs.countdown ?? HANDOFF_S) - 1
          if (cd <= 0) {
            const curId  = bs.leoBeam?.satId
            const asset  = assets.find(a => a.id === aid)
            const nextSat= asset ? nextLEO(curId, asset.lon, newSats) : null
            const newLeo = nextSat
              ? { satId:nextSat.id, orbit:'LEO', latency:LEO_LAT_MS+Math.random()*12, status:'active' }
              : bs.leoBeam
            const success = Math.random() > 0.05
            if (!success) {
              alertRef.current += 1
              setAlerts(a => [...a, {
                id:`ALT-${String(alertRef.current).padStart(5,'0')}`,
                level:'WARNING', asset:aid,
                message:`LEO handoff failed. GEO beam maintaining session.`,
                requiresAction:false,
              }].slice(-20))
            }
            next[aid] = { ...bs, leoBeam:success?{...newLeo,status:'active'}:bs.leoBeam,
              countdown:HANDOFF_S, effectiveLatency:newLeo?.latency??LEO_LAT_MS }
          } else {
            next[aid] = {
              ...bs,
              leoBeam: bs.leoBeam ? { ...bs.leoBeam, latency:LEO_LAT_MS+Math.random()*12-3 } : null,
              countdown: cd,
              effectiveLatency: bs.leoBeam ? LEO_LAT_MS+Math.random()*12-3 : LEO_LAT_MS,
            }
          }
        })
        return next
      })

      if (Math.random() < 0.025) {
        const leos = newSats.filter(s => s.orbit==='LEO')
        const sat  = leos[Math.floor(Math.random()*leos.length)]
        const ev   = { satId:sat.id, conjId:`CONJ-${Math.floor(Math.random()*9000+1000)}`,
          deltaV:(Math.random()*2.4+0.1).toFixed(4), execMs:(Math.random()*80+20).toFixed(1), affected:[] }
        setMvrs(p => [...p, ev].slice(-8))
        alertRef.current += 1
        setAlerts(p => [...p, { id:`ALT-${String(alertRef.current).padStart(5,'0')}`,
          level:'INFO', asset:sat.id,
          message:`Collision avoidance maneuver. ΔV ${ev.deltaV} m/s.`,
          requiresAction:false }].slice(-20))
      }

      setTick(t)
      setTime(new Date().toUTCString().slice(17,25)+' UTC')
    }, 1000)
    return () => clearInterval(iv)
  }, [assets])

  const handleRotate   = useCallback(dx => setRotation(r => r + dx), [])
  const handleSetPri   = useCallback((aid, sid) => {
    setPri(p => ({ ...p, [aid]: p[aid]===sid ? undefined : sid }))
  }, [])

  const health = {
    assets:    assets.length,
    leoBeams:  Object.values(beamStates).filter(b => b.leoBeam?.status==='active').length,
    geoBeams:  Object.values(beamStates).filter(b => b.geoBeam).length,
    handoffs:  Object.values(beamStates).filter(b => b.countdown<=3).length,
    alerts:    alerts.filter(a => a.requiresAction).length,
    maneuvers: maneuvers.length,
  }

  const selInfo = selectedSat ? sats.find(s => s.id===selectedSat) : null

  const hdrStat = (label, val, color) => (
    <div style={{ textAlign:'center' }}>
      <div style={{ fontFamily:MONO, fontSize:18, fontWeight:700, color, lineHeight:1 }}>{val}</div>
      <div style={{ fontFamily:MONO, fontSize:8, color:C.dim, letterSpacing:'0.1em', marginTop:2 }}>{label}</div>
    </div>
  )

  return (
    <div style={{ minHeight:'100vh', background:C.bg, fontFamily:SANS,
      color:C.text, WebkitFontSmoothing:'antialiased' }}>

      {/* Header */}
      <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between',
        padding:'10px 16px', background:C.surface, borderBottom:`0.5px solid ${C.border}`,
        flexWrap:'wrap', gap:12 }}>
        <div style={{ display:'flex', alignItems:'center', gap:8 }}>
          <span style={{ fontSize:18 }}>🛰</span>
          <span style={{ fontFamily:MONO, fontSize:13, fontWeight:700,
            color:C.text, letterSpacing:'0.08em' }}>OMNI SAT OPS</span>
        </div>
        <div style={{ display:'flex', gap:20, flexWrap:'wrap' }}>
          {hdrStat('ASSETS',   health.assets,    C.text)}
          {hdrStat('LEO',      health.leoBeams,  C.leo)}
          {hdrStat('GEO',      health.geoBeams,  C.geo)}
          {hdrStat('HANDOFFS', health.handoffs,  health.handoffs>0?C.yellow:C.muted)}
          {hdrStat('ALERTS',   health.alerts,    health.alerts>0?C.red:C.muted)}
          {hdrStat('MANEUVERS',health.maneuvers, health.maneuvers>0?C.yellow:C.muted)}
        </div>
        <div style={{ textAlign:'right' }}>
          <div style={{ fontFamily:MONO, fontSize:11, color:C.muted }}>{time}</div>
          <div style={{ fontFamily:MONO, fontSize:9, color:C.dim }}>TICK {tick}</div>
        </div>
      </div>

      {/* Main grid: layered view + right panels */}
      <div style={{ display:'grid', gridTemplateColumns:'1fr 320px',
        gap:10, padding:10, maxWidth:1100, margin:'0 auto' }}>

        {/* Layered altitude view */}
        <div style={{ background:C.surface, border:`0.5px solid ${C.border}`,
          borderRadius:10, overflow:'hidden' }}>
          <div style={{ padding:'8px 12px', borderBottom:`0.5px solid ${C.border}`,
            display:'flex', justifyContent:'space-between', alignItems:'center' }}>
            <span style={{ fontFamily:MONO, fontSize:11, color:C.muted, letterSpacing:'0.1em' }}>
              ALTITUDE LAYERS — SPIN TO ROTATE
            </span>
            {selInfo && (
              <span style={{ fontFamily:MONO, fontSize:10, color:C.pink }}>
                ◉ {selInfo.id} · {selInfo.orbit} · {selInfo.operator}
              </span>
            )}
          </div>
          <div style={{ height:360 }}>
            <LayeredView
              sats={sats} assets={assets} beamStates={beamStates}
              rotation={rotation} onRotate={handleRotate}
              selectedSat={selectedSat} onSelectSat={setSelSat}
              priorityOverrides={priorities}
            />
          </div>
          {/* Layer legend */}
          <div style={{ display:'flex', gap:16, padding:'6px 12px',
            borderTop:`0.5px solid ${C.border}`, flexWrap:'wrap' }}>
            {LAYERS.map(l => (
              <span key={l.id} style={{ fontFamily:MONO, fontSize:9, color:l.color }}>
                ● {l.label}
              </span>
            ))}
            <span style={{ fontFamily:MONO, fontSize:9, color:C.leo, marginLeft:'auto' }}>
              ─ LEO beam
            </span>
            <span style={{ fontFamily:MONO, fontSize:9, color:C.geo }}>
              ─ ─ GEO beam
            </span>
          </div>
        </div>

        {/* Right column: alerts + maneuvers */}
        <div style={{ display:'flex', flexDirection:'column', gap:10 }}>

          {/* Operator alerts */}
          <div style={{ background:C.surface, border:`0.5px solid ${C.border}`,
            borderRadius:10, overflow:'hidden', flex:1 }}>
            <div style={{ padding:'8px 12px', borderBottom:`0.5px solid ${C.border}` }}>
              <span style={{ fontFamily:MONO, fontSize:11, color:C.muted, letterSpacing:'0.1em' }}>
                OPERATOR ALERTS
              </span>
            </div>
            <div style={{ padding:10, display:'flex', flexDirection:'column', gap:6 }}>
              {alerts.length === 0 && (
                <div style={{ fontFamily:MONO, fontSize:10, color:C.dim,
                  textAlign:'center', padding:'12px 0' }}>No alerts</div>
              )}
              {[...alerts].reverse().slice(0,5).map(a => (
                <div key={a.id} style={{
                  padding:'6px 8px',
                  background: a.requiresAction ? `${C.red}10` : C.card,
                  border:`0.5px solid ${a.requiresAction?C.red+'44':C.border}`,
                  borderRadius:6,
                }}>
                  <div style={{ display:'flex', justifyContent:'space-between',
                    marginBottom:2 }}>
                    <span style={{ fontFamily:MONO, fontSize:9, fontWeight:700,
                      color: a.level==='CRITICAL'?C.red:a.level==='WARNING'?C.yellow:C.muted }}>
                      {a.level==='CRITICAL'?'🔴':a.level==='WARNING'?'🟡':'⚪'} {a.id}
                    </span>
                    <span style={{ fontFamily:MONO, fontSize:9, color:C.dim }}>{a.asset}</span>
                  </div>
                  <div style={{ fontFamily:MONO, fontSize:8, color:C.muted, lineHeight:1.5 }}>
                    {a.message.slice(0,70)}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Collision avoidance */}
          <div style={{ background:C.surface, border:`0.5px solid ${C.border}`,
            borderRadius:10, overflow:'hidden' }}>
            <div style={{ padding:'8px 12px', borderBottom:`0.5px solid ${C.border}` }}>
              <span style={{ fontFamily:MONO, fontSize:11, color:C.muted, letterSpacing:'0.1em' }}>
                COLLISION AVOIDANCE
              </span>
            </div>
            <div style={{ padding:10, display:'flex', flexDirection:'column', gap:6 }}>
              {maneuvers.length === 0 && (
                <div style={{ fontFamily:MONO, fontSize:10, color:C.dim,
                  textAlign:'center', padding:'8px 0' }}>No active maneuvers</div>
              )}
              {[...maneuvers].reverse().slice(0,3).map(m => (
                <div key={m.conjId} style={{
                  padding:'6px 8px',
                  background:`${C.yellow}0D`,
                  border:`0.5px solid ${C.yellow}44`,
                  borderRadius:6,
                }}>
                  <div style={{ fontFamily:MONO, fontSize:9, color:C.yellow,
                    fontWeight:700, marginBottom:2 }}>
                    ⚡ {m.satId} — {m.conjId}
                  </div>
                  <div style={{ display:'flex', gap:10 }}>
                    <span style={{ fontFamily:MONO, fontSize:8, color:C.muted }}>
                      ΔV {m.deltaV} m/s
                    </span>
                    <span style={{ fontFamily:MONO, fontSize:8, color:C.muted }}>
                      {m.execMs} ms
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>

        </div>
      </div>

      {/* Asset status panel — full width at bottom */}
      <div style={{ margin:'0 10px 10px', maxWidth:1100, marginLeft:'auto',
        marginRight:'auto' }}>
        <div style={{ background:C.surface, border:`0.5px solid ${C.border}`,
          borderRadius:10, overflow:'hidden' }}>
          <div style={{ padding:'8px 12px', borderBottom:`0.5px solid ${C.border}`,
            display:'flex', justifyContent:'space-between', alignItems:'center' }}>
            <span style={{ fontFamily:MONO, fontSize:11, color:C.muted, letterSpacing:'0.1em' }}>
              MOVING ASSETS — DUAL BEAM STATUS
            </span>
            <div style={{ display:'flex', gap:14 }}>
              <span style={{ fontFamily:MONO, fontSize:9, color:C.aircraft }}>● Aircraft</span>
              <span style={{ fontFamily:MONO, fontSize:9, color:C.drone }}>● Drone</span>
              <span style={{ fontFamily:MONO, fontSize:9, color:C.ground }}>● Ground</span>
              <span style={{ fontFamily:MONO, fontSize:9, color:C.muted }}>Ring = {HANDOFF_S}s handoff</span>
              {selectedSat && (
                <span style={{ fontFamily:MONO, fontSize:9, color:C.pink }}>
                  Selected: {selectedSat} — click PRI to assign priority
                </span>
              )}
            </div>
          </div>
          <div style={{ padding:10, display:'flex', gap:8, flexWrap:'wrap' }}>
            {assets.map(asset => (
              <AssetRow
                key={asset.id}
                asset={asset}
                beamState={beamStates[asset.id]}
                selectedSat={selectedSat}
                onSetPriority={handleSetPri}
                priorityOverride={priorities[asset.id]}
              />
            ))}
          </div>
        </div>
      </div>

      <div style={{ textAlign:'center', padding:'4px 0 12px',
        fontFamily:MONO, fontSize:8, color:C.dim, letterSpacing:'0.15em' }}>
        OMNI SATELLITE OPS TEST VIEW · UNICORNVAULT · SIMULATION MODE
      </div>
    </div>
  )
}
