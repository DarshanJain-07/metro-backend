from django.db import migrations, models


DEFAULT_ROLES = (
    {"code": "SUPER_ADMIN", "name": "Super Admin", "requires_office": False, "sort_order": 10},
    {"code": "BRANCH_ADMIN", "name": "Branch Admin", "requires_office": True, "sort_order": 20},
    {"code": "BOOKING_USER", "name": "Booking User", "requires_office": True, "sort_order": 30},
    {"code": "DELIVERY_USER", "name": "Delivery User", "requires_office": True, "sort_order": 40},
    {"code": "ACCOUNTANT", "name": "Accountant", "requires_office": True, "sort_order": 50},
    {"code": "VIEWER", "name": "Viewer", "requires_office": True, "sort_order": 60},
)


def seed_role_definitions(apps, schema_editor):
    RoleDefinition = apps.get_model("core", "RoleDefinition")
    for role in DEFAULT_ROLES:
        RoleDefinition.objects.update_or_create(
            code=role["code"],
            defaults={
                "name": role["name"],
                "requires_office": role["requires_office"],
                "sort_order": role["sort_order"],
                "is_active": True,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_citus_composite_tenant_keys"),
    ]

    operations = [
        migrations.CreateModel(
            name="RoleDefinition",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=50, unique=True)),
                ("name", models.CharField(max_length=120)),
                ("description", models.TextField(blank=True)),
                ("requires_office", models.BooleanField(default=True)),
                ("is_active", models.BooleanField(default=True)),
                ("sort_order", models.PositiveIntegerField(default=100)),
            ],
            options={
                "ordering": ["sort_order", "name"],
            },
        ),
        migrations.RemoveConstraint(
            model_name="usermembership",
            name="office_required_for_operational_roles",
        ),
        migrations.AlterField(
            model_name="companyrolepermissionoverride",
            name="role",
            field=models.CharField(max_length=50),
        ),
        migrations.AlterField(
            model_name="roletemplate",
            name="role",
            field=models.CharField(max_length=50),
        ),
        migrations.AlterField(
            model_name="usermembership",
            name="role",
            field=models.CharField(max_length=50),
        ),
        migrations.RunPython(seed_role_definitions, migrations.RunPython.noop),
    ]
