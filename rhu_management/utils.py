import requests
from django.conf import settings

def send_checkup_reminder_sms(checkup):
    """Send SMS reminder for upcoming checkup"""
    api_url = "https://api.semaphore.co/api/v4/messages"
    
    message = (
        f"Hi {checkup.patient.user.first_name}, this is a reminder for your "
        f"prenatal checkup tomorrow at {checkup.checkup_date.strftime('%I:%M %p')}. "
        f"Please don't forget to bring your prenatal record book. Thank you!\n\n"
        f"- RHU KABACAN"
    )
    
    payload = {
        'apikey': settings.SEMAPHORE_API_KEY,
        'number': checkup.patient.contact_number,
        'message': message,
        'sendername': settings.SEMAPHORE_SENDER_NAME
    }
    
    try:
        response = requests.post(api_url, data=payload)
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"Error sending SMS: {str(e)}")
        return False 