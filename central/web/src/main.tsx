import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { installAuthExpiryWatch } from './authExpiry'
import './styles/tokens.css'
import './styles/app.css'

installAuthExpiryWatch() // 로그인 만료(프록시가 /api 를 로그인으로 돌림)를 알아채려고 — 화면을 그리기 전에

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
