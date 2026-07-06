from collections import OrderedDict

from django.core.exceptions import ValidationError
from import_export import fields, resources
from import_export.widgets import BooleanWidget, Widget

from core.models import City, CompanyOffice, MasterScope, Party, State
from core.policies import active_master_scope


def scoped_manager(model):
    return getattr(model, "unscoped_objects", model.objects)


class ScopedForeignKeyWidget(Widget):
    def __init__(self, model, lookup_fields=("id",), company_scoped=False, extra_filters=None):
        self.model = model
        self.lookup_fields = lookup_fields
        self.company_scoped = company_scoped
        self.extra_filters = extra_filters or {}

    def get_queryset(self, **kwargs):
        qs = scoped_manager(self.model).all()
        company = kwargs.get("company")
        if self.company_scoped and company and hasattr(self.model, "company_id"):
            qs = qs.filter(company=company)
        if self.extra_filters:
            qs = qs.filter(**self.extra_filters)
        return qs

    def clean(self, value, row=None, **kwargs):
        value = super().clean(value)
        if value in (None, ""):
            return None

        qs = self.get_queryset(**kwargs)
        for field_name in self.lookup_fields:
            lookup = f"{field_name}__iexact" if isinstance(value, str) and field_name != "id" else field_name
            match = qs.filter(**{lookup: str(value).strip()}).first()
            if match:
                return match
        try:
            return qs.get(pk=value)
        except (self.model.DoesNotExist, ValueError, TypeError):
            raise ValidationError(
                f'Could not resolve {self.model._meta.verbose_name} for value "{value}".'
            )

    def render(self, value, obj=None, **kwargs):
        if value is None:
            return ""
        return getattr(value, "pk", value)


class ImportExportBaseResource(resources.ModelResource):
    class Meta:
        skip_unchanged = True
        report_skipped = True
        clean_model_instances = True
        use_transactions = True

    def __init__(self, *args, company=None, user=None, office=None, role=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        self.user = user
        self.office = office
        self.role = role

    def normalize_row(self, row):
        for key, value in list(row.items()):
            if isinstance(value, str):
                cleaned = value.strip()
                row[key] = cleaned if cleaned != "" else None

    def before_import_row(self, row, **kwargs):
        self.normalize_row(row)

    def get_context_value(self, name, kwargs):
        return kwargs.get(name) or getattr(self, name)

    def clean_field(self, field_name, row, **kwargs):
        field = self.fields[field_name]
        if field.column_name not in row:
            return None
        return field.clean(row, **kwargs)

    def queryset(self):
        return scoped_manager(self._meta.model).all()

    def is_existing_instance(self, instance):
        return bool(instance.pk and self.queryset().filter(pk=instance.pk).exists())


class CompanyScopedResourceMixin:
    def apply_company_scope(self, instance, **kwargs):
        company = self.get_context_value("company", kwargs)
        if company and hasattr(instance, "company_id") and not instance.company_id:
            instance.company = company

        if hasattr(instance, "scope_type") and not self.is_existing_instance(instance):
            role = self.get_context_value("role", kwargs)
            office = self.get_context_value("office", kwargs)
            scope_type, scope_id = active_master_scope(role=role, office=office)
            instance.scope_type = scope_type
            instance.scope_id = scope_id

    def after_init_instance(self, instance, new, row, **kwargs):
        super().after_init_instance(instance, new, row, **kwargs)
        self.apply_company_scope(instance, **kwargs)

    def before_save_instance(self, instance, row, **kwargs):
        super().before_save_instance(instance, row, **kwargs)
        self.apply_company_scope(instance, **kwargs)

    def get_company_queryset(self):
        company = self.company
        qs = self.queryset()
        if company and hasattr(self._meta.model, "company_id"):
            qs = qs.filter(company=company)
        return qs

    def scope_filter(self):
        role = self.role
        office = self.office
        scope_type, scope_id = active_master_scope(role=role, office=office)
        if scope_type == MasterScope.COMPANY:
            return {"scope_type": scope_type, "scope_id__isnull": True}
        return {"scope_type": scope_type, "scope_id": scope_id}


class StateResource(ImportExportBaseResource):
    is_active = fields.Field(attribute="is_active", widget=BooleanWidget())

    class Meta(ImportExportBaseResource.Meta):
        model = State
        fields = ("id", "name", "code", "is_active")
        export_order = fields

    def get_instance(self, instance_loader, row):
        instance = super().get_instance(instance_loader, row)
        if instance:
            return instance
        code = row.get("code")
        if code:
            return State.unscoped_objects.filter(code__iexact=code).first()
        return None


class CityResource(ImportExportBaseResource):
    state = fields.Field(
        column_name="state",
        attribute="state",
        widget=ScopedForeignKeyWidget(State, lookup_fields=("id", "code", "name")),
    )
    is_active = fields.Field(attribute="is_active", widget=BooleanWidget())

    class Meta(ImportExportBaseResource.Meta):
        model = City
        fields = ("id", "name", "state", "is_active")
        export_order = fields

    def get_instance(self, instance_loader, row):
        instance = super().get_instance(instance_loader, row)
        if instance:
            return instance
        name = row.get("name")
        state = self.clean_field("state", row) if row.get("state") else None
        if name and state:
            return City.unscoped_objects.filter(name__iexact=name, state=state).first()
        return None


class CompanyOfficeResource(CompanyScopedResourceMixin, ImportExportBaseResource):
    city = fields.Field(
        column_name="city",
        attribute="city",
        widget=ScopedForeignKeyWidget(City, lookup_fields=("id", "name")),
    )
    is_active = fields.Field(attribute="is_active", widget=BooleanWidget())

    class Meta(ImportExportBaseResource.Meta):
        model = CompanyOffice
        fields = (
            "id",
            "name",
            "city",
            "address",
            "gst_number",
            "contact_name",
            "phone",
            "status",
            "notes",
            "is_active",
        )
        export_order = fields

    def get_instance(self, instance_loader, row):
        instance = super().get_instance(instance_loader, row)
        if instance:
            return instance
        name = row.get("name")
        if not name:
            return None
        return self.get_company_queryset().filter(name__iexact=name, **self.scope_filter()).first()


class PartyResource(CompanyScopedResourceMixin, ImportExportBaseResource):
    city = fields.Field(
        column_name="city",
        attribute="city",
        widget=ScopedForeignKeyWidget(City, lookup_fields=("id", "name")),
    )
    is_active = fields.Field(attribute="is_active", widget=BooleanWidget())

    class Meta(ImportExportBaseResource.Meta):
        model = Party
        fields = ("id", "name", "phone", "address", "city", "gst_number", "is_active")
        export_order = fields

    def get_instance(self, instance_loader, row):
        instance = super().get_instance(instance_loader, row)
        if instance:
            return instance
        name = row.get("name")
        phone = row.get("phone")
        if not name or not phone:
            return None
        return self.get_company_queryset().filter(
            name__iexact=name,
            phone=str(phone).strip(),
            **self.scope_filter(),
        ).first()


MASTER_IMPORT_EXPORT_RESOURCES = OrderedDict(
    [
        ("states", StateResource),
        ("cities", CityResource),
        ("offices", CompanyOfficeResource),
        ("parties", PartyResource),
    ]
)
