# patient_management/views.py
import json
from datetime import datetime, timedelta
from functools import wraps

from django.contrib import messages
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from rhu_management.models import Patient, PregnancyHistory, PrenatalCheckup, EmergencyAlert, \
    Barangay


def patient_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not hasattr(request.user, 'patient'):
            messages.error(request, 'Only patients can access this area.')
            logout(request)
            return redirect('patient_management:login')
        return view_func(request, *args, **kwargs)

    return _wrapped_view


@login_required(login_url='patient_management:login')
@patient_required
def patient_dashboard(request):
    """Display patient dashboard with overview of all information"""

    # Get patient info
    patient = request.user.patient

    # Get latest checkup
    latest_checkup = PrenatalCheckup.objects.filter(
        patient=patient
    ).order_by('-checkup_date').first()

    # Get recent checkups (last 3)
    recent_checkups = PrenatalCheckup.objects.filter(
        patient=patient
    ).order_by('-checkup_date')[:3]

    # Get active emergency alerts
    active_emergencies = EmergencyAlert.objects.filter(
        patient=patient,
        status='ACTIVE'
    ).exists()

    # Calculate pregnancy week and progress
    weeks_pregnant = None
    progress_percentage = None
    if latest_checkup and latest_checkup.last_menstrual_period:  # Add check for latest_checkup
        days_pregnant = (timezone.now().date() - latest_checkup.last_menstrual_period).days
        weeks_pregnant = min(days_pregnant // 7, 42)  # Cap at 42 weeks
        progress_percentage = min((weeks_pregnant / 42) * 100, 100)  # Cap at 100%

    # Get upcoming checkups (next 7 days)
    upcoming_checkups = PrenatalCheckup.objects.filter(
        patient=patient,
        checkup_date__gte=timezone.now(),
        checkup_date__lte=timezone.now() + timedelta(days=7),
        status='SCHEDULED'
    ).order_by('checkup_date')[:3]

    # Calculate time remaining until next checkup
    next_checkup = upcoming_checkups.first()
    days_until_next = None
    hours_until_next = None
    if next_checkup:
        if next_checkup.checkup_date > timezone.now():
            time_remaining = next_checkup.checkup_date - timezone.now()
            days_until_next = time_remaining.days
            hours_until_next = time_remaining.seconds // 3600
        else:
            days_until_next = hours_until_next = 0

    # Recent activity feed with more details
    recent_activity = []
    for checkup in recent_checkups:
        activity_type = 'checkup'
        status_class = {
            'SCHEDULED': 'bg-primary',
            'COMPLETED': 'bg-success',
            'CANCELLED': 'bg-danger',
            'MISSED': 'bg-danger'
        }.get(checkup.status, 'bg-primary')

        recent_activity.append({
            'type': activity_type,
            'date': checkup.checkup_date,
            'status': checkup.status,
            'status_class': status_class,
            'description': f"Checkup - Weight: {checkup.weight}kg, BP: {checkup.blood_pressure}"
        })

    # Quick stats
    stats = {
        'total_checkups': PrenatalCheckup.objects.filter(
            patient=patient).
        count(),
        'completed_checkups': PrenatalCheckup.objects.filter(
            patient=patient,
            status='COMPLETED'
        ).count(),
        'upcoming_checkups': PrenatalCheckup.objects.filter(
            patient=patient,
            checkup_date__gte=timezone.now(),
            status='SCHEDULED'
        ).count(),
        'emergency_alerts': EmergencyAlert.objects.filter(
            patient=patient).
        count()
    }

    context = {
        'patient': patient,
        'latest_checkup': latest_checkup,
        'recent_checkups': recent_checkups,
        'active_emergencies': active_emergencies,
        'weeks_pregnant': weeks_pregnant,
        'progress_percentage': progress_percentage,
        'next_checkup': next_checkup,
        'days_until_next': days_until_next,
        'hours_until_next': hours_until_next,
        'recent_activity': recent_activity,
        'stats': stats,
        'title': 'Dashboard'
    }

    return render(request, 'patient_management/patient_dashboard.html', context)


def patient_register(request):
    """Handle patient registration"""
    if request.user.is_authenticated:
        return redirect('patient_management:dashboard')

    if request.method == 'POST':
        try:
            # Get form data
            username = request.POST.get('username')
            email = request.POST.get('email')
            contact_number = request.POST.get('contact_number')
            password = request.POST.get('password')
            confirm_password = request.POST.get('confirm_password')

            # Validate passwords match
            if password != confirm_password:
                messages.error(request, 'Passwords do not match.')
                return render(request, 'patient_management/patient_register.html', {
                    'title': 'Patient Registration',
                    'barangays': Barangay.objects.all(),
                    'blood_type_choices': Patient.BLOOD_TYPE_CHOICES,
                    'religion_choices': Patient.RELIGION_CHOICES,
                    'form_data': request.POST
                })

            # Check if username already exists
            if User.objects.filter(username=username).exists():
                messages.error(request, 'Username already exists.')
                return render(request, 'patient_management/patient_register.html', {
                    'title': 'Patient Registration',
                    'barangays': Barangay.objects.all(),
                    'blood_type_choices': Patient.BLOOD_TYPE_CHOICES,
                    'religion_choices': Patient.RELIGION_CHOICES,
                    'form_data': request.POST
                })

            # Check if email already exists
            if User.objects.filter(email=email).exists():
                messages.error(request, 'Email already exists.')
                return render(request, 'patient_management/patient_register.html', {
                    'title': 'Patient Registration',
                    'barangays': Barangay.objects.all(),
                    'blood_type_choices': Patient.BLOOD_TYPE_CHOICES,
                    'religion_choices': Patient.RELIGION_CHOICES,
                    'form_data': request.POST
                })

            # Check if contact number already exists
            if Patient.objects.filter(contact_number=contact_number).exists():
                messages.error(request, 'Contact number already exists.')
                return render(request, 'patient_management/patient_register.html', {
                    'title': 'Patient Registration',
                    'barangays': Barangay.objects.all(),
                    'blood_type_choices': Patient.BLOOD_TYPE_CHOICES,
                    'religion_choices': Patient.RELIGION_CHOICES,
                    'form_data': request.POST
                })

            with transaction.atomic():
                # Create User account
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    first_name=request.POST.get('first_name'),
                    last_name=request.POST.get('last_name')
                )

                # Create Patient profile with new fields
                patient = Patient.objects.create(
                    user=user,
                    contact_number=contact_number,
                    birth_date=datetime.strptime(request.POST.get('birth_date'), '%Y-%m-%d').date(),
                    sitio=request.POST.get('sitio'),
                    barangay=Barangay.objects.get(id=request.POST.get('barangay')),
                    # New personal information fields
                    occupation=request.POST.get('occupation'),
                    monthly_income=request.POST.get('monthly_income'),
                    blood_type=request.POST.get('blood_type'),
                    religion=request.POST.get('religion'),
                    # Family information fields
                    spouse_name=request.POST.get('spouse_name'),
                    spouse_occupation=request.POST.get('spouse_occupation'),
                    spouse_monthly_income=request.POST.get('spouse_monthly_income'),
                    number_of_children=request.POST.get('number_of_children'),
                    # Emergency contact fields
                    emergency_contact_name=request.POST.get('emergency_contact_name'),
                    emergency_contact_number=request.POST.get('emergency_contact_number')
                )

                messages.success(request, 'Registration successful! Please login.')
                return redirect('patient_management:login')

        except Exception as e:
            messages.error(request, f'Error during registration: {str(e)}')
            return render(request, 'patient_management/patient_register.html', {
                'title': 'Patient Registration',
                'barangays': Barangay.objects.all(),
                'blood_type_choices': Patient.BLOOD_TYPE_CHOICES,
                'religion_choices': Patient.RELIGION_CHOICES,
                'form_data': request.POST
            })

    return render(request, 'patient_management/patient_register.html', {
        'title': 'Patient Registration',
        'barangays': Barangay.objects.all(),
        'blood_type_choices': Patient.BLOOD_TYPE_CHOICES,
        'religion_choices': Patient.RELIGION_CHOICES
    })


