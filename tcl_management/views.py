from datetime import timedelta
from functools import wraps

from django.contrib import messages
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Q, Avg
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from rhu_management.models import Patient, PrenatalCheckup, EmergencyAlert, Barangay


def tcl_required(view_func):
    """Decorator to check if user is a TCL"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not hasattr(request.user, 'barangay'):
            messages.error(request, 'Only Team Community Leaders can access this area.')
            logout(request)
            return redirect('tcl_management:login')
        return view_func(request, *args, **kwargs)

    return _wrapped_view


# Authentication Views
def tcl_login(request):
    """Handle TCL login"""
    if request.user.is_authenticated:
        if hasattr(request.user, 'barangay'):
            return redirect('tcl_management:dashboard')
        else:
            logout(request)
            messages.error(request, 'Only Team Community Leaders can access this area.')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(username=username, password=password)

        if user is not None:
            if hasattr(user, 'barangay'):
                login(request, user)
                messages.success(request, f'Welcome back, {user.get_full_name()}!')
                return redirect('tcl_management:dashboard')
            else:
                messages.error(request, 'This account is not registered as a TCL.')
        else:
            messages.error(request, 'Invalid username or password.')

    return render(request, 'tcl_management/login.html', {
        'title': 'TCL Login'
    })


@login_required(login_url='tcl_management:login')
@tcl_required
def tcl_logout(request):
    """Handle TCL logout"""
    logout(request)
    messages.success(request, 'You have been logged out successfully.')
    return redirect('tcl_management:login')


@login_required(login_url='tcl_management:login')
@tcl_required
def profile_view(request):
    """Display TCL profile"""
    tcl = request.user.barangay

    # Get counts for quick stats
    active_checkups_count = PrenatalCheckup.objects.filter(
        patient__barangay=tcl,
        status='SCHEDULED'
    ).count()

    active_emergencies_count = EmergencyAlert.objects.filter(
        patient__barangay=tcl,
        status='ACTIVE'
    ).count()

    # Add counts to tcl object for template access
    tcl.active_checkups_count = active_checkups_count
    tcl.active_emergencies_count = active_emergencies_count

    context = {
        'tcl': tcl,
        'title': 'My Profile'
    }

    return render(request, 'tcl_management/profile_view.html', context)


@login_required(login_url='tcl_management:login')
@tcl_required
def profile_update(request):
    """Handle TCL profile update"""
    tcl = request.user.barangay

    if request.method == 'POST':
        try:
            # Update User model
            user = request.user
            user.first_name = request.POST.get('first_name')
            user.last_name = request.POST.get('last_name')
            user.email = request.POST.get('email')
            user.save()

            # Update TCL profile
            tcl.contact_number = request.POST.get('contact_number')
            tcl.save()

            messages.success(request, 'Profile updated successfully!')
            return redirect('tcl_management:profile_view')
        except Exception as e:
            messages.error(request, 'An error occurred while updating your profile.')

    return render(request, 'tcl_management/profile_edit.html', {
        'tcl': tcl,
        'title': 'Edit Profile'
    })


@login_required(login_url='tcl_management:login')
@tcl_required
def dashboard(request):
    """Display TCL dashboard with barangay-specific information"""
    tcl = request.user.barangay
    today = timezone.localtime(timezone.now()).date()

    # Get barangay statistics
    stats = {
        'total_patients': Patient.objects.filter(
            barangay=tcl
        ).count(),
        'new_patients': Patient.objects.filter(
            barangay=tcl,
            created_at__gte=today - timedelta(days=30)
        ).count(),
        'today_checkups': PrenatalCheckup.objects.filter(
            patient__barangay=tcl,
            checkup_date__date=today
        ).count(),
        'active_emergencies': EmergencyAlert.objects.filter(
            patient__barangay=tcl,
            status='ACTIVE'
        ).count()
    }

    # Get recent activities
    recent_activities = get_recent_barangay_activities(tcl)

    # Get active emergencies
    active_emergencies = EmergencyAlert.objects.filter(
        patient__barangay=tcl,
        status='ACTIVE'
    ).select_related('patient__user').order_by('-alert_time')

    context = {
        'stats': stats,
        'recent_activities': recent_activities,
        'active_emergencies': active_emergencies,
        'barangay': tcl,
        'title': f'TCL Dashboard - {tcl.barangay_name}'
    }

    return render(request, 'tcl_management/dashboard.html', context)


# Patient Management Views
@login_required(login_url='tcl_management:login')
@tcl_required
def patient_list(request):
    """Display list of patients from TCL's barangay"""
    tcl = request.user.barangay

    # Get all barangays for the filter dropdown
    barangays = Barangay.objects.all().order_by('barangay_name')

    # Base queryset filtered by barangay
    patients = Patient.objects.all().order_by('-created_at')

    # Search functionality
    search_query = request.GET.get('search', '')
    if search_query:
        patients = patients.filter(
            Q(user__first_name__icontains=search_query) |
            Q(user__last_name__icontains=search_query) |
            Q(contact_number__icontains=search_query)
        )

    # Barangay filter
    barangay_filter = request.GET.get('barangay', '')
    if barangay_filter:
        patients = patients.filter(barangay_id=barangay_filter)

    # Calculate statistics
    stats = {
        'total_patients': Patient.objects.count(),
        'active_patients': Patient.objects.count(),
    }

    # Pagination
    paginator = Paginator(patients, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'patients': page_obj,
        'stats': stats,
        'search_query': search_query,
        'barangay_filter': barangay_filter,
        'barangays': barangays,
        'barangay': tcl,
        'title': f'Patients - {tcl.barangay_name}'
    }

    return render(request, 'tcl_management/patient_list.html', context)


