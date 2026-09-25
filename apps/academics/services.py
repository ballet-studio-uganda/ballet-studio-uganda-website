"""
Teaching-side helpers: building the timetable, reading attendance, and
turning rubric scores into progress trends.
"""

from __future__ import annotations

import datetime as dt
from collections import OrderedDict

from django.db.models import Avg, Count, Q
from django.utils import timezone

from apps.accounts.models import Student
from .models import (
    ATTENDED_STATUSES,
    Attendance,
    AttendanceStatus,
    ClassSession,
    DanceClass,
    Enrolment,
    EnrolmentStatus,
    ProgressReport,
    ReportStatus,
    SessionStatus,
    Skill,
    SkillScore,
)


# ---------------------------------------------------------------------------
# Timetable
# ---------------------------------------------------------------------------
def generate_sessions(dance_class, start=None, end=None, skip_dates=None):
    """
    Create :class:`ClassSession` rows for every timetable slot of *dance_class*
    between *start* and *end* (its term by default).

    Idempotent -- existing sessions are left alone, so it is safe to re-run
    after adding a slot mid-term. Returns the sessions it created.
    """
    term = dance_class.term
    start = start or term.start_date
    end = end or term.end_date
    skip = set(skip_dates or [])

    slots = list(dance_class.schedules.all())
    if not slots:
        return []

    teacher = dance_class.teachers.first()
    existing = set(
        ClassSession.objects.filter(
            dance_class=dance_class, date__gte=start, date__lte=end,
        ).values_list('date', 'start_time')
    )

    created = []
    day = start
    while day <= end:
        if day not in skip:
            for slot in slots:
                if slot.weekday != day.weekday():
                    continue
                if (day, slot.start_time) in existing:
                    continue
                created.append(ClassSession(
                    dance_class=dance_class,
                    date=day,
                    start_time=slot.start_time,
                    end_time=slot.end_time,
                    studio=slot.studio or dance_class.studio,
                    teacher=teacher,
                    status=SessionStatus.SCHEDULED,
                ))
        day += dt.timedelta(days=1)

    if created:
        ClassSession.objects.bulk_create(created, ignore_conflicts=True)
    return created


def sessions_needing_registers(user=None, days_back=14):
    """Past sessions with no register taken -- the teacher's nag list."""
    since = dt.date.today() - dt.timedelta(days=days_back)
    qs = (
        ClassSession.objects.filter(
            date__gte=since,
            date__lte=dt.date.today(),
            register_taken=False,
            status__in=[SessionStatus.SCHEDULED, SessionStatus.HELD],
        )
        .select_related('dance_class', 'dance_class__program')
        .order_by('date', 'start_time')
    )
    if user is not None and user.is_teacher:
        qs = qs.filter(dance_class__teachers__user=user)
    return qs.distinct()


def timetable_for_week(monday, dance_classes=None, teacher=None):
    """
    ``OrderedDict`` of ``date -> [sessions]`` for a Monday-to-Sunday week,
    ready for the timetable grid.
    """
    sunday = monday + dt.timedelta(days=6)
    qs = (
        ClassSession.objects.filter(date__gte=monday, date__lte=sunday)
        .select_related('dance_class', 'dance_class__program', 'studio', 'teacher__user')
        .order_by('date', 'start_time')
    )
    if dance_classes is not None:
        qs = qs.filter(dance_class__in=dance_classes)
    if teacher is not None:
        qs = qs.filter(dance_class__teachers__user=teacher).distinct()

    week = OrderedDict()
    for offset in range(7):
        week[monday + dt.timedelta(days=offset)] = []
    for session in qs:
        week[session.date].append(session)
    return week


