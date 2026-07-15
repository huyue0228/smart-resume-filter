import { Checkbox, Modal, Space, Tag, Typography } from 'antd'

export default function ResumeProcessModal({
  open,
  processing,
  allocationMode,
  processCurrentSelected,
  processCandidateCount,
  processStatusSelection,
  statusOptions,
  onCurrentSelectedChange,
  onStatusChange,
  onConfirm,
  onCancel,
}) {
  return (
    <Modal
      title="处理简历"
      open={open}
      okText="开始处理"
      cancelText="取消"
      confirmLoading={processing}
      okButtonProps={{ disabled: !processCurrentSelected && !processStatusSelection.length }}
      onOk={onConfirm}
      onCancel={onCancel}
    >
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Typography.Text>
          选择当前勾选的候选人，或按简历状态重新处理。两种范围互斥，系统会保留历史分配与反馈记录。
        </Typography.Text>
        <Space>
          <Typography.Text>当前系统分配模式：</Typography.Text>
          <Tag color={allocationMode.mode === 'ai' ? 'purple' : 'blue'}>
            {allocationMode.mode === 'ai' ? 'AI 分配' : '规则分配'}
          </Tag>
          {allocationMode.mode === 'ai' && !allocationMode.ai_ready && (
            <Typography.Text type="danger">模型连接尚未测试成功</Typography.Text>
          )}
        </Space>
        <Checkbox
          checked={processCurrentSelected}
          disabled={!processCandidateCount}
          onChange={onCurrentSelectedChange}
        >
          当前选中（{processCandidateCount}）
        </Checkbox>
        <Checkbox.Group
          value={processStatusSelection}
          onChange={onStatusChange}
          style={{ width: '100%' }}
        >
          <Space direction="vertical">
            {Object.entries(statusOptions).map(([value, item]) => (
              <Checkbox key={value} value={value}>
                {item.text}
              </Checkbox>
            ))}
          </Space>
        </Checkbox.Group>
      </Space>
    </Modal>
  )
}
