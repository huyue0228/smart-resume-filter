import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  InputNumber,
  Select,
  Space,
  Switch,
  Tag,
  Typography,
  message,
} from 'antd'
import {
  fetchAIConnectionSettings,
  updateAIConnectionSetting,
} from '../../api/services'
import {
  DEFAULT_VALUES,
  ENABLED_KEY,
  SECONDARY_KEY,
  TERTIARY_KEY,
  THRESHOLD_KEY,
  saveAISpecialSettings,
} from './aiSpecialSettings'

function contactLabel(contact) {
  const details = [contact.department_name, contact.employee_no].filter(Boolean).join(' / ')
  return details ? `${contact.name}（${details}）` : contact.name
}

export default function AISpecialSettingsTab() {
  const [persisted, setPersisted] = useState(DEFAULT_VALUES)
  const [drafts, setDrafts] = useState(DEFAULT_VALUES)
  const [contacts, setContacts] = useState([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await fetchAIConnectionSettings()
      const specialSettings = (data?.settings || [])
        .filter((item) => item.section === 'special_route')
      const values = {
        ...DEFAULT_VALUES,
        ...Object.fromEntries(specialSettings.map((item) => [item.key, item.value])),
      }
      values[ENABLED_KEY] = Boolean(values[ENABLED_KEY])
      values[THRESHOLD_KEY] = Number(values[THRESHOLD_KEY])
      values[SECONDARY_KEY] = Number(values[SECONDARY_KEY]) || 0
      values[TERTIARY_KEY] = Number(values[TERTIARY_KEY]) || 0
      setPersisted(values)
      setDrafts(values)
      setContacts(Array.isArray(data?.contacts) ? data.contacts : [])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const secondaryContacts = useMemo(
    () => contacts.filter((contact) => contact.contact_level === 'secondary'),
    [contacts],
  )
  const selectedSecondary = secondaryContacts.find(
    (contact) => contact.id === drafts[SECONDARY_KEY],
  )
  const tertiaryContacts = useMemo(
    () => contacts.filter((contact) => (
      contact.contact_level === 'tertiary'
      && selectedSecondary
      && contact.parent_department === selectedSecondary.department
    )),
    [contacts, selectedSecondary],
  )

  const updateSecondary = (contactId) => {
    const secondary = secondaryContacts.find((contact) => contact.id === contactId)
    const currentTertiary = contacts.find(
      (contact) => contact.id === drafts[TERTIARY_KEY],
    )
    setDrafts((values) => ({
      ...values,
      [SECONDARY_KEY]: contactId || 0,
      [TERTIARY_KEY]: (
        secondary
        && currentTertiary?.parent_department === secondary.department
      ) ? values[TERTIARY_KEY] : 0,
    }))
  }

  const save = async () => {
    const secondary = contacts.find((contact) => contact.id === drafts[SECONDARY_KEY])
    const tertiary = contacts.find((contact) => contact.id === drafts[TERTIARY_KEY])
    if (drafts[ENABLED_KEY] && (!secondary || !tertiary)) {
      message.error('启用 AI 专项前，请选择二级接口人和其下属三级接口人')
      return
    }
    if (
      drafts[ENABLED_KEY]
      && tertiary.parent_department !== secondary.department
    ) {
      message.error('三级接口人必须属于所选二级接口人的下级部门')
      return
    }

    setSaving(true)
    try {
      await saveAISpecialSettings({
        persisted,
        drafts,
        update: updateAIConnectionSetting,
      })
      await load()
      message.success('AI 专项配置已保存')
    } catch {
      // 多键保存可能已经先安全关闭专项；失败后重新读取服务端真实状态。
      await load().catch(() => {})
    } finally {
      setSaving(false)
    }
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Alert
        type="info"
        showIcon
        message="AI 专项分配"
        description="AI 识别到专项人才且置信度严格大于阈值时，自动按所选二级、三级接口人完成两段分配。普通列表仍统一显示为 AI 自动分配。"
      />
      <Card
        size="small"
        title="专项路由"
        extra={drafts[ENABLED_KEY] ? <Tag color="green">已开启</Tag> : <Tag>已关闭</Tag>}
        loading={loading}
      >
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          <Space>
            <Typography.Text strong>启用 AI 专项</Typography.Text>
            <Switch
              aria-label="启用 AI 专项"
              checked={Boolean(drafts[ENABLED_KEY])}
              onChange={(checked) => setDrafts((values) => ({
                ...values,
                [ENABLED_KEY]: checked,
              }))}
            />
          </Space>
          <Space wrap size="large" align="start">
            <Space direction="vertical" size={4}>
              <Typography.Text>触发阈值</Typography.Text>
              <InputNumber
                aria-label="AI 专项触发阈值"
                min={0.9}
                max={1}
                step={0.01}
                precision={2}
                value={drafts[THRESHOLD_KEY]}
                onChange={(value) => setDrafts((values) => ({
                  ...values,
                  [THRESHOLD_KEY]: Number(value) || 0.9,
                }))}
              />
              <Typography.Text type="secondary">必须严格大于该值才触发</Typography.Text>
            </Space>
            <Space direction="vertical" size={4}>
              <Typography.Text>父级二级接口人</Typography.Text>
              <Select
                aria-label="AI 专项父级二级接口人"
                showSearch
                allowClear
                optionFilterProp="label"
                placeholder="请选择二级接口人"
                value={drafts[SECONDARY_KEY] || undefined}
                options={secondaryContacts.map((contact) => ({
                  value: contact.id,
                  label: contactLabel(contact),
                }))}
                onChange={updateSecondary}
                style={{ width: 300 }}
              />
            </Space>
            <Space direction="vertical" size={4}>
              <Typography.Text>目标三级接口人</Typography.Text>
              <Select
                aria-label="AI 专项目标三级接口人"
                showSearch
                allowClear
                optionFilterProp="label"
                disabled={!selectedSecondary}
                placeholder={selectedSecondary ? '请选择三级接口人' : '请先选择二级接口人'}
                value={drafts[TERTIARY_KEY] || undefined}
                options={tertiaryContacts.map((contact) => ({
                  value: contact.id,
                  label: contactLabel(contact),
                }))}
                onChange={(contactId) => setDrafts((values) => ({
                  ...values,
                  [TERTIARY_KEY]: contactId || 0,
                }))}
                style={{ width: 300 }}
              />
            </Space>
          </Space>
          <Space>
            <Button type="primary" loading={saving} onClick={save}>
              保存 AI 专项配置
            </Button>
            <Button disabled={saving} onClick={load}>重新加载</Button>
          </Space>
        </Space>
      </Card>
    </Space>
  )
}
