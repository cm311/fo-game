from django.contrib import admin
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet

from .models import (
    HeroBase,
    HeroInstance,
    PlayerProfile,

    # New models (add these to models.py as discussed)
    AssetImage,
    SpriteSheet,
    AbilityBase,
    HeroAbilityLoadout,
)


# -----------------------------
# Helpers
# -----------------------------

class HeroAbilityInlineFormSet(BaseInlineFormSet):
    """
    Enforce:
    - slot is unique (also enforced by unique_together)
    - slot is within 1..4
    - rarity-based ability count rule (Common 1-2, Uncommon 2, Rare 2-3, Epic 3-4, Legendary 4)
    """
    def clean(self):
        super().clean()

        # inline forms can be empty/deleted
        forms = [
            f for f in self.forms
            if hasattr(f, "cleaned_data")
            and f.cleaned_data
            and not f.cleaned_data.get("DELETE", False)
        ]

        # Slot validation + uniqueness in the inline UI
        slots = []
        for f in forms:
            slot = f.cleaned_data.get("slot")
            if slot is None:
                continue
            if slot < 1 or slot > 4:
                raise ValidationError("Ability slot must be between 1 and 4.")
            slots.append(slot)

        if len(slots) != len(set(slots)):
            raise ValidationError("Duplicate ability slots detected. Each slot (1-4) must be unique.")

        # Rarity rule (only if we have a parent instance)
        hero = getattr(self, "instance", None)
        if not hero or not getattr(hero, "rarity", None):
            return

        count = len(forms)
        rules = {
            "Common": (1, 2),
            "Uncommon": (2, 2),
            "Rare": (2, 3),
            "Epic": (3, 4),
            "Legendary": (4, 4),
        }
        min_n, max_n = rules.get(hero.rarity, (1, 4))
        if not (min_n <= count <= max_n):
            raise ValidationError(
                f"{hero.rarity} heroes must have {min_n}-{max_n} abilities, but you selected {count}."
            )


# -----------------------------
# Asset Admin
# -----------------------------

@admin.register(AssetImage)
class AssetImageAdmin(admin.ModelAdmin):
    list_display = ("key", "width", "height")
    search_fields = ("key",)
    list_filter = ("width", "height")


@admin.register(SpriteSheet)
class SpriteSheetAdmin(admin.ModelAdmin):
    list_display = ("key", "sheet", "frame_w", "frame_h", "directions", "frames_per_direction", "fps")
    search_fields = ("key",)
    list_filter = ("frame_w", "frame_h", "fps")
    autocomplete_fields = ("sheet",)


# -----------------------------
# Ability Admin
# -----------------------------

@admin.register(AbilityBase)
class AbilityBaseAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "kind", "targeting", "skill_power", "cooldown_ticks")
    list_filter = ("kind", "targeting")
    search_fields = ("name", "code")
    autocomplete_fields = ("icon", "anim_sheet")


# -----------------------------
# Hero Admin (with inline loadout)
# -----------------------------

class HeroAbilityLoadoutInline(admin.TabularInline):
    model = HeroAbilityLoadout
    formset = HeroAbilityInlineFormSet
    extra = 0
    fields = ("slot", "ability")
    autocomplete_fields = ("ability",)
    ordering = ("slot",)


@admin.register(HeroBase)
class HeroBaseAdmin(admin.ModelAdmin):
    list_display = ("name", "rarity", "element", "faction", "role")
    list_filter = ("rarity", "element", "faction", "role")
    search_fields = ("name",)

    # Art hooks (these fields must exist on HeroBase)
    # portrait, background, idle_sheet
    autocomplete_fields = ("portrait", "background")

    inlines = [HeroAbilityLoadoutInline]


# -----------------------------
# Existing Admin
# -----------------------------

@admin.register(HeroInstance)
class HeroInstanceAdmin(admin.ModelAdmin):
    list_display = ("owner", "hero_base", "level", "xp")
    list_filter = ("owner", "hero_base")
    search_fields = ("owner__username", "hero_base__name")
    autocomplete_fields = ("owner", "hero_base")


@admin.register(PlayerProfile)
class PlayerProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "coins")
    search_fields = ("user__username",)
    autocomplete_fields = ("user",)
