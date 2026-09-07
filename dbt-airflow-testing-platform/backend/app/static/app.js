// ---------------------------------------------------------------------------
// tiny API client
// ---------------------------------------------------------------------------
const api = {
  async get(path) {
    const res = await fetch(path);
    if (!res.ok) throw new Error(`${path} -> ${res.status}`);
    return res.json();
  },
  async post(path, body) {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`${path} -> ${res.status}: ${text}`);
    }
    return res.json();
  },
};

// ---------------------------------------------------------------------------
// small helpers
// ---------------------------------------------------------------------------
function badge(status) {
  const cls = (status || "pending").toLowerCase().replace(/\s+/g, "_");
  return `<span class="badge badge-${cls}">${status}</span>`;
}
function shortId(id) {
  return id ? id.slice(0, 8) : "";
}
function esc(s) {
  return (s ?? "").toString().replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

let modalOpen = false;
function openModal(innerHtml) {
  modalOpen = true;
  document.getElementById("modal-root").innerHTML = `
    <div class="modal-overlay" id="modal-overlay">
      <div class="modal-card">${innerHtml}</div>
    </div>`;
  document.getElementById("modal-overlay").addEventListener("click", (e) => {
    if (e.target.id === "modal-overlay") closeModal();
  });
}
function closeModal() {
  modalOpen = false;
  document.getElementById("modal-root").innerHTML = "";
}

// ---------------------------------------------------------------------------
// lineage graph: simple layered SVG (topological levels -> columns)
// ---------------------------------------------------------------------------
function renderLineageGraph(lineage) {
  const nodes = lineage.nodes || [];
  const edges = lineage.edges || [];
  if (!nodes.length) {
    return '<p class="text-slate-500 text-xs">No lineage captured yet.</p>';
  }

  const incoming = {};
  const outgoing = {};
  nodes.forEach((n) => {
    incoming[n.id] = [];
    outgoing[n.id] = [];
  });
  edges.forEach((e) => {
    if (outgoing[e.from]) outgoing[e.from].push(e.to);
    if (incoming[e.to]) incoming[e.to].push(e.from);
  });

  // Longest-path layering: level(n) = 1 + max(level(parent)) for a DAG.
  const level = {};
  function computeLevel(id, seen) {
    if (level[id] !== undefined) return level[id];
    if (seen.has(id)) return 0; // cycle guard
    seen.add(id);
    const parents = incoming[id] || [];
    const lvl = parents.length ? Math.max(...parents.map((p) => computeLevel(p, seen))) + 1 : 0;
    level[id] = lvl;
    return lvl;
  }
  nodes.forEach((n) => computeLevel(n.id, new Set()));

  const byLevel = {};
  nodes.forEach((n) => {
    (byLevel[level[n.id]] ||= []).push(n);
  });
  const maxLevel = Math.max(...Object.keys(byLevel).map(Number));

  const colWidth = 190;
  const rowHeight = 46;
  const nodeW = 160;
  const nodeH = 28;
  const pos = {};
  let maxRows = 1;
  for (let l = 0; l <= maxLevel; l++) {
    const col = byLevel[l] || [];
    maxRows = Math.max(maxRows, col.length);
    col.forEach((n, i) => {
      pos[n.id] = { x: l * colWidth + 20, y: i * rowHeight + 20 };
    });
  }

  const width = (maxLevel + 1) * colWidth + nodeW;
  const height = maxRows * rowHeight + 20;

  const edgeLines = edges
    .map((e) => {
      const a = pos[e.from];
      const b = pos[e.to];
      if (!a || !b) return "";
      const x1 = a.x + nodeW;
      const y1 = a.y + nodeH / 2;
      const x2 = b.x;
      const y2 = b.y + nodeH / 2;
      const midX = (x1 + x2) / 2;
      return `<path class="lineage-edge" d="M${x1},${y1} C${midX},${y1} ${midX},${y2} ${x2},${y2}" />`;
    })
    .join("");

  const nodeRects = nodes
    .map((n) => {
      const p = pos[n.id];
      const kind = (n.kind || "unknown").toLowerCase();
      return `
        <g transform="translate(${p.x},${p.y})">
          <rect class="lineage-node-rect kind-${kind}" width="${nodeW}" height="${nodeH}" rx="6" />
          <text class="lineage-node-text" x="8" y="${nodeH / 2 + 4}">${esc(n.label).slice(0, 22)}</text>
        </g>`;
    })
    .join("");

  return `
    <svg class="lineage-svg" viewBox="0 0 ${width} ${height}" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <marker id="arrowhead" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
          <path d="M0,0 L0,6 L7,3 z" fill="#475569" />
        </marker>
      </defs>
      ${edgeLines}
      ${nodeRects}
    </svg>`;
}

// ---------------------------------------------------------------------------
// router
// ---------------------------------------------------------------------------
const app = document.getElementById("app");

function currentRoute() {
  const hash = location.hash.replace(/^#\/?/, "");
  const parts = hash.split("/").filter(Boolean);
  return parts;
}

async function render() {
  const parts = currentRoute();
  const onProjectDetail = (parts[0] === "dbt" || parts[0] === "airflow") && parts[1];
  if (!onProjectDetail) lastProjectStatus = null;
  try {
    if (parts.length === 0) return renderDashboard();
    if (parts[0] === "dbt" && parts[1]) return renderDbtProjectDetail(parts[1]);
    if (parts[0] === "airflow" && parts[1]) return renderAirflowProjectDetail(parts[1]);
    if (parts[0] === "runs" && parts[1]) return renderRunDetail(parts[1]);
    if (parts[0] === "runs") return renderRunsList();
    if (parts[0] === "incidents") return renderIncidentsList();
    return renderDashboard();
  } catch (err) {
    app.innerHTML = `<div class="text-rose-400 text-sm">Failed to load: ${esc(err.message)}</div>`;
  }
}

window.addEventListener("hashchange", render);

// ---------------------------------------------------------------------------
// Dashboard: dbt projects + airflow projects
// ---------------------------------------------------------------------------
async function renderDashboard() {
  const [dbtProjects, airflowProjects] = await Promise.all([
    api.get("/api/dbt-projects"),
    api.get("/api/airflow-projects"),
  ]);

  app.innerHTML = `
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
      <section>
        <div class="flex items-center justify-between mb-3">
          <h2 class="font-medium">dbt Projects</h2>
          <button id="new-dbt-btn" class="btn btn-primary">+ New dbt Project</button>
        </div>
        <div id="dbt-project-list" class="space-y-2"></div>
      </section>
      <section>
        <div class="flex items-center justify-between mb-3">
          <h2 class="font-medium">Airflow Projects</h2>
          <button id="new-airflow-btn" class="btn btn-primary">+ New Airflow Project</button>
        </div>
        <div id="airflow-project-list" class="space-y-2"></div>
      </section>
    </div>
  `;

  const dbtListEl = document.getElementById("dbt-project-list");
  dbtListEl.innerHTML = dbtProjects.length
    ? dbtProjects
        .map(
          (p) => `
        <a href="#/dbt/${p.id}" class="project-card block">
          <div class="flex items-center justify-between">
            <span class="font-medium">${esc(p.name)}</span>
            ${badge(p.status)}
          </div>
          <div class="text-xs text-slate-400 mt-1">
            ${p.execution_mode === "local" ? `local &middot; ${esc(p.adapter)}` : `dbt Cloud &middot; account ${esc(p.dbt_cloud_account_id)}`}
          </div>
          ${p.error_message ? `<div class="text-xs text-rose-400 mt-1">${esc(p.error_message)}</div>` : ""}
        </a>`
        )
        .join("")
    : '<p class="text-slate-500 text-xs">No dbt projects yet.</p>';

  const airflowListEl = document.getElementById("airflow-project-list");
  airflowListEl.innerHTML = airflowProjects.length
    ? airflowProjects
        .map(
          (p) => `
        <a href="#/airflow/${p.id}" class="project-card block">
          <div class="flex items-center justify-between">
            <span class="font-medium">${esc(p.name)}</span>
            ${badge(p.status)}
          </div>
          <div class="text-xs text-slate-400 mt-1">
            ${p.base_url ? esc(p.base_url) : "provisioning…"} ${p.is_running ? "&middot; running" : p.status === "READY" ? "&middot; stopped" : ""}
          </div>
          ${p.error_message ? `<div class="text-xs text-rose-400 mt-1">${esc(p.error_message)}</div>` : ""}
        </a>`
        )
        .join("")
    : '<p class="text-slate-500 text-xs">No Airflow projects yet.</p>';

  document.getElementById("new-dbt-btn").addEventListener("click", openCreateDbtProjectModal);
  document.getElementById("new-airflow-btn").addEventListener("click", openCreateAirflowProjectModal);
}

function openCreateDbtProjectModal() {
  openModal(`
    <h3 class="font-medium mb-4">New dbt Project</h3>
    <label class="field-label">Project name</label>
    <input id="f-name" class="field-input mb-3" placeholder="e.g. XYZ Company" />

    <label class="field-label">Execution mode</label>
    <select id="f-mode" class="field-input mb-3">
      <option value="local">Local dbt-core (isolated venv, provisioned now)</option>
      <option value="cloud">dbt Cloud (run existing dbt Cloud jobs)</option>
    </select>

    <div id="local-fields">
      <label class="field-label">Adapter</label>
      <select id="f-adapter" class="field-input mb-3">
        <option value="duckdb">DuckDB (zero-config, local file warehouse)</option>
        <option value="snowflake">Snowflake (reads SNOWFLAKE_* env vars)</option>
      </select>
    </div>

    <div id="cloud-fields" class="hidden">
      <label class="field-label">dbt Cloud host</label>
      <input id="f-cloud-host" class="field-input mb-3" value="cloud.getdbt.com" />
      <label class="field-label">Account ID</label>
      <input id="f-cloud-account" class="field-input mb-3" />
      <label class="field-label">Project ID (optional, scopes job sync)</label>
      <input id="f-cloud-project" class="field-input mb-3" />
      <label class="field-label">API token</label>
      <input id="f-cloud-token" type="password" class="field-input mb-3" />
    </div>

    <p id="f-error" class="text-xs text-rose-400 mb-3 hidden"></p>

    <div class="flex justify-end gap-2 mt-2">
      <button class="btn btn-secondary" id="f-cancel">Cancel</button>
      <button class="btn btn-primary" id="f-submit">Create</button>
    </div>
  `);

  const modeSel = document.getElementById("f-mode");
  modeSel.addEventListener("change", () => {
    const isLocal = modeSel.value === "local";
    document.getElementById("local-fields").classList.toggle("hidden", !isLocal);
    document.getElementById("cloud-fields").classList.toggle("hidden", isLocal);
  });
  document.getElementById("f-cancel").addEventListener("click", closeModal);
  document.getElementById("f-submit").addEventListener("click", async () => {
    const name = document.getElementById("f-name").value.trim();
    const mode = modeSel.value;
    const errEl = document.getElementById("f-error");
    if (!name) {
      errEl.textContent = "Name is required.";
      errEl.classList.remove("hidden");
      return;
    }
    const payload = { name, execution_mode: mode };
    if (mode === "local") {
      payload.adapter = document.getElementById("f-adapter").value;
    } else {
      payload.dbt_cloud_host = document.getElementById("f-cloud-host").value.trim() || "cloud.getdbt.com";
      payload.dbt_cloud_account_id = document.getElementById("f-cloud-account").value.trim();
      payload.dbt_cloud_project_id = document.getElementById("f-cloud-project").value.trim() || null;
      payload.dbt_cloud_api_token = document.getElementById("f-cloud-token").value.trim();
    }
    try {
      const project = await api.post("/api/dbt-projects", payload);
      closeModal();
      location.hash = `#/dbt/${project.id}`;
    } catch (err) {
      errEl.textContent = err.message;
      errEl.classList.remove("hidden");
    }
  });
}

function openCreateAirflowProjectModal() {
  openModal(`
    <h3 class="font-medium mb-4">New Airflow Project</h3>
    <p class="text-xs text-slate-400 mb-4">
      Provisions a brand new, dedicated Airflow instance (its own venv, metadata DB,
      and webserver/scheduler/triggerer on a freshly allocated port). Takes ~30s.
    </p>
    <label class="field-label">Project name</label>
    <input id="f-name" class="field-input mb-3" placeholder="e.g. XYZ Company Airflow" />
    <p id="f-error" class="text-xs text-rose-400 mb-3 hidden"></p>
    <div class="flex justify-end gap-2 mt-2">
      <button class="btn btn-secondary" id="f-cancel">Cancel</button>
      <button class="btn btn-primary" id="f-submit">Create</button>
    </div>
  `);
  document.getElementById("f-cancel").addEventListener("click", closeModal);
  document.getElementById("f-submit").addEventListener("click", async () => {
    const name = document.getElementById("f-name").value.trim();
    const errEl = document.getElementById("f-error");
    if (!name) {
      errEl.textContent = "Name is required.";
      errEl.classList.remove("hidden");
      return;
    }
    try {
      const project = await api.post("/api/airflow-projects", { name });
      closeModal();
      location.hash = `#/airflow/${project.id}`;
    } catch (err) {
      errEl.textContent = err.message;
      errEl.classList.remove("hidden");
    }
  });
}

// ---------------------------------------------------------------------------
// dbt project detail
// ---------------------------------------------------------------------------
async function renderDbtProjectDetail(id) {
  const project = await api.get(`/api/dbt-projects/${id}`);
  lastProjectStatus = project.status;
  const lineage = project.status === "READY" ? await api.get(`/api/dbt-projects/${id}/lineage`).catch(() => ({ nodes: [], edges: [] })) : { nodes: [], edges: [] };

  const isCloud = project.execution_mode === "cloud";

  app.innerHTML = `
    <a href="#/" class="text-xs text-slate-400 hover:text-slate-200">&larr; Projects</a>
    <div class="flex items-center justify-between mt-2 mb-1">
      <h1 class="text-xl font-semibold">${esc(project.name)}</h1>
      ${badge(project.status)}
    </div>
    <div class="text-xs text-slate-400 mb-6">
      ${isCloud ? `dbt Cloud &middot; account ${esc(project.dbt_cloud_account_id)}` : `local &middot; ${esc(project.adapter)} &middot; ${esc(project.project_dir || "")}`}
    </div>
    ${project.error_message ? `<div class="bg-rose-950 border border-rose-800 text-rose-300 text-xs rounded-lg p-3 mb-6 whitespace-pre-wrap">${esc(project.error_message)}</div>` : ""}

    <div class="grid grid-cols-1 lg:grid-cols-5 gap-8">
      <section class="lg:col-span-2">
        <div class="flex items-center justify-between mb-3">
          <h2 class="font-medium">Jobs</h2>
          <div class="flex gap-2">
            ${isCloud ? '<button id="sync-jobs-btn" class="btn btn-secondary text-xs">Sync from dbt Cloud</button>' : '<button id="add-job-btn" class="btn btn-secondary text-xs">+ Add job</button>'}
          </div>
        </div>
        <div id="jobs-list" class="space-y-2 mb-4"></div>
        <button id="run-selected-btn" class="btn btn-primary w-full" ${project.status !== "READY" ? "disabled" : ""}>
          Run Selected
        </button>
        ${!isCloud ? '<button id="run-whole-btn" class="btn btn-secondary w-full mt-2">Run Whole Project</button>' : ""}
        <div id="run-error" class="text-xs text-rose-400 mt-2 hidden"></div>
      </section>

      <section class="lg:col-span-3">
        <div class="flex items-center justify-between mb-3">
          <h2 class="font-medium">Lineage</h2>
          ${!isCloud ? '<button id="refresh-lineage-btn" class="btn btn-secondary text-xs">Refresh</button>' : ""}
        </div>
        <div class="border border-slate-800 rounded-md p-3 overflow-x-auto">
          ${renderLineageGraph(lineage)}
        </div>
      </section>
    </div>

    <div class="mt-10 flex items-center justify-between mb-3">
      <h2 class="font-medium">Quality Rules</h2>
      <div class="flex gap-2">
        <button id="recheck-quality-btn" class="btn btn-secondary text-xs" ${project.status !== "READY" ? "disabled" : ""}>Recheck All</button>
        <button id="add-rule-btn" class="btn btn-primary text-xs" ${project.status !== "READY" ? "disabled" : ""}>+ Add Rule</button>
      </div>
    </div>
    <div id="quality-rules-table" class="results-wrap mb-10">
      <p class="text-slate-500 text-xs">Loading…</p>
    </div>

    <div class="mt-10 flex items-center justify-between mb-3">
      <h2 class="font-medium">Certifications</h2>
    </div>
    <div id="certifications-table" class="results-wrap mb-10">
      <p class="text-slate-500 text-xs">Loading…</p>
    </div>
  `;

  function renderJobs() {
    const jobsListEl = document.getElementById("jobs-list");
    jobsListEl.innerHTML = project.jobs.length
      ? project.jobs
          .map(
            (j) => `
        <label class="job-row">
          <input type="checkbox" class="job-checkbox" value="${j.id}" />
          <div class="flex-1">
            <div class="text-sm">${esc(j.name)}</div>
            <div class="text-xs text-slate-500">${j.kind === "local_select" ? `select: <code>${esc(j.select_str)}</code>` : `dbt Cloud job ${esc(j.dbt_cloud_job_id)}`}</div>
          </div>
        </label>`
          )
          .join("")
      : '<p class="text-slate-500 text-xs">No jobs yet.</p>';
  }
  renderJobs();

  document.getElementById("run-selected-btn").addEventListener("click", async () => {
    const ids = [...document.querySelectorAll(".job-checkbox:checked")].map((el) => el.value);
    const errEl = document.getElementById("run-error");
    if (!ids.length) {
      errEl.textContent = "Select at least one job (or use 'Run Whole Project').";
      errEl.classList.remove("hidden");
      return;
    }
    const run = await api.post("/api/runs", { dbt_project_id: id, dbt_job_ids: ids, triggered_by: "ui" });
    location.hash = `#/runs/${run.id}`;
  });

  const runWholeBtn = document.getElementById("run-whole-btn");
  if (runWholeBtn) {
    runWholeBtn.addEventListener("click", async () => {
      const run = await api.post("/api/runs", { dbt_project_id: id, triggered_by: "ui" });
      location.hash = `#/runs/${run.id}`;
    });
  }

  const addJobBtn = document.getElementById("add-job-btn");
  if (addJobBtn) {
    addJobBtn.addEventListener("click", () => {
      openModal(`
        <h3 class="font-medium mb-4">Add a dbt job (saved --select)</h3>
        <label class="field-label">Name</label>
        <input id="f-name" class="field-input mb-3" placeholder="e.g. staging models" />
        <label class="field-label">dbt --select string</label>
        <input id="f-select" class="field-input mb-3" placeholder="e.g. staging.* or fct_orders+" />
        <p id="f-error" class="text-xs text-rose-400 mb-3 hidden"></p>
        <div class="flex justify-end gap-2 mt-2">
          <button class="btn btn-secondary" id="f-cancel">Cancel</button>
          <button class="btn btn-primary" id="f-submit">Add</button>
        </div>
      `);
      document.getElementById("f-cancel").addEventListener("click", closeModal);
      document.getElementById("f-submit").addEventListener("click", async () => {
        const name = document.getElementById("f-name").value.trim();
        const select_str = document.getElementById("f-select").value.trim();
        const errEl = document.getElementById("f-error");
        if (!name || !select_str) {
          errEl.textContent = "Both fields are required.";
          errEl.classList.remove("hidden");
          return;
        }
        try {
          await api.post(`/api/dbt-projects/${id}/jobs`, { name, select_str });
          closeModal();
          render();
        } catch (err) {
          errEl.textContent = err.message;
          errEl.classList.remove("hidden");
        }
      });
    });
  }

  const syncJobsBtn = document.getElementById("sync-jobs-btn");
  if (syncJobsBtn) {
    syncJobsBtn.addEventListener("click", async () => {
      syncJobsBtn.disabled = true;
      syncJobsBtn.textContent = "Syncing…";
      try {
        await api.post(`/api/dbt-projects/${id}/sync-cloud-jobs`, {});
      } catch (err) {
        alert(err.message);
      }
      render();
    });
  }

  const refreshLineageBtn = document.getElementById("refresh-lineage-btn");
  if (refreshLineageBtn) {
    refreshLineageBtn.addEventListener("click", async () => {
      refreshLineageBtn.disabled = true;
      refreshLineageBtn.textContent = "Refreshing…";
      try {
        await api.post(`/api/dbt-projects/${id}/lineage/refresh`, {});
      } catch (err) {
        alert(err.message);
      }
      render();
    });
  }

  if (project.status === "READY") {
    await renderQualitySections(id);
  } else {
    document.getElementById("quality-rules-table").innerHTML = '<p class="text-slate-500 text-xs">Project must be READY.</p>';
    document.getElementById("certifications-table").innerHTML = "";
  }

  document.getElementById("add-rule-btn")?.addEventListener("click", () => openAddRuleModal(id));
  document.getElementById("recheck-quality-btn")?.addEventListener("click", async (e) => {
    e.target.disabled = true;
    e.target.textContent = "Rechecking…";
    try {
      await api.post(`/api/dbt-projects/${id}/quality/recheck`, {});
    } catch (err) {
      alert(err.message);
    }
    render();
  });
}

// ---------------------------------------------------------------------------
// Quality Rules + Certifications (within a dbt project detail page)
// ---------------------------------------------------------------------------

const RULE_DIMENSIONS = [
  "schema", "completeness", "uniqueness", "validity", "accuracy", "consistency",
  "referential_integrity", "freshness", "volume", "distribution", "anomaly",
  "transformation", "pipeline", "business_rule",
];
const RULE_TYPES = [
  "not_null", "unique", "accepted_values", "row_count_reconciliation",
  "aggregate_reconciliation", "custom_sql",
];

async function renderQualitySections(projectId) {
  const [rules, certs] = await Promise.all([
    api.get(`/api/quality-rules?dbt_project_id=${projectId}`),
    api.get(`/api/certifications?dbt_project_id=${projectId}`),
  ]);

  // one row per rule, with its most recent run fetched alongside
  const runsByRule = await Promise.all(
    rules.map((r) => api.get(`/api/quality-rules/${r.id}/runs`).then((runs) => runs[0] || null).catch(() => null))
  );

  const rulesTableEl = document.getElementById("quality-rules-table");
  rulesTableEl.innerHTML = rules.length
    ? `<table class="results">
        <thead><tr><th>Name</th><th>Dimension</th><th>Type</th><th>Target</th><th>Severity</th><th>Last result</th><th></th></tr></thead>
        <tbody>
          ${rules
            .map((r, i) => {
              const run = runsByRule[i];
              return `<tr>
                <td>${esc(r.name)}</td>
                <td>${esc(r.dimension)}</td>
                <td><code>${esc(r.rule_type)}</code></td>
                <td>${esc(r.target_table)}${r.target_column ? `.${esc(r.target_column)}` : ""}</td>
                <td>${badge(r.severity)}</td>
                <td>${run ? `${badge(run.status)} <span class="text-slate-500">(${run.measured_value})</span>` : '<span class="text-slate-500">not yet run</span>'}</td>
                <td><button class="btn btn-secondary text-xs execute-rule-btn" data-rule-id="${r.id}">Execute</button></td>
              </tr>`;
            })
            .join("")}
        </tbody>
      </table>`
    : '<p class="text-slate-500 text-xs">No quality rules yet. Click "+ Add Rule".</p>';

  rulesTableEl.querySelectorAll(".execute-rule-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      btn.textContent = "Running…";
      try {
        await api.post(`/api/quality-rules/${btn.dataset.ruleId}/execute`, {});
      } catch (err) {
        alert(err.message);
      }
      render();
    });
  });

  const datasetRefs = [...new Set(rules.map((r) => r.target_table))];
  const latestCertByDataset = {};
  for (const c of certs) {
    if (!(c.dataset_ref in latestCertByDataset)) latestCertByDataset[c.dataset_ref] = c;
  }

  const certsTableEl = document.getElementById("certifications-table");
  certsTableEl.innerHTML = datasetRefs.length
    ? `<table class="results">
        <thead><tr><th>Dataset</th><th>Status</th><th>Reason</th><th></th></tr></thead>
        <tbody>
          ${datasetRefs
            .map((ds) => {
              const cert = latestCertByDataset[ds];
              const needsInvestigation = cert && (cert.status === "FAILED" || cert.status === "AT_RISK");
              return `<tr>
                <td>${esc(ds)}</td>
                <td>${cert ? badge(cert.status) : '<span class="text-slate-500">not yet evaluated</span>'}</td>
                <td class="text-slate-400">${esc(cert ? cert.reason : "")}</td>
                <td class="whitespace-nowrap">
                  <button class="btn btn-secondary text-xs evaluate-cert-btn" data-dataset="${esc(ds)}">Evaluate</button>
                  ${needsInvestigation ? `<button class="btn btn-primary text-xs investigate-btn" data-dataset="${esc(ds)}">Investigate</button>` : ""}
                </td>
              </tr>`;
            })
            .join("")}
        </tbody>
      </table>`
    : '<p class="text-slate-500 text-xs">No datasets to certify yet -- add a quality rule first.</p>';

  certsTableEl.querySelectorAll(".evaluate-cert-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        const url = `/api/certifications/evaluate?dataset_ref=${encodeURIComponent(btn.dataset.dataset)}&dbt_project_id=${projectId}`;
        const resp = await fetch(url, { method: "POST" });
        if (!resp.ok) throw new Error(await resp.text());
      } catch (err) {
        alert(err.message);
      }
      render();
    });
  });

  certsTableEl.querySelectorAll(".investigate-btn").forEach((btn) => {
    btn.addEventListener("click", () => openInvestigateModal(projectId, btn.dataset.dataset));
  });
}