# ---------------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------------
def attendance_stats(queryset):
    """Counts and a rate from any :class:`Attendance` queryset."""
    totals = queryset.aggregate(
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


def student_attendance_trend(student, months=6):
    """Monthly attendance percentage for a dancer, for the progress page chart."""
    today = dt.date.today()
    start = (today.replace(day=1) - dt.timedelta(days=31 * (months - 1))).replace(day=1)

    labels, rates = [], []
    cursor = start
    while cursor <= today:
        if cursor.month == 12:
            nxt = cursor.replace(year=cursor.year + 1, month=1)
        else:
            nxt = cursor.replace(month=cursor.month + 1)
        stats = attendance_stats(
            Attendance.objects.filter(
                student=student,
                session__date__gte=cursor,
                session__date__lt=nxt,
            )
        )
        labels.append(cursor.strftime('%b %y'))
        rates.append(stats['rate'] if stats['rate'] is not None else None)
        cursor = nxt
    return {'labels': labels, 'rates': rates}


def attendance_by_class(start=None, end=None):
    """Attendance rate per class, for the staff overview."""
    rows = []
    for dance_class in (
        DanceClass.objects.active()
        .select_related('program', 'term')
        .prefetch_related('teachers__user')
    ):
        marks = Attendance.objects.filter(session__dance_class=dance_class)
        if start:
            marks = marks.filter(session__date__gte=start)
        if end:
            marks = marks.filter(session__date__lte=end)
        stats = attendance_stats(marks)
        if stats['total']:
            rows.append({
                'dance_class': dance_class,
                'colour': dance_class.program.accent_colour,
                **stats,
            })
    rows.sort(key=lambda r: r['rate'] or 0)
    return rows


def students_of_concern(threshold=70, min_sessions=4):
    """
    Dancers whose attendance has dropped below *threshold* percent.

    Surfaced on the staff dashboard so someone rings the family before a
    child quietly stops coming.
    """
    flagged = []
    for student in Student.objects.active().prefetch_related('enrolments__dance_class'):
        stats = attendance_stats(Attendance.objects.filter(student=student))
        if stats['total'] >= min_sessions and stats['rate'] is not None:
            if stats['rate'] < threshold:
                flagged.append({'student': student, **stats})
    flagged.sort(key=lambda r: r['rate'])
    return flagged


def bulk_mark_register(session, marks, user=None):
    """
    Save a whole register at once.

    *marks* maps ``student_id -> {'status': ..., 'remarks': ..., 'minutes_late': ...}``.
    Existing marks for the session are updated rather than duplicated.
    """
    existing = {a.student_id: a for a in session.attendances.all()}
    to_create, to_update = [], []

    for student_id, data in marks.items():
        status = data.get('status') or AttendanceStatus.PRESENT
        remarks = (data.get('remarks') or '')[:200]
        minutes_late = data.get('minutes_late') or None

        if student_id in existing:
            mark = existing[student_id]
            mark.status = status
            mark.remarks = remarks
            mark.minutes_late = minutes_late
            mark.marked_by = user
            to_update.append(mark)
        else:
            to_create.append(Attendance(
                session=session, student_id=student_id, status=status,
                remarks=remarks, minutes_late=minutes_late, marked_by=user,
            ))

    if to_create:
        Attendance.objects.bulk_create(to_create)
    if to_update:
        Attendance.objects.bulk_update(
            to_update, ['status', 'remarks', 'minutes_late', 'marked_by'],
        )

    session.mark_register_taken(by=user)
    return len(to_create), len(to_update)


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------
def ensure_report_scores(report):
    """
    Make sure a report has a :class:`SkillScore` row for every skill that
    applies to its programme, so the teacher sees a complete form.
    """
    applicable = Skill.for_program(report.dance_class.program)
    have = set(report.scores.values_list('skill_id', flat=True))
    missing = [
        SkillScore(report=report, skill=skill, score=0)
        for skill in applicable if skill.id not in have
    ]
    if missing:
        SkillScore.objects.bulk_create(missing)
    return report.scores.select_related('skill', 'skill__category').all()


def student_progress_trend(student):
    """
    Average rubric score per assessment period, plus the same split by
    category -- the dancer's progress chart.
    """
    reports = (
        student.progress_reports.filter(status=ReportStatus.PUBLISHED)
        .select_related('period', 'period__term')
        .order_by('period__opens_on')
    )

    labels, overall = [], []
    by_category: dict[str, dict] = {}

    for report in reports:
        labels.append(report.period.name)
        overall.append(report.average_percent)
        for row in report.category_averages():
            bucket = by_category.setdefault(
                row['category'], {'colour': row['colour'], 'values': []},
            )
            # Pad so every category series lines up with the labels.
            while len(bucket['values']) < len(labels) - 1:
                bucket['values'].append(None)
            bucket['values'].append(row['percent'])

    for bucket in by_category.values():
        while len(bucket['values']) < len(labels):
            bucket['values'].append(None)

    return {
        'labels': labels,
        'overall': overall,
        'categories': [
            {'name': name, 'colour': data['colour'], 'values': data['values']}
            for name, data in by_category.items()
        ],
    }


def latest_report_for(student):
    return (
        student.progress_reports.filter(status=ReportStatus.PUBLISHED)
        .select_related('period', 'dance_class', 'teacher__user')
        .order_by('-period__opens_on')
        .first()
    )


def class_progress_overview(dance_class, period):
    """Every enrolled dancer with their report state, for the teacher's grid."""
    reports = {
        r.student_id: r
        for r in ProgressReport.objects.filter(dance_class=dance_class, period=period)
        .prefetch_related('scores__skill')
    }
    rows = []
    for enrolment in (
        dance_class.enrolments.filter(status=EnrolmentStatus.ACTIVE)
        .select_related('student')
        .order_by('student__first_name')
    ):
        report = reports.get(enrolment.student_id)
        rows.append({
            'student': enrolment.student,
            'report': report,
            'status': report.status if report else None,
            'average': report.average_percent if report else None,
            'attendance': enrolment.attendance_summary(),
        })
    return rows


def report_completion(period):
    """How far through the reporting round the studio is."""
    expected = Enrolment.objects.filter(
        status=EnrolmentStatus.ACTIVE, dance_class__term=period.term,
    ).count()
    written = ProgressReport.objects.filter(period=period).count()
    published = ProgressReport.objects.filter(
        period=period, status=ReportStatus.PUBLISHED,
    ).count()
    return {
        'expected': expected,
        'written': written,
        'published': published,
        'percent': round(published / expected * 100) if expected else 0,
    }