def patient_login(request):
    """Handle patient login"""
    if request.user.is_authenticated:
        if hasattr(request.user, 'patient'):
            return redirect('patient_management:dashboard')
        else:
            logout(request)
            messages.error(request, 'Only patients can access this area.')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(username=username, password=password)

        if user is not None:
            if hasattr(user, 'patient'):
                login(request, user)
                messages.success(request, f'Welcome back, {user.first_name}!')
                return redirect('patient_management:dashboard')
            else:
                messages.error(request, 'This account is not registered as a patient.')
        else:
            messages.error(request, 'Invalid email or password.')

    return render(request, 'patient_management/patient_login.html', {
        'title': 'Patient Login'
    })


@login_required(login_url='patient_management:login')
@patient_required
def patient_logout(request):
    """Handle patient logout"""
    logout(request)
    messages.success(request, 'You have been logged out successfully.')
    return redirect('patient_management:login')


@login_required(login_url='patient_management:login')
@patient_required
def profile_view(request):
    """Display patient profile"""
    patient = get_object_or_404(Patient, user=request.user)

    return render(request, 'patient_management/profile_view.html', {
        'patient': patient,
        'title': 'My Profile'
    })


@login_required(login_url='patient_management:login')
@patient_required
def profile_update(request):
    """Handle patient profile update"""
    patient = request.user.patient

    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        contact_number = request.POST.get('contact_number')
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')

        # Check if username already exists (excluding current patient)
        if User.objects.exclude(id=patient.user.id).filter(username=username).exists():
            messages.error(request, 'Username already exists.')
            return redirect('patient_management:profile_update')

        # Check if email already exists (excluding current patient)
        if User.objects.exclude(id=patient.user.id).filter(email=email).exists():
            messages.error(request, 'Email already exists.')
            return redirect('patient_management:profile_update')

        # Check if contact number already exists (excluding current patient)
        if Patient.objects.exclude(id=patient.id).filter(contact_number=contact_number).exists():
            messages.error(request, 'Contact number already exists.')
            return redirect('patient_management:profile_update')

        # Validate passwords if provided
        if password:
            if password != confirm_password:
                messages.error(request, 'Passwords do not match.')
                return redirect('patient_management:profile_update')

        try:
            with transaction.atomic():
                # Update User information
                user = patient.user
                user.username = username
                user.first_name = request.POST.get('first_name')
                user.last_name = request.POST.get('last_name')
                user.email = email
                if password:
                    user.set_password(password)
                user.save()

                # Update Patient information
                patient.contact_number = contact_number
                patient.birth_date = datetime.strptime(request.POST.get('birth_date'), '%Y-%m-%d').date()
                patient.sitio = request.POST.get('sitio')
                patient.barangay = get_object_or_404(Barangay, id=request.POST.get('barangay'))
                patient.occupation = request.POST.get('occupation')
                patient.monthly_income = request.POST.get('monthly_income')
                patient.blood_type = request.POST.get('blood_type')
                patient.religion = request.POST.get('religion')
                patient.spouse_name = request.POST.get('spouse_name')
                patient.spouse_occupation = request.POST.get('spouse_occupation')
                patient.spouse_monthly_income = request.POST.get('spouse_monthly_income')
                patient.number_of_children = request.POST.get('number_of_children')
                patient.emergency_contact_name = request.POST.get('emergency_contact_name')
                patient.emergency_contact_number = request.POST.get('emergency_contact_number')
                patient.save()

                messages.success(request, 'Profile updated successfully!')

                # If password was changed, redirect to login
                if password:
                    logout(request)
                    messages.info(request, 'Please login with your new password.')
                    return redirect('patient_management:login')

                return redirect('patient_management:profile_view')

        except Exception as e:
            messages.error(request, f'Error updating profile: {str(e)}')

    return render(request, 'patient_management/profile_edit.html', {
        'patient': patient,
        'barangays': Barangay.objects.all().order_by('barangay_name'),
        'blood_type_choices': Patient.BLOOD_TYPE_CHOICES,
        'religion_choices': Patient.RELIGION_CHOICES,
        'title': 'Edit Profile'
    })


