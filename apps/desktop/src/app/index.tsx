import '@/macman/macman.css'

// MacMan owns the desktop presentation while the contribution wiring beneath
// it remains the canonical Hermes session, tool, approval, and model runtime.
// This boundary is intentionally visual: the shell never reimplements prompt
// submission or completion state.
export { MacManController as default } from '@/macman/macman-shell'
