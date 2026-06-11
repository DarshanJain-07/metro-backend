from django.db import migrations, models


def forwards(apps, schema_editor):
    Shipment = apps.get_model("shipments", "Shipment")
    RateRule = apps.get_model("shipments", "RateRule")

    Shipment.objects.filter(basis__in=["WEIGHT", "FIXED", "UNIT"]).update(basis="PAID")
    Shipment.objects.filter(payment_type="PAID").update(payment_type="CASH")
    Shipment.objects.filter(payment_type="TO_PAY").update(payment_type="BRANCH")
    Shipment.objects.filter(payment_type="TBB").update(payment_type="CREDIT")
    RateRule.objects.filter(basis__in=["WEIGHT", "FIXED", "UNIT"]).update(basis="PAID")


def backwards(apps, schema_editor):
    Shipment = apps.get_model("shipments", "Shipment")
    RateRule = apps.get_model("shipments", "RateRule")

    Shipment.objects.filter(basis__in=["PAID", "TO_PAY", "TBB"]).update(basis="WEIGHT")
    Shipment.objects.filter(payment_type="CASH").update(payment_type="PAID")
    Shipment.objects.filter(payment_type="BANK").update(payment_type="PAID")
    Shipment.objects.filter(payment_type="BRANCH").update(payment_type="TO_PAY")
    Shipment.objects.filter(payment_type="CREDIT").update(payment_type="TBB")
    RateRule.objects.filter(basis__in=["PAID", "TO_PAY", "TBB"]).update(basis="WEIGHT")


class Migration(migrations.Migration):
    dependencies = [
        ("shipments", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
        migrations.AlterField(
            model_name="shipment",
            name="basis",
            field=models.CharField(
                choices=[("PAID", "Paid"), ("TO_PAY", "To Pay"), ("TBB", "TBB (To Be Billed)")],
                default="PAID",
                max_length=50,
            ),
        ),
        migrations.AlterField(
            model_name="shipment",
            name="payment_type",
            field=models.CharField(
                choices=[("CASH", "Cash"), ("BANK", "Bank/UPI"), ("BRANCH", "Branch"), ("CREDIT", "Credit")],
                default="CASH",
                max_length=50,
            ),
        ),
        migrations.AlterField(
            model_name="raterule",
            name="basis",
            field=models.CharField(
                choices=[("PAID", "Paid"), ("TO_PAY", "To Pay"), ("TBB", "TBB (To Be Billed)")],
                max_length=50,
            ),
        ),
    ]
