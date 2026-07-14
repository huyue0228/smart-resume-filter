import { Routes, Route, Navigate } from 'react-router-dom'
import { RoleProvider, useRole } from './contexts/RoleContext'
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

  const defaultPath = '/resumes'

  const guarded = (permission, element) => {
    const permissions = Array.isArray(permission) ? permission : [permission]
    return permissions.some((code) => hasPermission(code)) ? (
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
          element={guarded(
            ['resume.view', 'attempt.view_received', 'attempt.view_assigned'],
            <ResumesPage />,
          )}
        />
        <Route path="/jobs" element={guarded('job.view', <JobsPage />)} />
        <Route path="/schools" element={guarded('school.view', <SchoolsPage />)} />
        <Route
          path="/departments"
          element={guarded('department.view', <DepartmentsPage />)}
        />
        <Route
          path="/config"
          element={guarded('settings.manage_config', <ConfigPage />)}
        />
        <Route
          path="/ai-connection"
          element={guarded('settings.manage_ai_connection', <AIConnectionPage />)}
        />
        <Route
          path="/users"
          element={guarded('settings.manage_permissions', <UsersPage />)}
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
