from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from .stats import calc_stats
from .kits import get_kit_for

# =========================
# CONFIG
# =========================

TURN_THRESHOLD = 100

# "Speed" coming out of calc_stats is currently HUGE (thousands).
# We convert that speed into "AP gain per tick" by dividing it down.
# Tune this one number only if needed.
SPEED_TO_AP_DIVISOR = 100  # higher = slower turns

DEFAULT_TICK_LIMIT = 100
DEFAULT_TICK_LIMIT_STEP = 400  # your MVP target

PHASE_RUNNING = "RUNNING"
PHASE_AWAIT_PLAYER = "AWAIT_PLAYER_ACTION"
PHASE_ENDED = "ENDED"


# =========================
# DATA TYPES
# =========================

@dataclass
class UnitRuntime:
    # id is HeroInstance.id for player units; None for enemy units
    id: int | None
    side: str  # "player" or "enemy"
    name: str
    level: int
    row: str  # "front" or "back"
    slot: int
    stats: dict
    hp: int
    max_hp: int
    ap: int = 0
    abilities: list = field(default_factory=list)

    # per-action mods
    temp_mods: dict[str, float] = field(default_factory=dict)

    @property
    def alive(self) -> bool:
        return self.hp > 0

    @property
    def tag(self) -> str:
        if self.id is None:
            return f"{self.name}"
        return f"{self.name}#{self.id}"


@dataclass
class BattleContext:
    rng: random.Random
    tick: int = 0
    log: list[dict] = field(default_factory=list)

    def event(
        self,
        tick: int,
        type_: str,
        source: str | None,
        target: str | None,
        value: int | None = None,
        meta: dict | None = None,
    ):
        self.log.append(
            {
                "tick": tick,
                "type": type_,
                "source": source,
                "target": target,
                "value": value,
                "meta": meta or {},
            }
        )


# =========================
# HELPERS (combat)
# =========================

def _formation_mult(unit: UnitRuntime) -> tuple[float, float, float]:
    """
    Returns: (phys_mult, magic_mult, target_bias)
    Front: +15% phys dmg dealt, slightly higher target chance
    Back: +5% magic dmg dealt
    """
    if unit.row == "front":
        return (1.15, 1.00, 1.20)
    return (1.00, 1.05, 1.00)


def _choose_target(ctx: BattleContext, attacker: UnitRuntime, enemies: list[UnitRuntime]) -> UnitRuntime | None:
    living = [u for u in enemies if u.alive]
    if not living:
        return None

    # bias front row slightly (based on TARGET row)
    weights: list[float] = []
    for u in living:
        _, _, bias = _formation_mult(u)
        weights.append(bias)

    return ctx.rng.choices(living, weights=weights, k=1)[0]


def _deal_damage(ctx: BattleContext, attacker: UnitRuntime, target: UnitRuntime) -> int:
    attacker.temp_mods = {"phys_mult": 1.0, "magic_mult": 1.0}

    # abilities can adjust temp_mods on_action
    for ab in attacker.abilities:
        ab.on_action(ctx, attacker, target)

    base = max(int(attacker.stats["atk"] - 0.5 * target.stats["def"]), 1)

    phys_mult, _, _ = _formation_mult(attacker)
    dmg = int(base * phys_mult * attacker.temp_mods["phys_mult"])

    target.hp = max(target.hp - dmg, 0)

    ctx.event(
        ctx.tick,
        "attack",
        attacker.tag,
        target.tag,
        dmg,
        {"row": attacker.row, "target_row": target.row},
    )

    # on_hit hooks
    for ab in attacker.abilities:
        ab.on_hit(ctx, attacker, target, dmg)

    if target.hp <= 0:
        ctx.event(ctx.tick, "death", target.tag, None, None, {})
        for ab in target.abilities:
            ab.on_death(ctx, target)

    return dmg


def _ap_gain_per_tick(stats: dict) -> int:
    """
    Convert your big 'speed' stat into a small AP gain per tick.
    Always returns at least 1 so everyone eventually acts.
    """
    spd = int(stats.get("speed", 1))
    return max(1, int(spd / SPEED_TO_AP_DIVISOR))


# =========================
# BUILD UNITS
# =========================

def build_units_from_instances(side: str, hero_instances: list, formation: dict[int, tuple[str, int]]) -> list[UnitRuntime]:
    """
    formation maps hero_instance.id -> (row, slot)
    row: "front" or "back"
    slot: 0..1 for front, 0..2 for back
    """
    units: list[UnitRuntime] = []
    for inst in hero_instances:
        row, slot = formation.get(inst.id, ("back", 0))
        stats = calc_stats(inst.hero_base, inst.level)
        unit = UnitRuntime(
            id=inst.id,
            side=side,
            name=inst.hero_base.name,
            level=inst.level,
            row=row,
            slot=slot,
            stats=stats,
            hp=stats["hp"],
            max_hp=stats["hp"],
            abilities=get_kit_for(inst.hero_base),
        )
        units.append(unit)
    return units


