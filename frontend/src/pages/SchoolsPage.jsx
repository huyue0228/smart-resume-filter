import { useRef } from 'react'
import { PageContainer, ProTable } from '@ant-design/pro-components'
import { Tag } from 'antd'
import { fetchSchools } from '../api/services'
import ImportButton from '../components/ImportButton'
import {
  normalizeTableFilters,
  selectColumnFilter,
  textColumnFilter,
  useResizableColumns,
} from '../components/DataTableControls'

const IMPORT_FIELDS = [
  { key: 'schools', label: '院校分类 (.xlsx/.xls/.csv)', accept: '.xlsx,.xls,.csv' },
]

const REGION_COLOR = { 南: 'geekblue', 北: 'volcano' }

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
    {
      title: '所在地（南/北）',
      dataIndex: 'region',
      width: 140,
      ...selectColumnFilter([
        { text: '南', value: '南' },
        { text: '北', value: '北' },
      ]),
      render: (_, r) =>
        r.region ? <Tag color={REGION_COLOR[r.region]}>{r.region}</Tag> : '-',
    },
  ]
  const { columns, components, scrollX } = useResizableColumns(baseColumns)

  return (
    <PageContainer title="院校清单" content="院校平台标签与南北所在地，可导入维护。">
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
            'region',
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
