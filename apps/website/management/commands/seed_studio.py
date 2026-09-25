"""
Populate the studio with realistic demo data.

    python manage.py seed_studio            # add anything missing
    python manage.py seed_studio --demo     # also create sample people & money
    python manage.py seed_studio --flush    # wipe demo rows first

The non-demo pass creates only *reference* data the studio genuinely needs on
day one -- programmes, terms, the skill rubric, fee and expense categories.
It is safe to run against a live database; everything is get_or_create.
"""

from __future__ import annotations

import datetime as dt
import random
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files import File
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.academics.models import (
    AcademicYear,
    AssessmentPeriod,
    AttendanceStatus,
    Attendance,
    ClassSchedule,
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
    SkillScore,
    Studio,
    Term,
)
from apps.academics.services import ensure_report_scores, generate_sessions
from apps.accounts.models import (
    ApprovalStatus,
    GuardianProfile,
    Relationship,
    Role,
    SickleCellStatus,
    StaffProfile,
    Student,
    StudentGuardian,
)
from apps.events.models import (
    Audience,
    Event,
    EventCategory,
    EventStatus,
    Partner,
    PartnerTier,
    Recital,
    RecitalCast,
    RecitalPerformance,
    RecitalRole,
)
from apps.finance.models import (
    Expense,
    ExpenseCategory,
    ExpenseStatus,
    FeeCategory,
    FeeStructure,
    IncomeCategory,
    Invoice,
    InvoiceStatus,
    OtherIncome,
    Payment,
    PaymentMethod,
    TransactionStatus,
)
from apps.website.models import (
    FAQ,
    Announcement,
    AnnouncementAudience,
    AnnouncementLevel,
    GalleryAlbum,
    HeroSlide,
    NewsCategory,
    NewsPost,
    Page,
    PublishStatus,
    SiteSettings,
    Testimonial,
)

User = get_user_model()

FIRST_NAMES = [
    'Amara', 'Nakato', 'Babirye', 'Zuri', 'Aisha', 'Nalubega', 'Esther', 'Grace',
    'Patience', 'Sanyu', 'Aine', 'Kirabo', 'Tendo', 'Nakalema', 'Joy', 'Mercy',
    'Daniel', 'Elijah', 'Mukisa', 'Wasswa', 'Kato', 'Isaac', 'Timothy', 'Emmanuel',
]
LAST_NAMES = [
    'Namutebi', 'Ssentongo', 'Kigozi', 'Nabirye', 'Mugisha', 'Atuhaire', 'Nakimuli',
    'Okello', 'Achieng', 'Byaruhanga', 'Nsubuga', 'Kembabazi', 'Tumwine', 'Lubega',
]


