"""
Identity and people models for Ballet Dance Studio UG.

Everything that describes a *person* lives here -- the login account itself
plus the three profile types the studio works with: staff (creative directors,
administrators, teachers), guardians (parents) and students.

Students deliberately keep their own name/date-of-birth fields and an OPTIONAL
``user`` link, because a three-year-old in Kinder Ballet is a real student of
the studio long before anyone gives them a password.
"""

from __future__ import annotations

import datetime as dt

from django.conf import settings
from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import Max
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from phonenumber_field.modelfields import PhoneNumberField


# ---------------------------------------------------------------------------
# Choices
# ---------------------------------------------------------------------------
class Role(models.TextChoices):
    DIRECTOR = 'director', _('Creative Director')
    ADMIN = 'admin', _('Administrator')
    TEACHER = 'teacher', _('Teacher')
    PARENT = 'parent', _('Parent / Guardian')
    STUDENT = 'student', _('Student')


#: Roles that may reach the staff side of the management system.
STAFF_ROLES = frozenset({Role.DIRECTOR, Role.ADMIN, Role.TEACHER})

#: Roles allowed to manage other people, money and published content.
MANAGEMENT_ROLES = frozenset({Role.DIRECTOR, Role.ADMIN})


class ApprovalStatus(models.TextChoices):
    PENDING = 'pending', _('Pending verification')
    APPROVED = 'approved', _('Verified')
    REJECTED = 'rejected', _('Rejected')
    SUSPENDED = 'suspended', _('Suspended')


class Gender(models.TextChoices):
    FEMALE = 'F', _('Female')
    MALE = 'M', _('Male')
    OTHER = 'O', _('Other')
    UNDISCLOSED = 'U', _('Prefer not to say')


class EmploymentType(models.TextChoices):
    FULL_TIME = 'full_time', _('Full time')
    PART_TIME = 'part_time', _('Part time')
    CONTRACT = 'contract', _('Contract')
    VOLUNTEER = 'volunteer', _('Volunteer')
    GUEST = 'guest', _('Guest artist')


class StudentStatus(models.TextChoices):
    ACTIVE = 'active', _('Active')
    ON_HOLD = 'on_hold', _('On hold')
    WITHDRAWN = 'withdrawn', _('Withdrawn')
    ALUMNI = 'alumni', _('Alumni')


class Relationship(models.TextChoices):
    MOTHER = 'mother', _('Mother')
    FATHER = 'father', _('Father')
    GUARDIAN = 'guardian', _('Legal guardian')
    GRANDPARENT = 'grandparent', _('Grandparent')
    SIBLING = 'sibling', _('Sibling')
    AUNT_UNCLE = 'aunt_uncle', _('Aunt / Uncle')
    OTHER = 'other', _('Other')


class SickleCellStatus(models.TextChoices):
    """
    The studio's annual recital raises sickle cell awareness, and several
    dancers live with the condition. Recording it -- always optional -- lets
    teachers plan rest breaks, hydration and safe exertion levels.
    """
    UNDISCLOSED = 'undisclosed', _('Not disclosed')
    UNKNOWN = 'unknown', _('Unknown / not tested')
    NEGATIVE = 'negative', _('Negative (AA)')
    TRAIT = 'trait', _('Carrier / trait (AS)')
    DISEASE = 'disease', _('Sickle cell disease (SS)')
    OTHER = 'other', _('Other haemoglobin variant')


class ContactMethod(models.TextChoices):
    PHONE = 'phone', _('Phone call')
    SMS = 'sms', _('SMS')
    WHATSAPP = 'whatsapp', _('WhatsApp')
    EMAIL = 'email', _('Email')


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------
class UserManager(DjangoUserManager):
    """Normalises email and keeps superusers auto-verified."""

    def create_superuser(self, username, email=None, password=None, **extra):
        extra.setdefault('role', Role.DIRECTOR)
        extra.setdefault('approval_status', ApprovalStatus.APPROVED)
        extra.setdefault('verified_at', timezone.now())
        return super().create_superuser(username, email, password, **extra)

    def staff_members(self):
        return self.filter(role__in=STAFF_ROLES)

    def pending_verification(self):
        return self.filter(approval_status=ApprovalStatus.PENDING)


