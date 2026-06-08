import random
from decimal import Decimal
from datetime import date, timedelta
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from core.models import Company, State, City, GlobalOffice, CompanyOffice, UserMembership, Role, Party
from core.request_context import set_current_user, set_current_company
from shipments.models import (
    Shipment, ShipmentLineItem, ShipmentEvent, ShipmentSequence, 
    RateCard, RateRule
)
from accounts.models import Invoice, InvoiceLine, LedgerEntry, PaymentReceipt

User = get_user_model()

class Command(BaseCommand):
    help = 'Seeds the database with initial data including shipments and accounts'

    def handle(self, *args, **options):
        self.stdout.write('Seeding expanded data...')

        # 1. Create a Company
        company, created = Company.objects.get_or_create(name='Metro Logistics')
        if created:
            self.stdout.write(f'Created company: {company.name}')
        set_current_company(company)

        # 2. Create Users
        admin_user, created = User.objects.get_or_create(
            username='admin',
            defaults={
                'email': 'admin@metro.com',
                'is_staff': True,
                'is_superuser': True,
                'company': company,
                'is_owner': True
            }
        )
        if created:
            admin_user.set_password('admin123')
            admin_user.save()
            self.stdout.write(f'Created superuser: {admin_user.username}')
        
        set_current_user(admin_user)

        # 3. Create States and Cities
        states_data = [
            {'name': 'Maharashtra', 'code': 'MH'},
            {'name': 'Karnataka', 'code': 'KA'},
        ]
        states = {}
        for data in states_data:
            state, _ = State.objects.get_or_create(name=data['name'], defaults={'code': data['code']})
            states[data['code']] = state

        cities_data = [
            {'name': 'Mumbai', 'state': states['MH']},
            {'name': 'Pune', 'state': states['MH']},
            {'name': 'Bangalore', 'state': states['KA']},
        ]
        cities = {}
        for data in cities_data:
            city, _ = City.objects.get_or_create(name=data['name'], state=data['state'])
            cities[data['name']] = city

        # 4. Create Offices
        mumbai_go, _ = GlobalOffice.objects.get_or_create(
            name='Mumbai Central', city=cities['Mumbai'], 
            defaults={'address': 'Mumbai Main St', 'phone': '9876543210'}
        )
        bangalore_go, _ = GlobalOffice.objects.get_or_create(
            name='Bangalore Hub', city=cities['Bangalore'], 
            defaults={'address': 'Bangalore Ring Rd', 'phone': '9876543212'}
        )

        mumbai_office, _ = CompanyOffice.objects.get_or_create(
            company=company, name='Mumbai Office', city=cities['Mumbai'],
            defaults={'global_office': mumbai_go, 'office_type': CompanyOffice.OfficeType.OWN}
        )
        bangalore_office, _ = CompanyOffice.objects.get_or_create(
            company=company, name='Bangalore Office', city=cities['Bangalore'],
            defaults={'global_office': bangalore_go, 'office_type': CompanyOffice.OfficeType.OWN}
        )

        # 5. Roles and Memberships
        UserMembership.objects.get_or_create(user=admin_user, company=company, role=Role.CLIENT_SUPER_ADMIN)
        
        # 6. Create Parties
        parties = []
        parties_data = [
            {'name': 'Reliance Ind', 'phone': '9988776655', 'gst': '27AAAAA0000A1Z5', 'address': 'Reliance Corporate Park, Navi Mumbai'},
            {'name': 'Tata Steel', 'phone': '9988776644', 'gst': '27BBBBB1111B1Z2', 'address': 'Bombay House, Fort, Mumbai'},
            {'name': 'Infosys', 'phone': '9988776633', 'gst': '29CCCCC2222C1Z3', 'address': 'Electronics City, Bangalore'},
        ]
        for p_data in parties_data:
            party, _ = Party.objects.get_or_create(
                company=company, 
                name=p_data['name'], 
                phone=p_data['phone'], 
                defaults={
                    'city': cities['Mumbai'] if p_data['name'] != 'Infosys' else cities['Bangalore'], 
                    'address': p_data['address'],
                    'gst_number': p_data['gst']
                }
            )
            parties.append(party)

        # 7. Initialize Shipment Sequence
        today = date.today()
        ShipmentSequence.objects.get_or_create(company=company, date=today, defaults={'last_value': 0})

        # 8. Create Sample Shipments (Dockets)
        self.stdout.write('Creating sample shipments...')
        statuses = [
            Shipment.StatusChoices.BOOKED,
            Shipment.StatusChoices.IN_TRANSIT,
            Shipment.StatusChoices.RECEIVED,
            Shipment.StatusChoices.DELIVERED,
            Shipment.StatusChoices.CANCELLED
        ]
        
        for i in range(1, 16):
            lr_no = f'LR2026{i:04d}'
            status = statuses[(i-1) % len(statuses)]
            
            shipment, created = Shipment.objects.get_or_create(
                company=company,
                lr_no=lr_no,
                defaults={
                    'date': today - timedelta(days=i),
                    'status': status,
                    'from_city': cities['Mumbai'],
                    'to_city': cities['Bangalore'],
                    'origin_office': mumbai_office,
                    'destination_office': bangalore_office,
                    'consignor_name': parties[i % len(parties)].name,
                    'consignor_city': cities['Mumbai'],
                    'consignor_phone': '9876543210',
                    'consignee_name': parties[(i+1) % len(parties)].name,
                    'consignee_city': cities['Bangalore'],
                    'consignee_phone': '9876543212',
                    'freight': Decimal('1000.00') + (i * 100),
                    'total_actual_weight': Decimal('50.00') + i,
                    'total_charge_weight': Decimal('55.00') + i,
                    'total_packages': 5 + (i % 3)
                }
            )
            
            if created:
                # Add Line Items
                ShipmentLineItem.objects.create(
                    shipment=shipment,
                    pieces=5,
                    actual_weight=Decimal('50.00'),
                    charged_weight=Decimal('55.00'),
                    rate=Decimal('20.00'),
                    charge=Decimal('1000.00')
                )

                # Add Events
                ShipmentEvent.objects.create(
                    shipment=shipment,
                    event_type=ShipmentEvent.EventType.BOOKED,
                    office=mumbai_office,
                    actor=admin_user,
                    occurred_at=timezone.now() - timedelta(days=i)
                )

                if shipment.status == Shipment.StatusChoices.DELIVERED:
                    ShipmentEvent.objects.create(
                        shipment=shipment,
                        event_type=ShipmentEvent.EventType.DELIVERED,
                        office=bangalore_office,
                        actor=admin_user,
                        occurred_at=timezone.now()
                    )

        # 9. Create Invoices and Ledger Entries
        self.stdout.write('Creating accounting records...')
        for i, party in enumerate(parties[:2]):
            invoice, created = Invoice.objects.get_or_create(
                company=company,
                invoice_no=f'INV-2026-{i+1}',
                defaults={
                    'office': mumbai_office,
                    'party': party,
                    'invoice_date': today,
                    'due_date': today + timedelta(days=30),
                    'total_amount': Decimal('5000.00'),
                    'status': Invoice.Status.SENT
                }
            )
            
            if created:
                InvoiceLine.objects.create(
                    invoice=invoice,
                    description='Logistics Services',
                    amount=Decimal('5000.00')
                )

                # Create Ledger Entry for Invoice (Debit)
                LedgerEntry.objects.create(
                    company=company,
                    office=mumbai_office,
                    party=party,
                    entry_type=LedgerEntry.EntryType.DEBIT,
                    reference_type=LedgerEntry.ReferenceType.INVOICE,
                    reference_id=invoice.id,
                    debit=Decimal('5000.00'),
                    entry_date=today
                )

        self.stdout.write(self.style.SUCCESS('Successfully seeded comprehensive data'))

