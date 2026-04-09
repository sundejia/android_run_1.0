import { app, BrowserWindow, ipcMain, shell } from 'electron'
import { join } from 'path'
import {
  startMirror as startScrcpyMirror,
  stopMirror as stopScrcpyMirror,
  isMirroring,
  stopAllMirrors,
  getActiveMirrors,
} from './scrcpy/mirror'

function createWindow(): BrowserWindow {
  const mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1000,
    minHeight: 700,
    webPreferences: {
      preload: join(__dirname, '../preload/index.mjs'),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: false,
    },
    titleBarStyle: 'hiddenInset',
    backgroundColor: '#010409',
    show: false,
  })

  // Show window when ready
  mainWindow.once('ready-to-show', () => {
    mainWindow.show()
  })

  // Load the app
  if (process.env.NODE_ENV === 'development') {
    mainWindow.loadURL('http://localhost:5173')
    mainWindow.webContents.openDevTools()
  } else {
    mainWindow.loadFile(join(__dirname, '../../dist/index.html'))
  }

  return mainWindow
}

function createSidecarWindow(serial: string): BrowserWindow {
  const sidecarWindow = new BrowserWindow({
    width: 420,
    height: 820,
    minWidth: 360,
    minHeight: 640,
    title: `Sidecar · ${serial}`,
    backgroundColor: '#010409',
    titleBarStyle: 'hiddenInset',
    webPreferences: {
      preload: join(__dirname, '../preload/index.mjs'),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: false,
    },
  })

  const route = `/sidecar/${serial}`

  if (process.env.NODE_ENV === 'development') {
    sidecarWindow.loadURL(`http://localhost:5173/?route=${encodeURIComponent(route)}`)
  } else {
    sidecarWindow.loadFile(join(__dirname, '../../dist/index.html'), {
      search: `?route=${encodeURIComponent(route)}`,
    })
  }

  return sidecarWindow
}

// Track log popup windows for setAlwaysOnTop
const logPopupWindows = new Map<number, BrowserWindow>()

function createLogPopupWindow(serial: string): BrowserWindow {
  const logPopupWindow = new BrowserWindow({
    width: 500,
    height: 400,
    minWidth: 300,
    minHeight: 200,
    title: `Logs · ${serial}`,
    backgroundColor: '#010409',
    titleBarStyle: 'hiddenInset',
    webPreferences: {
      preload: join(__dirname, '../preload/index.mjs'),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: false,
    },
  })

  // Set always on top with 'floating' level for stronger pinning (works better on macOS)
  logPopupWindow.setAlwaysOnTop(true, 'floating')

  const route = `/log-popup/${serial}`

  if (process.env.NODE_ENV === 'development') {
    logPopupWindow.loadURL(`http://localhost:5173/?route=${encodeURIComponent(route)}`)
  } else {
    logPopupWindow.loadFile(join(__dirname, '../../dist/index.html'), {
      search: `?route=${encodeURIComponent(route)}`,
    })
  }

  // Track this window - capture ID before it gets destroyed
  const webContentsId = logPopupWindow.webContents.id
  logPopupWindows.set(webContentsId, logPopupWindow)

  // Clean up when closed (use captured ID since webContents is destroyed by this point)
  logPopupWindow.on('closed', () => {
    logPopupWindows.delete(webContentsId)
  })

  return logPopupWindow
}

// IPC Handlers
ipcMain.handle('mirror:start', async (_, serial: string) => {
  return startScrcpyMirror({ serial })
})

ipcMain.handle('mirror:stop', async (_, serial: string) => {
  return stopScrcpyMirror(serial)
})

ipcMain.handle('mirror:status', async (_, serial: string) => {
  return isMirroring(serial)
})

ipcMain.handle('sidecar:open', async (_, serial: string) => {
  createSidecarWindow(serial)
})

ipcMain.handle('logPopup:open', async (_, serial: string) => {
  createLogPopupWindow(serial)
})

ipcMain.handle('logPopup:setAlwaysOnTop', async (event, alwaysOnTop: boolean) => {
  const window = logPopupWindows.get(event.sender.id)
  if (window && !window.isDestroyed()) {
    // Use 'floating' level for stronger always-on-top behavior on macOS
    window.setAlwaysOnTop(alwaysOnTop, 'floating')
    return window.isAlwaysOnTop()
  }
  return false
})

ipcMain.handle('logPopup:isAlwaysOnTop', async (event) => {
  const window = logPopupWindows.get(event.sender.id)
  if (window && !window.isDestroyed()) {
    return window.isAlwaysOnTop()
  }
  return false
})

ipcMain.handle('mirror:list', async () => {
  return getActiveMirrors()
})

ipcMain.handle('shell:openExternal', async (_, url: string) => {
  await shell.openExternal(url)
})

// App lifecycle
app.whenReady().then(() => {
  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow()
    }
  })
})

app.on('window-all-closed', () => {
  // Clean up all mirror processes
  stopAllMirrors()

  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('before-quit', () => {
  // Ensure all processes are cleaned up
  stopAllMirrors()
})

