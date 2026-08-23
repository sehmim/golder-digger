import { app, BrowserWindow, dialog, ipcMain, shell } from 'electron'
import type { OpenDialogOptions } from 'electron'
import { mkdir, readFile, rename, stat, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import * as api from './api'

/** How often main asks Python how an ingest job is doing. */
const POLL_MS = 400

const pollers = new Map<string, ReturnType<typeof setInterval>>()
let settingsWrite = Promise.resolve()
let primaryWindow: BrowserWindow | null = null
let devWindow: BrowserWindow | null = null
let devSnapshot: unknown = null

function settingsPath(): string {
  return join(app.getPath('userData'), 'settings.json')
}

async function loadSettings(): Promise<unknown> {
  try {
    return JSON.parse(await readFile(settingsPath(), 'utf8'))
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null
    if (error instanceof SyntaxError) {
      console.error(`Ignoring malformed settings file at ${settingsPath()}`, error)
      return null
    }
    throw error
  }
}

function saveSettings(settings: unknown): Promise<void> {
  settingsWrite = settingsWrite.catch(() => undefined).then(async () => {
    const destination = settingsPath()
    const temporary = `${destination}.tmp`
    await mkdir(app.getPath('userData'), { recursive: true })
    await writeFile(temporary, `${JSON.stringify(settings, null, 2)}\n`, 'utf8')
    await rename(temporary, destination)
  })
  return settingsWrite
}

function broadcast(channel: string, payload: unknown): void {
  for (const window of BrowserWindow.getAllWindows()) {
    window.webContents.send(channel, payload)
  }
}

/**
 * Polls one job until it finishes and pushes every reading to the renderer, so
 * the UI never has to know the API exists.
 */
function watchJob(jobId: string): void {
  if (pollers.has(jobId)) return

  const timer = setInterval(async () => {
    try {
      const status = await api.jobStatus(jobId)
      broadcast('ingest:progress', status)

      if (status.state === 'finished') {
        clearInterval(timer)
        pollers.delete(jobId)
      }
    } catch (error) {
      clearInterval(timer)
      pollers.delete(jobId)
      broadcast('ingest:error', { job_id: jobId, error: String(error) })
    }
  }, POLL_MS)

  pollers.set(jobId, timer)
}

function loadRenderer(window: BrowserWindow, target?: 'dev'): void {
  if (process.env.ELECTRON_RENDERER_URL) {
    const url = new URL(process.env.ELECTRON_RENDERER_URL)
    if (target) url.searchParams.set('window', target)
    void window.loadURL(url.toString())
  } else {
    void window.loadFile(join(__dirname, '../renderer/index.html'), {
      query: target ? { window: target } : undefined
    })
  }
}

function openSettings(): void {
  if (!primaryWindow || primaryWindow.isDestroyed()) return
  if (primaryWindow.isMinimized()) primaryWindow.restore()
  primaryWindow.show()
  primaryWindow.focus()
  primaryWindow.webContents.send('settings:open')
}

function attachInterfaceShortcuts(window: BrowserWindow): void {
  window.webContents.on('before-input-event', (event, input) => {
    const isInterfaceShortcut =
      input.type === 'keyDown' &&
      input.meta &&
      input.alt &&
      !input.control &&
      !input.shift &&
      !input.isAutoRepeat

    if (isInterfaceShortcut && input.code === 'KeyD') {
      event.preventDefault()
      openDevWindow()
    }

    if (isInterfaceShortcut && input.code === 'KeyS') {
      event.preventDefault()
      openSettings()
    }
  })
}

function openDevWindow(): void {
  if (devWindow && !devWindow.isDestroyed()) {
    if (devWindow.isMinimized()) devWindow.restore()
    devWindow.show()
    devWindow.focus()
    return
  }

  devWindow = new BrowserWindow({
    width: 980,
    height: 760,
    minWidth: 900,
    minHeight: 600,
    backgroundColor: '#eceee8',
    title: 'Gold Digger Dev',
    titleBarStyle: 'hiddenInset',
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      sandbox: true,
      contextIsolation: true
    }
  })
  devWindow.on('closed', () => {
    devWindow = null
  })
  attachInterfaceShortcuts(devWindow)
  loadRenderer(devWindow, 'dev')
}