@login_required(login_url='tcl_management:login')
@tcl_required
def patient_detail(request, patient_id):
    """Display patient details (read-only)"""
    patient = get_object_or_404(
        Patient,
        id=patient_id,
        barangay=request.user.barangay
    )

    # Get upcoming checkups - we'll get next 5 scheduled checkups
    upcoming_checkups = PrenatalCheckup.objects.filter(
        patient=patient,
        status='SCHEDULED',
        checkup_date__gt=timezone.now()
    ).order_by('checkup_date')[:5]  # Limit to next 5 checkups

    # Calculate pregnancy week if applicable
    weeks_pregnant = None
    progress_percentage = None
    if patient.last_checkup and patient.last_checkup.last_menstrual_period:  # Add check for latest_checkup
        days_pregnant = (timezone.now().date() - patient.last_checkup.last_menstrual_period).days
        weeks_pregnant = min(days_pregnant // 7, 42)  # Cap at 42 weeks
        progress_percentage = min((weeks_pregnant / 42) * 100, 100)  # Cap at 100%

    context = {
        'patient': patient,
        'upcoming_checkups': upcoming_checkups,
        'weeks_pregnant': weeks_pregnant,
        'progress_percentage': progress_percentage,
        'checkups': PrenatalCheckup.objects.filter(patient=patient).order_by('-checkup_date')[:5],
        'title': f'Patient Details - {patient.user.get_full_name()}'
    }

    return render(request, 'tcl_management/patient_detail.html', context)


# Records and Monitoring Views
@login_required(login_url='tcl_management:login')
@tcl_required
def checkup_list(request):
    """Display checkup records for the barangay"""
    tcl = request.user.barangay
    today = timezone.now().date()

    # Get base queryset
    checkups = PrenatalCheckup.objects.filter(
        patient__barangay=tcl
    ).order_by('-checkup_date')

    # Get all patients from this barangay for the filter
    barangay_patients = Patient.objects.filter(barangay=tcl)

    # Calculate statistics
    stats = {
        'total_checkups': checkups.count(),
        'today_checkups': checkups.filter(checkup_date__date=today).count(),
        'completed_checkups': checkups.filter(status='COMPLETED').count(),
        'upcoming_checkups': checkups.filter(
            status='SCHEDULED',
            checkup_date__gt=timezone.now()
        ).count()
    }

    # Patient filter
    patient_filter = request.GET.get('patient')
    if patient_filter:
        checkups = checkups.filter(patient_id=patient_filter)

    # Date range filter
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    if date_from:
        checkups = checkups.filter(checkup_date__date__gte=date_from)
    if date_to:
        checkups = checkups.filter(checkup_date__date__lte=date_to)

    # Pagination
    paginator = Paginator(checkups, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)  # Changed variable name

    context = {
        'page_obj': page_obj,  # Changed from 'checkups' to 'page_obj'
        'stats': stats,
        'barangay_patients': barangay_patients,
        'patient_filter': patient_filter,
        'date_from': date_from,
        'date_to': date_to,
        'title': f'Checkup Records - {tcl.barangay_name}'
    }

    return render(request, 'tcl_management/checkup_list.html', context)


@login_required(login_url='tcl_management:login')
@tcl_required
def checkup_detail(request, checkup_id):
    """Display checkup details (read-only)"""

    # Get checkup and verify barangay access
    checkup = get_object_or_404(
        PrenatalCheckup.objects.select_related('patient__user'),
        id=checkup_id,
        patient__barangay=request.user.barangay
    )

    # Get previous and next checkups
    previous_checkup = PrenatalCheckup.objects.filter(
        patient=checkup.patient,
        checkup_date__lt=checkup.checkup_date
    ).order_by('-checkup_date').first()

    next_checkup = PrenatalCheckup.objects.filter(
        patient=checkup.patient,
        checkup_date__gt=checkup.checkup_date
    ).order_by('checkup_date').first()

    context = {
        'checkup': checkup,
        'previous_checkup': previous_checkup,
        'next_checkup': next_checkup,
        'title': f'Checkup Details - {checkup.patient.user.get_full_name()}'
    }

    return render(request, 'tcl_management/checkup_detail.html', context)


@login_required(login_url='tcl_management:login')
@tcl_required
def emergency_monitor(request):
    """Monitor emergency alerts in the barangay"""
    tcl = request.user.barangay

    # Get all emergencies for the barangay
    emergencies = EmergencyAlert.objects.filter(
        patient__barangay=tcl
    ).order_by('-alert_time')

    # Get statistics
    stats = {
        'active': emergencies.filter(status='ACTIVE').count(),
        'responded': emergencies.filter(status='RESPONDED').count(),
        'resolved': emergencies.filter(status='RESOLVED').count(),
        'total': emergencies.count()
    }

    # Pagination
    paginator = Paginator(emergencies, 10)  # 10 items per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'stats': stats,
        'barangay': tcl,
        'title': f'Emergency Monitor - {tcl.barangay_name}'
    }

    return render(request, 'tcl_management/emergency_monitor.html', context)


