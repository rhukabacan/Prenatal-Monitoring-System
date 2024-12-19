# rhu_management/views.py

import os
from datetime import datetime, timedelta
from functools import wraps
import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout, authenticate, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db import transaction, models
from django.db.models import Count, Avg, Q, OuterRef, Subquery
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from django.views.decorators.http import require_GET
from django.views.decorators.cache import cache_page
from .tasks import check_active_emergencies
import requests

from .models import Barangay, Patient, PrenatalCheckup, EmergencyAlert, RHUReport, PregnancyHistory


def superuser_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_superuser:
            messages.error(request, 'Only administrators can access this area.')
            logout(request)
            return redirect('rhu_management:rhu_login')
        return view_func(request, *args, **kwargs)

    return _wrapped_view


def rhu_login(request):
    """Handle RHU staff login"""
    if request.user.is_authenticated:
        if request.user.is_superuser:
            return redirect('rhu_management:dashboard')
        else:
            logout(request)
            messages.error(request, 'Only administrators can access this area.')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        try:
            user = authenticate(username=username, password=password)
            if user is not None and user.is_superuser:
                login(request, user)
                messages.success(request, f'Welcome back, {user.get_full_name()}!')
                return redirect('rhu_management:dashboard')
            else:
                messages.error(request, 'Invalid credentials or insufficient permissions.')
        except Exception as e:
            messages.error(request, 'An error occurred during login.')

    return render(request, 'rhu_management/login.html', {
        'title': 'RHU Staff Login'
    })


@login_required(login_url='rhu_management:rhu_login')
@superuser_required
def rhu_logout(request):
    """Handle RHU staff logout"""
    logout(request)
    messages.success(request, 'You have been logged out successfully.')
    return redirect('rhu_management:rhu_login')


@login_required(login_url='rhu_management:rhu_login')
@superuser_required
def profile_update(request):
    """Handle RHU staff profile update"""
    # Get the user directly since we're updating the User model
    user = request.user

    if request.method == 'POST':
        try:
            with transaction.atomic():
                # Update User model fields
                user.first_name = request.POST.get('first_name')
                user.last_name = request.POST.get('last_name')
                user.email = request.POST.get('email')
                
                # Handle password change if provided
                new_password = request.POST.get('new_password')
                confirm_password = request.POST.get('confirm_password')
                
                if new_password:
                    if new_password != confirm_password:
                        messages.error(request, 'New passwords do not match.')
                        return redirect('rhu_management:profile_update')
                    
                    # Check if current password is correct
                    current_password = request.POST.get('current_password')
                    if not user.check_password(current_password):
                        messages.error(request, 'Current password is incorrect.')
                        return redirect('rhu_management:profile_update')
                    
                    user.set_password(new_password)
                    messages.success(request, 'Password updated successfully. Please login again.')
                
                user.save()
                
                messages.success(request, 'Profile updated successfully!')
                
                # If password was changed, redirect to login
                if new_password:
                    return redirect('rhu_management:rhu_login')
                    
                return redirect('rhu_management:dashboard')

        except Exception as e:
            messages.error(request, f'An error occurred while updating your profile: {str(e)}')

    context = {
        'user': user,
        'title': 'Edit Profile'
    }

    return render(request, 'rhu_management/edit_profile.html', context)


@login_required(login_url='rhu_management:rhu_login')
@superuser_required
def barangay_list(request):
    """Display list of barangays and their TCLs"""
    # Get search query and status filter
    search_query = request.GET.get('search', '')

    # Base queryset
    barangays = Barangay.objects.all()

    # Apply search filter
    if search_query:
        barangays = barangays.filter(
            Q(barangay_name__icontains=search_query) |
            Q(contact_number__icontains=search_query) |
            Q(user__username__icontains=search_query) |
            Q(user__email__icontains=search_query)
        )

    # Pagination
    paginator = Paginator(barangays, 10)  # Show 10 barangays per page
    page = request.GET.get('page')
    page_obj = paginator.get_page(page)

    # Get statistics for displayed barangays
    for barangay in page_obj:
        barangay.stats = {
            'total_patients': Patient.objects.filter(
                barangay=barangay
            ).count(),
            'active_emergencies': EmergencyAlert.objects.filter(
                patient__barangay=barangay,
                status='ACTIVE'
            ).count()
        }

    context = {
        'barangays': page_obj,
        'search_query': search_query,
        'total_barangays': barangays.count(),
        'title': 'Barangay Management'
    }
    return render(request, 'rhu_management/barangay/barangay_list.html', context)


@login_required(login_url='rhu_management:rhu_login')
@superuser_required
def barangay_detail(request, barangay_id):
    """Display detailed information about a specific barangay"""
    barangay = get_object_or_404(Barangay, id=barangay_id)

    # Get statistics
    stats = {
        'total_patients': Patient.objects.filter(barangay=barangay).count(),
        'pregnant_patients': Patient.objects.filter(
            barangay=barangay,
            prenatalcheckup__isnull=False,
            prenatalcheckup__checkup_date__gte=timezone.now() - timedelta(days=280)  # ~9 months
        ).distinct().count(),
        'emergency_alerts': EmergencyAlert.objects.filter(
            patient__barangay=barangay,
            status='ACTIVE'
        ).count()
    }

    # Get patients from this barangay with pagination
    patients = Patient.objects.filter(barangay=barangay).select_related('user')
    paginator = Paginator(patients, 10)
    page = request.GET.get('page')
    page_obj = paginator.get_page(page)

    context = {
        'barangay': barangay,
        'stats': stats,
        'page_obj': page_obj,
        'title': f'Barangay Details - {barangay.barangay_name}'
    }

    return render(request, 'rhu_management/barangay/barangay_detail.html', context)


@login_required(login_url='rhu_management:rhu_login')
@superuser_required
def barangay_add(request):
    """Add new barangay"""
    if request.method == 'POST':
        try:
            # Get form data
            username = request.POST.get('username')
            email = request.POST.get('email')
            password = request.POST.get('password')
            confirm_password = request.POST.get('confirm_password')
            barangay_name = request.POST.get('barangay_name')
            contact_number = request.POST.get('contact_number')

            # Validate passwords match
            if password != confirm_password:
                messages.error(request, 'Passwords do not match.')
                return render(request, 'rhu_management/barangay/barangay_add.html', {
                    'title': 'Add New Barangay',
                    'form_data': request.POST
                })

            # Check if username already exists
            if User.objects.filter(username=username).exists():
                messages.error(request, 'Username already exists.')
                return render(request, 'rhu_management/barangay/barangay_add.html', {
                    'title': 'Add New Barangay',
                    'form_data': request.POST
                })

            # Check if email already exists
            if User.objects.filter(email=email).exists():
                messages.error(request, 'Email already exists.')
                return render(request, 'rhu_management/barangay/barangay_add.html', {
                    'title': 'Add New Barangay',
                    'form_data': request.POST
                })

            # Check if contact number already exists
            if Barangay.objects.filter(contact_number=contact_number).exists():
                messages.error(request, 'Contact number already exists.')
                return render(request, 'rhu_management/barangay/barangay_add.html', {
                    'title': 'Add New Barangay',
                    'form_data': request.POST
                })

            with transaction.atomic():
                # Create user account
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password
                )

                # Create barangay
                barangay = Barangay.objects.create(
                    user=user,
                    barangay_name=barangay_name,
                    contact_number=contact_number
                )

                messages.success(request, f'Barangay {barangay.barangay_name} created successfully!')
                return redirect('rhu_management:barangay_list')

        except Exception as e:
            messages.error(request, f'Error creating barangay: {str(e)}')
            return render(request, 'rhu_management/barangay/barangay_add.html', {
                'title': 'Add New Barangay',
                'form_data': request.POST
            })

    return render(request, 'rhu_management/barangay/barangay_add.html', {
        'title': 'Add New Barangay'
    })


@login_required(login_url='rhu_management:rhu_login')
@superuser_required
def barangay_update(request, barangay_id):
    """Update barangay information"""
    barangay = get_object_or_404(Barangay, id=barangay_id)

    if request.method == 'POST':
        try:
            # Get form data
            barangay_name = request.POST.get('barangay_name')
            username = request.POST.get('username')
            email = request.POST.get('email')
            contact_number = request.POST.get('contact_number')
            password = request.POST.get('password')
            confirm_password = request.POST.get('confirm_password')

            # Validate username if changed
            if username != barangay.user.username:
                if User.objects.filter(username=username).exclude(id=barangay.user.id).exists():
                    messages.error(request, 'Username already exists.')
                    return render(request, 'rhu_management/barangay/barangay_update.html', {
                        'title': f'Update Barangay - {barangay.barangay_name}',
                        'barangay': barangay
                    })

            # Validate email if changed
            if email != barangay.user.email:
                if User.objects.filter(email=email).exclude(id=barangay.user.id).exists():
                    messages.error(request, 'Email already exists.')
                    return render(request, 'rhu_management/barangay/barangay_update.html', {
                        'title': f'Update Barangay - {barangay.barangay_name}',
                        'barangay': barangay
                    })

            # Validate contact number if changed
            if contact_number != barangay.contact_number:
                if Barangay.objects.filter(contact_number=contact_number).exclude(id=barangay.id).exists():
                    messages.error(request, 'Contact number already exists.')
                    return render(request, 'rhu_management/barangay/barangay_update.html', {
                        'title': f'Update Barangay - {barangay.barangay_name}',
                        'barangay': barangay
                    })

            # Validate passwords if provided
            if password:
                if password != confirm_password:
                    messages.error(request, 'Passwords do not match.')
                    return render(request, 'rhu_management/barangay/barangay_update.html', {
                        'title': f'Update Barangay - {barangay.barangay_name}',
                        'barangay': barangay
                    })

            with transaction.atomic():
                # Update user information
                user = barangay.user
                user.username = username
                user.email = email
                if password:
                    user.set_password(password)
                user.save()

                # Update barangay information
                barangay.barangay_name = barangay_name
                barangay.contact_number = contact_number
                barangay.save()

                messages.success(request, f'Barangay {barangay.barangay_name} updated successfully!')
                return redirect('rhu_management:barangay_list')

        except Exception as e:
            messages.error(request, f'Error updating barangay: {str(e)}')

    context = {
        'barangay': barangay,
        'title': f'Update Barangay - {barangay.barangay_name}'
    }

    return render(request, 'rhu_management/barangay/barangay_update.html', context)


