import { Table } from 'antd'
import { useResizableColumns } from './DataTableControls'

export default function ResizableTable({ columns: baseColumns, scroll, ...props }) {
  const { columns, components, scrollX } = useResizableColumns(baseColumns)

  return (
    <Table
      {...props}
      columns={columns}
      components={components}
      scroll={{ ...scroll, x: Math.max(Number(scroll?.x || 0), scrollX) }}
    />
  )
}
