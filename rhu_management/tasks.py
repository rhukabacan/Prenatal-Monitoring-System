from datetime import timedelta
from django.utils import timezone
from .models import PrenatalCheckup
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
