"""Public website URLs. The flat-page catch-all stays last."""

from django.urls import path

from . import views

app_name = 'website'

urlpatterns = [
    path('', views.home, name='home'),

    path('about/', views.about, name='about'),
    path('faculty/', views.faculty, name='faculty'),

    path('programmes/', views.programme_list, name='programmes'),
    path('programmes/<slug:slug>/', views.programme_detail, name='programme_detail'),

    path('news/', views.news_list, name='news_list'),
    path('news/<slug:slug>/', views.news_detail, name='news_detail'),

    path('gallery/', views.gallery, name='gallery'),
    path('gallery/<slug:slug>/', views.album_detail, name='album_detail'),
    path('watch/', views.videos, name='videos'),

    path('contact/', views.contact, name='contact'),
    path('enrol/', views.enrol, name='enrol'),
    path('enrol/thank-you/', views.enrol_thanks, name='enrol_thanks'),
    path('newsletter/', views.newsletter_signup, name='newsletter'),
    path('faqs/', views.faqs, name='faqs'),
    path('search/', views.search, name='search'),

    # Staff-side content management
    path('manage/inbox/', views.inbox, name='inbox'),
    path('manage/inbox/<int:pk>/', views.inbox_detail, name='inbox_detail'),
    path('manage/applications/', views.applications, name='applications'),

    # Editable flat pages -- must stay last.
    path('<slug:slug>/', views.page, name='page'),
]
