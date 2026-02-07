#!/usr/bin/env python3
"""
WhatsApp Debug Script
=====================
Tests Twilio WhatsApp message sending with detailed logging.
"""

import os
import sys
from dotenv import load_dotenv

# Load .env file
load_dotenv()

print("=" * 60)
print("WhatsApp Debug Script")
print("=" * 60)

# Step 1: Check environment variables
print("\n📋 Step 1: Checking environment variables...")
print("-" * 40)

account_sid = os.getenv('TWILIO_ACCOUNT_SID', '')
auth_token = os.getenv('TWILIO_AUTH_TOKEN', '')
whatsapp_number = os.getenv('TWILIO_WHATSAPP_NUMBER', '')
my_number = os.getenv('MY_WHATSAPP_NUMBER', '')

def mask(value: str, show_chars: int = 4) -> str:
    """Mask a value for safe printing."""
    if not value:
        return "❌ NOT SET"
    if len(value) <= show_chars * 2:
        return f"✅ {value[:show_chars]}..."
    return f"✅ {value[:show_chars]}...{value[-show_chars:]} (len={len(value)})"

print(f"TWILIO_ACCOUNT_SID:    {mask(account_sid)}")
print(f"TWILIO_AUTH_TOKEN:     {mask(auth_token)}")
print(f"TWILIO_WHATSAPP_NUMBER: {whatsapp_number or '❌ NOT SET'}")
print(f"MY_WHATSAPP_NUMBER:     {my_number or '❌ NOT SET'}")

# Check for common issues
print("\n🔍 Step 2: Validating configuration...")
print("-" * 40)

issues = []

if not account_sid:
    issues.append("TWILIO_ACCOUNT_SID is missing")
elif not account_sid.startswith('AC'):
    issues.append(f"TWILIO_ACCOUNT_SID should start with 'AC', got: {account_sid[:10]}...")

if not auth_token:
    issues.append("TWILIO_AUTH_TOKEN is missing")
elif len(auth_token) < 30:
    issues.append(f"TWILIO_AUTH_TOKEN seems too short (length={len(auth_token)})")

if not whatsapp_number:
    issues.append("TWILIO_WHATSAPP_NUMBER is missing")
elif not whatsapp_number.startswith('+') and not whatsapp_number.startswith('whatsapp:'):
    issues.append(f"TWILIO_WHATSAPP_NUMBER should start with '+' or 'whatsapp:', got: {whatsapp_number}")

if not my_number:
    issues.append("MY_WHATSAPP_NUMBER is missing")
elif not my_number.startswith('+') and not my_number.startswith('whatsapp:'):
    issues.append(f"MY_WHATSAPP_NUMBER should start with '+' or 'whatsapp:', got: {my_number}")

if issues:
    print("⚠️  Configuration issues found:")
    for issue in issues:
        print(f"   - {issue}")
else:
    print("✅ Configuration looks valid")

# Step 3: Format numbers
print("\n📱 Step 3: Formatting numbers...")
print("-" * 40)

def format_whatsapp_number(number: str) -> str:
    if not number:
        return ""
    if number.startswith("whatsapp:"):
        return number
    return f"whatsapp:{number}"

from_num = format_whatsapp_number(whatsapp_number)
to_num = format_whatsapp_number(my_number)

print(f"From: {from_num}")
print(f"To:   {to_num}")

if not account_sid or not auth_token:
    print("\n❌ Cannot proceed - missing credentials")
    sys.exit(1)

# Step 4: Test Twilio connection
print("\n🔌 Step 4: Testing Twilio connection...")
print("-" * 40)

try:
    from twilio.rest import Client
    from twilio.base.exceptions import TwilioRestException

    client = Client(account_sid, auth_token)

    # Test account access
    account = client.api.accounts(account_sid).fetch()
    print(f"✅ Connected to Twilio account: {account.friendly_name}")
    print(f"   Status: {account.status}")