@login_required(login_url='rhu_management:rhu_login')
@superuser_required
def patient_list(request):
    """Display list of all patients with barangay filtering and search"""
    # Get filter parameters
    search_query = request.GET.get('search', '')
    barangay_filter = request.GET.get('barangay', '')

    # Base query with related fields
    patients = Patient.objects.select_related('user', 'barangay').prefetch_related(
        models.Prefetch(
            'prenatalcheckup_set',
            queryset=PrenatalCheckup.objects.filter(
                Q(status='COMPLETED') |
                Q(status='SCHEDULED', checkup_date__gt=timezone.now())
            ).order_by('-checkup_date'),
            to_attr='checkups'
        )
    )

    # Apply barangay filter first
    if barangay_filter:
        try:
            barangay = Barangay.objects.get(id=barangay_filter)
            patients = patients.filter(barangay=barangay)
        except Barangay.DoesNotExist:
            messages.error(request, 'Selected barangay not found.')

    # Then apply search filter within the barangay results if any
    if search_query:
        patients = patients.filter(
            Q(user__first_name__icontains=search_query) |
            Q(user__last_name__icontains=search_query) |
            Q(contact_number__icontains=search_query)
        )

    # Get statistics
    stats = {
        'total_patients': Patient.objects.count(),
        'pregnant_patients': Patient.objects.filter(
            prenatalcheckup__isnull=False,
            prenatalcheckup__checkup_date__gte=timezone.now() - timedelta(days=280)  # ~9 months
        ).distinct().count(),
        'due_this_month': Patient.objects.filter(
            prenatalcheckup__last_menstrual_period__month=(
                    timezone.now() - timedelta(days=280)).month,  # ~9 months ago
            prenatalcheckup__status='SCHEDULED'
        ).distinct().count()
    }

    # Get all barangays for the filter dropdown
    barangays = Barangay.objects.all().order_by('barangay_name')

    # Pagination
    paginator = Paginator(patients.order_by('-created_at'), 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'barangay_filter': barangay_filter,
        'barangays': barangays,
        'stats': stats,
        'title': 'Patient List'
    }

    return render(request, 'rhu_management/patient/patient_list.html', context)


@login_required(login_url='rhu_management:rhu_login')
@superuser_required
def patient_detail(request, patient_id):
    patient = get_object_or_404(Patient, id=patient_id)

    # Get latest active checkup and calculate pregnancy progress
    latest_checkups = PrenatalCheckup.objects.filter(
        patient=patient,
        status='COMPLETED'
    ).order_by('-checkup_date')

    # Find the first checkup that hasn't passed its estimated delivery date
    latest_checkup = None
    current_week = None
    progress_percentage = None
    current_pregnancy = False
    today = timezone.now().date()

    for checkup in latest_checkups:
        if checkup.estimated_delivery_date and checkup.estimated_delivery_date >= today:
            latest_checkup = checkup
            current_pregnancy = True
            if checkup.last_menstrual_period:
                days_pregnant = max((today - checkup.last_menstrual_period).days, 0)
                current_week = min(days_pregnant // 7, 42)
                progress_percentage = min((current_week / 42) * 100, 100)
            break

    context = {
        'patient': patient,
        'latest_checkup': latest_checkup,
        'current_week': current_week,
        'progress_percentage': progress_percentage,
        'current_pregnancy': current_pregnancy,
        'checkups': PrenatalCheckup.objects.filter(patient=patient).order_by('-checkup_date')[:5],
        'upcoming_checkups': PrenatalCheckup.objects.filter(
            patient=patient,
            checkup_date__gte=timezone.now(),
            status='SCHEDULED'
        ).order_by('checkup_date'),
        'pregnancy_history': PregnancyHistory.objects.filter(patient=patient).order_by('-delivery_date'),
        'title': f'Patient Details - {patient.user.get_full_name()}'
    }

    return render(request, 'rhu_management/patient/patient_detail.html', context)


@login_required(login_url='rhu_management:rhu_login')
@superuser_required
def patient_add(request):
    """Handle new patient registration"""
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        contact_number = request.POST.get('contact_number')
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')

        # Validate passwords match
        if password != confirm_password:
            messages.error(request, 'Passwords do not match.')
            return redirect('rhu_management:patient_add')

        # Check if username already exists
        if User.objects.filter(username=username).exists():
            messages.error(request, 'Username already exists.')
            return redirect('rhu_management:patient_add')

        # Check if email already exists
        if User.objects.filter(email=email).exists():
            messages.error(request, 'Email already exists.')
            return redirect('rhu_management:patient_add')

        # Check if contact number already exists
        if Patient.objects.filter(contact_number=contact_number).exists():
            messages.error(request, 'Contact number already exists.')
            return redirect('rhu_management:patient_add')

        try:
            with transaction.atomic():
                # Create User account
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password,  # Use provided password instead of random
                    first_name=request.POST.get('first_name'),
                    last_name=request.POST.get('last_name')
                )

                # Create Patient profile
                patient = Patient.objects.create(
                    user=user,
                    contact_number=contact_number,
                    birth_date=datetime.strptime(request.POST.get('birth_date'), '%Y-%m-%d').date(),
                    sitio=request.POST.get('sitio'),
                    barangay=get_object_or_404(Barangay, id=request.POST.get('barangay')),
                    occupation=request.POST.get('occupation'),
                    monthly_income=request.POST.get('monthly_income'),
                    blood_type=request.POST.get('blood_type'),
                    religion=request.POST.get('religion'),
                    spouse_name=request.POST.get('spouse_name'),
                    spouse_occupation=request.POST.get('spouse_occupation'),
                    spouse_monthly_income=request.POST.get('spouse_monthly_income'),
                    number_of_children=request.POST.get('number_of_children'),
                    emergency_contact_name=request.POST.get('emergency_contact_name'),
                    emergency_contact_number=request.POST.get('emergency_contact_number')
                )

                messages.success(request, f'Patient {patient.user.get_full_name()} added successfully!')
                return redirect('rhu_management:patient_detail', patient_id=patient.id)

        except Exception as e:
            messages.error(request, f'Error adding patient: {str(e)}')

    context = {
        'barangays': Barangay.objects.all().order_by('barangay_name'),
        'blood_type_choices': Patient.BLOOD_TYPE_CHOICES,
        'religion_choices': Patient.RELIGION_CHOICES,
        'title': 'Add New Patient'
    }

    return render(request, 'rhu_management/patient/add_patient.html', context)


@login_required(login_url='rhu_management:rhu_login')
@superuser_required
def patient_update(request, patient_id):
    """Update existing patient information"""
    patient = get_object_or_404(Patient, id=patient_id)

    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        contact_number = request.POST.get('contact_number')
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')

        # Check if username already exists (excluding current patient)
        if User.objects.exclude(id=patient.user.id).filter(username=username).exists():
            messages.error(request, 'Username already exists.')
            return redirect('rhu_management:patient_update', patient_id=patient.id)

        # Check if email already exists (excluding current patient)
        if User.objects.exclude(id=patient.user.id).filter(email=email).exists():
            messages.error(request, 'Email already exists.')
            return redirect('rhu_management:patient_update', patient_id=patient.id)

        # Check if contact number already exists (excluding current patient)
        if Patient.objects.exclude(id=patient.id).filter(contact_number=contact_number).exists():
            messages.error(request, 'Contact number already exists.')
            return redirect('rhu_management:patient_update', patient_id=patient.id)

        # Validate passwords if provided
        if password:
            if password != confirm_password:
                messages.error(request, 'Passwords do not match.')
                return redirect('rhu_management:patient_update', patient_id=patient.id)

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

                # Add occupation and income fields
                patient.occupation = request.POST.get('occupation')
                patient.monthly_income = request.POST.get('monthly_income')

                # Add blood type and religion fields
                patient.blood_type = request.POST.get('blood_type')
                patient.religion = request.POST.get('religion')

                # Add family information fields
                patient.spouse_name = request.POST.get('spouse_name')
                patient.spouse_occupation = request.POST.get('spouse_occupation')
                patient.spouse_monthly_income = request.POST.get('spouse_monthly_income')
                patient.number_of_children = request.POST.get('number_of_children')

                # Emergency contact fields
                patient.emergency_contact_name = request.POST.get('emergency_contact_name')
                patient.emergency_contact_number = request.POST.get('emergency_contact_number')

                patient.save()

                messages.success(request, f'Patient {patient.user.get_full_name()} updated successfully!')
                return redirect('rhu_management:patient_detail', patient_id=patient.id)

        except Exception as e:
            messages.error(request, f'Error updating patient: {str(e)}')

    context = {
        'patient': patient,
        'barangays': Barangay.objects.all().order_by('barangay_name'),
        'blood_type_choices': Patient.BLOOD_TYPE_CHOICES,
        'religion_choices': Patient.RELIGION_CHOICES,
        'title': f'Edit Patient - {patient.user.get_full_name()}'
    }

    return render(request, 'rhu_management/patient/edit_patient.html', context)


# Utility functions
def get_available_time_slots(exclude_checkup=None):
    """Get available checkup time slots"""
    # Define clinic hours
    CLINIC_START_TIME = 8  # 8 AM
    CLINIC_END_TIME = 17  # 5 PM
    SLOT_DURATION = 30  # 30 minutes per slot

    # Get today's date
    today = timezone.now().date()

    # Generate time slots for next 30 days
    available_slots = []
    for day in range(30):
        date = today + timedelta(days=day)

        # Skip weekends
        if date.weekday() >= 5:
            continue

        # Generate slots for the day
        time = timezone.now().replace(
            hour=CLINIC_START_TIME,
            minute=0,
            second=0,
            microsecond=0
        )

        while time.hour < CLINIC_END_TIME:
            slot_datetime = timezone.make_aware(
                datetime.combine(date, time.time())
            )

            # Skip if slot is in the past
            if slot_datetime <= timezone.now():
                time += timedelta(minutes=SLOT_DURATION)
                continue

            # Check if slot is available
            is_available = not PrenatalCheckup.objects.filter(
                checkup_date=slot_datetime,
                status='SCHEDULED'
            ).exists()

            # Include slot if it's available or belongs to the checkup being edited
            if is_available or (
                    exclude_checkup and
                    exclude_checkup.checkup_date == slot_datetime
            ):
                available_slots.append({
                    'datetime': slot_datetime,
                    'date': date,
                    'time': time.strftime('%I:%M %p')
                })

            time += timedelta(minutes=SLOT_DURATION)

    return available_slots


