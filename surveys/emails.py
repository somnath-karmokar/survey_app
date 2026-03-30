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
    subject = f'Lucky Draw Entry Confirmation - {entry.created_at.strftime("%B %Y")}'
    
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
        body=f'Your lucky draw entry has been recorded. Your number is: {entry.guessed_number}.',
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    
    msg.attach_alternative(html_content, "text/html")
    msg.send()

def send_lucky_draw_winner_email(entry):
    """Send email to lucky draw winner"""
    subject = f'Congratulations! You Won the {entry.created_at.strftime("%B %Y")} Lucky Draw!'
    
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
        body=f'Congratulations! You have won the lucky draw with number {entry.guessed_number}.',
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[entry.user.email],
    )
    
    msg.attach_alternative(html_content, "text/html")
    result = msg.send()
    print(f"Winner email sent: {result} (to {entry.user.email})")

def send_lucky_draw_winner_admin_notification(entry):
    """Send email notification to admin when a user wins the lucky draw"""
    subject = f'🎉 Lucky Draw Winner Alert: {entry.user.get_full_name() or entry.user.username} won the draw {entry.created_at.strftime("%B %Y")}!'
    
    context = {
        'user': entry.user,
        'entry': entry,
        'site_name': getattr(settings, 'SITE_NAME', 'Sudraw'),
        'site_url': getattr(settings, 'SITE_URL', ''),
        'admin_email': getattr(settings, 'ADMIN_EMAIL', settings.DEFAULT_FROM_EMAIL),
    }
    
    # Render HTML email for admin
    html_content = render_to_string('emails/lucky_draw_winner_admin.html', context)
    
    # Create email message for admin
    msg = EmailMultiAlternatives(
        subject=subject,
        body=f'Lucky Draw Winner Alert: {entry.user.get_full_name() or entry.user.username} has won the lucky draw on {entry.created_at.strftime("%B %Y")}. Winning number: {entry.guessed_number}',
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[getattr(settings, 'ADMIN_EMAIL', settings.DEFAULT_FROM_EMAIL)],
    )
    
    msg.attach_alternative(html_content, "text/html")
    result = msg.send()
    print(f"Admin notification email sent: {result} (to {getattr(settings, 'ADMIN_EMAIL', settings.DEFAULT_FROM_EMAIL)})")


def send_milestone_achievement_email(user, achievement):
    """Send email notification when a user reaches a milestone reward."""
    milestone_label = achievement.get_milestone_type_display()
    subject = f'Congratulations! You reached a Sudraw milestone'

    context = {
        'user': user,
        'achievement': achievement,
        'milestone_label': milestone_label,
        'site_name': getattr(settings, 'SITE_NAME', 'Sudraw'),
        'site_url': getattr(settings, 'SITE_URL', ''),
    }

    html_content = render_to_string('emails/milestone_achievement.html', context)
    body = (
        f"Hello {user.first_name or user.username},\n\n"
        f"You have reached the {milestone_label.lower()} milestone "
        f"with a total of {achievement.achieved_value}.\n"
        f"Prize awarded: {achievement.prize_name}\n\n"
        f"Our team will contact you with the next steps.\n\n"
        f"Best regards,\n"
        f"{getattr(settings, 'SITE_NAME', 'Sudraw')} Team"
    )

    msg = EmailMultiAlternatives(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    msg.attach_alternative(html_content, "text/html")
    msg.send()


def send_milestone_achievement_admin_notification(user, achievement):
    """Send admin notification when a user reaches a milestone reward."""
    milestone_label = achievement.get_milestone_type_display()
    admin_email = getattr(settings, 'ADMIN_EMAIL', settings.DEFAULT_FROM_EMAIL)
    subject = (
        f'Milestone Reward Alert: '
        f'{user.get_full_name() or user.username} reached {milestone_label}'
    )

    context = {
        'user': user,
        'achievement': achievement,
        'milestone_label': milestone_label,
        'site_name': getattr(settings, 'SITE_NAME', 'Sudraw'),
        'site_url': getattr(settings, 'SITE_URL', ''),
        'admin_email': admin_email,
    }

    html_content = render_to_string('emails/milestone_achievement_admin.html', context)
    body = (
        f"Milestone reward alert\n\n"
        f"User: {user.get_full_name() or user.username}\n"
        f"Email: {user.email}\n"
        f"Milestone: {milestone_label}\n"
        f"Threshold: {achievement.threshold}\n"
        f"Current total: {achievement.achieved_value}\n"
        f"Prize awarded: {achievement.prize_name}\n"
    )

    msg = EmailMultiAlternatives(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[admin_email],
    )
    msg.attach_alternative(html_content, "text/html")
    msg.send()
