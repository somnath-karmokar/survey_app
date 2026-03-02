# Email Verification System - Architecture & Flow Diagrams

## 1. Complete Registration & Verification Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    USER REGISTRATION FLOW                   │
└─────────────────────────────────────────────────────────────┘

    START
      │
      ▼
    ┌──────────────────────┐
    │ Visit /signup/       │
    │ (SignUpView GET)     │
    └──────┬───────────────┘
           │
           ▼
    ┌──────────────────────┐
    │ Fill Form:           │
    │ -First Name          │
    │ -Last Name           │
    │ -Email               │
    │ -Username            │
    │ -Country             │
    │ -Password (optional) │
    └──────┬───────────────┘
           │
           ▼
    ┌──────────────────────┐
    │ Submit Form          │
    │ (SignUpView POST)    │
    └──────┬───────────────┘
           │
           ▼
    ┌──────────────────────────────┐
    │ Form Validation             │
    │ -Check required fields       │
    │ -Validate email format       │
    │ -Check unique email/username │
    └──────┬──────────┬────────────┘
           │ Valid    │ Invalid
           │          └──▶ Show Errors
           │              │
           ▼              │
    ┌──────────────────────────────┐
    │ Create User Account          │
    │ -user.is_active = False      │
    │ -user.save()                 │
    └──────┬───────────────────────┘
           │
           ▼
    ┌──────────────────────────────┐
    │ Create UserProfile           │
    │ -email_verified = False      │
    │ -user_type = 'frontend'      │
    │ -Save profile data           │
    └──────┬───────────────────────┘
           │
           ▼
    ┌──────────────────────────────┐
    │ Generate Email Token         │
    │ -token = UUID() (32 chars)   │
    │ -expires_at = +24 hours      │
    │ -is_verified = False         │
    │ -Save to DB                  │
    └──────┬───────────────────────┘
           │
           ▼
    ┌──────────────────────────────┐
    │ Send Verification Email      │
    │ -To: user.email              │
    │ -Subject: "Verify Your..."   │
    │ -Body: Link with token       │
    │ -HTML + Plain text           │
    └──────┬──────────┬────────────┘
           │ Success  │ Failed
           │          └──▶ Log Error
           │              │
           ▼              │
    ┌──────────────────────────────┐
    │ Redirect to                  │
    │ /pending-verification/       │
    │                              │
    │ Show message:                │
    │ "Check your email"           │
    └──────┬───────────────────────┘
           │
           ▼
    ┌──────────────────────┐
    │ USER SEES:           │
    │ -Email address       │
    │ -Check inbox message │
    │ -Resend option       │
    │ -Link to login       │
    └──────┬───────────────┘
           │
           ▼
    ┌──────────────────────────────┐
    │   EMAIL VERIFICATION FLOW    │
    │                              │
    │ User checks email &          │
    │ clicks verification link     │
    │                              │
    │ Link format:                 │
    │ /verify-email/{token}/       │
    └──────┬───────────────────────┘
           │
           ▼
    ┌──────────────────────────────┐
    │ VerifyEmailView GET          │
    │ -Extract token from URL      │
    │ -Query token from DB         │
    └──────┬──────────┬────────────┘
           │ Found    │ Not Found
           │          └──▶ Error Page
           │              │
           ▼              │
    ┌──────────────────────────────┐
    │ Validate Token               │
    │ -Check not expired           │
    │ -Check not already verified  │
    │ -Validate format             │
    └──────┬──────────┬────────────┘
           │ Valid    │ Invalid
           │          └──▶ Error Page
           │              │
           ▼              │
    ┌──────────────────────────────┐
    │ Verify Email                 │
    │ -token.is_verified = True    │
    │ -token.verified_at = now()   │
    │ -token.save()                │
    └──────┬───────────────────────┘
           │
           ▼
    ┌──────────────────────────────┐
    │ Update UserProfile           │
    │ -email_verified = True       │
    │ -profile.save()              │
    └──────┬───────────────────────┘
           │
           ▼
    ┌──────────────────────────────┐
    │ Activate User                │
    │ -user.is_active = True       │
    │ -user.save()                 │
    └──────┬───────────────────────┘
           │
           ▼
    ┌──────────────────────────────┐
    │ Success Page                 │
    │ -Show: "Email Verified!"     │
    │ -Link to login               │
    │ -Message: Can now log in     │
    └──────┬───────────────────────┘
           │
           ▼
    ┌──────────────────────┐
    │ Visit /login/        │
    │ (CustomLoginView)    │
    └──────┬───────────────┘
           │
           ▼
    ┌──────────────────────────────┐
    │ Check Email Verified         │
    │ -profile.email_verified?     │
    └──────┬──────────┬────────────┘
           │ Verified │ Not Verified
           │          └──▶ Redirect to
           │              pending-verification
           │              │
           ▼              │
    ┌──────────────────────────────┐
    │ Authenticate User            │
    │ -Check password              │
    │ -Validate credentials        │
    └──────┬──────────┬────────────┘
           │ Valid    │ Invalid
           │          └──▶ Show Error
           │              │
           ▼              │
    ┌──────────────────────────────┐
    │ Log User In                  │
    │ -Create session              │
    │ -Set auth cookie             │
    │ -Record login time           │
    └──────┬───────────────────────┘
           │
           ▼
    ┌──────────────────────────────┐
    │ Redirect to Dashboard        │
    │ (/dashboard/)                │
    └──────┬───────────────────────┘
           │
           ▼
    ┌──────────────────────┐
    │ Access Granted ✓     │
    │ User can now:        │
    │ -Take surveys        │
    │ -View profile        │
    │ -Enter lucky draw    │
    │ -Access all features │
    └──────────────────────┘
