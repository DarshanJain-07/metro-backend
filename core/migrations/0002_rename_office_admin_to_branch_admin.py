# Generated manually to keep a single branch-admin role name.

from django.db import migrations, models


ROLE_CHOICES = [
    ("PLATFORM_ADMIN", "Platform Admin"),
    ("CLIENT_SUPER_ADMIN", "Client Super Admin"),
    ("BRANCH_ADMIN", "Branch Admin"),
    ("BOOKING_USER", "Booking User"),
    ("DELIVERY_USER", "Delivery User"),
    ("ACCOUNTANT", "Accountant"),
    ("VIEWER", "Viewer"),
]


def forwards(apps, schema_editor):
    UserMembership = apps.get_model("core", "UserMembership")
    UserMembership.objects.filter(role="OFFICE_ADMIN").update(role="BRANCH_ADMIN")


def backwards(apps, schema_editor):
    UserMembership = apps.get_model("core", "UserMembership")
    UserMembership.objects.filter(role="BRANCH_ADMIN").update(role="OFFICE_ADMIN")


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
        migrations.AlterField(
            model_name="usermembership",
            name="role",
            field=models.CharField(choices=ROLE_CHOICES, max_length=50),
        ),
        migrations.RemoveConstraint(
            model_name="usermembership",
            name="office_required_for_operational_roles",
        ),
        migrations.AddConstraint(
            model_name="usermembership",
            constraint=models.CheckConstraint(
                condition=~models.Q(role__in=["BRANCH_ADMIN", "BOOKING_USER", "DELIVERY_USER"])
                | models.Q(office__isnull=False),
                name="office_required_for_operational_roles",
            ),
        ),
    ]
