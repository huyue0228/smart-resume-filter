import { useRef } from 'react'
import { PageContainer, ProTable } from '@ant-design/pro-components'
import { Tag } from 'antd'
import { fetchJobs } from '../api/services'
import ImportButton from '../components/ImportButton'
import {
  normalizeTableFilters,
  selectColumnFilter,
  textColumnFilter,
  useResizableColumns,
} from '../components/DataTableControls'

const IMPORT_FIELDS = [
  { key: 'jobs', label: '校招岗位分类及专业要求 (.xlsx/.xls/.csv)', accept: '.xlsx,.xls,.csv' },
]

export default function JobsPage() {
  const actionRef = useRef()

  const baseColumns = [
    { title: '招聘主体', dataIndex: 'entity', width: 100, ...textColumnFilter('筛选主体') },
    {
      title: '对外名称',
      dataIndex: 'public_name',
      fixed: 'left',
      width: 160,
      ellipsis: true,
      ...textColumnFilter('筛选对外名称'),
    },
    {
      title: '职位名称',
      dataIndex: 'position_name',
      width: 160,
      ellipsis: true,
      ...textColumnFilter('筛选职位名称'),
    },
    { title: '岗位类别', dataIndex: 'category', width: 120, ...textColumnFilter('筛选类别') },
    { title: '岗位族', dataIndex: 'job_family', width: 110, ...textColumnFilter('筛选岗位族') },
    { title: '部门', dataIndex: 'department_name', width: 140, ...textColumnFilter('筛选部门') },
    { title: '工作地点', dataIndex: 'location', width: 110, ...textColumnFilter('筛选地点') },
    { title: '学历要求', dataIndex: 'education', width: 100, ...textColumnFilter('筛选学历') },
    { title: 'HC', dataIndex: 'headcount', width: 70, ...textColumnFilter('筛选HC') },
    {
      title: '对外发布',
      dataIndex: 'is_public',
      width: 90,
      ...selectColumnFilter([
        { text: '是', value: 'true' },
        { text: '否', value: 'false' },
      ]),
      render: (_, r) =>
        r.is_public ? <Tag color="green">是</Tag> : <Tag>否</Tag>,
    },
  ]
  const { columns, components, scrollX } = useResizableColumns(baseColumns)

  return (
    <PageContainer title="岗位需求" content="校招岗位分类及专业要求，可导入维护。">
      <ProTable
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        components={components}
        scroll={{ x: scrollX }}
        search={false}
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
        request={async (params, _sort, filters) => {
          const {
            current,
            pageSize,
          } = params
          const tableFilters = normalizeTableFilters(filters, [
            'entity',
            'public_name',
            'position_name',
            'category',
            'job_family',
            'department_name',
            'location',
            'education',
            'headcount',
            'is_public',
          ])
          try {
            const { data } = await fetchJobs({
              page: current,
              page_size: pageSize,
              ...tableFilters,
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
