"""Django admin for public content."""

from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html

from .models import (
    FAQ,
    Announcement,
    ContactMessage,
    GalleryAlbum,
    GalleryImage,
    HeroSlide,
    NewsCategory,
    NewsPost,
    NewsletterSubscriber,
    Page,
    PublishStatus,
    SiteSettings,
    Testimonial,
    VideoFeature,
)


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    fieldsets = (
        ('Identity', {'fields': ('studio_name', 'short_name', 'tagline',
                                 'founded_year', 'logo', 'logo_light',
                                 'favicon', 'og_image')}),
        ('Story', {'fields': ('about_short', 'about_full', 'mission', 'vision',
                              'values', 'sickle_cell_statement')}),
        ('Contact', {'fields': ('email', 'phone', 'whatsapp', 'address',
                                'map_embed_url', 'opening_hours')}),
        ('Social', {'fields': ('facebook_url', 'instagram_url', 'youtube_url',
                               'tiktok_url', 'twitter_url', 'linkedin_url')}),
        ('Behaviour', {'fields': ('enrolment_open', 'show_announcement_bar',
                                  'maintenance_mode', 'google_analytics_id')}),
    )

    def has_add_permission(self, request):
        return not SiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(HeroSlide)
class HeroSlideAdmin(admin.ModelAdmin):
    list_display = ('headline', 'kicker', 'has_video', 'display_order', 'is_active')
    list_editable = ('display_order', 'is_active')

    fieldsets = (
        ('Animated text', {'fields': ('kicker', 'headline', 'headline_accent',
                                      'subtext')}),
        ('Background', {
            'fields': ('video', 'video_url', 'poster_image', 'overlay_opacity'),
            'description': 'Upload a short muted MP4, or paste a hosted URL. '
                           'The poster image shows while the video loads.',
        }),
        ('Calls to action', {'fields': ('primary_cta_text', 'primary_cta_url',
                                        'secondary_cta_text', 'secondary_cta_url')}),
        ('Publishing', {'fields': ('is_active', 'display_order')}),
    )


@admin.register(NewsCategory)
class NewsCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'display_order')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(NewsPost)
class NewsPostAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'status', 'published_at', 'author',
                    'is_featured', 'is_pinned', 'view_count')
    list_filter = ('status', 'category', 'is_featured', 'is_pinned', 'published_at')
    search_fields = ('title', 'excerpt', 'body', 'tags')
    prepopulated_fields = {'slug': ('title',)}
    date_hierarchy = 'published_at'
    list_editable = ('status', 'is_featured', 'is_pinned')
    readonly_fields = ('view_count', 'reading_minutes')
    actions = ('publish_now',)

    fieldsets = (
        (None, {'fields': ('title', 'slug', 'category', 'excerpt', 'body')}),
        ('Image', {'fields': ('cover_image', 'cover_caption')}),
        ('Publishing', {'fields': ('status', 'published_at', 'author',
                                   'is_featured', 'is_pinned')}),
        ('Extras', {'fields': ('tags', 'related_event', 'meta_description',
                               'view_count', 'reading_minutes'),
                    'classes': ('collapse',)}),
    )

    def save_model(self, request, obj, form, change):
        if not obj.author_id:
            obj.author = request.user
        super().save_model(request, obj, form, change)

    @admin.action(description='Publish now')
    def publish_now(self, request, queryset):
        updated = queryset.update(
            status=PublishStatus.PUBLISHED, published_at=timezone.now(),
        )
        self.message_user(request, f'{updated} post(s) published.')


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ('title', 'level', 'audience', 'starts_at', 'ends_at',
                    'is_active', 'is_pinned', 'show_in_bar', 'is_live')
    list_filter = ('level', 'audience', 'is_active', 'show_in_bar')
    search_fields = ('title', 'message')
    list_editable = ('is_active', 'is_pinned', 'show_in_bar')

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


class GalleryImageInline(admin.TabularInline):
    model = GalleryImage
    extra = 3
    fields = ('image', 'thumb', 'caption', 'alt_text', 'credit',
              'display_order', 'is_featured')
    readonly_fields = ('thumb',)

    @admin.display(description='Preview')
    def thumb(self, obj):
        if obj.pk and obj.image:
            return format_html(
                '<img src="{}" style="height:56px;border-radius:6px;">', obj.image.url,
            )
        return '—'


@admin.register(GalleryAlbum)
class GalleryAlbumAdmin(admin.ModelAdmin):
    list_display = ('title', 'date', 'event', 'image_count', 'is_public',
                    'is_featured', 'display_order')
    list_filter = ('is_public', 'is_featured', 'date')
    search_fields = ('title', 'description', 'photographer')
    prepopulated_fields = {'slug': ('title',)}
    inlines = (GalleryImageInline,)
    list_editable = ('is_public', 'is_featured', 'display_order')

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(GalleryImage)
class GalleryImageAdmin(admin.ModelAdmin):
    list_display = ('thumb', 'album', 'caption', 'display_order', 'is_featured')
    list_filter = ('album', 'is_featured')
    search_fields = ('caption', 'alt_text', 'credit')
    list_editable = ('display_order', 'is_featured')

    @admin.display(description='Photo')
    def thumb(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="height:48px;border-radius:6px;">', obj.image.url,
            )
        return '—'


@admin.register(VideoFeature)
class VideoFeatureAdmin(admin.ModelAdmin):
    list_display = ('title', 'recorded_on', 'event', 'is_published', 'is_featured')
    list_filter = ('is_published', 'is_featured')
    list_editable = ('is_published', 'is_featured')


@admin.register(Testimonial)
class TestimonialAdmin(admin.ModelAdmin):
    list_display = ('name', 'role', 'rating', 'is_published', 'is_featured',
                    'display_order')
    list_filter = ('is_published', 'is_featured', 'rating')
    search_fields = ('name', 'quote')
    list_editable = ('is_published', 'is_featured', 'display_order')


@admin.register(FAQ)
class FAQAdmin(admin.ModelAdmin):
    list_display = ('question', 'category', 'display_order', 'is_published')
    list_filter = ('category', 'is_published')
    search_fields = ('question', 'answer')
    list_editable = ('category', 'display_order', 'is_published')


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = ('title', 'slug', 'status', 'show_in_footer', 'display_order')
    list_filter = ('status', 'show_in_footer')
    prepopulated_fields = {'slug': ('title',)}
    list_editable = ('status', 'show_in_footer', 'display_order')


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ('name', 'topic', 'subject', 'email', 'phone',
                    'is_read', 'created_at')
    list_filter = ('topic', 'is_read', 'is_archived', 'created_at')
    search_fields = ('name', 'email', 'subject', 'message')
    readonly_fields = ('name', 'email', 'phone', 'topic', 'subject', 'message',
                       'ip_address', 'created_at')
    date_hierarchy = 'created_at'

    def has_add_permission(self, request):
        return False


@admin.register(NewsletterSubscriber)
class NewsletterSubscriberAdmin(admin.ModelAdmin):
    list_display = ('email', 'name', 'is_active', 'source', 'subscribed_at')
    list_filter = ('is_active', 'source')
    search_fields = ('email', 'name')
