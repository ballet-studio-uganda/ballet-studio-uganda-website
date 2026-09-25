"""Classes, registers, dancer records and progress reports."""

from __future__ import annotations

import datetime as dt

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.forms import StudentForm, StudentGuardianForm
from apps.accounts.models import (
    AuditLog,
    GuardianProfile,
    Notification,
    NotificationLevel,
    StaffProfile,
    Student,
    StudentStatus,
)
from apps.accounts.permissions import (
    can_mark_register,
    can_view_student,
    management_required,
    require_student_access,
    staff_required,
    verified_required,
)

from . import services
from .forms import (
    ClassScheduleFormSet,
    DanceClassForm,
    EnrolmentForm,
    GenerateSessionsForm,
    ProgressReportForm,
    SessionForm,
    SkillScoreFormSet,
    StudentNoteForm,
)
from .models import (
    AssessmentPeriod,
    Attendance,
    AttendanceStatus,
    ClassSession,
    DanceClass,
    Enrolment,
    EnrolmentStatus,
    Program,
    ProgressReport,
    ReportStatus,
    SessionStatus,
    Skill,
    SkillCategory,
    Studio,
    StudentNote,
    Term,
)


# ---------------------------------------------------------------------------
# Classes
# ---------------------------------------------------------------------------
@staff_required
def class_list(request):
    term_id = request.GET.get('term')
    term = (
        get_object_or_404(Term, pk=term_id) if term_id else Term.current()
    )

    classes = (
        DanceClass.objects.select_related('program', 'term', 'studio')
        .prefetch_related('teachers__user', 'schedules')
        .annotate(n_enrolled=Count(
            'enrolments', filter=Q(enrolments__status=EnrolmentStatus.ACTIVE),
        ))
    )
    if term:
        classes = classes.filter(term=term)
    if request.user.is_teacher and not request.user.is_management:
        classes = classes.taught_by(request.user)

    programme = request.GET.get('programme')
    if programme:
        classes = classes.filter(program__slug=programme)

    return render(request, 'academics/class_list.html', {
        'page_title': 'Classes',
        'classes': classes,
        'terms': Term.objects.select_related('academic_year')[:12],
        'term': term,
        'programmes': Program.objects.filter(is_active=True),
        'active_programme': programme,
    })


@staff_required
def class_detail(request, pk):
    dance_class = get_object_or_404(
        DanceClass.objects.select_related('program', 'term', 'studio')
        .prefetch_related('teachers__user', 'schedules__studio'),
        pk=pk,
    )
    enrolments = (
        dance_class.enrolments.filter(status=EnrolmentStatus.ACTIVE)
        .select_related('student')
        .order_by('student__first_name')
    )
    return render(request, 'academics/class_detail.html', {
        'page_title': dance_class.name,
        'dance_class': dance_class,
        'enrolments': enrolments,
        'sessions': dance_class.sessions.order_by('-date')[:20],
        'upcoming': dance_class.sessions.filter(
            date__gte=dt.date.today(), status=SessionStatus.SCHEDULED,
        ).order_by('date')[:5],
        'attendance_rate': dance_class.attendance_rate(),
        'waitlist': dance_class.enrolments.filter(status=EnrolmentStatus.WAITLIST),
        'can_manage': request.user.is_management,
    })


@management_required
def class_create(request):
    form = DanceClassForm(request.POST or None)
    formset = ClassScheduleFormSet(request.POST or None)

    if request.method == 'POST' and form.is_valid() and formset.is_valid():
        dance_class = form.save()
        formset.instance = dance_class
        formset.save()
        AuditLog.record(request.user, AuditLog.Action.CREATE,
                        f'created class {dance_class.name}', obj=dance_class, request=request)
        messages.success(request, f'{dance_class.name} created. Now generate its sessions.')
        return redirect('academics:class_detail', pk=dance_class.pk)

    return render(request, 'academics/class_form.html', {
        'page_title': 'New class', 'form': form, 'formset': formset,
    })


