import { useEffect, useMemo, useState } from 'react'
import { Badge, Button, Card, Drawer, Empty, Popconfirm, Progress, Space, Tag, Typography, message } from 'antd'
import { SyncOutlined } from '@ant-design/icons'
import { cancelPipelineRun, fetchPipelineRuns } from '../api/services'

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

function formatTime(value) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '-'
}

function progressOf(run) {
  const stages = run.stages || []
  if (stages.length) {
    const completed = stages.filter((stage) => ['success', 'partial_failed'].includes(stage.status)).length
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

function TaskCard({ run, cancellingId, onCancel }) {
  const percent = progressOf(run)
  const stage = (run.stages || []).find((item) => item.step === run.current_stage)
  const status = STATUS_META[run.status] || { text: run.status || '未知', color: 'default' }
  const scopeSummary = scopeSummaryText(run)
  return (
    <Card size="small" style={{ marginBottom: 12 }}>
      <Space direction="vertical" size={6} style={{ width: '100%' }}>
        <Space style={{ justifyContent: 'space-between', width: '100%' }}>
          <Typography.Text strong>{taskTitle(run)}</Typography.Text>
          <Tag color={status.color}>{status.text}</Tag>
        </Space>
        <Typography.Text type="secondary">
          {run.created_by_username_snapshot || '系统'} · {run.mode === 'ai' ? 'AI 分配' : '规则分配'}
        </Typography.Text>
        <Progress percent={percent} size="small" status={run.status === 'failed' ? 'exception' : undefined} />
        <Typography.Text type="secondary">
          {stage?.label || run.message || '等待任务开始'}
          {run.total_count ? `：${run.processed_count || 0} / ${run.total_count}` : ''}
        </Typography.Text>
        {scopeSummary ? <Typography.Text type="secondary">范围：{scopeSummary}</Typography.Text> : null}
        {(run.failed_count || run.review_count || run.dispatch_count || run.archive_count) ? (
          <Typography.Text type="secondary">
            成功 {run.success_count || 0} · 失败 {run.failed_count || 0} · 待复核 {run.review_count || 0} · 待下发 {run.dispatch_count || 0} · 归档 {run.archive_count || 0}
          </Typography.Text>
        ) : null}
        {run.error ? <Typography.Text type="danger">{run.error}</Typography.Text> : null}
        {run.cancel_requested_at ? (
          <Typography.Text type="secondary">
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
            <Button danger size="small" loading={cancellingId === run.id}>
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
    return () => window.clearInterval(timer)
  }, [])

  const activeRuns = useMemo(() => runs.filter((run) => ACTIVE_STATUSES.has(run.status)), [runs])
  const visibleRuns = useMemo(() => [...activeRuns, ...runs.filter((run) => !ACTIVE_STATUSES.has(run.status))], [activeRuns, runs])

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

  return (
    <>
      <Badge count={activeRuns.length} size="small" offset={[-2, 2]}>
        <Button icon={<SyncOutlined spin={loading} />} onClick={() => setOpen(true)}>
          处理任务
        </Button>
      </Badge>
      <Drawer
        title="处理任务中心"
        open={open}
        onClose={() => setOpen(false)}
        mask={false}
        width={440}
        extra={<Button size="small" onClick={refresh} loading={loading}>刷新</Button>}
      >
        {visibleRuns.length ? visibleRuns.map((run) => <TaskCard key={run.id} run={run} cancellingId={cancellingId} onCancel={cancel} />) : <Empty description="暂无处理任务" />}
      </Drawer>
    </>
  )
}
