from django.core.cache import caches
from rest_framework import status, generics
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.throttling import AnonRateThrottle
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.signals import user_logged_in
from django.db import transaction
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken
from .serializers import UserSerializer, ChangePasswordSerializer

User = get_user_model()

class LoginThrottle(AnonRateThrottle):
    scope = 'login_attempts'
    cache = caches['throttle']

class LoginView(generics.GenericAPIView):
    permission_classes = [AllowAny]
    throttle_classes = [LoginThrottle]
    serializer_class = TokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.user
        
        # FIX: Resolve N+1 query issue for the UserSerializer relations
        user_with_relations = User.objects.select_related('company', 'branch').get(pk=user.pk)

        # Log the login action (triggers Django signals, useful for Audit Trails)
        user_logged_in.send(sender=user_with_relations.__class__, request=request, user=user_with_relations)
        
        return Response({
            'access': serializer.validated_data['access'],
            'refresh': serializer.validated_data['refresh'],
            'user': UserSerializer(user_with_relations).data
        })

class ChangePasswordView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ChangePasswordSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        user = request.user
        if not user.check_password(serializer.validated_data['old_password']):
            return Response({"old_password": ["Wrong password."]}, status=status.HTTP_400_BAD_REQUEST)
        
        with transaction.atomic():
            user.set_password(serializer.validated_data['new_password'])
            user.save()
            
            # Keep the user's browser session alive (e.g., for Django Admin)
            update_session_auth_hash(request, user)

            outstanding_tokens = OutstandingToken.objects.filter(user=user)
            BlacklistedToken.objects.bulk_create(
                [BlacklistedToken(token=t) for t in outstanding_tokens],
                ignore_conflicts=True
            )

            refresh = RefreshToken.for_user(user)
        
        return Response({
            "detail": "Password has been updated successfully.",
            "access": str(refresh.access_token),
            "refresh": str(refresh),
        }, status=status.HTTP_200_OK)
