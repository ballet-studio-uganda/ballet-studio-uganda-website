"""
Money in, money out.

The studio takes payments physically -- cash at the desk, MTN/Airtel mobile
money, bank deposits and transfers -- so nothing here talks to a payment
gateway. What it does instead is record each transaction in enough detail
(date, time, method, transaction ID, who received it) that any figure on a
report can be traced back to a real receipt months later.

All amounts are in UGX.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import Max, Sum
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import Student, TimeStampedModel, _next_sequence
from apps.academics.models import Program, Term

ZERO = Decimal('0.00')


# ---------------------------------------------------------------------------
# Choices
# ---------------------------------------------------------------------------
class PaymentMethod(models.TextChoices):
    """How the money physically arrived."""

    CASH = 'cash', _('Cash')
    MTN_MOMO = 'mtn_momo', _('MTN Mobile Money')
    AIRTEL_MONEY = 'airtel_money', _('Airtel Money')
    BANK_DEPOSIT = 'bank_deposit', _('Bank deposit')
    BANK_TRANSFER = 'bank_transfer', _('Bank transfer / EFT')
    CHEQUE = 'cheque', _('Cheque')
    CARD = 'card', _('Card (POS)')
    IN_KIND = 'in_kind', _('In kind')
    OTHER = 'other', _('Other')


#: Methods where a transaction ID is expected, and its absence is a red flag.
REFERENCED_METHODS = frozenset({
    PaymentMethod.MTN_MOMO,
    PaymentMethod.AIRTEL_MONEY,
    PaymentMethod.BANK_DEPOSIT,
    PaymentMethod.BANK_TRANSFER,
    PaymentMethod.CHEQUE,
    PaymentMethod.CARD,
})


class InvoiceStatus(models.TextChoices):
    DRAFT = 'draft', _('Draft')
    ISSUED = 'issued', _('Issued')
    PART_PAID = 'part_paid', _('Partially paid')
    PAID = 'paid', _('Paid in full')
    OVERDUE = 'overdue', _('Overdue')
    CANCELLED = 'cancelled', _('Cancelled')
    WRITTEN_OFF = 'written_off', _('Written off')


#: Invoices that still represent money the studio expects to receive.
OPEN_INVOICE_STATUSES = frozenset({
    InvoiceStatus.ISSUED, InvoiceStatus.PART_PAID, InvoiceStatus.OVERDUE,
})


class TransactionStatus(models.TextChoices):
    PENDING = 'pending', _('Pending confirmation')
    CONFIRMED = 'confirmed', _('Confirmed')
    REVERSED = 'reversed', _('Reversed')
    FAILED = 'failed', _('Failed / bounced')


class ExpenseStatus(models.TextChoices):
    DRAFT = 'draft', _('Draft')
    AWAITING = 'awaiting', _('Awaiting approval')
    APPROVED = 'approved', _('Approved')
    PAID = 'paid', _('Paid')
    REJECTED = 'rejected', _('Rejected')


class BillingCycle(models.TextChoices):
    ONE_OFF = 'one_off', _('One off')
    PER_TERM = 'per_term', _('Per term')
    MONTHLY = 'monthly', _('Monthly')
    PER_SESSION = 'per_session', _('Per session')
    ANNUAL = 'annual', _('Annual')


class DiscountType(models.TextChoices):
    PERCENT = 'percent', _('Percentage')
    FIXED = 'fixed', _('Fixed amount')


# ---------------------------------------------------------------------------
# Fee catalogue
# ---------------------------------------------------------------------------
class FeeCategory(models.Model):
    """Tuition, registration, costume, recital, uniform, trip, exam..."""

    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=20, unique=True, blank=True)
    description = models.TextField(blank=True)
    is_tuition = models.BooleanField(
        default=False, help_text=_('Counts as core teaching income in reports.'),
    )
    colour = models.CharField(max_length=7, default='#EE2A7B')
    display_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = _('fee category')
        verbose_name_plural = _('fee categories')
        ordering = ('display_order', 'name')

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self.name.upper().replace(' ', '_')[:20]
        super().save(*args, **kwargs)


class FeeStructure(TimeStampedModel):
    """
    The price list. One row per (programme, term, category) so the studio can
    raise Junior Ballet tuition without touching Kinder Ballet.
    """

    name = models.CharField(max_length=160)
    category = models.ForeignKey(FeeCategory, on_delete=models.PROTECT, related_name='fees')
    program = models.ForeignKey(
        Program, null=True, blank=True, on_delete=models.CASCADE, related_name='fees',
        help_text=_('Leave empty to apply to every programme.'),
    )
    term = models.ForeignKey(
        Term, null=True, blank=True, on_delete=models.CASCADE, related_name='fees',
        help_text=_('Leave empty for a standing fee that carries across terms.'),
    )
    amount = models.DecimalField(
        max_digits=14, decimal_places=2, validators=[MinValueValidator(ZERO)],
    )
    billing_cycle = models.CharField(
        max_length=20, choices=BillingCycle.choices, default=BillingCycle.PER_TERM,
    )
    is_mandatory = models.BooleanField(default=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = _('fee')
        verbose_name_plural = _('fee structure')
        ordering = ('category__display_order', 'program__display_order', 'name')

    def __str__(self):
        scope = self.program.name if self.program else 'All programmes'
        return f'{self.name} - {scope} - UGX {self.amount:,.0f}'


class Scholarship(TimeStampedModel):
    """
    A bursary or discount granted to a dancer. Applied automatically when
    invoices are generated.
    """

    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name='scholarships',
    )
    name = models.CharField(max_length=140, help_text=_('e.g. "Sickle Cell Warriors Bursary"'))
    discount_type = models.CharField(
        max_length=20, choices=DiscountType.choices, default=DiscountType.PERCENT,
    )
    value = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(ZERO)],
        help_text=_('A percentage (0-100) or a fixed UGX amount, per the type above.'),
    )
    applies_to_category = models.ForeignKey(
        FeeCategory, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='scholarships', help_text=_('Leave empty to discount the whole invoice.'),
    )
    sponsor = models.CharField(max_length=160, blank=True)
    reason = models.TextField(blank=True)
    starts_on = models.DateField(default=dt.date.today)
    ends_on = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='scholarships_approved',
    )

    class Meta:
        ordering = ('-starts_on',)

    def __str__(self):
        return f'{self.student.full_name} - {self.name}'

    @property
    def is_current(self):
        today = dt.date.today()
        return (
            self.is_active
            and self.starts_on <= today
            and (self.ends_on is None or self.ends_on >= today)
        )

    def discount_on(self, amount):
        if self.discount_type == DiscountType.PERCENT:
            return (amount * self.value / Decimal('100')).quantize(Decimal('0.01'))
        return min(self.value, amount)


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------
class InvoiceQuerySet(models.QuerySet):
    def open(self):
        return self.filter(status__in=OPEN_INVOICE_STATUSES)

    def overdue(self):
        return self.open().filter(due_date__lt=dt.date.today())

    def for_guardian(self, guardian):
        return self.filter(student__guardian_links__guardian=guardian).distinct()

    def outstanding_total(self):
        rows = self.open().aggregate(
            billed=Sum('total_amount'), paid=Sum('amount_paid'),
        )
        return (rows['billed'] or ZERO) - (rows['paid'] or ZERO)


class Invoice(TimeStampedModel):
    """What a family owes for a term."""

    number = models.CharField(max_length=24, unique=True, blank=True, editable=False)
    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name='invoices')
    term = models.ForeignKey(
        Term, null=True, blank=True, on_delete=models.SET_NULL, related_name='invoices',
    )

    issue_date = models.DateField(default=dt.date.today)
    due_date = models.DateField()
    status = models.CharField(
        max_length=20, choices=InvoiceStatus.choices, default=InvoiceStatus.DRAFT, db_index=True,
    )

    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)
    discount_amount = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)
    amount_paid = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)

    discount_reason = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)
    internal_notes = models.TextField(blank=True)

    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='invoices_issued',
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    last_reminder_at = models.DateTimeField(null=True, blank=True)
    reminder_count = models.PositiveSmallIntegerField(default=0)

    objects = InvoiceQuerySet.as_manager()

    class Meta:
        ordering = ('-issue_date', '-number')
        indexes = [
            models.Index(fields=('status', 'due_date')),
            models.Index(fields=('student', 'status')),
        ]

    def __str__(self):
        return f'{self.number} - {self.student.full_name} - UGX {self.total_amount:,.0f}'

    def get_absolute_url(self):
        return reverse('finance:invoice_detail', args=[self.pk])

    # -- derived -----------------------------------------------------------
    @property
    def balance(self):
        return self.total_amount - self.amount_paid

    @property
    def is_settled(self):
        return self.balance <= ZERO

    @property
    def is_overdue(self):
        return (
            self.status in OPEN_INVOICE_STATUSES
            and self.due_date < dt.date.today()
            and not self.is_settled
        )

    @property
    def days_overdue(self):
        if not self.is_overdue:
            return 0
        return (dt.date.today() - self.due_date).days

    @property
    def percent_paid(self):
        if self.total_amount <= ZERO:
            return 100
        return min(100, round(self.amount_paid / self.total_amount * 100))

    # -- maintenance -------------------------------------------------------
    def recalculate(self, save=True):
        """Re-derive subtotal, paid amount and status from the child rows."""
        self.subtotal = self.items.aggregate(t=Sum('amount'))['t'] or ZERO
        self.total_amount = max(ZERO, self.subtotal - self.discount_amount)
        self.amount_paid = (
            self.payments.filter(status=TransactionStatus.CONFIRMED)
            .aggregate(t=Sum('amount'))['t'] or ZERO
        )

        if self.status not in {InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED,
                               InvoiceStatus.WRITTEN_OFF}:
            if self.is_settled:
                self.status = InvoiceStatus.PAID
            elif self.amount_paid > ZERO:
                self.status = InvoiceStatus.PART_PAID
            elif self.due_date < dt.date.today():
                self.status = InvoiceStatus.OVERDUE
            else:
                self.status = InvoiceStatus.ISSUED

        if save:
            super().save(update_fields=[
                'subtotal', 'total_amount', 'amount_paid', 'status', 'updated_at',
            ])
        return self

    def apply_scholarships(self):
        """Set ``discount_amount`` from the dancer's live bursaries."""
        total = ZERO
        reasons = []
        for scholarship in self.student.scholarships.all():
            if not scholarship.is_current:
                continue
            if scholarship.applies_to_category_id:
                base = self.items.filter(
                    fee_category=scholarship.applies_to_category_id,
                ).aggregate(t=Sum('amount'))['t'] or ZERO
            else:
                base = self.subtotal
            if base > ZERO:
                total += scholarship.discount_on(base)
                reasons.append(scholarship.name)
        self.discount_amount = min(total, self.subtotal)
        self.discount_reason = ', '.join(reasons)
        return self.discount_amount

    def issue(self, by=None):
        self.status = InvoiceStatus.ISSUED
        self.issued_by = by
        self.sent_at = timezone.now()
        self.save(update_fields=['status', 'issued_by', 'sent_at', 'updated_at'])
        self.recalculate()

    def save(self, *args, **kwargs):
        if not self.number:
            with transaction.atomic():
                self.number = _next_sequence(Invoice, 'number', 'INV', width=5)
                return super().save(*args, **kwargs)
        super().save(*args, **kwargs)


