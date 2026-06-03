from rest_framework import serializers

from .models import Branch, City, Party, State


class StateSerializer(serializers.ModelSerializer):
    class Meta:
        model = State
        fields = ('id', 'name', 'code', 'is_active', 'created_at', 'updated_at')
        read_only_fields = ('id', 'created_at', 'updated_at')


class CitySerializer(serializers.ModelSerializer):
    state_code = serializers.ReadOnlyField(source='state.code')
    state_name = serializers.ReadOnlyField(source='state.name')

    class Meta:
        model = City
        fields = ('id', 'name', 'state', 'state_name', 'state_code', 'is_active', 'created_at', 'updated_at')
        read_only_fields = ('id', 'state_name', 'state_code', 'created_at', 'updated_at')


class BranchSerializer(serializers.ModelSerializer):
    city_name = serializers.ReadOnlyField(source='city.name')
    state_code = serializers.ReadOnlyField(source='city.state.code')

    class Meta:
        model = Branch
        fields = ('id', 'name', 'city', 'city_name', 'state_code', 'is_active', 'created_at', 'updated_at')
        read_only_fields = ('id', 'city_name', 'state_code', 'created_at', 'updated_at')


class PartySerializer(serializers.ModelSerializer):
    city_name = serializers.ReadOnlyField(source='city.name')
    state_code = serializers.ReadOnlyField(source='city.state.code')

    class Meta:
        model = Party
        fields = (
            'id', 'name', 'phone', 'address', 'city', 'city_name',
            'state_code', 'gst_number', 'is_active', 'created_at', 'updated_at',
        )
        read_only_fields = ('id', 'city_name', 'state_code', 'created_at', 'updated_at')