@management_required
def class_edit(request, pk):
    dance_class = get_object_or_404(DanceClass, pk=pk)
    form = DanceClassForm(request.POST or None, instance=dance_class)
    formset = ClassScheduleFormSet(request.POST or None, instance=dance_class)

    if request.method == 'POST' and form.is_valid() and formset.is_valid():
        form.save()
        formset.save()
        messages.success(request, 'Class updated.')
        return redirect('academics:class_detail', pk=dance_class.pk)

    return render(request, 'academics/class_form.html', {
        'page_title': f'Edit {dance_class.name}',
        'form': form, 'formset': formset, 'dance_class': dance_class,
    })


@management_required
def generate_sessions(request, pk):
    """Build the term's sessions from the class timetable."""
    dance_class = get_object_or_404(DanceClass, pk=pk)
    form = GenerateSessionsForm(request.POST or None, dance_class=dance_class)

    if request.method == 'POST' and form.is_valid():
        created = services.generate_sessions(
            dance_class,
            start=form.cleaned_data['start_date'],
            end=form.cleaned_data['end_date'],
            skip_dates=form.skip_dates(),
        )
        messages.success(
            request,
            f'{len(created)} session(s) added to the timetable.' if created
            else 'No new sessions to add — the timetable is already complete.',
        )
        return redirect('academics:class_detail', pk=dance_class.pk)

    return render(request, 'academics/generate_sessions.html', {
        'page_title': f'Generate sessions — {dance_class.name}',
        'dance_class': dance_class, 'form': form,
    })


# ---------------------------------------------------------------------------
# Timetable
# ---------------------------------------------------------------------------
@staff_required
def timetable(request):
    today = dt.date.today()
    offset = int(request.GET.get('week', 0))
    monday = today - dt.timedelta(days=today.weekday()) + dt.timedelta(weeks=offset)

    teacher = request.user if (request.user.is_teacher and not request.user.is_management) else None
    week = services.timetable_for_week(monday, teacher=teacher)

    return render(request, 'academics/timetable.html', {
        'page_title': 'Timetable',
        'week': week,
        'week_start': monday,
        'week_end': monday + dt.timedelta(days=6),
        'offset': offset,
        'today': today,
    })


# ---------------------------------------------------------------------------
# Registers and attendance
# ---------------------------------------------------------------------------
@staff_required
def register_list(request):
    """Sessions still waiting for a register."""
    user = None if request.user.is_management else request.user
    return render(request, 'academics/register_list.html', {
        'page_title': 'Registers',
        'outstanding': services.sessions_needing_registers(user, days_back=30),
        'recent': ClassSession.objects.filter(register_taken=True)
                      .select_related('dance_class', 'register_taken_by')
                      .order_by('-register_taken_at')[:15],
    })


@staff_required
def register(request, pk):
    """Mark the register for one session."""
    session = get_object_or_404(
        ClassSession.objects.select_related('dance_class__program', 'studio'), pk=pk,
    )
    if not can_mark_register(request.user, session):
        messages.error(request, 'You do not teach this class.')
        return redirect('academics:register_list')

    students = list(session.expected_students.order_by('first_name'))
    existing = {a.student_id: a for a in session.attendances.all()}

    if request.method == 'POST':
        marks = {}
        for student in students:
            status = request.POST.get(f'status_{student.pk}')
            if not status:
                continue
            minutes = request.POST.get(f'late_{student.pk}') or None
            marks[student.pk] = {
                'status': status,
                'remarks': request.POST.get(f'remarks_{student.pk}', ''),
                'minutes_late': int(minutes) if minutes and minutes.isdigit() else None,
            }

        session.topic = request.POST.get('topic', session.topic)
        session.notes = request.POST.get('notes', session.notes)
        session.save(update_fields=['topic', 'notes'])

        created, updated = services.bulk_mark_register(session, marks, user=request.user)
        AuditLog.record(
            request.user, AuditLog.Action.UPDATE,
            f'took the register for {session}', obj=session, request=request,
        )
        messages.success(
            request, f'Register saved — {created + updated} dancer(s) marked.',
        )
        return redirect('academics:register_list')

    rows = [
        {'student': s, 'mark': existing.get(s.pk)} for s in students
    ]
    return render(request, 'academics/register.html', {
        'page_title': f'Register — {session.dance_class.name}',
        'session': session,
        'rows': rows,
        'statuses': AttendanceStatus.choices,
        'counts': session.attendance_counts(),
    })


