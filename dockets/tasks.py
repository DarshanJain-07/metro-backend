import time
from celery import shared_task
from django.core.mail import send_mail
from .models import Docket
import logging

logger = logging.getLogger(__name__)

@shared_task
def send_status_update_notification(docket_id, old_status, new_status):
    """
    Asynchronously sends notifications (e.g., Email/SMS or webhooks)
    when a docket's status changes.
    """
    try:
        docket = Docket.objects.get(pk=docket_id)
        logger.info(f"Notification Task: Docket {docket.docket_no} changed from {old_status} to {new_status}")
        
        # Simulate network delay for third-party webhook or email
        time.sleep(1)
        
        # In a real scenario, we might send an email or an SMS here:
        # send_mail(
        #     subject=f"Update on your shipment {docket.docket_no}",
        #     message=f"Your shipment is now {new_status}.",
        #     from_email="noreply@metro.test",
        #     recipient_list=["consignee@example.com"],
        # )
        
        return True
    except Docket.DoesNotExist:
        logger.error(f"Notification Task failed: Docket {docket_id} not found.")
        return False
