import assert from "node:assert/strict";
import test from "node:test";
import { airflowDagLoadsSourceTable, dbtDiscoveryNeedsRefresh, dbtResourceIdsForSourceTable, DBT_DISCOVERY_VERSION, isPostgresSourceTableAsset, isSnowflakeRawTargetForSourceTable, newConnection, validateConnectionProfile, validateDiscoveryEvidence, type DbtLineageResource, type DiscoveryResult } from "../lib/onboarding.ts";

test("new connection forms are type-specific and untested", () => {
  const postgres = newConnection("postgres");
  const dbt = newConnection("dbt");
  const files = newConnection("files");
  assert.equal(postgres.config.authMethod, "DSN / connection URL");
  assert.equal(postgres.config.dsnEnv, "ADE_POSTGRES_DSN");
  assert.equal(newConnection("snowflake").config.authMethod, "Username + password");
  assert.equal(dbt.config.projectDir, "");
  assert.equal(files.config.storageType, "local");
  assert.equal(postgres.source, "manual");
});

test("connection profiles reject raw secrets", () => {
  const profile = newConnection("snowflake");
  profile.config.password = "do-not-store-this";
  assert.throws(() => validateConnectionProfile(profile), /Raw secret field/);
});

test("connection profiles accept environment-variable references", () => {
  const profile = newConnection("snowflake");
  profile.config.passwordEnv = "ADE_SNOWFLAKE_PASSWORD";
  assert.equal(validateConnectionProfile(profile).config.passwordEnv, "ADE_SNOWFLAKE_PASSWORD");
});

test("passing discovery requires complete evidence on every displayed asset", () => {
  const result: DiscoveryResult = {
    status: "PASS",
    detail: "one live object",
    source: "information_schema",
    discoveredAt: "2026-09-12T15:54:09.000Z",
    assets: [{
      id: "postgres:public:bookings",
      connectionId: "postgres",
      name: "bookings",
      type: "BASE TABLE",
      proposedLayer: "Sources",
      roleStatus: "PROPOSED",
      evidence: {
        source: "PostgreSQL information_schema.tables",
        collectedAt: "2026-09-12T15:54:09.000Z",
        collectionMethod: "Authenticated information_schema query",
        classification: "LIVE_RUNTIME",
        confidence: "HIGH",
        location: "hospitality.public.bookings",
      },
    }],
  };
  assert.equal(validateDiscoveryEvidence(result, "postgres"), result);
  assert.throws(() => validateDiscoveryEvidence({ ...result, assets: [{ ...result.assets[0], evidence: undefined }] }, "postgres"), /missing required evidence/);
  assert.throws(() => validateDiscoveryEvidence({ ...result, assets: [{ ...result.assets[0], connectionId: "other" }] }, "postgres"), /not bound to the tested connection/);
});

test("Airflow matches every source table from the exact discovered task-group identity", () => {
  const dags: Record<string, string[]> = {
    ingest_reference_data: ["load_properties.determine_window", "load_room_types.determine_window", "load_rooms.determine_window", "load_booking_channels.determine_window", "load_promotions.determine_window", "load_rate_plans.determine_window"],
    ingest_guests: ["load_guests.determine_window"],
    ingest_inventory: ["load_room_inventory.determine_window"],
    ingest_loyalty_accounts: ["load_loyalty_accounts.determine_window"],
    ingest_payments: ["load_payments.determine_window"],
    payment_backfill: ["load_payments.determine_window"],
    ingest_refunds: ["load_refunds.determine_window"],
    ingest_reservation_guests: ["load_reservation_guests.determine_window"],
    ingest_reservations: ["load_reservations.determine_window"],
    reservation_backfill: ["load_reservations.determine_window"],
    ingest_stays: ["load_stays.determine_window"],
  };
  const expected = new Map<string, string[]>([
    ["booking_channels", ["ingest_reference_data"]], ["guests", ["ingest_guests"]],
    ["loyalty_accounts", ["ingest_loyalty_accounts"]], ["payments", ["ingest_payments", "payment_backfill"]],
    ["promotions", ["ingest_reference_data"]], ["properties", ["ingest_reference_data"]],
    ["rate_plans", ["ingest_reference_data"]], ["refunds", ["ingest_refunds"]],
    ["reservation_guests", ["ingest_reservation_guests"]], ["reservations", ["ingest_reservations", "reservation_backfill"]],
    ["room_inventory", ["ingest_inventory"]], ["room_types", ["ingest_reference_data"]],
    ["rooms", ["ingest_reference_data"]], ["stays", ["ingest_stays"]],
    ["reservation_status_history", []],
  ]);
  for (const [table, expectedDags] of expected) {
    const actual = Object.entries(dags).filter(([, tasks]) => tasks.some((task) => airflowDagLoadsSourceTable([task], table))).map(([dag]) => dag).sort();
    assert.deepEqual(actual, [...expectedDags].sort(), `${table} must match only its discovered ingestion task group(s)`);
  }
});

