"""
Teaching: the timetable, the register and the progress rubric.

The register is the most-used screen in the building, so it is tested for the
things that actually go wrong -- re-saving a register, marking a dancer twice,
and reports that must not reach a family before a teacher has finished them.
"""

import datetime as dt

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import (
    ApprovalStatus,
    GuardianProfile,
    Role,
    StaffProfile,
    Student,
    StudentGuardian,
    User,
)

from . import services
from .forms import EnrolmentForm
from .models import (
    AcademicYear,
    AssessmentPeriod,
    Attendance,
    AttendanceStatus,
    ClassSchedule,
    ClassSession,
    DanceClass,
    Enrolment,
    EnrolmentStatus,
    Program,
    ProgressReport,
    ReportStatus,
    Skill,
    SkillCategory,
    Studio,
    Term,
    Weekday,
)


class TeachingTestCase(TestCase):
    """One programme, one class meeting twice a week, three dancers."""

    @classmethod
    def setUpTestData(cls):
        cls.year = AcademicYear.objects.create(
            name='2026', start_date=dt.date(2026, 1, 1),
            end_date=dt.date(2026, 12, 31), is_current=True,
        )
        cls.term = Term.objects.create(
            academic_year=cls.year, name='Term 1',
            start_date=dt.date(2026, 1, 5),      # a Monday
            end_date=dt.date(2026, 1, 25),
            is_current=True,
        )
        cls.programme = Program.objects.create(
            name='Junior Ballet', description='...', min_age=7, max_age=11,
        )
        cls.studio = Studio.objects.create(name='Studio A')

        cls.teacher_user = User.objects.create_user(
            username='aisha', email='aisha@example.com', password='pw',
            role=Role.TEACHER, approval_status=ApprovalStatus.APPROVED,
        )
        cls.teacher = StaffProfile.objects.create(user=cls.teacher_user)

        cls.admin = User.objects.create_user(
            username='grace', email='grace@example.com', password='pw',
            role=Role.ADMIN, approval_status=ApprovalStatus.APPROVED,
        )

        cls.dance_class = DanceClass.objects.create(
            name='Junior A', program=cls.programme, term=cls.term,
            studio=cls.studio, capacity=3,
        )
        cls.dance_class.teachers.add(cls.teacher)
        ClassSchedule.objects.create(
            dance_class=cls.dance_class, weekday=Weekday.MONDAY,
            start_time=dt.time(16, 0), end_time=dt.time(17, 0),
        )
        ClassSchedule.objects.create(
            dance_class=cls.dance_class, weekday=Weekday.WEDNESDAY,
            start_time=dt.time(16, 0), end_time=dt.time(17, 0),
        )

        cls.students = [
            Student.objects.create(
                first_name=name, last_name='Test',
                date_of_birth=dt.date(2016, 1, 1),
            )
            for name in ('Amara', 'Zuri', 'Kato')
        ]
        for student in cls.students:
            Enrolment.objects.create(student=student, dance_class=cls.dance_class)


class TimetableTests(TeachingTestCase):

    def test_sessions_are_generated_from_the_weekly_slots(self):
        created = services.generate_sessions(self.dance_class)
        # 5–25 January 2026: Mondays 5, 12, 19 and Wednesdays 7, 14, 21 = 6.
        self.assertEqual(len(created), 6)
        self.assertEqual(self.dance_class.sessions.count(), 6)
        weekdays = {s.date.weekday() for s in self.dance_class.sessions.all()}
        self.assertEqual(weekdays, {0, 2})

    def test_generating_twice_creates_nothing_new(self):
        services.generate_sessions(self.dance_class)
        second = services.generate_sessions(self.dance_class)
        self.assertEqual(second, [])
        self.assertEqual(self.dance_class.sessions.count(), 6)

    def test_holidays_are_skipped(self):
        created = services.generate_sessions(
            self.dance_class, skip_dates=[dt.date(2026, 1, 12), dt.date(2026, 1, 14)],
        )
        self.assertEqual(len(created), 4)

    def test_class_reports_its_own_capacity(self):
        self.assertEqual(self.dance_class.enrolled_count, 3)
        self.assertEqual(self.dance_class.places_left, 0)
        self.assertTrue(self.dance_class.is_full)
        self.assertEqual(self.dance_class.fill_percent, 100)

    def test_a_full_class_cannot_be_enrolled_into(self):
        extra = Student.objects.create(
            first_name='Late', last_name='Comer', date_of_birth=dt.date(2016, 5, 5),
        )
        form = EnrolmentForm(
            data={'dance_class': self.dance_class.pk, 'status': EnrolmentStatus.ACTIVE,
                  'date_enrolled': dt.date.today().isoformat()},
            student=extra,
        )
        self.assertFalse(form.is_valid())
        self.assertIn('dance_class', form.errors)


