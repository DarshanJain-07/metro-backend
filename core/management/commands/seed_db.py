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
    help = 'Seeds the database with expanded initial data for testing'

    def handle(self, *args, **options):
        self.stdout.write('Seeding massive expanded data...')

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
        self.stdout.write('Generating states and cities...')
        states_data = [
            {'name': 'Maharashtra', 'code': 'MH'},
            {'name': 'Karnataka', 'code': 'KA'},
            {'name': 'Gujarat', 'code': 'GJ'},
            {'name': 'Tamil Nadu', 'code': 'TN'},
            {'name': 'Delhi', 'code': 'DL'},
            {'name': 'Rajasthan', 'code': 'RJ'},
            {'name': 'Uttar Pradesh', 'code': 'UP'},
            {'name': 'West Bengal', 'code': 'WB'},
            {'name': 'Telangana', 'code': 'TS'},
            {'name': 'Kerala', 'code': 'KL'},
        ]
        
        states = {}
        for data in states_data:
            state, _ = State.objects.get_or_create(name=data['name'], defaults={'code': data['code']})
            states[data['code']] = state

        cities_config = {
            'MH': ['Mumbai', 'Pune', 'Nagpur', 'Nashik', 'Aurangabad', 'Thane', 'Solapur', 'Amravati', 'Kolhapur', 'Akola'],
            'KA': ['Bangalore', 'Mysore', 'Hubli', 'Mangalore', 'Belgaum', 'Gulbarga', 'Davanagere', 'Bellary', 'Bijapur', 'Shimoga'],
            'GJ': ['Ahmedabad', 'Surat', 'Vadodara', 'Rajkot', 'Bhavnagar', 'Jamnagar', 'Junagadh', 'Gandhidham', 'Nadiad', 'Morbi'],
            'TN': ['Chennai', 'Coimbatore', 'Madurai', 'Tiruchirappalli', 'Salem', 'Tirunelveli', 'Tiruppur', 'Erode', 'Vellore', 'Thoothukudi'],
            'DL': ['New Delhi', 'North Delhi', 'South Delhi', 'West Delhi', 'East Delhi', 'Rohini', 'Dwarka', 'Najafgarh', 'Narela', 'Saraswati Vihar'],
            'RJ': ['Jaipur', 'Jodhpur', 'Kota', 'Bikaner', 'Ajmer', 'Udaipur', 'Bhilwara', 'Alwar', 'Bharatpur', 'Sriganganagar'],
            'UP': ['Lucknow', 'Kanpur', 'Ghaziabad', 'Agra', 'Meerut', 'Varanasi', 'Prayagraj', 'Bareilly', 'Aligarh', 'Moradabad'],
            'WB': ['Kolkata', 'Howrah', 'Durgapur', 'Asansol', 'Siliguri', 'Maheshtala', 'Rajpur Sonarpur', 'Bhatpara', 'South Dumdum', 'Gopalpur'],
            'TS': ['Hyderabad', 'Warangal', 'Nizamabad', 'Karimnagar', 'Khammam', 'Ramagundam', 'Mahbubnagar', 'Nalgonda', 'Adilabad', 'Suryapet'],
            'KL': ['Thiruvananthapuram', 'Kochi', 'Kozhikode', 'Kollam', 'Thrissur', 'Alappuzha', 'Palakkad', 'Malappuram', 'Punnapra', 'Thalassery'],
        }

        cities = []
        for code, city_names in cities_config.items():
            state = states[code]
            for city_name in city_names:
                city, _ = City.objects.get_or_create(name=city_name, state=state)
                cities.append(city)

        # 4. Create Offices (150+)
        self.stdout.write('Generating 150 detailed branches...')
        office_types = ['Central', 'Hub', 'Transit', 'Logistics Center', 'Distribution Point', 'Regional Office', 'Annex', 'Warehouse', 'Cargo Terminal', 'Branch Office']
        streets = ['Main St', 'Ring Rd', 'Highway Jn', 'Industrial Area', 'Cargo Park', 'Station Rd', 'Port Rd', 'Market Rd', 'Business Park', 'Link Road']
        
        offices = []
        for i in range(1, 151):
            city = random.choice(cities)
            office_suffix = random.choice(office_types)
            office_name = f"{city.name} {office_suffix} {i}"
            address = f"{random.randint(1, 999)}, {random.choice(streets)}, {city.name}, {city.state.name} - {random.randint(400000, 600000)}"
            phone = f"{random.randint(7000000000, 9999999999)}"
            contact = f"Manager {i}"
            
            # Global Office for discovery
            go, _ = GlobalOffice.objects.get_or_create(
                name=office_name,
                city=city,
                defaults={
                    'address': address,
                    'phone': phone,
                    'contact_name': contact
                }
            )
            
            # Company Office for actual operations
            office, _ = CompanyOffice.objects.get_or_create(
                company=company,
                name=office_name,
                city=city,
                defaults={
                    'global_office': go,
                    'office_type': random.choice([CompanyOffice.OfficeType.OWN, CompanyOffice.OfficeType.PARTNER]),
                    'address': address,
                    'phone': phone,
                    'contact_name': contact
                }
            )
            offices.append(office)

        # 5. Roles and Memberships
        UserMembership.objects.get_or_create(user=admin_user, company=company, role=Role.CLIENT_SUPER_ADMIN)
        
        # 6. Create Parties (50+)
        self.stdout.write('Generating 50 parties...')
        company_prefixes = ['Global', 'Metro', 'Indian', 'Swift', 'Dynamic', 'Elite', 'Pacific', 'Total', 'Prime', 'Apex']
        company_suffixes = ['Industries', 'Solutions', 'Logistics', 'Manufacturing', 'Trading', 'Ventures', 'Corporation', 'Enterprises', 'Steel', 'Automobiles']
        
        parties = []
        for i in range(1, 51):
            name = f"{random.choice(company_prefixes)} {random.choice(company_suffixes)} {i}"
            phone = f"{random.randint(7000000000, 9999999999)}"
            gst = f"{random.randint(10, 35)}AAAAA{random.randint(1000, 9999)}A1Z{random.randint(1, 9)}"
            city = random.choice(cities)
            address = f"{random.randint(10, 500)}, Industrial Estate, {city.name}"
            
            party, _ = Party.objects.get_or_create(
                company=company, 
                name=name, 
                phone=phone, 
                defaults={
                    'city': city, 
                    'address': address,
                    'gst_number': gst
                }
            )
            parties.append(party)

        # 7. Initialize Shipment Sequence
        today = date.today()
        ShipmentSequence.objects.get_or_create(company=company, date=today, defaults={'last_value': 0})

        # 8. Create Sample Shipments (500)
        self.stdout.write('Creating 500 sample shipments...')
        statuses = [
            Shipment.StatusChoices.BOOKED,
            Shipment.StatusChoices.IN_TRANSIT,
            Shipment.StatusChoices.RECEIVED,
            Shipment.StatusChoices.DELIVERED,
            Shipment.StatusChoices.CANCELLED
        ]
        
        for i in range(1, 501):
            lr_no = f'LR2026{i:05d}'
            status = random.choice(statuses)
            
            origin = random.choice(offices)
            destination = random.choice([o for o in offices if o != origin])
            
            consignor = random.choice(parties)
            consignee = random.choice([p for p in parties if p != consignor])
            
            ship_date = today - timedelta(days=random.randint(0, 60))
            
            shipment, created = Shipment.objects.get_or_create(
                company=company,
                lr_no=lr_no,
                defaults={
                    'date': ship_date,
                    'status': status,
                    'from_city': origin.city,
                    'to_city': destination.city,
                    'origin_office': origin,
                    'destination_office': destination,
                    'consignor_name': consignor.name,
                    'consignor_city': consignor.city,
                    'consignor_phone': consignor.phone,
                    'consignee_name': consignee.name,
                    'consignee_city': consignee.city,
                    'consignee_phone': consignee.phone,
                    'freight': Decimal(str(random.randint(500, 5000))),
                    'total_actual_weight': Decimal(str(random.randint(10, 200))),
                    'total_charge_weight': Decimal(str(random.randint(10, 210))),
                    'total_packages': random.randint(1, 20)
                }
            )
            
            if created:
                # Add Line Items
                pieces = random.randint(1, 10)
                ShipmentLineItem.objects.create(
                    shipment=shipment,
                    pieces=pieces,
                    actual_weight=shipment.total_actual_weight,
                    charged_weight=shipment.total_charge_weight,
                    rate=shipment.freight / Decimal(str(pieces)),
                    charge=shipment.freight
                )

                # Add Events
                ShipmentEvent.objects.create(
                    shipment=shipment,
                    event_type=ShipmentEvent.EventType.BOOKED,
                    office=origin,
                    actor=admin_user,
                    occurred_at=timezone.make_aware(timezone.datetime.combine(ship_date, timezone.datetime.min.time()))
                )

                if status == Shipment.StatusChoices.DELIVERED:
                    ShipmentEvent.objects.create(
                        shipment=shipment,
                        event_type=ShipmentEvent.EventType.DELIVERED,
                        office=destination,
                        actor=admin_user,
                        occurred_at=timezone.now()
                    )

        # 9. Create Invoices and Ledger Entries
        self.stdout.write('Creating accounting records for some parties...')
        for i in range(20):
            party = random.choice(parties)
            office = random.choice(offices)
            amount = Decimal(str(random.randint(1000, 10000)))
            
            invoice, created = Invoice.objects.get_or_create(
                company=company,
                invoice_no=f'INV-2026-{i+100}',
                defaults={
                    'office': office,
                    'party': party,
                    'invoice_date': today - timedelta(days=random.randint(1, 30)),
                    'due_date': today + timedelta(days=random.randint(1, 30)),
                    'total_amount': amount,
                    'status': random.choice([Invoice.Status.SENT, Invoice.Status.PAID, Invoice.Status.PARTIALLY_PAID])
                }
            )
            
            if created:
                InvoiceLine.objects.create(
                    invoice=invoice,
                    description='Logistics Services',
                    amount=amount
                )

                # Create Ledger Entry for Invoice (Debit)
                LedgerEntry.objects.create(
                    company=company,
                    office=office,
                    party=party,
                    entry_type=LedgerEntry.EntryType.DEBIT,
                    reference_type=LedgerEntry.ReferenceType.INVOICE,
                    reference_id=invoice.id,
                    debit=amount,
                    entry_date=invoice.invoice_date
                )
                
                if invoice.status == Invoice.Status.PAID:
                    # Create Payment Receipt and Credit entry
                    PaymentReceipt.objects.create(
                        company=company,
                        office=office,
                        party=party,
                        amount=amount,
                        received_at=timezone.now(),
                        payment_mode=PaymentReceipt.PaymentMode.BANK_TRANSFER
                    )
                    LedgerEntry.objects.create(
                        company=company,
                        office=office,
                        party=party,
                        entry_type=LedgerEntry.EntryType.CREDIT,
                        reference_type=LedgerEntry.ReferenceType.PAYMENT,
                        reference_id="N/A",  # Reference ID for payment entry
                        credit=amount,
                        entry_date=today
                    )

        self.stdout.write(self.style.SUCCESS('Successfully seeded massive comprehensive data'))
