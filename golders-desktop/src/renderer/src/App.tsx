import { useState } from 'react'

export default function App() {
  const [selectedDirectories, setSelectedDirectories] = useState<string[]>([])

  async function chooseDirectories() {
    const directories = await window.desktop.selectDirectories()

    if (directories.length > 0) {
      setSelectedDirectories((current) => [...new Set([...current, ...directories])])
    }
  }

  function removeDirectory(directory: string) {
    setSelectedDirectories((current) => current.filter((item) => item !== directory))
  }

  return (
    <main className="page">
      <section className="directory-picker">
        <div className="folder-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" role="img">
            <path d="M3.5 6.5a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2v-11Z" />
          </svg>
        </div>

        <div className="copy">
          <p className="eyebrow">Get started</p>
          <h1>Select your sample directories</h1>
          <p className="description">
            Choose the folders that contain the audio files you want Gold Digger to explore.
          </p>
        </div>

        <button className="primary-button" type="button" onClick={chooseDirectories}>
          {selectedDirectories.length > 0 ? 'Add directories' : 'Choose directories'}
        </button>

        {selectedDirectories.length > 0 ? (
          <div className="selections" aria-live="polite">
            <div className="selections-header">
              <span>
                {selectedDirectories.length}{' '}
                {selectedDirectories.length === 1 ? 'directory' : 'directories'} selected
              </span>
              <button
                className="clear-button"
                type="button"
                onClick={() => setSelectedDirectories([])}
              >
                Clear all
              </button>
            </div>

            <ul>
              {selectedDirectories.map((directory) => (
                <li key={directory}>
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M3.5 6.5a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2v-11Z" />
                  </svg>
                  <span title={directory}>{directory}</span>
                  <button
                    className="remove-button"
                    type="button"
                    aria-label={`Remove ${directory}`}
                    onClick={() => removeDirectory(directory)}
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="hint">Select multiple folders with Command-click.</p>
        )}
      </section>
    </main>
  )
}
