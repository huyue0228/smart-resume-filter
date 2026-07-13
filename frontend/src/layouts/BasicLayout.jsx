import { useState } from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { ProLayout } from '@ant-design/pro-components'
import { Dropdown, Tag } from 'antd'
import {
  DatabaseOutlined,
  ProfileOutlined,
  ApartmentOutlined,
  BankOutlined,
  TeamOutlined,
  DeploymentUnitOutlined,
  SettingOutlined,
  ControlOutlined,
  UserOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons'
import { useRole, ROLES } from '../contexts/RoleContext'
import ProcessingTaskCenter from '../components/ProcessingTaskCenter'

const ROOT_MENU_KEYS = ['/data', '/allocations', '/system']

function pathMatchesGroup(pathname, route) {
  if (!route.routes) return false
  return route.routes.some((child) => child.path === pathname)
}

function defaultOpenKeys(pathname) {
  return allRoute.routes
    .filter((route) => ROOT_MENU_KEYS.includes(route.path) && pathMatchesGroup(pathname, route))
    .map((route) => route.path)
}

// 简历分配按来源拆为两个子页；两页复用同一分配尝试操作台和相同处置能力。
const assignGroup = {
  path: '/allocations',
  name: '简历分配',
  icon: <DeploymentUnitOutlined />,
  routes: [
    { path: '/allocations/rule', name: '规则分配' },
    { path: '/allocations/ai', name: 'AI分配' },
  ],
}

const allRoute = {
  path: '/',
  routes: [
    {
      path: '/data',
      name: '数据管理',
      icon: <DatabaseOutlined />,
      routes: [
        { path: '/resumes', name: '简历库', icon: <ProfileOutlined /> },
        { path: '/jobs', name: '岗位需求', icon: <ApartmentOutlined /> },
        { path: '/schools', name: '院校清单', icon: <BankOutlined /> },
        { path: '/departments', name: '部门接口人', icon: <TeamOutlined /> },
      ],
    },
    assignGroup,
    {
      path: '/system',
      name: '系统设置',
      icon: <SettingOutlined />,
      routes: [
        { path: '/config', name: '配置项', icon: <ControlOutlined /> },
        { path: '/users', name: '用户权限', icon: <SafetyCertificateOutlined /> },
      ],
    },
  ],
}

function filterRoutesByPermission(routes, hasPermission) {
  const permissionMap = {
    '/resumes': 'resume.view',
    '/jobs': 'job.view',
    '/schools': 'school.view',
    '/departments': 'department.view',
    '/allocations/rule': ['attempt.view_all', 'attempt.view_received', 'attempt.view_assigned'],
    '/allocations/ai': 'attempt.view_all',
    '/config': 'settings.manage_config',
    '/users': 'settings.manage_permissions',
  }
  const keepRoute = (route) => {
    const needed = permissionMap[route.path]
    if (!needed) return true
    const codes = Array.isArray(needed) ? needed : [needed]
    return codes.some((code) => hasPermission(code))
  }
  const next = routes
    .map((route) => {
      const children = route.routes
        ? filterRoutesByPermission(route.routes, hasPermission)
        : undefined
      return { ...route, routes: children }
    })
    .filter((route) => {
      if (route.routes) return route.routes.length > 0
      return keepRoute(route)
    })
  return next
}

export default function BasicLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const { role, roles, user, logout, hasPermission, isContact } = useRole()
  const [pathname, setPathname] = useState(location.pathname)
  const [openKeys, setOpenKeys] = useState(() => defaultOpenKeys(location.pathname))

  const handleLogout = async () => {
    await logout()
    navigate('/login', { replace: true })
  }

  const route = {
    ...allRoute,
    routes: filterRoutesByPermission(allRoute.routes, hasPermission),
  }

  return (
    <ProLayout
      title="智能简历筛选系统"
      logo={false}
      layout="mix"
      fixedHeader
      fixSiderbar
      route={route}
      location={{ pathname }}
      onPageChange={(loc) => setPathname(loc?.pathname || location.pathname)}
      menuProps={{
        openKeys,
        onOpenChange: setOpenKeys,
      }}
      menuItemRender={(item, dom) => (
        <div
          onClick={() => {
            setPathname(item.path)
            navigate(item.path)
          }}
        >
          {dom}
        </div>
      )}
      actionsRender={() => (hasPermission('pipeline.view') ? [<ProcessingTaskCenter key="processing-tasks" />] : [])}
      avatarProps={{
        icon: <UserOutlined />,
        title: (
          <span>
            {user?.username || ROLES[role]?.label}
            <Tag color={isContact ? 'orange' : 'blue'} style={{ marginLeft: 8 }}>
              {roles?.[0] || ROLES[role]?.label || '用户'}
            </Tag>
          </span>
        ),
        size: 'small',
        render: (_, avatar) => (
          <Dropdown
            menu={{
              items: [
                {
                  key: 'profile',
                  label: `${user?.first_name || user?.username || '当前用户'}`,
                  disabled: true,
                },
                { type: 'divider' },
                { key: 'logout', label: '退出登录' },
              ],
              onClick: ({ key }) => {
                if (key === 'logout') handleLogout()
              },
            }}
          >
            {avatar}
          </Dropdown>
        ),
      }}
    >
      <Outlet />
    </ProLayout>
  )
}
