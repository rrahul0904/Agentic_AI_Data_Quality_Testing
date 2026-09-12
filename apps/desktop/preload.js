const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('adeDesktop', {
  runtime: () => ipcRenderer.invoke('ade:runtime'),
  restartApi: () => ipcRenderer.invoke('ade:restart-api'),
  openWebConsole: () => ipcRenderer.invoke('ade:open-web-console'),
  openExternal: (url) => ipcRenderer.invoke('ade:open-external', url),
});
