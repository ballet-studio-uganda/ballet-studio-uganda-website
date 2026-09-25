"""The public-facing website."""

from __future__ import annotations

import datetime as dt

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.academics.models import ApplicationStatus, EnrolmentApplication, Program
from apps.accounts.models import (
    ApprovalStatus,
    Student,
    Notification,
    NotificationLevel,
    Role,
    StaffProfile,
    User,
)
from apps.events.models import Event, Recital

from .forms import ContactForm, EnrolmentApplicationForm, NewsletterForm
from .models import (
    FAQ,
    ContactMessage,
    GalleryAlbum,
    HeroSlide,
    NewsCategory,
    NewsPost,
    NewsletterSubscriber,
    Page,
    PublishStatus,
    SiteSettings,
    Testimonial,
    VideoFeature,
)


# ---------------------------------------------------------------------------
# Home
# ---------------------------------------------------------------------------
def home(request):
    """
    The landing page: a full-bleed video hero with animated text over it,
    then programmes, the recital, news, gallery and testimonials.
    """
    recital = Recital.current()
    settings_row = SiteSettings.load()

    context = {
        'page_title': 'Ballet Dance Studio UG',
        'meta_description': (
            'Ballet Dance Studio UG — classical ballet training in Kampala. '
            'Resilience. Hope. Dreams.'
        ),
        'hero_slides': HeroSlide.objects.filter(is_active=True),
        'programmes': Program.objects.filter(is_active=True, show_on_website=True)[:6],
        'recital': recital,
        'featured_news': NewsPost.objects.published().select_related('category')[:3],
        'upcoming_events': Event.objects.public().upcoming()[:4],
        'featured_albums': GalleryAlbum.objects.filter(is_public=True)
                               .prefetch_related('images')[:6],
        'testimonials': Testimonial.objects.filter(is_published=True)[:6],
        'faculty': StaffProfile.objects.filter(
            show_on_website=True, is_active_staff=True,
        ).select_related('user')[:4],
        # Dancers means people the studio has actually taught -- not the
        # subset old enough to hold a login.
        'stats': {
            'years': timezone.now().year - settings_row.founded_year,
            'dancers': Student.objects.count(),
            'programmes': Program.objects.filter(is_active=True).count(),
            'recitals': Recital.objects.filter(is_published=True).count(),
        },
    }
    return render(request, 'website/home.html', context)


# ---------------------------------------------------------------------------
# About and programmes
# ---------------------------------------------------------------------------
def about(request):
    return render(request, 'website/about.html', {
        'page_title': 'About the studio',
        'faculty': StaffProfile.objects.filter(
            show_on_website=True, is_active_staff=True,
        ).select_related('user'),
        'testimonials': Testimonial.objects.filter(is_published=True)[:4],
        'partners': _partners(),
    })


def _partners():
    from apps.events.models import Partner
    return Partner.objects.filter(is_active=True)


def faculty(request):
    return render(request, 'website/faculty.html', {
        'page_title': 'Our faculty',
        'faculty': StaffProfile.objects.filter(
            show_on_website=True, is_active_staff=True,
        ).select_related('user').prefetch_related('classes_taught__program'),
    })


def programme_list(request):
    return render(request, 'website/programmes.html', {
        'page_title': 'Training programmes',
        'programmes': Program.objects.filter(is_active=True, show_on_website=True),
    })


def programme_detail(request, slug):
    programme = get_object_or_404(
        Program, slug=slug, is_active=True, show_on_website=True,
    )
    return render(request, 'website/programme_detail.html', {
        'page_title': programme.name,
        'programme': programme,
        'classes': programme.classes.filter(is_active=True)
                       .select_related('term', 'studio')
                       .prefetch_related('teachers__user', 'schedules'),
        'related': Program.objects.filter(is_active=True, show_on_website=True)
                       .exclude(pk=programme.pk)[:3],
    })


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------
def news_list(request):
    posts = NewsPost.objects.published().select_related('category', 'author')

    category_slug = request.GET.get('category')
    if category_slug:
        posts = posts.filter(category__slug=category_slug)

    query = request.GET.get('q', '').strip()
    if query:
        posts = posts.filter(
            Q(title__icontains=query) | Q(excerpt__icontains=query)
            | Q(body__icontains=query) | Q(tags__icontains=query)
        )

    page = Paginator(posts, 9).get_page(request.GET.get('page'))
    return render(request, 'website/news_list.html', {
        'page_title': 'News & announcements',
        'page_obj': page,
        'categories': NewsCategory.objects.annotate(n=Count('posts')),
        'active_category': category_slug,
        'q': query,
    })


