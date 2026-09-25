"""
Financial reporting.

One place that knows how to turn the ledger into the numbers and series the
dashboards draw. Every figure here traces back to a :class:`Payment`,
:class:`OtherIncome` or :class:`Expense` row that a member of staff entered by
hand, so anything on a chart can be clicked through to a real receipt.
"""

from __future__ import annotations

import calendar
import datetime as dt
from decimal import Decimal

from django.db.models import Count, DecimalField, F, Q, Sum, Value
from django.db.models.functions import Coalesce, TruncDay, TruncMonth, TruncWeek

from apps.academics.models import EnrolmentStatus, Program
from .models import (
    ZERO,
    Expense,
    ExpenseStatus,
    Invoice,
    InvoiceStatus,
    OPEN_INVOICE_STATUSES,
    OtherIncome,
    Payment,
    PaymentMethod,
    TransactionStatus,
)

MONEY = DecimalField(max_digits=16, decimal_places=2)


def _sum(qs, field='amount'):
    return qs.aggregate(t=Coalesce(Sum(field), Value(ZERO), output_field=MONEY))['t']


def chart_rows(rows):
    """
    Make a breakdown list safe for ``json_script``.

    Decimal survives Django's JSON encoder only as a *string*, which Chart.js
    then has to coerce. Casting to float here keeps the template dumb.
    """
    return [
        {
            'label': row['label'],
            'colour': row.get('colour', '#EE2A7B'),
            'amount': float(row['amount']),
            'percent': row.get('percent', 0),
            'count': row.get('count'),
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Period handling
# ---------------------------------------------------------------------------
PERIOD_CHOICES = [
    ('week', 'This week'),
    ('month', 'This month'),
    ('quarter', 'This quarter'),
    ('year', 'This year'),
    ('last_7', 'Last 7 days'),
    ('last_30', 'Last 30 days'),
    ('last_90', 'Last 90 days'),
    ('last_12_months', 'Last 12 months'),
    ('all', 'All time'),
    ('custom', 'Custom range'),
]


def period_bounds(period='month', anchor=None, start=None, end=None):
    """
    Resolve a named period to a concrete ``(start_date, end_date)`` pair.

    ``custom`` uses the *start* and *end* passed in; everything else is derived
    from *anchor* (today by default).
    """
    today = anchor or dt.date.today()

    if period == 'custom' and start and end:
        return start, end

    if period == 'week':
        begin = today - dt.timedelta(days=today.weekday())
        return begin, begin + dt.timedelta(days=6)

    if period == 'month':
        last_day = calendar.monthrange(today.year, today.month)[1]
        return today.replace(day=1), today.replace(day=last_day)

    if period == 'quarter':
        first_month = 3 * ((today.month - 1) // 3) + 1
        last_month = first_month + 2
        last_day = calendar.monthrange(today.year, last_month)[1]
        return (
            dt.date(today.year, first_month, 1),
            dt.date(today.year, last_month, last_day),
        )

    if period == 'year':
        return dt.date(today.year, 1, 1), dt.date(today.year, 12, 31)

    if period == 'last_7':
        return today - dt.timedelta(days=6), today

    if period == 'last_30':
        return today - dt.timedelta(days=29), today

    if period == 'last_90':
        return today - dt.timedelta(days=89), today

    if period == 'last_12_months':
        begin = (today.replace(day=1) - dt.timedelta(days=334)).replace(day=1)
        return begin, today

    # 'all'
    return dt.date(2000, 1, 1), today


def label_for_period(period, start, end):
    if period == 'month':
        return start.strftime('%B %Y')
    if period == 'year':
        return start.strftime('%Y')
    if period == 'week':
        return f'{start:%d %b} - {end:%d %b %Y}'
    if period == 'all':
        return 'All time'
    return f'{start:%d %b %Y} - {end:%d %b %Y}'


def pick_granularity(start, end):
    """Choose day/week/month buckets so a chart never has hundreds of points."""
    span = (end - start).days
    if span <= 45:
        return 'day'
    if span <= 200:
        return 'week'
    return 'month'


_TRUNC = {'day': TruncDay, 'week': TruncWeek, 'month': TruncMonth}
_LABEL_FORMAT = {'day': '%d %b', 'week': '%d %b', 'month': '%b %Y'}


# ---------------------------------------------------------------------------
# Base querysets -- confirmed money only
# ---------------------------------------------------------------------------
def payments_in(start, end):
    return Payment.objects.filter(
        status=TransactionStatus.CONFIRMED,
        payment_date__gte=start,
        payment_date__lte=end,
    )


def other_income_in(start, end):
    return OtherIncome.objects.filter(
        status=TransactionStatus.CONFIRMED,
        received_date__gte=start,
        received_date__lte=end,
    )


def expenses_in(start, end):
    return Expense.objects.filter(
        expense_date__gte=start, expense_date__lte=end,
    ).exclude(status__in=[ExpenseStatus.REJECTED, ExpenseStatus.DRAFT])


# ---------------------------------------------------------------------------
# Headline figures
# ---------------------------------------------------------------------------
def financial_summary(start, end):
    """The KPI row: income, expenses, net, and what is still owed."""
    fees = _sum(payments_in(start, end))
    other = _sum(other_income_in(start, end))
    spend = _sum(expenses_in(start, end))
    income = fees + other

    open_invoices = Invoice.objects.filter(status__in=OPEN_INVOICE_STATUSES)
    billed = _sum(open_invoices, 'total_amount')
    collected = _sum(open_invoices, 'amount_paid')
    outstanding = billed - collected

    overdue_qs = open_invoices.filter(due_date__lt=dt.date.today())
    overdue = _sum(overdue_qs, 'total_amount') - _sum(overdue_qs, 'amount_paid')

    # Collection rate across every invoice issued in the window.
    issued = Invoice.objects.filter(
        issue_date__gte=start, issue_date__lte=end,
    ).exclude(status__in=[InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED])
    issued_total = _sum(issued, 'total_amount')
    issued_paid = _sum(issued, 'amount_paid')

    return {
        'start': start,
        'end': end,
        'fee_income': fees,
        'other_income': other,
        'total_income': income,
        'total_expenses': spend,
        'net': income - spend,
        'margin_percent': (
            round((income - spend) / income * 100, 1) if income > ZERO else None
        ),
        'outstanding': outstanding,
        'overdue': overdue,
        'overdue_count': overdue_qs.count(),
        'invoices_issued': issued.count(),
        'invoiced_total': issued_total,
        'collection_rate': (
            round(issued_paid / issued_total * 100, 1) if issued_total > ZERO else None
        ),
        'payment_count': payments_in(start, end).count(),
        'expense_count': expenses_in(start, end).count(),
    }


def compare_with_previous(start, end):
    """Same-length window immediately before, for the percentage deltas."""
    span = (end - start).days + 1
    prev_end = start - dt.timedelta(days=1)
    prev_start = prev_end - dt.timedelta(days=span - 1)

    current = financial_summary(start, end)
    previous = financial_summary(prev_start, prev_end)

    def delta(now, before):
        if before in (None, ZERO):
            return None
        return round((now - before) / before * 100, 1)

    return {
        'current': current,
        'previous': previous,
        'income_change': delta(current['total_income'], previous['total_income']),
        'expense_change': delta(current['total_expenses'], previous['total_expenses']),
        'net_change': delta(current['net'], previous['net']),
    }


# ---------------------------------------------------------------------------
# Time series
# ---------------------------------------------------------------------------
def income_expense_series(start, end, granularity=None):
    """
    ``{'labels': [...], 'income': [...], 'expenses': [...], 'net': [...]}``
    ready to hand straight to Chart.js.
    """
    granularity = granularity or pick_granularity(start, end)
    trunc = _TRUNC[granularity]
    fmt = _LABEL_FORMAT[granularity]

    def bucket(qs, date_field):
        rows = (
            qs.annotate(bucket=trunc(date_field))
            .values('bucket')
            .annotate(total=Coalesce(Sum('amount'), Value(ZERO), output_field=MONEY))
            .order_by('bucket')
        )
        return {row['bucket']: row['total'] for row in rows}

    fees = bucket(payments_in(start, end), 'payment_date')
    other = bucket(other_income_in(start, end), 'received_date')
    spend = bucket(expenses_in(start, end), 'expense_date')

    buckets = sorted(set(fees) | set(other) | set(spend))
    if not buckets:
        return {'labels': [], 'income': [], 'expenses': [], 'net': [], 'granularity': granularity}

    labels, income_row, expense_row, net_row = [], [], [], []
    for key in buckets:
        moment = key.date() if hasattr(key, 'date') else key
        income = fees.get(key, ZERO) + other.get(key, ZERO)
        outgoing = spend.get(key, ZERO)
        labels.append(moment.strftime(fmt))
        income_row.append(float(income))
        expense_row.append(float(outgoing))
        net_row.append(float(income - outgoing))

    return {
        'labels': labels,
        'income': income_row,
        'expenses': expense_row,
        'net': net_row,
        'granularity': granularity,
    }


def monthly_series(year):
    """Twelve fixed buckets for the annual report, including empty months."""
    labels, income_row, expense_row, net_row = [], [], [], []
    for month in range(1, 13):
        last_day = calendar.monthrange(year, month)[1]
        start = dt.date(year, month, 1)
        end = dt.date(year, month, last_day)
        income = _sum(payments_in(start, end)) + _sum(other_income_in(start, end))
        spend = _sum(expenses_in(start, end))
        labels.append(calendar.month_abbr[month])
        income_row.append(float(income))
        expense_row.append(float(spend))
        net_row.append(float(income - spend))
    return {
        'labels': labels, 'income': income_row,
        'expenses': expense_row, 'net': net_row, 'granularity': 'month',
    }


# ---------------------------------------------------------------------------
# Breakdowns
# ---------------------------------------------------------------------------
def income_breakdown(start, end):
    """Fee income by fee category, plus each other-income category."""
    rows = []

    fee_rows = (
        payments_in(start, end)
        .filter(invoice__isnull=False)
        .values('invoice__items__fee_category__name', 'invoice__items__fee_category__colour')
        .annotate(total=Coalesce(Sum('amount'), Value(ZERO), output_field=MONEY))
        .order_by('-total')
    )
    for row in fee_rows:
        name = row['invoice__items__fee_category__name']
        if not name:
            continue
        rows.append({
            'label': name,
            'colour': row['invoice__items__fee_category__colour'] or '#EE2A7B',
            'amount': row['total'],
        })

    unallocated = _sum(payments_in(start, end).filter(invoice__isnull=True))
    if unallocated > ZERO:
        rows.append({'label': 'Unallocated payments', 'colour': '#8a1a55', 'amount': unallocated})

    other_rows = (
        other_income_in(start, end)
        .values('category__name', 'category__colour')
        .annotate(total=Coalesce(Sum('amount'), Value(ZERO), output_field=MONEY))
        .order_by('-total')
    )
    for row in other_rows:
        rows.append({
            'label': row['category__name'],
            'colour': row['category__colour'] or '#c9a84c',
            'amount': row['total'],
        })

    rows.sort(key=lambda r: r['amount'], reverse=True)
    total = sum((r['amount'] for r in rows), ZERO)
    for row in rows:
        row['percent'] = round(row['amount'] / total * 100, 1) if total > ZERO else 0
    return rows


def expense_breakdown(start, end):
    rows = (
        expenses_in(start, end)
        .values('category__name', 'category__colour')
        .annotate(
            total=Coalesce(Sum('amount'), Value(ZERO), output_field=MONEY),
            count=Count('id'),
        )
        .order_by('-total')
    )
    total = sum((row['total'] for row in rows), ZERO)
    return [
        {
            'label': row['category__name'],
            'colour': row['category__colour'] or '#701344',
            'amount': row['total'],
            'count': row['count'],
            'percent': round(row['total'] / total * 100, 1) if total > ZERO else 0,
        }
        for row in rows
    ]


def payment_method_breakdown(start, end):
    """
    How families actually pay. Useful for deciding which mobile money float
    to keep topped up, and for spotting cash-handling risk.
    """
    labels = dict(PaymentMethod.choices)
    rows = (
        payments_in(start, end)
        .values('method')
        .annotate(
            total=Coalesce(Sum('amount'), Value(ZERO), output_field=MONEY),
            count=Count('id'),
        )
        .order_by('-total')
    )
    total = sum((row['total'] for row in rows), ZERO)
    palette = {
        PaymentMethod.CASH: '#c9a84c',
        PaymentMethod.MTN_MOMO: '#ffcc00',
        PaymentMethod.AIRTEL_MONEY: '#e8112d',
        PaymentMethod.BANK_DEPOSIT: '#701344',
        PaymentMethod.BANK_TRANSFER: '#8a1a55',
        PaymentMethod.CHEQUE: '#6b5a62',
        PaymentMethod.CARD: '#EE2A7B',
    }
    return [
        {
            'label': labels.get(row['method'], row['method']),
            'method': row['method'],
            'colour': palette.get(row['method'], '#4d0a2e'),
            'amount': row['total'],
            'count': row['count'],
            'percent': round(row['total'] / total * 100, 1) if total > ZERO else 0,
        }
        for row in rows
    ]


def revenue_by_programme(start, end):
    """Which programmes carry the studio financially."""
    rows = []
    for program in Program.objects.filter(is_active=True):
        amount = _sum(
            payments_in(start, end).filter(
                invoice__student__enrolments__dance_class__program=program,
                invoice__student__enrolments__status=EnrolmentStatus.ACTIVE,
            ).distinct()
        )
        students = program.active_student_count
        rows.append({
            'label': program.name,
            'colour': program.accent_colour,
            'amount': amount,
            'students': students,
            'per_student': (amount / students) if students else ZERO,
        })
    rows.sort(key=lambda r: r['amount'], reverse=True)
    total = sum((r['amount'] for r in rows), ZERO)
    for row in rows:
        row['percent'] = round(row['amount'] / total * 100, 1) if total > ZERO else 0
    return rows


# ---------------------------------------------------------------------------
# Debtors
# ---------------------------------------------------------------------------
def outstanding_invoices(limit=None):
    """Open invoices, worst overdue first -- the chase list."""
    qs = (
        Invoice.objects.filter(status__in=OPEN_INVOICE_STATUSES)
        .annotate(owing=F('total_amount') - F('amount_paid'))
        .filter(owing__gt=ZERO)
        .select_related('student', 'term')
        .order_by('due_date')
    )
    return qs[:limit] if limit else qs


def ageing_analysis():
    """Outstanding balances bucketed by how long they have been owed."""
    today = dt.date.today()
    buckets = [
        ('Not yet due', None, 0),
        ('1-30 days', 1, 30),
        ('31-60 days', 31, 60),
        ('61-90 days', 61, 90),
        ('Over 90 days', 91, None),
    ]
    base = (
        Invoice.objects.filter(status__in=OPEN_INVOICE_STATUSES)
        .annotate(owing=F('total_amount') - F('amount_paid'))
        .filter(owing__gt=ZERO)
    )

    results = []
    for label, low, high in buckets:
        if low is None:
            qs = base.filter(due_date__gte=today)
        else:
            qs = base.filter(due_date__lte=today - dt.timedelta(days=low))
            if high is not None:
                qs = qs.filter(due_date__gte=today - dt.timedelta(days=high))
        total = qs.aggregate(
            t=Coalesce(Sum('owing'), Value(ZERO), output_field=MONEY)
        )['t']
        results.append({'label': label, 'amount': total, 'count': qs.count()})
    return results


def guardian_statement(guardian):
    """Every invoice and payment for one family, with a running balance."""
    invoices = (
        Invoice.objects.for_guardian(guardian)
        .exclude(status=InvoiceStatus.DRAFT)
        .select_related('student', 'term')
        .prefetch_related('items', 'payments')
        .order_by('-issue_date')
    )
    billed = _sum(invoices, 'total_amount')
    paid = _sum(invoices, 'amount_paid')
    return {
        'invoices': invoices,
        'total_billed': billed,
        'total_paid': paid,
        'balance': billed - paid,
        'overdue_count': sum(1 for inv in invoices if inv.is_overdue),
    }


# ---------------------------------------------------------------------------
# Everything a report page needs, in one call
# ---------------------------------------------------------------------------
def build_report(period='month', start=None, end=None, anchor=None):
    start, end = period_bounds(period, anchor=anchor, start=start, end=end)
    return {
        'period': period,
        'start': start,
        'end': end,
        'period_label': label_for_period(period, start, end),
        'summary': financial_summary(start, end),
        'comparison': compare_with_previous(start, end),
        'series': income_expense_series(start, end),
        'income_breakdown': income_breakdown(start, end),
        'expense_breakdown': expense_breakdown(start, end),
        'payment_methods': payment_method_breakdown(start, end),
        'programme_revenue': revenue_by_programme(start, end),
        'ageing': ageing_analysis(),
    }
