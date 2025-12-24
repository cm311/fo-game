# FO_game/engine/rules.py

from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Tuple


@dataclass
class RuleError(Exception):
    code: str
    message: str
    details: Optional[Dict[str, Any]] = None


# ============================================================
# EASY TO CHANGE STUFF (keep it here)
# ============================================================

BASE_SQUAD_LIMIT = 5          # max number of UNIQUE heroes (anchors) in squad
EXTENDED_SQUAD_LIMIT = 6      # reserved for future traits/factions that increase limit

# old layout (current live): 6 slots per row, 2 rows
OLD_COLS = 6

# new layout (future): 3 cols × 3 rows (front/mid/back)
NEW_COLS = 3


def get_squad_limit(hero_instances) -> int:
    """
    Default = 5.
    Later: traits/factions can raise this to 6+.
    """
    # TODO: hook trait logic here (undead, etc.)
    return BASE_SQUAD_LIMIT


# ============================================================
# HELPERS
# ============================================================

def _pad_or_trim(row: List[Any], cols: int) -> List[Optional[int]]:
    """
    Normalizes a row to exactly `cols` length with None.
    Also converts "", "0", 0 to None and casts ints where possible.
    """
    row = list(row or [])
    out: List[Optional[int]] = []
    for i in range(cols):
        v = row[i] if i < len(row) else None
        if v in ("", "0", 0):
            v = None
        if v is None:
            out.append(None)
        else:
            out.append(int(v))
    return out


def normalize_rows(front: list, back: list, mid: Optional[list] = None) -> Tuple[List[Optional[int]], Optional[List[Optional[int]]], List[Optional[int]]]:
    """
    Supports BOTH:
    - old: front/back with 6 columns
    - new: front/mid/back with 3 columns

    If `mid` is None -> old mode (6 cols).
    If `mid` is provided -> new mode (3 cols).
    """
    if mid is None:
        cols = OLD_COLS
        nf = _pad_or_trim(front, cols)
        nb = _pad_or_trim(back, cols)
        return nf, None, nb

    cols = NEW_COLS
    nf = _pad_or_trim(front, cols)
    nm = _pad_or_trim(mid, cols)
    nb = _pad_or_trim(back, cols)
    return nf, nm, nb


def _extract_ids(rows: List[List[Optional[int]]]) -> Tuple[List[int], List[int]]:
    """
    Returns:
      anchors:  positive ids (the real selected heroes)
      occupied: negative ids converted to positive (grid occupancy markers)
    """
    anchors: List[int] = []
    occupied: List[int] = []

    for row in rows:
        for v in row:
            if v is None:
                continue
            v = int(v)
            if v > 0:
                anchors.append(v)
            elif v < 0:
                occupied.append(abs(v))

    return anchors, occupied


# ============================================================
# VALIDATION
# ============================================================

def validate_squad(front: list, back: list, roster_by_id: dict, mid: Optional[list] = None) -> None:
    """
    Main validator used by Heroes + Campaign.

    ✅ No longer requires "1 in front and 1 in back".
    ✅ Only requires at least 1 hero total.
    ✅ Supports optional 3-row format (front/mid/back) and negative occupied cells.

    Rules enforced:
    - must select at least 1 hero (anchor)
    - no duplicate anchors
    - all anchors belong to the player (exist in roster_by_id)
    - squad size <= get_squad_limit(...)
    - if using occupancy markers (-id), they must have a matching anchor somewhere
    """
    nf, nm, nb = normalize_rows(front, back, mid=mid)

    rows = [nf, nb] if nm is None else [nf, nm, nb]

    anchors, occupied = _extract_ids(rows)

    if not anchors:
        raise RuleError(
            code="EMPTY_SQUAD",
            message="Pick at least 1 hero."
        )

    if len(set(anchors)) != len(anchors):
        raise RuleError(
            code="DUPLICATE",
            message="Duplicate hero selected."
        )

    # Ownership / validity
    for hid in anchors:
        if hid not in roster_by_id:
            raise RuleError(
                code="INVALID_HERO",
                message="Invalid hero selected.",
                details={"hero_id": hid}
            )

    # Occupancy cells must point at a real anchor (only matters in 3-row future layout)
    if occupied:
        anchor_set = set(anchors)
        for hid in occupied:
            if hid not in anchor_set:
                raise RuleError(
                    code="OCCUPIED_WITHOUT_ANCHOR",
                    message="Formation data is invalid (occupied cell without anchor).",
                    details={"hero_id": hid}
                )

    # Squad limit counts ONLY anchors (unique heroes)
    limit = get_squad_limit([roster_by_id[i] for i in anchors])
    if len(anchors) > limit:
        raise RuleError(
            code="SQUAD_LIMIT",
            message=f"Maximum squad size is {limit}.",
            details={"limit": limit}
        )

    # NOTE:
    # We are intentionally NOT enforcing front/mid/back requirements here anymore.
    # Future: you can add formation validation (fit/size/anchor placement) once HeroBase has a `size`.
    return
