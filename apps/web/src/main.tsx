import { createRoot } from 'react-dom/client';
import App from './App';
import { prepareMinisDramaPreload } from './plugins/minis-player';
import './styles.css';

// Resolve TTMinis.getPlayer() and prepare MSE preload before React starts its
// first render. Preload is an optimization, so an unsupported SDK never blocks
// the application from rendering or falling back to normal playback.
void prepareMinisDramaPreload();

// Do not wrap the theater in React StrictMode: its development-only remount
// would create, destroy and immediately recreate the native Minis Player.
createRoot(document.getElementById('root')!).render(<App />);