@login_required(login_url='rhu_management:rhu_login')
@superuser_required
def checkup_list(request):
    """Display list of latest checkups per patient with filtering"""
    # Get filter parameters
    patient_filter = request.GET.get('patient')
    barangay_filter = request.GET.get('barangay')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    # Get the latest checkup for each patient using a subquery
    latest_checkups = PrenatalCheckup.objects.filter(
        patient=OuterRef('patient')
    ).order_by('-checkup_date')

    # Base queryset with distinct patients and their latest checkup
    checkups = PrenatalCheckup.objects.filter(
        id=Subquery(
            latest_checkups.values('id')[:1]
        )
    ).order_by('-checkup_date')  # Move order_by here after the filter

    # Apply filters
    if patient_filter:
        checkups = checkups.filter(patient_id=patient_filter)

    if barangay_filter:
        checkups = checkups.filter(patient__barangay_id=barangay_filter)

    if date_from:
        checkups = checkups.filter(checkup_date__gte=date_from)

    if date_to:
        checkups = checkups.filter(checkup_date__lte=date_to)

    # Get statistics
    stats = {
        'total_checkups': PrenatalCheckup.objects.count(),  # Total all checkups
        'today_checkups': PrenatalCheckup.objects.filter(
            checkup_date__date=timezone.now().date()
        ).count(),
        'this_week': PrenatalCheckup.objects.filter(
            checkup_date__gte=timezone.now().date() - timedelta(days=7)
        ).count(),
        'this_month': PrenatalCheckup.objects.filter(
            checkup_date__gte=timezone.now().date().replace(day=1)
        ).count()
    }

    # Pagination
    paginator = Paginator(checkups, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Get all patients and barangays for filters
    patients = Patient.objects.all().order_by('user__first_name', 'user__last_name')
    barangays = Barangay.objects.all().order_by('barangay_name')

    context = {
        'page_obj': page_obj,
        'stats': stats,
        'patients': patients,
        'barangays': barangays,
        'patient_filter': patient_filter,
        'barangay_filter': barangay_filter,
        'date_from': date_from,
        'date_to': date_to,
        'title': 'Checkup Records'
    }

    return render(request, 'rhu_management/checkup/checkup_list.html', context)


@login_required(login_url='rhu_management:rhu_login')
@superuser_required
def checkup_create(request, patient_id):
    """Record new checkup for a patient"""
    patient = get_object_or_404(Patient, id=patient_id)

    # Get previous checkup for reference
    previous_checkup = PrenatalCheckup.objects.filter(
        patient=patient
    ).order_by('-checkup_date').first()

    if request.method == 'POST':
        try:
            with transaction.atomic():
                # Determine if this is the initial record
                is_initial = not previous_checkup

                # Determine last menstrual period
                last_menstrual_period = request.POST.get('last_menstrual_period')
                if not last_menstrual_period and previous_checkup:
                    last_menstrual_period = previous_checkup.last_menstrual_period

                # Convert last_menstrual_period to date if it's a string
                if isinstance(last_menstrual_period, str):
                    last_menstrual_period = datetime.strptime(last_menstrual_period, '%Y-%m-%d').date()

                # Create checkup record with vital signs data
                checkup = PrenatalCheckup.objects.create(
                    patient=patient,
                    checkup_date=datetime.combine(
                        datetime.strptime(request.POST.get('checkup_date'), '%Y-%m-%d').date(),
                        datetime.strptime(request.POST.get('checkup_time'), '%H:%M').time()
                    ),
                    last_menstrual_period=last_menstrual_period,
                    notes=request.POST.get('notes', ''),
                    status='SCHEDULED',
                    is_initial_record=is_initial,
                    
                    # Basic Measurements
                    weight=request.POST.get('weight'),
                    height=request.POST.get('height'),
                    blood_pressure=request.POST.get('blood_pressure'),
                    age_of_gestation=request.POST.get('age_of_gestation'),
                    
                    # Status & Planning
                    nutritional_status=request.POST.get('nutritional_status'),
                    birth_plan_status=request.POST.get('birth_plan_status'),
                    dental_checkup_status=request.POST.get('dental_checkup_status'),
                    dental_checkup_date=request.POST.get('dental_checkup_date') or None,
                    
                    # Laboratory Tests
                    hemoglobin_count=request.POST.get('hemoglobin_count') or None,
                    urinalysis_date=request.POST.get('urinalysis_date') or None,
                    cbc_date=request.POST.get('cbc_date') or None,
                    stool_exam_date=request.POST.get('stool_exam_date') or None,
                    
                    # STI Tests
                    syphilis_test_date=request.POST.get('syphilis_test_date') or None,
                    syphilis_result=request.POST.get('syphilis_result'),
                    hiv_test_date=request.POST.get('hiv_test_date') or None,
                    hiv_result=request.POST.get('hiv_result'),
                    hepatitis_b_test_date=request.POST.get('hepatitis_b_test_date') or None,
                    hepatitis_b_result=request.POST.get('hepatitis_b_result'),
                    
                    # Treatments
                    tetanus_vaccine_date=request.POST.get('tetanus_vaccine_date') or None,
                    syphilis_treatment=request.POST.get('syphilis_treatment'),
                    arv_treatment=request.POST.get('arv_treatment'),
                    bacteriuria_treatment=request.POST.get('bacteriuria_treatment'),
                    anemia_treatment=request.POST.get('anemia_treatment')
                )

                # Send SMS notification
                api_url = "https://api.semaphore.co/api/v4/messages"
                message = (
                    f"RHU KABACAN NOTIFICATION!\n\n"
                    f"Dear {patient.user.first_name},\n\n"
                    f"Your prenatal checkup is scheduled on "
                    f"{checkup.checkup_date.strftime('%B %d, %Y')} ({checkup.checkup_date.strftime('%A')}) "
                    f"at {checkup.checkup_date.strftime('%I:%M %p')}.\n"
                    f"Please bring your prenatal record book.\n\n"
                    f"For any concerns, please contact us at {settings.RHU_CONTACT_NUMBER}. THANK YOU!"
                )
                
                payload = {
                    'apikey': settings.SEMAPHORE_API_KEY,
                    'number': patient.contact_number,
                    'message': message,
                    'sendername': settings.SEMAPHORE_SENDER_NAME
                }
                
                try:
                    response = requests.post(api_url, data=payload)
                    response.raise_for_status()
                    messages.success(request, 'Checkup record added and SMS reminder sent successfully!')
                except Exception as sms_error:
                    print(f"Error sending SMS: {str(sms_error)}")
                    messages.success(request, 'Checkup record added successfully!')
                    messages.warning(request, 'Failed to send SMS reminder.')

                return redirect('rhu_management:checkup_detail', checkup.id)

        except Exception as e:
            messages.error(request, f'Error adding checkup record: {str(e)}')
            return redirect('rhu_management:checkup_create', patient_id=patient_id)

    context = {
        'patient': patient,
        'previous_checkup': previous_checkup,
        'latest_vitals': PrenatalCheckup.objects.filter(patient=patient).order_by('-checkup_date').first(),  # Changed from recorded_at to checkup_date
        'birth_plan_choices': PrenatalCheckup.BIRTH_PLAN_STATUS,
        'dental_checkup_choices': PrenatalCheckup.DENTAL_CHECKUP_STATUS,
        'nutritional_status_choices': PrenatalCheckup.NUTRITIONAL_STATUS_CHOICES,
        'title': f'New Checkup - {patient.user.get_full_name()}'
    }

    return render(request, 'rhu_management/checkup/create_checkup.html', context)


@login_required(login_url='rhu_management:rhu_login')
@superuser_required
def checkup_detail(request, checkup_id):
    """Display detailed checkup information"""
    checkup = get_object_or_404(PrenatalCheckup, id=checkup_id)

    # Calculate pregnancy week and progress
    weeks_pregnant = None
    progress_percentage = None
    if checkup.last_menstrual_period:
        days_pregnant = (timezone.now().date() - checkup.last_menstrual_period).days
        weeks_pregnant = min(days_pregnant // 7, 42)
        progress_percentage = min((weeks_pregnant / 42) * 100, 100)

    # Get previous checkup and calculate changes
    previous_checkup = PrenatalCheckup.objects.filter(
        patient=checkup.patient,
        checkup_date__lt=checkup.checkup_date
    ).order_by('-checkup_date').first()

    # Calculate changes if previous checkup exists
    changes = {}
    if previous_checkup:
        # Weight change
        if checkup.weight and previous_checkup.weight:
            weight_diff = float(checkup.weight) - float(previous_checkup.weight)
            changes['weight'] = {
                'diff': round(weight_diff, 2),
                'increased': weight_diff > 0
            }

        # Blood pressure change
        if checkup.blood_pressure != previous_checkup.blood_pressure:
            changes['blood_pressure'] = True

        # Status changes
        if checkup.nutritional_status != previous_checkup.nutritional_status:
            changes['nutritional_status'] = True
            
        if checkup.birth_plan_status != previous_checkup.birth_plan_status:
            changes['birth_plan_status'] = True
            
        if checkup.dental_checkup_status != previous_checkup.dental_checkup_status:
            changes['dental_checkup_status'] = True

        # Treatment changes
        if checkup.syphilis_treatment != previous_checkup.syphilis_treatment:
            changes['syphilis_treatment'] = True
            
        if checkup.arv_treatment != previous_checkup.arv_treatment:
            changes['arv_treatment'] = True
            
        if checkup.bacteriuria_treatment != previous_checkup.bacteriuria_treatment:
            changes['bacteriuria_treatment'] = True
            
        if checkup.anemia_treatment != previous_checkup.anemia_treatment:
            changes['anemia_treatment'] = True

        # Height change
        if checkup.height and previous_checkup.height:
            height_diff = float(checkup.height) - float(previous_checkup.height)
            changes['height'] = {
                'diff': round(height_diff, 2),
                'increased': height_diff > 0
            }

        # Age of gestation change
        if checkup.age_of_gestation != previous_checkup.age_of_gestation:
            changes['age_of_gestation'] = True

        # Laboratory test changes
        if checkup.hemoglobin_count != previous_checkup.hemoglobin_count:
            changes['hemoglobin_count'] = True
        if checkup.urinalysis_date != previous_checkup.urinalysis_date:
            changes['urinalysis_date'] = True
        if checkup.cbc_date != previous_checkup.cbc_date:
            changes['cbc_date'] = True
        if checkup.stool_exam_date != previous_checkup.stool_exam_date:
            changes['stool_exam_date'] = True

        # STI test changes
        if checkup.syphilis_test_date != previous_checkup.syphilis_test_date:
            changes['syphilis_test_date'] = True
        if checkup.syphilis_result != previous_checkup.syphilis_result:
            changes['syphilis_result'] = True
        if checkup.hiv_test_date != previous_checkup.hiv_test_date:
            changes['hiv_test_date'] = True
        if checkup.hiv_result != previous_checkup.hiv_result:
            changes['hiv_result'] = True
        if checkup.hepatitis_b_test_date != previous_checkup.hepatitis_b_test_date:
            changes['hepatitis_b_test_date'] = True
        if checkup.hepatitis_b_result != previous_checkup.hepatitis_b_result:
            changes['hepatitis_b_result'] = True

        # Vaccine changes
        if checkup.tetanus_vaccine_date != previous_checkup.tetanus_vaccine_date:
            changes['tetanus_vaccine_date'] = True

        # Dental checkup date change
        if checkup.dental_checkup_date != previous_checkup.dental_checkup_date:
            changes['dental_checkup_date'] = True

    # Get next checkup
    next_checkup = PrenatalCheckup.objects.filter(
        patient=checkup.patient,
        checkup_date__gt=checkup.checkup_date
    ).order_by('checkup_date').first()

    context = {
        'checkup': checkup,
        'weeks_pregnant': weeks_pregnant,
        'progress_percentage': progress_percentage,
        'previous_checkup': previous_checkup,
        'next_checkup': next_checkup,
        'changes': changes,
        'title': f'Checkup Details - {checkup.patient.user.get_full_name()}'
    }

    return render(request, 'rhu_management/checkup/checkup_detail.html', context)


@login_required(login_url='rhu_management:rhu_login')
@superuser_required
def checkup_update(request, checkup_id):
    """Update existing checkup record"""
    checkup = get_object_or_404(PrenatalCheckup, id=checkup_id)

    if request.method == 'POST':
        try:
            with transaction.atomic():
                # Update checkup details
                checkup_date = datetime.strptime(request.POST.get('checkup_date'), '%Y-%m-%d').date()
                checkup_time = datetime.strptime(request.POST.get('checkup_time'), '%H:%M').time()
                checkup.checkup_date = datetime.combine(checkup_date, checkup_time)
                checkup.status = request.POST.get('status')
                checkup.notes = request.POST.get('notes', '')
                
                # Update vital signs data
                checkup.weight = request.POST.get('weight')
                checkup.height = request.POST.get('height')
                checkup.blood_pressure = request.POST.get('blood_pressure')
                checkup.age_of_gestation = request.POST.get('age_of_gestation')
                
                # Status & Planning
                checkup.nutritional_status = request.POST.get('nutritional_status')
                checkup.birth_plan_status = request.POST.get('birth_plan_status')
                checkup.dental_checkup_status = request.POST.get('dental_checkup_status')
                checkup.dental_checkup_date = request.POST.get('dental_checkup_date') or None
                
                # Laboratory Tests
                checkup.hemoglobin_count = request.POST.get('hemoglobin_count')
                checkup.urinalysis_date = request.POST.get('urinalysis_date') or None
                checkup.cbc_date = request.POST.get('cbc_date') or None
                checkup.stool_exam_date = request.POST.get('stool_exam_date') or None
                
                # STI Tests
                checkup.syphilis_test_date = request.POST.get('syphilis_test_date') or None
                checkup.syphilis_result = request.POST.get('syphilis_result')
                checkup.hiv_test_date = request.POST.get('hiv_test_date') or None
                checkup.hiv_result = request.POST.get('hiv_result')
                checkup.hepatitis_b_test_date = request.POST.get('hepatitis_b_test_date') or None
                checkup.hepatitis_b_result = request.POST.get('hepatitis_b_result')
                
                # Treatments
                checkup.tetanus_vaccine_date = request.POST.get('tetanus_vaccine_date') or None
                checkup.syphilis_treatment = request.POST.get('syphilis_treatment')
                checkup.arv_treatment = request.POST.get('arv_treatment')
                checkup.bacteriuria_treatment = request.POST.get('bacteriuria_treatment')
                checkup.anemia_treatment = request.POST.get('anemia_treatment')
                
                checkup.save()

                messages.success(request, 'Checkup record updated successfully!')
                return redirect('rhu_management:checkup_detail', checkup_id=checkup.id)

        except Exception as e:
            messages.error(request, f'Error updating checkup record: {str(e)}')

    context = {
        'checkup': checkup,
        'status_choices': PrenatalCheckup.STATUS_CHOICES,
        'birth_plan_choices': PrenatalCheckup.BIRTH_PLAN_STATUS,
        'dental_checkup_choices': PrenatalCheckup.DENTAL_CHECKUP_STATUS,
        'nutritional_status_choices': PrenatalCheckup.NUTRITIONAL_STATUS_CHOICES,
        'title': f'Edit Checkup - {checkup.patient.user.get_full_name()}'
    }

    return render(request, 'rhu_management/checkup/edit_checkup.html', context)


@cache_page(60 * 5)  # Cache for 5 minutes
@login_required(login_url='rhu_management:rhu_login')
@superuser_required
def emergency_list(request):
    """Display list of all emergency alerts with filters"""
    # Get filter parameters with defaults
    status_filter = request.GET.get('status', '')
    barangay_filter = request.GET.get('barangay', '')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    
    # Base query with select_related and only needed fields
    alerts = EmergencyAlert.objects.select_related(
        'patient',
        'patient__user',
        'patient__barangay'
    ).only(
        'id', 'status', 'alert_time', 'response_time', 'resolved_time', 'location',
        'patient__contact_number', 'patient__sitio',
        'patient__user__first_name', 'patient__user__last_name',
        'patient__barangay__barangay_name'
    )

    # Apply filters
    if status_filter:
        alerts = alerts.filter(status=status_filter)
    if barangay_filter:
        alerts = alerts.filter(patient__barangay_id=barangay_filter)
    if date_from:
        alerts = alerts.filter(alert_time__date__gte=date_from)
    if date_to:
        alerts = alerts.filter(alert_time__date__lte=date_to)

    # Get active alerts with pagination
    active_alerts = alerts.filter(status='ACTIVE').order_by('-alert_time')
    active_paginator = Paginator(active_alerts, 6)  # Show 6 active alerts per page
    active_page = request.GET.get('active_page', 1)
    active_page_obj = active_paginator.get_page(active_page)

    # Get in-progress alerts with pagination
    in_progress_alerts = alerts.filter(
        status__in=['RESPONDED', 'EN_ROUTE']
    ).order_by('-alert_time')
    in_progress_paginator = Paginator(in_progress_alerts, 10)
    in_progress_page = request.GET.get('in_progress_page', 1)
    in_progress_page_obj = in_progress_paginator.get_page(in_progress_page)

    # Get recent alerts with pagination
    recent_alerts = alerts.order_by('-alert_time')
    recent_paginator = Paginator(recent_alerts, 10)
    recent_page = request.GET.get('recent_page', 1)
    recent_page_obj = recent_paginator.get_page(recent_page)

    # Use database aggregation for statistics
    from django.db.models import Count
    today = timezone.now().date()

    stats = EmergencyAlert.objects.aggregate(
        active_alerts=Count('id', filter=models.Q(status='ACTIVE')),
        in_progress=Count('id', filter=models.Q(status__in=['RESPONDED', 'EN_ROUTE'])),
        resolved_today=Count('id', filter=models.Q(
            status='RESOLVED',
            resolved_time__date=today
        ))
    )

    # Calculate average response time efficiently
    avg_response_time = EmergencyAlert.objects.filter(
        status='RESOLVED',
        response_time__isnull=False,
        alert_time__isnull=False
    ).exclude(
        status='CANCELLED'
    ).order_by('-alert_time')[:100].aggregate(
        avg_time=models.Avg(
            models.F('response_time') - models.F('alert_time')
        )
    )['avg_time']

    if avg_response_time:
        stats['average_response_time'] = avg_response_time.total_seconds() / 60
    else:
        stats['average_response_time'] = 0

    context = {
        'active_page_obj': active_page_obj,
        'in_progress_page_obj': in_progress_page_obj,
        'recent_page_obj': recent_page_obj,
        'stats': stats,
        'status_choices': EmergencyAlert.STATUS_CHOICES,
        'barangays': Barangay.objects.values('id', 'barangay_name'),
        'status_filter': status_filter,
        'barangay_filter': barangay_filter,
        'date_from': date_from,
        'date_to': date_to,
        'title': 'Emergency Alerts'
    }

    return render(request, 'rhu_management/emergency/emergency_list.html', context)


@login_required(login_url='rhu_management:rhu_login')
@superuser_required
def emergency_respond(request, alert_id):
    """Handle emergency response actions"""
    alert = get_object_or_404(EmergencyAlert, id=alert_id)

    if request.method == 'POST':
        try:
            with transaction.atomic():
                # Get new status from form
                new_status = request.POST.get('status')
                current_time = timezone.now()

                # Update alert status
                alert.status = new_status

                # Record timestamps based on status
                if new_status == 'RESPONDED' and not alert.response_time:
                    alert.response_time = current_time
                elif new_status == 'RESOLVED' and not alert.resolved_time:
                    alert.resolved_time = current_time

                # Save notes if provided
                if request.POST.get('notes'):
                    alert.notes = f"{alert.notes}\n[{current_time.strftime('%Y-%m-%d %H:%M')}] {request.POST.get('notes')}"

                alert.save()

                # Send SMS notification based on status
                api_url = "https://api.semaphore.co/api/v4/messages"
                
                # Define status-specific messages
                if new_status == 'RESPONDED':
                    message = (
                        f"EMERGENCY ALERT UPDATE!\n\n"
                        f"Dear {alert.patient.user.first_name},\n\n"
                        f"RHU Kabacan has received your emergency alert and is coordinating response. "
                        f"Our medical team will contact you shortly.\n\n"
                        f"Stay calm and keep your phone line open.\n"
                        f"Emergency Hotline: {settings.RHU_CONTACT_NUMBER}"
                    )
                elif new_status == 'EN_ROUTE':
                    message = (
                        f"EMERGENCY ALERT UPDATE!\n\n"
                        f"Dear {alert.patient.user.first_name},\n\n"
                        f"Our medical response team is now en route to your location. "
                        f"Please ensure your location is accessible.\n\n"
                        f"Keep your phone line open for updates.\n"
                        f"Emergency Hotline: {settings.RHU_CONTACT_NUMBER}"
                    )
                elif new_status == 'RESOLVED':
                    message = (
                        f"EMERGENCY ALERT UPDATE!\n\n"
                        f"Dear {alert.patient.user.first_name},\n\n"
                        f"Your emergency alert has been resolved. "
                        f"Please don't hesitate to reach out if you need further assistance.\n\n"
                        f"Take care and stay healthy!\n"
                        f"RHU Kabacan Hotline: {settings.RHU_CONTACT_NUMBER}"
                    )

                # Send SMS
                payload = {
                    'apikey': settings.SEMAPHORE_API_KEY,
                    'number': alert.patient.contact_number,
                    'message': message,
                    'sendername': settings.SEMAPHORE_SENDER_NAME
                }

                try:
                    response = requests.post(api_url, data=payload)
                    response.raise_for_status()
                    messages.success(request, f'Emergency alert updated and notification sent successfully!')
                except Exception as sms_error:
                    print(f"Error sending SMS: {str(sms_error)}")
                    messages.success(request, 'Emergency alert updated successfully!')
                    messages.warning(request, 'Failed to send status update notification.')

                return redirect('rhu_management:emergency_list')

        except Exception as e:
            messages.error(request, 'Error updating emergency alert.')

    return redirect('rhu_management:emergency_list')


@login_required(login_url='rhu_management:rhu_login')
@superuser_required
def emergency_detail(request, alert_id):
    """Display detailed emergency alert information"""
    alert = get_object_or_404(EmergencyAlert, id=alert_id)

    # Calculate response times if available
    response_time = None
    resolution_time = None

    if alert.response_time:
        response_time = (alert.response_time - alert.alert_time).total_seconds() // 60

    if alert.resolved_time and alert.response_time:
        resolution_time = (alert.resolved_time - alert.response_time).total_seconds() // 60

    context = {
        'alert': alert,
        'response_time': response_time,
        'resolution_time': resolution_time,
        'title': f'Emergency Alert Details - {alert.patient.user.get_full_name()}'
    }

    return render(request, 'rhu_management/emergency/emergency_detail.html', context)


# Utility Functions
def calculate_average_response_time():
    """Calculate average response time for resolved alerts"""
    resolved_alerts = EmergencyAlert.objects.filter(
        status='RESOLVED',
        response_time__isnull=False
    )

    if not resolved_alerts.exists():
        return None

    total_response_time = 0
    count = 0

    for alert in resolved_alerts:
        response_time = (alert.response_time - alert.alert_time).total_seconds()
        total_response_time += response_time
        count += 1

    return total_response_time / count / 60  # Convert to minutes


def get_status_notification_message(status):
    """Get notification message based on alert status"""
    messages = {
        'RESPONDED': f'Emergency response team has been notified. RHU is coordinating the response.',
        'EN_ROUTE': f'Emergency response team is on the way. RHU is leading the response.',
        'RESOLVED': f'Emergency has been resolved. Thank you for using our emergency alert system.',
        'CANCELLED': 'Emergency alert has been cancelled.'
    }
    return messages.get(status, 'Emergency alert status has been updated.')


def send_sms(phone_number, message):
    """Implement SMS sending logic"""
    # Integrate with your SMS service provider
    pass


def send_email(email, subject, message):
    """Implement email sending logic"""
    # Implement using Django's email functionality
    pass


@login_required(login_url='rhu_management:rhu_login')
@superuser_required
def reports_dashboard(request):
    """Display reports dashboard with overview and quick stats"""
    # Get date range for statistics
    end_date = timezone.now()
    start_date = end_date - timedelta(days=30)

    # Calculate general statistics
    stats = {
        'total_patients': Patient.objects.all().count(),
        'new_patients': Patient.objects.filter(
            created_at__gte=start_date
        ).count(),
        'total_checkups': PrenatalCheckup.objects.filter(
            checkup_date__gte=start_date
        ).count(),
        'emergency_alerts': EmergencyAlert.objects.filter(
            alert_time__gte=start_date
        ).count()
    }

    # Get recent reports
    recent_reports = RHUReport.objects.all().order_by('-created_at')[:5]

    # Get monthly trends
    monthly_trends = get_monthly_trends()

    context = {
        'stats': stats,
        'recent_reports': recent_reports,
        'monthly_trends': monthly_trends,
        'title': 'Reports Dashboard'
    }

    return render(request, 'rhu_management/report/report_dashboard.html', context)


@login_required(login_url='rhu_management:rhu_login')
@login_required(login_url='rhu_management:rhu_login')
@superuser_required
def generate_report(request):
    """Handle report generation with custom parameters"""
    if request.method == 'POST':
        try:
            report_type = request.POST.get('report_type')
            start_date = datetime.strptime(request.POST.get('start_date'), '%Y-%m-%d').date()
            end_date = datetime.strptime(request.POST.get('end_date'), '%Y-%m-%d').date()

            # Generate report based on type
            if report_type == 'DAILY':
                report_data = generate_daily_report(start_date, end_date)
            elif report_type == 'WEEKLY':
                report_data = generate_weekly_report(start_date, end_date)
            elif report_type == 'MONTHLY':
                report_data = generate_monthly_report(start_date, end_date)
            elif report_type == 'QUARTERLY':
                report_data = generate_quarterly_report(start_date, end_date)
            elif report_type == 'ANNUAL':
                report_data = generate_annual_report(start_date, end_date)
            elif report_type == 'CUSTOM':
                report_data = generate_custom_report(
                    start_date,
                    end_date,
                    request.POST.getlist('metrics')
                )

            # Generate summary
            summary = generate_summary(report_data, report_type, start_date, end_date)

            # Create report
            report = RHUReport.objects.create(
                title=request.POST.get('title'),
                type=report_type,
                period_start=start_date,
                period_end=end_date,
                content=report_data,
                summary=summary
            )

            messages.success(request, 'Report generated successfully!')
            return redirect('rhu_management:reports_dashboard')

        except Exception as e:
            messages.error(request, f'Error generating report: {str(e)}')
            return redirect('rhu_management:generate_report')

    context = {
        'report_types': RHUReport.REPORT_TYPES,
        'metrics': get_available_metrics(),
        'title': 'Generate Report'
    }

    return render(request, 'rhu_management/report/generate_report.html', context)


def get_available_metrics():
    """Return available metrics for custom reports"""
    return [
        {'id': 'patients', 'name': 'Patient Statistics'},
        {'id': 'checkups', 'name': 'Checkup Analytics'},
        {'id': 'emergencies', 'name': 'Emergency Alerts'},
        {'id': 'notifications', 'name': 'Notification Stats'}
    ]


def generate_summary(report_data, report_type, start_date, end_date):
    """Generate a text summary of the report"""
    summary_lines = [
        f"Report Period: {start_date.strftime('%B %d, %Y')} to {end_date.strftime('%B %d, %Y')}",
        f"Report Type: {dict(RHUReport.REPORT_TYPES)[report_type]}"
    ]

    return "\n".join(summary_lines)


def generate_daily_report(start_date, end_date):
    """Generate daily activity report"""
    data = {
        'metadata': {
            'report_type': 'Daily Report',
            'period': f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}",
            'generated_at': timezone.now().strftime('%Y-%m-%d %H:%M:%S')
        },
        'statistics': {
            'total_patients': Patient.objects.filter(
                created_at__date__gte=start_date,
                created_at__date__lte=end_date
            ).count(),
            'total_checkups': PrenatalCheckup.objects.filter(
                checkup_date__gte=start_date,
                checkup_date__lte=end_date
            ).count(),
            'total_emergencies': EmergencyAlert.objects.filter(
                alert_time__gte=start_date,
                alert_time__lte=end_date
            ).count()
        },
        'daily_breakdown': []
    }

    current_date = start_date
    while current_date <= end_date:
        next_date = current_date + timedelta(days=1)
        daily_data = {
            'date': current_date.strftime('%Y-%m-%d'),
            'metrics': {
                'patients': Patient.objects.filter(
                    created_at__gte=current_date,
                    created_at__lt=next_date
                ).count(),
                'checkups': PrenatalCheckup.objects.filter(
                    checkup_date__gte=current_date,
                    checkup_date__lt=next_date
                ).count(),
                'emergencies': EmergencyAlert.objects.filter(
                    alert_time__gte=current_date,
                    alert_time__lt=next_date
                ).count()
            }
        }
        data['daily_breakdown'].append(daily_data)
        current_date = next_date

    return data


def generate_weekly_report(start_date, end_date):
    """Generate weekly activity report"""
    data = {
        'metadata': {
            'report_type': 'Weekly Report',
            'period': f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}",
            'generated_at': timezone.now().strftime('%Y-%m-%d %H:%M:%S')
        },
        'statistics': {
            'total_patients': Patient.objects.filter(
                created_at__gte=start_date,
                created_at__lte=end_date
            ).count(),
            'total_checkups': PrenatalCheckup.objects.filter(
                checkup_date__gte=start_date,
                checkup_date__lte=end_date
            ).count(),
            'total_emergencies': EmergencyAlert.objects.filter(
                alert_time__gte=start_date,
                alert_time__lte=end_date
            ).count()
        },
        'weekly_breakdown': []
    }

    current_date = start_date
    while current_date <= end_date:
        week_end = min(current_date + timedelta(days=6), end_date)
        next_date = week_end + timedelta(days=1)

        weekly_data = {
            'week': f"Week {current_date.strftime('%Y-%m-%d')} to {week_end.strftime('%Y-%m-%d')}",
            'metrics': {
                'patients': Patient.objects.filter(
                    created_at__gte=current_date,
                    created_at__lt=next_date
                ).count(),
                'checkups': PrenatalCheckup.objects.filter(
                    checkup_date__gte=current_date,
                    checkup_date__lt=next_date
                ).count(),
                'emergencies': EmergencyAlert.objects.filter(
                    alert_time__gte=current_date,
                    alert_time__lt=next_date
                ).count()
            }
        }
        data['weekly_breakdown'].append(weekly_data)
        current_date = next_date

    return data


