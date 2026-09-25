"""Event forms."""

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.accounts.forms import StyledFormMixin

from .models import EventRegistration


class EventRegistrationForm(StyledFormMixin, forms.ModelForm):
    """Reserve seats. Payment, where there is any, is taken in person."""

    class Meta:
        model = EventRegistration
        fields = ('full_name', 'email', 'phone', 'seats', 'notes')
        labels = {
            'full_name': _('Your name'),
            'seats': _('How many seats?'),
            'notes': _('Anything we should know?'),
        }
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 3}),
            'phone': forms.TextInput(attrs={'placeholder': '+256 7XX XXX XXX'}),
        }

    def __init__(self, *args, event=None, user=None, **kwargs):
        self.event = event
        super().__init__(*args, **kwargs)
        if user is not None and user.is_authenticated:
            self.fields['full_name'].initial = user.display_name
            self.fields['email'].initial = user.email
        if event is not None and event.seats_left is not None:
            self.fields['seats'].widget.attrs['max'] = max(1, event.seats_left)

    def clean_seats(self):
        seats = self.cleaned_data['seats']
        if self.event is not None and self.event.capacity is not None:
            if seats > self.event.capacity:
                raise forms.ValidationError(
                    _('This event only holds %(n)s people in total.')
                    % {'n': self.event.capacity},
                )
        return seats
