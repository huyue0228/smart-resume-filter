import { useEffect, useRef, useState } from 'react'
import { PageContainer } from '@ant-design/pro-components'
import { message, Popconfirm, Space, Switch, Tag } from 'antd'
import {
  deleteContact,
  fetchConfig,
  fetchContactFilterOptions,
  fetchContacts,
  updateConfig,
} from '../api/services'
import ImportButton from '../components/ImportButton'
import SmartDataTable from '../components/SmartDataTable'
import { useRole } from '../contexts/roleState'

const IMPORT_FIELDS = [
  { key: 'contacts', label: '部门接口人信息 (.xlsx/.xls/.csv)', accept: '.xlsx,.xls,.csv' },
]

export default function DepartmentsPage() {
  const actionRef = useRef()
  const role = useRole()
  const canManageContacts = Boolean(role?.hasPermission?.('department.manage'))
  const [welinkEnabled, setWelinkEnabled] = useState(false)
  const [welinkLoading, setWelinkLoading] = useState(false)

  useEffect(() => {
    if (!canManageContacts) return
    let active = true
    setWelinkLoading(true)
    fetchConfig('welink_enabled')
      .then(({ data }) => {
        if (active) setWelinkEnabled(Boolean(data?.value))
      })
      .catch(() => {
        if (active) setWelinkEnabled(false)
      })
      .finally(() => {
        if (active) setWelinkLoading(false)
      })
    return () => {
      active = false
    }
  }, [canManageContacts])

  const handleWelinkChange = async (checked) => {
    setWelinkLoading(true)
    try {
      const { data } = await updateConfig('welink_enabled', checked)
      setWelinkEnabled(Boolean(data?.value))
      message.success(checked ? '已开启 WeLink 通知' : '已关闭 WeLink 通知')
    } finally {
      setWelinkLoading(false)
    }
  }

  const handleDelete = async (record) => {
    try {
      await deleteContact(record.id)
      message.success('已删除')
      actionRef.current?.reload()
      actionRef.current?.reloadOptions()
    } catch (error) {
      message.error(error?.response?.data?.detail || '删除失败')
    }
  }

  const baseColumns = [
    {
      title: '姓名',
      dataIndex: 'name',
      fixed: 'left',
      width: 120,
      filter: { type: 'text', param: 'name', pinyin: true, placeholder: '筛选姓名/拼音' },
    },
    {
      title: '工号',
      dataIndex: 'employee_no',
      width: 140,
      filter: { type: 'text', param: 'employee_no', placeholder: '筛选工号' },
    },
    {
      title: '所属部门',
      dataIndex: 'department_name',
      width: 160,
      ellipsis: true,
      filter: { type: 'select', param: 'department_in', multiple: true, options: 'department' },
    },
    {
      title: '部门层级',
      dataIndex: 'department_level',
      width: 100,
      filter: { type: 'select', param: 'department_level', options: [
        { label: '二级部门', value: '2' },
        { label: '三级部门', value: '3' },
      ] },
      render: (value) => (value === 3 ? '三级部门' : value === 2 ? '二级部门' : '-'),
    },
    {
      title: '可转派',
      dataIndex: 'can_delegate',
      width: 90,
      filter: { type: 'select', param: 'can_delegate', options: [
        { label: '是', value: 'true' },
        { label: '否', value: 'false' },
      ] },
      render: (_, record) =>
        record.contact_level === 'secondary' && record.can_delegate ? (
          <Tag color="green">是</Tag>
        ) : (
          '-'
        ),
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      width: 90,
      filter: { type: 'select', param: 'is_active', options: [
        { label: '启用', value: 'true' },
        { label: '停用', value: 'false' },
      ] },
      render: (value) =>
        value ? <Tag color="green">启用</Tag> : <Tag color="default">停用</Tag>,
    },
    {
      title: '招聘主体',
      dataIndex: 'entity',
      width: 140,
      filter: { type: 'text', param: 'entity', placeholder: '筛选主体' },
      render: (_, r) => (r.entity ? <Tag color="blue">{r.entity}</Tag> : '-'),
    },
    {
      title: '操作',
      valueType: 'option',
      fixed: 'right',
      width: 90,
      render: (_, record) => (
        <Space>
          <Popconfirm
            title="删除接口人"
            description="将删除该接口人及绑定用户，历史分配记录仅保留快照。"
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
            onConfirm={() => handleDelete(record)}
          >
            <a style={{ color: '#cf1322' }}>删除</a>
          </Popconfirm>
        </Space>
      ),
    },
  ]
  return (
    <PageContainer
      title="部门接口人"
      content="二级/三级部门接口人名单，可导入维护；二级接口人负责转派，三级接口人负责反馈。"
    >
      {canManageContacts && (
        <div
          style={{
            alignItems: 'center',
            background: '#fff',
            border: '1px solid #f0f0f0',
            borderRadius: 8,
            display: 'flex',
            justifyContent: 'space-between',
            marginBottom: 16,
            padding: '14px 16px',
          }}
        >
          <div>
            <div style={{ fontWeight: 600 }}>WeLink 通知</div>
            <div style={{ color: '#8c8c8c', marginTop: 4 }}>
              开启后，HR 下发简历时向对应二级接口人发送 WeLink 通知。
            </div>
          </div>
          <Switch
            aria-label="WeLink 通知"
            checked={welinkEnabled}
            loading={welinkLoading}
            onChange={handleWelinkChange}
          />
        </div>
      )}
      <SmartDataTable
        tableId="contacts"
        stickyPagination
        actionRef={actionRef}
        rowKey="id"
        columns={baseColumns}
        request={fetchContacts}
        filterOptionsRequest={fetchContactFilterOptions}
        toolBarRender={() => [
          <ImportButton
            key="import"
            buttonText="导入接口人"
            title="导入部门接口人信息"
            fields={IMPORT_FIELDS}
            onDone={() => {
              actionRef.current?.reload()
              actionRef.current?.reloadOptions()
            }}
          />,
        ]}
      />
    </PageContainer>
  )
}