def build_enemy_units(hero_bases: list, level: int = 1) -> list[UnitRuntime]:
    """
    Enemy is made from HeroBase objects (no instances yet).
    """
    units: list[UnitRuntime] = []
    for i, hb in enumerate(hero_bases[:5]):
        row = "front" if i < 2 else "back"
        slot = i if i < 2 else (i - 2)
        stats = calc_stats(hb, level)
        unit = UnitRuntime(
            id=None,
            side="enemy",
            name=hb.name,
            level=level,
            row=row,
            slot=slot,
            stats=stats,
            hp=stats["hp"],
            max_hp=stats["hp"],
            abilities=get_kit_for(hb),
        )
        units.append(unit)
    return units


# =========================
# AUTO-RUN BATTLE (non-step)
# =========================

def run_battle(
    player_units: list[UnitRuntime],
    enemy_units: list[UnitRuntime],
    seed: int | None = None,
    tick_limit: int = DEFAULT_TICK_LIMIT,
) -> dict[str, Any]:
    rng = random.Random(seed)
    ctx = BattleContext(rng=rng)
    ctx.event(0, "start", None, None, None, {"tick_limit": tick_limit})

    # start hooks
    for u in player_units + enemy_units:
        for ab in u.abilities:
            ab.on_battle_start(ctx, u)

    damage_done: dict[str, int] = {}
    actions_taken: dict[str, int] = {}

    winner: str | None = None

    for tick in range(1, tick_limit + 1):
        ctx.tick = tick

        # tick hooks
        for u in player_units + enemy_units:
            if u.alive:
                for ab in u.abilities:
                    ab.on_tick(ctx, u)

        # AP accumulation (scaled + clamped)
        for u in player_units + enemy_units:
            if u.alive:
                u.ap = min(TURN_THRESHOLD, u.ap + _ap_gain_per_tick(u.stats))

        # resolve as many actions as possible this tick
        while True:
            if not any(u.alive for u in player_units):
                winner = "enemy"
                break
            if not any(u.alive for u in enemy_units):
                winner = "player"
                break

            ready = [u for u in (player_units + enemy_units) if u.alive and u.ap >= TURN_THRESHOLD]
            if not ready:
                break

            # pick next actor: highest speed, then random tie-breaker
            ready.sort(key=lambda u: (u.stats.get("speed", 0), rng.random()), reverse=True)
            actor = ready[0]

            actor.ap = 0
            actions_taken[actor.tag] = actions_taken.get(actor.tag, 0) + 1

            enemies = enemy_units if actor.side == "player" else player_units
            target = _choose_target(ctx, actor, enemies)
            if target is None:
                continue

            dmg = _deal_damage(ctx, actor, target)
            damage_done[actor.tag] = damage_done.get(actor.tag, 0) + dmg

        if winner is not None:
            break

    if winner is None:
        winner = "draw"

    ctx.event(ctx.tick, "end", None, None, None, {"winner": winner})

    # MVP
    mvp = None
    if winner in ("player", "enemy"):
        side_units = player_units if winner == "player" else enemy_units
        best = None
        best_dmg = -1
        for u in side_units:
            d = damage_done.get(u.tag, 0)
            if d > best_dmg:
                best_dmg = d
                best = u
        if best:
            mvp = {"side": best.side, "unit_id": best.id, "name": best.name, "damage": best_dmg}

    # XP
    xp_map: dict[int, int] = {}
    if winner == "player":
        base_xp = 120
    elif winner == "draw":
        base_xp = 60
    else:
        base_xp = 30

    for u in player_units:
        if u.id is not None:
            bonus = 10 * actions_taken.get(u.tag, 0)
            xp_map[u.id] = base_xp + bonus

    def _fmt_team(units: list[UnitRuntime]):
        front = [f"{u.name} (Lv {u.level})" for u in units if u.row == "front"]
        back = [f"{u.name} (Lv {u.level})" for u in units if u.row == "back"]
        return {"front": front, "back": back}

    # highlights
    biggest = None
    for e in ctx.log:
        if e["type"] == "attack" and isinstance(e.get("value"), int):
            if biggest is None or e["value"] > biggest["value"]:
                biggest = e

    first_death = None
    for e in ctx.log:
        if e["type"] == "death":
            first_death = e
            break

    highlights: list[str] = []
    if biggest:
        highlights.append(
            f"Biggest hit: {biggest.get('source')} → {biggest.get('target')} for {biggest.get('value')}"
        )
    if first_death:
        highlights.append(f"First death: {first_death.get('source')}")
    if mvp:
        highlights.append(f"MVP: {mvp['name']} ({mvp['damage']} dmg)")

    return {
        "winner": winner,
        "log": ctx.log,
        "mvp": mvp,
        "xp": xp_map,
        "summary": {"player": _fmt_team(player_units), "enemy": _fmt_team(enemy_units)},
        "highlights": highlights,
        "final": {
            "player": [{"id": u.id, "name": u.name, "hp": u.hp, "max_hp": u.max_hp, "row": u.row} for u in player_units],
            "enemy": [{"id": None, "name": u.name, "hp": u.hp, "max_hp": u.max_hp, "row": u.row} for u in enemy_units],
        },
    }


