// Public-facing business details. Replace the placeholders before launch.
// Wording shown to customers (tagline, hours, the parts promise...) lives in
// the translation files: src/i18n/locales/en.json and es.json.
export const business = {
  name: 'Wrench on Wheels',
  phone: '(555) 010-0000',
  email: 'hello@example.com'
}

export function phoneHref(phone: string = business.phone): string {
  return `tel:${phone.replace(/[^\d+]/g, '')}`
}
