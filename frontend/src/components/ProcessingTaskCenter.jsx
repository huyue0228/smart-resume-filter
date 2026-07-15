import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, Badge, Button, Card, Drawer, Empty, Popconfirm, Progress, Space, Tag, Tooltip, Typography, message } from 'antd'
import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  ExclamationCircleOutlined,
  ReloadOutlined,
  RobotOutlined,
  StopOutlined,
  SyncOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { cancelPipelineRun, fetchPipelineRuns } from '../api/services'
import './ProcessingTaskCenter.css'

const ACTIVE_STATUSES = new Set(['pending', 'running', 'waiting_conflict', 'cancelling'])
const STATUS_META = {
  pending: { text: '排队中', color: 'default' },
  running: { text: '处理中', color: 'processing' },
  waiting_conflict: { text: '等待同一候选人处理', color: 'warning' },
  cancelling: { text: '正在取消', color: 'warning' },
  cancelled: { text: '已取消', color: 'default' },
  success: { text: '已完成', color: 'success' },
  partial_failed: { text: '部分失败', color: 'warning' },
  failed: { text: '失败', color: 'error' },
  undone: { text: '已撤销', color: 'default' },
}
const FINISHED_STATUSES = new Set(['success', 'partial_failed', 'failed', 'cancelled', 'undone'])
const ATTENTION_STATUSES = new Set(['partial_failed', 'failed'])

function formatTime(value) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '-'
}

