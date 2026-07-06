import { useRef } from 'react'
import { PageContainer, ProTable } from '@ant-design/pro-components'
import { Tag } from 'antd'
import { fetchJobs } from '../api/services'
import ImportButton from '../components/ImportButton'

const IMPORT_FIELDS = [
  { key: 'jobs', label: '校招岗位分类及专业要求 (.xlsx/.xls/.csv)', accept: '.xlsx,.xls,.csv' },
]

export default function JobsPage() {
  const actionRef = useRef()

  const columns = [
    { title: '对外名称', dataIndex: 'public_name', fixed: 'left', width: 160, ellipsis: true },
    { title: '职位名称', dataIndex: 'position_name', width: 160, ellipsis: true, search: false },
    { title: '岗位类别', dataIndex: 'category', width: 120 },
    { title: '岗位族', dataIndex: 'job_family', width: 110, search: false },
    { title: '部门', dataIndex: 'department_name', width: 140, search: false },
    { title: '工作地点', dataIndex: 'location', width: 110, search: false },
    { title: '学历要求', dataIndex: 'education', width: 100, search: false },
    { title: 'HC', dataIndex: 'headcount', width: 70, search: false },
    {
      title: '对外发布',
      dataIndex: 'is_public',
      width: 90,
      search: false,
      render: (_, r) =>
        r.is_public ? <Tag color="green">是</Tag> : <Tag>否</Tag>,
    },
  ]

  return (
    <PageContainer title="岗位需求" content="校招岗位分类及专业要求，可导入维护。">
      <ProTable
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        scroll={{ x: 1200 }}
        search={{ labelWidth: 'auto' }}
        pagination={{ defaultPageSize: 10, showSizeChanger: true }}
        toolBarRender={() => [
          <ImportButton
            key="import"
            buttonText="导入岗位"
            title="导入岗位分类及专业要求"
            fields={IMPORT_FIELDS}
            onDone={() => actionRef.current?.reload()}
          />,
        ]}
        request={async (params) => {
          const { current, pageSize, public_name, category } = params
          try {
            const { data } = await fetchJobs({
              page: current,
              page_size: pageSize,
              public_name,
              category,
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
