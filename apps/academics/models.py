"""
Teaching and training models.

Covers the studio calendar (academic years and terms), what is taught
(programmes and classes), who is in the room (enrolments, sessions,
attendance) and how each dancer is developing (the skill rubric).

Progress is assessed with a *rubric*: every programme has a set of skills
grouped into categories, and each assessment period a teacher scores those
skills and writes comments. Scores over time become the dancer's progress
chart -- no formal exam ladder.
"""

from __future__ import annotations

import datetime as dt

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Avg, Count, Q
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Student, TimeStampedModel


# ---------------------------------------------------------------------------
# Choices
# ---------------------------------------------------------------------------
class Weekday(models.IntegerChoices):
    MONDAY = 0, _('Monday')
    TUESDAY = 1, _('Tuesday')
    WEDNESDAY = 2, _('Wednesday')
    THURSDAY = 3, _('Thursday')
    FRIDAY = 4, _('Friday')
    SATURDAY = 5, _('Saturday')
    SUNDAY = 6, _('Sunday')


class EnrolmentStatus(models.TextChoices):
    ACTIVE = 'active', _('Active')
    COMPLETED = 'completed', _('Completed')
    WITHDRAWN = 'withdrawn', _('Withdrawn')
    TRIAL = 'trial', _('Trial class')
    WAITLIST = 'waitlist', _('Waiting list')


class SessionStatus(models.TextChoices):
    SCHEDULED = 'scheduled', _('Scheduled')
    HELD = 'held', _('Held')
    CANCELLED = 'cancelled', _('Cancelled')
    HOLIDAY = 'holiday', _('Studio holiday')


class AttendanceStatus(models.TextChoices):
    PRESENT = 'present', _('Present')
    LATE = 'late', _('Late')
    EXCUSED = 'excused', _('Excused absence')
    ABSENT = 'absent', _('Absent')


#: Statuses that count towards a dancer's attendance rate.
ATTENDED_STATUSES = frozenset({AttendanceStatus.PRESENT, AttendanceStatus.LATE})


class ReportStatus(models.TextChoices):
    DRAFT = 'draft', _('Draft')
    SUBMITTED = 'submitted', _('Submitted for review')
    PUBLISHED = 'published', _('Published to guardians')


class ApplicationStatus(models.TextChoices):
    NEW = 'new', _('New enquiry')
    CONTACTED = 'contacted', _('Contacted')
    TRIAL_BOOKED = 'trial_booked', _('Trial booked')
    ACCEPTED = 'accepted', _('Accepted / enrolled')
    DECLINED = 'declined', _('Declined')


# ---------------------------------------------------------------------------
# Studio calendar
# ---------------------------------------------------------------------------
class AcademicYear(models.Model):
    name = models.CharField(max_length=40, unique=True, help_text=_('e.g. "2026"'))
    start_date = models.DateField()
    end_date = models.DateField()
    is_current = models.BooleanField(default=False)

    class Meta:
        verbose_name = _('academic year')
        ordering = ('-start_date',)

    def __str__(self):
        return self.name

    def clean(self):
        if self.end_date <= self.start_date:
            raise ValidationError({'end_date': _('The year must end after it starts.')})

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_current:
            AcademicYear.objects.exclude(pk=self.pk).update(is_current=False)

    @classmethod
    def current(cls):
        return cls.objects.filter(is_current=True).first() or cls.objects.first()


