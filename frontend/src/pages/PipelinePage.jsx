import { useEffect, useState } from 'react'
import { PageContainer, ProTable } from '@ant-design/pro-components'
import { Card, Button, Radio, Space, Tag, Row, Col, Badge, message } from 'antd'
import { PlayCircleOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { runPipeline, fetchPipelineRuns } from '../api/services'

// Steps. Step2 / Step5 support a rule/AI mode toggle.
const STEPS = [
  { key: 'step1', title: 'Step1 查重与志愿排序', hasMode: false },
  { key: 'step2', title: 'Step2 岗位分类', hasMode: true },
  { key: 'step3', title: 'Step3 院校分类', hasMode: false },
  { key: 'step4', title: 'Step4 需求录入', hasMode: false },
  { key: 'step5', title: 'Step5 简历分配', hasMode: true },
]

const STATUS_BADGE = {
  pending: { status: 'default', text: '未运行' },
  running: { status: 'processing', text: '运行中' },
  success: { status: 'success', text: '完成' },
  failed: { status: 'error', text: '失败' },
}

function StepCard({ step, running, onRun, modes, setMode }) {
  return (
    <Card size="small" title={step.title} style={{ height: '100%' }}>
      <Space direction="vertical" style={{ width: '100%' }} size="middle">
        {step.hasMode ? (
          <Radio.Group
            value={modes[step.key]}
            onChange={(e) => setMode(step.key, e.target.value)}
          >
            <Radio value="rule">规则</Radio>
            <Radio value="ai">AI</Radio>
          </Radio.Group>
        ) : (
          <Tag>规则</Tag>
        )}
        <Button
          type="primary"
          icon={<PlayCircleOutlined />}
          loading={running === step.key}
          onClick={() => onRun(step.key)}
          block
        >
          运行
        </Button>
      </Space>
    </Card>
  )
}

export default function PipelinePage() {
  const [running, setRunning] = useState(null)
  const [modes, setModes] = useState({ step2: 'rule', step5: 'rule' })
  const [runs, setRuns] = useState([])
  const [loading, setLoading] = useState(false)

  const setMode = (key, value) =>
    setModes((prev) => ({ ...prev, [key]: value }))

  const loadRuns = async () => {
    setLoading(true)
    try {
      const { data } = await fetchPipelineRuns({ page: 1, page_size: 20 })
      setRuns(data?.results || [])
    } catch {
      setRuns([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadRuns()
  }, [])

  const handleRun = async (step) => {
    setRunning(step)
    try {
      const { data } = await runPipeline({
        step,
        mode: modes[step] || 'rule',
      })
      message.success(data?.message || `已触发 ${step}`)
      loadRuns()
    } catch {
      // toasted by interceptor
    } finally {
      setRunning(null)
    }
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 70 },
    { title: '步骤', dataIndex: 'step', width: 100 },
    {
      title: '模式',
      dataIndex: 'mode',
      width: 90,
      render: (v) => (v ? <Tag color={v === 'ai' ? 'purple' : 'blue'}>{v}</Tag> : '-'),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (v) => {
        const conf = STATUS_BADGE[v] || { status: 'default', text: v }
        return <Badge status={conf.status} text={conf.text} />
      },
    },
    { title: '开始时间', dataIndex: 'created_at', width: 180 },
    { title: '结束时间', dataIndex: 'finished_at', width: 180 },
    { title: '信息', dataIndex: 'message', ellipsis: true },
  ]

  return (
    <PageContainer
      title="流水线运行"
      content="分步触发或一键全流程；Step2 / Step5 可选择规则或 AI 模式。"
    >
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={16}>
          {STEPS.map((step) => (
            <Col key={step.key} xs={24} sm={12} md={8} lg={6} xxl={4} style={{ marginBottom: 16 }}>
              <StepCard
                step={step}
                running={running}
                onRun={handleRun}
                modes={modes}
                setMode={setMode}
              />
            </Col>
          ))}
        </Row>
        <Button
          icon={<ThunderboltOutlined />}
          loading={running === 'all'}
          onClick={() => handleRun('all')}
        >
          一键全流程
        </Button>
      </Card>

      <ProTable
        headerTitle="运行记录"
        rowKey="id"
        columns={columns}
        dataSource={runs}
        loading={loading}
        search={false}
        options={{ reload: loadRuns, density: false, setting: false }}
        pagination={{ pageSize: 10 }}
      />
    </PageContainer>
  )
}
