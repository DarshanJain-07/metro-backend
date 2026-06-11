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
    help = 'Seeds the database with massive expanded data for multi-user and branch testing'

    def handle(self, *args, **options):
        self.stdout.write('Seeding massive expanded data with multi-user support...')

        # 1. Create Companies
        metro, _ = Company.objects.get_or_create(name='Metro Logistics')
        swift, _ = Company.objects.get_or_create(name='Swift Carriers')
        self.stdout.write(f'Companies: {metro.name}, {swift.name}')

        # 2. Setup States and Cities
        self.stdout.write('Generating states and cities...')
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
            'MH': ['Mumbai', 'Pune', 'Nagpur'],
            'KA': ['Bangalore', 'Mysore', 'Hubli'],
            'GJ': ['Ahmedabad', 'Surat', 'Vadodara'],
            'TN': ['Chennai', 'Coimbatore', 'Madurai'],
            'DL': ['New Delhi', 'Rohini', 'Dwarka'],
        }

        all_cities = []
        for code, names in cities_config.items():
            for name in names:
                city, _ = City.objects.get_or_create(name=name, state=states[code])
                all_cities.append(city)

        def seed_for_company(company, user_prefix):
            self.stdout.write(f'Seeding data for {company.name}...')
            set_current_company(company)
            
            # Create a Super Admin
            admin_username = f'{user_prefix}_admin'
            admin, created = User.objects.get_or_create(
                username=admin_username,
                defaults={'email': f'{admin_username}@test.com', 'company': company, 'is_owner': True}
            )
            if created: admin.set_password('admin123'); admin.save()
            UserMembership.objects.get_or_create(user=admin, company=company, role=Role.CLIENT_SUPER_ADMIN)
            set_current_user(admin)

            # 3. Create Offices
            offices = []
            for i in range(1, 21):
                city = random.choice(all_cities)
                name = f"{city.name} Office {i}"
                office, _ = CompanyOffice.objects.get_or_create(
                    company=company, name=name, city=city,
                    defaults={
                        'address': f'Industrial Area {i}, {city.name}',
                        'phone': f'{random.randint(7000000000, 9999999999)}',
                        'office_type': random.choice([CompanyOffice.OfficeType.OWN, CompanyOffice.OfficeType.PARTNER])
                    }
                )
                offices.append(office)

            # 4. Create Users for specific branches
            roles_to_seed = [
                (Role.BRANCH_ADMIN, 'manager'),
                (Role.BOOKING_USER, 'booking'),
                (Role.ACCOUNTANT, 'acc'),
            ]
            
            for office in offices[:5]: # Only first 5 offices get dedicated users
                for role, suffix in roles_to_seed:
                    username = f"{user_prefix}_{office.name.split()[0].lower()}_{suffix}"
                    user, created = User.objects.get_or_create(
                        username=username,
                        defaults={'company': company, 'office': office}
                    )
                    if created: user.set_password('pass123'); user.save()
                    UserMembership.objects.get_or_create(user=user, company=company, office=office, role=role)

            # 5. Create Parties
            parties = []
            for i in range(1, 31):
                city = random.choice(all_cities)
                party, _ = Party.objects.get_or_create(
                    company=company, 
                    name=f"{company.name} Client {i}", 
                    phone=f"{random.randint(7000000000, 9999999999)}",
                    defaults={'city': city, 'address': f'Factory {i}, {city.name}'}
                )
                parties.append(party)

            # 6. Create Shipments
            ShipmentSequence.objects.get_or_create(company=company, date=date.today(), defaults={'last_value': 0})
            
            for i in range(1, 201):
                origin = random.choice(offices)
                destination = random.choice([o for o in offices if o != origin])
                consignor = random.choice(parties)
                consignee = random.choice(parties)
                
                status = random.choice(Shipment.StatusChoices.values)
                basis = random.choice(Shipment.BasisChoices.values)
                payment = random.choice(Shipment.PaymentTypeChoices.values)
                
                shipment = Shipment.objects.create(
                    company=company,
                    lr_no=f'{user_prefix.upper()}{date.today().strftime("%y%m")}{i:04d}',
                    date=date.today() - timedelta(days=random.randint(0, 30)),
                    status=status,
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
                    freight=Decimal(random.randint(500, 5000)),
                    total_actual_weight=Decimal(random.randint(20, 500)),
                    total_charge_weight=Decimal(random.randint(20, 500)),
                    total_packages=random.randint(1, 50)
                )

                # Add Booked Event
                ShipmentEvent.objects.create(
                    shipment=shipment,
                    event_type=ShipmentEvent.EventType.BOOKED,
                    office=origin,
                    actor=admin,
                    occurred_at=timezone.now() - timedelta(days=2)
                )

        # Execute for both companies
        seed_for_company(metro, 'metro')
        seed_for_company(swift, 'swift')

        self.stdout.write(self.style.SUCCESS('Successfully seeded multi-tenant, multi-user data'))
