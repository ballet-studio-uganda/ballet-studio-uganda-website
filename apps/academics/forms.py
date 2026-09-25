"""Forms for classes, enrolment, registers and progress reports."""

from __future__ import annotations

import datetime as dt

from django import forms
from django.core.exceptions import ValidationError
from django.forms import inlineformset_factory
from django.utils.translation import gettext_lazy as _

from apps.accounts.forms import StyledFormMixin
from apps.accounts.models import StaffProfile

from .models import (
    ClassSchedule,
    ClassSession,
    DanceClass,
    Enrolment,
    EnrolmentStatus,
    ProgressReport,
    SkillScore,
    StudentNote,
    Term,
)


class DanceClassForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = DanceClass
        fields = (
            'name', 'program', 'term', 'teachers', 'studio',
            'capacity', 'description', 'is_active',
        )
        widgets = {
            'teachers': forms.CheckboxSelectMultiple,
            'description': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['teachers'].queryset = (
            StaffProfile.objects.filter(is_active_staff=True)
            .select_related('user').order_by('user__first_name')
        )
        self.fields['term'].queryset = Term.objects.select_related('academic_year')
        if not self.instance.pk:
            current = Term.current()
            if current:
                self.fields['term'].initial = current


ClassScheduleFormSet = inlineformset_factory(
    DanceClass, ClassSchedule,
    fields=('weekday', 'start_time', 'end_time', 'studio'),
    extra=2, can_delete=True,
    widgets={
        'start_time': forms.TimeInput(attrs={'type': 'time', 'class': 'form-input'}),
        'end_time': forms.TimeInput(attrs={'type': 'time', 'class': 'form-input'}),
        'weekday': forms.Select(attrs={'class': 'form-input form-select'}),
        'studio': forms.Select(attrs={'class': 'form-input form-select'}),
    },
)


class GenerateSessionsForm(StyledFormMixin, forms.Form):
    """Build the term's timetable, skipping any dates the studio is closed."""

    start_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    end_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    holidays = forms.CharField(
        required=False, label=_('Dates to skip'),
        widget=forms.Textarea(attrs={
            'rows': 3, 'placeholder': '2026-04-06\n2026-04-07',
        }),
        help_text=_('One YYYY-MM-DD date per line — public holidays, studio closures.'),
    )

    def __init__(self, *args, dance_class=None, **kwargs):
        self.dance_class = dance_class
        super().__init__(*args, **kwargs)
        if dance_class is not None and not self.is_bound:
            self.fields['start_date'].initial = dance_class.term.start_date
            self.fields['end_date'].initial = dance_class.term.end_date

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get('start_date'), cleaned.get('end_date')
        if start and end and end < start:
            raise ValidationError(_('The end date must fall after the start date.'))
        if start and end and (end - start).days > 400:
            raise ValidationError(_('Please generate at most one year at a time.'))
        return cleaned

    def skip_dates(self):
        dates = []
        for line in (self.cleaned_data.get('holidays') or '').splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                dates.append(dt.date.fromisoformat(line))
            except ValueError:
                continue
        return dates


class SessionForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ClassSession
        fields = (
            'date', 'start_time', 'end_time', 'studio', 'teacher',
            'status', 'topic', 'notes', 'cancellation_reason',
        )
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'start_time': forms.TimeInput(attrs={'type': 'time'}),
            'end_time': forms.TimeInput(attrs={'type': 'time'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }


class EnrolmentForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Enrolment
        fields = ('dance_class', 'status', 'date_enrolled', 'notes')
        widgets = {
            'date_enrolled': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, student=None, **kwargs):
        self.student = student
        super().__init__(*args, **kwargs)
        qs = DanceClass.objects.active().select_related('program', 'term')
        term = Term.current()
        if term:
            qs = qs.filter(term=term)
        if student is not None:
            qs = qs.exclude(enrolments__student=student)
        self.fields['dance_class'].queryset = qs

    def clean_dance_class(self):
        dance_class = self.cleaned_data['dance_class']
        status = self.data.get('status', EnrolmentStatus.ACTIVE)
        if status == EnrolmentStatus.ACTIVE and dance_class.is_full:
            raise ValidationError(
                _('%(name)s is full (%(n)s places). Use the waiting list instead.')
                % {'name': dance_class.name, 'n': dance_class.capacity},
            )
        return dance_class


class ProgressReportForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ProgressReport
        fields = (
            'strengths', 'areas_to_develop', 'teacher_comment',
            'recommendation', 'conduct_comment',
        )
        widgets = {
            'strengths': forms.Textarea(attrs={
                'rows': 3, 'placeholder': 'What is this dancer doing well?',
            }),
            'areas_to_develop': forms.Textarea(attrs={
                'rows': 3, 'placeholder': 'What should they focus on next term?',
            }),
            'teacher_comment': forms.Textarea(attrs={
                'rows': 4, 'placeholder': 'Overall remarks for the family.',
            }),
        }


class SkillScoreForm(forms.ModelForm):
    class Meta:
        model = SkillScore
        fields = ('score', 'comment')
        widgets = {
            'score': forms.NumberInput(attrs={
                'class': 'score-input', 'min': 0, 'step': 1,
            }),
            'comment': forms.TextInput(attrs={
                'class': 'form-input', 'placeholder': 'Optional note',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.skill_id:
            self.fields['score'].widget.attrs['max'] = self.instance.skill.max_score


SkillScoreFormSet = inlineformset_factory(
    ProgressReport, SkillScore, form=SkillScoreForm,
    extra=0, can_delete=False,
)


class StudentNoteForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = StudentNote
        fields = ('kind', 'title', 'body', 'date', 'visible_to_guardian')
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'body': forms.Textarea(attrs={'rows': 3}),
        }
