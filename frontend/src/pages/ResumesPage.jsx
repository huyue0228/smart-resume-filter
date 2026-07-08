import { useRef, useEffect, useState } from 'react'
import { PageContainer, ProTable } from '@ant-design/pro-components'
import { Button, Tag, Space, Modal, message, Drawer, Descriptions, Table, Typography } from 'antd'
import { DownloadOutlined, PlayCircleOutlined, UndoOutlined } from '@ant-design/icons'
import {
  deleteCandidate,
  exportCandidates,
  fetchCandidates,
  fetchUndoStatus,
  undoLastImport,
} from '../api/services'
import ImportButton from '../components/ImportButton'
import ResumePreview from '../components/ResumePreview'
import { useProcessRunner } from '../components/useProcessRunner'
import { useMode } from '../contexts/ModeContext'
import {
  normalizeTableFilters,
  selectColumnFilter,
  textColumnFilter,
  useResizableColumns,
} from '../components/DataTableControls'
import { downloadBlobFromResponse } from '../utils/download'

const RESUME_IMPORT_FIELDS = [
  { key: 'resume_list', label: '① 简历信息列表 (.xlsx/.xls/.csv)', accept: '.xlsx,.xls,.csv' },
  { key: 'resume_package', label: '② 简历包 (.zip，文件名含应聘ID)', accept: '.zip' },
]

// 上传后自动处理：前置数据准备 + 候选人处理主流程
const PROCESS_STEPS = [
  { step: 'step3', label: '院校分类' },
  { step: 'step4', label: '需求录入' },
  { step: 'step1', label: '查重与志愿排序' },
  { step: 'step2', label: '简历分类、分配与下发' },
]

const SYSTEM_STATUS_OPTIONS = {
  raw: { text: '待处理', color: 'default', status: 'Default' },
  classified: { text: '已分类', color: 'blue', status: 'Processing' },
  allocated: { text: '已分配', color: 'gold', status: 'Warning' },
  pending_screening: { text: '待筛选', color: 'processing', status: 'Processing' },
  screening_passed: { text: '筛选通过', color: 'success', status: 'Success' },
  screening_rejected: { text: '筛选不通过', color: 'error', status: 'Error' },
}

const ATTEMPT_STATUS = {
  pending_dispatch: { color: 'default', text: '待下发' },
  dispatched_l2: { color: 'processing', text: '已下发二级' },
  assigned_l3: { color: 'processing', text: '已转派三级' },
  passed: { color: 'success', text: '已通过' },
  rejected: { color: 'error', text: '未通过' },
  cancelled: { color: 'default', text: '已取消' },
}

const SOURCE_TEXT = {
  rule: '规则',
  ai: 'AI',
  manual: '手动',
}

