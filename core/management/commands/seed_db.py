import random
import uuid
from decimal import Decimal
from datetime import date, timedelta, datetime
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from core.models import (
    Company, State, City, CompanyOffice, UserMembership, Role, Party
)
from core.request_context import set_current_user, set_current_company
from shipments.models import (
    Shipment, ShipmentLineItem, ShipmentEvent, ShipmentSequence, 
    RateCard, RateRule
)
from accounts.models import (
    Invoice, InvoiceLine, LedgerEntry, PaymentReceipt, Expense, BankPaymentVerification
)

User = get_user_model()

class Command(BaseCommand):
    help = 'Seeds the database with massive, rich, and detailed data for testing'

    def handle(self, *args, **options):
        self.stdout.write('Seeding rich, detailed data across all modules...')

        # 1. Setup Foundations
        self.stdout.write('Setting up states and cities...')
        states_data = [
            {'name': 'Maharashtra', 'code': 'MH'},
            {'name': 'Karnataka', 'code': 'KA'},
            {'name': 'Gujarat', 'code': 'GJ'},
            {'name': 'Tamil Nadu', 'code': 'TN'},
            {'name': 'Delhi', 'code': 'DL'},
        ]
        states = {}
        for data in states_data:
            state, _ = State.objects.get_or_create(name=data['name'], defaults={'code': data['code']})
            states[data['code']] = state

        cities_config = {
            'MH': ['Mumbai', 'Pune', 'Nagpur', 'Nashik', 'Aurangabad'],
            'KA': ['Bangalore', 'Mysore', 'Hubli', 'Mangalore', 'Belgaum'],
            'GJ': ['Ahmedabad', 'Surat', 'Vadodara', 'Rajkot', 'Jamnagar'],
            'TN': ['Chennai', 'Coimbatore', 'Madurai', 'Salem', 'Trichy'],
            'DL': ['New Delhi', 'Rohini', 'Dwarka', 'South Delhi', 'Noida'],
        }

        all_cities = []
        for code, names in cities_config.items():
            for name in names:
                city, _ = City.objects.get_or_create(name=name, state=states[code])
                all_cities.append(city)

        # 2. Create Companies
        companies = []
        company_names = ['Metro Logistics', 'Swift Carriers', 'FastTrack Express']
        for name in company_names:
            company, _ = Company.objects.get_or_create(name=name)
            companies.append(company)

        def get_or_create_user(username, company, office, role, is_owner=False):
            user, _ = User.objects.get_or_create(
                username=username,
                defaults={'email': f'{username}@example.com', 'company': company, 'office': office, 'is_owner': is_owner}
            )
            user.set_unusable_password()
            user.save()
            UserMembership.objects.get_or_create(user=user, company=company, office=office, role=role)
            return user

        def create_shipment_event(shipment, event_type, office, actor, days_ago):
            occurred_at = timezone.now() - timedelta(days=days_ago) + timedelta(hours=random.randint(0, 23))
            event = ShipmentEvent.objects.create(
                shipment=shipment,
                event_type=event_type,
                office=office,
                actor=actor,
                occurred_at=occurred_at,
                notes=f"Processed at {office.name}"
            )
            # Update shipment status based on event
            shipment.status = event_type
            shipment.save()
            return event

        def seed_for_company(company):
            self.stdout.write(f'Generating rich data for {company.name}...')
            set_current_company(company)
            
            # Create a Super Admin for context
            admin = get_or_create_user(f"{company.name.split()[0].lower()}_admin", company, None, Role.SUPER_ADMIN, is_owner=True)
            set_current_user(admin)

            # 3. Create Offices (Varied types)
            offices = []
            random_cities = random.sample(all_cities, 10)
            for i, city in enumerate(random_cities, 1):
                office, _ = CompanyOffice.objects.get_or_create(
                    company=company,
                    name=f"{city.name} Office",
                    defaults={
                        'city': city,
                        'address': f"Gate {i}, Industrial Park, {city.name}",
                        'phone': f"{random.randint(7000000000, 9999999999)}",
                        'office_type': random.choice(CompanyOffice.OfficeType.values)
                    }
                )
                offices.append(office)

            # 4. Create Staff for each office
            office_staff = {}
            for office in offices:
                prefix = f"{company.name.split()[0].lower()}_{office.name.split()[0].lower()}".replace(" ", "_")
                staff = {
                    'admin': get_or_create_user(f"{prefix}_mgr", company, office, Role.BRANCH_ADMIN),
                    'booking': get_or_create_user(f"{prefix}_book", company, office, Role.BOOKING_USER),
                    'delivery': get_or_create_user(f"{prefix}_dlv", company, office, Role.DELIVERY_USER),
                    'accountant': get_or_create_user(f"{prefix}_acc", company, office, Role.ACCOUNTANT),
                }
                office_staff[office.id] = staff

            # 5. Create Parties (Regular clients)
            parties = []
            for i in range(1, 21):
                city = random.choice(all_cities)
                party, _ = Party.objects.get_or_create(
                    company=company,
                    name=f"{company.name} Partner {i}",
                    defaults={
                        'phone': f"{random.randint(7000000000, 9999999999)}",
                        'city': city,
                        'address': f"Business Hub {i}, {city.name}",
                        'gst_number': f"{random.randint(10, 35)}ABCDE{random.randint(1000, 9999)}F1Z{random.randint(0, 9)}"
                    }
                )
                parties.append(party)

            # 6. Create Rate Cards
            for i in range(1, 4):
                card = RateCard.objects.create(
                    company=company,
                    name=f"Rate Card {i} - {company.name}",
                    is_default=(i == 1),
                    effective_from=timezone.now() - timedelta(days=30)
                )
                for _ in range(5):
                    RateRule.objects.create(
                        rate_card=card,
                        origin_city=random.choice(all_cities),
                        destination_city=random.choice(all_cities),
                        basis=random.choice(Shipment.BasisChoices.values),
                        rate_type=random.choice(ShipmentLineItem.RateTypeChoices.values),
                        rate=Decimal(random.randint(5, 50)),
                        min_charge=Decimal(random.randint(100, 300)),
                        delivery_charge=Decimal(random.randint(50, 200))
                    )

            # 7. Create Shipments with lifecycles
            shipment_count = 150
            for i in range(1, shipment_count + 1):
                origin = random.choice(offices)
                destination = random.choice([o for o in offices if o != origin])
                consignor = random.choice(parties)
                consignee = random.choice(parties)
                
                # Vary dates over last 60 days
                days_ago = random.randint(1, 60)
                shipment_date = date.today() - timedelta(days=days_ago)
                
                basis = random.choice(Shipment.BasisChoices.values)
                payment = random.choice(Shipment.PaymentTypeChoices.values)
                
                # Initial Freight setup
                freight = Decimal(random.randint(500, 5000))
                advance = Decimal(0)
                if payment == Shipment.PaymentTypeChoices.CASH and random.random() > 0.5:
                    advance = Decimal(random.randint(100, int(freight/2)))

                shipment = Shipment.objects.create(
                    company=company,
                    lr_no=f"{company.name[:2].upper()}{shipment_date.strftime('%m%d')}{i:04d}",
                    date=shipment_date,
                    from_city=origin.city,
                    origin_office=origin,
                    to_city=destination.city,
                    destination_office=destination,
                    basis=basis,
                    payment_type=payment,
                    consignor_name=consignor.name,
                    consignor_city=consignor.city,
                    consignor_phone=consignor.phone,
                    consignee_name=consignee.name,
                    consignee_city=consignee.city,
                    consignee_phone=consignee.phone,
                    freight=freight,
                    advance_amount=advance,
                    total_actual_weight=Decimal(random.randint(10, 200)),
                    total_charge_weight=Decimal(random.randint(10, 200)),
                    total_packages=random.randint(1, 10)
                )

                # Add items
                for j in range(1, random.randint(2, 4)):
                    item_rate = Decimal(random.randint(5, 50))
                    item_weight = shipment.total_actual_weight / 3
                    ShipmentLineItem.objects.create(
                        shipment=shipment,
                        pieces=1,
                        actual_weight=item_weight,
                        charged_weight=item_weight,
                        rate_type=random.choice(ShipmentLineItem.RateTypeChoices.values),
                        rate=item_rate,
                        charge=item_rate * item_weight
                    )

                # Generate Lifecycle Events
                current_staff = office_staff[origin.id]
                create_shipment_event(shipment, ShipmentEvent.EventType.BOOKED, origin, current_staff['booking'], days_ago)
                
                # Determine how far the shipment progressed
                progress = random.random()
                if progress > 0.2: # 80% Dispatched
                    create_shipment_event(shipment, ShipmentEvent.EventType.DISPATCHED, origin, current_staff['booking'], max(0, days_ago - 1))
                
                if progress > 0.4: # 60% Received at Destination
                    create_shipment_event(shipment, ShipmentEvent.EventType.RECEIVED, destination, office_staff[destination.id]['delivery'], max(0, days_ago - 2))
                
                if progress > 0.6: # 40% Out for delivery
                    create_shipment_event(shipment, ShipmentEvent.EventType.OUT_FOR_DELIVERY, destination, office_staff[destination.id]['delivery'], max(0, days_ago - 3))
                
                if progress > 0.8: # 20% Delivered
                    create_shipment_event(shipment, ShipmentEvent.EventType.DELIVERED, destination, office_staff[destination.id]['delivery'], max(0, days_ago - 3))
                elif progress < 0.05: # 5% Cancelled
                    create_shipment_event(shipment, ShipmentEvent.EventType.CANCELLED, origin, current_staff['admin'], max(0, days_ago - 1))

                # 8. Financials (Accounts)
                if shipment.status == Shipment.StatusChoices.DELIVERED:
                    # Create Invoice for TBB or Paid/To Pay
                    if shipment.basis == Shipment.BasisChoices.TBB:
                        invoice_date = shipment.date + timedelta(days=5)
                        invoice = Invoice.objects.create(
                            company=company,
                            office=destination,
                            party=consignor, # Usually billed to consignor in TBB
                            invoice_no=f"INV-{shipment.lr_no}",
                            invoice_date=invoice_date,
                            due_date=invoice_date + timedelta(days=15),
                            total_amount=shipment.final_freight,
                            status=Invoice.Status.SENT if random.random() > 0.3 else Invoice.Status.PAID
                        )
                        InvoiceLine.objects.create(
                            invoice=invoice,
                            shipment=shipment,
                            description=f"Freight for LR {shipment.lr_no}",
                            amount=shipment.final_freight
                        )
                        
                        # Ledger for Invoice
                        LedgerEntry.objects.create(
                            company=company, office=destination, party=consignor,
                            entry_type=LedgerEntry.EntryType.DEBIT,
                            reference_type=LedgerEntry.ReferenceType.INVOICE,
                            reference_id=invoice.id,
                            debit=invoice.total_amount,
                            entry_date=invoice_date
                        )

                        if invoice.status == Invoice.Status.PAID:
                            receipt = PaymentReceipt.objects.create(
                                company=company, office=destination, party=consignor,
                                amount=invoice.total_amount,
                                payment_mode=random.choice(PaymentReceipt.PaymentMode.values),
                                status=PaymentReceipt.Status.VERIFIED,
                                received_at=timezone.now()
                            )
                            # Ledger for Payment
                            LedgerEntry.objects.create(
                                company=company, office=destination, party=consignor,
                                entry_type=LedgerEntry.EntryType.CREDIT,
                                reference_type=LedgerEntry.ReferenceType.PAYMENT,
                                reference_id=receipt.id,
                                credit=receipt.amount,
                                entry_date=date.today()
                            )

                    # Simple direct payments (non-TBB)
                    elif shipment.payment_type != Shipment.PaymentTypeChoices.CREDIT:
                        receipt = PaymentReceipt.objects.create(
                            company=company, office=destination, party=consignee,
                            amount=shipment.final_freight,
                            payment_mode=random.choice(PaymentReceipt.PaymentMode.values),
                            status=PaymentReceipt.Status.VERIFIED,
                            received_at=timezone.now()
                        )
                
                # 9. Random Expenses
                if i % 10 == 0:
                    Expense.objects.create(
                        company=company,
                        office=random.choice(offices),
                        date=date.today() - timedelta(days=random.randint(0, 30)),
                        category=random.choice(['Fuel', 'Maintenance', 'Rent', 'Electricity', 'Tea/Coffee']),
                        amount=Decimal(random.randint(100, 2000)),
                        notes="Regular office expense"
                    )

        # Run for all companies
        for comp in companies:
            seed_for_company(comp)

        self.stdout.write(self.style.SUCCESS('Successfully seeded massive rich dataset across all modules!'))
