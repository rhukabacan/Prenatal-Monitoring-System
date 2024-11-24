# Generated by Django 4.2.16 on 2024-11-23 05:58

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rhu_management', '0010_delete_familyinformation'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='prenatalcheckup',
            name='blood_type',
        ),
        migrations.AddField(
            model_name='prenatalcheckup',
            name='compliance_status',
            field=models.CharField(default='PENDING', max_length=20),
        ),
        migrations.AlterField(
            model_name='prenatalcheckup',
            name='blood_pressure',
            field=models.CharField(blank=True, max_length=20, null=True),
        ),
        migrations.AlterField(
            model_name='prenatalcheckup',
            name='height',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True),
        ),
        migrations.AlterField(
            model_name='prenatalcheckup',
            name='weight',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True),
        ),
    ]