def news_detail(request, slug):
    post = get_object_or_404(
        NewsPost.objects.published().select_related('category', 'author'), slug=slug,
    )
    NewsPost.objects.filter(pk=post.pk).update(view_count=post.view_count + 1)
    return render(request, 'website/news_detail.html', {
        'page_title': post.title,
        'meta_description': post.meta_description or post.excerpt,
        'post': post,
        'related': NewsPost.objects.published()
                       .filter(category=post.category)
                       .exclude(pk=post.pk)[:3],
    })


# ---------------------------------------------------------------------------
# Gallery
# ---------------------------------------------------------------------------
def gallery(request):
    albums = (
        GalleryAlbum.objects.filter(is_public=True)
        .select_related('event')
        .prefetch_related('images')
        .annotate(photo_count=Count('images'))
        # annotate() drops Meta.ordering, which makes pagination unstable.
        .order_by('display_order', '-date', '-created_at')
    )
    year = request.GET.get('year')
    if year and year.isdigit():
        albums = albums.filter(date__year=int(year))

    years = (
        GalleryAlbum.objects.filter(is_public=True, date__isnull=False)
        .dates('date', 'year', order='DESC')
    )
    page = Paginator(albums, 12).get_page(request.GET.get('page'))
    return render(request, 'website/gallery.html', {
        'page_title': 'Gallery',
        'page_obj': page,
        'years': years,
        'active_year': year,
    })


def album_detail(request, slug):
    album = get_object_or_404(
        GalleryAlbum.objects.filter(is_public=True).prefetch_related('images'), slug=slug,
    )
    return render(request, 'website/album_detail.html', {
        'page_title': album.title,
        'album': album,
        'images': album.images.all(),
        'more': GalleryAlbum.objects.filter(is_public=True).exclude(pk=album.pk)[:4],
    })


def videos(request):
    return render(request, 'website/videos.html', {
        'page_title': 'Watch',
        'videos': VideoFeature.objects.filter(is_published=True).select_related('event'),
    })


# ---------------------------------------------------------------------------
# Contact, enrolment, newsletter
# ---------------------------------------------------------------------------
def contact(request):
    form = ContactForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        message = form.save(commit=False)
        forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
        message.ip_address = (
            forwarded.split(',')[0].strip() or request.META.get('REMOTE_ADDR')
        )
        message.save()
        _notify_office(
            'New message from the website',
            f'{message.name} wrote about {message.get_topic_display()}.',
            reverse('website:inbox'),
        )
        messages.success(
            request, 'Thank you for writing to us. We will reply within two working days.',
        )
        return redirect('website:contact')

    return render(request, 'website/contact.html', {
        'page_title': 'Contact us',
        'form': form,
        'faqs': FAQ.objects.filter(is_published=True)[:8],
    })


def enrol(request):
    """The public enrolment enquiry form."""
    site = SiteSettings.load()
    form = EnrolmentApplicationForm(request.POST or None)

    if request.method == 'POST' and form.is_valid():
        application = form.save()
        _notify_office(
            'New enrolment enquiry',
            f'{application.student_full_name} (age {application.student_age}) '
            f'— {application.program.name if application.program else "no programme chosen"}.',
            reverse('website:applications'),
        )
        messages.success(
            request,
            'Thank you. We have your enquiry and will be in touch to arrange a trial class.',
        )
        return redirect('website:enrol_thanks')

    return render(request, 'website/enrol.html', {
        'page_title': 'Enrol with us',
        'form': form,
        'programmes': Program.objects.filter(is_active=True, show_on_website=True),
        'enrolment_open': site.enrolment_open,
        'faqs': FAQ.objects.filter(is_published=True, category__iexact='Enrolment'),
    })


def enrol_thanks(request):
    return render(request, 'website/enrol_thanks.html', {
        'page_title': 'Enquiry received',
    })


def _notify_office(title, message, url):
    """Ping every verified administrator and director."""
    Notification.send(
        User.objects.filter(
            role__in=[Role.ADMIN, Role.DIRECTOR], approval_status=ApprovalStatus.APPROVED,
        ),
        title=title, message=message, level=NotificationLevel.INFO,
        url=url, icon='fa-envelope',
    )


@require_POST
def newsletter_signup(request):
    form = NewsletterForm(request.POST)
    if form.is_valid():
        NewsletterSubscriber.objects.get_or_create(
            email=form.cleaned_data['email'].lower(),
            defaults={'name': form.cleaned_data.get('name', '')},
        )
        text = 'You are on the list. Thank you for following the studio.'
    else:
        text = 'Please check the email address and try again.'

    if request.headers.get('HX-Request'):
        return HttpResponse(f'<p class="form-flash">{text}</p>')
    messages.info(request, text)
    return redirect(request.META.get('HTTP_REFERER', 'website:home'))


