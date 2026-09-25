"""Authentication backends."""

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


class EmailOrUsernameBackend(ModelBackend):
    """
    Let people sign in with whichever they remember -- email or username.

    Parents in particular register with an email address and never think of
    themselves as having a username, so requiring one is a support burden.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()
        identifier = username or kwargs.get('email')
        if not identifier or not password:
            return None

        try:
            user = User.objects.get(
                Q(username__iexact=identifier) | Q(email__iexact=identifier)
            )
        except User.DoesNotExist:
            # Equalise timing against the "user exists" path.
            User().set_password(password)
            return None
        except User.MultipleObjectsReturned:
            user = (
                User.objects.filter(
                    Q(username__iexact=identifier) | Q(email__iexact=identifier)
                )
                .order_by('id')
                .first()
            )

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
