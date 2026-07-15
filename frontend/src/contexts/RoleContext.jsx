import { useEffect, useMemo, useState } from 'react'
import { fetchMe, login as loginApi, logout as logoutApi } from '../api/services'
import { RoleContext } from './roleState'

export function RoleProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem('srf_token') || '')
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(Boolean(token))

  const refreshMe = async () => {
    if (!localStorage.getItem('srf_token')) {
      setUser(null)
      setLoading(false)
      return null
    }
    setLoading(true)
    try {
      const { data } = await fetchMe()
      setUser(data)
      return data
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refreshMe().catch(() => {
      localStorage.removeItem('srf_token')
      setToken('')
      setUser(null)
      setLoading(false)
    })
  }, [token])

  const login = async (values) => {
    const { data } = await loginApi(values)
    localStorage.setItem('srf_token', data.token)
    setToken(data.token)
    setUser(data.user)
    return data.user
  }

  const logout = async () => {
    try {
      await logoutApi()
    } catch {
      // token may already be invalid
    }
    localStorage.removeItem('srf_token')
    setToken('')
    setUser(null)
  }

  const permissions = useMemo(() => new Set(user?.permissions || []), [user])
  const hasPermission = (code) => permissions.has(code)
  const role = user?.role || 'hr'
  const isSecondaryContact = Boolean(user?.contact) && hasPermission('attempt.view_received')
  const isTertiaryContact = Boolean(user?.contact) && hasPermission('attempt.view_assigned')
  const isContact = isSecondaryContact || isTertiaryContact

  return (
    <RoleContext.Provider
      value={{
        token,
        user,
        loading,
        role,
        roles: user?.roles || [],
        permissions: user?.permissions || [],
        contact: user?.contact || null,
        isAuthenticated: Boolean(token && user),
        login,
        logout,
        refreshMe,
        hasPermission,
        isContact,
        isSecondaryContact,
        isTertiaryContact,
      }}
    >
      {children}
    </RoleContext.Provider>
  )
}
