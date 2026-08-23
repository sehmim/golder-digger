import splashVideo from '../assets/boot-splash.webm'

interface BootSplashProps {
  /** Flips the fade-out; the shell unmounts the splash after the transition. */
  ready: boolean
  error: string | null
}

/**
 * Covers the interfaces while the engine boots -- importing the package pulls
 * in torch, so real mode stares at nothing for ~20s otherwise. The animation
 * is a VP9-with-alpha loop, which Chromium composites straight onto the theme
 * background; a boot failure surfaces here too, because a splash that never
 * resolves is where the user will be looking when it doesn't.
 */
export default function BootSplash({ ready, error }: BootSplashProps): React.JSX.Element {
  return (
    <div className="boot-splash" data-ready={ready || undefined} role="status">
      <video
        className="boot-splash__video"
        src={splashVideo}
        autoPlay
        loop
        muted
        playsInline
        aria-hidden="true"
      />
      <p className="boot-splash__status" data-error={error ? '' : undefined}>
        {error ?? 'Starting the audio engine…'}
      </p>
    </div>
  )
}
