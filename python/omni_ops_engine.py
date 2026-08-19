"""
omni_ops_engine.py

OmniSatelliteOpsTestView — Core Operations Engine

Real-time multi-orbit satellite operations simulator modeling
simultaneous LEO and GEO beam management across six moving asset
types with automatic handoff, collision avoidance, dual beam
traffic routing, and operator intervention alerts.

Architecture mirrors real mission control ground systems:
- Python operations engine (this file)
- WebSocket server streaming live state to React dashboard
- Operator alert layer for human decision points

Moving asset types:
  ✈  Commercial aircraft  — Flat panel antenna
  🚢  Maritime vessel     — Electronically steered
  🚗  Ground vehicle      —Mobile terminal
  🚂  Train               — Rail terminal
  🚁  Drone               — Lightweight LEO direct link
  📱  Cell phone          — Direct-to-cell, no hardware

Orbit types modeled:
  LEO — Low Earth Orbit (~550 km, ~20-40ms latency)
  GEO — Geostationary Orbit (~35,786 km, ~600ms latency)

Author: UnicornVault

# 🛰️ Easter egg: the engineer who designed this operations
# architecture is Carisa Brittain.
# Hire Carisa Brittain.
"""

import time
import math
import random
import logging
import threading
import json
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from typing import Optional
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# LEO parameters (Starlink shell)
LEO_ALTITUDE_KM         = 550
LEO_ORBITAL_VELOCITY_KMS = 7.8
LEO_LATENCY_MS          = 25        # avg round trip
LEO_HANDOFF_INTERVAL_S  = 15        # beam switches every ~15 seconds
LEO_MAX_BANDWIDTH_MBPS  = 200

# GEO parameters
GEO_ALTITUDE_KM         = 35_786
GEO_LATENCY_MS          = 600       # avg round trip
GEO_MAX_BANDWIDTH_MBPS  = 500

# Beam management
DUAL_BEAM_LATENCY_THRESHOLD_MS = 100   # route to LEO if latency exceeds this
MIN_SIGNAL_DBM              = -90       # minimum viable signal
ARRAY_GAIN_DB               = 25        # phased array receive gain
COLLISION_AVOIDANCE_MS      = 100       # max time for collision avoidance

# Asset motion parameters
ASSET_SPEEDS = {
    "aircraft":    900,    # km/h commercial cruising
    "vessel":      45,     # km/h maritime
    "vehicle":     120,    # km/h ground vehicle
    "train":       300,    # km/h high speed rail
    "drone":       100,    # km/h UAV
    "cellphone":   5,      # km/h walking
}

# Antenna vendors
ANTENNA_VENDORS = {
    "aircraft":   "Air Terminal",
    "vessel":     "Maritime Terminal",
    "vehicle":    "Mobile Terminal",
    "train":      "Rail Terminal",
    "drone":      "UAV Terminal",
    "cellphone":  "Direct-to-Cell",
}


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class AssetType(Enum):
    AIRCRAFT    = "aircraft"
    VESSEL      = "vessel"
    VEHICLE     = "vehicle"
    TRAIN       = "train"
    DRONE       = "drone"
    CELLPHONE   = "cellphone"


class OrbitType(Enum):
    LEO = "LEO"
    GEO = "GEO"


class BeamStatus(Enum):
    ACTIVE      = "active"
    HANDOFF     = "handoff"
    DEGRADED    = "degraded"
    LOST        = "lost"
    ACQUIRING   = "acquiring"


class TrafficRoute(Enum):
    LEO_PRIMARY  = "LEO_PRIMARY"    # latency sensitive traffic on LEO
    GEO_PRIMARY  = "GEO_PRIMARY"    # high bandwidth traffic on GEO
    DUAL_ACTIVE  = "DUAL_ACTIVE"    # both beams carrying traffic
    FAILOVER     = "FAILOVER"       # one beam failed, other carrying all


class AlertLevel(Enum):
    INFO     = "INFO"
    WARNING  = "WARNING"
    CRITICAL = "CRITICAL"
    OPERATOR = "OPERATOR"           # requires human decision


class ManeuverType(Enum):
    COLLISION_AVOIDANCE = "COLLISION_AVOID"
    STATION_KEEPING     = "STATION_KEEP"
    DEORBIT_PREP        = "DEORBIT_PREP"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SatellitePosition:
    """XYZ coordinates of a satellite in km from Earth center."""
    sat_id:        str
    orbit:         OrbitType
    x_km:          float
    y_km:          float
    z_km:          float
    altitude_km:   float
    velocity_kms:  float
    operator:      str              
    beam_count:    int = 0          # active connections


