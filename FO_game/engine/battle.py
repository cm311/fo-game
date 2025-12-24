from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, List, Optional

from .stats import calc_stats
from .kits import get_kit_for

# =========================
# CONFIG
# =========================

TURN_THRESHOLD = 100
SPEED_TO_AP_DIVISOR = 40
DEFAULT_TICK_LIMIT = 100
DEFAULT_TICK_LIMIT_STEP = 400

PHASE_RUNNING = "RUNNING"
PHASE_PLAYER_PAUSE = "PLAYER_PAUSE"
PHASE_ENDED = "ENDED"

ROWS_3 = ("front", "mid", "back")


# =========================
# RUNTIME TYPES
# =========================

@dataclass
class UnitRuntime:
    tag: str  # unique string for logs ("p:123" or "e:0")
    id: int | None
    name: str
    level: int
    row: str  # "front" / "mid" / "back"
    slot: int
    stats: dict
    hp: int
    max_hp: int
    faction: str = ""  # REQUIRED for re-hydrating kits
    ap: int = 0
    abilities: list = field(default_factory=list)

    # Per-battle contribution stats (for XP)
    damage_dealt: int = 0
    kills: int = 0

    # Per-action mods
    temp_mods: dict = field(default_factory=dict)

    @property
    def alive(self):
        return self.hp > 0


@dataclass
class BattleContext:
    tick: int
    log: list
    player_units: list[UnitRuntime]
    enemy_units: list[UnitRuntime]
    seed: int | None = None

    def event(self, tick, type_, source, target, value=None, meta=None):
        self.log.append({
            "tick": tick,
            "type": type_,
            "source": source,
            "target": target,
            "value": value,
            "meta": meta or {}
        })


# =========================
# SERIALIZATION
# =========================

def _unit_to_dict(u: UnitRuntime) -> dict:
    """
    Convert runtime unit to JSON-serializable dict.
    NOTE: We do NOT store 'abilities' here; they are code objects.
    We re-hydrate them using 'faction' on load.
    """
    return {
        "tag": u.tag,
        "id": u.id,
        "name": u.name,
        "level": u.level,
        "row": u.row,
        "slot": u.slot,
        "stats": u.stats,
        "hp": u.hp,
        "max_hp": u.max_hp,
        "faction": u.faction,
        "ap": u.ap,
        "damage_dealt": u.damage_dealt,
        "kills": u.kills,
        # temp_mods are transient per action, usually safe to reset or store if needed.
        # For MVP we reset them.
    }

def _unit_from_dict(d: dict) -> UnitRuntime:
    return UnitRuntime(
        tag=d["tag"],
        id=d["id"],
        name=d["name"],
        level=d["level"],
        row=d["row"],
        slot=d["slot"],
        stats=d["stats"],
        hp=d["hp"],
        max_hp=d["max_hp"],
        faction=d.get("faction", ""),
        ap=d.get("ap", 0),
        damage_dealt=d.get("damage_dealt", 0),
        kills=d.get("kills", 0),
        abilities=[],  # Will be re-hydrated
    )


# =========================
# PUBLIC API
# =========================

def build_units_from_instances(side: str, instances: list, formation: dict) -> list[UnitRuntime]:
    """
    Convert Django models -> UnitRuntime.
    formation = { instance_id: ("front", 0), ... }
    """
    out = []
    for inst in instances:
        row, slot = formation.get(inst.id, ("front", 0))
        st = calc_stats(inst.hero_base, inst.level)
        
        u = UnitRuntime(
            tag=f"{side[0]}:{inst.id}",
            id=inst.id,
            name=inst.hero_base.name,
            level=inst.level,
            row=row,
            slot=slot,
            stats=st,
            hp=st["hp"],
            max_hp=st["hp"],
            faction=inst.hero_base.faction,  # Store faction for kit lookup
            ap=random.randint(0, 20),  # minor stagger
        )
        
        # Initial kit load
        u.abilities = get_kit_for(inst.hero_base)
        out.append(u)
    return out


def build_enemy_units(bases: list, level=1) -> list[UnitRuntime]:
    out = []
    for i, base in enumerate(bases):
        st = calc_stats(base, level)
        # simplistic enemy formation: fill front, then mid
        row = "front" if i < 3 else "mid"
        slot = i % 3
        
        u = UnitRuntime(
            tag=f"e:{i}",
            id=None,  # Enemy mobs usually don't have DB IDs
            name=base.name,
            level=level,
            row=row,
            slot=slot,
            stats=st,
            hp=st["hp"],
            max_hp=st["hp"],
            faction=base.faction,
            ap=random.randint(0, 20),
        )
        u.abilities = get_kit_for(base)
        out.append(u)
    return out


def battle_state_new(player_units, enemy_units, seed=None, tick_limit=DEFAULT_TICK_LIMIT):
    return {
        "phase": PHASE_RUNNING,
        "tick": 0,
        "tick_limit": tick_limit,
        "log": [],
        "player_units": [_unit_to_dict(u) for u in player_units],
        "enemy_units": [_unit_to_dict(u) for u in enemy_units],
        "seed": seed,
        "winner": None,
    }


