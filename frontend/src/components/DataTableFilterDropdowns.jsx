import { useEffect, useState } from 'react'
import { Button, Input, Select, Space } from 'antd'
import { FilterOutlined, SearchOutlined } from '@ant-design/icons'

export function TextFilterDropdown({
  selectedKeys,
  setSelectedKeys,
  confirm,
  clearFilters,
  close,
  placeholder,
  onApply,
}) {
  const selectedValue = selectedKeys[0] || ''
  const [draft, setDraft] = useState(selectedValue)

  useEffect(() => {
    setDraft(selectedValue)
  }, [selectedValue])

  const applyFilter = () => {
    setSelectedKeys(draft ? [draft] : [])
    onApply?.(draft ? [draft] : [])
    confirm()
  }

  const resetFilter = () => {
    setDraft('')
    setSelectedKeys([])
    onApply?.([])
    clearFilters?.()
    confirm()
  }

  const cancelFilter = () => {
    setDraft(selectedValue)
    close?.()
  }

  return (
    <div style={{ padding: 8, width: 220 }} onKeyDown={(event) => event.stopPropagation()}>
      <Input
        autoFocus
        allowClear
        placeholder={placeholder}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onPressEnter={applyFilter}
        style={{ marginBottom: 8 }}
      />
      <Space>
        <Button type="primary" size="small" icon={<SearchOutlined />} onClick={applyFilter}>
          确认
        </Button>
        <Button size="small" onClick={resetFilter}>
          重置
        </Button>
        <Button size="small" onClick={cancelFilter}>
          取消
        </Button>
      </Space>
    </div>
  )
}

export function SelectFilterDropdown({
  options,
  multiple,
  selectedKeys,
  setSelectedKeys,
  confirm,
  clearFilters,
  close,
  onApply,
}) {
  const [draftKeys, setDraftKeys] = useState([...(selectedKeys || [])])

  useEffect(() => {
    setDraftKeys([...(selectedKeys || [])])
  }, [selectedKeys])

  const applyFilter = () => {
    setSelectedKeys(draftKeys)
    onApply?.(draftKeys)
    confirm()
  }

  const resetFilter = () => {
    setDraftKeys([])
    setSelectedKeys([])
    onApply?.([])
    clearFilters?.()
    confirm()
  }

  const cancelFilter = () => {
    setDraftKeys([...(selectedKeys || [])])
    close?.()
  }

  return (
    <div style={{ padding: 8, width: 260 }} onKeyDown={(event) => event.stopPropagation()}>
      <Select
        allowClear
        mode={multiple ? 'multiple' : undefined}
        optionFilterProp="label"
        options={options.map((option) => ({ label: option.text, value: option.value }))}
        placeholder="请选择"
        showSearch
        value={multiple ? draftKeys : draftKeys[0]}
        onChange={(value) =>
          setDraftKeys(
            multiple ? value || [] : value === undefined || value === null ? [] : [value],
          )
        }
        style={{ width: '100%', marginBottom: 8 }}
      />
      <Space>
        <Button type="primary" size="small" icon={<FilterOutlined />} onClick={applyFilter}>
          确认
        </Button>
        <Button size="small" onClick={resetFilter}>
          重置
        </Button>
        <Button size="small" onClick={cancelFilter}>
          取消
        </Button>
      </Space>
    </div>
  )
}
