from django.db import migrations


TENANT_TABLES = [
    "core_companyoffice",
    "core_companyrolepermissionoverride",
    "core_party",
    "core_usermembership",
    "shipments_deliveryassignment",
    "shipments_officeratepolicy",
    "shipments_proofofdelivery",
    "shipments_ratecard",
    "shipments_raterule",
    "shipments_shipment",
    "shipments_shipmentevent",
    "shipments_shipmentlineitem",
    "shipments_shipmentsequence",
    "accounts_bankpaymentverification",
    "accounts_expense",
    "accounts_invoice",
    "accounts_invoiceline",
    "accounts_ledgerentry",
    "accounts_paymentreceipt",
]


def _quoted_table_list():
    return ", ".join(f"'{table}'::regclass" for table in TENANT_TABLES)


FORWARD_SQL = f"""
DO $$
DECLARE
    tenant_tables regclass[] := ARRAY[{_quoted_table_list()}];
    tenant_table regclass;
    constraint_row record;
    pk_name text;
BEGIN
    FOR constraint_row IN
        SELECT con.conrelid::regclass AS table_name, con.conname AS constraint_name
        FROM pg_constraint con
        WHERE con.contype = 'f'
          AND con.confrelid = ANY(tenant_tables)
    LOOP
        EXECUTE format(
            'ALTER TABLE %s DROP CONSTRAINT IF EXISTS %I',
            constraint_row.table_name,
            constraint_row.constraint_name
        );
    END LOOP;

    FOR constraint_row IN
        SELECT con.conrelid::regclass AS table_name, con.conname AS constraint_name
        FROM pg_constraint con
        WHERE con.contype = 'u'
          AND con.conrelid = ANY(tenant_tables)
          AND NOT EXISTS (
              SELECT 1
              FROM unnest(con.conkey) AS key(attnum)
              JOIN pg_attribute att
                ON att.attrelid = con.conrelid
               AND att.attnum = key.attnum
              WHERE att.attname = 'company_id'
          )
    LOOP
        EXECUTE format(
            'ALTER TABLE %s DROP CONSTRAINT IF EXISTS %I',
            constraint_row.table_name,
            constraint_row.constraint_name
        );
    END LOOP;

    FOREACH tenant_table IN ARRAY tenant_tables
    LOOP
        SELECT con.conname INTO pk_name
        FROM pg_constraint con
        WHERE con.contype = 'p'
          AND con.conrelid = tenant_table;

        IF pk_name IS NOT NULL THEN
            EXECUTE format('ALTER TABLE %s DROP CONSTRAINT IF EXISTS %I', tenant_table, pk_name);
        END IF;

        EXECUTE format(
            'ALTER TABLE %s ADD CONSTRAINT %I PRIMARY KEY (company_id, id)',
            tenant_table,
            replace(tenant_table::text, '.', '_') || '_company_id_id_pk'
        );
    END LOOP;
END $$;
"""


REVERSE_SQL = f"""
DO $$
DECLARE
    tenant_tables regclass[] := ARRAY[{_quoted_table_list()}];
    tenant_table regclass;
    pk_name text;
BEGIN
    FOREACH tenant_table IN ARRAY tenant_tables
    LOOP
        SELECT con.conname INTO pk_name
        FROM pg_constraint con
        WHERE con.contype = 'p'
          AND con.conrelid = tenant_table;

        IF pk_name IS NOT NULL THEN
            EXECUTE format('ALTER TABLE %s DROP CONSTRAINT IF EXISTS %I', tenant_table, pk_name);
        END IF;

        EXECUTE format(
            'ALTER TABLE %s ADD CONSTRAINT %I PRIMARY KEY (id)',
            tenant_table,
            replace(tenant_table::text, '.', '_') || '_pkey'
        );
    END LOOP;
END $$;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_initial"),
        ("core", "0001_initial"),
        ("shipments", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(sql=FORWARD_SQL, reverse_sql=REVERSE_SQL, state_operations=[]),
    ]