def generate_monthly_report(start_date, end_date):
    """Generate monthly activity report"""
    data = {
        'metadata': {
            'report_type': 'Monthly Report',
            'period': f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}",
            'generated_at': timezone.now().strftime('%Y-%m-%d %H:%M:%S')
        },
        'statistics': {
            'total_patients': Patient.objects.filter(
                created_at__gte=start_date,
                created_at__lte=end_date
            ).count(),
            'total_checkups': PrenatalCheckup.objects.filter(
                checkup_date__gte=start_date,
                checkup_date__lte=end_date
            ).count(),
            'total_emergencies': EmergencyAlert.objects.filter(
                alert_time__gte=start_date,
                alert_time__lte=end_date
            ).count()
        },
        'monthly_breakdown': []
    }

    current_date = start_date.replace(day=1)
    while current_date <= end_date:
        # Get last day of current month
        if current_date.month == 12:
            month_end = current_date.replace(day=31)
        else:
            month_end = current_date.replace(month=current_date.month + 1, day=1) - timedelta(days=1)

        month_end = min(month_end, end_date)
        next_date = month_end + timedelta(days=1)

        monthly_data = {
            'month': current_date.strftime('%B %Y'),
            'metrics': {
                'patients': Patient.objects.filter(
                    created_at__gte=current_date,
                    created_at__lt=next_date
                ).count(),
                'checkups': PrenatalCheckup.objects.filter(
                    checkup_date__gte=current_date,
                    checkup_date__lt=next_date
                ).count(),
                'emergencies': EmergencyAlert.objects.filter(
                    alert_time__gte=current_date,
                    alert_time__lt=next_date
                ).count()
            }
        }
        data['monthly_breakdown'].append(monthly_data)

        # Move to first day of next month
        if current_date.month == 12:
            current_date = current_date.replace(year=current_date.year + 1, month=1)
        else:
            current_date = current_date.replace(month=current_date.month + 1)

    return data



