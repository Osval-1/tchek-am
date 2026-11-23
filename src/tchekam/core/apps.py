from django.apps import AppConfig
from django.contrib.admin import apps as admin_apps


class CoreConfig(AppConfig):
    name = "tchekam.core"
    label = "core"

    def ready(self):
        from . import signals  # noqa: F401  (connects the login audit receiver)


class TchekAdminConfig(admin_apps.AdminConfig):
    # Not a default: INSTALLED_APPS names it explicitly, and "tchekam.core" must pick CoreConfig.
    default = False
    # Same app label as django.contrib.admin, so every `admin.register` keeps working,
    # but the default site requires a verified OTP device.
    default_site = "tchekam.core.admin_site.TchekAdminSite"
