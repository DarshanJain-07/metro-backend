from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import City, Company, Party, Role, State, User, UserMembership


class MasterImportExportApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Metro Express")
        self.state = State.objects.create(name="Maharashtra", code="MH")
        self.city = City.objects.create(name="Mumbai", state=self.state)
        self.user = User.objects.create_user(
            username="import_admin",
            password="pw",
            company=self.company,
            is_superuser=True,
            is_staff=True,
        )
        UserMembership.objects.create(user=self.user, company=self.company, role=Role.SUPER_ADMIN)
        self.client.force_authenticate(user=self.user)

    def test_master_import_rows_uses_import_export_resource(self):
        response = self.client.post(
            reverse("master-import-rows", kwargs={"resource": "parties"}),
            {
                "rows": [
                    {
                        "name": "Acme Traders",
                        "phone": "1234567890",
                        "city": self.city.id,
                        "address": "Dock Road",
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["totals"]["new"], 1)
        party = Party.objects.get(name="Acme Traders")
        self.assertEqual(party.company_id, self.company.id)
        self.assertEqual(party.city_id, self.city.id)

    def test_master_import_file_accepts_csv(self):
        csv_file = SimpleUploadedFile(
            "parties.csv",
            b"name,phone,city,address\nCSV Traders,1234567890,Mumbai,Market Road\n",
            content_type="text/csv",
        )

        response = self.client.post(
            reverse("master-import-file", kwargs={"resource": "parties"}),
            {"file": csv_file, "format": "csv"},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Party.objects.filter(company=self.company, name="CSV Traders").exists())

    def test_master_export_file_uses_import_export_resource(self):
        Party.objects.create(company=self.company, name="Export Customer", phone="1234567890", city=self.city)

        response = self.client.get(
            reverse("master-export-file", kwargs={"resource": "parties"}),
            {"format": "csv"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertIn("Export Customer", response.content.decode())