def generate_quarterly_report(start_date, end_date):
    """Generate quarterly activity report"""
    data = {
        'metadata': {
            'report_type': 'Quarterly Report',
            'period': f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}",
            'generated_at': timezone.now().strftime('%Y-%m-%d %H:%M:%S')
        },
        'statistics': {
            'total_patients': Patient.objects.filter(
                created_at__gte=start_date,
                created_at__lte=end_date
            ).count(),
            'total_checkups': PrenatalCheckup.objects.filter(
                checkup_date__gte=start_date,
                checkup_date__lte=end_date
            ).count(),
            'total_emergencies': EmergencyAlert.objects.filter(
                alert_time__gte=start_date,
                alert_time__lte=end_date
            ).count()
        },
        'quarterly_breakdown': []
    }

    # Function to get quarter start month
    def get_quarter_start_month(month):
        return ((month - 1) // 3) * 3 + 1

    current_date = start_date.replace(month=get_quarter_start_month(start_date.month), day=1)
    while current_date <= end_date:
        # Calculate quarter end
        quarter_end_month = min(current_date.month + 2, 12)
        if quarter_end_month == 12:
            quarter_end = current_date.replace(month=12, day=31)
        else:
            quarter_end = current_date.replace(month=quarter_end_month + 1, day=1) - timedelta(days=1)

        quarter_end = min(quarter_end, end_date)
        next_date = quarter_end + timedelta(days=1)

        # Calculate quarter number (Q1, Q2, Q3, Q4)
        quarter_num = (current_date.month - 1) // 3 + 1

        quarterly_data = {
            'quarter': f"Q{quarter_num} {current_date.year}",
            'metrics': {
                'patients': Patient.objects.filter(
                    created_at__gte=current_date,
                    created_at__lt=next_date
                ).count(),
                'checkups': PrenatalCheckup.objects.filter(
                    checkup_date__gte=current_date,
                    checkup_date__lt=next_date
                ).count(),
                'emergencies': EmergencyAlert.objects.filter(
                    alert_time__gte=current_date,
                    alert_time__lt=next_date
                ).count()
            }
        }
        data['quarterly_breakdown'].append(quarterly_data)

        # Move to next quarter
        if current_date.month >= 10:  # If current quarter is Q4
            current_date = current_date.replace(year=current_date.year + 1, month=1)
        else:
            current_date = current_date.replace(month=current_date.month + 3)

    return data


def generate_annual_report(start_date, end_date):
    """Generate annual activity report"""
    data = {
        'metadata': {
            'report_type': 'Annual Report',
            'period': f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}",
            'generated_at': timezone.now().strftime('%Y-%m-%d %H:%M:%S')
        },
        'statistics': {
            'total_patients': Patient.objects.filter(
                created_at__gte=start_date,
                created_at__lte=end_date
            ).count(),
            'total_checkups': PrenatalCheckup.objects.filter(
                checkup_date__gte=start_date,
                checkup_date__lte=end_date
            ).count(),
            'total_emergencies': EmergencyAlert.objects.filter(
                alert_time__gte=start_date,
                alert_time__lte=end_date
            ).count()
        },
        'yearly_breakdown': []
    }

    current_date = start_date.replace(month=1, day=1)
    while current_date <= end_date:
        year_end = current_date.replace(month=12, day=31)
        year_end = min(year_end, end_date)
        next_date = year_end + timedelta(days=1)

        yearly_data = {
            'year': current_date.year,
            'metrics': {
                'patients': Patient.objects.filter(
                    created_at__gte=current_date,
                    created_at__lt=next_date
                ).count(),
                'checkups': PrenatalCheckup.objects.filter(
                    checkup_date__gte=current_date,
                    checkup_date__lt=next_date
                ).count(),
                'emergencies': EmergencyAlert.objects.filter(
                    alert_time__gte=current_date,
                    alert_time__lt=next_date
                ).count()
            }
        }
        data['yearly_breakdown'].append(yearly_data)
        current_date = current_date.replace(year=current_date.year + 1)

    return data


