import os
import django
import random
from datetime import date, timedelta
from decimal import Decimal

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.db import transaction
from core.models import State, City, Branch, Company, User, Party
from dockets.models import Docket, DocketLineItem
from dockets.utils import generate_docket_no
from core.request_context import set_current_user, set_current_company

def seed():
    print("Starting database seeding...")
    
    with transaction.atomic():
        # 1. Get or create Company
        company, created = Company.objects.get_or_create(name="Metro Logistics Corp")
        if created:
            print(f"Created company: {company.name}")
        
        # 2. Get or create Admin User
        admin_user = User.objects.filter(is_superuser=True).first()
        if not admin_user:
            admin_user = User.objects.create_superuser('admin', 'admin@example.com', 'admin')
            admin_user.company = company
            admin_user.save()
            print("Created superuser 'admin' with password 'admin'")
        else:
            if not admin_user.company:
                admin_user.company = company
                admin_user.save()
            print(f"Using existing superuser: {admin_user.username}")

        # Create/Update 'metro' superuser
        metro_user = User.objects.filter(username='metro').first()
        if not metro_user:
            metro_user = User.objects.create_superuser('metro', 'metro@example.com', '123')
            metro_user.company = company
            metro_user.save()
            print("Created superuser 'metro' with password '123'")
        else:
            metro_user.set_password('123')
            metro_user.company = company
            metro_user.save()
            print("Updated superuser 'metro' password to '123'")

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
        # Create a branch for each state's primary city if it doesn't exist
        for city in all_cities:
            # For testing, let's just create branches in major cities
            if city.name in ["Mumbai", "Pune", "Ahmedabad", "Bangalore", "New Delhi", "Kolkata", "Hyderabad", "Chennai"]:
                branch, created = Branch.objects.get_or_create(
                    company=company,
                    name=f"{city.name} Branch",
                    defaults={'city': city}
                )
                if created:
                    # print(f"Created branch: {branch.name}")
                    pass
        
        all_branches = list(Branch.objects.filter(company=company))
        print(f"Ensured {len(all_branches)} branches.")

        # 5. Parties
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

        # 6. Dockets
        print("Creating 100 dockets...")
        statuses = [choice[0] for choice in Docket.StatusChoices.choices]
        bases = [choice[0] for choice in Docket.BasisChoices.choices]
        payment_types = [choice[0] for choice in Docket.PaymentTypeChoices.choices]
        modes = [choice[0] for choice in Docket.ModeChoices.choices]
        delivery_types = [choice[0] for choice in Docket.DeliveryTypeChoices.choices]
        
        item_types = [choice[0] for choice in DocketLineItem.ItemTypeChoices.choices]
        package_types = [choice[0] for choice in DocketLineItem.PackageTypeChoices.choices]
        rate_types = [choice[0] for choice in DocketLineItem.RateTypeChoices.choices]

        # Use a fixed range of dates for better testing
        today = date.today()
        
        for i in range(100):
            docket_date = today - timedelta(days=random.randint(0, 30))
            origin_branch = random.choice(all_branches)
            dest_branch = random.choice(all_branches)
            while dest_branch == origin_branch:
                dest_branch = random.choice(all_branches)
            
            consignor = random.choice(all_parties)
            consignee = random.choice(all_parties)
            while consignee == consignor:
                consignee = random.choice(all_parties)
            
            status = random.choice(statuses)
            # If date is older, more likely to be delivered
            if (today - docket_date).days > 15 and random.random() > 0.2:
                status = Docket.StatusChoices.DELIVERED
            
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
                notes="Seeded test docket",
                created_by=admin_user,
                updated_by=admin_user,
                # Temporary values to satisfy non-null/check constraints
                total_actual_weight=Decimal('0.00'),
                total_charge_weight=Decimal('0.00'),
            )
            
            # Generate docket number
            docket.docket_no = generate_docket_no(docket_date, company)
            docket.save()
            
            # Create line items
            num_items = random.randint(1, 3)
            total_freight = Decimal('0.00')
            total_pkgs = 0
            total_act_w = Decimal('0.00')
            total_chg_w = Decimal('0.00')
            
            for _ in range(num_items):
                pieces = random.randint(1, 50)
                act_w = Decimal(str(round(random.uniform(5.0, 500.0), 2)))
                chg_w = act_w + Decimal(str(round(random.uniform(0.0, 50.0), 2)))
                
                rate_type = random.choice(rate_types)
                rate = Decimal(str(round(random.uniform(2.0, 20.0), 2)))
                
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
            
            # Update totals on docket
            docket.freight = total_freight
            docket.total_packages = total_pkgs
            docket.total_actual_weight = total_act_w
            docket.total_charge_weight = total_chg_w
            
            # Add some charges
            if random.random() > 0.7:
                docket.additional_charges = Decimal(str(random.randint(50, 500)))
            if random.random() > 0.7:
                docket.delivery_charge = Decimal(str(random.randint(100, 1000)))
            
            # Add advance if PAID
            final_f = docket.freight + docket.additional_charges + docket.delivery_charge
            if docket.payment_type == Docket.PaymentTypeChoices.PAID:
                docket.advance_amount = final_f
            elif random.random() > 0.5:
                # Partial advance
                docket.advance_amount = (final_f * Decimal('0.3')).quantize(Decimal('0.01'))
            
            docket.save()

    print("Seeding completed successfully!")

if __name__ == "__main__":
    seed()
