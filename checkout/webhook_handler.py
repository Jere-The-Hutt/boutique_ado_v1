from django.http import HttpResponse
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings

from .models import Order, OrderLineItem
from products.models import Product
from profiles.models import UserProfile

import json
import time
import logging

logger = logging.getLogger(__name__)


class StripeWH_Handler:
    """Handle Stripe webhooks"""

    def __init__(self, request):
        self.request = request

    def _send_confirmation_email(self, order):
        """Send the user a confirmation email"""
        cust_email = order.email
        subject = render_to_string(
            'checkout/confirmation_emails/confirmation_email_subject.txt',
            {'order': order})
        body = render_to_string(
            'checkout/confirmation_emails/confirmation_email_body.txt',
            {'order': order, 'contact_email': settings.DEFAULT_FROM_EMAIL})

        send_mail(
            subject,
            body,
            settings.DEFAULT_FROM_EMAIL,
            [cust_email]
        )

    def handle_event(self, event):
        """
        Handle a generic/unknown/unexpected webhook event
        """
        return HttpResponse(
            content=f'Unhandled webhook received: {event["type"]}',
            status=200)

    def handle_payment_intent_succeeded(self, event):
        """
        Handle the payment_intent.succeeded webhook from Stripe
        """
        # DEBUGGING - Let's see what we're getting
        print(f"=== WEBHOOK DEBUG START ===")
        print(f"Event type: {event.get('type', 'NO TYPE')}")
        print(f"Event keys: {list(event.keys()) if hasattr(event, 'keys') else 'NO KEYS'}")
        
        try:
            intent = event['data']['object']
            print(f"Payment intent ID: {intent.get('id', 'NO ID')}")
            print(f"Intent object type: {type(intent)}")
            print(f"Intent keys: {list(intent.keys()) if hasattr(intent, 'keys') else 'NO KEYS'}")
            
            # Check metadata
            metadata = intent.get('metadata', {})
            print(f"Metadata: {metadata}")
            
            # Check charges
            charges = intent.get('charges', {})
            print(f"Charges type: {type(charges)}")
            print(f"Charges keys: {list(charges.keys()) if hasattr(charges, 'keys') else 'NO KEYS'}")
            
            if 'data' in charges:
                print(f"Charges data length: {len(charges['data'])}")
                if charges['data']:
                    charge = charges['data'][0]
                    print(f"First charge keys: {list(charge.keys()) if hasattr(charge, 'keys') else 'NO KEYS'}")
            
            # Check shipping
            shipping = intent.get('shipping')
            print(f"Shipping: {shipping}")
            print(f"Shipping type: {type(shipping)}")
            
            print(f"=== WEBHOOK DEBUG END ===")
            
            # For now, just return success to avoid the 400 error
            return HttpResponse(
                content=f'DEBUG: Webhook received and logged: {event["type"]}',
                status=200)
                
        except Exception as e:
            print(f"ERROR in webhook handler: {e}")
            print(f"ERROR type: {type(e)}")
            import traceback
            traceback.print_exc()
            return HttpResponse(
                content=f'ERROR: {str(e)}',
                status=500)

    def handle_payment_intent_payment_failed(self, event):
        """
        Handle the payment_intent.payment_failed webhook from Stripe
        """
        return HttpResponse(
            content=f'Webhook received: {event["type"]}',
            status=200)
