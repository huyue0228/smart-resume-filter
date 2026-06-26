import { useRef } from 'react'
import { PageContainer, ProTable } from '@ant-design/pro-components'
import { Tag } from 'antd'
import { fetchDepartments } from '../api/services'
import ImportButton from '../components/ImportButton'

const IMPORT_FIELDS = [
  { key: 'contacts', label: '部门接口人信息 (.xlsx)', accept: '.xlsx,.xls' },
]

export default function DepartmentsPage() {
  const actionRef = useRef()

  const columns = [
    { title: '部门', dataIndex: 'name', fixed: 'left', width: 220, ellipsis: true },
    {
      title: '层级',
      dataIndex: 'level',
      width: 100,
      search: false,
      render: (_, r) =>
        r.level === 1 ? <Tag color="purple">一层</Tag> : <Tag>二层</Tag>,
    },
    { title: '招聘主体', dataIndex: 'entity', width: 140, search: false },
  ]

  return (
    <PageContainer
      title="部门接口人"
      content="部门层级与接口人信息，可导入维护（导入后用于简历下发）。"
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
          const { current, pageSize, name } = params
          try {
            const { data } = await fetchDepartments({
              page: current,
              page_size: pageSize,
              name,
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
