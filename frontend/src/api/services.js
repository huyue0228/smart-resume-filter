import client from './client'

// ---- Auth / RBAC ----
export function login(body) {
  return client.post('/auth/login/', body)
}
export function logout() {
  return client.post('/auth/logout/')
}
export function fetchMe() {
  return client.get('/me/')
}
export function fetchUsers(params) {
  return client.get('/users/', { params })
}
export function createUser(body) {
  return client.post('/users/', body)
}
export function updateUser(id, body) {
  return client.patch(`/users/${id}/`, body)
}
export function fetchRoles(params) {
  return client.get('/roles/', { params })
}
export function createRole(body) {
  return client.post('/roles/', body)
}
export function updateRole(id, body) {
  return client.patch(`/roles/${id}/`, body)
}
export function fetchPermissionTree() {
  return client.get('/permissions/')
}
export function fetchConfigs() {
  return client.get('/configs/')
}
export function updateConfig(key, value) {
  return client.patch(`/configs/${key}/`, { value })
}

// ---- Data import ----
// POST /api/import/  (multipart)
// fields: resume_list, jobs, schools, contacts, resume_package (all optional files)
//         + mode = 'incremental' | 'replace'
// returns { detail, counts: { candidates_created, candidates_updated,
//           resumes_created, resumes_updated } }
export function importData(formData) {
  return client.post('/import/', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}
// 撤销（单级）：GET 查状态，POST 执行
export function fetchUndoStatus() {
  return client.get('/import/undo/')
}
export function undoLastImport() {
  return client.post('/import/undo/')
}

// ---- Resumes ----
// GET /api/resumes/  DRF paginated { count, results: [...] }
export function fetchResumes(params) {
  return client.get('/resumes/', { params })
}

// ---- Generic list endpoints (placeholder pages / dropdowns) ----
export function fetchCandidates(params) {
  return client.get('/candidates/', { params })
}
export function fetchJobs(params) {
  return client.get('/jobs/', { params })
}
export function fetchSchools(params) {
  return client.get('/schools/', { params })
}
export function fetchDepartments(params) {
  return client.get('/departments/', { params })
}
export function fetchContacts(params) {
  return client.get('/contacts/', { params })
}

// ---- Pipeline ----
// POST /api/pipeline/run/  body { step, mode }
// returns { id, step, mode, status, message }
export function runPipeline(body) {
  return client.post('/pipeline/run/', body)
}
// GET /api/pipeline/runs/  paginated list of run records
export function fetchPipelineRuns(params) {
  return client.get('/pipeline/runs/', { params })
}

// ---- Workflow attempts ----
export function fetchAllocations(params) {
  return client.get('/workflow-attempts/', { params })
}
export function dispatchAllocation(id) {
  return client.post(`/workflow-attempts/${id}/dispatch/`)
}
export function confirmReviewAllocation(id) {
  return client.post(`/workflow-attempts/${id}/confirm-review/`)
}
export function bulkDispatchAllocations(body, params) {
  return client.post('/workflow-attempts/bulk-dispatch/', body, { params })
}
export function assignSubContact(id, body) {
  return client.post(`/workflow-attempts/${id}/assign-sub-contact/`, body)
}
export function submitAllocationFeedback(id, body) {
  return client.post(`/workflow-attempts/${id}/feedback/`, body)
}
export function exportAllocations(ids, params) {
  return client.get('/workflow-attempts/export/', {
    params: { ...(ids && ids.length ? { ids: ids.join(',') } : {}), ...params },
    responseType: 'blob',
  })
}