class InvoiceItem(models.Model):
    """A single billed line."""

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='items')
    fee_category = models.ForeignKey(
        FeeCategory, null=True, blank=True, on_delete=models.SET_NULL, related_name='invoice_items',
    )
    fee_structure = models.ForeignKey(
        FeeStructure, null=True, blank=True, on_delete=models.SET_NULL, related_name='invoice_items',
    )
    description = models.CharField(max_length=220)
    quantity = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('1.00'))
    unit_amount = models.DecimalField(
        max_digits=14, decimal_places=2, validators=[MinValueValidator(ZERO)],
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)

    class Meta:
        verbose_name = _('invoice line')
        ordering = ('id',)

    def __str__(self):
        return f'{self.description} - UGX {self.amount:,.0f}'

    def save(self, *args, **kwargs):
        self.amount = (self.quantity * self.unit_amount).quantize(Decimal('0.01'))
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Payments received
# ---------------------------------------------------------------------------
class PaymentQuerySet(models.QuerySet):
    def confirmed(self):
        return self.filter(status=TransactionStatus.CONFIRMED)

    def in_period(self, start, end):
        return self.filter(payment_date__gte=start, payment_date__lte=end)

    def total(self):
        return self.confirmed().aggregate(t=Sum('amount'))['t'] or ZERO


