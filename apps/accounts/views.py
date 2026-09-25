"""Authentication, profiles, people management and the dashboard router."""

from __future__ import annotations

import datetime as dt

from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView, PasswordChangeView
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.academics import services as academics
from apps.academics.models import (
    AssessmentPeriod,
    ClassSession,
    DanceClass,
    Enrolment,
    EnrolmentStatus,
    ProgressReport,
    ReportStatus,
    SessionStatus,
    Term,
)
from apps.events.models import Event
from apps.finance import services as finance
from apps.finance.models import Invoice, OPEN_INVOICE_STATUSES, Payment
from apps.website.models import Announcement

from .forms import (
    GuardianProfileForm,
    GuardianSignupForm,
    ProfileForm,
    StaffProfileForm,
    StaffSignupForm,
    StudentSignupForm,
    StudioLoginForm,
    UserSearchForm,
    UserVerificationForm,
)
from .models import (
    ApprovalStatus,
    AuditLog,
    GuardianProfile,
    Notification,
    NotificationLevel,
    Role,
    STAFF_ROLES,
    StaffProfile,
    Student,
    User,
)
from .permissions import management_required, staff_required, verified_required


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
class StudioLoginView(LoginView):
    template_name = 'accounts/login.html'
    authentication_form = StudioLoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        if not form.cleaned_data.get('remember_me'):
            self.request.session.set_expiry(0)
        user = self.request.user
        user.last_seen = timezone.now()
        user.save(update_fields=['last_seen'])
        AuditLog.record(user, AuditLog.Action.LOGIN, 'signed in', request=self.request)
        return response

    def get_success_url(self):
        if not self.request.user.is_verified and not self.request.user.is_superuser:
            return reverse('accounts:pending')
        return super().get_success_url()


class StudioLogoutView(LogoutView):
    next_page = reverse_lazy('website:home')


def signup_choice(request):
    """Pick which kind of account to open."""
    if request.user.is_authenticated:
        return redirect('dashboard:home')
    return render(request, 'accounts/signup_choice.html')


