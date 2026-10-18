import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import './index.css'
import { readBootstrap } from './publicPages/bootstrap'
import { initialProps } from './publicPages/contract'

const container = document.getElementById('root')
const bootstrap = readBootstrap(document)
const app = (
  <React.StrictMode>
    <App {...(bootstrap ? initialProps(bootstrap) : {})} />
  </React.StrictMode>
)
if (bootstrap) ReactDOM.hydrateRoot(container, app)
else ReactDOM.createRoot(container).render(app)
