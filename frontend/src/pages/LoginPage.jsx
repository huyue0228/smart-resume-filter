import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { LoginForm, ProFormText } from '@ant-design/pro-components'
import { Alert, Typography } from 'antd'
import { LockOutlined, UserOutlined } from '@ant-design/icons'
import { useRole } from '../contexts/RoleContext'

const { Text } = Typography

export default function LoginPage() {
  const navigate = useNavigate()
  const { login } = useRole()
  const [error, setError] = useState('')

  const handleFinish = async (values) => {
    setError('')
    try {
      await login(values)
      navigate('/resumes', {
        replace: true,
      })
      return true
    } catch (err) {
      setError(err?.response?.data?.detail || '登录失败')
      return false
    }
  }

  return (
    <div className="login-shell">
      <LoginForm
        title="智能简历筛选系统"
        subTitle="正式权限基座：使用本地账号登录，W3 认证待外部方案接入"
        onFinish={handleFinish}
        submitter={{ searchConfig: { submitText: '登录' } }}
      >
        {error && <Alert type="error" showIcon message={error} />}
        <ProFormText
          name="username"
          fieldProps={{ size: 'large', prefix: <UserOutlined /> }}
          placeholder="用户名"
          rules={[{ required: true, message: '请输入用户名' }]}
        />
        <ProFormText.Password
          name="password"
          fieldProps={{ size: 'large', prefix: <LockOutlined /> }}
          placeholder="密码"
          rules={[{ required: true, message: '请输入密码' }]}
        />
        <Text type="secondary">
          本地初始化账号可通过 README 查看；生产环境请在 W3 接入后禁用临时密码登录。
        </Text>
      </LoginForm>
    </div>
  )
}
