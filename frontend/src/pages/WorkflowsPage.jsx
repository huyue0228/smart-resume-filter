import { PageContainer, ProTable } from '@ant-design/pro-components'
import { Tag } from 'antd'
import { fetchWorkflows } from '../api/services'

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

  const columns = [
    { title: '候选人', dataIndex: 'candidate_name', width: 130, fixed: 'left' },
    { title: '手机', dataIndex: 'phone', width: 130, search: false },
    {
      title: '当前志愿',
      dataIndex: 'current_rank',
      width: 90,
      search: false,
      render: (_, record) => record.current_rank || '-',
    },
    { title: '应聘ID', dataIndex: 'current_apply_id', width: 120, search: false },
    {
      title: '当前投递',
      dataIndex: 'current_position_name',
      ellipsis: true,
    },
    {
      title: '策略',
      dataIndex: 'dispatch_strategy',
      width: 90,
      search: false,
      render: (value) => STRATEGY_TEXT[value] || value || '-',
    },
    !archivedOnly && {
      title: '流程状态',
      dataIndex: 'status',
      width: 110,
      valueType: 'select',
      valueEnum: STATUS_ENUM,
      render: (_, record) => {
        const item = STATUS_ENUM[record.status]
        return item ? <Tag color={item.color}>{item.text}</Tag> : record.status || '-'
      },
    },
    {
      title: '归档原因',
      dataIndex: 'archive_reason',
      ellipsis: true,
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

  return (
    <PageContainer title={title} content={content}>
      <ProTable
        rowKey="id"
        columns={columns}
        scroll={{ x: 1100 }}
        search={{ labelWidth: 'auto' }}
        pagination={{ defaultPageSize: 10, showSizeChanger: true }}
        request={async (params) => {
          const {
            current,
            pageSize,
            status,
            candidate_name: search,
            current_position_name: currentPositionName,
            archive_reason: archiveReason,
          } = params
          try {
            const { data } = await fetchWorkflows({
              page: current,
              page_size: pageSize,
              status: archivedOnly ? 'archived' : status,
              search,
              current_position_name: currentPositionName,
              archive_reason: archiveReason,
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
