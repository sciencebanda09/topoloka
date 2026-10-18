// Minimal typings for @mkkellogg/gaussian-splats-3d (ships no .d.ts).
declare module '@mkkellogg/gaussian-splats-3d' {
  export class Viewer {
    constructor(options?: Record<string, unknown>);
    addSplatScene(path: string, options?: Record<string, unknown>): Promise<void>;
    update(): void;
    render(): void;
    start(): void;
    dispose(): void;
  }
  export class DropInViewer {
    constructor(options?: Record<string, unknown>);
    addSplatScenes(options: Record<string, unknown>[]): Promise<void>;
  }
  export const LogLevel: { None: number; Error: number; Warn: number; Info: number; Debug: number };
  export const SceneRevealMode: { Default: number; Gradual: number; Instant: number };
  export const RenderMode: { Always: number; OnChange: number; Never: number };
  export const WebXRMode: { None: number; VR: number; AR: number };
}
