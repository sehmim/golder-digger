import { app, BrowserWindow, dialog, ipcMain, shell } from 'electron'
import type { OpenDialogOptions } from 'electron'
import { join } from 'node:path'
import * as api from './api'

/** How often main asks Python how an ingest job is doing. */
const POLL_MS = 400

const pollers = new Map<string, ReturnType<typeof setInterval>>()

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

  if (process.env.ELECTRON_RENDERER_URL) {
    void window.loadURL(process.env.ELECTRON_RENDERER_URL)
  } else {
    void window.loadFile(join(__dirname, '../renderer/index.html'))
  }
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

  ipcMain.handle('chunk:audio', (_event, chunkId: string, options: api.AuditionOptions) =>
    api.chunkAudio(chunkId, options)
  )

  ipcMain.handle(
    'session:analyze',
    (_event, contextIds: string[], distance: number, k: number) =>
      api.analyze(contextIds, distance, k)
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