@login_required(login_url='patient_management:login')
@patient_required
def checkup_list(request):
    """Display list of patient's checkups"""
    # Get the sort parameter from request, default to '-checkup_date'
    current_sort = request.GET.get('sort', '-checkup_date')
    
    # Apply sorting to the queryset
    checkups = PrenatalCheckup.objects.filter(
        patient=request.user.patient
    ).order_by(current_sort)

    # Calculate statistics
    stats = {
        'today': checkups.filter(checkup_date__date=timezone.now().date()).count(),
        'upcoming': checkups.filter(
            checkup_date__gt=timezone.now(),
            status='SCHEDULED'
        ).count(),
        'completed': checkups.filter(status='COMPLETED').count(),
        'cancelled': checkups.filter(status__in=['CANCELLED', 'MISSED']).count()
    }

    paginator = Paginator(checkups, 10)
    page = request.GET.get('page')
    page_obj = paginator.get_page(page)

    return render(request, 'patient_management/checkup_list.html', {
        'page_obj': page_obj,
        'stats': stats,
        'current_sort': current_sort,  # Pass the current sort to the template
        'title': 'My Checkups'
    })


@login_required(login_url='patient_management:login')
@patient_required
def checkup_detail(request, checkup_id):
    """Display detailed checkup information"""
    patient = request.user.patient

    # Get the specific checkup
    checkup = get_object_or_404(
        PrenatalCheckup,
        id=checkup_id,
        patient=patient
    )

    # Calculate pregnancy week at time of checkup
    weeks_pregnant = None
    if checkup.last_menstrual_period:
        days_pregnant = (timezone.now().date() - checkup.last_menstrual_period).days
        weeks_pregnant = days_pregnant // 7

    # Calculate time remaining until checkup (if scheduled)
    days_remaining = hours_remaining = 0
    if checkup.status == 'SCHEDULED' and checkup.checkup_date > timezone.now():
        time_remaining = checkup.checkup_date - timezone.now()
        days_remaining = time_remaining.days
        hours_remaining = time_remaining.seconds // 3600

    return render(request, 'patient_management/checkup_detail.html', {
        'checkup': checkup,
        'weeks_pregnant': weeks_pregnant,
        'days_remaining': days_remaining,
        'hours_remaining': hours_remaining,
        'title': f'Checkup Details - {checkup.checkup_date.strftime("%B %d, %Y")}'
    })


