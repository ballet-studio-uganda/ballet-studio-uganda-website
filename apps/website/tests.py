"""
The public site and the content an administrator controls.

Covers the two inbound forms the studio depends on (enrolment enquiries and
contact messages), the announcement audience rules, and a smoke pass over every
public URL so a broken template is caught before a visitor finds it.
"""

import datetime as dt

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.academics.models import ApplicationStatus, EnrolmentApplication, Program
from apps.accounts.models import ApprovalStatus, Role, StaffProfile, User

from .models import (
    Announcement,
    AnnouncementAudience,
    ContactMessage,
    GalleryAlbum,
    HeroSlide,
    NewsPost,
    NewsletterSubscriber,
    Page,
    PublishStatus,
    SiteSettings,
)


class PublicPageTests(TestCase):
    """Every public URL must render for an anonymous visitor."""

    @classmethod
    def setUpTestData(cls):
        cls.programme = Program.objects.create(
            name='Junior Ballet', description='Technique and musicality.',
            show_on_website=True,
        )
        cls.post = NewsPost.objects.create(
            title='Enrolment is open', body='<p>Places are filling.</p>',
            status=PublishStatus.PUBLISHED, published_at=timezone.now(),
        )
        cls.album = GalleryAlbum.objects.create(title='Studio life', is_public=True)
        cls.page = Page.objects.create(
            title='Privacy Policy', slug='privacy-policy', body='<p>...</p>',
        )

    def test_every_public_url_renders(self):
        urls = [
            reverse('website:home'),
            reverse('website:about'),
            reverse('website:faculty'),
            reverse('website:programmes'),
            reverse('website:programme_detail', args=[self.programme.slug]),
            reverse('website:news_list'),
            reverse('website:news_detail', args=[self.post.slug]),
            reverse('website:gallery'),
            reverse('website:album_detail', args=[self.album.slug]),
            reverse('website:videos'),
            reverse('website:contact'),
            reverse('website:enrol'),
            reverse('website:enrol_thanks'),
            reverse('website:faqs'),
            reverse('website:search'),
            reverse('website:page', args=[self.page.slug]),
            reverse('events:list'),
            reverse('events:calendar'),
            reverse('events:calendar_year', args=[dt.date.today().year]),
            reverse('events:recital'),
            reverse('events:recital_archive'),
            reverse('accounts:login'),
            reverse('accounts:signup'),
            '/robots.txt',
            '/sitemap.xml',
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_home_page_survives_an_empty_database(self):
        """A brand-new install must not show a broken home page."""
        NewsPost.objects.all().delete()
        Program.objects.all().delete()
        GalleryAlbum.objects.all().delete()
        response = self.client.get(reverse('website:home'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ballet')

    def test_an_unpublished_post_is_not_reachable(self):
        draft = NewsPost.objects.create(title='Draft', body='...',
                                        status=PublishStatus.DRAFT)
        response = self.client.get(
            reverse('website:news_detail', args=[draft.slug])
        )
        self.assertEqual(response.status_code, 404)

    def test_the_404_page_is_the_branded_one(self):
        response = self.client.get('/no-such-page/')
        self.assertEqual(response.status_code, 404)

    def test_robots_keeps_crawlers_out_of_the_management_system(self):
        body = self.client.get('/robots.txt').content.decode()
        for path in ('/dashboard/', '/finance/', '/studio/', '/django-admin/'):
            self.assertIn(f'Disallow: {path}', body)


class EnrolmentEnquiryTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.programme = Program.objects.create(
            name='Kinder Ballet', description='...', show_on_website=True,
        )
        cls.admin = User.objects.create_user(
            username='grace', email='grace@example.com', password='pw',
            role=Role.ADMIN, approval_status=ApprovalStatus.APPROVED,
        )

    def valid_data(self, **overrides):
        data = {
            'student_first_name': 'Amara', 'student_last_name': 'Kigozi',
            'student_date_of_birth': '2020-05-14', 'student_gender': 'F',
            'guardian_name': 'Miriam Kigozi', 'guardian_email': 'miriam@example.com',
            'guardian_phone': '+256772000111', 'guardian_relationship': 'Mother',
            'program': self.programme.pk, 'consent': 'on',
        }
        data.update(overrides)
        return data

    def test_an_enquiry_is_saved_and_the_office_is_notified(self):
        response = self.client.post(reverse('website:enrol'), self.valid_data())
        self.assertRedirects(response, reverse('website:enrol_thanks'))

        application = EnrolmentApplication.objects.get()
        self.assertEqual(application.student_full_name, 'Amara Kigozi')
        self.assertEqual(application.status, ApplicationStatus.NEW)
        self.assertTrue(
            self.admin.notifications.filter(title__icontains='enrolment').exists()
        )

    def test_consent_is_required(self):
        data = self.valid_data()
        data.pop('consent')
        response = self.client.post(reverse('website:enrol'), data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(EnrolmentApplication.objects.count(), 0)

    def test_the_honeypot_silently_blocks_bots(self):
        response = self.client.post(
            reverse('website:enrol'), self.valid_data(website='http://spam.example')
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(EnrolmentApplication.objects.count(), 0)

    def test_student_age_is_derived_from_the_date_of_birth(self):
        self.client.post(reverse('website:enrol'), self.valid_data(
            student_date_of_birth=(
                dt.date.today().replace(year=dt.date.today().year - 6)
            ).isoformat(),
        ))
        self.assertEqual(EnrolmentApplication.objects.get().student_age, 6)


class ContactFormTests(TestCase):

    def test_a_message_is_stored(self):
        response = self.client.post(reverse('website:contact'), {
            'name': 'Joseph Okot', 'email': 'joseph@example.com',
            'phone': '+256701222333', 'topic': 'general',
            'subject': 'Class times', 'message': 'What time is Saturday Kinder Ballet?',
        })
        self.assertRedirects(response, reverse('website:contact'))
        message = ContactMessage.objects.get()
        self.assertEqual(message.name, 'Joseph Okot')
        self.assertFalse(message.is_read)

    def test_the_honeypot_blocks_bots(self):
        self.client.post(reverse('website:contact'), {
            'name': 'Bot', 'email': 'bot@example.com', 'topic': 'general',
            'message': 'spam', 'website': 'http://spam.example',
        })
        self.assertEqual(ContactMessage.objects.count(), 0)

    def test_newsletter_signup_is_idempotent(self):
        for _ in range(2):
            self.client.post(reverse('website:newsletter'),
                             {'email': 'family@example.com'})
        self.assertEqual(NewsletterSubscriber.objects.count(), 1)


class AnnouncementAudienceTests(TestCase):
    """An announcement must only reach the audience it was written for."""

    @classmethod
    def setUpTestData(cls):
        for audience in (AnnouncementAudience.PUBLIC, AnnouncementAudience.PARENTS,
                         AnnouncementAudience.STAFF, AnnouncementAudience.STUDENTS):
            Announcement.objects.create(
                title=f'For {audience}', message='...', audience=audience,
            )
        cls.parent = User.objects.create_user(
            username='parent', email='parent@example.com', password='pw',
            role=Role.PARENT, approval_status=ApprovalStatus.APPROVED,
        )
        cls.teacher = User.objects.create_user(
            username='teacher', email='teacher@example.com', password='pw',
            role=Role.TEACHER, approval_status=ApprovalStatus.APPROVED,
        )

    def audiences_for(self, user):
        return set(Announcement.live_for(user).values_list('audience', flat=True))

    def test_anonymous_visitors_see_only_public_notices(self):
        from django.contrib.auth.models import AnonymousUser
        self.assertEqual(
            self.audiences_for(AnonymousUser()), {AnnouncementAudience.PUBLIC},
        )

    def test_a_parent_sees_public_and_parent_notices(self):
        self.assertEqual(
            self.audiences_for(self.parent),
            {AnnouncementAudience.PUBLIC, AnnouncementAudience.PARENTS},
        )
        self.assertNotIn(AnnouncementAudience.STAFF, self.audiences_for(self.parent))

    def test_staff_see_the_staff_notices(self):
        self.assertIn(AnnouncementAudience.STAFF, self.audiences_for(self.teacher))

    def test_an_expired_announcement_disappears(self):
        Announcement.objects.update(
            ends_at=timezone.now() - dt.timedelta(days=1),
        )
        from django.contrib.auth.models import AnonymousUser
        self.assertEqual(Announcement.live_for(AnonymousUser()).count(), 0)


class SiteSettingsTests(TestCase):

    def test_settings_are_a_singleton(self):
        first = SiteSettings.load()
        first.studio_name = 'Ballet Dance Studio UG'
        first.save()

        second = SiteSettings.load()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(SiteSettings.objects.count(), 1)

    def test_social_links_skip_the_blanks(self):
        settings_row = SiteSettings.load()
        settings_row.facebook_url = 'https://facebook.com/bdsug'
        settings_row.instagram_url = ''
        settings_row.save()
        links = dict((icon, url) for icon, url in settings_row.social_links)
        self.assertEqual(len(links), 1)
        self.assertIn('fab fa-facebook-f', links)


class SeedCommandTests(TestCase):
    """The seed command is how a new studio gets its first day of data."""

    def test_reference_seed_is_idempotent(self):
        call_command('seed_studio', verbosity=0)
        programmes = Program.objects.count()
        self.assertGreater(programmes, 0)

        call_command('seed_studio', verbosity=0)
        self.assertEqual(Program.objects.count(), programmes)

    def test_seed_creates_the_rubric_and_fee_catalogue(self):
        from apps.academics.models import Skill, SkillCategory
        from apps.finance.models import ExpenseCategory, FeeCategory

        call_command('seed_studio', verbosity=0)
        self.assertGreater(SkillCategory.objects.count(), 0)
        self.assertGreater(Skill.objects.count(), 0)
        self.assertGreater(FeeCategory.objects.count(), 0)
        self.assertGreater(ExpenseCategory.objects.count(), 0)
        self.assertTrue(HeroSlide.objects.filter(is_active=True).exists())


class HealthCheckTests(TestCase):
    """
    The endpoint Render polls to decide whether a deploy is healthy.

    It has to be stricter than "the process is running", because a build that
    skipped `migrate` produces a process that starts fine and then fails every
    real request.
    """

    def test_healthy_deployment_reports_ok(self):
        response = self.client.get('/healthz')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'ok')

    def test_it_is_reachable_without_signing_in(self):
        # Render's prober carries no session.
        self.assertEqual(self.client.get('/healthz').status_code, 200)

    def test_unapplied_migrations_fail_the_check(self):
        from unittest.mock import patch
        from apps.website import views

        views._SCHEMA_VERIFIED = False           # undo any earlier caching
        fake = [(type('M', (), {'app_label': 'finance', 'name': '0002_x'})(), False)]

        with patch('django.db.migrations.executor.MigrationExecutor.migration_plan',
                   return_value=fake):
            response = self.client.get('/healthz')

        self.assertEqual(response.status_code, 503)
        self.assertIn(b'unapplied migration', response.content)
        self.assertIn(b'finance.0002_x', response.content)

        views._SCHEMA_VERIFIED = False           # leave it as we found it

    def test_the_result_is_cached_after_it_passes(self):
        from apps.website import views

        views._SCHEMA_VERIFIED = False
        self.assertEqual(self.client.get('/healthz').status_code, 200)
        self.assertTrue(
            views._SCHEMA_VERIFIED,
            'the migration check should not re-run on every ping',
        )

    def test_uncollected_static_files_fail_the_check(self):
        """
        A build that skipped collectstatic 500s on every page, including the
        error page, because manifest storage raises while rendering the
        template. The health check has to catch it.
        """
        from unittest.mock import patch
        from apps.website import views

        views._STATIC_VERIFIED = False

        class FakeManifestStorage:
            def stored_name(self, name):            # marks it manifest-backed
                raise NotImplementedError

            def url(self, name):
                raise ValueError(f"The file '{name}' could not be found.")

        with patch('django.contrib.staticfiles.storage.staticfiles_storage',
                   FakeManifestStorage()):
            message = views._check_static_files()

        self.assertIsNotNone(message)
        self.assertIn('static files are not collected', message)
        self.assertIn('collectstatic', message)

        views._STATIC_VERIFIED = False

    def test_plain_storage_skips_the_static_check(self):
        """Development uses non-manifest storage, which needs no collectstatic."""
        from apps.website import views

        views._STATIC_VERIFIED = False
        self.assertIsNone(views._check_static_files())
        self.assertTrue(views._STATIC_VERIFIED)
