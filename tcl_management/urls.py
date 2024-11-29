from django.urls import path
from . import views

app_name = 'tcl_management'

urlpatterns = [
    # Authentication URLs
    path('login/', views.tcl_login, name='login'),
    path('logout/', views.tcl_logout, name='logout'),
    path('profile/', views.profile_view, name='profile'),
    path('profile/edit/', views.profile_update, name='profile_edit'),

    # Dashboard
    path('', views.dashboard, name='dashboard'),

    # Patient Management (Read-only)
    path('patients/', views.patient_list, name='patient_list'),
    path('patients/<int:patient_id>/', views.patient_detail, name='patient_detail'),

    # Checkup Records (Read-only)
    path('checkups/', views.checkup_list, name='checkup_list'),
    path('checkups/<int:checkup_id>/', views.checkup_detail, name='checkup_detail'),

    # Emergency Monitoring (Read-only)
    path('emergencies/', views.emergency_monitor, name='emergency_monitor'),
    path('emergencies/<int:emergency_id>/', views.emergency_detail, name='emergency_detail'),

    # Reports (Barangay-specific)
    path('reports/patients/', views.patient_report, name='patient_report'),
    path('reports/checkups/', views.checkup_report, name='checkup_report'),
    path('reports/emergencies/', views.emergency_report, name='emergency_report'),
]