function formatDuration(value) {
  const totalSeconds = Math.max(0, Math.floor(Number(value) || 0))
  const days = Math.floor(totalSeconds / 86400)
  const hours = Math.floor((totalSeconds % 86400) / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  if (days) return `${days}天${hours ? `${hours}小时` : ''}`
  if (hours) return `${hours}小时${minutes ? `${minutes}分` : ''}`
  if (minutes) return `${minutes}分${seconds ? `${seconds}秒` : ''}`
  return `${seconds}秒`
}

function progressOf(run) {
  const stages = run.stages || []
  if (stages.length) {
    const completed = stages.filter((stage) => ['success', 'partial_failed', 'cancelled'].includes(stage.status)).length
    const active = stages.find((stage) => stage.status === 'running')
    const activePart = active?.total_count
      ? Math.min(1, Number(active.processed_count || 0) / Number(active.total_count))
      : 0
    return Math.round(Math.min(100, ((completed + activePart) / stages.length) * 100))
  }
  return run.total_count
    ? Math.round(Math.min(100, (Number(run.processed_count || 0) / Number(run.total_count)) * 100))
    : 0
}

function taskTitle(run) {
  if (run.step === 'resume_process') return '上传后候选人处理'
  if (run.step === 'step2') return '简历分类、分配与下发'
  return run.step || '处理任务'
}

function scopeSummaryText(run) {
  const summary = run.scope_summary || {}
  const parts = []
  if (summary.candidate_count != null) parts.push(`候选人 ${summary.candidate_count} 名`)
  if (summary.system_statuses?.length) parts.push(`状态 ${summary.system_statuses.join('、')}`)
  if (summary.source) parts.push(`来源 ${summary.source}`)
  return parts.join(' · ')
}

const RESULT_METRICS = [
  { key: 'success', label: '成功' },
  { key: 'failed', label: '失败', danger: true },
  { key: 'review', label: '待复核' },
  { key: 'dispatch', label: '待下发' },
  { key: 'archive', label: '归档' },
  { key: 'skipped', label: '跳过' },
  { key: 'cancelled', label: '取消' },
]

function TaskCard({ run, cancellingId, onCancel, onOpenCandidates }) {
  const percent = progressOf(run)
  const stage = (run.stages || []).find((item) => item.step === run.current_stage)
  const status = STATUS_META[run.status] || { text: run.status || '未知', color: 'default' }
  const scopeSummary = scopeSummaryText(run)
  const hasResults = Boolean(
    run.success_count || run.failed_count || run.review_count || run.dispatch_count || run.archive_count
      || run.skipped_count || run.cancelled_count,
  )
  return (
    <Card
      size="small"
      className={`processing-task-card ${ACTIVE_STATUSES.has(run.status) ? 'is-active' : ''}`}
    >
      <Space direction="vertical" size={12} className="processing-task-card-content">
        <div className="processing-task-heading">
          <div className="processing-task-title-wrap">
            <Typography.Text strong className="processing-task-title">
              {taskTitle(run)}
            </Typography.Text>
            <Typography.Text type="secondary" className="processing-task-id">
              #{run.id}
            </Typography.Text>
          </div>
          <Tag color={status.color} bordered={false} className="processing-task-status">
            {status.text}
          </Tag>
        </div>

        <div className="processing-task-meta">
          <span><UserOutlined /> {run.created_by_username_snapshot || '系统'}</span>
          <span><RobotOutlined /> {run.mode === 'ai' ? 'AI 分配' : '规则分配'}</span>
          <span>提交于 {formatTime(run.created_at)}</span>
        </div>

        <div className="processing-task-primary-metrics">
          <div>
            <span className="processing-task-metric-label">任务耗时</span>
            <strong><ClockCircleOutlined /> {formatDuration(run.elapsed_seconds)}</strong>
          </div>
          <div>
            <span className="processing-task-metric-label">处理进度</span>
            <strong>{percent}%</strong>
          </div>
        </div>

        <Progress
          percent={percent}
          showInfo={false}
          size="small"
          status={run.status === 'failed' ? 'exception' : run.status === 'success' ? 'success' : undefined}
        />

        <div className="processing-task-stage">
          <Typography.Text>
            {stage?.label || run.message || '等待任务开始'}
          </Typography.Text>
          {run.total_count ? (
            <Typography.Text type="secondary">
              {run.processed_count || 0} / {run.total_count}
            </Typography.Text>
          ) : null}
        </div>

        {scopeSummary ? (
          <Typography.Text type="secondary" className="processing-task-scope">
            范围：{scopeSummary}
          </Typography.Text>
        ) : null}

        {hasResults ? (
          <div className="processing-task-results">
            {RESULT_METRICS.map(({ key, label, danger }) => {
              const count = Number(run[`${key}_count`] || 0)
              return (
                <Button
                  key={key}
                  type="text"
                  size="small"
                  disabled={!count || run.mode !== 'ai'}
                  className={danger && count ? 'is-danger' : ''}
                  onClick={() => onOpenCandidates(run, key)}
                  aria-label={`筛选本任务${label}简历 ${count} 名`}
                >
                  <strong>{count}</strong>{label}
                </Button>
              )
            })}
          </div>
        ) : null}

        {run.mode === 'ai' && run.ai_concurrency_limit ? (
          <Typography.Text type="secondary" className="processing-task-audit">
            AI 自适应并发 {run.ai_effective_concurrency || 1}/{run.ai_concurrency_limit}
            {' · '}模型重试 {run.ai_retry_count || 0}
            {' · '}429 限流 {run.ai_rate_limit_count || 0}
          </Typography.Text>
        ) : null}

        {run.error ? <Alert type="error" showIcon message="任务异常" description={run.error} /> : null}
        {run.cancel_requested_at ? (
          <Typography.Text type="secondary" className="processing-task-audit">
            取消请求 {formatTime(run.cancel_requested_at)} · {run.cancelled_at ? `已取消 ${formatTime(run.cancelled_at)}` : '等待安全停止'} · 操作人 {run.cancelled_by_username_snapshot || '系统'}
          </Typography.Text>
        ) : null}
        {ACTIVE_STATUSES.has(run.status) && (
          <Popconfirm
            title="取消处理任务？"
            description="已完成的候选人处理结果会保留，未开始的处理不会继续执行。"
            okText="取消任务"
            cancelText="返回"
            okButtonProps={{ danger: true }}
            onConfirm={() => onCancel(run)}
          >
            <Button danger size="small" icon={<StopOutlined />} loading={cancellingId === run.id}>
              取消任务
            </Button>
          </Popconfirm>
        )}
      </Space>
    </Card>
  )
}

// 常驻于主布局的非模态任务中心：所有有 pipeline.view 权限的 HR/管理员看到同一份服务端任务状态。
export default function ProcessingTaskCenter() {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [runs, setRuns] = useState([])
  const [loading, setLoading] = useState(false)
  const [cancellingId, setCancellingId] = useState(null)

  const refresh = async () => {
    setLoading(true)
    try {
      const { data } = await fetchPipelineRuns({ page_size: 20 })
      setRuns(data?.results || [])
    } catch {
      // 网络短暂不可用时保留上一次任务视图，下一轮轮询会自动恢复。
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
    const timer = window.setInterval(refresh, 2000)
    window.addEventListener('srf:processing-run-created', refresh)
    return () => {
      window.clearInterval(timer)
      window.removeEventListener('srf:processing-run-created', refresh)
    }
  }, [])

  const activeRuns = useMemo(() => runs.filter((run) => ACTIVE_STATUSES.has(run.status)), [runs])
  const visibleRuns = useMemo(() => [...activeRuns, ...runs.filter((run) => !ACTIVE_STATUSES.has(run.status))], [activeRuns, runs])
  const finishedCount = useMemo(() => runs.filter((run) => FINISHED_STATUSES.has(run.status)).length, [runs])
  const attentionCount = useMemo(() => runs.filter((run) => ATTENTION_STATUSES.has(run.status)).length, [runs])

  const cancel = async (run) => {
    setCancellingId(run.id)
    try {
      const { data } = await cancelPipelineRun(run.id)
      message.success(data.status === 'cancelled' ? '任务已取消' : '已请求取消任务')
      await refresh()
    } finally {
      setCancellingId(null)
    }
  }

  const openCandidates = (run, result) => {
    setOpen(false)
    navigate({
      pathname: '/resumes',
      search: `?processing_run_id=${run.id}&processing_result=${result}`,
    })
  }

  return (
    <>
      <Badge count={activeRuns.length} size="small" offset={[-2, 2]}>
        <Button icon={<SyncOutlined spin={loading} />} onClick={() => setOpen(true)}>
          处理任务
        </Button>
      </Badge>
      <Drawer
        title={(
          <div className="processing-task-drawer-title">
            <span>处理任务中心</span>
            <Typography.Text type="secondary">最近 {runs.length} 条任务</Typography.Text>
          </div>
        )}
        open={open}
        onClose={() => setOpen(false)}
        mask={false}
        width="min(520px, 100vw)"
        className="processing-task-drawer"
        extra={(
          <Tooltip title="刷新任务">
            <Button
              aria-label="刷新任务"
              icon={<ReloadOutlined />}
              onClick={refresh}
              loading={loading}
            />
          </Tooltip>
        )}
      >
        <div className="processing-task-summary" aria-label="最近任务概览">
          <div>
            <SyncOutlined spin={Boolean(activeRuns.length)} />
            <span>进行中</span>
            <strong>{activeRuns.length}</strong>
          </div>
          <div>
            <CheckCircleOutlined />
            <span>已结束</span>
            <strong>{finishedCount}</strong>
          </div>
          <div className={attentionCount ? 'has-attention' : ''}>
            <ExclamationCircleOutlined />
            <span>需关注</span>
            <strong>{attentionCount}</strong>
          </div>
        </div>
        <div className="processing-task-list">
          {visibleRuns.length ? visibleRuns.map((run) => (
            <TaskCard
              key={run.id}
              run={run}
              cancellingId={cancellingId}
              onCancel={cancel}
              onOpenCandidates={openCandidates}
            />
          )) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无处理任务" />}
        </div>
      </Drawer>
    </>
  )
}
