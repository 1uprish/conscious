import { BrandMark } from '@/components/brand-mark'

export type InstallProductName = 'Hermes' | 'MacMan'

export function rebrandInstallCopy<T>(value: T, productName: InstallProductName): T {
  if (productName === 'Hermes') {
    return value
  }

  if (typeof value === 'string') {
    return value.replace(/Hermes(?: Agent| Desktop)?/gi, productName) as T
  }

  if (typeof value === 'function') {
    const fn = value as (...args: unknown[]) => unknown

    return ((...args: unknown[]) => rebrandInstallCopy(fn(...args), productName)) as T
  }

  if (Array.isArray(value)) {
    return value.map(item => rebrandInstallCopy(item, productName)) as T
  }

  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value).map(([key, child]) => [key, rebrandInstallCopy(child, productName)])
    ) as T
  }

  return value
}

export function InstallProductMark({
  className,
  productName
}: {
  className?: string
  productName: InstallProductName
}) {
  return productName === 'MacMan' ? (
    <img alt="" className={className} src="./macman-mark-transparent.png" />
  ) : (
    <BrandMark className={className} />
  )
}
