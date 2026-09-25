"""Django admin for the calendar and the annual recital."""

from django.contrib import admin
from django.utils.html import format_html

from .models import (
    Event,
    EventCategory,
    EventRegistration,
    Partner,
    Recital,
    RecitalCast,
    RecitalPerformance,
    RehearsalSchedule,
)


@admin.register(EventCategory)
class EventCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'swatch', 'display_order', 'is_active')
    list_editable = ('display_order', 'is_active')
    prepopulated_fields = {'slug': ('name',)}

    @admin.display(description='Colour')
    def swatch(self, obj):
        return format_html(
            '<span style="display:inline-block;width:34px;height:14px;'
            'border-radius:3px;background:{};"></span>', obj.colour,
        )


class EventRegistrationInline(admin.TabularInline):
    model = EventRegistration
    extra = 0
    fields = ('full_name', 'email', 'phone', 'seats', 'status', 'checked_in_at')


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ('title', 'start_at', 'category', 'venue_name', 'audience',
                    'status', 'is_featured', 'seats_taken')
    list_filter = ('status', 'audience', 'category', 'is_featured',
                   'requires_registration', 'start_at')
    search_fields = ('title', 'description', 'venue_name')
    prepopulated_fields = {'slug': ('title',)}
    date_hierarchy = 'start_at'
    inlines = (EventRegistrationInline,)
    list_editable = ('is_featured',)

    fieldsets = (
        (None, {'fields': ('title', 'slug', 'category', 'summary', 'description')}),
        ('When', {'fields': ('start_at', 'end_at', 'is_all_day')}),
        ('Where', {'fields': ('venue_name', 'venue_address', 'map_url')}),
        ('Media', {'fields': ('poster', 'banner')}),
        ('Visibility', {'fields': ('status', 'audience', 'is_featured',
                                   'cancellation_reason')}),
        ('Registration & tickets', {
            'fields': ('requires_registration', 'registration_closes_at',
                       'capacity', 'ticket_price'),
            'description': 'Tickets are sold in person; this only reserves seats.',
        }),
        ('Contact', {'fields': ('contact_name', 'contact_phone', 'contact_email'),
                     'classes': ('collapse',)}),
    )


@admin.register(EventRegistration)
class EventRegistrationAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'event', 'seats', 'status', 'phone', 'created_at')
    list_filter = ('status', 'event')
    search_fields = ('full_name', 'email', 'phone')


class RecitalPerformanceInline(admin.TabularInline):
    model = RecitalPerformance
    extra = 1
    fields = ('order', 'act', 'title', 'music', 'choreographer',
              'dance_class', 'duration_minutes')


class RehearsalInline(admin.TabularInline):
    model = RehearsalSchedule
    extra = 0
    fields = ('title', 'date', 'start_time', 'end_time', 'venue',
              'is_full_cast', 'is_dress_rehearsal')


@admin.register(Recital)
class RecitalAdmin(admin.ModelAdmin):
    list_display = ('year', 'title', 'performance_date', 'venue_name',
                    'cast_size', 'raised_display', 'is_published', 'is_current')
    list_filter = ('is_published', 'is_current', 'year')
    search_fields = ('title', 'theme', 'description')
    prepopulated_fields = {'slug': ('title',)}
    inlines = (RecitalPerformanceInline, RehearsalInline)
    list_editable = ('is_published', 'is_current')

    fieldsets = (
        ('Identity', {'fields': ('year', 'title', 'slug', 'theme', 'tagline', 'event')}),
        ('When and where', {'fields': ('performance_date', 'additional_dates',
                                       'doors_open_time', 'start_time',
                                       'venue_name', 'venue_address')}),
        ('The story', {'fields': ('introduction', 'description',
                                  'sickle_cell_message', 'director_note')}),
        ('Media', {'fields': ('hero_image', 'hero_video', 'hero_video_url', 'poster',
                              'programme_pdf', 'trailer_url', 'gallery_album')}),
        ('Tickets', {'fields': ('ticket_price_regular', 'ticket_price_vip',
                                'ticket_price_child', 'ticket_info')}),
        ('Fundraising', {'fields': ('fundraising_goal', 'beneficiary',
                                    'beneficiary_url')}),
        ('Publishing', {'fields': ('is_published', 'is_current')}),
    )

    @admin.display(description='Raised')
    def raised_display(self, obj):
        if not obj.fundraising_goal:
            return f'UGX {obj.amount_raised:,.0f}'
        return format_html(
            'UGX {} <small>({}% of goal)</small>',
            f'{obj.amount_raised:,.0f}', obj.fundraising_percent or 0,
        )


class RecitalCastInline(admin.TabularInline):
    model = RecitalCast
    extra = 1
    autocomplete_fields = ('student',)


@admin.register(RecitalPerformance)
class RecitalPerformanceAdmin(admin.ModelAdmin):
    list_display = ('order', 'title', 'recital', 'act', 'choreographer',
                    'dance_class', 'duration_minutes')
    list_filter = ('recital', 'act')
    search_fields = ('title', 'music', 'choreographer')
    inlines = (RecitalCastInline,)


@admin.register(RecitalCast)
class RecitalCastAdmin(admin.ModelAdmin):
    list_display = ('student', 'performance', 'role_name', 'role_type', 'costume_ready')
    list_filter = ('role_type', 'costume_ready', 'performance__recital')
    search_fields = ('student__first_name', 'student__last_name', 'role_name')
    autocomplete_fields = ('student',)
    list_editable = ('costume_ready',)


@admin.register(RehearsalSchedule)
class RehearsalScheduleAdmin(admin.ModelAdmin):
    list_display = ('title', 'recital', 'date', 'start_time', 'venue',
                    'is_full_cast', 'is_dress_rehearsal')
    list_filter = ('recital', 'is_dress_rehearsal', 'date')
    filter_horizontal = ('performances',)


@admin.register(Partner)
class PartnerAdmin(admin.ModelAdmin):
    list_display = ('name', 'tier', 'is_sickle_cell_partner', 'display_order', 'is_active')
    list_filter = ('tier', 'is_sickle_cell_partner', 'is_active')
    list_editable = ('display_order', 'is_active')
    filter_horizontal = ('recitals',)
