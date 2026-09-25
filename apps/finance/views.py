"""Fees, payments, expenses and the visual financial reports."""

from __future__ import annotations

import csv
import datetime as dt
from decimal import Decimal

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.academics.models import EnrolmentStatus, Program, Term
from apps.accounts.models import (
    AuditLog,
    Notification,
    NotificationLevel,
    Student,
)
from apps.accounts.permissions import (
    can_view_student,
    management_required,
    verified_required,
)

from . import services
from .forms import (
    ExpenseForm,
    InvoiceForm,
    InvoiceItemFormSet,
    OtherIncomeForm,
    PayrollEntryForm,
    PaymentForm,
    ReportFilterForm,
)
from .models import (
    ZERO,
    Budget,
    Expense,
    ExpenseCategory,
    ExpenseStatus,
    FeeCategory,
    FeeStructure,
    Invoice,
    InvoiceStatus,
    OPEN_INVOICE_STATUSES,
    OtherIncome,
    REFERENCED_METHODS,
    PayrollEntry,
    Payment,
    PaymentMethod,
    Scholarship,
    TransactionStatus,
)


# ---------------------------------------------------------------------------
# Dashboard and reports
# ---------------------------------------------------------------------------
@management_required
def dashboard(request):
    """This month at a glance, with the drill-downs one click away."""
    start, end = services.period_bounds('month')
    report = services.build_report('month')
    return render(request, 'finance/dashboard.html', {
        'page_title': 'Finance',
        'report': report,
        'income_chart': services.chart_rows(report['income_breakdown']),
        'expense_chart': services.chart_rows(report['expense_breakdown']),
        'recent_payments': Payment.objects.confirmed()
                               .select_related('student', 'invoice', 'received_by')[:10],
        'recent_expenses': Expense.objects.select_related('category', 'recorded_by')[:10],
        'outstanding': services.outstanding_invoices(limit=10),
        'unconfirmed': Payment.objects.filter(status=TransactionStatus.PENDING).count(),
        'budgets': Budget.objects.filter(
            period_start__lte=end, period_end__gte=start,
        ).select_related('category'),
    })


@management_required
def reports(request):
    """
    The visual report page — weekly, monthly, quarterly, annual or a custom
    range, all rendered from the same aggregation.
    """
    form = ReportFilterForm(request.GET or None)
    period, start, end = 'month', None, None
    if form.is_valid():
        period = form.cleaned_data.get('period') or 'month'
        start = form.cleaned_data.get('start_date')
        end = form.cleaned_data.get('end_date')

    report = services.build_report(period, start=start, end=end)

    # The annual view gets fixed twelve-month buckets so empty months show.
    if period == 'year':
        report['series'] = services.monthly_series(report['start'].year)

    return render(request, 'finance/reports.html', {
        'page_title': 'Financial reports',
        'form': form,
        'report': report,
        'period_choices': services.PERIOD_CHOICES,
        'income_chart': services.chart_rows(report['income_breakdown']),
        'expense_chart': services.chart_rows(report['expense_breakdown']),
        'method_chart': services.chart_rows(report['payment_methods']),
        'programme_chart': services.chart_rows(report['programme_revenue']),
        'ageing_chart': services.chart_rows(report['ageing']),
    })


@management_required
def report_data(request):
    """JSON for the charts, so a period change does not reload the page."""
    period = request.GET.get('period', 'month')
    start = request.GET.get('start')
    end = request.GET.get('end')
    report = services.build_report(
        period,
        start=dt.date.fromisoformat(start) if start else None,
        end=dt.date.fromisoformat(end) if end else None,
    )

    def money_rows(rows):
        return [
            {'label': r['label'], 'amount': float(r['amount']),
             'colour': r['colour'], 'percent': r.get('percent', 0)}
            for r in rows
        ]

    summary = {k: (float(v) if isinstance(v, Decimal) else v)
               for k, v in report['summary'].items()
               if not isinstance(v, dt.date)}

    return JsonResponse({
        'period_label': report['period_label'],
        'summary': summary,
        'series': report['series'],
        'income': money_rows(report['income_breakdown']),
        'expenses': money_rows(report['expense_breakdown']),
        'methods': money_rows(report['payment_methods']),
        'programmes': money_rows(report['programme_revenue']),
        'ageing': [
            {'label': r['label'], 'amount': float(r['amount']), 'count': r['count']}
            for r in report['ageing']
        ],
    })


