import api from '@/services/api'

/** Ask for a reset link. Answers the same whether or not the email has an account. */
export async function requestPasswordReset(email: string): Promise<void> {
  await api.post('/api/v1/auth/password-reset/', { email })
}

/** Set a new password using the uid and token from the emailed link. */
export async function confirmPasswordReset(uid: string, token: string, password: string): Promise<void> {
  await api.post('/api/v1/auth/password-reset/confirm/', { uid, token, password })
}
