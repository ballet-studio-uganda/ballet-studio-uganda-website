"""Sign-up, sign-in and people-management forms."""

from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from .models import (
    ApprovalStatus,
    GuardianProfile,
    Relationship,
    Role,
    STAFF_ROLES,
    StaffProfile,
    Student,
    StudentGuardian,
    User,
)

FIELD_CLASS = 'form-input'


class StyledFormMixin:
    """Applies the studio's input styling without a template pack per field."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            widget = field.widget
            existing = widget.attrs.get('class', '')
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs['class'] = f'{existing} form-check'.strip()
            elif isinstance(widget, forms.Select):
                widget.attrs['class'] = f'{existing} form-input form-select'.strip()
            elif isinstance(widget, forms.Textarea):
                widget.attrs.setdefault('rows', 4)
                widget.attrs['class'] = f'{existing} {FIELD_CLASS}'.strip()
            else:
                widget.attrs['class'] = f'{existing} {FIELD_CLASS}'.strip()
            if field.required:
                widget.attrs['required'] = 'required'


class StudioLoginForm(StyledFormMixin, AuthenticationForm):
    username = forms.CharField(
        label=_('Email or username'),
        widget=forms.TextInput(attrs={'autofocus': True, 'autocomplete': 'username',
                                      'placeholder': 'you@example.com'}),
    )
    password = forms.CharField(
        label=_('Password'),
        widget=forms.PasswordInput(attrs={'autocomplete': 'current-password',
                                          'placeholder': '••••••••'}),
    )
    remember_me = forms.BooleanField(required=False, initial=True, label=_('Keep me signed in'))

    error_messages = {
        'invalid_login': _('That email/username and password do not match an account.'),
        'inactive': _('This account has been deactivated. Please contact the studio office.'),
    }

    def confirm_login_allowed(self, user):
        # Unverified users are allowed *in* -- they land on the holding page.
        if not user.is_active:
            raise ValidationError(self.error_messages['inactive'], code='inactive')


class BaseSignupForm(StyledFormMixin, UserCreationForm):
    """
    Shared sign-up fields. Every registration lands as PENDING; an
    administrator verifies it before the account can do anything.
    """

    first_name = forms.CharField(max_length=150, label=_('First name'))
    last_name = forms.CharField(max_length=150, label=_('Surname'))
    email = forms.EmailField(label=_('Email address'))
    phone = forms.CharField(
        max_length=40, required=False, label=_('Phone number'),
        widget=forms.TextInput(attrs={'placeholder': '+256 7XX XXX XXX'}),
    )
    agree_to_terms = forms.BooleanField(
        required=True, label=_('I agree to the studio’s terms and privacy policy'),
    )

    signup_role = Role.PARENT

    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email', 'phone', 'username')

    def clean_email(self):
        email = self.cleaned_data['email'].lower().strip()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError(_('An account with this email already exists.'))
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.phone = self.cleaned_data.get('phone') or ''
        user.role = self.signup_role
        user.approval_status = ApprovalStatus.PENDING
        if commit:
            user.save()
        return user


class GuardianSignupForm(BaseSignupForm):
    signup_role = Role.PARENT

    occupation = forms.CharField(max_length=120, required=False, label=_('Occupation'))
    residential_address = forms.CharField(
        max_length=255, required=False, label=_('Home address'),
    )
    child_names = forms.CharField(
        required=False, label=_('Names of your children who dance with us'),
        widget=forms.Textarea(attrs={
            'rows': 2,
            'placeholder': 'One name per line — helps us match your account to their records.',
        }),
        help_text=_('Optional, but it speeds up verification.'),
    )

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            GuardianProfile.objects.create(
                user=user,
                occupation=self.cleaned_data.get('occupation', ''),
                residential_address=self.cleaned_data.get('residential_address', ''),
                notes=(
                    f"Children named at sign-up:\n{self.cleaned_data.get('child_names', '')}"
                    if self.cleaned_data.get('child_names') else ''
                ),
            )
        return user


class StaffSignupForm(BaseSignupForm):
    signup_role = Role.TEACHER

    role = forms.ChoiceField(
        choices=[
            (Role.TEACHER, _('Teacher')),
            (Role.ADMIN, _('Administrator')),
            (Role.DIRECTOR, _('Creative Director')),
        ],
        label=_('Your role at the studio'),
    )
    job_title = forms.CharField(max_length=120, required=False, label=_('Job title'))
    qualifications = forms.CharField(
        required=False, label=_('Training and qualifications'),
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'One per line'}),
    )

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = self.cleaned_data['role']
        if commit:
            user.save()
            StaffProfile.objects.create(
                user=user,
                job_title=self.cleaned_data.get('job_title', ''),
                qualifications=self.cleaned_data.get('qualifications', ''),
            )
        return user


class StudentSignupForm(BaseSignupForm):
    """
    For dancers old enough to hold their own login. The account is linked to
    an existing :class:`Student` record by an administrator during verification.
    """

    signup_role = Role.STUDENT

    date_of_birth = forms.DateField(
        label=_('Date of birth'), widget=forms.DateInput(attrs={'type': 'date'}),
    )
    student_id = forms.CharField(
        max_length=20, required=False, label=_('Student ID'),
        widget=forms.TextInput(attrs={'placeholder': 'BDSU-2026-0001'}),
        help_text=_('On your enrolment letter. Leave blank if you do not have it.'),
    )
    guardian_email = forms.EmailField(
        required=False, label=_('Parent or guardian’s email'),
    )

    def clean_student_id(self):
        value = (self.cleaned_data.get('student_id') or '').strip().upper()
        if value and not Student.objects.filter(student_id=value).exists():
            raise ValidationError(_('No dancer found with that student ID.'))
        return value

    def save(self, commit=True):
        user = super().save(commit=False)
        user.date_of_birth = self.cleaned_data['date_of_birth']
        if commit:
            user.save()
            student_id = self.cleaned_data.get('student_id')
            if student_id:
                Student.objects.filter(student_id=student_id, user__isnull=True).update(user=user)
        return user


# ---------------------------------------------------------------------------
# Profile editing
# ---------------------------------------------------------------------------
class ProfileForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = (
            'first_name', 'last_name', 'email', 'phone', 'whatsapp', 'photo',
            'date_of_birth', 'gender', 'address', 'city', 'country',
            'receives_email', 'receives_sms',
        )
        widgets = {'date_of_birth': forms.DateInput(attrs={'type': 'date'})}

    def clean_email(self):
        email = self.cleaned_data['email'].lower().strip()
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise ValidationError(_('Another account already uses this email.'))
        return email


class StaffProfileForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = StaffProfile
        fields = (
            'job_title', 'employment_type', 'date_joined_studio', 'short_bio', 'bio',
            'qualifications', 'specialisms', 'years_of_experience',
            'emergency_contact_name', 'emergency_contact_phone',
            'emergency_contact_relationship',
            'show_on_website', 'website_order',
            'instagram_url', 'facebook_url', 'linkedin_url',
        )
        widgets = {'date_joined_studio': forms.DateInput(attrs={'type': 'date'})}


class StaffPayrollForm(StyledFormMixin, forms.ModelForm):
    """Pay details -- only ever shown to directors and administrators."""

    class Meta:
        model = StaffProfile
        fields = (
            'monthly_salary', 'hourly_rate', 'bank_name', 'bank_account_name',
            'bank_account_number', 'mobile_money_number', 'national_id', 'tin_number',
            'is_active_staff', 'date_left_studio',
        )
        widgets = {'date_left_studio': forms.DateInput(attrs={'type': 'date'})}


class GuardianProfileForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = GuardianProfile
        fields = (
            'occupation', 'employer', 'alternate_phone', 'national_id',
            'residential_address', 'postal_address', 'preferred_contact_method',
            'receives_invoices', 'receives_progress_reports',
            'emergency_contact_name', 'emergency_contact_phone',
            'emergency_contact_relationship',
        )


# ---------------------------------------------------------------------------
# Administrator tools
# ---------------------------------------------------------------------------
class UserVerificationForm(StyledFormMixin, forms.Form):
    """Approve, reject or suspend a pending account, optionally changing its role."""

    DECISION_CHOICES = [
        (ApprovalStatus.APPROVED, _('Approve this account')),
        (ApprovalStatus.REJECTED, _('Reject this account')),
        (ApprovalStatus.SUSPENDED, _('Suspend this account')),
    ]

    decision = forms.ChoiceField(choices=DECISION_CHOICES, widget=forms.RadioSelect)
    role = forms.ChoiceField(
        choices=Role.choices, required=False,
        help_text=_('Correct the role if the applicant chose the wrong one.'),
    )
    note = forms.CharField(
        required=False, widget=forms.Textarea(attrs={'rows': 3}),
        label=_('Internal note'),
        help_text=_('Recorded against the account. Not shown to the applicant.'),
    )


class StaffUserForm(StyledFormMixin, forms.ModelForm):
    """Administrator creating a staff account directly, no self sign-up."""

    class Meta:
        model = User
        fields = (
            'first_name', 'last_name', 'email', 'username', 'phone',
            'role', 'photo', 'gender', 'address', 'city',
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['role'].choices = [
            (value, label) for value, label in Role.choices if value in STAFF_ROLES
        ]


class StudentForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Student
        fields = (
            'first_name', 'middle_name', 'last_name', 'preferred_name',
            'date_of_birth', 'gender', 'photo', 'status', 'enrolment_date',
            'school_name', 'home_address', 'how_heard_about_us',
            'previous_dance_experience',
            'height_cm', 'leotard_size', 'shoe_size',
            'blood_group', 'sickle_cell_status', 'medical_conditions', 'allergies',
            'medication', 'doctor_name', 'doctor_phone', 'medical_notes',
            'photo_consent', 'media_consent', 'medical_treatment_consent',
            'notes',
        )
        widgets = {
            'date_of_birth': forms.DateInput(attrs={'type': 'date'}),
            'enrolment_date': forms.DateInput(attrs={'type': 'date'}),
        }


class StudentGuardianForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = StudentGuardian
        fields = (
            'guardian', 'relationship', 'is_primary', 'is_emergency_contact',
            'can_collect', 'receives_invoices',
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['guardian'].queryset = (
            GuardianProfile.objects.select_related('user').order_by('user__first_name')
        )


class UserSearchForm(StyledFormMixin, forms.Form):
    q = forms.CharField(
        required=False, label='',
        widget=forms.TextInput(attrs={
            'placeholder': 'Search by name, email or ID…',
            'hx-trigger': 'keyup changed delay:350ms, search',
        }),
    )
    role = forms.ChoiceField(
        required=False, label='',
        choices=[('', 'All roles')] + list(Role.choices),
    )
    status = forms.ChoiceField(
        required=False, label='',
        choices=[('', 'All statuses')] + list(ApprovalStatus.choices),
    )