class Payment(TimeStampedModel):
    """
    A physical payment recorded by a member of staff.

    Everything needed to reconcile against an MTN statement or a bank slip
    lives here: the date AND time it was made, the method, the network's
    transaction ID, who handed it over and who took it.
    """

    receipt_number = models.CharField(max_length=24, unique=True, blank=True, editable=False)

    invoice = models.ForeignKey(
        Invoice, null=True, blank=True, on_delete=models.SET_NULL, related_name='payments',
        help_text=_('Leave empty for a payment not tied to a specific invoice.'),
    )
    student = models.ForeignKey(
        Student, null=True, blank=True, on_delete=models.SET_NULL, related_name='payments',
    )

    amount = models.DecimalField(
        max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))],
    )

    # When the money actually moved -- not when it was typed in.
    payment_date = models.DateField(default=dt.date.today, db_index=True)
    payment_time = models.TimeField(
        null=True, blank=True,
        help_text=_('Time on the mobile money SMS or bank slip, if known.'),
    )

    method = models.CharField(
        max_length=20, choices=PaymentMethod.choices, default=PaymentMethod.CASH, db_index=True,
    )
    transaction_id = models.CharField(
        _('transaction ID'), max_length=80, blank=True, db_index=True,
        help_text=_('MTN/Airtel transaction ID, bank reference or cheque number.'),
    )
    payer_name = models.CharField(
        max_length=140, blank=True, help_text=_('Name on the account the money came from.'),
    )
    payer_phone = models.CharField(max_length=40, blank=True)
    bank_name = models.CharField(max_length=120, blank=True)
    account_number = models.CharField(max_length=60, blank=True)

    status = models.CharField(
        max_length=20, choices=TransactionStatus.choices,
        default=TransactionStatus.CONFIRMED, db_index=True,
    )
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='payments_received',
        help_text=_('The staff member who took the money.'),
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='payments_recorded',
    )
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='payments_confirmed',
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)

    proof = models.FileField(
        upload_to='finance/payment-proof/%Y/%m/', blank=True,
        help_text=_('Photo of the receipt, deposit slip or mobile money SMS.'),
    )
    notes = models.TextField(blank=True)
    reversal_reason = models.CharField(max_length=200, blank=True)

    objects = PaymentQuerySet.as_manager()

    class Meta:
        ordering = ('-payment_date', '-payment_time', '-created_at')
        indexes = [
            models.Index(fields=('payment_date', 'method')),
            models.Index(fields=('status', 'payment_date')),
        ]

    def __str__(self):
        return f'{self.receipt_number} - UGX {self.amount:,.0f} ({self.get_method_display()})'

    def get_absolute_url(self):
        return reverse('finance:payment_detail', args=[self.pk])

    def clean(self):
        if self.method in REFERENCED_METHODS and not self.transaction_id.strip():
            raise ValidationError({
                'transaction_id': _(
                    'A transaction ID or reference is required for %(method)s payments.'
                ) % {'method': self.get_method_display()},
            })
        if self.payment_date > dt.date.today():
            raise ValidationError({'payment_date': _('A payment cannot be dated in the future.')})

    @property
    def paid_at(self):
        """Date and time combined, for sorting and receipts."""
        return dt.datetime.combine(self.payment_date, self.payment_time or dt.time.min)

    @property
    def needs_reference(self):
        return self.method in REFERENCED_METHODS

    @property
    def is_confirmed(self):
        return self.status == TransactionStatus.CONFIRMED

    def confirm(self, by=None):
        self.status = TransactionStatus.CONFIRMED
        self.confirmed_by = by
        self.confirmed_at = timezone.now()
        self.save(update_fields=['status', 'confirmed_by', 'confirmed_at', 'updated_at'])
        if self.invoice_id:
            self.invoice.recalculate()

    def reverse_payment(self, by=None, reason=''):
        self.status = TransactionStatus.REVERSED
        self.reversal_reason = reason
        self.confirmed_by = by
        self.save(update_fields=['status', 'reversal_reason', 'confirmed_by', 'updated_at'])
        if self.invoice_id:
            self.invoice.recalculate()

    def save(self, *args, **kwargs):
        if not self.receipt_number:
            with transaction.atomic():
                self.receipt_number = _next_sequence(Payment, 'receipt_number', 'RCP', width=5)
                super().save(*args, **kwargs)
                if self.invoice_id:
                    self.invoice.recalculate()
                return
        super().save(*args, **kwargs)
        if self.invoice_id:
            self.invoice.recalculate()


