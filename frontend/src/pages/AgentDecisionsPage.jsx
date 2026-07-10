import { useRef, useState } from 'react'
import { PageContainer, ProTable } from '@ant-design/pro-components'
import { Button, Descriptions, Drawer, List, Progress, Space, Tag, message } from 'antd'
import { fetchAgentDecisions, retryAgentDecision } from '../api/services'

const RECOMMENDATIONS = {
  dispatch: { text: '建议下发', color: 'green' },
  review: { text: '人工复核', color: 'orange' },
  archive: { text: '建议归档', color: 'default' },
}

const SCORE_LABELS = {
  major_match: '专业匹配',
  skills_match: '技能匹配',
  experience_evidence: '项目/实习证据',
  job_requirement: '岗位需求覆盖',
  department_certainty: '部门确定性',
  resume_quality: '简历文本质量',
}

export default function AgentDecisionsPage() {
  const actionRef = useRef()
  const [detail, setDetail] = useState(null)
  const [retrying, setRetrying] = useState(null)

  const retry = async (record) => {
    setRetrying(record.id)
    try {
      const { data } = await retryAgentDecision(record.id)
      message.success(data?.attempt ? 'AI 已重试并生成分配尝试' : 'AI 已重试，结果需人工处理')
      setDetail(data?.decision || null)
      actionRef.current?.reload()
    } finally {
      setRetrying(null)
    }
  }

  const columns = [
    { title: '候选人', dataIndex: 'candidate_name', width: 120 },
    { title: '应聘ID', dataIndex: 'apply_id', width: 130, search: false },
    { title: '当前志愿', dataIndex: 'position_name', ellipsis: true, search: false },
    {
      title: '建议',
      dataIndex: 'recommendation',
      valueType: 'select',
      valueEnum: Object.fromEntries(
        Object.entries(RECOMMENDATIONS).map(([key, value]) => [key, { text: value.text }]),
      ),
      render: (_, record) =>
        record.error_code ? (
          <Tag color="red">处理失败</Tag>
        ) : (
          <Tag color={RECOMMENDATIONS[record.recommendation]?.color}>
            {RECOMMENDATIONS[record.recommendation]?.text || '-'}
          </Tag>
        ),
    },
    {
      title: '置信度',
      dataIndex: 'confidence_score',
      search: false,
      width: 100,
      render: (value) => (value == null ? '-' : `${Math.round(value * 100)}%`),
    },
    { title: '推荐岗位', dataIndex: 'recommended_job_name', search: false, ellipsis: true },
    { title: '推荐部门', dataIndex: 'recommended_department_name', search: false },
    { title: '接口人', dataIndex: 'recommended_contact_name', search: false },
    { title: '模型', dataIndex: 'model_name', search: false, width: 130 },
    {
      title: '操作',
      valueType: 'option',
      width: 140,
      render: (_, record) => (
        <Space>
          <a onClick={() => setDetail(record)}>详情</a>
          {(record.error_code || record.recommendation === 'archive') && (
            <Button type="link" size="small" loading={retrying === record.id} onClick={() => retry(record)}>
              重试 AI
            </Button>
          )}
        </Space>
      ),
    },
  ]

  return (
    <PageContainer title="AI 筛选决策" subTitle="查看结构化评分、简历证据、风险与失败原因">
      <ProTable
        rowKey="id"
        actionRef={actionRef}
        columns={columns}
        request={async (params) => {
          const { current, pageSize, ...filters } = params
          const { data } = await fetchAgentDecisions({ page: current, page_size: pageSize, ...filters })
          return { data: data.results || [], total: data.count || 0, success: true }
        }}
        scroll={{ x: 1250 }}
        search={{ labelWidth: 'auto' }}
      />
      <Drawer title="AI 决策详情" width={720} open={Boolean(detail)} onClose={() => setDetail(null)}>
        {detail && (
          <>
            <Descriptions column={2} bordered size="small">
              <Descriptions.Item label="候选人">{detail.candidate_name}</Descriptions.Item>
              <Descriptions.Item label="应聘ID">{detail.apply_id}</Descriptions.Item>
              <Descriptions.Item label="当前志愿">{detail.position_name}</Descriptions.Item>
              <Descriptions.Item label="置信度">
                {detail.confidence_score == null ? '-' : `${Math.round(detail.confidence_score * 100)}%`}
              </Descriptions.Item>
              <Descriptions.Item label="推荐岗位">{detail.recommended_job_name || '-'}</Descriptions.Item>
              <Descriptions.Item label="推荐部门">{detail.recommended_department_name || '-'}</Descriptions.Item>
              <Descriptions.Item label="推荐接口人">{detail.recommended_contact_name || '-'}</Descriptions.Item>
              <Descriptions.Item label="版本">{detail.prompt_version} / {detail.decision_version}</Descriptions.Item>
              <Descriptions.Item label="摘要" span={2}>{detail.summary || '-'}</Descriptions.Item>
              <Descriptions.Item label="理由" span={2}>{detail.reason || '-'}</Descriptions.Item>
              {detail.error_code && (
                <Descriptions.Item label={`失败：${detail.error_code}`} span={2}>
                  {detail.error_message}
                </Descriptions.Item>
              )}
            </Descriptions>
            <List
              header="分项评分"
              dataSource={Object.entries(detail.score_breakdown || {})}
              renderItem={([key, value]) => (
                <List.Item>
                  <div style={{ width: '100%' }}>
                    <span>{SCORE_LABELS[key] || key}</span>
                    <Progress percent={Math.round(Number(value) * 100)} size="small" />
                  </div>
                </List.Item>
              )}
            />
            <List header="简历证据" dataSource={detail.evidence || []} renderItem={(item) => <List.Item>{item}</List.Item>} />
            <List header="风险点" dataSource={detail.risks || []} renderItem={(item) => <List.Item><Tag color="orange">风险</Tag>{item}</List.Item>} />
          </>
        )}
      </Drawer>
    </PageContainer>
  )
}
