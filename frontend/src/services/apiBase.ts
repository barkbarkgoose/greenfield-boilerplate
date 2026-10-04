// The API's base URL, in its own module so the session helper can use it
// without importing the Axios instance (which imports the router).
export const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8800'