export default function ResumesPage() {
  const actionRef = useRef()
  const { mode } = useMode()
  const { run, modal } = useProcessRunner()
  const [undo, setUndo] = useState({ available: false })
  const [detailRecord, setDetailRecord] = useState(null)
  const [previewRecord, setPreviewRecord] = useState(null)
  const [exporting, setExporting] = useState(false)
  const [processing, setProcessing] = useState(false)
  const [lastQuery, setLastQuery] = useState({})

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

  useEffect(() => {
    if (!detailRecord) {
      setPreviewRecord(null)
      return
    }
    setPreviewRecord(detailRecord.current_resume || detailRecord.resumes?.[0] || null)
  }, [detailRecord])

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

  const handleDelete = (record) => {
    Modal.confirm({
      title: '删除候选人',
      content: `将删除 ${record.name} 及其全部投递记录。若已产生分配历史，系统会阻止删除。确定继续？`,
      okText: '删除',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await deleteCandidate(record.id)
          message.success('已删除')
          actionRef.current?.reload()
        } catch (error) {
          message.error(error?.response?.data?.detail || '删除失败')
        }
      },
    })
  }

  const handleExport = async () => {
    setExporting(true)
    try {
      const resp = await exportCandidates(null, lastQuery)
      const count = Number(resp.headers?.['x-export-count'] ?? 0)
      const missing = Number(resp.headers?.['x-export-missing'] ?? 0)
      if (count === 0 && missing === 0) {
        message.warning('当前筛选结果暂无可导出的简历文件')
      } else {
        downloadBlobFromResponse(resp, 'resumes_export.zip')
        message.success(
          `已导出 ${count} 份简历${missing ? `，${missing} 份缺文件（见压缩包内清单）` : ''}`,
        )
      }
    } catch {
      message.error('导出失败')
    } finally {
      setExporting(false)
    }
  }

  const selectedSystemStatuses = () => {
    const value = lastQuery.system_status
    if (!value) return []
    return Array.isArray(value) ? value : String(value).split(',').filter(Boolean)
  }

  const handleProcessSelectedStatuses = () => {
    const statuses = selectedSystemStatuses()
    if (!statuses.length) {
      message.warning('请先在“系统简历状态”列勾选需要重新分配的状态')
      return
    }
    const statusText = statuses
      .map((status) => SYSTEM_STATUS_OPTIONS[status]?.text || status)
      .join('、')
    Modal.confirm({
      title: '处理简历',
      content: `将按当前${mode === 'ai' ? 'AI' : '规则'}模式，对当前筛选条件下状态为“${statusText}”的候选人重新执行分配；历史分配与反馈记录会保留，未反馈的自动分配会取消。确定继续？`,
      okText: '开始处理',
      onOk: async () => {
        setProcessing(true)
        try {
          const r = await run(
            [{ step: 'step2', label: '简历分类、分配与下发' }],
            mode,
            `正在重新处理简历（${mode === 'ai' ? 'AI' : '规则'}模式）`,
            {
              scope: {
                system_statuses: statuses,
                candidate_filters: lastQuery,
              },
            },
          )
          if (r.success) {
            message.success('简历重新处理完成')
            actionRef.current?.reload()
          }
        } finally {
          setProcessing(false)
        }
      },
    })
  }

  const baseColumns = [
    {
      title: '姓名',
      dataIndex: 'name',
      fixed: 'left',
      width: 100,
      ...textColumnFilter('筛选姓名/拼音'),
    },
    { title: '手机', dataIndex: 'phone', width: 130, ...textColumnFilter('筛选手机') },
    {
      title: '最高学历专业',
      dataIndex: 'highest_major',
      width: 130,
      ellipsis: true,
      ...textColumnFilter('筛选最高学历专业'),
      render: (_, record) => record.highest_major || '-',
    },
    {
      title: '当前志愿',
      dataIndex: 'current_rank',
      width: 90,
      ...textColumnFilter('筛选志愿'),
      render: (_, record) => record.current_rank || '-',
    },
    {
      title: '当前主体',
      dataIndex: 'current_entity',
      width: 120,
      ...textColumnFilter('筛选主体'),
      render: (_, record) => record.current_resume?.entity || '-',
    },
    {
      title: '当前投递岗位',
      dataIndex: 'current_position_name',
      width: 180,
      ellipsis: true,
      ...textColumnFilter('筛选投递岗位'),
      render: (_, record) => record.current_resume?.position_name || '-',
    },
    {
      title: '岗位类别',
      dataIndex: 'current_job_category',
      width: 110,
      ...textColumnFilter('筛选岗位类别'),
      render: (_, record) => record.current_resume?.job_category || '-',
    },
    {
      title: '院校标签',
      dataIndex: 'school_tag',
      width: 110,
      ...textColumnFilter('筛选院校标签'),
      render: (_, record) =>
        record.school_tag ? <Tag color="blue">{record.school_tag}</Tag> : '-',
    },
    {
      title: '系统简历状态',
      dataIndex: 'system_status',
      width: 110,
      valueType: 'select',
      valueEnum: Object.fromEntries(
        Object.entries(SYSTEM_STATUS_OPTIONS).map(([value, item]) => [
          value,
          { text: item.text, status: item.status },
        ]),
      ),
      ...selectColumnFilter(
        Object.entries(SYSTEM_STATUS_OPTIONS).map(([value, item]) => ({
          text: item.text,
          value,
        })),
        true,
      ),
      render: (_, record) => {
        const status = record.system_status
        const item = SYSTEM_STATUS_OPTIONS[status]
        return item ? <Tag color={item.color}>{item.text}</Tag> : '-'
      },
    },
    {
      title: '操作',
      valueType: 'option',
      width: 160,
      fixed: 'right',
      render: (_, record) => (
        <Space>
          <a onClick={() => setDetailRecord(record)}>详情</a>
          <a
            style={{ color: '#cf1322' }}
            onClick={() => handleDelete(record)}
          >
            删除
          </a>
        </Space>
      ),
    },
  ]
  const { columns, components, scrollX } = useResizableColumns(baseColumns)

  return (
    <PageContainer
      title="简历库"
      content="按候选人聚合展示当前有效志愿；点开详情查看全部投递、分配尝试和反馈。"
    >
      <ProTable
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        components={components}
        scroll={{ x: scrollX }}
        pagination={{ defaultPageSize: 10, showSizeChanger: true }}
        search={false}
        toolBarRender={() => [
          <ImportButton
            key="import"
            buttonText="上传简历"
            title="上传简历（简历列表 + 简历包），上传后自动处理"
            fields={RESUME_IMPORT_FIELDS}
            onDone={handleImported}
          />,
          <Button
            key="process"
            type="primary"
            icon={<PlayCircleOutlined />}
            loading={processing}
            onClick={handleProcessSelectedStatuses}
          >
            处理简历
          </Button>,
          <Button
            key="undo"
            icon={<UndoOutlined />}
            disabled={!undo.available}
            onClick={handleUndo}
          >
            撤销上次上传
          </Button>,
          <Button
            key="export"
            icon={<DownloadOutlined />}
            loading={exporting}
            onClick={handleExport}
          >
            导出
          </Button>,
        ]}
        request={async (params, _sort, filters) => {
          const {
            current,
            pageSize,
          } = params
          const tableFilters = normalizeTableFilters(filters, [
            'name',
            'phone',
            'highest_major',
            'current_rank',
            'current_entity',
            'current_position_name',
            'current_job_category',
            'school_tag',
            'system_status',
          ])
          const query = {
            system_status: Array.isArray(tableFilters.system_status)
              ? tableFilters.system_status.join(',')
              : tableFilters.system_status,
            name: tableFilters.name,
            phone: tableFilters.phone,
            highest_major: tableFilters.highest_major,
            current_rank: tableFilters.current_rank,
            current_entity: tableFilters.current_entity,
            current_position_name: tableFilters.current_position_name,
            current_job_category: tableFilters.current_job_category,
            school_tag: tableFilters.school_tag,
          }
          setLastQuery(query)
          try {
            const { data } = await fetchCandidates({
              page: current,
              page_size: pageSize,
              ...query,
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
      <Drawer
        title={detailRecord ? `${detailRecord.name} 的简历详情` : '简历详情'}
        width={1100}
        open={!!detailRecord}
        onClose={() => setDetailRecord(null)}
      >
        {detailRecord && (
          <>
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="姓名">{detailRecord.name}</Descriptions.Item>
              <Descriptions.Item label="手机">{detailRecord.phone || '-'}</Descriptions.Item>
              <Descriptions.Item label="最高学历专业">
                {detailRecord.highest_major || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="第一学历院校">
                {detailRecord.first_degree_school || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="第一学历标签">
                {detailRecord.first_degree_platform || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="最高学历院校">
                {detailRecord.highest_degree_school || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="最高学历标签">
                {detailRecord.highest_degree_platform || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="当前志愿">
                {detailRecord.current_rank || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="系统简历状态">
                {detailRecord.system_status_label || '-'}
              </Descriptions.Item>
              {detailRecord.archive_reason && (
                <Descriptions.Item label="归档原因" span={2}>
                  {detailRecord.archive_detail || detailRecord.archive_reason}
                </Descriptions.Item>
              )}
            </Descriptions>

            <Table
              style={{ marginTop: 16 }}
              title={() => '投递志愿'}
              rowKey="id"
              size="small"
              pagination={false}
              dataSource={detailRecord.resumes || []}
              columns={[
                { title: '志愿', dataIndex: 'volunteer_rank', width: 70 },
                { title: '应聘ID', dataIndex: 'apply_id', width: 110 },
                { title: '主体', dataIndex: 'entity', width: 100 },
                { title: '投递岗位', dataIndex: 'position_name', ellipsis: true },
                { title: '岗位类别', dataIndex: 'job_category', width: 110 },
                { title: '应聘状态', dataIndex: 'status', width: 100 },
                {
                  title: '预览',
                  valueType: 'option',
                  width: 70,
                  render: (_, resume) => (
                    <a onClick={() => setPreviewRecord(resume)}>预览</a>
                  ),
                },
              ]}
            />

            <div style={{ marginTop: 16 }}>
              <Typography.Title level={5} style={{ marginTop: 0 }}>
                简历预览
              </Typography.Title>
              <ResumePreview resume={previewRecord} />
            </div>

            <Table
              style={{ marginTop: 16 }}
              title={() => '分配尝试'}
              rowKey="id"
              size="small"
              pagination={false}
              dataSource={detailRecord.attempts || []}
              locale={{ emptyText: '暂无分配尝试' }}
              columns={[
                { title: '次序', dataIndex: 'attempt_no', width: 70 },
                {
                  title: '来源',
                  dataIndex: 'source',
                  width: 80,
                  render: (value) => SOURCE_TEXT[value] || value || '-',
                },
                { title: '投递岗位', dataIndex: 'position_name', ellipsis: true },
                { title: '二级接口人', dataIndex: 'contact_name', width: 110 },
                { title: '三级接口人', dataIndex: 'sub_contact_name', width: 110 },
                {
                  title: '状态',
                  dataIndex: 'status',
                  width: 100,
                  render: (value) => (
                    <Tag color={ATTEMPT_STATUS[value]?.color || 'default'}>
                      {ATTEMPT_STATUS[value]?.text || value || '-'}
                    </Tag>
                  ),
                },
                {
                  title: '反馈',
                  dataIndex: 'feedback_result',
                  width: 100,
                  render: (value) =>
                    value === 'passed' ? '通过' : value === 'rejected' ? '未通过' : '-',
                },
                { title: '备注', dataIndex: 'feedback_note', ellipsis: true },
              ]}
            />
          </>
        )}
      </Drawer>
      {modal}
    </PageContainer>
  )
}
