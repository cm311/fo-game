import random, json

from .engine.battle import (
    battle_state_new,
    battle_state_snapshot,
    battle_state_advance_until_pause,
    battle_state_player_basic_attack,
    build_units_from_instances,
    build_enemy_units,
    DEFAULT_TICK_LIMIT_STEP,
)

from .engine.rules import validate_squad, RuleError

from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST, require_http_methods
from django.contrib.auth.models import User
from django.http import HttpResponseBadRequest, JsonResponse

from django.contrib.auth.decorators import login_required
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response

from .models import HeroBase, HeroInstance, PlayerProfile, summon_random_hero, apply_xp_and_level
from .serializers import HeroBaseSerializer, PlayerProfileSerializer

from .engine.kits import get_kit_for


@api_view(["GET"])
@permission_classes([IsAuthenticatedOrReadOnly])
def hero_list(request):
    heroes = HeroBase.objects.all()
    serializer = HeroBaseSerializer(heroes, many=True)
    return Response(serializer.data)


@api_view(["GET"])
@permission_classes([IsAuthenticatedOrReadOnly])
def player_profile(request):
    profile = PlayerProfile.objects.first()
    if not profile:
        return Response({"detail": "No player profile yet."}, status=404)
    serializer = PlayerProfileSerializer(profile)
    return Response(serializer.data)


def get_current_profile(request):
    if request.user.is_authenticated:
        profile, _ = PlayerProfile.objects.get_or_create(user=request.user)
        return profile

    # Prototype fallback
    user = User.objects.first()
    if not user:
        return None
    profile, _ = PlayerProfile.objects.get_or_create(user=user)
    return profile


def home_view(request):
    profile = get_current_profile(request)
    return render(request, "FO_game/home.html", {
        "active_tab": None,
        "profile": profile,
    })


def _anchors_only(row):
    """
    Convert a row list into only anchors (positive ids) / None.
    Keeps length the same.
    """
    out = []
    for v in (row or []):
        if v in ("", "0", 0, None):
            out.append(None)
            continue
        v = int(v)
        if v < 0:
            out.append(None)  # occupied marker is not an anchor
        else:
            out.append(v)
    return out


def campaign_view(request):
    profile = get_current_profile(request)

    if not profile:
        return render(request, "FO_game/campaign.html", {
            "active_tab": "campaign",
            "profile": None,
            "battle": None,
            "xp_results": None,
            "error": "No profile found. Create a user or log in.",
        })

    # load saved squad
    squad = request.session.get("squad") or {}

    # Detect new 3-row (front/mid/back) vs old 2-row (front/back 6 slots)
    has_mid = isinstance(squad, dict) and ("mid" in squad)

    if has_mid:
        front = _anchors_only((squad.get("front") or [])[:3])
        mid   = _anchors_only((squad.get("mid") or [])[:3])
        back  = _anchors_only((squad.get("back") or [])[:3])

        front = front + [None] * (3 - len(front))
        mid   = mid   + [None] * (3 - len(mid))
        back  = back  + [None] * (3 - len(back))

        selected_ids = [i for i in (front + mid + back) if i]
        selected_ids = list(dict.fromkeys(selected_ids))

    else:
        front = (squad.get("front") or [])[:6]
        back  = (squad.get("back") or [])[:6]
        front = front + [None] * (6 - len(front))
        back  = back  + [None] * (6 - len(back))

        selected_ids = [i for i in (front + back) if i]
        selected_ids = list(dict.fromkeys(selected_ids))

    # fetch instances (owned)
    roster = list(
        HeroInstance.objects.filter(owner=profile.user, id__in=selected_ids)
        .select_related("hero_base")
    )
    roster_by_id = {h.id: h for h in roster}

    # validate (rules.py now no longer requires 1 front/back)
    try:
        if has_mid:
            validate_squad(front, back, roster_by_id, mid=mid)
        else:
            validate_squad(front, back, roster_by_id)
    except RuleError as e:
        msg = (
            "No squad selected yet. Go to Heroes and save a squad."
            if e.code == "EMPTY_SQUAD"
            else e.message
        )
        return render(request, "FO_game/campaign.html", {
            "active_tab": "campaign",
            "profile": profile,
            "battle": None,
            "xp_results": None,
            "error": msg,
        })

    # build formation mapping expected by engine
    formation = {}

    if has_mid:
        for idx, hid in enumerate(front):
            if hid and hid in roster_by_id:
                formation[hid] = ("front", idx)
        for idx, hid in enumerate(mid):
            if hid and hid in roster_by_id:
                formation[hid] = ("mid", idx)
        for idx, hid in enumerate(back):
            if hid and hid in roster_by_id:
                formation[hid] = ("back", idx)

        squad_instances = [roster_by_id[hid] for hid in selected_ids if hid in roster_by_id]
    else:
        for idx, hid in enumerate(front):
            if hid and hid in roster_by_id:
                formation[hid] = ("front", idx)
        for idx, hid in enumerate(back):
            if hid and hid in roster_by_id:
                formation[hid] = ("back", idx)

        squad_instances = [roster_by_id[hid] for hid in selected_ids if hid in roster_by_id]

    # engine
    from .engine.battle import run_battle

    player_units = build_units_from_instances("player", squad_instances, formation)

    # enemy: 5× Level 1 Fungal Sporeling
    sporeling = (
        HeroBase.objects.filter(name__iexact="Fungal Sporeling").first()
        or HeroBase.objects.filter(name__icontains="Fungal").filter(name__icontains="Spore").first()
        or HeroBase.objects.filter(name__icontains="Sporeling").first()
    )

    if not sporeling:
        return render(request, "FO_game/campaign.html", {
            "active_tab": "campaign",
            "profile": profile,
            "battle": None,
            "xp_results": None,
            "error": "Enemy base not found: 'Fungal Sporeling'. Make sure it's seeded in HeroBase.",
        })

    enemy_units = build_enemy_units([sporeling] * 5, level=1)

    battle_result = run_battle(player_units, enemy_units, seed=None, tick_limit=100)

    # award XP only to participating instances
    xp_results = {}
    for inst in squad_instances:
        gained = battle_result["xp"].get(inst.id, 0)
        xp_results[inst.id] = apply_xp_and_level(inst, gained)

    return render(request, "FO_game/campaign.html", {
        "active_tab": "campaign",
        "profile": profile,
        "battle": battle_result,
        "xp_results": xp_results,
        "error": None,
    })


