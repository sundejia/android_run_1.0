/**
 * Scrcpy Mirror Manager
 * 
 * Handles spawning and managing scrcpy processes for device mirroring.
 * Supports both system-installed scrcpy and bundled binaries.
 */

import { spawn, ChildProcess } from 'child_process'
import electron from 'electron'
import { join } from 'path'
import { existsSync } from 'fs'

const { app } = electron

export interface MirrorOptions {
  serial: string
  title?: string
  maxSize?: number
  bitRate?: number
  maxFps?: number
  stayAwake?: boolean
  turnScreenOff?: boolean
  showTouches?: boolean
  noAudio?: boolean
  borderless?: boolean
  alwaysOnTop?: boolean
  position?: { x: number; y: number }
  size?: { width: number; height: number }
}

export interface MirrorProcess {
  process: ChildProcess
  serial: string
  startedAt: Date
}

// Store active mirror processes
const mirrorProcesses = new Map<string, MirrorProcess>()

/**
 * Find scrcpy binary path
 */
function findScrcpyPath(): string {
  // Explicit override
  const envPath = process.env.SCRCPY_PATH
  if (envPath) {
    if (existsSync(envPath)) {
      return envPath
    }
    console.warn(`[Mirror] SCRCPY_PATH is set but not found: ${envPath}`)
  }

  // Check for bundled scrcpy in resources
  const resourcesPath = process.resourcesPath || app.getAppPath()
  const bundledPaths = [
    join(resourcesPath, 'scrcpy', 'scrcpy'),
    join(resourcesPath, 'scrcpy', 'scrcpy.exe'),
    join(resourcesPath, 'bin', 'scrcpy'),
    join(resourcesPath, 'bin', 'scrcpy.exe'),
  ]

  for (const path of bundledPaths) {
    if (existsSync(path)) {
      return path
    }
  }

  // Check project-local scrcpy folder (for development)
  // app.getAppPath() returns the electron source dir, we need to go up to wecom-desktop
  const appPath = app.getAppPath()
  const projectLocalPaths = [
    // When running from electron/ folder
    join(appPath, '..', 'scrcpy', 'scrcpy.exe'),
    join(appPath, '..', 'scrcpy', 'scrcpy'),
    // When running from wecom-desktop root
    join(appPath, 'scrcpy', 'scrcpy.exe'),
    join(appPath, 'scrcpy', 'scrcpy'),
    // Direct relative paths
    join(__dirname, '..', '..', 'scrcpy', 'scrcpy.exe'),
    join(__dirname, '..', '..', 'scrcpy', 'scrcpy'),
    join(__dirname, '..', '..', '..', 'scrcpy', 'scrcpy.exe'),
    join(__dirname, '..', '..', '..', 'scrcpy', 'scrcpy'),
  ]

  for (const path of projectLocalPaths) {
    if (existsSync(path)) {
      console.log(`[Mirror] Found project-local scrcpy: ${path}`)
      return path
    }
  }

  // Check common install locations (handles Finder launch without PATH)
  const commonPaths = [
    '/opt/homebrew/bin/scrcpy', // macOS ARM (brew)
    '/usr/local/bin/scrcpy',    // macOS Intel / some Linux
    '/usr/bin/scrcpy',          // Linux
    'C:\\Program Files\\scrcpy\\scrcpy.exe',
    'C:\\Program Files (x86)\\scrcpy\\scrcpy.exe',
  ]

  for (const path of commonPaths) {
    if (existsSync(path)) {
      return path
    }
  }

  // Fall back to system scrcpy (PATH)
  return 'scrcpy'
}

/**
 * Build scrcpy command arguments
 */
function buildArgs(options: MirrorOptions): string[] {
  const args: string[] = ['-s', options.serial]

  // Window title
  if (options.title) {
    args.push('--window-title', options.title)
  } else {
    args.push('--window-title', `WeCom Mirror - ${options.serial}`)
  }

  // Video quality
  if (options.maxSize) {
    args.push('--max-size', options.maxSize.toString())
  }

  if (options.bitRate) {
    args.push('--video-bit-rate', `${options.bitRate}M`)
  }

  if (options.maxFps) {
    args.push('--max-fps', options.maxFps.toString())
  }

  // Screen behavior
  if (options.stayAwake !== false) {
    args.push('--stay-awake')
  }

  if (options.turnScreenOff) {
    args.push('--turn-screen-off')
  }

  if (options.showTouches) {
    args.push('--show-touches')
  }

  // Audio
  if (options.noAudio !== false) {
    args.push('--no-audio')
  }

  // Window options
  if (options.borderless) {
    args.push('--window-borderless')
  }

  if (options.alwaysOnTop) {
    args.push('--always-on-top')
  }

  if (options.position) {
    args.push('--window-x', options.position.x.toString())
    args.push('--window-y', options.position.y.toString())
  }

  if (options.size) {
    args.push('--window-width', options.size.width.toString())
    args.push('--window-height', options.size.height.toString())
  }

  return args
}

