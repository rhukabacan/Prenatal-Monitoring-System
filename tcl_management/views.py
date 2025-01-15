from datetime import timedelta
from functools import wraps
import json

from django.contrib import messages
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Q, Avg, Exists, OuterRef, Count, Case, When, Value, CharField, Prefetch, JSONField, \
    FloatField, F, ExpressionWrapper, DurationField
from django.db.models.functions import TruncDate, ExtractWeek, ExtractYear
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
        # Get form data
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()
        contact_number = request.POST.get('contact_number', '').strip()
        new_password = request.POST.get('new_password', '').strip()
        confirm_password = request.POST.get('confirm_password', '').strip()

        # Validate required fields
        if not all([first_name, last_name, contact_number]):
            messages.error(request, 'Please fill in all required fields.')
            return render(request, 'tcl_management/profile_edit.html', {
                'tcl': tcl,
                'title': 'Edit Profile'
            })

        try:
            # Update User model
            user = request.user
            user.first_name = first_name
            user.last_name = last_name
            user.email = email

            # Handle password change if provided
            if new_password:
                if new_password != confirm_password:
                    messages.error(request, 'Passwords do not match.')
                    return render(request, 'tcl_management/profile_edit.html', {
                        'tcl': tcl,
                        'title': 'Edit Profile'
                    })
                if len(new_password) < 8:
                    messages.error(request, 'Password must be at least 8 characters long.')
                    return render(request, 'tcl_management/profile_edit.html', {
                        'tcl': tcl,
                        'title': 'Edit Profile'
                    })
                user.set_password(new_password)
                messages.success(request, 'Password updated successfully. Please login again.')
                user.save()
                logout(request)
                return redirect('tcl_management:login')

            user.save()

            # Update TCL profile
            tcl.contact_number = contact_number
            tcl.save()

            messages.success(request, 'Profile updated successfully!')
            return redirect('tcl_management:profile')

        except Exception as e:
            # Log the actual error for debugging
            print(f"Profile update error: {str(e)}")
            messages.error(request, 'An error occurred while updating your profile. Please try again.')

    return render(request, 'tcl_management/profile_edit.html', {
        'tcl': tcl,
        'title': 'Edit Profile'
    })


