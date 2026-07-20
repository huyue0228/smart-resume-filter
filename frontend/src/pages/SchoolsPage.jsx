import { useRef } from 'react'
import { PageContainer } from '@ant-design/pro-components'
import { fetchSchoolFilterOptions, fetchSchools } from '../api/services'
import ImportButton from '../components/ImportButton'
import SchoolTagBadge from '../components/SchoolTagBadge'
import SmartDataTable from '../components/SmartDataTable'

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
      filter: { type: 'text', param: 'name', pinyin: true, placeholder: '筛选学校/拼音' },
    },
    {
      title: '平台标签',
      dataIndex: 'platform',
      width: 160,
      filter: { type: 'select', param: 'platform_in', multiple: true, options: 'platform' },
      render: (_, r) => (r.platform ? <SchoolTagBadge value={r.platform} /> : '-'),
    },
  ]
  return (
    <PageContainer title="院校清单" content="维护院校与院校标签，可导入更新。">
      <SmartDataTable
        tableId="schools"
        stickyPagination
        actionRef={actionRef}
        rowKey="id"
        columns={baseColumns}
        request={fetchSchools}
        filterOptionsRequest={fetchSchoolFilterOptions}
        toolBarRender={() => [
          <ImportButton
            key="import"
            buttonText="导入院校"
            title="导入院校分类"
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
