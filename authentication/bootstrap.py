import logging
import os
import sys

from authentication.workos_service import bootstrap_owner_account

logger = logging.getLogger(__name__)

BOOTSTRAP_ENV_FIELDS = {
    "company_name": "BOOTSTRAP_COMPANY_NAME",
    "owner_email": "BOOTSTRAP_OWNER_EMAIL",
    "owner_password": "BOOTSTRAP_OWNER_PASSWORD",
    "owner_name": "BOOTSTRAP_OWNER_NAME",
}
REQUIRED_BOOTSTRAP_FIELDS = ("company_name", "owner_email", "owner_password")


def bootstrap_config_from_environment():
    config = {}
    for field, env_name in BOOTSTRAP_ENV_FIELDS.items():
        value = os.environ.get(env_name, "") or ""
        if field != "owner_password":
            value = value.strip()
        config[field] = value
    return config


def missing_bootstrap_environment(config):
    return [
        BOOTSTRAP_ENV_FIELDS[field]
        for field in REQUIRED_BOOTSTRAP_FIELDS
        if not config.get(field)
    ]


def bootstrap_owner_from_environment(*, if_configured=False):
    config = bootstrap_config_from_environment()
    missing = missing_bootstrap_environment(config)
    if missing:
        if if_configured:
            configured = any(config.values())
            if configured:
                logger.warning(
                    "Owner bootstrap skipped; missing required env vars: %s",
                    ", ".join(missing),
                )
            return None
        raise ValueError(f"Missing required bootstrap values: {', '.join(missing)}")

    return bootstrap_owner_account(**config)


def is_test_process():
    return "pytest" in sys.modules or "test" in sys.argv


def bootstrap_owner_after_migrate(sender, **kwargs):
    if is_test_process():
        return

    result = bootstrap_owner_from_environment(if_configured=True)
    if result:
        logger.info(
            "Owner bootstrap completed after migrations for company %s and owner %s.",
            result["company"].name,
            result["user"].email,
        )
