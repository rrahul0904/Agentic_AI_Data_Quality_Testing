{{ config(materialized='table', sort=['account_country']) }}

SELECT DISTINCT
    id_salesforce,
    id_account,
    sfdc_account.ParentId AS id_salesforce_parent,
    sfdc_account.name AS account_name,
    sfdc_account.ultimate_parent_text__c AS parent_name,
    Marketing_Affiliate__c AS marketing_affiliate,
    Marketing_Affiliate2__c AS marketing_affiliate2,
    Management_Company__c AS management_company,
    Brand__c AS brand,
    Ownership__c AS ownership_group
FROM {{ ref('account_primary') }} account_primary
LEFT JOIN {{ source('salesforce_crm', 'Account') }} sfdc_account
  ON account_primary.id_salesforce = sfdc_account.Account_ID_API__c
 AND account_primary.id_account = sfdc_account.Account_ID__c
