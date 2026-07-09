import { useMemo, useState } from 'react'
import { Button, Checkbox, Input, Space } from 'antd'
import { FilterOutlined, SearchOutlined } from '@ant-design/icons'
import ResizableHeaderCell from './ResizableHeaderCell'

export function textColumnFilter(placeholder) {
  return {
    filterDropdown: ({ selectedKeys, setSelectedKeys, confirm, clearFilters, close }) => (
      <div style={{ padding: 8, width: 220 }} onKeyDown={(event) => event.stopPropagation()}>
        <Input
          autoFocus
          allowClear
          placeholder={placeholder}
          value={selectedKeys[0]}
          onChange={(event) =>
            setSelectedKeys(event.target.value ? [event.target.value] : [])
          }
          onPressEnter={() => confirm()}
          style={{ marginBottom: 8 }}
        />
        <Space>
          <Button type="primary" size="small" icon={<SearchOutlined />} onClick={() => confirm()}>
            确认
          </Button>
          <Button
            size="small"
            onClick={() => {
              clearFilters?.()
              confirm()
            }}
          >
            重置
          </Button>
          <Button size="small" onClick={() => close?.()}>
            取消
          </Button>
        </Space>
      </div>
    ),
    filterIcon: (filtered) => (
      <SearchOutlined style={{ color: filtered ? '#1677ff' : undefined }} />
    ),
  }
}

export function selectColumnFilter(options, multiple = false) {
  return {
    filterMultiple: multiple,
    filterDropdown: ({ selectedKeys, setSelectedKeys, confirm, clearFilters, close }) => (
      <div style={{ padding: 8, width: 220 }} onKeyDown={(event) => event.stopPropagation()}>
        <Space direction="vertical" size={4} style={{ width: '100%', marginBottom: 8 }}>
          {options.map((option) => {
            const checked = selectedKeys.includes(option.value)
            return (
              <Checkbox
                key={option.value}
                checked={checked}
                onChange={(event) => {
                  if (multiple) {
                    setSelectedKeys(
                      event.target.checked
                        ? [...selectedKeys, option.value]
                        : selectedKeys.filter((value) => value !== option.value),
                    )
                    return
                  }
                  setSelectedKeys(event.target.checked ? [option.value] : [])
                }}
              >
                {option.text}
              </Checkbox>
            )
          })}
        </Space>
        <Space>
          <Button type="primary" size="small" icon={<FilterOutlined />} onClick={() => confirm()}>
            确认
          </Button>
          <Button
            size="small"
            onClick={() => {
              clearFilters?.()
              confirm()
            }}
          >
            重置
          </Button>
          <Button size="small" onClick={() => close?.()}>
            取消
          </Button>
        </Space>
      </div>
    ),
    filterIcon: (filtered) => (
      <FilterOutlined style={{ color: filtered ? '#1677ff' : undefined }} />
    ),
  }
}

export function normalizeTableFilters(filters, fields) {
  return fields.reduce((acc, field) => {
    const value = filters?.[field]
    if (Array.isArray(value) && value.length > 0 && value[0] !== undefined) {
      acc[field] = value.length === 1 ? value[0] : value
    }
    return acc
  }, {})
}

function columnKey(column) {
  if (column.key) return column.key
  if (Array.isArray(column.dataIndex)) return column.dataIndex.join('.')
  return column.dataIndex
}

function totalWidth(columns) {
  return columns.reduce((sum, column) => sum + Number(column.width || 120), 0)
}

export function useResizableColumns(baseColumns) {
  const [widths, setWidths] = useState({})

  const columns = useMemo(
    () =>
      baseColumns.map((column) => {
        const key = columnKey(column)
        if (!key || column.valueType === 'option') {
          return column
        }
        const width = widths[key] || column.width || 120
        return {
          ...column,
          width,
          onHeaderCell: () => ({
            width,
            minWidth: column.minWidth || 72,
            onResize: (nextWidth) =>
              setWidths((prev) => ({ ...prev, [key]: nextWidth })),
          }),
        }
      }),
    [baseColumns, widths],
  )

  return {
    columns,
    components: { header: { cell: ResizableHeaderCell } },
    scrollX: Math.max(totalWidth(columns), totalWidth(baseColumns)),
  }
}
