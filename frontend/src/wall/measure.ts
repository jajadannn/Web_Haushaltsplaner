/** Textbreite in Pixeln für die Kartenplanung der Zeitleiste (Canvas, gleiche Schrift wie die Karte). */

let context: CanvasRenderingContext2D | null = null

export function textWidth(text: string, font: string): number {
  if (typeof document !== 'undefined') {
    context ??= document.createElement('canvas').getContext('2d')
  }
  if (!context) return text.length * 0.6 * parseFloat(/(\d+)px/.exec(font)?.[1] ?? '16')
  context.font = font
  return context.measureText(text).width
}
