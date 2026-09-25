"""
Identity, verification and access control.

These are the tests that matter most for safeguarding: children's records must
never be reachable by someone outside the family or the teaching team.
"""

import datetime as dt

from django.test import TestCase
from django.urls import reverse

from apps.academics.models import (
    AcademicYear,
    DanceClass,
    Enrolment,
    Program,
    Term,
)
from .models import (
    ApprovalStatus,
    GuardianProfile,
    Role,
    StaffProfile,
    Student,
    StudentGuardian,
    User,
)
from .permissions import can_mark_register, can_view_student


def make_user(username, role, approved=True, **extra):
    user = User.objects.create_user(
        username=username,
        email=f'{username}@example.com',
        password='studio-test-pw',
        role=role,
        first_name=username.title(),
        last_name='Test',
        approval_status=ApprovalStatus.APPROVED if approved else ApprovalStatus.PENDING,
        **extra,
    )
    return user


class SignupTests(TestCase):
    """Every self-registration must land as PENDING and be gated until approved."""

    def test_guardian_signup_creates_pending_account_and_profile(self):
        response = self.client.post(reverse('accounts:signup_guardian'), {
            'first_name': 'Miriam', 'last_name': 'Nakamya',
            'email': 'miriam@example.com', 'username': 'miriam',
            'phone': '+256772000111',
            'password1': 'BalletStudio2026!', 'password2': 'BalletStudio2026!',
            'agree_to_terms': 'on',
        })
        self.assertRedirects(response, reverse('accounts:pending'))

        user = User.objects.get(email='miriam@example.com')
        self.assertEqual(user.role, Role.PARENT)
        self.assertEqual(user.approval_status, ApprovalStatus.PENDING)
        self.assertFalse(user.is_verified)
        self.assertTrue(hasattr(user, 'guardian_profile'))

    def test_duplicate_email_is_rejected(self):
        make_user('existing', Role.PARENT)
        response = self.client.post(reverse('accounts:signup_guardian'), {
            'first_name': 'Someone', 'last_name': 'Else',
            'email': 'existing@example.com', 'username': 'someoneelse',
            'password1': 'BalletStudio2026!', 'password2': 'BalletStudio2026!',
            'agree_to_terms': 'on',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'already exists')
        self.assertEqual(User.objects.filter(email='existing@example.com').count(), 1)

    def test_student_signup_links_to_an_existing_dancer_by_id(self):
        student = Student.objects.create(
            first_name='Zuri', last_name='Okello',
            date_of_birth=dt.date(2010, 4, 2),
        )
        self.client.post(reverse('accounts:signup_student'), {
            'first_name': 'Zuri', 'last_name': 'Okello',
            'email': 'zuri@example.com', 'username': 'zuri',
            'date_of_birth': '2010-04-02', 'student_id': student.student_id,
            'password1': 'BalletStudio2026!', 'password2': 'BalletStudio2026!',
            'agree_to_terms': 'on',
        })
        student.refresh_from_db()
        self.assertIsNotNone(student.user)
        self.assertEqual(student.user.email, 'zuri@example.com')


class VerificationGateTests(TestCase):
    """An unverified account can sign in, but goes no further than the holding page."""

    def setUp(self):
        self.pending = make_user('pending', Role.PARENT, approved=False)
        self.admin = make_user('admin', Role.ADMIN)

    def test_unverified_user_is_held(self):
        self.client.force_login(self.pending)
        for url in ('dashboard:home', 'finance:dashboard', 'academics:class_list'):
            with self.subTest(url=url):
                response = self.client.get(reverse(url))
                self.assertEqual(response.status_code, 302)
                self.assertIn('pending', response['Location'])

    def test_administrator_verification_opens_access(self):
        self.client.force_login(self.admin)
        self.client.post(reverse('dashboard:quick_verify', args=[self.pending.pk]))

        self.pending.refresh_from_db()
        self.assertTrue(self.pending.is_verified)
        self.assertEqual(self.pending.verified_by, self.admin)
        self.assertIsNotNone(self.pending.verified_at)
        self.assertTrue(hasattr(self.pending, 'guardian_profile'))
        self.assertTrue(
            self.pending.notifications.filter(title__icontains='verified').exists()
        )

        self.client.force_login(self.pending)
        self.assertEqual(self.client.get(reverse('dashboard:home')).status_code, 200)

    def test_rejection_keeps_the_user_out(self):
        self.pending.reject(by=self.admin, note='Could not match to our records')
        self.assertEqual(self.pending.approval_status, ApprovalStatus.REJECTED)
        self.assertFalse(self.pending.has_studio_access())


class RoleBoundaryTests(TestCase):
    """Each role sees its own part of the system and no more."""

    def setUp(self):
        self.director = make_user('director', Role.DIRECTOR)
        self.teacher = make_user('teacher', Role.TEACHER)
        self.parent = make_user('parent', Role.PARENT)
        GuardianProfile.objects.create(user=self.parent)

    def test_teacher_cannot_reach_money_or_people_admin(self):
        self.client.force_login(self.teacher)
        for url in ('finance:dashboard', 'finance:payment_list', 'dashboard:user_list'):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(reverse(url)).status_code, 302)

    def test_teacher_can_reach_teaching_areas(self):
        self.client.force_login(self.teacher)
        for url in ('academics:class_list', 'academics:register_list',
                    'academics:student_list', 'academics:report_list'):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(reverse(url)).status_code, 200)

    def test_parent_is_limited_to_their_own_family(self):
        self.client.force_login(self.parent)
        self.assertEqual(self.client.get(reverse('academics:class_list')).status_code, 302)
        self.assertEqual(self.client.get(reverse('finance:dashboard')).status_code, 302)
        self.assertEqual(self.client.get(reverse('finance:my_statement')).status_code, 200)

    def test_director_reaches_everything(self):
        self.client.force_login(self.director)
        for url in ('dashboard:home', 'finance:dashboard', 'finance:reports',
                    'academics:class_list', 'dashboard:user_list'):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(reverse(url)).status_code, 200)


