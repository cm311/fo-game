from django.db import models, transaction
from django.contrib.auth.models import User

import random


class AssetImage(models.Model):
    """
    Any single image: portraits, backgrounds, UI icons, etc.
    """
    key = models.CharField(max_length=120, unique=True)
    image = models.ImageField(upload_to="game_assets/")
    width = models.IntegerField(default=0)
    height = models.IntegerField(default=0)

    def __str__(self):
        return self.key


class SpriteSheet(models.Model):
    """
    A sprite sheet + enough metadata for your renderer (Godot/Phaser) to play it.
    """
    key = models.CharField(max_length=120, unique=True)
    sheet = models.ForeignKey(AssetImage, on_delete=models.CASCADE, related_name="sheets")

    frame_w = models.IntegerField(default=48)
    frame_h = models.IntegerField(default=48)

    # store as JSON-ish strings for now (simple)
    directions = models.CharField(max_length=40, default="NW,NE,SE,SW")  # your 4-diagonal style
    frames_per_direction = models.IntegerField(default=4)
    fps = models.IntegerField(default=8)

    def __str__(self):
        return self.key


class AbilityBase(models.Model):
    KIND_CHOICES = [
        ("basic", "Basic"),
        ("active", "Active"),
        ("passive", "Passive"),
    ]
    TARGET_CHOICES = [
        ("single_enemy", "Single Enemy"),
        ("all_enemies", "All Enemies"),
        ("single_ally", "Single Ally"),
        ("all_allies", "All Allies"),
        ("self", "Self"),
    ]

    code = models.CharField(max_length=120, unique=True)  # used by get_kit_for mapping
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)

    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default="active")
    targeting = models.CharField(max_length=30, choices=TARGET_CHOICES, default="single_enemy")

    skill_power = models.FloatField(default=1.0)  # matches your doc’s SkillPower concept :contentReference[oaicite:5]{index=5}
    cooldown_ticks = models.IntegerField(default=0)

    # Art hooks (optional, but this is what you asked for)
    # “same base sprite, unique anim per ability” => this is where that anim lives
    anim_sheet = models.ForeignKey(SpriteSheet, null=True, blank=True, on_delete=models.SET_NULL, related_name="abilities")
    icon = models.ForeignKey(AssetImage, null=True, blank=True, on_delete=models.SET_NULL, related_name="ability_icons")

    def __str__(self):
        return self.name


class HeroAbilityLoadout(models.Model):
    hero_base = models.ForeignKey("HeroBase", on_delete=models.CASCADE, related_name="ability_loadout")
    ability = models.ForeignKey(AbilityBase, on_delete=models.CASCADE, related_name="equipped_on")
    slot = models.IntegerField()  # 1..4
    unlock_level = models.IntegerField(default=1)

    class Meta:
        unique_together = [("hero_base", "slot")]
        ordering = ["slot"]

    def clean(self):
        if self.slot < 1 or self.slot > 4:
            raise ValidationError("slot must be 1..4")

    def __str__(self):
        return f"{self.hero_base.name} slot{self.slot}: {self.ability.name}"
    
