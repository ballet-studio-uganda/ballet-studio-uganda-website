"""Calendar, events and the annual recital."""

from __future__ import annotations

import calendar as cal
import datetime as dt
from collections import defaultdict

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.permissions import management_required

from .forms import EventRegistrationForm
from .models import (
    Event,
    EventCategory,
    EventRegistration,
    Partner,
    Recital,
    RecitalCast,
    RegistrationStatus,
)


# ---------------------------------------------------------------------------
# Listing and calendar
# ---------------------------------------------------------------------------
def event_list(request):
    events = Event.objects.visible_to(request.user).select_related('category')

    category = request.GET.get('category')
    if category:
        events = events.filter(category__slug=category)

    when = request.GET.get('when', 'upcoming')
    if when == 'past':
        events = events.filter(start_at__lt=timezone.now()).order_by('-start_at')
    else:
        events = events.filter(start_at__gte=timezone.now()).order_by('start_at')

    page = Paginator(events, 12).get_page(request.GET.get('page'))
    return render(request, 'events/event_list.html', {
        'page_title': 'What’s on',
        'page_obj': page,
        'categories': EventCategory.objects.filter(is_active=True),
        'active_category': category,
        'when': when,
    })


def event_detail(request, slug):
    event = get_object_or_404(
        Event.objects.visible_to(request.user).select_related('category'), slug=slug,
    )
    form = None
    if event.registration_open:
        form = EventRegistrationForm(request.POST or None, event=event, user=request.user)
        if request.method == 'POST' and form.is_valid():
            registration = form.save(commit=False)
            registration.event = event
            if request.user.is_authenticated:
                registration.user = request.user
            registration.status = (
                RegistrationStatus.WAITLIST
                if event.seats_left is not None and registration.seats > event.seats_left
                else RegistrationStatus.CONFIRMED
            )
            registration.save()
            messages.success(
                request,
                'You are booked in. We have sent the details to your email.'
                if registration.status == RegistrationStatus.CONFIRMED
                else 'This event is full — you are on the waiting list.',
            )
            return redirect(event.get_absolute_url())

    return render(request, 'events/event_detail.html', {
        'page_title': event.title,
        'meta_description': event.summary,
        'event': event,
        'form': form,
        'related': Event.objects.visible_to(request.user)
                       .filter(category=event.category)
                       .exclude(pk=event.pk)
                       .filter(start_at__gte=timezone.now())[:3],
    })


def calendar_view(request, year=None, month=None):
    """
    A month grid of events. Falls back to the current month, and hands the
    template a list of week rows so the markup stays simple.
    """
    today = dt.date.today()
    year = int(year or request.GET.get('year') or today.year)
    month = int(month or request.GET.get('month') or today.month)

    if not 1 <= month <= 12:
        raise Http404('No such month.')

    events = (
        Event.objects.visible_to(request.user)
        .in_month(year, month)
        .select_related('category')
        .order_by('start_at')
    )

    by_day = defaultdict(list)
    for event in events:
        by_day[timezone.localtime(event.start_at).day].append(event)

    grid = cal.Calendar(firstweekday=0).monthdayscalendar(year, month)
    weeks = [
        [
            {
                'day': day,
                'date': dt.date(year, month, day) if day else None,
                'events': by_day.get(day, []),
                'is_today': bool(day) and dt.date(year, month, day) == today,
            }
            for day in week
        ]
        for week in grid
    ]

    prev_month = dt.date(year, month, 1) - dt.timedelta(days=1)
    next_month = dt.date(year, month, cal.monthrange(year, month)[1]) + dt.timedelta(days=1)

    context = {
        'page_title': f'{cal.month_name[month]} {year}',
        'year': year,
        'month': month,
        'month_name': cal.month_name[month],
        'weeks': weeks,
        'weekday_names': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
        'events': events,
        'prev': {'year': prev_month.year, 'month': prev_month.month},
        'next': {'year': next_month.year, 'month': next_month.month},
        'today': today,
        'categories': EventCategory.objects.filter(is_active=True),
    }
    if request.headers.get('HX-Request'):
        return render(request, 'events/partials/calendar_grid.html', context)
    return render(request, 'events/calendar.html', context)


