"""Dashboard and people-management URLs (mounted at /dashboard/)."""

from django.urls import path

from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.dashboard, name='home'),

    # People
    path('people/', views.user_list, name='user_list'),
    path('people/verify/', views.verification_queue, name='verification_queue'),
    path('people/<int:pk>/', views.user_detail, name='user_detail'),
    path('people/<int:pk>/verify/', views.quick_verify, name='quick_verify'),

    path('staff/', views.staff_list, name='staff_list'),
    path('staff/<int:pk>/', views.staff_detail, name='staff_detail'),

    path('guardians/', views.guardian_list, name='guardian_list'),
    path('guardians/<int:pk>/', views.guardian_detail, name='guardian_detail'),
]