class User(AbstractUser):
    """
    A single login account for every human who touches the studio.

    ``role`` decides which dashboard the user lands on; ``approval_status``
    decides whether they get past the holding page at all. New sign-ups are
    always PENDING until an administrator verifies them.
    """

    email = models.EmailField(_('email address'), unique=True)
    role = models.CharField(
        _('role'), max_length=20, choices=Role.choices, default=Role.STUDENT, db_index=True,
    )
    approval_status = models.CharField(
        _('account status'), max_length=20,
        choices=ApprovalStatus.choices, default=ApprovalStatus.PENDING, db_index=True,
    )

    phone = PhoneNumberField(_('phone number'), blank=True)
    whatsapp = PhoneNumberField(_('WhatsApp number'), blank=True)
    photo = models.ImageField(_('profile photo'), upload_to='people/avatars/', blank=True)
    date_of_birth = models.DateField(_('date of birth'), null=True, blank=True)
    gender = models.CharField(
        _('gender'), max_length=1, choices=Gender.choices, default=Gender.UNDISCLOSED, blank=True,
    )

    address = models.CharField(_('residential address'), max_length=255, blank=True)
    city = models.CharField(_('city / town'), max_length=100, blank=True, default='Kampala')
    country = models.CharField(_('country'), max_length=100, blank=True, default='Uganda')

    # Verification trail
    verified_by = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='verified_users', verbose_name=_('verified by'),
    )
    verified_at = models.DateTimeField(_('verified at'), null=True, blank=True)
    verification_note = models.TextField(
        _('verification note'), blank=True,
        help_text=_('Internal note explaining an approval, rejection or suspension.'),
    )

    # Preferences / housekeeping
    receives_email = models.BooleanField(_('receives email notifications'), default=True)
    receives_sms = models.BooleanField(_('receives SMS notifications'), default=True)
    must_change_password = models.BooleanField(default=False)
    last_seen = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    class Meta:
        verbose_name = _('user account')
        verbose_name_plural = _('user accounts')
        ordering = ('first_name', 'last_name', 'username')
        indexes = [
            models.Index(fields=('role', 'approval_status')),
        ]

    def __str__(self):
        return f'{self.get_full_name() or self.username} ({self.get_role_display()})'

    def get_absolute_url(self):
        return reverse('dashboard:user_detail', args=[self.pk])

    # -- naming ------------------------------------------------------------
    @property
    def display_name(self):
        return self.get_full_name().strip() or self.username

    @property
    def initials(self):
        parts = [p for p in (self.first_name, self.last_name) if p]
        if not parts:
            return self.username[:2].upper()
        return ''.join(p[0] for p in parts).upper()

    # -- role helpers ------------------------------------------------------
    @property
    def is_verified(self):
        return self.approval_status == ApprovalStatus.APPROVED

    @property
    def is_pending(self):
        return self.approval_status == ApprovalStatus.PENDING

    @property
    def is_studio_staff(self):
        return self.role in STAFF_ROLES

    @property
    def is_management(self):
        """Directors and administrators -- full run of the system."""
        return self.role in MANAGEMENT_ROLES or self.is_superuser

    @property
    def is_director(self):
        return self.role == Role.DIRECTOR or self.is_superuser

    @property
    def is_teacher(self):
        return self.role == Role.TEACHER

    @property
    def is_guardian(self):
        return self.role == Role.PARENT

    @property
    def is_student(self):
        return self.role == Role.STUDENT

    def has_studio_access(self):
        """Verified, active, and allowed through the dashboard gate."""
        return self.is_active and self.is_verified

    # -- actions -----------------------------------------------------------
    def approve(self, by=None, note=''):
        self.approval_status = ApprovalStatus.APPROVED
        self.verified_by = by
        self.verified_at = timezone.now()
        if note:
            self.verification_note = note
        self.is_active = True
        self.save(update_fields=[
            'approval_status', 'verified_by', 'verified_at',
            'verification_note', 'is_active', 'updated_at',
        ])

    def reject(self, by=None, note=''):
        self.approval_status = ApprovalStatus.REJECTED
        self.verified_by = by
        self.verified_at = timezone.now()
        self.verification_note = note
        self.save(update_fields=[
            'approval_status', 'verified_by', 'verified_at',
            'verification_note', 'updated_at',
        ])

    def suspend(self, by=None, note=''):
        self.approval_status = ApprovalStatus.SUSPENDED
        self.verified_by = by
        self.verification_note = note
        self.save(update_fields=[
            'approval_status', 'verified_by', 'verification_note', 'updated_at',
        ])

    def save(self, *args, **kwargs):
        # Django's ``is_staff`` controls the /admin back-door; the studio's own
        # notion of staff is ``role``. Keep directors/admins able to reach both.
        if self.role in MANAGEMENT_ROLES and self.is_verified:
            self.is_staff = True
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Shared behaviour
# ---------------------------------------------------------------------------
class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


