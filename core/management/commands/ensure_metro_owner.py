from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from core.models import Company, Role, RoleDefinition, UserMembership


DEFAULT_USERNAME = "metro"
DEFAULT_EMAIL = "metroexpress456@gmail.com"
DEFAULT_COMPANY = "Metro Logistics"


class Command(BaseCommand):
    help = "Creates or updates the built-in Metro owner account."

    def add_arguments(self, parser):
        parser.add_argument("--username", default=DEFAULT_USERNAME)
        parser.add_argument("--email", default=DEFAULT_EMAIL)
        parser.add_argument("--company", default=DEFAULT_COMPANY)

    def handle(self, *args, **options):
        username = options["username"].strip()
        email = options["email"].strip()
        company_name = options["company"].strip()

        if not username or not email or not company_name:
            raise CommandError("Metro owner username, email, and company are required.")

        company, _ = Company.objects.get_or_create(name=company_name)
        RoleDefinition.objects.update_or_create(
            code=Role.METRO,
            defaults={
                "name": "Metro",
                "workos_role_slug": "metro",
                "requires_office": False,
                "sort_order": 1,
                "is_active": True,
            },
        )

        User = get_user_model()
        user = User.objects.filter(username__iexact=username).first()
        if user is None:
            user = User.objects.filter(email__iexact=email).first()

        if user is None:
            user = User(username=username)

        user.username = username
        user.email = email
        user.first_name = user.first_name or "Metro"
        user.last_name = user.last_name or "Owner"
        user.company = company
        user.office = None
        user.is_owner = True
        user.set_unusable_password()
        user.save()

        user.memberships.filter(company=company).exclude(role=Role.METRO, office__isnull=True).update(is_active=False)
        membership, _ = UserMembership.objects.update_or_create(
            user=user,
            company=company,
            office=None,
            role=Role.METRO,
            defaults={"is_active": True},
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Ensured Metro owner {user.username} ({user.email}) in {company.name}; "
                f"role={membership.role}, branch=None."
            )
        )
