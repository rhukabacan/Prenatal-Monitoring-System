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

import requests
from django.conf import settings


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
            'description': "Checkup"
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


# @login_required(login_url='patient_management:login')
# @patient_required
# def request_checkup(request):
#     """Handle checkup requests from patients"""
#     patient = request.user.patient
#
#     # Get previous checkup for reference
#     previous_checkup = PrenatalCheckup.objects.filter(
#         patient=patient
#     ).order_by('-checkup_date').first()
#
#     # Check if patient has vital signs
#     has_vital_signs = VitalSigns.objects.filter(patient=patient).exists()
#
#     if request.method == 'POST':
#         try:
#             requested_date = datetime.combine(
#                 datetime.strptime(request.POST.get('checkup_date'), '%Y-%m-%d').date(),
#                 datetime.strptime(request.POST.get('checkup_time'), '%H:%M').time()
#             )
#
#             # Determine last menstrual period
#             last_menstrual_period = request.POST.get('last_menstrual_period')
#             if not last_menstrual_period and previous_checkup:
#                 last_menstrual_period = previous_checkup.last_menstrual_period
#
#             # Convert last_menstrual_period to date if it's a string
#             if isinstance(last_menstrual_period, str):
#                 last_menstrual_period = datetime.strptime(last_menstrual_period, '%Y-%m-%d').date()
#
#             # Create checkup record
#             checkup = PrenatalCheckup.objects.create(
#                 patient=patient,
#                 checkup_date=requested_date,
#                 last_menstrual_period=last_menstrual_period,
#                 notes=request.POST.get('notes', ''),
#                 status='REQUESTED'
#             )
#
#             if not previous_checkup:
#                 # Check if vital signs exist before creating first checkup
#                 if not has_vital_signs:
#                     messages.warning(request, 'Please update your vital signs first before requesting a checkup.')
#                     return redirect('patient_management:vital_signs')
#
#             messages.success(request, 'Checkup request submitted successfully!')
#             return redirect('patient_management:checkup_list')
#
#         except ValueError as e:
#             messages.error(request, 'Please check your input values.')
#         except Exception as e:
#             messages.error(request, str(e))
#
#     return render(request, 'patient_management/checkup_request.html', {
#         'previous_checkup': previous_checkup,
#         'has_vital_signs': has_vital_signs,
#         'title': 'Request Checkup'
#     })


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
        # Get location data from request
        data = json.loads(request.body)
        location_data = data.get('location', {})
        
        # Format location data for storage
        location_info = {
            'coordinates': location_data.get('coordinates', ''),
            'accuracy': location_data.get('accuracy'),
            'altitude': location_data.get('altitude'),
            'speed': location_data.get('speed'),
            'timestamp': location_data.get('timestamp')
        }

        patient = request.user.patient

        # Create emergency alert with formatted location data
        alert = EmergencyAlert.objects.create(
            patient=patient,
            location=json.dumps(location_info),  # Store as JSON string
            status='ACTIVE'
        )

        try:
            # Get the latest checkup for vital signs info
            latest_checkup = PrenatalCheckup.objects.filter(
                patient=patient
            ).order_by('-checkup_date').first()

            # Prepare base message with more relevant details
            message = (
                f"!!! EMERGENCY ALERT !!!\n\n"
                f"PATIENT DETAILS:\n"
                f"Name: {patient.user.first_name} {patient.user.last_name}\n"
                f"Age: {patient.age} years old\n"
                f"Contact: {patient.contact_number}\n"
            )

            # Add pregnancy and vital signs section if available
            if latest_checkup:
                message += f"\nMEDICAL INFO:\n"
                if latest_checkup.age_of_gestation:
                    message += f"Pregnancy: {latest_checkup.age_of_gestation} weeks\n"
                if latest_checkup.blood_pressure:
                    message += f"Blood Pressure: {latest_checkup.blood_pressure}\n"
                if latest_checkup.weight:
                    message += f"Weight: {latest_checkup.weight} kg\n"

            # Add location section with coordinates
            message += (
                f"\nLOCATION:\n"
                f"Barangay: {patient.barangay.barangay_name}\n"
                f"Sitio: {patient.sitio}\n"
            )

            if location_info['coordinates']:
                message += f"GPS Coordinates: {location_info['coordinates']}\n"
                message += f"Location Accuracy: {location_info['accuracy']} meters\n"
                message += f"Google Maps: https://www.google.com/maps?q={location_info['coordinates']}\n"

            # Add emergency contact section
            message += (
                f"\nEMERGENCY CONTACT:\n"
                f"Name: {patient.emergency_contact_name}\n"
                f"Number: {patient.emergency_contact_number}\n\n"
                f"PLEASE RESPOND IMMEDIATELY!"
            )

            # Prepare emergency contact message
            emergency_contact_message = (
                f"!!! EMERGENCY ALERT !!!\n\n"
                f"Your emergency contact {patient.user.first_name} {patient.user.last_name} "
                f"has triggered an emergency alert.\n\n"
                f"Patient Location:\n"
                f"Barangay: {patient.barangay.barangay_name}\n"
                f"Sitio: {patient.sitio}\n"
            )
            
            if location_info['coordinates']:
                emergency_contact_message += (
                    f"Google Maps: https://www.google.com/maps?q={location_info['coordinates']}\n\n"
                )
            
            emergency_contact_message += (
                f"Medical personnel have been notified and are responding.\n"
                f"Please proceed to assist if possible.\n\n"
                f"Patient Contact: {patient.contact_number}"
            )

            # Verify TCL contact number exists
            if not hasattr(patient.barangay, 'contact_number') or not patient.barangay.contact_number:
                # Continue with just RHU notification
                tcl_number = None
            else:
                tcl_number = patient.barangay.contact_number

            # Prepare payloads
            url = "https://api.semaphore.co/api/v4/messages"
            responses = []

            # Send to RHU
            try:
                rhu_payload = {
                    "apikey": settings.SEMAPHORE_API_KEY,
                    "number": settings.RHU_CONTACT_NUMBER,
                    "message": message,
                    "sendername": settings.SEMAPHORE_SENDER_NAME
                }
                rhu_response = requests.post(url, data=rhu_payload)
                responses.append(('RHU', rhu_response))
            except Exception as e:
                print(f"Error sending RHU SMS: {str(e)}")

            # Send to TCL if number exists
            if tcl_number:
                try:
                    tcl_payload = {
                        "apikey": settings.SEMAPHORE_API_KEY,
                        "number": tcl_number,
                        "message": message,
                        "sendername": settings.SEMAPHORE_SENDER_NAME
                    }
                    tcl_response = requests.post(url, data=tcl_payload)
                    responses.append(('TCL', tcl_response))
                except Exception as e:
                    print(f"Error sending TCL SMS: {str(e)}")

            # Send to Emergency Contact
            try:
                emergency_contact_payload = {
                    "apikey": settings.SEMAPHORE_API_KEY,
                    "number": patient.emergency_contact_number,
                    "message": emergency_contact_message,
                    "sendername": settings.SEMAPHORE_SENDER_NAME
                }
                emergency_contact_response = requests.post(url, data=emergency_contact_payload)
                responses.append(('Emergency Contact', emergency_contact_response))
            except Exception as e:
                print(f"Error sending Emergency Contact SMS: {str(e)}")

            # Check responses
            failed_requests = [(recipient, r) for recipient, r in responses if not r.ok]
            if failed_requests:
                failed_details = [f"{recipient}: {r.status_code} - {r.text}" 
                                for recipient, r in failed_requests]
                print(f"SMS sending failures: {failed_details}")
                return JsonResponse({
                    'success': True,
                    'message': 'Emergency alert has been recorded but there were issues sending some notifications.',
                    'alert_id': alert.id
                })

            return JsonResponse({
                'success': True,
                'message': 'Emergency alert has been sent. Help is on the way.',
                'alert_id': alert.id
            })

        except Exception as e:
            print(f"Error in SMS sending process: {str(e)}")
            return JsonResponse({
                'success': True,
                'message': 'Emergency alert has been recorded but there was an issue sending notifications.',
                'alert_id': alert.id
            })

    except Exception as e:
        print(f"Critical error in emergency alert: {str(e)}")
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

    # Parse location data for each alert
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
            except json.JSONDecodeError as e:
                alert.parsed_location = None
        else:
            alert.parsed_location = None

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


