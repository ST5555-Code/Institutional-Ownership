import { Component, type ErrorInfo, type ReactNode } from 'react'

/**
 * Phase 1-B2 — per-tab error boundary.
 *
 * Catches React render/commit errors in the wrapped subtree and shows a
 * consistent error card. Envelope-level errors from `useFetchEnvelope`
 * surface as normal `error` strings handled by the tab itself — this
 * boundary is for unexpected exceptions, not expected API failures.
 *
 * Usage:
 *   <ErrorBoundary tab="register">
 *     <RegisterTab />
 *   </ErrorBoundary>
 */

interface Props {
  tab: string
  children: ReactNode
}

interface State {
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Surface the stack in the dev console — Sentry/Datadog wiring
    // lives elsewhere (see ARCHITECTURE_REVIEW.md Observability plan,
    // not yet implemented).
    // eslint-disable-next-line no-console
    console.error(`[ErrorBoundary:${this.props.tab}]`, error, info.componentStack)
  }

  reset = () => this.setState({ error: null })

  render() {
    if (this.state.error) {
      return (
        <div
          style={{
            padding: 32,
            margin: 16,
            border: '1px solid #fecaca',
            borderRadius: 6,
            backgroundColor: '#fef2f2',
            color: '#7f1d1d',
          }}
          role="alert"
        >
          <div style={{ fontWeight: 700, marginBottom: 8, fontSize: 14 }}>
            Something went wrong on the {this.props.tab} tab.
          </div>
          <div style={{ fontSize: 13, marginBottom: 12, fontFamily: 'monospace' }}>
            {this.state.error.message}
          </div>
          <button
            type="button"
            onClick={this.reset}
            style={{
              padding: '6px 12px',
              fontSize: 13,
              color: '#ffffff',
              backgroundColor: '#991b1b',
              border: 'none',
              borderRadius: 4,
              cursor: 'pointer',
            }}
          >
            Try again
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