@staff_required
def attendance_overview(request):
    days = int(request.GET.get('days', 60))
    since = dt.date.today() - dt.timedelta(days=days)
    return render(request, 'academics/attendance_overview.html', {
        'page_title': 'Attendance',
        'by_class': services.attendance_by_class(start=since),
        'concerns': services.students_of_concern(),
        'overall': services.attendance_stats(
            Attendance.objects.filter(session__date__gte=since),
        ),
        'days': days,
        'since': since,
    })


# ---------------------------------------------------------------------------
# Students
# ---------------------------------------------------------------------------
@staff_required
def student_list(request):
    query = request.GET.get('q', '').strip()
    status = request.GET.get('status', StudentStatus.ACTIVE)

    students = Student.objects.select_related('user').prefetch_related(
        Prefetch(
            'enrolments',
            queryset=Enrolment.objects.filter(status=EnrolmentStatus.ACTIVE)
            .select_related('dance_class__program'),
        ),
        'guardian_links__guardian__user',
    )
    if request.user.is_teacher and not request.user.is_management:
        students = students.for_teacher(request.user)
    if status:
        students = students.filter(status=status)
    if query:
        students = students.filter(
            Q(first_name__icontains=query) | Q(last_name__icontains=query)
            | Q(student_id__icontains=query) | Q(preferred_name__icontains=query)
        )

    programme = request.GET.get('programme')
    if programme:
        students = students.filter(
            enrolments__dance_class__program__slug=programme,
            enrolments__status=EnrolmentStatus.ACTIVE,
        ).distinct()

    page = Paginator(students.order_by('first_name'), 30).get_page(request.GET.get('page'))
    context = {
        'page_title': 'Dancers',
        'page_obj': page,
        'q': query,
        'status': status,
        'statuses': StudentStatus.choices,
        'programmes': Program.objects.filter(is_active=True),
        'active_programme': programme,
        'total': Student.objects.active().count(),
    }
    if request.headers.get('HX-Request'):
        return render(request, 'academics/partials/student_rows.html', context)
    return render(request, 'academics/student_list.html', context)


@verified_required
def student_detail(request, pk):
    student = get_object_or_404(
        Student.objects.select_related('user')
        .prefetch_related('guardian_links__guardian__user'),
        pk=pk,
    )
    require_student_access(request.user, student)

    is_staff_view = request.user.is_studio_staff or request.user.is_superuser
    attendance = services.attendance_stats(student.attendance_records.all())

    return render(request, 'academics/student_detail.html', {
        'page_title': student.full_name,
        'student': student,
        'enrolments': student.enrolments.select_related(
            'dance_class__program', 'dance_class__term',
        ).order_by('-date_enrolled'),
        'attendance': attendance,
        'attendance_trend': services.student_attendance_trend(student),
        'recent_marks': student.attendance_records.select_related(
            'session__dance_class',
        ).order_by('-session__date')[:15],
        'progress': services.student_progress_trend(student),
        'reports': student.progress_reports.filter(
            **({} if is_staff_view else {'status': ReportStatus.PUBLISHED})
        ).select_related('period', 'dance_class', 'teacher__user'),
        'notes': student.notes_log.select_related('author').filter(
            **({} if is_staff_view else {'visible_to_guardian': True})
        )[:10],
        'invoices': student.invoices.order_by('-issue_date')[:6] if is_staff_view
                    or request.user.is_guardian else [],
        'recital_roles': student.recital_roles.select_related(
            'performance__recital',
        ),
        'is_staff_view': is_staff_view,
        'note_form': StudentNoteForm() if is_staff_view else None,
    })


@management_required
def student_create(request):
    form = StudentForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        student = form.save()
        AuditLog.record(request.user, AuditLog.Action.CREATE,
                        f'added dancer {student.full_name}', obj=student, request=request)
        messages.success(
            request, f'{student.full_name} added — student ID {student.student_id}.',
        )
        return redirect('academics:student_detail', pk=student.pk)
    return render(request, 'academics/student_form.html', {
        'page_title': 'Add a dancer', 'form': form,
    })


