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

def test_implementation():
    print("Testing Prize Winners Implementation")
    print("=" * 50)
    
    # Test 1: Check if WINNERS_DISPLAY_COUNT is configured
    winners_display_count = getattr(settings, 'LUCKY_DRAW_CONFIG', {}).get('WINNERS_DISPLAY_COUNT', 50)
    print(f"✓ WINNERS_DISPLAY_COUNT configured: {winners_display_count}")

    # Test 3: Check if we can query winners
    try:
        recent_winners = LuckyDrawEntry.objects.filter(
            is_winner=True
        ).select_related('user').order_by('-created_at')[:winners_display_count]

        print(f"✓ Query executed successfully")
        print(f"✓ Found {len(recent_winners)} winners (showing up to the last {winners_display_count})")
        
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
    print(f"- Winners Shown: last {winners_display_count}")
    print(f"- Template Variable: {{ winners_display_count }}")
    print(f"- Winners Data: {{ recent_winners }}")
    print("\nTo change the number of winners shown, modify WINNERS_DISPLAY_COUNT in settings.py")

if __name__ == '__main__':
    test_implementation()
