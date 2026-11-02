import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('hotel', '0002_booking_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='booking',
            name='rescheduled_from',
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='rescheduled_to', to='hotel.booking'),
        ),
        migrations.AlterField(
            model_name='booking',
            name='status',
            field=models.CharField(choices=[('confirmed', 'Confirmed'), ('cancelled', 'Cancelled'), ('rescheduled', 'Rescheduled')], default='confirmed', max_length=12),
        ),
    ]