class StudentAccessTests(TestCase):
    """Object-level access: the safeguarding boundary around a dancer's record."""

    def setUp(self):
        year = AcademicYear.objects.create(
            name='2026', start_date=dt.date(2026, 1, 1),
            end_date=dt.date(2026, 12, 31), is_current=True,
        )
        self.term = Term.objects.create(
            academic_year=year, name='Term 1',
            start_date=dt.date(2026, 1, 15), end_date=dt.date(2026, 4, 10),
            is_current=True,
        )
        programme = Program.objects.create(name='Junior Ballet', description='...')

        self.teacher = make_user('teacher', Role.TEACHER)
        teacher_profile = StaffProfile.objects.create(user=self.teacher)
        self.other_teacher = make_user('other_teacher', Role.TEACHER)
        StaffProfile.objects.create(user=self.other_teacher)

        self.dance_class = DanceClass.objects.create(
            name='Junior A', program=programme, term=self.term,
        )
        self.dance_class.teachers.add(teacher_profile)

        self.student = Student.objects.create(
            first_name='Amara', last_name='Kigozi', date_of_birth=dt.date(2016, 3, 1),
        )
        Enrolment.objects.create(student=self.student, dance_class=self.dance_class)

        self.parent = make_user('parent', Role.PARENT)
        guardian = GuardianProfile.objects.create(user=self.parent)
        StudentGuardian.objects.create(
            student=self.student, guardian=guardian, is_primary=True,
        )

        self.stranger = make_user('stranger', Role.PARENT)
        GuardianProfile.objects.create(user=self.stranger)

        self.director = make_user('director', Role.DIRECTOR)

    def test_who_may_view_the_record(self):
        self.assertTrue(can_view_student(self.director, self.student))
        self.assertTrue(can_view_student(self.teacher, self.student))
        self.assertTrue(can_view_student(self.parent, self.student))
        self.assertFalse(can_view_student(self.other_teacher, self.student))
        self.assertFalse(can_view_student(self.stranger, self.student))

    def test_unrelated_guardian_is_refused_over_http(self):
        self.client.force_login(self.stranger)
        response = self.client.get(
            reverse('academics:student_detail', args=[self.student.pk])
        )
        self.assertEqual(response.status_code, 403)

    def test_own_guardian_is_allowed(self):
        self.client.force_login(self.parent)
        response = self.client.get(
            reverse('academics:student_detail', args=[self.student.pk])
        )
        self.assertEqual(response.status_code, 200)

    def test_only_the_assigned_teacher_may_mark_the_register(self):
        from apps.academics.models import ClassSession
        session = ClassSession.objects.create(
            dance_class=self.dance_class, date=dt.date(2026, 2, 2),
            start_time=dt.time(16, 0), end_time=dt.time(17, 0),
        )
        self.assertTrue(can_mark_register(self.teacher, session))
        self.assertTrue(can_mark_register(self.director, session))
        self.assertFalse(can_mark_register(self.other_teacher, session))
        self.assertFalse(can_mark_register(self.parent, session))


class ReferenceNumberTests(TestCase):
    """Human-readable IDs are what staff quote on the phone -- they must be unique."""

    def test_student_ids_are_sequential_and_unique(self):
        ids = [
            Student.objects.create(
                first_name=f'Dancer{i}', last_name='Test',
                date_of_birth=dt.date(2015, 1, 1),
            ).student_id
            for i in range(5)
        ]
        self.assertEqual(len(set(ids)), 5)
        year = dt.date.today().year
        self.assertTrue(all(i.startswith(f'BDSU-{year}-') for i in ids))
        self.assertEqual(ids[0][-4:], '0001')
        self.assertEqual(ids[4][-4:], '0005')

    def test_login_accepts_email_or_username(self):
        make_user('grace', Role.ADMIN)
        for identifier in ('grace', 'grace@example.com', 'GRACE@EXAMPLE.COM'):
            with self.subTest(identifier=identifier):
                self.assertTrue(
                    self.client.login(username=identifier, password='studio-test-pw')
                )
                self.client.logout()