```

---

## 2. Database Schema & Relationships

```
┌─────────────────────────────────────┐
│         Django Auth User            │
├─────────────────────────────────────┤
│ id (PK)                             │
│ username (UNIQUE)                   │
│ email                               │
│ password (hashed)                   │
│ first_name                          │
│ last_name                           │
│ is_active ◄──────────┐              │
│ is_staff              │              │
│ is_superuser          │              │
│ date_joined           │              │
└─────────────┬─────────┘              │
              │                        │
              │ OneToOne              │
              │                        │
              ▼                        │
┌─────────────────────────────────────┐
│        UserProfile                  │ Updated during verification
├─────────────────────────────────────┤
│ id (PK)                             │
│ user (FK - OneToOne)                │
│ email_verified ◄────────────────────┘
│ user_type                           │
│ middle_name                         │
│ city                                │
│ state                               │
│ country (FK)                        │
│ date_of_birth                       │
│ profile_picture                     │
│ created_at                          │
│ updated_at                          │
└─────────────┬───────────────────────┘
              │
              │  1:1 Relationship
              │
              ▼
┌─────────────────────────────────────┐
│     EmailVerification               │ NEW MODEL
├─────────────────────────────────────┤
│ id (PK)                             │
│ user (FK - OneToOne) ◄──┐           │
│ email                   │ Indexed   │
│ token (UNIQUE) ◄───────┘            │
│ created_at                          │
│ expires_at                          │
│ is_verified                         │
│ verified_at                         │
│                                     │
│ Methods:                            │
│ -generate_token()                   │
│ -is_valid()                         │
│ -verify()                           │
└─────────────────────────────────────┘
```

---

## 3. URL Routing & Views

```
┌────────────────────────────────────────────┐
│         URL ROUTING STRUCTURE              │
└────────────────────────────────────────────┘

GET /signup/
    │
    └─────▶ SignUpView.get()
            ├─ Render form
            ├─ Pass countries context
            └─ Return form HTML

POST /signup/
    │
    └─────▶ SignUpView.post()
            ├─ Validate form
            ├─ Create user (inactive)
            ├─ Create profile
            ├─ Generate token
            ├─ Send email
            ├─ Return JSON (AJAX) or redirect
            └─ Redirect to /pending-verification/

GET /pending-verification/
    │
    └─────▶ PendingVerificationView.get()
            ├─ Render status page
            ├─ Show email address
            └─ Show resend form

POST /pending-verification/
    │
    └─────▶ PendingVerificationView.post()
            ├─ Get user by email
            ├─ Generate new token
            ├─ Send email
            ├─ Show success message
            └─ Reload page

GET /verify-email/<token>/
    │
    └─────▶ VerifyEmailView.get()
            ├─ Extract token from URL
            ├─ Query database
            ├─ Validate token
            ├─ Update profile
            ├─ Activate user
            └─ Show success/error

GET /login/
    │
    └─────▶ CustomLoginView.get()
            ├─ Render login form
            ├─ Check not already logged in
            └─ Return form HTML

POST /login/
    │
    └─────▶ CustomLoginView.post()
            ├─ Validate credentials
            ├─ Check email_verified
            │  ├─ If not verified
            │  │  └─ Redirect to /pending-verification/
            │  └─ If verified
            │     └─ Continue
            ├─ Authenticate user
            ├─ Create session
            └─ Redirect to /dashboard/
```

---

## 4. Email Verification Token Lifecycle

```
┌─────────────────────────────────────┐
│    TOKEN LIFECYCLE (24 HOURS)       │
└─────────────────────────────────────┘

