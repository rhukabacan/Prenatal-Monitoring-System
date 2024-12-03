from datetime import timedelta
from django.utils import timezone
from django.core.cache import cache
from .models import PrenatalCheckup, EmergencyAlert
from .utils import send_checkup_reminder_sms

def check_new_emergencies():
    """Task to check for new emergency alerts"""
    last_check_time = cache.get('last_emergency_check') or timezone.now()
    current_time = timezone.now()
    
    # Check for new emergencies since last check
    new_emergencies = EmergencyAlert.objects.filter(
        alert_time__gt=last_check_time,
        status='ACTIVE'
    ).exists()
    
    # Update last check time
    cache.set('last_emergency_check', current_time)
    
    return new_emergencies

def send_checkup_reminders():
    """Task to send SMS reminders for tomorrow's checkups"""
    tomorrow = timezone.now().date() + timedelta(days=1)
    
    upcoming_checkups = PrenatalCheckup.objects.filter(
        checkup_date__date=tomorrow,
        status='SCHEDULED'
    ).select_related('patient', 'patient__user')
    
    for checkup in upcoming_checkups:
        send_checkup_reminder_sms(checkup) 