@management_required
def student_edit(request, pk):
    student = get_object_or_404(Student, pk=pk)
    form = StudentForm(request.POST or None, request.FILES or None, instance=student)
    if request.method == 'POST' and form.is_valid():
        form.save()
        AuditLog.record(request.user, AuditLog.Action.UPDATE,
                        f'updated dancer {student.full_name}', obj=student, request=request)
        messages.success(request, 'Dancer record updated.')
        return redirect('academics:student_detail', pk=student.pk)
    return render(request, 'academics/student_form.html', {
        'page_title': f'Edit {student.full_name}', 'form': form, 'student': student,
    })


@management_required
def student_add_guardian(request, pk):
    student = get_object_or_404(Student, pk=pk)
    form = StudentGuardianForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        link = form.save(commit=False)
        link.student = student
        link.save()
        messages.success(request, f'{link.guardian} linked to {student.full_name}.')
        return redirect('academics:student_detail', pk=student.pk)
    return render(request, 'academics/student_guardian_form.html', {
        'page_title': f'Link a guardian to {student.full_name}',
        'student': student, 'form': form,
    })


@staff_required
@require_POST
def student_add_note(request, pk):
    student = get_object_or_404(Student, pk=pk)
    form = StudentNoteForm(request.POST)
    if form.is_valid():
        note = form.save(commit=False)
        note.student = student
        note.author = request.user
        note.save()
        messages.success(request, 'Note added.')
    else:
        messages.error(request, 'The note could not be saved.')
    return redirect('academics:student_detail', pk=student.pk)


@management_required
def enrol_student(request, pk):
    student = get_object_or_404(Student, pk=pk)
    form = EnrolmentForm(request.POST or None, student=student)
    if request.method == 'POST' and form.is_valid():
        enrolment = form.save(commit=False)
        enrolment.student = student
        enrolment.enrolled_by = request.user
        enrolment.save()
        messages.success(
            request, f'{student.full_name} enrolled in {enrolment.dance_class.name}.',
        )
        return redirect('academics:student_detail', pk=student.pk)
    return render(request, 'academics/enrolment_form.html', {
        'page_title': f'Enrol {student.full_name}', 'student': student, 'form': form,
    })


# ---------------------------------------------------------------------------
# Progress reports
# ---------------------------------------------------------------------------
@staff_required
def report_list(request):
    period = AssessmentPeriod.current()
    classes = DanceClass.objects.active().select_related('program', 'term')
    if request.user.is_teacher and not request.user.is_management:
        classes = classes.taught_by(request.user)
    if period:
        classes = classes.filter(term=period.term)

    rows = [
        {
            'dance_class': dance_class,
            'expected': dance_class.enrolled_count,
            'written': ProgressReport.objects.filter(
                dance_class=dance_class, period=period,
            ).count() if period else 0,
            'published': ProgressReport.objects.filter(
                dance_class=dance_class, period=period, status=ReportStatus.PUBLISHED,
            ).count() if period else 0,
        }
        for dance_class in classes
    ]

    return render(request, 'academics/report_list.html', {
        'page_title': 'Progress reports',
        'period': period,
        'periods': AssessmentPeriod.objects.select_related('term')[:8],
        'rows': rows,
        'completion': services.report_completion(period) if period else None,
    })


@staff_required
def report_class(request, class_pk, period_pk=None):
    """The grid of dancers in one class for one assessment period."""
    dance_class = get_object_or_404(DanceClass, pk=class_pk)
    period = (
        get_object_or_404(AssessmentPeriod, pk=period_pk)
        if period_pk else AssessmentPeriod.current()
    )
    if not period:
        messages.warning(request, 'No assessment period is open yet.')
        return redirect('academics:report_list')

    return render(request, 'academics/report_class.html', {
        'page_title': f'{dance_class.name} — {period.name}',
        'dance_class': dance_class,
        'period': period,
        'rows': services.class_progress_overview(dance_class, period),
        'can_publish': request.user.is_management,
    })


