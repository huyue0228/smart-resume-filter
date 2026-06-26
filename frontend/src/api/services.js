import client from './client'

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

// ---- Allocations ----
// GET /api/allocations/  paginated
export function fetchAllocations(params) {
  return client.get('/allocations/', { params })
}
// POST /api/allocations/{id}/dispatch/  returns { detail, status }
export function dispatchAllocation(id) {
  return client.post(`/allocations/${id}/dispatch/`)
}
// GET /api/allocations/export/?ids=1,2,3  -> zip blob（不传 ids 则导出当前筛选全部）
export function exportAllocations(ids, params) {
  return client.get('/allocations/export/', {
    params: { ...(ids && ids.length ? { ids: ids.join(',') } : {}), ...params },
    responseType: 'blob',
  })
}
