"""
WhatsApp Integration via Twilio
===============================
Sends messages to the creator via WhatsApp.
"""

import logging
from typing import Optional
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

from ..config import config

logger = logging.getLogger(__name__)


class WhatsAppClient:
    """
    WhatsApp messaging client using Twilio.

    Setup:
    1. Create Twilio account at https://www.twilio.com
    2. Enable WhatsApp Sandbox
    3. Send join code from your phone
    4. Get Account SID, Auth Token, and Sandbox number
    """

    def __init__(self):
        self.client = None
        self.from_number = config.twilio.whatsapp_number
        self.to_number = config.twilio.my_number

        if config.twilio.account_sid and config.twilio.auth_token:
            self.client = Client(
                config.twilio.account_sid,
                config.twilio.auth_token
            )
            logger.info("WhatsApp client initialized")
        else:
            logger.warning("WhatsApp client not configured - messages will be logged only")

    def send_message(self, message: str) -> Optional[str]:
        """
        Send a WhatsApp message.

        Args:
            message: Message content to send

        Returns:
            Message SID if successful, None otherwise
        """
        if not self.client:
            logger.info(f"[WhatsApp - DRY RUN] Would send:\n{message}")
            return "dry_run_sid"

        if not self.from_number or not self.to_number:
            logger.error("WhatsApp numbers not configured")
            return None

        try:
            # Ensure numbers are in WhatsApp format
            from_num = self._format_whatsapp_number(self.from_number)
            to_num = self._format_whatsapp_number(self.to_number)

            twilio_message = self.client.messages.create(
                body=message,
                from_=from_num,
                to=to_num
            )

            logger.info(f"WhatsApp message sent: {twilio_message.sid}")
            return twilio_message.sid

        except TwilioRestException as e:
            logger.error(f"Twilio error: {e.msg}")
            return None
        except Exception as e:
            logger.error(f"WhatsApp send error: {e}")
            return None

    def _format_whatsapp_number(self, number: str) -> str:
        """
        Ensure number is in WhatsApp format.

        Args:
            number: Phone number

        Returns:
            Formatted WhatsApp number
        """
        if number.startswith("whatsapp:"):
            return number
        return f"whatsapp:{number}"

    def get_message_status(self, message_sid: str) -> Optional[str]:
        """
        Get the status of a sent message.

        Args:
            message_sid: Twilio message SID

        Returns:
            Message status ('queued', 'sent', 'delivered', 'read', 'failed')
        """
        if not self.client or message_sid == "dry_run_sid":
            return "dry_run"

        try:
            message = self.client.messages(message_sid).fetch()
            return message.status
        except Exception as e:
            logger.error(f"Error fetching message status: {e}")
            return None

    def send_media_message(
        self,
        message: str,
        media_url: str
    ) -> Optional[str]:
        """
        Send a WhatsApp message with media attachment.

        Args:
            message: Message content
            media_url: URL of media to attach

        Returns:
            Message SID if successful
        """
        if not self.client:
            logger.info(f"[WhatsApp - DRY RUN] Would send with media:\n{message}\nMedia: {media_url}")
            return "dry_run_sid"

        try:
            from_num = self._format_whatsapp_number(self.from_number)
            to_num = self._format_whatsapp_number(self.to_number)

            twilio_message = self.client.messages.create(
                body=message,
                from_=from_num,
                to=to_num,
                media_url=[media_url]
            )

            logger.info(f"WhatsApp media message sent: {twilio_message.sid}")
            return twilio_message.sid

        except TwilioRestException as e:
            logger.error(f"Twilio error: {e.msg}")
            return None
        except Exception as e:
            logger.error(f"WhatsApp send error: {e}")
            return None

    def is_configured(self) -> bool:
        """Check if WhatsApp is properly configured."""
        return (
            self.client is not None and
            self.from_number is not None and
            self.to_number is not None
        )


# Global WhatsApp client instance
whatsapp = WhatsAppClient()
