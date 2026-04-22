export interface LoginRequest {
  email: string
  password: string
}

export interface RegisterRequest {
  email: string
  password: string
  name: string
  organization_name: string
}

export interface LoginResponse {
  access: string
  refresh: string
}

export interface RegisterResponse {
  id: number
  email: string
  name: string
  organization: {
    id: number
    name: string
  }
  token: string
}

export interface User {
  id: number
  email: string
  name: string
  organization?: {
    id: number
    name: string
  }
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