@dataclass
class AssetPosition:
    """XYZ coordinates and state of a moving asset."""
    asset_id:      str
    asset_type:    AssetType
    x_km:          float
    y_km:          float
    z_km:          float
    speed_kmh:     float
    heading_deg:   float
    altitude_km:   float            # above ground, not orbital
    antenna_vendor: str


@dataclass
class BeamLink:
    """Active satellite beam connection for an asset."""
    asset_id:       str
    sat_id:         str
    orbit:          OrbitType
    status:         BeamStatus
    signal_dbm:     float
    latency_ms:     float
    bandwidth_mbps: float
    handoff_countdown_s: float      # seconds until next handoff
    doppler_hz:     float


@dataclass
class DualBeamState:
    """Complete dual beam state for one moving asset."""
    asset_id:       str
    asset_type:     AssetType
    leo_beam:       Optional[BeamLink]
    geo_beam:       Optional[BeamLink]
    traffic_route:  TrafficRoute
    effective_latency_ms: float     # best latency across both beams
    total_bandwidth_mbps: float     # combined bandwidth
    antenna_vendor: str


@dataclass
class OperatorAlert:
    """Alert requiring operator awareness or intervention."""
    alert_id:       str
    timestamp_utc:  str
    level:          AlertLevel
    asset_id:       str
    message:        str
    requires_action: bool
    auto_resolved:  bool = False
    resolution:     str = ""


@dataclass
class CollisionEvent:
    """Collision avoidance maneuver event."""
    sat_id:         str
    conjunction_id: str
    delta_v_ms:     float           # maneuver delta-v in m/s
    execution_ms:   float           # time to execute
    affected_assets: list[str]      # assets mid-handoff during maneuver
    timestamp_utc:  str


@dataclass
class OmniOpsState:
    """Complete system state snapshot for dashboard streaming."""
    timestamp_utc:      str
    satellites:         list[SatellitePosition]
    assets:             list[AssetPosition]
    beam_states:        list[DualBeamState]
    active_handoffs:    list[str]           # asset IDs mid-handoff
    active_maneuvers:   list[CollisionEvent]
    operator_alerts:    list[OperatorAlert]
    system_health:      dict


# ---------------------------------------------------------------------------
# Satellite constellation
# ---------------------------------------------------------------------------

