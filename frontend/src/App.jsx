import { Routes, Route, Navigate } from 'react-router-dom'
import BasicLayout from './layouts/BasicLayout'
import ImportPage from './pages/ImportPage'
import ResumesPage from './pages/ResumesPage'
import PipelinePage from './pages/PipelinePage'
import AllocationsPage from './pages/AllocationsPage'
import JobsPage from './pages/JobsPage'
import SchoolsPage from './pages/SchoolsPage'
import DepartmentsPage from './pages/DepartmentsPage'
import ConfigPage from './pages/ConfigPage'
import UsersPage from './pages/UsersPage'

export default function App() {
  return (
    <Routes>
      <Route element={<BasicLayout />}>
        <Route index element={<Navigate to="/import" replace />} />
        <Route path="/import" element={<ImportPage />} />
        <Route path="/resumes" element={<ResumesPage />} />
        <Route path="/jobs" element={<JobsPage />} />
        <Route path="/schools" element={<SchoolsPage />} />
        <Route path="/departments" element={<DepartmentsPage />} />
        <Route path="/pipeline" element={<PipelinePage />} />
        <Route path="/allocations" element={<AllocationsPage />} />
        <Route path="/config" element={<ConfigPage />} />
        <Route path="/users" element={<UsersPage />} />
        <Route path="*" element={<Navigate to="/import" replace />} />
      </Route>
    </Routes>
  )
}