def _next_sequence(model, field, prefix, width=4):
    """
    Build the next ``PREFIX-YYYY-0001`` style reference for *model*.*field*.

    Called inside the object's own ``save()`` within a transaction, so two
    concurrent enrolments cannot land on the same number.
    """
    year = timezone.now().year
    stem = f'{prefix}-{year}-'
    last = (
        model.objects.filter(**{f'{field}__startswith': stem})
        .aggregate(top=Max(field))['top']
    )
    counter = int(last.rsplit('-', 1)[-1]) + 1 if last else 1
    return f'{stem}{counter:0{width}d}'


# ---------------------------------------------------------------------------
# Staff
# ---------------------------------------------------------------------------
class StaffProfile(TimeStampedModel):
    """Employment and faculty-page detail for directors, admins and teachers."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='staff_profile',
    )
    staff_id = models.CharField(max_length=20, unique=True, blank=True, editable=False)

    job_title = models.CharField(
        max_length=120, blank=True,
        help_text=_('e.g. "Artistic Director", "Ballet Teacher - Junior Division"'),
    )
    employment_type = models.CharField(
        max_length=20, choices=EmploymentType.choices, default=EmploymentType.FULL_TIME,
    )
    date_joined_studio = models.DateField(null=True, blank=True)
    date_left_studio = models.DateField(null=True, blank=True)
    is_active_staff = models.BooleanField(default=True)

    # Faculty page content
    short_bio = models.CharField(
        max_length=255, blank=True, help_text=_('One-line introduction for the faculty page.'),
    )
    bio = models.TextField(blank=True)
    qualifications = models.TextField(
        blank=True, help_text=_('One qualification per line.'),
    )
    specialisms = models.CharField(
        max_length=255, blank=True,
        help_text=_('Comma separated, e.g. "Classical ballet, Contemporary, Pointe"'),
    )
    years_of_experience = models.PositiveSmallIntegerField(null=True, blank=True)

    # Payroll
    monthly_salary = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(0)],
        help_text=_('Gross monthly pay in UGX. Visible to directors and administrators only.'),
    )
    hourly_rate = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(0)],
    )
    bank_name = models.CharField(max_length=120, blank=True)
    bank_account_name = models.CharField(max_length=120, blank=True)
    bank_account_number = models.CharField(max_length=60, blank=True)
    mobile_money_number = PhoneNumberField(blank=True)
    national_id = models.CharField(_('NIN / national ID'), max_length=40, blank=True)
    tin_number = models.CharField(_('TIN'), max_length=40, blank=True)

    # Emergency contact
    emergency_contact_name = models.CharField(max_length=120, blank=True)
    emergency_contact_phone = PhoneNumberField(blank=True)
    emergency_contact_relationship = models.CharField(max_length=60, blank=True)

    # Public site
    show_on_website = models.BooleanField(
        default=False, help_text=_('Feature this person on the public Faculty page.'),
    )
    website_order = models.PositiveSmallIntegerField(default=0)
    instagram_url = models.URLField(blank=True)
    facebook_url = models.URLField(blank=True)
    linkedin_url = models.URLField(blank=True)

    class Meta:
        verbose_name = _('staff profile')
        verbose_name_plural = _('staff profiles')
        ordering = ('website_order', 'user__first_name')

    def __str__(self):
        title = self.job_title or self.user.get_role_display()
        return f'{self.user.display_name} - {title}'

    def get_absolute_url(self):
        return reverse('dashboard:staff_detail', args=[self.pk])

    @property
    def qualification_list(self):
        return [line.strip() for line in self.qualifications.splitlines() if line.strip()]

    @property
    def specialism_list(self):
        return [item.strip() for item in self.specialisms.split(',') if item.strip()]

    def save(self, *args, **kwargs):
        if not self.staff_id:
            with transaction.atomic():
                self.staff_id = _next_sequence(StaffProfile, 'staff_id', 'BDSU-STF', width=3)
                return super().save(*args, **kwargs)
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Guardians (parents)
# ---------------------------------------------------------------------------
class GuardianProfile(TimeStampedModel):
    """A parent or guardian -- the person who receives invoices and reports."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='guardian_profile',
    )
    guardian_id = models.CharField(max_length=20, unique=True, blank=True, editable=False)

    occupation = models.CharField(max_length=120, blank=True)
    employer = models.CharField(max_length=150, blank=True)
    alternate_phone = PhoneNumberField(blank=True)
    national_id = models.CharField(_('NIN / national ID'), max_length=40, blank=True)

    residential_address = models.CharField(max_length=255, blank=True)
    postal_address = models.CharField(max_length=120, blank=True)

    preferred_contact_method = models.CharField(
        max_length=20, choices=ContactMethod.choices, default=ContactMethod.WHATSAPP,
    )
    receives_invoices = models.BooleanField(
        default=True, help_text=_('Send fee invoices and statements to this guardian.'),
    )
    receives_progress_reports = models.BooleanField(default=True)

    emergency_contact_name = models.CharField(max_length=120, blank=True)
    emergency_contact_phone = PhoneNumberField(blank=True)
    emergency_contact_relationship = models.CharField(max_length=60, blank=True)

    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = _('guardian profile')
        verbose_name_plural = _('guardian profiles')
        ordering = ('user__first_name', 'user__last_name')

    def __str__(self):
        return self.user.display_name

    def get_absolute_url(self):
        return reverse('dashboard:guardian_detail', args=[self.pk])

    @property
    def students(self):
        return Student.objects.filter(guardian_links__guardian=self).distinct()

    def save(self, *args, **kwargs):
        if not self.guardian_id:
            with transaction.atomic():
                self.guardian_id = _next_sequence(
                    GuardianProfile, 'guardian_id', 'BDSU-GRD', width=4,
                )
                return super().save(*args, **kwargs)
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Students
# ---------------------------------------------------------------------------
class StudentQuerySet(models.QuerySet):
    def active(self):
        return self.filter(status=StudentStatus.ACTIVE)

    def with_logins(self):
        return self.filter(user__isnull=False)

    def for_guardian(self, guardian):
        return self.filter(guardian_links__guardian=guardian).distinct()

    def for_teacher(self, user):
        """Students enrolled in any class the given teacher leads."""
        return self.filter(
            enrolments__dance_class__teachers__user=user,
            enrolments__status='active',
        ).distinct()


