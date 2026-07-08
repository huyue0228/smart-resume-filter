import { useEffect, useRef, useState } from 'react'
import {
  ModalForm,
  PageContainer,
  ProFormDigit,
  ProFormSelect,
  ProFormSwitch,
  ProFormText,
  ProTable,
} from '@ant-design/pro-components'
import { Button, Popconfirm, Space, Tag, message } from 'antd'
import { createJob, deleteJob, fetchDepartments, fetchJobs, updateJob } from '../api/services'
import ImportButton from '../components/ImportButton'
import { useRole } from '../contexts/RoleContext'
import {
  normalizeTableFilters,
  selectColumnFilter,
  textColumnFilter,
  useResizableColumns,
} from '../components/DataTableControls'

const IMPORT_FIELDS = [
  { key: 'jobs', label: '校招岗位分类及专业要求 (.xlsx/.xls/.csv)', accept: '.xlsx,.xls,.csv' },
]

export default function JobsPage() {
  const actionRef = useRef()
  const { hasPermission } = useRole()
  const [jobModal, setJobModal] = useState({ open: false, record: null })
  const [departments, setDepartments] = useState([])

  useEffect(() => {
    fetchDepartments({ page_size: 500 })
      .then(({ data }) => setDepartments(data?.results || []))
      .catch(() => setDepartments([]))
  }, [])

  const canManageJobs = hasPermission('job.manage')
  const departmentOptions = departments
    .filter((department) => department.level === 2)
    .map((department) => ({
      label: department.name,
      value: department.id,
    }))

  const baseColumns = [
    { title: '招聘主体', dataIndex: 'entity', width: 100, ...textColumnFilter('筛选主体') },
    {
      title: '对外名称',
      dataIndex: 'public_name',
      fixed: 'left',
      width: 160,
      ellipsis: true,
      ...textColumnFilter('筛选对外名称'),
    },
    {
      title: '职位名称',
      dataIndex: 'position_name',
      width: 160,
      ellipsis: true,
      ...textColumnFilter('筛选职位名称'),
    },
    { title: '岗位类别', dataIndex: 'category', width: 120, ...textColumnFilter('筛选类别') },
    { title: '岗位族', dataIndex: 'job_family', width: 110, ...textColumnFilter('筛选岗位族') },
    { title: '部门', dataIndex: 'department_name', width: 140, ...textColumnFilter('筛选部门') },
    { title: '工作地点', dataIndex: 'location', width: 110, ...textColumnFilter('筛选地点') },
    { title: '学历要求', dataIndex: 'education', width: 100, ...textColumnFilter('筛选学历') },
    {
      title: '需求专业',
      dataIndex: 'majors',
      width: 180,
      search: false,
      ellipsis: true,
      render: (_, record) => record.majors?.join('、') || '-',
    },
    { title: 'HC', dataIndex: 'headcount', width: 70, ...textColumnFilter('筛选HC') },
    {
      title: '对外发布',
      dataIndex: 'is_public',
      width: 90,
      ...selectColumnFilter([
        { text: '是', value: 'true' },
        { text: '否', value: 'false' },
      ]),
      render: (_, r) =>
        r.is_public ? <Tag color="green">是</Tag> : <Tag>否</Tag>,
    },
    canManageJobs && {
      title: '操作',
      valueType: 'option',
      width: 120,
      fixed: 'right',
      render: (_, record) => (
        <Space>
          <a onClick={() => setJobModal({ open: true, record })}>编辑</a>
          <Popconfirm
            title="删除岗位"
            description="删除后岗位将停用，历史投递和分配记录仍可追溯。"
            okText="删除"
            okButtonProps={{ danger: true }}
            onConfirm={async () => {
              await deleteJob(record.id)
              message.success('岗位已删除')
              actionRef.current?.reload()
            }}
          >
            <a style={{ color: '#cf1322' }}>删除</a>
          </Popconfirm>
        </Space>
      ),
    },
  ].filter(Boolean)
  const { columns, components, scrollX } = useResizableColumns(baseColumns)

  return (
    <PageContainer title="岗位需求" content="校招岗位分类及专业要求，可导入维护。">
      <ProTable
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        components={components}
        scroll={{ x: scrollX }}
        search={false}
        pagination={{ defaultPageSize: 10, showSizeChanger: true }}
        toolBarRender={() =>
          [
            canManageJobs && (
              <Button
                key="create"
                type="primary"
                onClick={() => setJobModal({ open: true, record: null })}
              >
                新增岗位
              </Button>
            ),
            canManageJobs && (
              <ImportButton
                key="import"
                buttonText="导入岗位"
                title="导入岗位分类及专业要求"
                fields={IMPORT_FIELDS}
                onDone={() => actionRef.current?.reload()}
              />
            ),
          ].filter(Boolean)
        }
        request={async (params, _sort, filters) => {
          const {
            current,
            pageSize,
          } = params
          const tableFilters = normalizeTableFilters(filters, [
            'entity',
            'public_name',
            'position_name',
            'category',
            'job_family',
            'department_name',
            'location',
            'education',
            'headcount',
            'is_public',
          ])
          try {
            const { data } = await fetchJobs({
              page: current,
              page_size: pageSize,
              ...tableFilters,
            })
            return { data: data?.results || [], total: data?.count || 0, success: true }
          } catch {
            return { data: [], total: 0, success: false }
          }
        }}
      />
      <ModalForm
        title={jobModal.record ? '编辑岗位' : '新增岗位'}
        open={jobModal.open}
        modalProps={{
          destroyOnHidden: true,
          onCancel: () => setJobModal({ open: false, record: null }),
        }}
        initialValues={
          jobModal.record
            ? {
                ...jobModal.record,
                major_names: jobModal.record.majors?.join('、') || '',
              }
            : { is_public: true, headcount: 0 }
        }
        onFinish={async (values) => {
          const majorNames =
            values.major_names
              ?.split(/[、,，;；\n]/)
              .map((item) => item.trim())
              .filter(Boolean) || []
          const body = {
            ...values,
            department: values.department || null,
            major_names: majorNames,
          }
          if (jobModal.record) {
            await updateJob(jobModal.record.id, body)
          } else {
            await createJob(body)
          }
          message.success('岗位已保存')
          setJobModal({ open: false, record: null })
          actionRef.current?.reload()
          return true
        }}
      >
        <ProFormText name="entity" label="招聘主体" placeholder="如 GW / YLS" />
        <ProFormText name="public_name" label="对外名称" />
        <ProFormText name="position_name" label="职位名称" rules={[{ required: true }]} />
        <ProFormText name="category" label="岗位类别" />
        <ProFormText name="job_family" label="岗位族" />
        <ProFormSelect
          name="department"
          label="部门"
          showSearch
          options={departmentOptions}
        />
        <ProFormText name="location" label="工作地点" />
        <ProFormText name="education" label="学历要求" />
        <ProFormText
          name="major_names"
          label="需求专业"
          placeholder="多个专业可用顿号、逗号、分号或换行分隔"
        />
        <ProFormDigit name="headcount" label="HC" min={0} fieldProps={{ precision: 0 }} />
        <ProFormSwitch name="is_public" label="对外发布" />
      </ModalForm>
    </PageContainer>
  )
}
