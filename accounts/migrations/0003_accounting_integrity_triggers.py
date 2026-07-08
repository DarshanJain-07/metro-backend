from django.db import migrations


SQL = """
CREATE OR REPLACE FUNCTION accounts_scope_allows(
    p_scope text,
    p_membership_office_id varchar,
    p_target_office_id varchar
) RETURNS boolean AS $$
BEGIN
    IF p_scope IN ('all', 'company') THEN
        RETURN TRUE;
    ELSIF p_scope IN ('branch', 'region') THEN
        IF p_target_office_id IS NULL THEN
            RETURN p_membership_office_id IS NULL;
        END IF;
        RETURN p_membership_office_id = p_target_office_id;
    END IF;

    RETURN FALSE;
END;
$$ LANGUAGE plpgsql STABLE;

CREATE OR REPLACE FUNCTION accounts_user_has_permission(
    p_user_id bigint,
    p_company_id bigint,
    p_office_id varchar,
    p_permission_code text
) RETURNS boolean AS $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM core_user
        WHERE id = p_user_id
          AND is_active
          AND is_superuser
    ) THEN
        RETURN TRUE;
    END IF;

    RETURN EXISTS (
        SELECT 1
        FROM core_usermembership membership
        JOIN core_user actor
          ON actor.id = membership.user_id
         AND actor.is_active
        LEFT JOIN core_permissioncatalog permission
          ON permission.code = p_permission_code
         AND permission.is_active
        LEFT JOIN core_companyrolepermissionoverride role_override
          ON role_override.company_id = p_company_id
         AND role_override.role = membership.role
         AND role_override.permission_id = permission.id
         AND role_override.is_active
        LEFT JOIN LATERAL (
            SELECT template_permission.scope
            FROM core_roletemplate template
            JOIN core_roletemplatepermission template_permission
              ON template_permission.template_id = template.id
             AND template_permission.permission_id = permission.id
            WHERE template.role = membership.role
              AND template.is_active
            ORDER BY template.revision DESC
            LIMIT 1
        ) template_grant ON TRUE
        WHERE membership.user_id = p_user_id
          AND membership.company_id = p_company_id
          AND membership.is_active
          AND (
            membership.role = 'METRO'
            OR membership.role = 'SUPER_ADMIN'
            OR (
                role_override.id IS NOT NULL
                AND role_override.enabled
                AND accounts_scope_allows(role_override.scope, membership.office_id, p_office_id)
            )
            OR (
                role_override.id IS NULL
                AND template_grant.scope IS NOT NULL
                AND accounts_scope_allows(template_grant.scope, membership.office_id, p_office_id)
            )
            OR (
                role_override.id IS NULL
                AND template_grant.scope IS NULL
                AND p_permission_code = 'invoice:edit'
                AND membership.role = 'ACCOUNTANT'
                AND accounts_scope_allows('branch', membership.office_id, p_office_id)
            )
          )
    );
END;
$$ LANGUAGE plpgsql STABLE;

CREATE OR REPLACE FUNCTION accounts_validate_ledger_entry()
RETURNS trigger AS $$
DECLARE
    actor_setting text;
    actor_id bigint;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Ledger entries cannot be hard-deleted';
    END IF;

    IF NEW.debit < 0 OR NEW.credit < 0 THEN
        RAISE EXCEPTION 'Ledger debit and credit must be non-negative';
    END IF;

    IF NEW.entry_type = 'DEBIT' AND NOT (NEW.debit > 0 AND NEW.credit = 0) THEN
        RAISE EXCEPTION 'Debit ledger entries must have debit > 0 and credit = 0';
    END IF;

    IF NEW.entry_type = 'CREDIT' AND NOT (NEW.credit > 0 AND NEW.debit = 0) THEN
        RAISE EXCEPTION 'Credit ledger entries must have credit > 0 and debit = 0';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM core_companyoffice
        WHERE id = NEW.office_id AND company_id = NEW.company_id
    ) THEN
        RAISE EXCEPTION 'Ledger office must belong to the ledger company';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM core_party
        WHERE id = NEW.party_id AND company_id = NEW.company_id
    ) THEN
        RAISE EXCEPTION 'Ledger party must belong to the ledger company';
    END IF;

    IF TG_OP = 'UPDATE' THEN
        IF OLD.company_id IS DISTINCT FROM NEW.company_id THEN
            RAISE EXCEPTION 'Ledger entries cannot be moved across companies';
        END IF;

        actor_setting := NULLIF(current_setting('metro.current_user_id', true), '');
        IF actor_setting IS NULL THEN
            RAISE EXCEPTION 'Ledger updates require an authenticated database actor';
        END IF;

        actor_id := actor_setting::bigint;
        IF NOT accounts_user_has_permission(actor_id, NEW.company_id, NEW.office_id, 'invoice:edit') THEN
            RAISE EXCEPTION 'User % is not authorized to update this ledger entry', actor_id;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION accounts_validate_invoice()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status <> 'DRAFT' THEN
            RAISE EXCEPTION 'Posted invoices cannot be hard-deleted';
        END IF;
        RETURN OLD;
    END IF;

    IF NEW.total_amount < 0 OR NEW.paid_amount < 0 THEN
        RAISE EXCEPTION 'Invoice amounts must be non-negative';
    END IF;

    IF NEW.paid_amount > NEW.total_amount THEN
        RAISE EXCEPTION 'Invoice paid amount cannot exceed total amount';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM core_companyoffice
        WHERE id = NEW.office_id AND company_id = NEW.company_id
    ) THEN
        RAISE EXCEPTION 'Invoice office must belong to the invoice company';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM core_party
        WHERE id = NEW.party_id AND company_id = NEW.company_id
    ) THEN
        RAISE EXCEPTION 'Invoice party must belong to the invoice company';
    END IF;

    IF TG_OP = 'UPDATE' THEN
        IF OLD.status <> NEW.status AND NOT (
            (OLD.status = 'DRAFT' AND NEW.status IN ('SENT', 'CANCELLED')) OR
            (OLD.status = 'SENT' AND NEW.status IN ('PARTIALLY_PAID', 'PAID', 'CANCELLED')) OR
            (OLD.status = 'PARTIALLY_PAID' AND NEW.status IN ('PAID', 'CANCELLED'))
        ) THEN
            RAISE EXCEPTION 'Invalid invoice status transition from % to %', OLD.status, NEW.status;
        END IF;

        IF OLD.status <> 'DRAFT' AND (
            OLD.company_id IS DISTINCT FROM NEW.company_id OR
            OLD.office_id IS DISTINCT FROM NEW.office_id OR
            OLD.party_id IS DISTINCT FROM NEW.party_id OR
            OLD.invoice_no IS DISTINCT FROM NEW.invoice_no OR
            OLD.invoice_date IS DISTINCT FROM NEW.invoice_date OR
            OLD.due_date IS DISTINCT FROM NEW.due_date OR
            OLD.total_amount IS DISTINCT FROM NEW.total_amount
        ) THEN
            RAISE EXCEPTION 'Posted invoice business fields are read-only';
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION accounts_validate_invoice_line()
RETURNS trigger AS $$
DECLARE
    invoice_status text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        SELECT status INTO invoice_status
        FROM accounts_invoice
        WHERE id = OLD.invoice_id;

        IF invoice_status <> 'DRAFT' THEN
            RAISE EXCEPTION 'Posted invoice lines cannot be deleted';
        END IF;
        RETURN OLD;
    END IF;

    IF NEW.amount < 0 THEN
        RAISE EXCEPTION 'Invoice line amount must be non-negative';
    END IF;

    SELECT status INTO invoice_status
    FROM accounts_invoice
    WHERE id = NEW.invoice_id AND company_id = NEW.company_id;

    IF invoice_status IS NULL THEN
        RAISE EXCEPTION 'Invoice line must belong to an invoice in the same company';
    END IF;

    IF NEW.shipment_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM shipments_shipment
        WHERE id = NEW.shipment_id AND company_id = NEW.company_id
    ) THEN
        RAISE EXCEPTION 'Invoice line shipment must belong to the invoice line company';
    END IF;

    IF TG_OP = 'INSERT' AND invoice_status <> 'DRAFT' THEN
        RAISE EXCEPTION 'Cannot add lines to a posted invoice';
    END IF;

    IF TG_OP = 'UPDATE' AND invoice_status <> 'DRAFT' THEN
        RAISE EXCEPTION 'Posted invoice lines are read-only';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION accounts_validate_payment_receipt()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status = 'VERIFIED' THEN
            RAISE EXCEPTION 'Verified payment receipts cannot be hard-deleted';
        END IF;
        RETURN OLD;
    END IF;

    IF NEW.amount <= 0 THEN
        RAISE EXCEPTION 'Payment receipt amount must be positive';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM core_companyoffice
        WHERE id = NEW.office_id AND company_id = NEW.company_id
    ) THEN
        RAISE EXCEPTION 'Payment receipt office must belong to the receipt company';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM core_party
        WHERE id = NEW.party_id AND company_id = NEW.company_id
    ) THEN
        RAISE EXCEPTION 'Payment receipt party must belong to the receipt company';
    END IF;

    IF TG_OP = 'UPDATE' AND OLD.status <> NEW.status AND NOT (
        OLD.status = 'PENDING' AND NEW.status IN ('VERIFIED', 'REJECTED')
    ) THEN
        RAISE EXCEPTION 'Invalid payment receipt status transition from % to %', OLD.status, NEW.status;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION accounts_validate_bank_payment_verification()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Bank payment verifications cannot be hard-deleted';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM accounts_paymentreceipt
        WHERE id = NEW.payment_receipt_id
          AND company_id = NEW.company_id
    ) THEN
        RAISE EXCEPTION 'Payment verification must belong to the receipt company';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS accounts_ledgerentry_integrity ON accounts_ledgerentry;
CREATE TRIGGER accounts_ledgerentry_integrity
BEFORE INSERT OR UPDATE OR DELETE ON accounts_ledgerentry
FOR EACH ROW EXECUTE FUNCTION accounts_validate_ledger_entry();

DROP TRIGGER IF EXISTS accounts_invoice_integrity ON accounts_invoice;
CREATE TRIGGER accounts_invoice_integrity
BEFORE INSERT OR UPDATE OR DELETE ON accounts_invoice
FOR EACH ROW EXECUTE FUNCTION accounts_validate_invoice();

DROP TRIGGER IF EXISTS accounts_invoiceline_integrity ON accounts_invoiceline;
CREATE TRIGGER accounts_invoiceline_integrity
BEFORE INSERT OR UPDATE OR DELETE ON accounts_invoiceline
FOR EACH ROW EXECUTE FUNCTION accounts_validate_invoice_line();

DROP TRIGGER IF EXISTS accounts_paymentreceipt_integrity ON accounts_paymentreceipt;
CREATE TRIGGER accounts_paymentreceipt_integrity
BEFORE INSERT OR UPDATE OR DELETE ON accounts_paymentreceipt
FOR EACH ROW EXECUTE FUNCTION accounts_validate_payment_receipt();

DROP TRIGGER IF EXISTS accounts_bankpaymentverification_integrity ON accounts_bankpaymentverification;
CREATE TRIGGER accounts_bankpaymentverification_integrity
BEFORE INSERT OR UPDATE OR DELETE ON accounts_bankpaymentverification
FOR EACH ROW EXECUTE FUNCTION accounts_validate_bank_payment_verification();
"""


