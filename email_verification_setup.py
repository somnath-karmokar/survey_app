#!/usr/bin/env python
"""
Email Verification Setup Script
Helps with testing the email verification system
"""

import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'survey_app.settings')
django.setup()

from django.contrib.auth.models import User
from surveys.models import EmailVerification, UserProfile
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from datetime import timedelta

def test_email_configuration():
    """Test if email configuration is working"""
    print("\n" + "="*50)
    print("Testing Email Configuration")
    print("="*50)
    
    print(f"\nEmail Backend: {settings.EMAIL_BACKEND}")
    print(f"Email Host: {settings.EMAIL_HOST}")
    print(f"Email Port: {settings.EMAIL_PORT}")
    print(f"Email Use TLS: {settings.EMAIL_USE_TLS}")
    print(f"Default From Email: {settings.DEFAULT_FROM_EMAIL}")
    
    try:
        # Try to send a test email
        send_mail(
            'Test Email from Sudraw',
            'This is a test email to verify your email configuration is working correctly.',
            settings.DEFAULT_FROM_EMAIL,
            [settings.DEFAULT_FROM_EMAIL],
            fail_silently=False,
        )
        print("\n✓ Email configuration is working correctly!")
        return True
    except Exception as e:
        print(f"\n✗ Email configuration error: {e}")
        return False

def create_test_user():
    """Create a test user with email verification"""
    print("\n" + "="*50)
    print("Creating Test User")
    print("="*50)
    
    username = input("\nEnter username (default: testuser): ").strip() or "testuser"
    email = input("Enter email address: ").strip()
    
    if not email:
        print("✗ Email is required!")
        return None
    
    try:
        # Check if user already exists
        if User.objects.filter(username=username).exists():
            print(f"✗ User '{username}' already exists!")
            return None
        
        if User.objects.filter(email=email).exists():
            print(f"✗ Email '{email}' is already registered!")
            return None
        
        # Create user
        user = User.objects.create_user(
            username=username,
            email=email,
            password='TestPassword123!',
            first_name='Test',
            last_name='User'
        )
        user.is_active = False
        user.save()
        
        # Create profile
        UserProfile.objects.get_or_create(
            user=user,
            defaults={
                'user_type': 'frontend',
                'email_verified': False
            }
        )
        
        # Generate email verification token
        email_verification = EmailVerification.generate_token(user, email)
        
        print(f"\n✓ Test user created successfully!")
        print(f"  Username: {username}")
        print(f"  Email: {email}")
        print(f"  Password: TestPassword123!")
        print(f"  Account Status: Inactive (awaiting email verification)")
        print(f"\n  Verification Token: {email_verification.token}")
        print(f"  Token Expires: {email_verification.expires_at}")
        
        return user
    
    except Exception as e:
        print(f"\n✗ Error creating test user: {e}")
        return None

def list_unverified_users():
    """List all unverified users"""
    print("\n" + "="*50)
    print("Unverified Users")
    print("="*50)
    
    unverified = UserProfile.objects.filter(email_verified=False)
    
    if not unverified.exists():
        print("\n✓ All users are verified!")
        return
    
    print(f"\nFound {unverified.count()} unverified users:\n")
    
    for profile in unverified:
        user = profile.user
        has_token = hasattr(user, 'email_verification')
        token_status = "Valid" if (has_token and user.email_verification.is_valid()) else "Expired/None"
        
        print(f"  • {user.username} ({user.email})")
        print(f"    Status: Not Verified (Account: {'Active' if user.is_active else 'Inactive'})")
        print(f"    Token: {token_status}")
        print()

