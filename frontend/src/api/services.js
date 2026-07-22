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
export function deleteUser(id) {
  return client.delete(`/users/${id}/`)
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
export function fetchConfig(key) {
  return client.get(`/configs/${key}/`)
}
export function updateConfig(key, value) {
  return client.patch(`/configs/${key}/`, { value })
}
export function fetchAIConnection() {
  return client.get('/ai-connection/')
}
export function updateAIConnection(body) {
  return client.patch('/ai-connection/', body)
}
export function testAIConnection() {
  return client.post('/ai-connection/test/')
}
export function fetchAIModels(body) {
  return client.post('/ai-connection/models/', body)
}
export function fetchAIConnectionSettings() {
  return client.get('/ai-connection/settings/')
}
export function updateAIConnectionSetting(key, value) {
  return client.patch(`/ai-connection/settings/${key}/`, { value })
}
export function fetchAllocationMode() {
  return client.get('/allocation-mode/')
}
export function fetchSchoolTagRules(params) {
  return client.get('/school-tag-rules/', { params })
}
export function createSchoolTagRule(body) {
  return client.post('/school-tag-rules/', body)
}
export function updateSchoolTagRule(id, body) {
  return client.patch(`/school-tag-rules/${id}/`, body)
}
export function deleteSchoolTagRule(id) {
  return client.delete(`/school-tag-rules/${id}/`)
}
export function fetchSchoolTags(params) {
  return client.get('/school-tags/', { params })
}
export function createSchoolTag(body) {
  return client.post('/school-tags/', body)
}
export function updateSchoolTag(id, body) {
  return client.patch(`/school-tags/${id}/`, body)
}
export function deleteSchoolTag(id) {
  return client.delete(`/school-tags/${id}/`)
}
export function fetchMajorCategories(params) {
  return client.get('/major-categories/', { params })
}
export function createMajorCategory(body) {
  return client.post('/major-categories/', body)
}
export function updateMajorCategory(id, body) {
  return client.patch(`/major-categories/${id}/`, body)
}
export function deleteMajorCategory(id) {
  return client.delete(`/major-categories/${id}/`)
}
export function fetchMajorAliases(params) {
  return client.get('/major-aliases/', { params })
}
export function createMajorAlias(body) {
  return client.post('/major-aliases/', body)
}
export function updateMajorAlias(id, body) {
  return client.patch(`/major-aliases/${id}/`, body)
}
export function deleteMajorAlias(id) {
  return client.delete(`/major-aliases/${id}/`)
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
export function previewResume(id) {
  return client.get(`/resumes/${id}/preview/`, { responseType: 'blob' })
}
export function previewAllocationResume(id) {
  return client.get(`/workflow-attempts/${id}/resume-preview/`, { responseType: 'blob' })
}
export function manualAssignResume(id, body) {
  return client.post(`/resumes/${id}/manual-assign/`, body)
}
export function exportResumeResultReport(params) {
  return client.get('/resumes/result-report/', { params, responseType: 'blob' })
}

// ---- Generic list endpoints (placeholder pages / dropdowns) ----
export function fetchCandidates(params) {
  return client.get('/candidates/', { params })
}
export function fetchCandidateFilterOptions() {
  return client.get('/candidates/filter-options/')
}
export function fetchCandidateExportFields() {
  return client.get('/candidates/export-fields/')
}
export function deleteCandidate(id) {
  return client.delete(`/candidates/${id}/`)
}
export function exportCandidates(ids, params) {
  return client.get('/candidates/export/', {
    params: { ...(ids && ids.length ? { ids: ids.join(',') } : {}), ...params },
    responseType: 'blob',
  })
}
export function fetchJobs(params) {
  return client.get('/jobs/', { params })
}
export function fetchJobFilterOptions() {
  return client.get('/jobs/filter-options/')
}
export function createJob(body) {
  return client.post('/jobs/', body)
}
export function updateJob(id, body) {
  return client.patch(`/jobs/${id}/`, body)
}
export function deleteJob(id) {
  return client.delete(`/jobs/${id}/`)
}
export function fetchSchools(params) {
  return client.get('/schools/', { params })
}
export function fetchSchoolFilterOptions() {
  return client.get('/schools/filter-options/')
}
export function createSchool(body) {
  return client.post('/schools/', body)
}
export function updateSchool(id, body) {
  return client.patch(`/schools/${id}/`, body)
}
export function fetchDepartments(params) {
  return client.get('/departments/', { params })
}
export function fetchContacts(params) {
  return client.get('/contacts/', { params })
}
export function fetchContactFilterOptions() {
  return client.get('/contacts/filter-options/')
}
export function createContact(body) {
  return client.post('/contacts/', body)
}
export function updateContact(id, body) {
  return client.patch(`/contacts/${id}/`, body)
}
export function deleteContact(id) {
  return client.delete(`/contacts/${id}/`)
}

// ---- Pipeline ----
// POST /api/pipeline/run/  body { step, mode, scope }; mode is selected per run
// returns { id, step, mode, status, message }
export function runPipeline(body) {
  return client.post('/pipeline/run/', body)
}
// GET /api/pipeline/runs/  paginated list of run records
export function fetchPipelineRuns(params) {
  return client.get('/pipeline/runs/', { params })
}
export function fetchPipelineRun(id) {
  return client.get(`/pipeline/runs/${id}/`)
}
export function cancelPipelineRun(id) {
  return client.post(`/pipeline/runs/${id}/cancel/`)
}

// ---- Recruitment analytics ----
export function fetchRecruitmentOverview(params) {
  return client.get('/analytics/recruitment-overview/', { params })
}

// ---- Workflow attempts ----
export function dispatchAllocation(id) {
  return client.post(`/workflow-attempts/${id}/dispatch/`)
}
export function confirmReviewAllocation(id) {
  return client.post(`/workflow-attempts/${id}/confirm-review/`)
}
export function cancelAllocation(id, body) {
  return client.post(`/workflow-attempts/${id}/cancel/`, body)
}
export function cancelReviewAllocation(id, body) {
  return client.post(`/workflow-attempts/${id}/cancel-review/`, body)
}
export function transferAllocationToManual(id, body) {
  return client.post(`/workflow-attempts/${id}/transfer-to-manual/`, body)
}
export function bulkDispatchCandidates(body) {
  return client.post('/candidates/bulk-dispatch/', body)
}
export function assignSubContact(id, body) {
  return client.post(`/workflow-attempts/${id}/assign-sub-contact/`, body)
}
export function fetchEligibleSubContacts(id) {
  return client.get(`/workflow-attempts/${id}/eligible-sub-contacts/`)
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

// ---- AI decisions ----
export function fetchAgentDecisions(params) {
  return client.get('/agent-decisions/', { params })
}
export function retryAgentDecision(id) {
  return client.post(`/agent-decisions/${id}/retry/`)
}
