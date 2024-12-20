# Generated by Django 4.2.16 on 2024-12-19 19:03

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rhu_management', '0002_alter_emergencyalert_alert_time_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='emergencyalert',
            name='alert_time',
            field=models.DateTimeField(auto_now_add=True),
        ),
        migrations.AlterField(
            model_name='patient',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True),
        ),
        migrations.AlterField(
            model_name='prenatalcheckup',
            name='checkup_date',
            field=models.DateTimeField(),
        ),
        migrations.AlterField(
            model_name='prenatalcheckup',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True),
        ),
        migrations.AlterField(
            model_name='rhureport',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True),
        ),
    ]
