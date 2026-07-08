import { useRef } from 'react'
import { PageContainer, ProTable } from '@ant-design/pro-components'
import { Tag } from 'antd'
import { fetchContacts } from '../api/services'
import ImportButton from '../components/ImportButton'
import {
  normalizeTableFilters,
  selectColumnFilter,
  textColumnFilter,
  useResizableColumns,
} from '../components/DataTableControls'

const IMPORT_FIELDS = [
  { key: 'contacts', label: '部门接口人信息 (.xlsx/.xls/.csv)', accept: '.xlsx,.xls,.csv' },
]

export default function DepartmentsPage() {
  const actionRef = useRef()

  const baseColumns = [
    { title: '姓名', dataIndex: 'name', fixed: 'left', width: 120, ...textColumnFilter('筛选姓名') },
    { title: '工号', dataIndex: 'employee_no', width: 140, ...textColumnFilter('筛选工号') },
    {
      title: '所属部门',
      dataIndex: 'department_name',
      width: 160,
      ellipsis: true,
      ...textColumnFilter('筛选部门'),
    },
    {
      title: '部门层级',
      dataIndex: 'department_level',
      width: 100,
      ...selectColumnFilter([
        { text: '二级部门', value: '2' },
        { text: '三级部门', value: '3' },
      ]),
      render: (value) => (value === 3 ? '三级部门' : value === 2 ? '二级部门' : '-'),
    },
    {
      title: '接口人层级',
      dataIndex: 'contact_level',
      width: 120,
      ...selectColumnFilter([
        { text: '二级接口人', value: 'secondary' },
        { text: '三级接口人', value: 'tertiary' },
      ]),
    },
    {
      title: '可转派',
      dataIndex: 'can_delegate',
      width: 90,
      ...selectColumnFilter([
        { text: '是', value: 'true' },
        { text: '否', value: 'false' },
      ]),
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
      ...selectColumnFilter([
        { text: '启用', value: 'true' },
        { text: '停用', value: 'false' },
      ]),
      render: (value) =>
        value ? <Tag color="green">启用</Tag> : <Tag color="default">停用</Tag>,
    },
    {
      title: '招聘主体',
      dataIndex: 'entity',
      width: 140,
      ...textColumnFilter('筛选主体'),
      render: (_, r) => (r.entity ? <Tag color="blue">{r.entity}</Tag> : '-'),
    },
  ]
  const { columns, components, scrollX } = useResizableColumns(baseColumns)

  return (
    <PageContainer
      title="部门接口人"
      content="二级/三级部门接口人名单，可导入维护；二级接口人负责转派，三级接口人负责反馈。"
    >
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
            buttonText="导入接口人"
            title="导入部门接口人信息"
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
            'name',
            'employee_no',
            'department_name',
            'department_level',
            'contact_level',
            'can_delegate',
            'is_active',
            'entity',
          ])
          try {
            const { data } = await fetchContacts({
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