class RegisterTests(TeachingTestCase):

    def setUp(self):
        services.generate_sessions(self.dance_class)
        self.session = self.dance_class.sessions.order_by('date').first()

    def test_expected_students_are_the_active_enrolments(self):
        self.assertEqual(self.session.expected_students.count(), 3)

    def test_marking_a_register_records_everyone(self):
        marks = {s.pk: {'status': AttendanceStatus.PRESENT} for s in self.students}
        marks[self.students[1].pk] = {'status': AttendanceStatus.LATE, 'minutes_late': 10}

        created, updated = services.bulk_mark_register(
            self.session, marks, user=self.teacher_user,
        )
        self.assertEqual((created, updated), (3, 0))

        self.session.refresh_from_db()
        self.assertTrue(self.session.register_taken)
        self.assertEqual(self.session.register_taken_by, self.teacher_user)

        late = Attendance.objects.get(session=self.session, student=self.students[1])
        self.assertEqual(late.status, AttendanceStatus.LATE)
        self.assertEqual(late.minutes_late, 10)

    def test_re_marking_updates_rather_than_duplicates(self):
        marks = {s.pk: {'status': AttendanceStatus.PRESENT} for s in self.students}
        services.bulk_mark_register(self.session, marks, user=self.teacher_user)

        marks[self.students[0].pk] = {'status': AttendanceStatus.ABSENT}
        created, updated = services.bulk_mark_register(
            self.session, marks, user=self.teacher_user,
        )
        self.assertEqual((created, updated), (0, 3))
        self.assertEqual(Attendance.objects.filter(session=self.session).count(), 3)
        self.assertEqual(
            Attendance.objects.get(
                session=self.session, student=self.students[0]).status,
            AttendanceStatus.ABSENT,
        )

    def test_late_counts_as_attended_but_absent_does_not(self):
        marks = {
            self.students[0].pk: {'status': AttendanceStatus.PRESENT},
            self.students[1].pk: {'status': AttendanceStatus.LATE},
            self.students[2].pk: {'status': AttendanceStatus.ABSENT},
        }
        services.bulk_mark_register(self.session, marks, user=self.teacher_user)

        stats = services.attendance_stats(
            Attendance.objects.filter(session=self.session)
        )
        self.assertEqual(stats['total'], 3)
        self.assertEqual(stats['attended'], 2)
        self.assertAlmostEqual(stats['rate'], 66.7, places=1)

    def test_taking_the_register_over_http(self):
        self.client.force_login(self.teacher_user)
        payload = {'topic': 'Barre and centre', 'notes': ''}
        for student in self.students:
            payload[f'status_{student.pk}'] = AttendanceStatus.PRESENT
            payload[f'remarks_{student.pk}'] = ''

        response = self.client.post(
            reverse('academics:register', args=[self.session.pk]), payload,
        )
        self.assertRedirects(response, reverse('academics:register_list'))

        self.session.refresh_from_db()
        self.assertTrue(self.session.register_taken)
        self.assertEqual(self.session.topic, 'Barre and centre')

    def test_outstanding_registers_are_listed_for_the_right_teacher(self):
        past = ClassSession.objects.create(
            dance_class=self.dance_class,
            date=dt.date.today() - dt.timedelta(days=2),
            start_time=dt.time(16, 0), end_time=dt.time(17, 0),
        )
        outstanding = services.sessions_needing_registers(self.teacher_user)
        self.assertIn(past, outstanding)

        other_teacher = User.objects.create_user(
            username='daniel', email='daniel@example.com', password='pw',
            role=Role.TEACHER, approval_status=ApprovalStatus.APPROVED,
        )
        self.assertNotIn(past, services.sessions_needing_registers(other_teacher))


