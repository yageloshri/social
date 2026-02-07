"""
WhatsApp Webhook Server
=======================
Receives incoming WhatsApp messages via Twilio webhook.
Enables two-way conversation with the agent.

Uses direct Twilio API for replies (more reliable than TwiML).
"""

import asyncio
import logging
from datetime import datetime
from flask import Flask, request, Response
from twilio.twiml.messaging_response import MessagingResponse

from .config import config
from .conversation_handler import ConversationHandler
from .integrations.whatsapp import whatsapp

logger = logging.getLogger(__name__)

# Flask app for webhook
app = Flask(__name__)

# Conversation handler (initialized later)
conversation_handler = None


def init_conversation_handler():
    """Initialize the conversation handler."""
    global conversation_handler
    if conversation_handler is None:
        conversation_handler = ConversationHandler()
    return conversation_handler


@app.route("/webhook/whatsapp", methods=["POST"])
def whatsapp_webhook():
    """
    Twilio WhatsApp webhook endpoint.
    Receives incoming messages and responds using direct API (not TwiML).
    """
    try:
        # Get message details
        incoming_msg = request.values.get("Body", "").strip()
        from_number = request.values.get("From", "")
        to_number = request.values.get("To", "")
        message_sid = request.values.get("MessageSid", "")

        logger.info(f"📨 Incoming WhatsApp: '{incoming_msg}' from {from_number}")
        logger.info(f"   MessageSid: {message_sid}")
        logger.info(f"   To: {to_number}")

        # No number validation - single user system
        # All messages are accepted and processed

        # Initialize handler if needed
        handler = init_conversation_handler()

        # Process message and get response (run async in sync context)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            response_text = loop.run_until_complete(
                handler.process_message(incoming_msg, from_number)
            )
        finally:
            loop.close()

        # Log response details
        logger.info(f"📤 Response length: {len(response_text)} chars")

        # Truncate if too long for WhatsApp (limit ~1600 chars)
        if len(response_text) > 1500:
            logger.warning(f"⚠️ Response too long ({len(response_text)} chars), truncating...")
            response_text = response_text[:1450] + "\n\n... (הודעה נחתכה)"

        # Send response via direct API call (more reliable than TwiML)
        logger.info(f"📤 Sending via direct API...")
        result_sid = whatsapp.send_message(response_text)

        if result_sid:
            logger.info(f"✅ Message sent successfully! SID: {result_sid}")
        else:
            logger.error(f"❌ Failed to send message via API!")

        # Return empty TwiML (acknowledge receipt, don't send via TwiML)
        resp = MessagingResponse()
        return Response(str(resp), mimetype="application/xml")

    except Exception as e:
        logger.error(f"❌ Webhook error: {e}", exc_info=True)

        # Try to send error message via direct API
        try:
            whatsapp.send_message("אופס, משהו השתבש. נסה שוב בעוד רגע 🙏")
        except Exception as send_err:
            logger.error(f"Failed to send error message: {send_err}")

        # Return empty TwiML
        resp = MessagingResponse()
        return Response(str(resp), mimetype="application/xml")


@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint for Railway."""
    return {"status": "healthy", "service": "content-master-agent"}


@app.route("/test-send", methods=["GET"])
def test_send():
    """
    Test endpoint to manually trigger a WhatsApp message.
    Used for debugging delivery issues.
    """
    try:
        test_message = f"🧪 Test message from webhook endpoint - {datetime.now().strftime('%H:%M:%S')}"

        logger.info(f"📤 Test send: {test_message}")
        result_sid = whatsapp.send_message(test_message)

        if result_sid:
            logger.info(f"✅ Test message sent! SID: {result_sid}")
            return {
                "status": "success",
                "message": "Test message sent",
                "sid": result_sid
            }
        else:
            logger.error("❌ Test message failed!")
            return {
                "status": "error",
                "message": "Failed to send test message"
            }, 500

    except Exception as e:
        logger.error(f"Test send error: {e}")
        return {
            "status": "error",
            "message": str(e)
        }, 500


@app.route("/", methods=["GET"])
def root():
    """Root endpoint."""
    return {
        "name": "Content Master Agent",
        "status": "running",
        "webhook": "/webhook/whatsapp",
        "health": "/health"
    }


def run_webhook_server(host: str = "0.0.0.0", port: int = 8080):
    """
    Run the webhook server.

    Args:
        host: Host to bind to
        port: Port to listen on
    """
    logger.info(f"Starting webhook server on {host}:{port}")
    app.run(host=host, port=port, debug=False)
