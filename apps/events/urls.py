"""Calendar, events and recital URLs."""

from django.urls import path

from . import views

app_name = 'events'

urlpatterns = [
    path('', views.event_list, name='list'),

    path('calendar/', views.calendar_view, name='calendar'),
    path('calendar/<int:year>/<int:month>/', views.calendar_view, name='calendar_month'),
    path('calendar/<int:year>/', views.year_view, name='calendar_year'),
    path('calendar/feed/', views.calendar_feed, name='calendar_feed'),

    path('recital/', views.recital, name='recital'),
    path('recital/archive/', views.recital_archive, name='recital_archive'),
    path('recital/<int:year>/', views.recital_year, name='recital_year'),

    path('manage/<int:pk>/registrations/', views.registration_list, name='registrations'),
    path('manage/registration/<int:pk>/check-in/', views.check_in, name='check_in'),
    path('manage/cast/<int:year>/', views.cast_sheet, name='cast_sheet'),

    path('<slug:slug>/', views.event_detail, name='detail'),
]
