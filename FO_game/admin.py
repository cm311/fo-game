from django.contrib import admin
from .models import HeroBase, HeroInstance, PlayerProfile

@admin.register(HeroBase)
class HeroBaseAdmin(admin.ModelAdmin):
    list_display = ("name", "rarity", "element", "faction", "role")
    list_filter = ("rarity", "element", "faction", "role")
    search_fields = ("name",)

@admin.register(HeroInstance)
class HeroInstanceAdmin(admin.ModelAdmin):
    list_display = ("owner", "hero_base", "level", "xp")
    list_filter = ("owner", "hero_base")

@admin.register(PlayerProfile)
class PlayerProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "coins")