# ---------------------------------------------------------------------------
# Other income
# ---------------------------------------------------------------------------
class IncomeCategory(models.Model):
    """Donations, recital tickets, merchandise, sponsorship, hall hire..."""

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    colour = models.CharField(max_length=7, default='#c9a84c')
    display_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = _('income category')
        verbose_name_plural = _('income categories')
        ordering = ('display_order', 'name')

    def __str__(self):
        return self.name


class OtherIncome(TimeStampedModel):
    """Studio income that is not a student fee."""

    reference = models.CharField(max_length=24, unique=True, blank=True, editable=False)
    category = models.ForeignKey(IncomeCategory, on_delete=models.PROTECT, related_name='entries')
    description = models.CharField(max_length=220)
    amount = models.DecimalField(
        max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))],
    )

    received_date = models.DateField(default=dt.date.today, db_index=True)
    received_time = models.TimeField(null=True, blank=True)
    method = models.CharField(
        max_length=20, choices=PaymentMethod.choices, default=PaymentMethod.CASH,
    )
    transaction_id = models.CharField(max_length=80, blank=True)
    source_name = models.CharField(
        max_length=160, blank=True, help_text=_('Donor, sponsor or buyer.'),
    )
    source_contact = models.CharField(max_length=120, blank=True)

    event = models.ForeignKey(
        'events.Event', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='income_entries',
    )
    status = models.CharField(
        max_length=20, choices=TransactionStatus.choices, default=TransactionStatus.CONFIRMED,
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='income_recorded',
    )
    proof = models.FileField(upload_to='finance/income-proof/%Y/%m/', blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = _('other income')
        verbose_name_plural = _('other income')
        ordering = ('-received_date', '-created_at')

    def __str__(self):
        return f'{self.description} - UGX {self.amount:,.0f}'

    def save(self, *args, **kwargs):
        if not self.reference:
            with transaction.atomic():
                self.reference = _next_sequence(OtherIncome, 'reference', 'INC', width=5)
                return super().save(*args, **kwargs)
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Expenses
# ---------------------------------------------------------------------------
class ExpenseCategory(models.Model):
    """Rent, salaries, costumes, utilities, marketing, transport, equipment..."""

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    colour = models.CharField(max_length=7, default='#701344')
    is_recurring = models.BooleanField(
        default=False, help_text=_('A standing monthly cost such as rent or salaries.'),
    )
    display_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = _('expense category')
        verbose_name_plural = _('expense categories')
        ordering = ('display_order', 'name')

    def __str__(self):
        return self.name


class Expense(TimeStampedModel):
    """Money leaving the studio, with the same traceability as money coming in."""

    reference = models.CharField(max_length=24, unique=True, blank=True, editable=False)
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT, related_name='expenses')
    description = models.CharField(max_length=220)
    amount = models.DecimalField(
        max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))],
    )

    expense_date = models.DateField(default=dt.date.today, db_index=True)
    expense_time = models.TimeField(null=True, blank=True)
    method = models.CharField(
        max_length=20, choices=PaymentMethod.choices, default=PaymentMethod.CASH,
    )
    transaction_id = models.CharField(max_length=80, blank=True)

    payee_name = models.CharField(max_length=160, blank=True)
    payee_contact = models.CharField(max_length=120, blank=True)
    invoice_reference = models.CharField(
        max_length=80, blank=True, help_text=_("The supplier's own invoice number."),
    )

    event = models.ForeignKey(
        'events.Event', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='expenses', help_text=_('Attribute this cost to an event, e.g. the recital.'),
    )
    term = models.ForeignKey(
        Term, null=True, blank=True, on_delete=models.SET_NULL, related_name='expenses',
    )

    status = models.CharField(
        max_length=20, choices=ExpenseStatus.choices, default=ExpenseStatus.PAID, db_index=True,
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='expenses_recorded',
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='expenses_approved',
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    receipt = models.FileField(upload_to='finance/receipts/%Y/%m/', blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ('-expense_date', '-created_at')
        indexes = [
            models.Index(fields=('expense_date', 'category')),
            models.Index(fields=('status', 'expense_date')),
        ]

    def __str__(self):
        return f'{self.reference} - {self.description} - UGX {self.amount:,.0f}'

    def get_absolute_url(self):
        return reverse('finance:expense_detail', args=[self.pk])

    def clean(self):
        if self.expense_date > dt.date.today():
            raise ValidationError({'expense_date': _('An expense cannot be dated in the future.')})

    def approve(self, by=None):
        self.status = ExpenseStatus.APPROVED
        self.approved_by = by
        self.approved_at = timezone.now()
        self.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])

    def save(self, *args, **kwargs):
        if not self.reference:
            with transaction.atomic():
                self.reference = _next_sequence(Expense, 'reference', 'EXP', width=5)
                return super().save(*args, **kwargs)
        super().save(*args, **kwargs)


