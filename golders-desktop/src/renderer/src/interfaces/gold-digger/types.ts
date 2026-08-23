export type GoldDiggerStep = 'sources' | 'project' | 'dig'

export interface GoldDiggerDiagnostics {
  currentStep: GoldDiggerStep
  leavingStep: GoldDiggerStep | null
  visiblePanels: GoldDiggerStep[]
  hasReachedProject: boolean
}