@login_required(login_url='patient_management:login')
@patient_required
def request_checkup(request):
    """Handle checkup requests from patients"""
    patient = request.user.patient

    # Get the initial checkup data
    initial_checkup = PrenatalCheckup.objects.filter(
        patient=patient,
        is_initial_record=True
    ).first()

    if request.method == 'POST':
        try:
            requested_date = datetime.strptime(
                f"{request.POST.get('checkup_date')} {request.POST.get('checkup_time')}",
                '%Y-%m-%d %H:%M'
            )

            checkup_data = {
                'patient': patient,
                'checkup_date': requested_date,
                'notes': request.POST.get('notes'),
                'status': 'REQUESTED'
            }

            if not initial_checkup:
                # This is the first checkup
                checkup_data.update({
                    'is_initial_record': True,
                    'weight': float(request.POST.get('weight')),
                    'height': float(request.POST.get('height')),
                    'blood_pressure': request.POST.get('blood_pressure'),
                    'last_menstrual_period': datetime.strptime(
                        request.POST.get('last_menstrual_period'),
                        '%Y-%m-%d'
                    ).date(),
                    'initial_weight': float(request.POST.get('weight')),
                    'initial_height': float(request.POST.get('height')),
                    'initial_blood_pressure': request.POST.get('blood_pressure'),
                    'initial_last_menstrual_period': datetime.strptime(
                        request.POST.get('last_menstrual_period'),
                        '%Y-%m-%d'
                    ).date()
                })
            else:
                # Copy values from initial checkup
                checkup_data.update({
                    'weight': initial_checkup.weight,
                    'height': initial_checkup.height,
                    'blood_pressure': initial_checkup.blood_pressure,
                    'last_menstrual_period': initial_checkup.last_menstrual_period,
                    'initial_weight': initial_checkup.initial_weight,
                    'initial_height': initial_checkup.initial_height,
                    'initial_blood_pressure': initial_checkup.initial_blood_pressure,
                    'initial_last_menstrual_period': initial_checkup.initial_last_menstrual_period
                })

            PrenatalCheckup.objects.create(**checkup_data)
            messages.success(request, 'Checkup request submitted successfully!')
            return redirect('patient_management:checkup_list')

        except ValueError as e:
            messages.error(request, 'Please check your input values.')
        except Exception as e:
            messages.error(request, str(e))

    return render(request, 'patient_management/checkup_request.html', {
        'has_previous_checkup': bool(initial_checkup),
        'initial_checkup': initial_checkup,
        'title': 'Request Checkup'
    })


@login_required(login_url='patient_management:login')
@patient_required
def pregnancy_history_create(request):
    """Handle creation of pregnancy history record"""
    if request.method == 'POST':
        try:
            with transaction.atomic():
                pregnancy = PregnancyHistory.objects.create(
                    patient=request.user.patient,
                    delivery_date=datetime.strptime(request.POST.get('delivery_date'), '%Y-%m-%d').date(),
                    delivery_type=request.POST.get('delivery_type'),
                    delivery_location=request.POST.get('delivery_location'),
                    birth_weight=request.POST.get('birth_weight'),
                    complications=request.POST.get('complications', '')
                )

                messages.success(request, 'Pregnancy history added successfully!')
                return redirect('patient_management:pregnancy_history_list')
        except Exception as e:
            messages.error(request, 'Error adding pregnancy history.')

    return render(request, 'patient_management/pregnancy_history_add.html', {
        'title': 'Add Pregnancy History'
    })