class Term(models.Model):
    """A teaching term. Fees, enrolments and progress reports all hang off one."""

    academic_year = models.ForeignKey(
        AcademicYear, on_delete=models.CASCADE, related_name='terms',
    )
    name = models.CharField(max_length=60, help_text=_('e.g. "Term 1", "Easter Holiday Intensive"'))
    start_date = models.DateField()
    end_date = models.DateField()
    is_current = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ('-start_date',)
        constraints = [
            models.UniqueConstraint(fields=('academic_year', 'name'), name='unique_term_per_year'),
        ]

    def __str__(self):
        return f'{self.name} {self.academic_year.name}'

    def clean(self):
        if self.end_date <= self.start_date:
            raise ValidationError({'end_date': _('The term must end after it starts.')})

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_current:
            Term.objects.exclude(pk=self.pk).update(is_current=False)

    @classmethod
    def current(cls):
        today = dt.date.today()
        return (
            cls.objects.filter(is_current=True).first()
            or cls.objects.filter(start_date__lte=today, end_date__gte=today).first()
            or cls.objects.first()
        )

    @property
    def is_running(self):
        return self.start_date <= dt.date.today() <= self.end_date

    @property
    def week_count(self):
        return max(1, ((self.end_date - self.start_date).days // 7) + 1)


class Studio(models.Model):
    """A physical room. Used for timetabling and clash detection."""

    name = models.CharField(max_length=80, unique=True, help_text=_('e.g. "Studio A"'))
    location = models.CharField(max_length=200, blank=True)
    capacity = models.PositiveSmallIntegerField(default=20)
    has_barre = models.BooleanField(default=True)
    has_mirrors = models.BooleanField(default=True)
    has_sprung_floor = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = _('studio / room')
        verbose_name_plural = _('studios / rooms')
        ordering = ('name',)

    def __str__(self):
        return self.name


# ---------------------------------------------------------------------------
# What is taught
# ---------------------------------------------------------------------------
class Program(TimeStampedModel):
    """
    A stream of training -- Kinder Ballet, Junior Ballet, Adult Ballet and so on.

    Doubles as public marketing content: everything on this model is safe to
    show on the programmes page.
    """

    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    tagline = models.CharField(max_length=180, blank=True)
    description = models.TextField()
    what_you_learn = models.TextField(
        blank=True, help_text=_('One outcome per line. Shown as a bullet list publicly.'),
    )

    min_age = models.PositiveSmallIntegerField(default=3)
    max_age = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text=_('Leave empty for "and above".'),
    )
    level_label = models.CharField(
        max_length=60, blank=True, help_text=_('e.g. "Introductory", "Foundation", "All levels"'),
    )

    image = models.ImageField(upload_to='programmes/', blank=True)
    accent_colour = models.CharField(
        max_length=7, default='#EE2A7B',
        help_text=_('Hex colour used on cards and charts for this programme.'),
    )
    icon = models.CharField(max_length=60, blank=True, default='fa-shoe-prints')

    duration_minutes = models.PositiveSmallIntegerField(default=60)
    sessions_per_week = models.PositiveSmallIntegerField(default=1)

    is_active = models.BooleanField(default=True)
    show_on_website = models.BooleanField(default=True)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = _('programme')
        verbose_name_plural = _('programmes')
        ordering = ('display_order', 'min_age')

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('website:programme_detail', args=[self.slug])

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:140]
        super().save(*args, **kwargs)

    @property
    def age_range_display(self):
        if self.max_age:
            return f'Ages {self.min_age}-{self.max_age}'
        return f'Ages {self.min_age}+'

    @property
    def outcome_list(self):
        return [line.strip() for line in self.what_you_learn.splitlines() if line.strip()]

    @property
    def active_student_count(self):
        return (
            Student.objects.filter(
                enrolments__dance_class__program=self,
                enrolments__status=EnrolmentStatus.ACTIVE,
            )
            .distinct()
            .count()
        )


class DanceClassQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def for_term(self, term):
        return self.filter(term=term)

    def taught_by(self, user):
        return self.filter(teachers__user=user).distinct()


