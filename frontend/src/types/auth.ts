export interface LoginRequest {
  email: string
  password: string
}

export interface RegisterRequest {
  email: string
  password: string
  name: string
}

export interface LoginResponse {
  access: string
  refresh: string
  user?: User
}

export interface RegisterResponse {
  id: number
  email: string
  name: string
  is_staff?: boolean
  token: string
}

export interface User {
  id: number
  email: string
  name: string
  is_staff?: boolean
}

export interface AuthState {
  user: User | null
  token: string | null
  isAuthenticated: boolean
}

export interface LoginCredentials {
  email: string
  password: string
}
