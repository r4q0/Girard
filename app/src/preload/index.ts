import { contextBridge, ipcRenderer, type IpcRendererEvent } from 'electron'
import type { AppState, Command, GirardApi, Toast } from '@shared/schema'

const api: GirardApi = {
  send: (command: Command) => ipcRenderer.invoke('girard:cmd', command),
  onState: (listener) => {
    const fn = (_e: IpcRendererEvent, state: AppState) => listener(state)
    ipcRenderer.on('girard:state', fn)
    return () => ipcRenderer.removeListener('girard:state', fn)
  },
  onToast: (listener) => {
    const fn = (_e: IpcRendererEvent, toast: Toast) => listener(toast)
    ipcRenderer.on('girard:toast', fn)
    return () => ipcRenderer.removeListener('girard:toast', fn)
  }
}

contextBridge.exposeInMainWorld('girard', api)
