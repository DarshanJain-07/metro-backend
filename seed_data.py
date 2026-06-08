import os
import django
import random
from datetime import date, datetime, timedelta
from decimal import Decimal

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.db import transaction
from django.utils import timezone
from core.models import State, City, Branch, Company, User, Party, Role, UserMembership
from dockets.models import (
    Docket, DocketLineItem, RateCard, RateRule, 
    BranchRatePolicy, DocketStatusEvent, DeliveryAssignment, ProofOfDelivery
)
from dockets.utils import generate_docket_no
from core.request_context import set_current_user, set_current_company

def seed():
    print("Starting enhanced database seeding...")
    
    with transaction.atomic():
        # 0. Cleanup existing data (optional, but recommended for clean init)
        print("Cleaning up existing data...")
        ProofOfDelivery.objects.all().delete()
        DeliveryAssignment.objects.all().delete()
        DocketStatusEvent.objects.all().delete()
        DocketLineItem.objects.all().delete()
        Docket.objects.all().delete()
        RateRule.objects.all().delete()
        RateCard.objects.all().delete()
        BranchRatePolicy.objects.all().delete()
        UserMembership.objects.all().delete()
        Party.objects.all().delete()
        # We'll keep Users, Cities, States, Companies to avoid breaking foreign keys 
        # but you could clear them too if needed. 
        # For now, let's keep it surgical.

        # 1. Get or create Company
        company, created = Company.objects.get_or_create(name="Metro Logistics Corp")
        if created:
            print(f"Created company: {company.name}")
        
        # 2. Users
        # Admin User
        admin_user = User.objects.filter(username='admin').first()
        if not admin_user:
            admin_user = User.objects.create_superuser('admin', 'admin@example.com', 'admin')
            admin_user.company = company
            admin_user.save()
            print("Created superuser 'admin' with password 'admin'")
        else:
            admin_user.company = company
            admin_user.save()

        # Metro User (Client Super Admin)
        metro_user = User.objects.filter(username='metro').first()
        if not metro_user:
            metro_user = User.objects.create_user('metro', 'metro@example.com', '123')
            metro_user.company = company
            metro_user.is_staff = True
            metro_user.save()
            print("Created user 'metro' with password '123'")
        else:
            metro_user.set_password('123')
            metro_user.company = company
            metro_user.save()

        # Set context for AuditBaseModel
        set_current_user(admin_user)
        set_current_company(company)

        # 3. States and Cities
        states_data = [
            ("Maharashtra", "MH", ["Mumbai", "Pune", "Nagpur", "Nashik", "Aurangabad"]),
            ("Gujarat", "GJ", ["Ahmedabad", "Surat", "Vadodara", "Rajkot"]),
            ("Karnataka", "KA", ["Bangalore", "Hubli", "Mangalore", "Mysore"]),
            ("Delhi", "DL", ["New Delhi"]),
            ("West Bengal", "WB", ["Kolkata", "Howrah", "Siliguri"]),
            ("Telangana", "TG", ["Hyderabad", "Warangal"]),
            ("Tamil Nadu", "TN", ["Chennai", "Coimbatore", "Madurai"]),
            ("Rajasthan", "RJ", ["Jaipur", "Jodhpur", "Udaipur"]),
        ]

        all_cities = []
        for state_name, state_code, cities in states_data:
            state, _ = State.objects.get_or_create(code=state_code, defaults={'name': state_name})
            for city_name in cities:
                city, _ = City.objects.get_or_create(name=city_name, state=state)
                all_cities.append(city)
        
        print(f"Ensured {State.objects.count()} states and {City.objects.count()} cities.")

        # 4. Branches
        major_cities = ["Mumbai", "Pune", "Ahmedabad", "Bangalore", "New Delhi", "Kolkata", "Hyderabad", "Chennai"]
        all_branches = []
        for city_name in major_cities:
            city = City.objects.get(name=city_name)
            branch, created = Branch.objects.get_or_create(
                company=company,
                name=f"{city.name} Branch",
                defaults={'city': city}
            )
            all_branches.append(branch)
            
            # Create Branch Rate Policy
            BranchRatePolicy.objects.get_or_create(
                company=company,
                branch=branch,
                defaults={
                    'can_override_rate': True,
                    'max_discount_percent': Decimal('10.00'),
                    'requires_approval': False
                }
            )
        
        print(f"Ensured {len(all_branches)} branches with rate policies.")

        # 5. Memberships for 'metro' user
        # Give 'metro' user Client Super Admin role for the company
        UserMembership.objects.get_or_create(
            user=metro_user,
            company=company,
            role=Role.CLIENT_SUPER_ADMIN,
            branch=None
        )
        
        # Also assign 'metro' to Mumbai Branch as Branch Admin for testing branch scoping
        mumbai_branch = Branch.objects.get(name="Mumbai Branch")
        UserMembership.objects.get_or_create(
            user=metro_user,
            company=company,
            role=Role.BRANCH_ADMIN,
            branch=mumbai_branch
        )
        
        # Create some other functional users
        users_to_create = [
            ('pune_mgr', Role.BRANCH_ADMIN, "Pune Branch"),
            ('blr_booking', Role.BOOKING_USER, "Bangalore Branch"),
            ('del_delivery', Role.DELIVERY_USER, "New Delhi Branch"),
        ]
        
        for username, role, branch_name in users_to_create:
            u, _ = User.objects.get_or_create(username=username, defaults={'email': f'{username}@example.com'})
            u.set_password('password123')
            u.company = company
            u.save()
            
            branch = Branch.objects.get(name=branch_name)
            UserMembership.objects.get_or_create(
                user=u,
                company=company,
                role=role,
                branch=branch
            )

        # 6. Parties
        party_names = [
            "Reliance Industries", "Tata Motors", "Infosys Ltd", "Wipro", "HDFC Bank",
            "Adani Enterprises", "Mahindra & Mahindra", "Sun Pharma", "ICICI Bank", "L&T",
            "ITC Limited", "Bharti Airtel", "Kotak Mahindra", "Bajaj Finance", "Axis Bank",
            "Asian Paints", "HCL Tech", "Maruti Suzuki", "Titan Company", "UltraTech Cement"
        ]
        
        all_parties = []
        for name in party_names:
            city = random.choice(all_cities)
            phone = str(random.randint(7000000000, 9999999999))
            party, created = Party.objects.get_or_create(
                company=company,
                name=name,
                defaults={
                    'phone': phone,
                    'address': f"Plot {random.randint(1, 500)}, Industrial Area, {city.name}",
                    'city': city,
                    'gst_number': f"{random.randint(10, 35)}AAAAA{random.randint(1000, 9999)}A1Z{random.randint(1, 9)}"
                }
            )
            all_parties.append(party)
        
        print(f"Ensured {len(all_parties)} parties.")

        # 7. Rate Cards and Rules
        rate_card, _ = RateCard.objects.get_or_create(
            company=company,
            name="Standard Rate Card 2024",
            defaults={
                'is_default': True,
                'effective_from': timezone.now() - timedelta(days=365)
            }
        )
        
        # Create some rules between major cities
        for origin in all_branches:
            for destination in all_branches:
                if origin == destination: continue
                RateRule.objects.get_or_create(
                    rate_card=rate_card,
                    origin_city=origin.city,
                    destination_city=destination.city,
                    defaults={
                        'basis': Docket.BasisChoices.WEIGHT,
                        'rate_type': DocketLineItem.RateTypeChoices.PER_KG,
                        'rate': Decimal(str(random.randint(5, 15))),
                        'min_charge': Decimal('100.00'),
                        'delivery_charge': Decimal('50.00')
                    }
                )

        # 8. Dockets
        print("Creating 150 dockets with history...")
        statuses = [choice[0] for choice in Docket.StatusChoices.choices]
        bases = [choice[0] for choice in Docket.BasisChoices.choices]
        payment_types = [choice[0] for choice in Docket.PaymentTypeChoices.choices]
        modes = [choice[0] for choice in Docket.ModeChoices.choices]
        delivery_types = [choice[0] for choice in Docket.DeliveryTypeChoices.choices]
        
        item_types = [choice[0] for choice in DocketLineItem.ItemTypeChoices.choices]
        package_types = [choice[0] for choice in DocketLineItem.PackageTypeChoices.choices]
        rate_types = [choice[0] for choice in DocketLineItem.RateTypeChoices.choices]

        today = date.today()
        
        for i in range(150):
            docket_date = today - timedelta(days=random.randint(0, 45))
            origin_branch = random.choice(all_branches)
            dest_branch = random.choice(all_branches)
            while dest_branch == origin_branch:
                dest_branch = random.choice(all_branches)
            
            consignor = random.choice(all_parties)
            consignee = random.choice(all_parties)
            while consignee == consignor:
                consignee = random.choice(all_parties)
            
            status = random.choice(statuses)
            # Logical status progression based on age
            age_days = (today - docket_date).days
            if age_days > 20:
                status = random.choice([Docket.StatusChoices.DELIVERED, Docket.StatusChoices.CANCELLED, Docket.StatusChoices.DELIVERED])
            elif age_days > 10:
                status = random.choice([Docket.StatusChoices.IN_TRANSIT, Docket.StatusChoices.INCOMING, Docket.StatusChoices.DELIVERED])
            elif age_days > 5:
                status = random.choice([Docket.StatusChoices.BOOKED, Docket.StatusChoices.IN_TRANSIT])
            
            docket = Docket(
                company=company,
                date=docket_date,
                status=status,
                from_city=origin_branch.city,
                origin_branch=origin_branch,
                to_city=dest_branch.city,
                destination_branch=dest_branch,
                basis=random.choice(bases),
                payment_type=random.choice(payment_types),
                mode=random.choice(modes),
                delivery_type=random.choice(delivery_types),
                consignor_name=consignor.name,
                consignor_city=consignor.city,
                consignor_phone=consignor.phone,
                consignor_address=consignor.address,
                consignee_name=consignee.name,
                consignee_city=consignee.city,
                consignee_phone=consignee.phone,
                consignee_address=consignee.address,
                gst_party=consignor.name if random.random() > 0.5 else consignee.name,
                gst_number=consignor.gst_number if random.random() > 0.5 else consignee.gst_number,
                notes=f"Seeded test docket {i}",
                created_by=admin_user,
                updated_by=admin_user,
                total_actual_weight=Decimal('0.00'),
                total_charge_weight=Decimal('0.00'),
            )
            
            docket.docket_no = generate_docket_no(docket_date, company)
            docket.save()
            
            # Create line items
            num_items = random.randint(1, 4)
            total_freight = Decimal('0.00')
            total_pkgs = 0
            total_act_w = Decimal('0.00')
            total_chg_w = Decimal('0.00')
            
            for _ in range(num_items):
                pieces = random.randint(1, 100)
                act_w = Decimal(str(round(random.uniform(1.0, 1000.0), 2)))
                chg_w = act_w * Decimal('1.1') # Simulating volumetric
                
                rate_type = random.choice(rate_types)
                rate = Decimal(str(round(random.uniform(2.0, 50.0), 2)))
                
                if rate_type == DocketLineItem.RateTypeChoices.PER_KG:
                    charge = (rate * chg_w).quantize(Decimal('0.01'))
                elif rate_type == DocketLineItem.RateTypeChoices.PER_PIECE:
                    charge = (rate * pieces).quantize(Decimal('0.01'))
                else: # Flat
                    charge = rate.quantize(Decimal('0.01'))
                
                DocketLineItem.objects.create(
                    docket=docket,
                    item_type=random.choice(item_types),
                    package_type=random.choice(package_types),
                    rate_type=rate_type,
                    pieces=pieces,
                    actual_weight=act_w,
                    charged_weight=chg_w,
                    rate=rate,
                    charge=charge,
                    created_by=admin_user,
                    updated_by=admin_user
                )
                
                total_freight += charge
                total_pkgs += pieces
                total_act_w += act_w
                total_chg_w += chg_w
            
            docket.freight = total_freight
            docket.total_packages = total_pkgs
            docket.total_actual_weight = total_act_w
            docket.total_charge_weight = total_chg_w
            
            if random.random() > 0.5:
                docket.additional_charges = Decimal(str(random.randint(20, 200)))
            if random.random() > 0.5:
                docket.delivery_charge = Decimal(str(random.randint(50, 500)))
            
            final_f = docket.freight + docket.additional_charges + docket.delivery_charge
            if docket.payment_type == Docket.PaymentTypeChoices.PAID:
                docket.advance_amount = final_f
            elif random.random() > 0.3:
                docket.advance_amount = (final_f * Decimal(str(random.uniform(0.1, 0.5)))).quantize(Decimal('0.01'))
            
            docket.save()

            # Create some status history
            DocketStatusEvent.objects.create(
                docket=docket,
                from_status=Docket.StatusChoices.DRAFT,
                to_status=Docket.StatusChoices.BOOKED,
                changed_by=admin_user,
                branch=origin_branch,
                notes="Initial booking"
            )
            
            if docket.status in [Docket.StatusChoices.IN_TRANSIT, Docket.StatusChoices.INCOMING, Docket.StatusChoices.DELIVERED]:
                DocketStatusEvent.objects.create(
                    docket=docket,
                    from_status=Docket.StatusChoices.BOOKED,
                    to_status=Docket.StatusChoices.IN_TRANSIT,
                    changed_by=admin_user,
                    branch=origin_branch,
                    notes="Dispatched from origin"
                )
            
            if docket.status in [Docket.StatusChoices.INCOMING, Docket.StatusChoices.DELIVERED]:
                DocketStatusEvent.objects.create(
                    docket=docket,
                    from_status=Docket.StatusChoices.IN_TRANSIT,
                    to_status=Docket.StatusChoices.INCOMING,
                    changed_by=admin_user,
                    branch=dest_branch,
                    notes="Received at destination"
                )

            # Create Delivery Assignment and POD if DELIVERED
            if docket.status == Docket.StatusChoices.DELIVERED:
                delivery_user = User.objects.get(username='del_delivery')
                assignment = DeliveryAssignment.objects.create(
                    docket=docket,
                    delivery_user=delivery_user,
                    assigned_by=admin_user,
                    status=DeliveryAssignment.StatusChoices.COMPLETED,
                    completed_at=timezone.now() - timedelta(hours=random.randint(1, 24))
                )
                
                ProofOfDelivery.objects.create(
                    docket=docket,
                    received_by_name=docket.consignee_name,
                    received_by_phone=docket.consignee_phone,
                    delivery_notes="Delivered successfully",
                    delivered_at=assignment.completed_at
                )

    print("Enhanced seeding completed successfully!")

if __name__ == "__main__":
    seed()
