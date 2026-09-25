"""Template context available on every page."""

import datetime as dt

from django.conf import settings as django_settings

from apps.academics.models import Program

from .models import Announcement, Page, SiteSettings


def site_settings(request):
    """
    Studio identity, navigation content, live announcements and the unread
    notification count.

    Kept deliberately lean -- this runs on every single request including the
    dashboards, so it is a handful of small, indexed queries.
    """
    user = getattr(request, 'user', None)

    unread_notifications = 0
    if user is not None and user.is_authenticated:
        unread_notifications = user.notifications.filter(is_read=False).count()

    announcements = list(
        Announcement.live_for(user).order_by('-is_pinned', '-starts_at')[:5]
    )

    return {
        'studio': SiteSettings.load(),
        'site_programmes': Program.objects.filter(
            is_active=True, show_on_website=True,
        ).only('name', 'slug')[:6],
        'footer_pages': Page.objects.filter(
            show_in_footer=True, status='published',
        ).only('title', 'slug'),
        'announcements': announcements,
        'bar_announcement': next((a for a in announcements if a.show_in_bar), None),
        'unread_notifications': unread_notifications,
        'current_year': dt.date.today().year,
        'CURRENCY': django_settings.CURRENCY_SYMBOL,
        'DEBUG': django_settings.DEBUG,
    }
