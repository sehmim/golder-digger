import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('desktop', {
  selectDirectories: (): Promise<string[]> => ipcRenderer.invoke('directory:select')
})
