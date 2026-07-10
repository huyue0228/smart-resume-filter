import { useEffect, useState } from 'react'
import { Button, Checkbox, Input, Space } from 'antd'
import { FilterOutlined, SearchOutlined } from '@ant-design/icons'

export function TextFilterDropdown({
  selectedKeys,
  setSelectedKeys,
  confirm,
  clearFilters,
  close,
  placeholder,
}) {
  const selectedValue = selectedKeys[0] || ''
  const [draft, setDraft] = useState(selectedValue)

  useEffect(() => {
    setDraft(selectedValue)
  }, [selectedValue])

  const applyFilter = () => {
    setSelectedKeys(draft ? [draft] : [])
    confirm()
  }

  const resetFilter = () => {
    setDraft('')
    setSelectedKeys([])
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
}) {
  const normalizedSelectedKeys = selectedKeys || []
  const [draftKeys, setDraftKeys] = useState([...normalizedSelectedKeys])

  const toggleKey = (value, checked) => {
    if (multiple) {
      setDraftKeys((prev) =>
        checked ? [...prev, value] : prev.filter((item) => item !== value),
      )
      return
    }
    setDraftKeys(checked ? [value] : [])
  }

  const applyFilter = () => {
    setSelectedKeys(draftKeys)
    confirm()
  }

  const resetFilter = () => {
    setDraftKeys([])
    setSelectedKeys([])
    clearFilters?.()
    confirm()
  }

  const cancelFilter = () => {
    setDraftKeys([...normalizedSelectedKeys])
    close?.()
  }

  return (
    <div style={{ padding: 8, width: 220 }} onKeyDown={(event) => event.stopPropagation()}>
      <Space direction="vertical" size={4} style={{ width: '100%', marginBottom: 8 }}>
        {options.map((option) => {
          const checked = draftKeys.includes(option.value)
          return (
            <Checkbox
              key={option.value}
              checked={checked}
              onChange={(event) => toggleKey(option.value, event.target.checked)}
            >
              {option.text}
            </Checkbox>
          )
        })}
      </Space>
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
