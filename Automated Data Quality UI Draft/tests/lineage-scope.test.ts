import assert from "node:assert/strict";
import test from "node:test";
import { nodeBelongsToSourceTable } from "../lib/lineage-scope.ts";

const guests = {
  id: "postgres:public:guests",
  database: "hospitality_oltp",
  schema: "public",
  table: "guests",
  columns: [],
};

test("lineage table scope excludes similarly named, untagged assets", () => {
  for (const name of ["reservation_guests", "stg_reservation_guests", "ingest_reservation_guests", "raw.reservation_guests"]) {
    assert.equal(nodeBelongsToSourceTable({ node_id: name, name, kind: "dbt_model", properties: {} }, guests.id, [guests]), false, name);
  }
});

test("lineage table scope includes explicit canonical associations", () => {
  assert.equal(nodeBelongsToSourceTable({
    node_id: "model.stg_guests",
    name: "stg_guests",
    kind: "dbt_model",
    properties: { source_table_ids: [guests.id] },
  }, guests.id, [guests]), true);
  assert.equal(nodeBelongsToSourceTable({
    node_id: "model.dim_guest",
    name: "dim_guest",
    kind: "mart",
    properties: { source_table_id: guests.id },
  }, guests.id, [guests]), true);
});

test("legacy root matching is exact and rejects a mismatched database", () => {
  assert.equal(nodeBelongsToSourceTable({ node_id: "postgres.public.guests", name: "postgres.public.guests", kind: "source_table", properties: {} }, guests.id, [guests]), true);
  assert.equal(nodeBelongsToSourceTable({ node_id: "postgres.public.reservation_guests", name: "postgres.public.reservation_guests", kind: "source_table", properties: {} }, guests.id, [guests]), false);
  assert.equal(nodeBelongsToSourceTable({ node_id: "postgres.public.guests", name: "postgres.public.guests", kind: "source_table", properties: { catalog: "other_db" } }, guests.id, [guests]), false);
});
