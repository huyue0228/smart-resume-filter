export const DEFAULT_AUTHENTICATED_PATH = '/resumes'

export const ROUTE_PERMISSIONS = {
  '/resumes': ['resume.view', 'attempt.view_received', 'attempt.view_assigned'],
  '/jobs': ['job.view'],
  '/schools': ['school.view'],
  '/departments': ['department.view'],
  '/config': ['settings.manage_config'],
  '/ai-connection': ['settings.manage_ai_connection'],
  '/users': ['settings.manage_permissions'],
}

export function canAccessRoute(path, hasPermission) {
  const permissions = ROUTE_PERMISSIONS[path]
  return !permissions || permissions.some((code) => hasPermission(code))
}
