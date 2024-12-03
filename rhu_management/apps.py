from django.apps import AppConfig
from django.conf import settings


class RhuManagementConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'rhu_management'

    def ready(self):
        try:
            from django_q.tasks import schedule
            from django_q.models import Schedule
            
            # Remove existing schedules
            Schedule.objects.filter(
                name__in=['checkup_reminders', 'emergency_check']
            ).delete()
            
            # Schedule checkup reminders
            schedule(
                'rhu_management.tasks.send_checkup_reminders',
                name='checkup_reminders',
                schedule_type='I',
                minutes=5
            )
            
            # Schedule emergency checks
            schedule(
                'rhu_management.tasks.check_new_emergencies',
                name='emergency_check',
                schedule_type='I',
                minutes=1  # Check every minute
            )
        except Exception as e:
            print(f"Error scheduling tasks: {str(e)}")