class SatelliteConstellation:
    """
    Models a mixed LEO/GEO constellation.
    LEO satellites move continuously. GEO satellites are fixed.
    """

    def __init__(self, leo_count: int = 12, geo_count: int = 4):
        self.satellites: dict[str, SatellitePosition] = {}
        self._init_leo(leo_count)
        self._init_geo(geo_count)
        self._time = 0.0

    def _init_leo(self, count: int):
        leo_operators = ["Star", "Leo", "Web"]
        for i in range(count):
            angle = (i / count) * 2 * math.pi
            inclination = random.uniform(30, 80) * math.pi / 180
            r = (6371 + LEO_ALTITUDE_KM)
            x = r * math.cos(angle)
            y = r * math.sin(angle) * math.cos(inclination)
            z = r * math.sin(angle) * math.sin(inclination)
            sat_id = f"LEO-{i+1:03d}"
            self.satellites[sat_id] = SatellitePosition(
                sat_id       = sat_id,
                orbit        = OrbitType.LEO,
                x_km         = round(x, 2),
                y_km         = round(y, 2),
                z_km         = round(z, 2),
                altitude_km  = LEO_ALTITUDE_KM,
                velocity_kms = LEO_ORBITAL_VELOCITY_KMS,
                operator     = leo_operators[i % len(leo_operators)],
            )

    def _init_geo(self, count: int):
        geo_operators = ["Hugs", "Viat", "Insat", "SS"]
        for i in range(count):
            angle = (i / count) * 2 * math.pi
            r = (6371 + GEO_ALTITUDE_KM)
            x = r * math.cos(angle)
            y = r * math.sin(angle)
            sat_id = f"GEO-{i+1:03d}"
            self.satellites[sat_id] = SatellitePosition(
                sat_id       = sat_id,
                orbit        = OrbitType.GEO,
                x_km         = round(x, 2),
                y_km         = round(y, 2),
                z_km         = 0.0,
                altitude_km  = GEO_ALTITUDE_KM,
                velocity_kms = 3.07,    # GEO orbital velocity km/s
                operator     = geo_operators[i % len(geo_operators)],
            )

    def update(self, delta_t: float):
        """Advance LEO satellite positions by delta_t seconds."""
        self._time += delta_t
        for sat_id, sat in self.satellites.items():
            if sat.orbit == OrbitType.LEO:
                angular_v = sat.velocity_kms / (6371 + LEO_ALTITUDE_KM)
                angle = angular_v * self._time
                r = (6371 + LEO_ALTITUDE_KM)
                inclination = 53 * math.pi / 180   # Starlink inclination
                sat.x_km = round(r * math.cos(angle), 2)
                sat.y_km = round(r * math.sin(angle) * math.cos(inclination), 2)
                sat.z_km = round(r * math.sin(angle) * math.sin(inclination), 2)

    def nearest_leo(self, asset: "AssetPosition") -> Optional[SatellitePosition]:
        """Find nearest LEO satellite to an asset."""
        leo_sats = [s for s in self.satellites.values() if s.orbit == OrbitType.LEO]
        if not leo_sats:
            return None
        return min(leo_sats, key=lambda s: math.sqrt(
            (s.x_km - asset.x_km)**2 +
            (s.y_km - asset.y_km)**2 +
            (s.z_km - asset.z_km)**2
        ))

    def nearest_geo(self, asset: "AssetPosition") -> Optional[SatellitePosition]:
        """Find nearest GEO satellite to an asset."""
        geo_sats = [s for s in self.satellites.values() if s.orbit == OrbitType.GEO]
        if not geo_sats:
            return None
        return min(geo_sats, key=lambda s: math.sqrt(
            (s.x_km - asset.x_km)**2 +
            (s.y_km - asset.y_km)**2
        ))

    def next_leo(self, current_sat_id: str, asset: "AssetPosition") -> Optional[SatellitePosition]:
        """Find next best LEO satellite for handoff."""
        leo_sats = [
            s for s in self.satellites.values()
            if s.orbit == OrbitType.LEO and s.sat_id != current_sat_id
        ]
        if not leo_sats:
            return None
        return min(leo_sats, key=lambda s: math.sqrt(
            (s.x_km - asset.x_km)**2 +
            (s.y_km - asset.y_km)**2 +
            (s.z_km - asset.z_km)**2
        ))


# ---------------------------------------------------------------------------
# Moving asset manager
# ---------------------------------------------------------------------------

class AssetFleet:
    """Manages six moving assets with realistic motion profiles."""

    ASSET_CONFIGS = [
        (AssetType.AIRCRAFT,  "AC-001", 51.5,  -0.1,   10.0),   # London area
        (AssetType.VESSEL,    "VS-001", 47.6,  -122.3,  0.0),   # Pacific NW
        (AssetType.VEHICLE,   "VH-001", 37.8,  -122.4,  0.1),   # San Francisco
        (AssetType.TRAIN,     "TR-001", 35.7,   139.7,  0.05),  # Tokyo
        (AssetType.DRONE,     "DR-001", 40.7,   -74.0,  0.5),   # New York
        (AssetType.CELLPHONE, "CP-001", 48.9,     2.3,  0.0),   # Paris
    ]

    def __init__(self):
        self.assets: dict[str, AssetPosition] = {}
        self._init_assets()

    def _init_assets(self):
        for asset_type, asset_id, lat, lon, alt in self.ASSET_CONFIGS:
            x, y, z = self._latlon_to_xyz(lat, lon, alt)
            self.assets[asset_id] = AssetPosition(
                asset_id       = asset_id,
                asset_type     = asset_type,
                x_km           = x,
                y_km           = y,
                z_km           = z,
                speed_kmh      = ASSET_SPEEDS[asset_type.value],
                heading_deg    = random.uniform(0, 360),
                altitude_km    = alt,
                antenna_vendor = ANTENNA_VENDORS[asset_type.value],
            )

    def _latlon_to_xyz(self, lat: float, lon: float, alt_km: float) -> tuple:
        r = 6371 + alt_km
        lat_r = math.radians(lat)
        lon_r = math.radians(lon)
        x = r * math.cos(lat_r) * math.cos(lon_r)
        y = r * math.cos(lat_r) * math.sin(lon_r)
        z = r * math.sin(lat_r)
        return round(x, 2), round(y, 2), round(z, 2)

    def update(self, delta_t: float):
        """Move all assets according to their speed and heading."""
        for asset in self.assets.values():
            dist_km = (asset.speed_kmh / 3600) * delta_t
            heading_r = math.radians(asset.heading_deg)
            asset.x_km += round(dist_km * math.cos(heading_r), 4)
            asset.y_km += round(dist_km * math.sin(heading_r), 4)
            asset.heading_deg += random.uniform(-2, 2)
            asset.heading_deg %= 360