@management_required
def export_csv(request):
    """Download the ledger for a period — for the accountant, or for backup."""
    kind = request.GET.get('kind', 'payments')
    period = request.GET.get('period', 'month')
    start, end = services.period_bounds(period)

    response = HttpResponse(content_type='text/csv')
    filename = f'bdsu-{kind}-{start:%Y%m%d}-{end:%Y%m%d}.csv'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)

    if kind == 'expenses':
        writer.writerow([
            'Reference', 'Date', 'Time', 'Category', 'Description', 'Payee',
            'Amount (UGX)', 'Method', 'Transaction ID', 'Status', 'Recorded by',
        ])
        for e in services.expenses_in(start, end).select_related('category', 'recorded_by'):
            writer.writerow([
                e.reference, e.expense_date, e.expense_time or '', e.category.name,
                e.description, e.payee_name, e.amount, e.get_method_display(),
                e.transaction_id, e.get_status_display(),
                e.recorded_by.display_name if e.recorded_by else '',
            ])
    else:
        writer.writerow([
            'Receipt', 'Date', 'Time', 'Dancer', 'Invoice', 'Amount (UGX)',
            'Method', 'Transaction ID', 'Payer', 'Status', 'Received by',
        ])
        for p in services.payments_in(start, end).select_related(
            'student', 'invoice', 'received_by',
        ):
            writer.writerow([
                p.receipt_number, p.payment_date, p.payment_time or '',
                p.student.full_name if p.student else '',
                p.invoice.number if p.invoice else '',
                p.amount, p.get_method_display(), p.transaction_id,
                p.payer_name, p.get_status_display(),
                p.received_by.display_name if p.received_by else '',
            ])

    AuditLog.record(request.user, AuditLog.Action.EXPORT,
                    f'exported {kind} for {start} to {end}', request=request)
    return response


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------
@management_required
def invoice_list(request):
    invoices = Invoice.objects.select_related('student', 'term')

    status = request.GET.get('status')
    if status == 'open':
        invoices = invoices.filter(status__in=OPEN_INVOICE_STATUSES)
    elif status == 'overdue':
        invoices = invoices.overdue()
    elif status:
        invoices = invoices.filter(status=status)

    query = request.GET.get('q', '').strip()
    if query:
        invoices = invoices.filter(
            Q(number__icontains=query)
            | Q(student__first_name__icontains=query)
            | Q(student__last_name__icontains=query)
            | Q(student__student_id__icontains=query)
        )

    page = Paginator(invoices.order_by('-issue_date'), 30).get_page(request.GET.get('page'))
    return render(request, 'finance/invoice_list.html', {
        'page_title': 'Invoices',
        'page_obj': page,
        'statuses': InvoiceStatus.choices,
        'active_status': status,
        'q': query,
        'totals': {
            'outstanding': Invoice.objects.outstanding_total(),
            'overdue_count': Invoice.objects.overdue().count(),
        },
    })


@verified_required
def invoice_detail(request, pk):
    invoice = get_object_or_404(
        Invoice.objects.select_related('student', 'term', 'issued_by')
        .prefetch_related('items__fee_category', 'payments__received_by'),
        pk=pk,
    )
    if not request.user.is_management and not can_view_student(request.user, invoice.student):
        messages.error(request, 'You do not have access to that invoice.')
        return redirect('dashboard:home')

    return render(request, 'finance/invoice_detail.html', {
        'page_title': f'Invoice {invoice.number}',
        'invoice': invoice,
        'can_manage': request.user.is_management,
    })


@management_required
def invoice_create(request, student_pk=None):
    student = get_object_or_404(Student, pk=student_pk) if student_pk else None
    form = InvoiceForm(request.POST or None, student=student)
    formset = InvoiceItemFormSet(request.POST or None)

    if request.method == 'POST' and form.is_valid() and formset.is_valid():
        invoice = form.save(commit=False)
        invoice.issued_by = request.user
        invoice.save()
        formset.instance = invoice
        formset.save()
        invoice.recalculate(save=False)
        invoice.apply_scholarships()
        invoice.recalculate()

        AuditLog.record(request.user, AuditLog.Action.CREATE,
                        f'raised invoice {invoice.number} for {invoice.student.full_name}',
                        obj=invoice, request=request)
        messages.success(request, f'Invoice {invoice.number} created.')
        return redirect('finance:invoice_detail', pk=invoice.pk)

    return render(request, 'finance/invoice_form.html', {
        'page_title': 'New invoice',
        'form': form, 'formset': formset, 'student': student,
        'fee_structures': FeeStructure.objects.filter(is_active=True)
                              .select_related('category', 'program'),
    })


