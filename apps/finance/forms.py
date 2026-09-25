"""Forms for recording money in and money out."""

from __future__ import annotations

import datetime as dt

from django import forms
from django.core.exceptions import ValidationError
from django.forms import inlineformset_factory
from django.utils.translation import gettext_lazy as _

from apps.accounts.forms import StyledFormMixin
from apps.accounts.models import StaffProfile, Student

from .services import PERIOD_CHOICES
from .models import (
    REFERENCED_METHODS,
    Expense,
    FeeStructure,
    Invoice,
    InvoiceItem,
    OtherIncome,
    PayrollEntry,
    Payment,
)


class PaymentForm(StyledFormMixin, forms.ModelForm):
    """
    Record a payment the studio has already physically received.

    The date and time are those on the mobile money SMS or bank slip, not the
    moment this form is filled in — that is what makes reconciliation possible.
    """

    class Meta:
        model = Payment
        fields = (
            'invoice', 'student', 'amount',
            'payment_date', 'payment_time',
            'method', 'transaction_id',
            'payer_name', 'payer_phone', 'bank_name', 'account_number',
            'received_by', 'status', 'proof', 'notes',
        )
        labels = {
            'payment_date': _('Date the payment was made'),
            'payment_time': _('Time on the SMS / slip'),
            'transaction_id': _('Transaction ID / reference'),
            'received_by': _('Received by'),
            'proof': _('Photo of the receipt or SMS'),
        }
        help_texts = {
            'payment_time': _('Optional, but it makes reconciliation far easier.'),
            'payer_name': _('Whose account or hand the money came from.'),
        }
        widgets = {
            'payment_date': forms.DateInput(attrs={'type': 'date'}),
            'payment_time': forms.TimeInput(attrs={'type': 'time'}),
            'amount': forms.NumberInput(attrs={'step': '1', 'min': '0',
                                               'placeholder': 'e.g. 250000'}),
            'transaction_id': forms.TextInput(attrs={
                'placeholder': 'e.g. MP240915.1423.A12345',
                'autocomplete': 'off',
            }),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, invoice=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['student'].queryset = Student.objects.active().order_by('first_name')
        self.fields['invoice'].queryset = (
            Invoice.objects.open().select_related('student').order_by('-issue_date')
        )
        self.fields['invoice'].required = False
        self.fields['student'].required = False
        self.fields['payment_date'].initial = dt.date.today()

        if invoice is not None:
            self.fields['invoice'].initial = invoice
            self.fields['student'].initial = invoice.student
            self.fields['amount'].initial = invoice.balance
            self.fields['invoice'].widget = forms.HiddenInput()

        # Mark the methods that require a reference, for the inline hint.
        self.fields['method'].widget.attrs['data-referenced'] = ','.join(
            sorted(REFERENCED_METHODS)
        )

    def clean(self):
        cleaned = super().clean()
        method = cleaned.get('method')
        reference = (cleaned.get('transaction_id') or '').strip()
        invoice = cleaned.get('invoice')
        student = cleaned.get('student')
        amount = cleaned.get('amount')

        if method in REFERENCED_METHODS and not reference:
            self.add_error(
                'transaction_id',
                _('A transaction ID is required for %(m)s payments.')
                % {'m': dict(self.fields["method"].choices).get(method, method)},
            )

        if not invoice and not student:
            raise ValidationError(
                _('Attach the payment to an invoice, or at least to a dancer.'),
            )

        if invoice and amount and amount > invoice.balance:
            over = amount - invoice.balance
            self.add_error(
                'amount',
                _('That is UGX %(over)s more than the outstanding balance of '
                  'UGX %(bal)s. Record the excess as a separate credit if intended.')
                % {'over': f'{over:,.0f}', 'bal': f'{invoice.balance:,.0f}'},
            )

        if reference and method:
            clash = Payment.objects.filter(
                transaction_id__iexact=reference, method=method,
            ).exclude(pk=self.instance.pk)
            if clash.exists():
                self.add_error(
                    'transaction_id',
                    _('Transaction %(ref)s has already been recorded (receipt %(r)s).')
                    % {'ref': reference, 'r': clash.first().receipt_number},
                )
        return cleaned


class InvoiceForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Invoice
        fields = (
            'student', 'term', 'issue_date', 'due_date',
            'discount_amount', 'discount_reason', 'notes', 'internal_notes',
        )
        widgets = {
            'issue_date': forms.DateInput(attrs={'type': 'date'}),
            'due_date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={
                'rows': 2, 'placeholder': 'Shown to the family on the invoice.',
            }),
            'internal_notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, student=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['student'].queryset = Student.objects.active().order_by('first_name')
        if student is not None:
            self.fields['student'].initial = student
        if not self.instance.pk:
            self.fields['issue_date'].initial = dt.date.today()
            self.fields['due_date'].initial = dt.date.today() + dt.timedelta(days=14)

    def clean(self):
        cleaned = super().clean()
        issue, due = cleaned.get('issue_date'), cleaned.get('due_date')
        if issue and due and due < issue:
            self.add_error('due_date', _('The due date cannot precede the issue date.'))
        return cleaned