@login_required(login_url='tcl_management:login')
@tcl_required
def emergency_detail(request, emergency_id):
    """Display emergency alert details (read-only)"""
    tcl = request.user.barangay

    # Get emergency alert and verify barangay access
    alert = get_object_or_404(
        EmergencyAlert.objects.select_related('patient__user'),
        id=emergency_id,
        patient__barangay=tcl
    )

    # Get patient's latest checkup
    latest_checkup = PrenatalCheckup.objects.filter(
        patient=alert.patient
    ).order_by('-checkup_date').first()

    context = {
        'alert': alert,
        'latest_checkup': latest_checkup,
        'title': f'Emergency Alert - {alert.patient.user.get_full_name()}'
    }

    return render(request, 'tcl_management/emergency_detail.html', context)


# Utility Functions
def get_recent_barangay_activities(barangay):
    """Get recent activities in the barangay"""
    activities = []

    # Get recent checkups
    recent_checkups = PrenatalCheckup.objects.filter(
        patient__barangay=barangay
    ).order_by('-checkup_date')[:5]

    for checkup in recent_checkups:
        activities.append({
            'type': 'checkup',
            'time': checkup.checkup_date,
            'patient': checkup.patient,
            'description': f"{checkup.patient.user.get_full_name()} had a prenatal checkup"
        })

    # Get recent emergencies
    recent_emergencies = EmergencyAlert.objects.filter(
        patient__barangay=barangay
    ).order_by('-alert_time')[:5]

    for emergency in recent_emergencies:
        activities.append({
            'type': 'emergency',
            'time': emergency.alert_time,
            'patient': emergency.patient,
            'description': f"Emergency alert from {emergency.patient.user.get_full_name()}"
        })

    # Sort combined activities by time
    activities.sort(key=lambda x: x['time'], reverse=True)
    return activities[:10]


