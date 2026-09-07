# Security model

Secrets stay in environment/configuration files excluded from Git. Connector
adapters expose read-only operations only. Destructive SQL is denied by policy;
production mutations and external/workspace writes require explicit approval.
Failure and quality logs redact password, token, secret, API-key, and private
credential values.
