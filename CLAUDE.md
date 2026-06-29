# Sudraw — Codebase Context

This file gives an AI coding agent full working context for the **Sudraw** survey/lucky-draw platform. Read it top-to-bottom before touching any file.

---

## Project identity

| Key | Value |
|---|---|
| Product name | Sudraw |
| Framework | Django 4.2.7 |
| Database | PostgreSQL (Render.com — see `settings.py` for credentials) |
| Python | 3.x (venv at `d:\somnath projects\Aniket\survey_app\myenv\`) |
| Deployed at | https://sudraw.com |
| Admin panel | https://sudraw.com/admin/ |
| Static serving | WhiteNoise (`CompressedManifestStaticFilesStorage`) |
| Email | Office365 SMTP, `smtp.office365.com:587`, from `info@sudraw.com` |
| REST API | Django REST Framework + JWT (`djangorestframework-simplejwt`) |

---

## Repository layout

```
survey_app/                  ← Django project package
    settings.py              ← all config lives here
    urls.py                  ← top-level URL routing
    static/css/              ← project-wide static CSS/JS

surveys/                     ← only Django app (all business logic here)
    models.py                ← every data model
    admin.py                 ← all admin registrations
    urls.py                  ← app URL patterns (namespaced "surveys")
    views.py                 ← ad-counter helpers, survey list
    views_surveys.py         ← survey detail, take survey, complete
    views_frontend.py        ← home, dashboard, auth, wallet, polls
    views_categories.py      ← category list/detail
    lucky_draw.py            ← LuckyDrawView (GET + POST)
    serializers.py           ← DRF serializers
    api_views.py             ← DRF ViewSets
    emails.py                ← all email-sending functions
    migrations/              ← 23 migrations (latest: 0023)
    static/surveys/css/      ← app-level CSS
    templates/surveys/       ← survey/poll/lucky-draw templates
    templates/emails/        ← transactional email HTML templates

templates/                   ← project-level templates
    base.html                ← root base template
    admin/base_site.html     ← custom admin branding
    admin/surveys/survey/change_form.html  ← question reorder UI
    frontpage/               ← public marketing pages
    frontend/                ← logged-in user pages (dashboard, wallet)
    registration/            ← password reset templates
    surveys/                 ← shared survey templates

static/
    admin/css/sudraw_admin.css   ← entire custom admin CSS (flexbox layout)
    admin/js/question_admin.js   ← question reorder admin JS
    ads.txt                      ← Google AdSense

staticfiles/                 ← collectstatic output (WhiteNoise serves this)
```

---

## Running the project locally

```bash
# activate venv (Windows)
"d:\somnath projects\Aniket\survey_app\myenv\Scripts\activate"

cd "d:\somnath projects\Aniket\development\survey_app"

python manage.py runserver          # dev server
python manage.py migrate            # apply migrations
python manage.py collectstatic      # publish static files
```

> **collectstatic caveat:** The project has a pre-existing `bootstrap.css.map` missing-file error that blocks `collectstatic`. When you change CSS files in `static/admin/css/`, also manually copy the file into `staticfiles/admin/css/` (both the plain and hashed filename versions).

---

## Key settings (`survey_app/settings.py`)

### Important dictionaries

```python
SURVEY_CONFIG = {
    'DEFAULT_COOLDOWN_DAYS': 2,   # days before a user can retake a survey
    'AD_FREQUENCY': 4,            # show ad modal every N surveys
}

LUCKY_DRAW_CONFIG = {
    'SURVEYS_REQUIRED': 2,        # surveys to complete between plays
    'POLLS_REQUIRED': 1,          # polls to complete between plays
    'NUMBER_RANGE_START': 1,
    'NUMBER_RANGE_END': 49,
    'SHOW_NUMBERS_FOR_TESTING': False,  # keep False in production
    'WINNERS_DISPLAY_DAYS': 30,
    # 'PRIZES': [...]             # country config overrides this
}

MILESTONE_REWARDS = {
    'surveys_completed': {'threshold': 5, 'repeat': True, ...},
    'polls_completed':   {'threshold': 5, 'repeat': True, ...},
    'points_earned':     {'threshold': 2200, ...},
}
```

### Auth settings

```python
AUTH_USER_MODEL = 'auth.User'   # standard User, extended via UserProfile OneToOne
LOGIN_URL = 'surveys:login'
LOGIN_REDIRECT_URL = 'surveys:survey_list'
LOGOUT_REDIRECT_URL = 'surveys:survey_list'

AUTHENTICATION_BACKENDS = [
    'surveys.backends.OTPBackend',
    'surveys.backends.EmailOnlyBackend',
    'django.contrib.auth.backends.ModelBackend',
]
```

### Session / security

- Auto-logout middleware: `AutoLogoutMiddleware` — 3-hour timeout (`SESSION_COOKIE_AGE = 10800`)
- Custom middleware stack includes `ExceptionRedirectMiddleware`
- CORS allowed for `http://localhost:3000` and `http://127.0.0.1:3000` (React frontend)

---

## URL structure

### Top-level (`survey_app/urls.py`)

| Pattern | Destination |
|---|---|
| `/admin/` | `survey_admin_site.urls` (custom Grappelli-based admin) |
| `/grappelli/` | `grappelli.urls` |
| `/api/token/` | JWT `TokenObtainPairView` |
| `/api/token/refresh/` | JWT `TokenRefreshView` |
| `/api/users/` | `UserViewSet` (admin only) |
| `/api/categories/` | `SurveyCategoryViewSet` (read-only) |
| `/api/surveys/` | `SurveyViewSet` (read-only, filter `?category=`) |
| `/api/questions/` | `QuestionViewSet` (read-only, filter `?survey=`) |
| `/api/responses/` | `SurveyResponseViewSet` (current user's responses) |
| `/api/lucky-draw/` | `LuckyDrawEntryViewSet` |
| `/ads.txt` | `ads_txt_view` |
| `/(everything else)` | `surveys.urls` (namespace: `surveys`) |

### App-level (`surveys/urls.py`, namespace `surveys`)

**Public / marketing**

| Name | Path |
|---|---|
| `home` | `/` |
| `features` | `/features/` |
| `contact` | `/contact/` |
| `faq` | `/faq/` |
| `search` | `/search/` |

**Auth**

| Name | Path |
|---|---|
| `login` | `/login/` |
| `signup` | `/signup/` |
| `logout` | `/logout/` |
| `send_otp` | `/send-otp/` |
| `verify_email` | `/verify-email/<token>/` |
| `pending_verification` | `/pending-verification/` |
| `user_profile` | `/profile/` |
| `edit_profile` | `/profile/edit/` |
| `delete_account` | `/profile/delete/` |

**Surveys**

| Name | Path |
|---|---|
| `survey_list` | `/surveys/` |
| `survey_detail` | `/surveys/<id>/` |
| `survey_question` | `/surveys/<id>/q/<index>/` |
| `survey_complete` | `/surveys/<id>/complete/` |
| `take_survey` | `/surveys/take/<id>/` |
| `take_survey_with_question` | `/surveys/take/<id>/q/<q_id>/` |
| `my_surveys` | `/my-surveys/` |

**Categories**

| Name | Path |
|---|---|
| `category_list` | `/categories/` |
| `category_detail` | `/category/<slug>/` |

**Polls**

| Name | Path |
|---|---|
| `poll_list` | `/polls/` |
| `poll_detail` | `/polls/<id>/` |
| `poll_question` | `/polls/<id>/q/<index>/` |

**Lucky draw**

| Name | Path |
|---|---|
| `lucky_draw` | `/lucky-draw/` |
| `lucky_draw_number` | `/lucky-draw/number/` |

**Wallet**

| Name | Path |
|---|---|
| `dashboard` | `/dashboard/` |
| `wallet_history` | `/wallet/` |
| `wallet_withdrawal_request` | `/wallet/withdraw/` |

**Misc**

| Name | Path |
|---|---|
| `survey_ad_shown` | `/survey/ad-shown/` |
| `debug_ad` | `/debug/ad/` |

---

## Data models (`surveys/models.py`)

### Core hierarchy

```
Country
  └── SurveyCategory (slug, parent=self, image, order)
        └── Survey (level 1-10, cooldown, sequential lock)
              ├── Question (M2M, types: text/single_choice/multiple_choice/rating)
              │     └── Choice
              └── SurveyResponse (user, started_at, completed_at)
                    └── Answer (text_answer | selected_choices M2M | rating_value)

Country
  └── Poll (is_active, order)
        └── PollQuestion (same types as Question)
        │     └── PollChoice
        └── PollResponse (user, unique per user/poll)
              └── PollAnswer
```

### User-related

```
User (Django built-in)
  └── UserProfile (OneToOne)
        ├── country → Country
        ├── wallet_balance (Decimal)
        ├── email_verified (Bool)
        └── user_type: 'admin'|'frontend'|'staff'|'api'

UserWallet        ← proxy of UserProfile (admin display only)
UserSurveyProgress(user, category, level, completed_count)  ← unique per (user, category, level)
WalletTransaction (credit/debit, linked to lucky_draw_entry)
WalletWithdrawalRequest (pending/approved/rejected, multiple payment methods)
```

### Lucky draw

```
CountryLuckyDrawConfig (OneToOne Country, poll_count_required, prize_amount, currency)

LuckyDrawEntry
  ├── user, draw_type ('survey'|'poll')
  ├── survey FK (nullable), poll FK (nullable)
  ├── guessed_number, winning_number, is_winner
  ├── prize (CharField)
  ├── surveys_at_play (snapshot), polls_at_play (snapshot)
  └── created_at
```

### Auth helpers

```
LoginOTP (user, email, code 6-char, expires_at, attempts, max_attempts=3)
EmailVerification (user OneToOne, token 64-char, expires_at 24h, is_verified)
```

### Achievements

```
MilestoneAchievement
  ├── user, milestone_type ('surveys_completed'|'polls_completed'|'points_earned')
  ├── threshold, achieved_value, prize_name
  └── unique: (user, milestone_type, threshold)
```

---

## Views quick reference

### `surveys/views_frontend.py`
| View | What it does |
|---|---|
| `HomePageView` | Public landing page |
| `DashboardView` | Logged-in dashboard with stats |
| `SignUpView` | Registration + auto email-verification send |
| `CustomLoginView` | Email/username or OTP login |
| `VerifyEmailView` | Token-based email confirmation |
| `WalletTransactionHistoryView` | User's transaction list |
| `WalletWithdrawalRequestView` | Country-aware withdrawal form (PayPal / bank / gift card) |
| `SearchView` | Full-text search across surveys, polls, categories |
| `MySurveysView` | Completed survey history |
| `poll_list()` | Active polls for user's country |
| `poll_detail()` | Single poll with questions |
| `send_otp()` | Generate + email OTP code |

### `surveys/views_surveys.py`
| View | What it does |
|---|---|
| `survey_list()` | Surveys for user's country, with cooldown/lock state |
| `survey_detail()` | Paginated question display |
| `take_survey()` | Submit answers, advance to next question |
| `survey_complete()` | Mark complete, trigger milestone check, credit wallet |

### `surveys/views_categories.py`
| View | What it does |
|---|---|
| `CategoryListView` | Categories filtered by user's country |
| `CategoryDetailView` | Category + survey list + user progress |

### `surveys/lucky_draw.py` — `LuckyDrawView`

**GET** — renders the board:
1. Generates shuffled number grid + lucky number server-side
2. Stores both in `request.session['lucky_draw_grid']` and `request.session['lucky_draw_number']`
3. Passes only `grid_range` (list of indices, no actual numbers) to template
4. **Never** sends the lucky number or actual board numbers to the HTML

**POST** — processes a pick:
1. Reads `index` (0-based) from request body
2. Resolves actual number: `grid[index]` from session
3. Gets winning number from session (never from client)
4. Clears both session keys immediately (prevents replay)
5. Records `LuckyDrawEntry`, credits wallet if winner, sends emails
6. Returns `{is_winner, guessed_number, winning_number, prize, plays_remaining}`

**Security invariant:** numbers and the lucky number never appear in HTML — inspecting source or network traffic reveals only opaque indices.

---

## Admin panel

- Custom admin site: `SurveyAdminSite` registered in `surveys/admin.py`
- Custom branding via `templates/admin/base_site.html`
- Custom CSS: `static/admin/css/sudraw_admin.css` (flexbox layout, cross-browser)
- Grappelli is installed but the custom site bypasses Grappelli styling on `/admin/`

### Key admin customisations

| Model | Notable feature |
|---|---|
| `Survey` | Custom change_form with drag-drop question reordering (jQuery UI sortable) |
| `Question` | Country/category AJAX filter to narrow survey dropdown |
| `WalletWithdrawalRequest` | `approve_requests` / `reject_requests` bulk actions — creates `WalletTransaction` and debits wallet |
| `UserWallet` | Proxy of `UserProfile`, read-only, shows transaction history inline |
| `LuckyDrawEntry` | Read-only (system-created only) |
| `Country` | `populate_countries` action from django-countries |

### Admin CSS layout notes
The filter sidebar (`.#content-related`) and main list (`#content-main`) use **flexbox** layout defined in `sudraw_admin.css`. Do not add `float` or `width: 100%` to `#content-main` — that breaks the filter panel. Key rules:
```css
#content          { display: flex; flex-wrap: wrap; align-items: flex-start; }
#content-main     { flex: 1 1 0%; min-width: 0; }
#content-related  { flex: 0 0 210px; position: sticky; top: 16px; }
```

---

## Email system (`surveys/emails.py`)

All functions use `EmailMultiAlternatives` (HTML + plain text fallback). Templates live in `surveys/templates/emails/`.

| Function | Trigger |
|---|---|
| `send_survey_completion_email` | On survey complete |
| `send_lucky_draw_winner_email` | On lucky draw win |
| `send_lucky_draw_winner_admin_notification` | On lucky draw win |
| `send_milestone_achievement_email` | On milestone hit |
| `send_milestone_achievement_admin_notification` | On milestone hit |
| `send_withdrawal_request_admin_notification` | On withdrawal submitted |
| `send_withdrawal_request_status_email` | On withdrawal approved/rejected |

---

## Advertisement system

- Controlled by `SURVEY_CONFIG['AD_FREQUENCY']` (default 4)
- Session key `survey_counter` tracks surveys completed since last ad
- `should_show_advertisement(request)` returns bool; view passes `show_ad` to template
- Template: `surveys/templates/surveys/includes/advertisement_modal.html`
- Ad modal is currently a placeholder ("Ads Coming Soon…") — Adsterra scripts were removed
- The modal unlocks the "Continue" button via a 3-second `setTimeout` (no iframe click needed)
- `survey_ad_shown` POST endpoint resets the counter

---

## Lucky draw board — template notes

`surveys/templates/surveys/lucky_draw.html`:
- Buttons use `data-index="{{ forloop.counter0 }}"` — **no actual numbers in HTML**
- JS shuffles button DOM order visually (random appearance without revealing mapping)
- JS sends `{ index: N, draw_type: "survey"|"poll" }` to POST endpoint
- Result numbers are only revealed in the server JSON response (`guessed_number`, `winning_number`)

---

## REST API

Base URL: `/api/`  
Auth: JWT Bearer token (`Authorization: Bearer <access_token>`)

| Endpoint | Method | Notes |
|---|---|---|
| `/api/token/` | POST | `{username, password}` → `{access, refresh}` |
| `/api/token/refresh/` | POST | `{refresh}` → `{access}` |
| `/api/categories/` | GET | All categories (public) |
| `/api/surveys/` | GET | Active surveys; filter `?category=<id>` |
| `/api/questions/` | GET | Questions; filter `?survey=<id>` |
| `/api/responses/` | GET/POST/PATCH/DELETE | Current user's responses |
| `/api/lucky-draw/` | GET/POST | Current user's lucky draw entries |
| `/api/users/` | GET | Admin only |

CORS is enabled for `localhost:3000` (React dev frontend).

---

## Dependencies (requirements.txt)

```
Django==4.2.7
djangorestframework==3.16.1
djangorestframework-simplejwt==5.5.1
django-grappelli==4.0.2
django-ckeditor==6.7.3
django-cors-headers==4.3.1
django-countries==8.2.0
django-mathfilters==1.0.0
psycopg2-binary==2.9.11
whitenoise
gunicorn==25.1.0
Pillow
PyJWT==2.10.1
python-dateutil==2.8.2
python-docx==1.2.0
lxml==6.0.2
```

---

## Patterns and conventions to follow

### Django conventions in use
- All views that need login use `@login_required` or `LoginRequiredMixin`
- Country-filtered content: views check `request.user.profile.country` to filter surveys/polls
- F() expressions used for all counter increments (prevents race conditions)
- `select_related` / `prefetch_related` used on all querysets that traverse FK chains

### Template conventions
- All public pages extend `templates/base.html`
- All survey/poll pages extend `surveys/templates/surveys/base/base.html`
- Emails extend `surveys/templates/emails/base_email.html`
- Bootstrap 5 for all UI components
- Font Awesome icons (`fas fa-*`)

### Security rules (do not break)
- Lucky draw numbers **must never** be in HTML — store in session, pass only indices to template
- Lucky draw winning number **must never** come from the client POST body — always read from session
- Session keys `lucky_draw_grid` and `lucky_draw_number` must be cleared after each play
- `current_lucky_number` must not appear in the template context or JavaScript source

### CSS rules (do not break)
- Admin `#content-main` must not have `width: 100%` or `float` — it will break the filter sidebar
- All admin cards use `overflow: visible` (not `overflow: hidden`) so date-picker popups are not clipped
- `box-sizing: border-box` is set globally via `*, *::before, *::after`

### Wallet rules
- All wallet debits/credits must use `select_for_update()` inside `transaction.atomic()`
- Every lucky draw win must create a matching `WalletTransaction` (checked via `WalletTransaction.objects.filter(lucky_draw_entry=entry).exists()` guard)
- Withdrawal approval debits the wallet and creates a `WalletTransaction` linked via `wallet_transaction` FK

---

## Common tasks — where to look

| Task | Files to edit |
|---|---|
| Change survey cooldown or ad frequency | `survey_app/settings.py` → `SURVEY_CONFIG` |
| Change lucky draw number range or requirements | `survey_app/settings.py` → `LUCKY_DRAW_CONFIG` |
| Add a new page/route | `surveys/urls.py`, add view in appropriate `views_*.py` |
| Add a new model | `surveys/models.py`, then `python manage.py makemigrations && migrate` |
| Add an admin panel for a model | `surveys/admin.py` |
| Change email content | `surveys/templates/emails/*.html` + `surveys/emails.py` |
| Change admin look/feel | `static/admin/css/sudraw_admin.css` + copy to `staticfiles/admin/css/` |
| Change the ad modal | `surveys/templates/surveys/includes/advertisement_modal.html` |
| Change lucky draw board behaviour | `surveys/lucky_draw.py` (LuckyDrawView) + `surveys/templates/surveys/lucky_draw.html` |
| Change wallet withdrawal flow | `surveys/models.py` (WalletWithdrawalRequest) + `surveys/views_frontend.py` (WalletWithdrawalRequestView) + `surveys/admin.py` (WalletWithdrawalRequestAdmin) |
| Add a new API endpoint | `surveys/serializers.py` + `surveys/api_views.py` + `survey_app/urls.py` (router) |
