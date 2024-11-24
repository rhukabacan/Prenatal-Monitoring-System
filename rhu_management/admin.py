from django.contrib import admin

from rhu_management.models import *

# Register all your models
admin.site.register(Barangay)
admin.site.register(Patient)
admin.site.register(PregnancyHistory)
admin.site.register(PrenatalCheckup)
admin.site.register(EmergencyAlert)
admin.site.register(RHUReport)