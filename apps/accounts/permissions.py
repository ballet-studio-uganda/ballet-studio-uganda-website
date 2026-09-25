"""
Role gates for the management system.

Two things are always checked together: *is this person verified* and *does
their role allow this*. An unverified sign-up can log in but sees only the
holding page until an administrator approves them.
"""

from functools import wraps

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

from .models import MANAGEMENT_ROLES, STAFF_ROLES, Role


def _deny(request, message):
    """Bounce a signed-in user who lacks the role, or send a guest to log in."""
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    messages.error(request, message)
    return redirect('dashboard:home')


def role_required(*roles, message='You do not have access to that area.'):
    """
    Allow only the given roles. Superusers always pass; unverified accounts
    never do.

    Usage::

        @role_required(Role.DIRECTOR, Role.ADMIN)
        def finance_dashboard(request): ...
    """
    allowed = set(roles)

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not user.is_verified and not user.is_superuser:
                return redirect('accounts:pending')
            if user.is_superuser or user.role in allowed:
                return view(request, *args, **kwargs)
            return _deny(request, message)

        return wrapper

    return decorator


def verified_required(view):
    """Any role, so long as the account has been verified."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not request.user.is_verified and not request.user.is_superuser:
            return redirect('accounts:pending')
        return view(request, *args, **kwargs)

    return wrapper


staff_required = role_required(
    *STAFF_ROLES, message='That area is for studio staff.',
)
management_required = role_required(
    *MANAGEMENT_ROLES, message='That area is for directors and administrators.',
)
director_required = role_required(
    Role.DIRECTOR, message='That area is for the creative director.',
)
finance_required = role_required(
    *MANAGEMENT_ROLES, message='Financial records are restricted to management.',
)


# ---------------------------------------------------------------------------
# Class-based view mixins
# ---------------------------------------------------------------------------
class VerifiedRequiredMixin:
    """Signed in and approved."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not request.user.is_verified and not request.user.is_superuser:
            return redirect('accounts:pending')
        return super().dispatch(request, *args, **kwargs)


class RoleRequiredMixin(VerifiedRequiredMixin):
    """Set ``allowed_roles`` on the view."""

    allowed_roles: set = set()
    permission_message = 'You do not have access to that area.'

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        return response

    def has_role(self):
        user = self.request.user
        return user.is_superuser or user.role in self.allowed_roles


class StaffRequiredMixin(VerifiedRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if (
            request.user.is_authenticated
            and not request.user.is_superuser
            and not request.user.is_studio_staff
        ):
            return _deny(request, 'That area is for studio staff.')
        return super().dispatch(request, *args, **kwargs)


class ManagementRequiredMixin(VerifiedRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if (
            request.user.is_authenticated
            and not request.user.is_superuser
            and not request.user.is_management
        ):
            return _deny(request, 'That area is for directors and administrators.')
        return super().dispatch(request, *args, **kwargs)


# ---------------------------------------------------------------------------
# Object-level checks
# ---------------------------------------------------------------------------
def can_view_student(user, student):
    """
    Who may open a dancer's record:

    * management -- everyone;
    * teachers -- dancers in a class they lead;
    * guardians -- their own children;
    * students -- themselves.
    """
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.is_management:
        return True
    if user.is_teacher:
        return student.enrolments.filter(dance_class__teachers__user=user).exists()
    if user.is_guardian:
        guardian = getattr(user, 'guardian_profile', None)
        return bool(guardian) and student.guardian_links.filter(guardian=guardian).exists()
    if user.is_student:
        return student.user_id == user.id
    return False


def can_edit_student(user, student):
    """Teachers may add notes and reports; only management may edit the record."""
    if not user.is_authenticated:
        return False
    return user.is_superuser or user.is_management


def can_mark_register(user, session):
    """Management, or a teacher assigned to that class."""
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.is_management:
        return True
    return (
        user.is_teacher
        and session.dance_class.teachers.filter(user=user).exists()
    )


def require_student_access(user, student):
    if not can_view_student(user, student):
        raise PermissionDenied('You do not have access to this dancer’s record.')
