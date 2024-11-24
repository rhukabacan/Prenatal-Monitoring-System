from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('rhu/', include('rhu_management.urls')),
    path('tcl/', include('tcl_management.urls')),
    path('', include('patient_management.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
