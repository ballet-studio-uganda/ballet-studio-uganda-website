"""Teaching-side URLs (mounted at /studio/)."""

from django.urls import path

from . import views

app_name = 'academics'

urlpatterns = [
    # Classes
    path('classes/', views.class_list, name='class_list'),
    path('classes/new/', views.class_create, name='class_create'),
    path('classes/<int:pk>/', views.class_detail, name='class_detail'),
    path('classes/<int:pk>/edit/', views.class_edit, name='class_edit'),
    path('classes/<int:pk>/sessions/', views.generate_sessions, name='generate_sessions'),

    path('timetable/', views.timetable, name='timetable'),

    # Registers
    path('registers/', views.register_list, name='register_list'),
    path('registers/<int:pk>/', views.register, name='register'),
    path('attendance/', views.attendance_overview, name='attendance'),

    # Dancers
    path('dancers/', views.student_list, name='student_list'),
    path('dancers/new/', views.student_create, name='student_create'),
    path('dancers/<int:pk>/', views.student_detail, name='student_detail'),
    path('dancers/<int:pk>/edit/', views.student_edit, name='student_edit'),
    path('dancers/<int:pk>/guardian/', views.student_add_guardian, name='student_add_guardian'),
    path('dancers/<int:pk>/note/', views.student_add_note, name='student_add_note'),
    path('dancers/<int:pk>/enrol/', views.enrol_student, name='enrol_student'),
    path('dancers/<int:pk>/progress.json', views.student_progress_json, name='student_progress_json'),

    # Progress reports
    path('reports/', views.report_list, name='report_list'),
    path('reports/class/<int:class_pk>/', views.report_class, name='report_class_current'),
    path('reports/class/<int:class_pk>/<int:period_pk>/', views.report_class, name='report_class'),
    path('reports/class/<int:class_pk>/<int:period_pk>/publish/',
         views.report_publish_class, name='report_publish_class'),
    path('reports/write/<int:class_pk>/<int:student_pk>/',
         views.report_edit, name='report_edit_current'),
    path('reports/write/<int:class_pk>/<int:student_pk>/<int:period_pk>/',
         views.report_edit, name='report_edit'),
    path('reports/<int:pk>/', views.report_detail, name='report_detail'),
    path('reports/<int:pk>/publish/', views.report_publish, name='report_publish'),
]