@require_http_methods(["GET", "POST"])
def heroes_view(request):
    """
    NOTE: You already replaced this in your project during the 3-row work.
    I'm leaving your current version alone.
    """
    profile = get_current_profile(request)
    if not profile:
        return render(request, "FO_game/heroes.html", {
            "active_tab": "heroes",
            "profile": None,
            "roster": [],
            "current": None,
            "current_units": None,
            "saved": False,
            "error": "No profile found."
        })

    roster = list(
        HeroInstance.objects.filter(owner=profile.user)
        .select_related("hero_base")
        .order_by("-level", "-id")
    )
    roster_by_id = {h.id: h for h in roster}

    saved = False
    error = None

    # IMPORTANT:
    # Your heroes.html now posts front/mid/back. We store the raw grid rows in session.
    if request.method == "POST":
        raw = request.POST.get("squad_json", "")
        try:
            payload = json.loads(raw)
            front = payload.get("front", [])
            mid   = payload.get("mid", [])
            back  = payload.get("back", [])
        except Exception:
            return HttpResponseBadRequest("Invalid squad payload.")

        # normalize to 3 cols each (keep negatives, your rules.py supports them)
        def norm3(row):
            row = list(row or [])
            out = []
            for i in range(3):
                v = row[i] if i < len(row) else None
                if v in ("", "0", 0):
                    v = None
                out.append(int(v) if v is not None else None)
            return out

        front = norm3(front)
        mid   = norm3(mid)
        back  = norm3(back)

        # validate anchors + ownership + max size
        try:
            validate_squad(front, back, roster_by_id, mid=mid)
        except RuleError as e:
            error = e.message
            return render(request, "FO_game/heroes.html", {
                "active_tab": "heroes",
                "profile": profile,
                "roster": roster,
                "current": request.session.get("squad"),
                "current_units": None,
                "saved": False,
                "error": error,
            })

        request.session["squad"] = {"front": front, "mid": mid, "back": back}
        request.session.modified = True
        saved = True

    current = request.session.get("squad")

    # resolve for display (anchors only)
    current_units = None
    if current and isinstance(current, dict):
        try:
            def show_row(row):
                row = (row or [])[:3]
                row = row + [None] * (3 - len(row))
                # show only anchors
                out = []
                for v in row:
                    if not v:
                        out.append(None)
                    else:
                        v = int(v)
                        out.append(roster_by_id.get(v) if v > 0 else None)
                return out

            current_units = {
                "front": show_row(current.get("front")),
                "mid":   show_row(current.get("mid")),
                "back":  show_row(current.get("back")),
            }
        except Exception:
            current_units = None

    return render(request, "FO_game/heroes.html", {
        "active_tab": "heroes",
        "profile": profile,
        "roster": roster,
        "current": current,
        "current_units": current_units,
        "saved": saved,
        "error": error,
    })


def library_view(request):
    profile = get_current_profile(request)
    heroes = HeroBase.objects.all().order_by("faction", "rarity", "name")

    hero_rows = []
    for hb in heroes:
        kit = get_kit_for(hb)
        hero_rows.append({
            "hero": hb,
            "abilities": [ab.describe() for ab in kit],
        })

    return render(request, "FO_game/library.html", {
        "active_tab": "library",
        "profile": profile,
        "hero_rows": hero_rows,
    })


