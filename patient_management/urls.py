from django.urls import path
from . import views

app_name = 'patient_management'

urlpatterns = [
    # Authentication URLs
    path('register/', views.patient_register, name='register'),
    path('login/', views.patient_login, name='login'),
    path('logout/', views.patient_logout, name='logout'),

    # Dashboard
    path('', views.patient_dashboard, name='dashboard'),

    # Profile Management
    path('profile/', views.profile_view, name='profile_view'),
    path('profile/edit/', views.profile_update, name='profile_update'),

    # Prenatal Checkups
    path('checkups/', views.checkup_list, name='checkup_list'),
    path('checkups/<int:checkup_id>/', views.checkup_detail,
         name='checkup_detail'),
    # path('checkups/request/', views.request_checkup, name='request_checkup'),

    # Pregnancy History
    path('pregnancy-history/', views.pregnancy_history_list,
         name='pregnancy_history_list'),
    path('pregnancy-history/create/', views.pregnancy_history_create,
         name='pregnancy_history_create'),
    path('pregnancy-history/<int:history_id>/update/',
         views.pregnancy_history_update, name='pregnancy_history_update'),

    # Emergency Features
    path('emergency/', views.emergency_alert, name='emergency_alert'),
    path('emergency/history/', views.emergency_history,
         name='emergency_history'),

    # Vital Signs
    path('vital-signs/', views.vital_signs, name='vital_signs'),
    path('vital-signs/update/', views.update_vital_signs, name='update_vital_signs'),
]
