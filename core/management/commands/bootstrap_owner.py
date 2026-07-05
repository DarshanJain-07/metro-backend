import os

from django.core.management.base import BaseCommand, CommandError

from authentication.workos_service import bootstrap_owner_account


class Command(BaseCommand):
    help = "Create or update the first company owner from environment variables."

    def add_arguments(self, parser):
        parser.add_argument("--company", default=os.environ.get("BOOTSTRAP_COMPANY_NAME", ""))
        parser.add_argument("--email", default=os.environ.get("BOOTSTRAP_OWNER_EMAIL", ""))
        parser.add_argument("--password", default=os.environ.get("BOOTSTRAP_OWNER_PASSWORD", ""))
        parser.add_argument("--name", default=os.environ.get("BOOTSTRAP_OWNER_NAME", ""))
        parser.add_argument(
            "--if-configured",
            action="store_true",
            help="Exit successfully when bootstrap environment variables are not set.",
        )

    def handle(self, *args, **options):
        company = (options["company"] or "").strip()
        email = (options["email"] or "").strip()
        password = options["password"] or ""
        name = (options["name"] or "").strip()

        missing = [
            label
            for label, value in (
                ("BOOTSTRAP_COMPANY_NAME", company),
                ("BOOTSTRAP_OWNER_EMAIL", email),
                ("BOOTSTRAP_OWNER_PASSWORD", password),
            )
            if not value
        ]
        if missing:
            if options["if_configured"]:
                self.stdout.write("Owner bootstrap skipped; bootstrap env vars are not fully configured.")
                return
            raise CommandError(f"Missing required bootstrap values: {', '.join(missing)}")

        result = bootstrap_owner_account(
            company_name=company,
            owner_email=email,
            owner_password=password,
            owner_name=name,
        )
        self.stdout.write(self.style.SUCCESS("Owner bootstrap completed."))
        self.stdout.write(f"Company: {result['company'].name}")
        self.stdout.write(f"Owner: {result['user'].email}")
        self.stdout.write(f"Organization ID: {result['organization_id']}")