except TwilioRestException as e:
    print(f"❌ Twilio API Error: {e.msg}")
    print(f"   Error code: {e.code}")
    print(f"   HTTP status: {e.status}")
    sys.exit(1)
except Exception as e:
    print(f"❌ Connection error: {type(e).__name__}: {e}")
    sys.exit(1)

# Step 5: Send test message
print("\n📤 Step 5: Sending test message...")
print("-" * 40)

test_message = "🧪 בדיקה! Test message from debug script - " + \
               str(__import__('datetime').datetime.now().strftime('%H:%M:%S'))

print(f"Message: {test_message}")
print(f"Message length: {len(test_message)} chars")
print(f"From: {from_num}")
print(f"To: {to_num}")
print()

try:
    message = client.messages.create(
        body=test_message,
        from_=from_num,
        to=to_num
    )

    print("✅ Message submitted to Twilio!")
    print(f"   SID: {message.sid}")
    print(f"   Status: {message.status}")
    print(f"   Date created: {message.date_created}")
    print(f"   Direction: {message.direction}")
    print(f"   From: {message.from_}")
    print(f"   To: {message.to}")

    if message.error_code:
        print(f"   ⚠️ Error code: {message.error_code}")
        print(f"   ⚠️ Error message: {message.error_message}")

    # Wait a moment and check status
    print("\n⏳ Waiting 5 seconds to check delivery status...")
    import time
    time.sleep(5)

    updated = client.messages(message.sid).fetch()
    print(f"\n📊 Updated status after 5s: {updated.status}")

    # Wait more for final status
    print("⏳ Waiting 5 more seconds for final status...")
    time.sleep(5)

    final = client.messages(message.sid).fetch()
    print(f"📊 Final status after 10s: {final.status}")

    if updated.error_code:
        print(f"   ❌ Error code: {updated.error_code}")
        print(f"   ❌ Error message: {updated.error_message}")

        # Common error codes
        if updated.error_code == 63016:
            print("\n💡 Error 63016: Sandbox session expired!")
            print("   You need to rejoin the sandbox by sending the join code again.")
        elif updated.error_code == 21211:
            print("\n💡 Error 21211: Invalid 'To' phone number")
        elif updated.error_code == 21608:
            print("\n💡 Error 21608: The 'From' number is not a valid WhatsApp sender")
    else:
        print(f"   ✅ No errors reported")

    # Possible status values
    status_info = {
        'queued': '📥 Message is queued for sending',
        'sending': '📤 Message is being sent',
        'sent': '✅ Message sent to carrier',
        'delivered': '✅✅ Message delivered to recipient',
        'read': '👀 Message was read',
        'failed': '❌ Message failed to send',
        'undelivered': '❌ Message could not be delivered'
    }

    if updated.status in status_info:
        print(f"\n   {status_info[updated.status]}")

except TwilioRestException as e:
    print(f"\n❌ Twilio error sending message:")
    print(f"   Code: {e.code}")
    print(f"   Message: {e.msg}")
    print(f"   HTTP status: {e.status}")

    # Common error codes and solutions
    if e.code == 63007:
        print("\n💡 Error 63007: User hasn't opted in to receive messages.")
        print("   The recipient needs to send the join code to the sandbox number first.")
        print("   Ask them to send: 'join <sandbox-code>' to your Twilio WhatsApp number.")
    elif e.code == 63016:
        print("\n💡 Error 63016: The sandbox participant session has expired.")
        print("   Send the join code again to the sandbox number.")
    elif e.code == 21211:
        print("\n💡 Error 21211: Invalid 'To' phone number format.")
        print("   Make sure the number is in E.164 format: +972528461777")
    elif e.code == 21608:
        print("\n💡 Error 21608: The 'From' number is not valid for WhatsApp.")
        print("   Check TWILIO_WHATSAPP_NUMBER environment variable")

except Exception as e:
    print(f"\n❌ Unexpected error: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("Debug complete!")
print("=" * 60)
