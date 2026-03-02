# Email Verification Registration System - User Guide

## Table of Contents
1. [Registration Process](#registration-process)
2. [Email Verification](#email-verification)
3. [Login After Verification](#login-after-verification)
4. [Troubleshooting](#troubleshooting)
5. [Developer Setup](#developer-setup)

---

## Registration Process

### Step 1: Navigate to Signup Page
- Go to `/signup/` or click the "Sign Up" button on the website
- You'll see a registration form with the following fields:
  - **First Name** (required)
  - **Last Name** (required)
  - **Email** (required)
  - **Username** (required)
  - **Middle Name** (optional)
  - **Date of Birth** (optional - year required for age verification)
  - **City** (optional)
  - **State** (optional)
  - **Country** (required)
  - **Profile Picture** (optional)

### Step 2: Fill in Registration Details
- All required fields marked with `*` must be completed
- Email must be unique (no duplicate accounts)
- Username must be unique
- Date of birth is used to calculate age (minimum 16 years old)
- Country selection is mandatory

### Step 3: Submit Registration
- Click the "Register" button
- If form validation passes, account is created
- **Important**: Account is created but NOT yet active
- User receives a confirmation message and is redirected to pending verification page

---

## Email Verification

### What Happens After Registration

1. **Verification Email Sent**
   - User receives an email at their registered email address
   - Email subject: "Verify Your Email - Survey App"
   - Email contains a secure verification link

2. **Pending Verification Page** (`/pending-verification/`)
   - Shows user their registered email
   - Displays message: "Check your inbox to verify your account"
   - Provides option to resend verification email
   - User cannot log in yet

### How to Verify Email

#### Option 1: Click Verification Link (Recommended)
1. Check email inbox (including spam/junk folder)
2. Open email from Survey App
3. Click the "Verify Email" link in the email
4. You'll be redirected to verification confirmation page
5. See success message: "Email verified successfully!"
6. Click "Proceed to Login" to go to login page

#### Option 2: Resend Verification Email
1. On pending verification page, enter your email address
2. Click "Resend Verification Email"
3. New verification email is sent to your inbox
4. Click the link in the new email to verify

### Important Notes About Verification

- **Link Validity**: Verification link is valid for **24 hours**
- **One-Time Use**: Each link can only be used once
- **Security**: Links are cryptographically secure and unique
- **Token Format**: Link contains a 32-character secure token
- **After Verification**: 
  - Account automatically activated
  - Can now log in with username and password
  - Email marked as verified in profile

---

## Login After Verification

### Prerequisites
- Email must be verified
- Account must be active

### Login Process
1. Go to `/login/` page
2. Enter your **username** (or email) and **password**
3. Click "Login"
4. If successful, redirected to dashboard
5. If email not verified, see error message and option to verify

### Error When Logging In

**Error**: "Please verify your email before logging in."

**Solution**:
1. Click the link to go to pending verification page
2. Resend verification email to your registered address
3. Click the verification link in email
4. Try logging in again

---

## Troubleshooting

### "I Didn't Receive a Verification Email"

**Possible Reasons**:
1. Email in spam/junk folder
2. Email address misspelled during registration
3. Email server issue
4. Email delivery delay (can take 5-10 minutes)

**Solutions**:
1. **Check Spam Folder**
   - Look in spam, junk, or other email folders
   - Mark Survey App email as "not spam"

2. **Resend Email**
   - Go to `/pending-verification/`
   - Enter your email address
   - Click "Resend Verification Email"

3. **Check Email Address**
   - If email was misspelled, register again with correct email

4. **Contact Support**
   - Contact admin at info@sudraw.com
   - Include your username and registration email

### "The Verification Link Expired"

**Explanation**: Link is only valid for 24 hours from registration

**Solution**:
1. Go to `/pending-verification/`
2. Enter your email address
3. Click "Resend Verification Email"
4. Click the new link to verify

### "Invalid Verification Link"

**Possible Reasons**:
1. Link was already used to verify email
2. Link was modified or corrupted
3. Wrong email link
4. Account no longer exists

**Solutions**:
1. If already verified, try logging in directly
2. Try resending verification email from pending verification page
3. Register again if account issue

### "I Can't Log In Even After Verification"

**Troubleshooting Steps**:

1. **Verify Email Status**
   - Resend verification email
   - Open email and click verification link
   - See confirmation message

2. **Check Credentials**
   - Use **username** (not email) for login
   - Ensure capslock is OFF
   - Verify password is correct

3. **Account Status**
   - Account should be active after verification
   - If issues persist, contact support

4. **Browser Cache**
   - Clear browser cache and cookies
   - Try in different browser
   - Try incognito/private mode

### Email Not Showing Up in Admin View

Possible reasons:
1. Email configuration not working
2. SMTP credentials incorrect
3. Network/firewall issues
4. Email provider blocks the request

Check logs in `bulk_script/logs/` for email errors.

---

## Developer Setup

### Requirements

- Django 4.2.7+
- Python 3.8+
- Database with migrations applied
- Email server access (SMTP)

### Installation Steps

#### 1. Apply Database Migration

```bash
cd "d:\somnath projects\Aniket\development\survey_app"
python manage.py migrate surveys
```

This creates the `EmailVerification` table in the database.

#### 2. Configure Email Settings

Edit `survey_app/settings.py`:

```python
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.office365.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = 'your-email@example.com'
EMAIL_HOST_PASSWORD = 'your-password'
DEFAULT_FROM_EMAIL = 'your-email@example.com'
```

#### 3. Test Email Configuration

```bash
python manage.py shell
```

```python
from django.core.mail import send_mail

send_mail(
    'Test Email',
    'This is a test email from Survey App.',
    'info@sudraw.com',
    ['recipient@example.com'],
    fail_silently=False
)
```

If no error, email configuration works.

#### 4. Run Development Server

```bash
python manage.py runserver
```

#### 5. Test Registration Flow

1. Go to `http://localhost:8000/signup/`
2. Fill in registration form
3. Submit
4. Check email for verification link
5. Click link to verify
6. Log in to verify success

### File Structure

```
surveys/
├── models.py                    # EmailVerification model
├── views_frontend.py           # SignUpView, VerifyEmailView, PendingVerificationView
├── urls.py                     # URL routes for verification views
├── admin.py                    # EmailVerificationAdmin
└── migrations/
    └── 0008_emailverification.py    # Migration file

templates/frontpage/
├── pending_verification.html   # Pending verification page
└── verify_email.html          # Verification result page

static/
├── css/
└── js/
```

### Key Files and Functions

#### EmailVerification Model
- `generate_token()`: Creates new verification token
- `is_valid()`: Checks if token is valid (not expired, not used)
- `verify()`: Marks email as verified and activates user

#### SignUpView
- `send_verification_email()`: Sends verification email
- `form_valid()`: Handles successful registration

#### VerifyEmailView
- `get()`: Handles token validation and email verification

#### PendingVerificationView
- `get()`: Shows pending verification page
- `post()`: Resends verification email

### Email Template

Verification emails include:
- User greeting with first name
- Verification link (absolute URL)
- Expiration notice (24 hours)
- Disclaimer about account creation

HTML and plain text versions are sent.

### Admin Panel

Access at `/admin/`:

1. Login with superuser credentials
2. Navigate to **Surveys > Email Verifications**
3. View all email verification records
4. See status (verified/pending)
5. View creation and verification dates

### Testing

Add to your test file:

```python
from django.test import TestCase
from django.contrib.auth.models import User
from surveys.models import EmailVerification

class EmailVerificationTestCase(TestCase):
    def test_token_generation(self):
        user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass'
        )
        
        email_verification = EmailVerification.generate_token(
            user, 
            'test@example.com'
        )
        
        self.assertIsNotNone(email_verification.token)
        self.assertFalse(email_verification.is_verified)
    
    def test_token_validity(self):
        user = User.objects.create_user(
            username='testuser',
            email='test@example.com'
        )
        
        email_verification = EmailVerification.generate_token(
            user, 
            'test@example.com'
        )
        
        self.assertTrue(email_verification.is_valid())
```

### Logging

Email verification process logs to:
- `logger.info()`: For normal operations
- `logger.error()`: For errors
- `logger.warning()`: For validation issues

View logs in Django console during development.

### Production Considerations

1. **SMTP Configuration**
   - Use secure SMTP connection
   - Don't hardcode credentials
   - Use environment variables

2. **Rate Limiting**
   - Consider adding rate limit to resend endpoint
   - Prevent abuse of email sending

3. **Email Bounces**
   - Monitor invalid emails
   - Consider email validation service

4. **Database Backup**
   - Backup user and verification data
   - Retention policy for old tokens

5. **Security**
   - Tokens use UUID (cryptographically secure)
   - Tokens indexed in database for performance
   - One-time use tokens
   - 24-hour expiration window

### Common Issues

#### "Email backend not configured"
- Check EMAIL_BACKEND in settings
- Use `django.core.mail.backends.console.EmailBackend` for testing

#### "Connection refused" error
- Check SMTP host and port
- Verify firewall allows SMTP
- Check credentials

#### "Authentication failed"
- Verify email credentials
- Check if application-specific password needed
- Test SMTP connection manually

### Performance Tips

1. Use database indexing on `token` field (already done)
2. Implement token cleanup for expired tokens
3. Cache country list for registration form
4. Use select_related for user queries

---

## Summary

**Email Verification Registration Flow:**

```
User Registration → Account Created (inactive) → Verification Email Sent
                                                 ↓
User Clicks Link → Email Verified → Account Activated → User Can Log In
                                                 ↓
                          Resend Email Option (if needed)
```

**Key Points:**
- Email must be verified before login
- Verification link valid for 24 hours
- Can resend verification email anytime
- Account automatically activated after verification
- Secure token-based verification system

For more details, refer to:
- `EMAIL_VERIFICATION_SETUP.md` - Technical setup guide
- Django official documentation: https://docs.djangoproject.com/en/4.2/