@login_required(login_url='patient_management:login')
@patient_required
def vital_signs(request):
    """Display vital signs monitoring page"""
    patient = request.user.patient
    
    # Get latest checkup with vital signs
    latest_checkup = PrenatalCheckup.objects.filter(
        patient=patient
    ).order_by('-checkup_date').first()
    
    # Get previous checkup for comparison with latest
    previous_checkup = None
    if latest_checkup:
        previous_checkup = PrenatalCheckup.objects.filter(
            patient=patient,
            checkup_date__lt=latest_checkup.checkup_date
        ).order_by('-checkup_date').first()

    # Calculate changes for latest checkup
    changes = {}
    if previous_checkup:
        # Calculate all changes between latest and previous checkup
        calculate_changes(latest_checkup, previous_checkup, changes)

    # Get checkup history and calculate changes for each
    checkups = list(PrenatalCheckup.objects.filter(
        patient=patient
    ).order_by('-checkup_date')[:10])

    # Calculate changes for each checkup in history
    for i, checkup in enumerate(checkups[:-1]):  # Skip last checkup as it has no previous
        next_checkup = checkups[i + 1]  # Get next checkup (chronologically previous)
        checkup.weight_change = None
        checkup.weight_change_type = None
        
        # Calculate weight change
        if checkup.weight and next_checkup.weight:
            weight_diff = float(checkup.weight) - float(next_checkup.weight)
            checkup.weight_change = abs(weight_diff)
            checkup.weight_change_type = 'increase' if weight_diff > 0 else 'decrease'
        
        # Calculate height change
        if checkup.height and next_checkup.height:
            height_diff = float(checkup.height) - float(next_checkup.height)
            checkup.height_change = abs(height_diff)
            checkup.height_change_type = 'increase' if height_diff > 0 else 'decrease'
        
        # Status changes
        checkup.blood_pressure_changed = checkup.blood_pressure != next_checkup.blood_pressure
        checkup.age_of_gestation_changed = checkup.age_of_gestation != next_checkup.age_of_gestation
        checkup.nutritional_status_changed = checkup.nutritional_status != next_checkup.nutritional_status
        checkup.birth_plan_status_changed = checkup.birth_plan_status != next_checkup.birth_plan_status
        checkup.dental_checkup_status_changed = checkup.dental_checkup_status != next_checkup.dental_checkup_status
        
        # Lab test changes
        checkup.hemoglobin_count_changed = checkup.hemoglobin_count != next_checkup.hemoglobin_count
        checkup.urinalysis_date_changed = checkup.urinalysis_date != next_checkup.urinalysis_date
        checkup.cbc_date_changed = checkup.cbc_date != next_checkup.cbc_date
        checkup.stool_exam_date_changed = checkup.stool_exam_date != next_checkup.stool_exam_date
        
        # STI test changes
        checkup.syphilis_test_date_changed = checkup.syphilis_test_date != next_checkup.syphilis_test_date
        checkup.syphilis_result_changed = checkup.syphilis_result != next_checkup.syphilis_result
        checkup.hiv_test_date_changed = checkup.hiv_test_date != next_checkup.hiv_test_date
        checkup.hiv_result_changed = checkup.hiv_result != next_checkup.hiv_result
        checkup.hepatitis_b_test_date_changed = checkup.hepatitis_b_test_date != next_checkup.hepatitis_b_test_date
        checkup.hepatitis_b_result_changed = checkup.hepatitis_b_result != next_checkup.hepatitis_b_result
        
        # Treatment changes
        checkup.tetanus_vaccine_date_changed = checkup.tetanus_vaccine_date != next_checkup.tetanus_vaccine_date
        checkup.syphilis_treatment_changed = checkup.syphilis_treatment != next_checkup.syphilis_treatment
        checkup.arv_treatment_changed = checkup.arv_treatment != next_checkup.arv_treatment
        checkup.bacteriuria_treatment_changed = checkup.bacteriuria_treatment != next_checkup.bacteriuria_treatment
        checkup.anemia_treatment_changed = checkup.anemia_treatment != next_checkup.anemia_treatment

    context = {
        'title': 'Vital Signs Monitoring',
        'latest_checkup': latest_checkup,
        'changes': changes,
        'checkups': checkups,
        'birth_plan_choices': PrenatalCheckup.BIRTH_PLAN_STATUS,
        'dental_checkup_choices': PrenatalCheckup.DENTAL_CHECKUP_STATUS,
        'nutritional_status_choices': PrenatalCheckup.NUTRITIONAL_STATUS_CHOICES,
    }

    return render(request, 'patient_management/vital_signs.html', context)

