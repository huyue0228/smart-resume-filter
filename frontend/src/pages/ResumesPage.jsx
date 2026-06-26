import { useRef, useEffect, useState } from 'react'
import { PageContainer, ProTable } from '@ant-design/pro-components'
import { Button, Tag, Space, Modal, message } from 'antd'
import { UndoOutlined } from '@ant-design/icons'
import {
  fetchResumes,
  fetchUndoStatus,
  undoLastImport,
} from '../api/services'
import ImportButton from '../components/ImportButton'
import { useProcessRunner } from '../components/useProcessRunner'
import { useMode } from '../contexts/ModeContext'

const RESUME_IMPORT_FIELDS = [
  { key: 'resume_list', label: '① 简历信息列表 (.xlsx)', accept: '.xlsx,.xls' },
  { key: 'resume_package', label: '② 简历包 (.zip，文件名含应聘ID)', accept: '.zip' },
]

// 上传后自动处理的五步（院校分类提前）
const PROCESS_STEPS = [
  { step: 'step1', label: '查重与志愿排序' },
  { step: 'step3', label: '院校分类' },
  { step: 'step2', label: '岗位分类' },
  { step: 'step4', label: '需求录入' },
  { step: 'step5', label: '简历分配' },
]

const STATUS_OPTIONS = {
  pending: { text: '待处理', status: 'Default' },
  processing: { text: '处理中', status: 'Processing' },
  allocated: { text: '已分配', status: 'Success' },
  dispatched: { text: '已下发', status: 'Success' },
  rejected: { text: '已淘汰', status: 'Error' },
}

export default function ResumesPage() {
  const actionRef = useRef()
  const { mode } = useMode()
  const { run, modal } = useProcessRunner()
  const [undo, setUndo] = useState({ available: false })

  const refreshUndo = async () => {
    try {
      const { data } = await fetchUndoStatus()
      setUndo(data || { available: false })
    } catch {
      setUndo({ available: false })
    }
  }

  useEffect(() => {
    refreshUndo()
  }, [])

  // 导入成功 → 自动按当前模式跑五步 → 刷新
  const handleImported = async () => {
    await refreshUndo()
    const r = await run(
      PROCESS_STEPS,
      mode,
      `正在处理简历（${mode === 'ai' ? 'AI' : '规则'}模式）`,
    )
    if (r.success) message.success('简历处理完成')
    actionRef.current?.reload()
  }

  const handleUndo = () => {
    Modal.confirm({
      title: '撤销上次上传',
      content: '将删除最近一次上传的简历及其处理结果，回到上传前状态。确定撤销？',
      okText: '撤销',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          const { data } = await undoLastImport()
          message.success(data?.detail || '已撤销')
          await refreshUndo()
          actionRef.current?.reload()
        } catch {
          message.error('撤销失败')
        }
      },
    })
  }

  const columns = [
    { title: '姓名', dataIndex: 'candidate_name', fixed: 'left', width: 100 },
    { title: '手机', dataIndex: 'phone', width: 130, search: false },
    { title: '主体', dataIndex: 'entity', width: 120, search: false },
    { title: '投递岗位', dataIndex: 'position_name', ellipsis: true, search: false },
    { title: '志愿', dataIndex: 'volunteer_rank', width: 80, search: false },
    { title: '岗位类别', dataIndex: 'job_category', width: 110, search: false },
    {
      title: '院校标签',
      dataIndex: 'school_tag',
      width: 110,
      search: false,
      render: (_, record) =>
        record.school_tag ? <Tag color="blue">{record.school_tag}</Tag> : '-',
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      valueType: 'select',
      valueEnum: STATUS_OPTIONS,
    },
    {
      title: '关键词',
      dataIndex: 'search',
      hideInTable: true,
      fieldProps: { placeholder: '姓名 / 手机' },
    },
    {
      title: '导入时间',
      dataIndex: 'imported_at',
      valueType: 'dateRange',
      hideInTable: true,
      search: {
        transform: (value) => ({
          imported_after: value?.[0],
          imported_before: value?.[1],
        }),
      },
    },
    {
      title: '操作',
      valueType: 'option',
      width: 160,
      fixed: 'right',
      render: (_, record) => (
        <Space>
          <a onClick={() => message.info(`查看 ${record.candidate_name}`)}>查看</a>
          <a onClick={() => message.info(`编辑 ${record.candidate_name}`)}>编辑</a>
          <a
            style={{ color: '#cf1322' }}
            onClick={() => message.info(`删除 ${record.candidate_name}`)}
          >
            删除
          </a>
        </Space>
      ),
    },
  ]

  return (
    <PageContainer
      title="简历库"
      content="上传简历后自动完成查重、分类、院校、分配处理；可撤销最近一次上传。"
    >
      <ProTable
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        scroll={{ x: 1200 }}
        pagination={{ defaultPageSize: 10, showSizeChanger: true }}
        search={{ labelWidth: 'auto' }}
        toolBarRender={() => [
          <ImportButton
            key="import"
            buttonText="上传简历"
            title="上传简历（简历列表 + 简历包），上传后自动处理"
            fields={RESUME_IMPORT_FIELDS}
            onDone={handleImported}
          />,
          <Button
            key="undo"
            icon={<UndoOutlined />}
            disabled={!undo.available}
            onClick={handleUndo}
          >
            撤销上次上传
          </Button>,
          <Button key="export" onClick={() => message.info('导出')}>
            导出
          </Button>,
        ]}
        request={async (params) => {
          const { current, pageSize, status, search, imported_after, imported_before } =
            params
          try {
            const { data } = await fetchResumes({
              page: current,
              page_size: pageSize,
              status,
              search,
              imported_after,
              imported_before,
            })
            return {
              data: data?.results || [],
              total: data?.count || 0,
              success: true,
            }
          } catch {
            return { data: [], total: 0, success: false }
          }
        }}
      />
      {modal}
    </PageContainer>
  )
}
