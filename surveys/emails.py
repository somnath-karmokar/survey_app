from django.template.loader import render_to_string
from django.core.mail import EmailMultiAlternatives
from django.conf import settings

def send_survey_completion_email(user, survey):
    """Send email notification when a user completes a survey"""
    subject = f'Survey Completed: {survey.name}'
    
    context = {
        'user': user,
        'survey': survey,
        'site_name': settings.SITE_NAME,
        'site_url': settings.SITE_URL,
    }
    
    # Render HTML email
    html_content = render_to_string('emails/survey_completion.html', context)
    
    # Create email message
    msg = EmailMultiAlternatives(
        subject=subject,
        body=f'Thank you for completing the survey: {survey.name}.',
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    
    msg.attach_alternative(html_content, "text/html")
    msg.send()

def send_lucky_draw_entry_email(user, entry):
    """Send email confirmation for lucky draw entry"""
    subject = f'Lucky Draw Entry Confirmation - {entry.month}/{entry.year}'
    
    context = {
        'user': user,
        'entry': entry,
        'site_name': settings.SITE_NAME,
        'site_url': settings.SITE_URL,
    }
    
    # Render HTML email
    html_content = render_to_string('emails/lucky_draw_entry.html', context)
    
    # Create email message
    msg = EmailMultiAlternatives(
        subject=subject,
        body=f'Your lucky draw entry has been recorded. Your number is: {entry.selected_number}.',
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    
    msg.attach_alternative(html_content, "text/html")
    msg.send()

def send_lucky_draw_winner_email(entry):
    """Send email to lucky draw winner"""
    subject = f'Congratulations! You Won the {entry.month}/{entry.year} Lucky Draw!'
    
    context = {
        'user': entry.user,
        'entry': entry,
        'site_name': settings.SITE_NAME,
        'site_url': settings.SITE_URL,
    }
    
    # Render HTML email
    html_content = render_to_string('emails/lucky_draw_winner.html', context)
    
    # Create email message
    msg = EmailMultiAlternatives(
        subject=subject,
        body=f'Congratulations! You have won the lucky draw with number {entry.selected_number}.',
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[entry.user.email],
    )
    
    msg.attach_alternative(html_content, "text/html")
    msg.send()

def send_lucky_draw_winner_admin_notification(entry):
    """Send email notification to admin when a user wins the lucky draw"""
    subject = f'🎉 Lucky Draw Winner Alert: {entry.user.get_full_name() or entry.user.username} won {entry.prize}!'
    
    context = {
        'user': entry.user,
        'entry': entry,
        'site_name': getattr(settings, 'SITE_NAME', 'Survey App'),
        'site_url': getattr(settings, 'SITE_URL', ''),
        'admin_email': getattr(settings, 'ADMIN_EMAIL', settings.DEFAULT_FROM_EMAIL),
    }
    
    # Render HTML email for admin
    html_content = render_to_string('emails/lucky_draw_winner_admin.html', context)
    
    # Create email message for admin
    msg = EmailMultiAlternatives(
        subject=subject,
        body=f'Lucky Draw Winner Alert: {entry.user.get_full_name() or entry.user.username} has won {entry.prize} in the {entry.month}/{entry.year} lucky draw. Winning number: {entry.guessed_number}',
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[getattr(settings, 'ADMIN_EMAIL', settings.DEFAULT_FROM_EMAIL)],
    )
    
    msg.attach_alternative(html_content, "text/html")
    msg.send()
