"""Django admin for teaching, attendance and progress."""

from django.contrib import admin, messages
from django.utils.html import format_html

from . import services
from .models import (
    AcademicYear,
    AssessmentPeriod,
    Attendance,
    ClassSchedule,
    ClassSession,
    DanceClass,
    EnrolmentApplication,
    Enrolment,
    Program,
    ProgressReport,
    Skill,
    SkillCategory,
    SkillScore,
    Studio,
    StudentNote,
    Term,
)


class TermInline(admin.TabularInline):
    model = Term
    extra = 1


@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ('name', 'start_date', 'end_date', 'is_current')
    list_editable = ('is_current',)
    inlines = (TermInline,)


@admin.register(Term)
class TermAdmin(admin.ModelAdmin):
    list_display = ('name', 'academic_year', 'start_date', 'end_date',
                    'is_current', 'week_count')
    list_filter = ('academic_year', 'is_current')
    list_editable = ('is_current',)


@admin.register(Studio)
class StudioAdmin(admin.ModelAdmin):
    list_display = ('name', 'location', 'capacity', 'has_sprung_floor', 'is_active')
    list_editable = ('is_active',)


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ('name', 'age_range_display', 'level_label', 'swatch',
                    'active_student_count', 'is_active', 'show_on_website')
    list_filter = ('is_active', 'show_on_website')
    list_editable = ('is_active', 'show_on_website')
    search_fields = ('name', 'description')
    prepopulated_fields = {'slug': ('name',)}

    fieldsets = (
        (None, {'fields': ('name', 'slug', 'tagline', 'description', 'what_you_learn')}),
        ('Who it is for', {'fields': ('min_age', 'max_age', 'level_label')}),
        ('Sessions', {'fields': ('duration_minutes', 'sessions_per_week')}),
        ('Presentation', {'fields': ('image', 'accent_colour', 'icon',
                                     'display_order', 'is_active', 'show_on_website')}),
    )

    @admin.display(description='Colour')
    def swatch(self, obj):
        return format_html(
            '<span style="display:inline-block;width:34px;height:14px;'
            'border-radius:3px;background:{};"></span>', obj.accent_colour,
        )


class ClassScheduleInline(admin.TabularInline):
    model = ClassSchedule
    extra = 1


class EnrolmentInline(admin.TabularInline):
    model = Enrolment
    extra = 0
    autocomplete_fields = ('student',)
    fields = ('student', 'status', 'date_enrolled', 'notes')


@admin.register(DanceClass)
class DanceClassAdmin(admin.ModelAdmin):
    list_display = ('name', 'program', 'term', 'teacher_names', 'schedule_display',
                    'enrolled_count', 'capacity', 'is_active')
    list_filter = ('program', 'term', 'is_active', 'studio')
    search_fields = ('name', 'description')
    filter_horizontal = ('teachers',)
    inlines = (ClassScheduleInline, EnrolmentInline)
    actions = ('build_sessions',)

    @admin.action(description='Generate sessions for the whole term')
    def build_sessions(self, request, queryset):
        total = sum(len(services.generate_sessions(c)) for c in queryset)
        self.message_user(request, f'{total} session(s) created.', messages.SUCCESS)


@admin.register(Enrolment)
class EnrolmentAdmin(admin.ModelAdmin):
    list_display = ('student', 'dance_class', 'status', 'date_enrolled')
    list_filter = ('status', 'dance_class__program', 'dance_class__term')
    search_fields = ('student__first_name', 'student__last_name', 'student__student_id')
    autocomplete_fields = ('student', 'dance_class')


class AttendanceInline(admin.TabularInline):
    model = Attendance
    extra = 0
    autocomplete_fields = ('student',)
    fields = ('student', 'status', 'minutes_late', 'remarks')


@admin.register(ClassSession)
class ClassSessionAdmin(admin.ModelAdmin):
    list_display = ('dance_class', 'date', 'start_time', 'status',
                    'register_taken', 'topic')
    list_filter = ('status', 'register_taken', 'date', 'dance_class__program')
    search_fields = ('dance_class__name', 'topic')
    date_hierarchy = 'date'
    inlines = (AttendanceInline,)
    autocomplete_fields = ('dance_class',)


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ('student', 'session', 'status', 'minutes_late', 'marked_by')
    list_filter = ('status', 'session__date', 'session__dance_class__program')
    search_fields = ('student__first_name', 'student__last_name')
    autocomplete_fields = ('student', 'session')
    date_hierarchy = 'session__date'


class SkillInline(admin.TabularInline):
    model = Skill
    extra = 2
    fields = ('name', 'description', 'max_score', 'display_order', 'is_active')


@admin.register(SkillCategory)
class SkillCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'display_order', 'skill_count', 'is_active')
    list_editable = ('display_order', 'is_active')
    prepopulated_fields = {'slug': ('name',)}
    inlines = (SkillInline,)

    @admin.display(description='Skills')
    def skill_count(self, obj):
        return obj.skills.count()


@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'max_score', 'display_order', 'is_active')
    list_filter = ('category', 'is_active', 'programs')
    search_fields = ('name', 'description')
    filter_horizontal = ('programs',)


@admin.register(AssessmentPeriod)
class AssessmentPeriodAdmin(admin.ModelAdmin):
    list_display = ('name', 'term', 'opens_on', 'closes_on', 'is_open', 'is_accepting')
    list_filter = ('is_open', 'term')
    list_editable = ('is_open',)


class SkillScoreInline(admin.TabularInline):
    model = SkillScore
    extra = 0
    autocomplete_fields = ('skill',)


@admin.register(ProgressReport)
class ProgressReportAdmin(admin.ModelAdmin):
    list_display = ('student', 'dance_class', 'period', 'status',
                    'average_percent', 'teacher', 'published_at')
    list_filter = ('status', 'period', 'dance_class__program')
    search_fields = ('student__first_name', 'student__last_name')
    autocomplete_fields = ('student', 'dance_class')
    inlines = (SkillScoreInline,)
    actions = ('publish_selected',)
    readonly_fields = ('submitted_at', 'published_at', 'guardian_viewed_at')

    @admin.action(description='Publish selected reports to guardians')
    def publish_selected(self, request, queryset):
        count = 0
        for report in queryset:
            report.publish(by=request.user)
            count += 1
        self.message_user(request, f'{count} report(s) published.', messages.SUCCESS)


@admin.register(StudentNote)
class StudentNoteAdmin(admin.ModelAdmin):
    list_display = ('student', 'kind', 'title', 'date', 'author', 'visible_to_guardian')
    list_filter = ('kind', 'visible_to_guardian', 'date')
    search_fields = ('title', 'body', 'student__first_name', 'student__last_name')
    autocomplete_fields = ('student',)


@admin.register(EnrolmentApplication)
class EnrolmentApplicationAdmin(admin.ModelAdmin):
    list_display = ('student_full_name', 'student_age', 'program', 'guardian_name',
                    'guardian_phone', 'status', 'created_at')
    list_filter = ('status', 'program', 'created_at')
    search_fields = ('student_first_name', 'student_last_name', 'guardian_name',
                     'guardian_email', 'guardian_phone')
    list_editable = ('status',)
    readonly_fields = ('created_at', 'updated_at')
    date_hierarchy = 'created_at'