REVERSE_SQL = """
DROP TRIGGER IF EXISTS accounts_bankpaymentverification_integrity ON accounts_bankpaymentverification;
DROP TRIGGER IF EXISTS accounts_paymentreceipt_integrity ON accounts_paymentreceipt;
DROP TRIGGER IF EXISTS accounts_invoiceline_integrity ON accounts_invoiceline;
DROP TRIGGER IF EXISTS accounts_invoice_integrity ON accounts_invoice;
DROP TRIGGER IF EXISTS accounts_ledgerentry_integrity ON accounts_ledgerentry;

DROP FUNCTION IF EXISTS accounts_validate_bank_payment_verification();
DROP FUNCTION IF EXISTS accounts_validate_payment_receipt();
DROP FUNCTION IF EXISTS accounts_validate_invoice_line();
DROP FUNCTION IF EXISTS accounts_validate_invoice();
DROP FUNCTION IF EXISTS accounts_validate_ledger_entry();
DROP FUNCTION IF EXISTS accounts_user_has_permission(bigint, bigint, varchar, text);
DROP FUNCTION IF EXISTS accounts_scope_allows(text, varchar, varchar);
"""


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_initial"),
        ("core", "0001_initial"),
        ("shipments", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(SQL, REVERSE_SQL),
    ]
