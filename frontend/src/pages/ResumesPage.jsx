import { useRef, useEffect, useState, useCallback } from 'react'
import { PageContainer, ProTable } from '@ant-design/pro-components'
import {
  Button,
  Checkbox,
  Tag,
  Space,
  Modal,
  message,
  Drawer,
  Descriptions,
  Typography,
  Tooltip,
  Select,
  Input,
  Popconfirm,
} from 'antd'
import { DownloadOutlined, PlayCircleOutlined, UndoOutlined } from '@ant-design/icons'
import {
  deleteCandidate,
  exportCandidates,
  fetchCandidates,
  fetchCandidateFilterOptions,
  fetchUndoStatus,
  undoLastImport,
  fetchContacts,
  manualAssignResume,
  fetchAgentDecisions,
  retryAgentDecision,
  fetchAllocationMode,
  dispatchAllocation,
  confirmReviewAllocation,
  cancelAllocation,
  cancelReviewAllocation,
  transferAllocationToManual,
  bulkDispatchCandidates,
  assignSubContact,
  fetchEligibleSubContacts,
  submitAllocationFeedback,
  exportAllocations,
} from '../api/services'
import ImportButton from '../components/ImportButton'
import ResumePreview from '../components/ResumePreview'
import ResizableTable from '../components/ResizableTable'
import { useProcessRunner } from '../components/useProcessRunner'
import { useRole } from '../contexts/RoleContext'
import {
  normalizeTableFilters,
  localSelectColumnFilter,
  localTextColumnFilter,
  selectColumnFilter,
  textColumnFilter,
  useResizableColumns,
} from '../components/DataTableControls'
import { downloadBlobFromResponse } from '../utils/download'

const RESUME_IMPORT_FIELDS = [
  { key: 'resume_list', label: '① 简历信息列表 (.xlsx/.xls/.csv)', accept: '.xlsx,.xls,.csv' },
  { key: 'resume_package', label: '② 简历包 (.zip，文件名含应聘ID)', accept: '.zip' },
]

const SYSTEM_STATUS_OPTIONS = {
  raw: {
    text: '待处理',
    color: 'default',
    status: 'Default',
    description: '当前候选人/当前投递尚未完成岗位类别和院校标签分类',
  },
  classified: {
    text: '已分类',
    color: 'blue',
    status: 'Processing',
    description: '已完成岗位类别和院校标签分类，但没有有效业务部门推荐或下发尝试',
  },
  allocated: {
    text: '已分配',
    color: 'gold',
    status: 'Warning',
    description: '存在待复核/待下发等 HR 待处理尝试，业务部门尚不可见',
  },
  pending_screening: {
    text: '待筛选',
    color: 'processing',
    status: 'Processing',
    description: '存在已下发二级/已转派三级尝试，已给业务部门但尚未反馈',
  },
  screening_passed: {
    text: '筛选通过',
    color: 'success',
    status: 'Success',
    description: '当前流程或最近有效尝试已由业务部门反馈通过',
  },
  screening_rejected: {
    text: '筛选不通过',
    color: 'error',
    status: 'Error',
    description: '最近有效尝试已反馈未通过，或全部志愿未通过导致归档',
  },
}

const ATTEMPT_STATUS = {
  pending_review: { color: 'warning', text: '待复核' },
  pending_dispatch: { color: 'default', text: '待下发' },
  dispatched_l2: { color: 'processing', text: '已下发二级' },
  assigned_l3: { color: 'processing', text: '已转派三级' },
  passed: { color: 'success', text: '已通过' },
  rejected: { color: 'error', text: '未通过' },
  cancelled: { color: 'default', text: '已取消' },
}

const SOURCE_TEXT = {
  rule: '规则',
  ai: 'AI',
  manual: '手动',
}

const WORKFLOW_STATUS = {
  pending: { text: '待分配', color: 'default' },
  in_progress: { text: '进行中', color: 'processing' },
  passed: { text: '已通过', color: 'success' },
  archived: { text: '已归档', color: 'default' },
}

const REASON_TYPE = {
  assignment: { text: '分配理由', color: 'blue' },
  archive: { text: '归档理由', color: 'default' },
  block: { text: '阻塞原因', color: 'orange' },
  classification: { text: '分类理由', color: 'purple' },
  none: { text: '无', color: 'default' },
}

