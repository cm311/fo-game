from django.apps import AppConfig

class FOGameConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "FO_game"

    def ready(self):
        from . import signals  # noqa