class DanceClass(TimeStampedModel):
    """A specific taught group, e.g. "Junior Ballet A - Term 1 2026"."""

    name = models.CharField(max_length=140)
    slug = models.SlugField(max_length=160, blank=True)
    program = models.ForeignKey(Program, on_delete=models.PROTECT, related_name='classes')
    term = models.ForeignKey(Term, on_delete=models.PROTECT, related_name='classes')
    teachers = models.ManyToManyField(
        'accounts.StaffProfile', related_name='classes_taught', blank=True,
    )
    studio = models.ForeignKey(
        Studio, null=True, blank=True, on_delete=models.SET_NULL, related_name='classes',
    )

    capacity = models.PositiveSmallIntegerField(default=20)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    objects = DanceClassQuerySet.as_manager()

    class Meta:
        verbose_name = _('class')
        verbose_name_plural = _('classes')
        ordering = ('program__display_order', 'name')
        constraints = [
            models.UniqueConstraint(fields=('name', 'term'), name='unique_class_name_per_term'),
        ]

    def __str__(self):
        return f'{self.name} ({self.term})'

    def get_absolute_url(self):
        return reverse('academics:class_detail', args=[self.pk])

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:160]
        super().save(*args, **kwargs)

    @property
    def enrolled_count(self):
        return self.enrolments.filter(status=EnrolmentStatus.ACTIVE).count()

    @property
    def places_left(self):
        return max(0, self.capacity - self.enrolled_count)

    @property
    def is_full(self):
        return self.places_left == 0

    @property
    def fill_percent(self):
        if not self.capacity:
            return 0
        return round(self.enrolled_count / self.capacity * 100)

    @property
    def teacher_names(self):
        return ', '.join(t.user.display_name for t in self.teachers.all()) or 'Unassigned'

    @property
    def schedule_display(self):
        return ' | '.join(str(s) for s in self.schedules.all()) or 'No timetable set'

    def attendance_rate(self, since=None):
        """Percentage of registered attendance marks that were present or late."""
        marks = Attendance.objects.filter(session__dance_class=self)
        if since:
            marks = marks.filter(session__date__gte=since)
        totals = marks.aggregate(
            total=Count('id'),
            attended=Count('id', filter=Q(status__in=ATTENDED_STATUSES)),
        )
        if not totals['total']:
            return None
        return round(totals['attended'] / totals['total'] * 100, 1)


class ClassSchedule(models.Model):
    """A recurring weekly slot. Sessions are generated from these."""

    dance_class = models.ForeignKey(
        DanceClass, on_delete=models.CASCADE, related_name='schedules',
    )
    weekday = models.IntegerField(choices=Weekday.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()
    studio = models.ForeignKey(
        Studio, null=True, blank=True, on_delete=models.SET_NULL, related_name='schedules',
    )

    class Meta:
        verbose_name = _('timetable slot')
        ordering = ('weekday', 'start_time')
        constraints = [
            models.UniqueConstraint(
                fields=('dance_class', 'weekday', 'start_time'), name='unique_class_slot',
            ),
        ]

    def __str__(self):
        return (
            f'{self.get_weekday_display()} '
            f'{self.start_time:%H:%M}-{self.end_time:%H:%M}'
        )

    def clean(self):
        if self.end_time <= self.start_time:
            raise ValidationError({'end_time': _('A class must end after it starts.')})

    @property
    def duration_minutes(self):
        start = dt.datetime.combine(dt.date.today(), self.start_time)
        end = dt.datetime.combine(dt.date.today(), self.end_time)
        return int((end - start).total_seconds() // 60)


class Enrolment(TimeStampedModel):
    """One dancer in one class for one term."""

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='enrolments')
    dance_class = models.ForeignKey(
        DanceClass, on_delete=models.CASCADE, related_name='enrolments',
    )
    status = models.CharField(
        max_length=20, choices=EnrolmentStatus.choices,
        default=EnrolmentStatus.ACTIVE, db_index=True,
    )
    date_enrolled = models.DateField(default=dt.date.today)
    date_ended = models.DateField(null=True, blank=True)
    enrolled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='enrolments_created',
    )
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = _('enrolment')
        ordering = ('-date_enrolled',)
        constraints = [
            models.UniqueConstraint(
                fields=('student', 'dance_class'), name='unique_student_per_class',
            ),
        ]
        indexes = [models.Index(fields=('status', 'dance_class'))]

    def __str__(self):
        return f'{self.student.full_name} in {self.dance_class.name}'

    @property
    def term(self):
        return self.dance_class.term

    def attendance_summary(self):
        marks = Attendance.objects.filter(
            student=self.student, session__dance_class=self.dance_class,
        )
        totals = marks.aggregate(
            total=Count('id'),
            present=Count('id', filter=Q(status=AttendanceStatus.PRESENT)),
            late=Count('id', filter=Q(status=AttendanceStatus.LATE)),
            excused=Count('id', filter=Q(status=AttendanceStatus.EXCUSED)),
            absent=Count('id', filter=Q(status=AttendanceStatus.ABSENT)),
        )
        attended = totals['present'] + totals['late']
        totals['attended'] = attended
        totals['rate'] = round(attended / totals['total'] * 100, 1) if totals['total'] else None
        return totals