def year_view(request, year=None):
    """Twelve small month grids -- the year at a glance."""
    today = dt.date.today()
    year = int(year or today.year)

    events = (
        Event.objects.visible_to(request.user)
        .filter(start_at__year=year)
        .select_related('category')
        .order_by('start_at')
    )

    by_month = defaultdict(list)
    for event in events:
        by_month[timezone.localtime(event.start_at).month].append(event)

    months = [
        {
            'number': m,
            'name': cal.month_name[m],
            'abbr': cal.month_abbr[m],
            'events': by_month.get(m, []),
            'weeks': cal.Calendar(firstweekday=0).monthdayscalendar(year, m),
            'event_days': {
                timezone.localtime(e.start_at).day for e in by_month.get(m, [])
            },
        }
        for m in range(1, 13)
    ]

    return render(request, 'events/year.html', {
        'page_title': f'{year} calendar',
        'year': year,
        'months': months,
        'total_events': events.count(),
        'today': today,
        'prev_year': year - 1,
        'next_year': year + 1,
    })


def calendar_feed(request):
    """JSON feed, for any client-side calendar widget."""
    start = request.GET.get('start')
    end = request.GET.get('end')
    events = Event.objects.visible_to(request.user).select_related('category')
    if start:
        events = events.filter(start_at__gte=start)
    if end:
        events = events.filter(start_at__lte=end)

    return JsonResponse([
        {
            'id': e.pk,
            'title': e.title,
            'start': e.start_at.isoformat(),
            'end': e.end_at.isoformat() if e.end_at else None,
            'allDay': e.is_all_day,
            'url': e.get_absolute_url(),
            'colour': e.category.colour if e.category else '#EE2A7B',
            'category': e.category.name if e.category else '',
            'venue': e.venue_name,
        }
        for e in events[:500]
    ], safe=False)


# ---------------------------------------------------------------------------
# The annual recital
# ---------------------------------------------------------------------------
def recital(request):
    """The current recital, or the archive if none is published."""
    current = Recital.current()
    if not current:
        return render(request, 'events/recital_empty.html', {
            'page_title': 'The annual recital',
            'past': Recital.objects.filter(is_published=True).order_by('-year'),
        })
    return _render_recital(request, current)


def recital_year(request, year):
    entry = get_object_or_404(Recital, year=year, is_published=True)
    return _render_recital(request, entry)


def _render_recital(request, entry):
    performances = (
        entry.performances.select_related('dance_class__program')
        .prefetch_related('cast__student')
        .order_by('order')
    )
    acts = defaultdict(list)
    for item in performances:
        acts[item.act or 'Programme'].append(item)

    return render(request, 'events/recital.html', {
        'page_title': f'{entry.title} — {entry.year} Recital',
        'meta_description': (
            entry.tagline
            or f'{entry.title}: the Ballet Dance Studio UG annual recital for sickle cell awareness.'
        ),
        'recital': entry,
        'performances': performances,
        'acts': dict(acts),
        'partners': Partner.objects.filter(is_active=True).filter(
            recitals=entry,
        ) or Partner.objects.filter(is_active=True),
        'sickle_cell_partners': Partner.objects.filter(
            is_active=True, is_sickle_cell_partner=True,
        ),
        'archive': Recital.objects.filter(is_published=True)
                       .exclude(pk=entry.pk).order_by('-year')[:6],
        'rehearsals': entry.rehearsals.all() if request.user.is_authenticated else None,
        'gallery': entry.gallery_album,
    })


def recital_archive(request):
    return render(request, 'events/recital_archive.html', {
        'page_title': 'Recital archive',
        'recitals': Recital.objects.filter(is_published=True).order_by('-year'),
    })


# ---------------------------------------------------------------------------
# Staff side
# ---------------------------------------------------------------------------
@management_required
def registration_list(request, pk):
    event = get_object_or_404(Event, pk=pk)
    return render(request, 'events/manage/registrations.html', {
        'page_title': f'Registrations — {event.title}',
        'event': event,
        'registrations': event.registrations.select_related('user').order_by('-created_at'),
        'summary': event.financial_summary(),
    })


@management_required
@require_POST
def check_in(request, pk):
    registration = get_object_or_404(EventRegistration, pk=pk)
    registration.status = RegistrationStatus.ATTENDED
    registration.checked_in_at = timezone.now()
    registration.save(update_fields=['status', 'checked_in_at'])
    if request.headers.get('HX-Request'):
        return HttpResponse('<span class="pill pill-success">Checked in</span>')
    return redirect('events:registrations', pk=registration.event_id)


@management_required
def cast_sheet(request, year):
    """Printable cast list for a recital."""
    entry = get_object_or_404(Recital, year=year)
    return render(request, 'events/manage/cast_sheet.html', {
        'page_title': f'{entry.title} — cast',
        'recital': entry,
        'cast': RecitalCast.objects.filter(performance__recital=entry)
                    .select_related('student', 'performance')
                    .order_by('performance__order', 'student__first_name'),
    })