# =========================
# STEP-BASED BATTLE (session state)
# =========================

def _unit_to_dict(u: UnitRuntime) -> dict:
    return {
        "id": u.id,
        "side": u.side,
        "name": u.name,
        "level": u.level,
        "row": u.row,
        "slot": u.slot,
        "stats": u.stats,
        "hp": u.hp,
        "max_hp": u.max_hp,
        "ap": u.ap,
    }


def _unit_from_dict(d: dict) -> UnitRuntime:
    return UnitRuntime(
        id=d.get("id"),
        side=d["side"],
        name=d["name"],
        level=d["level"],
        row=d["row"],
        slot=d["slot"],
        stats=d["stats"],
        hp=d["hp"],
        max_hp=d["max_hp"],
        ap=d.get("ap", 0),
        abilities=[],  # MVP: ignore passives/abilities for now
    )


def _fmt_units(units: list[UnitRuntime]) -> dict:
    """Return units grouped by row for UI."""
    front = [u for u in units if u.row == "front"]
    back = [u for u in units if u.row == "back"]

    front.sort(key=lambda u: (u.slot, u.id or 0, u.name))
    back.sort(key=lambda u: (u.slot, u.id or 0, u.name))

    return {"front": [_unit_to_dict(u) for u in front], "back": [_unit_to_dict(u) for u in back]}


def _check_winner(player_units: list[UnitRuntime], enemy_units: list[UnitRuntime]) -> str | None:
    if not any(u.alive for u in player_units):
        return "enemy"
    if not any(u.alive for u in enemy_units):
        return "player"
    return None


def _pick_next_ready_any(player_units: list[UnitRuntime], enemy_units: list[UnitRuntime], ctx: BattleContext) -> UnitRuntime | None:
    """
    Choose the next actor among units with AP >= threshold.
    Important: we DO NOT force player-first. We let speed decide,
    and use rng to break ties so enemies actually get turns.
    """
    ready = [u for u in (player_units + enemy_units) if u.alive and u.ap >= TURN_THRESHOLD]
    if not ready:
        return None
    ready.sort(
        key=lambda u: (u.stats.get("speed", 0), ctx.rng.random()),
        reverse=True,
    )
    return ready[0]


def battle_state_new(
    player_units: list[UnitRuntime],
    enemy_units: list[UnitRuntime],
    seed: int | None = None,
    tick_limit: int = DEFAULT_TICK_LIMIT_STEP,
) -> dict:
    rng = random.Random(seed)
    ctx = BattleContext(rng=rng)
    ctx.event(0, "start", None, None, None, {"tick_limit": tick_limit})

    return {
        "tick": 0,
        "tick_limit": tick_limit,
        "seed": seed,
        "winner": None,
        "phase": PHASE_RUNNING,
        "awaiting": None,  # {"actor_id": int}
        "log": ctx.log,
        "player_units": [_unit_to_dict(u) for u in player_units],
        "enemy_units": [_unit_to_dict(u) for u in enemy_units],
    }


def battle_state_snapshot(state: dict, log_tail: int = 40) -> dict:
    player_units = [_unit_from_dict(d) for d in state["player_units"]]
    enemy_units = [_unit_from_dict(d) for d in state["enemy_units"]]

    return {
        "tick": state["tick"],
        "tick_limit": state["tick_limit"],
        "phase": state["phase"],
        "winner": state["winner"],
        "awaiting": state["awaiting"],
        "player": _fmt_units(player_units),
        "enemy": _fmt_units(enemy_units),
        "log": (state["log"][-log_tail:] if state.get("log") else []),
        "ended": state["phase"] == PHASE_ENDED,
    }