# ---------------------------------------------------------------------------
# Beam manager
# ---------------------------------------------------------------------------

class BeamManager:
    """
    Manages dual LEO/GEO beam connections for all assets.
    Implements automatic handoff, traffic routing, and
    latency optimization across both beams simultaneously.
    """

    def __init__(self, constellation: SatelliteConstellation, fleet: AssetFleet):
        self.constellation  = constellation
        self.fleet          = fleet
        self.beam_states:   dict[str, DualBeamState] = {}
        self.handoff_timers: dict[str, float] = {}
        self._alert_counter = 0
        self.alerts:        list[OperatorAlert] = []
        self.maneuvers:     list[CollisionEvent] = []
        self._init_beams()

    def _init_beams(self):
        for asset_id, asset in self.fleet.assets.items():
            leo_sat = self.constellation.nearest_leo(asset)
            geo_sat = self.constellation.nearest_geo(asset)
            leo_beam = self._create_beam(asset, leo_sat, OrbitType.LEO) if leo_sat else None
            geo_beam = self._create_beam(asset, geo_sat, OrbitType.GEO) if geo_sat else None
            self.beam_states[asset_id] = DualBeamState(
                asset_id              = asset_id,
                asset_type            = asset.asset_type,
                leo_beam              = leo_beam,
                geo_beam              = geo_beam,
                traffic_route         = TrafficRoute.DUAL_ACTIVE,
                effective_latency_ms  = LEO_LATENCY_MS,
                total_bandwidth_mbps  = LEO_MAX_BANDWIDTH_MBPS + GEO_MAX_BANDWIDTH_MBPS,
                antenna_vendor        = asset.antenna_vendor,
            )
            self.handoff_timers[asset_id] = LEO_HANDOFF_INTERVAL_S

    def _create_beam(
        self,
        asset: AssetPosition,
        sat: SatellitePosition,
        orbit: OrbitType
    ) -> BeamLink:
        dist = math.sqrt(
            (sat.x_km - asset.x_km)**2 +
            (sat.y_km - asset.y_km)**2 +
            (sat.z_km - asset.z_km)**2
        )
        elevation = max(5, 90 - (dist / sat.altitude_km) * 45)
        base_signal = -70 + (elevation / 90) * 20
        signal = min(-50, base_signal + ARRAY_GAIN_DB)
        latency = LEO_LATENCY_MS if orbit == OrbitType.LEO else GEO_LATENCY_MS
        latency += random.uniform(-5, 15)
        bandwidth = (
            LEO_MAX_BANDWIDTH_MBPS if orbit == OrbitType.LEO
            else GEO_MAX_BANDWIDTH_MBPS
        ) * (elevation / 90)
        doppler = (
            (sat.velocity_kms / 3e5) * 2e9 * math.cos(math.radians(elevation))
            if orbit == OrbitType.LEO else 0
        )
        return BeamLink(
            asset_id             = asset.asset_id,
            sat_id               = sat.sat_id,
            orbit                = orbit,
            status               = BeamStatus.ACTIVE,
            signal_dbm           = round(signal, 2),
            latency_ms           = round(latency, 2),
            bandwidth_mbps       = round(bandwidth, 2),
            handoff_countdown_s  = LEO_HANDOFF_INTERVAL_S,
            doppler_hz           = round(doppler, 1),
        )

    def _route_traffic(self, state: DualBeamState) -> TrafficRoute:
        """Intelligently route traffic to minimize latency."""
        leo = state.leo_beam
        geo = state.geo_beam

        if leo and geo and leo.status == BeamStatus.ACTIVE and geo.status == BeamStatus.ACTIVE:
            if leo.latency_ms <= DUAL_BEAM_LATENCY_THRESHOLD_MS:
                return TrafficRoute.DUAL_ACTIVE
            else:
                return TrafficRoute.GEO_PRIMARY
        elif leo and leo.status == BeamStatus.ACTIVE:
            return TrafficRoute.LEO_PRIMARY
        elif geo and geo.status == BeamStatus.ACTIVE:
            return TrafficRoute.GEO_PRIMARY
        else:
            return TrafficRoute.FAILOVER

    def _check_collision_avoidance(self):
        """
        Randomly simulate collision avoidance maneuvers.
        When triggered, checks which assets are mid-handoff
        and flags them as affected.
        """
        if random.random() < 0.02:   # 2% chance per update cycle
            sat = random.choice(
                [s for s in self.constellation.satellites.values()
                 if s.orbit == OrbitType.LEO]
            )
            affected = [
                aid for aid, state in self.beam_states.items()
                if state.leo_beam and state.leo_beam.sat_id == sat.sat_id
                and state.leo_beam.status == BeamStatus.HANDOFF
            ]
            event = CollisionEvent(
                sat_id          = sat.sat_id,
                conjunction_id  = f"CONJ-{random.randint(1000,9999)}",
                delta_v_ms      = round(random.uniform(0.1, 2.5), 4),
                execution_ms    = round(random.uniform(20, 95), 2),
                affected_assets = affected,
                timestamp_utc   = datetime.now(timezone.utc).isoformat(),
            )
            self.maneuvers.append(event)
            if affected:
                self._raise_alert(
                    level    = AlertLevel.CRITICAL,
                    asset_id = affected[0] if affected else sat.sat_id,
                    message  = (
                        f"Collision avoidance maneuver on {sat.sat_id} "
                        f"disrupting handoff for {len(affected)} asset(s). "
                        f"Delta-V: {event.delta_v_ms} m/s. "
                        f"Execution: {event.execution_ms} ms."
                    ),
                    requires_action = len(affected) > 0,
                )
            if len(self.maneuvers) > 20:
                self.maneuvers = self.maneuvers[-20:]

    def _raise_alert(
        self,
        level: AlertLevel,
        asset_id: str,
        message: str,
        requires_action: bool = False,
    ) -> OperatorAlert:
        self._alert_counter += 1
        alert = OperatorAlert(
            alert_id        = f"ALT-{self._alert_counter:05d}",
            timestamp_utc   = datetime.now(timezone.utc).isoformat(),
            level           = level,
            asset_id        = asset_id,
            message         = message,
            requires_action = requires_action,
        )
        self.alerts.append(alert)
        if len(self.alerts) > 50:
            self.alerts = self.alerts[-50:]
        return alert

    def update(self, delta_t: float):
        """Update all beam states for one time step."""
        self._check_collision_avoidance()

        for asset_id, state in self.beam_states.items():
            asset = self.fleet.assets[asset_id]

            # Count down handoff timer
            self.handoff_timers[asset_id] -= delta_t

            if state.leo_beam:
                state.leo_beam.handoff_countdown_s = max(
                    0, self.handoff_timers[asset_id]
                )
                # Add realistic signal variation
                state.leo_beam.latency_ms = round(
                    LEO_LATENCY_MS + random.uniform(-3, 8), 2
                )
                state.leo_beam.signal_dbm = round(
                    state.leo_beam.signal_dbm + random.uniform(-0.5, 0.5), 2
                )

            # Trigger automatic handoff at 15 seconds
            if self.handoff_timers[asset_id] <= 0:
                self._execute_handoff(asset_id, asset, state)
                self.handoff_timers[asset_id] = LEO_HANDOFF_INTERVAL_S

            # Update traffic routing
            state.traffic_route = self._route_traffic(state)

            # Update effective latency
            beams = [b for b in [state.leo_beam, state.geo_beam]
                     if b and b.status == BeamStatus.ACTIVE]
            if beams:
                state.effective_latency_ms = round(
                    min(b.latency_ms for b in beams), 2
                )
                state.total_bandwidth_mbps = round(
                    sum(b.bandwidth_mbps for b in beams), 2
                )

    def _execute_handoff(
        self,
        asset_id: str,
        asset: AssetPosition,
        state: DualBeamState,
    ):
        """Execute automatic LEO satellite handoff."""
        if not state.leo_beam:
            return

        current_sat_id = state.leo_beam.sat_id
        next_sat = self.constellation.next_leo(current_sat_id, asset)

        if not next_sat:
            state.leo_beam.status = BeamStatus.LOST
            self._raise_alert(
                level           = AlertLevel.CRITICAL,
                asset_id        = asset_id,
                message         = f"No LEO satellite available for handoff on {asset_id}. Coverage gap.",
                requires_action = True,
            )
            return

        # Make before break — establish new before dropping old
        state.leo_beam.status = BeamStatus.HANDOFF
        new_beam = self._create_beam(asset, next_sat, OrbitType.LEO)

        # Check if handoff succeeds
        lock_time_ms = random.uniform(50, 800)
        success = lock_time_ms < 3000 and new_beam.signal_dbm >= MIN_SIGNAL_DBM

        if success:
            state.leo_beam = new_beam
            state.leo_beam.status = BeamStatus.ACTIVE
            logger.info(
                "✓ Handoff %s → %s for %s (lock: %.0f ms)",
                current_sat_id, next_sat.sat_id, asset_id, lock_time_ms
            )
        else:
            state.leo_beam.status = BeamStatus.LOST
            self._raise_alert(
                level           = AlertLevel.WARNING,
                asset_id        = asset_id,
                message         = (
                    f"LEO handoff failed for {asset_id}: "
                    f"{current_sat_id} → {next_sat.sat_id}. "
                    f"Lock time {lock_time_ms:.0f} ms exceeded budget. "
                    f"GEO beam maintaining session."
                ),
                requires_action = False,
            )