@management_required
@require_POST
def invoice_issue(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    invoice.issue(by=request.user)

    guardian = invoice.student.billing_guardian
    if guardian:
        Notification.send(
            guardian.user,
            f'Invoice {invoice.number} — {invoice.student.display_name}',
            f'UGX {invoice.total_amount:,.0f} is due by {invoice.due_date:%d %B %Y}.',
            level=NotificationLevel.WARNING,
            url=reverse('finance:invoice_detail', args=[invoice.pk]),
            icon='fa-file-invoice-dollar',
        )
    messages.success(request, f'Invoice {invoice.number} issued.')
    return redirect('finance:invoice_detail', pk=invoice.pk)


@management_required
def bulk_invoice(request):
    """Raise the same term fee for every active dancer in a programme."""
    term = Term.current()
    if request.method == 'POST':
        term = get_object_or_404(Term, pk=request.POST.get('term'))
        structure = get_object_or_404(FeeStructure, pk=request.POST.get('fee_structure'))
        due_date = dt.date.fromisoformat(request.POST['due_date'])

        students = Student.objects.active().filter(
            enrolments__status=EnrolmentStatus.ACTIVE,
            enrolments__dance_class__term=term,
        )
        if structure.program_id:
            students = students.filter(
                enrolments__dance_class__program_id=structure.program_id,
            )
        students = students.distinct()

        created = 0
        for student in students:
            if Invoice.objects.filter(
                student=student, term=term,
                items__fee_structure=structure,
            ).exists():
                continue
            invoice = Invoice.objects.create(
                student=student, term=term, due_date=due_date,
                status=InvoiceStatus.DRAFT, issued_by=request.user,
            )
            invoice.items.create(
                fee_category=structure.category, fee_structure=structure,
                description=structure.name, quantity=1, unit_amount=structure.amount,
            )
            invoice.recalculate(save=False)
            invoice.apply_scholarships()
            invoice.recalculate()
            created += 1

        AuditLog.record(request.user, AuditLog.Action.CREATE,
                        f'bulk-raised {created} invoices for {term}', request=request)
        messages.success(request, f'{created} draft invoice(s) created. Review, then issue them.')
        return redirect('finance:invoice_list')

    return render(request, 'finance/bulk_invoice.html', {
        'page_title': 'Raise term invoices',
        'terms': Term.objects.select_related('academic_year')[:8],
        'term': term,
        'fee_structures': FeeStructure.objects.filter(is_active=True)
                              .select_related('category', 'program'),
    })


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------
@management_required
def payment_list(request):
    payments = Payment.objects.select_related('student', 'invoice', 'received_by')

    method = request.GET.get('method')
    if method:
        payments = payments.filter(method=method)
    status = request.GET.get('status')
    if status:
        payments = payments.filter(status=status)

    query = request.GET.get('q', '').strip()
    if query:
        payments = payments.filter(
            Q(receipt_number__icontains=query)
            | Q(transaction_id__icontains=query)
            | Q(payer_name__icontains=query)
            | Q(student__first_name__icontains=query)
            | Q(student__last_name__icontains=query)
        )

    period = request.GET.get('period', 'month')
    start, end = services.period_bounds(period)
    if period != 'all':
        payments = payments.filter(payment_date__gte=start, payment_date__lte=end)

    page = Paginator(payments, 30).get_page(request.GET.get('page'))
    return render(request, 'finance/payment_list.html', {
        'page_title': 'Payments received',
        'page_obj': page,
        'methods': PaymentMethod.choices,
        'statuses': TransactionStatus.choices,
        'active_method': method,
        'active_status': status,
        'period': period,
        'period_choices': services.PERIOD_CHOICES,
        'q': query,
        'total': payments.total(),
        'method_breakdown': services.payment_method_breakdown(start, end),
    })


@management_required
def payment_create(request, invoice_pk=None):
    """
    Record a payment that has already happened in the real world.

    The form insists on a transaction ID for mobile money, bank and cheque
    payments, so the ledger can always be reconciled against a statement.
    """
    invoice = get_object_or_404(Invoice, pk=invoice_pk) if invoice_pk else None
    form = PaymentForm(request.POST or None, request.FILES or None, invoice=invoice)

    if request.method == 'POST' and form.is_valid():
        payment = form.save(commit=False)
        payment.recorded_by = request.user
        if not payment.received_by_id:
            payment.received_by = request.user
        if payment.invoice_id and not payment.student_id:
            payment.student = payment.invoice.student
        payment.save()

        AuditLog.record(
            request.user, AuditLog.Action.CREATE,
            f'recorded {payment.get_method_display()} payment of UGX {payment.amount:,.0f}'
            + (f' against {payment.invoice.number}' if payment.invoice_id else ''),
            obj=payment, request=request,
        )

        if payment.invoice_id:
            guardian = payment.invoice.student.billing_guardian
            if guardian:
                Notification.send(
                    guardian.user,
                    f'Payment received — {payment.receipt_number}',
                    f'UGX {payment.amount:,.0f} received. '
                    f'Balance on {payment.invoice.number}: UGX {payment.invoice.balance:,.0f}.',
                    level=NotificationLevel.SUCCESS,
                    url=reverse('finance:invoice_detail', args=[payment.invoice_id]),
                    icon='fa-receipt',
                )

        messages.success(
            request, f'Payment recorded — receipt {payment.receipt_number}.',
        )
        return redirect('finance:payment_detail', pk=payment.pk)

    return render(request, 'finance/payment_form.html', {
        'page_title': 'Record a payment',
        'form': form,
        'invoice': invoice,
        # Drives the "transaction ID required" hint in the form as the
        # method dropdown changes.
        'referenced_methods': sorted(REFERENCED_METHODS),
    })


@verified_required
def payment_detail(request, pk):
    payment = get_object_or_404(
        Payment.objects.select_related(
            'student', 'invoice', 'received_by', 'recorded_by', 'confirmed_by',
        ),
        pk=pk,
    )
    if not request.user.is_management and not (
        payment.student and can_view_student(request.user, payment.student)
    ):
        messages.error(request, 'You do not have access to that receipt.')
        return redirect('dashboard:home')

    return render(request, 'finance/payment_detail.html', {
        'page_title': f'Receipt {payment.receipt_number}',
        'payment': payment,
        'can_manage': request.user.is_management,
    })


@management_required
@require_POST
def payment_confirm(request, pk):
    payment = get_object_or_404(Payment, pk=pk)
    payment.confirm(by=request.user)
    messages.success(request, f'{payment.receipt_number} confirmed.')
    return redirect('finance:payment_detail', pk=payment.pk)


@management_required
@require_POST
def payment_reverse(request, pk):
    payment = get_object_or_404(Payment, pk=pk)
    reason = request.POST.get('reason', '')
    payment.reverse_payment(by=request.user, reason=reason)
    AuditLog.record(request.user, AuditLog.Action.UPDATE,
                    f'reversed {payment.receipt_number}: {reason}', obj=payment, request=request)
    messages.warning(request, f'{payment.receipt_number} reversed.')
    return redirect('finance:payment_detail', pk=payment.pk)


# ---------------------------------------------------------------------------
# Expenses
# ---------------------------------------------------------------------------
@management_required
def expense_list(request):
    expenses = Expense.objects.select_related('category', 'recorded_by', 'event')

    category = request.GET.get('category')
    if category:
        expenses = expenses.filter(category_id=category)

    period = request.GET.get('period', 'month')
    start, end = services.period_bounds(period)
    if period != 'all':
        expenses = expenses.filter(expense_date__gte=start, expense_date__lte=end)

    query = request.GET.get('q', '').strip()
    if query:
        expenses = expenses.filter(
            Q(description__icontains=query) | Q(payee_name__icontains=query)
            | Q(reference__icontains=query) | Q(transaction_id__icontains=query)
        )

    page = Paginator(expenses, 30).get_page(request.GET.get('page'))
    return render(request, 'finance/expense_list.html', {
        'page_title': 'Expenses',
        'page_obj': page,
        'categories': ExpenseCategory.objects.filter(is_active=True),
        'active_category': category,
        'period': period,
        'period_choices': services.PERIOD_CHOICES,
        'q': query,
        'total': expenses.aggregate(t=Sum('amount'))['t'] or ZERO,
        'breakdown': services.expense_breakdown(start, end),
    })


@management_required
def expense_create(request):
    form = ExpenseForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        expense = form.save(commit=False)
        expense.recorded_by = request.user
        expense.save()
        AuditLog.record(request.user, AuditLog.Action.CREATE,
                        f'recorded expense {expense.reference}: {expense.description}',
                        obj=expense, request=request)
        messages.success(request, f'Expense recorded — {expense.reference}.')
        return redirect('finance:expense_detail', pk=expense.pk)
    return render(request, 'finance/expense_form.html', {
        'page_title': 'Record an expense', 'form': form,
    })


@management_required
def expense_detail(request, pk):
    expense = get_object_or_404(
        Expense.objects.select_related('category', 'recorded_by', 'approved_by', 'event'), pk=pk,
    )
    return render(request, 'finance/expense_detail.html', {
        'page_title': expense.reference, 'expense': expense,
    })


@management_required
def expense_edit(request, pk):
    expense = get_object_or_404(Expense, pk=pk)
    form = ExpenseForm(request.POST or None, request.FILES or None, instance=expense)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Expense updated.')
        return redirect('finance:expense_detail', pk=expense.pk)
    return render(request, 'finance/expense_form.html', {
        'page_title': f'Edit {expense.reference}', 'form': form, 'expense': expense,
    })


# ---------------------------------------------------------------------------
# Other income and payroll
# ---------------------------------------------------------------------------
@management_required
def income_list(request):
    period = request.GET.get('period', 'month')
    start, end = services.period_bounds(period)
    entries = OtherIncome.objects.select_related('category', 'event', 'recorded_by')
    if period != 'all':
        entries = entries.filter(received_date__gte=start, received_date__lte=end)
    page = Paginator(entries, 30).get_page(request.GET.get('page'))
    return render(request, 'finance/income_list.html', {
        'page_title': 'Other income',
        'page_obj': page,
        'period': period,
        'period_choices': services.PERIOD_CHOICES,
        'total': entries.aggregate(t=Sum('amount'))['t'] or ZERO,
    })


@management_required
def income_create(request):
    form = OtherIncomeForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        entry = form.save(commit=False)
        entry.recorded_by = request.user
        entry.save()
        messages.success(request, f'Income recorded — {entry.reference}.')
        return redirect('finance:income_list')
    return render(request, 'finance/income_form.html', {
        'page_title': 'Record other income', 'form': form,
    })


@management_required
def payroll_list(request):
    entries = PayrollEntry.objects.select_related('staff__user', 'processed_by')
    page = Paginator(entries, 30).get_page(request.GET.get('page'))
    return render(request, 'finance/payroll_list.html', {
        'page_title': 'Payroll',
        'page_obj': page,
        'month_total': entries.filter(
            paid_date__gte=services.period_bounds('month')[0],
        ).aggregate(t=Sum('net_amount'))['t'] or ZERO,
    })


@management_required
def payroll_create(request):
    form = PayrollEntryForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        entry = form.save(commit=False)
        entry.processed_by = request.user
        entry.save()

        # Mirror a paid salary into the expense ledger so reports balance.
        if entry.status == ExpenseStatus.PAID and not entry.expense_id:
            category, _ = ExpenseCategory.objects.get_or_create(
                name='Salaries & wages', defaults={'is_recurring': True},
            )
            entry.expense = Expense.objects.create(
                category=category,
                description=f'Salary — {entry.staff.user.display_name} '
                            f'({entry.period_start:%b %Y})',
                amount=entry.net_amount,
                expense_date=entry.paid_date or dt.date.today(),
                expense_time=entry.paid_time,
                method=entry.method,
                transaction_id=entry.transaction_id,
                payee_name=entry.staff.user.display_name,
                status=ExpenseStatus.PAID,
                recorded_by=request.user,
            )
            entry.save(update_fields=['expense'])

        messages.success(request, 'Payroll entry saved.')
        return redirect('finance:payroll_list')
    return render(request, 'finance/payroll_form.html', {
        'page_title': 'New payroll entry', 'form': form,
    })


# ---------------------------------------------------------------------------
# Fee catalogue
# ---------------------------------------------------------------------------
@management_required
def fee_structure(request):
    return render(request, 'finance/fee_structure.html', {
        'page_title': 'Fee structure',
        'fees': FeeStructure.objects.filter(is_active=True)
                    .select_related('category', 'program', 'term'),
        'categories': FeeCategory.objects.filter(is_active=True),
        'scholarships': Scholarship.objects.filter(is_active=True)
                            .select_related('student', 'applies_to_category'),
    })


# ---------------------------------------------------------------------------
# Family-facing
# ---------------------------------------------------------------------------
@verified_required
def my_statement(request):
    """A guardian's own fee statement."""
    guardian = getattr(request.user, 'guardian_profile', None)
    if not guardian:
        messages.info(request, 'Fee statements are available to parent accounts.')
        return redirect('dashboard:home')

    return render(request, 'finance/my_statement.html', {
        'page_title': 'My fee statement',
        'statement': services.guardian_statement(guardian),
        'guardian': guardian,
        'payments': Payment.objects.confirmed().filter(
            student__guardian_links__guardian=guardian,
        ).select_related('student', 'invoice').distinct()[:20],
    })
