import { useEffect, useMemo, useRef, useState } from 'react'
import { PlusOutlined } from '@ant-design/icons'
import {
  ModalForm,
  ProFormDigit,
  ProFormSelect,
  ProFormSwitch,
  ProFormText,
  ProFormTextArea,
  ProTable,
} from '@ant-design/pro-components'
import { Button, Popconfirm, Space, Tag, Typography, message } from 'antd'
import {
  createMajorAlias,
  createMajorCategory,
  deleteMajorAlias,
  deleteMajorCategory,
  fetchMajorAliases,
  fetchMajorCategories,
  updateMajorAlias,
  updateMajorCategory,
} from '../../api/services'
import { useModalRecord } from './useModalRecord'
import {
  normalizeTableFilters,
  selectColumnFilter,
  textColumnFilter,
  useResizableColumns,
} from '../../components/DataTableControls'

const matchTypeOptions = [
  { label: '包含匹配', value: 'contains' },
  { label: '精确匹配', value: 'exact' },
]

const sourceOptions = [
  { label: '内置', value: 'builtin' },
  { label: '人工维护', value: 'user' },
  { label: '导入', value: 'import' },
]

function StatusTag({ active }) {
  return active ? <Tag color="green">启用</Tag> : <Tag color="default">停用</Tag>
}