# ---------------------------------------------------------------------------
# Sessions and attendance
# ---------------------------------------------------------------------------
class ClassSession(models.Model):
    """
    A single occurrence of a class on a given date -- the thing a register is
    taken against.
    """

    dance_class = models.ForeignKey(
        DanceClass, on_delete=models.CASCADE, related_name='sessions',
    )
    date = models.DateField(db_index=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    studio = models.ForeignKey(
        Studio, null=True, blank=True, on_delete=models.SET_NULL, related_name='sessions',
    )
    teacher = models.ForeignKey(
        'accounts.StaffProfile', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='sessions_taught',
    )
    status = models.CharField(
        max_length=20, choices=SessionStatus.choices, default=SessionStatus.SCHEDULED,
    )
    topic = models.CharField(
        max_length=200, blank=True, help_text=_('What was covered, e.g. "Barre + petit allegro".'),
    )
    notes = models.TextField(blank=True)
    cancellation_reason = models.CharField(max_length=200, blank=True)

    register_taken = models.BooleanField(default=False)
    register_taken_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='registers_taken',
    )
    register_taken_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _('class session')
        ordering = ('-date', 'start_time')
        constraints = [
            models.UniqueConstraint(
                fields=('dance_class', 'date', 'start_time'), name='unique_session_slot',
            ),
        ]
        indexes = [models.Index(fields=('date', 'status'))]

    def __str__(self):
        return f'{self.dance_class.name} - {self.date:%d %b %Y}'

    def get_absolute_url(self):
        return reverse('academics:register', args=[self.pk])

    @property
    def is_past(self):
        return self.date < dt.date.today()

    @property
    def needs_register(self):
        return (
            self.status in {SessionStatus.SCHEDULED, SessionStatus.HELD}
            and not self.register_taken
            and self.date <= dt.date.today()
        )

    @property
    def expected_students(self):
        return Student.objects.filter(
            enrolments__dance_class=self.dance_class,
            enrolments__status__in=[EnrolmentStatus.ACTIVE, EnrolmentStatus.TRIAL],
        ).distinct()

    def attendance_counts(self):
        return self.attendances.aggregate(
            total=Count('id'),
            present=Count('id', filter=Q(status=AttendanceStatus.PRESENT)),
            late=Count('id', filter=Q(status=AttendanceStatus.LATE)),
            excused=Count('id', filter=Q(status=AttendanceStatus.EXCUSED)),
            absent=Count('id', filter=Q(status=AttendanceStatus.ABSENT)),
        )

    def mark_register_taken(self, by=None):
        self.register_taken = True
        self.register_taken_by = by
        self.register_taken_at = timezone.now()
        if self.status == SessionStatus.SCHEDULED and self.is_past:
            self.status = SessionStatus.HELD
        self.save(update_fields=[
            'register_taken', 'register_taken_by', 'register_taken_at', 'status',
        ])


