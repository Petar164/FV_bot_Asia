/**
 * fashionvoid-bot · src/preload.js
 * Electron preload — exposes safe IPC bridges to the renderer via
 * contextBridge.  The renderer never touches Node or Electron APIs directly.
 */

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('bot', {
  start:      ()    => ipcRenderer.invoke('bot:start'),
  stop:       ()    => ipcRenderer.invoke('bot:stop'),
  onMessage:  (cb)  => ipcRenderer.on('bot:message', (_e, msg) => cb(msg)),
  onLog:      (cb)  => ipcRenderer.on('bot:log',     (_e, log) => cb(log)),
  onExit:     (cb)  => ipcRenderer.on('bot:exit',    (_e, info) => cb(info)),
});

contextBridge.exposeInMainWorld('keywords', {
  getSuggestions: (inputText)          => ipcRenderer.invoke('keywords:getSuggestions', inputText),
  addTerm:        (groupIndex, term)   => ipcRenderer.invoke('keywords:addTerm', { groupIndex, term }),
  reExpand:       (groupIndex)         => ipcRenderer.invoke('keywords:reExpand', { groupIndex }),
});

contextBridge.exposeInMainWorld('shell', {
  openExternal: (url) => ipcRenderer.invoke('shell:openExternal', url),
});
