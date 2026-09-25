"""Django admin for the ledger."""

from django.contrib import admin, messages
from django.db.models import Sum
from django.utils.html import format_html

from .models import (
    Budget,
    Expense,
    ExpenseCategory,
    FeeCategory,
    FeeStructure,
    IncomeCategory,
    Invoice,
    InvoiceItem,
    OtherIncome,
    PayrollEntry,
    Payment,
    Scholarship,
    TransactionStatus,
)


def _money(value):
    return format_html('<strong>UGX {}</strong>', f'{value:,.0f}')


@admin.register(FeeCategory)
class FeeCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'is_tuition', 'display_order', 'is_active')
    list_editable = ('display_order', 'is_active')


@admin.register(FeeStructure)
class FeeStructureAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'program', 'term', 'amount_display',
                    'billing_cycle', 'is_mandatory', 'is_active')
    list_filter = ('category', 'program', 'term', 'billing_cycle', 'is_active')
    search_fields = ('name', 'description')

    @admin.display(description='Amount', ordering='amount')
    def amount_display(self, obj):
        return _money(obj.amount)


@admin.register(Scholarship)
class ScholarshipAdmin(admin.ModelAdmin):
    list_display = ('student', 'name', 'discount_type', 'value', 'sponsor',
                    'starts_on', 'ends_on', 'is_active')
    list_filter = ('discount_type', 'is_active', 'applies_to_category')
    search_fields = ('name', 'sponsor', 'student__first_name', 'student__last_name')
    autocomplete_fields = ('student',)


class InvoiceItemInline(admin.TabularInline):
    model = InvoiceItem
    extra = 1
    readonly_fields = ('amount',)


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    fields = ('receipt_number', 'payment_date', 'payment_time', 'amount',
              'method', 'transaction_id', 'status')
    readonly_fields = ('receipt_number',)


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('number', 'student', 'term', 'issue_date', 'due_date',
                    'total_display', 'paid_display', 'balance_display', 'status_pill')
    list_filter = ('status', 'term', 'issue_date', 'due_date')
    search_fields = ('number', 'student__first_name', 'student__last_name',
                     'student__student_id')
    readonly_fields = ('number', 'subtotal', 'total_amount', 'amount_paid',
                       'created_at', 'updated_at')
    autocomplete_fields = ('student',)
    inlines = (InvoiceItemInline, PaymentInline)
    date_hierarchy = 'issue_date'
    actions = ('recalculate_selected', 'issue_selected')

    @admin.display(description='Total', ordering='total_amount')
    def total_display(self, obj):
        return _money(obj.total_amount)

    @admin.display(description='Paid', ordering='amount_paid')
    def paid_display(self, obj):
        return f'UGX {obj.amount_paid:,.0f}'

    @admin.display(description='Balance')
    def balance_display(self, obj):
        colour = '#1f8a5f' if obj.balance <= 0 else '#b3261e'
        return format_html(
            '<span style="color:{};font-weight:600;">UGX {}</span>',
            colour, f'{obj.balance:,.0f}',
        )

    @admin.display(description='Status', ordering='status')
    def status_pill(self, obj):
        if obj.is_overdue:
            return format_html(
                '<span style="background:#b3261e;color:#fff;padding:2px 10px;'
                'border-radius:20px;font-size:11px;">Overdue {} days</span>',
                obj.days_overdue,
            )
        return obj.get_status_display()

    @admin.action(description='Recalculate totals')
    def recalculate_selected(self, request, queryset):
        for invoice in queryset:
            invoice.recalculate()
        self.message_user(request, f'{queryset.count()} invoice(s) recalculated.')

    @admin.action(description='Issue selected draft invoices')
    def issue_selected(self, request, queryset):
        count = 0
        for invoice in queryset.filter(status='draft'):
            invoice.issue(by=request.user)
            count += 1
        self.message_user(request, f'{count} invoice(s) issued.', messages.SUCCESS)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('receipt_number', 'payment_date', 'payment_time', 'student',
                    'amount_display', 'method', 'transaction_id', 'status',
                    'received_by')
    list_filter = ('method', 'status', 'payment_date')
    search_fields = ('receipt_number', 'transaction_id', 'payer_name',
                     'student__first_name', 'student__last_name')
    readonly_fields = ('receipt_number', 'created_at', 'updated_at')
    autocomplete_fields = ('student', 'invoice')
    date_hierarchy = 'payment_date'
    actions = ('confirm_selected',)

    fieldsets = (
        ('The payment', {'fields': ('receipt_number', 'amount', 'payment_date',
                                    'payment_time', 'method', 'transaction_id')}),
        ('Applied to', {'fields': ('invoice', 'student')}),
        ('Who paid', {'fields': ('payer_name', 'payer_phone', 'bank_name',
                                 'account_number')}),
        ('Handling', {'fields': ('status', 'received_by', 'recorded_by',
                                 'confirmed_by', 'confirmed_at', 'proof', 'notes',
                                 'reversal_reason')}),
    )

    @admin.display(description='Amount', ordering='amount')
    def amount_display(self, obj):
        return _money(obj.amount)

    @admin.action(description='Confirm selected payments')
    def confirm_selected(self, request, queryset):
        count = 0
        for payment in queryset.exclude(status=TransactionStatus.CONFIRMED):
            payment.confirm(by=request.user)
            count += 1
        self.message_user(request, f'{count} payment(s) confirmed.', messages.SUCCESS)


