"""
Everything on the studio calendar.

:class:`Event` powers the public month/year calendar and the events listing.
:class:`Recital` is a first-class model of its own because the annual
December recital -- the studio's sickle cell awareness performance -- gets a
dedicated page, a cast list, a programme of works and a fundraising total.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Student, TimeStampedModel

ZERO = Decimal('0.00')


# ---------------------------------------------------------------------------
# Choices
# ---------------------------------------------------------------------------
class EventStatus(models.TextChoices):
    DRAFT = 'draft', _('Draft')
    SCHEDULED = 'scheduled', _('Scheduled')
    CANCELLED = 'cancelled', _('Cancelled')
    POSTPONED = 'postponed', _('Postponed')
    COMPLETED = 'completed', _('Completed')


class Audience(models.TextChoices):
    PUBLIC = 'public', _('Everyone (public)')
    STUDENTS = 'students', _('Students and guardians')
    GUARDIANS = 'guardians', _('Guardians only')
    STAFF = 'staff', _('Staff only')


class RegistrationStatus(models.TextChoices):
    PENDING = 'pending', _('Pending')
    CONFIRMED = 'confirmed', _('Confirmed')
    WAITLIST = 'waitlist', _('Waiting list')
    CANCELLED = 'cancelled', _('Cancelled')
    ATTENDED = 'attended', _('Attended')


class RecitalRole(models.TextChoices):
    PRINCIPAL = 'principal', _('Principal')
    SOLOIST = 'soloist', _('Soloist')
    CORPS = 'corps', _('Corps de ballet')
    ENSEMBLE = 'ensemble', _('Ensemble')
    UNDERSTUDY = 'understudy', _('Understudy')


class PartnerTier(models.TextChoices):
    HEADLINE = 'headline', _('Headline partner')
    GOLD = 'gold', _('Gold')
    SILVER = 'silver', _('Silver')
    BRONZE = 'bronze', _('Bronze')
    COMMUNITY = 'community', _('Community partner')


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------
class EventCategory(models.Model):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=100, unique=True, blank=True)
    description = models.TextField(blank=True)
    colour = models.CharField(
        max_length=7, default='#EE2A7B',
        help_text=_('Colour this category shows as on the calendar.'),
    )
    icon = models.CharField(max_length=60, blank=True, default='fa-calendar-day')
    display_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = _('event category')
        verbose_name_plural = _('event categories')
        ordering = ('display_order', 'name')

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:100]
        super().save(*args, **kwargs)


class EventQuerySet(models.QuerySet):
    def published(self):
        return self.filter(status__in=[EventStatus.SCHEDULED, EventStatus.COMPLETED])

    def public(self):
        return self.published().filter(audience=Audience.PUBLIC)

    def upcoming(self):
        return self.published().filter(start_at__gte=timezone.now()).order_by('start_at')

    def past(self):
        return self.published().filter(start_at__lt=timezone.now()).order_by('-start_at')

    def in_month(self, year, month):
        return self.filter(start_at__year=year, start_at__month=month)

    def visible_to(self, user):
        """Filter by audience for the signed-in (or anonymous) viewer."""
        if not getattr(user, 'is_authenticated', False):
            return self.public()
        if user.is_studio_staff:
            return self.published()
        allowed = [Audience.PUBLIC, Audience.STUDENTS]
        if user.is_guardian:
            allowed.append(Audience.GUARDIANS)
        return self.published().filter(audience__in=allowed)


class Event(TimeStampedModel):
    """A dated happening: class showing, workshop, masterclass, open day, trip."""

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    category = models.ForeignKey(
        EventCategory, null=True, blank=True, on_delete=models.SET_NULL, related_name='events',
    )

    summary = models.CharField(
        max_length=300, blank=True, help_text=_('One or two lines for calendar tooltips and cards.'),
    )
    description = models.TextField(blank=True)

    start_at = models.DateTimeField(db_index=True)
    end_at = models.DateTimeField(null=True, blank=True)
    is_all_day = models.BooleanField(default=False)

    venue_name = models.CharField(max_length=180, blank=True)
    venue_address = models.CharField(max_length=255, blank=True)
    map_url = models.URLField(blank=True)

    poster = models.ImageField(upload_to='events/posters/', blank=True)
    banner = models.ImageField(upload_to='events/banners/', blank=True)

    status = models.CharField(
        max_length=20, choices=EventStatus.choices, default=EventStatus.SCHEDULED, db_index=True,
    )
    audience = models.CharField(
        max_length=20, choices=Audience.choices, default=Audience.PUBLIC, db_index=True,
    )
    is_featured = models.BooleanField(
        default=False, help_text=_('Highlight on the home page and events banner.'),
    )

    requires_registration = models.BooleanField(default=False)
    registration_closes_at = models.DateTimeField(null=True, blank=True)
    capacity = models.PositiveSmallIntegerField(null=True, blank=True)
    ticket_price = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(ZERO)],
        help_text=_('Leave empty for a free event. Tickets are sold in person.'),
    )

    contact_name = models.CharField(max_length=140, blank=True)
    contact_phone = models.CharField(max_length=40, blank=True)
    contact_email = models.EmailField(blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='events_created',
    )
    cancellation_reason = models.CharField(max_length=250, blank=True)

    objects = EventQuerySet.as_manager()

    class Meta:
        ordering = ('start_at',)
        indexes = [
            models.Index(fields=('start_at', 'status')),
            models.Index(fields=('audience', 'status')),
        ]

    def __str__(self):
        return f'{self.title} - {self.start_at:%d %b %Y}'

    def get_absolute_url(self):
        return reverse('events:detail', args=[self.slug])

    def clean(self):
        if self.end_at and self.end_at < self.start_at:
            raise ValidationError({'end_at': _('An event cannot end before it starts.')})

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(f'{self.title}-{self.start_at:%Y-%m}')[:210]
            slug, n = base, 2
            while Event.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base}-{n}'
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)

    # -- derived -----------------------------------------------------------
    @property
    def is_past(self):
        return (self.end_at or self.start_at) < timezone.now()

    @property
    def is_today(self):
        return timezone.localdate(self.start_at) == dt.date.today()

    @property
    def days_until(self):
        return (timezone.localdate(self.start_at) - dt.date.today()).days

    @property
    def duration_display(self):
        if self.is_all_day:
            return 'All day'
        if not self.end_at:
            return f'{timezone.localtime(self.start_at):%H:%M}'
        return (
            f'{timezone.localtime(self.start_at):%H:%M} - '
            f'{timezone.localtime(self.end_at):%H:%M}'
        )

    @property
    def is_free(self):
        return self.ticket_price is None or self.ticket_price <= ZERO

    @property
    def confirmed_registrations(self):
        return self.registrations.filter(
            status__in=[RegistrationStatus.CONFIRMED, RegistrationStatus.ATTENDED],
        )

    @property
    def seats_taken(self):
        return self.confirmed_registrations.aggregate(t=Sum('seats'))['t'] or 0

    @property
    def seats_left(self):
        if self.capacity is None:
            return None
        return max(0, self.capacity - self.seats_taken)

    @property
    def registration_open(self):
        if not self.requires_registration or self.status != EventStatus.SCHEDULED:
            return False
        if self.registration_closes_at and self.registration_closes_at < timezone.now():
            return False
        if self.start_at < timezone.now():
            return False
        return self.seats_left is None or self.seats_left > 0

    def financial_summary(self):
        """Income and cost attributed to this event, for the finance reports."""
        income = self.income_entries.aggregate(t=Sum('amount'))['t'] or ZERO
        cost = self.expenses.aggregate(t=Sum('amount'))['t'] or ZERO
        return {'income': income, 'expenses': cost, 'net': income - cost}


class EventRegistration(TimeStampedModel):
    """A seat reservation. Payment, if any, is taken in person and logged in finance."""

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='registrations')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='event_registrations',
    )
    full_name = models.CharField(max_length=140)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    seats = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1)])
    status = models.CharField(
        max_length=20, choices=RegistrationStatus.choices, default=RegistrationStatus.PENDING,
    )
    notes = models.TextField(blank=True)
    checked_in_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _('event registration')
        ordering = ('-created_at',)

    def __str__(self):
        return f'{self.full_name} - {self.event.title} ({self.seats})'


# ---------------------------------------------------------------------------
# The annual recital
# ---------------------------------------------------------------------------
class Recital(TimeStampedModel):
    """
    The studio's flagship December performance, staged for sickle cell
    awareness. One record per year, with its own public page.
    """

    year = models.PositiveSmallIntegerField(unique=True, db_index=True)
    title = models.CharField(max_length=200, help_text=_('e.g. "Hope in Motion"'))
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    theme = models.CharField(max_length=200, blank=True)
    tagline = models.CharField(
        max_length=250, blank=True, default='Resilience. Hope. Dreams.',
    )

    event = models.OneToOneField(
        Event, null=True, blank=True, on_delete=models.SET_NULL, related_name='recital',
        help_text=_('The calendar entry for this recital.'),
    )

    performance_date = models.DateField(
        help_text=_('The studio stages this in the first week of December each year.'),
    )
    additional_dates = models.CharField(
        max_length=200, blank=True, help_text=_('Any matinee or second night, free text.'),
    )
    doors_open_time = models.TimeField(null=True, blank=True)
    start_time = models.TimeField(null=True, blank=True)
    venue_name = models.CharField(max_length=180, blank=True)
    venue_address = models.CharField(max_length=255, blank=True)

    # Story
    introduction = models.TextField(
        blank=True, help_text=_('The opening paragraph on the recital page.'),
    )
    description = models.TextField(blank=True)
    sickle_cell_message = models.TextField(
        blank=True,
        help_text=_('Why the studio dances for sickle cell awareness. Shown prominently.'),
    )
    director_note = models.TextField(blank=True)

    # Media
    hero_image = models.ImageField(upload_to='recitals/hero/', blank=True)
    hero_video = models.FileField(
        upload_to='recitals/video/', blank=True,
        help_text=_('Optional background video for the recital page hero.'),
    )
    hero_video_url = models.URLField(
        blank=True, help_text=_('Or paste a hosted video URL instead of uploading.'),
    )
    poster = models.ImageField(upload_to='recitals/posters/', blank=True)
    programme_pdf = models.FileField(upload_to='recitals/programmes/', blank=True)
    trailer_url = models.URLField(blank=True, help_text=_('YouTube or Vimeo link.'))
    gallery_album = models.ForeignKey(
        'website.GalleryAlbum', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='recitals',
    )

    # Tickets (sold in person)
    ticket_price_regular = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(ZERO)],
    )
    ticket_price_vip = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(ZERO)],
    )
    ticket_price_child = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(ZERO)],
    )
    ticket_info = models.TextField(
        blank=True, help_text=_('Where and how to buy. Tickets are not sold online.'),
    )

    # Fundraising
    fundraising_goal = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(ZERO)],
        help_text=_('Target raised for the sickle cell cause, in UGX.'),
    )
    beneficiary = models.CharField(
        max_length=200, blank=True,
        help_text=_('The organisation or fund the proceeds support.'),
    )
    beneficiary_url = models.URLField(blank=True)

    is_published = models.BooleanField(default=False)
    is_current = models.BooleanField(
        default=False, help_text=_('The recital the public page shows by default.'),
    )

    class Meta:
        verbose_name = _('recital')
        ordering = ('-year',)

    def __str__(self):
        return f'{self.title} ({self.year})'

    def get_absolute_url(self):
        return reverse('events:recital_year', args=[self.year])

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(f'{self.title}-{self.year}')[:220]
        super().save(*args, **kwargs)
        if self.is_current:
            Recital.objects.exclude(pk=self.pk).update(is_current=False)

    @classmethod
    def current(cls):
        return (
            cls.objects.filter(is_current=True, is_published=True).first()
            or cls.objects.filter(is_published=True).order_by('-year').first()
        )

    # -- derived -----------------------------------------------------------
    @property
    def is_upcoming(self):
        return self.performance_date >= dt.date.today()

    @property
    def days_until(self):
        return (self.performance_date - dt.date.today()).days

    @property
    def amount_raised(self):
        """Confirmed income attributed to this recital's calendar event."""
        if not self.event_id:
            return ZERO
        return self.event.income_entries.aggregate(t=Sum('amount'))['t'] or ZERO

    @property
    def fundraising_percent(self):
        if not self.fundraising_goal or self.fundraising_goal <= ZERO:
            return None
        return min(100, round(self.amount_raised / self.fundraising_goal * 100))

    @property
    def cast_size(self):
        return (
            RecitalCast.objects.filter(performance__recital=self)
            .values('student').distinct().count()
        )


