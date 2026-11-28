import { create } from 'zustand';

export type WorkspaceId =
  | 'console'
  | 'computer'
  | 'globe'
  | 'sentinel'
  | 'agents'
  | 'research'
  | 'developer'
  | 'academic'
  | 'professional'
  | 'communications'
  | 'smarthome'
  | 'automation'
  | 'containers'
  | 'voice'
  | 'models'
  | 'connections'
  | 'audit'
  | 'repair'
  | 'settings';

export interface WorkspaceMeta {
  id: WorkspaceId;
  label: string;
  group: 'Core' | 'Intelligence' | 'Operations' | 'System';
  shortcut: string;
}

export const WORKSPACES: WorkspaceMeta[] = [
  { id: 'console', label: 'Console', group: 'Core', shortcut: '1' },
  { id: 'computer', label: 'Computer Control', group: 'Core', shortcut: '2' },
  { id: 'globe', label: 'Global Intelligence', group: 'Intelligence', shortcut: '3' },
  { id: 'sentinel', label: 'Sentinel Cybersecurity', group: 'Operations', shortcut: '4' },
  { id: 'agents', label: 'Agent Center', group: 'Core', shortcut: '5' },
  { id: 'research', label: 'Research', group: 'Intelligence', shortcut: '6' },
  { id: 'developer', label: 'Developer Center', group: 'Core', shortcut: '7' },
  { id: 'academic', label: 'Academic Center', group: 'Intelligence', shortcut: '8' },
  { id: 'professional', label: 'Professional & Docs', group: 'Intelligence', shortcut: '9' },
  { id: 'communications', label: 'Communications', group: 'Operations', shortcut: '' },
  { id: 'smarthome', label: 'Smart Home & Cameras', group: 'Operations', shortcut: '' },
  { id: 'automation', label: 'Automation', group: 'Operations', shortcut: '' },
  { id: 'containers', label: 'Container Management', group: 'Operations', shortcut: '' },
  { id: 'voice', label: 'Voice Studio', group: 'System', shortcut: '' },
  { id: 'models', label: 'AI Models', group: 'System', shortcut: '' },
  { id: 'connections', label: 'Connections', group: 'System', shortcut: '' },
  { id: 'audit', label: 'Audit', group: 'System', shortcut: '' },
  { id: 'repair', label: 'Repair', group: 'System', shortcut: '' },
  { id: 'settings', label: 'Settings', group: 'System', shortcut: '' },
];

export interface ChatMessage {
  id: string;
  role: 'user' | 'jarvis' | 'tuki' | 'system';
  text: string;
  ts: string;
}

interface CommandCenterState {
  workspace: WorkspaceId;
  setWorkspace: (w: WorkspaceId) => void;
  sidebarWidth: number;
  setSidebarWidth: (px: number) => void;
  fullscreen: boolean;
  toggleFullscreen: () => void;
  reducedMotion: boolean;
  toggleReducedMotion: () => void;
  floatingMode: boolean;
  toggleFloatingMode: () => void;
  paletteOpen: boolean;
  setPaletteOpen: (v: boolean) => void;
  coreStatus: string;
  activeAssistant: 'jarvis' | 'tuki';
  setCoreStatus: (s: string, assistant?: 'jarvis' | 'tuki') => void;
  appState: Record<string, any>;
  setAppState: (s: Record<string, any>) => void;
  vitals: Record<string, any> | null;
  setVitals: (v: Record<string, any>) => void;
  messages: ChatMessage[];
  addMessage: (role: ChatMessage['role'], text: string) => void;
  pendingApproval: { id: string; summary: string } | null;
  setPendingApproval: (a: { id: string; summary: string } | null) => void;
}

export const useCCStore = create<CommandCenterState>((set) => ({
  workspace: 'console',
  setWorkspace: (workspace) => set({ workspace }),
  sidebarWidth: 236,
  setSidebarWidth: (px) => set({ sidebarWidth: Math.max(180, Math.min(340, px)) }),
  fullscreen: false,
  toggleFullscreen: () => set((s) => ({ fullscreen: !s.fullscreen })),
  reducedMotion: false,
  toggleReducedMotion: () => set((s) => ({ reducedMotion: !s.reducedMotion })),
  floatingMode: false,
  toggleFloatingMode: () => set((s) => ({ floatingMode: !s.floatingMode })),
  paletteOpen: false,
  setPaletteOpen: (paletteOpen) => set({ paletteOpen }),
  coreStatus: 'idle',
  activeAssistant: 'jarvis',
  setCoreStatus: (coreStatus, assistant) =>
    set((s) => ({ coreStatus, activeAssistant: assistant || s.activeAssistant })),
  appState: {},
  setAppState: (appState) => set({ appState }),
  vitals: null,
  setVitals: (vitals) => set({ vitals }),
  messages: [
    {
      id: 'welcome',
      role: 'jarvis',
      text: 'Jarvis & TUKI Command Center ready. Check each workspace for available actions and integration status.',
      ts: new Date().toLocaleTimeString(),
    },
  ],
  addMessage: (role, text) =>
    set((s) => ({
      messages: [
        ...s.messages.slice(-80),
        { id: `${Date.now()}-${Math.random()}`, role, text, ts: new Date().toLocaleTimeString() },
      ],
    })),
  pendingApproval: null,
  setPendingApproval: (pendingApproval) => set({ pendingApproval }),
}));
