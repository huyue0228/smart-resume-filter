import { useRef } from 'react'
import { PageContainer, ProTable } from '@ant-design/pro-components'
import { Tag } from 'antd'
import { fetchSchools } from '../api/services'
import ImportButton from '../components/ImportButton'
import {
  normalizeTableFilters,
  textColumnFilter,
  useResizableColumns,
} from '../components/DataTableControls'

const IMPORT_FIELDS = [
  { key: 'schools', label: '院校分类 (.xlsx/.xls/.csv)', accept: '.xlsx,.xls,.csv' },
]

export default function SchoolsPage() {
  const actionRef = useRef()

  const baseColumns = [
    {
      title: '学校',
      dataIndex: 'name',
      fixed: 'left',
      width: 220,
      ellipsis: true,
      ...textColumnFilter('筛选学校'),
    },
    {
      title: '平台标签',
      dataIndex: 'platform',
      width: 160,
      ...textColumnFilter('筛选平台标签'),
      render: (_, r) => (r.platform ? <Tag color="blue">{r.platform}</Tag> : '-'),
    },
  ]
  const { columns, components, scrollX } = useResizableColumns(baseColumns)

  return (
    <PageContainer title="院校清单" content="维护院校与院校标签，可导入更新。">
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
            buttonText="导入院校"
            title="导入院校分类"
            fields={IMPORT_FIELDS}
            onDone={() => actionRef.current?.reload()}
          />,
        ]}
        request={async (params, _sort, filters) => {
          const { current, pageSize } = params
          const tableFilters = normalizeTableFilters(filters, [
            'name',
            'platform',
          ])
          try {
            const { data } = await fetchSchools({
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