@login_required(login_url='tcl_management:login')
@tcl_required
def dashboard(request):
    """Display enhanced TCL dashboard with comprehensive statistics"""
    tcl = request.user.barangay
    today = timezone.now().date()
    now = timezone.now()

    # Get all stats in a single query using aggregation
    stats = Patient.objects.filter(barangay=tcl).aggregate(
        total_patients=Count('id'),
        new_patients=Count('id', filter=Q(created_at__gte=today - timedelta(days=30))),
        today_checkups=Count(
            'prenatalcheckup',
            filter=Q(prenatalcheckup__checkup_date__date=today)
        ),
        active_emergencies=Count(
            'emergencyalert',
            filter=Q(emergencyalert__status='ACTIVE')
        ),
        recent_emergencies=Count(
            'emergencyalert',
            filter=Q(emergencyalert__alert_time__gte=now - timedelta(hours=24))
        ),
        high_risk_cases=Count(
            'id',
            filter=Q(prenatalcheckup__blood_pressure__contains='HIGH'),
            distinct=True
        ),
        critical_cases=Count(
            'emergencyalert',
            filter=Q(
                emergencyalert__status='ACTIVE',
                emergencyalert__alert_time__lte=now - timedelta(hours=1)
            )
        ),
        overdue_checkups=Count(
            'prenatalcheckup',
            filter=Q(
                prenatalcheckup__checkup_date__lt=today,
                prenatalcheckup__status='SCHEDULED'
            )
        ),
        upcoming_deliveries=Count(
            'id',
            filter=Q(prenatalcheckup__last_menstrual_period__lte=today - timedelta(weeks=38)),
            distinct=True
        ),
        pending_followups=Count(
            'prenatalcheckup',
            filter=Q(
                prenatalcheckup__status='COMPLETED',
                prenatalcheckup__checkup_date__date=today - timedelta(days=1)
            )
        )
    )

    # Get age distribution using database aggregation
    age_distribution = Patient.objects.filter(barangay=tcl).annotate(
        age_days=ExpressionWrapper(
            (timezone.now().date() - F('birth_date')),
            output_field=DurationField()
        )
    ).annotate(
        age_group=Case(
            When(age_days__gt=timedelta(days=365*45), then=Value('45+')),
            When(age_days__gt=timedelta(days=365*35), then=Value('36-45')),
            When(age_days__gt=timedelta(days=365*25), then=Value('26-35')),
            default=Value('18-25'),
            output_field=CharField(),
        )
    ).values('age_group').annotate(
        count=Count('id')
    ).order_by('age_group')

    # Convert to dictionary format
    age_distribution = {
        item['age_group']: item['count'] 
        for item in age_distribution
    } or {'No Data': 1}

    # Get checkup status distribution in a single query
    checkup_status = PrenatalCheckup.objects.filter(
        patient__barangay=tcl
    ).values('status').annotate(
        count=Count('id')
    ).order_by('status')

    # Convert to dictionary format
    checkup_status = {
        item['status']: item['count']
        for item in checkup_status
    } or {'No Data': 1}

    # Get weekly trend using database aggregation
    weekly_trend = PrenatalCheckup.objects.filter(
        patient__barangay=tcl,
        checkup_date__date__gte=today - timedelta(days=6),
        checkup_date__date__lte=today
    ).annotate(
        day=TruncDate('checkup_date')
    ).values('day').annotate(
        count=Count('id')
    ).order_by('day')

    # Format weekly trend data
    trend_dict = {item['day']: item['count'] for item in weekly_trend}
    weekly_trend = []
    for i in range(7):
        day = today - timedelta(days=i)
        weekly_trend.append({
            'day': day.strftime('%a'),
            'count': trend_dict.get(day, 0)
        })
    weekly_trend.reverse()

    # Get recent activities efficiently
    recent_activities = []
    
    # Recent checkups with efficient querying
    recent_checkups = PrenatalCheckup.objects.select_related(
        'patient__user'
    ).filter(
        patient__barangay=tcl
    ).order_by('-checkup_date')[:5]

    for checkup in recent_checkups:
        recent_activities.append({
            'type': 'checkup',
            'time': checkup.checkup_date,
            'timestamp': checkup.checkup_date.isoformat(),
            'patient': checkup.patient,
            'description': f"{checkup.patient.user.get_full_name()} had a prenatal checkup"
        })

    # Recent emergencies with efficient querying
    recent_emergencies = EmergencyAlert.objects.select_related(
        'patient__user'
    ).filter(
        patient__barangay=tcl
    ).order_by('-alert_time')[:5]

    for emergency in recent_emergencies:
        recent_activities.append({
            'type': 'emergency',
            'time': emergency.alert_time,
            'timestamp': emergency.alert_time.isoformat(),
            'patient': emergency.patient,
            'description': f"Emergency alert from {emergency.patient.user.get_full_name()}"
        })

    # Sort and limit recent activities
    recent_activities.sort(key=lambda x: x['time'], reverse=True)
    recent_activities = recent_activities[:10]

    # Get upcoming checkups efficiently
    upcoming_checkups = PrenatalCheckup.objects.select_related(
        'patient__user'
    ).filter(
        patient__barangay=tcl,
        checkup_date__date=today,
        status='SCHEDULED'
    ).order_by('checkup_date')

    # Get active emergencies efficiently
    active_emergencies = EmergencyAlert.objects.select_related(
        'patient__user'
    ).filter(
        patient__barangay=tcl,
        status='ACTIVE'
    ).order_by('-alert_time')

    context = {
        'stats': stats,
        'age_distribution': age_distribution,
        'checkup_status': checkup_status,
        'weekly_trend': weekly_trend,
        'recent_activities': recent_activities,
        'upcoming_checkups': upcoming_checkups,
        'active_emergencies': active_emergencies,
        'title': f'TCL Dashboard - {tcl.barangay_name}'
    }

    return render(request, 'tcl_management/dashboard.html', context)