@login_required
def summon_one(request):
    profile, _ = PlayerProfile.objects.get_or_create(user=request.user)

    hero = summon_random_hero(profile, cost=5000)
    if hero is None:
        request.session["last_summon_msg"] = "Not enough coins to summon."
    else:
        name = hero.hero_base.name
        rarity = hero.hero_base.rarity
        request.session["last_summon_msg"] = f"You summoned: {name} ({rarity})!"

    return redirect("summon")


def summon_view(request):
    profile = get_current_profile(request)

    msg = request.session.pop("last_summon_msg", None)
    return render(request, "FO_game/summon.html", {
        "active_tab": "summon",
        "profile": profile,
        "message": msg,
    })


@require_POST
def api_battle_start(request):
    profile = get_current_profile(request)
    if not profile:
        return JsonResponse({"ok": False, "error": "No profile found."}, status=400)

    squad = request.session.get("squad")
    if not squad:
        return JsonResponse({"ok": False, "error": "No squad saved. Go to Heroes."}, status=400)

    has_mid = isinstance(squad, dict) and ("mid" in squad)

    roster = list(HeroInstance.objects.filter(owner=profile.user).select_related("hero_base"))
    roster_by_id = {h.id: h for h in roster}

    if has_mid:
        front = _anchors_only((squad.get("front") or [])[:3])
        mid   = _anchors_only((squad.get("mid") or [])[:3])
        back  = _anchors_only((squad.get("back") or [])[:3])
        front = front + [None] * (3 - len(front))
        mid   = mid   + [None] * (3 - len(mid))
        back  = back  + [None] * (3 - len(back))

        try:
            validate_squad(front, back, roster_by_id, mid=mid)
        except RuleError as e:
            return JsonResponse({"ok": False, "error": e.message, "code": e.code}, status=400)

        formation = {}
        for i, hid in enumerate(front):
            if hid:
                formation[int(hid)] = ("front", i)
        for i, hid in enumerate(mid):
            if hid:
                formation[int(hid)] = ("mid", i)
        for i, hid in enumerate(back):
            if hid:
                formation[int(hid)] = ("back", i)

        chosen = [hid for hid in (front + mid + back) if hid][:5]

    else:
        front = (squad.get("front") or [])[:6]
        back  = (squad.get("back") or [])[:6]
        try:
            validate_squad(front, back, roster_by_id)
        except RuleError as e:
            return JsonResponse({"ok": False, "error": e.message, "code": e.code}, status=400)

        formation = {}
        for i, hid in enumerate(front):
            if hid:
                formation[int(hid)] = ("front", i)
        for i, hid in enumerate(back):
            if hid:
                formation[int(hid)] = ("back", i)

        chosen = [hid for hid in (front + back) if hid][:5]

    player_insts = [roster_by_id[hid] for hid in chosen if hid in roster_by_id]
    player_units = build_units_from_instances("player", player_insts, formation)

    # enemy squad: 5 units
    enemy_base = HeroBase.objects.filter(name__icontains="spore").first()
    if enemy_base is None:
        enemy_base = HeroBase.objects.filter(faction="Wild").first()
    if enemy_base is None:
        enemy_base = HeroBase.objects.first()

    if enemy_base is None:
        return JsonResponse({"ok": False, "error": "No HeroBase rows exist to spawn enemies."}, status=400)

    enemy_units = build_enemy_units([enemy_base] * 5, level=1)

    state = battle_state_new(player_units, enemy_units, seed=1337, tick_limit=DEFAULT_TICK_LIMIT_STEP)
    state = battle_state_advance_until_pause(state)

    request.session["battle_state"] = state
    request.session.modified = True

    return JsonResponse({"ok": True, "snapshot": battle_state_snapshot(state)})


@require_POST
def api_battle_step(request):
    state = request.session.get("battle_state")
    if not state:
        return JsonResponse({"ok": False, "error": "No active battle. Start first."}, status=400)

    state = battle_state_advance_until_pause(state)
    request.session["battle_state"] = state
    request.session.modified = True

    return JsonResponse({"ok": True, "snapshot": battle_state_snapshot(state)})


@require_POST
def api_battle_act(request):
    state = request.session.get("battle_state")
    if not state:
        return JsonResponse({"ok": False, "error": "No active battle. Start first."}, status=400)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        payload = {}

    target_side = payload.get("target_side", "enemy")
    target_row  = payload.get("target_row")
    target_slot = payload.get("target_slot")

    if target_row not in ("front", "mid", "back") or target_slot is None:
        return JsonResponse({"ok": False, "error": "Missing target."}, status=400)

    state = battle_state_player_basic_attack(state, target_side, target_row, int(target_slot))
    request.session["battle_state"] = state
    request.session.modified = True

    return JsonResponse({"ok": True, "snapshot": battle_state_snapshot(state)})
