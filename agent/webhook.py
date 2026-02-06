"""
WhatsApp Webhook Server
=======================
Receives incoming WhatsApp messages via Twilio webhook.
Enables two-way conversation with the agent.
"""

import asyncio
import logging
from datetime import datetime
from flask import Flask, request, Response
from twilio.twiml.messaging_response import MessagingResponse

from .config import config
from .conversation_handler import ConversationHandler

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
    Receives incoming messages and responds.
    """
    try:
        # Get message details
        incoming_msg = request.values.get("Body", "").strip()
        from_number = request.values.get("From", "")
        to_number = request.values.get("To", "")
        message_sid = request.values.get("MessageSid", "")

        logger.info(f"Incoming WhatsApp: '{incoming_msg}' from {from_number}")

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

        # Create Twilio response
        resp = MessagingResponse()
        resp.message(response_text)

        logger.info(f"Response sent: {response_text[:100]}...")

        return Response(str(resp), mimetype="application/xml")

    except Exception as e:
        logger.error(f"Webhook error: {e}")
        resp = MessagingResponse()
        resp.message("אופס, משהו השתבש. נסה שוב בעוד רגע 🙏")
        return Response(str(resp), mimetype="application/xml")


@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint for Railway."""
    return {"status": "healthy", "service": "content-master-agent"}


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
