import hashlib
import json

from django.db import models
from rest_framework import serializers, status
from rest_framework.exceptions import APIException
from rest_framework.response import Response


class PreconditionFailed(APIException):
    status_code = status.HTTP_412_PRECONDITION_FAILED
    default_detail = "The record has been updated by another user. Please refresh and try again."
    default_code = "precondition_failed"


class ConflictException(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "A different request was already made with this idempotency key."
    default_code = "idempotency_conflict"


class TenantOfficeScopedQuerysetMixin:
    office_scope_permission = None
    office_scope_fields = ("origin_office", "destination_office")

    def get_queryset(self):
        return self.apply_office_scope(super().get_queryset())

    def apply_office_scope(self, qs):
        user = getattr(self.request, "user", None)
        if not user or not user.is_authenticated:
            return qs.none()

        from core.models import Role
        from core.policies import active_office_ids, has_role
        from core.request_context import get_current_company

        if user.is_superuser or has_role(user, roles=[Role.PLATFORM_ADMIN]):
            return qs

        company = get_current_company()
        if company and hasattr(qs.model, "company"):
            qs = qs.filter(company=company)

        if company and has_role(user, company=company, roles=[Role.CLIENT_SUPER_ADMIN]):
            return qs

        if self.office_scope_permission and user.has_perm(self.office_scope_permission):
            return qs

        office_ids = active_office_ids(user, company)
        if not office_ids:
            return qs.none()

        office_filter = models.Q()
        for field_name in self.office_scope_fields:
            office_filter |= models.Q(**{f"{field_name}__in": office_ids})
        return qs.filter(office_filter)


class SoftDeleteMixin:
    soft_delete_field = "is_active"

    def perform_destroy(self, instance):
        setattr(instance, self.soft_delete_field, False)
        instance.save(update_fields=[self.soft_delete_field])


class OptimisticConcurrencyMixin:
    concurrency_field = "updated_at"

    def perform_update(self, serializer):
        self.check_precondition(serializer.instance)
        serializer.save()

    def check_precondition(self, instance):
        if self.request.method not in ("PUT", "PATCH"):
            return
        client_value = self.request.data.get(self.concurrency_field)
        if not client_value:
            raise PreconditionFailed(detail=f"Missing {self.concurrency_field} for concurrency check.")
        try:
            parsed_client_value = serializers.DateTimeField().to_internal_value(client_value)
        except serializers.ValidationError:
            raise PreconditionFailed(detail=f"Invalid {self.concurrency_field} format for concurrency check.")
        if getattr(instance, self.concurrency_field) != parsed_client_value:
            raise PreconditionFailed()


class IdempotentCreateMixin:
    idempotency_key_field = "idempotency_key"
    idempotency_hash_field = "idempotency_hash"
    idempotency_header = "X-Idempotency-Key"

    def create(self, request, *args, **kwargs):
        idempotency_key = self.get_idempotency_key()
        if not idempotency_key:
            return super().create(request, *args, **kwargs)

        request_hash = self.get_idempotency_hash()
        existing = self.get_existing_idempotent_object(idempotency_key)
        if existing:
            existing_hash = getattr(existing, self.idempotency_hash_field, None)
            if existing_hash != request_hash:
                raise ConflictException()
            serializer = self.get_serializer(existing)
            return Response(serializer.data, status=status.HTTP_201_CREATED, headers={"X-Idempotency-Hit": "true"})

        self._idempotency_values = {
            self.idempotency_key_field: idempotency_key,
            self.idempotency_hash_field: request_hash,
        }
        try:
            return super().create(request, *args, **kwargs)
        finally:
            self._idempotency_values = None

    def get_idempotency_key(self):
        return self.request.data.get(self.idempotency_key_field) or self.request.headers.get(self.idempotency_header) or None

    def get_idempotency_hash(self):
        data = self.normalize_idempotency_data(self.request.data)
        payload = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def normalize_idempotency_data(self, value):
        if isinstance(value, dict):
            return {
                key: self.normalize_idempotency_data(item)
                for key, item in value.items()
                if key != self.idempotency_hash_field
            }
        if isinstance(value, list):
            return [self.normalize_idempotency_data(item) for item in value]
        return value

    def get_existing_idempotent_object(self, idempotency_key):
        return self.get_queryset().filter(**{self.idempotency_key_field: idempotency_key}).first()

    def get_idempotency_save_kwargs(self):
        return getattr(self, "_idempotency_values", None) or {}
