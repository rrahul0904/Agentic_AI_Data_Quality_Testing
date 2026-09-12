const API = 'http://127.0.0.1:8001';

async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const body = await response.json().catch(() => ({ status: 'ERROR', detail: 'Non-JSON response' }));
  if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
  return body;
}

function pretty(value) {
  return JSON.stringify(value, null, 2);
}

function message(role, content) {
  const node = document.createElement('div');
  node.className = `message ${role}`;
  node.textContent = content;
  document.querySelector('#chat').appendChild(node);
  node.scrollIntoView({ behavior: 'smooth', block: 'end' });
}

async function refreshRuntime() {
  const state = await window.adeDesktop.runtime();
  document.querySelector('#runtime').textContent = pretty(state);
  const dot = document.querySelector('#api-dot');
  dot.classList.toggle('ok', state.apiReachable);
  document.querySelector('#api-state').textContent = state.apiReachable ? 'API connected' : 'API unavailable';
  if (state.apiReachable) {
    const [health, competitive, coco] = await Promise.all([
      api('/api/v1/platform/health').catch((error) => ({ status: 'ERROR', error: error.message })),
      api('/api/v1/competitive/status').catch((error) => ({ status: 'ERROR', error: error.message })),
      api('/api/v1/certification/coco').catch((error) => ({ status: 'ERROR', error: error.message })),
    ]);
    document.querySelector('#health').textContent = pretty(health);
    document.querySelector('#competitive').textContent = pretty(competitive);
    document.querySelector('#coco').textContent = pretty(coco);
  }
}

document.querySelectorAll('.nav').forEach((button) => {
  button.addEventListener('click', () => {
    document.querySelectorAll('.nav').forEach((item) => item.classList.remove('active'));
    document.querySelectorAll('.view').forEach((item) => item.classList.remove('active'));
    button.classList.add('active');
    const view = button.dataset.view;
    document.querySelector(`#view-${view}`).classList.add('active');
    document.querySelector('#title').textContent = button.textContent;
  });
});

document.querySelector('#agent-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const question = document.querySelector('#agent-question').value.trim();
  const mode = document.querySelector('#agent-mode').value;
  if (!question) return;
  message('user', question);
  document.querySelector('#agent-question').value = '';
  try {
    const result = await api('/api/v1/agent/query', {
      method: 'POST',
      body: JSON.stringify({ question, mode }),
    });
    const answer = result.answer || result.response || result.error || pretty(result);
    message('assistant', typeof answer === 'string' ? answer : pretty(answer));
  } catch (error) {
    message('error', error.message);
  }
});

document.querySelector('#sql-review').addEventListener('click', async () => {
  const output = document.querySelector('#sql-output');
  output.textContent = 'Reviewing…';
  try {
    const result = await api('/api/v1/sql/review', {
      method: 'POST',
      body: JSON.stringify({ sql: document.querySelector('#sql-input').value, dialect: 'snowflake' }),
    });
    output.textContent = pretty(result);
  } catch (error) {
    output.textContent = error.message;
  }
});

document.querySelector('#restart-api').addEventListener('click', async () => {
  await window.adeDesktop.restartApi();
  setTimeout(refreshRuntime, 1000);
});

document.querySelector('#open-console').addEventListener('click', async () => {
  const result = await window.adeDesktop.openWebConsole();
  if (result.status !== 'PASS') message('error', `Full console unavailable at ${result.url}`);
});

refreshRuntime().catch((error) => {
  document.querySelector('#runtime').textContent = error.message;
});
setInterval(() => refreshRuntime().catch(() => {}), 15000);
