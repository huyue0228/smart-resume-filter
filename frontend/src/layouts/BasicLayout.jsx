import { useState } from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { ProLayout } from '@ant-design/pro-components'
import { Dropdown } from 'antd'
import {
  DatabaseOutlined,
  ImportOutlined,
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

const route = {
  path: '/',
  routes: [
    {
      path: '/data',
      name: '数据管理',
      icon: <DatabaseOutlined />,
      routes: [
        { path: '/import', name: '数据导入', icon: <ImportOutlined /> },
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
      routes: [
        { path: '/pipeline', name: '流水线运行', icon: <NodeIndexOutlined /> },
      ],
    },
    {
      path: '/assign',
      name: '简历分配',
      icon: <DeploymentUnitOutlined />,
      routes: [
        {
          path: '/allocations',
          name: '分配结果',
          icon: <DeploymentUnitOutlined />,
        },
      ],
    },
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

export default function BasicLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const [pathname, setPathname] = useState(location.pathname)

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
        title: '管理员',
        size: 'small',
        render: (_, avatar) => (
          <Dropdown
            menu={{
              items: [
                { key: 'profile', label: '个人信息' },
                { key: 'logout', label: '退出登录' },
              ],
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
