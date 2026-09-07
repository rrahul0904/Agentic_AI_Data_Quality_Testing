from shiftforge.dbt import extract_sort_keys, selected_columns, enforce_sort_keys


SQL = """{{ config(materialized='table', sort=['account_country']) }}
SELECT
  id_salesforce,
  sfdc_account.name AS account_name
FROM {{ ref('account_primary') }} account_primary
LEFT JOIN {{ source('salesforce_crm','Account') }} sfdc_account
  ON account_primary.id_salesforce = sfdc_account.Account_ID_API__c
"""


def test_extract_sort_key():
    assert extract_sort_keys(SQL) == ["account_country"]


def test_sort_key_blocks_without_hint():
    out, hits, unresolved = enforce_sort_keys(SQL)
    assert out == SQL
    assert unresolved == ["account_country"]
    assert any(h.rule_id == "RS_SORTKEY_002" for h in hits)


def test_sort_key_injected_with_explicit_hint():
    out, hits, unresolved = enforce_sort_keys(SQL, {"account_country": "sfdc_account.BillingCountry"})
    assert "sfdc_account.BillingCountry AS account_country" in out
    assert unresolved == []
    assert "account_country" in selected_columns(out)
