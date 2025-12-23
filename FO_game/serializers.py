from rest_framework import serializers
from .models import HeroBase, HeroInstance, PlayerProfile

class HeroBaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = HeroBase
        fields = "__all__"

class HeroInstanceSerializer(serializers.ModelSerializer):
    hero_base = HeroBaseSerializer()

    class Meta:
        model = HeroInstance
        fields = "__all__"

class PlayerProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlayerProfile
        fields = "__all__"
