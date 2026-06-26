import { useRef, useState } from 'react'
import { PageContainer, ProTable } from '@ant-design/pro-components'
import { Button, Tag, Space, Popconfirm, message } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import {
  fetchAllocations,
  dispatchAllocation,
  exportAllocations,
} from '../api/services'
import { useRole } from '../contexts/RoleContext'

const STATUS_ENUM = {
  pending: { text: '待下发', status: 'Default' },
  dispatched: { text: '已下发', status: 'Success' },
  claimed: { text: '已领取', status: 'Processing' },
  failed: { text: '下发失败', status: 'Error' },
}

function triggerDownload(data, filename) {
  const url = URL.createObjectURL(new Blob([data]))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

export default function AllocationsPage() {
  const actionRef = useRef()
  const { isContact } = useRole()
  const [dispatchingId, setDispatchingId] = useState(null)
  const [selectedRowKeys, setSelectedRowKeys] = useState([])
  const [exporting, setExporting] = useState(false)
  const [lastQuery, setLastQuery] = useState({})

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

  // ids 为空 -> 按当前筛选导出全部
  const handleExport = async (ids) => {
    setExporting(true)
    try {
      const resp = await exportAllocations(ids, lastQuery)
      const count = Number(resp.headers?.['x-export-count'] ?? 0)
      const missing = Number(resp.headers?.['x-export-missing'] ?? 0)
      if (count === 0) {
        message.warning('所选记录暂无可导出的简历文件')
      } else {
        triggerDownload(resp.data, 'resumes_export.zip')
        message.success(
          `已导出 ${count} 份简历${missing ? `，${missing} 份缺文件（见压缩包内清单）` : ''}`,
        )
      }
    } catch {
      message.error('导出失败')
    } finally {
      setExporting(false)
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
      width: isContact ? 90 : 160,
      fixed: 'right',
      render: (_, record) => {
        const dispatched = record.status === 'dispatched'
        return (
          <Space>
            <a onClick={() => handleExport([record.id])}>导出</a>
            {!isContact && (
              <Popconfirm
                title="确认下发该简历到 WeLink？"
                onConfirm={() => handleDispatch(record)}
                disabled={dispatched}
              >
                <Button
                  type="link"
                  size="small"
                  style={{ padding: 0 }}
                  disabled={dispatched}
                  loading={dispatchingId === record.id}
                >
                  下发
                </Button>
              </Popconfirm>
            )}
            {!isContact && dispatched && <Tag color="green">已下发</Tag>}
          </Space>
        )
      },
    },
  ]

  return (
    <PageContainer
      title="简历分配"
      content={
        isContact
          ? '分配给你的简历，可单条或批量导出简历文件。'
          : 'Step5 分配结果，可逐条下发到 WeLink，并导出候选人简历文件。'
      }
    >
      <ProTable
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        scroll={{ x: 1100 }}
        search={{ labelWidth: 'auto' }}
        pagination={{ defaultPageSize: 10, showSizeChanger: true }}
        rowSelection={{
          selectedRowKeys,
          onChange: (keys) => setSelectedRowKeys(keys),
        }}
        tableAlertOptionRender={() => (
          <Space>
            <a onClick={() => handleExport(selectedRowKeys)}>导出选中</a>
            <a onClick={() => setSelectedRowKeys([])}>取消选择</a>
          </Space>
        )}
        toolBarRender={() => [
          <Button
            key="export-selected"
            icon={<DownloadOutlined />}
            disabled={selectedRowKeys.length === 0}
            loading={exporting}
            onClick={() => handleExport(selectedRowKeys)}
          >
            导出选中{selectedRowKeys.length ? `(${selectedRowKeys.length})` : ''}
          </Button>,
          <Button
            key="export-all"
            type="primary"
            icon={<DownloadOutlined />}
            loading={exporting}
            onClick={() => handleExport([])}
          >
            导出全部
          </Button>,
        ]}
        request={async (params) => {
          const { current, pageSize, status } = params
          const query = { status }
          setLastQuery(query)
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
