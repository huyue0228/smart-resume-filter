import { useRef, useState } from 'react'
import { PageContainer, ProTable } from '@ant-design/pro-components'
import {
  Button,
  Tag,
  Space,
  Popconfirm,
  Segmented,
  Modal,
  message,
  Select,
  Radio,
  Input,
  Drawer,
  Descriptions,
  Typography,
} from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import {
  fetchAllocations,
  dispatchAllocation,
  confirmReviewAllocation,
  bulkDispatchAllocations,
  assignSubContact,
  submitAllocationFeedback,
  exportAllocations,
  fetchContacts,
} from '../api/services'
import { useRole } from '../contexts/RoleContext'
import { useMode } from '../contexts/ModeContext'
import { useProcessRunner } from '../components/useProcessRunner'
import ResumePreview from '../components/ResumePreview'
import { downloadBlobFromResponse } from '../utils/download'

const REPROCESS_STEPS = [
  { step: 'step2', label: '简历分类、分配与下发' },
]

const STATUS_ENUM = {
  pending_dispatch: { text: '待下发', status: 'Default' },
  pending_review: { text: '待复核', status: 'Warning' },
  dispatched_l2: { text: '已下发二级', status: 'Processing' },
  assigned_l3: { text: '已转派三级', status: 'Processing' },
  passed: { text: '已通过', status: 'Success' },
  rejected: { text: '未通过', status: 'Error' },
  cancelled: { text: '已取消', status: 'Default' },
}

const SOURCE_TEXT = {
  rule: '规则',
  ai: 'AI',
  manual: '手动',
}

