import re
from django.db import transaction
from django.conf import settings
from .models import DocketSequence

def generate_docket_no(docket_date, company):
    """
    Generates a unique docket number based on the settings format and daily sequence per company.
    """
    # Isolate the lock strictly to the sequence increment
    with transaction.atomic():
        seq, created = DocketSequence.objects.select_for_update().get_or_create(
            date=docket_date,
            company=company
        )
        seq.last_value += 1
        seq.save()
        last_value = seq.last_value

    # Parse the format: D{YY}{MM}{DD}{SEQ:4}
    fmt = getattr(settings, 'DOCKET_FORMAT', 'D{YY}{MM}{DD}{SEQ:4}')
    
    # Replace date parts
    fmt = fmt.replace('{YY}', docket_date.strftime('%y'))
    fmt = fmt.replace('{YYYY}', docket_date.strftime('%Y'))
    fmt = fmt.replace('{MM}', docket_date.strftime('%m'))
    fmt = fmt.replace('{DD}', docket_date.strftime('%d'))
    
    # Extract sequence padding (e.g. {SEQ:4}) and format sequence
    seq_match = re.search(r'\{SEQ:(\d+)\}', fmt)
    if seq_match:
        padding = int(seq_match.group(1))
        seq_str = str(last_value).zfill(padding)
        fmt = re.sub(r'\{SEQ:\d+\}', seq_str, fmt)
    else:
        # Fallback if no SEQ formatting exists
        fmt += str(last_value)
        
    return fmt
