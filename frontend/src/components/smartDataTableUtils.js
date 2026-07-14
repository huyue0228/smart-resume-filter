import { match } from 'pinyin-pro'

export function tableStorageKey(userId, tableId) {
  return `srf:table:v1:${userId || 'anonymous'}:${tableId}`
}

export function tableColumnKey(column, index) {
  if (column.key) return String(column.key)
  if (Array.isArray(column.dataIndex)) return column.dataIndex.join('.')
  return column.dataIndex ? String(column.dataIndex) : `column-${index}`
}

function recordValue(record, dataIndex) {
  if (Array.isArray(dataIndex)) {
    return dataIndex.reduce((value, key) => value?.[key], record)
  }
  return record?.[dataIndex]
}

export function serializeTableFilters(columns, filters) {
  return columns.reduce((params, column, index) => {
    const filter = column.filter
    const values = filters[tableColumnKey(column, index)] || []
    if (!filter?.param || !values.length) return params
    params[filter.param] = filter.multiple ? values.join(',') : values[0]
    return params
  }, {})
}

export function localTextMatches(value, query, pinyin = false) {
  const text = String(value ?? '')
  const needle = String(query ?? '').trim()
  if (!needle) return true
  if (text.toLocaleLowerCase().includes(needle.toLocaleLowerCase())) return true
  return pinyin && match(text, needle, { continuous: true }) !== null
}

export function filterLocalData(dataSource, columns, filters) {
  const activeColumns = columns
    .map((column, index) => ({ column, key: tableColumnKey(column, index) }))
    .filter(({ column, key }) => column.filter && filters[key]?.length)
  if (!activeColumns.length) return dataSource || []
  return (dataSource || []).filter((record) =>
    activeColumns.every(({ column, key }) => {
      const values = filters[key]
      const value = column.filter.value
        ? column.filter.value(record)
        : recordValue(record, column.filter.dataIndex || column.dataIndex)
      if (column.filter.type === 'select') {
        const current = String(value ?? '')
        return values.some((item) => current === String(item))
      }
      return localTextMatches(value, values[0], column.filter.pinyin)
    }),
  )
}
