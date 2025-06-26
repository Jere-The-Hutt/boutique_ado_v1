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
        try:
            intent = event.data.object
            pid = intent.id

            # Validate required metadata
            if not hasattr(intent, 'metadata') or not intent.metadata:
                logger.error("No metadata found in payment intent")
                return HttpResponse(
                    content=f'Webhook received: {event["type"]} | ERROR: No metadata',
                    status=400)

            bag = getattr(intent.metadata, 'bag', None)
            save_info = getattr(intent.metadata, 'save_info', None)
            username = getattr(intent.metadata, 'username', 'AnonymousUser')

            if not bag:
                logger.error("No bag metadata found")
                return HttpResponse(
                    content=f'Webhook received: {event["type"]} | ERROR: Missing bag metadata',
                    status=400)

            # Validate charges data
            if not hasattr(intent, 'charges') or not intent.charges.data:
                logger.error("No charge data found in payment intent")
                return HttpResponse(
                    content=f'Webhook received: {event["type"]} | ERROR: No charge data',
                    status=400)

            billing_details = intent.charges.data[0].billing_details
            shipping_details = intent.shipping
            grand_total = round(intent.charges.data[0].amount / 100, 2)

            # Validate shipping details
            if not shipping_details:
                logger.error("No shipping details found")
                return HttpResponse(
                    content=f'Webhook received: {event["type"]} | ERROR: No shipping details',
                    status=400)

            if not hasattr(shipping_details, 'address') or not shipping_details.address:
                logger.error("No shipping address found")
                return HttpResponse(
                    content=f'Webhook received: {event["type"]} | ERROR: No shipping address',
                    status=400)

            # Clean data in the shipping details
            for field, value in shipping_details.address.items():
                if value == "":
                    shipping_details.address[field] = None

            # Update profile information if save_info was checked
            profile = None
            if username != 'AnonymousUser':
                try:
                    profile = UserProfile.objects.get(user__username=username)
                    if save_info:
                        profile.default_phone_number = shipping_details.phone
                        profile.default_country = shipping_details.address.country
                        profile.default_postcode = shipping_details.address.postal_code
                        profile.default_town_or_city = shipping_details.address.city
                        profile.default_street_address1 = shipping_details.address.line1
                        profile.default_street_address2 = shipping_details.address.line2
                        profile.default_county = shipping_details.address.state
                        profile.save()
                except UserProfile.DoesNotExist:
                    logger.warning(f"User profile not found for username: {username}")

            order_exists = False
            attempt = 1
            while attempt <= 5:
                try:
                    order = Order.objects.get(
                        full_name__iexact=shipping_details.name,
                        email__iexact=billing_details.email,
                        phone_number__iexact=shipping_details.phone,
                        country__iexact=shipping_details.address.country,
                        postcode__iexact=shipping_details.address.postal_code,
                        town_or_city__iexact=shipping_details.address.city,
                        street_address1__iexact=shipping_details.address.line1,
                        street_address2__iexact=shipping_details.address.line2,
                        county__iexact=shipping_details.address.state,
                        grand_total=grand_total,
                        original_bag=bag,
                        stripe_pid=pid,
                    )
                    order_exists = True
                    break
                except Order.DoesNotExist:
                    attempt += 1
                    time.sleep(1)

            if order_exists:
                self._send_confirmation_email(order)
                return HttpResponse(
                    content=f'Webhook received: {event["type"]} | SUCCESS: Verified order already in database',
                    status=200)
            else:
                order = None
                try:
                    # Validate bag JSON
                    try:
                        bag_data = json.loads(bag)
                    except json.JSONDecodeError as e:
                        logger.error(f"Invalid bag JSON: {e}")
                        return HttpResponse(
                            content=f'Webhook received: {event["type"]} | ERROR: Invalid bag JSON',
                            status=400)

                    order = Order.objects.create(
                        full_name=shipping_details.name,
                        user_profile=profile,
                        email=billing_details.email,
                        phone_number=shipping_details.phone,
                        country=shipping_details.address.country,
                        postcode=shipping_details.address.postal_code,
                        town_or_city=shipping_details.address.city,
                        street_address1=shipping_details.address.line1,
                        street_address2=shipping_details.address.line2,
                        county=shipping_details.address.state,
                        grand_total=grand_total,
                        original_bag=bag,
                        stripe_pid=pid,
                    )

                    for item_id, item_data in bag_data.items():
                        try:
                            product = Product.objects.get(id=item_id)
                        except Product.DoesNotExist:
                            logger.error(f"Product not found: {item_id}")
                            if order:
                                order.delete()
                            return HttpResponse(
                                content=f'Webhook received: {event["type"]} | ERROR: Product not found',
                                status=400)

                        if isinstance(item_data, int):
                            order_line_item = OrderLineItem(
                                order=order,
                                product=product,
                                quantity=item_data,
                            )
                            order_line_item.save()
                        else:
                            for size, quantity in item_data['items_by_size'].items():
                                order_line_item = OrderLineItem(
                                    order=order,
                                    product=product,
                                    quantity=quantity,
                                    product_size=size,
                                )
                                order_line_item.save()

                except Exception as e:
                    logger.error(f"Error creating order: {e}")
                    if order:
                        order.delete()
                    return HttpResponse(
                        content=f'Webhook received: {event["type"]} | ERROR: {e}',
                        status=500)

            self._send_confirmation_email(order)
            return HttpResponse(
                content=f'Webhook received: {event["type"]} | SUCCESS: Created order in webhook',
                status=200)

        except Exception as e:
            logger.error(f"Unexpected error in payment_intent_succeeded: {e}")
            return HttpResponse(
                content=f'Webhook received: {event["type"]} | ERROR: {e}',
                status=500)

    def handle_payment_intent_payment_failed(self, event):
        """
        Handle the payment_intent.payment_failed webhook from Stripe
        """
        return HttpResponse(
            content=f'Webhook received: {event["type"]}',
            status=200)
