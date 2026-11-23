from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from .audit import audit
from .http import client_ip


@receiver(user_logged_in)
def audit_verified_login(sender, request, user, **kwargs):
    # Only the OTP-aware login form sets otp_device; force_login and password-only paths do not.
    if getattr(user, "otp_device", None) is not None:
        audit(user, "moderator.login", ip=client_ip(request))
