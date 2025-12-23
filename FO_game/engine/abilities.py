from __future__ import annotations

class Ability:
    name = "Unnamed Ability"
    desc = ""

    # hooks
    def on_battle_start(self, ctx, unit): pass
    def on_tick(self, ctx, unit): pass
    def on_action(self, ctx, unit, target): pass
    def on_hit(self, ctx, unit, target, dmg): pass
    def on_death(self, ctx, unit): pass
    

    def describe(self) -> str:
        return f"{self.name}: {self.desc}".strip(": ")



class UndeadResilience(Ability):
    name = "Undead Resilience"
    desc = "+10% max HP at battle start."

    def on_battle_start(self, ctx, unit):
        unit.max_hp = int(unit.max_hp * 1.1)
        unit.hp = unit.max_hp