class Student(TimeStampedModel):
    """
    A dancer at the studio.

    ``user`` is optional on purpose: Kinder Ballet children are enrolled by
    their guardians long before they have their own login. Names therefore live
    on the student record, not on the account.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='student_profile',
        help_text=_('Optional. Link once the dancer is old enough for their own login.'),
    )
    student_id = models.CharField(max_length=20, unique=True, blank=True, editable=False)

    first_name = models.CharField(max_length=80)
    middle_name = models.CharField(max_length=80, blank=True)
    last_name = models.CharField(max_length=80)
    preferred_name = models.CharField(
        max_length=80, blank=True, help_text=_('What the dancer is actually called in class.'),
    )
    date_of_birth = models.DateField()
    gender = models.CharField(max_length=1, choices=Gender.choices, default=Gender.UNDISCLOSED)
    photo = models.ImageField(upload_to='people/students/', blank=True)

    guardians = models.ManyToManyField(
        GuardianProfile, through='StudentGuardian', related_name='wards', blank=True,
    )

    status = models.CharField(
        max_length=20, choices=StudentStatus.choices, default=StudentStatus.ACTIVE, db_index=True,
    )
    enrolment_date = models.DateField(default=dt.date.today)
    withdrawal_date = models.DateField(null=True, blank=True)
    withdrawal_reason = models.TextField(blank=True)

    # Background
    school_name = models.CharField(
        _('day school'), max_length=150, blank=True,
        help_text=_('The regular school the dancer attends.'),
    )
    home_address = models.CharField(max_length=255, blank=True)
    how_heard_about_us = models.CharField(max_length=150, blank=True)
    previous_dance_experience = models.TextField(blank=True)

    # Costume / wardrobe -- needed every December for the recital
    height_cm = models.PositiveSmallIntegerField(null=True, blank=True)
    leotard_size = models.CharField(max_length=20, blank=True)
    shoe_size = models.CharField(max_length=20, blank=True)

    # Health -- all optional, all sensitive
    blood_group = models.CharField(max_length=10, blank=True)
    sickle_cell_status = models.CharField(
        max_length=20, choices=SickleCellStatus.choices, default=SickleCellStatus.UNDISCLOSED,
        help_text=_('Optional. Helps teachers plan hydration and rest breaks safely.'),
    )
    medical_conditions = models.TextField(blank=True)
    allergies = models.TextField(blank=True)
    medication = models.TextField(blank=True)
    doctor_name = models.CharField(max_length=120, blank=True)
    doctor_phone = PhoneNumberField(blank=True)
    medical_notes = models.TextField(blank=True)

    # Consents
    photo_consent = models.BooleanField(
        default=False, help_text=_('Guardian permits photos of this dancer in studio media.'),
    )
    media_consent = models.BooleanField(
        default=False, help_text=_('Guardian permits use in public marketing and press.'),
    )
    medical_treatment_consent = models.BooleanField(default=False)

    notes = models.TextField(blank=True, help_text=_('Internal staff notes.'))

    objects = StudentQuerySet.as_manager()

    class Meta:
        verbose_name = _('student')
        verbose_name_plural = _('students')
        ordering = ('first_name', 'last_name')
        indexes = [
            models.Index(fields=('status',)),
            models.Index(fields=('last_name', 'first_name')),
        ]

    def __str__(self):
        return f'{self.full_name} ({self.student_id})'

    def get_absolute_url(self):
        return reverse('academics:student_detail', args=[self.pk])

    @property
    def full_name(self):
        return ' '.join(p for p in (self.first_name, self.last_name) if p)

    @property
    def display_name(self):
        return self.preferred_name or self.first_name

    @property
    def age(self):
        today = dt.date.today()
        born = self.date_of_birth
        return today.year - born.year - ((today.month, today.day) < (born.month, born.day))

    @property
    def initials(self):
        return f'{self.first_name[:1]}{self.last_name[:1]}'.upper()

    @property
    def primary_guardian(self):
        link = self.guardian_links.filter(is_primary=True).select_related('guardian__user').first()
        return link.guardian if link else None

    @property
    def billing_guardian(self):
        """Whoever should receive this dancer's invoices."""
        link = (
            self.guardian_links.filter(receives_invoices=True)
            .select_related('guardian__user')
            .order_by('-is_primary')
            .first()
        )
        return link.guardian if link else self.primary_guardian

    @property
    def needs_health_watch(self):
        return self.sickle_cell_status in {SickleCellStatus.TRAIT, SickleCellStatus.DISEASE}

    def save(self, *args, **kwargs):
        if not self.student_id:
            with transaction.atomic():
                self.student_id = _next_sequence(Student, 'student_id', 'BDSU', width=4)
                return super().save(*args, **kwargs)
        super().save(*args, **kwargs)