def generate_custom_report(start_date, end_date, metrics):
    """Generate custom report based on selected metrics"""
    data = {
        'metadata': {
            'report_type': 'Custom Report',
            'period': f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}",
            'generated_at': timezone.now().strftime('%Y-%m-%d %H:%M:%S'),
            'selected_metrics': metrics
        },
        'statistics': {}
    }

    if 'patients' in metrics:
        data['statistics']['patients'] = {
            'total': Patient.objects.filter(
                created_at__gte=start_date,
                created_at__lte=end_date
            ).count(),
            'active': Patient.objects.filter(
                created_at__gte=start_date,
                created_at__lte=end_date,
                is_active=True
            ).count()
        }

    if 'checkups' in metrics:
        data['statistics']['checkups'] = {
            'total': PrenatalCheckup.objects.filter(
                checkup_date__gte=start_date,
                checkup_date__lte=end_date
            ).count(),
            'normal': PrenatalCheckup.objects.filter(
                checkup_date__gte=start_date,
                checkup_date__lte=end_date,
                status='NORMAL'
            ).count(),
            'high_risk': PrenatalCheckup.objects.filter(
                checkup_date__gte=start_date,
                checkup_date__lte=end_date,
                status='HIGH_RISK'
            ).count()
        }

    if 'emergencies' in metrics:
        data['statistics']['emergencies'] = {
            'total': EmergencyAlert.objects.filter(
                alert_time__gte=start_date,
                alert_time__lte=end_date
            ).count(),
            'resolved': EmergencyAlert.objects.filter(
                alert_time__gte=start_date,
                alert_time__lte=end_date,
                status='RESOLVED'
            ).count()
        }

    return data


def export_report(report):
    """Generate and export report as PDF"""
    try:
        # Create reports directory if it doesn't exist
        reports_dir = '/tmp/reports' if os.path.exists('/tmp') else os.path.join(settings.MEDIA_ROOT, 'reports')
        os.makedirs(reports_dir, exist_ok=True)

        # Generate unique filename
        filename = f'report_{report.id}_{int(time.time())}.pdf'
        filepath = os.path.join(reports_dir, filename)

        # Create the PDF document
        doc = SimpleDocTemplate(
            filepath,
            pagesize=letter,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=72
        )

        # Styles
        styles = getSampleStyleSheet()
        
        # Custom styles
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            spaceAfter=30,
            alignment=TA_CENTER
        )
        
        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=16,
            spaceAfter=12,
            textColor=colors.HexColor('#2c3e50')
        )
        
        normal_style = ParagraphStyle(
            'CustomNormal',
            parent=styles['Normal'],
            fontSize=12,
            spaceAfter=12,
            textColor=colors.HexColor('#2c3e50')
        )

        # Initialize elements list
        elements = []

        # Add title
        elements.append(Paragraph(report.title, title_style))
        elements.append(Spacer(1, 20))

        # Add report period
        period_text = f"Report Period: {report.period_start.strftime('%B %d, %Y')} - {report.period_end.strftime('%B %d, %Y')}"
        elements.append(Paragraph(period_text, normal_style))
        elements.append(Spacer(1, 20))

        # Add Summary if exists
        if report.summary:
            elements.append(Paragraph("Executive Summary", heading_style))
            summary_paragraphs = report.summary.split('\n')
            for para in summary_paragraphs:
                if para.strip():
                    elements.append(Paragraph(para, normal_style))
            elements.append(Spacer(1, 20))

        # Add Statistics if they exist
        if isinstance(report.content, dict) and 'statistics' in report.content:
            elements.append(Paragraph("Key Statistics", heading_style))
            stats_data = []
            
            # Format patient statistics
            if 'patients' in report.content['statistics']:
                patient_stats = report.content['statistics']['patients']
                
                # Add total patients
                if 'total_patients' in patient_stats:
                    stats_data.append([
                        Paragraph("Total Patients", normal_style),
                        Paragraph(str(patient_stats['total_patients']), normal_style)
                    ])
                
                # Format age distribution
                if 'age_distribution' in patient_stats:
                    age_dist = patient_stats['age_distribution']
                    age_text = ", ".join([
                        f"{age_range}: {count}" 
                        for age_range, count in age_dist.items()
                    ])
                    stats_data.append([
                        Paragraph("Age Distribution", normal_style),
                        Paragraph(age_text, normal_style)
                    ])
                
                # Format location distribution
                if 'location_distribution' in patient_stats:
                    loc_dist = patient_stats['location_distribution']
                    loc_text = ", ".join([
                        f"{item['location']}: {item['count']}" 
                        for item in loc_dist
                    ])
                    stats_data.append([
                        Paragraph("Location Distribution", normal_style),
                        Paragraph(loc_text, normal_style)
                    ])
            
            # Format checkup statistics
            if 'checkups' in report.content['statistics']:
                checkup_stats = report.content['statistics']['checkups']
                for key, value in checkup_stats.items():
                    if key != 'weekly_distribution':  # Handle weekly distribution separately
                        stats_data.append([
                            Paragraph(key.replace('_', ' ').title(), normal_style),
                            Paragraph(str(value), normal_style)
                        ])
            
            # Format emergency statistics
            if 'emergencies' in report.content['statistics']:
                emergency_stats = report.content['statistics']['emergencies']
                for key, value in emergency_stats.items():
                    if key not in ['status_distribution', 'weekly_distribution']:
                        stats_data.append([
                            Paragraph(key.replace('_', ' ').title(), normal_style),
                            Paragraph(str(value), normal_style)
                        ])

            if stats_data:
                # Create and style the statistics table
                stats_table = Table(stats_data, colWidths=[doc.width * 0.7, doc.width * 0.3])
                stats_table.setStyle(TableStyle([
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#2c3e50')),
                    ('FONTSIZE', (0, 0), (-1, -1), 11),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
                    ('TOPPADDING', (0, 0), (-1, -1), 12),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdc3c7')),
                    ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8f9fa')),
                    ('ROWBACKGROUNDS', (0, 0), (-1, -1), 
                     [colors.HexColor('#ffffff'), colors.HexColor('#f8f9fa')]),
                ]))
                elements.append(stats_table)
                elements.append(Spacer(1, 20))

        # Add Breakdown Tables if they exist
        breakdown_keys = [
            'daily_breakdown', 'weekly_breakdown',
            'monthly_breakdown', 'quarterly_breakdown',
            'yearly_breakdown'
        ]

        for key in breakdown_keys:
            if isinstance(report.content, dict) and key in report.content:
                breakdown_data = report.content[key]
                if breakdown_data and isinstance(breakdown_data, list):
                    elements.append(Paragraph(
                        f"{key.replace('_', ' ').title()} Analysis",
                        heading_style
                    ))

                    # Get metrics from first entry
                    if breakdown_data[0] and isinstance(breakdown_data[0], dict):
                        first_entry = breakdown_data[0]
                        metrics = first_entry.get('metrics', {})
                        if metrics:
                            metric_keys = list(metrics.keys())

                            # Create table data
                            table_data = [[
                                Paragraph('Period', heading_style)
                            ] + [
                                Paragraph(k.replace('_', ' ').title(), heading_style)
                                for k in metric_keys
                            ]]

                            # Add rows
                            for entry in breakdown_data:
                                if isinstance(entry, dict):
                                    period = entry.get('date', entry.get('week', entry.get('month',
                                        entry.get('quarter', entry.get('year', '')))))
                                    metrics = entry.get('metrics', {})
                                    
                                    row = [Paragraph(str(period), normal_style)]
                                    row.extend([
                                        Paragraph(str(metrics.get(k, '')), normal_style)
                                        for k in metric_keys
                                    ])
                                    table_data.append(row)

                            if len(table_data) > 1:  # Only create table if we have data rows
                                # Calculate column widths
                                col_widths = [doc.width / len(table_data[0])] * len(table_data[0])
                                
                                # Create and style the table
                                breakdown_table = Table(table_data, colWidths=col_widths)
                                breakdown_table.setStyle(TableStyle([
                                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ecf0f1')),
                                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
                                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                                    ('FONTSIZE', (0, 0), (-1, -1), 10),
                                    ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#bdc3c7')),
                                    ('ROWBACKGROUNDS', (0, 1), (-1, -1),
                                     [colors.HexColor('#ffffff'), colors.HexColor('#f9f9f9')]),
                                ]))
                                elements.append(breakdown_table)
                                elements.append(Spacer(1, 20))

        # Add footer
        footer_text = f"Generated by RHU Management System • Report ID: {report.id}"
        elements.append(Paragraph(footer_text, 
            ParagraphStyle('Footer', 
                parent=styles['Normal'],
                fontSize=8,
                textColor=colors.HexColor('#95a5a6'),
                alignment=TA_CENTER
            )
        ))

        # Build the PDF
        doc.build(elements)

        # Update report with filename
        report.file_path = filename
        report.save(update_fields=['file_path'])

        return filepath

    except Exception as e:
        print(f"Error in export_report: {str(e)}")
        raise