export default function MajorDictionaryTab() {
  const categoryActionRef = useRef()
  const aliasActionRef = useRef()
  const categoryModal = useModalRecord()
  const aliasModal = useModalRecord()
  const [categories, setCategories] = useState([])
  const [selectedCategory, setSelectedCategory] = useState(null)

  const loadCategoryOptions = async () => {
    const { data } = await fetchMajorCategories({ page_size: 500 })
    setCategories(data?.results || [])
  }

  useEffect(() => {
    loadCategoryOptions()
  }, [])

  useEffect(() => {
    aliasActionRef.current?.reload()
  }, [selectedCategory])

  const categoryOptions = useMemo(
    () =>
      categories.map((category) => ({
        label: `${category.name}（${category.code}）`,
        value: category.id,
      })),
    [categories],
  )

  const saveCategory = async (values) => {
    const body = {
      code: values.code,
      name: values.name,
      description: values.description || '',
      is_active: Boolean(values.is_active),
      sort_order: values.sort_order ?? 0,
    }
    if (categoryModal.record) {
      await updateMajorCategory(categoryModal.record.id, body)
      message.success('专业大类已保存')
    } else {
      await createMajorCategory(body)
      message.success('专业大类已创建')
    }
    categoryModal.close()
    await loadCategoryOptions()
    categoryActionRef.current?.reload()
    aliasActionRef.current?.reload()
    return true
  }

  const saveAlias = async (values) => {
    const body = {
      category: values.category,
      name: values.name,
      match_type: values.match_type || 'contains',
      source: values.source || 'user',
      note: values.note || '',
      is_active: Boolean(values.is_active),
    }
    if (aliasModal.record) {
      await updateMajorAlias(aliasModal.record.id, body)
      message.success('专业别名已保存')
    } else {
      await createMajorAlias(body)
      message.success('专业别名已创建')
    }
    aliasModal.close()
    categoryActionRef.current?.reload()
    aliasActionRef.current?.reload()
    return true
  }

  const categoryBaseColumns = [
    {
      title: '编码',
      dataIndex: 'code',
      width: 170,
      fixed: 'left',
      ...textColumnFilter('筛选编码'),
    },
    { title: '名称', dataIndex: 'name', width: 180, ...textColumnFilter('筛选名称') },
    {
      title: '说明',
      dataIndex: 'description',
      ellipsis: true,
      ...textColumnFilter('筛选说明'),
    },
    { title: '别名数', dataIndex: 'alias_count', width: 90 },
    { title: '排序', dataIndex: 'sort_order', width: 80 },
    {
      title: '状态',
      dataIndex: 'is_active',
      width: 90,
      ...selectColumnFilter([
        { value: 'true', text: '启用' },
        { value: 'false', text: '停用' },
      ]),
      render: (value) => <StatusTag active={value} />,
    },
    {
      title: '操作',
      valueType: 'option',
      width: 150,
      fixed: 'right',
      render: (_, record) => (
        <Space>
          <a onClick={() => categoryModal.open(record)}>编辑</a>
          <a
            onClick={() => {
              setSelectedCategory(record)
            }}
          >
            别名
          </a>
          <Popconfirm
            title="删除专业大类"
            description="若大类仍有关联别名，后端会阻止删除。"
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
            onConfirm={async () => {
              await deleteMajorCategory(record.id)
              message.success('已删除')
              if (selectedCategory?.id === record.id) {
                setSelectedCategory(null)
              }
              await loadCategoryOptions()
              categoryActionRef.current?.reload()
              aliasActionRef.current?.reload()
            }}
          >
            <a style={{ color: '#cf1322' }}>删除</a>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const aliasBaseColumns = [
    {
      title: '专业名称 / 关键词',
      dataIndex: 'name',
      width: 180,
      fixed: 'left',
      ...textColumnFilter('筛选专业名称'),
    },
    {
      title: '规范化名称',
      dataIndex: 'normalized_name',
      width: 150,
      ...textColumnFilter('筛选规范化名称'),
    },
    {
      title: '所属大类',
      key: 'category',
      dataIndex: 'category_name',
      width: 180,
      ...selectColumnFilter(
        categories.map((category) => ({ value: category.id, text: category.name })),
      ),
    },
    {
      title: '匹配方式',
      dataIndex: 'match_type',
      width: 110,
      ...selectColumnFilter(
        matchTypeOptions.map((item) => ({ value: item.value, text: item.label })),
      ),
      render: (value) =>
        value === 'exact' ? <Tag color="blue">精确</Tag> : <Tag color="cyan">包含</Tag>,
    },
    {
      title: '来源',
      dataIndex: 'source',
      width: 100,
      ...selectColumnFilter(
        sourceOptions.map((item) => ({ value: item.value, text: item.label })),
      ),
      render: (value) => {
        const option = sourceOptions.find((item) => item.value === value)
        return option?.label || value || '-'
      },
    },
    { title: '备注', dataIndex: 'note', ellipsis: true, ...textColumnFilter('筛选备注') },
    {
      title: '状态',
      dataIndex: 'is_active',
      width: 90,
      ...selectColumnFilter([
        { value: 'true', text: '启用' },
        { value: 'false', text: '停用' },
      ]),
      render: (value) => <StatusTag active={value} />,
    },
    {
      title: '操作',
      valueType: 'option',
      width: 130,
      fixed: 'right',
      render: (_, record) => (
        <Space>
          <a onClick={() => aliasModal.open(record)}>编辑</a>
          <Popconfirm
            title="删除专业别名"
            description="删除后后续分配不再使用该关键词。"
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
            onConfirm={async () => {
              await deleteMajorAlias(record.id)
              message.success('已删除')
              categoryActionRef.current?.reload()
              aliasActionRef.current?.reload()
            }}
          >
            <a style={{ color: '#cf1322' }}>删除</a>
          </Popconfirm>
        </Space>
      ),
    },
  ]
  const {
    columns: categoryColumns,
    components: categoryComponents,
    scrollX: categoryScrollX,
  } = useResizableColumns(categoryBaseColumns)
  const {
    columns: aliasColumns,
    components: aliasComponents,
    scrollX: aliasScrollX,
  } = useResizableColumns(aliasBaseColumns)

  const categoryInitialValues = categoryModal.record || {
    is_active: true,
    sort_order: 0,
  }

  const aliasInitialValues = aliasModal.record
    ? {
        ...aliasModal.record,
        category: aliasModal.record.category,
      }
    : {
        category: selectedCategory?.id,
        match_type: 'contains',
        source: 'user',
        is_active: true,
      }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <ProTable
        actionRef={categoryActionRef}
        rowKey="id"
        search={false}
        columns={categoryColumns}
        components={categoryComponents}
        scroll={{ x: categoryScrollX }}
        pagination={{ defaultPageSize: 10, showSizeChanger: true }}
        rowClassName={(record) =>
          selectedCategory?.id === record.id ? 'ant-table-row-selected' : ''
        }
        onRow={(record) => ({
          onClick: () => setSelectedCategory(record),
        })}
        toolBarRender={() => [
          <Button
            icon={<PlusOutlined />}
            key="create"
            type="primary"
            onClick={() => categoryModal.open()}
          >
            新增大类
          </Button>,
        ]}
        request={async (params, _sort, filters) => {
          const { current, pageSize } = params
          const tableFilters = normalizeTableFilters(filters, [
            'code',
            'name',
            'description',
            'is_active',
          ])
          const { data } = await fetchMajorCategories({
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

      <ProTable
        actionRef={aliasActionRef}
        rowKey="id"
        search={false}
        columns={aliasColumns}
        components={aliasComponents}
        scroll={{ x: aliasScrollX }}
        pagination={{ defaultPageSize: 10, showSizeChanger: true }}
        headerTitle={
          selectedCategory ? (
            <Space>
              <Typography.Text>{selectedCategory.name}</Typography.Text>
              <Tag>{selectedCategory.code}</Tag>
              <a onClick={() => setSelectedCategory(null)}>全部别名</a>
            </Space>
          ) : (
            '全部别名'
          )
        }
        toolBarRender={() => [
          <Button
            icon={<PlusOutlined />}
            key="create"
            type="primary"
            onClick={() => aliasModal.open()}
          >
            新增别名
          </Button>,
        ]}
        request={async (params, _sort, filters) => {
          const { current, pageSize } = params
          const tableFilters = normalizeTableFilters(filters, [
            'category',
            'name',
            'normalized_name',
            'match_type',
            'source',
            'note',
            'is_active',
          ])
          const { data } = await fetchMajorAliases({
            page: current,
            page_size: pageSize,
            ...tableFilters,
            category: selectedCategory?.id || tableFilters.category,
          })
          return {
            data: data?.results || [],
            total: data?.count || 0,
            success: true,
          }
        }}
      />

      <ModalForm
        key={categoryModal.record?.id || 'create-major-category'}
        title={categoryModal.record ? '编辑专业大类' : '新增专业大类'}
        open={categoryModal.visible}
        width={560}
        modalProps={{
          destroyOnHidden: true,
          onCancel: categoryModal.close,
        }}
        initialValues={categoryInitialValues}
        onFinish={saveCategory}
      >
        <ProFormText
          name="code"
          label="大类编码"
          rules={[{ required: true, message: '请输入大类编码' }]}
        />
        <ProFormText
          name="name"
          label="大类名称"
          rules={[{ required: true, message: '请输入大类名称' }]}
        />
        <ProFormTextArea name="description" label="说明" fieldProps={{ rows: 3 }} />
        <ProFormDigit name="sort_order" label="排序" fieldProps={{ precision: 0 }} />
        <ProFormSwitch name="is_active" label="是否启用" />
      </ModalForm>

      <ModalForm
        key={aliasModal.record?.id || 'create-major-alias'}
        title={aliasModal.record ? '编辑专业别名' : '新增专业别名'}
        open={aliasModal.visible}
        width={560}
        modalProps={{
          destroyOnHidden: true,
          onCancel: aliasModal.close,
        }}
        initialValues={aliasInitialValues}
        onFinish={saveAlias}
      >
        <ProFormSelect
          name="category"
          label="所属大类"
          options={categoryOptions}
          rules={[{ required: true, message: '请选择所属大类' }]}
        />
        <ProFormText
          name="name"
          label="专业名称 / 关键词"
          rules={[{ required: true, message: '请输入专业名称或关键词' }]}
        />
        <ProFormSelect
          name="match_type"
          label="匹配方式"
          options={matchTypeOptions}
          rules={[{ required: true, message: '请选择匹配方式' }]}
        />
        <ProFormSelect
          name="source"
          label="来源"
          options={sourceOptions}
          rules={[{ required: true, message: '请选择来源' }]}
        />
        <ProFormTextArea name="note" label="备注" fieldProps={{ rows: 3 }} />
        <ProFormSwitch name="is_active" label="是否启用" />
      </ModalForm>
    </Space>
  )
}
