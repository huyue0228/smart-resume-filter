import { Routes, Route, Navigate } from 'react-router-dom'
import { RoleProvider } from './contexts/RoleContext'
import { useRole } from './contexts/roleState'
import { canAccessRoute, DEFAULT_AUTHENTICATED_PATH } from './routePermissions'
import BasicLayout from './layouts/BasicLayout'
import LoginPage from './pages/LoginPage'
import ResumesPage from './pages/ResumesPage'
import JobsPage from './pages/JobsPage'
import SchoolsPage from './pages/SchoolsPage'
import DepartmentsPage from './pages/DepartmentsPage'
import ConfigPage from './pages/ConfigPage'
import AIConnectionPage from './pages/AIConnectionPage'
import UsersPage from './pages/UsersPage'

function AppRoutes() {
  const { loading, isAuthenticated, hasPermission } = useRole()

  if (loading) return null

  if (!isAuthenticated) {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    )
  }

  const defaultPath = DEFAULT_AUTHENTICATED_PATH

  const guarded = (path, element) => {
    return canAccessRoute(path, hasPermission) ? (
      element
    ) : (
      <Navigate to={defaultPath} replace />
    )
  }

  return (
    <Routes>
      <Route path="/login" element={<Navigate to={defaultPath} replace />} />
      <Route element={<BasicLayout />}>
        <Route index element={<Navigate to={defaultPath} replace />} />
        <Route
          path="/resumes"
          element={guarded('/resumes', <ResumesPage />)}
        />
        <Route path="/jobs" element={guarded('/jobs', <JobsPage />)} />
        <Route path="/schools" element={guarded('/schools', <SchoolsPage />)} />
        <Route
          path="/departments"
          element={guarded('/departments', <DepartmentsPage />)}
        />
        <Route
          path="/config"
          element={guarded('/config', <ConfigPage />)}
        />
        <Route
          path="/ai-connection"
          element={guarded('/ai-connection', <AIConnectionPage />)}
        />
        <Route
          path="/users"
          element={guarded('/users', <UsersPage />)}
        />
        <Route path="*" element={<Navigate to={defaultPath} replace />} />
      </Route>
    </Routes>
  )
}

export default function App() {
  return (
    <RoleProvider>
      <AppRoutes />
    </RoleProvider>
  )
}
