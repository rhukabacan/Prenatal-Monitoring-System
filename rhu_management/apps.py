from django.apps import AppConfig
from django.conf import settings


class RhuManagementConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'rhu_management'

    def ready(self):
        try:
            from django_q.tasks import schedule
            from django_q.models import Schedule
            
            # Remove existing schedule
            Schedule.objects.filter(name='checkup_reminders').delete()
            
            # Create new daily schedule
            schedule(
                'rhu_management.tasks.send_checkup_reminders',
                name='checkup_reminders',
                schedule_type='I',  # Minutes schedule
                minutes=5  # Run every 5 minutes
            )
        except Exception as e:
            print(f"Error scheduling task: {str(e)}")