@login_required(login_url='patient_management:login')
@patient_required
def pregnancy_history_list(request):
    """Display list of pregnancy history records"""
    histories = PregnancyHistory.objects.filter(
        patient=request.user.patient
    ).order_by('-delivery_date')

    stats = {
        'total_pregnancies': histories.count(),
        'normal_deliveries': histories.filter(delivery_type='NORMAL').count(),
        'cs_deliveries': histories.filter(delivery_type='CS').count(),
        'assisted_deliveries': histories.filter(delivery_type='ASSISTED').count(),
    }

    return render(request, 'patient_management/pregnancy_history_list.html', {
        'histories': histories,
        'stats': stats,
        'title': 'Pregnancy History'
    })


@login_required(login_url='patient_management:login')
@patient_required
def pregnancy_history_update(request, history_id):
    """Handle updating of pregnancy history record"""
    history = get_object_or_404(PregnancyHistory, id=history_id, patient=request.user.patient)

    if request.method == 'POST':
        try:
            with transaction.atomic():
                history.delivery_date = datetime.strptime(request.POST.get('delivery_date'), '%Y-%m-%d').date()
                history.delivery_type = request.POST.get('delivery_type')
                history.delivery_location = request.POST.get('delivery_location')
                history.birth_weight = request.POST.get('birth_weight')
                history.complications = request.POST.get('complications', '')
                history.save()

                messages.success(request, 'Pregnancy history updated successfully!')
                return redirect('patient_management:pregnancy_history_list')
        except Exception as e:
            messages.error(request, 'Error updating pregnancy history.')

    return render(request, 'patient_management/pregnancy_history_edit.html', {
        'history': history,
        'title': 'Edit Pregnancy History'
    })


@require_POST
@login_required(login_url='patient_management:login')
@patient_required
def emergency_alert(request):
    """Handle emergency alert trigger"""
    try:
        # Get location data if provided
        data = json.loads(request.body)
        location = data.get('location', '')
        coordinates = data.get('coordinates', '')

        # Create emergency alert
        alert = EmergencyAlert.objects.create(
            patient=request.user.patient,
            location=location,
            status='ACTIVE'
        )

        # TODO: Send notifications to healthcare providers
        # This would involve sending SMS/calling the assigned healthcare provider
        # Implementation depends on your notification service

        return JsonResponse({
            'success': True,
            'message': 'Emergency alert has been sent. Help is on the way.',
            'alert_id': alert.id
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': 'Failed to send emergency alert. Please call emergency services directly.'
        }, status=500)


@login_required(login_url='patient_management:login')
@patient_required
def emergency_history(request):
    """Display emergency alert history"""
    # Get all alerts for the patient
    alerts = EmergencyAlert.objects.filter(
        patient=request.user.patient
    ).order_by('-alert_time')

    # Get statistics
    stats = {
        'total_alerts': alerts.count(),
        'active_alerts': alerts.filter(status='ACTIVE').count(),
        'resolved_alerts': alerts.filter(status='RESOLVED').count(),
        'recent_alerts': alerts.filter(
            alert_time__gte=timezone.now() - timezone.timedelta(days=30)
        ).count()
    }

    # Pagination
    paginator = Paginator(alerts, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'patient_management/emergency_history.html', {
        'page_obj': page_obj,
        'stats': stats,
        'title': 'Emergency Alert History'
    })


def send_test_sms(phone_number):
    """Send a test SMS"""
    # Implement SMS sending logic here
    # This would integrate with your SMS service provider
    pass


def send_test_email(email):
    """Send a test email"""
    # Implement email sending logic here
    # This would use Django's email functionality
    from django.core.mail import send_mail

    try:
        send_mail(
            subject='Test Notification - Prenatal Care System',
            message='This is a test notification to verify your notification settings.',
            from_email='noreply@example.com',
            recipient_list=[email],
            fail_silently=False,
        )
        return True
    except Exception as e:
        print(f"Error sending test email: {str(e)}")
        return False
