import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Form, Input, Popconfirm, Select, Space, Tag, Typography, message } from 'antd'
import { fetchAIConnection, testAIConnection, updateAIConnection } from '../../api/services'

export default function AIConnectionTab() {
  const [form] = Form.useForm()
  const [connection, setConnection] = useState(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await fetchAIConnection()
      setConnection(data)
      form.setFieldsValue({
        profile: data.profile,
        api_style: data.api_style,
        model_name: data.model_name,
        base_url: data.base_url,
        api_key: '',
      })
    } finally {
      setLoading(false)
    }
  }, [form])

  useEffect(() => {
    load()
  }, [load])

  const handleProfileChange = (profileKey) => {
    const profile = connection?.profiles?.find((item) => item.key === profileKey)
    if (!profile) return
    form.setFieldsValue({
      api_style: profile.api_style,
      model_name: profile.default_model,
      base_url: profile.base_url,
    })
  }

  const save = async (clearApiKey = false) => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      const { data } = await updateAIConnection({ ...values, clear_api_key: clearApiKey })
      setConnection(data)
      form.setFieldValue('api_key', '')
      setTestResult(null)
      message.success(clearApiKey ? '已清除已保存的 API Key' : '模型连接配置已保存')
    } finally {
      setSaving(false)
    }
  }

  const test = async () => {
    setTesting(true)
    try {
      const { data } = await testAIConnection()
      setTestResult(data)
      if (data.ok) message.success('模型连接测试成功')
      else message.error(data.detail || '模型连接测试失败')
    } finally {
      setTesting(false)
    }
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%', maxWidth: 760 }}>
      <Alert
        type="info"
        showIcon
        message="模型 API Key 仅在保存时提交，服务端以密文保存，后续不会回显。保存后可执行真实连接测试。"
      />
      <Form form={form} layout="vertical" disabled={loading}>
        <Form.Item name="profile" label="模型 Profile" rules={[{ required: true, message: '请选择模型 Profile' }]}>
          <Select
            options={(connection?.profiles || []).map((profile) => ({ label: profile.label, value: profile.key }))}
            onChange={handleProfileChange}
          />
        </Form.Item>
        <Form.Item name="api_style" label="API 风格" rules={[{ required: true }]}>
          <Select options={[{ label: 'Responses API', value: 'responses' }, { label: 'Chat JSON', value: 'chat_json' }]} />
        </Form.Item>
        <Form.Item name="model_name" label="模型名称" rules={[{ required: true, message: '请输入模型名称' }]}>
          <Input placeholder="例如 deepseek-v4-pro" />
        </Form.Item>
        <Form.Item name="base_url" label="API 地址" rules={[{ type: 'url', message: '请输入完整的 http(s) 地址' }]}>
          <Input placeholder="例如 https://api.deepseek.com" />
        </Form.Item>
        <Form.Item name="api_key" label="API Key">
          <Input.Password autoComplete="new-password" placeholder={connection?.api_key_configured ? '已配置；留空则保持不变' : '请输入 API Key'} />
        </Form.Item>
      </Form>
      <Space wrap>
        <Tag color={connection?.api_key_configured ? 'success' : 'warning'}>
          {connection?.api_key_configured ? 'API Key 已配置（系统设置）' : '未配置 API Key'}
        </Tag>
        <Button type="primary" loading={saving} onClick={() => save(false)}>保存连接配置</Button>
        <Button loading={testing} disabled={!connection?.api_key_configured} onClick={test}>测试模型连接</Button>
        {connection?.api_key_configured && (
          <Popconfirm title="清除已保存的 API Key？" onConfirm={() => save(true)}>
            <Button danger loading={saving}>清除 API Key</Button>
          </Popconfirm>
        )}
      </Space>
      {testResult && (
        <Alert
          type={testResult.ok ? 'success' : 'error'}
          showIcon
          message={testResult.detail}
          description={testResult.ok ? `Profile：${testResult.profile}；模型：${testResult.model_name}` : `错误码：${testResult.code || 'unknown'}`}
        />
      )}
      <Typography.Text type="secondary">
        运行中的 AI 筛选失败会写入对应候选人的 AI 决策错误信息，并同步输出到后端/worker 容器日志；不会记录或打印 API Key。
      </Typography.Text>
    </Space>
  )
}