function openAddRuleModal(projectId) {
  openModal(`
    <h3 class="font-medium mb-4">Add a quality rule</h3>
    <label class="field-label">Name</label>
    <input id="f-name" class="field-input mb-3" placeholder="e.g. net revenue reconciliation" />

    <div class="grid grid-cols-2 gap-3 mb-3">
      <div>
        <label class="field-label">Dimension</label>
        <select id="f-dimension" class="field-input">
          ${RULE_DIMENSIONS.map((d) => `<option value="${d}">${d}</option>`).join("")}
        </select>
      </div>
      <div>
        <label class="field-label">Rule type</label>
        <select id="f-rule-type" class="field-input">
          ${RULE_TYPES.map((t) => `<option value="${t}">${t}</option>`).join("")}
        </select>
      </div>
    </div>

    <div class="grid grid-cols-2 gap-3 mb-3">
      <div>
        <label class="field-label">Target table</label>
        <input id="f-target-table" class="field-input" placeholder="e.g. fact_revenue" />
      </div>
      <div>
        <label class="field-label">Target column (not_null / unique)</label>
        <input id="f-target-column" class="field-input" placeholder="e.g. order_id" />
      </div>
    </div>

    <label class="field-label">Expression (JSON -- rule-type specific, see docs/ARCHITECTURE.md)</label>
    <textarea id="f-expression" class="field-input mb-3" rows="3" style="font-family: ui-monospace, monospace; font-size: 0.75rem;" placeholder='e.g. {"sql": "SELECT count(*) AS failing_count FROM ..."}'></textarea>

    <div class="grid grid-cols-3 gap-3 mb-3">
      <div>
        <label class="field-label">Tolerance type</label>
        <select id="f-tolerance-type" class="field-input">
          <option value="">none</option>
          <option value="absolute">absolute</option>
          <option value="percentage">percentage</option>
        </select>
      </div>
      <div>
        <label class="field-label">Tolerance value</label>
        <input id="f-tolerance-value" type="number" step="any" class="field-input" placeholder="0" />
      </div>
      <div>
        <label class="field-label">Severity</label>
        <select id="f-severity" class="field-input">
          <option value="P1">P1</option>
          <option value="P2" selected>P2</option>
          <option value="P3">P3</option>
        </select>
      </div>
    </div>

    <p id="f-error" class="text-xs text-rose-400 mb-3 hidden"></p>
    <div class="flex justify-end gap-2 mt-2">
      <button class="btn btn-secondary" id="f-cancel">Cancel</button>
      <button class="btn btn-primary" id="f-submit">Add</button>
    </div>
  `);

  document.getElementById("f-cancel").addEventListener("click", closeModal);
  document.getElementById("f-submit").addEventListener("click", async () => {
    const errEl = document.getElementById("f-error");
    const name = document.getElementById("f-name").value.trim();
    const target_table = document.getElementById("f-target-table").value.trim();
    if (!name || !target_table) {
      errEl.textContent = "Name and target table are required.";
      errEl.classList.remove("hidden");
      return;
    }
    let expression = {};
    const rawExpr = document.getElementById("f-expression").value.trim();
    if (rawExpr) {
      try {
        expression = JSON.parse(rawExpr);
      } catch {
        errEl.textContent = "Expression must be valid JSON.";
        errEl.classList.remove("hidden");
        return;
      }
    }
    const toleranceValueRaw = document.getElementById("f-tolerance-value").value;
    const payload = {
      dbt_project_id: projectId,
      name,
      dimension: document.getElementById("f-dimension").value,
      rule_type: document.getElementById("f-rule-type").value,
      target_table,
      target_column: document.getElementById("f-target-column").value.trim() || null,
      expression,
      tolerance_type: document.getElementById("f-tolerance-type").value || null,
      tolerance_value: toleranceValueRaw ? Number(toleranceValueRaw) : null,
      severity: document.getElementById("f-severity").value,
    };
    try {
      await api.post("/api/quality-rules", payload);
      closeModal();
      render();
    } catch (err) {
      errEl.textContent = err.message;
      errEl.classList.remove("hidden");
    }
  });
}

