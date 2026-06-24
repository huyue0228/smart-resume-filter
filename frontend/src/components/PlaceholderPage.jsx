import { PageContainer } from '@ant-design/pro-components'
import { Empty, Card } from 'antd'

export default function PlaceholderPage({ title, description }) {
  return (
    <PageContainer title={title} content={description}>
      <Card>
        <Empty description={`「${title}」页面建设中`} />
      </Card>
    </PageContainer>
  )
}
