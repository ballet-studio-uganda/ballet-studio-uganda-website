"""Authentication and profile URLs."""

from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = 'accounts'

urlpatterns = [
    # Sign in / out
    path('login/', views.StudioLoginView.as_view(), name='login'),
    path('logout/', views.StudioLogoutView.as_view(), name='logout'),

    # Registration
    path('signup/', views.signup_choice, name='signup'),
    path('signup/parent/', views.signup_guardian, name='signup_guardian'),
    path('signup/student/', views.signup_student, name='signup_student'),
    path('signup/staff/', views.signup_staff, name='signup_staff'),
    path('pending/', views.pending, name='pending'),

    # Profile
    path('profile/', views.profile, name='profile'),
    path('profile/edit/', views.profile_edit, name='profile_edit'),
    path('password/', views.StudioPasswordChangeView.as_view(), name='password_change'),

    # Password reset
    path('password-reset/', auth_views.PasswordResetView.as_view(
        template_name='accounts/password_reset.html',
        email_template_name='accounts/email/password_reset_email.txt',
        subject_template_name='accounts/email/password_reset_subject.txt',
        success_url='/accounts/password-reset/sent/',
    ), name='password_reset'),
    path('password-reset/sent/', auth_views.PasswordResetDoneView.as_view(
        template_name='accounts/password_reset_sent.html',
    ), name='password_reset_done'),
    path('password-reset/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='accounts/password_reset_confirm.html',
        success_url='/accounts/password-reset/done/',
    ), name='password_reset_confirm'),
    path('password-reset/done/', auth_views.PasswordResetCompleteView.as_view(
        template_name='accounts/password_reset_complete.html',
    ), name='password_reset_complete'),

    # Notifications
    path('notifications/', views.notification_list, name='notification_list'),
    path('notifications/menu/', views.notification_dropdown, name='notification_dropdown'),
    path('notifications/<int:pk>/read/', views.notification_read, name='notification_read'),
    path('notifications/read-all/', views.notifications_read_all, name='notifications_read_all'),
]
