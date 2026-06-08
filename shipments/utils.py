import re

from django.conf import settings
from django.db import transaction

from .models import ShipmentSequence


def generate_lr_no(shipment_date, company):
    with transaction.atomic():
        seq, _ = ShipmentSequence.objects.select_for_update().get_or_create(date=shipment_date, company=company)
        seq.last_value += 1
        seq.save()
        last_value = seq.last_value

    fmt = getattr(settings, "LR_FORMAT", "{DD}{MM}{YY}{SEQ:3}")
    fmt = fmt.replace("{YY}", shipment_date.strftime("%y"))
    fmt = fmt.replace("{YYYY}", shipment_date.strftime("%Y"))
    fmt = fmt.replace("{MM}", shipment_date.strftime("%m"))
    fmt = fmt.replace("{DD}", shipment_date.strftime("%d"))

    seq_match = re.search(r"\{SEQ:(\d+)\}", fmt)
    if seq_match:
        padding = int(seq_match.group(1))
        return re.sub(r"\{SEQ:\d+\}", str(last_value).zfill(padding), fmt)
    return f"{fmt}{last_value}"
