import { createContext, type ReactNode, useContext } from 'react'

export interface ProductPresentation {
  name: string
  showWakeWord: boolean
  wordmark: string
}

const HERMES_PRESENTATION: ProductPresentation = {
  name: 'Hermes',
  showWakeWord: true,
  wordmark: 'HERMES AGENT'
}

export const MACMAN_PRESENTATION: ProductPresentation = {
  name: 'MacMan',
  // The bundled on-device acoustic model recognizes "hey hermes". Hiding
  // that control is more honest than relabeling it "hey macman" while the
  // detector still listens for a different phrase.
  showWakeWord: false,
  wordmark: 'MACMAN'
}

const ProductPresentationContext = createContext<ProductPresentation>(HERMES_PRESENTATION)

export function ProductPresentationProvider({
  children,
  value
}: {
  children: ReactNode
  value: ProductPresentation
}) {
  return <ProductPresentationContext.Provider value={value}>{children}</ProductPresentationContext.Provider>
}

export function useProductPresentation(): ProductPresentation {
  return useContext(ProductPresentationContext)
}

export function presentProductCopy(value: string, presentation: ProductPresentation): string {
  return value.replaceAll('Hermes Agent', presentation.name).replaceAll('Hermes', presentation.name)
}