class Attendance(models.Model):
    """One dancer's mark for one session."""

    session = models.ForeignKey(
        ClassSession, on_delete=models.CASCADE, related_name='attendances',
    )
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name='attendance_records',
    )
    status = models.CharField(
        max_length=20, choices=AttendanceStatus.choices,
        default=AttendanceStatus.PRESENT, db_index=True,
    )
    arrival_time = models.TimeField(null=True, blank=True)
    minutes_late = models.PositiveSmallIntegerField(null=True, blank=True)
    remarks = models.CharField(max_length=200, blank=True)

    marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='attendance_marked',
    )
    marked_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('attendance mark')
        verbose_name_plural = _('attendance marks')
        ordering = ('-session__date', 'student__first_name')
        constraints = [
            models.UniqueConstraint(
                fields=('session', 'student'), name='unique_attendance_per_session',
            ),
        ]
        indexes = [models.Index(fields=('student', 'status'))]

    def __str__(self):
        return f'{self.student.full_name} - {self.get_status_display()} ({self.session.date})'

    @property
    def attended(self):
        return self.status in ATTENDED_STATUSES


# ---------------------------------------------------------------------------
# Progress: the skill rubric
# ---------------------------------------------------------------------------
class SkillCategory(models.Model):
    """A grouping of skills, e.g. Technique, Musicality, Artistry, Discipline."""

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    description = models.TextField(blank=True)
    colour = models.CharField(max_length=7, default='#701344')
    icon = models.CharField(max_length=60, blank=True, default='fa-star')
    display_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = _('skill category')
        verbose_name_plural = _('skill categories')
        ordering = ('display_order', 'name')

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:120]
        super().save(*args, **kwargs)


class Skill(models.Model):
    """
    One assessable thing, e.g. "Turnout", "Port de bras", "Musical timing".

    Restrict a skill to particular programmes when it only makes sense there --
    pointe work has no place in a Kinder Ballet report.
    """

    category = models.ForeignKey(SkillCategory, on_delete=models.CASCADE, related_name='skills')
    name = models.CharField(max_length=140)
    description = models.TextField(
        blank=True, help_text=_('What a teacher should be looking for.'),
    )
    programs = models.ManyToManyField(
        Program, blank=True, related_name='skills',
        help_text=_('Leave empty to assess this skill in every programme.'),
    )
    max_score = models.PositiveSmallIntegerField(
        default=5, validators=[MinValueValidator(1), MaxValueValidator(10)],
    )
    display_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ('category__display_order', 'display_order', 'name')
        constraints = [
            models.UniqueConstraint(fields=('category', 'name'), name='unique_skill_per_category'),
        ]

    def __str__(self):
        return f'{self.category.name} / {self.name}'

    @classmethod
    def for_program(cls, program):
        """Skills that apply to *program* -- its own, plus the universal ones."""
        return (
            cls.objects.filter(is_active=True)
            .filter(Q(programs=program) | Q(programs__isnull=True))
            .select_related('category')
            .distinct()
        )


class AssessmentPeriod(models.Model):
    """A window in which teachers write progress reports, usually end of term."""

    term = models.ForeignKey(Term, on_delete=models.CASCADE, related_name='assessment_periods')
    name = models.CharField(max_length=100, help_text=_('e.g. "End of Term 1"'))
    opens_on = models.DateField()
    closes_on = models.DateField()
    publish_to_guardians = models.BooleanField(
        default=True, help_text=_('Allow guardians to read published reports from this period.'),
    )
    is_open = models.BooleanField(default=True)
    instructions = models.TextField(
        blank=True, help_text=_('Guidance shown to teachers while they write reports.'),
    )

    class Meta:
        verbose_name = _('assessment period')
        ordering = ('-opens_on',)
        constraints = [
            models.UniqueConstraint(fields=('term', 'name'), name='unique_period_per_term'),
        ]

    def __str__(self):
        return f'{self.name} - {self.term}'

    @property
    def is_accepting(self):
        return self.is_open and self.opens_on <= dt.date.today() <= self.closes_on

    @classmethod
    def current(cls):
        today = dt.date.today()
        return (
            cls.objects.filter(is_open=True, opens_on__lte=today, closes_on__gte=today).first()
            or cls.objects.filter(is_open=True).first()
        )