/**
 * Start a mirror for a device
 */
export function startMirror(options: MirrorOptions): boolean {
  const { serial } = options

  // Check if already mirroring
  if (mirrorProcesses.has(serial)) {
    const existing = mirrorProcesses.get(serial)!
    if (existing.process.exitCode === null) {
      console.log(`[Mirror] Already mirroring ${serial}`)
      return true
    }
    // Process has exited, clean up
    mirrorProcesses.delete(serial)
  }

  try {
    const scrcpyPath = findScrcpyPath()
    const args = buildArgs(options)

    console.log(`[Mirror] Starting: ${scrcpyPath} ${args.join(' ')}`)

    const process = spawn(scrcpyPath, args, {
      detached: false,
      stdio: ['ignore', 'pipe', 'pipe'],
    })

    // Handle stdout
    process.stdout?.on('data', (data) => {
      const message = data.toString().trim()
      if (message) {
        console.log(`[Mirror ${serial}] ${message}`)
      }
    })

    // Handle stderr
    process.stderr?.on('data', (data) => {
      const message = data.toString().trim()
      if (message) {
        console.error(`[Mirror ${serial}] ${message}`)
      }
    })

    // Handle process exit
    process.on('close', (code) => {
      console.log(`[Mirror ${serial}] Process exited with code ${code}`)
      mirrorProcesses.delete(serial)
    })

    // Handle spawn error
    process.on('error', (err) => {
      console.error(`[Mirror ${serial}] Failed to start:`, err.message)
      mirrorProcesses.delete(serial)
    })

    // Store process
    mirrorProcesses.set(serial, {
      process,
      serial,
      startedAt: new Date(),
    })

    return true
  } catch (error) {
    console.error(`[Mirror] Failed to start mirror for ${serial}:`, error)
    return false
  }
}

/**
 * Stop a mirror for a device
 */
export function stopMirror(serial: string): boolean {
  const mirror = mirrorProcesses.get(serial)
  
  // If no mirror process exists, consider it already stopped (success)
  if (!mirror) {
    console.log(`[Mirror] No active mirror found for ${serial}, considering already stopped`)
    return true
  }

  // If process already exited, clean up and return success
  if (mirror.process.exitCode !== null) {
    console.log(`[Mirror] Mirror process for ${serial} already exited (code: ${mirror.process.exitCode})`)
    mirrorProcesses.delete(serial)
    return true
  }

  try {
    // Send SIGTERM for graceful shutdown
    mirror.process.kill('SIGTERM')

    // Force kill after timeout
    setTimeout(() => {
      if (mirror.process.exitCode === null) {
        mirror.process.kill('SIGKILL')
      }
    }, 2000)

    mirrorProcesses.delete(serial)
    console.log(`[Mirror] Stopped mirror for ${serial}`)
    return true
  } catch (error) {
    console.error(`[Mirror] Failed to stop mirror for ${serial}:`, error)
    // Still clean up the reference even if kill failed
    mirrorProcesses.delete(serial)
    return true  // Return true so UI can update
  }
}

/**
 * Check if a device is being mirrored
 */
export function isMirroring(serial: string): boolean {
  const mirror = mirrorProcesses.get(serial)
  return mirror !== undefined && mirror.process.exitCode === null
}

/**
 * Get all active mirrors
 */
export function getActiveMirrors(): string[] {
  return Array.from(mirrorProcesses.keys()).filter((serial) => {
    const mirror = mirrorProcesses.get(serial)
    return mirror && mirror.process.exitCode === null
  })
}

/**
 * Stop all mirrors
 */
export function stopAllMirrors(): void {
  for (const serial of mirrorProcesses.keys()) {
    stopMirror(serial)
  }
}

/**
 * Get mirror info for a device
 */
export function getMirrorInfo(serial: string): MirrorProcess | undefined {
  return mirrorProcesses.get(serial)
}

