import { Suspense } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { SquarePage } from './pages/SquarePage';
import { LazyForYouPage, LazyTheaterPage } from './router/lazy-pages';
import { SessionGate } from './components/SessionGate';
import { DetailPage } from './pages/DetailPage';
import { SubscriptionPage } from './pages/SubscriptionPage';
import { HistoryPage, ProfilePage, WalletPage } from './pages/AccountPages';
import { IAP_ENABLED } from './monetization';

// IAA-only builds have nothing to buy: old links to these pages land on Profile instead.
const profile = <Navigate to="/playlet/profile" replace />;

export default function App() {
  return (
    <BrowserRouter>
      <SessionGate>
        <Routes>
          <Route path="/" element={<Navigate to="/playlet/square" replace />} />
          <Route path="/playlet/square" element={<SquarePage />} />
          <Route path="/playlet/detail" element={<DetailPage />} />
          <Route
            path="/playlet/foryou"
            element={(
              <Suspense fallback={<main className="app-shell feed-page" />}>
                <LazyForYouPage />
              </Suspense>
            )}
          />
          <Route path="/playlet/subscription" element={IAP_ENABLED ? <SubscriptionPage /> : profile} />
          <Route path="/playlet/profile" element={<ProfilePage />} />
          <Route path="/playlet/wallet" element={IAP_ENABLED ? <WalletPage /> : profile} />
          <Route path="/playlet/history" element={<HistoryPage />} />
          <Route
            path="/playlet/theater"
            element={(
              <Suspense fallback={<main className="app-shell theater-page" />}>
                <LazyTheaterPage />
              </Suspense>
            )}
          />
          <Route path="*" element={<Navigate to="/playlet/square" replace />} />
        </Routes>
      </SessionGate>
    </BrowserRouter>
  );
}