class Command(BaseCommand):
    help = 'Seed Ballet Dance Studio UG with reference data and optional demo content.'

    def add_arguments(self, parser):
        parser.add_argument('--demo', action='store_true',
                            help='Also create sample people, classes, attendance and money.')
        parser.add_argument('--flush', action='store_true',
                            help='Delete existing demo rows before seeding.')
        parser.add_argument('--students', type=int, default=36,
                            help='How many demo dancers to create (default 36).')

    @transaction.atomic
    def handle(self, *args, **options):
        random.seed(20261204)          # stable output between runs
        self.verbosity = options.get('verbosity', 1)

        if options['flush']:
            self._flush()

        self._say('Reference data', self.style.MIGRATE_HEADING)
        self._site_settings()
        year, terms = self._calendar()
        studios = self._studios()
        programmes = self._programmes()
        self._skills(programmes)
        self._finance_catalogue(programmes, terms)
        self._event_categories()
        self._content()

        if options['demo']:
            self._say('Demo content', self.style.MIGRATE_HEADING)
            staff = self._staff()
            classes = self._classes(programmes, terms, studios, staff)
            students = self._students(options['students'])
            self._enrol(students, classes)
            self._attendance(classes)
            self._reports(terms, classes)
            self._money(students, terms)
            self._events_and_recital(classes, students)
            self._announcements()

        self._say('')
        self._say('Studio seeded.', self.style.SUCCESS)
        self._say('  Create a login with:  python manage.py createsuperuser')

    # -- housekeeping ------------------------------------------------------
    def _flush(self):
        self._say('Flushing demo rows...', self.style.WARNING)
        for model in (
            Attendance, ClassSession, SkillScore, ProgressReport, Enrolment,
            ClassSchedule, DanceClass, Payment, Invoice, Expense, OtherIncome,
            RecitalCast, RecitalPerformance, Recital, Event, StudentGuardian,
            Student, GuardianProfile, StaffProfile,
        ):
            model.objects.all().delete()
        User.objects.filter(is_superuser=False).delete()

    def _say(self, message, style=None):
        """Write to the console only when the caller asked for output."""
        if getattr(self, 'verbosity', 1) >= 1:
            self.stdout.write(style(message) if style else message)

    def _log(self, label, created, total=None):
        mark = self.style.SUCCESS('+') if created else self.style.HTTP_INFO('=')
        suffix = f' ({total})' if total is not None else ''
        self._say(f'  {mark} {label}{suffix}')

    # -- reference ---------------------------------------------------------
    def _site_settings(self):
        site = SiteSettings.load()
        if not site.about_short:
            site.studio_name = 'Ballet Dance Studio UG'
            site.short_name = 'BDSU'
            site.tagline = 'Resilience. Hope. Dreams.'
            site.founded_year = 2016
            site.about_short = (
                'We train dancers in the classical tradition — turnout, port de bras, '
                'musicality and the quiet discipline ballet asks for — in a Kampala studio '
                'where every child is known by name.'
            )
            site.about_full = (
                'Ballet Dance Studio UG opened its doors in 2016 with eight children and one '
                'borrowed barre. We now train dancers from age three to adulthood across '
                'several programmes, and every December we stage a full recital in aid of '
                'sickle cell awareness — a cause close to our studio family.'
            )
            site.mission = (
                'To make world-class ballet training available to Ugandan children, and to '
                'use the stage to change how our community understands sickle cell disease.'
            )
            site.vision = (
                'A Uganda where any child who wants to dance can, and where no family faces '
                'sickle cell in silence.'
            )
            site.values = 'Discipline\nJoy\nResilience\nCommunity\nExcellence'
            site.sickle_cell_statement = (
                'Sickle cell disease affects a significant number of Ugandan children. Several '
                'of our own dancers live with it. Our annual recital raises awareness and funds, '
                'and our teachers are trained to plan hydration, rest and safe exertion.'
            )
            site.email = 'info@balletdancestudioug.com'
            site.phone = '+256 700 000 000'
            site.whatsapp = '+256 700 000 000'
            site.address = 'Kampala, Uganda'
            site.opening_hours = 'Mon–Fri: 14:00 – 20:00\nSaturday: 08:00 – 18:00\nSunday: closed'
            site.enrolment_open = True
            site.show_announcement_bar = True
            site.save()
            self._log('Site settings', True)
        else:
            self._log('Site settings', False)

        self._hero_slide(site)

    def _hero_slide(self, site):
        """
        Make sure the home page has something behind the headline.

        The placeholder clip is committed under static/placeholders/ and copied
        into MEDIA_ROOT here, because uploads live outside the repo -- a fresh
        deploy would otherwise come up with an empty hero.
        """
        if not HeroSlide.objects.exists():
            HeroSlide.objects.create(
                kicker=f'Kampala · Since {site.founded_year}',
                headline='Where discipline becomes',
                headline_accent='grace',
                subtext=(
                    'Classical ballet training for every dancer in Uganda — from a '
                    'three-year-old’s first plié to the stage of our annual December recital.'
                ),
                primary_cta_text='Begin your journey',
                primary_cta_url='/enrol/',
                secondary_cta_text='Watch the recital',
                secondary_cta_url='/events/recital/',
                overlay_opacity=Decimal('0.45'),
                is_active=True,
            )
            self._log('Hero slide', True)

        slide = HeroSlide.objects.filter(is_active=True).first()
        if slide and not slide.video and not slide.video_url:
            source = settings.BASE_DIR / 'static' / 'placeholders'
            video = source / 'hero-placeholder.mp4'
            poster = source / 'hero-placeholder.jpg'
            if video.exists():
                with open(video, 'rb') as fh:
                    slide.video.save(video.name, File(fh), save=False)
                if poster.exists():
                    with open(poster, 'rb') as fh:
                        slide.poster_image.save(poster.name, File(fh), save=False)
                # The stock veil is tuned for real footage, which is brighter
                # than this abstract loop.
                slide.overlay_opacity = Decimal('0.30')
                slide.save()
                self._log('Hero placeholder video installed', True)
            else:
                self._log('Hero video missing - add one in the admin', False)

    def _calendar(self):
        this_year = dt.date.today().year
        year, created = AcademicYear.objects.get_or_create(
            name=str(this_year),
            defaults={
                'start_date': dt.date(this_year, 1, 15),
                'end_date': dt.date(this_year, 12, 15),
                'is_current': True,
            },
        )
        self._log(f'Academic year {year.name}', created)

        spec = [
            ('Term 1', dt.date(this_year, 1, 15), dt.date(this_year, 4, 10)),
            ('Term 2', dt.date(this_year, 5, 5), dt.date(this_year, 8, 8)),
            ('Term 3', dt.date(this_year, 9, 1), dt.date(this_year, 12, 12)),
        ]
        terms = []
        today = dt.date.today()
        for name, start, end in spec:
            term, created = Term.objects.get_or_create(
                academic_year=year, name=name,
                defaults={'start_date': start, 'end_date': end,
                          'is_current': start <= today <= end},
            )
            terms.append(term)
            self._log(f'{term}', created)

        if not Term.objects.filter(is_current=True).exists():
            current = terms[-1]
            current.is_current = True
            current.save()

        return year, terms

    def _studios(self):
        spec = [
            ('Studio A', 'Main hall — sprung floor', 24, True),
            ('Studio B', 'Upper studio', 16, False),
            ('Studio C', 'Rehearsal room', 12, False),
        ]
        studios = []
        for name, location, capacity, sprung in spec:
            studio, created = Studio.objects.get_or_create(
                name=name,
                defaults={'location': location, 'capacity': capacity,
                          'has_sprung_floor': sprung},
            )
            studios.append(studio)
            self._log(name, created)
        return studios

    def _programmes(self):
        spec = [
            {
                'name': 'Kinder Ballet', 'min_age': 3, 'max_age': 6,
                'level_label': 'Introductory', 'accent_colour': '#EE2A7B',
                'icon': 'fa-star', 'duration_minutes': 45,
                'tagline': 'Creative movement and a first taste of the barre.',
                'description': (
                    'Our youngest dancers learn through story, song and play. Sessions build '
                    'coordination, listening and confidence, and introduce the first positions '
                    'of classical ballet without ever feeling like a lesson.'
                ),
                'what_you_learn': (
                    'The five positions of the feet\nMusical timing and rhythm\n'
                    'Balance, coordination and spatial awareness\n'
                    'Classroom courtesy — the reverence\nConfidence performing for others'
                ),
            },
            {
                'name': 'Junior Ballet', 'min_age': 7, 'max_age': 11,
                'level_label': 'Foundation', 'accent_colour': '#701344',
                'icon': 'fa-shoe-prints', 'duration_minutes': 60,
                'tagline': 'Proper technique, real strength, genuine musicality.',
                'description': (
                    'The years where technique is built. Dancers work at the barre and in the '
                    'centre, learning turnout, alignment and port de bras, and begin to dance '
                    'full combinations to live counts.'
                ),
                'what_you_learn': (
                    'Barre work: pliés, tendus, ronds de jambe\n'
                    'Correct turnout and alignment\nPort de bras and épaulement\n'
                    'Petit and grand allegro\nFrench ballet vocabulary'
                ),
            },
            {
                'name': 'Senior Ballet', 'min_age': 12, 'max_age': 17,
                'level_label': 'Intermediate & advanced', 'accent_colour': '#c9a84c',
                'icon': 'fa-crown', 'duration_minutes': 90,
                'tagline': 'Pointe work, repertoire and the discipline of a dancer.',
                'description': (
                    'Serious training for dancers who want to go further. Pre-pointe and pointe '
                    'work where readiness allows, classical repertoire, and preparation for '
                    'performance and audition.'
                ),
                'what_you_learn': (
                    'Pre-pointe strengthening and pointe work\nClassical repertoire and variations\n'
                    'Pirouettes and advanced allegro\nPerformance quality and artistry\n'
                    'Injury prevention and conditioning'
                ),
            },
            {
                'name': 'Adult Ballet', 'min_age': 18, 'max_age': None,
                'level_label': 'All levels', 'accent_colour': '#8a1a55',
                'icon': 'fa-heart', 'duration_minutes': 75,
                'tagline': 'Start at any age. Return after any number of years.',
                'description': (
                    'A welcoming, unhurried class for adults — complete beginners and returning '
                    'dancers side by side. Real ballet technique, taught at a pace that respects '
                    'adult bodies and adult lives.'
                ),
                'what_you_learn': (
                    'Full barre at your own level\nPosture, core strength and flexibility\n'
                    'Centre practice and simple combinations\nBallet vocabulary\n'
                    'A genuinely enjoyable hour and a bit'
                ),
            },
            {
                'name': 'Contemporary', 'min_age': 10, 'max_age': None,
                'level_label': 'Open level', 'accent_colour': '#4d0a2e',
                'icon': 'fa-wind', 'duration_minutes': 60,
                'tagline': 'Where classical training meets the floor.',
                'description': (
                    'Release technique, floor work and improvisation for dancers with a ballet '
                    'foundation. Contemporary sharpens musicality and gives dancers a second '
                    'language for the recital stage.'
                ),
                'what_you_learn': (
                    'Release and fall-and-recovery technique\nFloor work and inversions\n'
                    'Improvisation and choreographic tools\nWeight sharing and partnering\n'
                    'Dancing with breath and intention'
                ),
            },
        ]

        programmes = []
        for order, data in enumerate(spec):
            programme, created = Program.objects.get_or_create(
                name=data['name'], defaults={**data, 'display_order': order},
            )
            programmes.append(programme)
            self._log(programme.name, created)
        return programmes

    def _skills(self, programmes):
        rubric = {
            'Technique': ('#701344', 'fa-shoe-prints', [
                ('Turnout', 'Rotation from the hip, held through movement.'),
                ('Alignment & placement', 'Stacked posture, square hips, lifted spine.'),
                ('Port de bras', 'Arm carriage, softness through the elbow and wrist.'),
                ('Footwork', 'Articulation through the foot, pointed toes, clean positions.'),
                ('Balance & control', 'Stability in retiré, arabesque and on relevé.'),
            ]),
            'Musicality': ('#EE2A7B', 'fa-music', [
                ('Timing', 'Dancing on the count, not behind it.'),
                ('Phrasing', 'Shaping movement across the musical line.'),
                ('Dynamics', 'Contrast between sharp and sustained.'),
            ]),
            'Artistry': ('#c9a84c', 'fa-star', [
                ('Performance quality', 'Projection, focus and presence.'),
                ('Expression', 'Face and body telling the same story.'),
                ('Épaulement', 'Use of head and shoulders to give movement dimension.'),
            ]),
            'Physical development': ('#8a1a55', 'fa-dumbbell', [
                ('Strength', 'Core and leg strength appropriate to the level.'),
                ('Flexibility', 'Safe, working range of motion.'),
                ('Stamina', 'Holding technique through a full class.'),
            ]),
            'Discipline & conduct': ('#4d0a2e', 'fa-hands', [
                ('Focus in class', 'Attention held through corrections and repetition.'),
                ('Response to correction', 'Applying what the teacher gives, and keeping it.'),
                ('Studio etiquette', 'Punctuality, uniform, reverence, care for others.'),
                ('Teamwork', 'Working generously with the rest of the class.'),
            ]),
        }

        for order, (name, (colour, icon, skills)) in enumerate(rubric.items()):
            category, created = SkillCategory.objects.get_or_create(
                name=name,
                defaults={'colour': colour, 'icon': icon, 'display_order': order},
            )
            self._log(f'Rubric: {name}', created, len(skills))
            for skill_order, (skill_name, description) in enumerate(skills):
                Skill.objects.get_or_create(
                    category=category, name=skill_name,
                    defaults={'description': description, 'max_score': 5,
                              'display_order': skill_order},
                )

        # Pointe work only makes sense from Senior Ballet upwards.
        senior = next((p for p in programmes if p.name == 'Senior Ballet'), None)
        if senior:
            technique = SkillCategory.objects.get(name='Technique')
            pointe, created = Skill.objects.get_or_create(
                category=technique, name='Pointe work',
                defaults={'description': 'Strength, alignment and safety en pointe.',
                          'max_score': 5, 'display_order': 9},
            )
            if created:
                pointe.programs.add(senior)

    def _finance_catalogue(self, programmes, terms):
        fee_spec = [
            ('Tuition', True, '#EE2A7B'),
            ('Registration', False, '#701344'),
            ('Costume', False, '#c9a84c'),
            ('Recital', False, '#8a1a55'),
            ('Uniform & shoes', False, '#4d0a2e'),
            ('Examination', False, '#6b5a62'),
        ]
        categories = {}
        for order, (name, is_tuition, colour) in enumerate(fee_spec):
            category, created = FeeCategory.objects.get_or_create(
                name=name,
                defaults={'is_tuition': is_tuition, 'colour': colour,
                          'display_order': order},
            )
            categories[name] = category
            self._log(f'Fee category: {name}', created)

        tuition = {
            'Kinder Ballet': 180000, 'Junior Ballet': 240000,
            'Senior Ballet': 320000, 'Adult Ballet': 260000, 'Contemporary': 220000,
        }
        current_term = Term.current()
        for programme in programmes:
            FeeStructure.objects.get_or_create(
                name=f'{programme.name} — term tuition',
                category=categories['Tuition'],
                program=programme,
                term=current_term,
                defaults={'amount': Decimal(tuition.get(programme.name, 200000))},
            )

        FeeStructure.objects.get_or_create(
            name='Registration (one off)', category=categories['Registration'],
            program=None, term=None,
            defaults={'amount': Decimal('50000'), 'billing_cycle': 'one_off'},
        )
        FeeStructure.objects.get_or_create(
            name='Recital costume', category=categories['Costume'],
            program=None, term=None,
            defaults={'amount': Decimal('120000'), 'billing_cycle': 'annual',
                      'is_mandatory': False},
        )

        for order, name in enumerate([
            'Rent', 'Salaries & wages', 'Utilities', 'Costumes & wardrobe',
            'Music & licensing', 'Marketing', 'Equipment & maintenance',
            'Transport', 'Venue hire', 'Administration',
        ]):
            ExpenseCategory.objects.get_or_create(
                name=name,
                defaults={'display_order': order,
                          'is_recurring': name in {'Rent', 'Salaries & wages', 'Utilities'}},
            )

        for order, name in enumerate([
            'Donations', 'Recital tickets', 'Merchandise', 'Sponsorship',
            'Studio hire', 'Workshops',
        ]):
            IncomeCategory.objects.get_or_create(
                name=name, defaults={'display_order': order},
            )
        self._log('Expense & income categories', True)

    def _event_categories(self):
        spec = [
            ('Recital', '#EE2A7B', 'fa-star'),
            ('Workshop', '#701344', 'fa-chalkboard-user'),
            ('Masterclass', '#c9a84c', 'fa-award'),
            ('Open day', '#8a1a55', 'fa-door-open'),
            ('Showcase', '#4d0a2e', 'fa-masks-theater'),
            ('Fundraiser', '#b3261e', 'fa-ribbon'),
            ('Studio holiday', '#6b5a62', 'fa-umbrella-beach'),
        ]
        for order, (name, colour, icon) in enumerate(spec):
            EventCategory.objects.get_or_create(
                name=name,
                defaults={'colour': colour, 'icon': icon, 'display_order': order},
            )
        self._log('Event categories', True, len(spec))

    def _content(self):
        for order, name in enumerate(['Studio news', 'Performances', 'Community',
                                      'Sickle cell awareness', 'Achievements']):
            NewsCategory.objects.get_or_create(name=name, defaults={'display_order': order})

        faqs = [
            ('Enrolment', 'What age can my child start?',
             'Kinder Ballet takes dancers from age three. We place every new dancer by age '
             'and readiness, and the first class is always a trial so you can be sure of the fit.'),
            ('Enrolment', 'Do we need previous experience?',
             'None at all. Most of our dancers start with us, and our Adult Ballet class is '
             'full of complete beginners.'),
            ('Fees', 'How are fees paid?',
             'Fees are invoiced per term. You can pay by cash at the studio, MTN Mobile Money, '
             'Airtel Money, bank deposit or transfer. Every payment gets a receipt, and you can '
             'see your full statement in your parent account.'),
            ('Fees', 'Are there bursaries?',
             'Yes. We hold a small number of bursary places each year, including places '
             'reserved through our sickle cell awareness work. Please contact the office.'),
            ('Uniform', 'What should my child wear?',
             'For the first class, anything they can move in. Once enrolled we will give you '
             'the uniform list for their programme.'),
            ('The recital', 'Does every dancer perform?',
             'Yes. Every enrolled dancer has a place in the December recital, whatever their '
             'level. It is the highlight of our year.'),
        ]
        for order, (category, question, answer) in enumerate(faqs):
            FAQ.objects.get_or_create(
                question=question,
                defaults={'answer': answer, 'category': category, 'display_order': order},
            )
        self._log('FAQs', True, len(faqs))

        pages = [
            ('Privacy Policy', 'privacy-policy',
             '<p>We collect only what we need to teach your child safely and bill you '
             'correctly: contact details, dates of birth, medical information you choose to '
             'share, and a record of attendance, progress and payments.</p>'
             '<p>We never sell your data. Photographs are only used publicly where you have '
             'given consent, and you may withdraw that consent at any time by writing to the '
             'studio office.</p>'),
            ('Terms of Service', 'terms',
             '<p>Fees are invoiced per term and due by the date shown on the invoice. Places '
             'are held for the term once fees are settled.</p>'
             '<p>We ask for a term’s notice before withdrawing a dancer. Classes cancelled by '
             'the studio are rescheduled or credited.</p>'),
            ('Safeguarding', 'safeguarding',
             '<p>The welfare of every child in our studio comes first. All teaching staff are '
             'vetted, classes are observable, and children are released only to adults named '
             'on their record.</p>'
             '<p>Any safeguarding concern should go directly to the Creative Director.</p>'),
        ]
        for order, (title, slug, body) in enumerate(pages):
            Page.objects.get_or_create(
                slug=slug,
                defaults={'title': title, 'body': body, 'show_in_footer': True,
                          'display_order': order},
            )
        self._log('Flat pages', True, len(pages))

    # -- demo --------------------------------------------------------------
    def _staff(self):
        spec = [
            ('Nakato', 'Ssentongo', Role.DIRECTOR, 'Creative Director',
             'Founded the studio in 2016 after training in Nairobi and London.'),
            ('Grace', 'Namutebi', Role.ADMIN, 'Studio Administrator',
             'Runs enrolment, invoicing and the studio office.'),
            ('Aisha', 'Kigozi', Role.TEACHER, 'Ballet Teacher — Junior Division',
             'RAD-trained, teaches Junior Ballet and Contemporary.'),
            ('Daniel', 'Okello', Role.TEACHER, 'Ballet Teacher — Senior Division',
             'Former company dancer; teaches Senior Ballet and pointe.'),
            ('Sanyu', 'Mugisha', Role.TEACHER, 'Kinder Ballet Specialist',
             'Early-years specialist who makes three-year-olds fall in love with ballet.'),
        ]
        staff = []
        for first, last, role, title, bio in spec:
            username = f'{first.lower()}.{last.lower()}'
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    'first_name': first, 'last_name': last,
                    'email': f'{username}@balletdancestudioug.com',
                    'role': role, 'approval_status': ApprovalStatus.APPROVED,
                    'verified_at': timezone.now(),
                    'phone': f'+2567{random.randint(10000000, 99999999)}',
                },
            )
            if created:
                user.set_password('studio2026')
                user.save()
            profile, _ = StaffProfile.objects.get_or_create(
                user=user,
                defaults={
                    'job_title': title, 'short_bio': bio, 'bio': bio,
                    'show_on_website': True, 'website_order': len(staff),
                    'date_joined_studio': dt.date(2016 + len(staff) % 5, 3, 1),
                    'monthly_salary': Decimal(random.choice([900000, 1200000, 1500000, 2200000])),
                    'qualifications': 'RAD Certificate\nFirst aid trained',
                    'specialisms': 'Classical ballet, Contemporary',
                },
            )
            staff.append(profile)
            self._log(f'{user.display_name} — {title}', created)

        self._say('    demo staff password: studio2026', self.style.WARNING)
        return staff

    def _classes(self, programmes, terms, studios, staff):
        term = Term.current() or terms[-1]
        spec = [
            ('Kinder Ballet A', 'Kinder Ballet', 5, [(5, dt.time(9, 0), dt.time(9, 45))], 16),
            ('Kinder Ballet B', 'Kinder Ballet', 5, [(5, dt.time(10, 0), dt.time(10, 45))], 16),
            ('Junior Ballet A', 'Junior Ballet', 2, [(1, dt.time(16, 0), dt.time(17, 0)),
                                                     (3, dt.time(16, 0), dt.time(17, 0))], 20),
            ('Junior Ballet B', 'Junior Ballet', 2, [(5, dt.time(11, 0), dt.time(12, 0))], 20),
            ('Senior Ballet', 'Senior Ballet', 3, [(1, dt.time(17, 30), dt.time(19, 0)),
                                                   (4, dt.time(17, 30), dt.time(19, 0))], 14),
            ('Adult Ballet Evening', 'Adult Ballet', 3, [(2, dt.time(18, 30), dt.time(19, 45))], 18),
            ('Contemporary Open', 'Contemporary', 4, [(4, dt.time(16, 0), dt.time(17, 0))], 18),
        ]

        by_name = {p.name: p for p in programmes}
        classes = []
        for name, programme_name, teacher_index, slots, capacity in spec:
            dance_class, created = DanceClass.objects.get_or_create(
                name=name, term=term,
                defaults={
                    'program': by_name[programme_name],
                    'studio': studios[len(classes) % len(studios)],
                    'capacity': capacity,
                },
            )
            if created:
                dance_class.teachers.add(staff[teacher_index % len(staff)])
                for weekday, start, end in slots:
                    ClassSchedule.objects.create(
                        dance_class=dance_class, weekday=weekday,
                        start_time=start, end_time=end, studio=dance_class.studio,
                    )
                # Only build sessions up to today, so registers look realistic.
                generate_sessions(
                    dance_class,
                    start=term.start_date,
                    end=min(term.end_date, dt.date.today() + dt.timedelta(days=21)),
                )
            classes.append(dance_class)
            self._log(f'{name} ({dance_class.sessions.count()} sessions)', created)
        return classes

    def _students(self, count):
        existing = Student.objects.count()
        if existing >= count:
            self._log('Dancers', False, existing)
            return list(Student.objects.all())

        today = dt.date.today()
        students = []
        for i in range(count - existing):
            first = random.choice(FIRST_NAMES)
            last = random.choice(LAST_NAMES)
            age = random.choices(
                [4, 5, 6, 8, 9, 10, 11, 13, 14, 15, 22, 30],
                weights=[8, 9, 8, 10, 10, 9, 8, 6, 5, 4, 3, 3],
            )[0]
            born = today.replace(year=today.year - age) - dt.timedelta(days=random.randint(0, 364))

            student = Student.objects.create(
                first_name=first, last_name=last,
                date_of_birth=born,
                gender=random.choice(['F', 'F', 'F', 'M']),
                enrolment_date=today - dt.timedelta(days=random.randint(30, 900)),
                school_name=random.choice([
                    'Kampala Parents School', 'Greenhill Academy',
                    'Kabojja Junior School', 'Nakasero Primary', '',
                ]),
                # A realistic minority disclose a sickle cell status.
                sickle_cell_status=random.choices(
                    [SickleCellStatus.UNDISCLOSED, SickleCellStatus.NEGATIVE,
                     SickleCellStatus.TRAIT, SickleCellStatus.DISEASE],
                    weights=[62, 24, 10, 4],
                )[0],
                photo_consent=random.random() > 0.15,
                media_consent=random.random() > 0.3,
                medical_treatment_consent=True,
            )

            # Roughly one guardian account per family; siblings share one.
            guardian_first = random.choice(FIRST_NAMES)
            username = f'parent.{guardian_first.lower()}.{last.lower()}{i}'
            guardian_user = User.objects.create(
                username=username,
                email=f'{username}@example.com',
                first_name=guardian_first, last_name=last,
                role=Role.PARENT,
                approval_status=ApprovalStatus.APPROVED if random.random() > 0.12
                                else ApprovalStatus.PENDING,
                verified_at=timezone.now(),
                phone=f'+2567{random.randint(10000000, 99999999)}',
            )
            guardian_user.set_password('studio2026')
            guardian_user.save()

            guardian = GuardianProfile.objects.create(
                user=guardian_user,
                occupation=random.choice(['Teacher', 'Nurse', 'Engineer', 'Trader',
                                          'Accountant', 'Civil servant', '']),
            )
            StudentGuardian.objects.create(
                student=student, guardian=guardian,
                relationship=random.choice([Relationship.MOTHER, Relationship.FATHER,
                                            Relationship.GUARDIAN]),
                is_primary=True,
            )
            students.append(student)

        self._log('Dancers (with guardian accounts)', True, Student.objects.count())
        return list(Student.objects.all())

    def _enrol(self, students, classes):
        if Enrolment.objects.exists():
            self._log('Enrolments', False, Enrolment.objects.count())
            return

        by_programme = {}
        for dance_class in classes:
            by_programme.setdefault(dance_class.program.name, []).append(dance_class)

        def pick(age):
            if age <= 6:
                return by_programme.get('Kinder Ballet', [])
            if age <= 11:
                return by_programme.get('Junior Ballet', [])
            if age <= 17:
                return by_programme.get('Senior Ballet', [])
            return by_programme.get('Adult Ballet', [])

        for student in students:
            options = pick(student.age)
            if not options:
                continue
            dance_class = random.choice(options)
            if dance_class.enrolled_count >= dance_class.capacity:
                continue
            Enrolment.objects.get_or_create(
                student=student, dance_class=dance_class,
                defaults={'date_enrolled': student.enrolment_date,
                          'status': EnrolmentStatus.ACTIVE},
            )
            # A few older dancers also take Contemporary.
            if student.age >= 10 and random.random() > 0.75:
                extra = by_programme.get('Contemporary', [])
                if extra and extra[0].enrolled_count < extra[0].capacity:
                    Enrolment.objects.get_or_create(
                        student=student, dance_class=extra[0],
                        defaults={'status': EnrolmentStatus.ACTIVE},
                    )

        self._log('Enrolments', True, Enrolment.objects.count())

    def _attendance(self, classes):
        if Attendance.objects.exists():
            self._log('Attendance marks', False, Attendance.objects.count())
            return

        today = dt.date.today()
        marks = 0
        for session in ClassSession.objects.filter(date__lte=today).select_related('dance_class'):
            students = list(session.expected_students)
            if not students:
                continue
            rows = []
            for student in students:
                status = random.choices(
                    [AttendanceStatus.PRESENT, AttendanceStatus.LATE,
                     AttendanceStatus.EXCUSED, AttendanceStatus.ABSENT],
                    weights=[82, 8, 5, 5],
                )[0]
                rows.append(Attendance(
                    session=session, student=student, status=status,
                    minutes_late=random.randint(4, 20)
                    if status == AttendanceStatus.LATE else None,
                ))
            Attendance.objects.bulk_create(rows, ignore_conflicts=True)
            marks += len(rows)
            session.register_taken = True
            session.register_taken_at = timezone.now()
            session.status = SessionStatus.HELD
            session.save(update_fields=['register_taken', 'register_taken_at', 'status'])

        self._log('Attendance marks', True, marks)

    def _reports(self, terms, classes):
        if ProgressReport.objects.exists():
            self._log('Progress reports', False, ProgressReport.objects.count())
            return

        term = Term.current() or terms[-1]
        period, _ = AssessmentPeriod.objects.get_or_create(
            term=term, name=f'End of {term.name}',
            defaults={
                'opens_on': max(term.start_date, dt.date.today() - dt.timedelta(days=21)),
                'closes_on': min(term.end_date, dt.date.today() + dt.timedelta(days=14)),
                'instructions': (
                    'Score each skill 1–5 against what you would expect of this dancer at '
                    'this stage, not against the class. Write to the family, not to a file.'
                ),
            },
        )

        made = 0
        for dance_class in classes:
            teacher = dance_class.teachers.first()
            for enrolment in dance_class.enrolments.filter(
                status=EnrolmentStatus.ACTIVE,
            ).select_related('student')[:12]:
                report, created = ProgressReport.objects.get_or_create(
                    student=enrolment.student, dance_class=dance_class, period=period,
                    defaults={
                        'teacher': teacher,
                        'strengths': random.choice([
                            'Beautiful port de bras and a genuine musical instinct.',
                            'Works with real focus and takes every correction seriously.',
                            'Strong, clean footwork and a lovely stage presence.',
                            'Has grown enormously in confidence this term.',
                        ]),
                        'areas_to_develop': random.choice([
                            'Holding turnout through the whole of an adage.',
                            'Spotting cleanly in pirouettes.',
                            'Keeping the shoulders down in grand allegro.',
                            'Building stamina to hold technique to the end of class.',
                        ]),
                        'teacher_comment': (
                            'A pleasure to teach this term. Steady, visible progress and a '
                            'lovely attitude in the studio.'
                        ),
                        'recommendation': random.choice([
                            'Ready to continue at this level next term.',
                            'Ready to move up next term.',
                            'Would benefit from a second class each week.',
                        ]),
                    },
                )
                if not created:
                    continue

                for score in ensure_report_scores(report):
                    score.score = random.choices([2, 3, 4, 5], weights=[8, 30, 42, 20])[0]
                    score.save(update_fields=['score'])

                if random.random() > 0.35:
                    report.publish()
                else:
                    report.submit()
                made += 1

        self._log(f'Progress reports ({period.name})', True, made)

    def _money(self, students, terms):
        if Invoice.objects.exists():
            self._log('Invoices & payments', False, Invoice.objects.count())
            return

        term = Term.current() or terms[-1]
        admin = User.objects.filter(role__in=[Role.ADMIN, Role.DIRECTOR]).first()
        tuition_category = FeeCategory.objects.filter(is_tuition=True).first()
        today = dt.date.today()

        invoices = 0
        payments = 0
        for student in students:
            enrolment = student.enrolments.filter(status=EnrolmentStatus.ACTIVE).first()
            if not enrolment:
                continue

            fee = FeeStructure.objects.filter(
                program=enrolment.dance_class.program, term=term,
            ).first()
            amount = fee.amount if fee else Decimal('200000')

            invoice = Invoice.objects.create(
                student=student, term=term,
                issue_date=term.start_date,
                due_date=term.start_date + dt.timedelta(days=21),
                status=InvoiceStatus.ISSUED,
                issued_by=admin,
            )
            invoice.items.create(
                fee_category=tuition_category, fee_structure=fee,
                description=f'{enrolment.dance_class.program.name} — {term}',
                quantity=1, unit_amount=amount,
            )
            invoice.recalculate()
            invoices += 1

            # Most families pay; some pay in part; a few have not paid at all.
            roll = random.random()
            if roll < 0.62:
                portions = [invoice.total_amount]
            elif roll < 0.85:
                half = (invoice.total_amount / 2).quantize(Decimal('1'))
                portions = [half]
            else:
                portions = []

            for portion in portions:
                method = random.choices(
                    [PaymentMethod.MTN_MOMO, PaymentMethod.AIRTEL_MONEY,
                     PaymentMethod.CASH, PaymentMethod.BANK_DEPOSIT,
                     PaymentMethod.BANK_TRANSFER],
                    weights=[42, 20, 20, 10, 8],
                )[0]
                paid_on = term.start_date + dt.timedelta(days=random.randint(1, 45))
                if paid_on > today:
                    paid_on = today - dt.timedelta(days=random.randint(0, 10))

                Payment.objects.create(
                    invoice=invoice, student=student, amount=portion,
                    payment_date=paid_on,
                    payment_time=dt.time(random.randint(8, 19), random.choice([0, 15, 30, 45])),
                    method=method,
                    transaction_id=(
                        '' if method == PaymentMethod.CASH
                        else f'{method[:2].upper()}{paid_on:%y%m%d}.{random.randint(1000, 9999)}.'
                             f'{random.choice("ABCDEFGH")}{random.randint(10000, 99999)}'
                    ),
                    payer_name=student.primary_guardian.user.display_name
                               if student.primary_guardian else '',
                    received_by=admin, recorded_by=admin,
                    status=TransactionStatus.CONFIRMED,
                )
                payments += 1

        self._log('Invoices', True, invoices)
        self._log('Payments', True, payments)

        # Twelve months of running costs, so the annual report has shape.
        categories = list(ExpenseCategory.objects.all())
        recurring = {
            'Rent': 1800000, 'Salaries & wages': 5400000, 'Utilities': 420000,
        }
        expenses = 0
        for months_ago in range(11, -1, -1):
            anchor = (today.replace(day=1) - dt.timedelta(days=months_ago * 30)).replace(day=1)
            if anchor > today:
                continue
            for name, base in recurring.items():
                category = ExpenseCategory.objects.filter(name=name).first()
                if not category:
                    continue
                Expense.objects.create(
                    category=category,
                    description=f'{name} — {anchor:%B %Y}',
                    amount=Decimal(base + random.randint(-90000, 140000)),
                    expense_date=min(anchor + dt.timedelta(days=random.randint(1, 5)), today),
                    expense_time=dt.time(random.randint(9, 16), 0),
                    method=random.choice([PaymentMethod.BANK_TRANSFER, PaymentMethod.MTN_MOMO]),
                    transaction_id=f'EXP{anchor:%y%m}{random.randint(1000, 9999)}',
                    payee_name=random.choice(['Kampala Properties Ltd', 'Studio staff',
                                              'UMEME', 'NWSC']),
                    status=ExpenseStatus.PAID, recorded_by=admin,
                )
                expenses += 1

            for _ in range(random.randint(2, 5)):
                category = random.choice(categories)
                Expense.objects.create(
                    category=category,
                    description=f'{category.name} — {anchor:%b %Y}',
                    amount=Decimal(random.randint(60000, 900000)),
                    expense_date=min(anchor + dt.timedelta(days=random.randint(1, 27)), today),
                    method=random.choice([PaymentMethod.CASH, PaymentMethod.MTN_MOMO]),
                    transaction_id=f'EXP{anchor:%y%m}{random.randint(1000, 9999)}',
                    status=ExpenseStatus.PAID, recorded_by=admin,
                )
                expenses += 1

        self._log('Expenses (12 months)', True, expenses)

        donations = IncomeCategory.objects.filter(name='Donations').first()
        if donations:
            for _ in range(9):
                OtherIncome.objects.create(
                    category=donations,
                    description='Sickle cell awareness donation',
                    amount=Decimal(random.randint(100000, 2500000)),
                    received_date=today - dt.timedelta(days=random.randint(1, 300)),
                    method=random.choice([PaymentMethod.MTN_MOMO, PaymentMethod.BANK_TRANSFER]),
                    transaction_id=f'DON{random.randint(100000, 999999)}',
                    source_name=random.choice(['Anonymous', 'Kampala Rotary Club',
                                               'Family friend', 'Corporate donor']),
                    recorded_by=admin,
                )
            self._log('Donations', True, 9)

    def _events_and_recital(self, classes, students):
        today = dt.date.today()
        year = today.year if today.month < 12 else today.year + 1

        recital_category = EventCategory.objects.filter(name='Recital').first()
        # The studio always performs in the first week of December.
        performance_date = dt.date(year, 12, 6)

        event, _ = Event.objects.get_or_create(
            title=f'{year} Annual Recital',
            defaults={
                'category': recital_category,
                'summary': 'Our annual recital, danced for sickle cell awareness.',
                'description': 'Every dancer in the studio performs. Tickets at the office.',
                'start_at': timezone.make_aware(
                    dt.datetime.combine(performance_date, dt.time(18, 0))),
                'end_at': timezone.make_aware(
                    dt.datetime.combine(performance_date, dt.time(20, 30))),
                'venue_name': 'National Theatre, Kampala',
                'status': EventStatus.SCHEDULED, 'audience': Audience.PUBLIC,
                'is_featured': True, 'ticket_price': Decimal('40000'),
            },
        )

        recital, created = Recital.objects.get_or_create(
            year=year,
            defaults={
                'title': 'Hope in Motion',
                'theme': 'Dancing for sickle cell awareness',
                'tagline': 'Resilience. Hope. Dreams.',
                'event': event,
                'performance_date': performance_date,
                'doors_open_time': dt.time(17, 15),
                'start_time': dt.time(18, 0),
                'venue_name': 'National Theatre, Kampala',
                'venue_address': 'De Winton Road, Kampala',
                'introduction': (
                    'Once a year, every dancer in our studio steps onto a real stage. '
                    'Hope in Motion is our December recital — and it is danced for a reason.'
                ),
                'description': (
                    'From the youngest Kinder Ballet dancer to our senior soloists, every '
                    'dancer in the studio performs. The evening moves from classical repertoire '
                    'through contemporary work to a full-company finale.'
                ),
                'sickle_cell_message': (
                    'Sickle cell disease affects thousands of Ugandan children, and several of '
                    'our own dancers live with it. We dance to say plainly what many families '
                    'are told to keep quiet: this condition is common, it is manageable, and it '
                    'is nothing to hide. Proceeds support sickle cell testing and family '
                    'support in our community.'
                ),
                'director_note': (
                    'Watching a child who was too shy to stand at the barre in January take a '
                    'bow in December is why this studio exists. — Nakato Ssentongo'
                ),
                'ticket_price_regular': Decimal('40000'),
                'ticket_price_vip': Decimal('100000'),
                'ticket_price_child': Decimal('20000'),
                'ticket_info': (
                    'Tickets are sold at the studio office and at the door. Cash, MTN Mobile '
                    'Money and Airtel Money accepted.'
                ),
                'fundraising_goal': Decimal('15000000'),
                'beneficiary': 'Uganda Sickle Cell Rescue Foundation',
                'is_published': True, 'is_current': True,
            },
        )

        if created:
            pieces = [
                ('Act I', 'Waltz of the Flowers', 'Tchaikovsky', 'Junior Ballet A'),
                ('Act I', 'First Steps', 'Saint-Saëns', 'Kinder Ballet A'),
                ('Act I', 'Little Swans', 'Tchaikovsky', 'Kinder Ballet B'),
                ('Act II', 'Paquita — Variations', 'Minkus', 'Senior Ballet'),
                ('Act II', 'Breath', 'Ólafur Arnalds', 'Contemporary Open'),
                ('Act II', 'Grown', 'Nina Simone', 'Adult Ballet Evening'),
                ('Finale', 'Hope in Motion — full company', 'Original score', None),
            ]
            by_name = {c.name: c for c in classes}
            for order, (act, title, music, class_name) in enumerate(pieces, start=1):
                performance = RecitalPerformance.objects.create(
                    recital=recital, order=order, act=act, title=title,
                    music=music, choreographer='Nakato Ssentongo',
                    dance_class=by_name.get(class_name),
                    duration_minutes=random.randint(4, 12),
                )
                pool = (
                    list(performance.dance_class.enrolments.filter(
                        status=EnrolmentStatus.ACTIVE).values_list('student', flat=True))
                    if performance.dance_class else
                    [s.pk for s in random.sample(students, min(18, len(students)))]
                )
                for i, student_id in enumerate(pool[:20]):
                    RecitalCast.objects.get_or_create(
                        performance=performance, student_id=student_id,
                        defaults={'role_type': RecitalRole.PRINCIPAL if i == 0
                                  else RecitalRole.SOLOIST if i < 3
                                  else RecitalRole.ENSEMBLE},
                    )
            self._log(f'{recital.title} ({year}) with cast', True)

        Partner.objects.get_or_create(
            name='Uganda Sickle Cell Rescue Foundation',
            defaults={'tier': PartnerTier.HEADLINE, 'is_sickle_cell_partner': True,
                      'description': 'Our partner in sickle cell testing and family support.'},
        )

        # A handful of other dates on the calendar.
        others = [
            ('Open Day — meet the studio', 'Open day', 30, 'Studio A, Kampala'),
            ('Contemporary Masterclass', 'Masterclass', 52, 'Studio A, Kampala'),
            ('End of Term Showcase', 'Showcase', 74, 'Studio A, Kampala'),
            ('Sickle Cell Awareness Walk', 'Fundraiser', 96, 'Kololo Independence Grounds'),
        ]
        for title, category_name, offset, venue in others:
            start = timezone.now() + dt.timedelta(days=offset)
            Event.objects.get_or_create(
                title=title,
                defaults={
                    'category': EventCategory.objects.filter(name=category_name).first(),
                    'summary': f'{title} at {venue}.',
                    'start_at': start.replace(hour=10, minute=0, second=0, microsecond=0),
                    'end_at': start.replace(hour=13, minute=0, second=0, microsecond=0),
                    'venue_name': venue,
                    'status': EventStatus.SCHEDULED, 'audience': Audience.PUBLIC,
                },
            )
        self._log('Calendar events', True, len(others) + 1)

    def _announcements(self):
        if Announcement.objects.exists():
            return
        Announcement.objects.create(
            title='Term enrolment is open',
            message='Places are filling for Kinder and Junior Ballet. Book a trial class.',
            level=AnnouncementLevel.IMPORTANT,
            audience=AnnouncementAudience.PUBLIC,
            link_text='Enrol now', link_url='/enrol/',
            show_in_bar=True, is_pinned=True,
        )
        Announcement.objects.create(
            title='Recital costume measurements',
            message='Please bring your dancer to the office before the end of the month '
                    'for costume measurements.',
            level=AnnouncementLevel.INFO,
            audience=AnnouncementAudience.PARENTS,
        )
        self._log('Announcements', True, 2)

        news_category = NewsCategory.objects.filter(name='Studio news').first()
        author = User.objects.filter(role=Role.DIRECTOR).first()
        stories = [
            ('Enrolment is open for the new term',
             'Places are filling quickly across Kinder and Junior Ballet.',
             '<p>We have opened enrolment for the coming term. Kinder Ballet and Junior Ballet '
             'fill first, so if your dancer has a place in mind, do book a trial class early.</p>'
             '<p>Every new dancer starts with a trial so both of you can be sure of the fit. '
             'There is no obligation and no charge for the first class.</p>'),
            ('Why we dance for sickle cell awareness',
             'Our December recital is more than a performance.',
             '<p>Every year our recital raises awareness and funds for sickle cell disease. '
             'Several of our own dancers live with the condition, and their families have taught '
             'us how much silence still surrounds it.</p>'
             '<p>This year we are again partnering with the Uganda Sickle Cell Rescue Foundation. '
             'Proceeds support testing and family support in our community.</p>'),
            ('Our dancers on the National Theatre stage',
             'A look back at last December.',
             '<p>Forty dancers, seven pieces and a full house. Thank you to every family who '
             'made it possible.</p>'),
        ]
        for title, excerpt, body in stories:
            NewsPost.objects.get_or_create(
                title=title,
                defaults={
                    'category': news_category, 'excerpt': excerpt, 'body': body,
                    'author': author, 'status': PublishStatus.PUBLISHED,
                    'published_at': timezone.now() - dt.timedelta(days=random.randint(2, 60)),
                    'is_featured': True,
                },
            )
        self._log('News posts', True, len(stories))

        quotes = [
            ('Sarah Nakimuli', 'Parent of a Junior Ballet dancer',
             'My daughter walked in shy and walked out three terms later standing taller than '
             'I have ever seen her. The teachers know every child by name.'),
            ('Robert Byaruhanga', 'Parent of two dancers',
             'The reports we get each term are genuinely useful — not just marks, but what she '
             'is working on and what comes next. And the fees statement is always clear.'),
            ('Patience Aine', 'Adult Ballet student',
             'I started at thirty-one having never danced. Nobody made me feel late to it.'),
        ]
        for order, (name, role, quote) in enumerate(quotes):
            Testimonial.objects.get_or_create(
                name=name,
                defaults={'role': role, 'quote': quote, 'rating': 5,
                          'is_published': True, 'display_order': order},
            )
        self._log('Testimonials', True, len(quotes))

        GalleryAlbum.objects.get_or_create(
            title='Studio life',
            defaults={'description': 'Everyday moments from the barre.',
                      'date': dt.date.today(), 'is_public': True, 'is_featured': True},
        )
