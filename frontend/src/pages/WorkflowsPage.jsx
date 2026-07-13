import { PageContainer, ProTable } from '@ant-design/pro-components'
import { Tag } from 'antd'
import { fetchWorkflows } from '../api/services'
import {
  normalizeTableFilters,
  selectColumnFilter,
  textColumnFilter,
  useResizableColumns,
} from '../components/DataTableControls'

const STATUS_ENUM = {
  pending: { text: '待分配', status: 'Default', color: 'default' },
  in_progress: { text: '进行中', status: 'Processing', color: 'processing' },
  passed: { text: '已通过', status: 'Success', color: 'success' },
  archived: { text: '已归档', status: 'Error', color: 'error' },
}

const STRATEGY_TEXT = {
  rule: '规则',
  ai: 'AI',
  manual: '手动',
}

export default function WorkflowsPage({ archivedOnly = false }) {
  const title = archivedOnly ? '归档候选人' : '候选人工作流'
  const content = archivedOnly
    ? '查看已归档候选人的当前志愿、归档原因和最后处理时间。'
    : '查看候选人当前流程状态、当前有效志愿、分配策略和归档信息。'

  const baseColumns = [
    {
      title: '候选人',
      dataIndex: 'candidate_name',
      width: 130,
      fixed: 'left',
      ...textColumnFilter('筛选候选人'),
    },
    {
      title: '手机',
      dataIndex: 'phone',
      width: 130,
      search: false,
      ...textColumnFilter('筛选手机号'),
    },
    {
      title: '当前志愿',
      dataIndex: 'current_rank',
      width: 90,
      search: false,
      ...textColumnFilter('筛选志愿序号'),
      render: (_, record) => record.current_rank || '-',
    },
    {
      title: '应聘ID',
      dataIndex: 'current_apply_id',
      width: 120,
      search: false,
      ...textColumnFilter('筛选应聘ID'),
    },
    {
      title: '当前投递',
      dataIndex: 'current_position_name',
      ellipsis: true,
      ...textColumnFilter('筛选当前投递'),
    },
    {
      title: '策略',
      dataIndex: 'dispatch_strategy',
      width: 90,
      search: false,
      ...selectColumnFilter(
        Object.entries(STRATEGY_TEXT).map(([value, text]) => ({ value, text })),
      ),
      render: (value) => STRATEGY_TEXT[value] || value || '-',
    },
    !archivedOnly && {
      title: '流程状态',
      dataIndex: 'status',
      width: 110,
      valueType: 'select',
      valueEnum: STATUS_ENUM,
      ...selectColumnFilter(
        Object.entries(STATUS_ENUM).map(([value, item]) => ({ value, text: item.text })),
      ),
      render: (_, record) => {
        const item = STATUS_ENUM[record.status]
        return item ? <Tag color={item.color}>{item.text}</Tag> : record.status || '-'
      },
    },
    {
      title: '归档原因',
      dataIndex: 'archive_reason',
      ellipsis: true,
      ...textColumnFilter('筛选归档原因'),
      render: (_, record) => record.archive_detail || record.archive_reason || '-',
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      width: 180,
      search: false,
      valueType: 'dateTime',
    },
  ].filter(Boolean)
  const { columns, components, scrollX } = useResizableColumns(baseColumns)

  return (
    <PageContainer title={title} content={content}>
      <ProTable
        rowKey="id"
        columns={columns}
        components={components}
        scroll={{ x: scrollX }}
        search={false}
        pagination={{ defaultPageSize: 10, showSizeChanger: true }}
        request={async (params, _sort, filters) => {
          const { current, pageSize } = params
          const tableFilters = normalizeTableFilters(filters, [
            'candidate_name',
            'phone',
            'current_rank',
            'current_apply_id',
            'current_position_name',
            'dispatch_strategy',
            'status',
            'archive_reason',
          ])
          try {
            const { data } = await fetchWorkflows({
              page: current,
              page_size: pageSize,
              ...tableFilters,
              status: archivedOnly ? 'archived' : tableFilters.status,
            })
            return {
              data: data?.results || [],
              total: data?.count || 0,
              success: true,
            }
          } catch {
            return { data: [], total: 0, success: false }
          }
        }}
      />
    </PageContainer>
  )
}