def calculate_changes(current, previous, changes):
    """Helper function to calculate changes between two checkups"""
    if current.weight and previous.weight:
        weight_diff = float(current.weight) - float(previous.weight)
        changes['weight'] = {
            'diff': round(weight_diff, 2),
            'increased': weight_diff > 0
        }

    if current.height and previous.height:
        height_diff = float(current.height) - float(previous.height)
        changes['height'] = {
            'diff': round(height_diff, 2),
            'increased': height_diff > 0
        }

    # Status changes
    changes['blood_pressure_changed'] = current.blood_pressure != previous.blood_pressure
    changes['age_of_gestation_changed'] = current.age_of_gestation != previous.age_of_gestation
    changes['nutritional_status_changed'] = current.nutritional_status != previous.nutritional_status
    changes['birth_plan_status_changed'] = current.birth_plan_status != previous.birth_plan_status
    changes['dental_checkup_status_changed'] = current.dental_checkup_status != previous.dental_checkup_status
    changes['dental_checkup_date_changed'] = current.dental_checkup_date != previous.dental_checkup_date

    # Lab test changes
    changes['hemoglobin_count_changed'] = current.hemoglobin_count != previous.hemoglobin_count
    changes['urinalysis_date_changed'] = current.urinalysis_date != previous.urinalysis_date
    changes['cbc_date_changed'] = current.cbc_date != previous.cbc_date
    changes['stool_exam_date_changed'] = current.stool_exam_date != previous.stool_exam_date

    # STI test changes
    changes['syphilis_test_date_changed'] = current.syphilis_test_date != previous.syphilis_test_date
    changes['syphilis_result_changed'] = current.syphilis_result != previous.syphilis_result
    changes['hiv_test_date_changed'] = current.hiv_test_date != previous.hiv_test_date
    changes['hiv_result_changed'] = current.hiv_result != previous.hiv_result
    changes['hepatitis_b_test_date_changed'] = current.hepatitis_b_test_date != previous.hepatitis_b_test_date
    changes['hepatitis_b_result_changed'] = current.hepatitis_b_result != previous.hepatitis_b_result

    # Treatment changes
    changes['tetanus_vaccine_date_changed'] = current.tetanus_vaccine_date != previous.tetanus_vaccine_date
    changes['syphilis_treatment_changed'] = current.syphilis_treatment != previous.syphilis_treatment
    changes['arv_treatment_changed'] = current.arv_treatment != previous.arv_treatment
    changes['bacteriuria_treatment_changed'] = current.bacteriuria_treatment != previous.bacteriuria_treatment
    changes['anemia_treatment_changed'] = current.anemia_treatment != previous.anemia_treatment