class ProgressReportTests(TeachingTestCase):

    def setUp(self):
        technique = SkillCategory.objects.create(name='Technique', display_order=0)
        musicality = SkillCategory.objects.create(name='Musicality', display_order=1)
        for name in ('Turnout', 'Alignment'):
            Skill.objects.create(category=technique, name=name, max_score=5)
        Skill.objects.create(category=musicality, name='Timing', max_score=5)

        pointe = Skill.objects.create(
            category=technique, name='Pointe work', max_score=5,
        )
        other = Program.objects.create(name='Senior Ballet', description='...')
        pointe.programs.add(other)      # restricted -- must not appear here

        self.period = AssessmentPeriod.objects.create(
            term=self.term, name='End of Term 1',
            opens_on=dt.date.today() - dt.timedelta(days=3),
            closes_on=dt.date.today() + dt.timedelta(days=10),
        )
        self.student = self.students[0]

    def test_rubric_only_includes_skills_for_this_programme(self):
        report = ProgressReport.objects.create(
            student=self.student, dance_class=self.dance_class,
            period=self.period, teacher=self.teacher,
        )
        scores = services.ensure_report_scores(report)
        names = {s.skill.name for s in scores}
        self.assertEqual(names, {'Turnout', 'Alignment', 'Timing'})
        self.assertNotIn('Pointe work', names)

    def test_scores_average_correctly(self):
        report = ProgressReport.objects.create(
            student=self.student, dance_class=self.dance_class, period=self.period,
        )
        services.ensure_report_scores(report)
        for score in report.scores.all():
            score.score = 4
            score.save()

        report.refresh_from_db()
        self.assertEqual(report.average_score, 4.0)
        self.assertEqual(report.average_percent, 80.0)

    def test_category_averages_drive_the_radar_chart(self):
        report = ProgressReport.objects.create(
            student=self.student, dance_class=self.dance_class, period=self.period,
        )
        services.ensure_report_scores(report)
        for score in report.scores.select_related('skill__category'):
            score.score = 5 if score.skill.category.name == 'Technique' else 3
            score.save()

        rows = {r['category']: r['percent'] for r in report.category_averages()}
        self.assertEqual(rows['Technique'], 100.0)
        self.assertEqual(rows['Musicality'], 60.0)

    def test_a_draft_report_is_not_visible_to_the_family(self):
        report = ProgressReport.objects.create(
            student=self.student, dance_class=self.dance_class, period=self.period,
        )
        parent = User.objects.create_user(
            username='parent', email='parent@example.com', password='pw',
            role=Role.PARENT, approval_status=ApprovalStatus.APPROVED,
        )
        guardian = GuardianProfile.objects.create(user=parent)
        StudentGuardian.objects.create(
            student=self.student, guardian=guardian, is_primary=True,
        )

        self.client.force_login(parent)
        response = self.client.get(
            reverse('academics:report_detail', args=[report.pk])
        )
        self.assertEqual(response.status_code, 302)

        report.publish(by=self.admin)
        response = self.client.get(
            reverse('academics:report_detail', args=[report.pk])
        )
        self.assertEqual(response.status_code, 200)

    def test_publishing_snapshots_attendance_and_notifies_the_family(self):
        services.generate_sessions(self.dance_class)
        session = self.dance_class.sessions.first()
        services.bulk_mark_register(
            session, {self.student.pk: {'status': AttendanceStatus.PRESENT}},
        )

        parent = User.objects.create_user(
            username='parent2', email='parent2@example.com', password='pw',
            role=Role.PARENT, approval_status=ApprovalStatus.APPROVED,
        )
        guardian = GuardianProfile.objects.create(user=parent)
        StudentGuardian.objects.create(
            student=self.student, guardian=guardian, is_primary=True,
        )

        report = ProgressReport.objects.create(
            student=self.student, dance_class=self.dance_class, period=self.period,
            status=ReportStatus.SUBMITTED,
        )
        self.client.force_login(self.admin)
        self.client.post(reverse('academics:report_publish', args=[report.pk]))

        report.refresh_from_db()
        self.assertEqual(report.status, ReportStatus.PUBLISHED)
        self.assertEqual(report.attendance_rate, 100.0)
        self.assertTrue(
            parent.notifications.filter(title__icontains='Progress report').exists()
        )

    def test_progress_trend_only_reports_published_rounds(self):
        report = ProgressReport.objects.create(
            student=self.student, dance_class=self.dance_class, period=self.period,
        )
        services.ensure_report_scores(report)
        for score in report.scores.all():
            score.score = 4
            score.save()

        self.assertEqual(services.student_progress_trend(self.student)['labels'], [])

        report.publish()
        trend = services.student_progress_trend(self.student)
        self.assertEqual(trend['labels'], ['End of Term 1'])
        self.assertEqual(trend['overall'], [80.0])


class TermTests(TestCase):

    def test_only_one_term_can_be_current(self):
        year = AcademicYear.objects.create(
            name='2026', start_date=dt.date(2026, 1, 1),
            end_date=dt.date(2026, 12, 31), is_current=True,
        )
        first = Term.objects.create(
            academic_year=year, name='Term 1',
            start_date=dt.date(2026, 1, 15), end_date=dt.date(2026, 4, 10),
            is_current=True,
        )
        second = Term.objects.create(
            academic_year=year, name='Term 2',
            start_date=dt.date(2026, 5, 5), end_date=dt.date(2026, 8, 8),
            is_current=True,
        )
        first.refresh_from_db()
        self.assertFalse(first.is_current)
        self.assertTrue(second.is_current)
        self.assertEqual(Term.current(), second)