# Patient Management Views
@login_required(login_url='tcl_management:login')
@tcl_required
def patient_list(request):
    """Display list of patients from TCL's barangay"""
    tcl = request.user.barangay

    # Base queryset with efficient joins
    patients = Patient.objects.select_related(
        'user',
        'barangay'
    ).prefetch_related(
        Prefetch(
            'prenatalcheckup_set',
            queryset=PrenatalCheckup.objects.order_by('-checkup_date')[:1],
            to_attr='latest_checkup'
        )
    ).filter(barangay=tcl).order_by('-created_at')

    # Search functionality with optimized query
    search_query = request.GET.get('search', '')
    if search_query:
        patients = patients.filter(
            Q(user__first_name__icontains=search_query) |
            Q(user__last_name__icontains=search_query) |
            Q(contact_number__icontains=search_query)
        )

    # Get all stats in a single query
    stats = Patient.objects.filter(barangay=tcl).aggregate(
        total_patients=Count('id'),
        active_patients=Count(
            'id',
            filter=Q(prenatalcheckup__status='SCHEDULED'),
            distinct=True
        ),
        total_checkups=Count('prenatalcheckup'),
        patients_with_checkups=Count('id', filter=Q(prenatalcheckup__isnull=False), distinct=True)
    )

    # Calculate average checkups per patient
    if stats['patients_with_checkups'] > 0:
        stats['avg_checkups'] = round(stats['total_checkups'] / stats['patients_with_checkups'], 1)
    else:
        stats['avg_checkups'] = 0

    # Pagination
    paginator = Paginator(patients, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'patients': page_obj,
        'stats': stats,
        'search_query': search_query,
        'tcl': tcl,
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

    # Get latest vital signs
    latest_vitals = PrenatalCheckup.objects.filter(
        patient=patient
    ).order_by('-checkup_date').first()

    # Get latest checkups with vital signs
    checkups = PrenatalCheckup.objects.filter(
        patient=patient
    ).order_by('-checkup_date')[:5]
    
    # Get vital signs for each checkup
    for checkup in checkups:
        checkup.vitals = PrenatalCheckup.objects.filter(
            patient=patient,
            checkup_date__date=checkup.checkup_date.date()
        ).first()

    # Get upcoming checkups
    upcoming_checkups = PrenatalCheckup.objects.filter(
        patient=patient,
        status='SCHEDULED',
        checkup_date__gt=timezone.now()
    ).order_by('checkup_date')[:5]

    # Calculate pregnancy week if applicable
    weeks_pregnant = None
    progress_percentage = None
    if patient.last_checkup and patient.last_checkup.last_menstrual_period:
        days_pregnant = (timezone.now().date() - patient.last_checkup.last_menstrual_period).days
        weeks_pregnant = min(days_pregnant // 7, 42)  # Cap at 42 weeks
        progress_percentage = min((weeks_pregnant / 42) * 100, 100)  # Cap at 100%

    context = {
        'patient': patient,
        'latest_vitals': latest_vitals,
        'upcoming_checkups': upcoming_checkups,
        'weeks_pregnant': weeks_pregnant,
        'progress_percentage': progress_percentage,
        'checkups': checkups,
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

    # Get base queryset with efficient joins
    checkups = PrenatalCheckup.objects.select_related(
        'patient__user',
        'patient__barangay'
    ).filter(
        patient__barangay=tcl
    ).order_by('-checkup_date')

    # Get all patients from this barangay efficiently
    barangay_patients = Patient.objects.filter(
        barangay=tcl
    ).select_related('user').order_by('user__first_name')

    # Calculate all statistics in a single query
    stats = checkups.aggregate(
        total_checkups=Count('id'),
        today_checkups=Count('id', filter=Q(checkup_date__date=today)),
        completed_checkups=Count('id', filter=Q(status='COMPLETED')),
        upcoming_checkups=Count(
            'id',
            filter=Q(
            status='SCHEDULED',
            checkup_date__gt=timezone.now()
            )
        )
    )

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
    page_obj = paginator.get_page(page_number)

    context = {
        'tcl': tcl,
        'page_obj': page_obj,
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

    # Get all alerts with efficient joins
    alerts = EmergencyAlert.objects.select_related(
        'patient__user',
        'patient__barangay'
    ).filter(
        patient__barangay=tcl
    ).order_by('-alert_time')

    # Parse location data efficiently
    for alert in alerts:
        if alert.location:
            try:
                location_data = json.loads(alert.location)
                alert.parsed_location = {
                    'coordinates': location_data.get('coordinates', ''),
                    'accuracy': location_data.get('accuracy'),
                    'altitude': location_data.get('altitude'),
                    'speed': location_data.get('speed'),
                    'timestamp': location_data.get('timestamp')
                }
            except json.JSONDecodeError:
                alert.parsed_location = None
        else:
            alert.parsed_location = None

    # Calculate all statistics in a single query
    stats = alerts.aggregate(
        active=Count('id', filter=Q(status='ACTIVE')),
        responded=Count('id', filter=Q(status__in=['RESPONDED', 'EN_ROUTE'])),
        resolved=Count('id', filter=Q(status='RESOLVED'))
    )

    # Pagination
    paginator = Paginator(alerts, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'stats': stats,
        'tcl': tcl,
        'title': 'Emergency Monitor'
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

    # Parse location data
    if alert.location:
        try:
            location_data = json.loads(alert.location)
            alert.parsed_location = {
                'coordinates': location_data.get('coordinates', ''),
                'accuracy': location_data.get('accuracy'),
                'altitude': location_data.get('altitude'),
                'speed': location_data.get('speed'),
                'timestamp': location_data.get('timestamp')
            }
        except json.JSONDecodeError:
            alert.parsed_location = None
    else:
        alert.parsed_location = None

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
    today = timezone.now().date()

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
        'tcl': tcl,  # Changed this line
        'today': today,
        'title': f'Patient Report - {tcl.barangay_name}'  # Changed this line if 'name' is the field
    }

    return render(request, 'tcl_management/patient_report.html', context)


@login_required(login_url='tcl_management:login')
@tcl_required
def checkup_report(request):
    """Generate barangay-specific checkup statistics"""
    tcl = request.user.barangay
    today = timezone.now().date()

    # Get checkups from barangay
    checkups = PrenatalCheckup.objects.filter(
        patient__barangay=tcl
    )

    # Calculate all statistics in a single query
    stats = checkups.aggregate(
        total_checkups=Count('id'),
        this_month=Count('id', filter=Q(checkup_date__month=today.month)),
        high_bp_cases=Count('id', filter=Q(blood_pressure__contains='HIGH')),
        completed=Count('id', filter=Q(status='COMPLETED')),
        scheduled=Count('id', filter=Q(status='SCHEDULED')),
        missed=Count('id', filter=Q(status='MISSED')),
        cancelled=Count('id', filter=Q(status='CANCELLED'))
    )

    # Set no_data flag if needed
    stats['no_data'] = not any([
        stats['completed'],
        stats['scheduled'],
        stats['missed'],
        stats['cancelled']
    ])

    # Get weekly trend using efficient database aggregation
    end_date = today
    start_date = end_date - timedelta(days=7 * 8)  # 8 weeks of data

    weekly_trend = checkups.filter(
        checkup_date__range=[start_date, end_date]
    ).annotate(
        week=ExtractWeek('checkup_date'),
        year=ExtractYear('checkup_date')
    ).values('week', 'year').annotate(
        count=Count('id')
    ).order_by('year', 'week')

    # Format weekly trend data
    formatted_trend = []
    for i, data in enumerate(weekly_trend, 1):
        formatted_trend.append({
            'week': f'Week {i}',
            'count': data['count']
        })

    context = {
        'stats': stats,
        'weekly_trend': formatted_trend,
        'tcl': tcl,
        'today': today,
        'title': f'Checkup Report - {tcl.barangay_name}'
    }

    return render(request, 'tcl_management/checkup_report.html', context)


@login_required(login_url='tcl_management:login')
@tcl_required
def emergency_report(request):
    """Generate barangay-specific emergency statistics"""
    tcl = request.user.barangay
    today = timezone.now().date()

    # Get emergencies from barangay
    emergencies = EmergencyAlert.objects.filter(
        patient__barangay=tcl
    )

    # Calculate basic statistics in a single query
    stats = emergencies.aggregate(
        total_alerts=Count('id'),
        active_alerts=Count('id', filter=Q(status='ACTIVE')),
        resolved_cases=Count('id', filter=Q(status='RESOLVED')),
        responded_cases=Count('id', filter=Q(status='RESPONDED')),
        cancelled_cases=Count('id', filter=Q(status='CANCELLED'))
    )

    # Calculate average response time
    resolved_alerts = emergencies.filter(
        status='RESOLVED',
        response_time__isnull=False,
        alert_time__isnull=False
    ).annotate(
        response_minutes=ExpressionWrapper(
            F('response_time') - F('alert_time'),
            output_field=DurationField()
        )
    ).values_list('response_minutes', flat=True)

    if resolved_alerts:
        total_seconds = sum(
            duration.total_seconds() 
            for duration in resolved_alerts
        )
        avg_minutes = total_seconds / (60 * len(resolved_alerts))
        stats['response_time_avg'] = round(avg_minutes, 1)
    else:
        stats['response_time_avg'] = None

    # Set no_data flag if needed
    stats['no_data'] = not any([
        stats['active_alerts'],
        stats['responded_cases'],
        stats['resolved_cases'],
        stats['cancelled_cases']
    ])

    # Get daily trend using efficient database aggregation
    end_date = today
    start_date = end_date - timedelta(days=6)

    daily_trend = emergencies.filter(
        alert_time__date__range=[start_date, end_date]
    ).annotate(
        day=TruncDate('alert_time')
    ).values('day').annotate(
        count=Count('id')
    ).order_by('day')

    # Format daily trend data with all days included
    trend_dict = {item['day']: item['count'] for item in daily_trend}
    formatted_trend = []
    for i in range(7):
        day = today - timedelta(days=i)
        formatted_trend.append({
            'day': day.strftime('%A'),
            'count': trend_dict.get(day, 0)
        })

    context = {
        'stats': stats,
        'daily_trend': formatted_trend,
        'tcl': tcl,
        'today': today,
        'title': f'Emergency Report - {tcl.barangay_name}'
    }

    return render(request, 'tcl_management/emergency_report.html', context)
