# Email Verification Registration System

## Overview

This document describes the improved registration process with email verification for the Sudraw. Users must now verify their email address before they can access the platform.

## How It Works

### Registration Flow

1. **User Registration** (`/signup/`)
   - User fills in all required registration fields
   - Form submitted to `SignUpView`
   - User account is created with `is_active=False`
   - `UserProfile` is created with `email_verified=False`
   - Email verification token is generated

2. **Send Verification Email**
   - Verification email sent to user's email address
   - Email contains a secure link with a unique token
   - Link valid for 24 hours
   - User redirected to pending verification page

3. **Pending Verification Page** (`/pending-verification/`)
   - Shows user their email address needs verification
   - Provides option to resend verification email
   - User can enter email to resend verification link

4. **Email Verification** (`/verify-email/<token>/`)
   - User clicks the verification link in email
   - System validates the token
   - Token must not be expired or already used
   - Upon successful verification:
     - `EmailVerification.is_verified` set to `True`
     - `UserProfile.email_verified` set to `True`
     - User `is_active` set to `True`
     - User redirected to login page

5. **Login**
   - System checks if user's email is verified during login
   - Unverified users cannot log in
   - Error message directing them to verify email

## Models

### EmailVerification Model

```python
class EmailVerification(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='email_verification')
    email = models.EmailField()
    token = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(blank=True, null=True)
```

### UserProfile Updates

- Added `email_verified` field (already exists)
- Used to track email verification status

## URL Routes

| URL | Name | View | Description |
|-----|------|------|-------------|
| `/signup/` | `surveys:signup` | `SignUpView` | User registration form |
| `/verify-email/<token>/` | `surveys:verify_email` | `VerifyEmailView` | Email verification endpoint |
| `/pending-verification/` | `surveys:pending_verification` | `PendingVerificationView` | Pending verification status page |
| `/login/` | `surveys:login` | `CustomLoginView` | User login (updated to check verification) |

## Views

### SignUpView (Updated)

**Changes:**
- User account created with `is_active=False`
- Email verification token generated automatically
- Verification email sent with secure link
- Redirects to pending verification page
- AJAX support included

**Key Method:** `send_verification_email()`
- Builds absolute verification URL
- Sends HTML email with verification link
- Includes expiration info

### VerifyEmailView (New)

**Purpose:** Handle email verification via token

**Process:**
1. Validates token exists and is valid
2. Checks token not expired
3. Marks email as verified
4. Activates user account
5. Updates user profile
6. Redirects to login

**Errors Handled:**
- Invalid/missing token
- Expired token
- Already verified email

### PendingVerificationView (New)

**GET Request:**
- Displays pending verification page
- User sees their email and instructions

**POST Request:**
- Allows resending verification email
- User enters their email address
- New verification token generated
- Email resent to user

### CustomLoginView (Updated)

**Changes:**
- Checks `email_verified` status before login
- Shows error if email not verified
- Redirects unverified users to pending verification page

## Templates

### pending_verification.html (New)

**Purpose:** Show pending verification status

**Features:**
- Clean, modern UI with gradient background
- Shows email verification instructions
- Resend email form
- Link back to login

### verify_email.html (New)

**Purpose:** Show verification result

**Features:**
- Animated loading state
- Success/error messages
- Links to login or signup

## Email Configuration

Verification emails use settings:
- `EMAIL_BACKEND`
- `EMAIL_HOST`
- `EMAIL_PORT`
- `EMAIL_HOST_USER`
- `EMAIL_HOST_PASSWORD`
- `DEFAULT_FROM_EMAIL`

Current settings use Office365 SMTP.

## Setup Instructions

### 1. Create Migration

```bash
python manage.py makemigrations surveys
python manage.py migrate
```

### 2. Verify Settings

Check `surveys/settings.py` has email configuration:

```python
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.office365.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = 'your-email@example.com'
EMAIL_HOST_PASSWORD = 'your-password'
DEFAULT_FROM_EMAIL = 'your-email@example.com'
```

### 3. Test Email Sending

```bash
python manage.py shell
```

```python
from django.core.mail import send_mail
send_mail(
    'Test Email',
    'This is a test email.',
    'your-email@example.com',
    ['recipient@example.com']
)
```

## Security Features

1. **Unique Tokens**: UUID-based, cryptographically secure
2. **Token Expiration**: 24-hour validity window
3. **One-Time Use**: Tokens deleted after verification
4. **Database Indexing**: Token indexed for fast lookup
5. **Account Activation**: User can't log in until verified
6. **Rate Limiting Ready**: Structure supports adding rate limiting

## User Experience Flow

```
User Registration
    ↓
Account Created (inactive)
    ↓
Verification Email Sent
    ↓
User Clicks Email Link
    ↓
Email Verified (account activated)
    ↓
User Can Log In
```

## Error Handling

| Error Scenario | User Experience |
|---|---|
| Invalid token | Error message, link to signup |
| Expired token | Error message, option to resend |
| Already verified | Info message, link to login |
| Email sending failure | Graceful error, can retry |
| Missing email | Required field validation |

## Admin Features

New admin interface available at Django admin:

```
Surveys > Email Verifications
```

Can view:
- All verification tokens
- Status (verified/pending)
- Creation and verification dates
- Associated user

## Testing

### Manual Testing Checklist

- [ ] User can register with valid data
- [ ] Verification email is sent
- [ ] Verification email contains correct link
- [ ] Clicking link verifies email
- [ ] User profile shows `email_verified=True`
- [ ] User can log in after verification
- [ ] Unverified user cannot log in
- [ ] Resend email works
- [ ] Expired tokens are handled

### Automated Testing

Add to `test_prize_winners.py`:

```python
from django.test import TestCase
from surveys.models import EmailVerification, UserProfile

class EmailVerificationTestCase(TestCase):
    def test_verification_token_generation(self):
        # Test token generation
        pass
    
    def test_verification_email_sent(self):
        # Test email sending
        pass
    
    def test_token_expiration(self):
        # Test token validity
        pass
```

## Troubleshooting

### Emails Not Sending

1. Check email configuration in settings
2. Verify credentials with email provider
3. Check firewall/network settings
4. Review Django logs for errors

### User Can Log In Without Verification

1. Ensure `CustomLoginView` checks `email_verified`
2. Verify migration was applied
3. Check `UserProfile` has `email_verified` field

### Token Not Found

1. Check token is valid UUID format
2. Verify token not already used
3. Check token not expired

## Future Enhancements

1. **Email Confirmation Countdown**: Show time remaining for token
2. **Rate Limiting**: Limit resend attempts
3. **Custom Email Templates**: Allow HTML email customization
4. **Auto-Resend**: Send reminder if not verified after 3 days
5. **Two-Factor Auth**: Optional 2FA verification
6. **Verification Analytics**: Track verification rates

## Code Files Modified

1. **surveys/models.py**
   - Added `EmailVerification` model

2. **surveys/views_frontend.py**
   - Updated `SignUpView` for email verification
   - Updated `CustomLoginView` to check verification
   - Added `VerifyEmailView` for email verification
   - Added `PendingVerificationView` for pending status

3. **surveys/urls.py**
   - Added URL routes for email verification views

4. **templates/frontpage/pending_verification.html** (New)
   - Pending verification page template

5. **templates/frontpage/verify_email.html** (New)
   - Email verification result template

## Dependencies

- Django 4.2.7+
- Python 3.8+
- Standard Django email backend
- SMTP server access

## Support

For issues or questions about the email verification system:

1. Check Django email documentation
2. Review log files in `bulk_script/logs/`
3. Test email sending with `python manage.py shell`
4. Verify SMTP credentials
