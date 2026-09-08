import { QueryClient, useQueryClient } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Providers } from '../providers'

function Reporter() {
  const queryClient = useQueryClient()
  const queries = queryClient.getDefaultOptions().queries

  return (
    <span data-testid="defaults">
      {String(queries?.staleTime)}/{String(queries?.retry)}
    </span>
  )
}

describe('Providers', () => {
  it('puts a query client with the app’s defaults over the tree', () => {
    render(
      <Providers>
        <Reporter />
      </Providers>,
    )

    expect(screen.getByTestId('defaults')).toHaveTextContent('5000/1')
  })

  it('uses the client it is given, so a test can seed the cache', () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { staleTime: 7, retry: 3 } },
    })

    render(
      <Providers client={queryClient}>
        <Reporter />
      </Providers>,
    )

    expect(screen.getByTestId('defaults')).toHaveTextContent('7/3')
  })
})
