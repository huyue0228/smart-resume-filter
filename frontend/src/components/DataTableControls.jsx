import { useMemo, useState } from 'react'
import { FilterOutlined, SearchOutlined } from '@ant-design/icons'
import { SelectFilterDropdown, TextFilterDropdown } from './DataTableFilterDropdowns'
import ResizableHeaderCell from './ResizableHeaderCell'

export function textColumnFilter(placeholder, onApply) {
  return {
    filterDropdown: (props) => (
      <TextFilterDropdown {...props} placeholder={placeholder} onApply={onApply} />
    ),
    filterIcon: (filtered) => (
      <SearchOutlined style={{ color: filtered ? '#1677ff' : undefined }} />
    ),
  }
}

export function selectColumnFilter(options, multiple = false, onApply) {
  return {
    filterMultiple: multiple,
    filterDropdown: (props) => {
      const filterKey = (props.selectedKeys || []).join('\u0001')
      return (
        <SelectFilterDropdown
          key={filterKey}
          {...props}
          onApply={onApply}
          options={options}
          multiple={multiple}
        />
      )
    },
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

function columnKey(column, index) {
  if (column.key) return column.key
  if (Array.isArray(column.dataIndex)) return column.dataIndex.join('.')
  return column.dataIndex || `column-${index}`
}

function totalWidth(columns) {
  return columns.reduce((sum, column) => sum + Number(column.width || 120), 0)
}

export function useResizableColumns(baseColumns) {
  const [widths, setWidths] = useState({})

  const columns = useMemo(
    () =>
      baseColumns.map((column, index) => {
        const key = columnKey(column, index)
        const width = widths[key] || column.width || 120
        return {
          ...column,
          key,
          width,
          onHeaderCell: (...args) => ({
            ...(column.onHeaderCell?.(...args) || {}),
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

function localValue(record, dataIndex) {
  if (Array.isArray(dataIndex)) {
    return dataIndex.reduce((value, key) => value?.[key], record)
  }
  return record?.[dataIndex]
}

export function localTextColumnFilter(dataIndex, placeholder) {
  return {
    ...textColumnFilter(placeholder),
    onFilter: (value, record) =>
      String(localValue(record, dataIndex) ?? '')
        .toLowerCase()
        .includes(String(value).toLowerCase()),
  }
}

export function localSelectColumnFilter(dataIndex, options, multiple = false) {
  return {
    ...selectColumnFilter(options, multiple),
    onFilter: (value, record) => String(localValue(record, dataIndex) ?? '') === String(value),
  }
}
