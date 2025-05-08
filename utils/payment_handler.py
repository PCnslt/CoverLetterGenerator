import os
import datetime
import stripe
from typing import Optional, Dict
from supabase import create_client
from tenacity import retry, stop_after_attempt, wait_exponential
import streamlit as st
import time

class PaymentProcessor:
    """Handles payment processing with Stripe integration and Supabase logging"""
    
    def __init__(self, stripe_secret_key: str, supabase_url: str, supabase_key: str, stripe_success_url: str = "http://localhost:8501", stripe_webhook_secret: str = None):
        # Validate secrets first
        if not all([supabase_url, supabase_key, stripe_secret_key]):
            raise ValueError("Missing required configuration")
            
        if not supabase_url.startswith("https://"):
            raise ValueError("Invalid Supabase URL format")
            
        if not supabase_key.startswith("eyJ"):
            raise ValueError("Invalid Supabase key format")

        stripe.api_key = stripe_secret_key
        self.supabase = create_client(supabase_url, supabase_key)
        self.stripe_price_id = stripe_price_id
        self.stripe_success_url = stripe_success_url
        self.stripe_webhook_secret = stripe_webhook_secret
        
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=10))
    def create_payment_session(self, user_id: str) -> Optional[str]:
        """Create Stripe Checkout session with retry logic"""
        try:
            session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'usd',
                        'unit_amount': 100,  # $1.00
                        'product_data': {'name': 'AI Cover Letter Generation'}
                    },
                    'quantity': 1
                }],
                mode='payment',
                success_url=f"{self.stripe_success_url}?payment_success=true&session_id={{CHECKOUT_SESSION_ID}}",
                metadata={'user_id': user_id}
            )
            self.log_transaction(user_id, session.id)
            return session.url
        except stripe.error.StripeError as e:
            print(f"Payment failed: {str(e)}")
            return None


    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=5))
    def log_transaction(self, user_id: str, session_id: str):
        """Log transaction to Supabase with retry logic"""
        self.supabase.table('payments').insert({
            'user_id': user_id,
            'session_id': session_id,
            'status': 'pending',
            'created_at': time.strftime('%Y-%m-%d %H:%M:%S')
        }).execute()

    def check_payment_status(self, session_id: str) -> str:
        """Check payment status with proper error handling and status updates"""
        try:
            # Retrieve full session details from Stripe
            session = stripe.checkout.Session.retrieve(
                session_id,
                expand=['payment_intent', 'customer']
            )
            
            # Update Supabase with latest status
            self.supabase.table('payments').update({
                'status': session.payment_status,
                'updated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
                'stripe_data': session.to_dict()
            }).eq('session_id', session_id).execute()
            
            return session.payment_status
        except stripe.error.StripeError as e:
            print(f"Payment status check failed: {str(e)}")
            return "error"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=10))
    def verify_webhook(self, payload: bytes, sig_header: str) -> Optional[Dict]:
        """Verify Stripe webhook signature and handle payment completion"""
        try:
            event = stripe.Webhook.construct_event(
                payload,
                sig_header,
                self.stripe_webhook_secret
            )
            
            if event['type'] == 'checkout.session.completed':
                session = event['data']['object']
                self.supabase.table('payments').update({
                    'status': session['payment_status'],
                    'updated_at': datetime.datetime.utcnow().isoformat(),
                    'session_id': session.get('id') or f"local_{datetime.datetime.utcnow().timestamp()}"
                }).eq('session_id', session['id']).execute()
                
            return event
        except stripe.error.SignatureVerificationError as e:
            print(f"Webhook verification failed: {str(e)}")
            return None
