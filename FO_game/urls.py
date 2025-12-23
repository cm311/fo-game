from django.urls import path
from . import views

urlpatterns = [
    path("", views.home_view, name="home"),
    path("campaign/", views.campaign_view, name="campaign"),
    path("summon/", views.summon_view, name="summon"),
    path("summon/one/", views.summon_one_view, name="summon-one"),
    path("heroes/", views.heroes_view, name="heroes"),
    path("library/", views.library_view, name="library"),

    path("api/heroes/", views.hero_list, name="hero-list"),
    path("api/player/", views.player_profile, name="player-profile"),
    # add under your existing urlpatterns
    path("api/battle/start/", views.api_battle_start, name="api-battle-start"),
    path("api/battle/step/", views.api_battle_step, name="api-battle-step"),
    path("api/battle/act/", views.api_battle_act, name="api-battle-act"),

]
