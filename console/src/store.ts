import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { Role } from './roles.ts'

interface AppState {
  role: Role
  setRole: (role: Role) => void
}

// The one piece of client-only, cross-page state the console has: which
// role's view the operator is looking through. Persisted to localStorage
// (zustand's `persist` middleware) so a reload keeps the chosen role,
// same as the theme choice will once Stage 5 lands. Everything else in
// the console (findings, feed health, cost) still comes from the server
// on each load -- this store is deliberately small.
export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      role: 'TRANSPORT_MANAGER',
      setRole: (role) => set({ role }),
    }),
    { name: 'signal-desk:role' },
  ),
)
