const { app, BrowserWindow, ipcMain, shell } = require('electron');
const { spawn } = require('node:child_process');
const path = require('node:path');
const http = require('node:http');

const API_URL = process.env.ADE_API_URL || 'http://127.0.0.1:8001';
const WEB_URL = process.env.ADE_WEB_URL || 'http://127.0.0.1:3000';
const MANAGE_API = process.env.ADE_DESKTOP_MANAGE_API !== '0';
let apiProcess = null;
let mainWindow = null;

function pythonCommand() {
  if (process.env.ADE_PYTHON) return process.env.ADE_PYTHON;
  return process.platform === 'win32' ? 'python' : 'python3';
}

function startApi() {
  if (!MANAGE_API || apiProcess) return;
  apiProcess = spawn(
    pythonCommand(),
    ['-m', 'uvicorn', 'agentic_data_platform.api.app:app', '--host', '127.0.0.1', '--port', '8001'],
    {
      env: { ...process.env, PYTHONUNBUFFERED: '1' },
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    },
  );
  apiProcess.stdout?.on('data', (chunk) => console.log(`[ade-api] ${chunk}`));
  apiProcess.stderr?.on('data', (chunk) => console.error(`[ade-api] ${chunk}`));
  apiProcess.once('exit', () => {
    apiProcess = null;
  });
}

function stopApi() {
  if (!apiProcess) return;
  apiProcess.kill('SIGTERM');
  apiProcess = null;
}

function probe(url) {
  return new Promise((resolve) => {
    let parsed;
    try {
      parsed = new URL(url);
    } catch {
      resolve(false);
      return;
    }
    const request = http.request(
      {
        hostname: parsed.hostname,
        port: parsed.port || 80,
        path: parsed.pathname || '/',
        method: 'GET',
        timeout: 1200,
      },
      (response) => {
        response.resume();
        resolve(Boolean(response.statusCode && response.statusCode < 500));
      },
    );
    request.on('error', () => resolve(false));
    request.on('timeout', () => {
      request.destroy();
      resolve(false);
    });
    request.end();
  });
}

async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1500,
    height: 960,
    minWidth: 1000,
    minHeight: 700,
    title: 'Agentic Data Engineering',
    backgroundColor: '#090b10',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      webSecurity: true,
    },
  });
  mainWindow.removeMenu();
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('https://')) shell.openExternal(url);
    return { action: 'deny' };
  });
  await mainWindow.loadFile(path.join(__dirname, 'index.html'));
}

ipcMain.handle('ade:runtime', async () => ({
  apiUrl: API_URL,
  webUrl: WEB_URL,
  apiManaged: MANAGE_API,
  apiProcessRunning: Boolean(apiProcess),
  apiReachable: await probe(`${API_URL}/api/v1/platform/health`),
  webReachable: await probe(WEB_URL),
}));

ipcMain.handle('ade:restart-api', async () => {
  stopApi();
  startApi();
  return { status: 'PASS' };
});

ipcMain.handle('ade:open-web-console', async () => {
  const reachable = await probe(WEB_URL);
  if (reachable && mainWindow) {
    await mainWindow.loadURL(WEB_URL);
    return { status: 'PASS', url: WEB_URL };
  }
  return { status: 'UNAVAILABLE', url: WEB_URL };
});

ipcMain.handle('ade:open-external', async (_event, url) => {
  if (typeof url !== 'string' || !url.startsWith('https://')) {
    return { status: 'DENIED' };
  }
  await shell.openExternal(url);
  return { status: 'PASS' };
});

app.whenReady().then(async () => {
  startApi();
  await createWindow();
  app.on('activate', async () => {
    if (BrowserWindow.getAllWindows().length === 0) await createWindow();
  });
});

app.on('before-quit', stopApi);
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