class ProgressReport(TimeStampedModel):
    """
    A dancer's assessment for one class in one period.

    The numeric side lives in :class:`SkillScore`; this model carries the
    narrative a guardian actually reads.
    """

    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name='progress_reports',
    )
    dance_class = models.ForeignKey(
        DanceClass, on_delete=models.CASCADE, related_name='progress_reports',
    )
    period = models.ForeignKey(
        AssessmentPeriod, on_delete=models.CASCADE, related_name='reports',
    )
    teacher = models.ForeignKey(
        'accounts.StaffProfile', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='reports_written',
    )

    status = models.CharField(
        max_length=20, choices=ReportStatus.choices, default=ReportStatus.DRAFT, db_index=True,
    )
    strengths = models.TextField(blank=True, help_text=_('What is going well.'))
    areas_to_develop = models.TextField(blank=True, help_text=_('What to work on next.'))
    teacher_comment = models.TextField(blank=True, help_text=_('Overall remarks to the guardian.'))
    recommendation = models.CharField(
        max_length=255, blank=True,
        help_text=_('e.g. "Ready to move up to Junior Ballet B next term."'),
    )
    conduct_comment = models.CharField(max_length=255, blank=True)

    attendance_rate = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True,
        help_text=_('Snapshot taken when the report is published.'),
    )

    submitted_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='reports_published',
    )
    guardian_viewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _('progress report')
        ordering = ('-period__opens_on', 'student__first_name')
        constraints = [
            models.UniqueConstraint(
                fields=('student', 'dance_class', 'period'), name='unique_report_per_period',
            ),
        ]

    def __str__(self):
        return f'{self.student.full_name} - {self.period.name}'

    def get_absolute_url(self):
        return reverse('academics:report_detail', args=[self.pk])

    @property
    def is_published(self):
        return self.status == ReportStatus.PUBLISHED

    @property
    def average_score(self):
        result = self.scores.aggregate(avg=Avg('score'))['avg']
        return round(result, 2) if result is not None else None

    @property
    def average_percent(self):
        """Average expressed against each skill's own maximum."""
        rows = list(self.scores.select_related('skill').all())
        if not rows:
            return None
        total = sum(row.score / row.skill.max_score for row in rows if row.skill.max_score)
        return round(total / len(rows) * 100, 1)

    def category_averages(self):
        """``[{'category': ..., 'average': 4.2, 'percent': 84.0}, ...]`` for the radar chart."""
        rows = (
            self.scores.select_related('skill__category')
            .values('skill__category__name', 'skill__category__colour')
            .annotate(average=Avg('score'), max_avg=Avg('skill__max_score'))
            .order_by('skill__category__display_order')
        )
        return [
            {
                'category': row['skill__category__name'],
                'colour': row['skill__category__colour'],
                'average': round(row['average'], 2),
                'percent': round(row['average'] / row['max_avg'] * 100, 1)
                if row['max_avg'] else None,
            }
            for row in rows
        ]

    def submit(self, by=None):
        self.status = ReportStatus.SUBMITTED
        self.submitted_at = timezone.now()
        self.save(update_fields=['status', 'submitted_at', 'updated_at'])

    def publish(self, by=None):
        summary = Enrolment(
            student=self.student, dance_class=self.dance_class,
        ).attendance_summary()
        self.attendance_rate = summary['rate']
        self.status = ReportStatus.PUBLISHED
        self.published_at = timezone.now()
        self.published_by = by
        self.save(update_fields=[
            'status', 'published_at', 'published_by', 'attendance_rate', 'updated_at',
        ])


