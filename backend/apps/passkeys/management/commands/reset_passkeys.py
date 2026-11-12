"""Recover an account whose passkeys are lost (e.g. an admin's only phone)::

    python manage.py reset_passkeys you@example.com

Removes all of the user's passkeys and signs them out everywhere (revokes their refresh
tokens). They can then sign in with their password; an admin is asked to add a new
passkey straight away. Use ``changepassword EMAIL`` too if the password may be known.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken


class Command(BaseCommand):
    help = "Remove a user's passkeys and sign them out everywhere."

    def add_arguments(self, parser):
        parser.add_argument("email")

    def handle(self, *args, email: str, **options):
        User = get_user_model()
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist as exc:
            raise CommandError(f"No user with email {email}.") from exc

        removed, _ = user.passkeys.all().delete()
        revoked = 0
        for token in OutstandingToken.objects.filter(user=user):
            revoked += BlacklistedToken.objects.get_or_create(token=token)[1]
        self.stdout.write(
            self.style.SUCCESS(
                f"Removed {removed} passkey(s) and revoked {revoked} session(s) for {user.email}."
            )
        )
