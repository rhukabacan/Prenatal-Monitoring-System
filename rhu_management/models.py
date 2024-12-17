from datetime import timedelta

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class Barangay(models.Model):
    """Model for barangay information"""
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    barangay_name = models.CharField(max_length=100, unique=True)
    contact_number = models.CharField(max_length=15)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Barangays"
        ordering = ['barangay_name']

    def __str__(self):
        return self.barangay_name.upper()


class Patient(models.Model):
    """Extended user model for patient-specific information"""

    BLOOD_TYPE_CHOICES = [
        ('A+', 'A+'),
        ('A-', 'A-'),
        ('B+', 'B+'),
        ('B-', 'B-'),
        ('O+', 'O+'),
        ('O-', 'O-'),
        ('AB+', 'AB+'),
        ('AB-', 'AB-'),
    ]

    RELIGION_CHOICES = [
        ('ROMAN_CATHOLIC', 'Roman Catholic'),
        ('ISLAM', 'Islam'),
        ('EVANGELICAL', 'Evangelical'),
        ('IGLESIA_NI_CRISTO', 'Iglesia Ni Cristo'),
        ('PROTESTANT', 'Protestant'),
        ('SEVENTH_DAY_ADVENTIST', 'Seventh Day Adventist'),
        ('BUDDHISM', 'Buddhism'),
        ('HINDUISM', 'Hinduism'),
        ('OTHERS', 'Others'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    contact_number = models.CharField(max_length=15)
    sitio = models.CharField(max_length=50)
    barangay = models.ForeignKey(Barangay, on_delete=models.PROTECT)
    birth_date = models.DateField()
    occupation = models.CharField(max_length=100)
    monthly_income = models.DecimalField(max_digits=10, decimal_places=2)
    blood_type = models.CharField(max_length=3, choices=BLOOD_TYPE_CHOICES)
    religion = models.CharField(max_length=50, choices=RELIGION_CHOICES)
    spouse_name = models.CharField(max_length=100)
    spouse_occupation = models.CharField(max_length=100)
    spouse_monthly_income = models.DecimalField(max_digits=10, decimal_places=2)
    number_of_children = models.PositiveIntegerField(default=0)
    emergency_contact_name = models.CharField(max_length=100)
    emergency_contact_number = models.CharField(max_length=15)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def last_checkup(self):
        """Get the most recent completed checkup"""
        return self.prenatalcheckup_set.filter(
            checkup_date__lte=timezone.now()
        ).order_by('-checkup_date').first()

    @property
    def next_checkup(self):
        """Get the next scheduled checkup"""
        return self.prenatalcheckup_set.filter(
            status='SCHEDULED',
            checkup_date__gt=timezone.now()
        ).order_by('checkup_date').first()

    @property
    def age(self):
        """Calculate age based on birth_date"""
        today = timezone.now().date()
        age = today.year - self.birth_date.year
        # Subtract 1 if birthday hasn't occurred this year
        if today.month < self.birth_date.month or (
            today.month == self.birth_date.month and
            today.day < self.birth_date.day
        ):
            age -= 1
        return age

    def __str__(self):
        return f"{self.user.first_name} {self.user.last_name}"


class PregnancyHistory(models.Model):
    """Model for previous pregnancy records"""
    DELIVERY_CHOICES = [
        ('NORMAL', 'Normal Delivery'),
        ('CS', 'Cesarean Section'),
        ('ASSISTED', 'Assisted Delivery')
    ]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    delivery_date = models.DateField()
    delivery_type = models.CharField(max_length=10, choices=DELIVERY_CHOICES)
    delivery_location = models.CharField(max_length=100)
    birth_weight = models.DecimalField(max_digits=4, decimal_places=2)  # in kg
    complications = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-delivery_date']

    def __str__(self):
        return f"Pregnancy History - {self.patient} ({self.delivery_date})"


class PrenatalCheckup(models.Model):
    STATUS_CHOICES = [
        ('SCHEDULED', 'Scheduled'),
        ('COMPLETED', 'Completed'),
        ('REQUESTED', 'Requested'),
        ('CANCELLED', 'Cancelled'),
        ('MISSED', 'Missed')
    ]

    NUTRITIONAL_STATUS_CHOICES = [
        ('NORMAL', 'Normal'),
        ('UNDERWEIGHT', 'Underweight'),
        ('OVERWEIGHT', 'Overweight')
    ]

    BIRTH_PLAN_STATUS = [
        ('COMPLETED', 'Completed'),
        ('IN_PROGRESS', 'In Progress'),
        ('NOT_STARTED', 'Not Started')
    ]

    DENTAL_CHECKUP_STATUS = [
        ('COMPLETED', 'Completed'),
        ('SCHEDULED', 'Scheduled'),
        ('NOT_DONE', 'Not Done')
    ]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    checkup_date = models.DateTimeField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='SCHEDULED')
    last_menstrual_period = models.DateField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    is_initial_record = models.BooleanField(default=False)

    # Basic Measurements (from VitalSigns)
    weight = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    height = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    age_of_gestation = models.PositiveIntegerField(null=True, blank=True)  # in weeks
    blood_pressure = models.CharField(max_length=20, null=True, blank=True)
    nutritional_status = models.CharField(
        max_length=20, 
        choices=NUTRITIONAL_STATUS_CHOICES,
        null=True, blank=True
    )

    # Birth Plan and Dental
    birth_plan_status = models.CharField(
        max_length=20,
        choices=BIRTH_PLAN_STATUS,
        default='NOT_STARTED'
    )
    dental_checkup_status = models.CharField(
        max_length=20,
        choices=DENTAL_CHECKUP_STATUS,
        default='NOT_DONE'
    )
    dental_checkup_date = models.DateField(null=True, blank=True)

    # Laboratory Tests
    hemoglobin_count = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    urinalysis_date = models.DateField(null=True, blank=True)
    cbc_date = models.DateField(null=True, blank=True)
    
    # STI Tests
    syphilis_test_date = models.DateField(null=True, blank=True)
    syphilis_result = models.CharField(max_length=20, null=True, blank=True)
    hiv_test_date = models.DateField(null=True, blank=True)
    hiv_result = models.CharField(max_length=20, null=True, blank=True)
    hepatitis_b_test_date = models.DateField(null=True, blank=True)
    hepatitis_b_result = models.CharField(max_length=20, null=True, blank=True)
    
    # Additional Tests
    stool_exam_date = models.DateField(null=True, blank=True)
    stool_exam_result = models.TextField(null=True, blank=True)
    acetic_acid_wash_date = models.DateField(null=True, blank=True)
    acetic_acid_wash_result = models.TextField(null=True, blank=True)

    # Vaccines and Treatments
    tetanus_vaccine_date = models.DateField(null=True, blank=True)
    
    # Treatments
    syphilis_treatment = models.TextField(null=True, blank=True)
    arv_treatment = models.TextField(null=True, blank=True)
    bacteriuria_treatment = models.TextField(null=True, blank=True)
    anemia_treatment = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-checkup_date']

    def clean(self):
        from django.core.exceptions import ValidationError

        # Check for schedule conflicts
        if self.checkup_date:
            conflicts = PrenatalCheckup.objects.filter(
                checkup_date__date=self.checkup_date.date(),
                checkup_date__hour=self.checkup_date.hour,
                status='SCHEDULED'
            ).exclude(id=self.id)

            if conflicts.exists():
                raise ValidationError('This time slot is already booked')

    @property
    def estimated_delivery_date(self):
        """Calculate EDD using Naegele's rule"""
        if self.last_menstrual_period:
            return self.last_menstrual_period + timedelta(days=280)
        return None

    def get_pregnancy_week(self):
        """Calculate pregnancy week using initial checkup values"""
        checkup = PrenatalCheckup.objects.filter(
            patient=self.patient,
        ).first()

        if not checkup or not checkup.last_menstrual_period:
            return None

        # Calculate weeks based on current date
        days_pregnant = (timezone.now().date() - checkup.last_menstrual_period).days
        weeks = min(days_pregnant // 7, 42)

        return {
            'weeks': weeks,
            'progress': min((weeks / 42) * 100, 100),
            'trimester': "First Trimester" if weeks <= 13 else
            "Second Trimester" if weeks <= 26 else
            "Third Trimester"
        }

    def __str__(self):
        return f'Checkup - {self.patient} ({self.checkup_date.strftime("%B %d, %Y %I:%M %p")})'


class EmergencyAlert(models.Model):
    """Model for tracking emergency alerts"""
    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('RESPONDED', 'Responded'),
        ('EN_ROUTE', 'En Route'),
        ('RESOLVED', 'Resolved'),
        ('CANCELLED', 'Cancelled')
    ]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    alert_time = models.DateTimeField(auto_now_add=True)
    location = models.TextField(blank=True)  # Optional GPS coordinates or address
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='ACTIVE')
    response_time = models.DateTimeField(null=True, blank=True)
    resolved_time = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-alert_time']

    def get_active_duration(self):
        if self.status == 'ACTIVE':
            return timezone.now() - self.alert_time
        return None

    def get_response_time_minutes(self):
        if self.alert_time and self.response_time:
            time_diff = self.response_time - self.alert_time
            minutes = int(time_diff.total_seconds() / 60)

            if minutes >= 60:
                hours = minutes // 60
                remaining_minutes = minutes % 60
                return f"{hours}h {remaining_minutes}"

            return f"{minutes}"
        return None

    def __str__(self):
        return f"Emergency Alert - {self.patient} ({self.alert_time})"



class RHUReport(models.Model):
    """Model for RHU generated reports"""
    REPORT_TYPES = [
        ('DAILY', 'Daily Report'),
        ('WEEKLY', 'Weekly Report'),
        ('MONTHLY', 'Monthly Report'),
        ('QUARTERLY', 'Quarterly Report'),
        ('ANNUAL', 'Annual Report'),
        ('CUSTOM', 'Custom Report')
    ]

    title = models.CharField(max_length=200)
    type = models.CharField(max_length=20, choices=REPORT_TYPES)
    period_start = models.DateField()
    period_end = models.DateField()
    content = models.JSONField()  # Store report data
    summary = models.TextField()
    file_path = models.CharField(max_length=255, blank=True)  # Path to saved report file
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} ({self.period_start} to {self.period_end})"
