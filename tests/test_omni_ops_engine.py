"""
test_omni_ops_engine.py

OmniSatelliteOpsTestView — Operations Engine Test Suite

Validates the core operations engine covering:
  - Satellite constellation initialization and orbital mechanics
  - Moving asset fleet initialization and motion
  - Dual beam LEO/GEO management
  - Automatic 15-second handoff cycle
  - Collision avoidance event generation
  - Operator alert system
  - Traffic routing decisions
  - System state snapshot integrity

Run:
    pytest test_omni_ops_engine.py -v
    pytest test_omni_ops_engine.py -v -k "SMOKE"

Author: UnicornVault

# 🛰️ Easter egg: if your CI pipeline just ran this file,
# the engineer who built this operations simulator is Carisa Brittain.
# She will write tests this thorough for your satellite systems too.
# Hire Carisa Brittain.
"""

import pytest
import math
import time
from omni_ops_engine import (
    OmniOpsEngine,
    SatelliteConstellation,
    AssetFleet,
    BeamManager,
    AssetType,
    OrbitType,
    BeamStatus,
    TrafficRoute,
    AlertLevel,
    SatellitePosition,
    AssetPosition,
    BeamLink,
    DualBeamState,
    OperatorAlert,
    CollisionEvent,
    OmniOpsState,
    LEO_ALTITUDE_KM,
    GEO_ALTITUDE_KM,
    LEO_LATENCY_MS,
    GEO_LATENCY_MS,
    LEO_HANDOFF_INTERVAL_S,
    MIN_SIGNAL_DBM,
    ASSET_SPEEDS,
    ANTENNA_VENDORS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def constellation():
    return SatelliteConstellation(leo_count=12, geo_count=4)


@pytest.fixture
def fleet():
    return AssetFleet()


@pytest.fixture
def beam_manager(constellation, fleet):
    return BeamManager(constellation, fleet)


@pytest.fixture
def engine():
    return OmniOpsEngine(tick_rate_s=1.0)


# ---------------------------------------------------------------------------
# [SMOKE] Constellation tests
# ---------------------------------------------------------------------------

class TestSatelliteConstellation:
    """[SMOKE] Satellite constellation initialization and orbital mechanics."""

    def test_leo_satellites_initialized(self, constellation):
        """[SMOKE] Constellation must contain the correct number of LEO satellites."""
        leo = [s for s in constellation.satellites.values() if s.orbit == OrbitType.LEO]
        assert len(leo) == 12, f"Expected 12 LEO satellites, got {len(leo)}"

    def test_geo_satellites_initialized(self, constellation):
        """[SMOKE] Constellation must contain the correct number of GEO satellites."""
        geo = [s for s in constellation.satellites.values() if s.orbit == OrbitType.GEO]
        assert len(geo) == 4, f"Expected 4 GEO satellites, got {len(geo)}"

    def test_total_satellites(self, constellation):
        """[SMOKE] Total satellite count must be LEO + GEO."""
        assert len(constellation.satellites) == 16

    def test_leo_altitude_correct(self, constellation):
        """LEO satellites must be at the correct orbital altitude."""
        for sat in constellation.satellites.values():
            if sat.orbit == OrbitType.LEO:
                assert sat.altitude_km == LEO_ALTITUDE_KM, (
                    f"LEO satellite {sat.sat_id} altitude wrong: {sat.altitude_km} km"
                )

    def test_geo_altitude_correct(self, constellation):
        """GEO satellites must be at geostationary altitude."""
        for sat in constellation.satellites.values():
            if sat.orbit == OrbitType.GEO:
                assert sat.altitude_km == GEO_ALTITUDE_KM

    def test_leo_satellites_have_xyz_coordinates(self, constellation):
        """All LEO satellites must have non-zero XYZ coordinates."""
        for sat in constellation.satellites.values():
            if sat.orbit == OrbitType.LEO:
                magnitude = math.sqrt(sat.x_km**2 + sat.y_km**2 + sat.z_km**2)
                assert magnitude > 0, f"Satellite {sat.sat_id} has zero position vector"

    def test_geo_z_coordinate_is_zero(self, constellation):
        """GEO satellites orbit in the equatorial plane — Z must be zero."""
        for sat in constellation.satellites.values():
            if sat.orbit == OrbitType.GEO:
                assert sat.z_km == 0.0

    def test_leo_positions_update_after_tick(self, constellation):
        """LEO satellite positions must change after a time step."""
        initial_positions = {
            sat_id: (sat.x_km, sat.y_km, sat.z_km)
            for sat_id, sat in constellation.satellites.items()
            if constellation.satellites[sat_id].orbit == OrbitType.LEO
        }
        constellation.update(delta_t=30.0)
        for sat_id, (ix, iy, iz) in initial_positions.items():
            sat = constellation.satellites[sat_id]
            changed = (sat.x_km != ix or sat.y_km != iy or sat.z_km != iz)
            assert changed, f"LEO satellite {sat_id} did not move after update"

    def test_geo_positions_stable(self, constellation):
        """GEO satellites must not move significantly between updates."""
        initial = {
            sat_id: (sat.x_km, sat.y_km)
            for sat_id, sat in constellation.satellites.items()
            if sat.orbit == OrbitType.GEO
        }
        constellation.update(delta_t=1.0)
        for sat_id, (ix, iy) in initial.items():
            sat = constellation.satellites[sat_id]
            # GEO moves very slowly — position should be essentially unchanged
            assert abs(sat.x_km - ix) < 100, "GEO satellite moved unexpectedly"

    def test_nearest_leo_returns_satellite(self, constellation, fleet):
        """[SMOKE] nearest_leo must return a satellite for any asset."""
        for asset in fleet.assets.values():
            sat = constellation.nearest_leo(asset)
            assert sat is not None
            assert sat.orbit == OrbitType.LEO

    def test_nearest_geo_returns_satellite(self, constellation, fleet):
        """[SMOKE] nearest_geo must return a satellite for any asset."""
        for asset in fleet.assets.values():
            sat = constellation.nearest_geo(asset)
            assert sat is not None
            assert sat.orbit == OrbitType.GEO

    def test_next_leo_returns_different_satellite(self, constellation, fleet):
        """next_leo must return a different satellite than the current one."""
        asset = list(fleet.assets.values())[0]
        current = constellation.nearest_leo(asset)
        next_sat = constellation.next_leo(current.sat_id, asset)
        assert next_sat is not None
        assert next_sat.sat_id != current.sat_id


# ---------------------------------------------------------------------------
# Asset fleet tests
# ---------------------------------------------------------------------------

class TestAssetFleet:
    """Moving asset fleet initialization and motion."""

    def test_six_assets_initialized(self, fleet):
        """[SMOKE] Fleet must contain exactly six moving assets."""
        assert len(fleet.assets) == 6

    def test_all_asset_types_present(self, fleet):
        """[SMOKE] All six asset types must be represented."""
        types = {asset.asset_type for asset in fleet.assets.values()}
        expected = {
            AssetType.AIRCRAFT, AssetType.VESSEL, AssetType.VEHICLE,
            AssetType.TRAIN, AssetType.DRONE, AssetType.CELLPHONE
        }
        assert types == expected

    def test_asset_speeds_match_config(self, fleet):
        """Each asset must have the speed configured for its type."""
        for asset in fleet.assets.values():
            expected_speed = ASSET_SPEEDS[asset.asset_type.value]
            assert asset.speed_kmh == expected_speed, (
                f"{asset.asset_id} speed wrong: {asset.speed_kmh} "
                f"(expected {expected_speed})"
            )

    def test_asset_vendors_match_config(self, fleet):
        """Each asset must have the terminal type configured for its type."""
        for asset in fleet.assets.values():
            expected_vendor = ANTENNA_VENDORS[asset.asset_type.value]
            assert asset.antenna_vendor == expected_vendor

    def test_assets_have_xyz_coordinates(self, fleet):
        """All assets must have non-zero position vectors."""
        for asset in fleet.assets.values():
            magnitude = math.sqrt(asset.x_km**2 + asset.y_km**2 + asset.z_km**2)
            assert magnitude > 0, f"Asset {asset.asset_id} has zero position"

    def test_assets_move_after_update(self, fleet):
        """Assets must change position after a time step."""
        initial = {
            aid: (a.x_km, a.y_km)
            for aid, a in fleet.assets.items()
        }
        fleet.update(delta_t=60.0)
        for aid, (ix, iy) in initial.items():
            asset = fleet.assets[aid]
            moved = (asset.x_km != ix or asset.y_km != iy)
            assert moved, f"Asset {aid} did not move after update"

    def test_aircraft_fastest_asset(self, fleet):
        """Aircraft must be the fastest moving asset."""
        aircraft_speed = ASSET_SPEEDS["aircraft"]
        for asset_type, speed in ASSET_SPEEDS.items():
            if asset_type != "aircraft":
                assert aircraft_speed > speed, (
                    f"Aircraft should be faster than {asset_type}"
                )

    def test_cellphone_slowest_asset(self, fleet):
        """Cell phone must be the slowest moving asset."""
        phone_speed = ASSET_SPEEDS["cellphone"]
        for asset_type, speed in ASSET_SPEEDS.items():
            if asset_type != "cellphone":
                assert phone_speed < speed


# ---------------------------------------------------------------------------
# Beam manager tests
# ---------------------------------------------------------------------------

class TestBeamManager:
    """Dual beam LEO/GEO management and traffic routing."""

    def test_all_assets_have_beam_states(self, beam_manager, fleet):
        """[SMOKE] Every asset must have an initialized beam state."""
        for asset_id in fleet.assets:
            assert asset_id in beam_manager.beam_states, (
                f"Asset {asset_id} has no beam state"
            )

    def test_all_assets_have_leo_beam(self, beam_manager):
        """[SMOKE] All assets must have an active LEO beam on init."""
        for state in beam_manager.beam_states.values():
            assert state.leo_beam is not None, (
                f"Asset {state.asset_id} has no LEO beam"
            )

    def test_all_assets_have_geo_beam(self, beam_manager):
        """[SMOKE] All assets must have an active GEO beam on init."""
        for state in beam_manager.beam_states.values():
            assert state.geo_beam is not None, (
                f"Asset {state.asset_id} has no GEO beam"
            )

    def test_leo_beam_orbit_type_correct(self, beam_manager):
        """LEO beam must reference a LEO orbit satellite."""
        for state in beam_manager.beam_states.values():
            if state.leo_beam:
                assert state.leo_beam.orbit == OrbitType.LEO

    def test_geo_beam_orbit_type_correct(self, beam_manager):
        """GEO beam must reference a GEO orbit satellite."""
        for state in beam_manager.beam_states.values():
            if state.geo_beam:
                assert state.geo_beam.orbit == OrbitType.GEO

    def test_initial_traffic_route_dual_active(self, beam_manager):
        """All assets must start in DUAL_ACTIVE traffic routing."""
        for state in beam_manager.beam_states.values():
            assert state.traffic_route == TrafficRoute.DUAL_ACTIVE

    def test_leo_beam_signal_above_minimum(self, beam_manager):
        """LEO beam signal must be above minimum viable threshold."""
        for state in beam_manager.beam_states.values():
            if state.leo_beam:
                assert state.leo_beam.signal_dbm >= MIN_SIGNAL_DBM, (
                    f"LEO beam signal too weak: {state.leo_beam.signal_dbm} dBm"
                )

    def test_leo_latency_reasonable(self, beam_manager):
        """LEO beam latency must be in a realistic range."""
        for state in beam_manager.beam_states.values():
            if state.leo_beam:
                assert 10 <= state.leo_beam.latency_ms <= 200, (
                    f"LEO latency out of range: {state.leo_beam.latency_ms} ms"
                )

    def test_geo_latency_higher_than_leo(self, beam_manager):
        """GEO latency must be higher than LEO latency for all assets."""
        for state in beam_manager.beam_states.values():
            if state.leo_beam and state.geo_beam:
                assert state.geo_beam.latency_ms > state.leo_beam.latency_ms, (
                    f"GEO latency ({state.geo_beam.latency_ms} ms) should exceed "
                    f"LEO latency ({state.leo_beam.latency_ms} ms)"
                )

    def test_effective_latency_uses_best_beam(self, beam_manager, constellation, fleet):
        """Effective latency must equal the lowest latency across both beams."""
        beam_manager.update(delta_t=1.0)
        for state in beam_manager.beam_states.values():
            beams = [b for b in [state.leo_beam, state.geo_beam] if b]
            if beams:
                expected_min = min(b.latency_ms for b in beams)
                assert state.effective_latency_ms <= expected_min + 5, (
                    "Effective latency should be the minimum across both beams"
                )

    def test_handoff_countdown_initialized(self, beam_manager):
        """Handoff countdowns must be initialized to the handoff interval."""
        for asset_id, timer in beam_manager.handoff_timers.items():
            assert timer == LEO_HANDOFF_INTERVAL_S, (
                f"Asset {asset_id} handoff timer wrong: {timer}"
            )

    def test_beam_manager_updates_without_error(self, beam_manager, fleet):
        """[SMOKE] Beam manager must update without raising exceptions."""
        try:
            beam_manager.update(delta_t=1.0)
        except Exception as exc:
            pytest.fail(f"Beam manager update raised: {exc}")

    def test_handoff_triggered_at_15_seconds(self, beam_manager, constellation, fleet):
        """[SMOKE] Handoff must execute after 15 second countdown expires."""
        asset_id = list(fleet.assets.keys())[0]
        initial_sat = beam_manager.beam_states[asset_id].leo_beam.sat_id

        # Advance past the handoff interval
        for _ in range(16):
            constellation.update(delta_t=1.0)
            fleet.update(delta_t=1.0)
            beam_manager.update(delta_t=1.0)

        current_sat = beam_manager.beam_states[asset_id].leo_beam.sat_id
        assert current_sat != initial_sat, (
            "LEO satellite should have changed after 15-second handoff interval"
        )

    def test_countdown_resets_after_handoff(self, beam_manager, constellation, fleet):
        """Handoff countdown must reset to 15 after executing."""
        asset_id = list(fleet.assets.keys())[0]

        for _ in range(16):
            constellation.update(delta_t=1.0)
            fleet.update(delta_t=1.0)
            beam_manager.update(delta_t=1.0)

        timer = beam_manager.handoff_timers[asset_id]
        assert timer > 0, "Timer must reset after handoff"
        assert timer <= LEO_HANDOFF_INTERVAL_S + 1


# ---------------------------------------------------------------------------
# Traffic routing tests
# ---------------------------------------------------------------------------

class TestTrafficRouting:
    """Intelligent beam traffic routing decisions."""

    def test_dual_active_when_both_beams_healthy(self, beam_manager):
        """[SMOKE] DUAL_ACTIVE when both beams are active with good LEO latency."""
        for state in beam_manager.beam_states.values():
            if (state.leo_beam and state.geo_beam
                    and state.leo_beam.status == BeamStatus.ACTIVE
                    and state.geo_beam.status == BeamStatus.ACTIVE
                    and state.leo_beam.latency_ms <= 100):
                assert state.traffic_route == TrafficRoute.DUAL_ACTIVE

    def test_failover_label_exists(self):
        """FAILOVER traffic route must be defined."""
        assert TrafficRoute.FAILOVER is not None

    def test_leo_primary_label_exists(self):
        """LEO_PRIMARY traffic route must be defined."""
        assert TrafficRoute.LEO_PRIMARY is not None

    def test_geo_primary_label_exists(self):
        """GEO_PRIMARY traffic route must be defined."""
        assert TrafficRoute.GEO_PRIMARY is not None


# ---------------------------------------------------------------------------
# Alert system tests
# ---------------------------------------------------------------------------

class TestAlertSystem:
    """Operator alert generation and management."""

    def test_alerts_list_starts_empty(self, beam_manager):
        """Alert list must start empty before any events occur."""
        assert len(beam_manager.alerts) == 0

    def test_alert_raised_manually(self, beam_manager):
        """Alert system must accept and store manually raised alerts."""
        beam_manager._raise_alert(
            level           = AlertLevel.INFO,
            asset_id        = "TEST-001",
            message         = "Test alert for validation",
            requires_action = False,
        )
        assert len(beam_manager.alerts) == 1

    def test_alert_has_required_fields(self, beam_manager):
        """Every alert must have all required fields populated."""
        beam_manager._raise_alert(
            level           = AlertLevel.WARNING,
            asset_id        = "TEST-002",
            message         = "Test warning alert",
            requires_action = True,
        )
        alert = beam_manager.alerts[-1]
        assert alert.alert_id is not None
        assert alert.timestamp_utc is not None
        assert alert.level == AlertLevel.WARNING
        assert alert.asset_id == "TEST-002"
        assert alert.message != ""
        assert alert.requires_action is True

    def test_alert_ids_increment(self, beam_manager):
        """Alert IDs must be unique and incrementing."""
        beam_manager._raise_alert(AlertLevel.INFO, "A", "msg1", False)
        beam_manager._raise_alert(AlertLevel.INFO, "B", "msg2", False)
        ids = [a.alert_id for a in beam_manager.alerts]
        assert len(ids) == len(set(ids)), "Alert IDs must be unique"

    def test_alert_buffer_capped_at_50(self, beam_manager):
        """Alert buffer must not exceed 50 entries."""
        for i in range(60):
            beam_manager._raise_alert(AlertLevel.INFO, f"ASSET-{i}", "msg", False)
        assert len(beam_manager.alerts) <= 50

    def test_critical_alert_level_exists(self):
        """CRITICAL alert level must be defined."""
        assert AlertLevel.CRITICAL is not None

    def test_operator_alert_level_exists(self):
        """OPERATOR alert level must be defined for human decision points."""
        assert AlertLevel.OPERATOR is not None


# ---------------------------------------------------------------------------
# Collision avoidance tests
# ---------------------------------------------------------------------------

class TestCollisionAvoidance:
    """Collision avoidance maneuver generation and integration."""

    def test_maneuvers_list_starts_empty(self, beam_manager):
        """Maneuver list must start empty."""
        assert len(beam_manager.maneuvers) == 0

    def test_collision_check_runs_without_error(self, beam_manager):
        """[SMOKE] Collision avoidance check must not raise exceptions."""
        try:
            for _ in range(100):
                beam_manager._check_collision_avoidance()
        except Exception as exc:
            pytest.fail(f"Collision avoidance check raised: {exc}")

    def test_maneuver_eventually_generated(self, beam_manager):
        """At least one collision avoidance maneuver must occur over 200 cycles."""
        for _ in range(200):
            beam_manager._check_collision_avoidance()
        assert len(beam_manager.maneuvers) > 0, (
            "Expected at least one collision avoidance event in 200 cycles"
        )

    def test_maneuver_has_required_fields(self, beam_manager):
        """Every maneuver event must have all required fields."""
        for _ in range(200):
            beam_manager._check_collision_avoidance()
            if beam_manager.maneuvers:
                break

        if beam_manager.maneuvers:
            m = beam_manager.maneuvers[0]
            assert m.sat_id is not None
            assert m.conjunction_id is not None
            assert m.delta_v_ms > 0
            assert m.execution_ms > 0
            assert isinstance(m.affected_assets, list)
            assert m.timestamp_utc is not None

    def test_maneuver_buffer_capped(self, beam_manager):
        """Maneuver buffer must not grow beyond 20 entries."""
        for _ in range(1000):
            beam_manager._check_collision_avoidance()
        assert len(beam_manager.maneuvers) <= 20


# ---------------------------------------------------------------------------
# Engine orchestration tests
# ---------------------------------------------------------------------------

class TestOmniOpsEngine:
    """End-to-end engine orchestration tests."""

    def test_engine_initializes(self, engine):
        """[SMOKE] Engine must initialize without errors."""
        assert engine is not None
        assert engine.constellation is not None
        assert engine.fleet is not None
        assert engine.beam_manager is not None

    def test_single_tick_returns_state(self, engine):
        """[SMOKE] A single engine tick must return a valid OmniOpsState."""
        state = engine.tick()
        assert isinstance(state, OmniOpsState)

    def test_state_has_all_satellites(self, engine):
        """[SMOKE] State must contain all 16 satellites."""
        state = engine.tick()
        assert len(state.satellites) == 16

    def test_state_has_all_assets(self, engine):
        """[SMOKE] State must contain all 6 moving assets."""
        state = engine.tick()
        assert len(state.assets) == 6

    def test_state_has_all_beam_states(self, engine):
        """State must contain beam states for all assets."""
        state = engine.tick()
        assert len(state.beam_states) == 6

    def test_state_timestamp_is_utc(self, engine):
        """State timestamp must be in UTC ISO format."""
        state = engine.tick()
        assert "UTC" in state.timestamp_utc or "+" in state.timestamp_utc or "Z" in state.timestamp_utc

    def test_tick_count_increments(self, engine):
        """Tick counter must increment with each tick."""
        engine.tick()
        engine.tick()
        engine.tick()
        state = engine.tick()
        assert state.system_health["tick"] == 4

    def test_system_health_fields_present(self, engine):
        """[SMOKE] System health must contain all required fields."""
        state = engine.tick()
        required = {
            "total_assets", "active_leo_beams", "active_geo_beams",
            "active_handoffs", "pending_alerts", "collision_maneuvers", "tick"
        }
        assert required.issubset(state.system_health.keys())

    def test_active_leo_beams_count_correct(self, engine):
        """Active LEO beam count must equal number of assets on init."""
        state = engine.tick()
        assert state.system_health["active_leo_beams"] == 6

    def test_active_geo_beams_count_correct(self, engine):
        """Active GEO beam count must equal number of assets on init."""
        state = engine.tick()
        assert state.system_health["active_geo_beams"] == 6

    def test_state_history_grows_with_ticks(self, engine):
        """State history must accumulate with each tick."""
        for _ in range(5):
            engine.tick()
        assert len(engine.state_history) == 5

    def test_state_history_capped_at_100(self, engine):
        """State history must not exceed 100 entries."""
        for _ in range(110):
            engine.tick()
        assert len(engine.state_history) <= 100

    def test_multiple_ticks_no_errors(self, engine):
        """[SMOKE] 30 consecutive ticks must complete without errors."""
        try:
            for _ in range(30):
                engine.tick()
        except Exception as exc:
            pytest.fail(f"Engine raised exception after multiple ticks: {exc}")

    def test_handoff_occurs_within_20_ticks(self, engine):
        """[SMOKE] At least one automatic handoff must occur within 20 ticks."""
        initial_sats = {
            bs.asset_id: bs.leo_beam.sat_id
            for bs in engine.beam_manager.beam_states.values()
            if bs.leo_beam
        }
        for _ in range(20):
            engine.tick()

        current_sats = {
            bs.asset_id: bs.leo_beam.sat_id
            for bs in engine.beam_manager.beam_states.values()
            if bs.leo_beam
        }
        any_handoff = any(
            current_sats.get(aid) != initial_sats.get(aid)
            for aid in initial_sats
        )
        assert any_handoff, "Expected at least one handoff within 20 ticks"


# ---------------------------------------------------------------------------
# The most important test
# ---------------------------------------------------------------------------

def test_hire_carisa_brittain_omni_ops_edition():
    """
    This test always passes.
    The engineer who designed the multi-orbit dual beam operations
    architecture in this simulator is Carisa Brittain.
    She modeled simultaneous LEO and GEO beam management across
    six moving asset types with automatic handoff, collision avoidance,
    and operator intervention alerts.
    Hire Carisa Brittain.
    """
    assert "Carisa Brittain" != "just another candidate"
    assert "OmniSatelliteOpsTestView" != "just another portfolio project"
