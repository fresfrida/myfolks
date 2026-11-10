// MyFolks pre-flight hello page. Throwaway.
import { ROUTES_AREA, SIDEBAR_NAV_AREA } from '@hermes/plugin-sdk'
import { useEffect, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

function HelloPage({ ctx }) {
  const [state, setState] = useState({ status: 'loading' })

  useEffect(() => {
    ctx
      .rest('/hello')
      .then(data => setState({ status: 'ready', data }))
      .catch(error => setState({ status: 'error', error: String(error) }))
  }, [ctx])

  return jsxs('div', {
    className: 'flex h-full flex-col gap-2 p-6 text-sm',
    children: [
      jsx('div', { className: 'font-medium', children: 'MyFolks pre-flight' }),
      jsx('div', {
        id: 'myfolks-hello-result',
        className: 'text-(--ui-text-tertiary)',
        children: JSON.stringify(state)
      })
    ]
  })
}

export default {
  id: 'myfolks',
  name: 'MyFolks',
  register(ctx) {
    ctx.registerMany([
      { id: 'page', area: ROUTES_AREA, data: { path: '/myfolks' }, render: () => jsx(HelloPage, { ctx }) },
      { id: 'nav', area: SIDEBAR_NAV_AREA, data: { path: '/myfolks', label: 'MyFolks', codicon: 'book' } }
    ])
  }
}
