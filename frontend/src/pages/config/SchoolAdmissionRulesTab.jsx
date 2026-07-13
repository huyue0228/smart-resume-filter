import { useEffect, useMemo, useRef, useState } from 'react'
import {
  ModalForm,
  ProFormDigit,
  ProFormSelect,
  ProFormSwitch,
  ProFormText,
  ProTable,
} from '@ant-design/pro-components'
import { Button, Popconfirm, Space, Tag, message } from 'antd'
import {
  createSchoolTagRule,
  deleteSchoolTagRule,
  fetchSchoolTags,
  fetchSchoolTagRules,
  updateSchoolTagRule,
} from '../../api/services'
import { useModalRecord } from './useModalRecord'
import {
  normalizeTableFilters,
  selectColumnFilter,
  textColumnFilter,
  useResizableColumns,
} from '../../components/DataTableControls'

function tagIds(tags) {
  return (tags || []).map((tag) => tag.id).filter(Boolean)
}

function TagList({ tags = [], color }) {
  if (!tags.length) return '-'
  return (
    <Space wrap>
      {tags.map((tag) => (
        <Tag color={color} key={tag.id}>
          {tag.name}
        </Tag>
      ))}
    </Space>
  )
}

export default function SchoolAdmissionRulesTab() {
  const actionRef = useRef()
  const modal = useModalRecord()
  const [schoolTags, setSchoolTags] = useState([])

  const loadSchoolTags = async () => {
    const { data } = await fetchSchoolTags({ page_size: 500, is_active: 'true' })
    setSchoolTags(data?.results || [])
  }

  useEffect(() => {
    loadSchoolTags()
  }, [])

  const schoolTagOptions = useMemo(
    () =>
      schoolTags.map((tag) => ({
        label: `${tag.name}（${tag.code}）`,
        value: tag.id,
      })),
    [schoolTags],
  )

  const saveRule = async (values) => {
    const body = {
      name: values.name,
      priority: values.priority ?? 0,
      is_active: Boolean(values.is_active),
      first_degree_tag_ids: values.first_degree_tag_ids || [],
      highest_degree_tag_ids: values.highest_degree_tag_ids || [],
    }
    if (modal.record) {
      await updateSchoolTagRule(modal.record.id, body)
      message.success('规则已保存')
    } else {
      await createSchoolTagRule(body)
      message.success('规则已创建')
    }
    modal.close()
    actionRef.current?.reload()
    return true
  }

  const baseColumns = [
    {
      title: '规则名称',
      dataIndex: 'name',
      width: 180,
      fixed: 'left',
      ...textColumnFilter('筛选规则名称'),
    },
    { title: '优先级', dataIndex: 'priority', width: 90, ...textColumnFilter('筛选优先级') },
    {
      title: '状态',
      dataIndex: 'is_active',
      width: 90,
      ...selectColumnFilter([
        { value: 'true', text: '启用' },
        { value: 'false', text: '停用' },
      ]),
      render: (value) =>
        value ? <Tag color="green">启用</Tag> : <Tag color="default">停用</Tag>,
    },
    {
      title: '第一学历允许标签',
      dataIndex: 'first_degree_tags',
      render: (tags) => <TagList tags={tags} />,
    },
    {
      title: '最高学历允许标签',
      dataIndex: 'highest_degree_tags',
      render: (tags) => <TagList tags={tags} color="blue" />,
    },
    {
      title: '操作',
      valueType: 'option',
      width: 130,
      fixed: 'right',
      render: (_, record) => (
        <Space>
          <a onClick={() => modal.open(record)}>编辑</a>
          <Popconfirm
            title="删除院校规则"
            description="删除后不会影响历史分配记录中的规则快照。"
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
            onConfirm={async () => {
              await deleteSchoolTagRule(record.id)
              message.success('已删除')
              actionRef.current?.reload()
            }}
          >
            <a style={{ color: '#cf1322' }}>删除</a>
          </Popconfirm>
        </Space>
      ),
    },
  ]
  const { columns, components, scrollX } = useResizableColumns(baseColumns)

  const initialValues = modal.record
    ? {
        ...modal.record,
        first_degree_tag_ids: tagIds(modal.record.first_degree_tags),
        highest_degree_tag_ids: tagIds(modal.record.highest_degree_tags),
      }
    : {
        is_active: true,
        priority: 0,
        first_degree_tag_ids: [],
        highest_degree_tag_ids: [],
      }

  return (
    <>
      <ProTable
        actionRef={actionRef}
        rowKey="id"
        search={false}
        columns={columns}
        components={components}
        scroll={{ x: scrollX }}
        pagination={{ defaultPageSize: 10, showSizeChanger: true }}
        toolBarRender={() => [
          <Button key="create" type="primary" onClick={() => modal.open()}>
            新增规则
          </Button>,
        ]}
        request={async (params, _sort, filters) => {
          const { current, pageSize } = params
          const tableFilters = normalizeTableFilters(filters, [
            'name',
            'priority',
            'is_active',
          ])
          const { data } = await fetchSchoolTagRules({
            page: current,
            page_size: pageSize,
            ...tableFilters,
          })
          return {
            data: data?.results || [],
            total: data?.count || 0,
            success: true,
          }
        }}
      />
      <ModalForm
        key={modal.record?.id || 'create-rule'}
        title={modal.record ? '编辑院校准入规则' : '新增院校准入规则'}
        open={modal.visible}
        width={560}
        modalProps={{
          destroyOnHidden: true,
          onCancel: modal.close,
        }}
        initialValues={initialValues}
        onFinish={saveRule}
      >
        <ProFormText
          name="name"
          label="规则名称"
          rules={[{ required: true, message: '请输入规则名称' }]}
        />
        <ProFormDigit name="priority" label="优先级" min={0} fieldProps={{ precision: 0 }} />
        <ProFormSwitch name="is_active" label="是否启用" />
        <ProFormSelect
          name="first_degree_tag_ids"
          label="第一学历允许标签"
          mode="multiple"
          options={schoolTagOptions}
          placeholder="选择第一学历允许标签"
          rules={[{ required: true, message: '请至少配置一个第一学历标签' }]}
        />
        <ProFormSelect
          name="highest_degree_tag_ids"
          label="最高学历允许标签"
          mode="multiple"
          options={schoolTagOptions}
          placeholder="选择最高学历允许标签"
          rules={[{ required: true, message: '请至少配置一个最高学历标签' }]}
        />
      </ModalForm>
    </>
  )
}
