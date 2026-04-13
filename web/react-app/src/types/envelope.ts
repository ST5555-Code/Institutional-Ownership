/**
 * Phase 1-B2 — response envelope types.
 *
 * Mirrors scripts/schemas.py. Every enveloped endpoint returns
 * `{data, error, meta}` where:
 *
 *   - data: T | null  — the payload (null on error or unavailable)
 *   - error: ErrorShape | null  — non-null when the request failed
 *   - meta: MetaShape  — always present; carries quarter/rollup/generated_at
 *
 * Not every endpoint is wrapped yet. The rollout is per-endpoint
 * (Batch 1-B2 covers the 6 priority endpoints). Unwrapped endpoints
 * continue to use `useFetch` + the bare response type.
 */

export interface ErrorShape {
  code: string
  message: string
  detail?: Record<string, unknown>
}

export interface MetaShape {
  quarter: string | null
  rollup_type: string | null
  generated_at: string  // ISO-8601 UTC
}

export interface Envelope<T> {
  data: T | null
  error: ErrorShape | null
  meta: MetaShape
}
