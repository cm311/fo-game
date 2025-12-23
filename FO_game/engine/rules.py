# FO_game/engine/rules.py

from dataclasses import dataclass
from typing import Optional, Dict, Any, List


@dataclass
class RuleError(Exception):
    code: str
    message: str
    details: Optional[Dict[str, Any]] = None


# ---------- Squad limits ----------

BASE_SQUAD_LIMIT = 5
EXTENDED_SQUAD_LIMIT = 6


def get_squad_limit(hero_instances) -> int:
    """
    Default = 5
    Later: undead / traits can raise this to 6.
    """
    # TODO: hook undead / trait logic here
    return BASE_SQUAD_LIMIT


# ---------- Formation rules ----------

def normalize_rows(front: list, back: list):
    front = (front + [None] * 6)[:6]
    back  = (back  + [None] * 6)[:6]
    return front, back


def validate_formation(front: list, back: list) -> None:
    front_count = sum(1 for x in front if x)
    back_count  = sum(1 for x in back if x)

    if front_count < 1:
        raise RuleError(
            code="NO_FRONT",
            message="You need at least 1 hero in the Front row."
        )

    if back_count < 1:
        raise RuleError(
            code="NO_BACK",
            message="You need at least 1 hero in the Back row."
        )


def validate_squad(front: list, back: list, roster_by_id: dict) -> None:
    front, back = normalize_rows(front, back)
    chosen = [x for x in (front + back) if x]

    if not chosen:
        raise RuleError(
            code="EMPTY_SQUAD",
            message="Pick at least 1 hero."
        )

    if len(set(chosen)) != len(chosen):
        raise RuleError(
            code="DUPLICATE",
            message="Duplicate hero selected."
        )

    for hid in chosen:
        if hid not in roster_by_id:
            raise RuleError(
                code="INVALID_HERO",
                message="Invalid hero selected.",
                details={"hero_id": hid}
            )

    limit = get_squad_limit([roster_by_id[i] for i in chosen])
    if len(chosen) > limit:
        raise RuleError(
            code="SQUAD_LIMIT",
            message=f"Maximum squad size is {limit}.",
            details={"limit": limit}
        )

    validate_formation(front, back)
