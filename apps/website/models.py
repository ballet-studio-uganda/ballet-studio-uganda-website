"""
Public-facing content, all of it editable by an administrator.

Nothing on the public site is hard-coded into a template: the hero video, the
news, the announcement bar, the galleries, the testimonials and the contact
details all come from here so the studio can run its own site.
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import TimeStampedModel


# ---------------------------------------------------------------------------
# Choices
# ---------------------------------------------------------------------------
class PublishStatus(models.TextChoices):
    DRAFT = 'draft', _('Draft')
    PUBLISHED = 'published', _('Published')
    ARCHIVED = 'archived', _('Archived')


class AnnouncementLevel(models.TextChoices):
    INFO = 'info', _('Information')
    IMPORTANT = 'important', _('Important')
    URGENT = 'urgent', _('Urgent')
    CELEBRATION = 'celebration', _('Celebration')


class AnnouncementAudience(models.TextChoices):
    PUBLIC = 'public', _('Public website')
    ALL_USERS = 'all_users', _('All signed-in users')
    PARENTS = 'parents', _('Parents / guardians')
    STUDENTS = 'students', _('Students')
    STAFF = 'staff', _('Staff only')


# ---------------------------------------------------------------------------
# Site-wide settings
# ---------------------------------------------------------------------------
class SiteSettings(models.Model):
    """
    Singleton holding the studio's identity and contact details.

    Loaded into every template by ``apps.website.context_processors``.
    """

    studio_name = models.CharField(max_length=140, default='Ballet Dance Studio UG')
    short_name = models.CharField(max_length=60, default='BDSU')
    tagline = models.CharField(max_length=160, default='Resilience. Hope. Dreams.')
    founded_year = models.PositiveSmallIntegerField(default=2016)

    logo = models.ImageField(upload_to='site/', blank=True)
    logo_light = models.ImageField(
        upload_to='site/', blank=True, help_text=_('Version for use on dark backgrounds.'),
    )
    favicon = models.ImageField(upload_to='site/', blank=True)
    og_image = models.ImageField(
        upload_to='site/', blank=True, help_text=_('Preview image used when links are shared.'),
    )

    # Story
    about_short = models.TextField(blank=True, help_text=_('Two or three sentences for the home page.'))
    about_full = models.TextField(blank=True)
    mission = models.TextField(blank=True)
    vision = models.TextField(blank=True)
    values = models.TextField(blank=True, help_text=_('One value per line.'))
    sickle_cell_statement = models.TextField(
        blank=True, help_text=_('The studio’s standing message on sickle cell awareness.'),
    )

    # Contact
    email = models.EmailField(blank=True, default='info@balletdancestudioug.com')
    phone = models.CharField(max_length=40, blank=True)
    whatsapp = models.CharField(max_length=40, blank=True)
    address = models.CharField(max_length=255, blank=True, default='Kampala, Uganda')
    map_embed_url = models.URLField(blank=True)
    opening_hours = models.TextField(blank=True, help_text=_('One line per day or range.'))

    # Social
    facebook_url = models.URLField(blank=True)
    instagram_url = models.URLField(blank=True)
    youtube_url = models.URLField(blank=True)
    tiktok_url = models.URLField(blank=True)
    twitter_url = models.URLField(blank=True)
    linkedin_url = models.URLField(blank=True)

    # Behaviour
    enrolment_open = models.BooleanField(default=True)
    show_announcement_bar = models.BooleanField(default=True)
    maintenance_mode = models.BooleanField(default=False)
    google_analytics_id = models.CharField(max_length=40, blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('site settings')
        verbose_name_plural = _('site settings')

    def __str__(self):
        return self.studio_name

    def save(self, *args, **kwargs):
        self.pk = 1          # enforce the singleton
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(_('Site settings cannot be deleted.'))

    @classmethod
    def load(cls):
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def value_list(self):
        return [line.strip() for line in self.values.splitlines() if line.strip()]

    @property
    def opening_hours_list(self):
        return [line.strip() for line in self.opening_hours.splitlines() if line.strip()]

    @property
    def social_links(self):
        """``[(icon_class, url), ...]`` for whichever networks are filled in."""
        candidates = [
            ('fab fa-facebook-f', self.facebook_url),
            ('fab fa-instagram', self.instagram_url),
            ('fab fa-youtube', self.youtube_url),
            ('fab fa-tiktok', self.tiktok_url),
            ('fab fa-x-twitter', self.twitter_url),
            ('fab fa-linkedin-in', self.linkedin_url),
        ]
        return [(icon, url) for icon, url in candidates if url]


class HeroSlide(TimeStampedModel):
    """
    The video hero directly beneath the navigation, with animated text over it.

    Multiple active slides rotate; a single one simply plays. Either upload a
    video file or point at a hosted URL.
    """

    headline = models.CharField(
        max_length=120, help_text=_('The large animated line, e.g. "Where dreams take flight".'),
    )
    headline_accent = models.CharField(
        max_length=80, blank=True,
        help_text=_('Optional trailing words shown in the brand pink.'),
    )
    kicker = models.CharField(
        max_length=90, blank=True,
        help_text=_('Small uppercase line above the headline.'),
    )
    subtext = models.CharField(max_length=250, blank=True)

    video = models.FileField(
        upload_to='site/hero/', blank=True,
        help_text=_('MP4, muted, roughly 10-25 seconds and under 15 MB for fast loading.'),
    )
    video_url = models.URLField(
        blank=True, help_text=_('Use instead of an upload if the video is hosted elsewhere.'),
    )
    poster_image = models.ImageField(
        upload_to='site/hero/', blank=True,
        help_text=_('Shown while the video loads, and on slow connections.'),
    )
    overlay_opacity = models.DecimalField(
        max_digits=3, decimal_places=2, default=0.45,
        help_text=_('0 = no darkening, 1 = black. 0.45 keeps text readable over most footage.'),
    )

    primary_cta_text = models.CharField(max_length=40, blank=True, default='Begin your journey')
    primary_cta_url = models.CharField(max_length=250, blank=True)
    secondary_cta_text = models.CharField(max_length=40, blank=True, default='Watch the recital')
    secondary_cta_url = models.CharField(max_length=250, blank=True)

    is_active = models.BooleanField(default=True)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = _('hero slide')
        ordering = ('display_order', '-created_at')

    def __str__(self):
        return self.headline

    def clean(self):
        if not self.video and not self.video_url and not self.poster_image:
            raise ValidationError(
                _('Provide a video file, a video URL, or at least a poster image.')
            )

    @property
    def media_url(self):
        if self.video:
            return self.video.url
        return self.video_url

    @property
    def has_video(self):
        return bool(self.video or self.video_url)


# ---------------------------------------------------------------------------
# News and announcements
# ---------------------------------------------------------------------------
class NewsCategory(models.Model):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=100, unique=True, blank=True)
    description = models.TextField(blank=True)
    colour = models.CharField(max_length=7, default='#701344')
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = _('news category')
        verbose_name_plural = _('news categories')
        ordering = ('display_order', 'name')

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)[:100]
        super().save(*args, **kwargs)


class NewsQuerySet(models.QuerySet):
    def published(self):
        return self.filter(
            status=PublishStatus.PUBLISHED, published_at__lte=timezone.now(),
        )

    def featured(self):
        return self.published().filter(is_featured=True)


class NewsPost(TimeStampedModel):
    """A news story or blog article."""

    title = models.CharField(max_length=220)
    slug = models.SlugField(max_length=240, unique=True, blank=True)
    category = models.ForeignKey(
        NewsCategory, null=True, blank=True, on_delete=models.SET_NULL, related_name='posts',
    )

    excerpt = models.TextField(
        max_length=400, blank=True, help_text=_('Shown on cards and in search results.'),
    )
    body = models.TextField(help_text=_('Supports basic HTML.'))

    cover_image = models.ImageField(upload_to='news/%Y/%m/', blank=True)
    cover_caption = models.CharField(max_length=200, blank=True)

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='news_posts',
    )
    status = models.CharField(
        max_length=20, choices=PublishStatus.choices, default=PublishStatus.DRAFT, db_index=True,
    )
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)
    is_featured = models.BooleanField(default=False)
    is_pinned = models.BooleanField(default=False)

    tags = models.CharField(max_length=250, blank=True, help_text=_('Comma separated.'))
    related_event = models.ForeignKey(
        'events.Event', null=True, blank=True, on_delete=models.SET_NULL, related_name='news_posts',
    )

    view_count = models.PositiveIntegerField(default=0, editable=False)
    reading_minutes = models.PositiveSmallIntegerField(default=1, editable=False)

    meta_description = models.CharField(max_length=200, blank=True)

    objects = NewsQuerySet.as_manager()

    class Meta:
        verbose_name = _('news post')
        ordering = ('-is_pinned', '-published_at', '-created_at')
        indexes = [models.Index(fields=('status', 'published_at'))]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('website:news_detail', args=[self.slug])

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title)[:230]
            slug, n = base, 2
            while NewsPost.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base}-{n}'
                n += 1
            self.slug = slug
        if self.status == PublishStatus.PUBLISHED and not self.published_at:
            self.published_at = timezone.now()
        words = len(self.body.split())
        self.reading_minutes = max(1, round(words / 200))
        super().save(*args, **kwargs)

    @property
    def tag_list(self):
        return [t.strip() for t in self.tags.split(',') if t.strip()]

    @property
    def is_published(self):
        return (
            self.status == PublishStatus.PUBLISHED
            and self.published_at is not None
            and self.published_at <= timezone.now()
        )


class Announcement(TimeStampedModel):
    """
    A short, time-boxed notice -- the bar across the top of the public site and
    the notice board inside the dashboards.
    """

    title = models.CharField(max_length=180)
    message = models.TextField()
    level = models.CharField(
        max_length=20, choices=AnnouncementLevel.choices, default=AnnouncementLevel.INFO,
    )
    audience = models.CharField(
        max_length=20, choices=AnnouncementAudience.choices,
        default=AnnouncementAudience.PUBLIC, db_index=True,
    )

    link_text = models.CharField(max_length=60, blank=True)
    link_url = models.CharField(max_length=250, blank=True)
    icon = models.CharField(max_length=60, blank=True, default='fa-bullhorn')

    starts_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField(
        null=True, blank=True, help_text=_('Leave empty to show until switched off.'),
    )
    is_active = models.BooleanField(default=True, db_index=True)
    is_pinned = models.BooleanField(default=False)
    show_in_bar = models.BooleanField(
        default=False, help_text=_('Also show in the sticky bar at the top of the public site.'),
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='announcements',
    )

    class Meta:
        ordering = ('-is_pinned', '-starts_at')
        indexes = [models.Index(fields=('is_active', 'audience'))]

    def __str__(self):
        return self.title

    @property
    def is_live(self):
        now = timezone.now()
        return (
            self.is_active
            and self.starts_at <= now
            and (self.ends_at is None or self.ends_at >= now)
        )

    @classmethod
    def live_for(cls, user):
        """Announcements currently visible to *user* (or the public if anonymous)."""
        now = timezone.now()
        qs = cls.objects.filter(is_active=True, starts_at__lte=now).filter(
            models.Q(ends_at__isnull=True) | models.Q(ends_at__gte=now)
        )
        if not getattr(user, 'is_authenticated', False):
            return qs.filter(audience=AnnouncementAudience.PUBLIC)

        allowed = [AnnouncementAudience.PUBLIC, AnnouncementAudience.ALL_USERS]
        if user.is_studio_staff:
            allowed.append(AnnouncementAudience.STAFF)
        if user.is_guardian:
            allowed.append(AnnouncementAudience.PARENTS)
        if user.is_student:
            allowed.append(AnnouncementAudience.STUDENTS)
        return qs.filter(audience__in=allowed)


# ---------------------------------------------------------------------------
# Gallery
# ---------------------------------------------------------------------------
class GalleryAlbum(TimeStampedModel):
    """A set of photographs, usually from one event."""

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    description = models.TextField(blank=True)
    cover_image = models.ImageField(
        upload_to='gallery/covers/', blank=True,
        help_text=_('Falls back to the first photo in the album.'),
    )

    event = models.ForeignKey(
        'events.Event', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='albums',
    )
    date = models.DateField(null=True, blank=True, help_text=_('When the photos were taken.'))
    photographer = models.CharField(max_length=140, blank=True)

    is_public = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    display_order = models.PositiveSmallIntegerField(default=0)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='albums_created',
    )

    class Meta:
        verbose_name = _('gallery album')
        ordering = ('display_order', '-date', '-created_at')

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('website:album_detail', args=[self.slug])

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title)[:210]
            slug, n = base, 2
            while GalleryAlbum.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base}-{n}'
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def cover(self):
        if self.cover_image:
            return self.cover_image
        first = self.images.first()
        return first.image if first else None

    @property
    def image_count(self):
        return self.images.count()


class GalleryImage(models.Model):
    album = models.ForeignKey(GalleryAlbum, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='gallery/%Y/%m/')
    caption = models.CharField(max_length=250, blank=True)
    alt_text = models.CharField(
        max_length=200, blank=True,
        help_text=_('Describes the photo for screen readers. Please fill this in.'),
    )
    credit = models.CharField(max_length=140, blank=True)
    display_order = models.PositiveSmallIntegerField(default=0)
    is_featured = models.BooleanField(default=False)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='images_uploaded',
    )

    class Meta:
        verbose_name = _('photo')
        ordering = ('display_order', 'id')

    def __str__(self):
        return self.caption or f'Photo {self.pk} in {self.album.title}'


class VideoFeature(models.Model):
    """An embedded performance video for the media page."""

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    video_url = models.URLField(help_text=_('YouTube or Vimeo link.'))
    thumbnail = models.ImageField(upload_to='videos/', blank=True)
    event = models.ForeignKey(
        'events.Event', null=True, blank=True, on_delete=models.SET_NULL, related_name='videos',
    )
    recorded_on = models.DateField(null=True, blank=True)
    is_published = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = _('video')
        ordering = ('display_order', '-recorded_on')

    def __str__(self):
        return self.title


# ---------------------------------------------------------------------------
# Social proof and support content
# ---------------------------------------------------------------------------
class Testimonial(TimeStampedModel):
    name = models.CharField(max_length=140)
    role = models.CharField(
        max_length=140, blank=True, help_text=_('e.g. "Parent of Junior Ballet dancer"'),
    )
    quote = models.TextField()
    photo = models.ImageField(upload_to='testimonials/', blank=True)
    rating = models.PositiveSmallIntegerField(null=True, blank=True)
    is_published = models.BooleanField(default=False)
    is_featured = models.BooleanField(default=False)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ('display_order', '-created_at')

    def __str__(self):
        return f'{self.name} - {self.quote[:50]}'


class FAQ(models.Model):
    question = models.CharField(max_length=250)
    answer = models.TextField()
    category = models.CharField(
        max_length=80, blank=True, help_text=_('e.g. "Enrolment", "Fees", "Uniform"'),
    )
    display_order = models.PositiveSmallIntegerField(default=0)
    is_published = models.BooleanField(default=True)

    class Meta:
        verbose_name = _('FAQ')
        verbose_name_plural = _('FAQs')
        ordering = ('category', 'display_order')

    def __str__(self):
        return self.question


class Page(TimeStampedModel):
    """A simple editable page -- privacy policy, terms, safeguarding, and so on."""

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    body = models.TextField()
    meta_description = models.CharField(max_length=200, blank=True)
    status = models.CharField(
        max_length=20, choices=PublishStatus.choices, default=PublishStatus.PUBLISHED,
    )
    show_in_footer = models.BooleanField(default=False)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ('display_order', 'title')

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('website:page', args=[self.slug])


# ---------------------------------------------------------------------------
# Inbound
# ---------------------------------------------------------------------------
class ContactMessage(models.Model):
    class Topic(models.TextChoices):
        GENERAL = 'general', _('General enquiry')
        ENROLMENT = 'enrolment', _('Enrolment')
        FEES = 'fees', _('Fees and payments')
        RECITAL = 'recital', _('The annual recital')
        PARTNERSHIP = 'partnership', _('Partnership or sponsorship')
        MEDIA = 'media', _('Press and media')
        OTHER = 'other', _('Something else')

    name = models.CharField(max_length=140)
    email = models.EmailField()
    phone = models.CharField(max_length=40, blank=True)
    topic = models.CharField(max_length=20, choices=Topic.choices, default=Topic.GENERAL)
    subject = models.CharField(max_length=200, blank=True)
    message = models.TextField()

    is_read = models.BooleanField(default=False, db_index=True)
    is_archived = models.BooleanField(default=False)
    replied_at = models.DateTimeField(null=True, blank=True)
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='messages_handled',
    )
    staff_notes = models.TextField(blank=True)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _('contact message')
        ordering = ('-created_at',)

    def __str__(self):
        return f'{self.name} - {self.subject or self.get_topic_display()}'


class NewsletterSubscriber(models.Model):
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=140, blank=True)
    is_active = models.BooleanField(default=True)
    source = models.CharField(max_length=80, blank=True, default='website')
    subscribed_at = models.DateTimeField(auto_now_add=True)
    unsubscribed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _('newsletter subscriber')
        ordering = ('-subscribed_at',)

    def __str__(self):
        return self.email
