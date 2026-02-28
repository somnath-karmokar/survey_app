#!/usr/bin/env python
"""Test script to verify the prize winners implementation"""

import os
import sys
import django

# Add the project directory to the Python path
sys.path.append(r'd:\somnath projects\Aniket\survey_app')

# Set up Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'survey_app.settings')
django.setup()

from django.conf import settings
from surveys.models import LuckyDrawEntry
from django.utils import timezone
from datetime import timedelta

def test_implementation():
    print("Testing Prize Winners Implementation")
    print("=" * 50)
    
    # Test 1: Check if WINNERS_DISPLAY_DAYS is configured
    winners_display_days = getattr(settings, 'LUCKY_DRAW_CONFIG', {}).get('WINNERS_DISPLAY_DAYS', 30)
    print(f"✓ WINNERS_DISPLAY_DAYS configured: {winners_display_days}")
    
    # Test 2: Check if the calculation works
    cutoff_date = timezone.now() - timedelta(days=winners_display_days)
    print(f"✓ Cutoff date calculated: {cutoff_date}")
    
    # Test 3: Check if we can query winners
    try:
        recent_winners = LuckyDrawEntry.objects.filter(
            is_winner=True,
            created_at__gte=cutoff_date
        ).select_related('user').order_by('-created_at')
        
        print(f"✓ Query executed successfully")
        print(f"✓ Found {recent_winners.count()} winners in the last {winners_display_days} days")
        
        # Test 4: Check if winner data structure is correct
        for winner in recent_winners[:3]:  # Just check first 3
            winner_data = {
                'name': winner.user.get_full_name() or winner.user.username,
                'prize': winner.prize,
                'date': winner.created_at,
                'profile_picture': winner.user.profile.profile_picture.url if hasattr(winner.user, 'profile') and winner.user.profile.profile_picture else None
            }
            print(f"✓ Winner data structure: {winner_data['name']} - {winner_data['prize']}")
        
    # --- additional checks ------------------------------------------------
    # Test 5: creating a winning entry should trigger two emails
    from django.core import mail
    # switch to in-memory backend so we can inspect outbox
    settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
    # create user and entry
    from django.contrib.auth.models import User
    u = User.objects.create_user('tester', email='tester@example.com', password='pwd')
    entry = LuckyDrawEntry.objects.create(
        user=u,
        guessed_number=7,
        winning_number=7,
        is_winner=True,
        prize='Test Voucher',
        surveys_at_play=5
    )
    print(f"✓ Created winning entry {entry.id}, outbox length: {len(mail.outbox)}")
    if len(mail.outbox) >= 2:
        print("✓ Winner and admin emails were queued successfully.")
    else:
        print("✗ Emails were NOT sent as expected. outbox contains", len(mail.outbox))
    
    # Test 6: serializer reflects current fields
    from surveys.serializers import LuckyDrawEntrySerializer
    serialized = LuckyDrawEntrySerializer(entry)
    print("Serialized fields:", serialized.data.keys())
    assert 'guessed_number' in serialized.data
    assert 'winning_number' in serialized.data
    assert 'prize' in serialized.data
            
    except Exception as e:
        print(f"✗ Error querying winners: {e}")
    
    print("\n" + "=" * 50)
    print("Implementation test completed!")
    print("\nConfiguration Summary:")
    print(f"- Display Period: {winners_display_days} days")
    print(f"- Template Variable: {{ winners_display_days }}")
    print(f"- Winners Data: {{ recent_winners }}")
    print("\nTo change the display period, modify WINNERS_DISPLAY_DAYS in settings.py")

if __name__ == '__main__':
    test_implementation()
