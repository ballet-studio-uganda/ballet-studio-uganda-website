"""
The ledger.

Money is the part of this system the studio will be audited on, so these tests
cover the arithmetic (invoice totals, balances, bursaries) and the rules that
keep every figure traceable back to a real receipt.
"""

import datetime as dt
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.academics.models import AcademicYear, Program, Term
from apps.accounts.models import ApprovalStatus, Role, Student, User

from . import services
from .forms import PaymentForm
from .models import (
    Expense,
    ExpenseCategory,
    ExpenseStatus,
    FeeCategory,
    Invoice,
    InvoiceStatus,
    OtherIncome,
    IncomeCategory,
    Payment,
    PaymentMethod,
    Scholarship,
    TransactionStatus,
)


class LedgerTestCase(TestCase):
    """Shared fixture: one dancer, one issued invoice."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username='admin', email='admin@example.com', password='pw',
            role=Role.ADMIN, approval_status=ApprovalStatus.APPROVED,
        )
        year = AcademicYear.objects.create(
            name='2026', start_date=dt.date(2026, 1, 1),
            end_date=dt.date(2026, 12, 31), is_current=True,
        )
        cls.term = Term.objects.create(
            academic_year=year, name='Term 1',
            start_date=dt.date(2026, 1, 15), end_date=dt.date(2026, 4, 10),
            is_current=True,
        )
        cls.programme = Program.objects.create(name='Junior Ballet', description='...')
        cls.tuition = FeeCategory.objects.create(name='Tuition', is_tuition=True)
        cls.student = Student.objects.create(
            first_name='Amara', last_name='Kigozi', date_of_birth=dt.date(2016, 3, 1),
        )

    def make_invoice(self, amount='240000', **kwargs):
        invoice = Invoice.objects.create(
            student=self.student, term=self.term,
            issue_date=dt.date(2026, 1, 20), due_date=dt.date(2026, 2, 10),
            status=InvoiceStatus.ISSUED, issued_by=self.admin, **kwargs,
        )
        invoice.items.create(
            fee_category=self.tuition, description='Term 1 tuition',
            quantity=1, unit_amount=Decimal(amount),
        )
        return invoice.recalculate()


class InvoiceArithmeticTests(LedgerTestCase):

    def test_totals_come_from_the_line_items(self):
        invoice = self.make_invoice('240000')
        self.assertEqual(invoice.subtotal, Decimal('240000.00'))
        self.assertEqual(invoice.total_amount, Decimal('240000.00'))
        self.assertEqual(invoice.balance, Decimal('240000.00'))
        self.assertFalse(invoice.is_settled)

    def test_quantity_multiplies_the_unit_amount(self):
        invoice = Invoice.objects.create(
            student=self.student, term=self.term, due_date=dt.date(2026, 2, 10),
        )
        invoice.items.create(description='Two costumes', quantity=2,
                             unit_amount=Decimal('120000'))
        invoice.recalculate()
        self.assertEqual(invoice.subtotal, Decimal('240000.00'))

    def test_part_payment_moves_the_status_and_balance(self):
        invoice = self.make_invoice('240000')
        Payment.objects.create(
            invoice=invoice, student=self.student, amount=Decimal('100000'),
            payment_date=dt.date(2026, 1, 25), method=PaymentMethod.CASH,
            status=TransactionStatus.CONFIRMED,
        )
        invoice.refresh_from_db()
        self.assertEqual(invoice.amount_paid, Decimal('100000.00'))
        self.assertEqual(invoice.balance, Decimal('140000.00'))
        self.assertEqual(invoice.status, InvoiceStatus.PART_PAID)

    def test_settling_in_full_marks_it_paid(self):
        invoice = self.make_invoice('240000')
        Payment.objects.create(
            invoice=invoice, student=self.student, amount=Decimal('240000'),
            payment_date=dt.date(2026, 1, 25), method=PaymentMethod.CASH,
            status=TransactionStatus.CONFIRMED,
        )
        invoice.refresh_from_db()
        self.assertTrue(invoice.is_settled)
        self.assertEqual(invoice.status, InvoiceStatus.PAID)
        self.assertEqual(invoice.percent_paid, 100)

    def test_unconfirmed_payments_do_not_count(self):
        invoice = self.make_invoice('240000')
        Payment.objects.create(
            invoice=invoice, student=self.student, amount=Decimal('240000'),
            payment_date=dt.date(2026, 1, 25), method=PaymentMethod.CASH,
            status=TransactionStatus.PENDING,
        )
        invoice.refresh_from_db()
        self.assertEqual(invoice.amount_paid, Decimal('0.00'))
        self.assertFalse(invoice.is_settled)

    def test_reversing_a_payment_restores_the_balance(self):
        invoice = self.make_invoice('240000')
        payment = Payment.objects.create(
            invoice=invoice, student=self.student, amount=Decimal('240000'),
            payment_date=dt.date(2026, 1, 25), method=PaymentMethod.MTN_MOMO,
            transaction_id='MP1', status=TransactionStatus.CONFIRMED,
        )
        invoice.refresh_from_db()
        self.assertTrue(invoice.is_settled)

        payment.reverse_payment(by=self.admin, reason='Mobile money bounced')
        invoice.refresh_from_db()
        self.assertEqual(invoice.balance, Decimal('240000.00'))
        self.assertFalse(invoice.is_settled)

    def test_overdue_is_derived_from_the_due_date(self):
        invoice = self.make_invoice('240000')
        invoice.due_date = dt.date.today() - dt.timedelta(days=12)
        invoice.save()
        invoice.recalculate()
        self.assertTrue(invoice.is_overdue)
        self.assertEqual(invoice.days_overdue, 12)

    def test_a_settled_invoice_is_never_overdue(self):
        invoice = self.make_invoice('240000')
        invoice.due_date = dt.date.today() - dt.timedelta(days=30)
        invoice.save()
        Payment.objects.create(
            invoice=invoice, student=self.student, amount=Decimal('240000'),
            payment_date=dt.date.today(), method=PaymentMethod.CASH,
            status=TransactionStatus.CONFIRMED,
        )
        invoice.refresh_from_db()
        self.assertFalse(invoice.is_overdue)


class ScholarshipTests(LedgerTestCase):

    def test_percentage_bursary_reduces_the_total(self):
        Scholarship.objects.create(
            student=self.student, name='Sickle Cell Warriors Bursary',
            discount_type='percent', value=Decimal('50'),
        )
        invoice = self.make_invoice('240000')
        invoice.apply_scholarships()
        invoice.recalculate()
        self.assertEqual(invoice.discount_amount, Decimal('120000.00'))
        self.assertEqual(invoice.total_amount, Decimal('120000.00'))
        self.assertIn('Sickle Cell', invoice.discount_reason)

    def test_fixed_bursary_never_exceeds_the_bill(self):
        Scholarship.objects.create(
            student=self.student, name='Full sponsorship',
            discount_type='fixed', value=Decimal('900000'),
        )
        invoice = self.make_invoice('240000')
        invoice.apply_scholarships()
        invoice.recalculate()
        self.assertEqual(invoice.discount_amount, Decimal('240000.00'))
        self.assertEqual(invoice.total_amount, Decimal('0.00'))

    def test_expired_bursary_is_ignored(self):
        Scholarship.objects.create(
            student=self.student, name='Last year only',
            discount_type='percent', value=Decimal('50'),
            starts_on=dt.date(2024, 1, 1), ends_on=dt.date(2024, 12, 31),
        )
        invoice = self.make_invoice('240000')
        invoice.apply_scholarships()
        self.assertEqual(invoice.discount_amount, Decimal('0.00'))


class PaymentValidationTests(LedgerTestCase):
    """
    The rules that keep the ledger reconcilable against an MTN statement or a
    bank slip.
    """

    def base_data(self, **overrides):
        data = {
            'student': self.student.pk, 'amount': '50000',
            'payment_date': dt.date.today().isoformat(),
            'method': PaymentMethod.MTN_MOMO,
            'transaction_id': 'MP260904.1430.AB123',
            'status': TransactionStatus.CONFIRMED,
        }
        data.update(overrides)
        return data

    def test_mobile_money_requires_a_transaction_id(self):
        form = PaymentForm(data=self.base_data(transaction_id=''))
        self.assertFalse(form.is_valid())
        self.assertIn('transaction_id', form.errors)

    def test_bank_transfer_requires_a_reference(self):
        form = PaymentForm(data=self.base_data(
            method=PaymentMethod.BANK_TRANSFER, transaction_id=''))
        self.assertFalse(form.is_valid())
        self.assertIn('transaction_id', form.errors)

    def test_cash_does_not(self):
        form = PaymentForm(data=self.base_data(
            method=PaymentMethod.CASH, transaction_id=''))
        self.assertTrue(form.is_valid(), form.errors)

    def test_the_same_transaction_id_cannot_be_banked_twice(self):
        Payment.objects.create(
            student=self.student, amount=Decimal('50000'),
            payment_date=dt.date.today(), method=PaymentMethod.MTN_MOMO,
            transaction_id='MP260904.1430.AB123',
            status=TransactionStatus.CONFIRMED,
        )
        form = PaymentForm(data=self.base_data())
        self.assertFalse(form.is_valid())
        self.assertIn('already been recorded', str(form.errors['transaction_id']))

    def test_payment_must_attach_to_an_invoice_or_a_dancer(self):
        data = self.base_data()
        data.pop('student')
        form = PaymentForm(data=data)
        self.assertFalse(form.is_valid())

    def test_overpaying_an_invoice_is_flagged(self):
        invoice = self.make_invoice('100000')
        form = PaymentForm(data=self.base_data(
            invoice=invoice.pk, amount='150000'))
        self.assertFalse(form.is_valid())
        self.assertIn('amount', form.errors)

    def test_receipt_numbers_are_unique_and_sequential(self):
        numbers = [
            Payment.objects.create(
                student=self.student, amount=Decimal('1000'),
                payment_date=dt.date.today(), method=PaymentMethod.CASH,
                status=TransactionStatus.CONFIRMED,
            ).receipt_number
            for _ in range(4)
        ]
        self.assertEqual(len(set(numbers)), 4)
        self.assertTrue(all(n.startswith('RCP-') for n in numbers))


class ReportingTests(LedgerTestCase):
    """The aggregation behind every chart on the reports page."""

    def setUp(self):
        today = dt.date.today()
        invoice = self.make_invoice('300000')
        Payment.objects.create(
            invoice=invoice, student=self.student, amount=Decimal('300000'),
            payment_date=today, method=PaymentMethod.MTN_MOMO,
            transaction_id='MP-A', status=TransactionStatus.CONFIRMED,
        )
        rent = ExpenseCategory.objects.create(name='Rent')
        Expense.objects.create(
            category=rent, description='Studio rent', amount=Decimal('180000'),
            expense_date=today, method=PaymentMethod.BANK_TRANSFER,
            status=ExpenseStatus.PAID,
        )
        donations = IncomeCategory.objects.create(name='Donations')
        OtherIncome.objects.create(
            category=donations, description='Recital donation',
            amount=Decimal('50000'), received_date=today,
            method=PaymentMethod.CASH, status=TransactionStatus.CONFIRMED,
        )

    def test_summary_adds_fees_and_other_income(self):
        start, end = services.period_bounds('month')
        summary = services.financial_summary(start, end)
        self.assertEqual(summary['fee_income'], Decimal('300000.00'))
        self.assertEqual(summary['other_income'], Decimal('50000.00'))
        self.assertEqual(summary['total_income'], Decimal('350000.00'))
        self.assertEqual(summary['total_expenses'], Decimal('180000.00'))
        self.assertEqual(summary['net'], Decimal('170000.00'))

    def test_draft_and_rejected_rows_are_excluded(self):
        rent = ExpenseCategory.objects.get(name='Rent')
        Expense.objects.create(
            category=rent, description='Not approved', amount=Decimal('999999'),
            expense_date=dt.date.today(), status=ExpenseStatus.REJECTED,
        )
        start, end = services.period_bounds('month')
        self.assertEqual(
            services.financial_summary(start, end)['total_expenses'],
            Decimal('180000.00'),
        )

    def test_every_named_period_resolves(self):
        for period, _label in services.PERIOD_CHOICES:
            if period == 'custom':
                continue
            with self.subTest(period=period):
                start, end = services.period_bounds(period)
                self.assertLessEqual(start, end)

    def test_week_period_is_monday_to_sunday(self):
        start, end = services.period_bounds('week', anchor=dt.date(2026, 9, 4))
        self.assertEqual(start, dt.date(2026, 8, 31))   # Monday
        self.assertEqual(end, dt.date(2026, 9, 6))      # Sunday

    def test_year_period_spans_january_to_december(self):
        start, end = services.period_bounds('year', anchor=dt.date(2026, 6, 15))
        self.assertEqual(start, dt.date(2026, 1, 1))
        self.assertEqual(end, dt.date(2026, 12, 31))

    def test_series_and_breakdowns_are_json_safe(self):
        start, end = services.period_bounds('month')
        series = services.income_expense_series(start, end)
        self.assertEqual(len(series['labels']), len(series['income']))
        self.assertTrue(all(isinstance(v, float) for v in series['income']))

        rows = services.chart_rows(services.expense_breakdown(start, end))
        self.assertTrue(all(isinstance(r['amount'], float) for r in rows))

    def test_monthly_series_always_has_twelve_buckets(self):
        series = services.monthly_series(dt.date.today().year)
        self.assertEqual(len(series['labels']), 12)
        self.assertEqual(len(series['income']), 12)

    def test_ageing_buckets_outstanding_debt(self):
        overdue = self.make_invoice('80000')
        overdue.due_date = dt.date.today() - dt.timedelta(days=45)
        overdue.save()
        rows = {r['label']: r['amount'] for r in services.ageing_analysis()}
        self.assertEqual(rows['31-60 days'], Decimal('80000.00'))

    def test_build_report_returns_every_section(self):
        report = services.build_report('month')
        for key in ('summary', 'series', 'income_breakdown', 'expense_breakdown',
                    'payment_methods', 'programme_revenue', 'ageing', 'period_label'):
            self.assertIn(key, report)


class ExportTests(LedgerTestCase):

    def test_payments_export_is_csv_with_the_traceability_columns(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse('finance:export_csv'), {'kind': 'payments', 'period': 'year'}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        header = response.content.decode().splitlines()[0]
        for column in ('Receipt', 'Date', 'Time', 'Method', 'Transaction ID', 'Received by'):
            self.assertIn(column, header)