TIME 0 MIN (Registration)
├─ Token created in DB
├─ expires_at = now + 24 hours
├─ is_verified = False
└─ Email sent to user

TIME 0-1440 MIN (Valid Window)
├─ User can click link
├─ Token is_valid() returns True
└─ Verification succeeds

TIME 1440 MIN (24 HOURS - EXPIRED)
├─ Token automatically invalid
├─ timezone.now() > expires_at
├─ is_valid() returns False
└─ User must resend email

RESEND REQUEST
├─ Old token deleted from DB
├─ New token generated
├─ expires_at = now + 24 hours
├─ Email sent again
└─ New 24-hour window starts

TOKEN VERIFICATION ATTEMPT
├─ Query DB for token
├─ Check exists
├─ Check not expired
├─ Check not already used (is_verified)
├─ If all pass:
│  ├─ token.is_verified = True
│  ├─ verified_at = now()
│  ├─ profile.email_verified = True
│  ├─ user.is_active = True
│  └─ Return success
└─ If any fail:
   └─ Return error message

CLEANUP (Manual or Scheduled)
├─ Delete tokens older than 30 days
├─ Delete already-verified tokens
└─ OR Keep for audit trail
```

---

## 5. Authentication & Access Control

```
┌──────────────────────────────────────┐
│   ACCESS CONTROL FLOW               │
└──────────────────────────────────────┘

Request to /dashboard/
    │
    ▼
Is User Authenticated?
    ├─ No ──▶ Redirect to /login/
    └─ Yes
        │
        ▼
    Is Email Verified?
    │ profile.email_verified == True
    │
    ├─ No ──▶ Show Error: "Verify email"
    │         Redirect to /pending-verification/
    │
    └─ Yes
        │
        ▼
    Is User Active?
    │ user.is_active == True
    │
    ├─ No ──▶ Show Error: "Account inactive"
    │
    └─ Yes
        │
        ▼
    Render Dashboard ✓
    │
    ▼
    Access Granted
```

---

## 6. Email Sending Process

```
┌──────────────────────────────────────┐
│   EMAIL SENDING FLOW                │
└──────────────────────────────────────┘

Trigger: User Registration or Resend
    │
    ▼
Build Email Content
├─ subject = "Verify Your Email - Survey App"
├─ Build verification link:
│  │ build_absolute_uri()
│  │ reverse_lazy('surveys:verify_email')
│  │ kwargs={'token': token_value}
│  │
│  └─ Result: https://example.com/verify-email/{32-char-token}/
│
├─ Create plain text version
│  └─ "Click link: {url}"
│
└─ Create HTML version
   └─ "<a href='{url}'>Verify Email</a>"

Get SMTP Configuration
├─ EMAIL_HOST = 'smtp.office365.com'
├─ EMAIL_PORT = 587
├─ EMAIL_USE_TLS = True
├─ EMAIL_HOST_USER = 'info@sudraw.com'
├─ EMAIL_HOST_PASSWORD = '***'
└─ DEFAULT_FROM_EMAIL = 'info@sudraw.com'

Connect to SMTP Server
├─ HOST:PORT (587)
├─ TLS handshake
├─ Authenticate with credentials
└─ Establish connection

Send Email
├─ From: sender email
├─ To: recipient email
├─ Subject: "Verify Your Email..."
├─ Plain text body
├─ HTML body
└─ Wait for ACK

Handle Response
├─ Success
│  └─ Log: "Email sent to {email}"
│
└─ Failure
   ├─ Log: "Email failed: {error}"
   ├─ Notify user
   └─ Show error message

Close Connection
└─ Disconnect from SMTP server
```

---

## 7. Data Flow Diagram

```
┌──────────────┐
│    USER      │
│  (Browser)   │
└──────┬───────┘
       │
       │ HTTP Requests
       ▼
┌──────────────────────────────────────┐
│   DJANGO APPLICATION                 │
│                                      │
│  URL Router                          │
│  ├─ /signup/                         │
│  ├─ /verify-email/<token>/           │
│  ├─ /pending-verification/           │
│  ├─ /login/                          │
│  └─ /dashboard/                      │
│                                      │
│  Views                               │
│  ├─ SignUpView                       │
│  ├─ VerifyEmailView                  │
│  ├─ PendingVerificationView          │
│  └─ CustomLoginView                  │
│                                      │
│  Models                              │
│  ├─ User                             │
│  ├─ UserProfile                      │
│  ├─ EmailVerification                │
│  └─ Country                          │
│                                      │
│  Forms                               │
│  └─ UserRegisterForm                 │
│                                      │
│  Email Backend                       │
│  ├─ SMTP Client                      │
│  └─ Message Formatter                │
│                                      │
└──────┬───────────────────────────────┘
       │
       ├────────────────────┬──────────────────┐
       │                    │                  │
       ▼                    ▼                  ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│   DATABASE   │  │  SMTP SERVER │  │    EMAIL     │