@staff_required
def report_edit(request, class_pk, student_pk, period_pk=None):
    """Write or update one dancer's rubric and comments."""
    dance_class = get_object_or_404(DanceClass, pk=class_pk)
    student = get_object_or_404(Student, pk=student_pk)
    period = (
        get_object_or_404(AssessmentPeriod, pk=period_pk)
        if period_pk else AssessmentPeriod.current()
    )
    if not period:
        messages.warning(request, 'No assessment period is open yet.')
        return redirect('academics:report_list')

    report, _created = ProgressReport.objects.get_or_create(
        student=student, dance_class=dance_class, period=period,
        defaults={'teacher': getattr(request.user, 'staff_profile', None)},
    )
    services.ensure_report_scores(report)

    form = ProgressReportForm(request.POST or None, instance=report)
    formset = SkillScoreFormSet(request.POST or None, instance=report)

    if request.method == 'POST' and form.is_valid() and formset.is_valid():
        report = form.save(commit=False)
        if not report.teacher_id:
            report.teacher = getattr(request.user, 'staff_profile', None)
        report.save()
        formset.save()

        if request.POST.get('action') == 'submit':
            report.submit(by=request.user)
            messages.success(request, f'Report for {student.display_name} submitted.')
        else:
            messages.success(request, 'Draft saved.')
        return redirect('academics:report_class', class_pk=dance_class.pk, period_pk=period.pk)

    return render(request, 'academics/report_edit.html', {
        'page_title': f'Report — {student.full_name}',
        'report': report,
        'student': student,
        'dance_class': dance_class,
        'period': period,
        'form': form,
        'formset': formset,
        'attendance': Enrolment(
            student=student, dance_class=dance_class,
        ).attendance_summary(),
        'history': services.student_progress_trend(student),
    })


@verified_required
def report_detail(request, pk):
    report = get_object_or_404(
        ProgressReport.objects.select_related(
            'student', 'dance_class__program', 'period__term', 'teacher__user',
        ).prefetch_related('scores__skill__category'),
        pk=pk,
    )
    require_student_access(request.user, report.student)

    if not report.is_published and not request.user.is_studio_staff:
        messages.info(request, 'That report has not been published yet.')
        return redirect('academics:student_detail', pk=report.student.pk)

    if request.user.is_guardian and report.is_published and not report.guardian_viewed_at:
        report.guardian_viewed_at = timezone.now()
        report.save(update_fields=['guardian_viewed_at'])

    grouped: dict = {}
    for score in report.scores.all():
        grouped.setdefault(score.skill.category, []).append(score)

    return render(request, 'academics/report_detail.html', {
        'page_title': f'{report.student.full_name} — {report.period.name}',
        'report': report,
        'grouped_scores': grouped,
        'category_averages': report.category_averages(),
        'history': services.student_progress_trend(report.student),
    })


@management_required
@require_POST
def report_publish(request, pk):
    report = get_object_or_404(ProgressReport, pk=pk)
    report.publish(by=request.user)

    guardians = [
        link.guardian.user
        for link in report.student.guardian_links.select_related('guardian__user')
        if link.guardian.receives_progress_reports
    ]
    if report.student.user:
        guardians.append(report.student.user)
    if guardians:
        Notification.send(
            guardians,
            f'Progress report ready — {report.student.display_name}',
            f'{report.period.name} report from {report.dance_class.name} is now available.',
            level=NotificationLevel.SUCCESS,
            url=reverse('academics:report_detail', args=[report.pk]),
            icon='fa-chart-line',
        )

    messages.success(request, f'Report published to {report.student.display_name}’s family.')
    return redirect('academics:report_class',
                    class_pk=report.dance_class_id, period_pk=report.period_id)


@management_required
@require_POST
def report_publish_class(request, class_pk, period_pk):
    """Publish every submitted report for a class in one go."""
    reports = ProgressReport.objects.filter(
        dance_class_id=class_pk, period_id=period_pk, status=ReportStatus.SUBMITTED,
    )
    count = 0
    for report in reports:
        report.publish(by=request.user)
        count += 1
    messages.success(request, f'{count} report(s) published.')
    return redirect('academics:report_class', class_pk=class_pk, period_pk=period_pk)


# ---------------------------------------------------------------------------
# Chart data
# ---------------------------------------------------------------------------
@verified_required
def student_progress_json(request, pk):
    student = get_object_or_404(Student, pk=pk)
    require_student_access(request.user, student)
    return JsonResponse({
        'progress': services.student_progress_trend(student),
        'attendance': services.student_attendance_trend(student),
    })
