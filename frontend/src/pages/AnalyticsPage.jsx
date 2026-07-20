import { useCallback, useEffect, useMemo, useState } from 'react'
import { PageContainer } from '@ant-design/pro-components'
import {
  Alert,
  Button,
  Card,
  Col,
  DatePicker,
  Empty,
  Row,
  Select,
  Skeleton,
  Spin,
  Tag,
  Typography,
} from 'antd'
import {
  CalendarOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  CommentOutlined,
  DeploymentUnitOutlined,
  ReloadOutlined,
  SearchOutlined,
  SendOutlined,
  TeamOutlined,
} from '@ant-design/icons'
import { fetchRecruitmentOverview } from '../api/services'
import {
  DoughnutChartCard,
  HorizontalBarChartCard,
} from './analytics/DashboardCharts'
import './AnalyticsPage.css'

const numberFormatter = new Intl.NumberFormat('zh-CN')

function formatCount(value) {
  return numberFormatter.format(Number(value || 0))
}

function formatRate(value) {
  return `${Number(value || 0).toFixed(1)}%`
}

function formatDuration(value) {
  if (value == null) return '暂无数据'
  const hours = Number(value)
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))} 分钟`
  if (hours >= 48) return `${(hours / 24).toFixed(1)} 天`
  return `${hours.toFixed(hours < 10 ? 1 : 0)} 小时`
}

function SectionHeading({ title, description }) {
  return (
    <div className="analytics-section-heading">
      <Typography.Title level={4}>{title}</Typography.Title>
      {description ? <Typography.Text type="secondary">{description}</Typography.Text> : null}
    </div>
  )
}

function FilterField({ label, className = '', children }) {
  return (
    <label className={`analytics-filter-field ${className}`}>
      <Typography.Text type="secondary">{label}</Typography.Text>
      {children}
    </label>
  )
}

function MetricCard({ title, value, icon, tone, rate, detail }) {
  return (
    <Card className={`analytics-metric-card analytics-metric-card--${tone}`}>
      <span className="analytics-metric-icon" aria-hidden="true">{icon}</span>
      <Typography.Text className="analytics-metric-label">{title}</Typography.Text>
      <strong className="analytics-metric-value">{formatCount(value)}</strong>
      <div className="analytics-metric-footer">
        {rate == null ? null : <Tag bordered={false}>{formatRate(rate)}</Tag>}
        <span>{detail}</span>
      </div>
    </Card>
  )
}

function EfficiencyStrip({ values = {} }) {
  const items = [
    ['导入至分配', values.to_allocation, DeploymentUnitOutlined],
    ['导入至下发', values.to_dispatch, SendOutlined],
    ['导入至反馈', values.to_feedback, CommentOutlined],
  ]
  return (
    <Card className="analytics-efficiency-strip">
      {items.map(([label, value, Icon]) => (
        <div className="analytics-efficiency-item" key={label}>
          <span className="analytics-efficiency-icon"><Icon /></span>
          <div>
            <Typography.Text type="secondary">{label}</Typography.Text>
            <strong>{formatDuration(value)}</strong>
          </div>
          <ClockCircleOutlined className="analytics-efficiency-clock" />
        </div>
      ))}
    </Card>
  )
}

export default function AnalyticsPage() {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [data, setData] = useState(null)
  const [filters, setFilters] = useState({})
  const [dateRange, setDateRange] = useState(null)

  const load = useCallback(async (nextFilters = {}) => {
    setLoading(true)
    setError('')
    try {
      const response = await fetchRecruitmentOverview(nextFilters)
      setData(response.data)
    } catch (requestError) {
      setError(requestError?.response?.data?.detail || '招聘分析数据加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const options = data?.filter_options || {}
  const activeRange = data?.filters
    ? `${data.filters.date_from} 至 ${data.filters.date_to}`
    : '最近 30 天'
  const asOf = useMemo(() => {
    if (!data?.data_as_of) return '-'
    return new Date(data.data_as_of).toLocaleString('zh-CN', { hour12: false })
  }, [data?.data_as_of])

  const apply = () => load(filters)
  const reset = () => {
    setFilters({})
    setDateRange(null)
    load({})
  }
  const initialLoading = loading && !data
  const summary = data?.summary || {}
  const conversion = data?.conversion || {}
  const pipelineRows = [
    { key: 'candidate', label: '候选人', count: summary.candidate_count },
    { key: 'allocated', label: '生成分配', count: summary.allocated_count },
    { key: 'dispatched', label: '完成下发', count: summary.dispatched_count },
    { key: 'feedback', label: '收到反馈', count: summary.feedback_count },
    { key: 'passed', label: '最终通过', count: summary.passed_count },
  ]

  return (
    <PageContainer
      className="analytics-page"
      title="DashBoard"
      content="聚焦候选规模、转化效率与招聘结果，所有阶段指标按候选人去重。"
      extra={(
        <div className="analytics-as-of">
          <CalendarOutlined />
          <span>数据截至</span>
          <strong>{asOf}</strong>
        </div>
      )}
    >
      {error ? (
        <Alert
          className="analytics-alert"
          type="error"
          showIcon
          message={error}
          action={<Button size="small" onClick={() => load(filters)}>重试</Button>}
        />
      ) : null}

      {initialLoading ? (
        <Card className="analytics-loading-card">
          <Skeleton active paragraph={{ rows: 8 }} />
        </Card>
      ) : data ? (
        <Spin spinning={loading}>
          <div className="analytics-content">
            <section className="analytics-overview-section">
              <div className="analytics-overview-toolbar">
                <div className="analytics-inline-filter">
                  <FilterField label="时间区间" className="analytics-filter-field--range">
                    <DatePicker.RangePicker
                      value={dateRange}
                      onChange={(range, dateStrings) => {
                        setDateRange(range)
                        setFilters((current) => ({
                          ...current,
                          date_from: dateStrings?.[0] || undefined,
                          date_to: dateStrings?.[1] || undefined,
                        }))
                      }}
                    />
                  </FilterField>
                  <FilterField label="二级部门">
                    <Select
                      allowClear
                      value={filters.department_id}
                      showSearch
                      optionFilterProp="label"
                      placeholder="全部部门"
                      options={options.departments || []}
                      onChange={(value) => setFilters((current) => ({ ...current, department_id: value }))}
                    />
                  </FilterField>
                  <div className="analytics-filter-actions">
                    <Button type="primary" icon={<SearchOutlined />} onClick={apply}>查询</Button>
                    <Button icon={<ReloadOutlined />} onClick={reset}>重置</Button>
                  </div>
                </div>
                <div className="analytics-filter-note">
                  <CalendarOutlined />
                  <Typography.Text>当前范围：{activeRange}</Typography.Text>
                </div>
              </div>

              <div className="analytics-metric-grid">
                <MetricCard
                  title="候选人数"
                  value={summary.candidate_count}
                  icon={<TeamOutlined />}
                  tone="primary"
                  detail={`投递 ${formatCount(summary.resume_count)} · 已分类 ${formatCount(summary.classified_count)}`}
                />
                <MetricCard
                  title="已生成分配"
                  value={summary.allocated_count}
                  icon={<DeploymentUnitOutlined />}
                  tone="violet"
                  rate={conversion.allocated_rate}
                  detail="候选人分配转化率"
                />
                <MetricCard
                  title="已下发"
                  value={summary.dispatched_count}
                  icon={<SendOutlined />}
                  tone="cyan"
                  rate={conversion.dispatched_rate}
                  detail="候选人下发转化率"
                />
                <MetricCard
                  title="已反馈"
                  value={summary.feedback_count}
                  icon={<CommentOutlined />}
                  tone="warning"
                  rate={conversion.feedback_rate}
                  detail="候选人反馈转化率"
                />
                <MetricCard
                  title="已通过"
                  value={summary.passed_count}
                  icon={<CheckCircleOutlined />}
                  tone="success"
                  rate={conversion.passed_rate}
                  detail={`已归档 ${formatCount(summary.archived_count)}`}
                />
              </div>
            </section>

            <section>
              <SectionHeading title="招聘概览" description="分配来源、流程转化与 AI 建议构成" />
              <Row gutter={[16, 16]} className="analytics-equal-row">
                <Col xs={24} xl={7}>
                  <DoughnutChartCard title="分配来源" rows={data.source_distribution} />
                </Col>
                <Col xs={24} xl={10}>
                  <HorizontalBarChartCard
                    title="招聘流程"
                    rows={pipelineRows}
                    palette="pipeline"
                  />
                </Col>
                <Col xs={24} xl={7}>
                  <DoughnutChartCard title="AI 建议分布" rows={data.ai_recommendation_distribution} />
                </Col>
              </Row>
            </section>

            <section>
              <SectionHeading title="处理效率" description="候选人从导入到关键阶段的平均耗时" />
              <EfficiencyStrip values={data.average_hours} />
            </section>

            <section>
              <SectionHeading title="岗位与人才结构" description="识别需求集中度和候选人结构分布" />
              <Row gutter={[16, 16]} className="analytics-equal-row">
                <Col xs={24} lg={12}>
                  <HorizontalBarChartCard title="岗位排行" rows={data.job_ranking} />
                </Col>
                <Col xs={24} lg={12}>
                  <HorizontalBarChartCard title="二级部门排行" rows={data.department_ranking} />
                </Col>
                <Col xs={24} lg={12}>
                  <DoughnutChartCard title="院校标签" rows={data.school_tag_ranking} />
                </Col>
                <Col xs={24} lg={12}>
                  <DoughnutChartCard title="最高学历" rows={data.education_distribution} />
                </Col>
              </Row>
            </section>

            <section>
              <SectionHeading title="结果诊断" description="集中查看 AI 异常、归档和未通过原因" />
              <Row gutter={[16, 16]} className="analytics-equal-row">
                <Col xs={24} xl={8}>
                  <DoughnutChartCard
                    title="AI 错误码"
                    rows={data.ai_error_distribution}
                    successWhenEmpty
                  />
                </Col>
                <Col xs={24} xl={8}>
                  <DoughnutChartCard title="归档原因" rows={data.archive_reason_distribution} />
                </Col>
                <Col xs={24} xl={8}>
                  <DoughnutChartCard title="未通过原因" rows={data.rejection_reason_distribution} />
                </Col>
              </Row>
            </section>
          </div>
        </Spin>
      ) : !error ? (
        <Card className="analytics-empty-card">
          <Empty description="暂无招聘分析数据" />
        </Card>
      ) : null}
    </PageContainer>
  )
}
