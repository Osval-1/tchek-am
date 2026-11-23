import ipaddress

from django.core.management.base import BaseCommand, CommandError

from tchekam.core import login_throttle
from tchekam.core.audit import audit


class Command(BaseCommand):
    help = "Clear the failed-login counters and lock for a username or an IP address."

    def add_arguments(self, parser):
        parser.add_argument("username", nargs="?")
        parser.add_argument("--ip", help="Unlock this client IP address instead of a username.")

    def handle(self, *args, username, ip, **options):
        # --all is deliberately absent: the shared DatabaseCache cannot list keys by prefix.
        if bool(username) == bool(ip):
            raise CommandError("Give either a username or --ip <address>.")
        if ip:
            try:
                ip = str(ipaddress.ip_address(ip))
            except ValueError:
                raise CommandError("Not a valid IP address.") from None
            login_throttle.unlock_ip(ip)
            kind, digest = "ip", login_throttle.ip_digest(ip)
        else:
            login_throttle.reset(username)
            kind, digest = "username", login_throttle.username_digest(username)
        # Only the kind and a keyed hash prefix are recorded, never the clear value.
        audit(None, "moderator.login_unlocked", kind=kind, hash=digest[:8])
        self.stdout.write(f"Unlocked {kind} ({digest[:8]}).")