class StudentGuardian(models.Model):
    """Links a dancer to a guardian, and says what that guardian may do."""

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='guardian_links')
    guardian = models.ForeignKey(
        GuardianProfile, on_delete=models.CASCADE, related_name='student_links',
    )
    relationship = models.CharField(
        max_length=20, choices=Relationship.choices, default=Relationship.GUARDIAN,
    )
    is_primary = models.BooleanField(
        default=False, help_text=_('The main contact for this dancer.'),
    )
    is_emergency_contact = models.BooleanField(default=True)
    can_collect = models.BooleanField(
        default=True, help_text=_('May collect the dancer after class.'),
    )
    receives_invoices = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('guardian link')
        verbose_name_plural = _('guardian links')
        constraints = [
            models.UniqueConstraint(
                fields=('student', 'guardian'), name='unique_student_guardian',
            ),
        ]
        ordering = ('-is_primary', 'guardian__user__first_name')

    def __str__(self):
        return f'{self.guardian} -> {self.student.full_name} ({self.get_relationship_display()})'


# ---------------------------------------------------------------------------
# Cross-cutting: notifications and audit
# ---------------------------------------------------------------------------
class NotificationLevel(models.TextChoices):
    INFO = 'info', _('Information')
    SUCCESS = 'success', _('Success')
    WARNING = 'warning', _('Warning')
    URGENT = 'urgent', _('Urgent')


