from django.core.exceptions import ValidationError
from django_otp.admin import OTPAdminAuthenticationForm, OTPAdminSite

from . import login_throttle
from .audit import audit
from .http import client_ip


class ThrottledOTPLoginForm(OTPAdminAuthenticationForm):
    """Password + OTP login with lockout and audit of failures."""

    def clean(self):
        username = (self.data.get("username") or "").strip()
        ip = client_ip(self.request) if self.request else None
        # Checked before authenticating, and with one message for known and unknown
        # usernames, so a lock reveals nothing about which accounts exist.
        if login_throttle.is_locked(username, ip):
            raise ValidationError(login_throttle.LOCKED_MESSAGE, code="locked")
        try:
            cleaned = super().clean()
        except ValidationError:
            login_throttle.record_failure(username, ip)
            audit(
                None,
                "moderator.login_failed",
                ip=ip,
                username_hash=login_throttle.username_digest(username)[:8],
            )
            raise
        login_throttle.reset(username)
        return cleaned


class TchekAdminSite(OTPAdminSite):
    login_form = ThrottledOTPLoginForm

    def __init__(self, name="admin"):
        # OTPAdminSite defaults to "otpadmin"; keep the "admin:" URL namespace.
        super().__init__(name)