def verify_user_email():
    """Manually verify a user's email"""
    print("\n" + "="*50)
    print("Manually Verify User Email")
    print("="*50)
    
    username = input("\nEnter username to verify: ").strip()
    
    try:
        user = User.objects.get(username=username)
        
        if not hasattr(user, 'email_verification'):
            print(f"✗ No email verification token found for {username}")
            return
        
        email_verification = user.email_verification
        
        if email_verification.is_verified:
            print(f"✓ {username}'s email is already verified!")
            return
        
        # Verify email
        if email_verification.verify():
            print(f"\n✓ Email verified successfully!")
            print(f"  User: {username}")
            print(f"  Email: {user.email}")
            print(f"  Account Status: Active")
            print(f"  User can now log in!")
        else:
            print(f"✗ Verification failed (token expired?)")
            print(f"  Token Expires: {email_verification.expires_at}")
    
    except User.DoesNotExist:
        print(f"✗ User '{username}' not found!")

def show_verification_stats():
    """Show email verification statistics"""
    print("\n" + "="*50)
    print("Email Verification Statistics")
    print("="*50)
    
    total_users = User.objects.filter(is_staff=False, is_superuser=False).count()
    verified_users = UserProfile.objects.filter(email_verified=True).count()
    unverified_users = UserProfile.objects.filter(email_verified=False).count()
    
    total_tokens = EmailVerification.objects.count()
    verified_tokens = EmailVerification.objects.filter(is_verified=True).count()
    pending_tokens = EmailVerification.objects.filter(is_verified=False).count()
    expired_tokens = EmailVerification.objects.filter(
        is_verified=False,
        expires_at__lt=timezone.now()
    ).count()
    
    print(f"\nUser Statistics:")
    print(f"  Total Users (non-staff): {total_users}")
    print(f"  Verified Emails: {verified_users} ({verified_users*100//total_users if total_users else 0}%)")
    print(f"  Unverified Emails: {unverified_users}")
    
    print(f"\nToken Statistics:")
    print(f"  Total Tokens: {total_tokens}")
    print(f"  Verified Tokens: {verified_tokens}")
    print(f"  Pending Tokens: {pending_tokens}")
    print(f"  Expired Tokens: {expired_tokens}")

def cleanup_expired_tokens():
    """Delete expired email verification tokens"""
    print("\n" + "="*50)
    print("Cleanup Expired Tokens")
    print("="*50)
    
    expired = EmailVerification.objects.filter(
        is_verified=False,
        expires_at__lt=timezone.now()
    )
    
    if not expired.exists():
        print("\n✓ No expired tokens to clean up!")
        return
    
    count = expired.count()
    confirm = input(f"\nDelete {count} expired tokens? (y/n): ").strip().lower()
    
    if confirm == 'y':
        expired.delete()
        print(f"✓ Deleted {count} expired tokens!")
    else:
        print("✗ Cleanup cancelled")

def main_menu():
    """Show main menu"""
    while True:
        print("\n" + "="*50)
        print("Email Verification Setup & Testing Tool")
        print("="*50)
        print("\n1. Test Email Configuration")
        print("2. Create Test User")
        print("3. List Unverified Users")
        print("4. Manually Verify User Email")
        print("5. Show Verification Statistics")
        print("6. Cleanup Expired Tokens")
        print("7. Exit")
        
        choice = input("\nSelect option (1-7): ").strip()
        
        if choice == '1':
            test_email_configuration()
        elif choice == '2':
            create_test_user()
        elif choice == '3':
            list_unverified_users()
        elif choice == '4':
            verify_user_email()
        elif choice == '5':
            show_verification_stats()
        elif choice == '6':
            cleanup_expired_tokens()
        elif choice == '7':
            print("\n✓ Goodbye!")
            break
        else:
            print("✗ Invalid option!")

if __name__ == '__main__':
    try:
        print("\nStarting Email Verification Setup Tool...")
        # Check if database is ready
        from django.db import connection
        with connection.cursor() as cursor:
            pass
        main_menu()
    except Exception as e:
        print(f"\n✗ Error: {e}")
        print("\nMake sure you have:")
        print("1. Applied migrations: python manage.py migrate")
        print("2. Django settings configured properly")
        print("3. Database is accessible")
