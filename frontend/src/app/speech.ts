/** Spracheingabe über die Web Speech API – nur, wenn der Browser sie anbietet. */

interface RecognitionResult { 0: { transcript: string } }
interface RecognitionEvent { results: ArrayLike<RecognitionResult> }
interface Recognition {
  lang: string
  interimResults: boolean
  maxAlternatives: number
  onresult: ((e: RecognitionEvent) => void) | null
  onerror: (() => void) | null
  onend: (() => void) | null
  start: () => void
  stop: () => void
}
type RecognitionCtor = new () => Recognition

function ctor(): RecognitionCtor | null {
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor }
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null
}

export const speechAvailable = (): boolean => ctor() !== null

/** Startet eine Aufnahme; `onText` bekommt den erkannten Satz, `onEnd` kommt immer am Schluss. */
export function listen(onText: (text: string) => void, onEnd: () => void): (() => void) | null {
  const Ctor = ctor()
  if (!Ctor) return null
  const rec = new Ctor()
  rec.lang = 'de-DE'
  rec.interimResults = false
  rec.maxAlternatives = 1
  rec.onresult = (e) => onText(Array.from(e.results).map((r) => r[0].transcript).join(' ').trim())
  rec.onerror = () => onEnd()
  rec.onend = () => onEnd()
  rec.start()
  return () => rec.stop()
}
