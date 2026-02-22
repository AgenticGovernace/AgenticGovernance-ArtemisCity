/**
 * MCP Dashboard Frontend Entry Point
 *
 * This is the main entry point for the MCP (Model Context Protocol)
 * dashboard frontend. It bootstraps the React application with
 * Chakra UI theming and strict mode for development safety.
 *
 * @module main
 */

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { ChakraProvider } from '@chakra-ui/react'

/**
 * Bootstrap the React application into the DOM.
 * Renders the App component wrapped in StrictMode and ChakraProvider.
 */
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ChakraProvider>
      <App />
    </ChakraProvider>
  </StrictMode>,
)