@login_required(login_url='rhu_management:rhu_login')
@superuser_required
def view_report(request, report_id):
    """View report PDF in browser"""
    try:
        report = RHUReport.objects.get(id=report_id)

        # Generate the report if it doesn't exist or regenerate if needed
        try:
            # Use /tmp directory for Lambda environment
            reports_dir = '/tmp/reports' if os.path.exists('/tmp') else os.path.join(settings.MEDIA_ROOT, 'reports')
            file_path = os.path.join(reports_dir, os.path.basename(report.file_path)) if report.file_path else None

            if not file_path or not os.path.exists(file_path):
                file_path = export_report(report)
                report.file_path = os.path.basename(file_path)  # Store only filename in database
                report.save()

            # Serve the file
            with open(file_path, 'rb') as pdf_file:
                response = HttpResponse(pdf_file.read(), content_type='application/pdf')
                response['Content-Disposition'] = f'inline; filename="{os.path.basename(file_path)}"'
                return response

        except Exception as e:
            messages.error(request, f'Error generating report: {str(e)}')
            return redirect('rhu_management:reports_dashboard')

    except RHUReport.DoesNotExist:
        messages.error(request, 'Report not found.')
        return redirect('rhu_management:reports_dashboard')

@login_required(login_url='rhu_management:rhu_login')
@superuser_required
def download_report(request, report_id):
    """Download exported report file"""
    try:
        report = RHUReport.objects.get(id=report_id)

        try:
            # Use /tmp directory for Lambda environment
            reports_dir = '/tmp/reports' if os.path.exists('/tmp') else os.path.join(settings.MEDIA_ROOT, 'reports')
            file_path = os.path.join(reports_dir, os.path.basename(report.file_path)) if report.file_path else None

            if not file_path or not os.path.exists(file_path):
                file_path = export_report(report)
                report.file_path = os.path.basename(file_path)  # Store only filename in database
                report.save()

            # Serve the file
            with open(file_path, 'rb') as pdf_file:
                response = HttpResponse(pdf_file.read(), content_type='application/pdf')
                response['Content-Disposition'] = f'attachment; filename="{os.path.basename(file_path)}"'
                return response

        except Exception as e:
            messages.error(request, f'Error generating report: {str(e)}')
            return redirect('rhu_management:reports_dashboard')

    except RHUReport.DoesNotExist:
        messages.error(request, 'Report not found.')
        return redirect('rhu_management:reports_dashboard')


@login_required(login_url='rhu_management:rhu_login')
@superuser_required
def analytics_view(request):
    """Display analytics dashboard with filters"""
    # Get filter parameters
    time_range = request.GET.get('range', '30')  # Default to 30 days
    metric_type = request.GET.get('metric', 'all')  # Default to all metrics
    
    # Calculate date range
    end_date = timezone.now()
    start_date = end_date - timedelta(days=int(time_range))
    
    context = {
        'time_range': time_range,
        'metric_type': metric_type,
        'title': 'Analytics Dashboard'
    }
    
    try:
        # Patient Analytics
        if metric_type in ['all', 'patients']:
            patients_queryset = Patient.objects.filter(
                created_at__range=(start_date, end_date)
            )
            context['patient_stats'] = {
                'age_distribution': get_age_distribution(patients_queryset),
                'location_distribution': get_location_distribution(patients_queryset),
                'total_patients': patients_queryset.count()
            }
        
        # Checkup Analytics
        if metric_type in ['all', 'checkups']:
            checkups_queryset = PrenatalCheckup.objects.filter(
                checkup_date__range=(start_date, end_date)
            )
            context['checkup_stats'] = {
                'weekly_distribution': get_weekly_checkup_distribution(checkups_queryset),
                'total_checkups': checkups_queryset.count(),
                'completed_checkups': checkups_queryset.filter(status='COMPLETED').count(),
                'scheduled_checkups': checkups_queryset.filter(status='SCHEDULED').count()
            }
        
        # Emergency Analytics
        if metric_type in ['all', 'emergencies']:
            alerts_queryset = EmergencyAlert.objects.filter(
                alert_time__range=(start_date, end_date)
            )
            context['emergency_stats'] = {
                'avg_response_time': calculate_avg_response_time(alerts_queryset),
                'resolution_rate': calculate_resolution_rate(alerts_queryset),
                'status_distribution': get_status_distribution(alerts_queryset),
                'total_alerts': alerts_queryset.count(),
                'active_alerts': alerts_queryset.filter(status='ACTIVE').count()
            }
    
    except Exception as e:
        messages.error(request, f'Error generating analytics: {str(e)}')
        print(f"Analytics Error: {str(e)}")
    
    return render(request, 'rhu_management/report_analytics.html', context)

