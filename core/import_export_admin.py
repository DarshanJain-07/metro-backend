from core.request_context import get_current_company, get_current_office, get_current_role


class RequestContextResourceAdminMixin:
    def get_resource_kwargs(self, request, *args, **kwargs):
        resource_kwargs = super().get_resource_kwargs(request, *args, **kwargs)
        resource_kwargs.update(
            {
                "company": get_current_company(request.user) or getattr(request.user, "company", None),
                "user": request.user,
                "office": get_current_office(request.user) or getattr(request.user, "office", None),
                "role": get_current_role(),
            }
        )
        return resource_kwargs
