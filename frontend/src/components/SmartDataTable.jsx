import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from 'react'
import { FilterOutlined, SearchOutlined } from '@ant-design/icons'
import { ProTable } from '@ant-design/pro-components'
import { Alert, Button, Input, Select, Space } from 'antd'
import { useRole } from '../contexts/roleState'
import ResizableHeaderCell from './ResizableHeaderCell'
import {
  filterLocalData,
  serializeTableFilters,
  tableColumnKey,
  tableStorageKey,
} from './smartDataTableUtils'

const DEFAULT_COLUMN_WIDTH = 120
const EMPTY_COLUMN_STATE = {}
const INTERACTIVE_SELECTOR = [
  'a',
  'button',
  'input',
  'select',
  'textarea',
  '[role="button"]',
  '.ant-checkbox-wrapper',
  '.ant-table-filter-trigger',
  '.srf-column-resize-handle',
].join(',')

function normalizeOption(option) {
  if (option && typeof option === 'object') {
    const label = option.label ?? option.text ?? option.value
    return {
      label,
      value: option.value ?? label,
      searchText: option.searchText ?? option.search_text ?? label,
    }
  }
  return { label: option, value: option, searchText: option }
}

function optionValues(options, filterOptions) {
  const source = typeof options === 'string' ? filterOptions?.[options] : options
  return (source || []).map(normalizeOption)
}

function TextFilterDropdown({ selectedKeys, onApply, placeholder }) {
  const [draft, setDraft] = useState(selectedKeys[0] || '')

  useEffect(() => setDraft(selectedKeys[0] || ''), [selectedKeys])

  return (
    <div className="srf-table-filter" onKeyDown={(event) => event.stopPropagation()}>
      <Input
        autoFocus
        allowClear
        placeholder={placeholder || '请输入筛选内容'}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onPressEnter={() => onApply(draft ? [draft] : [])}
      />
      <Space>
        <Button
          icon={<SearchOutlined />}
          size="small"
          type="primary"
          onClick={() => onApply(draft ? [draft] : [])}
        >
          确认
        </Button>
        <Button size="small" onClick={() => { setDraft(''); onApply([]) }}>
          重置
        </Button>
      </Space>
    </div>
  )
}

function SelectFilterDropdown({ multiple, options, selectedKeys, onApply }) {
  const [draft, setDraft] = useState(selectedKeys)

  useEffect(() => setDraft(selectedKeys), [selectedKeys])

  return (
    <div className="srf-table-filter" onKeyDown={(event) => event.stopPropagation()}>
      <Select
        allowClear
        mode={multiple ? 'multiple' : undefined}
        options={options}
        placeholder="请选择"
        showSearch
        value={multiple ? draft : draft[0]}
        filterOption={(input, option) =>
          String(option?.searchText ?? option?.label ?? '')
            .toLocaleLowerCase()
            .includes(String(input).trim().toLocaleLowerCase())
        }
        onChange={(value) =>
          setDraft(multiple ? value || [] : value === undefined ? [] : [value])
        }
      />
      <Space>
        <Button
          icon={<FilterOutlined />}
          size="small"
          type="primary"
          onClick={() => onApply(draft)}
        >
          确认
        </Button>
        <Button size="small" onClick={() => { setDraft([]); onApply([]) }}>
          重置
        </Button>
      </Space>
    </div>
  )
}

function loadPersisted(key) {
  try {
    return JSON.parse(localStorage.getItem(key) || '{}')
  } catch {
    return {}
  }
}

function persist(key, widths, columnsState) {
  if (!Object.keys(widths).length && !Object.keys(columnsState).length) {
    localStorage.removeItem(key)
    return
  }
  localStorage.setItem(key, JSON.stringify({ widths, columnsState }))
}

function sameState(left, right) {
  return JSON.stringify(left || {}) === JSON.stringify(right || {})
}

