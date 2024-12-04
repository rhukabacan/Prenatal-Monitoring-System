from django.db import migrations
from django.db.migrations.recorder import MigrationRecorder

def skip_if_exists(apps, schema_editor):
    # Check if the table exists
    table_name = 'rhu_management_vitalsigns'
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = %s
            );
        """, [table_name])
        exists = cursor.fetchone()[0]
        
        if not exists:
            # Create the table if it doesn't exist
            cursor.execute("""
                CREATE TABLE rhu_management_vitalsigns (
                    id SERIAL PRIMARY KEY,
                    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL,
                    weight NUMERIC(5,2),
                    height NUMERIC(5,2),
                    age_of_gestation INTEGER,
                    blood_pressure VARCHAR(20),
                    nutritional_status VARCHAR(20),
                    birth_plan_status VARCHAR(20) NOT NULL,
                    dental_checkup_status VARCHAR(20) NOT NULL,
                    dental_checkup_date DATE,
                    hemoglobin_count NUMERIC(5,2),
                    urinalysis_date DATE,
                    cbc_date DATE,
                    syphilis_test_date DATE,
                    syphilis_result VARCHAR(20),
                    hiv_test_date DATE,
                    hiv_result VARCHAR(20),
                    hepatitis_b_test_date DATE,
                    hepatitis_b_result VARCHAR(20),
                    stool_exam_date DATE,
                    stool_exam_result TEXT,
                    acetic_acid_wash_date DATE,
                    acetic_acid_wash_result TEXT,
                    tetanus_vaccine_date DATE,
                    syphilis_treatment TEXT,
                    arv_treatment TEXT,
                    bacteriuria_treatment TEXT,
                    anemia_treatment TEXT,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
                    patient_id INTEGER NOT NULL REFERENCES rhu_management_patient(id)
                );
            """)

class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.RunPython(skip_if_exists),
    ]