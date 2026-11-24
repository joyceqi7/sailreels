import type { SVGProps } from 'react';

type IconProps = SVGProps<SVGSVGElement>;
const Icon = ({ children, ...props }: IconProps) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>
    {children}
  </svg>
);

export const HomeIcon = (props: IconProps) => <Icon {...props}><path d="m3 10 9-7 9 7v10h-6v-6H9v6H3Z" /></Icon>;
export const PlayIcon = (props: IconProps) => <Icon {...props}><rect x="4" y="3" width="16" height="18" rx="3"/><path d="m10 8 6 4-6 4Z"/></Icon>;
export const BookmarkIcon = (props: IconProps) => <Icon {...props}><path d="M6 3h12v18l-6-4-6 4Z"/></Icon>;
export const UserIcon = (props: IconProps) => <Icon {...props}><circle cx="12" cy="8" r="4"/><path d="M4 21c.8-4.4 3.5-6 8-6s7.2 1.6 8 6"/></Icon>;
export const BackIcon = (props: IconProps) => <Icon {...props}><path d="m15 18-6-6 6-6"/></Icon>;
export const HeartIcon = (props: IconProps) => <Icon {...props}><path d="M20.8 4.6a5.4 5.4 0 0 0-7.6 0L12 5.8l-1.2-1.2a5.4 5.4 0 0 0-7.6 7.6L12 21l8.8-8.8a5.4 5.4 0 0 0 0-7.6Z"/></Icon>;
export const CommentIcon = (props: IconProps) => <Icon {...props}><path d="M21 12a8 8 0 0 1-8 8 9 9 0 0 1-4-.9L3 21l1.8-5A8 8 0 1 1 21 12Z"/><path d="M8 12h.01M12 12h.01M16 12h.01"/></Icon>;
export const ShareIcon = (props: IconProps) => <Icon {...props}><path d="m14 4 7 7-7 7v-4C8 14 5 16 3 20c.5-8 4-11 11-11Z"/></Icon>;
export const VolumeIcon = (props: IconProps) => <Icon {...props}><path d="M11 5 6 9H2v6h4l5 4Z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/></Icon>;
export const GridIcon = (props: IconProps) => <Icon {...props}><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></Icon>;
export const DramaIcon = (props: IconProps) => (
  <Icon {...props}>
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <path d="M7 4v16M17 4v16M3 8h4M3 12h4M3 16h4M17 8h4M17 12h4M17 16h4" />
    <path d="m10 9 5 3-5 3Z" fill="currentColor" stroke="none" />
  </Icon>
);
export const ChevronUpIcon = (props: IconProps) => <Icon {...props}><path d="m6 15 6-6 6 6" /></Icon>;