class Notification(models.Model):
    """In-app notification shown in the dashboard bell menu."""

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications',
    )
    title = models.CharField(max_length=160)
    message = models.TextField(blank=True)
    level = models.CharField(
        max_length=20, choices=NotificationLevel.choices, default=NotificationLevel.INFO,
    )
    url = models.CharField(max_length=300, blank=True)
    icon = models.CharField(max_length=60, blank=True, default='fa-bell')
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ('-created_at',)
        indexes = [models.Index(fields=('recipient', 'is_read'))]

    def __str__(self):
        return f'{self.title} -> {self.recipient.display_name}'

    def mark_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])

    @classmethod
    def send(cls, recipients, title, message='', level=NotificationLevel.INFO, url='', icon='fa-bell'):
        """Fan a notification out to one user or an iterable of users."""
        if isinstance(recipients, User):
            recipients = [recipients]
        return cls.objects.bulk_create([
            cls(recipient=user, title=title, message=message,
                level=level, url=url, icon=icon)
            for user in recipients
        ])


class AuditLog(models.Model):
    """
    A plain-language trail of who changed what.

    Money and student records are the two things the studio most needs to be
    able to answer questions about months later, so writes to those go here.
    """

    class Action(models.TextChoices):
        CREATE = 'create', _('Created')
        UPDATE = 'update', _('Updated')
        DELETE = 'delete', _('Deleted')
        APPROVE = 'approve', _('Approved')
        REJECT = 'reject', _('Rejected')
        LOGIN = 'login', _('Signed in')
        EXPORT = 'export', _('Exported')

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='audit_entries',
    )
    action = models.CharField(max_length=20, choices=Action.choices)
    target_model = models.CharField(max_length=80, blank=True)
    target_id = models.CharField(max_length=40, blank=True)
    description = models.CharField(max_length=300)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _('audit log entry')
        verbose_name_plural = _('audit log')
        ordering = ('-created_at',)

    def __str__(self):
        who = self.actor.display_name if self.actor else 'System'
        return f'{who} {self.get_action_display().lower()} {self.description}'

    @classmethod
    def record(cls, actor, action, description, obj=None, request=None):
        ip = None
        if request is not None:
            forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
            ip = forwarded.split(',')[0].strip() or request.META.get('REMOTE_ADDR')
        return cls.objects.create(
            actor=actor if getattr(actor, 'is_authenticated', False) else None,
            action=action,
            description=description[:300],
            target_model=obj._meta.label if obj is not None else '',
            target_id=str(obj.pk) if obj is not None else '',
            ip_address=ip or None,
        )
