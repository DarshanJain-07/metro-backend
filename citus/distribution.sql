-- Manual Citus lab SQL. Run only against the local Citus coordinator after
-- applying Django migrations. Plain Postgres remains the default target.

SELECT citus_set_coordinator_host('citus-coordinator', 5432);
SELECT master_add_node('citus-worker-1', 5432);

SELECT create_reference_table('core_state');
SELECT create_reference_table('core_city');
SELECT create_reference_table('core_permissioncatalog');
SELECT create_reference_table('core_roletemplate');
SELECT create_reference_table('core_roletemplatepermission');
SELECT create_reference_table('auth_group');
SELECT create_reference_table('auth_permission');
SELECT create_reference_table('django_content_type');

SELECT create_distributed_table('core_company', 'id');

SELECT create_distributed_table('core_companyoffice', 'company_id');
SELECT create_distributed_table('core_companyrolepermissionoverride', 'company_id');
SELECT create_distributed_table('core_party', 'company_id');
SELECT create_distributed_table('core_usermembership', 'company_id');

SELECT create_distributed_table('shipments_shipment', 'company_id');
SELECT create_distributed_table('shipments_shipmentlineitem', 'company_id');
SELECT create_distributed_table('shipments_shipmentevent', 'company_id');
SELECT create_distributed_table('shipments_deliveryassignment', 'company_id');
SELECT create_distributed_table('shipments_proofofdelivery', 'company_id');
SELECT create_distributed_table('shipments_ratecard', 'company_id');
SELECT create_distributed_table('shipments_raterule', 'company_id');
SELECT create_distributed_table('shipments_officeratepolicy', 'company_id');
SELECT create_distributed_table('shipments_shipmentsequence', 'company_id');

SELECT create_distributed_table('accounts_invoice', 'company_id');
SELECT create_distributed_table('accounts_invoiceline', 'company_id');
SELECT create_distributed_table('accounts_paymentreceipt', 'company_id');
SELECT create_distributed_table('accounts_bankpaymentverification', 'company_id');
SELECT create_distributed_table('accounts_ledgerentry', 'company_id');
SELECT create_distributed_table('accounts_expense', 'company_id');
