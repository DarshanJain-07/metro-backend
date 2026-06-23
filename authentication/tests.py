from unittest.mock import patch

from django.test import override_settings
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from authentication.models import AuthAuditLog
from authentication.workos_service import WorkOSPendingAuthentication
from core.models import City, Company, CompanyOffice, GlobalOffice, Role, State, User, UserMembership
from core.policies import can

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

        self.owner = User.objects.create_user(
            username="owner",
            password="password",
            company=self.company,
            is_owner=True,
        )
        UserMembership.objects.create(user=self.owner, company=self.company, role=Role.SUPER_ADMIN)

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

    def test_super_admin_can_create_user_with_default_branch_shorthand(self):
        self.client.force_authenticate(user=self.super_admin)
        url = reverse('user-list')
        data = {
            "username": "branch_user",
            "password": "StrongPass123!",
            "email": "branch_user@test.com",
            "role": Role.VIEWER,
            "branch": self.office.id,
        }
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(username="branch_user")
        self.assertEqual(user.office_id, self.office.id)
        self.assertTrue(
            UserMembership.objects.filter(
                user=user,
                company=self.company,
                office=self.office,
                role=Role.VIEWER,
                is_active=True,
            ).exists()
        )

    def test_owner_can_create_metro_user_without_branch(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            reverse("user-list"),
            {
                "username": "metro_creator",
                "password": "StrongPass123!",
                "email": "metro_creator@test.com",
                "role": Role.METRO,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(username="metro_creator")
        self.assertTrue(UserMembership.objects.filter(user=user, company=self.company, role=Role.METRO).exists())
        self.assertTrue(can(user, "users:edit", company=self.company))

    def test_super_admin_cannot_demote_metro_user(self):
        metro_user = User.objects.create_user(username="metro_user", password="password", company=self.company)
        UserMembership.objects.create(user=metro_user, company=self.company, role=Role.METRO)

        self.client.force_authenticate(user=self.super_admin)
        response = self.client.patch(
            reverse("user-detail", kwargs={"pk": metro_user.pk}),
            {"role": Role.VIEWER, "branch": self.office.id},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        metro_user.refresh_from_db()
        self.assertTrue(UserMembership.objects.filter(user=metro_user, company=self.company, role=Role.METRO).exists())

    def test_metro_role_permissions_are_immutable(self):
        self.client.force_authenticate(user=self.owner)

        roles_response = self.client.get(reverse("role-list"))
        self.assertEqual(roles_response.status_code, status.HTTP_200_OK)
        self.assertIn(Role.METRO, {item["code"] for item in roles_response.data})

        permissions_response = self.client.get(reverse("company-role-permission-list"), {"role": Role.METRO})
        self.assertEqual(permissions_response.status_code, status.HTTP_200_OK)
        self.assertEqual(permissions_response.data[0]["permissions"], [{"code": "*", "scope": "all"}])

        override_response = self.client.post(
            reverse("company-role-override-list"),
            {
                "role": Role.METRO,
                "permission_code": "users:edit",
                "enabled": False,
                "scope": "company",
            },
            format="json",
        )
        self.assertEqual(override_response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_assignable_branches_use_owner_company_not_office_type(self):
        own_global = GlobalOffice.objects.create(
            name="Own Partner-Marked Hub",
            city=self.city,
            owner_company=self.company,
        )
        own_partner_marked_office = CompanyOffice.objects.create(
            company=self.company,
            global_office=own_global,
            name="Own Partner-Marked Hub",
            city=self.city,
            office_type=CompanyOffice.OfficeType.PARTNER,
        )
        partner_company = Company.objects.create(name="Partner Company")
        partner_global = GlobalOffice.objects.create(
            name="Partner Hub",
            city=self.city,
            owner_company=partner_company,
        )
        partner_office = CompanyOffice.objects.create(
            company=self.company,
            global_office=partner_global,
            name="Partner Hub",
            city=self.city,
            office_type=CompanyOffice.OfficeType.PARTNER,
        )

        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(reverse("user-assignable-branches"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        branch_ids = {item["id"] for item in response.data}
        self.assertIn(self.office.id, branch_ids)
        self.assertIn(own_partner_marked_office.id, branch_ids)
        self.assertNotIn(partner_office.id, branch_ids)

    def test_user_create_rejects_partner_discovery_default_branch(self):
        partner_company = Company.objects.create(name="Partner Company")
        partner_global = GlobalOffice.objects.create(
            name="Partner Hub",
            city=self.city,
            owner_company=partner_company,
        )
        partner_office = CompanyOffice.objects.create(
            company=self.company,
            global_office=partner_global,
            name="Partner Hub",
            city=self.city,
            office_type=CompanyOffice.OfficeType.PARTNER,
        )

        self.client.force_authenticate(user=self.super_admin)
        response = self.client.post(
            reverse("user-list"),
            {
                "username": "partner_branch_user",
                "password": "StrongPass123!",
                "email": "partner_branch_user@test.com",
                "role": Role.VIEWER,
                "branch": partner_office.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("branch", response.data)

    def test_normal_user_can_list_users(self):
        self.client.force_authenticate(user=self.normal_user)
        url = reverse('user-list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should only see users in their company
        self.assertTrue(len(response.data['results']) >= 2) # super_admin and normal_user

    def test_inactive_default_branch_serializes_as_none(self):
        self.office.is_active = False
        self.office.save(update_fields=["is_active", "updated_at"])

        self.client.force_authenticate(user=self.super_admin)
        response = self.client.get(reverse("user-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        users = response.data["results"]
        normal_user = next(item for item in users if item["id"] == self.normal_user.id)
        self.assertIsNone(normal_user["branch"])
        self.assertIsNone(normal_user["branch_name"])
        self.assertIsNone(normal_user["office_name"])

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
        self.assertFalse(self.normal_user.has_usable_password())

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
        self.assertFalse(self.branch_admin.has_usable_password())

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


@override_settings(
    WORKOS_API_KEY="",
    WORKOS_CLIENT_ID="",
    WORKOS_AUTO_PROVISION_USERS=False,
)
class WorkOSAuthIntegrationTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(
            name="WorkOS Company",
            workos_organization_id="org_123",
        )
        self.state = State.objects.create(name="WorkOS State", code="WS")
        self.city = City.objects.create(name="WorkOS City", state=self.state)
        self.office = CompanyOffice.objects.create(company=self.company, name="WorkOS Office", city=self.city)
        self.user = User.objects.create_user(
            username="workos_user",
            email="worker@example.com",
            password="legacy-password",
            company=self.company,
            office=self.office,
        )
        UserMembership.objects.create(
            user=self.user,
            company=self.company,
            office=self.office,
            role=Role.VIEWER,
        )

    def workos_auth_response(self, user_id="user_123", email="worker@example.com"):
        return {
            "user": {
                "id": user_id,
                "email": email,
                "first_name": "WorkOS",
                "last_name": "User",
            },
            "organization_id": "org_123",
        }

    def workos_membership(self, role_slug="viewer", status_value="active"):
        return {
            "id": "om_123",
            "status": status_value,
            "role_slug": role_slug,
        }

    @patch("authentication.workos_service.list_workos_memberships")
    @patch("authentication.views.authenticate_with_password")
    def test_password_login_syncs_workos_user_and_issues_metro_tokens(self, authenticate_with_password, list_memberships):
        authenticate_with_password.return_value = self.workos_auth_response()
        list_memberships.return_value = [self.workos_membership()]

        response = self.client.post(
            reverse("login_password"),
            {"identifier": "worker@example.com", "password": "workos-password"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        self.user.refresh_from_db()
        self.assertEqual(self.user.workos_user_id, "user_123")
        self.assertFalse(self.user.has_usable_password())
        membership = self.user.memberships.get(company=self.company, office=self.office)
        self.assertEqual(membership.workos_organization_membership_id, "om_123")
        self.assertEqual(membership.workos_role_slug, "viewer")
        self.assertTrue(AuthAuditLog.objects.filter(event_type="auth.login.password", status="SUCCESS").exists())

    @patch("authentication.views.authenticate_with_password")
    def test_password_login_returns_pending_mfa_state(self, authenticate_with_password):
        authenticate_with_password.side_effect = WorkOSPendingAuthentication(
            {
                "status": "pending",
                "type": "mfa_challenge",
                "pending_authentication_token": "pat_123",
                "authentication_factors": [{"id": "auth_factor_123", "type": "totp"}],
            }
        )

        response = self.client.post(
            reverse("login_password"),
            {"identifier": "worker@example.com", "password": "workos-password"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.data["type"], "mfa_challenge")
        self.assertEqual(response.data["pending_authentication_token"], "pat_123")
        self.assertTrue(AuthAuditLog.objects.filter(event_type="auth.login.password", status="PENDING").exists())

    @patch("authentication.views.authenticate_with_password")
    def test_unknown_workos_user_is_rejected_without_auto_provisioning(self, authenticate_with_password):
        authenticate_with_password.return_value = self.workos_auth_response(
            user_id="user_unknown",
            email="unknown@example.com",
        )

        response = self.client.post(
            reverse("login_password"),
            {"identifier": "unknown@example.com", "password": "workos-password"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(User.objects.filter(email="unknown@example.com").exists())
        self.assertTrue(AuthAuditLog.objects.filter(event_type="auth.login.password", status="FAILURE").exists())

    @patch("authentication.workos_service.list_workos_memberships")
    @patch("authentication.workos_service.get_workos_user")
    @patch("authentication.views.get_current_company")
    def test_deprovisioned_workos_user_loses_access_on_sync(self, get_current_company, get_workos_user, list_memberships):
        self.user.workos_user_id = "user_123"
        self.user.set_unusable_password()
        self.user.save(update_fields=["workos_user_id", "password"])
        get_current_company.return_value = self.company
        get_workos_user.return_value = self.workos_auth_response()["user"]
        list_memberships.return_value = []

        self.client.force_authenticate(user=self.user)
        response = self.client.post(reverse("auth_sync"), {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(UserMembership.unscoped_objects.get(user=self.user, company=self.company).is_active)
        self.assertTrue(AuthAuditLog.objects.filter(event_type="auth.sync", status="FAILURE").exists())

    def test_legacy_django_password_login_is_deprecated(self):
        response = self.client.post(
            reverse("login"),
            {"username": "workos_user", "password": "legacy-password"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_410_GONE)
