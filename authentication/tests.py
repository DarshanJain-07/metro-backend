from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from core.models import User, Company, Role, UserMembership

class UserPermissionsTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Test Company")
        
        # Superuser
        self.superuser = User.objects.create_superuser(username="admin", password="password", email="admin@test.com")
        
        # Client Super Admin
        self.client_admin = User.objects.create_user(username="client_admin", password="password", company=self.company)
        UserMembership.objects.create(user=self.client_admin, company=self.company, role=Role.CLIENT_SUPER_ADMIN)
        
        # Normal User
        self.normal_user = User.objects.create_user(username="normal_user", password="password", company=self.company)
        UserMembership.objects.create(user=self.normal_user, company=self.company, role=Role.VIEWER)

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

    def test_client_admin_can_create_user(self):
        self.client.force_authenticate(user=self.client_admin)
        url = reverse('user-list')
        data = {
            "username": "new_user_by_admin",
            "password": "password123",
            "email": "new_admin@test.com"
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_normal_user_can_list_users(self):
        self.client.force_authenticate(user=self.normal_user)
        url = reverse('user-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should only see users in their company
        self.assertTrue(len(response.data['results']) >= 2) # client_admin and normal_user

    def test_normal_user_cannot_update_other_user(self):
        self.client.force_authenticate(user=self.normal_user)
        url = reverse('user-detail', kwargs={'pk': self.client_admin.pk})
        data = {"username": "hacked_admin"}
        response = self.client.patch(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_client_admin_can_update_user_in_same_company(self):
        self.client.force_authenticate(user=self.client_admin)
        url = reverse('user-detail', kwargs={'pk': self.normal_user.pk})
        data = {"first_name": "Updated Name"}
        response = self.client.patch(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.normal_user.refresh_from_db()
        self.assertEqual(self.normal_user.first_name, "Updated Name")

    def test_client_admin_cannot_update_user_in_other_company(self):
        other_company = Company.objects.create(name="Other Company")
        other_user = User.objects.create_user(username="other_user", password="password", company=other_company)
        
        self.client.force_authenticate(user=self.client_admin)
        url = reverse('user-detail', kwargs={'pk': other_user.pk})
        data = {"first_name": "Hacked"}
        response = self.client.patch(url, data, format='json')
        # Depending on how get_queryset and permissions interact, this might be 404 or 403.
        # get_queryset filters by current company, so it should be 404.
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_membership_permissions(self):
        url = reverse('membership-list')
        
        # Normal user cannot create membership
        self.client.force_authenticate(user=self.normal_user)
        data = {
            "user": self.normal_user.pk,
            "company": self.company.pk,
            "role": Role.ACCOUNTANT
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        
        # Client admin can create membership
        self.client.force_authenticate(user=self.client_admin)
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
