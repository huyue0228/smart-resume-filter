import { useRef } from 'react'
import { PageContainer, ProTable } from '@ant-design/pro-components'
import { Button, Tag, Space, message } from 'antd'
import { fetchResumes } from '../api/services'
import ImportButton from '../components/ImportButton'

const RESUME_IMPORT_FIELDS = [
  { key: 'resume_list', label: '① 简历信息列表 (.xlsx)', accept: '.xlsx,.xls' },
  { key: 'resume_package', label: '② 简历包 (.zip，文件名含应聘ID)', accept: '.zip' },
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

  const columns = [
    {
      title: '姓名',
      dataIndex: 'candidate_name',
      fixed: 'left',
      width: 100,
    },
    { title: '手机', dataIndex: 'phone', width: 130, search: false },
    { title: '主体', dataIndex: 'entity', width: 120, search: false },
    {
      title: '投递岗位',
      dataIndex: 'position_name',
      ellipsis: true,
      search: false,
    },
    {
      title: '志愿',
      dataIndex: 'volunteer_rank',
      width: 80,
      search: false,
    },
    {
      title: '岗位类别',
      dataIndex: 'job_category',
      width: 110,
      search: false,
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
          <a onClick={() => message.info(`查看 ${record.candidate_name}`)}>
            查看
          </a>
          <a onClick={() => message.info(`编辑 ${record.candidate_name}`)}>
            编辑
          </a>
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
    <PageContainer title="简历库" content="投递记录列表，支持时间 / 状态 / 关键词筛选。">
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
            buttonText="导入简历"
            title="导入简历（简历列表 + 简历包）"
            fields={RESUME_IMPORT_FIELDS}
            onDone={() => actionRef.current?.reload()}
          />,
          <Button key="add" onClick={() => message.info('新增')}>
            新增
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
    </PageContainer>
  )
}