class PayrollEntry(TimeStampedModel):
    """A staff payment for a period. Feeds the salaries line of the expense report."""

    staff = models.ForeignKey(
        'accounts.StaffProfile', on_delete=models.PROTECT, related_name='payroll_entries',
    )
    period_start = models.DateField()
    period_end = models.DateField()

    gross_amount = models.DecimalField(
        max_digits=14, decimal_places=2, validators=[MinValueValidator(ZERO)],
    )
    allowances = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)
    deductions = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)
    deduction_reason = models.CharField(max_length=200, blank=True)
    net_amount = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)

    paid_date = models.DateField(null=True, blank=True)
    paid_time = models.TimeField(null=True, blank=True)
    method = models.CharField(
        max_length=20, choices=PaymentMethod.choices, default=PaymentMethod.MTN_MOMO,
    )
    transaction_id = models.CharField(max_length=80, blank=True)

    status = models.CharField(
        max_length=20, choices=ExpenseStatus.choices, default=ExpenseStatus.AWAITING,
    )
    expense = models.OneToOneField(
        Expense, null=True, blank=True, on_delete=models.SET_NULL, related_name='payroll_entry',
        help_text=_('The expense row this payment created, for the books.'),
    )
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='payroll_processed',
    )
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = _('payroll entry')
        verbose_name_plural = _('payroll')
        ordering = ('-period_start',)
        constraints = [
            models.UniqueConstraint(
                fields=('staff', 'period_start', 'period_end'), name='unique_payroll_period',
            ),
        ]

    def __str__(self):
        return f'{self.staff.user.display_name} - {self.period_start:%b %Y} - UGX {self.net_amount:,.0f}'

    def save(self, *args, **kwargs):
        self.net_amount = self.gross_amount + self.allowances - self.deductions
        super().save(*args, **kwargs)


