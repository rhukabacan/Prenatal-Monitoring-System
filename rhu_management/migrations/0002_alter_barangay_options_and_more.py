# Generated by Django 4.2.16 on 2024-11-20 04:49

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('rhu_management', '0001_initial'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='barangay',
            options={'ordering': ['barangay_name'], 'verbose_name_plural': 'Barangays'},
        ),
        migrations.RenameField(
            model_name='barangay',
            old_name='name',
            new_name='barangay_name',
        ),
    ]
