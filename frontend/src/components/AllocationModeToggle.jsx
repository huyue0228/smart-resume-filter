import { Segmented } from 'antd'

export default function AllocationModeToggle({ value, aiReady, onChange, className = '' }) {
  return (
    <Segmented
      aria-label="分配模式"
      className={`srf-allocation-mode-toggle ${className}`.trim()}
      size="small"
      value={value}
      onChange={onChange}
      options={[
        { label: 'Rule', value: 'rule' },
        { label: 'AI', value: 'ai', disabled: !aiReady },
      ]}
    />
  )
}
