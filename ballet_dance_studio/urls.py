"""Root URL configuration for Ballet Dance Studio UG."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve

from apps.website import views as website_views

urlpatterns = [
    path('healthz', website_views.healthz, name='healthz'),

    path('django-admin/', admin.site.urls),

    path('accounts/', include('apps.accounts.urls')),
    path('dashboard/', include('apps.accounts.dashboard_urls')),
    path('studio/', include('apps.academics.urls')),
    path('finance/', include('apps.finance.urls')),
    path('events/', include('apps.events.urls')),

    path('robots.txt', website_views.robots_txt, name='robots'),
    path('sitemap.xml', website_views.sitemap_xml, name='sitemap'),

    # Public site last so its catch-all page slug does not shadow the apps.
    path('', include('apps.website.urls')),
]

handler404 = 'apps.website.views.error_404'
handler500 = 'apps.website.views.error_500'

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.BASE_DIR / 'static')
elif settings.SERVE_MEDIA:
    # WhiteNoise handles /static/, but uploads live outside it. With a Render
    # persistent disk mounted at MEDIA_ROOT, Django serves them itself.
    #
    # This ties up a worker for the length of each file transfer, which is fine
    # for a studio's traffic but is the first thing to move behind a CDN or
    # object store if the gallery ever gets busy. Setting SERVE_MEDIA=false
    # turns it off once storage lives elsewhere.
    urlpatterns += [
        re_path(
            r'^media/(?P<path>.*)$', serve,
            {'document_root': settings.MEDIA_ROOT},
        ),
    ]