@login_required(login_url='tcl_management:login')
@tcl_required
def patient_report(request):
    """Generate barangay-specific patient statistics"""
    tcl = request.user.barangay
    today = timezone.localtime(timezone.now()).date()

    # Get patients from barangay
    patients = Patient.objects.filter(barangay=tcl)

    # Calculate statistics
    stats = {
        'total_patients': patients.count(),
        'new_patients': patients.filter(created_at__gte=today - timedelta(days=30)).count(),
    }

    # Monthly registration trend
    monthly_trend = []
    for i in range(6):
        month_start = today.replace(day=1) - timedelta(days=30 * i)
        month_end = month_start.replace(day=1) + timedelta(days=32)
        month_end = month_end.replace(day=1) - timedelta(days=1)

        count = patients.filter(created_at__date__range=[month_start, month_end]).count()
        monthly_trend.append({
            'month': month_start.strftime('%B %Y'),
            'count': count
        })

    context = {
        'stats': stats,
        'monthly_trend': monthly_trend,
        'barangay': tcl,  # Changed this line
        'title': f'Patient Report - {tcl.barangay_name}'  # Changed this line if 'name' is the field
    }

    return render(request, 'tcl_management/patient_report.html', context)


@login_required(login_url='tcl_management:login')
@tcl_required
def checkup_report(request):
    """Generate barangay-specific checkup statistics"""
    tcl = request.user.barangay
    today = timezone.localtime(timezone.now()).date()

    # Get checkups from barangay
    checkups = PrenatalCheckup.objects.filter(
        patient__barangay=tcl
    )

    # Calculate statistics
    stats = {
        'total_checkups': checkups.count(),
        'this_month': checkups.filter(checkup_date__month=today.month).count(),
        'high_bp_cases': checkups.filter(blood_pressure__contains='HIGH').count(),
        'completed': checkups.filter(status='COMPLETED').count()
    }

    # Weekly checkup trend
    weekly_trend = []
    for i in range(8):
        week_start = today - timedelta(days=7 * i)
        week_end = week_start + timedelta(days=6)
        count = checkups.filter(checkup_date__range=[week_start, week_end]).count()
        weekly_trend.append({
            'week': f'Week {i + 1}',
            'count': count
        })

    context = {
        'stats': stats,
        'weekly_trend': weekly_trend,
        'barangay': tcl,
        'today': today,
        'title': f'Checkup Report - {tcl.barangay_name}'
    }

    return render(request, 'tcl_management/checkup_report.html', context)


@login_required(login_url='tcl_management:login')
@tcl_required
def emergency_report(request):
    """Generate barangay-specific emergency statistics"""
    tcl = request.user.barangay
    today = timezone.localtime(timezone.now()).date()

    # Get emergencies from barangay
    emergencies = EmergencyAlert.objects.filter(
        patient__barangay=tcl
    )

    # Calculate response time average manually
    total_minutes = 0
    count = 0
    for e in emergencies.exclude(response_time=None):
        if e.response_time and e.alert_time:
            # Calculate time difference in minutes
            time_diff = (e.response_time - e.alert_time).total_seconds() / 60
            total_minutes += time_diff
            count += 1

    avg_response_time = (total_minutes / count) if count > 0 else None

    # Calculate statistics
    stats = {
        'total_alerts': emergencies.count(),
        'active_alerts': emergencies.filter(status='ACTIVE').count(),
        'response_time_avg': round(avg_response_time, 1) if avg_response_time else None,
        'resolved_cases': emergencies.filter(status='RESOLVED').count()
    }

    # Daily emergency trend
    daily_trend = []
    for i in range(7):
        day = today - timedelta(days=i)
        count = emergencies.filter(alert_time__date=day).count()
        daily_trend.append({
            'day': day.strftime('%A'),
            'count': count
        })

    context = {
        'stats': stats,
        'daily_trend': daily_trend,
        'barangay': tcl,
        'today': today,
        'title': f'Emergency Report - {tcl.barangay_name}'
    }

    return render(request, 'tcl_management/emergency_report.html', context)