class InvoiceItemForm(forms.ModelForm):
    class Meta:
        model = InvoiceItem
        fields = ('description', 'fee_category', 'fee_structure', 'quantity', 'unit_amount')
        widgets = {
            'description': forms.TextInput(attrs={
                'class': 'form-input', 'placeholder': 'e.g. Term 1 tuition — Junior Ballet',
            }),
            'fee_category': forms.Select(attrs={'class': 'form-input form-select'}),
            'fee_structure': forms.Select(attrs={
                'class': 'form-input form-select js-fee-picker',
            }),
            'quantity': forms.NumberInput(attrs={'class': 'form-input', 'step': '1', 'min': '1'}),
            'unit_amount': forms.NumberInput(attrs={'class': 'form-input', 'step': '1', 'min': '0'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['fee_structure'].queryset = (
            FeeStructure.objects.filter(is_active=True).select_related('category', 'program')
        )
        self.fields['fee_structure'].required = False
        self.fields['fee_category'].required = False


InvoiceItemFormSet = inlineformset_factory(
    Invoice, InvoiceItem, form=InvoiceItemForm, extra=3, can_delete=True,
)


class ExpenseForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Expense
        fields = (
            'category', 'description', 'amount',
            'expense_date', 'expense_time', 'method', 'transaction_id',
            'payee_name', 'payee_contact', 'invoice_reference',
            'event', 'term', 'status', 'receipt', 'notes',
        )
        labels = {
            'expense_date': _('Date paid'),
            'expense_time': _('Time paid'),
            'transaction_id': _('Transaction ID / reference'),
            'invoice_reference': _('Supplier’s invoice number'),
            'receipt': _('Photo of the receipt'),
            'event': _('Attribute to an event'),
        }
        widgets = {
            'expense_date': forms.DateInput(attrs={'type': 'date'}),
            'expense_time': forms.TimeInput(attrs={'type': 'time'}),
            'amount': forms.NumberInput(attrs={'step': '1', 'min': '0'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields['expense_date'].initial = dt.date.today()
        self.fields['event'].required = False
        self.fields['term'].required = False

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('method') in REFERENCED_METHODS and not (
            cleaned.get('transaction_id') or ''
        ).strip():
            self.add_error(
                'transaction_id',
                _('A transaction ID or reference is required for this payment method.'),
            )
        return cleaned


class OtherIncomeForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = OtherIncome
        fields = (
            'category', 'description', 'amount',
            'received_date', 'received_time', 'method', 'transaction_id',
            'source_name', 'source_contact', 'event', 'status', 'proof', 'notes',
        )
        labels = {
            'source_name': _('Donor / sponsor / buyer'),
            'event': _('Attribute to an event'),
        }
        widgets = {
            'received_date': forms.DateInput(attrs={'type': 'date'}),
            'received_time': forms.TimeInput(attrs={'type': 'time'}),
            'amount': forms.NumberInput(attrs={'step': '1', 'min': '0'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields['received_date'].initial = dt.date.today()
        self.fields['event'].required = False


class PayrollEntryForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = PayrollEntry
        fields = (
            'staff', 'period_start', 'period_end',
            'gross_amount', 'allowances', 'deductions', 'deduction_reason',
            'paid_date', 'paid_time', 'method', 'transaction_id', 'status', 'notes',
        )
        widgets = {
            'period_start': forms.DateInput(attrs={'type': 'date'}),
            'period_end': forms.DateInput(attrs={'type': 'date'}),
            'paid_date': forms.DateInput(attrs={'type': 'date'}),
            'paid_time': forms.TimeInput(attrs={'type': 'time'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['staff'].queryset = (
            StaffProfile.objects.filter(is_active_staff=True)
            .select_related('user').order_by('user__first_name')
        )

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get('period_start'), cleaned.get('period_end')
        if start and end and end < start:
            self.add_error('period_end', _('The period must end after it starts.'))
        gross = cleaned.get('gross_amount') or 0
        deductions = cleaned.get('deductions') or 0
        if deductions > gross:
            self.add_error('deductions', _('Deductions cannot exceed gross pay.'))
        return cleaned


class ReportFilterForm(StyledFormMixin, forms.Form):
    """Drives the period selector on the reports page."""

    period = forms.ChoiceField(
        choices=PERIOD_CHOICES, required=False, initial='month', label='',
    )
    start_date = forms.DateField(
        required=False, label=_('From'), widget=forms.DateInput(attrs={'type': 'date'}),
    )
    end_date = forms.DateField(
        required=False, label=_('To'), widget=forms.DateInput(attrs={'type': 'date'}),
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('period') == 'custom':
            if not cleaned.get('start_date') or not cleaned.get('end_date'):
                raise ValidationError(_('Choose both a start and an end date.'))
            if cleaned['end_date'] < cleaned['start_date']:
                raise ValidationError(_('The end date must fall after the start date.'))
        return cleaned
