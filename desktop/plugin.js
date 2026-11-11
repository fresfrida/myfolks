// MyFolks Desktop page. Contact data stays in component memory: never in browser storage.
import {
  Badge, Button, ConfirmDialog, EmptyState, ErrorState, Input, ListRow, ROUTES_AREA, ScrollArea, SearchField, SegmentedControl, Separator,
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
  notSetUpBody: 'Set it up here. You’ll see your recovery code once.',
  notSetUpCommand: 'hermes myfolks setup',
  setUp: 'Set up MyFolks',
  settingUp: 'Setting up…',
  setupDone: 'MyFolks is ready.',
  setupNext: 'Next, bring in your contacts: send /myfolks sync to use your Google contacts, or run hermes myfolks import <file>.',
  setupStoredHere: 'MyFolks keeps what you save only in your Hermes folder, on the computer that runs Hermes. If you use it from a chat app like Telegram, that app also keeps a copy of the chat. Your address book is separate, and MyFolks never changes it.',
  setupCodeIntro: 'Your recovery code. It is shown once. Keep it somewhere safe:',
  setupCodePurpose: 'You need it if MyFolks stops opening, and to back up or export.',
  setupBackupIntro: 'Back up what you’ve saved, in case you lose that computer:',
  setupBackupCommand: 'hermes myfolks backup',
  setupBackupResult: 'You’ll get one file, locked with a passphrase you choose. Keep it somewhere else, like a USB drive.',
  setupHermesBackupHeading: 'About Hermes’s own backups',
  setupHermesBackupNote: 'If you also run hermes backup, those files include MyFolks.',
  savedIt: 'I’ve saved it',
  lockedTitle: 'MyFolks can’t open its data',
  lockedBody: 'Nothing was changed. To unlock it with your recovery code, run this in your terminal.',
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
  choose: 'More than one match. Choose one:',
  moreThanShown: (shown, total) => `Showing ${shown} of ${total}. Search to narrow it down.`,
  noLines: 'No lines saved yet.',
  hiddenTag: 'Hidden from chat',
  hideFromChat: 'Hide from chat',
  showInChat: 'Show in chat',
  linked: 'Linked',
  linkTo: (relation, name, outgoing) => {
    const word = relation.charAt(0).toUpperCase() + relation.slice(1)
    return outgoing ? `${word}: ${name}` : `${word} of ${name}`
  },
  deletedPersonToast: name => `Deleted ${name}.`,
  deletedLineToast: 'Deleted.',
  savedToast: 'Saved.',
  addedToast: name => `Added ${name}.`,
  newPerson: 'New person',
  nameLabel: 'Name',
  firstDetailLabel: 'First detail (optional)',
  add: 'Add',
  didYouMean: names => `Did you mean ${names.join(' or ')}?`,
  nameIsDetailWord: 'Start with their name, like Priya.',
  editLine: 'Edit',
  undo: 'Undo',
  couldNotUndo: 'That couldn’t be undone.',
  deletePerson: 'Delete person',
  deleteLine: 'Delete',
  deletePersonTitle: name => `Delete ${name}?`,
  deletePersonBody: 'They disappear from MyFolks. Their details stay in history, and Undo brings them back.',
  delete: 'Delete',
  cancel: 'Cancel',
  couldNotDelete: 'That couldn’t be deleted.',
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
  storeRowBody: 'Encrypted in this Hermes profile. MyFolks connects only to Google, and only after you send /myfolks sync.',
  recoveryRow: 'If MyFolks stops opening',
  recoveryRowBody: 'Unlock it with your recovery code: hermes myfolks recover',
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

// After a change made on this page: a toast whose Undo undoes exactly that change, and only while it is
// still the latest one. The backend refuses otherwise, so a later change (from chat, say) is never undone.
function offerUndo(ctx, message, changeId, reload) {
  host.notify({
    kind: 'success',
    message,
    action: changeId
      ? {
          label: COPY.undo,
          onClick: () =>
            ctx
              .rest('/undo', { body: { change_id: changeId }, method: 'POST' })
              .then(result => {
                host.notify({ kind: result.state === 'ready' ? 'info' : 'warning', message: result.message || COPY.couldNotUndo })
                reload()
              })
              .catch(() => host.notify({ kind: 'error', message: COPY.couldNotUndo }))
        }
      : undefined
  })
}

const Muted = ({ children }) => jsx('div', { className: 'text-xs text-(--ui-text-tertiary)', children })
const Note = ({ children }) => jsx('div', { className: 'text-sm text-(--ui-text-secondary)', children })
const Command = ({ children }) => jsx('code', { className: 'font-mono text-sm text-(--ui-text-secondary)', children })
// The one thing the setup screen must get across: the card title's size on the command font.
const RecoveryCode = ({ children }) => jsx('code', { className: 'font-mono text-lg font-medium', children })

// The signature element: the saved words first, then when and where they came from.
// Edit a line in place. Save goes through the same path as /myfolks correct, so the old text stays in history.
function EditLine({ ctx, line, onDone }) {
  const [text, setText] = useState(line.text)
  const [saving, setSaving] = useState(false)
  const [failed, setFailed] = useState(false)
  const save = () => {
    setSaving(true)
    setFailed(false)
    ctx
      .rest(`/lines/${line.id}/edit`, { body: { text }, method: 'POST' })
      .then(result => {
        if (result.state === 'ready' || result.state === 'unchanged') {
          onDone(result)
        } else {
          setFailed(true)
        }
      })
      .catch(() => setFailed(true))
      .finally(() => setSaving(false))
  }
  return jsxs('div', {
    className: 'flex flex-col gap-2 py-1',
    children: [
      jsx(Textarea, { 'aria-label': COPY.editLine, onChange: event => setText(event.target.value), value: text }),
      failed ? jsx(Muted, { children: COPY.couldNotSave }) : null,
      jsxs('div', {
        className: 'flex gap-2 self-end',
        children: [
          jsx(Button, { onClick: () => onDone(null), size: 'sm', variant: 'ghost', children: COPY.cancel }),
          jsx(Button, { disabled: saving || !text.trim(), onClick: save, size: 'sm', children: saving ? COPY.saving : COPY.save })
        ]
      })
    ]
  })
}

function Receipt({ line, onToggleHidden, onDelete, onEdit }) {
  return jsxs('div', {
    className: 'flex flex-col gap-1 border-l-2 py-1 pl-3',
    style: { borderColor: 'var(--ui-accent)' },
    children: [
      jsxs('div', {
        className: 'text-base font-medium',
        children: [
          line.number ? jsx('span', { className: 'text-(--ui-text-tertiary)', children: `${line.number}. ` }) : null,
          `\u201c${line.text}\u201d`
        ]
      }),
      jsxs('div', {
        className: 'flex items-center gap-2',
        children: [
          jsx(Muted, { children: line.receipt }),
          line.private ? jsx(Badge, { children: COPY.hiddenTag }) : null,
          onToggleHidden
            ? jsx(Button, { onClick: () => onToggleHidden(line), size: 'inline', variant: 'text', children: line.private ? COPY.showInChat : COPY.hideFromChat })
            : null,
          onEdit ? jsx(Button, { onClick: () => onEdit(line), size: 'inline', variant: 'text', children: COPY.editLine }) : null,
          onDelete ? jsx(Button, { onClick: () => onDelete(line), size: 'inline', variant: 'text', children: COPY.deleteLine }) : null
        ]
      })
    ]
  })
}

function CenteredMessage({ title, body, command, action }) {
  return jsxs('div', {
    className: 'flex h-full flex-col items-center justify-center gap-3 p-6',
    children: [
      jsxs('div', {
        className: 'flex flex-col items-center gap-2',
        children: [jsx(EmptyState, { className: 'min-h-0', description: body, title }), command ? jsx(Command, { children: command }) : null]
      }),
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
  if (answer.kind === 'nothing') {
    return jsx(Note, { children: COPY.nothing })
  }
  if (answer.kind === 'did_you_mean') {
    return jsxs('div', {
      className: 'flex flex-col gap-2',
      children: [
        jsx(Note, { children: answer.question }),
        jsx('div', {
          className: 'flex flex-wrap gap-2',
          children: answer.choices.map(card =>
            jsx(Button, { onClick: () => onOpen(card), size: 'sm', variant: 'outline', children: card.name }, card.id)
          )
        })
      ]
    })
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

// Add someone from the list page, with the chat save rules: an exact name opens that person, a close name asks first.
function NewPerson({ ctx, onOpen, onAdded }) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [detail, setDetail] = useState('')
  const [close, setClose] = useState(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState(null)
  const reset = () => {
    setOpen(false)
    setName('')
    setDetail('')
    setClose(null)
    setMessage(null)
  }
  const submit = choice => {
    setBusy(true)
    setMessage(null)
    ctx
      .rest('/people', { body: { choice: choice ?? null, first_detail: detail, name }, method: 'POST' })
      .then(result => {
        if (result.state === 'ready') {
          reset()
          onAdded(result)
        } else if (result.state === 'exists') {
          reset()
          onOpen(result.card)
        } else if (result.state === 'close') {
          setClose(result.names)
        } else {
          setMessage(result.state === 'detail_word' ? COPY.nameIsDetailWord : COPY.couldNotSave)
        }
      })
      .catch(() => setMessage(COPY.couldNotSave))
      .finally(() => setBusy(false))
  }

  if (!open) {
    return jsx(Button, { className: 'self-start', onClick: () => setOpen(true), size: 'sm', variant: 'outline', children: COPY.newPerson })
  }
  return jsxs('div', {
    className: 'flex flex-col gap-2',
    children: [
      jsx(Input, {
        'aria-label': COPY.nameLabel,
        onChange: event => {
          setName(event.target.value)
          setClose(null)
        },
        placeholder: COPY.nameLabel,
        value: name
      }),
      jsx(Textarea, { 'aria-label': COPY.firstDetailLabel, onChange: event => setDetail(event.target.value), placeholder: COPY.firstDetailLabel, value: detail }),
      message ? jsx(Muted, { children: message }) : null,
      close
        ? jsxs('div', {
            className: 'flex flex-col gap-2',
            children: [
              jsx(Note, { children: COPY.didYouMean(close.map(card => card.name)) }),
              jsxs('div', {
                className: 'flex flex-wrap gap-2',
                children: [
                  ...close.map(card => jsx(Button, { disabled: busy, onClick: () => submit(String(card.id)), size: 'sm', variant: 'outline', children: card.name }, card.id)),
                  jsx(Button, { disabled: busy, onClick: () => submit('new'), size: 'sm', children: COPY.newPerson }, 'new')
                ]
              })
            ]
          })
        : jsxs('div', {
            className: 'flex gap-2 self-end',
            children: [
              jsx(Button, { onClick: reset, size: 'sm', variant: 'ghost', children: COPY.cancel }),
              jsx(Button, { disabled: busy || !name.trim(), onClick: () => submit(null), size: 'sm', children: COPY.add })
            ]
          })
    ]
  })
}

function CardView({ ctx, trail, onCrumb, onFollow, onBack, onDeleted }) {
  const current = trail[trail.length - 1]
  const detail = useApi(ctx, `/cards/${current.id}`)
  const data = detail.data
  const [confirming, setConfirming] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const edited = result => {
    setEditingId(null)
    if (result && result.state === 'ready') {
      detail.reload()
      offerUndo(ctx, COPY.savedToast, result.change_id, detail.reload)
    }
  }
  // ConfirmDialog shows a thrown error inline and keeps the dialog open; nothing is deleted then.
  const deletePerson = () =>
    ctx.rest(`/cards/${current.id}/delete`, { body: {}, method: 'POST' }).then(result => {
      if (result.state !== 'ready') {
        throw new Error(COPY.couldNotDelete)
      }
      setConfirming(false)
      onDeleted(result)
    })
  const toggleHidden = line =>
    ctx
      .rest(`/lines/${line.id}/hidden`, { body: { hidden: !line.private }, method: 'POST' })
      .then(detail.reload)
      .catch(detail.reload)
  const deleteLine = line =>
    ctx
      .rest(`/lines/${line.id}/delete`, { body: {}, method: 'POST' })
      .then(result => {
        detail.reload()
        if (result.state === 'ready') {
          offerUndo(ctx, COPY.deletedLineToast, result.change_id, detail.reload)
        }
      })
      .catch(detail.reload)

  if (detail.failed) {
    return jsx(StatePanel, { onRetry: detail.reload, state: 'error' })
  }
  if (data && data.state !== 'ready') {
    return jsx(StatePanel, { onRetry: detail.reload, state: data.state })
  }
  return jsxs('div', {
    className: 'flex flex-col gap-3',
    children: [
      onBack ? jsx(Button, { className: 'self-start', onClick: onBack, size: 'inline', variant: 'ghost', children: COPY.allContacts }) : null,
      jsx(Trail, { onCrumb, trail }),
      jsx('h2', { className: 'text-lg font-medium', children: current.name }),
      !data
        ? jsx(Skeleton, { className: 'h-16 w-full' })
        : jsxs('div', {
            className: 'flex flex-col',
            children: data.lines.length
              ? data.lines.map(line =>
                  line.id === editingId
                    ? jsx(EditLine, { ctx, line, onDone: edited }, line.number)
                    : jsx(Receipt, { line, onDelete: deleteLine, onEdit: target => setEditingId(target.id), onToggleHidden: toggleHidden }, line.number)
                )
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
      jsx(AddLine, { cardId: current.id, ctx, onSaved: detail.reload }),
      data
        ? jsx(Button, { className: 'self-start', onClick: () => setConfirming(true), size: 'sm', variant: 'ghost', children: COPY.deletePerson })
        : null,
      jsx(ConfirmDialog, {
        cancelLabel: COPY.cancel,
        confirmLabel: COPY.delete,
        description: COPY.deletePersonBody,
        destructive: true,
        onClose: () => setConfirming(false),
        onConfirm: deletePerson,
        open: confirming,
        title: COPY.deletePersonTitle(current.name)
      })
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

  // Each new search result can open its card, even when a changed search lands on the same person.
  useEffect(() => {
    if (answerCardId !== null) {
      setTrail([answer.card])
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [answerCardId, data])

  const open = card => setTrail([card])
  const follow = card => setTrail(previous => [...previous, card])
  const crumb = index => setTrail(previous => previous.slice(0, index + 1))
  const added = result => {
    found.reload()
    setTrail([result.card])
    offerUndo(ctx, COPY.addedToast(result.card.name), result.change_id, () => {
      setTrail([])
      found.reload()
    })
  }
  const deleted = result => {
    setTrail([])
    found.reload()
    offerUndo(ctx, COPY.deletedPersonToast(result.name), result.change_id, found.reload)
  }
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
      jsx(NewPerson, { ctx, onAdded: added, onOpen: open }),
      jsx(Answer, { answer, onOpen: open }),
      data ? jsx(CardList, { cards: data.cards, onOpen: open, selectedId: showCard ? trail[trail.length - 1].id : null, total: data.total }) : jsx(Skeleton, { className: 'h-16 w-full' })
    ]
  })
  const cardColumn = showCard
    ? jsx('div', {
        className: 'flex min-w-0 flex-1 flex-col',
        children: jsx(CardView, { ctx, onBack: narrow ? () => setTrail([]) : null, onCrumb: crumb, onDeleted: deleted, onFollow: follow, trail })
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

function SetupPanel({ ctx, onDone }) {
  const [step, setStep] = useState({ name: 'ask' })
  const start = () => {
    setStep({ name: 'working' })
    ctx
      .rest('/setup', { body: {}, method: 'POST' })
      .then(data => (data && data.code ? setStep({ name: 'code', code: data.code }) : onDone()))
      .catch(() => setStep({ name: 'failed' }))
  }
  if (step.name === 'failed') {
    return jsx(Failure, { body: COPY.errorBody, onRetry: start, title: COPY.errorTitle })
  }
  if (step.name === 'code') {
    const group = children => jsx('div', { className: 'flex flex-col items-center gap-2 text-center', children })
    return jsxs('div', {
      className: 'flex h-full flex-col items-center justify-center gap-4 p-6',
      children: [
        group([jsx(Note, { children: COPY.setupDone }), jsx(Note, { children: COPY.setupNext }), jsx(Note, { children: COPY.setupStoredHere })]),
        group([
          jsx(Note, { children: COPY.setupCodeIntro }),
          jsx(RecoveryCode, { children: step.code }),
          jsx(Note, { children: COPY.setupCodePurpose })
        ]),
        group([
          jsx(Note, { children: COPY.setupBackupIntro }),
          jsx(Command, { children: COPY.setupBackupCommand }),
          jsx(Note, { children: COPY.setupBackupResult })
        ]),
        group([
          jsx('div', { className: 'text-sm font-medium', children: COPY.setupHermesBackupHeading }),
          jsx(Note, { children: COPY.setupHermesBackupNote })
        ]),
        jsx(Button, { onClick: onDone, size: 'sm', children: COPY.savedIt })
      ]
    })
  }
  return jsx(CenteredMessage, {
    action: jsx(Button, { disabled: step.name === 'working', onClick: start, size: 'sm', children: step.name === 'working' ? COPY.settingUp : COPY.setUp }),
    body: COPY.notSetUpBody,
    title: COPY.notSetUpTitle
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
  } else if (data.state === 'not_set_up') {
    body = jsx(SetupPanel, { ctx, onDone: status.reload })
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