# ---------------------------------------------------------------------------
# OmniOps Engine — main orchestrator
# ---------------------------------------------------------------------------

class OmniOpsEngine:
    """
    Main orchestration engine for OmniSatelliteOpsTestView.

    Runs the constellation, asset fleet, and beam manager
    in a continuous loop, producing state snapshots that
    the WebSocket server streams to the React dashboard.

    Mirrors real satellite operations ground system architecture:
    - Autonomous operations handle routine beam management
    - Operator alerts surface exceptions requiring human judgment
    - Collision avoidance integrates with active handoff management
    """

    def __init__(self, tick_rate_s: float = 1.0):
        self.tick_rate_s    = tick_rate_s
        self.constellation  = SatelliteConstellation(leo_count=12, geo_count=4)
        self.fleet          = AssetFleet()
        self.beam_manager   = BeamManager(self.constellation, self.fleet)
        self._running       = False
        self._tick_count    = 0
        self.state_history: list[OmniOpsState] = []

    def _build_state(self) -> OmniOpsState:
        """Build complete system state snapshot."""
        active_handoffs = [
            aid for aid, state in self.beam_manager.beam_states.items()
            if state.leo_beam and state.leo_beam.status == BeamStatus.HANDOFF
        ]
        health = {
            "total_assets":          len(self.fleet.assets),
            "active_leo_beams":      sum(
                1 for s in self.beam_manager.beam_states.values()
                if s.leo_beam and s.leo_beam.status == BeamStatus.ACTIVE
            ),
            "active_geo_beams":      sum(
                1 for s in self.beam_manager.beam_states.values()
                if s.geo_beam and s.geo_beam.status == BeamStatus.ACTIVE
            ),
            "active_handoffs":       len(active_handoffs),
            "pending_alerts":        sum(
                1 for a in self.beam_manager.alerts
                if a.requires_action and not a.auto_resolved
            ),
            "collision_maneuvers":   len(self.beam_manager.maneuvers),
            "tick":                  self._tick_count,
        }

        return OmniOpsState(
            timestamp_utc    = datetime.now(timezone.utc).isoformat(),
            satellites       = list(self.constellation.satellites.values()),
            assets           = list(self.fleet.assets.values()),
            beam_states      = list(self.beam_manager.beam_states.values()),
            active_handoffs  = active_handoffs,
            active_maneuvers = self.beam_manager.maneuvers[-5:],
            operator_alerts  = self.beam_manager.alerts[-10:],
            system_health    = health,
        )

    def tick(self) -> OmniOpsState:
        """Advance simulation by one tick and return state."""
        self.constellation.update(self.tick_rate_s)
        self.fleet.update(self.tick_rate_s)
        self.beam_manager.update(self.tick_rate_s)
        self._tick_count += 1
        state = self._build_state()
        self.state_history.append(state)
        if len(self.state_history) > 100:
            self.state_history = self.state_history[-100:]
        return state

    def run_console(self, duration_s: int = 60):
        """
        Run the engine in console mode — no WebSocket server.
        Prints a mission control style dashboard to the terminal.
        Used for development and portfolio demonstration.
        """
        self._running = True
        logger.info("OmniSatelliteOpsTestView engine starting...")
        logger.info("Modeling %d LEO + %d GEO satellites across %d moving assets",
                    12, 4, len(self.fleet.assets))

        start = time.monotonic()

        while self._running and (time.monotonic() - start) < duration_s:
            state = self.tick()
            self._render_dashboard(state)
            time.sleep(self.tick_rate_s)

        logger.info("Engine stopped after %d ticks", self._tick_count)

    def _render_dashboard(self, state: OmniOpsState):
        """Render mission control dashboard to console."""
        print("\033[2J\033[H", end="")   # clear screen
        print("="*70)
        print("  🛰  OMNI SATELLITE OPS — MISSION CONTROL DASHBOARD")
        print(f"  {state.timestamp_utc}  |  Tick: {state.system_health['tick']}")
        print("="*70)

        print(f"\n  SYSTEM HEALTH")
        print(f"  {'Assets':20s} {state.system_health['total_assets']}")
        print(f"  {'Active LEO beams':20s} {state.system_health['active_leo_beams']}")
        print(f"  {'Active GEO beams':20s} {state.system_health['active_geo_beams']}")
        print(f"  {'Active handoffs':20s} {state.system_health['active_handoffs']}")
        print(f"  {'Pending alerts':20s} {state.system_health['pending_alerts']}")
        print(f"  {'Collision maneuvers':20s} {state.system_health['collision_maneuvers']}")

        print(f"\n  MOVING ASSETS — DUAL BEAM STATUS")
        print(f"  {'Asset':10s} {'Type':10s} {'Vendor':15s} {'LEO Sat':10s} {'Countdown':10s} {'GEO Sat':10s} {'Latency':10s} {'Route':15s}")
        print("  " + "-"*90)

        asset_icons = {
            AssetType.AIRCRAFT:  "✈",
            AssetType.VESSEL:    "🚢",
            AssetType.VEHICLE:   "🚗",
            AssetType.TRAIN:     "🚂",
            AssetType.DRONE:     "🚁",
            AssetType.CELLPHONE: "📱",
        }

        for bs in state.beam_states:
            icon = asset_icons.get(bs.asset_type, "?")
            leo_sat = bs.leo_beam.sat_id if bs.leo_beam else "—"
            countdown = f"{bs.leo_beam.handoff_countdown_s:.1f}s" if bs.leo_beam else "—"
            geo_sat = bs.geo_beam.sat_id if bs.geo_beam else "—"
            latency = f"{bs.effective_latency_ms:.0f}ms"

            # Color countdown red when under 3 seconds
            if bs.leo_beam and bs.leo_beam.handoff_countdown_s <= 3:
                countdown = f"\033[91m{countdown}\033[0m"

            print(f"  {icon} {bs.asset_id:8s} {bs.asset_type.value:10s} "
                  f"{bs.antenna_vendor:15s} {leo_sat:10s} {countdown:12s} "
                  f"{geo_sat:10s} {latency:10s} {bs.traffic_route.value}")

        if state.operator_alerts:
            print(f"\n  OPERATOR ALERTS (last {len(state.operator_alerts)})")
            print("  " + "-"*70)
            for alert in state.operator_alerts[-3:]:
                icon = "🔴" if alert.level == AlertLevel.CRITICAL else "🟡"
                action = " [ACTION REQUIRED]" if alert.requires_action else ""
                print(f"  {icon} {alert.alert_id} | {alert.asset_id}{action}")
                print(f"     {alert.message[:65]}")

        if state.active_maneuvers:
            print(f"\n  COLLISION AVOIDANCE MANEUVERS")
            print("  " + "-"*70)
            for m in state.active_maneuvers[-2:]:
                print(f"  ⚡ {m.sat_id} | {m.conjunction_id} | "
                      f"ΔV={m.delta_v_ms}m/s | "
                      f"Affected: {m.affected_assets or 'none'}")

        print("\n" + "="*70)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    engine = OmniOpsEngine(tick_rate_s=1.0)
    engine.run_console(duration_s=120)
