import io
from base64 import b32encode

import qrcode
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from tchekam.core.audit import audit

RECOVERY_TOKENS = 8


class Command(BaseCommand):
    help = "Enrol an existing staff user's authenticator app (TOTP) and print recovery tokens."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Replace the user's existing devices (lost phone).",
        )

    def handle(self, *args, username, replace, **options):
        user = get_user_model().objects.filter(username=username).first()
        if user is None or not (user.is_active and user.is_staff):
            raise CommandError("No active staff user with that username.")
        had_device = TOTPDevice.objects.filter(user=user, confirmed=True).exists()
        if had_device and not replace:
            raise CommandError("User already has a confirmed device; pass --replace to reset it.")

        with transaction.atomic():
            # Replacing also drops old recovery tokens, which belonged to the lost setup.
            TOTPDevice.objects.filter(user=user).delete()
            StaticDevice.objects.filter(user=user).delete()
            device = TOTPDevice.objects.create(user=user, name="authenticator", confirmed=True)
            recovery = StaticDevice.objects.create(user=user, name="recovery", confirmed=True)
            tokens = [StaticToken.random_token() for _ in range(RECOVERY_TOKENS)]
            StaticToken.objects.bulk_create(StaticToken(device=recovery, token=t) for t in tokens)
            # Metadata carries no secrets: the key and tokens are only ever printed here.
            audit(None, "moderator.totp_enrolled", user, replaced=had_device)

        # Secrets go to stdout only, never to logs.
        out = self.stdout
        out.write(f"Secret (base32): {b32encode(device.bin_key).decode()}")
        out.write(f"URI: {device.config_url}")
        qr = qrcode.QRCode()
        qr.add_data(device.config_url)
        buffer = io.StringIO()
        qr.print_ascii(out=buffer)
        art = buffer.getvalue()
        try:
            # Block characters fail on legacy Windows code pages; the tokens below must still print.
            art.encode(out.encoding or "utf-8")
            out.write(art)
        except UnicodeEncodeError:
            out.write("(QR not shown: this terminal cannot display it; use the URI above.)")
        out.write("Recovery tokens (each works once, shown only now):")
        for token in tokens:
            out.write(f"  {token}")