export default function AllocationsPage() {
  const actionRef = useRef()
  const { hasPermission, isContact, isSecondaryContact, isTertiaryContact } = useRole()
  const { mode, setMode } = useMode()
  const { run, modal } = useProcessRunner()
  const [dispatchingId, setDispatchingId] = useState(null)
  const [bulkDispatching, setBulkDispatching] = useState(false)
  const [selectedRowKeys, setSelectedRowKeys] = useState([])
  const [exporting, setExporting] = useState(false)
  const [lastQuery, setLastQuery] = useState({})
  const [detailRecord, setDetailRecord] = useState(null)
  const [assignModal, setAssignModal] = useState({
    open: false,
    record: null,
    contacts: [],
    selected: undefined,
    loading: false,
  })
  const [feedbackModal, setFeedbackModal] = useState({
    open: false,
    record: null,
    result: 'passed',
    note: '',
    loading: false,
  })

  const handleModeChange = (next) => {
    if (next === mode) return
    Modal.confirm({
      title: `切换到${next === 'ai' ? 'AI' : '规则'}模式`,
      content: '将按新模式重新进行简历分类、分配与下发，是否继续？',
      okText: '重新处理',
      onOk: async () => {
        setMode(next)
        const r = await run(
          REPROCESS_STEPS,
          next,
          `正在按${next === 'ai' ? 'AI' : '规则'}模式重算`,
        )
        if (r.success) message.success('已按新模式重新分配')
        actionRef.current?.reload()
      },
    })
  }

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

  const handleConfirmReview = async (record) => {
    setDispatchingId(record.id)
    try {
      await confirmReviewAllocation(record.id)
      message.success('已确认，进入待下发')
      actionRef.current?.reload()
    } catch {
      // toasted by interceptor
    } finally {
      setDispatchingId(null)
    }
  }

  const handleBulkDispatch = (ids) => {
    const isSelected = ids?.length > 0
    Modal.confirm({
      title: isSelected ? '批量下发选中简历？' : '一键下发当前筛选下全部简历？',
      content: isSelected
        ? `将下发选中的 ${ids.length} 条待下发记录，其他状态会自动跳过。`
        : '将按当前表格筛选条件下发全部待下发记录，其他状态会自动跳过。',
      okText: isSelected ? '下发选中' : '下发全部',
      onOk: async () => {
        setBulkDispatching(true)
        try {
          const { data } = await bulkDispatchAllocations(
            { ids: isSelected ? ids : [] },
            isSelected ? undefined : lastQuery,
          )
          message.success(data?.detail || '批量下发完成')
          setSelectedRowKeys([])
          actionRef.current?.reload()
        } catch {
          // toasted by interceptor
        } finally {
          setBulkDispatching(false)
        }
      },
    })
  }

  const openAssignModal = async (record) => {
    setAssignModal({
      open: true,
      record,
      contacts: [],
      selected: record.sub_contact || undefined,
      loading: true,
    })
    try {
      const { data } = await fetchContacts({
        contact_level: 'tertiary',
        parent_department: record.department,
        is_active: 'true',
        page_size: 200,
      })
      setAssignModal((prev) => ({
        ...prev,
        contacts: data?.results || [],
        loading: false,
      }))
    } catch {
      setAssignModal((prev) => ({ ...prev, loading: false }))
    }
  }

  const handleAssignSubContact = async () => {
    if (!assignModal.selected) {
      message.warning('请选择三级接口人')
      return
    }
    setAssignModal((prev) => ({ ...prev, loading: true }))
    try {
      await assignSubContact(assignModal.record.id, {
        sub_contact_id: assignModal.selected,
      })
      message.success('已转派给三级接口人')
      setAssignModal({
        open: false,
        record: null,
        contacts: [],
        selected: undefined,
        loading: false,
      })
      actionRef.current?.reload()
    } catch {
      setAssignModal((prev) => ({ ...prev, loading: false }))
    }
  }

  const openFeedbackModal = (record) => {
    setFeedbackModal({
      open: true,
      record,
      result: 'passed',
      note: '',
      loading: false,
    })
  }

  const handleFeedback = async () => {
    setFeedbackModal((prev) => ({ ...prev, loading: true }))
    try {
      await submitAllocationFeedback(feedbackModal.record.id, {
        result: feedbackModal.result,
        note: feedbackModal.note,
      })
      message.success('反馈已提交')
      setFeedbackModal({
        open: false,
        record: null,
        result: 'passed',
        note: '',
        loading: false,
      })
      actionRef.current?.reload()
    } catch {
      setFeedbackModal((prev) => ({ ...prev, loading: false }))
    }
  }

  const handleExport = async (ids) => {
    setExporting(true)
    try {
      const resp = await exportAllocations(ids, lastQuery)
      const count = Number(resp.headers?.['x-export-count'] ?? 0)
      const missing = Number(resp.headers?.['x-export-missing'] ?? 0)
      if (count === 0 && missing === 0) {
        message.warning('所选记录暂无可导出的简历文件')
      } else {
        downloadBlobFromResponse(resp, 'resumes_export.zip')
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

  const statusValueEnum = isContact
    ? {
        dispatched_l2: STATUS_ENUM.dispatched_l2,
        assigned_l3: STATUS_ENUM.assigned_l3,
        passed: STATUS_ENUM.passed,
        rejected: STATUS_ENUM.rejected,
      }
    : STATUS_ENUM

  const columns = [
    { title: '候选人', dataIndex: 'candidate_name', width: 120, fixed: 'left' },
    { title: '投递岗位', dataIndex: 'position_name', ellipsis: true },
    {
      title: '来源',
      dataIndex: 'source',
      width: 80,
      search: false,
      render: (value) => SOURCE_TEXT[value] || value || '-',
    },
    { title: '分配部门', dataIndex: 'department_name', width: 160 },
    !isSecondaryContact && { title: '二级接口人', dataIndex: 'contact_name', width: 120 },
    { title: '三级接口人', dataIndex: 'sub_contact_name', width: 120 },
    { title: '分配理由', dataIndex: 'match_reason', ellipsis: true, search: false },
    {
      title: '状态',
      dataIndex: 'status',
      width: 120,
      valueType: 'select',
      valueEnum: statusValueEnum,
    },
    {
      title: '操作',
      valueType: 'option',
      width: isContact ? 190 : 210,
      fixed: 'right',
      render: (_, record) => {
        const canDispatch =
          hasPermission('attempt.dispatch') && record.status === 'pending_dispatch'
        const canConfirmReview =
          hasPermission('attempt.dispatch') && record.status === 'pending_review'
        const canAssign =
          isSecondaryContact &&
          ['dispatched_l2', 'assigned_l3'].includes(record.status) &&
          !record.feedback_at
        const canExport = hasPermission('attempt.export')
        const canFeedback =
          isTertiaryContact && record.status === 'assigned_l3' && !record.feedback_at
        return (
          <Space>
            <a onClick={() => setDetailRecord(record)}>详情</a>
            {canExport && <a onClick={() => handleExport([record.id])}>导出</a>}
            {canDispatch && (
              <Popconfirm
                title="确认下发该简历到二级接口人？"
                onConfirm={() => handleDispatch(record)}
              >
                <Button
                  type="link"
                  size="small"
                  style={{ padding: 0 }}
                  loading={dispatchingId === record.id}
                >
                  下发二级
                </Button>
              </Popconfirm>
            )}
            {canConfirmReview && (
              <Popconfirm
                title="确认采纳 AI 复核建议并进入待下发？"
                onConfirm={() => handleConfirmReview(record)}
              >
                <Button
                  type="link"
                  size="small"
                  style={{ padding: 0 }}
                  loading={dispatchingId === record.id}
                >
                  确认下发
                </Button>
              </Popconfirm>
            )}
            {canAssign && (
              <Button
                type="link"
                size="small"
                style={{ padding: 0 }}
                onClick={() => openAssignModal(record)}
              >
                {record.sub_contact ? '改派' : '转派'}
              </Button>
            )}
            {canFeedback && (
              <Button
                type="link"
                size="small"
                style={{ padding: 0 }}
                onClick={() => openFeedbackModal(record)}
              >
                反馈
              </Button>
            )}
            {!canDispatch &&
              !canConfirmReview &&
              !canAssign &&
              !canFeedback &&
              record.feedback_at && <Tag color="green">已反馈</Tag>}
          </Space>
        )
      },
    },
  ].filter(Boolean)

  return (
    <PageContainer
      title="简历分配"
      content={
        isContact
          ? isSecondaryContact
            ? 'HR 下发给你的分配尝试，可选择本二级部门下的三级接口人转派。'
            : '转派给你的分配尝试，可导出简历并提交通过/未通过反馈。'
          : '简历分类、分配与下发尝试，可逐条下发到二级接口人，并导出候选人简历文件。'
      }
      extra={
        isContact
          ? undefined
          : [
              <Space key="mode" align="center">
                <span style={{ color: '#666' }}>处理模式：</span>
                <Segmented
                  value={mode}
                  onChange={handleModeChange}
                  options={[
                    { label: '规则模式', value: 'rule' },
                    { label: 'AI 模式', value: 'ai' },
                  ]}
                />
              </Space>,
            ]
      }
    >
      <ProTable
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        scroll={{ x: 1250 }}
        search={{ labelWidth: 'auto' }}
        pagination={{ defaultPageSize: 10, showSizeChanger: true }}
        rowSelection={{
          selectedRowKeys,
          onChange: (keys) => setSelectedRowKeys(keys),
        }}
        tableAlertOptionRender={() => (
          <Space>
            {hasPermission('attempt.export') && (
              <a onClick={() => handleExport(selectedRowKeys)}>导出选中</a>
            )}
            {hasPermission('attempt.dispatch') && (
              <a onClick={() => handleBulkDispatch(selectedRowKeys)}>下发选中</a>
            )}
            <a onClick={() => setSelectedRowKeys([])}>取消选择</a>
          </Space>
        )}
        toolBarRender={() => [
          hasPermission('attempt.dispatch') && (
            <Button
              key="dispatch-selected"
              disabled={selectedRowKeys.length === 0}
              loading={bulkDispatching}
              onClick={() => handleBulkDispatch(selectedRowKeys)}
            >
              下发选中{selectedRowKeys.length ? `(${selectedRowKeys.length})` : ''}
            </Button>
          ),
          hasPermission('attempt.dispatch') && (
            <Button
              key="dispatch-all"
              loading={bulkDispatching}
              onClick={() => handleBulkDispatch([])}
            >
              一键全部下发
            </Button>
          ),
          hasPermission('attempt.export') && (
            <Button
              key="export-selected"
              icon={<DownloadOutlined />}
              disabled={selectedRowKeys.length === 0}
              loading={exporting}
              onClick={() => handleExport(selectedRowKeys)}
            >
              导出选中{selectedRowKeys.length ? `(${selectedRowKeys.length})` : ''}
            </Button>
          ),
          hasPermission('attempt.export') && (
            <Button
              key="export-all"
              type="primary"
              icon={<DownloadOutlined />}
              loading={exporting}
              onClick={() => handleExport([])}
            >
              导出全部
            </Button>
          ),
        ]}
        request={async (params) => {
          const { current, pageSize, status } = params
          const query = { status }
          setLastQuery(query)
          try {
            const { data } = await fetchAllocations({
              page: current,
              page_size: pageSize,
              ...query,
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
      <Drawer
        title={
          detailRecord ? `${detailRecord.candidate_name || '-'} 的分配详情` : '分配详情'
        }
        width={1000}
        open={!!detailRecord}
        onClose={() => setDetailRecord(null)}
      >
        {detailRecord && (
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="候选人">
                {detailRecord.candidate_name || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="应聘ID">
                {detailRecord.apply_id || detailRecord.resume_apply_id_snapshot || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="投递岗位">
                {detailRecord.position_name || detailRecord.position_name_snapshot || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="来源">
                {SOURCE_TEXT[detailRecord.source] || detailRecord.source || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="状态">
                {STATUS_ENUM[detailRecord.status]?.text || detailRecord.status || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="分配部门">
                {detailRecord.department_name ||
                  detailRecord.department_name_snapshot ||
                  '-'}
              </Descriptions.Item>
              <Descriptions.Item label="二级接口人">
                {detailRecord.contact_name || detailRecord.contact_name_snapshot || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="三级接口人">
                {detailRecord.sub_contact_name ||
                  detailRecord.sub_contact_name_snapshot ||
                  '-'}
              </Descriptions.Item>
              <Descriptions.Item label="分配理由" span={2}>
                {detailRecord.match_reason || '-'}
              </Descriptions.Item>
              {detailRecord.agent_decision_summary?.summary && (
                <Descriptions.Item label="AI 摘要" span={2}>
                  {detailRecord.agent_decision_summary.summary}
                </Descriptions.Item>
              )}
              {detailRecord.feedback_result && (
                <Descriptions.Item label="反馈结果">
                  {detailRecord.feedback_result === 'passed' ? '通过' : '未通过'}
                </Descriptions.Item>
              )}
              {detailRecord.feedback_at && (
                <Descriptions.Item label="反馈时间">
                  {detailRecord.feedback_at}
                </Descriptions.Item>
              )}
              {detailRecord.feedback_note && (
                <Descriptions.Item label="反馈备注" span={2}>
                  {detailRecord.feedback_note}
                </Descriptions.Item>
              )}
            </Descriptions>

            <div>
              <Typography.Title level={5} style={{ marginTop: 0 }}>
                简历预览
              </Typography.Title>
              <ResumePreview
                attemptId={detailRecord.id}
                resume={{
                  id: detailRecord.resume,
                  apply_id:
                    detailRecord.apply_id || detailRecord.resume_apply_id_snapshot,
                  position_name:
                    detailRecord.position_name || detailRecord.position_name_snapshot,
                }}
              />
            </div>
          </Space>
        )}
      </Drawer>
      <Modal
        title="转派三级接口人"
        open={assignModal.open}
        confirmLoading={assignModal.loading}
        onOk={handleAssignSubContact}
        onCancel={() =>
          setAssignModal({
            open: false,
            record: null,
            contacts: [],
            selected: undefined,
            loading: false,
          })
        }
        okText="转派"
      >
        <Select
          style={{ width: '100%' }}
          placeholder="选择本二级部门下的三级接口人"
          value={assignModal.selected}
          loading={assignModal.loading}
          options={assignModal.contacts.map((contact) => ({
            value: contact.id,
            label: `${contact.name}（${contact.department_name || '未绑定部门'}）`,
          }))}
          onChange={(value) =>
            setAssignModal((prev) => ({ ...prev, selected: value }))
          }
        />
      </Modal>
      <Modal
        title="提交反馈"
        open={feedbackModal.open}
        confirmLoading={feedbackModal.loading}
        onOk={handleFeedback}
        onCancel={() =>
          setFeedbackModal({
            open: false,
            record: null,
            result: 'passed',
            note: '',
            loading: false,
          })
        }
        okText="提交"
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Radio.Group
            value={feedbackModal.result}
            onChange={(event) =>
              setFeedbackModal((prev) => ({
                ...prev,
                result: event.target.value,
              }))
            }
          >
            <Radio.Button value="passed">通过</Radio.Button>
            <Radio.Button value="rejected">未通过</Radio.Button>
          </Radio.Group>
          <Input.TextArea
            rows={4}
            placeholder="备注（可选）"
            value={feedbackModal.note}
            onChange={(event) =>
              setFeedbackModal((prev) => ({
                ...prev,
                note: event.target.value,
              }))
            }
          />
        </Space>
      </Modal>
      {modal}
    </PageContainer>
  )
}
