from django.http import HttpResponse
from django.conf import settings
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt

from checkout.webhook_handler import StripeWH_Handler

import stripe


@require_POST
@csrf_exempt
def webhook(request):
"""Listen for webhooks from Stripe"""
    print("=== WEBHOOK VIEW DEBUG START ===")
    
    # Setup
    wh_secret = settings.STRIPE_WH_SECRET
    stripe.api_key = settings.STRIPE_SECRET_KEY
    print(f"Webhook secret exists: {bool(wh_secret)}")
    print(f"Stripe API key exists: {bool(stripe.api_key)}")

    # get the webhook data and verify its signature
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
    print(f"Payload length: {len(payload) if payload else 0}")
    print(f"Signature header exists: {bool(sig_header)}")
    
    event = None

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WH_SECRET
        )
        print("✅ Webhook signature verified successfully")
    except ValueError as e:
        print(f"❌ ValueError: {e}")
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError as e:
        print(f"❌ SignatureVerificationError: {e}")
        return HttpResponse(status=400)
    except Exception as e:
        print(f"❌ Unexpected Exception: {e}")
        return HttpResponse(content=e, status=400)

    print(f"Event type: {event['type']}")
    print("=== WEBHOOK VIEW DEBUG END ===")

    # Set up a webhook handler
    handler = StripeWH_Handler(request)

    # Map webhook events to relevant handler functions
    event_map = {
        'payment_intent.succeeded': handler.handle_payment_intent_succeeded,
        'payment_intent.payment_failed': handler.handle_payment_intent_payment_failed,
    }

    # Get the webhook type from Stripe
    event_type = event['type']

    # If there's a handler for it, get it from the event map
    # Use the generic one by default
    event_handler = event_map.get(event_type, handler.handle_event)
    
    # Call the event handler with the event
    response = event_handler(event)
    return response