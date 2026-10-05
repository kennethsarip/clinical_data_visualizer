/** `start_year` -> "Start year". */
export function humanize(field: string): string {
  const words = field.replace(/_/g, ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}

/** 2968 -> "2,968". */
export function count(n: number): string {
  return n.toLocaleString('en-US')
}

/** 1 -> "1 trial", 4 -> "4 trials". */
export function trials(n: number): string {
  return `${count(n)} trial${n === 1 ? '' : 's'}`
}
