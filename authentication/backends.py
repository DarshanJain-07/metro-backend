from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model

User = get_user_model()

class CaseInsensitiveModelBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(User.USERNAME_FIELD)
        try:
            # Use __iexact for case-insensitive lookup
            case_insensitive_username_field = '{}__iexact'.format(User.USERNAME_FIELD)
            users = User.objects.filter(**{case_insensitive_username_field: username})
            
            # If multiple users found, this is a data integrity error (should be prevented by DB constraint)
            # In such case, we shouldn't arbitrarily pick one.
            if users.count() > 1:
                # Log this or handle appropriately. For now, we fail to authenticate.
                return None
            
            user = users.first()
        except Exception:
            # Although filter(...).first() shouldn't raise DoesNotExist or MultipleObjectsReturned, 
            # we keep a generic catch just in case of unexpected DB issues during lookup.
            user = None
            
        if user:
            if user.check_password(password) and self.user_can_authenticate(user):
                return user
        else:
            # Run the default password hasher once to reduce the timing
            # difference between an existing and a nonexistent user (Security Best Practice)
            User().set_password(password)
            return None
