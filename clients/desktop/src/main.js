const fs = require("node:fs");
const path = require("node:path");
const { app, BrowserWindow, Menu, session, shell } = require("electron");

const DEFAULT_SERVER_URL = "https://record.uino.com";
const SERVER_URL = getServerUrl();

app.commandLine.appendSwitch("unsafely-treat-insecure-origin-as-secure", new URL(SERVER_URL).origin);

function getServerUrl() {
  const cliArg = process.argv.find((arg) => arg.startsWith("--server="));
  const raw = cliArg
    ? cliArg.slice("--server=".length)
    : process.env.SOLO_SERVER_URL || readPackagedServerUrl();
  return normalizeUrl(raw || DEFAULT_SERVER_URL);
}

function readPackagedServerUrl() {
  const candidates = [
    path.join(path.dirname(process.execPath), "server-url.txt"),
    path.join(process.resourcesPath || "", "server-url.txt"),
  ];
  for (const candidate of candidates) {
    try {
      const value = fs.readFileSync(candidate, "utf8").trim();
      if (value) return value;
    } catch {
      // Missing config is fine; internal builds fall back to the company server.
    }
  }
  return "";
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

function createWindow(serverUrl = SERVER_URL) {
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
      webSecurity: true,
    },
  });

  mainWindow.loadURL(withDesktopMode(serverUrl));
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });
}

function withDesktopMode(serverUrl) {
  const url = new URL(serverUrl);
  url.searchParams.set("client", "desktop");
  return url.toString();
}

function configureMediaPermissions(serverUrl = SERVER_URL) {
  const allowedOrigin = new URL(serverUrl).origin;
  const isAllowedOrigin = (value) => {
    try {
      return new URL(value || allowedOrigin).origin === allowedOrigin;
    } catch {
      return false;
    }
  };

  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback) => {
    callback(permission === "media" && isAllowedOrigin(webContents.getURL()));
  });

  session.defaultSession.setPermissionCheckHandler((webContents, permission, requestingOrigin) => {
    return permission === "media" && isAllowedOrigin(requestingOrigin || webContents?.getURL());
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
  configureMediaPermissions();
  Menu.setApplicationMenu(buildMenu());
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
