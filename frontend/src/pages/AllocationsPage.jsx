import { useRef, useState } from 'react'
import { PageContainer, ProTable } from '@ant-design/pro-components'
import { Button, Tag, Space, Popconfirm, message } from 'antd'
import { fetchAllocations, dispatchAllocation } from '../api/services'

const STATUS_ENUM = {
  pending: { text: '待下发', status: 'Default' },
  dispatched: { text: '已下发', status: 'Success' },
  claimed: { text: '已领取', status: 'Processing' },
  failed: { text: '下发失败', status: 'Error' },
}

export default function AllocationsPage() {
  const actionRef = useRef()
  const [dispatchingId, setDispatchingId] = useState(null)

  const handleDispatch = async (record) => {
    setDispatchingId(record.id)
    try {
      const { data } = await dispatchAllocation(record.id)
      message.success(data?.detail || '下发成功')
      actionRef.current?.reload()
    } catch {
      // toasted by interceptor
    } finally {
      setDispatchingId(null)
    }
  }

  const columns = [
    { title: '候选人', dataIndex: 'candidate_name', width: 120, fixed: 'left' },
    { title: '投递岗位', dataIndex: 'position_name', ellipsis: true },
    { title: '分配部门', dataIndex: 'department_name', width: 160 },
    { title: '接口人', dataIndex: 'contact_name', width: 120 },
    { title: '分配理由', dataIndex: 'reason', ellipsis: true, search: false },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      valueType: 'select',
      valueEnum: STATUS_ENUM,
    },
    {
      title: '操作',
      valueType: 'option',
      width: 140,
      fixed: 'right',
      render: (_, record) => {
        const disabled = record.status === 'dispatched'
        return (
          <Space>
            <Popconfirm
              title="确认下发该简历到 WeLink？"
              onConfirm={() => handleDispatch(record)}
              disabled={disabled}
            >
              <Button
                type="link"
                size="small"
                disabled={disabled}
                loading={dispatchingId === record.id}
              >
                下发
              </Button>
            </Popconfirm>
            {disabled && <Tag color="green">已下发</Tag>}
          </Space>
        )
      },
    },
  ]

  return (
    <PageContainer
      title="简历分配"
      content="Step5 分配结果，可逐条下发到 WeLink。"
    >
      <ProTable
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        scroll={{ x: 1100 }}
        search={{ labelWidth: 'auto' }}
        pagination={{ defaultPageSize: 10, showSizeChanger: true }}
        request={async (params) => {
          const { current, pageSize, status } = params
          try {
            const { data } = await fetchAllocations({
              page: current,
              page_size: pageSize,
              status,
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
