import { ApplicationStateProvider } from './application/ApplicationState'
import DevWindow from './interfaces/dev/DevWindow'
import RendererShell from './shell/RendererShell'

export default function App(): React.JSX.Element {
  if (new URLSearchParams(window.location.search).get('window') === 'dev') {
    return <DevWindow />
  }

  return (
    <ApplicationStateProvider>
      <RendererShell />
    </ApplicationStateProvider>
  )
}