class HeroBase(models.Model):
    RARITY_CHOICES = [
        ('Common', 'Common'),
        ('Uncommon', 'Uncommon'),
        ('Rare', 'Rare'),
        ('Epic', 'Epic'),
        ('Legendary', 'Legendary'),
    ]

    ELEMENT_CHOICES = [
        ('Magic', 'Magic'),
        ('Spirit', 'Spirit'),
        ('Force', 'Force'),
        ('Void', 'Void'),
        ('Tech', 'Tech'),
        ('Fire', 'Fire'),
    ]

    FACTION_CHOICES = [
        ('Undead', 'Undead'),
        ('Goblin', 'Goblin'),
        ('Wild', 'Wild'),  # you also have Wild in your TS data
    ]

    name = models.CharField(max_length=100, unique=True)
    rarity = models.CharField(max_length=20, choices=RARITY_CHOICES)
    element = models.CharField(max_length=20, choices=ELEMENT_CHOICES)
    faction = models.CharField(max_length=20, choices=FACTION_CHOICES)
    role = models.CharField(max_length=20)
    description = models.TextField()

    base_hp = models.IntegerField()
    base_atk = models.IntegerField()
    base_def = models.IntegerField()
    base_matk = models.IntegerField()
    base_mdef = models.IntegerField()
    base_speed = models.IntegerField()

    growth_hp = models.IntegerField()
    growth_atk = models.IntegerField()
    growth_def = models.IntegerField()
    growth_matk = models.IntegerField()
    growth_mdef = models.IntegerField()
    growth_speed = models.IntegerField()

    portrait = models.ForeignKey(AssetImage, null=True, blank=True, on_delete=models.SET_NULL, related_name="hero_portraits")
    background = models.ForeignKey(AssetImage, null=True, blank=True, on_delete=models.SET_NULL, related_name="hero_backgrounds")

    base_idle_sheet = models.ForeignKey(SpriteSheet, null=True, blank=True, on_delete=models.SET_NULL, related_name="hero_idle_sheets")

    def clean(self):
        super().clean()

        # only validate when saved already (so it has loadout rows)
        if not self.pk:
            return

        count = self.ability_loadout.count()

        rules = {
            "Common": (1, 2),
            "Uncommon": (2, 2),
            "Rare": (2, 3),
            "Epic": (3, 4),
            "Legendary": (4, 4),
        }

        min_n, max_n = rules.get(self.rarity, (1, 4))
        if not (min_n <= count <= max_n):
            raise ValidationError(
                f"{self.rarity} heroes must have {min_n}-{max_n} abilities, but this hero has {count}."
            )



class HeroInstance(models.Model):
    owner = models.ForeignKey(User, related_name='heroes', on_delete=models.CASCADE)
    hero_base = models.ForeignKey(HeroBase, on_delete=models.CASCADE)
    level = models.IntegerField(default=1)
    xp = models.IntegerField(default=0)

class PlayerProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    coins = models.BigIntegerField(default=200000)



def summon_random_hero(profile: PlayerProfile, cost: int = 5000) -> HeroInstance | None:
    """
    Simple rarity-weighted summon.
    Pull rates (design doc):
      Common 50%, Uncommon 30%, Rare 15%, Epic 4%, Legendary 1%
    """
    if profile.coins < cost:
        return None

    rarities = ["Common", "Uncommon", "Rare", "Epic", "Legendary"]
    weights  = [50,        30,         15,     4,      1]

    chosen_rarity = random.choices(rarities, weights=weights, k=1)[0]

    pool = list(HeroBase.objects.filter(rarity=chosen_rarity))
    if not pool:
        # fallback if you have no heroes of that rarity yet
        pool = list(HeroBase.objects.all())
        if not pool:
            return None

    base = random.choice(pool)

    with transaction.atomic():
        # re-check inside transaction (prevents weird double-spend on spam clicks)
        profile.refresh_from_db()
        if profile.coins < cost:
            return None

        profile.coins -= cost
        profile.save(update_fields=["coins"])

        instance = HeroInstance.objects.create(
            owner=profile.user,
            hero_base=base,
            level=1,
            xp=0,
        )

    return instance



def xp_to_level_up(level: int) -> int:
    # simple curve
    return 100 + (level - 1) * 50

def apply_xp_and_level(hero: HeroInstance, gained: int) -> dict:
    hero.xp += gained
    leveled = 0
    while hero.xp >= xp_to_level_up(hero.level):
        hero.xp -= xp_to_level_up(hero.level)
        hero.level += 1
        leveled += 1
    hero.save()
    return {"gained": gained, "leveled": leveled, "new_level": hero.level, "xp": hero.xp}
