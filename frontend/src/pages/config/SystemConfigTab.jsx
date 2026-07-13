import { useEffect, useState } from 'react'
import { ProTable } from '@ant-design/pro-components'
import { Button, InputNumber, Space, Switch, Tag, message } from 'antd'
import { fetchConfigs, updateConfig } from '../../api/services'
import {
  localTextColumnFilter,
  useResizableColumns,
} from '../../components/DataTableControls'

function ConfigValueEditor({ record, value, onChange }) {
  if (record.value_type === 'boolean') {
    return <Switch checked={Boolean(value)} onChange={onChange} />
  }
  if (record.value_type === 'number') {
    return (
      <InputNumber
        min={0}
        max={1}
        step={0.01}
        precision={2}
        value={Number(value)}
        onChange={onChange}
      />
    )
  }
  if (record.value_type === 'integer') {
    return (
      <InputNumber min={0} precision={0} value={Number(value)} onChange={onChange} />
    )
  }
  return value
}

export default function SystemConfigTab() {
  const [configs, setConfigs] = useState([])
  const [drafts, setDrafts] = useState({})
  const [loading, setLoading] = useState(false)
  const [savingKey, setSavingKey] = useState('')

  const load = async () => {
    setLoading(true)
    try {
      const { data } = await fetchConfigs()
      setConfigs(data || [])
      setDrafts(
        Object.fromEntries((data || []).map((item) => [item.key, item.value])),
      )
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const save = async (record) => {
    setSavingKey(record.key)
    try {
      const { data } = await updateConfig(record.key, drafts[record.key])
      setConfigs((prev) => prev.map((item) => (item.key === record.key ? data : item)))
      setDrafts((prev) => ({ ...prev, [record.key]: data.value }))
      message.success('配置已保存')
    } catch {
      setDrafts((prev) => ({ ...prev, [record.key]: record.value }))
    } finally {
      setSavingKey('')
    }
  }

  const baseColumns = [
    {
      title: '配置项',
      dataIndex: 'label',
      width: 180,
      fixed: 'left',
      ...localTextColumnFilter('label', '筛选配置项'),
    },
    {
      title: '键',
      dataIndex: 'key',
      width: 180,
      ...localTextColumnFilter('key', '筛选配置键'),
      render: (value) => <Tag color="blue">{value}</Tag>,
    },
    {
      title: '说明',
      dataIndex: 'description',
      ellipsis: true,
      ...localTextColumnFilter('description', '筛选说明'),
    },
    {
      title: '值',
      dataIndex: 'value',
      width: 180,
      render: (_, record) => (
        <ConfigValueEditor
          record={record}
          value={drafts[record.key]}
          onChange={(value) =>
            setDrafts((prev) => ({
              ...prev,
              [record.key]: value,
            }))
          }
        />
      ),
    },
    {
      title: '操作',
      valueType: 'option',
      width: 110,
      render: (_, record) => (
        <Button
          type="primary"
          size="small"
          loading={savingKey === record.key}
          onClick={() => save(record)}
        >
          保存
        </Button>
      ),
    },
  ]
  const { columns, components, scrollX } = useResizableColumns(baseColumns)

  return (
    <Space direction="vertical" style={{ width: '100%' }} size={16}>
      <ProTable
        rowKey="key"
        search={false}
        loading={loading}
        columns={columns}
        components={components}
        dataSource={configs}
        pagination={false}
        scroll={{ x: scrollX }}
        toolBarRender={() => [
          <Button key="reload" onClick={load}>
            刷新
          </Button>,
        ]}
      />
    </Space>
  )
}
