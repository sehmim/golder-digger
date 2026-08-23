import { ApplicationStateProvider } from './application/ApplicationState'
import RendererShell from './shell/RendererShell'

export default function App(): React.JSX.Element {
  return (
    <ApplicationStateProvider>
      <RendererShell />
    </ApplicationStateProvider>
  )
}