def _do_signup(request, form_class, template, heading, blurb):
    if request.user.is_authenticated:
        return redirect('dashboard:home')

    form = form_class(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        AuditLog.record(None, AuditLog.Action.CREATE, f'{user.email} signed up', obj=user,
                        request=request)

        # Tell the administrators someone is waiting.
        Notification.send(
            User.objects.filter(role__in=[Role.ADMIN, Role.DIRECTOR],
                                approval_status=ApprovalStatus.APPROVED),
            title='New account awaiting verification',
            message=f'{user.display_name} registered as {user.get_role_display()}.',
            level=NotificationLevel.WARNING,
            url=reverse('dashboard:verification_queue'),
            icon='fa-user-check',
        )

        auth_login(request, user, backend='apps.accounts.backends.EmailOrUsernameBackend')
        messages.success(
            request,
            'Welcome to Ballet Dance Studio UG. Your account is with our team for verification.',
        )
        return redirect('accounts:pending')

    return render(request, template, {
        'form': form, 'heading': heading, 'blurb': blurb,
    })


def signup_guardian(request):
    return _do_signup(
        request, GuardianSignupForm, 'accounts/signup.html',
        'Parent & guardian account',
        'Follow your dancer’s attendance, progress reports and fees in one place.',
    )


def signup_student(request):
    return _do_signup(
        request, StudentSignupForm, 'accounts/signup.html',
        'Student account',
        'See your timetable, your attendance and your progress reports.',
    )


def signup_staff(request):
    return _do_signup(
        request, StaffSignupForm, 'accounts/signup.html',
        'Staff account',
        'For teachers, administrators and the creative directors of the studio.',
    )


@login_required
def pending(request):
    """Holding page for accounts that have not been verified yet."""
    if request.user.is_verified or request.user.is_superuser:
        return redirect('dashboard:home')
    return render(request, 'accounts/pending.html', {
        'status': request.user.approval_status,
    })


class StudioPasswordChangeView(PasswordChangeView):
    template_name = 'accounts/password_change.html'
    success_url = reverse_lazy('accounts:profile')

    def form_valid(self, form):
        messages.success(self.request, 'Your password has been updated.')
        self.request.user.must_change_password = False
        self.request.user.save(update_fields=['must_change_password'])
        return super().form_valid(form)


# ---------------------------------------------------------------------------
# Dashboard router
# ---------------------------------------------------------------------------
@login_required
def dashboard(request):
    """Send each role to the dashboard built for it."""
    user = request.user
    if not user.is_verified and not user.is_superuser:
        return redirect('accounts:pending')
    if user.is_management:
        return admin_dashboard(request)
    if user.is_teacher:
        return teacher_dashboard(request)
    if user.is_guardian:
        return guardian_dashboard(request)
    return student_dashboard(request)


@verified_required
def admin_dashboard(request):
    """The director / administrator view: the whole studio at a glance."""
    today = dt.date.today()
    month_start, month_end = finance.period_bounds('month')
    summary = finance.financial_summary(month_start, month_end)
    term = Term.current()

    active_students = Student.objects.active().count()
    new_this_month = Student.objects.filter(
        enrolment_date__gte=month_start, enrolment_date__lte=month_end,
    ).count()

    context = {
        'page_title': 'Studio overview',
        'summary': summary,
        'series': finance.income_expense_series(month_start, month_end),
        'expense_breakdown': finance.expense_breakdown(month_start, month_end)[:6],
        'expense_chart': finance.chart_rows(
            finance.expense_breakdown(month_start, month_end)[:6]),
        'payment_methods': finance.payment_method_breakdown(month_start, month_end),
        'method_chart': finance.chart_rows(
            finance.payment_method_breakdown(month_start, month_end)),
        'term': term,

        'active_students': active_students,
        'new_students_this_month': new_this_month,
        'staff_count': User.objects.filter(
            role__in=STAFF_ROLES, approval_status=ApprovalStatus.APPROVED,
        ).count(),
        'guardian_count': GuardianProfile.objects.count(),
        'class_count': DanceClass.objects.active().filter(term=term).count() if term else 0,

        'pending_users': User.objects.pending_verification()
                             .order_by('-created_at')[:6],
        'pending_count': User.objects.pending_verification().count(),

        'recent_payments': Payment.objects.confirmed()
                               .select_related('student', 'invoice', 'received_by')[:8],
        'outstanding_invoices': finance.outstanding_invoices(limit=8),
        'ageing': finance.ageing_analysis(),

        'registers_due': academics.sessions_needing_registers()[:8],
        'registers_due_count': academics.sessions_needing_registers().count(),
        'attendance_concerns': academics.students_of_concern()[:6],
        'attendance_by_class': academics.attendance_by_class(
            start=today - dt.timedelta(days=60),
        )[:6],

        'upcoming_events': Event.objects.upcoming().select_related('category')[:5],
        'announcements': Announcement.live_for(request.user)[:4],
        'today_sessions': ClassSession.objects.filter(date=today)
                              .select_related('dance_class', 'studio', 'teacher__user')
                              .order_by('start_time'),
    }
    return render(request, 'dashboard/admin.html', context)


@verified_required
def teacher_dashboard(request):
    """What a teacher needs: my classes, my registers, my reports."""
    user = request.user
    today = dt.date.today()
    monday = today - dt.timedelta(days=today.weekday())
    term = Term.current()

    my_classes = (
        DanceClass.objects.active()
        .taught_by(user)
        .select_related('program', 'term', 'studio')
        .prefetch_related('teachers__user')
    )
    if term:
        my_classes = my_classes.filter(term=term)

    period = AssessmentPeriod.current()
    reports_due = 0
    if period:
        expected = Enrolment.objects.filter(
            dance_class__in=my_classes, status=EnrolmentStatus.ACTIVE,
        ).count()
        written = ProgressReport.objects.filter(
            dance_class__in=my_classes, period=period,
        ).exclude(status=ReportStatus.DRAFT).count()
        reports_due = max(0, expected - written)

    my_students = Student.objects.for_teacher(user)

    context = {
        'page_title': 'My teaching',
        'my_classes': my_classes,
        'student_count': my_students.count(),
        'week': academics.timetable_for_week(monday, teacher=user),
        'week_start': monday,
        'today_sessions': ClassSession.objects.filter(
            date=today, dance_class__in=my_classes,
        ).select_related('dance_class', 'studio').order_by('start_time'),
        'registers_due': academics.sessions_needing_registers(user)[:10],
        'registers_due_count': academics.sessions_needing_registers(user).count(),
        'assessment_period': period,
        'reports_due': reports_due,
        'attendance_concerns': [
            row for row in academics.students_of_concern()
            if my_students.filter(pk=row['student'].pk).exists()
        ][:5],
        'upcoming_events': Event.objects.upcoming().visible_to(user)[:4],
        'announcements': Announcement.live_for(user)[:4],
    }
    return render(request, 'dashboard/teacher.html', context)


@verified_required
def guardian_dashboard(request):
    """A parent's view of their own children."""
    user = request.user
    guardian = getattr(user, 'guardian_profile', None)
    children = guardian.students.prefetch_related(
        'enrolments__dance_class__program',
    ) if guardian else Student.objects.none()

    rows = []
    for child in children:
        stats = academics.attendance_stats(child.attendance_records.all())
        rows.append({
            'student': child,
            'attendance': stats,
            'latest_report': academics.latest_report_for(child),
            'classes': [e.dance_class for e in child.enrolments.filter(
                status=EnrolmentStatus.ACTIVE,
            )],
            'next_session': ClassSession.objects.filter(
                dance_class__enrolments__student=child,
                dance_class__enrolments__status=EnrolmentStatus.ACTIVE,
                date__gte=dt.date.today(),
                status=SessionStatus.SCHEDULED,
            ).order_by('date', 'start_time').first(),
        })

    statement = finance.guardian_statement(guardian) if guardian else None

    context = {
        'page_title': 'My family',
        'guardian': guardian,
        'children': rows,
        'statement': statement,
        'open_invoices': (
            Invoice.objects.for_guardian(guardian)
            .filter(status__in=OPEN_INVOICE_STATUSES)
            .select_related('student')[:5]
            if guardian else []
        ),
        'upcoming_events': Event.objects.upcoming().visible_to(user)[:5],
        'announcements': Announcement.live_for(user)[:5],
    }
    return render(request, 'dashboard/guardian.html', context)


@verified_required
def student_dashboard(request):
    """A dancer's own view."""
    user = request.user
    student = getattr(user, 'student_profile', None)
    today = dt.date.today()
    monday = today - dt.timedelta(days=today.weekday())

    context = {
        'page_title': 'My dancing',
        'student': student,
        'announcements': Announcement.live_for(user)[:5],
        'upcoming_events': Event.objects.upcoming().visible_to(user)[:5],
    }

    if student:
        enrolments = student.enrolments.filter(
            status=EnrolmentStatus.ACTIVE,
        ).select_related('dance_class__program', 'dance_class__term')
        classes = [e.dance_class for e in enrolments]
        context.update({
            'enrolments': enrolments,
            'attendance': academics.attendance_stats(student.attendance_records.all()),
            'attendance_trend': academics.student_attendance_trend(student),
            'progress': academics.student_progress_trend(student),
            'latest_report': academics.latest_report_for(student),
            'week': academics.timetable_for_week(monday, dance_classes=classes),
            'week_start': monday,
            'recital_roles': student.recital_roles.select_related(
                'performance__recital',
            )[:5],
        })
    return render(request, 'dashboard/student.html', context)


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------
@verified_required
def profile(request):
    user = request.user
    return render(request, 'accounts/profile.html', {
        'page_title': 'My profile',
        'staff_profile': getattr(user, 'staff_profile', None),
        'guardian_profile': getattr(user, 'guardian_profile', None),
        'student_profile': getattr(user, 'student_profile', None),
    })


@verified_required
def profile_edit(request):
    user = request.user
    form = ProfileForm(request.POST or None, request.FILES or None, instance=user)

    extra_form = None
    if user.is_studio_staff and hasattr(user, 'staff_profile'):
        extra_form = StaffProfileForm(request.POST or None, instance=user.staff_profile)
    elif user.is_guardian and hasattr(user, 'guardian_profile'):
        extra_form = GuardianProfileForm(request.POST or None, instance=user.guardian_profile)

    if request.method == 'POST':
        forms_ok = form.is_valid() and (extra_form is None or extra_form.is_valid())
        if forms_ok:
            form.save()
            if extra_form is not None:
                extra_form.save()
            messages.success(request, 'Your profile has been updated.')
            return redirect('accounts:profile')

    return render(request, 'accounts/profile_edit.html', {
        'page_title': 'Edit profile', 'form': form, 'extra_form': extra_form,
    })


# ---------------------------------------------------------------------------
# People management (administrators)
# ---------------------------------------------------------------------------
@management_required
def user_list(request):
    form = UserSearchForm(request.GET or None)
    qs = User.objects.all().select_related('staff_profile', 'guardian_profile')

    if form.is_valid():
        query = form.cleaned_data.get('q')
        if query:
            qs = qs.filter(
                Q(first_name__icontains=query) | Q(last_name__icontains=query)
                | Q(email__icontains=query) | Q(username__icontains=query)
            )
        if form.cleaned_data.get('role'):
            qs = qs.filter(role=form.cleaned_data['role'])
        if form.cleaned_data.get('status'):
            qs = qs.filter(approval_status=form.cleaned_data['status'])

    page = Paginator(qs.order_by('-created_at'), 25).get_page(request.GET.get('page'))
    context = {
        'page_title': 'People',
        'form': form,
        'page_obj': page,
        'counts': User.objects.values('role').annotate(n=Count('id')),
        'pending_count': User.objects.pending_verification().count(),
    }
    if request.headers.get('HX-Request'):
        return render(request, 'accounts/partials/user_rows.html', context)
    return render(request, 'accounts/user_list.html', context)


@management_required
def verification_queue(request):
    pending_users = (
        User.objects.pending_verification()
        .select_related('staff_profile', 'guardian_profile')
        .order_by('created_at')
    )
    return render(request, 'accounts/verification_queue.html', {
        'page_title': 'Awaiting verification',
        'pending_users': pending_users,
    })


@management_required
def user_detail(request, pk):
    person = get_object_or_404(
        User.objects.select_related('staff_profile', 'guardian_profile'), pk=pk,
    )
    form = UserVerificationForm(request.POST or None, initial={'role': person.role})

    if request.method == 'POST' and form.is_valid():
        decision = form.cleaned_data['decision']
        note = form.cleaned_data.get('note', '')
        new_role = form.cleaned_data.get('role')

        if new_role and new_role != person.role:
            person.role = new_role
            person.save(update_fields=['role'])

        if decision == ApprovalStatus.APPROVED:
            person.approve(by=request.user, note=note)
            _ensure_profile_for(person)
            Notification.send(
                person, 'Your account has been verified',
                'You now have full access to your Ballet Dance Studio UG dashboard.',
                level=NotificationLevel.SUCCESS, url=reverse('dashboard:home'),
                icon='fa-circle-check',
            )
            messages.success(request, f'{person.display_name} has been verified.')
        elif decision == ApprovalStatus.REJECTED:
            person.reject(by=request.user, note=note)
            messages.warning(request, f'{person.display_name} was rejected.')
        else:
            person.suspend(by=request.user, note=note)
            messages.warning(request, f'{person.display_name} was suspended.')

        AuditLog.record(
            request.user, AuditLog.Action.APPROVE,
            f'set {person.email} to {person.get_approval_status_display()}',
            obj=person, request=request,
        )
        return redirect('dashboard:verification_queue')

    return render(request, 'accounts/user_detail.html', {
        'page_title': person.display_name,
        'person': person,
        'form': form,
        'audit': AuditLog.objects.filter(target_id=str(person.pk))[:10],
    })


def _ensure_profile_for(person):
    """Give a newly approved account the profile row its role needs."""
    if person.role in STAFF_ROLES and not hasattr(person, 'staff_profile'):
        StaffProfile.objects.create(user=person)
    elif person.role == Role.PARENT and not hasattr(person, 'guardian_profile'):
        GuardianProfile.objects.create(user=person)


@management_required
@require_POST
def quick_verify(request, pk):
    """One-click approve from the queue, for HTMX."""
    person = get_object_or_404(User, pk=pk)
    person.approve(by=request.user)
    _ensure_profile_for(person)
    Notification.send(
        person, 'Your account has been verified',
        'You now have full access to your dashboard.',
        level=NotificationLevel.SUCCESS, url=reverse('dashboard:home'),
    )
    AuditLog.record(request.user, AuditLog.Action.APPROVE,
                    f'verified {person.email}', obj=person, request=request)

    if request.headers.get('HX-Request'):
        return HttpResponse(
            f'<div class="verified-flash">✓ {person.display_name} verified</div>'
        )
    messages.success(request, f'{person.display_name} has been verified.')
    return redirect('dashboard:verification_queue')


@staff_required
def staff_list(request):
    return render(request, 'accounts/staff_list.html', {
        'page_title': 'Faculty & team',
        'staff': StaffProfile.objects.select_related('user')
                     .filter(is_active_staff=True)
                     .prefetch_related('classes_taught'),
    })


@management_required
def guardian_list(request):
    query = request.GET.get('q', '').strip()
    qs = GuardianProfile.objects.select_related('user').prefetch_related('wards')
    if query:
        qs = qs.filter(
            Q(user__first_name__icontains=query) | Q(user__last_name__icontains=query)
            | Q(user__email__icontains=query) | Q(guardian_id__icontains=query)
        )
    page = Paginator(qs.order_by('user__first_name'), 25).get_page(request.GET.get('page'))
    return render(request, 'accounts/guardian_list.html', {
        'page_title': 'Parents & guardians', 'page_obj': page, 'q': query,
    })


@management_required
def guardian_detail(request, pk):
    guardian = get_object_or_404(
        GuardianProfile.objects.select_related('user'), pk=pk,
    )
    return render(request, 'accounts/guardian_detail.html', {
        'page_title': guardian.user.display_name,
        'guardian': guardian,
        'children': guardian.students.prefetch_related('enrolments__dance_class'),
        'statement': finance.guardian_statement(guardian),
    })


@staff_required
def staff_detail(request, pk):
    member = get_object_or_404(StaffProfile.objects.select_related('user'), pk=pk)
    return render(request, 'accounts/staff_detail.html', {
        'page_title': member.user.display_name,
        'member': member,
        'classes': member.classes_taught.select_related('program', 'term'),
        'can_see_pay': request.user.is_management,
    })


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
@login_required
def notification_list(request):
    page = Paginator(
        request.user.notifications.all(), 30,
    ).get_page(request.GET.get('page'))
    return render(request, 'accounts/notifications.html', {
        'page_title': 'Notifications', 'page_obj': page,
    })


@login_required
def notification_dropdown(request):
    """HTMX partial for the bell menu."""
    return render(request, 'accounts/partials/notification_dropdown.html', {
        'items': request.user.notifications.all()[:8],
    })


@login_required
@require_POST
def notification_read(request, pk):
    note = get_object_or_404(Notification, pk=pk, recipient=request.user)
    note.mark_read()
    if request.headers.get('HX-Request'):
        return HttpResponse(status=204)
    return redirect(note.url or 'accounts:notification_list')


@login_required
@require_POST
def notifications_read_all(request):
    request.user.notifications.filter(is_read=False).update(
        is_read=True, read_at=timezone.now(),
    )
    if request.headers.get('HX-Request'):
        return notification_dropdown(request)
    messages.success(request, 'All notifications marked as read.')
    return redirect('accounts:notification_list')
