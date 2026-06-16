from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from core.models import City, Company, CompanyOffice, Role, State, User, UserMembership

class UserPermissionsTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Test Company")
        self.state = State.objects.create(name="Test State", code="TS")
        self.city = City.objects.create(name="Test City", state=self.state)
        self.office = CompanyOffice.objects.create(company=self.company, name="Test Office", city=self.city)
        
        # Superuser
        self.superuser = User.objects.create_superuser(username="admin", password="password", email="admin@test.com")
        
        # Super Admin
        self.super_admin = User.objects.create_user(username="super_admin", password="password", company=self.company)
        UserMembership.objects.create(user=self.super_admin, company=self.company, role=Role.SUPER_ADMIN)
        
        # Normal User
        self.normal_user = User.objects.create_user(username="normal_user", password="password", company=self.company, office=self.office)
        UserMembership.objects.create(user=self.normal_user, company=self.company, office=self.office, role=Role.VIEWER)

        self.branch_admin = User.objects.create_user(username="branch_admin", password="password", company=self.company, office=self.office)
        UserMembership.objects.create(user=self.branch_admin, company=self.company, office=self.office, role=Role.BRANCH_ADMIN)

    def test_normal_user_cannot_create_user(self):
        self.client.force_authenticate(user=self.normal_user)
        url = reverse('user-list')
        data = {
            "username": "new_user",
            "password": "password",
            "email": "new@test.com"
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_super_admin_can_create_user(self):
        self.client.force_authenticate(user=self.super_admin)
        url = reverse('user-list')
        data = {
            "username": "new_user_by_admin",
            "password": "StrongPass123!",
            "email": "new_admin@test.com",
            "membership_inputs": [
                {"office": self.office.id, "role": Role.VIEWER}
            ]
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_normal_user_can_list_users(self):
        self.client.force_authenticate(user=self.normal_user)
        url = reverse('user-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should only see users in their company
        self.assertTrue(len(response.data['results']) >= 2) # super_admin and normal_user

    def test_normal_user_cannot_update_other_user(self):
        self.client.force_authenticate(user=self.normal_user)
        url = reverse('user-detail', kwargs={'pk': self.super_admin.pk})
        data = {"username": "hacked_admin"}
        response = self.client.patch(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_super_admin_can_update_user_in_same_company(self):
        self.client.force_authenticate(user=self.super_admin)
        url = reverse('user-detail', kwargs={'pk': self.normal_user.pk})
        data = {"first_name": "Updated Name"}
        response = self.client.patch(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.normal_user.refresh_from_db()
        self.assertEqual(self.normal_user.first_name, "Updated Name")

    def test_super_admin_cannot_update_user_in_other_company(self):
        other_company = Company.objects.create(name="Other Company")
        other_user = User.objects.create_user(username="other_user", password="password", company=other_company)
        
        self.client.force_authenticate(user=self.super_admin)
        url = reverse('user-detail', kwargs={'pk': other_user.pk})
        data = {"first_name": "Hacked"}
        response = self.client.patch(url, data, format='json')
        # Depending on how get_queryset and permissions interact, this might be 404 or 403.
        # get_queryset filters by current company, so it should be 404.
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_branch_admin_can_reset_same_branch_member_password(self):
        self.client.force_authenticate(user=self.branch_admin)
        url = reverse('user-detail', kwargs={'pk': self.normal_user.pk})
        response = self.client.patch(url, {"password": "NewStrongPass123!"}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.normal_user.refresh_from_db()
        self.assertTrue(self.normal_user.check_password("NewStrongPass123!"))

    def test_branch_admin_cannot_reset_branch_admin_password(self):
        other_branch_admin = User.objects.create_user(
            username="other_branch_admin",
            password="password",
            company=self.company,
            office=self.office,
        )
        UserMembership.objects.create(
            user=other_branch_admin,
            company=self.company,
            office=self.office,
            role=Role.BRANCH_ADMIN,
        )

        self.client.force_authenticate(user=self.branch_admin)
        url = reverse('user-detail', kwargs={'pk': other_branch_admin.pk})
        response = self.client.patch(url, {"password": "NewStrongPass123!"}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        other_branch_admin.refresh_from_db()
        self.assertTrue(other_branch_admin.check_password("password"))

    def test_branch_admin_cannot_reset_other_branch_member_password(self):
        other_office = CompanyOffice.objects.create(company=self.company, name="Other Office", city=self.city)
        other_user = User.objects.create_user(
            username="other_branch_user",
            password="password",
            company=self.company,
            office=other_office,
        )
        UserMembership.objects.create(
            user=other_user,
            company=self.company,
            office=other_office,
            role=Role.VIEWER,
        )

        self.client.force_authenticate(user=self.branch_admin)
        url = reverse('user-detail', kwargs={'pk': other_user.pk})
        response = self.client.patch(url, {"password": "NewStrongPass123!"}, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        other_user.refresh_from_db()
        self.assertTrue(other_user.check_password("password"))

    def test_super_admin_can_reset_branch_admin_password(self):
        self.client.force_authenticate(user=self.super_admin)
        url = reverse('user-detail', kwargs={'pk': self.branch_admin.pk})
        response = self.client.patch(url, {"password": "NewStrongPass123!"}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.branch_admin.refresh_from_db()
        self.assertTrue(self.branch_admin.check_password("NewStrongPass123!"))

    def test_membership_permissions(self):
        url = reverse('membership-list')
        
        # Normal user cannot create membership
        self.client.force_authenticate(user=self.normal_user)
        data = {
            "user": self.normal_user.pk,
            "company": self.company.pk,
            "office": self.office.id,
            "role": Role.ACCOUNTANT
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        
        # Super admin can create membership
        self.client.force_authenticate(user=self.super_admin)
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
