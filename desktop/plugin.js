// MyFolks Desktop page. Contact data stays in component memory: never in browser storage.
import {
  Badge, Button, EmptyState, ErrorState, ListRow, ROUTES_AREA, ScrollArea, SearchField, SegmentedControl, Separator,
  SIDEBAR_NAV_AREA, Skeleton, Textarea, host, useValue
} from '@hermes/plugin-sdk'
import { useCallback, useEffect, useRef, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

// All page wording, in one place. TENTATIVE until the Owner approves it.
const COPY = {
  title: 'MyFolks',
  searchPlaceholder: 'Find someone, or ask: priya allergy',
  searchLabel: 'Search your contacts',
  contacts: 'Contacts',
  review: 'To review',
  allContacts: 'All contacts',
  notSetUpTitle: 'MyFolks isn’t set up yet',
  notSetUpBody: 'Run this once in your terminal. It shows your recovery code.',
  notSetUpCommand: 'hermes myfolks setup',
  lockedTitle: 'MyFolks can’t open its data',
  lockedBody: 'Nothing was changed. If you moved to a new device, run this in your terminal.',
  lockedCommand: 'hermes myfolks recover',
  busyTitle: 'MyFolks is busy',
  busyBody: 'Try again in a moment.',
  errorTitle: 'Something went wrong',
  errorBody: 'Nothing was changed.',
  tryAgain: 'Try again',
  emptyTitle: 'No contacts yet',
  emptyBody: 'Bring them in from a vCard or CSV file, or save your first one with /contacts save.',
  emptyCommand: 'hermes myfolks import <file>',
  nothing: 'Nothing saved about that.',
  unsure: 'Related, not sure:',
  showing: name => `Showing ${name}.`,
  choose: 'More than one match. Choose one:',
  moreThanShown: (shown, total) => `Showing ${shown} of ${total}. Search to narrow it down.`,
  noLines: 'No lines saved yet.',
  privateTag: 'Private',
  linked: 'Linked',
  linkTo: (relation, name, outgoing) => (outgoing ? `${relation}: ${name}` : `${relation} of: ${name}`),
  addLine: 'Add a line',
  addPlaceholder: 'What do you want to remember?',
  save: 'Save',
  saving: 'Saving…',
  couldNotSave: 'That couldn’t be saved.',
  couldBe: 'Could be:',
  merge: name => `Merge into ${name}`,
  keep: 'Keep as new card',
  nothingToReview: 'Nothing to review.',
  reviewNote: 'These came from an import and look like someone you already have.',
  settingsTitle: 'MyFolks',
  storeRow: 'Your data',
  storeRowBody: 'Encrypted in this Hermes profile. Nothing is sent anywhere.',
  recoveryRow: 'New device',
  recoveryRowBody: 'Use your recovery code with: hermes myfolks recover',
  importRow: 'Import',
  importRowBody: 'Bring in a vCard or CSV with: hermes myfolks import <file>'
}

const NARROW_WIDTH = 640
const SEARCH_DELAY_MS = 200

function useApi(ctx, path, options) {
  const profile = useValue(host.state.profile)
  const [result, setResult] = useState({ loading: true })
  const [version, setVersion] = useState(0)
  const key = path === null ? null : `${path}|${options ? JSON.stringify(options.body) : ''}`

  useEffect(() => {
    if (key === null) {
      setResult({ loading: false })
      return undefined
    }
    let live = true
    setResult(previous => ({ ...previous, loading: true }))
    ctx
      .rest(path, options)
      .then(data => live && setResult({ loading: false, data }))
      .catch(() => live && setResult({ loading: false, failed: true }))
    return () => {
      live = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ctx, key, profile, version])

  return { ...result, reload: useCallback(() => setVersion(value => value + 1), []) }
}

function useNarrow() {
  const ref = useRef(null)
  const [narrow, setNarrow] = useState(false)

  useEffect(() => {
    if (!ref.current) {
      return undefined
    }
    const observer = new ResizeObserver(entries => setNarrow(entries[0].contentRect.width < NARROW_WIDTH))
    observer.observe(ref.current)
    return () => observer.disconnect()
  }, [])

  return [ref, narrow]
}

const Muted = ({ children }) => jsx('div', { className: 'text-xs text-(--ui-text-tertiary)', children })
const Note = ({ children }) => jsx('div', { className: 'text-sm text-(--ui-text-secondary)', children })
const Command = ({ children }) => jsx('code', { className: 'font-mono text-sm text-(--ui-text-secondary)', children })

function Receipt({ line }) {
  return jsxs('div', {
    className: 'flex flex-col gap-1 py-2',
    children: [
      jsx('div', { className: 'text-sm', children: `${line.number ? `${line.number}. ` : ''}“${line.text}”` }),
      jsxs('div', {
        className: 'flex items-center gap-2',
        children: [jsx(Muted, { children: line.receipt }), line.private ? jsx(Badge, { children: COPY.privateTag }) : null]
      })
    ]
  })
}

function CenteredMessage({ title, body, command, action }) {
  return jsxs('div', {
    className: 'flex h-full flex-col items-center justify-center gap-3 p-6',
    children: [
      jsx(EmptyState, { className: 'min-h-0', description: body, title }),
      command ? jsx(Command, { children: command }) : null,
      action || null
    ]
  })
}

function Failure({ title, body, command, onRetry }) {
  return jsx('div', {
    className: 'flex h-full flex-col items-center justify-center gap-3 p-6',
    children: jsxs(ErrorState, {
      title,
      description: body,
      children: [
        command ? jsx(Command, { children: command }) : null,
        onRetry ? jsx(Button, { onClick: onRetry, size: 'sm', variant: 'outline', children: COPY.tryAgain }) : null
      ]
    })
  })
}

function StatePanel({ state, onRetry }) {
  if (state === 'not_set_up') {
    return jsx(CenteredMessage, { body: COPY.notSetUpBody, command: COPY.notSetUpCommand, title: COPY.notSetUpTitle })
  }
  if (state === 'locked') {
    return jsx(Failure, { body: COPY.lockedBody, command: COPY.lockedCommand, title: COPY.lockedTitle })
  }
  if (state === 'busy') {
    return jsx(Failure, { body: COPY.busyBody, onRetry, title: COPY.busyTitle })
  }
  return jsx(Failure, { body: COPY.errorBody, onRetry, title: COPY.errorTitle })
}

function Answer({ answer, onOpen }) {
  if (!answer || answer.kind === 'card') {
    return null
  }
  const note = answer.corrected && answer.card ? jsx(Muted, { children: COPY.showing(answer.card.name) }) : null
  if (answer.kind === 'nothing') {
    return jsxs('div', { className: 'flex flex-col gap-1', children: [note, jsx(Note, { children: COPY.nothing })] })
  }
  if (answer.kind === 'choose') {
    return jsxs('div', {
      className: 'flex flex-col gap-2',
      children: [
        jsx(Note, { children: COPY.choose }),
        jsx('div', {
          className: 'flex flex-wrap gap-2',
          children: answer.choices.map(card =>
            jsx(Button, { onClick: () => onOpen(card), size: 'sm', variant: 'outline', children: `${card.name} (#${card.id})` }, card.id)
          )
        })
      ]
    })
  }
  return jsxs('div', {
    className: 'flex flex-col gap-1',
    children: [
      note,
      answer.kind === 'related' ? jsx(Note, { children: COPY.unsure }) : null,
      jsx('button', {
        className: 'self-start text-sm font-medium',
        onClick: () => onOpen(answer.card),
        type: 'button',
        children: answer.card.name
      }),
      ...answer.lines.map((line, index) => jsx(Receipt, { line }, index))
    ]
  })
}

function CardList({ cards, total, selectedId, onOpen }) {
  if (!cards.length) {
    return null
  }
  return jsxs('div', {
    className: 'flex flex-col gap-1',
    children: [
      ...cards.map(card =>
        jsx(
          Button,
          {
            'aria-pressed': selectedId === card.id,
            className: 'w-full justify-start',
            onClick: () => onOpen(card),
            size: 'sm',
            variant: selectedId === card.id ? 'secondary' : 'ghost',
            children: card.name
          },
          card.id
        )
      ),
      total > cards.length ? jsx(Muted, { children: COPY.moreThanShown(cards.length, total) }) : null
    ]
  })
}

function Trail({ trail, onCrumb }) {
  if (trail.length < 2) {
    return null
  }
  return jsx('nav', {
    'aria-label': 'Card trail',
    className: 'flex flex-wrap items-center gap-1 text-xs text-(--ui-text-tertiary)',
    children: trail.flatMap((card, index) => [
      index ? jsx('span', { 'aria-hidden': true, children: '›' }, `s${index}`) : null,
      jsx('button', { onClick: () => onCrumb(index), type: 'button', children: card.name }, card.id)
    ])
  })
}

function AddLine({ ctx, cardId, onSaved }) {
  const [text, setText] = useState('')
  const [saving, setSaving] = useState(false)
  const [failed, setFailed] = useState(false)

  const save = () => {
    setSaving(true)
    setFailed(false)
    ctx
      .rest(`/cards/${cardId}/lines`, { body: { text }, method: 'POST' })
      .then(result => {
        if (result.state === 'ready') {
          setText('')
          onSaved()
        } else {
          setFailed(true)
        }
      })
      .catch(() => setFailed(true))
      .finally(() => setSaving(false))
  }

  return jsxs('div', {
    className: 'flex flex-col gap-2',
    children: [
      jsx(Textarea, {
        'aria-label': COPY.addLine,
        onChange: event => setText(event.target.value),
        placeholder: COPY.addPlaceholder,
        value: text
      }),
      failed ? jsx(Muted, { children: COPY.couldNotSave }) : null,
      jsx(Button, {
        className: 'self-end',
        disabled: saving || !text.trim(),
        onClick: save,
        size: 'sm',
        children: saving ? COPY.saving : COPY.save
      })
    ]
  })
}

function CardView({ ctx, trail, onCrumb, onFollow, onBack }) {
  const current = trail[trail.length - 1]
  const detail = useApi(ctx, `/cards/${current.id}`)
  const data = detail.data

  if (detail.failed) {
    return jsx(StatePanel, { onRetry: detail.reload, state: 'error' })
  }
  if (data && data.state !== 'ready') {
    return jsx(StatePanel, { onRetry: detail.reload, state: data.state })
  }
  return jsxs('div', {
    className: 'flex flex-col gap-3',
    children: [
      onBack ? jsx(Button, { className: 'self-start', onClick: onBack, size: 'sm', variant: 'ghost', children: COPY.allContacts }) : null,
      jsx(Trail, { onCrumb, trail }),
      jsx('h2', { className: 'text-lg font-medium', children: current.name }),
      !data
        ? jsx(Skeleton, { className: 'h-16 w-full' })
        : jsxs('div', {
            className: 'flex flex-col',
            children: data.lines.length
              ? data.lines.map(line => jsx(Receipt, { line }, line.number))
              : [jsx(Muted, { children: COPY.noLines }, 'none')]
          }),
      data && data.links.length
        ? jsxs('div', {
            className: 'flex flex-col gap-2',
            children: [
              jsx(Separator, {}),
              jsx(Muted, { children: COPY.linked }),
              jsx('div', {
                className: 'flex flex-wrap gap-2',
                children: data.links.map(link =>
                  jsx(
                    Button,
                    {
                      onClick: () => onFollow({ id: link.id, name: link.name }),
                      size: 'sm',
                      variant: 'outline',
                      children: COPY.linkTo(link.relation, link.name, link.outgoing)
                    },
                    `${link.id}${link.relation}`
                  )
                )
              })
            ]
          })
        : null,
      jsx(Separator, {}),
      jsx(AddLine, { cardId: current.id, ctx, onSaved: detail.reload })
    ]
  })
}

function ReviewList({ ctx, onChanged }) {
  const review = useApi(ctx, '/review')
  const resolve = (item, action, cardId) =>
    ctx
      .rest(`/review/${item.id}`, { body: { action, card_id: cardId ?? null }, method: 'POST' })
      .then(() => {
        review.reload()
        onChanged()
      })
      .catch(() => review.reload())

  if (review.failed) {
    return jsx(StatePanel, { onRetry: review.reload, state: 'error' })
  }
  if (!review.data) {
    return jsx(Skeleton, { className: 'h-16 w-full' })
  }
  if (review.data.state !== 'ready') {
    return jsx(StatePanel, { onRetry: review.reload, state: review.data.state })
  }
  if (!review.data.items.length) {
    return jsx(EmptyState, { className: 'min-h-0', title: COPY.nothingToReview })
  }
  return jsxs('div', {
    className: 'flex flex-col gap-3',
    children: [
      jsx(Muted, { children: COPY.reviewNote }),
      ...review.data.items.map(item =>
        jsxs(
          'div',
          {
            className: 'flex flex-col gap-2 py-2',
            children: [
              jsx('div', { className: 'text-sm font-medium', children: item.name }),
              ...item.lines.map((line, index) => jsx(Muted, { children: line }, index)),
              jsx(Note, { children: COPY.couldBe }),
              jsxs('div', {
                className: 'flex flex-wrap gap-2',
                children: [
                  ...item.candidates.map(card =>
                    jsx(Button, { onClick: () => resolve(item, 'merge', card.id), size: 'sm', variant: 'outline', children: COPY.merge(card.name) }, card.id)
                  ),
                  jsx(Button, { onClick: () => resolve(item, 'keep'), size: 'sm', variant: 'ghost', children: COPY.keep })
                ]
              }),
              jsx(Separator, {})
            ]
          },
          item.id
        )
      )
    ]
  })
}

function Contacts({ ctx, narrow, tabs }) {
  const [query, setQuery] = useState('')
  const [settled, setSettled] = useState('')
  const [trail, setTrail] = useState([])
  const found = useApi(ctx, '/find', { body: { query: settled }, method: 'POST' })

  useEffect(() => {
    const timer = setTimeout(() => setSettled(query), SEARCH_DELAY_MS)
    return () => clearTimeout(timer)
  }, [query])

  const data = found.data
  const answer = data && data.state === 'ready' ? data.answer : null
  const answerCardId = answer && answer.kind === 'card' ? answer.card.id : null

  useEffect(() => {
    if (answerCardId !== null) {
      setTrail([answer.card])
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [answerCardId])

  const open = card => setTrail([card])
  const follow = card => setTrail(previous => [...previous, card])
  const crumb = index => setTrail(previous => previous.slice(0, index + 1))
  const showCard = trail.length > 0

  const search = jsx(SearchField, {
    'aria-label': COPY.searchLabel,
    loading: found.loading,
    onChange: value => {
      setQuery(value)
      setTrail([])
    },
    placeholder: COPY.searchPlaceholder,
    value: query,
    variant: 'box'
  })

  if (found.failed) {
    return jsxs('div', { className: 'flex h-full flex-col gap-3', children: [search, jsx(StatePanel, { onRetry: found.reload, state: 'error' })] })
  }
  if (data && data.state !== 'ready') {
    return jsx(StatePanel, { onRetry: found.reload, state: data.state })
  }

  const listColumn = jsxs('div', {
    className: 'flex min-w-0 flex-1 flex-col gap-3',
    children: [
      jsx(Answer, { answer, onOpen: open }),
      data ? jsx(CardList, { cards: data.cards, onOpen: open, selectedId: showCard ? trail[trail.length - 1].id : null, total: data.total }) : jsx(Skeleton, { className: 'h-16 w-full' })
    ]
  })
  const cardColumn = showCard
    ? jsx('div', {
        className: 'flex min-w-0 flex-1 flex-col',
        children: jsx(CardView, { ctx, onBack: narrow ? () => setTrail([]) : null, onCrumb: crumb, onFollow: follow, trail })
      })
    : null

  return jsxs('div', {
    className: 'flex flex-col gap-4',
    children: [
      search,
      tabs,
      narrow
        ? showCard ? cardColumn : listColumn
        : jsxs('div', { className: 'flex flex-row gap-6', children: [listColumn, cardColumn] }),
    ]
  })
}

function Page({ ctx }) {
  const [rootRef, narrow] = useNarrow()
  const [tab, setTab] = useState('contacts')
  const status = useApi(ctx, '/status')
  const data = status.data

  let body
  if (status.failed) {
    body = jsx(StatePanel, { onRetry: status.reload, state: 'error' })
  } else if (!data) {
    body = jsx('div', { className: 'p-6', children: jsx(Skeleton, { className: 'h-16 w-full' }) })
  } else if (data.state !== 'ready') {
    body = jsx(StatePanel, { onRetry: status.reload, state: data.state })
  } else if (data.cards === 0 && !data.review) {
    body = jsx(CenteredMessage, { body: COPY.emptyBody, command: COPY.emptyCommand, title: COPY.emptyTitle })
  } else {
    const tabs = jsx(SegmentedControl, {
      onChange: setTab,
      options: [
        { id: 'contacts', label: COPY.contacts },
        { id: 'review', label: data.review ? `${COPY.review} (${data.review})` : COPY.review }
      ],
      value: tab
    })
    body = jsx(ScrollArea, {
      className: 'h-full',
      children: jsxs('div', {
        className: 'mx-auto flex w-full max-w-4xl flex-col gap-4 p-6',
        children:
          tab === 'contacts'
            ? jsx(Contacts, { ctx, narrow, tabs })
            : [jsx('div', { children: tabs }, 'tabs'), jsx(ReviewList, { ctx, onChanged: status.reload }, 'review')]
      })
    })
  }

  return jsx('div', { className: 'h-full min-h-0', ref: rootRef, children: body })
}

function SettingsPage() {
  return jsxs('div', {
    className: 'flex flex-col gap-2',
    children: [
      jsx(ListRow, { description: COPY.storeRowBody, title: COPY.storeRow }),
      jsx(ListRow, { description: COPY.recoveryRowBody, title: COPY.recoveryRow }),
      jsx(ListRow, { description: COPY.importRowBody, title: COPY.importRow })
    ]
  })
}

export default {
  id: 'myfolks',
  name: COPY.title,
  register(ctx) {
    ctx.registerMany([
      { id: 'page', area: ROUTES_AREA, data: { path: '/myfolks' }, render: () => jsx(Page, { ctx }) },
      { id: 'nav', area: SIDEBAR_NAV_AREA, data: { codicon: 'book', label: COPY.title, path: '/myfolks' } }
    ])
    ctx.registerSettingsPage?.({ icon: 'book', id: 'settings', render: () => jsx(SettingsPage, {}), title: COPY.settingsTitle })
  }
}
