"""Public-facing forms."""

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.academics.models import EnrolmentApplication, Program
from apps.accounts.forms import StyledFormMixin

from .models import ContactMessage


class ContactForm(StyledFormMixin, forms.ModelForm):
    # Bots fill everything in; people leave a hidden field alone.
    website = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = ContactMessage
        fields = ('name', 'email', 'phone', 'topic', 'subject', 'message')
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Your full name'}),
            'email': forms.EmailInput(attrs={'placeholder': 'you@example.com'}),
            'phone': forms.TextInput(attrs={'placeholder': '+256 7XX XXX XXX'}),
            'subject': forms.TextInput(attrs={'placeholder': 'What is this about?'}),
            'message': forms.Textarea(attrs={'rows': 6, 'placeholder': 'How can we help?'}),
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('website'):
            raise forms.ValidationError(_('Your message could not be sent.'))
        return cleaned


class EnrolmentApplicationForm(StyledFormMixin, forms.ModelForm):
    website = forms.CharField(required=False, widget=forms.HiddenInput)

    consent = forms.BooleanField(
        required=True,
        label=_('I confirm the details above are correct and agree to be contacted.'),
    )

    class Meta:
        model = EnrolmentApplication
        fields = (
            'student_first_name', 'student_last_name', 'student_date_of_birth',
            'student_gender', 'previous_experience',
            'guardian_name', 'guardian_email', 'guardian_phone',
            'guardian_relationship', 'home_address',
            'program', 'preferred_days', 'how_heard_about_us', 'message',
        )
        labels = {
            'student_first_name': _('Dancer’s first name'),
            'student_last_name': _('Dancer’s surname'),
            'student_date_of_birth': _('Date of birth'),
            'student_gender': _('Gender'),
            'previous_experience': _('Any previous dance experience?'),
            'guardian_name': _('Parent / guardian name'),
            'guardian_email': _('Email address'),
            'guardian_phone': _('Phone number'),
            'guardian_relationship': _('Relationship to the dancer'),
            'home_address': _('Home address'),
            'program': _('Programme of interest'),
            'preferred_days': _('Days that suit you best'),
            'how_heard_about_us': _('How did you hear about us?'),
            'message': _('Anything else we should know?'),
        }
        widgets = {
            'student_date_of_birth': forms.DateInput(attrs={'type': 'date'}),
            'student_gender': forms.Select(choices=[
                ('', '—'), ('F', 'Female'), ('M', 'Male'), ('O', 'Other'),
            ]),
            'previous_experience': forms.Textarea(attrs={'rows': 3}),
            'message': forms.Textarea(attrs={'rows': 4}),
            'guardian_phone': forms.TextInput(attrs={'placeholder': '+256 7XX XXX XXX'}),
            'preferred_days': forms.TextInput(
                attrs={'placeholder': 'e.g. Saturday mornings, weekday evenings'},
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['program'].queryset = Program.objects.filter(
            is_active=True, show_on_website=True,
        )
        self.fields['program'].empty_label = 'Not sure yet — please advise'

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('website'):
            raise forms.ValidationError(_('Your enquiry could not be sent.'))
        return cleaned


class NewsletterForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'placeholder': 'your@email.com', 'class': 'form-input',
            'aria-label': 'Email address',
        }),
    )
    name = forms.CharField(required=False, widget=forms.HiddenInput)
