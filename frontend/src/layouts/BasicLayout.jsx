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
  NodeIndexOutlined,
  DeploymentUnitOutlined,
  SettingOutlined,
  ControlOutlined,
  UserOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons'
import { useRole, ROLES } from '../contexts/RoleContext'

// 简历分配分组（接口人唯一可见）
const assignGroup = {
  path: '/assign',
  name: '简历分配',
  icon: <DeploymentUnitOutlined />,
  routes: [{ path: '/allocations', name: '分配结果', icon: <DeploymentUnitOutlined /> }],
}

// HR / 管理员完整菜单。导入入口已并入各数据页（简历库 / 岗位 / 院校 / 接口人），不再单设导入页。
const fullRoute = {
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
    {
      path: '/process',
      name: '处理流水线',
      icon: <NodeIndexOutlined />,
      routes: [{ path: '/pipeline', name: '流水线运行', icon: <NodeIndexOutlined /> }],
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

// 接口人仅见分配结果
const contactRoute = { path: '/', routes: [assignGroup] }

export default function BasicLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const { role, setRole, isContact } = useRole()
  const [pathname, setPathname] = useState(location.pathname)

  const switchRole = (next) => {
    setRole(next)
    setPathname(next === 'contact' ? '/allocations' : '/resumes')
    navigate(next === 'contact' ? '/allocations' : '/resumes')
  }

  return (
    <ProLayout
      title="智能简历筛选系统"
      logo={false}
      layout="mix"
      fixedHeader
      fixSiderbar
      route={isContact ? contactRoute : fullRoute}
      location={{ pathname }}
      onPageChange={(loc) => setPathname(loc?.pathname || location.pathname)}
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
      avatarProps={{
        icon: <UserOutlined />,
        title: (
          <span>
            {ROLES[role]?.label}
            <Tag color={isContact ? 'orange' : 'blue'} style={{ marginLeft: 8 }}>
              演示身份
            </Tag>
          </span>
        ),
        size: 'small',
        render: (_, avatar) => (
          <Dropdown
            menu={{
              selectedKeys: [role],
              items: [
                { key: 'hr', label: '切换为 HR' },
                { key: 'contact', label: '切换为 接口人' },
                { type: 'divider' },
                { key: 'profile', label: '个人信息', disabled: true },
              ],
              onClick: ({ key }) => {
                if (key === 'hr' || key === 'contact') switchRole(key)
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
