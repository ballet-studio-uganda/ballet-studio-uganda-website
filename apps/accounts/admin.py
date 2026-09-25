"""Django admin for people. A technical back-door -- day-to-day work happens
in the studio's own dashboards."""

from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.utils import timezone
from django.utils.html import format_html

from .models import (
    ApprovalStatus,
    AuditLog,
    GuardianProfile,
    Notification,
    StaffProfile,
    Student,
    StudentGuardian,
    User,
)


class StaffProfileInline(admin.StackedInline):
    model = StaffProfile
    can_delete = False
    extra = 0
    fieldsets = (
        (None, {'fields': ('job_title', 'employment_type', 'date_joined_studio',
                           'is_active_staff')}),
        ('Faculty page', {'fields': ('short_bio', 'bio', 'qualifications', 'specialisms',
                                     'show_on_website', 'website_order'),
                          'classes': ('collapse',)}),
        ('Payroll', {'fields': ('monthly_salary', 'hourly_rate', 'bank_name',
                                'bank_account_number', 'mobile_money_number'),
                     'classes': ('collapse',)}),
    )


class GuardianProfileInline(admin.StackedInline):
    model = GuardianProfile
    can_delete = False
    extra = 0


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = (
        'display_name', 'email', 'role', 'status_pill', 'phone', 'date_joined',
    )
    list_filter = ('role', 'approval_status', 'is_active', 'date_joined')
    search_fields = ('first_name', 'last_name', 'email', 'username', 'phone')
    ordering = ('-date_joined',)
    readonly_fields = ('verified_at', 'last_seen', 'created_at', 'updated_at')
    actions = ('approve_selected', 'suspend_selected')

    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Identity', {'fields': ('first_name', 'last_name', 'email', 'phone',
                                 'whatsapp', 'photo', 'date_of_birth', 'gender')}),
        ('Address', {'fields': ('address', 'city', 'country')}),
        ('Role & verification', {'fields': ('role', 'approval_status', 'verified_by',
                                            'verified_at', 'verification_note')}),
        ('Preferences', {'fields': ('receives_email', 'receives_sms',
                                    'must_change_password')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser',
                                    'groups', 'user_permissions'),
                         'classes': ('collapse',)}),
        ('Dates', {'fields': ('last_login', 'date_joined', 'last_seen'),
                   'classes': ('collapse',)}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'first_name', 'last_name',
                       'role', 'password1', 'password2'),
        }),
    )

    @admin.display(description='Status', ordering='approval_status')
    def status_pill(self, obj):
        colours = {
            ApprovalStatus.APPROVED: '#1f8a5f',
            ApprovalStatus.PENDING: '#c9a84c',
            ApprovalStatus.REJECTED: '#b3261e',
            ApprovalStatus.SUSPENDED: '#6b5a62',
        }
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 10px;'
            'border-radius:20px;font-size:11px;">{}</span>',
            colours.get(obj.approval_status, '#6b5a62'),
            obj.get_approval_status_display(),
        )

    def get_inlines(self, request, obj=None):
        if obj is None:
            return []
        if obj.is_studio_staff:
            return [StaffProfileInline]
        if obj.is_guardian:
            return [GuardianProfileInline]
        return []

    @admin.action(description='Verify selected accounts')
    def approve_selected(self, request, queryset):
        count = 0
        for user in queryset.exclude(approval_status=ApprovalStatus.APPROVED):
            user.approve(by=request.user)
            count += 1
        self.message_user(request, f'{count} account(s) verified.', messages.SUCCESS)

    @admin.action(description='Suspend selected accounts')
    def suspend_selected(self, request, queryset):
        updated = queryset.update(approval_status=ApprovalStatus.SUSPENDED)
        self.message_user(request, f'{updated} account(s) suspended.', messages.WARNING)


class StudentGuardianInline(admin.TabularInline):
    model = StudentGuardian
    extra = 1
    autocomplete_fields = ('guardian',)


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'student_id', 'age', 'status', 'guardian_summary',
                    'enrolment_date')
    list_filter = ('status', 'gender', 'sickle_cell_status', 'photo_consent',
                   'enrolment_date')
    search_fields = ('first_name', 'last_name', 'preferred_name', 'student_id')
    readonly_fields = ('student_id', 'age', 'created_at', 'updated_at')
    inlines = (StudentGuardianInline,)
    date_hierarchy = 'enrolment_date'

    fieldsets = (
        ('Dancer', {'fields': ('student_id', 'user', 'first_name', 'middle_name',
                               'last_name', 'preferred_name', 'date_of_birth', 'age',
                               'gender', 'photo')}),
        ('Enrolment', {'fields': ('status', 'enrolment_date', 'withdrawal_date',
                                  'withdrawal_reason')}),
        ('Background', {'fields': ('school_name', 'home_address', 'how_heard_about_us',
                                   'previous_dance_experience')}),
        ('Wardrobe', {'fields': ('height_cm', 'leotard_size', 'shoe_size'),
                      'classes': ('collapse',)}),
        ('Health (sensitive)', {
            'fields': ('blood_group', 'sickle_cell_status', 'medical_conditions',
                       'allergies', 'medication', 'doctor_name', 'doctor_phone',
                       'medical_notes'),
            'classes': ('collapse',),
            'description': 'Optional and confidential. Shared only with teaching staff.',
        }),
        ('Consents', {'fields': ('photo_consent', 'media_consent',
                                 'medical_treatment_consent')}),
        ('Internal', {'fields': ('notes',), 'classes': ('collapse',)}),
    )

    @admin.display(description='Guardians')
    def guardian_summary(self, obj):
        names = [link.guardian.user.display_name for link in obj.guardian_links.all()[:2]]
        return ', '.join(names) or '—'


@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'staff_id', 'job_title', 'employment_type',
                    'is_active_staff', 'show_on_website')
    list_filter = ('employment_type', 'is_active_staff', 'show_on_website')
    search_fields = ('user__first_name', 'user__last_name', 'staff_id', 'job_title')
    readonly_fields = ('staff_id',)
    autocomplete_fields = ('user',)


@admin.register(GuardianProfile)
class GuardianProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'guardian_id', 'occupation', 'preferred_contact_method',
                    'receives_invoices')
    list_filter = ('preferred_contact_method', 'receives_invoices')
    search_fields = ('user__first_name', 'user__last_name', 'user__email', 'guardian_id')
    readonly_fields = ('guardian_id',)
    autocomplete_fields = ('user',)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('title', 'recipient', 'level', 'is_read', 'created_at')
    list_filter = ('level', 'is_read', 'created_at')
    search_fields = ('title', 'message', 'recipient__email')


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'actor', 'action', 'description', 'ip_address')
    list_filter = ('action', 'created_at')
    search_fields = ('description', 'actor__email', 'target_model')
    readonly_fields = tuple(f.name for f in AuditLog._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