class RecitalPerformance(models.Model):
    """One piece in the recital programme."""

    recital = models.ForeignKey(Recital, on_delete=models.CASCADE, related_name='performances')
    order = models.PositiveSmallIntegerField(default=0)
    act = models.CharField(max_length=40, blank=True, help_text=_('e.g. "Act I", "Finale"'))
    title = models.CharField(max_length=200)
    music = models.CharField(max_length=250, blank=True, help_text=_('Composer and work.'))
    choreographer = models.CharField(max_length=180, blank=True)
    dance_class = models.ForeignKey(
        'academics.DanceClass', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='recital_performances',
    )
    duration_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    description = models.TextField(blank=True)
    costume_notes = models.TextField(blank=True)
    image = models.ImageField(upload_to='recitals/performances/', blank=True)

    class Meta:
        verbose_name = _('programme item')
        verbose_name_plural = _('programme')
        ordering = ('order', 'id')

    def __str__(self):
        return f'{self.order}. {self.title}'


class RecitalCast(models.Model):
    """A dancer's part in a piece."""

    performance = models.ForeignKey(
        RecitalPerformance, on_delete=models.CASCADE, related_name='cast',
    )
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='recital_roles')
    role_name = models.CharField(max_length=140, blank=True, help_text=_('The character or part.'))
    role_type = models.CharField(
        max_length=20, choices=RecitalRole.choices, default=RecitalRole.ENSEMBLE,
    )
    costume_ready = models.BooleanField(default=False)
    notes = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = _('cast member')
        verbose_name_plural = _('cast')
        ordering = ('performance__order', 'role_type', 'student__first_name')
        constraints = [
            models.UniqueConstraint(
                fields=('performance', 'student'), name='unique_cast_per_performance',
            ),
        ]

    def __str__(self):
        return f'{self.student.full_name} - {self.role_name or self.get_role_type_display()}'


