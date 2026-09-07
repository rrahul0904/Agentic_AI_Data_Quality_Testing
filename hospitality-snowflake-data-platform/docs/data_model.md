# Data model

The first core slice uses conformed guest, property, room, channel, loyalty, and date dimensions with reservation, room-night, payment, and clickstream facts. Reservations are one row per source reservation; room night is one row per room/date; payment is one row per processor transaction; clickstream is one row per event.

Surrogate keys are deterministic SHA-256 values over normalized natural keys. Facts retain their natural identifiers for reconciliation. Guest identity resolution joins synthetic Oracle guest and PostgreSQL app-user references and deliberately excludes names, email addresses, phone numbers, and documents from analytics models.

