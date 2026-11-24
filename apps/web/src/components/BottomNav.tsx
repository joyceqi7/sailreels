import { BookmarkIcon, HomeIcon, PlayIcon, UserIcon } from './Icons';
import { NavLink } from 'react-router-dom';

// VIP lives in Profile (top card), not in the tab bar.
const items = [
  { label: 'Home', Icon: HomeIcon, to: '/playlet/square' },
  { label: 'For You', Icon: PlayIcon, to: '/playlet/foryou' },
  { label: 'History', Icon: BookmarkIcon, to: '/playlet/history' },
  { label: 'Profile', Icon: UserIcon, to: '/playlet/profile' },
];

export function BottomNav() {
  return (
    <nav className="bottom-nav" aria-label="Primary navigation">
      {items.map(({ label, Icon, to }) => (
        <NavLink to={to} key={label} className={({ isActive }) => isActive ? 'nav-item is-active' : 'nav-item'}>
          <Icon />
          <span>{label}</span>
        </NavLink>
      ))}
    </nav>
  );
}
