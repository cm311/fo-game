from django.db import models, transaction
from django.contrib.auth.models import User

import random

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
