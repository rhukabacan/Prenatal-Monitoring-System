from datetime import timedelta
from django.utils import timezone
from .models import PrenatalCheckup, EmergencyAlert
from .utils import send_checkup_reminder_sms

def send_checkup_reminders():
    """Task to send SMS reminders for tomorrow's checkups"""
    tomorrow = timezone.now().date() + timedelta(days=1)
    
    upcoming_checkups = PrenatalCheckup.objects.filter(
        checkup_date__date=tomorrow,
        status='SCHEDULED'
    ).select_related('patient', 'patient__user')
    
    for checkup in upcoming_checkups:
        send_checkup_reminder_sms(checkup)

def check_active_emergencies():
    """Task to check for active emergency alerts"""
    active_alerts = EmergencyAlert.objects.filter(
        status='ACTIVE'
    ).select_related('patient', 'patient__user', 'patient__barangay')
    
    return {
        'has_active_alerts': active_alerts.exists(),
        'active_alerts': [{
            'id': alert.id,
            'patient_name': alert.patient.user.get_full_name(),
            'sitio': alert.patient.sitio,
            'barangay': alert.patient.barangay.barangay_name,
            'alert_time': alert.alert_time.strftime('%I:%M %p - %b. %d, %Y').replace(' 0', ' ').replace('AM', 'AM').replace('PM', 'PM'),
            'location': alert.location or 'No location provided'
        } for alert in active_alerts]
    } 