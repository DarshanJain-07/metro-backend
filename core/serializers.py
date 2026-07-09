from rest_framework import serializers

from .models import City, Company, CompanyOffice, GlobalOffice, OfficeStatus, Party, State


class StateSerializer(serializers.ModelSerializer):
    class Meta:
        model = State
        fields = ("id", "name", "code", "is_active", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")


class CitySerializer(serializers.ModelSerializer):
    state_code = serializers.ReadOnlyField(source="state.code")
    state_name = serializers.ReadOnlyField(source="state.name")

    class Meta:
        model = City
        fields = ("id", "name", "state", "state_name", "state_code", "is_active", "created_at", "updated_at")
        read_only_fields = ("id", "state_name", "state_code", "created_at", "updated_at")


class CompanyDiscoverySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = ("id", "name", "is_active", "created_at")
        read_only_fields = fields


class GlobalOfficeSerializer(serializers.ModelSerializer):
    city_name = serializers.ReadOnlyField(source="city.name")
    state_code = serializers.ReadOnlyField(source="city.state.code")
    owner_company_name = serializers.ReadOnlyField(source="owner_company.name")

    class Meta:
        model = GlobalOffice
        fields = (
            "id",
            "name",
            "city",
            "city_name",
            "state_code",
            "owner_company",
            "owner_company_name",
            "address",
            "contact_name",
            "phone",
            "status",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "city_name", "state_code", "owner_company_name", "created_at", "updated_at")


class CompanyOfficeSerializer(serializers.ModelSerializer):
    city_name = serializers.ReadOnlyField(source="city.name")
    state_code = serializers.ReadOnlyField(source="city.state.code")
    global_office_name = serializers.ReadOnlyField(source="global_office.name", default=None)
    owner_company_name = serializers.ReadOnlyField(source="global_office.owner_company.name", default=None)

    class Meta:
        model = CompanyOffice
        fields = (
            "id",
            "company",
            "global_office",
            "global_office_name",
            "owner_company_name",
            "name",
            "city",
            "city_name",
            "state_code",
            "address",
            "gst_number",
            "contact_name",
            "phone",
            "status",
            "notes",
            "scope_type",
            "scope_id",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "company",
            "global_office_name",
            "owner_company_name",
            "city_name",
            "state_code",
            "scope_type",
            "scope_id",
            "created_at",
            "updated_at",
        )

    def validate_gst_number(self, value):
        if value:
            return str(value).upper().strip()
        return value


class OfficeImportSerializer(serializers.Serializer):
    global_office = serializers.PrimaryKeyRelatedField(queryset=GlobalOffice.objects.filter(status=OfficeStatus.ACTIVE))
    office_type = serializers.ChoiceField(choices=CompanyOffice.OfficeType.choices, required=False)


class OwnerCompanyOfficeImportSerializer(serializers.Serializer):
    owner_company = serializers.CharField()
    office_type = serializers.ChoiceField(choices=CompanyOffice.OfficeType.choices, required=False)


class PartySerializer(serializers.ModelSerializer):
    city_name = serializers.ReadOnlyField(source="city.name")
    state_code = serializers.ReadOnlyField(source="city.state.code")

    class Meta:
        model = Party
        fields = (
            "id",
            "name",
            "phone",
            "address",
            "city",
            "city_name",
            "state_code",
            "gst_number",
            "scope_type",
            "scope_id",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "city_name", "state_code", "scope_type", "scope_id", "created_at", "updated_at")
