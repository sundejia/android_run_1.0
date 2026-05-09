import electron from 'electron'

const { contextBridge, ipcRenderer } = electron

// Expose protected methods that allow the renderer process to use
// ipcRenderer without exposing the entire object
contextBridge.exposeInMainWorld('electronAPI', {
  // Mirror controls
  mirror: {
    start: (serial: string) => ipcRenderer.invoke('mirror:start', serial),
    stop: (serial: string) => ipcRenderer.invoke('mirror:stop', serial),
    status: (serial: string) => ipcRenderer.invoke('mirror:status', serial),
  },

  // Sidecar window
  sidecar: {
    open: (serial: string) => ipcRenderer.invoke('sidecar:open', serial),
  },

  // Log popup window
  logPopup: {
    open: (serial: string) => ipcRenderer.invoke('logPopup:open', serial),
    setAlwaysOnTop: (alwaysOnTop: boolean) => ipcRenderer.invoke('logPopup:setAlwaysOnTop', alwaysOnTop),
    isAlwaysOnTop: () => ipcRenderer.invoke('logPopup:isAlwaysOnTop'),
  },
  
  // Shell operations
  shell: {
    openExternal: (url: string) => ipcRenderer.invoke('shell:openExternal', url),
  },
  
  // Platform info
  platform: process.platform,
})

// Type definitions for the exposed API
declare global {
  interface Window {
    electronAPI: {
      mirror: {
        start: (serial: string) => Promise<boolean>
        stop: (serial: string) => Promise<boolean>
        status: (serial: string) => Promise<boolean>
      }
      sidecar: {
        open: (serial: string) => Promise<void>
      }
      logPopup: {
        open: (serial: string) => Promise<void>
        setAlwaysOnTop: (alwaysOnTop: boolean) => Promise<boolean>
        isAlwaysOnTop: () => Promise<boolean>
      }
      shell: {
        openExternal: (url: string) => Promise<void>
      }
      platform: NodeJS.Platform
    }
  }
}

