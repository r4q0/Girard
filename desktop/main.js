// Desktop window for the Girard dashboard.
// Starts the dashboard dev server from ../dashboard if it is not running yet,
// opens it in one window, and stops the server again on quit.

const { app, BrowserWindow, Menu, shell } = require("electron");
const { spawn } = require("node:child_process");
const path = require("node:path");

const PORT = Number(process.env.GIRARD_DASHBOARD_PORT || 5173);
const URL = process.env.GIRARD_DASHBOARD_URL || `http://localhost:${PORT}/`;
const DASHBOARD_DIR = path.resolve(__dirname, "..", "dashboard");

let server = null;
let win = null;

async function isUp() {
  try {
    const res = await fetch(URL);
    return res.ok;
  } catch {
    return false;
  }
}

async function ensureDashboard() {
  if (await isUp()) return;
  server = spawn("npx", ["vite", "dev", "--port", String(PORT)], {
    cwd: DASHBOARD_DIR,
    stdio: "inherit",
    shell: process.platform === "win32",
  });
  server.on("exit", (code) => {
    server = null;
    if (code) console.error(`Dashboard server exited with code ${code}.`);
  });
  for (let i = 0; i < 60; i++) {
    if (await isUp()) return;
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(
    `Dashboard did not start at ${URL}. Run "npm install --no-package-lock" in dashboard/ first.`,
  );
}

function buildMenu() {
  const template = [
    ...(process.platform === "darwin" ? [{ role: "appMenu" }] : []),
    { role: "editMenu" },
    {
      label: "View",
      submenu: [
        {
          label: "Always on Top",
          type: "checkbox",
          accelerator: "CmdOrCtrl+Shift+T",
          click: (item) => win?.setAlwaysOnTop(item.checked, "floating"),
        },
        { type: "separator" },
        { role: "reload" },
        { role: "toggleDevTools" },
        { type: "separator" },
        { role: "resetZoom" },
        { role: "zoomIn" },
        { role: "zoomOut" },
        { role: "togglefullscreen" },
      ],
    },
    { role: "windowMenu" },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

async function createWindow() {
  win = new BrowserWindow({
    width: 760,
    height: 1000,
    minWidth: 420,
    minHeight: 400,
    title: "Girard",
    backgroundColor: "#050814",
  });
  // Links to other sites (research sources) open in the normal browser.
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });
  await win.loadURL(URL);
}

app.whenReady().then(async () => {
  buildMenu();
  try {
    await ensureDashboard();
  } catch (err) {
    console.error(err.message);
    app.quit();
    return;
  }
  await createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => app.quit());

app.on("will-quit", () => {
  if (server) server.kill();
});