│              │  │              │  │    CLIENT    │
│ ├─ Users     │  │ (office365)  │  │   (Gmail)    │
│ ├─ Profiles  │  │              │  │ ├─ Inbox     │
│ ├─ Tokens    │  │ Sends email  │  │ ├─ Spam      │
│ └─ ...       │  │ to provider  │  │ └─ ...       │
└──────────────┘  └──────────────┘  └──────────────┘
       │                                     │
       └─────────────────┬───────────────────┘
                         │
                         ▼
                    User Opens
                    Email & Clicks
                    Verification Link
                         │
                         ▼
                   Browser Requests
                   /verify-email/<token>/
                         │
                         ▼
                  System Verifies Email
                  Updates Database
                  Activates Account
                    Returns Success
```

---

## 8. State Machine Diagram

```
┌─────────────────────────────────────┐
│    USER ACCOUNT STATE MACHINE       │
└─────────────────────────────────────┘

                    ┌──────────────────┐
                    │   NOT REGISTERED │
                    └────────┬─────────┘
                             │
                  User fills form & clicks Register
                             │
                             ▼
                    ┌──────────────────┐
                    │   REGISTERED     │
                    │  (Not Verified)  │
                    │ is_active=False  │
                    └────────┬─────────┘
                             │
                    Email sent, token created
                             │
           ┌─────────────────┼─────────────────┐
           │                 │                 │
           ▼                 ▼                 ▼
   ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
   │   EXPIRES    │ │  RESEND REQ  │ │   VERIFIED   │
   │ (24 hours)   │ │   (User      │ │ (Email OK)   │
   │              │ │    asks)     │ │is_active=True│
   └────┬─────────┘ └──────┬───────┘ └────┬─────────┘
        │                  │               │
        └──────────┬───────┘               │
                   │                       │
        New token generated                │
        New email sent                      │
                   │                       │
                   ▼                       ▼
                ┌────────────────────────────┐
                │   ACTIVE & VERIFIED        │
                │  (Can Log In & Access)     │
                │ is_active=True             │
                │ email_verified=True        │
                └────────────────────────────┘
                             │
                  User logs in successfully
                             │
                             ▼
                    ┌──────────────────┐
                    │   AUTHENTICATED  │
                    │   (Session OK)   │
                    │                  │
                    │  Access Platform │
                    └──────────────────┘
```

---

## 9. Security Flow

```
┌─────────────────────────────────────────────────┐
│        SECURITY & TOKEN VALIDATION              │
└─────────────────────────────────────────────────┘

Token Generation:
├─ Generate UUID: str(uuid.uuid4()).replace('-', '')
├─ Result: 32 hex characters
├─ Entropy: 128 bits (cryptographically secure)
└─ Store in DB with user relationship

Token Storage:
├─ Store as text in EmailVerification model
├─ Index on token field for fast lookup
├─ OneToOne relationship prevents duplicates
└─ No sensitive data in token

Token Validation:
├─ Lookup token in database
├─ Check token exists
├─ Check not expired
│  └─ timezone.now() < expires_at
├─ Check not already used
│  └─ is_verified == False
├─ Return valid/invalid status
└─ No retry limit (room for enhancement)

Token Usage:
├─ Included in URL: /verify-email/{token}/
├─ URL is HTTPS in production
├─ One-time use only
│  └─ Set is_verified=True after use
└─ Automatically expires after 24 hours

After Verification:
├─ Token marked as verified
├─ User account activated
├─ Email marked as verified
├─ Session created on login
└─ Cookie-based auth for requests

Potential Attacks Mitigated:
├─ Brute force: 128-bit entropy
├─ Replay attacks: One-time use tokens
├─ Token reuse: Marked as verified
├─ Expired tokens: 24-hour window
├─ Account hijacking: Email verification required
└─ Session hijacking: CSRF protection enabled
```

---

## Summary of All Diagrams

1. **Registration Flow** - Complete user journey from signup to login
2. **Database Schema** - Model relationships and structure
3. **URL Routing** - How requests are handled
4. **Token Lifecycle** - Token creation, validation, expiration
5. **Authentication** - Access control checks
6. **Email Sending** - SMTP process
7. **Data Flow** - Components interaction
8. **State Machine** - User account states
9. **Security** - Token security measures

These diagrams provide a complete understanding of the email verification system architecture and flow.
