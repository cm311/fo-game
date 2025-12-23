from dataclasses import dataclass
from typing import List, Dict, Any

@dataclass
class BattleEvent:
    tick: int
    type: str
    source: str | None
    target: str | None
    value: int | None = None
    meta: Dict[str, Any] | None = None


BattleResult = Dict[str, Any]
"""
BattleResult contract:

{
  "winner": "player" | "enemy" | "draw",
  "log": List[BattleEvent],
  "mvp": HeroInstance | None,
  "xp": { hero_instance_id: xp_gained },
}
"""
