import { createRef } from 'react'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import SmartDataTable from './SmartDataTable'

const rows = [{ id: 1, name: '张三' }]

describe('SmartDataTable', () => {
  it('requests the first page and applies a confirmed text filter', async () => {
    const request = vi.fn().mockResolvedValue({ data: { results: rows, count: 1 } })
    const { container } = render(
      <SmartDataTable
        tableId="request"
        rowKey="id"
        columns={[{
          title: '姓名',
          dataIndex: 'name',
          filter: { type: 'text', param: 'name', placeholder: '筛选姓名' },
        }]}
        request={request}
      />,
    )

    await waitFor(() => expect(request).toHaveBeenCalledWith({ page: 1, page_size: 10 }))
    await userEvent.click(container.querySelector('.ant-table-filter-trigger'))
    await userEvent.type(screen.getByPlaceholderText('筛选姓名'), '张三')
    await userEvent.click(screen.getByRole('button', { name: /确认/ }))

    await waitFor(() => expect(request).toHaveBeenLastCalledWith({
      page: 1,
      page_size: 10,
      name: '张三',
    }))
  })

  it('resetTable clears filters and persisted column configuration', async () => {
    const actionRef = createRef()
    const storageKey = 'srf:table:v1:anonymous:reset'
    localStorage.setItem(storageKey, JSON.stringify({
      widths: { name: 240 },
      columnsState: { name: { show: false } },
    }))
    render(
      <SmartDataTable
        tableId="reset"
        actionRef={actionRef}
        rowKey="id"
        columns={[{ title: '姓名', dataIndex: 'name', filter: { type: 'text' } }]}
        dataSource={rows}
      />,
    )

    await act(async () => actionRef.current.resetTable())

    expect(actionRef.current.getFilters()).toEqual({})
    expect(localStorage.getItem(storageKey)).toBeNull()
  })

  it('shows batch actions only after selecting a row', async () => {
    render(
      <SmartDataTable
        tableId="batch"
        rowKey="id"
        columns={[{ title: '姓名', dataIndex: 'name' }]}
        dataSource={rows}
        rowSelection={{}}
        batchActions={() => <button type="button">批量处理</button>}
      />,
    )

    expect(screen.queryByRole('button', { name: '批量处理' })).toBeNull()
    const checkboxes = screen.getAllByRole('checkbox')
    await userEvent.click(checkboxes[1])
    expect(screen.getByRole('button', { name: '批量处理' })).toBeTruthy()
  })

  it('isolates interactive controls from row click actions', async () => {
    const onRowClick = vi.fn()
    render(
      <SmartDataTable
        tableId="row-click"
        rowKey="id"
        columns={[
          { title: '姓名', dataIndex: 'name' },
          { title: '操作', render: () => <button type="button">编辑</button> },
        ]}
        dataSource={rows}
        onRowClick={onRowClick}
      />,
    )

    await userEvent.click(screen.getByRole('button', { name: '编辑' }))
    expect(onRowClick).not.toHaveBeenCalled()
    fireEvent.click(screen.getByText('张三'))
    expect(onRowClick).toHaveBeenCalledWith(rows[0], 0, expect.anything())
  })
})