def battle_state_advance_until_pause(state: dict) -> dict:
    if state["phase"] == PHASE_ENDED:
        return state

    # 1. Deserialize
    player_units = [_unit_from_dict(d) for d in state["player_units"]]
    enemy_units = [_unit_from_dict(d) for d in state["enemy_units"]]
    
    # 2. RE-HYDRATE KITS (Critical Fix)
    # We need a mock object because get_kit_for expects a model with a .faction attribute
    @dataclass
    class MockHeroBase:
        faction: str

    all_units = player_units + enemy_units
    for u in all_units:
        mock_base = MockHeroBase(faction=u.faction)
        u.abilities = get_kit_for(mock_base)

    # 3. Setup Context
    ctx = BattleContext(
        tick=state["tick"],
        log=state["log"],
        player_units=player_units,
        enemy_units=enemy_units,
        seed=state.get("seed"),
    )

    limit = state["tick_limit"]

    # 4. Resume Loop
    while ctx.tick < limit:
        # Check Win/Loss
        if not any(u.alive for u in player_units):
            state["phase"] = PHASE_ENDED
            state["winner"] = "enemy"
            break
        if not any(u.alive for u in enemy_units):
            state["phase"] = PHASE_ENDED
            state["winner"] = "player"
            break

        # A. Start Tick hooks
        for u in all_units:
            if u.alive:
                for ab in u.abilities:
                    ab.on_tick(ctx, u)

        # B. AP Growth
        ready_player = None
        for u in all_units:
            if u.alive:
                speed = u.stats.get("speed", 10)
                # Gain AP
                gain = max(1, speed // SPEED_TO_AP_DIVISOR)
                u.ap += gain
                
                # Check ready
                if u.ap >= TURN_THRESHOLD:
                    if u in player_units:
                        # If multiple players ready, pick first (simplest)
                        if ready_player is None:
                            ready_player = u
                    else:
                        # Enemy acts immediately (AI)
                        _resolve_turn(ctx, u, is_player=False)

        # C. Player Pause?
        # If a player unit is ready, we pause BEFORE they act, 
        # allowing the UI to send an act command.
        if ready_player:
            state["phase"] = PHASE_PLAYER_PAUSE
            break

        ctx.tick += 1

    # 5. Save State
    state["tick"] = ctx.tick
    state["log"] = ctx.log # logs appended in place
    state["player_units"] = [_unit_to_dict(u) for u in player_units]
    state["enemy_units"] = [_unit_to_dict(u) for u in enemy_units]

    # XP Calculation (embedded in result if ended)
    if state["phase"] == PHASE_ENDED and state["winner"] == "player":
        xp_map = {}
        for u in player_units:
            if u.id:
                # Simple XP formula: Base 100 + 5% of damage + 50 per kill
                xp = 100 + int(u.damage_dealt * 0.05) + (u.kills * 50)
                xp_map[u.id] = xp
        state["xp"] = xp_map

    return state


def battle_state_player_basic_attack(state: dict, target_side: str, target_row: str, target_slot: int) -> dict:
    """
    Called when the user clicks a target while in PLAYER_PAUSE.
    Finds the ready player unit and executes an attack.
    """
    if state["phase"] != PHASE_PLAYER_PAUSE:
        return state

    # Re-load
    player_units = [_unit_from_dict(d) for d in state["player_units"]]
    enemy_units = [_unit_from_dict(d) for d in state["enemy_units"]]
    
    # Re-hydrate kits needed for on_action/on_hit
    @dataclass
    class MockHeroBase:
        faction: str
    for u in player_units + enemy_units:
        u.abilities = get_kit_for(MockHeroBase(faction=u.faction))

    ctx = BattleContext(
        tick=state["tick"],
        log=state["log"],
        player_units=player_units,
        enemy_units=enemy_units,
    )

    # Find the actor (first ready player unit)
    actor = next((u for u in player_units if u.alive and u.ap >= TURN_THRESHOLD), None)
    if not actor:
        # Should not happen if logic is sound, but safety first
        state["phase"] = PHASE_RUNNING
        return state

    # Validate Target
    targets_pool = enemy_units if target_side == "enemy" else player_units
    target = next((u for u in targets_pool if u.alive and u.row == target_row and u.slot == int(target_slot)), None)
    
    # Check targetability rules (e.g. back row protection)
    # If invalid target, we could return error, but for now we just log and do nothing
    # or fallback to auto-target. Let's try to act if valid.
    if target and _is_targetable(target, targets_pool):
        _execute_attack(ctx, actor, target)
        actor.ap -= TURN_THRESHOLD  # Deduct AP
        state["phase"] = PHASE_RUNNING  # Resume
    else:
        # Invalid target selected
        # In a real app, return error. For MVP, log it.
        ctx.event(ctx.tick, "error", actor.tag, None, meta={"msg": "Invalid target"})

    # Save
    state["tick"] = ctx.tick
    state["player_units"] = [_unit_to_dict(u) for u in player_units]
    state["enemy_units"] = [_unit_to_dict(u) for u in enemy_units]
    
    return state


def battle_state_snapshot(state: dict) -> dict:
    """
    Clean output for the frontend.
    """
    return {
        "tick": state["tick"],
        "tick_limit": state["tick_limit"],
        "phase": state["phase"],
        "winner": state["winner"],
        "log": state.get("log", [])[-30:],  # last 30 entries
        "player": _squad_snapshot(state["player_units"]),
        "enemy": _squad_snapshot(state["enemy_units"]),
        "xp": state.get("xp", {})
    }


def _squad_snapshot(unit_dicts: list[dict]) -> dict:
    # Group by row for easier UI rendering
    rows = {"front": [], "mid": [], "back": []}
    for d in unit_dicts:
        if d["hp"] > 0:  # Only send living units? Or all? 
            # Send all so we can show dead bodies if we want, or just filter in UI
            pass
        # We send everything, UI decides visibility
        rows[d["row"]].append(d)
    
    # Sort by slot
    for k in rows:
        rows[k].sort(key=lambda x: x["slot"])
        
    return rows


# =========================
# INTERNAL LOGIC
# =========================

def _resolve_turn(ctx: BattleContext, actor: UnitRuntime, is_player: bool):
    """
    AI Logic / Auto-Battle resolution.
    """
    targets = ctx.player_units if not is_player else ctx.enemy_units
    target = _choose_target(actor, targets)
    
    if target:
        _execute_attack(ctx, actor, target)
    
    actor.ap -= TURN_THRESHOLD


def _choose_target(actor: UnitRuntime, enemies: list[UnitRuntime]) -> Optional[UnitRuntime]:
    """
    Simple AI: Prioritize Front -> Mid -> Back.
    """
    candidates = _targetable_enemies(enemies)
    if not candidates:
        return None
    return random.choice(candidates)


def _targetable_enemies(units: list[UnitRuntime]) -> list[UnitRuntime]:
    alive = [u for u in units if u.alive]
    front = [u for u in alive if u.row == "front"]
    mid = [u for u in alive if u.row == "mid"]
    back = [u for u in alive if u.row == "back"]

    if front: return front
    if mid: return mid
    return back

def _is_targetable(target: UnitRuntime, squad: list[UnitRuntime]) -> bool:
    """
    Validates if specific unit can be targeted.
    """
    if not target.alive: return False
    valid_targets = _targetable_enemies(squad)
    return target in valid_targets


def _execute_attack(ctx: BattleContext, actor: UnitRuntime, target: UnitRuntime):
    # 1. Hooks (On Action)
    for ab in actor.abilities:
        ab.on_action(ctx, actor, target)

    # 2. Calc Damage
    # Basic formula: (Atk - Def) * Multiplier
    atk = actor.stats["atk"]
    defense = target.stats["def"]
    
    # Mitigation: Armor style (Damage = Atk * 100 / (100 + Def))
    # OR Flat reduction with floor.
    # MVP Flat: max(1, atk - def)
    raw_dmg = max(1, atk - defense)
    
    # Random variance +/- 10%
    variance = random.uniform(0.9, 1.1)
    final_dmg = int(raw_dmg * variance)

    # 3. Apply
    target.hp = max(0, target.hp - final_dmg)

    # 4. Log
    ctx.event(ctx.tick, "damage", actor.tag, target.tag, final_dmg)
    
    # 5. Stats (XP)
    actor.damage_dealt += final_dmg

    # 6. On Hit hooks
    for ab in actor.abilities:
        ab.on_hit(ctx, actor, target, final_dmg)

    # 7. Death?
    if target.hp == 0:
        ctx.event(ctx.tick, "death", target.tag, None)
        actor.kills += 1
        for ab in target.abilities:
            ab.on_death(ctx, target)


# =========================
# ONE-SHOT BATTLE (Legacy / Testing)
# =========================

def run_battle(player_units, enemy_units, seed=None, tick_limit=DEFAULT_TICK_LIMIT):
    """
    Runs a full battle in one go. Returns summary.
    """
    state = battle_state_new(player_units, enemy_units, seed, tick_limit)
    state = battle_state_advance_until_pause(state)
    
    # If it paused (waiting for player), we force auto-play for the rest
    # effectively acting as an "Auto-Battle"
    while state["phase"] == PHASE_PLAYER_PAUSE:
        # Simulate player choice: pick random valid target
        p_units = [_unit_from_dict(d) for d in state["player_units"]]
        e_units = [_unit_from_dict(d) for d in state["enemy_units"]]
        
        actor = next((u for u in p_units if u.alive and u.ap >= TURN_THRESHOLD), None)
        if actor:
            targets = [u for u in e_units if u.alive] # simplify target logic for auto
            if targets:
                t = random.choice(targets)
                state = battle_state_player_basic_attack(state, "enemy", t.row, t.slot)
            else:
                # No targets? should end loop
                break
        
        # Advance again
        state = battle_state_advance_until_pause(state)

    return battle_state_snapshot(state)