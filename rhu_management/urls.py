from django.urls import path

from . import views

app_name = 'rhu_management'

urlpatterns = [
    # Authentication URLs
    path('login/', views.rhu_login, name='rhu_login'),
    path('logout/', views.rhu_logout, name='rhu_logout'),

    # Dashboard
    path('', views.rhu_dashboard, name='dashboard'),

    # Profile Management
    path('profile/update/', views.profile_update, name='profile_update'),

    # Barangay Management
    path('barangays/', views.barangay_list, name='barangay_list'),
    path('barangay/<int:barangay_id>/', views.barangay_detail, name='barangay_detail'),
    path('barangays/add/', views.barangay_add, name='barangay_add'),
    path('barangays/<int:barangay_id>/update/', views.barangay_update, name='barangay_update'),

    # Patient Management
    path('patients/', views.patient_list, name='patient_list'),
    path('patients/add/', views.patient_add, name='patient_add'),
    path('patient/<int:patient_id>/', views.patient_detail, name='patient_detail'),
    path('patient/<int:patient_id>/update/', views.patient_update, name='patient_update'),

    # Checkup Management
    path('checkups/', views.checkup_list, name='checkup_list'),
    path('checkups/create/<int:patient_id>/', views.checkup_create, name='checkup_create'),
    path('checkups/<int:checkup_id>/', views.checkup_detail, name='checkup_detail'),
    path('checkups/<int:checkup_id>/update/', views.checkup_update, name='checkup_update'),
    # path('checkups/search/', views.checkup_search, name='checkup_search'),

    # Emergency Response
    path('emergency/list/', views.emergency_list, name='emergency_list'),
    path('emergency/<int:alert_id>/', views.emergency_detail, name='emergency_detail'),
    path('emergency/<int:alert_id>/respond/', views.emergency_respond,
         name='emergency_respond'),
    # path('emergency/<int:alert_id>/update/', views.emergency_update,
    #      name='emergency_update'),
    # path('emergency/active/', views.emergency_active, name='emergency_active'),

    # Notifications
    # path('notifications/', views.notification_dashboard, name='notification_dashboard'),
    # path('notifications/send/', views.send_notification, name='send_notification'),
    # path('notifications/templates/add/', views.notification_template_add,
    #      name='notification_template_add'),
    # path('notifications/templates/<int:template_id>/edit/',
    #      views.notification_template_edit, name='notification_template_edit'),
    # path('notifications/history/', views.notification_history,
    #      name='notification_history'),

    # Reports and Analytics
    path('reports/', views.reports_dashboard, name='reports_dashboard'),
    path('reports/generate/', views.generate_report, name='generate_report'),  # urls.py
    path('reports/<int:report_id>/view/', views.view_report, name='view_report'),
    path('reports/<int:report_id>/download/', views.download_report, name='download_report'),
    # path('reports/view/<int:report_id>/', views.view_report, name='view_report'),
    # path('reports/download/<int:report_id>/', views.download_report,
    #      name='download_report'),
    path('reports/analytics/', views.analytics_view, name='analytics_view'),
    path('reports/analytics/export/', views.export_analytics, name='export_analytics'),

    # Emergency Alert Endpoints
    path('active-emergencies/', views.get_active_emergencies, name='get_active_emergencies'),

    # # Staff Management (Admin only)
    # path('staff/', views.staff_list, name='staff_list'),
    # path('staff/add/', views.staff_add, name='staff_add'),
    # path('staff/<int:staff_id>/', views.staff_detail, name='staff_detail'),
    # path('staff/<int:staff_id>/update/', views.staff_update, name='staff_update'),
    # path('staff/<int:staff_id>/toggle-active/', views.staff_toggle_active,
    #      name='staff_toggle_active'),

    # # Settings
    # path('settings/', views.settings_dashboard, name='settings_dashboard'),
    # path('settings/system/', views.system_settings, name='system_settings'),
    # path('settings/notifications/', views.notification_settings,
    #      name='notification_settings'),
    # path('settings/schedule/', views.schedule_settings, name='schedule_settings'),

]
