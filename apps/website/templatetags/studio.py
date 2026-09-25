"""Small template helpers used across the studio's templates."""

import os

from django import template
from django.conf import settings
from django.contrib.staticfiles import finders
from django.templatetags.static import static
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag
def static_v(path):
    """
    ``{% static %}``, plus a cache-busting stamp while developing.

    Browsers cache CSS and JS hard even against the dev server, so an edit to a
    stylesheet quietly does nothing until a manual refresh. Stamping the URL
    with the file's mtime makes every save land immediately.

    In production the stamp is dropped: the manifest storage already puts a
    content hash in the filename, which is a better cache key than an mtime
    (it only changes when the bytes do) and keeps the URL free of a query
    string that some caches and CDNs handle badly.
    """
    url = static(path)
    if not settings.DEBUG:
        return url

    absolute = finders.find(path)
    if not absolute:
        return url

    stamp = int(os.path.getmtime(absolute))
    separator = '&' if '?' in url else '?'
    return f'{url}{separator}v={stamp}'


@register.filter
def money(value, symbol=None):
    """``250000`` -> ``UGX 250,000``. Blank input renders as an em dash."""
    if value in (None, ''):
        return mark_safe('&mdash;')
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return value
    return f'{symbol or settings.CURRENCY_SYMBOL} {amount:,.0f}'


@register.filter
def percent(value, places=0):
    """Render a number as a percentage, or an em dash when it is unknown."""
    if value is None or value == '':
        return mark_safe('&mdash;')
    try:
        return f'{float(value):.{places}f}%'
    except (TypeError, ValueError):
        return value


@register.filter
def initials(name):
    """First letters of the first two words, for avatar fallbacks."""
    parts = [p for p in str(name).split() if p][:2]
    return ''.join(p[0].upper() for p in parts) or '?'