@admin.register(IncomeCategory)
class IncomeCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'display_order', 'is_active')
    list_editable = ('display_order', 'is_active')


@admin.register(OtherIncome)
class OtherIncomeAdmin(admin.ModelAdmin):
    list_display = ('reference', 'received_date', 'category', 'description',
                    'amount_display', 'method', 'source_name', 'status')
    list_filter = ('category', 'method', 'status', 'received_date')
    search_fields = ('description', 'source_name', 'transaction_id', 'reference')
    readonly_fields = ('reference',)
    date_hierarchy = 'received_date'

    @admin.display(description='Amount', ordering='amount')
    def amount_display(self, obj):
        return _money(obj.amount)


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_recurring', 'display_order', 'spent_total', 'is_active')
    list_editable = ('display_order', 'is_active')

    @admin.display(description='Total spent')
    def spent_total(self, obj):
        total = obj.expenses.aggregate(t=Sum('amount'))['t'] or 0
        return f'UGX {total:,.0f}'


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ('reference', 'expense_date', 'category', 'description',
                    'amount_display', 'method', 'payee_name', 'status')
    list_filter = ('category', 'method', 'status', 'expense_date', 'event')
    search_fields = ('description', 'payee_name', 'transaction_id', 'reference')
    readonly_fields = ('reference', 'created_at', 'updated_at')
    date_hierarchy = 'expense_date'
    actions = ('approve_selected',)

    @admin.display(description='Amount', ordering='amount')
    def amount_display(self, obj):
        return _money(obj.amount)

    @admin.action(description='Approve selected expenses')
    def approve_selected(self, request, queryset):
        count = 0
        for expense in queryset:
            expense.approve(by=request.user)
            count += 1
        self.message_user(request, f'{count} expense(s) approved.', messages.SUCCESS)


@admin.register(PayrollEntry)
class PayrollEntryAdmin(admin.ModelAdmin):
    list_display = ('staff', 'period_start', 'period_end', 'gross_amount',
                    'deductions', 'net_amount', 'status', 'paid_date')
    list_filter = ('status', 'method', 'period_start')
    search_fields = ('staff__user__first_name', 'staff__user__last_name',
                     'transaction_id')
    readonly_fields = ('net_amount',)
    autocomplete_fields = ('staff',)


@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'period_start', 'period_end',
                    'planned_amount', 'actual_display', 'used_percent')
    list_filter = ('category', 'term')

    @admin.display(description='Actual')
    def actual_display(self, obj):
        colour = '#b3261e' if obj.is_over_budget else '#1f8a5f'
        return format_html(
            '<span style="color:{};">UGX {}</span>', colour, f'{obj.actual_amount:,.0f}',
        )
