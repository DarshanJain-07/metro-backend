from rest_framework import permissions

from core.policies import (
    can,
    can_assign_delivery,
    can_book_shipment,
    can_cancel_shipment,
    can_dispatch_shipment,
    can_edit_shipment,
    can_manage_company,
    can_mark_delivered,
    can_receive_shipment,
    can_view_shipment,
)
from core.request_context import get_current_company, get_current_office


class StrictActionPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        action = getattr(view, "action", None)
        if action in ["list", "retrieve", "incoming", "events"]:
            return True
        if action == "create":
            company = get_current_company()
            office = get_current_office()
            if office:
                return can(request.user, "shipment:create", company=company, office=office)
            return can_manage_company(request.user, company)
        if action in ["book", "dispatch_shipment", "receive", "assign_delivery", "mark_delivered", "cancel"]:
            return True
        return True

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        action = getattr(view, "action", None)
        if action in ["retrieve", "events"]:
            return can_view_shipment(request.user, obj)
        if action in ["update", "partial_update"]:
            return can_edit_shipment(request.user, obj)
        if action == "destroy":
            return can_manage_company(request.user, obj.company)
        if action == "book":
            return can_book_shipment(request.user, obj)
        if action == "dispatch_shipment":
            return can_dispatch_shipment(request.user, obj, get_current_office() or obj.origin_office)
        if action == "cancel":
            return can_cancel_shipment(request.user, obj)
        if action == "receive":
            return can_receive_shipment(request.user, obj, get_current_office())
        if action == "assign_delivery":
            return can_assign_delivery(request.user, obj)
        if action == "mark_delivered":
            return can_mark_delivered(request.user, obj)
        return False


class IsCompanyAdminPermission(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if getattr(view, "action", None) in ["list", "retrieve"]:
            return True
        company = get_current_company()
        return can_manage_company(request.user, company)

    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_superuser:
            return True
        if getattr(view, "action", None) in ["list", "retrieve"]:
            return True
        company = getattr(obj, "company", None) or get_current_company()
        return can_manage_company(request.user, company)
