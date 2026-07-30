import { useCallback, useEffect, useMemo, useState } from 'react'
import { PageContainer } from '@ant-design/pro-components'
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Divider,
  Input,
  Modal,
  Popconfirm,
  Row,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import {
  fetchAIPrompts,
  fetchAIPromptVersion,
  fetchAIPromptVersions,
  publishAIPromptDraft,
  resetAIPromptDraft,
  restoreAIPromptVersion,
  saveAIPromptDraft,
  testAIPromptDraft,
} from '../api/services'

const { TextArea } = Input

function formatTime(value) {
  if (!value) return '-'
  return new Date(value).toLocaleString()
}

function apiErrorDetail(error, fallback) {
  return error?.response?.data?.detail || error?.response?.data?.code || fallback
}

export default function PromptManagementPage() {
  const [data, setData] = useState(null)
  const [modules, setModules] = useState({})
  const [loading, setLoading] = useState(true)
  const [action, setAction] = useState('')
  const [history, setHistory] = useState([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyPagination, setHistoryPagination] = useState({
    current: 1,
    pageSize: 10,
    total: 0,
  })
  const [diffVersion, setDiffVersion] = useState(null)
  const [diffLoading, setDiffLoading] = useState(false)

  const loadHistory = useCallback(async (page = 1, pageSize = 10) => {
    setHistoryLoading(true)
    try {
      const { data: response } = await fetchAIPromptVersions({
        page,
        page_size: pageSize,
      })
      setHistory(response.results || [])
      setHistoryPagination({
        current: page,
        pageSize,
        total: response.count || 0,
      })
    } finally {
      setHistoryLoading(false)
    }
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const { data: response } = await fetchAIPrompts()
      setData(response)
      setModules(response.draft.modules)
      await loadHistory(1, 10)
    } catch (error) {
      message.error(apiErrorDetail(error, 'Prompt 管理信息加载失败'))
    } finally {
      setLoading(false)
    }
  }, [loadHistory])

  useEffect(() => {
    load()
  }, [load])

  const dirty = useMemo(
    () => Boolean(data) && JSON.stringify(modules) !== JSON.stringify(data.draft.modules),
    [data, modules],
  )
  const totalChars = useMemo(
    () => Object.values(modules).reduce((sum, value) => sum + String(value || '').length, 0),
    [modules],
  )
  const hasEmptyModule = useMemo(
    () => data?.module_definitions?.some(({ key }) => !String(modules[key] || '').trim()),
    [data, modules],
  )
  const overTotalLimit = Boolean(data && totalChars > data.limits.total_max_chars)

  const replaceDraft = (draft) => {
    setData((current) => ({ ...current, draft }))
    setModules(draft.modules)
  }

  const handleConflict = async (error) => {
    message.error(apiErrorDetail(error, '操作失败'))
    if (error?.response?.status === 409) await load()
  }

  const save = async () => {
    setAction('save')
    try {
      const { data: draft } = await saveAIPromptDraft(
        modules,
        data.draft.lock_version,
      )
      replaceDraft(draft)
      message.success('共享草稿已保存，原测试状态已失效')
    } catch (error) {
      await handleConflict(error)
    } finally {
      setAction('')
    }
  }

  const reset = async (source) => {
    setAction(`reset-${source}`)
    try {
      const { data: draft } = await resetAIPromptDraft(
        source,
        data.draft.lock_version,
      )
      replaceDraft(draft)
      message.success(source === 'active' ? '草稿已恢复为当前激活版本' : '草稿已恢复为系统默认值')
    } catch (error) {
      await handleConflict(error)
    } finally {
      setAction('')
    }
  }

  const testDraft = async () => {
    setAction('test')
    try {
      const { data: response } = await testAIPromptDraft()
      replaceDraft(response.draft)
      message.success(response.detail || '真实模型测试通过')
    } catch (error) {
      message.error(apiErrorDetail(error, 'Prompt 真实模型测试失败'))
      await load()
    } finally {
      setAction('')
    }
  }

  const publish = async () => {
    setAction('publish')
    try {
      const { data: response } = await publishAIPromptDraft(data.draft.lock_version)
      setData((current) => ({
        ...current,
        active: response.active,
        draft: response.draft,
      }))
      setModules(response.draft.modules)
      await loadHistory(1, historyPagination.pageSize)
      message.success(response.detail || 'Prompt 已发布')
    } catch (error) {
      await handleConflict(error)
    } finally {
      setAction('')
    }
  }

  const openDiff = async (version) => {
    setDiffLoading(true)
    try {
      const { data: detail } = await fetchAIPromptVersion(version)
      setDiffVersion(detail)
    } catch (error) {
      message.error(apiErrorDetail(error, '历史版本读取失败'))
    } finally {
      setDiffLoading(false)
    }
  }

  const restore = async (version) => {
    setAction(`restore-${version}`)
    try {
      const { data: draft } = await restoreAIPromptVersion(
        version,
        data.draft.lock_version,
      )
      replaceDraft(draft)
      message.success('历史版本已复制到共享草稿，需重新测试并发布')
    } catch (error) {
      await handleConflict(error)
    } finally {
      setAction('')
    }
  }

  const historyColumns = [
    {
      title: '版本',
      dataIndex: 'version',
      render: (value, record) => (
        <Space>
          <Typography.Text copyable>{value}</Typography.Text>
          {record.status === 'active' && <Tag color="success">当前激活</Tag>}
        </Space>
      ),
    },
    {
      title: '发布序号',
      dataIndex: 'release_sequence',
      width: 100,
      render: (value) => value ?? '-',
    },
    {
      title: '测试模型',
      dataIndex: 'test_model_name',
      render: (value) => value || '-',
    },
    {
      title: '发布时间',
      dataIndex: 'published_at',
      render: formatTime,
    },
    {
      title: '发布人',
      dataIndex: 'published_by_username',
      render: (value) => value || '-',
    },
    {
      title: '操作',
      key: 'actions',
      width: 210,
      render: (_, record) => (
        <Space>
          <Button
            type="link"
            loading={diffLoading}
            onClick={() => openDiff(record.version)}
          >
            查看模块差异
          </Button>
          <Popconfirm
            title="复制该历史版本到共享草稿？"
            description="当前草稿会被覆盖，恢复后仍需重新测试并发布。"
            onConfirm={() => restore(record.version)}
          >
            <Button
              type="link"
              disabled={dirty}
              loading={action === `restore-${record.version}`}
            >
              恢复到草稿
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  if (!data && loading) return <PageContainer title="Prompt 管理" loading />
  if (!data) return <PageContainer title="Prompt 管理" />

  return (
    <PageContainer title="Prompt 管理" loading={loading}>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Alert
          type="info"
          showIcon
          message="五个业务模块整套保存、真实测试和发布"
          description="安全底座、动态数据字段、省份白名单和结构化输出协议由后端固定，不可编辑。发布只影响新提交的 AI 任务；已创建或排队任务继续使用提交时冻结的版本。"
        />

        <Card title="版本与测试状态">
          <Descriptions column={{ xs: 1, sm: 2, lg: 3 }}>
            <Descriptions.Item label="当前激活版本">
              <Tag color="success">{data.active.version}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="草稿状态">
              <Tag color={dirty ? 'warning' : 'default'}>
                {dirty ? '有未保存修改' : '已保存'}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="Prompt 测试">
              <Tag color={data.draft.test_valid ? 'success' : 'warning'}>
                {data.draft.test_valid ? '当前草稿测试有效' : '未测试或已失效'}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="测试模型">
              {data.draft.test_model_name || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="测试时间">
              {formatTime(data.draft.tested_at)}
            </Descriptions.Item>
            <Descriptions.Item label="草稿更新人">
              {data.draft.updated_by_username || '-'}
            </Descriptions.Item>
          </Descriptions>
        </Card>

        <Card
          title="业务 Prompt 模块"
          extra={(
            <Typography.Text type={overTotalLimit ? 'danger' : 'secondary'}>
              总字符数：{totalChars.toLocaleString()} / {data.limits.total_max_chars.toLocaleString()}
            </Typography.Text>
          )}
        >
          <Space direction="vertical" size={20} style={{ width: '100%' }}>
            {data.module_definitions.map((definition) => (
              <div key={definition.key}>
                <Typography.Title level={5} style={{ marginBottom: 4 }}>
                  {definition.order}. {definition.label}
                </Typography.Title>
                <Typography.Paragraph type="secondary">
                  {definition.description}
                </Typography.Paragraph>
                <TextArea
                  aria-label={definition.label}
                  value={modules[definition.key] || ''}
                  autoSize={{ minRows: 5, maxRows: 14 }}
                  maxLength={definition.max_chars}
                  showCount
                  onChange={(event) => {
                    setModules((current) => ({
                      ...current,
                      [definition.key]: event.target.value,
                    }))
                  }}
                />
              </div>
            ))}
          </Space>
          <Divider />
          {(hasEmptyModule || overTotalLimit) && (
            <Alert
              type="error"
              showIcon
              message={hasEmptyModule ? '五个模块均为必填项' : '整套 Prompt 超出总字符限制'}
              style={{ marginBottom: 16 }}
            />
          )}
          <Space wrap>
            <Button
              type="primary"
              loading={action === 'save'}
              disabled={!dirty || hasEmptyModule || overTotalLimit}
              onClick={save}
            >
              保存共享草稿
            </Button>
            <Button
              loading={action === 'test'}
              disabled={dirty || !data.draft.modules}
              onClick={testDraft}
            >
              真实模型测试
            </Button>
            <Popconfirm
              title="发布当前草稿？"
              description="发布只影响新提交的 AI 任务，已创建或排队任务继续使用旧版本。"
              onConfirm={publish}
            >
              <Button
                type="primary"
                danger
                loading={action === 'publish'}
                disabled={dirty || !data.draft.test_valid}
              >
                发布
              </Button>
            </Popconfirm>
            <Popconfirm
              title="用当前激活版本覆盖共享草稿？"
              onConfirm={() => reset('active')}
            >
              <Button loading={action === 'reset-active'}>恢复激活值</Button>
            </Popconfirm>
            <Popconfirm
              title="用系统默认值覆盖共享草稿？"
              onConfirm={() => reset('default')}
            >
              <Button loading={action === 'reset-default'}>恢复默认值</Button>
            </Popconfirm>
          </Space>
        </Card>

        <Card title="最终组装顺序（只读）">
          <Alert
            type="warning"
            showIcon
            message="预览仅展示模块和固定区段顺序，不展示任何真实简历或岗位数据。"
            style={{ marginBottom: 16 }}
          />
          <Row gutter={[16, 16]}>
            {Object.entries(data.assembly_preview).map(([key, preview]) => (
              <Col xs={24} lg={12} key={key}>
                <Card
                  size="small"
                  title={key === 'resume_screening' ? '简历筛选' : '院校省份补全'}
                >
                  <Typography.Text strong>可编辑模块顺序</Typography.Text>
                  <ol>
                    {preview.editable_module_order.map((moduleKey) => (
                      <li key={moduleKey}>
                        {data.module_definitions.find((item) => item.key === moduleKey)?.label}
                      </li>
                    ))}
                  </ol>
                  <Typography.Text strong>固定追加区段</Typography.Text>
                  <ol>
                    {preview.fixed_sections.map((section) => (
                      <li key={section}>{section}</li>
                    ))}
                  </ol>
                </Card>
              </Col>
            ))}
          </Row>
        </Card>

        <Card title="发布历史">
          <Table
            rowKey="version"
            loading={historyLoading}
            columns={historyColumns}
            dataSource={history}
            pagination={historyPagination}
            onChange={(pagination) => loadHistory(
              pagination.current,
              pagination.pageSize,
            )}
            scroll={{ x: 900 }}
          />
        </Card>
      </Space>

      <Modal
        title={`模块差异：${diffVersion?.version || ''}`}
        open={Boolean(diffVersion)}
        width={1000}
        footer={null}
        onCancel={() => setDiffVersion(null)}
      >
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          {diffVersion && data.module_definitions.map((definition) => {
            const historical = diffVersion.modules[definition.key] || ''
            const active = data.active.modules[definition.key] || ''
            const changed = historical !== active
            return (
              <Card
                size="small"
                key={definition.key}
                title={(
                  <Space>
                    <span>{definition.label}</span>
                    <Tag color={changed ? 'warning' : 'default'}>
                      {changed ? '与当前激活版本不同' : '与当前激活版本相同'}
                    </Tag>
                  </Space>
                )}
              >
                <Row gutter={16}>
                  <Col span={12}>
                    <Typography.Text strong>历史版本</Typography.Text>
                    <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>
                      {historical}
                    </Typography.Paragraph>
                  </Col>
                  <Col span={12}>
                    <Typography.Text strong>当前激活版本</Typography.Text>
                    <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>
                      {active}
                    </Typography.Paragraph>
                  </Col>
                </Row>
              </Card>
            )
          })}
        </Space>
      </Modal>
    </PageContainer>
  )
}
