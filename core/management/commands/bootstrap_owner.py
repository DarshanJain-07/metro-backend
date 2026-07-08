import os

from django.core.management.base import BaseCommand, CommandError

from authentication.bootstrap import missing_bootstrap_environment
from authentication.workos_service import WorkOSConfigurationError, bootstrap_owner_account


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

        config = {
            "company_name": company,
            "owner_email": email,
            "owner_password": password,
            "owner_name": name,
        }
        missing = missing_bootstrap_environment(config)
        if missing:
            if options["if_configured"]:
                self.stdout.write("Owner bootstrap skipped; bootstrap env vars are not fully configured.")
                return
            raise CommandError(f"Missing required bootstrap values: {', '.join(missing)}")

        try:
            result = bootstrap_owner_account(**config)
        except (ValueError, WorkOSConfigurationError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS("Owner bootstrap completed."))
        self.stdout.write(f"Company: {result['company'].name}")
        self.stdout.write(f"Owner: {result['user'].email}")
        self.stdout.write(f"Organization ID: {result['organization_id']}")