// ---------------------------------------------------------------------------
// Investigation: RCA + remediation (propose -> approve -> apply)
// ---------------------------------------------------------------------------

function renderEvidenceTable(evidenceLinks) {
  if (!evidenceLinks.length) return '<p class="text-slate-500 text-xs">No linked evidence.</p>';
  return `<table class="results mb-4">
    <thead><tr><th>Relationship</th><th>Type</th><th>Dataset</th><th>Value</th><th>Query</th></tr></thead>
    <tbody>
      ${evidenceLinks
        .map(
          (l) => `<tr>
            <td>${esc(l.relationship_type)}</td>
            <td>${esc(l.evidence.evidence_type)}</td>
            <td>${esc(l.evidence.dataset_ref)}</td>
            <td>${esc(l.evidence.value)}</td>
            <td class="text-slate-400"><code>${esc((l.evidence.query_text || "").slice(0, 80))}</code></td>
          </tr>`
        )
        .join("")}
    </tbody>
  </table>`;
}

async function openInvestigateModal(projectId, datasetRef) {
  openModal(`
    <h3 class="font-medium mb-4">Investigate: ${esc(datasetRef)}</h3>
    <div id="investigate-body"><p class="text-slate-500 text-xs">Running RCA…</p></div>
  `);

  let claim;
  try {
    const resp = await fetch(
      `/api/rca?dbt_project_id=${projectId}&dataset_ref=${encodeURIComponent(datasetRef)}`,
      { method: "POST" }
    );
    if (!resp.ok) throw new Error(await resp.text());
    claim = await resp.json();
  } catch (err) {
    document.getElementById("investigate-body").innerHTML = `<p class="text-rose-400 text-xs">${esc(err.message)}</p>`;
    return;
  }

  const body = document.getElementById("investigate-body");
  body.innerHTML = `
    <div class="mb-3">${badge(claim.status)} <span class="text-xs text-slate-500 ml-2">generated_by: ${esc(claim.generated_by)}</span></div>
    <p class="text-sm mb-4">${esc(claim.statement)}</p>
    <h4 class="text-xs font-medium text-slate-400 mb-2">Linked evidence</h4>
    ${renderEvidenceTable(claim.evidence_links)}
    <div id="remediation-area"></div>
  `;

  if (!claim.evidence_links.length) return; // nothing concrete enough to propose a fix against

  const remediationArea = document.getElementById("remediation-area");
  remediationArea.innerHTML = `
    <h4 class="text-xs font-medium text-slate-400 mb-2 mt-4">Propose a remediation</h4>
    <label class="field-label">Target file (relative to the project directory)</label>
    <input id="rem-target-file" class="field-input mb-2" placeholder="e.g. models/intermediate/int_revenue.sql" />
    <label class="field-label">Find (must be unique in the file)</label>
    <textarea id="rem-find" class="field-input mb-2" rows="2" style="font-family: ui-monospace, monospace; font-size: 0.75rem;"></textarea>
    <label class="field-label">Replace with</label>
    <textarea id="rem-replace" class="field-input mb-2" rows="2" style="font-family: ui-monospace, monospace; font-size: 0.75rem;"></textarea>
    <p id="rem-error" class="text-xs text-rose-400 mb-2 hidden"></p>
    <button id="rem-propose-btn" class="btn btn-primary text-xs">Propose</button>
    <div id="rem-proposal"></div>
  `;

  document.getElementById("rem-propose-btn").addEventListener("click", async () => {
    const errEl = document.getElementById("rem-error");
    const target_file = document.getElementById("rem-target-file").value.trim();
    const find_text = document.getElementById("rem-find").value;
    const replace_text = document.getElementById("rem-replace").value;
    if (!target_file || !find_text) {
      errEl.textContent = "Target file and find text are required.";
      errEl.classList.remove("hidden");
      return;
    }
    try {
      const proposal = await api.post("/api/remediation-proposals", {
        claim_id: claim.id, target_file, find_text, replace_text,
      });
      renderProposal(proposal);
    } catch (err) {
      errEl.textContent = err.message;
      errEl.classList.remove("hidden");
    }
  });

  function renderProposal(proposal) {
    const area = document.getElementById("rem-proposal");
    area.innerHTML = `
      <div class="job-row mt-3">
        <div class="flex-1">
          <div class="text-sm">${esc(proposal.target_file)} ${badge(proposal.status)}</div>
          <div class="text-xs text-slate-500">${esc(proposal.proposed_change)}</div>
        </div>
        ${proposal.status === "PROPOSED" ? `<button class="btn btn-secondary text-xs" id="rem-approve-btn">Approve</button>` : ""}
        ${proposal.status === "APPROVED" ? `<button class="btn btn-primary text-xs" id="rem-apply-btn">Apply</button>` : ""}
        ${proposal.status === "APPLIED" ? `<span class="text-xs text-emerald-400">Applied. Now click "Run Whole Project" then "Recheck All" to confirm the fix.</span>` : ""}
      </div>
    `;
    document.getElementById("rem-approve-btn")?.addEventListener("click", async () => {
      const updated = await api.post(`/api/remediation-proposals/${proposal.id}/approve`, {});
      renderProposal(updated);
    });
    document.getElementById("rem-apply-btn")?.addEventListener("click", async () => {
      try {
        const updated = await api.post(`/api/remediation-proposals/${proposal.id}/apply`, {});
        renderProposal(updated);
      } catch (err) {
        alert(err.message);
      }
    });
  }
}

