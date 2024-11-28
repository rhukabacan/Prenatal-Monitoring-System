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

from rhu_management.models import Patient, PrenatalCheckup, EmergencyAlert


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
    return render(request, 'tcl_management/profile_view.html', {
        'tcl': tcl,
        'title': 'My Profile'
    })


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
            tcl.address = request.POST.get('address')
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

    # Base queryset filtered by barangay
    patients = Patient.objects.filter(
        barangay=tcl
    ).order_by('-created_at')

    # Search functionality
    search_query = request.GET.get('search', '')
    if search_query:
        patients = patients.filter(
            Q(user__first_name__icontains=search_query) |
            Q(user__last_name__icontains=search_query) |
            Q(contact_number__icontains=search_query)
        )

    # Status filter
    status_filter = request.GET.get('status', '')
    if status_filter:
        patients = patients.filter(is_active=(status_filter == 'active'))

    # Calculate statistics
    stats = {
        'total_patients': Patient.objects.filter(barangay=tcl).count(),
        'active_patients': Patient.objects.filter(barangay=tcl).count(),
    }

    # Pagination
    paginator = Paginator(patients, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'patients': page_obj,
        'stats': stats,
        'search_query': search_query,
        'status_filter': status_filter,
        'barangay': tcl,
        'title': f'Patients - {tcl.barangay_name}'
    }

    return render(request, 'tcl_management/patient_list.html', context)


@login_required(login_url='tcl_management:login')
@tcl_required
def patient_detail(request, patient_id):
    """Display patient details (read-only)"""
    tcl = request.user.barangay
    patient = get_object_or_404(
        Patient,
        id=patient_id,
        address__icontains=tcl.barangay.name
    )

    # Get latest checkup
    latest_checkup = PrenatalCheckup.objects.filter(
        patient=patient
    ).order_by('-checkup_date').first()

    # Calculate pregnancy week if applicable
    current_week = None
    if latest_checkup and latest_checkup.last_menstrual_period:
        days_pregnant = (timezone.localtime(timezone.now()).date() - latest_checkup.last_menstrual_period).days
        current_week = days_pregnant // 7

    context = {
        'patient': patient,
        'latest_checkup': latest_checkup,
        'current_week': current_week,
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

    checkups = PrenatalCheckup.objects.filter(
        patient__barangay=tcl
    ).order_by('-checkup_date')

    # Pagination
    paginator = Paginator(checkups, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'barangay': tcl,
        'title': f'Checkup Records - {tcl.barangay_name}'
    }

    return render(request, 'tcl_management/checkup_list.html', context)


@login_required(login_url='tcl_management:login')
@tcl_required
def checkup_detail(request, pk):
    """Display checkup details (read-only)"""
    tcl = request.user.barangay

    # Get checkup and verify barangay access
    checkup = get_object_or_404(
        PrenatalCheckup.objects.select_related('patient__user'),
        id=pk,
        patient__address__icontains=tcl.barangay.name
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

    context = {
        'emergencies': emergencies,
        'stats': stats,
        'barangay': tcl,
        'title': f'Emergency Monitor - {tcl.barangay_name}'
    }

    return render(request, 'tcl_management/emergency_monitor.html', context)


@login_required(login_url='tcl_management:login')
@tcl_required
def emergency_detail(request, pk):
    """Display emergency alert details (read-only)"""
    tcl = request.user.barangay

    # Get emergency alert and verify barangay access
    alert = get_object_or_404(
        EmergencyAlert.objects.select_related('patient__user'),
        id=pk,
        patient__address__icontains=tcl.barangay.name
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
    patients = Patient.objects.filter(address__icontains=tcl.barangay.name)

    # Calculate statistics
    stats = {
        'total_patients': patients.count(),
        'new_patients': patients.filter(created_at__gte=today - timedelta(days=30)).count(),
        'active_patients': patients.filter(is_active=True).count(),
        'high_risk_patients': patients.filter(risk_level='HIGH').count(),
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
        'barangay': tcl.barangay,
        'title': f'Patient Report - {tcl.barangay.name}'
    }

    return render(request, 'tcl_management/reports/patient_report.html', context)


@login_required(login_url='tcl_management:login')
@tcl_required
def checkup_report(request):
    """Generate barangay-specific checkup statistics"""
    tcl = request.user.barangay
    today = timezone.localtime(timezone.now()).date()

    # Get checkups from barangay
    checkups = PrenatalCheckup.objects.filter(
        patient__address__icontains=tcl.barangay.name
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
        'barangay': tcl.barangay,
        'title': f'Checkup Report - {tcl.barangay.name}'
    }

    return render(request, 'tcl_management/reports/checkup_report.html', context)


@login_required(login_url='tcl_management:login')
@tcl_required
def emergency_report(request):
    """Generate barangay-specific emergency statistics"""
    tcl = request.user.barangay
    today = timezone.localtime(timezone.now()).date()

    # Get emergencies from barangay
    emergencies = EmergencyAlert.objects.filter(
        patient__address__icontains=tcl.barangay.name
    )

    # Calculate statistics
    stats = {
        'total_alerts': emergencies.count(),
        'active_alerts': emergencies.filter(status='ACTIVE').count(),
        'response_time_avg': emergencies.aggregate(Avg('response_time'))['response_time__avg'],
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
        'barangay': tcl.barangay,
        'title': f'Emergency Report - {tcl.barangay.name}'
    }

    return render(request, 'tcl_management/reports/emergency_report.html', context)
