import axios from 'axios'
import { message } from 'antd'

// Axios instance. baseURL is /api which Vite dev server proxies to
// http://localhost:8000 (see vite.config.js). Backend demo uses AllowAny,
// so no auth token handling is needed.
const client = axios.create({
  baseURL: '/api',
  timeout: 60000,
})

client.interceptors.response.use(
  (response) => response,
  (error) => {
    const detail =
      error?.response?.data?.detail ||
      error?.response?.data?.message ||
      error?.message ||
      '请求失败'
    message.error(String(detail))
    return Promise.reject(error)
  },
)

export default client