@login_required(login_url='rhu_management:rhu_login')
@superuser_required
def export_analytics(request):
    """Export analytics data as PDF report"""
    try:
        # Get filter parameters
        time_range = request.GET.get('range', '30')
        metric_type = request.GET.get('metric', 'all')
        
        # Calculate date range
        end_date = timezone.now()
        start_date = end_date - timedelta(days=int(time_range))
        
        # Create report title
        title = f"Analytics Report - {start_date.strftime('%B %d, %Y')} to {end_date.strftime('%B %d, %Y')}"
        
        # Initialize report content
        content = {
            'statistics': {},
            'metadata': {
                'time_range': f'Last {time_range} days',
                'metric_type': metric_type,
                'generated_at': timezone.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        }
        
        # Add patient statistics
        if metric_type in ['all', 'patients']:
            patients = Patient.objects.filter(created_at__range=(start_date, end_date))
            content['statistics']['patients'] = {
                'total_patients': patients.count(),
                'age_distribution': get_age_distribution(patients),
                'location_distribution': get_location_distribution(patients)
            }
        
        # Add checkup statistics
        if metric_type in ['all', 'checkups']:
            checkups = PrenatalCheckup.objects.filter(
                checkup_date__range=(start_date, end_date)
            )
            content['statistics']['checkups'] = {
                'total_checkups': checkups.count(),
                'completed_checkups': checkups.filter(status='COMPLETED').count(),
                'scheduled_checkups': checkups.filter(status='SCHEDULED').count(),
                'weekly_distribution': get_weekly_checkup_distribution(checkups)
            }
        
        # Add emergency statistics
        if metric_type in ['all', 'emergencies']:
            alerts = EmergencyAlert.objects.filter(
                alert_time__range=(start_date, end_date)
            )
            content['statistics']['emergencies'] = {
                'total_alerts': alerts.count(),
                'active_alerts': alerts.filter(status='ACTIVE').count(),
                'avg_response_time': calculate_avg_response_time(alerts),
                'resolution_rate': calculate_resolution_rate(alerts),
                'status_distribution': get_status_distribution(alerts)
            }
        
        # Create and save report
        report = RHUReport.objects.create(
            title=title,
            type='CUSTOM',
            period_start=start_date,
            period_end=end_date,
            content=content,
            summary=f"Analytics report for {metric_type} metrics over the last {time_range} days."
        )
        
        # Generate PDF
        filepath = export_report(report)
        
        # Serve the file
        with open(filepath, 'rb') as pdf_file:
            response = HttpResponse(pdf_file.read(), content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="analytics_report_{timezone.now().strftime("%Y%m%d")}.pdf"'
            return response
            
    except Exception as e:
        messages.error(request, f'Error exporting analytics: {str(e)}')
        return redirect('rhu_management:analytics_view')


# Analytics Functions
def get_patient_analytics(start_date, end_date, barangay=None):
    """Get detailed patient statistics with optional barangay filter"""
    query = Patient.objects.all()
    if barangay:
        query = query.filter(barangay=barangay)  # Use the barangay foreign key directly

    return {
        'total_patients': query.count(),
        'new_patients': query.filter(
            created_at__range=(start_date, end_date)
        ).count(),
        'age_distribution': get_age_distribution(barangay),
        'location_distribution': get_location_distribution(barangay)
    }


def get_checkup_analytics(start_date, end_date, barangay=None):
    """Get checkup statistics with optional barangay filter"""
    query = PrenatalCheckup.objects.filter(
        checkup_date__range=(start_date, end_date)
    )
    if barangay:
        query = query.filter(patient__barangay=barangay)  # Use the correct path through patient to barangay

    return {
        'total_checkups': query.count(),
        'avg_checkups_per_patient': query.values('patient').annotate(
            count=Count('id')
        ).aggregate(avg=Avg('count'))['avg'],
        'weekly_distribution': get_weekly_checkup_distribution(query)
    }


def get_emergency_analytics(start_date, end_date, barangay=None):
    """Get emergency statistics with optional barangay filter"""
    query = EmergencyAlert.objects.filter(
        alert_time__range=(start_date, end_date)
    )
    if barangay:
        query = query.filter(patient__barangay=barangay)

    # Calculate average response time
    avg_response_time = calculate_avg_response_time(query)
    
    # Calculate resolution rate
    resolution_rate = calculate_resolution_rate(query)

    # Get status distribution
    status_dist = get_status_distribution(query)
    
    # Debug prints
    print("Emergency Analytics Debug:")
    print(f"Total Alerts: {query.count()}")
    print(f"Avg Response Time: {avg_response_time}")
    print(f"Resolution Rate: {resolution_rate}")
    print("Status Distribution:", status_dist)

    return {
        'total_alerts': query.count(),
        'avg_response_time': avg_response_time if avg_response_time else 0,
        'resolution_rate': resolution_rate,
        'response_times': calculate_response_times(query),
        'status_distribution': status_dist
    }


def get_age_distribution(patients_queryset):
    """Calculate age distribution from a Patient queryset"""
    age_ranges = {
        '15-20': (15, 20),
        '21-25': (21, 25),
        '26-30': (26, 30),
        '31-35': (31, 35),
        '36-40': (36, 40),
        '41+': (41, 200)
    }
    
    distribution = {range_name: 0 for range_name in age_ranges}
    
    for patient in patients_queryset:
        age = patient.age
        for range_name, (min_age, max_age) in age_ranges.items():
            if min_age <= age <= max_age:
                distribution[range_name] += 1
                break
    
    return distribution


def get_location_distribution(patients_queryset):
    """Get patient distribution by barangay"""
    return list(patients_queryset.values(
        'barangay__barangay_name'
    ).annotate(
        count=Count('id')
    ).values(
        location=models.F('barangay__barangay_name'),
        count=models.F('count')
    ).order_by('-count'))


def get_weekly_checkup_distribution(checkups_queryset):
    """Get checkup distribution by day of week"""
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    distribution = {day: 0 for day in days}
    
    for checkup in checkups_queryset:
        day = checkup.checkup_date.strftime('%A')
        distribution[day] += 1
    
    return distribution


def calculate_avg_response_time(alerts_queryset):
    """Calculate average response time for emergency alerts"""
    response_times = []
    
    for alert in alerts_queryset.filter(
        response_time__isnull=False,
        alert_time__isnull=False
    ).exclude(status='CANCELLED'):
        response_time = (alert.response_time - alert.alert_time).total_seconds() / 60
        response_times.append(response_time)
    
    return round(sum(response_times) / len(response_times), 1) if response_times else 0


def calculate_resolution_rate(alerts_queryset):
    """Calculate emergency resolution rate"""
    total = alerts_queryset.exclude(status='CANCELLED').count()
    resolved = alerts_queryset.filter(status='RESOLVED').count()
    
    return round((resolved / total) * 100, 1) if total > 0 else 0


def get_status_distribution(alerts_queryset):
    """Get distribution of emergency alert statuses"""
    return dict(alerts_queryset.values(
        'status'
    ).annotate(
        count=Count('id')
    ).values_list('status', 'count'))


@cache_page(60 * 5)  # Cache for 5 minutes
@login_required(login_url='rhu_management:rhu_login')
@superuser_required
def rhu_dashboard(request):
    """Display RHU dashboard with overview and quick stats"""
    today = timezone.now().date()
    
    # Use database aggregation for statistics
    from django.db.models import Count, Q
    
    # Get patient stats
    patient_stats = Patient.objects.aggregate(
        total_patients=Count('id'),
        new_patients=Count('id', filter=Q(
            created_at__gte=today - timedelta(days=30)
        ))
    )
    
    # Get checkup stats
    checkup_stats = PrenatalCheckup.objects.aggregate(
        today_checkups=Count('id', filter=Q(
            checkup_date__date=today,
            status='SCHEDULED'
        )),
        upcoming_checkups=Count('id', filter=Q(
            checkup_date__gt=today,
            status='SCHEDULED'
        )),
        tomorrow_checkups=Count('id', filter=Q(
            checkup_date__date=today + timedelta(days=1),
            status='SCHEDULED'
        ))
    )
    
    # Get emergency stats
    emergency_stats = EmergencyAlert.objects.aggregate(
        active_emergencies=Count('id', filter=Q(status='ACTIVE')),
        monthly_emergencies=Count('id', filter=Q(
            alert_time__gte=today - timedelta(days=30)
        ))
    )
    
    # Combine all stats
    stats = {
        **patient_stats,
        **checkup_stats,
        **emergency_stats
    }
    
    # Get upcoming checkups efficiently
    upcoming_checkups = PrenatalCheckup.objects.select_related(
        'patient__user'
    ).filter(
        checkup_date__date=today,
        status='SCHEDULED'
    ).order_by(
        'checkup_date'
    )[:5]
    
    # Get recent activities efficiently
    recent_activities = []
    
    # Recent checkups
    recent_checkups = PrenatalCheckup.objects.select_related(
        'patient__user'
    ).filter(
        status='COMPLETED'
    ).order_by('-checkup_date')[:3]
    
    for checkup in recent_checkups:
        recent_activities.append({
            'type': 'checkup',
            'time': checkup.checkup_date,
            'patient': checkup.patient,
            'description': 'completed a prenatal checkup'
        })
    
    # Recent emergencies
    recent_emergencies = EmergencyAlert.objects.select_related(
        'patient__user'
    ).order_by('-alert_time')[:3]
    
    for emergency in recent_emergencies:
        recent_activities.append({
            'type': 'emergency',
            'time': emergency.alert_time,
            'patient': emergency.patient,
            'description': 'triggered an emergency alert'
        })
    
    # Sort activities by time
    recent_activities.sort(key=lambda x: x['time'], reverse=True)
    recent_activities = recent_activities[:3]
    
    # Get pending tasks efficiently
    pending_tasks = []
    
    # Active emergencies as high priority tasks
    active_emergencies = EmergencyAlert.objects.select_related(
        'patient__user'
    ).filter(
        status='ACTIVE'
    ).order_by('-alert_time')[:3]
    
    for emergency in active_emergencies:
        pending_tasks.append({
            'type': 'emergency',
            'priority': 'high',
            'reference_id': emergency.id,
            'description': f'Emergency alert from {emergency.patient.user.get_full_name()} needs response'
        })
    
    # Today's checkups as medium priority tasks
    today_checkups = PrenatalCheckup.objects.select_related(
        'patient__user'
    ).filter(
        checkup_date__date=today,
        status='SCHEDULED'
    ).order_by('checkup_date')[:3]
    
    for checkup in today_checkups:
        pending_tasks.append({
            'type': 'checkup',
            'priority': 'medium',
            'reference_id': checkup.id,
            'description': f'Scheduled checkup for {checkup.patient.user.get_full_name()}'
        })
    
    # Calculate monthly trends efficiently
    monthly_trends = get_monthly_trends()
    
    context = {
        'stats': stats,
        'upcoming_checkups': upcoming_checkups,
        'recent_activities': recent_activities,
        'pending_tasks': pending_tasks,
        'monthly_trends': monthly_trends,
        'title': 'RHU Dashboard'
    }
    
    return render(request, 'rhu_management/dashboard.html', context)

def get_monthly_trends():
    """Calculate monthly trends for the dashboard chart"""
    now = timezone.now()
    months = []
    data = {
        'patients': [],
        'checkups': [],
        'emergencies': []
    }
    
    # Get data for last 6 months using database aggregation
    for i in range(6):
        month_start = (now - timedelta(days=30 * i)).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(seconds=1)
        months.append(month_start.strftime('%B %Y'))
        
        # Get counts for each type using aggregation
        patient_count = Patient.objects.filter(
            created_at__range=(month_start, month_end)
        ).count()
        
        checkup_count = PrenatalCheckup.objects.filter(
            checkup_date__range=(month_start, month_end)
        ).count()
        
        emergency_count = EmergencyAlert.objects.filter(
            alert_time__range=(month_start, month_end)
        ).count()
        
        data['patients'].append(patient_count)
        data['checkups'].append(checkup_count)
        data['emergencies'].append(emergency_count)
    
    return {
        'months': list(reversed(months)),
        'datasets': {k: list(reversed(v)) for k, v in data.items()}
    }


def get_recent_activities():
    """Get recent activities across all models"""
    activities = []

    # Get recent checkups
    recent_checkups = PrenatalCheckup.objects.select_related(
        'patient__user'
    ).filter(
        status='COMPLETED'
    ).order_by('-checkup_date')[:3]

    for checkup in recent_checkups:
        activities.append({
            'type': 'checkup',
            'time': checkup.created_at,  # Use created_at instead of checkup_date
            'patient': checkup.patient,
            'description': 'completed a prenatal checkup'
        })

    # Get recent emergency alerts
    recent_emergencies = EmergencyAlert.objects.select_related(
        'patient__user'
    ).order_by('-alert_time')[:3]

    for emergency in recent_emergencies:
        activities.append({
            'type': 'emergency',
            'time': emergency.alert_time,
            'patient': emergency.patient,
            'description': 'triggered an emergency alert'
        })

    # Get recent patient registrations
    recent_patients = Patient.objects.select_related(
        'user'
    ).order_by('-created_at')[:3]

    for patient in recent_patients:
        activities.append({
            'type': 'registration',
            'time': patient.created_at,
            'patient': patient,
            'description': 'registered as a new patient'
        })

    # Sort all activities by time and get the 3 most recent
    activities.sort(key=lambda x: x['time'], reverse=True)
    return activities[:3]


def get_pending_tasks(staff=None):
    """Get pending tasks for staff member"""
    tasks = []
    today = timezone.now().date()

    # Check unresponded emergency alerts
    active_emergencies = EmergencyAlert.objects.filter(
        status='ACTIVE'
    ).order_by('-alert_time')[:3]

    for emergency in active_emergencies:
        tasks.append({
            'type': 'emergency',
            'reference_id': emergency.id,
            'description': f'Emergency alert from {emergency.patient.user.get_full_name()} needs response',
            'priority': 'high'
        })

    # Check upcoming checkups
    upcoming_checkups = PrenatalCheckup.objects.filter(
        checkup_date__gte=today,
        status='SCHEDULED'
    ).order_by('checkup_date')[:3]

    for checkup in upcoming_checkups:
        tasks.append({
            'type': 'checkup',
            'reference_id': checkup.id,
            'description': f'Scheduled checkup for {checkup.patient.user.get_full_name()}',
            'priority': 'medium' if checkup.checkup_date == today else 'normal'
        })

    # Sort tasks by priority (high -> medium -> normal)
    priority_order = {'high': 0, 'medium': 1, 'normal': 2}
    tasks.sort(key=lambda x: priority_order[x['priority']])

    return tasks[:3]  # Return only top 5 tasks


def calculate_response_times(alerts):
    """Calculate various response time metrics for emergency alerts"""
    response_times = {
        'average': None,
        'min': None,
        'max': None,
        'under_15_min': 0,
        'under_30_min': 0,
        'over_30_min': 0
    }

    # Get alerts that have been responded to
    responded_alerts = alerts.filter(
        response_time__isnull=False,
        alert_time__isnull=False
    ).exclude(status='CANCELLED')

    if not responded_alerts.exists():
        return response_times

    total_minutes = 0
    min_time = float('inf')
    max_time = 0
    count = 0

    for alert in responded_alerts:
        # Calculate response time in minutes
        response_time = (alert.response_time - alert.alert_time).total_seconds() / 60

        # Update totals
        total_minutes += response_time
        count += 1

        # Update min/max
        min_time = min(min_time, response_time)
        max_time = max(max_time, response_time)

        # Update time brackets
        if response_time <= 15:
            response_times['under_15_min'] += 1
        elif response_time <= 30:
            response_times['under_30_min'] += 1
        else:
            response_times['over_30_min'] += 1

    # Calculate average
    if count > 0:
        response_times['average'] = round(total_minutes / count, 1)
        response_times['min'] = round(min_time, 1)
        response_times['max'] = round(max_time, 1)

    return response_times


@login_required(login_url='rhu_management:rhu_login')
@superuser_required
@require_GET
def check_emergency_alerts(request):
    """API endpoint to check for active emergency alerts"""
    result = check_active_emergencies()
    return JsonResponse(result)
