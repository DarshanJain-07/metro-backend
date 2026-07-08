from django.apps import AppConfig


class AuthenticationConfig(AppConfig):
    name = 'authentication'

    def ready(self):
        from django.db.models.signals import post_migrate

        from authentication.bootstrap import bootstrap_owner_after_migrate

        post_migrate.connect(
            bootstrap_owner_after_migrate,
            sender=self,
            dispatch_uid="authentication.bootstrap_owner_after_migrate",
        )
