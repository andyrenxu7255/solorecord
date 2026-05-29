const { app, BrowserWindow, Menu, shell } = require("electron");

const DEFAULT_SERVER_URL = "http://127.0.0.1:8000";

function getServerUrl() {
  const cliArg = process.argv.find((arg) => arg.startsWith("--server="));
  const raw = cliArg ? cliArg.slice("--server=".length) : process.env.SOLO_SERVER_URL;
  return normalizeUrl(raw || DEFAULT_SERVER_URL);
}

function normalizeUrl(value) {
  try {
    const url = new URL(value);
    if (!["http:", "https:"].includes(url.protocol)) return DEFAULT_SERVER_URL;
    return url.toString().replace(/\/$/, "");
  } catch {
    return DEFAULT_SERVER_URL;
  }
}

function createWindow() {
  const mainWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 960,
    minHeight: 640,
    title: "SoloRecord",
    backgroundColor: "#f5f7fb",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  mainWindow.loadURL(getServerUrl());
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });
}

function buildMenu() {
  return Menu.buildFromTemplate([
    {
      label: "SoloRecord",
      submenu: [
        { role: "about", label: "关于 SoloRecord" },
        { type: "separator" },
        { role: "quit", label: "退出" },
      ],
    },
    {
      label: "视图",
      submenu: [
        { role: "reload", label: "刷新" },
        { role: "forceReload", label: "强制刷新" },
        { role: "toggleDevTools", label: "开发者工具" },
        { type: "separator" },
        { role: "resetZoom", label: "实际大小" },
        { role: "zoomIn", label: "放大" },
        { role: "zoomOut", label: "缩小" },
      ],
    },
  ]);
}

app.whenReady().then(() => {
  Menu.setApplicationMenu(buildMenu());
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
