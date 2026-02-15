# Survey Application with Lucky Draw

A Django-based web application for conducting surveys with multiple categories and a lucky draw feature.

## Features

- Multiple survey categories
- Multiple survey levels (Survey A, B, C, etc.)
- Admin can activate/deactivate surveys
- User authentication system
- Lucky draw for users who complete all active surveys in a month
- Responsive design

## Setup Instructions

1. Create and activate a virtual environment:
   ```
   python -m venv venv
   .\venv\Scripts\activate  # On Windows
   source venv/bin/activate  # On macOS/Linux
   ```

2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

3. Run migrations:
   ```
   python manage.py migrate
   ```

4. Create a superuser (admin):
   ```
   python manage.py createsuperuser
   ```

5. Run the development server:
   ```
   python manage.py runserver
   ```

6. Access the admin panel at `http://127.0.0.1:8000/admin/` and the main site at `http://127.0.0.1:8000/`

## Project Structure

- `survey_app/`: Main project configuration
- `surveys/`: Main app containing survey functionality
- `templates/`: HTML templates
- `static/`: Static files (CSS, JS, images)
