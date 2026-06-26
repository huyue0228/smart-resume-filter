import { useRef } from 'react'
import { PageContainer, ProTable } from '@ant-design/pro-components'
import { Tag } from 'antd'
import { fetchContacts } from '../api/services'
import ImportButton from '../components/ImportButton'

const IMPORT_FIELDS = [
  { key: 'contacts', label: '部门接口人信息 (.xlsx)', accept: '.xlsx,.xls' },
]

export default function DepartmentsPage() {
  const actionRef = useRef()

  const columns = [
    { title: '姓名', dataIndex: 'name', fixed: 'left', width: 120 },
    { title: '工号', dataIndex: 'employee_no', width: 140 },
    { title: '所属部门', dataIndex: 'department_name', ellipsis: true, search: false },
    {
      title: '招聘主体',
      dataIndex: 'entity',
      width: 140,
      search: false,
      render: (_, r) => (r.entity ? <Tag color="blue">{r.entity}</Tag> : '-'),
    },
  ]

  return (
    <PageContainer
      title="部门接口人"
      content="二层部门接口人名单（姓名 / 工号 / 所属部门），简历下发的接收人。可导入维护。"
    >
      <ProTable
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        search={{ labelWidth: 'auto' }}
        pagination={{ defaultPageSize: 10, showSizeChanger: true }}
        toolBarRender={() => [
          <ImportButton
            key="import"
            buttonText="导入接口人"
            title="导入部门接口人信息"
            fields={IMPORT_FIELDS}
            onDone={() => actionRef.current?.reload()}
          />,
        ]}
        request={async (params) => {
          const { current, pageSize, name, employee_no } = params
          try {
            const { data } = await fetchContacts({
              page: current,
              page_size: pageSize,
              name,
              employee_no,
            })
            return { data: data?.results || [], total: data?.count || 0, success: true }
          } catch {
            return { data: [], total: 0, success: false }
          }
        }}
      />
    </PageContainer>
  )
}
