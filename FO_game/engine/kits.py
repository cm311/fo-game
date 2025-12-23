from __future__ import annotations
from .abilities import Ability

class UndeadResilience(Ability):
    name = "Undead Resilience"
    def on_battle_start(self, ctx, unit):
        # small starting HP bump
        unit.max_hp = int(unit.max_hp * 1.10)
        unit.hp = unit.max_hp
        ctx.event(ctx.tick, "passive", unit.tag, None, None, {"name": self.name, "effect": "+10% max HP"})

class BackRowChannel(Ability):
    name = "Back Row Channel"
    def on_action(self, ctx, unit, target):
        # tiny bonus magic damage if in back row (stacks with formation bonus)
        if unit.row == "back":
            unit.temp_mods["magic_mult"] *= 1.05
            ctx.event(ctx.tick, "passive", unit.tag, None, None, {"name": self.name, "effect": "+5% magic mult this action"})

def get_kit_for(hero_base) -> list[Ability]:
    # minimal mapping: faction -> passives
    if hero_base.faction == "Undead":
        return [UndeadResilience()]
    if hero_base.faction == "Wild":
        return [BackRowChannel()]
    return []