function createWindow(): void {
  const window = new BrowserWindow({
    width: 1180,
    height: 760,
    minWidth: 900,
    minHeight: 600,
    backgroundColor: '#11110f',
    titleBarStyle: 'hiddenInset',
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      sandbox: true,
      contextIsolation: true
    }
  })

  window.webContents.setWindowOpenHandler(({ url }) => {
    void shell.openExternal(url)
    return { action: 'deny' }
  })

  primaryWindow = window
  attachInterfaceShortcuts(window)
  window.on('closed', () => {
    primaryWindow = null
    devSnapshot = null
    if (devWindow && !devWindow.isDestroyed()) devWindow.close()
  })
  loadRenderer(window)
}

app.whenReady().then(() => {
  ipcMain.handle('directory:select', async () => {
    const parentWindow = BrowserWindow.getFocusedWindow()
    const options: OpenDialogOptions = {
      title: 'Select your sample directories',
      buttonLabel: 'Choose directories',
      properties: ['openDirectory', 'createDirectory', 'multiSelections']
    }
    const result = parentWindow
      ? await dialog.showOpenDialog(parentWindow, options)
      : await dialog.showOpenDialog(options)

    return result.canceled ? [] : result.filePaths
  })

  ipcMain.handle('project:select', async () => {
    const parentWindow = BrowserWindow.getFocusedWindow()
    const options: OpenDialogOptions = {
      title: 'Select your Ableton project',
      buttonLabel: 'Connect project',
      filters: [{ name: 'Ableton Live Set', extensions: ['als'] }],
      properties: ['openFile']
    }
    const result = parentWindow
      ? await dialog.showOpenDialog(parentWindow, options)
      : await dialog.showOpenDialog(options)

    return result.canceled ? null : result.filePaths[0]
  })

  ipcMain.handle('api:status', () => api.status())
  ipcMain.handle('dev:open', () => openDevWindow())
  ipcMain.handle('dev:snapshot:get', () => devSnapshot)
  ipcMain.on('dev:snapshot:publish', (event, snapshot: unknown) => {
    if (primaryWindow?.webContents !== event.sender) return
    devSnapshot = snapshot
    if (devWindow && !devWindow.isDestroyed()) {
      devWindow.webContents.send('dev:snapshot', snapshot)
    }
  })
  ipcMain.handle('folders:status', (_event, roots: string[]) => api.folderStatus(roots))
  ipcMain.handle(
    'dev:analysis-files',
    (_event, roots: string[] | null, limit: number, offset: number) =>
      api.analysisFiles(roots, limit, offset)
  )
  ipcMain.handle('settings:load', () => loadSettings())
  ipcMain.handle('settings:save', (_event, settings: unknown) => saveSettings(settings))
  ipcMain.handle('path:exists', async (_event, path: string) => {
    try {
      return (await stat(path)).isDirectory()
    } catch {
      return false
    }
  })

  ipcMain.handle('ingest:start', async (_event, roots: string[]) => {
    const { job_id } = await api.startIngest(roots)
    watchJob(job_id)
    return job_id
  })

  ipcMain.handle('session:load', (_event, path: string) => api.loadSet(path))

  // The same poller: an Essentia pass is a job row like any other.
  ipcMain.handle('essentia:start', async (_event, root: string) => {
    const { job_id } = await api.startEssentia(root)
    watchJob(job_id)
    return job_id
  })

  ipcMain.handle('essentia:summary', () => api.essentiaSummary())
  ipcMain.handle('dev:presets', () => api.presets())
  ipcMain.handle('dev:corpus-stats', () => api.corpusStats())

  ipcMain.handle('chunk:audio', (_event, chunkId: string, options: api.AuditionOptions) =>
    api.chunkAudio(chunkId, options)
  )

  ipcMain.handle(
    'session:analyze',
    (
      _event,
      contextIds: string[],
      distance: number | null,
      k: number,
      sessionPath: string | null,
      activeRoots: string[] | null | undefined,
      preset: string | null | undefined
    ) => api.analyze(contextIds, distance, k, sessionPath, activeRoots, preset)
  )

  createWindow()

  // The window paints while Python boots; the renderer polls api:status for it.
  api
    .start()
    .then(() => broadcast('api:ready', api.status()))
    .catch(() => broadcast('api:ready', api.status()))

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('before-quit', () => {
  for (const timer of pollers.values()) clearInterval(timer)
  pollers.clear()
  api.stop()
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
