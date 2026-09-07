{{ config(materialized='table', sort=['account_country']) }}

SELECT
    sfdc_account.id,
    sfdc_account.name,
    sfdc_account.BillingCountry,
    IFNULL(sfdc_account.status, 'unknown') AS status
FROM {{ source('salesforce_crm', 'Account') }} sfdc_account
LEFT JOIN {{ source('stitch_zuora_prod', 'Account') }} zuora_account
  ON sfdc_account.id = zuora_account.id
