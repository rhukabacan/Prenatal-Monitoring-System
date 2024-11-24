# Generated by Django 4.2.16 on 2024-11-23 06:55

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rhu_management', '0012_remove_prenatalcheckup_compliance_status_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='prenatalcheckup',
            name='status',
            field=models.CharField(choices=[('SCHEDULED', 'Scheduled'), ('COMPLETED', 'Completed'), ('REQUESTED', 'Requested'), ('CANCELLED', 'Cancelled'), ('MISSED', 'Missed')], default='SCHEDULED', max_length=10),
        ),
    ]