// ---------------------------------------------------------------------------
// Airflow project detail
// ---------------------------------------------------------------------------
async function renderAirflowProjectDetail(id) {
  const project = await api.get(`/api/airflow-projects/${id}`);
  lastProjectStatus = project.status;

  app.innerHTML = `
    <a href="#/" class="text-xs text-slate-400 hover:text-slate-200">&larr; Projects</a>
    <div class="flex items-center justify-between mt-2 mb-1">
      <h1 class="text-xl font-semibold">${esc(project.name)}</h1>
      <div class="flex items-center gap-2">
        ${badge(project.status)}
        ${project.status === "READY" ? `<button id="stop-btn" class="btn btn-secondary text-xs">${project.is_running ? "Stop" : "Start"}</button>` : ""}
      </div>
    </div>
    <div class="text-xs text-slate-400 mb-6">
      ${project.base_url ? `${esc(project.base_url)} &middot; ${esc(project.admin_username)}/(generated password)` : "provisioning…"}
    </div>
    ${project.error_message ? `<div class="bg-rose-950 border border-rose-800 text-rose-300 text-xs rounded-lg p-3 mb-6 whitespace-pre-wrap">${esc(project.error_message)}</div>` : ""}

    <div class="grid grid-cols-1 lg:grid-cols-5 gap-8">
      <section class="lg:col-span-2">
        <div class="flex items-center justify-between mb-3">
          <h2 class="font-medium">DAGs</h2>
          <div class="flex gap-2">
            <button id="upload-dag-btn" class="btn btn-secondary text-xs">Upload DAG</button>
            <button id="sync-dags-btn" class="btn btn-secondary text-xs">Sync</button>
          </div>
        </div>
        <div id="dags-list" class="space-y-2 mb-4"></div>
        <button id="run-selected-btn" class="btn btn-primary w-full" ${project.status !== "READY" ? "disabled" : ""}>
          Run Selected DAGs
        </button>
        <div id="run-error" class="text-xs text-rose-400 mt-2 hidden"></div>
      </section>

      <section class="lg:col-span-3">
        <h2 class="font-medium mb-3">Lineage <span class="text-xs text-slate-500 font-normal">(click a DAG to preview)</span></h2>
        <div id="lineage-container" class="border border-slate-800 rounded-md p-3 overflow-x-auto">
          <p class="text-slate-500 text-xs">Select a DAG on the left.</p>
        </div>
      </section>
    </div>
  `;

  function renderDags() {
    const dagsListEl = document.getElementById("dags-list");
    dagsListEl.innerHTML = project.dags.length
      ? project.dags
          .map(
            (d) => `
        <div class="job-row">
          <input type="checkbox" class="dag-checkbox" value="${esc(d.dag_id)}" />
          <div class="flex-1 cursor-pointer" data-dag-id="${esc(d.dag_id)}">
            <div class="text-sm">${esc(d.dag_id)} ${d.is_paused ? '<span class="text-slate-500 text-xs">(paused)</span>' : ""}</div>
            <div class="text-xs text-slate-500">
              schedule: ${esc(d.schedule_interval || "manual only")}
              ${d.tags && d.tags.length ? ` &middot; ${d.tags.map(esc).join(", ")}` : ""}
            </div>
          </div>
        </div>`
          )
          .join("")
      : '<p class="text-slate-500 text-xs">No DAGs discovered yet. Upload one, then Sync.</p>';

    dagsListEl.querySelectorAll("[data-dag-id]").forEach((el) => {
      el.addEventListener("click", async () => {
        const dagId = el.dataset.dagId;
        const container = document.getElementById("lineage-container");
        container.innerHTML = '<p class="text-slate-500 text-xs">Loading…</p>';
        try {
          const lineage = await api.get(`/api/airflow-projects/${id}/dags/${encodeURIComponent(dagId)}/lineage`);
          container.innerHTML = renderLineageGraph(lineage);
        } catch (err) {
          container.innerHTML = `<p class="text-rose-400 text-xs">${esc(err.message)}</p>`;
        }
      });
    });
  }
  renderDags();

  document.getElementById("run-selected-btn").addEventListener("click", async () => {
    const ids = [...document.querySelectorAll(".dag-checkbox:checked")].map((el) => el.value);
    const errEl = document.getElementById("run-error");
    if (!ids.length) {
      errEl.textContent = "Select at least one DAG.";
      errEl.classList.remove("hidden");
      return;
    }
    const run = await api.post("/api/runs", { airflow_project_id: id, airflow_dag_ids: ids, triggered_by: "ui" });
    location.hash = `#/runs/${run.id}`;
  });

  document.getElementById("sync-dags-btn").addEventListener("click", async () => {
    await api.post(`/api/airflow-projects/${id}/dags/sync`, {}).catch((err) => alert(err.message));
    render();
  });

  document.getElementById("upload-dag-btn").addEventListener("click", () => {
    openModal(`
      <h3 class="font-medium mb-4">Upload a DAG file</h3>
      <label class="field-label">Filename</label>
      <input id="f-filename" class="field-input mb-3" placeholder="e.g. my_dag.py" />
      <label class="field-label">Python source</label>
      <textarea id="f-content" class="field-input mb-3" rows="10" style="font-family: ui-monospace, monospace; font-size: 0.75rem;"></textarea>
      <p class="text-xs text-slate-500 mb-3">New files are discovered within ~10s; click Sync shortly after.</p>
      <p id="f-error" class="text-xs text-rose-400 mb-3 hidden"></p>
      <div class="flex justify-end gap-2 mt-2">
        <button class="btn btn-secondary" id="f-cancel">Cancel</button>
        <button class="btn btn-primary" id="f-submit">Upload</button>
      </div>
    `);
    document.getElementById("f-cancel").addEventListener("click", closeModal);
    document.getElementById("f-submit").addEventListener("click", async () => {
      const filename = document.getElementById("f-filename").value.trim();
      const content = document.getElementById("f-content").value;
      const errEl = document.getElementById("f-error");
      if (!filename || !content.trim()) {
        errEl.textContent = "Both fields are required.";
        errEl.classList.remove("hidden");
        return;
      }
      try {
        await api.post(`/api/airflow-projects/${id}/dags`, { filename, content });
        closeModal();
      } catch (err) {
        errEl.textContent = err.message;
        errEl.classList.remove("hidden");
      }
    });
  });

  const stopBtn = document.getElementById("stop-btn");
  if (stopBtn) {
    stopBtn.addEventListener("click", async () => {
      stopBtn.disabled = true;
      await api.post(`/api/airflow-projects/${id}/${project.is_running ? "stop" : "start"}`, {}).catch((err) => alert(err.message));
      render();
    });
  }
}

