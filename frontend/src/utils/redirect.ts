/**
 * The `?redirect=` target after sign-in: a path on this site, or null.
 *
 * Rejects absolute and protocol-relative URLs (`//evil.example`) so a crafted
 * login link can't send someone off-site.
 */
export function safeRedirect(value: unknown): string | null {
  if (typeof value !== 'string' || !value.startsWith('/')) return null
  if (value.startsWith('//') || value.startsWith('/\\')) return null
  return value
}
