from django.contrib.auth.backends import BaseBackend
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import models
from .models import LoginOTP

User = get_user_model()

class EmailOnlyBackend(BaseBackend):
    """
    Custom authentication backend that allows login with email only (no password).
    This is used for the passwordless registration system.
    """
    
    def authenticate(self, request, username=None, password=None, **kwargs):
        """
        Authenticate user by email (username field contains email).
        Password is ignored for this backend.
        """
        if username:
            try:
                # Try to get user by email or username (since we store email as username)
                user = User.objects.get(
                    models.Q(email=username) | models.Q(username=username)
                )
                # Check if user has a profile and is a frontend user
                if hasattr(user, 'profile') and user.profile.user_type == 'frontend':
                    return user
                elif not hasattr(user, 'profile'):
                    # Create profile if it doesn't exist
                    from .models import UserProfile
                    UserProfile.objects.create(user=user, user_type='frontend')
                    return user
            except User.DoesNotExist:
                return None
        return None
    
    def get_user(self, user_id):
        """
        Retrieve user by ID.
        """
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None


class OTPBackend(BaseBackend):
    """
    Custom authentication backend for OTP-based login.
    """
    
    def authenticate(self, request, email=None, otp_code=None, **kwargs):
        """
        Authenticate user using email and OTP code.
        """
        if email and otp_code:
            try:
                # Try to get user by email or username
                user = User.objects.get(
                    models.Q(email=email) | models.Q(username=email)
                )
                
                # Check if user has a profile and is a frontend user
                if not (hasattr(user, 'profile') and user.profile.user_type == 'frontend'):
                    return None
                
                # Get the most recent valid OTP for this user
                otp = LoginOTP.objects.filter(
                    user=user,
                    email=email,
                    is_used=False
                ).order_by('-created_at').first()
                
                if otp and otp.verify(otp_code):
                    return user
                    
            except User.DoesNotExist:
                return None
            except Exception:
                return None
        
        return None
    
    def get_user(self, user_id):
        """
        Retrieve user by ID.
        """
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
