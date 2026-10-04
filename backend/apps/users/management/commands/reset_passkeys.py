"""Recover an account locked out of its passkeys.

    python manage.py reset_passkeys you@example.com          # next sign-in sets up a new one
    python manage.py reset_passkeys you@example.com --off    # and stop requiring one
    python manage.py reset_passkeys you@example.com --on     # require one (no deletion)
"""

from django.core.management.base import BaseCommand, CommandError

from apps.users.models import User


class Command(BaseCommand):
    help = "Delete a user's passkeys (they set up a new one at next sign-in), or turn the requirement on/off."

    def add_arguments(self, parser):
        parser.add_argument("email")
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--off", action="store_true", help="Also stop requiring a passkey.")
        group.add_argument("--on", action="store_true", help="Only turn the requirement on; keep passkeys.")

    def handle(self, email, off=False, on=False, **options):
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            raise CommandError(f"No user with email {email}")
        if on:
            user.passkey_required = True
            user.save(update_fields=["passkey_required"])
            self.stdout.write(f"{user.email}: passkey now required.")
            return
        deleted, _ = user.passkeys.all().delete()
        if off:
            user.passkey_required = False
            user.save(update_fields=["passkey_required"])
        state = "not required" if not user.passkey_required else "required (set up at next sign-in)"
        self.stdout.write(f"{user.email}: deleted {deleted} passkey(s); passkey {state}.")