test("source and warehouse matches require exact canonical database, schema, name, and object type", () => {
  const source = { database: "hospitality_oltp", schema: "public", table: "guests" };
  assert.equal(isPostgresSourceTableAsset({ catalog: "hospitality_oltp", schema: "public", name: "guests" }, source), true);
  assert.equal(isPostgresSourceTableAsset({ catalog: "hospitality_oltp", schema: "public", name: "reservation_guests" }, source), false);
  assert.equal(isPostgresSourceTableAsset({ catalog: "other_db", schema: "public", name: "guests" }, source), false);

  const target = { catalog: "HOSPITALITY_RELIABILITY_LAB", schema: "RAW", name: "GUESTS", type: "BASE TABLE" };
  assert.equal(isSnowflakeRawTargetForSourceTable(target, "guests", "HOSPITALITY_RELIABILITY_LAB"), true);
  assert.equal(isSnowflakeRawTargetForSourceTable({ ...target, schema: "STAGING" }, "guests", "HOSPITALITY_RELIABILITY_LAB"), false);
  assert.equal(isSnowflakeRawTargetForSourceTable({ ...target, catalog: "OTHER_DB" }, "guests", "HOSPITALITY_RELIABILITY_LAB"), false);
  assert.equal(isSnowflakeRawTargetForSourceTable({ ...target, name: "RESERVATION_GUESTS" }, "guests", "HOSPITALITY_RELIABILITY_LAB"), false);
  assert.equal(isSnowflakeRawTargetForSourceTable({ ...target, type: "VIEW" }, "guests", "HOSPITALITY_RELIABILITY_LAB"), false);
  assert.equal(isSnowflakeRawTargetForSourceTable(target, "guests", ""), false);
});

test("dbt source-table scope follows exact manifest edges and includes related models and defined tests", () => {
  const resources: DbtLineageResource[] = [
    { unique_id: "source.project.raw.guests", name: "guests", resource_type: "source", database: "HOSPITALITY_RELIABILITY_LAB", schema: "RAW" },
    { unique_id: "source.project.raw.reservation_guests", name: "reservation_guests", resource_type: "source", database: "HOSPITALITY_RELIABILITY_LAB", schema: "RAW" },
    { unique_id: "model.project.stg_guests", name: "stg_guests", resource_type: "model", depends_on: { nodes: ["source.project.raw.guests"] } },
    { unique_id: "model.project.int_guest_stay_history", name: "int_guest_stay_history", resource_type: "model", depends_on: { nodes: ["model.project.stg_guests"] } },
    { unique_id: "test.project.not_null_stg_guests_guest_id", name: "not_null_stg_guests_guest_id", resource_type: "test", depends_on: { nodes: ["model.project.stg_guests"] } },
    { unique_id: "test.project.not_null_guest_id", name: "not_null_guest_id", resource_type: "test", depends_on: { nodes: ["model.project.int_guest_stay_history"] } },
    { unique_id: "model.project.stg_reservation_guests", name: "stg_reservation_guests", resource_type: "model", depends_on: { nodes: ["source.project.raw.reservation_guests"] } },
    { unique_id: "test.project.not_null_reservation_guest_id", name: "not_null_reservation_guest_id", resource_type: "test", depends_on: { nodes: ["model.project.stg_reservation_guests"] } },
  ];

  assert.deepEqual(
    [...dbtResourceIdsForSourceTable(resources, "guests", ["HOSPITALITY_RELIABILITY_LAB"])].sort(),
    ["model.project.int_guest_stay_history", "model.project.stg_guests", "test.project.not_null_guest_id", "test.project.not_null_stg_guests_guest_id"].sort(),
  );
  assert.deepEqual([...dbtResourceIdsForSourceTable(resources, "reservation_guests", ["HOSPITALITY_RELIABILITY_LAB"])].sort(), ["model.project.stg_reservation_guests", "test.project.not_null_reservation_guest_id"].sort());
  assert.deepEqual([...dbtResourceIdsForSourceTable(resources, "missing_table", ["HOSPITALITY_RELIABILITY_LAB"])], []);
  assert.deepEqual([...dbtResourceIdsForSourceTable(resources, "guests", [])], []);
  assert.deepEqual([...dbtResourceIdsForSourceTable(resources, "guests", ["OTHER_DATABASE"])], []);
  assert.deepEqual([...dbtResourceIdsForSourceTable([...resources, { unique_id: "source.other.raw.guests", name: "guests", resource_type: "source", database: "HOSPITALITY_RELIABILITY_LAB", schema: "RAW" }], "guests", ["HOSPITALITY_RELIABILITY_LAB"])], []);
});

test("legacy dbt discovery is marked for refresh until test-aware inventory has been collected", () => {
  assert.equal(dbtDiscoveryNeedsRefresh({ status: "PASS" }), true);
  assert.equal(dbtDiscoveryNeedsRefresh({ status: "PASS", discoveryVersion: DBT_DISCOVERY_VERSION }), false);
  assert.equal(dbtDiscoveryNeedsRefresh({ status: "FAIL" }), false);
  assert.equal(dbtDiscoveryNeedsRefresh(undefined), false);
});