def battle_state_advance_until_pause(state: dict) -> dict:
    """
    Advance time until:
    - a player is next to act => pause
    - battle ends
    - tick_limit reached => draw

    Enemy actions are auto-resolved.
    AP is a BAR only (0..100): it fills, hits 100, unit acts, then resets to 0.
    """
    rng = random.Random(state.get("seed"))
    ctx = BattleContext(rng=rng)
    ctx.log = state.get("log", [])

    player_units = [_unit_from_dict(d) for d in state["player_units"]]
    enemy_units = [_unit_from_dict(d) for d in state["enemy_units"]]

    if state.get("phase") == PHASE_ENDED:
        return state

    tick_limit = int(state.get("tick_limit", DEFAULT_TICK_LIMIT_STEP))

    while state["tick"] < tick_limit:
        state["tick"] += 1
        ctx.tick = state["tick"]

        # 1) Fill AP bars (scaled + clamped)
        for u in player_units + enemy_units:
            if u.alive:
                u.ap = min(TURN_THRESHOLD, u.ap + _ap_gain_per_tick(u.stats))

        # 2) Resolve as many actions as possible this "moment"
        while True:
            winner = _check_winner(player_units, enemy_units)
            if winner is not None:
                state["winner"] = winner
                state["phase"] = PHASE_ENDED
                ctx.event(ctx.tick, "end", None, None, None, {"winner": winner})
                break

            actor = _pick_next_ready_any(player_units, enemy_units, ctx)
            if actor is None:
                break  # nobody ready, go to next tick

            # If next is player, pause and wait for click
            if actor.side == "player":
                state["phase"] = PHASE_AWAIT_PLAYER
                state["awaiting"] = {"actor_id": actor.id}
                ctx.event(ctx.tick, "pause", actor.tag, None, None, {"ap": actor.ap})
                break

            # Enemy acts immediately
            actor.ap = 0
            target = _choose_target(ctx, actor, player_units)
            if target is None:
                continue
            _deal_damage(ctx, actor, target)

        if state["phase"] in (PHASE_AWAIT_PLAYER, PHASE_ENDED):
            break

    # 3) Tick limit => draw
    if state["tick"] >= tick_limit and state.get("phase") != PHASE_ENDED:
        state["winner"] = "draw"
        state["phase"] = PHASE_ENDED
        ctx.event(ctx.tick, "end", None, None, None, {"winner": "draw"})

    # persist
    state["log"] = ctx.log
    state["player_units"] = [_unit_to_dict(u) for u in player_units]
    state["enemy_units"] = [_unit_to_dict(u) for u in enemy_units]
    return state


def battle_state_player_basic_attack(state: dict, target_side: str, target_row: str, target_slot: int) -> dict:
    """
    Resolve ONE player action (basic attack), then advance until next pause/end.
    """
    if state.get("phase") != PHASE_AWAIT_PLAYER or not state.get("awaiting"):
        return state

    rng = random.Random(state.get("seed"))
    ctx = BattleContext(rng=rng)
    ctx.log = state.get("log", [])

    player_units = [_unit_from_dict(d) for d in state["player_units"]]
    enemy_units = [_unit_from_dict(d) for d in state["enemy_units"]]

    actor_id = state["awaiting"]["actor_id"]
    actor = next((u for u in player_units if u.id == actor_id and u.alive), None)
    if actor is None:
        state["phase"] = PHASE_RUNNING
        state["awaiting"] = None
        state["log"] = ctx.log
        state["player_units"] = [_unit_to_dict(u) for u in player_units]
        state["enemy_units"] = [_unit_to_dict(u) for u in enemy_units]
        return battle_state_advance_until_pause(state)

    if actor.ap < TURN_THRESHOLD:
        # not actually ready; resume
        state["phase"] = PHASE_RUNNING
        state["awaiting"] = None
        state["log"] = ctx.log
        state["player_units"] = [_unit_to_dict(u) for u in player_units]
        state["enemy_units"] = [_unit_to_dict(u) for u in enemy_units]
        return battle_state_advance_until_pause(state)

    targets = enemy_units if target_side == "enemy" else player_units
    target = next(
        (u for u in targets if u.alive and u.row == target_row and u.slot == int(target_slot)),
        None,
    )
    if target is None:
        ctx.event(ctx.tick, "error", actor.tag, None, None, {"message": "Invalid target"})
        state["log"] = ctx.log
        state["player_units"] = [_unit_to_dict(u) for u in player_units]
        state["enemy_units"] = [_unit_to_dict(u) for u in enemy_units]
        return state

    # resolve
    ctx.tick = state["tick"]
    actor.ap = 0
    _deal_damage(ctx, actor, target)

    # continue
    state["phase"] = PHASE_RUNNING
    state["awaiting"] = None
    state["log"] = ctx.log
    state["player_units"] = [_unit_to_dict(u) for u in player_units]
    state["enemy_units"] = [_unit_to_dict(u) for u in enemy_units]

    return battle_state_advance_until_pause(state)