@login_required(login_url='patient_management:login')
@patient_required
def update_vital_signs(request):
    """Handle vital signs update"""
    try:
        patient = request.user.patient
        
        # Get the latest checkup
        latest_checkup = PrenatalCheckup.objects.filter(
            patient=patient
        ).order_by('-checkup_date').first()
        
        if not latest_checkup:
            messages.error(request, 'No checkup record found to update.')
            return redirect('patient_management:vital_signs')

        # Helper function to handle decimal fields
        def get_decimal_or_none(value):
            return float(value) if value and value.strip() else None

        # Update the latest checkup with new vital signs data
        latest_checkup.weight = get_decimal_or_none(request.POST.get('weight'))
        latest_checkup.height = get_decimal_or_none(request.POST.get('height'))
        latest_checkup.blood_pressure = request.POST.get('blood_pressure')
        latest_checkup.age_of_gestation = request.POST.get('age_of_gestation') or None
        
        # Status & Planning
        latest_checkup.nutritional_status = request.POST.get('nutritional_status')
        latest_checkup.birth_plan_status = request.POST.get('birth_plan_status')
        latest_checkup.dental_checkup_status = request.POST.get('dental_checkup_status')
        latest_checkup.dental_checkup_date = request.POST.get('dental_checkup_date') or None
        
        # Laboratory Tests
        latest_checkup.hemoglobin_count = get_decimal_or_none(request.POST.get('hemoglobin_count'))
        latest_checkup.urinalysis_date = request.POST.get('urinalysis_date') or None
        latest_checkup.cbc_date = request.POST.get('cbc_date') or None
        latest_checkup.stool_exam_date = request.POST.get('stool_exam_date') or None
        
        # STI Tests
        latest_checkup.syphilis_test_date = request.POST.get('syphilis_test_date') or None
        latest_checkup.syphilis_result = request.POST.get('syphilis_result')
        latest_checkup.hiv_test_date = request.POST.get('hiv_test_date') or None
        latest_checkup.hiv_result = request.POST.get('hiv_result')
        latest_checkup.hepatitis_b_test_date = request.POST.get('hepatitis_b_test_date') or None
        latest_checkup.hepatitis_b_result = request.POST.get('hepatitis_b_result')
        
        # Treatments
        latest_checkup.tetanus_vaccine_date = request.POST.get('tetanus_vaccine_date') or None
        latest_checkup.syphilis_treatment = request.POST.get('syphilis_treatment')
        latest_checkup.arv_treatment = request.POST.get('arv_treatment')
        latest_checkup.bacteriuria_treatment = request.POST.get('bacteriuria_treatment')
        latest_checkup.anemia_treatment = request.POST.get('anemia_treatment')
        
        # Save the changes
        latest_checkup.save()
        
        messages.success(request, 'Vital signs updated successfully!')
        
    except ValueError as e:
        messages.error(request, 'Please enter valid numbers for measurements.')
    except Exception as e:
        messages.error(request, f'Error updating vital signs: {str(e)}')
    
    return redirect('patient_management:vital_signs')
