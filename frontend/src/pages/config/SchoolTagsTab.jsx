import { useRef } from 'react'
import { ModalForm, ProFormSwitch, ProFormText, ProTable } from '@ant-design/pro-components'
import { Button, Popconfirm, Space, Tag, message } from 'antd'
import {
  createSchoolTag,
  deleteSchoolTag,
  fetchSchoolTags,
  updateSchoolTag,
} from '../../api/services'
import { useModalRecord } from './useModalRecord'

export default function SchoolTagsTab() {
  const actionRef = useRef()
  const modal = useModalRecord()

  const saveTag = async (values) => {
    const body = {
      ...values,
      is_default: Boolean(values.is_default),
      is_active: Boolean(values.is_active),
    }
    if (modal.record) {
      await updateSchoolTag(modal.record.id, body)
      message.success('标签已保存')
    } else {
      await createSchoolTag(body)
      message.success('标签已创建')
    }
    modal.close()
    actionRef.current?.reload()
    return true
  }

  const columns = [
    { title: '编码', dataIndex: 'code', width: 150, fixed: 'left' },
    { title: '名称', dataIndex: 'name', width: 160 },
    {
      title: '默认标签',
      dataIndex: 'is_default',
      width: 100,
      render: (value) => (value ? <Tag color="blue">默认</Tag> : '-'),
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      width: 90,
      render: (value) =>
        value ? <Tag color="green">启用</Tag> : <Tag color="default">停用</Tag>,
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
            title="删除院校标签"
            description="若标签已被院校或规则引用，后端会阻止删除。"
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
            onConfirm={async () => {
              await deleteSchoolTag(record.id)
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

  return (
    <>
      <ProTable
        actionRef={actionRef}
        rowKey="id"
        search={false}
        columns={columns}
        scroll={{ x: 760 }}
        pagination={{ defaultPageSize: 10, showSizeChanger: true }}
        toolBarRender={() => [
          <Button key="create" type="primary" onClick={() => modal.open()}>
            新增标签
          </Button>,
        ]}
        request={async (params) => {
          const { current, pageSize } = params
          const { data } = await fetchSchoolTags({
            page: current,
            page_size: pageSize,
          })
          return {
            data: data?.results || [],
            total: data?.count || 0,
            success: true,
          }
        }}
      />
      <ModalForm
        key={modal.record?.id || 'create-tag'}
        title={modal.record ? '编辑院校标签' : '新增院校标签'}
        open={modal.visible}
        width={520}
        modalProps={{
          destroyOnHidden: true,
          onCancel: modal.close,
        }}
        initialValues={
          modal.record || {
            is_active: true,
            is_default: false,
          }
        }
        onFinish={saveTag}
      >
        <ProFormText
          name="code"
          label="标签编码"
          rules={[{ required: true, message: '请输入标签编码' }]}
        />
        <ProFormText
          name="name"
          label="标签名称"
          rules={[{ required: true, message: '请输入标签名称' }]}
        />
        <ProFormSwitch name="is_default" label="是否默认标签" />
        <ProFormSwitch name="is_active" label="是否启用" />
      </ModalForm>
    </>
  )
}