// ---------------------------------------------------------------------------
// Runs list + detail
// ---------------------------------------------------------------------------
async function renderRunsList() {
  const runs = await api.get("/api/runs");
  app.innerHTML = `
    <h1 class="text-xl font-semibold mb-4">Runs</h1>
    <div id="runs-list" class="space-y-2"></div>
  `;
  document.getElementById("runs-list").innerHTML = runs.length
    ? runs
        .map(
          (r) => `
      <a href="#/runs/${r.id}" class="run-row block">
        <div class="flex items-center justify-between">
          <span class="font-mono text-xs text-slate-400">${shortId(r.id)}</span>
          ${badge(r.status)}
        </div>
        <div class="text-xs text-slate-500 mt-1">triggered by ${esc(r.triggered_by)} at ${new Date(r.created_at).toLocaleString()}</div>
      </a>`
        )
        .join("")
    : '<p class="text-slate-500 text-xs">No runs yet.</p>';
}

async function renderIncidentsList() {
  const incidents = await api.get("/api/incidents");
  app.innerHTML = `
    <h1 class="text-xl font-semibold mb-4">Incidents</h1>
    <div id="incidents-list" class="space-y-2"></div>
  `;
  document.getElementById("incidents-list").innerHTML = incidents.length
    ? incidents
        .map(
          (i) => `
      <div class="run-row">
        <div class="flex items-center justify-between">
          <span class="font-medium text-sm">${esc(i.title)}</span>
          <div class="flex gap-2">${badge(i.severity)}${badge(i.status)}</div>
        </div>
        <div class="text-xs text-slate-500 mt-1">
          dataset: ${esc(i.dataset_ref)} &middot; opened ${new Date(i.created_at).toLocaleString()}
        </div>
        ${i.description ? `<div class="text-xs text-slate-400 mt-1">${esc(i.description)}</div>` : ""}
      </div>`
        )
        .join("")
    : '<p class="text-slate-500 text-xs">No incidents -- nothing has failed a P1 quality rule yet.</p>';
}