class RehearsalSchedule(models.Model):
    """Rehearsal calls in the run-up to the recital."""

    recital = models.ForeignKey(Recital, on_delete=models.CASCADE, related_name='rehearsals')
    title = models.CharField(max_length=180)
    date = models.DateField(db_index=True)
    start_time = models.TimeField()
    end_time = models.TimeField(null=True, blank=True)
    venue = models.CharField(max_length=180, blank=True)
    performances = models.ManyToManyField(
        RecitalPerformance, blank=True, related_name='rehearsals',
        help_text=_('Which pieces are called for this rehearsal.'),
    )
    is_full_cast = models.BooleanField(default=False)
    is_dress_rehearsal = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = _('rehearsal')
        ordering = ('date', 'start_time')

    def __str__(self):
        return f'{self.title} - {self.date:%d %b}'


class Partner(models.Model):
    """
    Sponsors and awareness partners -- shown on the recital page and in the
    footer's supporters strip.
    """

    name = models.CharField(max_length=180)
    tier = models.CharField(
        max_length=20, choices=PartnerTier.choices, default=PartnerTier.COMMUNITY,
    )
    logo = models.ImageField(upload_to='partners/', blank=True)
    website_url = models.URLField(blank=True)
    description = models.TextField(blank=True)
    recitals = models.ManyToManyField(Recital, blank=True, related_name='partners')
    is_sickle_cell_partner = models.BooleanField(
        default=False, help_text=_('A sickle cell organisation, not a commercial sponsor.'),
    )
    display_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ('display_order', 'name')

    def __str__(self):
        return self.name