const SmartDataTable = forwardRef(function SmartDataTable(
  {
    tableId,
    columns: baseColumns,
    request: dataRequest,
    filterOptionsRequest,
    dataSource,
    actionRef,
    defaultColumnsState = EMPTY_COLUMN_STATE,
    batchActions,
    rowSelection,
    onRowClick,
    onRow,
    pagination,
    params: externalParams,
    options,
    scroll,
    ...tableProps
  },
  forwardedRef,
) {
  const roleContext = useRole()
  const userId = roleContext?.user?.id || roleContext?.user?.username || 'anonymous'
  const storageKey = tableStorageKey(userId, tableId)
  const defaultColumnsStateRef = useRef(defaultColumnsState)
  if (JSON.stringify(defaultColumnsStateRef.current) !== JSON.stringify(defaultColumnsState)) {
    defaultColumnsStateRef.current = defaultColumnsState
  }
  const stableDefaultColumnsState = defaultColumnsStateRef.current
  const persisted = useMemo(() => loadPersisted(storageKey), [storageKey])
  const proActionRef = useRef()
  const filtersRef = useRef({})
  const columnsStateRef = useRef(persisted.columnsState || stableDefaultColumnsState)
  const [filters, setFilters] = useState({})
  const [filterOptions, setFilterOptions] = useState({})
  const [widths, setWidths] = useState(persisted.widths || {})
  const [columnsState, setColumnsState] = useState(columnsStateRef.current)
  const [selectedRowKeys, setSelectedRowKeys] = useState([])
  const [selectedRows, setSelectedRows] = useState([])

  const loadOptions = useCallback(async () => {
    if (!filterOptionsRequest) return
    try {
      const response = await filterOptionsRequest()
      setFilterOptions(response?.data ?? response ?? {})
    } catch {
      setFilterOptions({})
    }
  }, [filterOptionsRequest])

  useEffect(() => {
    loadOptions()
  }, [loadOptions])

  useEffect(() => {
    const next = loadPersisted(storageKey)
    const nextColumnsState = next.columnsState || stableDefaultColumnsState
    setWidths(next.widths || {})
    setColumnsState(nextColumnsState)
    columnsStateRef.current = nextColumnsState
  }, [storageKey, stableDefaultColumnsState])

  const updateFilter = useCallback((key, values, confirm) => {
    const next = { ...filtersRef.current }
    if (values?.length) next[key] = values
    else delete next[key]
    filtersRef.current = next
    setFilters(next)
    confirm?.({ closeDropdown: true })
    if (dataRequest) queueMicrotask(() => proActionRef.current?.reload(true))
  }, [dataRequest])

  const columns = useMemo(
    () => baseColumns.map((column, index) => {
      const key = tableColumnKey(column, index)
      const width = widths[key] || column.width || DEFAULT_COLUMN_WIDTH
      const filter = column.filter
      const next = {
        ...column,
        key,
        width,
        onHeaderCell: (...args) => ({
          ...(column.onHeaderCell?.(...args) || {}),
          width,
          minWidth: column.minWidth || 72,
          onResize: (nextWidth) => {
            setWidths((previous) => {
              const nextWidths = { ...previous, [key]: nextWidth }
              persist(storageKey, nextWidths, columnsStateRef.current)
              return nextWidths
            })
          },
        }),
      }
      if (!filter) return next
      const selectedKeys = filters[key] || []
      const apply = (values, confirm) => updateFilter(key, values, confirm)
      return {
        ...next,
        filteredValue: selectedKeys.length ? selectedKeys : null,
        filterMultiple: Boolean(filter.multiple),
        filterIcon: (filtered) => filter.type === 'select'
          ? <FilterOutlined style={{ color: filtered ? '#1677ff' : undefined }} />
          : <SearchOutlined style={{ color: filtered ? '#1677ff' : undefined }} />,
        filterDropdown: ({ confirm }) => filter.type === 'select' ? (
          <SelectFilterDropdown
            multiple={filter.multiple}
            options={optionValues(filter.options, filterOptions)}
            selectedKeys={selectedKeys}
            onApply={(values) => apply(values, confirm)}
          />
        ) : (
          <TextFilterDropdown
            placeholder={filter.placeholder}
            selectedKeys={selectedKeys}
            onApply={(values) => apply(values, confirm)}
          />
        ),
      }
    }),
    [baseColumns, widths, filters, filterOptions, storageKey, updateFilter],
  )

  const totalWidth = columns.reduce(
    (sum, column) => sum + Number(column.width || DEFAULT_COLUMN_WIDTH),
    0,
  )
  const localData = useMemo(
    () => filterLocalData(dataSource, columns, filters),
    [dataSource, columns, filters],
  )

  const clearSelection = useCallback(() => {
    setSelectedRowKeys([])
    setSelectedRows([])
    proActionRef.current?.clearSelected?.()
    rowSelection?.onChange?.([], [])
  }, [rowSelection])

  const resetTable = useCallback(() => {
    filtersRef.current = {}
    setFilters({})
    setWidths({})
    setColumnsState(stableDefaultColumnsState)
    columnsStateRef.current = stableDefaultColumnsState
    localStorage.removeItem(storageKey)
    clearSelection()
    queueMicrotask(() => proActionRef.current?.reload?.(true))
  }, [clearSelection, stableDefaultColumnsState, storageKey])

  const publicActions = useMemo(() => ({
    reload: (...args) => proActionRef.current?.reload?.(...args),
    reloadOptions: loadOptions,
    resetTable,
    clearSelected: clearSelection,
    getFilters: () => serializeTableFilters(baseColumns, filtersRef.current),
  }), [baseColumns, clearSelection, loadOptions, resetTable])

  useImperativeHandle(actionRef, () => publicActions, [publicActions])
  useImperativeHandle(forwardedRef, () => publicActions, [publicActions])

  const effectiveSelectedRowKeys = rowSelection?.selectedRowKeys ?? selectedRowKeys
  const mergedRowSelection = rowSelection ? {
    ...rowSelection,
    selectedRowKeys: effectiveSelectedRowKeys,
    onChange: (keys, rows, info) => {
      setSelectedRowKeys(keys)
      setSelectedRows(rows)
      rowSelection.onChange?.(keys, rows, info)
    },
  } : undefined

  const mergedOnRow = (record, index) => {
    const original = onRow?.(record, index) || {}
    return {
      ...original,
      onClick: (event) => {
        original.onClick?.(event)
        if (event.defaultPrevented || event.target.closest?.(INTERACTIVE_SELECTOR)) return
        onRowClick?.(record, index, event)
      },
    }
  }

  const batchContent = effectiveSelectedRowKeys.length && batchActions
    ? batchActions({
        selectedRowKeys: effectiveSelectedRowKeys,
        selectedRows,
        clearSelection,
        filters: serializeTableFilters(baseColumns, filtersRef.current),
      })
    : null

  return (
    <Space className="srf-smart-data-table" direction="vertical" size={12} style={{ width: '100%' }}>
      {batchContent ? (
        <Alert
          type="info"
          showIcon
          message={
            <Space wrap>
              <span>已选 {effectiveSelectedRowKeys.length} 项</span>
              {batchContent}
            </Space>
          }
        />
      ) : null}
      <ProTable
        {...tableProps}
        actionRef={proActionRef}
        columns={columns}
        columnsState={{
          defaultValue: stableDefaultColumnsState,
          value: columnsState,
          onChange: (nextState) => {
            const reset = sameState(nextState, stableDefaultColumnsState)
            const nextWidths = reset ? {} : widths
            setColumnsState(nextState)
            columnsStateRef.current = nextState
            if (reset) setWidths({})
            if (reset) localStorage.removeItem(storageKey)
            else persist(storageKey, nextWidths, nextState)
          },
        }}
        components={{ header: { cell: ResizableHeaderCell } }}
        dataSource={dataRequest ? undefined : localData}
        onRow={onRow || onRowClick ? mergedOnRow : undefined}
        options={{
          density: true,
          fullScreen: true,
          reload: Boolean(dataRequest),
          setting: { draggable: true },
          ...options,
        }}
        pagination={pagination === undefined
          ? dataRequest ? { defaultPageSize: 10, showSizeChanger: true } : false
          : pagination}
        params={externalParams}
        request={dataRequest ? async (params) => {
          try {
            const { current, pageSize, ...requestParams } = params
            const response = await dataRequest({
              ...requestParams,
              page: current,
              page_size: pageSize,
              ...serializeTableFilters(baseColumns, filtersRef.current),
            })
            const payload = response?.data ?? response ?? {}
            return {
              data: payload.results || [],
              total: payload.count || 0,
              success: true,
            }
          } catch {
            return { data: [], total: 0, success: false }
          }
        } : undefined}
        rowSelection={mergedRowSelection}
        scroll={{ ...scroll, x: Math.max(Number(scroll?.x || 0), totalWidth) }}
        search={false}
      />
    </Space>
  )
})

export default SmartDataTable
