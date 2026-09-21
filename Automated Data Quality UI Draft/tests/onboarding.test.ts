import assert from "node:assert/strict";
import test from "node:test";
import { newConnection, validateConnectionProfile, validateDiscoveryEvidence, type DiscoveryResult } from "../lib/onboarding.ts";

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
