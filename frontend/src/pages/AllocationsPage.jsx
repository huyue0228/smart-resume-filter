import { useRef, useState } from 'react'
import { PageContainer, ProTable } from '@ant-design/pro-components'
import {
  Button,
  Tag,
  Space,
  Popconfirm,
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
  cancelAllocation,
  cancelReviewAllocation,
  transferAllocationToManual,
  retryAgentDecision,
  bulkDispatchAllocations,
  assignSubContact,
  submitAllocationFeedback,
  exportAllocations,
  fetchContacts,
} from '../api/services'
import { useRole } from '../contexts/RoleContext'
import ResumePreview from '../components/ResumePreview'
import { downloadBlobFromResponse } from '../utils/download'
import {
  normalizeTableFilters,
  selectColumnFilter,
  textColumnFilter,
  useResizableColumns,
} from '../components/DataTableControls'

const STATUS_ENUM = {
  pending_dispatch: { text: '待下发', status: 'Default' },
  pending_review: { text: '待复核', status: 'Warning' },
  dispatched_l2: { text: '已下发二级', status: 'Processing' },
  assigned_l3: { text: '已转派三级', status: 'Processing' },
  passed: { text: '已通过', status: 'Success' },
  rejected: { text: '未通过', status: 'Error' },
  cancelled: { text: '已取消', status: 'Default' },
}