# ---------------------------------------------------------------------------
# Flat pages and utilities
# ---------------------------------------------------------------------------
def faqs(request):
    entries = FAQ.objects.filter(is_published=True)
    grouped: dict[str, list] = {}
    for item in entries:
        grouped.setdefault(item.category or 'General', []).append(item)
    return render(request, 'website/faqs.html', {
        'page_title': 'Frequently asked questions',
        'grouped': grouped,
    })


def page(request, slug):
    entry = get_object_or_404(Page, slug=slug, status=PublishStatus.PUBLISHED)
    return render(request, 'website/page.html', {
        'page_title': entry.title,
        'meta_description': entry.meta_description,
        'entry': entry,
    })


def search(request):
    query = request.GET.get('q', '').strip()
    results = {'news': [], 'programmes': [], 'events': [], 'albums': []}
    if query:
        results['news'] = NewsPost.objects.published().filter(
            Q(title__icontains=query) | Q(body__icontains=query)
        )[:8]
        results['programmes'] = Program.objects.filter(
            Q(name__icontains=query) | Q(description__icontains=query),
            is_active=True, show_on_website=True,
        )[:5]
        results['events'] = Event.objects.public().filter(
            Q(title__icontains=query) | Q(description__icontains=query)
        )[:8]
        results['albums'] = GalleryAlbum.objects.filter(
            title__icontains=query, is_public=True,
        )[:6]
    return render(request, 'website/search.html', {
        'page_title': f'Search: {query}' if query else 'Search',
        'q': query,
        'results': results,
        'total': sum(len(v) for v in results.values()),
    })


def healthz(request):
    """
    Render pings this to decide whether the deploy came up.

    It touches the database on purpose: a web process that cannot reach
    Postgres is not healthy, however cheerfully it returns 200.
    """
    from django.db import connection
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
    except Exception as exc:                       # pragma: no cover
        return HttpResponse(f'database unavailable: {exc}', status=503,
                            content_type='text/plain')
    return HttpResponse('ok', content_type='text/plain')


def robots_txt(request):
    lines = [
        'User-agent: *',
        'Disallow: /dashboard/',
        'Disallow: /finance/',
        'Disallow: /studio/',
        'Disallow: /django-admin/',
        'Disallow: /accounts/',
        'Allow: /',
        f'Sitemap: {request.build_absolute_uri("/sitemap.xml")}',
    ]
    return HttpResponse('\n'.join(lines), content_type='text/plain')


def sitemap_xml(request):
    urls = [request.build_absolute_uri(reverse(name)) for name in (
        'website:home', 'website:about', 'website:programmes', 'website:news_list',
        'website:gallery', 'website:contact', 'website:enrol', 'events:calendar',
        'events:recital',
    )]
    urls += [
        request.build_absolute_uri(obj.get_absolute_url())
        for obj in list(NewsPost.objects.published())
        + list(Program.objects.filter(is_active=True, show_on_website=True))
        + list(GalleryAlbum.objects.filter(is_public=True))
        + list(Event.objects.public())
    ]
    body = ''.join(f'<url><loc>{u}</loc></url>' for u in urls)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f'{body}</urlset>'
    )
    return HttpResponse(xml, content_type='application/xml')


def error_404(request, exception=None):
    return render(request, 'website/404.html', status=404)


def error_500(request):
    return render(request, 'website/500.html', status=500)


# ---------------------------------------------------------------------------
# Staff-side content management
# ---------------------------------------------------------------------------
from apps.accounts.permissions import management_required  # noqa: E402


@management_required
def inbox(request):
    """Messages sent through the contact form."""
    qs = ContactMessage.objects.filter(is_archived=False)
    if request.GET.get('filter') == 'unread':
        qs = qs.filter(is_read=False)
    page = Paginator(qs, 25).get_page(request.GET.get('page'))
    return render(request, 'website/manage/inbox.html', {
        'page_title': 'Website inbox',
        'page_obj': page,
        'unread': ContactMessage.objects.filter(is_read=False, is_archived=False).count(),
    })


@management_required
def inbox_detail(request, pk):
    message = get_object_or_404(ContactMessage, pk=pk)
    if not message.is_read:
        message.is_read = True
        message.handled_by = request.user
        message.save(update_fields=['is_read', 'handled_by'])
    return render(request, 'website/manage/inbox_detail.html', {
        'page_title': message.subject or message.name,
        'message': message,
    })


@management_required
def applications(request):
    """Enrolment enquiries from the public site."""
    qs = EnrolmentApplication.objects.select_related('program', 'created_student')
    status = request.GET.get('status')
    if status:
        qs = qs.filter(status=status)
    page = Paginator(qs, 25).get_page(request.GET.get('page'))
    return render(request, 'website/manage/applications.html', {
        'page_title': 'Enrolment enquiries',
        'page_obj': page,
        'statuses': ApplicationStatus.choices,
        'active_status': status,
        'new_count': EnrolmentApplication.objects.filter(
            status=ApplicationStatus.NEW,
        ).count(),
    })
