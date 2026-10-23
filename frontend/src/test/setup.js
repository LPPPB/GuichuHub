import '@testing-library/jest-dom'

import { beforeEach } from 'vitest'
beforeEach(() => { if (typeof window !== 'undefined') window.history.replaceState({}, '', '/') })