class SkillScore(models.Model):
    """One skill's mark inside a progress report."""

    report = models.ForeignKey(ProgressReport, on_delete=models.CASCADE, related_name='scores')
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE, related_name='scores')
    score = models.PositiveSmallIntegerField(validators=[MinValueValidator(0)])
    comment = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = _('skill score')
        ordering = ('skill__category__display_order', 'skill__display_order')
        constraints = [
            models.UniqueConstraint(fields=('report', 'skill'), name='unique_score_per_report'),
        ]

    def __str__(self):
        return f'{self.skill.name}: {self.score}/{self.skill.max_score}'

    def clean(self):
        if self.skill_id and self.score > self.skill.max_score:
            raise ValidationError({
                'score': _('Score cannot exceed %(max)s for this skill.')
                % {'max': self.skill.max_score},
            })

    @property
    def percent(self):
        if not self.skill.max_score:
            return 0
        return round(self.score / self.skill.max_score * 100)

    @property
    def descriptor(self):
        pct = self.percent
        if pct >= 90:
            return 'Outstanding'
        if pct >= 75:
            return 'Strong'
        if pct >= 60:
            return 'Developing well'
        if pct >= 40:
            return 'Emerging'
        return 'Needs focus'


class StudentNote(TimeStampedModel):
    """
    A dated observation about a dancer, outside the formal report cycle --
    an injury, a breakthrough, a conversation with a parent.
    """

    class Kind(models.TextChoices):
        OBSERVATION = 'observation', _('Observation')
        ACHIEVEMENT = 'achievement', _('Achievement')
        CONCERN = 'concern', _('Concern')
        INJURY = 'injury', _('Injury / health')
        BEHAVIOUR = 'behaviour', _('Behaviour')
        PARENT_CONTACT = 'parent_contact', _('Parent contact')

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='notes_log')
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='student_notes',
    )
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.OBSERVATION)
    title = models.CharField(max_length=160)
    body = models.TextField()
    date = models.DateField(default=dt.date.today)
    visible_to_guardian = models.BooleanField(
        default=False, help_text=_('Show this note to the dancer’s guardians.'),
    )

    class Meta:
        verbose_name = _('student note')
        ordering = ('-date', '-created_at')

    def __str__(self):
        return f'{self.student.full_name}: {self.title}'


# ---------------------------------------------------------------------------
# Public enrolment enquiries
# ---------------------------------------------------------------------------
class EnrolmentApplication(TimeStampedModel):
    """
    Submitted from the public site. An administrator reviews it and, on
    acceptance, converts it into a real Student + guardian record.
    """

    # Dancer
    student_first_name = models.CharField(max_length=80)
    student_last_name = models.CharField(max_length=80)
    student_date_of_birth = models.DateField()
    student_gender = models.CharField(max_length=1, blank=True)
    previous_experience = models.TextField(blank=True)

    # Guardian
    guardian_name = models.CharField(max_length=140)
    guardian_email = models.EmailField()
    guardian_phone = models.CharField(max_length=40)
    guardian_relationship = models.CharField(max_length=40, blank=True)
    home_address = models.CharField(max_length=255, blank=True)

    # Interest
    program = models.ForeignKey(
        Program, null=True, blank=True, on_delete=models.SET_NULL, related_name='applications',
    )
    preferred_days = models.CharField(max_length=160, blank=True)
    message = models.TextField(blank=True)
    how_heard_about_us = models.CharField(max_length=150, blank=True)

    # Handling
    status = models.CharField(
        max_length=20, choices=ApplicationStatus.choices,
        default=ApplicationStatus.NEW, db_index=True,
    )
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='applications_handled',
    )
    staff_notes = models.TextField(blank=True)
    created_student = models.ForeignKey(
        Student, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='source_application',
    )

    class Meta:
        verbose_name = _('enrolment application')
        ordering = ('-created_at',)

    def __str__(self):
        return f'{self.student_first_name} {self.student_last_name} - {self.get_status_display()}'

    @property
    def student_full_name(self):
        return f'{self.student_first_name} {self.student_last_name}'

    @property
    def student_age(self):
        today = dt.date.today()
        born = self.student_date_of_birth
        return today.year - born.year - ((today.month, today.day) < (born.month, born.day))