export default function ResumesPage() {
  const actionRef = useRef()
  const { hasPermission, isContact, isSecondaryContact, isTertiaryContact } = useRole()
  const canViewAgentDecisions = hasPermission('attempt.view_all')
  const canRunPipeline = hasPermission('pipeline.run')
  const canImport = hasPermission('resume.import')
  const { run } = useProcessRunner()
  const [undo, setUndo] = useState({ available: false })
  const [detailRecord, setDetailRecord] = useState(null)
  const [previewRecord, setPreviewRecord] = useState(null)
  const [agentDecisions, setAgentDecisions] = useState([])
  const [agentDecisionsLoading, setAgentDecisionsLoading] = useState(false)
  const [agentDecisionDetail, setAgentDecisionDetail] = useState(null)
  const [retryingDecisionId, setRetryingDecisionId] = useState(null)
  const [exporting, setExporting] = useState(false)
  const [processing, setProcessing] = useState(false)
  const [processModalOpen, setProcessModalOpen] = useState(false)
  const [processStatusSelection, setProcessStatusSelection] = useState([])
  const [allocationMode, setAllocationMode] = useState({ mode: 'rule', ai_enabled: false, ai_ready: false })
  const [lastQuery, setLastQuery] = useState({})
  const [selectedRowKeys, setSelectedRowKeys] = useState([])
  const [bulkDispatching, setBulkDispatching] = useState(false)
  const [dispatchingId, setDispatchingId] = useState(null)
  const [filterOptions, setFilterOptions] = useState({})
  const [tableFilters, setTableFilters] = useState({})
  const [manualModal, setManualModal] = useState({
    open: false,
    resume: null,
    attempt: null,
    contacts: [],
    contactId: undefined,
    secondaryId: undefined,
    reason: '',
    loading: false,
  })
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

  const openManualAssign = async (resume, attempt = null) => {
    setManualModal((prev) => ({ ...prev, open: true, resume, attempt, loading: true }))
    try {
      const { data } = await fetchContacts({
        is_active: 'true',
        page_size: 500,
      })
      setManualModal((prev) => ({ ...prev, contacts: data?.results || [], loading: false }))
    } catch {
      setManualModal((prev) => ({ ...prev, loading: false }))
    }
  }

  const handleManualAssign = async () => {
    if (!manualModal.contactId) {
      message.warning('请选择二级接口人')
      return
    }
    setManualModal((prev) => ({ ...prev, loading: true }))
    try {
      const payload = {
        contact_id: manualModal.contactId,
        secondary_contact_id: manualModal.secondaryId,
        manual_reason: manualModal.reason || 'HR 手动强制分配',
      }
      if (manualModal.attempt) {
        await transferAllocationToManual(manualModal.attempt.id, payload)
      } else {
        await manualAssignResume(manualModal.resume.id, payload)
      }
      message.success('已创建人工分配尝试')
      setManualModal({ open: false, resume: null, attempt: null, contacts: [], contactId: undefined, secondaryId: undefined, reason: '', loading: false })
      setDetailRecord(null)
      actionRef.current?.reload()
    } catch {
      setManualModal((prev) => ({ ...prev, loading: false }))
    }
  }

  const refreshUndo = async () => {
    try {
      const { data } = await fetchUndoStatus()
      setUndo(data || { available: false })
    } catch {
      setUndo({ available: false })
    }
  }

  const refreshFilterOptions = async () => {
    try {
      const { data } = await fetchCandidateFilterOptions()
      setFilterOptions(data || {})
    } catch {
      setFilterOptions({})
    }
  }

  useEffect(() => {
    if (canImport) refreshUndo()
    refreshFilterOptions()
    if (canRunPipeline) {
      fetchAllocationMode()
        .then(({ data }) => setAllocationMode(data || { mode: 'rule', ai_enabled: false, ai_ready: false }))
        .catch(() => setAllocationMode({ mode: 'rule', ai_enabled: false, ai_ready: false }))
    }
  }, [canImport, canRunPipeline])

  useEffect(() => {
    if (Object.keys(tableFilters).length || actionRef.current) {
      actionRef.current?.reloadAndRest()
    }
  }, [tableFilters])

  useEffect(() => {
    if (!detailRecord) {
      setPreviewRecord(null)
      return
    }
    setPreviewRecord(
      detailRecord.preview_resume || detailRecord.current_resume || detailRecord.resumes?.[0] || null,
    )
  }, [detailRecord])

  const loadAgentDecisions = useCallback(async (workflowId) => {
    if (!workflowId || !canViewAgentDecisions) {
      setAgentDecisions([])
      return
    }
    setAgentDecisionsLoading(true)
    try {
      const { data } = await fetchAgentDecisions({ workflow: workflowId, page_size: 100 })
      setAgentDecisions(data?.results || [])
    } catch {
      setAgentDecisions([])
    } finally {
      setAgentDecisionsLoading(false)
    }
  }, [canViewAgentDecisions])

  useEffect(() => {
    const workflowId = detailRecord?.workflow_id
    if (!workflowId) {
      setAgentDecisions([])
      setAgentDecisionDetail(null)
      return
    }
    loadAgentDecisions(workflowId)
  }, [detailRecord?.workflow_id, loadAgentDecisions])

  const handleRetryAgentDecision = async (decision) => {
    setRetryingDecisionId(decision.id)
    try {
      const { data } = await retryAgentDecision(decision.id)
      setAgentDecisionDetail(data?.decision || null)
      await loadAgentDecisions(decision.workflow)
      actionRef.current?.reload()
      message.success(data?.attempt ? 'AI 已重试并生成分配尝试' : 'AI 已重试，请查看最新决策')
    } finally {
      setRetryingDecisionId(null)
    }
  }

  const reloadCandidates = () => {
    setDetailRecord(null)
    actionRef.current?.reload()
  }

  const handleDispatch = async (attempt) => {
    setDispatchingId(attempt.id)
    try {
      const { data } = await dispatchAllocation(attempt.id)
      message.success(data?.detail || '下发成功')
      reloadCandidates()
    } finally {
      setDispatchingId(null)
    }
  }

  const handleConfirmReview = async (attempt) => {
    setDispatchingId(attempt.id)
    try {
      await confirmReviewAllocation(attempt.id)
      message.success('已确认 AI 建议，当前记录进入待下发')
      reloadCandidates()
    } finally {
      setDispatchingId(null)
    }
  }

  const handleCancelAttempt = async (attempt) => {
    setDispatchingId(attempt.id)
    try {
      const cancel = attempt.status === 'pending_review' ? cancelReviewAllocation : cancelAllocation
      await cancel(attempt.id, {
        reason: attempt.status === 'pending_review' ? 'hr_cancelled_review' : 'hr_cancelled_dispatch',
      })
      message.success(attempt.status === 'pending_review' ? '已取消 AI 复核建议' : '已取消待下发尝试')
      reloadCandidates()
    } finally {
      setDispatchingId(null)
    }
  }

  const handleBulkDispatch = (candidateIds = []) => {
    const selected = candidateIds.length > 0
    Modal.confirm({
      title: selected ? '批量下发选中简历？' : '下发当前筛选下全部简历？',
      content: selected
        ? `将处理选中的 ${candidateIds.length} 名候选人，仅下发当前有效的待下发记录。`
        : '将按当前简历库筛选条件处理全部候选人，仅下发当前有效的待下发记录。',
      okText: selected ? '下发选中' : '下发全部',
      onOk: async () => {
        setBulkDispatching(true)
        try {
          const { data } = await bulkDispatchCandidates(
            selected ? { candidate_ids: candidateIds } : { candidate_filters: lastQuery },
          )
          message.success(data?.detail || '批量下发完成')
          setSelectedRowKeys([])
          actionRef.current?.reload()
        } finally {
          setBulkDispatching(false)
        }
      },
    })
  }

  const openAssignModal = async (attempt) => {
    setAssignModal({
      open: true,
      record: attempt,
      contacts: [],
      selected: attempt.sub_contact || undefined,
      loading: true,
    })
    try {
      const { data } = await fetchEligibleSubContacts(attempt.id)
      setAssignModal((previous) => ({ ...previous, contacts: data || [], loading: false }))
    } catch {
      setAssignModal((previous) => ({ ...previous, loading: false }))
    }
  }

  const handleAssignSubContact = async () => {
    if (!assignModal.selected) {
      message.warning('请选择三级接口人')
      return
    }
    setAssignModal((previous) => ({ ...previous, loading: true }))
    try {
      await assignSubContact(assignModal.record.id, { sub_contact_id: assignModal.selected })
      message.success('已转派给三级接口人')
      setAssignModal({ open: false, record: null, contacts: [], selected: undefined, loading: false })
      reloadCandidates()
    } catch {
      setAssignModal((previous) => ({ ...previous, loading: false }))
    }
  }

  const handleFeedback = async () => {
    setFeedbackModal((previous) => ({ ...previous, loading: true }))
    try {
      await submitAllocationFeedback(feedbackModal.record.id, {
        result: feedbackModal.result,
        note: feedbackModal.note,
      })
      message.success('反馈已提交，简历状态已更新')
      setFeedbackModal({ open: false, record: null, result: 'passed', note: '', loading: false })
      reloadCandidates()
    } catch {
      setFeedbackModal((previous) => ({ ...previous, loading: false }))
    }
  }

  const handleAttemptExport = async (attempt) => {
    setExporting(true)
    try {
      const response = await exportAllocations([attempt.id], {})
      downloadBlobFromResponse(response, 'resume_export.zip')
      message.success('简历已导出')
    } finally {
      setExporting(false)
    }
  }

  // 导入接口已在服务端创建并提交 Step1 → Step2 后台任务，页面无需等待执行完成。
  const handleImported = async (data) => {
    await refreshUndo()
    await refreshFilterOptions()
    actionRef.current?.reload()
    if (data?.processing_runs?.length) {
      message.success('简历已导入并提交后台处理，可继续操作并在任务中心查看进度')
    }
  }

  const handleUndo = () => {
    Modal.confirm({
      title: '撤销上次上传',
      content: '将删除最近一次上传的简历及其处理结果，回到上传前状态。确定撤销？',
      okText: '撤销',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          const { data } = await undoLastImport()
          message.success(data?.detail || '已撤销')
          await refreshUndo()
          await refreshFilterOptions()
          actionRef.current?.reload()
        } catch {
          message.error('撤销失败')
        }
      },
    })
  }

  const handleDelete = (record) => {
    Modal.confirm({
      title: '删除候选人',
      content: `将删除 ${record.name} 及其全部投递记录。若已产生分配历史，系统会阻止删除。确定继续？`,
      okText: '删除',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await deleteCandidate(record.id)
          message.success('已删除')
          await refreshFilterOptions()
          actionRef.current?.reload()
        } catch (error) {
          message.error(error?.response?.data?.detail || '删除失败')
        }
      },
    })
  }

  const handleExport = async () => {
    setExporting(true)
    try {
      const resp = await exportCandidates(null, lastQuery)
      const count = Number(resp.headers?.['x-export-count'] ?? 0)
      const missing = Number(resp.headers?.['x-export-missing'] ?? 0)
      if (count === 0 && missing === 0) {
        message.warning('当前筛选结果暂无可导出的简历文件')
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

  const selectedSystemStatuses = () => {
    const value = lastQuery.system_status
    if (!value) return []
    return Array.isArray(value) ? value : String(value).split(',').filter(Boolean)
  }

  const handleProcessSelectedStatuses = () => {
    setProcessStatusSelection(selectedSystemStatuses())
    setProcessModalOpen(true)
  }

  const handleConfirmProcess = async () => {
    const statuses = processStatusSelection
    if (!statuses.length) {
      message.warning('请先勾选需要处理的简历状态')
      return
    }
    setProcessing(true)
    try {
      const { system_status: _ignoredSystemStatus, ...candidateFilters } = lastQuery
      const r = await run(
        [{ step: 'step2', label: '简历分类、分配与下发' }],
        `正在重新处理简历（${allocationMode.mode === 'ai' ? 'AI' : '规则'}）`,
        {
          scope: {
            system_statuses: statuses,
            candidate_filters: candidateFilters,
          },
        },
      )
      if (r.success) {
        message.success('已提交重新处理任务，可继续操作并在任务中心查看进度')
        setProcessModalOpen(false)
      }
    } finally {
      setProcessing(false)
    }
  }

  const selectorOptions = (field, labelFormatter = (value) => value) =>
    (filterOptions[field] || []).map((value) => ({
      text: labelFormatter(value),
      value,
    }))
  const toFilterValue = (value) =>
    Array.isArray(value) ? value.join(',') : value
  const updateTableFilter = (field, values) => {
    setTableFilters((previous) => {
      const next = { ...previous }
      if (values?.length) {
        next[field] = values
      } else {
        delete next[field]
      }
      return next
    })
  }
  const controlledFilter = (field) => ({
    filteredValue: tableFilters[field] || null,
  })

  const renderCandidateActions = (record) => {
    const attempt = record.current_attempt
    const canDispatch = hasPermission('attempt.dispatch') && attempt?.status === 'pending_dispatch'
    const canReview = hasPermission('attempt.dispatch') && attempt?.status === 'pending_review'
    const canAssign = isSecondaryContact && attempt && ['dispatched_l2', 'assigned_l3'].includes(attempt.status) && !attempt.feedback_at
    const canFeedback = isTertiaryContact && attempt?.status === 'assigned_l3' && !attempt.feedback_at
    return (
      <Space>
        <a onClick={() => setDetailRecord(record)}>详情</a>
        {attempt && hasPermission('attempt.export') && (
          <a onClick={() => handleAttemptExport(attempt)}>导出</a>
        )}
        {canReview && (
          <Popconfirm title="确认采纳 AI 建议？确认后进入待下发。" onConfirm={() => handleConfirmReview(attempt)}>
            <Button type="link" size="small" style={{ padding: 0 }} loading={dispatchingId === attempt.id}>确认建议</Button>
          </Popconfirm>
        )}
        {canReview && hasPermission('resume.manual_assign') && (
          <Button type="link" size="small" style={{ padding: 0 }} onClick={() => openManualAssign(record.current_resume, attempt)}>转人工</Button>
        )}
        {canDispatch && (
          <Popconfirm title="确认下发该简历到二级接口人？" onConfirm={() => handleDispatch(attempt)}>
            <Button type="link" size="small" style={{ padding: 0 }} loading={dispatchingId === attempt.id}>下发二级</Button>
          </Popconfirm>
        )}
        {(canReview || canDispatch) && (
          <Popconfirm title={canReview ? '取消该 AI 复核建议？' : '取消该待下发尝试？'} onConfirm={() => handleCancelAttempt(attempt)}>
            <Button type="link" danger size="small" style={{ padding: 0 }}>取消</Button>
          </Popconfirm>
        )}
        {canAssign && (
          <Button type="link" size="small" style={{ padding: 0 }} onClick={() => openAssignModal(attempt)}>
            {attempt.sub_contact ? '改派' : '转派'}
          </Button>
        )}
        {canFeedback && (
          <Button
            type="link"
            size="small"
            style={{ padding: 0 }}
            onClick={() => setFeedbackModal({ open: true, record: attempt, result: 'passed', note: '', loading: false })}
          >
            反馈
          </Button>
        )}
        {hasPermission('resume.import') && (
          <a style={{ color: '#cf1322' }} onClick={() => handleDelete(record)}>删除</a>
        )}
      </Space>
    )
  }

  const baseColumns = [
    {
      title: '姓名',
      dataIndex: 'name',
      fixed: 'left',
      width: 100,
      ...controlledFilter('name'),
      ...textColumnFilter('筛选姓名/拼音', (values) => updateTableFilter('name', values)),
    },
    {
      title: '最高学历专业',
      dataIndex: 'highest_major',
      width: 130,
      ellipsis: true,
      ...controlledFilter('highest_major'),
      ...selectColumnFilter(selectorOptions('highest_major'), true, (values) =>
        updateTableFilter('highest_major', values),
      ),
      render: (_, record) => record.highest_major || '-',
    },
    {
      title: '当前志愿',
      dataIndex: 'current_rank',
      width: 90,
      ...controlledFilter('current_rank'),
      ...selectColumnFilter(
        selectorOptions('current_rank', (value) => `第${value}志愿`),
        true,
        (values) => updateTableFilter('current_rank', values),
      ),
      render: (_, record) => record.current_rank || '-',
    },
    {
      title: '当前应聘ID',
      dataIndex: 'current_apply_id',
      width: 130,
      ...controlledFilter('current_apply_id'),
      ...textColumnFilter('筛选应聘ID', (values) =>
        updateTableFilter('current_apply_id', values),
      ),
      render: (value) => value || '-',
    },
    {
      title: '当前主体',
      dataIndex: 'current_entity',
      width: 120,
      ...controlledFilter('current_entity'),
      ...selectColumnFilter(selectorOptions('current_entity'), true, (values) =>
        updateTableFilter('current_entity', values),
      ),
      render: (_, record) => record.current_resume?.entity || '-',
    },
    {
      title: '当前投递岗位',
      dataIndex: 'current_position_name',
      width: 180,
      ellipsis: true,
      ...controlledFilter('current_position_name'),
      ...selectColumnFilter(selectorOptions('current_position_name'), true, (values) =>
        updateTableFilter('current_position_name', values),
      ),
      render: (_, record) => record.current_resume?.position_name || '-',
    },
    {
      title: '岗位部门',
      dataIndex: 'job_department_name',
      width: 130,
      ellipsis: true,
      ...controlledFilter('job_department_name'),
      ...selectColumnFilter(selectorOptions('job_department_name'), true, (values) =>
        updateTableFilter('job_department_name', values),
      ),
      render: (value) => value || '-',
    },
    {
      title: '岗位类别',
      dataIndex: 'current_job_category',
      width: 110,
      ...controlledFilter('current_job_category'),
      ...selectColumnFilter(selectorOptions('current_job_category'), true, (values) =>
        updateTableFilter('current_job_category', values),
      ),
      render: (_, record) => record.current_resume?.job_category || '-',
    },
    {
      title: '分配来源',
      dataIndex: 'allocation_source',
      width: 100,
      ...controlledFilter('allocation_source'),
      ...selectColumnFilter(
        Object.entries(SOURCE_TEXT).map(([value, text]) => ({ value, text })),
        true,
        (values) => updateTableFilter('allocation_source', values),
      ),
      render: (_, record) => SOURCE_TEXT[record.current_attempt?.source] || '-',
    },
    {
      title: '二级接口人',
      dataIndex: 'contact_name',
      width: 120,
      ...controlledFilter('contact_name'),
      ...textColumnFilter('筛选二级接口人', (values) => updateTableFilter('contact_name', values)),
      render: (_, record) => record.current_attempt?.contact_name || record.current_attempt?.contact_name_snapshot || '-',
    },
    {
      title: '三级接口人',
      dataIndex: 'sub_contact_name',
      width: 120,
      ...controlledFilter('sub_contact_name'),
      ...textColumnFilter('筛选三级接口人', (values) => updateTableFilter('sub_contact_name', values)),
      render: (_, record) => record.current_attempt?.sub_contact_name || record.current_attempt?.sub_contact_name_snapshot || '-',
    },
    {
      title: '分配状态',
      dataIndex: 'attempt_status',
      width: 120,
      ...controlledFilter('attempt_status'),
      ...selectColumnFilter(
        Object.entries(ATTEMPT_STATUS).map(([value, item]) => ({ value, text: item.text })),
        true,
        (values) => updateTableFilter('attempt_status', values),
      ),
      render: (_, record) => {
        const status = record.current_attempt?.status
        return status ? <Tag color={ATTEMPT_STATUS[status]?.color || 'default'}>{ATTEMPT_STATUS[status]?.text || status}</Tag> : '-'
      },
    },
    {
      title: '院校标签',
      dataIndex: 'school_tag',
      width: 110,
      ...controlledFilter('school_tag'),
      ...selectColumnFilter(selectorOptions('school_tag'), true, (values) =>
        updateTableFilter('school_tag', values),
      ),
      render: (_, record) =>
        record.school_tag ? <Tag color="blue">{record.school_tag}</Tag> : '-',
    },
    {
      title: '系统简历状态',
      dataIndex: 'system_status',
      width: 110,
      valueType: 'select',
      valueEnum: Object.fromEntries(
        Object.entries(SYSTEM_STATUS_OPTIONS).map(([value, item]) => [
          value,
          { text: item.text, status: item.status },
        ]),
      ),
      ...controlledFilter('system_status'),
      ...selectColumnFilter(
        Object.entries(SYSTEM_STATUS_OPTIONS).map(([value, item]) => ({
          text: item.text,
          value,
        })),
        true,
        (values) => updateTableFilter('system_status', values),
      ),
      render: (_, record) => {
        const status = record.system_status
        const item = SYSTEM_STATUS_OPTIONS[status]
        return item ? (
          <Tooltip title={item.description}>
            <Tag color={item.color}>{item.text}</Tag>
          </Tooltip>
        ) : '-'
      },
    },
    {
      title: '流程状态',
      dataIndex: 'workflow_status',
      width: 110,
      valueType: 'select',
      valueEnum: Object.fromEntries(
        Object.entries(WORKFLOW_STATUS).map(([value, item]) => [
          value,
          { text: item.text },
        ]),
      ),
      ...controlledFilter('workflow_status'),
      ...selectColumnFilter(
        Object.entries(WORKFLOW_STATUS).map(([value, item]) => ({
          text: item.text,
          value,
        })),
        true,
        (values) => updateTableFilter('workflow_status', values),
      ),
      render: (value) => {
        const item = WORKFLOW_STATUS[value]
        return item ? <Tag color={item.color}>{item.text}</Tag> : '-'
      },
    },
    {
      title: '原因',
      dataIndex: 'reason_type',
      width: 240,
      ellipsis: true,
      valueType: 'select',
      valueEnum: Object.fromEntries(
        Object.entries(REASON_TYPE).map(([value, item]) => [
          value,
          { text: item.text },
        ]),
      ),
      ...controlledFilter('reason_type'),
      ...selectColumnFilter(
        Object.entries(REASON_TYPE)
          .filter(([value]) => value !== 'none')
          .map(([value, item]) => ({
            text: item.text,
            value,
          })),
        false,
        (values) => updateTableFilter('reason_type', values),
      ),
      render: (_, record) => {
        const type = record.reason_type || 'none'
        const item = REASON_TYPE[type] || REASON_TYPE.none
        return (
          <Space size={4}>
            <Tag color={item.color}>{item.text}</Tag>
            <Typography.Text ellipsis style={{ maxWidth: 150 }}>
              {record.reason_text || '-'}
            </Typography.Text>
          </Space>
        )
      },
    },
    {
      title: '操作',
      valueType: 'option',
      width: 260,
      fixed: 'right',
      render: (_, record) => renderCandidateActions(record),
    },
  ]
  const { columns, components, scrollX } = useResizableColumns(baseColumns)

  return (
    <PageContainer
      title="简历库"
      content="按候选人聚合展示当前有效志愿；点开详情查看全部投递、分配尝试和反馈。"
    >
      <ProTable
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        components={components}
        scroll={{ x: scrollX }}
        pagination={{ defaultPageSize: 10, showSizeChanger: true }}
        search={false}
        rowSelection={
          hasPermission('attempt.dispatch')
            ? {
                selectedRowKeys,
                onChange: (keys) => setSelectedRowKeys(keys),
              }
            : false
        }
        tableAlertOptionRender={() => (
          <Space>
            <a onClick={() => handleBulkDispatch(selectedRowKeys)}>下发选中</a>
            <a onClick={() => setSelectedRowKeys([])}>取消选择</a>
          </Space>
        )}
        toolBarRender={() => [
          canImport && <ImportButton
            key="import"
            buttonText="上传简历"
            title="上传简历（简历列表 + 简历包），上传后自动处理"
            fields={RESUME_IMPORT_FIELDS}
              onDone={handleImported}
          />,
          canRunPipeline && <Button
            key="process"
            type="primary"
            icon={<PlayCircleOutlined />}
            loading={processing}
            onClick={handleProcessSelectedStatuses}
          >
            处理简历
          </Button>,
          canImport && <Button
            key="undo"
            icon={<UndoOutlined />}
            disabled={!undo.available}
            onClick={handleUndo}
          >
            撤销上次上传
          </Button>,
          hasPermission('attempt.dispatch') && <Button
            key="dispatch-selected"
            disabled={!selectedRowKeys.length}
            loading={bulkDispatching}
            onClick={() => handleBulkDispatch(selectedRowKeys)}
          >
            下发选中{selectedRowKeys.length ? `(${selectedRowKeys.length})` : ''}
          </Button>,
          hasPermission('attempt.dispatch') && <Button
            key="dispatch-all"
            loading={bulkDispatching}
            onClick={() => handleBulkDispatch([])}
          >
            一键全部下发
          </Button>,
          (hasPermission('resume.view') || hasPermission('attempt.export')) && <Button
            key="export"
            icon={<DownloadOutlined />}
            loading={exporting}
            onClick={handleExport}
          >
            导出
          </Button>,
        ].filter(Boolean)}
        request={async (params) => {
          const {
            current,
            pageSize,
          } = params
          const normalizedFilters = normalizeTableFilters(tableFilters, [
            'name',
            'highest_major',
            'current_rank',
            'current_apply_id',
            'current_entity',
            'current_position_name',
            'job_department_name',
            'current_job_category',
            'school_tag',
            'system_status',
            'workflow_status',
            'reason_type',
            'allocation_source',
            'contact_name',
            'sub_contact_name',
            'attempt_status',
          ])
          const query = {
            system_status: toFilterValue(normalizedFilters.system_status),
            name: toFilterValue(normalizedFilters.name),
            highest_major_in: toFilterValue(normalizedFilters.highest_major),
            current_rank_in: toFilterValue(normalizedFilters.current_rank),
            current_apply_id: toFilterValue(normalizedFilters.current_apply_id),
            current_entity_in: toFilterValue(normalizedFilters.current_entity),
            current_position_name_in: toFilterValue(normalizedFilters.current_position_name),
            job_department_name_in: toFilterValue(normalizedFilters.job_department_name),
            current_job_category_in: toFilterValue(normalizedFilters.current_job_category),
            school_tag_in: toFilterValue(normalizedFilters.school_tag),
            workflow_status: toFilterValue(normalizedFilters.workflow_status),
            reason_type: toFilterValue(normalizedFilters.reason_type),
            allocation_source: toFilterValue(normalizedFilters.allocation_source),
            contact_name: toFilterValue(normalizedFilters.contact_name),
            sub_contact_name: toFilterValue(normalizedFilters.sub_contact_name),
            attempt_status: toFilterValue(normalizedFilters.attempt_status),
          }
          setLastQuery(query)
          try {
            const { data } = await fetchCandidates({
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
      <Modal
        title="处理简历"
        open={processModalOpen}
        okText="开始处理"
        cancelText="取消"
        confirmLoading={processing}
        okButtonProps={{ disabled: !processStatusSelection.length }}
        onOk={handleConfirmProcess}
        onCancel={() => {
          if (!processing) setProcessModalOpen(false)
        }}
      >
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          <Typography.Text>
            选择需要重新处理的系统简历状态。系统会按当前表格的其它筛选条件限定范围，并保留历史分配与反馈记录。
          </Typography.Text>
          <Space>
            <Typography.Text>当前系统分配模式：</Typography.Text>
            <Tag color={allocationMode.mode === 'ai' ? 'purple' : 'blue'}>
              {allocationMode.mode === 'ai' ? 'AI 分配' : '规则分配'}
            </Tag>
            {allocationMode.mode === 'ai' && !allocationMode.ai_ready && (
              <Typography.Text type="danger">模型连接尚未测试成功</Typography.Text>
            )}
          </Space>
          <Checkbox.Group
            value={processStatusSelection}
            onChange={setProcessStatusSelection}
            style={{ width: '100%' }}
          >
            <Space direction="vertical">
              {Object.entries(SYSTEM_STATUS_OPTIONS).map(([value, item]) => (
                <Checkbox key={value} value={value}>
                  {item.text}
                </Checkbox>
              ))}
            </Space>
          </Checkbox.Group>
        </Space>
      </Modal>
      <Drawer
        title={detailRecord ? `${detailRecord.name} 的简历详情` : '简历详情'}
        width={1100}
        open={!!detailRecord}
        onClose={() => setDetailRecord(null)}
      >
        {detailRecord && (
          <>
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="姓名">{detailRecord.name}</Descriptions.Item>
              <Descriptions.Item label="手机">{detailRecord.phone || '-'}</Descriptions.Item>
              <Descriptions.Item label="最高学历专业">
                {detailRecord.highest_major || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="第一学历院校">
                {detailRecord.first_degree_school || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="第一学历标签">
                {detailRecord.first_degree_platform || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="最高学历院校">
                {detailRecord.highest_degree_school || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="最高学历标签">
                {detailRecord.highest_degree_platform || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="当前志愿">
                {detailRecord.current_rank || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="当前应聘ID">
                {detailRecord.current_apply_id || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="岗位部门">
                {detailRecord.job_department_name || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="系统简历状态">
                {detailRecord.system_status_label || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="流程状态">
                {WORKFLOW_STATUS[detailRecord.workflow_status]?.text || detailRecord.workflow_status || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="原因" span={2}>
                <Space>
                  <Tag color={REASON_TYPE[detailRecord.reason_type || 'none']?.color || 'default'}>
                    {REASON_TYPE[detailRecord.reason_type || 'none']?.text || '无'}
                  </Tag>
                  <span>{detailRecord.reason_text || '-'}</span>
                </Space>
              </Descriptions.Item>
            </Descriptions>

            {hasPermission('resume.manual_assign') && detailRecord.current_resume && (
              <Button
                style={{ marginTop: 16 }}
                onClick={() => openManualAssign(detailRecord.current_resume)}
              >
                手动强制分配当前志愿
              </Button>
            )}

            <ResizableTable
              style={{ marginTop: 16 }}
              title={() => '投递志愿'}
              rowKey="id"
              size="small"
              pagination={false}
              dataSource={detailRecord.resumes || []}
              columns={[
                {
                  title: '志愿',
                  dataIndex: 'volunteer_rank',
                  width: 70,
                  ...localTextColumnFilter('volunteer_rank', '筛选志愿'),
                },
                {
                  title: '应聘ID',
                  dataIndex: 'apply_id',
                  width: 110,
                  ...localTextColumnFilter('apply_id', '筛选应聘ID'),
                },
                {
                  title: '主体',
                  dataIndex: 'entity',
                  width: 100,
                  ...localTextColumnFilter('entity', '筛选主体'),
                },
                {
                  title: '投递岗位',
                  dataIndex: 'position_name',
                  ellipsis: true,
                  ...localTextColumnFilter('position_name', '筛选投递岗位'),
                },
                {
                  title: '岗位类别',
                  dataIndex: 'job_category',
                  width: 110,
                  ...localTextColumnFilter('job_category', '筛选岗位类别'),
                },
                {
                  title: '应聘状态',
                  dataIndex: 'status',
                  width: 100,
                  ...localTextColumnFilter('status', '筛选应聘状态'),
                },
                {
                  title: '预览',
                  valueType: 'option',
                  width: 70,
                  render: (_, resume) =>
                    resume.resume_file ? (
                      <a onClick={() => setPreviewRecord(resume)}>预览</a>
                    ) : (
                      <Tooltip title="该投递暂无简历文件">
                        <Typography.Text type="secondary">预览</Typography.Text>
                      </Tooltip>
                    ),
                },
              ]}
            />

            <div style={{ marginTop: 16 }}>
              <Typography.Title level={5} style={{ marginTop: 0 }}>
                简历预览
              </Typography.Title>
              <ResumePreview
                resume={previewRecord}
                attemptId={isContact ? detailRecord.current_attempt?.id : undefined}
              />
            </div>

            <ResizableTable
              style={{ marginTop: 16 }}
              title={() => '分配尝试'}
              rowKey="id"
              size="small"
              pagination={false}
              dataSource={detailRecord.attempts || []}
              locale={{ emptyText: '暂无分配尝试' }}
              columns={[
                { title: '次序', dataIndex: 'attempt_no', width: 70 },
                {
                  title: '来源',
                  dataIndex: 'source',
                  width: 80,
                  ...localSelectColumnFilter('source', [
                    { value: 'rule', text: '规则' },
                    { value: 'ai', text: 'AI' },
                    { value: 'manual', text: '手动' },
                  ]),
                  render: (value) => SOURCE_TEXT[value] || value || '-',
                },
                {
                  title: '投递岗位',
                  dataIndex: 'position_name',
                  ellipsis: true,
                  ...localTextColumnFilter('position_name', '筛选投递岗位'),
                },
                {
                  title: '二级接口人',
                  dataIndex: 'contact_name',
                  width: 110,
                  ...localTextColumnFilter('contact_name', '筛选二级接口人'),
                },
                {
                  title: '三级接口人',
                  dataIndex: 'sub_contact_name',
                  width: 110,
                  ...localTextColumnFilter('sub_contact_name', '筛选三级接口人'),
                },
                {
                  title: '原因',
                  key: 'reason',
                  width: 220,
                  ellipsis: true,
                  ...textColumnFilter('筛选原因'),
                  onFilter: (value, attempt) =>
                    String(
                      attempt.manual_reason ||
                        attempt.match_reason ||
                        attempt.feedback_note ||
                        '',
                    )
                      .toLowerCase()
                      .includes(String(value).toLowerCase()),
                  render: (_, attempt) =>
                    attempt.manual_reason || attempt.match_reason || attempt.feedback_note || '-',
                },
                {
                  title: '状态',
                  dataIndex: 'status',
                  width: 100,
                  ...localSelectColumnFilter(
                    'status',
                    Object.entries(ATTEMPT_STATUS).map(([value, item]) => ({
                      value,
                      text: item.text,
                    })),
                  ),
                  render: (value) => (
                    <Tag color={ATTEMPT_STATUS[value]?.color || 'default'}>
                      {ATTEMPT_STATUS[value]?.text || value || '-'}
                    </Tag>
                  ),
                },
                {
                  title: '反馈',
                  dataIndex: 'feedback_result',
                  width: 100,
                  ...localSelectColumnFilter('feedback_result', [
                    { value: 'passed', text: '通过' },
                    { value: 'rejected', text: '未通过' },
                  ]),
                  render: (value) =>
                    value === 'passed' ? '通过' : value === 'rejected' ? '未通过' : '-',
                },
                {
                  title: '备注',
                  dataIndex: 'feedback_note',
                  ellipsis: true,
                  ...localTextColumnFilter('feedback_note', '筛选备注'),
                },
              ]}
            />

            {canViewAgentDecisions && (
              <ResizableTable
                style={{ marginTop: 16 }}
                title={() => 'AI 筛选决策'}
                rowKey="id"
                size="small"
                loading={agentDecisionsLoading}
                pagination={false}
                dataSource={agentDecisions}
                locale={{ emptyText: '暂无 AI 筛选决策' }}
                columns={[
                  {
                    title: '结论',
                    key: 'recommendation',
                    width: 100,
                    ...selectColumnFilter([
                      { value: 'error', text: '处理失败' },
                      { value: 'dispatch', text: '建议下发' },
                      { value: 'review', text: '人工复核' },
                      { value: 'archive', text: '建议归档' },
                    ]),
                    onFilter: (value, decision) =>
                      value === 'error'
                        ? Boolean(decision.error_code)
                        : !decision.error_code && decision.recommendation === value,
                    render: (_, decision) =>
                      decision.error_code ? (
                        <Tag color="error">处理失败</Tag>
                      ) : (
                        <Tag color={decision.recommendation === 'dispatch' ? 'success' : decision.recommendation === 'review' ? 'warning' : 'default'}>
                          {decision.recommendation === 'dispatch' ? '建议下发' : decision.recommendation === 'review' ? '人工复核' : decision.recommendation === 'archive' ? '建议归档' : '-'}
                        </Tag>
                      ),
                  },
                  {
                    title: '置信度',
                    dataIndex: 'confidence_score',
                    width: 90,
                    render: (value) => (value == null ? '-' : `${Math.round(value * 100)}%`),
                  },
                  {
                    title: '推荐岗位',
                    dataIndex: 'recommended_job_name',
                    ellipsis: true,
                    ...localTextColumnFilter('recommended_job_name', '筛选推荐岗位'),
                  },
                  {
                    title: '摘要/失败原因',
                    key: 'summary',
                    width: 300,
                    ellipsis: true,
                    ...textColumnFilter('筛选摘要或失败原因'),
                    onFilter: (value, decision) =>
                      String(
                        decision.error_message || decision.summary || decision.reason || '',
                      )
                        .toLowerCase()
                        .includes(String(value).toLowerCase()),
                    render: (_, decision) =>
                      decision.error_message || decision.summary || decision.reason || '-',
                  },
                  {
                    title: '操作',
                    width: 145,
                    render: (_, decision) => (
                      <Space>
                        <a onClick={() => setAgentDecisionDetail(decision)}>详情</a>
                        {(decision.error_code || decision.recommendation === 'archive') && hasPermission('attempt.dispatch') && (
                          <Tooltip title={allocationMode.mode !== 'ai' || !allocationMode.ai_ready ? 'AI 分配未开启或模型连接未测试成功' : ''}>
                            <Button
                              type="link"
                              size="small"
                              disabled={allocationMode.mode !== 'ai' || !allocationMode.ai_ready}
                              loading={retryingDecisionId === decision.id}
                              onClick={() => handleRetryAgentDecision(decision)}
                            >
                              重试 AI
                            </Button>
                          </Tooltip>
                        )}
                      </Space>
                    ),
                  },
                ]}
              />
            )}
          </>
        )}
      </Drawer>
      <Modal
        title="AI 筛选决策详情"
        open={Boolean(agentDecisionDetail)}
        width={760}
        footer={null}
        onCancel={() => setAgentDecisionDetail(null)}
      >
        {agentDecisionDetail && (
          <Descriptions column={2} bordered size="small">
            <Descriptions.Item label="建议">
              {agentDecisionDetail.recommendation || '无有效建议'}
            </Descriptions.Item>
            <Descriptions.Item label="置信度">
              {agentDecisionDetail.confidence_score == null ? '-' : `${Math.round(agentDecisionDetail.confidence_score * 100)}%`}
            </Descriptions.Item>
            <Descriptions.Item label="推荐岗位">{agentDecisionDetail.recommended_job_name || '-'}</Descriptions.Item>
            <Descriptions.Item label="推荐二级部门">{agentDecisionDetail.recommended_department_name || '-'}</Descriptions.Item>
            <Descriptions.Item label="摘要" span={2}>{agentDecisionDetail.summary || '-'}</Descriptions.Item>
            <Descriptions.Item label="理由" span={2}>{agentDecisionDetail.reason || '-'}</Descriptions.Item>
            <Descriptions.Item label="简历证据" span={2}>{(agentDecisionDetail.evidence || []).join('；') || '-'}</Descriptions.Item>
            <Descriptions.Item label="风险点" span={2}>{(agentDecisionDetail.risks || []).join('；') || '-'}</Descriptions.Item>
            {agentDecisionDetail.error_code && (
              <Descriptions.Item label={`失败：${agentDecisionDetail.error_code}`} span={2}>
                {agentDecisionDetail.error_message || '-'}
              </Descriptions.Item>
            )}
          </Descriptions>
        )}
      </Modal>
      <Modal
        title={manualModal.attempt ? 'AI 复核转人工分配' : '手动强制分配当前志愿'}
        open={manualModal.open}
        confirmLoading={manualModal.loading}
        onOk={handleManualAssign}
        onCancel={() => setManualModal({ open: false, resume: null, attempt: null, contacts: [], contactId: undefined, secondaryId: undefined, reason: '', loading: false })}
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
              label: `${contact.name}（${contact.contact_level === 'secondary' ? '二级' : '三级'} / ${contact.department_name || '未绑定部门'} / ${contact.employee_no}）`,
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
        onCancel={() => setAssignModal({ open: false, record: null, contacts: [], selected: undefined, loading: false })}
        okText="转派"
      >
        <Select
          style={{ width: '100%' }}
          placeholder="选择本二级部门下的三级接口人"
          value={assignModal.selected}
          options={assignModal.contacts.map((contact) => ({
            value: contact.id,
            label: `${contact.name}（${contact.employee_no} / ${contact.department_name || '未绑定部门'}）`,
          }))}
          onChange={(value) => setAssignModal((previous) => ({ ...previous, selected: value }))}
        />
      </Modal>
      <Modal
        title="提交筛选反馈"
        open={feedbackModal.open}
        confirmLoading={feedbackModal.loading}
        onOk={handleFeedback}
        onCancel={() => setFeedbackModal({ open: false, record: null, result: 'passed', note: '', loading: false })}
        okText="提交反馈"
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Select
            style={{ width: '100%' }}
            value={feedbackModal.result}
            options={[
              { value: 'passed', label: '通过' },
              { value: 'rejected', label: '不通过' },
            ]}
            onChange={(value) => setFeedbackModal((previous) => ({ ...previous, result: value }))}
          />
          <Input.TextArea
            rows={4}
            placeholder="反馈备注（可选）"
            value={feedbackModal.note}
            onChange={(event) => setFeedbackModal((previous) => ({ ...previous, note: event.target.value }))}
          />
        </Space>
      </Modal>
    </PageContainer>
  )
}
