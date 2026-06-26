import { Routes, Route, Navigate } from 'react-router-dom'
import { RoleProvider, useRole } from './contexts/RoleContext'
import { ModeProvider } from './contexts/ModeContext'
import BasicLayout from './layouts/BasicLayout'
import ResumesPage from './pages/ResumesPage'
import AllocationsPage from './pages/AllocationsPage'
import JobsPage from './pages/JobsPage'
import SchoolsPage from './pages/SchoolsPage'
import DepartmentsPage from './pages/DepartmentsPage'
import ConfigPage from './pages/ConfigPage'
import UsersPage from './pages/UsersPage'

function AppRoutes() {
  const { isContact } = useRole()

  // 接口人：仅可访问「分配结果」，其余路由一律重定向过去
  if (isContact) {
    return (
      <Routes>
        <Route element={<BasicLayout />}>
          <Route index element={<Navigate to="/allocations" replace />} />
          <Route path="/allocations" element={<AllocationsPage />} />
          <Route path="*" element={<Navigate to="/allocations" replace />} />
        </Route>
      </Routes>
    )
  }

  return (
    <Routes>
      <Route element={<BasicLayout />}>
        <Route index element={<Navigate to="/resumes" replace />} />
        <Route path="/resumes" element={<ResumesPage />} />
        <Route path="/jobs" element={<JobsPage />} />
        <Route path="/schools" element={<SchoolsPage />} />
        <Route path="/departments" element={<DepartmentsPage />} />
        <Route path="/allocations" element={<AllocationsPage />} />
        <Route path="/config" element={<ConfigPage />} />
        <Route path="/users" element={<UsersPage />} />
        <Route path="*" element={<Navigate to="/resumes" replace />} />
      </Route>
    </Routes>
  )
}

export default function App() {
  return (
    <RoleProvider>
      <ModeProvider>
        <AppRoutes />
      </ModeProvider>
    </RoleProvider>
  )
}