class Budget(TimeStampedModel):
    """A planned spend for a category over a period, for variance reporting."""

    name = models.CharField(max_length=140)
    category = models.ForeignKey(
        ExpenseCategory, null=True, blank=True, on_delete=models.CASCADE, related_name='budgets',
    )
    term = models.ForeignKey(
        Term, null=True, blank=True, on_delete=models.CASCADE, related_name='budgets',
    )
    period_start = models.DateField()
    period_end = models.DateField()
    planned_amount = models.DecimalField(
        max_digits=14, decimal_places=2, validators=[MinValueValidator(ZERO)],
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ('-period_start',)

    def __str__(self):
        return f'{self.name} - UGX {self.planned_amount:,.0f}'

    @property
    def actual_amount(self):
        qs = Expense.objects.filter(
            expense_date__gte=self.period_start,
            expense_date__lte=self.period_end,
        ).exclude(status__in=[ExpenseStatus.REJECTED, ExpenseStatus.DRAFT])
        if self.category_id:
            qs = qs.filter(category_id=self.category_id)
        return qs.aggregate(t=Sum('amount'))['t'] or ZERO

    @property
    def variance(self):
        return self.planned_amount - self.actual_amount

    @property
    def used_percent(self):
        if self.planned_amount <= ZERO:
            return 0
        return round(self.actual_amount / self.planned_amount * 100)

    @property
    def is_over_budget(self):
        return self.actual_amount > self.planned_amount
