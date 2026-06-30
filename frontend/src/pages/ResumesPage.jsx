import { useRef, useEffect, useState } from 'react'
import { PageContainer, ProTable } from '@ant-design/pro-components'
import { Button, Tag, Space, Modal, message, Drawer, Descriptions, Table } from 'antd'
import { UndoOutlined } from '@ant-design/icons'
import {
  fetchCandidates,
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

// 上传后自动处理：前置数据准备 + 候选人处理主流程
const PROCESS_STEPS = [
  { step: 'step3', label: '院校分类' },
  { step: 'step4', label: '需求录入' },
  { step: 'step1', label: '查重与志愿排序' },
  { step: 'step2', label: '简历分类、分配与下发' },
]

const STATUS_OPTIONS = {
  pending: { text: '待分配', status: 'Default' },
  in_progress: { text: '进行中', status: 'Processing' },
  passed: { text: '已通过', status: 'Success' },
  archived: { text: '已归档', status: 'Error' },
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
    { title: '姓名', dataIndex: 'name', fixed: 'left', width: 100 },
    { title: '手机', dataIndex: 'phone', width: 130, search: false },
    {
      title: '当前志愿',
      dataIndex: 'current_rank',
      width: 90,
      search: false,
      render: (_, record) => record.current_rank || '-',
    },
    {
      title: '当前主体',
      dataIndex: ['current_resume', 'entity'],
      width: 120,
      search: false,
      render: (_, record) => record.current_resume?.entity || '-',
    },
    {
      title: '当前投递岗位',
      dataIndex: ['current_resume', 'position_name'],
      ellipsis: true,
      search: false,
      render: (_, record) => record.current_resume?.position_name || '-',
    },
    {
      title: '岗位类别',
      dataIndex: ['current_resume', 'job_category'],
      width: 110,
      search: false,
      render: (_, record) => record.current_resume?.job_category || '-',
    },
    {
      title: '院校标签',
      dataIndex: 'school_tag',
      width: 110,
      search: false,
      render: (_, record) =>
        record.school_tag ? <Tag color="blue">{record.school_tag}</Tag> : '-',
    },
    {
      title: '流程状态',
      dataIndex: 'workflow_status',
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
          <a onClick={() => setDetailRecord(record)}>详情</a>
          <a onClick={() => message.info(`编辑 ${record.name}`)}>编辑</a>
          <a
            style={{ color: '#cf1322' }}
            onClick={() => message.info(`删除 ${record.name}`)}
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
      content="按候选人聚合展示当前有效志愿；点开详情查看全部投递、分配尝试和反馈。"
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
          const {
            current,
            pageSize,
            workflow_status,
            search,
            imported_after,
            imported_before,
          } = params
          try {
            const { data } = await fetchCandidates({
              page: current,
              page_size: pageSize,
              status: workflow_status,
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
      <Drawer
        title={detailRecord ? `${detailRecord.name} 的简历详情` : '简历详情'}
        width={900}
        open={!!detailRecord}
        onClose={() => setDetailRecord(null)}
      >
        {detailRecord && (
          <>
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="姓名">{detailRecord.name}</Descriptions.Item>
              <Descriptions.Item label="手机">{detailRecord.phone || '-'}</Descriptions.Item>
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
              <Descriptions.Item label="流程状态">
                {STATUS_OPTIONS[detailRecord.workflow_status]?.text || '-'}
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
              ]}
            />

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
