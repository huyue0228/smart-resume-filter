import { Checkbox, Modal, Space, Typography } from 'antd'
import AllocationModeToggle from '../../components/AllocationModeToggle'

export default function ResumeProcessModal({
  open,
  processing,
  allocationAvailability,
  selectedMode,
  processCurrentSelected,
  processCandidateCount,
  processStatusSelection,
  statusOptions,
  onCurrentSelectedChange,
  onModeChange,
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
      okButtonProps={{
        disabled: (
          (!processCurrentSelected && !processStatusSelection.length)
          || (selectedMode === 'ai' && !allocationAvailability.ai_ready)
        ),
      }}
      onOk={onConfirm}
      onCancel={onCancel}
    >
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Typography.Text>
          选择当前勾选的候选人，或按简历状态重新处理。两种范围互斥，系统会保留历史分配与反馈记录。
        </Typography.Text>
        <Space direction="vertical" size={6}>
          <Typography.Text strong>分配模式</Typography.Text>
          <AllocationModeToggle
            value={selectedMode}
            aiReady={allocationAvailability.ai_ready}
            onChange={onModeChange}
          />
          {!allocationAvailability.ai_ready && (
            <Typography.Text type="secondary">AI 当前不可用，本次只能选择 Rule。</Typography.Text>
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
