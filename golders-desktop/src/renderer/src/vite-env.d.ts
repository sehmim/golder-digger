/// <reference types="vite/client" />

interface Window {
  desktop: {
    selectDirectories: () => Promise<string[]>
  }
}
