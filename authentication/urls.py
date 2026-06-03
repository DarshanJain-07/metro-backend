from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView
from .views import LoginView, ChangePasswordView, UserViewSet, UserMembershipViewSet

router = DefaultRouter()
router.register(r'users', UserViewSet, basename='user')
router.register(r'memberships', UserMembershipViewSet, basename='membership')

urlpatterns = [
    path('login/', LoginView.as_view(), name='login'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('token/verify/', TokenVerifyView.as_view(), name='token_verify'),
    path('change-password/', ChangePasswordView.as_view(), name='change_password'),
    path('', include(router.urls)),
]
