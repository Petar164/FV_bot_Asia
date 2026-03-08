/**
 * fashionvoid-bot · src/main.js
 * Electron main process — spawns the Python bot as a child process,
 * bridges IPC between renderer and bot via stdout/stdin JSON lines.
 */

const { app, BrowserWindow, ipcMain, shell } = require('electron');
const path   = require('path');
const { spawn } = require('child_process');

// ── Window ────────────────────────────────────────────────────────────────────

let win = null;
let botProcess = null;

function createWindow() {
  win = new BrowserWindow({
    width:           1280,
    height:          860,
    minWidth:        900,
    minHeight:       600,
    frame:           false,       // custom titlebar in renderer
    titleBarStyle:   'hidden',
    backgroundColor: '#070b10',
    webPreferences: {
      preload:          path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration:  false,
    },
  });

  if (process.env.NODE_ENV === 'development') {
    win.loadURL('http://localhost:5173');
    win.webContents.openDevTools({ mode: 'detach' });
  } else {
    win.loadFile(path.join(__dirname, '..', 'dist', 'index.html'));
  }

  win.on('closed', () => { win = null; });
}

// ── Python bot process ────────────────────────────────────────────────────────

function startBot() {
  const pythonPath = process.platform === 'win32'
    ? path.join(__dirname, '..', '.venv', 'Scripts', 'python.exe')
    : path.join(__dirname, '..', '.venv', 'bin', 'python');

  const botPath = path.join(__dirname, '..', 'main.py');

  botProcess = spawn(pythonPath, [botPath, '--once'], {
    cwd: path.join(__dirname, '..'),
  });

  botProcess.stdout.on('data', (data) => {
    const lines = data.toString().split('\n').filter(Boolean);
    lines.forEach(line => {
      try {
        const msg = JSON.parse(line);
        if (win) win.webContents.send('bot:message', msg);
      } catch {
        // not JSON — ignore (log output)
      }
    });
  });

  botProcess.stderr.on('data', (data) => {
    if (win) win.webContents.send('bot:log', data.toString());
  });

  botProcess.on('exit', (code) => {
    if (win) win.webContents.send('bot:exit', { code });
  });
}

// ── IPC handlers ──────────────────────────────────────────────────────────────

ipcMain.handle('bot:start', () => {
  if (!botProcess || botProcess.exitCode !== null) startBot();
});

ipcMain.handle('bot:stop', () => {
  if (botProcess) botProcess.kill();
});

ipcMain.handle('keywords:getSuggestions', async (_e, inputText) => {
  // Spawn keyword_suggester.py as a one-shot subprocess
  return new Promise((resolve) => {
    const pythonPath = process.platform === 'win32'
      ? path.join(__dirname, '..', '.venv', 'Scripts', 'python.exe')
      : path.join(__dirname, '..', '.venv', 'bin', 'python');

    const script = path.join(__dirname, '..', 'utils', '_suggest_cli.py');
    const proc = spawn(pythonPath, [script, inputText], {
      cwd: path.join(__dirname, '..'),
    });

    let output = '';
    proc.stdout.on('data', d => { output += d.toString(); });
    proc.on('exit', () => {
      try { resolve(JSON.parse(output)); }
      catch { resolve([]); }
    });
    setTimeout(() => { proc.kill(); resolve([]); }, 12_000);
  });
});

ipcMain.handle('keywords:addTerm', async (_e, { groupIndex, term }) => {
  const yaml  = require('js-yaml');
  const fs    = require('fs');
  const cfgPath = path.join(__dirname, '..', 'config.yaml');
  try {
    const cfg = yaml.load(fs.readFileSync(cfgPath, 'utf8'));
    const group = cfg.keywords[groupIndex];
    if (!group) return { ok: false };
    if (!group.terms_en) group.terms_en = [];
    if (!group.terms_en.includes(term)) group.terms_en.push(term);
    fs.writeFileSync(cfgPath, yaml.dump(cfg), 'utf8');
    return { ok: true };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
});

ipcMain.handle('keywords:reExpand', async (_e, { groupIndex }) => {
  const pythonPath = process.platform === 'win32'
    ? path.join(__dirname, '..', '.venv', 'Scripts', 'python.exe')
    : path.join(__dirname, '..', '.venv', 'bin', 'python');

  const script = path.join(__dirname, '..', 'utils', '_expand_cli.py');
  return new Promise((resolve) => {
    const proc = spawn(pythonPath, [script, String(groupIndex)], {
      cwd: path.join(__dirname, '..'),
    });
    let out = '';
    proc.stdout.on('data', d => { out += d.toString(); });
    proc.on('exit', () => {
      try { resolve(JSON.parse(out)); }
      catch { resolve({ ok: false }); }
    });
    setTimeout(() => { proc.kill(); resolve({ ok: false }); }, 60_000);
  });
});

ipcMain.handle('shell:openExternal', (_e, url) => shell.openExternal(url));

// ── App lifecycle ─────────────────────────────────────────────────────────────

app.whenReady().then(() => {
  createWindow();
  app.on('activate', () => { if (!win) createWindow(); });
});

app.on('window-all-closed', () => {
  if (botProcess) botProcess.kill();
  if (process.platform !== 'darwin') app.quit();
});
