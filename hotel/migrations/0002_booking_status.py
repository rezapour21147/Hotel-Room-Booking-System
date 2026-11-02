from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('hotel', '0001_initial'),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name='booking',
            name='hotel_booki_room_id_63801d_idx',
        ),
        migrations.AddField(
            model_name='booking',
            name='cancelled_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='booking',
            name='status',
            field=models.CharField(choices=[('confirmed', 'Confirmed'), ('cancelled', 'Cancelled')], default='confirmed', max_length=10),
        ),
        migrations.AddIndex(
            model_name='booking',
            index=models.Index(fields=['room', 'status', 'check_in', 'check_out'], name='hotel_booki_room_id_abd392_idx'),
        ),
    ]