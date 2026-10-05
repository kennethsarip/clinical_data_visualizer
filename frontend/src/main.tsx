import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// Dynamic subset: the browser downloads only the glyph ranges a page uses.
import 'pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css'
import './index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
