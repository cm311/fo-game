from FO_game.models import HeroBase

def calc_stats(hero_base: HeroBase, level: int) -> dict:
    lv = max(1, level)
    delta = lv - 1
    return {
        "hp": hero_base.base_hp + hero_base.growth_hp * delta,
        "atk": hero_base.base_atk + hero_base.growth_atk * delta,
        "def": hero_base.base_def + hero_base.growth_def * delta,
        "matk": hero_base.base_matk + hero_base.growth_matk * delta,
        "mdef": hero_base.base_mdef + hero_base.growth_mdef * delta,
        "speed": hero_base.base_speed + hero_base.growth_speed * delta,
    }