export default function AllocationsPage({ source = 'rule' }) {
  const actionRef = useRef()
  const { hasPermission, isContact, isSecondaryContact, isTertiaryContact } = useRole()
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
  const [manualModal, setManualModal] = useState({
    open: false,
    record: null,
    contacts: [],
    contactId: undefined,
    secondaryId: undefined,
    reason: '',
    loading: false,
  })

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

  const handleCancelAttempt = async (record) => {
    setDispatchingId(record.id)
    try {
      const cancel = record.status === 'pending_review' ? cancelReviewAllocation : cancelAllocation
      await cancel(record.id, {
        reason: record.status === 'pending_review' ? 'hr_cancelled_review' : 'hr_cancelled_dispatch',
      })
      message.success(record.status === 'pending_review' ? '已取消 AI 复核建议' : '已取消待下发尝试')
      actionRef.current?.reload()
    } finally {
      setDispatchingId(null)
    }
  }

  const handleRetryAI = async (record) => {
    if (!record.agent_decision) return
    setDispatchingId(record.id)
    try {
      await retryAgentDecision(record.agent_decision)
      message.success('已重新发起 AI 筛选')
      actionRef.current?.reload()
    } finally {
      setDispatchingId(null)
    }
  }

  const openManualModal = async (record) => {
    setManualModal((prev) => ({ ...prev, open: true, record, loading: true }))
    try {
      const { data } = await fetchContacts({ is_active: 'true', page_size: 500 })
      setManualModal((prev) => ({ ...prev, contacts: data?.results || [], loading: false }))
    } catch {
      setManualModal((prev) => ({ ...prev, loading: false }))
    }
  }

  const handleTransferToManual = async () => {
    if (!manualModal.contactId) {
      message.warning('请选择目标接口人')
      return
    }
    setManualModal((prev) => ({ ...prev, loading: true }))
    try {
      await transferAllocationToManual(manualModal.record.id, {
        contact_id: manualModal.contactId,
        secondary_contact_id: manualModal.secondaryId,
        manual_reason: manualModal.reason || 'AI 复核转人工分配',
      })
      message.success('已转为人工分配')
      setManualModal({ open: false, record: null, contacts: [], contactId: undefined, secondaryId: undefined, reason: '', loading: false })
      actionRef.current?.reload()
    } catch {
      setManualModal((prev) => ({ ...prev, loading: false }))
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
  const baseColumns = [
    {
      title: '候选人',
      dataIndex: 'candidate_name',
      width: 120,
      fixed: 'left',
      ...textColumnFilter('筛选候选人'),
    },
    {
      title: '当前志愿',
      dataIndex: 'volunteer_rank',
      width: 90,
      search: false,
      ...textColumnFilter('筛选志愿序号'),
      render: (_, record) => record.volunteer_rank || '-',
    },
    {
      title: '应聘ID',
      dataIndex: 'apply_id',
      width: 120,
      search: false,
      ...textColumnFilter('筛选应聘ID'),
    },
    {
      title: '当前投递',
      dataIndex: 'position_name',
      ellipsis: true,
      ...textColumnFilter('筛选投递岗位'),
    },
    {
      title: '分配部门',
      dataIndex: 'department_name',
      width: 160,
      ...textColumnFilter('筛选分配部门'),
    },
    !isSecondaryContact && {
      title: '二级接口人',
      dataIndex: 'contact_name',
      width: 120,
      ...textColumnFilter('筛选二级接口人'),
    },
    {
      title: '三级接口人',
      dataIndex: 'sub_contact_name',
      width: 120,
      ...textColumnFilter('筛选三级接口人'),
    },
    {
      title: '分配原因',
      dataIndex: 'match_reason',
      width: 240,
      ellipsis: true,
      search: false,
      ...textColumnFilter('筛选分配原因'),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 120,
      valueType: 'select',
      valueEnum: statusValueEnum,
      ...selectColumnFilter(
        Object.entries(statusValueEnum).map(([value, item]) => ({ value, text: item.text })),
      ),
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
            {canConfirmReview && hasPermission('resume.manual_assign') && (
              <Button type="link" size="small" style={{ padding: 0 }} onClick={() => openManualModal(record)}>
                转人工
              </Button>
            )}
            {canConfirmReview && record.agent_decision && (
              <Button type="link" size="small" style={{ padding: 0 }} onClick={() => handleRetryAI(record)}>
                重试 AI
              </Button>
            )}
            {(canConfirmReview || canDispatch) && (
              <Popconfirm
                title={canConfirmReview ? '取消该 AI 复核建议并归档？' : '取消该待下发尝试？'}
                onConfirm={() => handleCancelAttempt(record)}
              >
                <Button type="link" danger size="small" style={{ padding: 0 }}>取消</Button>
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
  const { columns, components, scrollX } = useResizableColumns(baseColumns)

  return (
    <PageContainer
      title={source === 'ai' ? 'AI分配' : '规则分配'}
      content={
        isContact
          ? isSecondaryContact
            ? 'HR 下发给你的分配尝试，可选择本二级部门下的三级接口人转派。'
            : '转派给你的分配尝试，可导出简历并提交通过/未通过反馈。'
          : `${source === 'ai' ? 'AI' : '规则'}分配尝试，可逐条下发到二级接口人，并导出候选人简历文件。`
      }
    >
      <ProTable
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        components={components}
        scroll={{ x: scrollX }}
        search={false}
        pagination={{ defaultPageSize: 10, showSizeChanger: true }}
        params={{ source }}
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
        request={async (params, _sort, filters) => {
          const { current, pageSize, source: requestedSource } = params
          const tableFilters = normalizeTableFilters(filters, [
            'candidate_name',
            'volunteer_rank',
            'apply_id',
            'position_name',
            'department_name',
            'contact_name',
            'sub_contact_name',
            'match_reason',
            'status',
          ])
          const query = { ...tableFilters, source: requestedSource }
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
              <Descriptions.Item label="分配原因" span={2}>
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
        title="AI 复核转人工分配"
        open={manualModal.open}
        confirmLoading={manualModal.loading}
        onOk={handleTransferToManual}
        onCancel={() => setManualModal({ open: false, record: null, contacts: [], contactId: undefined, secondaryId: undefined, reason: '', loading: false })}
        okText="确认分配"
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Select
            showSearch
            optionFilterProp="label"
            style={{ width: '100%' }}
            placeholder="选择二级或三级接口人"
            value={manualModal.contactId}
            options={manualModal.contacts.map((contact) => ({
              value: contact.id,
              label: `${contact.name}（${contact.contact_level === 'secondary' ? '二级' : '三级'} / ${contact.department_name || '未绑定部门'}）`,
            }))}
            onChange={(value) => setManualModal((prev) => ({ ...prev, contactId: value, secondaryId: undefined }))}
          />
          {(() => {
            const target = manualModal.contacts.find((item) => item.id === manualModal.contactId)
            if (target?.contact_level !== 'tertiary') return null
            const parents = manualModal.contacts.filter(
              (item) => item.contact_level === 'secondary' && item.department === target.parent_department,
            )
            if (parents.length <= 1) return null
            return (
              <Select
                style={{ width: '100%' }}
                placeholder="该三级部门有多个上级二级接口人，请明确选择"
                value={manualModal.secondaryId}
                options={parents.map((item) => ({ value: item.id, label: `${item.name}（${item.employee_no}）` }))}
                onChange={(value) => setManualModal((prev) => ({ ...prev, secondaryId: value }))}
              />
            )
          })()}
          <Input.TextArea
            rows={3}
            placeholder="人工分配原因"
            value={manualModal.reason}
            onChange={(event) => setManualModal((prev) => ({ ...prev, reason: event.target.value }))}
          />
        </Space>
      </Modal>
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
    </PageContainer>
  )
}