async function renderRunDetail(id) {
  const run = await api.get(`/api/runs/${id}`);

  const dbtSections = run.dbt_job_runs
    .map((jr) => {
      const rows = jr.results
        .map(
          (t) => `<tr>
            <td>${esc(t.node_kind)}</td>
            <td>${esc(t.name)}</td>
            <td>${badge(t.status)}</td>
            <td>${t.execution_time.toFixed(2)}s</td>
            <td class="text-slate-400">${esc(t.message || "")}</td>
          </tr>`
        )
        .join("");
      return `
        <div class="mb-5">
          <div class="text-sm font-medium mb-2">${esc(jr.label)} (${jr.mode}) ${badge(jr.status)}</div>
          <div class="results-wrap">
            <table class="results">
              <thead><tr><th>Kind</th><th>Name</th><th>Status</th><th>Time</th><th>Message</th></tr></thead>
              <tbody>${rows || '<tr><td colspan="5" class="text-slate-500">No per-test detail.</td></tr>'}</tbody>
            </table>
          </div>
        </div>`;
    })
    .join("");

  const airflowSections = run.airflow_dag_runs
    .map((dr) => {
      const taskRows = dr.tasks
        .map(
          (t) => `<tr>
            <td>${esc(t.task_id)}</td>
            <td>${badge(t.state)}</td>
            <td>${t.duration != null ? t.duration.toFixed(2) + "s" : "-"}</td>
          </tr>`
        )
        .join("");
      return `
        <div class="mb-5">
          <div class="text-sm font-medium mb-2">
            <code>${esc(dr.dag_id)}</code> ${badge(dr.state)}
          </div>
          <div class="results-wrap">
            <table class="results">
              <thead><tr><th>Task</th><th>State</th><th>Duration</th></tr></thead>
              <tbody>${taskRows || '<tr><td colspan="3" class="text-slate-500">No task instances yet.</td></tr>'}</tbody>
            </table>
          </div>
        </div>`;
    })
    .join("");

  app.innerHTML = `
    <a href="#/runs" class="text-xs text-slate-400 hover:text-slate-200">&larr; Runs</a>
    <div class="flex items-center justify-between mt-2 mb-1">
      <div class="font-mono text-xs text-slate-400">${run.id}</div>
      ${badge(run.status)}
    </div>
    <div class="text-sm text-slate-400 mb-6">triggered by ${esc(run.triggered_by)} at ${new Date(run.created_at).toLocaleString()}</div>
    ${run.error_message ? `<div class="bg-rose-950 border border-rose-800 text-rose-300 text-xs rounded-lg p-3 mb-6 whitespace-pre-wrap">${esc(run.error_message)}</div>` : ""}

    ${dbtSections ? `<h2 class="text-sm font-semibold mb-3">dbt job results</h2>${dbtSections}` : ""}
    ${airflowSections ? `<h2 class="text-sm font-semibold mb-3">Airflow DAG results</h2>${airflowSections}` : ""}
    ${!dbtSections && !airflowSections ? '<p class="text-slate-500 text-sm">Waiting for results…</p>' : ""}
  `;
}

// ---------------------------------------------------------------------------
// health pill + boot
// ---------------------------------------------------------------------------
async function fetchHealth() {
  const pill = document.getElementById("health-pill");
  try {
    await api.get("/api/health");
    pill.textContent = "● backend ok";
  } catch {
    pill.textContent = "○ backend unreachable";
    pill.classList.add("text-rose-500");
  }
}

// Project detail pages have live checkbox selections the user is actively
// making -- blindly re-rendering every 3s on a timer would wipe them mid-
// click. Track whether the *currently rendered* project is still
// provisioning; only that case justifies an unsolicited re-render (so the
// PROVISIONING -> READY transition still shows up live).
let lastProjectStatus = null;

fetchHealth();
render();
setInterval(() => {
  if (modalOpen) return;
  const parts = currentRoute();
  const onProjectDetail = (parts[0] === "dbt" || parts[0] === "airflow") && parts[1];
  if (onProjectDetail && lastProjectStatus !== "PROVISIONING") return;
  render();
}, 3000);
